"""wxauto4 微信驱动封装层"""

import time
import logging
from typing import Optional

logger = logging.getLogger("wechat_bot")


class WeChatDriver:
    """封装 wxauto4 的 WeChat 类，提供消息收发接口"""

    def __init__(self):
        # 初始化当前线程的 COM 环境（wxauto4 内部依赖 Windows COM/UIA）
        import pythoncom
        pythoncom.CoInitialize()

        from wxauto4 import WeChat

        self._wx = WeChat(ads=False)
        self._last_message_id: dict[str, str] = {}  # contact -> last msg id tracking
        logger.info("WeChatDriver 初始化完成，已登录: %s", self._wx.nickname)

    # ── 基础属性 ──────────────────────────────────────────

    @property
    def nickname(self) -> str:
        return getattr(self._wx, "nickname", "unknown")

    @property
    def raw_wx(self):
        """暴露底层 wxauto4 WeChat 实例（用于活动模拟等）"""
        return self._wx

    def is_online(self) -> bool:
        try:
            return self._wx.IsOnline()
        except Exception:
            return False

    # ── 会话管理 ──────────────────────────────────────────

    def get_sessions(self) -> list[dict]:
        """获取当前所有会话列表"""
        sessions = self._wx.GetSession()
        result = []
        for s in sessions:
            try:
                name = getattr(s, "name", None) or str(s)
                result.append({
                    "name": name,
                    "element": s,
                })
            except Exception:
                continue
        return result

    # ── 消息收发 ──────────────────────────────────────────

    def switch_chat(self, who: str) -> None:
        """切换到指定联系人的聊天窗口"""
        self._wx.ChatWith(who, exact=True)

    def get_all_messages(self) -> list:
        """获取当前聊天窗口的所有消息"""
        return self._wx.GetAllMessage()

    def get_new_messages(self, contact: str) -> list[dict]:
        """获取指定联系人的新消息

        返回消息 dict 列表: {sender, content, type, raw}
        """
        self.switch_chat(contact)
        time.sleep(0.3)
        msgs = self.get_all_messages()
        parsed = []
        for m in msgs:
            msg_type = getattr(m, "type", "")
            if msg_type == "self":
                continue
            sender = getattr(m, "sender", contact)
            content = getattr(m, "content", "")
            msg_id = getattr(m, "id", None) or content[:40]
            parsed.append({
                "sender": sender,
                "content": content,
                "type": msg_type,
                "raw": m,
                "id": msg_id,
            })
        return parsed

    def send_message(self, who: str, text: str) -> bool:
        """发送文本消息到指定联系人"""
        try:
            self._wx.SendMsg(text, who, clear=True)
            return True
        except Exception as e:
            logger.error("发送消息失败 [%s]: %s", who, e)
            return False

    def send_message_slowly(self, who: str, text: str,
                            char_delay: tuple[float, float] = (0.08, 0.2),
                            chunk_size: int = 300,
                            chunk_delay: tuple[float, float] = (1.0, 2.5)) -> bool:
        """模拟真人逐字输入发送长消息

        Args:
            who: 联系人
            text: 消息内容
            char_delay: 每字延迟范围 (min, max)
            chunk_size: 每段最大字数
            chunk_delay: 段间延迟范围 (min, max)
        """
        import random
        if len(text) <= chunk_size:
            return self.send_message(who, text)

        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        success = True
        for i, chunk in enumerate(chunks):
            if not self.send_message(who, chunk):
                success = False
                break
            if i < len(chunks) - 1:
                delay = random.uniform(*chunk_delay)
                time.sleep(delay)
        return success

    # ── 消息去重 ──────────────────────────────────────────

    def is_new_message(self, contact: str, msg_id: str) -> bool:
        last_id = self._last_message_id.get(contact, "")
        if msg_id == last_id:
            return False
        self._last_message_id[contact] = msg_id
        return True
