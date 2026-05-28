import json
import os
import sys
from pathlib import Path
from typing import Any, Optional, Union


def _default_config_path() -> Path:
    """返回配置路径（PyInstaller exe 优先加载同目录 config.json）"""
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        local = exe_dir / "config.json"
        if local.exists():
            return local
    return Path(__file__).parent / "config.json"


class Config:
    def __init__(self, path: Optional[Union[str, Path]] = None):
        self.path = Path(path) if path else _default_config_path()
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self._data = self._defaults()
            self.save()
        return self._data

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def _defaults(self) -> dict[str, Any]:
        return {
            "llm": {
                "enabled": False,
                "provider": "openai_compatible",
                "base_url": "",
                "api_key": "",
                "model": "",
                "temperature": 0.7,
                "max_tokens": 1024,
                "system_prompt": "你是一个友好的微信助手。请用中文自然回复，保持对话流畅。回答应简洁得体，不要提及你是AI助手。",
            },
            "bot": {
                "enabled": True,
                "driver": "hybrid",
                "mode": "whitelist",
                "contacts": [],
                "blacklist": [],
                "reply_prefix": "",
                "quiet_hours_start": "",
                "quiet_hours_end": "",
                "poll_interval_seconds": 3,
            },
            "anti_detect": {
                "enabled": True,
                "read_delay_min": 1.0,
                "read_delay_max": 3.0,
                "reply_delay_min": 2.0,
                "reply_delay_max": 8.0,
                "typing_speed_min": 0.08,
                "typing_speed_max": 0.2,
                "max_chars_per_message": 300,
                "message_interval_min": 1.0,
                "message_interval_max": 2.5,
                "random_skip_rate": 0.0,
                "simulate_activity_interval": 0,
                "idle_minutes_min": 0,
                "idle_minutes_max": 0,
            },
            "conversation": {
                "max_history": 6,
                "max_tokens": 2048,
                "enabled": False,
            },
        }

    @property
    def llm(self) -> dict[str, Any]:
        return self._data.get("llm", {})

    @property
    def bot(self) -> dict[str, Any]:
        return self._data.get("bot", {})

    @property
    def anti_detect(self) -> dict[str, Any]:
        return self._data.get("anti_detect", {})

    @property
    def conversation(self) -> dict[str, Any]:
        return self._data.get("conversation", {})

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def show_config(self) -> str:
        return json.dumps(self._data, ensure_ascii=False, indent=2)
