"""微信自动对话引擎 — 主循环 + 反检测 + LLM 集成"""

import logging
import random
import threading
import time
from typing import Optional

from llm_client import LLMClient
from anti_detect import AntiDetect
from conversation import ConversationManager
from config_manager import Config

logger = logging.getLogger("wechat_bot")


class BotEngine:
    """自动对话引擎核心"""

    def __init__(self, config: Config):
        self.cfg = config
        self.driver = None  # WeChatDriver or WeChatDriverPyAutoGUI
        self.llm: Optional[LLMClient] = None
        self.anti_detect = AntiDetect(config.anti_detect)
        self.conversation = ConversationManager(
            max_history=config.conversation.get("max_history", 6),
            max_tokens=config.conversation.get("max_tokens", 2048),
        )
        self._running = threading.Event()
        self._processed_msg_ids: set[str] = set()
        self._retry_count: dict[str, int] = {}  # msg_id → retry attempts
        self._last_replied: dict[str, str] = {}  # contact → last replied content (防 Vision 非确定性问题)

    # ── 初始化 ──────────────────────────────────────────

    def _create_driver(self):
        """根据配置创建微信驱动实例"""
        driver_type = self.cfg.bot.get("driver", "pyautogui")

        if driver_type == "hybrid":
            from wechat_driver_hybrid import WeChatDriverHybrid
            contacts = self.cfg.bot.get("contacts", [])
            mention_trigger = self.cfg.bot.get("mention_trigger", "豆咪")
            fuzzy_threshold = self.cfg.bot.get("fuzzy_match_threshold", 0.5)
            return WeChatDriverHybrid(contacts,
                                      mention_trigger=mention_trigger,
                                      fuzzy_match_threshold=fuzzy_threshold)
        elif driver_type == "wxauto":
            from wechat_driver import WeChatDriver
            return WeChatDriver()
        else:
            from wechat_driver_pyautogui import WeChatDriverPyAutoGUI
            contacts = self.cfg.bot.get("contacts", [])
            reading_method = self.cfg.bot.get("reading_method", "clipboard")
            mention_trigger = self.cfg.bot.get("mention_trigger", "豆咪")
            fuzzy_threshold = self.cfg.bot.get("fuzzy_match_threshold", 0.5)
            return WeChatDriverPyAutoGUI(contacts, reading_method=reading_method, llm=self.llm,
                                         mention_trigger=mention_trigger,
                                         fuzzy_match_threshold=fuzzy_threshold)

    def initialize(self) -> bool:
        """初始化驱动和 LLM"""
        # 先初始化 LLM（非致命），再创建驱动，确保驱动能拿到 llm 引用
        if self.cfg.llm.get("enabled", False):
            self._init_llm()

        try:
            self.driver = self._create_driver()
            logger.info(
                "微信驱动初始化成功(%s)，昵称: %s",
                self.cfg.bot.get("driver", "pyautogui"),
                self.driver.nickname,
            )
        except Exception as e:
            logger.error("微信驱动初始化失败: %s", e)
            return False

        # 启动后台活动模拟
        if self.anti_detect.enabled:
            self.anti_detect.start_activity_simulation(self.driver.raw_wx)

        return True

    def _init_llm(self) -> None:
        """初始化 LLM 客户端（非致命，失败不影响 bot 启动）"""
        try:
            self.llm = LLMClient(
                provider=self.cfg.llm.get("provider", "openai_compatible"),
                base_url=self.cfg.llm.get("base_url", ""),
                api_key=self.cfg.llm.get("api_key", ""),
                model=self.cfg.llm.get("model", ""),
                temperature=self.cfg.llm.get("temperature", 0.7),
                max_tokens=self.cfg.llm.get("max_tokens", 1024),
                system_prompt=self.cfg.llm.get("system_prompt", ""),
            )
            ok = self.llm.test_connection()
            if ok:
                models = self.llm.list_models()
                if models:
                    logger.info("LLM 可用, 模型: %s", models[:3])
                else:
                    logger.warning("LLM 连接成功但未获取到模型列表")
            else:
                logger.error("LLM 连接失败，Bot 将继续运行（不使用 LLM 回复）")
                self.llm = None
        except Exception as e:
            logger.error("LLM 初始化异常: %s", e)
            self.llm = None

    # ── 联系人检查 ──────────────────────────────────────

    def _is_whitelisted(self, contact: str) -> bool:
        mode = self.cfg.bot.get("mode", "whitelist")
        contacts = self.cfg.bot.get("contacts", [])
        blacklist = self.cfg.bot.get("blacklist", [])

        # 黑名单优先
        if contact in blacklist:
            return False

        if mode == "all":
            return True
        elif mode == "whitelist":
            return contact in contacts
        return False

    # ── 静默时段 ────────────────────────────────────────

    def _in_quiet_hours(self) -> bool:
        start = self.cfg.bot.get("quiet_hours_start", "")
        end = self.cfg.bot.get("quiet_hours_end", "")
        return self.anti_detect.is_quiet_hours(start, end)

    # ── LLM 回复 ────────────────────────────────────────

    def _generate_reply(self, contact: str, message: str) -> str:
        """调用 LLM 生成回复（LLM 不可用时返回 echo 回复）"""
        if not self.llm:
            return f"收到你的消息: {message[:50]}"

        history = None
        if self.cfg.conversation.get("enabled", False):
            history = self.conversation.format_history(contact)

        # Qwen 3.5-9B 对特定 prompt 格式敏感：请用中文回复 前缀可稳定工作
        reply = self.llm.chat(f"请用中文回复：{message}", history=history)

        if self.cfg.conversation.get("enabled", False):
            self.conversation.add_message(contact, "user", message)
            if reply:
                self.conversation.add_message(contact, "assistant", reply)

        return reply

    # ── 空闲模拟 ────────────────────────────────────────

    def _maybe_idle(self) -> None:
        """模拟离开状态：随机空闲一段时间（可被停止中断）"""
        idle_min = self.cfg.anti_detect.get("idle_minutes_min", 0)
        idle_max = self.cfg.anti_detect.get("idle_minutes_max", 0)
        if idle_max > 0 and idle_min > 0:
            idle_time = random.uniform(idle_min, idle_max) * 60
            logger.info("进入随机空闲 %.1f 秒...", idle_time)
            for _ in range(int(idle_time)):
                if not self._running.is_set():
                    break
                time.sleep(1)

    # ── 消息去重 ────────────────────────────────────────

    MAX_RETRIES = 3

    def _is_duplicate(self, msg_id: str) -> bool:
        """只检查不添加，防止 LLM 失败后消息被吞"""
        return msg_id in self._processed_msg_ids

    def _mark_processed(self, msg_id: str) -> None:
        """LLM 回复成功后才标记为已处理"""
        self._processed_msg_ids.add(msg_id)
        self._retry_count.pop(msg_id, None)
        if len(self._processed_msg_ids) > 10000:
            self._processed_msg_ids.clear()

    def _can_retry(self, msg_id: str) -> bool:
        """检查是否超过最大重试次数"""
        count = self._retry_count.get(msg_id, 0)
        if count >= self.MAX_RETRIES:
            # 超过上限，标记为已处理避免无限重试
            logger.warning("消息重试已达上限，放弃 [%s]", msg_id[:40])
            self._processed_msg_ids.add(msg_id)
            self._retry_count.pop(msg_id, None)
            return False
        self._retry_count[msg_id] = count + 1
        return True

    # ── 主循环 ──────────────────────────────────────────

    def _running_check(self) -> bool:
        """检查是否还在运行，用于提前退出"""
        return self._running.is_set()

    def _process_contact(self, contact: str) -> None:
        """处理单个联系人的消息（含运行状态检查，可快速停止）"""
        if not self._is_whitelisted(contact) or not self._running_check():
            return

        try:
            # 获取消息
            msgs = self.driver.get_new_messages(contact)

            # 检测到桌面内容 → 跳过本轮，不停止（可能是临时切换到其他页面）
            if msgs == "DESKTOP":
                logger.warning("读取到桌面内容而非微信，跳过本轮")
                return

            if not msgs or not self._running_check():
                return

            # 窗口消失则停止所有任务
            if not self.driver.is_window_visible():
                logger.warning("处理消息时微信窗口消失，停止所有任务")
                self.stop()
                return

            # 只处理最近一条非自己发送的消息
            friend_msgs = [m for m in msgs if m["type"] != "self"]
            if not friend_msgs or not self._running_check():
                return

            latest = friend_msgs[-1]
            content = latest["content"].strip()
            msg_id = latest.get("id", content[:40])

            if not content or not self._running_check():
                return

            # 只检查不添加，防止 LLM 失败后消息被吞
            if self._is_duplicate(msg_id):
                logger.debug("跳过已处理消息 [%s]", contact)
                return

            # 防止 LLM 非确定性：同样内容不发第二次
            last_replied = self._last_replied.get(contact)
            if last_replied is not None and content == last_replied:
                logger.debug("跳过已回复的重复内容 [%s]", contact)
                return

            # 重试次数检查（超过上限则标记已处理并放弃）
            if not self._can_retry(msg_id):
                self.driver.acknowledge_message(contact)  # 更新快照，避免重复读取
                return

            logger.info("收到消息 [%s]: %s [重试 #%d]", contact, content[:60],
                         self._retry_count.get(msg_id, 1))

            # 随机跳过
            if self.anti_detect.should_skip() or not self._running_check():
                logger.info("随机跳过回复 [%s]", contact)
                return

            # 模拟阅读时间（越长消息读越久）
            self.anti_detect.wait_read(len(content))
            if not self._running_check():
                return

            # 生成回复
            reply = self._generate_reply(contact, content)
            if not reply or not self._running_check():
                logger.warning("LLM 未生成回复 [%s] (将在下次轮询重试 %d/%d)",
                               contact, self._retry_count.get(msg_id, 1), self.MAX_RETRIES)
                return

            # 添加前缀
            prefix = self.cfg.bot.get("reply_prefix", "")
            if prefix:
                reply = f"{prefix}{reply}"

            # 模拟思考时间
            self.anti_detect.wait_reply(len(content))
            if not self._running_check():
                return

            # 发送（分段发送模拟真人逐条输入）
            chunks = self.anti_detect.chunk_messages(reply)
            for i, chunk in enumerate(chunks):
                if not self._running_check():
                    return
                self.driver.send_message(contact, chunk, skip_switch=True)
                if i < len(chunks) - 1:
                    time.sleep(self.anti_detect.message_interval)

            # 回复成功 → 标记已处理（防止重复）
            self._mark_processed(msg_id)
            self.driver.acknowledge_message(contact, reply)

            # 记录已回复内容，防止重复
            self._last_replied[contact] = content

            logger.info("回复 [%s]: %s", contact, reply[:80])

        except Exception as e:
            logger.error("处理联系人 [%s] 消息异常: %s", contact, e)

    def run(self) -> None:
        """启动主循环"""
        if not self.initialize():
            logger.error("初始化失败，退出")
            return

        self._running.set()
        poll_interval = self.cfg.bot.get("poll_interval_seconds", 3)
        logger.info("Bot 已启动，轮询间隔 %ds", poll_interval)
        logger.info("当前模式: %s", self.cfg.bot.get("mode", "whitelist"))

        try:
            while self._running.is_set():
                # 检查是否在静默时段（每2秒检查一次_running）
                if self._in_quiet_hours():
                    for _ in range(30):
                        if not self._running.is_set():
                            break
                        time.sleep(2)
                    continue

                # 随机空闲模拟
                self._maybe_idle()
                if not self._running.is_set():
                    break

                try:
                    # 检查微信窗口是否在桌面可见
                    if not self.driver.is_window_visible():
                        logger.info("微信窗口不可见，跳过本轮（继续监测）")
                        time.sleep(10)
                        continue

                    # 获取所有会话（PyAutoGUI 模式返回白名单列表）
                    sessions = self.driver.get_sessions()
                    active_contacts = [
                        s["name"] for s in sessions
                        if s["name"] != self.driver.nickname
                    ]

                    # fallback: 驱动未返回会话时，使用配置白名单
                    if not active_contacts:
                        active_contacts = self.cfg.bot.get("contacts", [])

                    for contact in active_contacts:
                        if not self._running.is_set():
                            break
                        self._process_contact(contact)

                except Exception as e:
                    logger.error("主循环异常: %s", e)
                    time.sleep(5)

                # 轮询间隔（每0.5秒检查一次_running）
                if self._running.is_set():
                    for _ in range(poll_interval * 2):
                        if not self._running.is_set():
                            break
                        time.sleep(0.5)

        except KeyboardInterrupt:
            logger.info("用户中断")
        finally:
            self.shutdown()

    def stop(self) -> None:
        """停止主循环"""
        self._running.clear()

    def shutdown(self) -> None:
        """清理资源（幂等，可多次调用）"""
        self._running.clear()
        if self.driver:
            self.anti_detect.stop_activity_simulation()
        logger.info("Bot 已停止")
