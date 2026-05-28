"""LLM 客户端 — 支持 OpenAI 兼容 API (DeepSeek, LM Studio, Groq 等)"""

import logging
from typing import Optional

logger = logging.getLogger("wechat_bot")

PROVIDER_PRESETS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "openai_compatible": {
        "base_url": "http://localhost:1234/v1",
        "model": "",
    },
}


class LLMClient:
    """连接 LLM API 生成回复"""

    def __init__(self, provider: str = "openai_compatible",
                 api_key: str = "",
                 model: str = "",
                 base_url: str = "",
                 temperature: float = 0.7,
                 max_tokens: int = 1024,
                 system_prompt: str = ""):
        self.provider = provider
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt

        preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["openai_compatible"])
        self.base_url = (base_url or preset["base_url"]).rstrip("/")
        self.api_key = api_key
        self.model = model or preset["model"]

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

    def chat(self, user_message: str,
             history: Optional[list[dict]] = None,
             temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> str:
        """发送聊天请求，返回回复文本"""
        messages = self._build_messages(user_message, history)

        try:
            resp = self.client.chat.completions.create(
                model=self.model or "local-model",
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

        try:
            stream = self.client.chat.completions.create(
                model=self.model or "local-model",
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
        """测试 API 是否可用"""
        try:
            # 先试 list_models（DeepSeek / LM Studio 均支持）
            models = self.client.models.list()
            logger.info("API 可用, 模型列表: %s", [m.id for m in models][:5])
            return True
        except Exception:
            # 兜底：发一条空消息测试
            try:
                resp = self.client.chat.completions.create(
                    model=self.model or "local-model",
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                )
                logger.info("API 连接测试通过")
                return True
            except Exception as e:
                logger.warning("API 连接测试失败: %s", e)
                return False

    def list_models(self) -> list[str]:
        """获取可用模型列表"""
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
