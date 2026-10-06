"""Minimal client for OpenAI-compatible chat APIs.

Ollama, OpenRouter, OpenAI, vLLM and most other providers speak this format,
so switching models is a matter of changing base_url and model.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

DEFAULT_BASE_URL = "http://localhost:11434/v1"  # local Ollama
DEFAULT_MODEL = "qwen2.5-coder:7b"


class LLMError(Exception):
    """Raised when the model API can't be reached or returns an error."""


@dataclass
class LLMConfig:
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_key: Optional[str] = None
    temperature: float = 0.7  # >0 so repeated trials explore different paths
    timeout: int = 300

    @classmethod
    def from_env(cls, model: Optional[str] = None, base_url: Optional[str] = None) -> LLMConfig:
        """CLI flags win; otherwise INVIG_MODEL / INVIG_BASE_URL / INVIG_API_KEY."""
        return cls(
            model=model or os.environ.get("INVIG_MODEL", DEFAULT_MODEL),
            base_url=base_url or os.environ.get("INVIG_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.environ.get("INVIG_API_KEY"),
        )


def chat(config: LLMConfig, messages: list[dict], tools: list[dict]) -> tuple[dict, dict]:
    """Send one chat completion request. Returns (assistant message, token usage)."""
    body = {
        "model": config.model,
        "messages": messages,
        "tools": tools,
        "temperature": config.temperature,
    }
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    request = urllib.request.Request(
        config.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code} from {config.base_url}: {e.read().decode(errors='replace')[:500]}")
    except urllib.error.URLError as e:
        raise LLMError(f"cannot reach {config.base_url}: {e.reason}")
    except TimeoutError:
        raise LLMError(f"model did not respond within {config.timeout}s")

    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError):
        raise LLMError(f"unexpected response: {json.dumps(data)[:500]}")
    return message, data.get("usage") or {}
