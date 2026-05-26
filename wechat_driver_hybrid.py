"""UIA + PyAutoGUI 混合微信驱动

架构：
  - 读取消息 → uia_sidecar.exe read（完全后台，不抢焦点）
  - 发送消息 → uia_sidecar.exe send（完全后台，不抢焦点）
  - 历史消息 → uia_sidecar.exe history N（完全后台，不抢焦点）
  - 窗口管理 → win32gui（纯查询，不操作前台）
  - 切换聊天 → （暂用手动切换，不自动操作）
"""

import difflib
import logging
import os
import re
import subprocess
import time
from typing import Optional

import win32gui
import win32api
import win32con

logger = logging.getLogger("wechat_bot")

SIDECAR_PATH = os.path.join(os.path.dirname(__file__), "uia_sidecar.exe")

_DESKTOP_CONTENT_MARKERS = [
    ".lnk", "快捷方式", "此电脑", "回收站", "控制面板",
    "我的电脑", "This PC", "Recycle Bin",
]


class WeChatDriverHybrid:
    """混合驱动：UIA 读取/发送 + 窗口状态查询"""

    WECHAT_CLASS = "Qt51514QWindowIcon"

    def __init__(self, contacts: Optional[list[str]] = None,
                 mention_trigger: str = "豆咪",
                 fuzzy_match_threshold: float = 0.5):
        """
        Args:
            contacts: 联系人白名单（hybrid 模式下仅监听当前聊天的消息，
                      白名单用于 _is_whitelisted 过滤）
            mention_trigger: @提及触发词
            fuzzy_match_threshold: 模糊匹配阈值
        """
        self._contacts = contacts or []
        self._mention_trigger = mention_trigger
        self._fuzzy_threshold = fuzzy_match_threshold
        self._nickname = "WeChat"
        self._hwnd: Optional[int] = None

        # UIA 侧载路径检查
        if not os.path.isfile(SIDECAR_PATH):
            raise FileNotFoundError(
                f"侧载程序未找到: {SIDECAR_PATH}\n"
                f"请先编译: csc.exe uia_sidecar.cs /reference:..."
            )

        self._find_window()
        logger.info("混合驱动初始化完成, HWND: %s, 联系人: %s",
                     self._hwnd, self._contacts)

    # ── 窗口查找 ──────────────────────────────────────────

    def _find_window(self) -> bool:
        def enum_cb(hwnd, results):
            try:
                if self.WECHAT_CLASS in win32gui.GetClassName(hwnd):
                    results.append(hwnd)
            except Exception:
                pass
            return True

        results = []
        win32gui.EnumWindows(enum_cb, results)
        if not results:
            logger.error("未找到微信窗口 (class: %s)", self.WECHAT_CLASS)
            return False

        self._hwnd = results[0]
        return True

    # ── UIA 侧载通信 ──────────────────────────────────────

    def _run_sidecar(self, *args, timeout: int = 60) -> str:
        """运行侧载程序并返回 stdout（失败时记录 stderr）"""
        try:
            r = subprocess.run(
                [SIDECAR_PATH] + list(args),
                capture_output=True, timeout=timeout
            )
            stderr_text = r.stderr.decode("utf-8", errors="replace").strip()
            if stderr_text:
                logger.error("侧载 stderr [%s]: %s", args[0], stderr_text)
            if r.returncode != 0:
                logger.error("侧载退出码 %d [%s]", r.returncode, args[0])
            return r.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            logger.error("侧载超时: %s", args)
            return ""
        except FileNotFoundError:
            logger.error("侧载程序不存在: %s", SIDECAR_PATH)
            return ""
        except Exception as e:
            logger.error("侧载异常: %s", e)
            return ""

    def _parse_output(self, output: str) -> list[str]:
        """解析侧载输出为消息列表"""
        lines = output.strip().split("\n")
        if not lines or not lines[0].startswith("COUNT:"):
            return []
        try:
            count = int(lines[0].replace("COUNT:", ""))
        except ValueError:
            return []
        messages = []
        for line in lines[1:1 + count]:
            # 格式: idx\tcontent
            if "\t" in line:
                _, content = line.split("\t", 1)
                messages.append(content.strip())
        return messages

    # ══════════════════════════════════════════════════════
    #  基础属性（与 WeChatDriverPyAutoGUI 兼容）
    # ══════════════════════════════════════════════════════

    @property
    def nickname(self) -> str:
        return self._nickname

    @property
    def raw_wx(self):
        return _RawWxStub()

    def is_online(self) -> bool:
        return self._hwnd is not None and win32gui.IsWindow(self._hwnd)

    def is_window_visible(self) -> bool:
        """检查微信窗口是否可用"""
        if not self._hwnd or not win32gui.IsWindow(self._hwnd):
            return False
        try:
            l, t, r, b = win32gui.GetWindowRect(self._hwnd)
            w, h = r - l, b - t
            if w <= 0 or h <= 0:
                return False
            screen_w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
            screen_h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
            if l >= screen_w or t >= screen_h or r <= 0 or b <= 0:
                return False
            return True
        except Exception:
            return False

    # ══════════════════════════════════════════════════════
    #  会话列表（返回白名单）
    # ══════════════════════════════════════════════════════

    def get_sessions(self) -> list[dict]:
        return [{"name": c} for c in self._contacts if c]

    # ══════════════════════════════════════════════════════
    #  切换聊天（手动模式，返回 False）
    # ══════════════════════════════════════════════════════

    def switch_chat(self, who: str) -> bool:
        """混合模式下由用户手动切换聊天"""
        return False

    # ══════════════════════════════════════════════════════
    #  读取消息（UIA 后台读取）
    # ══════════════════════════════════════════════════════

    def get_new_messages(self, contact: str) -> list[dict]:
        """读取当前聊天的消息，仅返回包含 @提及 的新消息"""
        output = self._run_sidecar("read", timeout=15)
        messages = self._parse_output(output)

        if not messages:
            return []

        # 检测桌面内容
        full_text = "\n".join(messages)
        if any(marker in full_text for marker in _DESKTOP_CONTENT_MARKERS):
            logger.error("检测到桌面内容而非微信聊天，停止所有任务")
            return "DESKTOP"

        # 提取包含 @提及 的消息
        mention_lines = self._find_fuzzy_mention_lines(full_text)
        if not mention_lines:
            return []

        # 对比上次已确认的快照，只返回新增的 @提及（快照在 acknowledge_message 时更新）
        last_text = getattr(self, f"_last_chat_text_{contact}", "")
        if last_text:
            # 快照不为空 → 只取新增的
            last_mentions = set(self._find_fuzzy_mention_lines(last_text))
            new_lines = [l for l in mention_lines if l not in last_mentions]
            if not new_lines:
                return []
            clean_msg = new_lines[-1]
        else:
            # 首次读取，直接返回最新一条
            clean_msg = mention_lines[-1]
        clean_msg = re.sub(
            rf'@{re.escape(self._mention_trigger)}[\w一-鿿]*',
            f'@{self._mention_trigger}',
            clean_msg
        )

        return [{"sender": contact, "content": clean_msg,
                 "type": "friend", "raw": clean_msg,
                 "id": clean_msg[:40]}]

    def _find_fuzzy_mention_lines(self, text: str) -> list[str]:
        """提取包含 @触发词（含模糊匹配）的行"""
        lines = text.split("\n")
        result = []
        for line in lines:
            line = line.strip()
            if "@" not in line:
                continue
            if f"@{self._mention_trigger}" in line:
                result.append(line)
                continue
            for at_idx in [i for i, c in enumerate(line) if c == "@"]:
                after_at = line[at_idx + 1:]
                match = re.match(r'([\w一-鿿＀-￯]+)', after_at)
                if match:
                    word = match.group(1)
                    ratio = difflib.SequenceMatcher(None, word, self._mention_trigger).ratio()
                    if ratio >= self._fuzzy_threshold:
                        result.append(line)
                        break
        return result

    def get_history(self, count: int = 20) -> list[str]:
        """获取当前聊天的历史消息（滚动读取）"""
        output = self._run_sidecar("history", str(count), timeout=120)
        return self._parse_output(output)

    # ══════════════════════════════════════════════════════
    #  发送消息（UIA 后台发送）
    # ══════════════════════════════════════════════════════

    def send_message(self, who: str, text: str, skip_switch: bool = False) -> bool:
        """发送消息到当前聊天（UIA 后台，无需前台焦点）"""
        # 转义特殊字符（防止 shell 注入）
        safe_text = text.replace('"', '\\"')
        result = self._run_sidecar("send", safe_text, timeout=15)
        return "SUCCESS" in result

    def send_message_slowly(self, who, text,
                            char_delay=(0.08, 0.2),
                            chunk_size=300,
                            chunk_delay=(1.0, 2.5)):
        """分段发送长消息"""
        if len(text) <= chunk_size:
            return self.send_message(who, text, skip_switch=True)

        import random
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        ok = True
        for i, chunk in enumerate(chunks):
            if not self.send_message(who, chunk, skip_switch=True):
                ok = False
                break
            if i < len(chunks) - 1:
                time.sleep(random.uniform(*chunk_delay))
        return ok

    # ══════════════════════════════════════════════════════
    #  消息确认
    # ══════════════════════════════════════════════════════

    def acknowledge_message(self, contact: str) -> None:
        """发送回复后更新聊天快照，下次轮询不再返回同一条 @提及"""
        # 重新读取当前聊天内容，更新 last_text 快照
        output = self._run_sidecar("read", timeout=15)
        messages = self._parse_output(output)
        if messages:
            full_text = "\n".join(messages)
            setattr(self, f"_last_chat_text_{contact}", full_text)
            self._last_snap: dict[str, str] = {}  # 清理缓存
        logger.debug("已确认消息 [%s], 快照已更新", contact)

    # ══════════════════════════════════════════════════════
    #  消息去重
    # ══════════════════════════════════════════════════════

    @staticmethod
    def is_new_message(contact: str, msg_id: str) -> bool:
        return True


class _RawWxStub:
    @staticmethod
    def SwitchToChat():
        pass

    @staticmethod
    def SwitchToContact():
        pass
