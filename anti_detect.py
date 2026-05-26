"""防微信官方检测机制 — 模拟真人操作行为"""

import random
import time
import logging
from datetime import datetime
from threading import Thread, Event

logger = logging.getLogger("wechat_bot")


class AntiDetect:
    """模仿人类行为的反检测控制器"""

    def __init__(self, config: dict):
        self.cfg = config
        self._activity_thread: Thread | None = None
        self._stop_event = Event()

    # ── 配置快捷属性 ──────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self.cfg.get("enabled", True)

    @property
    def read_delay(self) -> float:
        """模拟阅读消息的延迟（发现消息到点击查看）"""
        return random.uniform(
            self.cfg.get("read_delay_min", 1.0),
            self.cfg.get("read_delay_max", 3.0),
        )

    @property
    def reply_delay(self) -> float:
        """模拟思考回复的延迟"""
        return random.uniform(
            self.cfg.get("reply_delay_min", 2.0),
            self.cfg.get("reply_delay_max", 8.0),
        )

    @property
    def typing_speed(self) -> float:
        """逐字输入时每字间隔（秒）"""
        return random.uniform(
            self.cfg.get("typing_speed_min", 0.08),
            self.cfg.get("typing_speed_max", 0.2),
        )

    @property
    def max_chars_per_message(self) -> int:
        return self.cfg.get("max_chars_per_message", 300)

    @property
    def message_interval(self) -> float:
        """分段发送时段间延迟"""
        return random.uniform(
            self.cfg.get("message_interval_min", 1.0),
            self.cfg.get("message_interval_max", 2.5),
        )

    @property
    def random_skip_rate(self) -> float:
        """随机跳过回复的概率 0~1"""
        return self.cfg.get("random_skip_rate", 0.0)

    @property
    def simulate_activity_interval(self) -> int:
        """模拟活动间隔（秒），0 表示不启用"""
        return self.cfg.get("simulate_activity_interval", 0)

    # ── 延迟策略 ──────────────────────────────────────────

    def wait_read(self, content_length: int = 0) -> None:
        """模拟阅读消息的时间

        根据消息长度按比例增加阅读时间
        """
        if not self.enabled:
            return
        base = self.read_delay
        extra = min(content_length / 100 * 0.5, 5.0)
        delay = base + extra
        time.sleep(delay)

    def wait_reply(self, incoming_length: int = 0) -> None:
        """模拟回复前的思考时间

        根据消息长度调整思考时间，避免秒回
        """
        if not self.enabled:
            return
        base = self.reply_delay
        extra = min(incoming_length / 50 * 0.3, 4.0)
        delay = base + extra
        time.sleep(delay)

    def wait_typing(self, text: str) -> float:
        """计算逐字输入所需的总耗时

        Returns:
            预计输入完成所需秒数
        """
        if not self.enabled:
            return 0.1
        return len(text) * self.typing_speed

    # ── 分段发送 ──────────────────────────────────────────

    def chunk_messages(self, text: str) -> list[str]:
        """将长文本分段，模拟多条消息逐条发送"""
        if not self.enabled or len(text) <= self.max_chars_per_message:
            return [text]

        chunks = []
        for i in range(0, len(text), self.max_chars_per_message):
            chunks.append(text[i:i + self.max_chars_per_message])
        return chunks

    # ── 随机跳过 ──────────────────────────────────────────

    def should_skip(self) -> bool:
        """是否随机跳过本次回复"""
        if not self.enabled or self.random_skip_rate <= 0:
            return False
        return random.random() < self.random_skip_rate

    # ── 空闲时段检查 ──────────────────────────────────────

    def is_quiet_hours(self, start: str, end: str) -> bool:
        """检查当前是否在免打扰时段内"""
        if not start or not end:
            return False
        now = datetime.now().strftime("%H:%M")
        if start <= end:
            return start <= now <= end
        else:
            return now >= start or now <= end

    # ── 后台活动模拟 ──────────────────────────────────────

    def start_activity_simulation(self, wx_instance) -> None:
        """启动后台活动模拟（独立线程）"""
        interval = self.simulate_activity_interval
        if not self.enabled or interval <= 0:
            return

        self._stop_event.clear()
        self._activity_thread = Thread(
            target=self._activity_loop,
            args=(wx_instance, interval),
            daemon=True,
        )
        self._activity_thread.start()
        logger.info("后台活动模拟已启动，间隔 %d 秒", interval)

    def stop_activity_simulation(self) -> None:
        self._stop_event.set()
        if self._activity_thread and self._activity_thread.is_alive():
            self._activity_thread.join(timeout=5)
        self._activity_thread = None

    def _activity_loop(self, wx, interval: int) -> None:
        """模拟人类随机操作

        - 滚动联系人列表
        - 切换到聊天页
        - 随机停顿
        """
        import random
        actions = ["scroll", "switch_chat", "switch_contact"]

        while not self._stop_event.is_set():
            self._stop_event.wait(interval + random.randint(-10, 10))

            if self._stop_event.is_set():
                break

            try:
                action = random.choice(actions)
                if action == "scroll" and hasattr(wx, "SessionBox"):
                    wx.SwitchToChat()
                    time.sleep(0.5)
                elif action == "switch_chat":
                    wx.SwitchToChat()
                    time.sleep(0.3)
                elif action == "switch_contact":
                    wx.SwitchToContact()
                    time.sleep(0.5)
                    wx.SwitchToChat()

                logger.debug("活动模拟: %s", action)
            except Exception as e:
                logger.debug("活动模拟异常: %s", e)
