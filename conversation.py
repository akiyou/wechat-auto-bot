"""对话上下文管理"""

import logging
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger("wechat_bot")


class ConversationManager:
    """管理每个联系人的对话历史，控制上下文长度"""

    def __init__(self, max_history: int = 6, max_tokens: int = 2048):
        self.max_history = max_history
        self.max_tokens = max_tokens
        # contact_name -> list[{"role": "user"|"assistant", "content": str}]
        self._histories: dict[str, list[dict]] = OrderedDict()

    def add_message(self, contact: str, role: str, content: str) -> None:
        if contact not in self._histories:
            self._histories[contact] = []
        self._histories[contact].append({"role": role, "content": content})
        self._trim(contact)

    def get_history(self, contact: str) -> list[dict]:
        return self._histories.get(contact, [])

    def clear_history(self, contact: Optional[str] = None) -> None:
        if contact:
            self._histories.pop(contact, None)
        else:
            self._histories.clear()

    def _trim(self, contact: str) -> None:
        """按 max_history 和 max_tokens 裁剪历史"""
        history = self._histories.get(contact, [])
        if not history:
            return

        # 按条数裁剪
        if len(history) > self.max_history * 2:  # user + assistant = 1 turn
            history = history[-(self.max_history * 2):]

        # 按 token 估算裁剪（粗略按中文字符数）
        total_chars = sum(len(m["content"]) for m in history)
        if total_chars > self.max_tokens * 2:  # 假设中文字符 ≈ 2 token
            # 从最旧的删起，保留最近的
            while total_chars > self.max_tokens * 2 and len(history) > 2:
                removed = history.pop(0)
                total_chars -= len(removed["content"])

        self._histories[contact] = history

    def format_history(self, contact: str) -> list[dict]:
        """返回 OpenAI 格式的 history（不含 system）"""
        return self.get_history(contact)[:]

    def __len__(self) -> int:
        return sum(len(h) for h in self._histories.values())

    def count_contacts(self) -> int:
        return len(self._histories)
