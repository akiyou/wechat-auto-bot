"""LM Studio / OpenAI 兼容 LLM 客户端"""

import logging
from typing import Optional

logger = logging.getLogger("wechat_bot")


class LLMClient:
    """连接 LM Studio (或任何 OpenAI 兼容 API) 生成回复"""

    def __init__(self, base_url: str = "http://localhost:1234/v1",
                 api_key: str = "not-needed",
                 model: str = "",
                 temperature: float = 0.7,
                 max_tokens: int = 1024,
                 system_prompt: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )
        return self._client

    def _build_messages(self, user_message: str,
                        history: Optional[list[dict]] = None) -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def chat_with_image(self, image_bytes: bytes,
                        text_prompt: str = "请提取这张图片中的所有文字内容，只返回文字本身，不要任何解释。") -> str:
        """发送图片 + 文字到视觉模型，返回识别结果"""
        import base64
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": text_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        })
        # 使用配置的模型名（空则让服务端决定默认模型）
        model = self.model if self.model else None
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=self.max_tokens if self.max_tokens else 4096,
            )
            content = resp.choices[0].message.content
            return content.strip() if content else ""
        except Exception as e:
            logger.error("LLM 视觉识别失败: %s", e)
            return ""

    def chat(self, user_message: str,
             history: Optional[list[dict]] = None,
             temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> str:
        """发送聊天请求，返回回复文本"""
        messages = self._build_messages(user_message, history)
        model = self.model if self.model else None

        try:
            resp = self.client.chat.completions.create(
                model=model or "local-model",
                messages=messages,
                temperature=temperature or self.temperature,
                max_tokens=max_tokens or self.max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error("LLM 请求失败: %s", e)
            return ""

    def chat_stream(self, user_message: str,
                    history: Optional[list[dict]] = None):
        """流式生成回复（逐块返回）"""
        messages = self._build_messages(user_message, history)
        model = self.model if self.model else None

        try:
            stream = self.client.chat.completions.create(
                model=model or "local-model",
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield delta
        except Exception as e:
            logger.error("LLM 流式请求失败: %s", e)
            yield ""

    def test_connection(self) -> bool:
        """测试 LM Studio API 是否可用"""
        try:
            models = self.client.models.list()
            logger.info("LM Studio 可用, 模型列表: %s",
                        [m.id for m in models])
            return True
        except Exception as e:
            logger.warning("LM Studio 连接测试失败: %s", e)
            return False

    def list_models(self) -> list[str]:
        """获取 LM Studio 可用模型列表"""
        try:
            models = self.client.models.list()
            return [m.id for m in models]
        except Exception:
            return []

    def update_config(self, **kwargs):
        """动态更新配置"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self._client = None  # 强制重新创建
