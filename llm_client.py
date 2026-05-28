"""LLM 客户端 — 支持 OpenAI 兼容 API 和 Anthropic 兼容 API"""

import logging
from typing import Optional

logger = logging.getLogger("wechat_bot")

PROVIDER_PRESETS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_type": "openai",
    },
    "deepseek-anthropic": {
        "base_url": "https://api.deepseek.com/anthropic",
        "model": "deepseek-v4-flash",
        "api_type": "anthropic",
    },
    "openai_compatible": {
        "base_url": "http://localhost:1234/v1",
        "model": "",
        "api_type": "openai",
    },
}


class LLMClient:
    """连接 LLM API 生成回复（自动选择 OpenAI / Anthropic 后端）"""

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
        self.api_type = preset["api_type"]

        self._client = None

    # ── 客户端创建 ──────────────────────────────────────

    def _create_client(self):
        if self.api_type == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(
                base_url=self.base_url,
                api_key=self.api_key,
            )
        else:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )

    @property
    def client(self):
        if self._client is None:
            self._create_client()
        return self._client

    # ── 消息构建 ────────────────────────────────────────

    def _build_openai_messages(self, user_message: str,
                                history: Optional[list[dict]] = None) -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _build_anthropic_messages(self, user_message: str,
                                   history: Optional[list[dict]] = None) -> list[dict]:
        """构建 Anthropic 格式消息（system 单独提取，消息需交替 user/assistant）"""
        messages = []
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    # ── 聊天 ────────────────────────────────────────────

    def chat(self, user_message: str,
             history: Optional[list[dict]] = None,
             temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> str:
        """发送聊天请求，返回回复文本"""
        try:
            if self.api_type == "anthropic":
                return self._chat_anthropic(user_message, history, temperature, max_tokens)
            else:
                return self._chat_openai(user_message, history, temperature, max_tokens)
        except Exception as e:
            logger.error("LLM 请求失败 [%s]: %s", self.provider, e)
            return ""

    def _chat_openai(self, user_message, history, temperature, max_tokens) -> str:
        messages = self._build_openai_messages(user_message, history)
        resp = self.client.chat.completions.create(
            model=self.model or "local-model",
            messages=messages,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
        )
        return resp.choices[0].message.content.strip()

    def _chat_anthropic(self, user_message, history, temperature, max_tokens) -> str:
        messages = self._build_anthropic_messages(user_message, history)
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
        )
        if self.system_prompt:
            kwargs["system"] = self.system_prompt
        resp = self.client.messages.create(**kwargs)
        return resp.content[0].text.strip()

    # ── 流式 ────────────────────────────────────────────

    def chat_stream(self, user_message: str,
                    history: Optional[list[dict]] = None):
        """流式生成回复（逐块返回）"""
        try:
            if self.api_type == "anthropic":
                yield from self._stream_anthropic(user_message, history)
            else:
                yield from self._stream_openai(user_message, history)
        except Exception as e:
            logger.error("LLM 流式请求失败 [%s]: %s", self.provider, e)
            yield ""

    def _stream_openai(self, user_message, history):
        messages = self._build_openai_messages(user_message, history)
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

    def _stream_anthropic(self, user_message, history):
        messages = self._build_anthropic_messages(user_message, history)
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )
        if self.system_prompt:
            kwargs["system"] = self.system_prompt
        with self.client.messages.create(**kwargs) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    yield event.delta.text or ""

    # ── 测试连接 ────────────────────────────────────────

    def test_connection(self) -> bool:
        """测试 API 是否可用"""
        try:
            if self.api_type == "anthropic":
                self.client.messages.create(
                    model=self.model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                )
                logger.info("Anthropic API 连接测试通过")
                return True
            else:
                models = self.client.models.list()
                logger.info("OpenAI API 可用, 模型: %s", [m.id for m in models][:5])
                return True
        except Exception as e:
            logger.warning("API 连接测试失败 [%s]: %s", self.provider, e)
            return False

    def list_models(self) -> list[str]:
        """获取可用模型列表"""
        try:
            if self.api_type == "anthropic":
                # Anthropic API 无 list_models，返回预设模型名
                model = PROVIDER_PRESETS.get(self.provider, {}).get("model", "")
                return [model] if model else []
            models = self.client.models.list()
            return [m.id for m in models]
        except Exception:
            return []

    def update_config(self, **kwargs):
        """动态更新配置"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self._client = None
