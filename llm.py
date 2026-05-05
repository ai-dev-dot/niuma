"""LLM API 调用封装 —— 支持 OpenAI 兼容接口，含指数退避和 token 计数。"""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int


def call(
    prompt: str,
    *,
    model: str = "",
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    api_key: str = "",
    base_url: str = "",
    max_retries: int = 3,
) -> LLMResponse:
    """调用 LLM API，含指数退避重试。"""
    api_key = api_key or os.getenv("LLM_API_KEY", "")
    base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    model = model or os.getenv("LLM_MODEL", "gpt-4o")

    url = f"{base_url.rstrip('/')}/chat/completions"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            choice = data["choices"][0]
            content = choice["message"]["content"]
            usage = data.get("usage", {})
            return LLMResponse(
                content=content.strip(),
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            )
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            last_error = e
            if attempt < max_retries:
                delay = 2 ** attempt
                time.sleep(delay)

    raise RuntimeError(f"LLM API 调用失败（{max_retries} 次重试后）: {last_error}")


def call_strong(prompt: str, **kwargs) -> LLMResponse:
    """调用强模型（编译器/审核器）。"""
    return call(
        prompt,
        model=kwargs.pop("model", None) or os.getenv("STRONG_MODEL", ""),
        max_tokens=kwargs.pop("max_tokens", 4096),
        temperature=kwargs.pop("temperature", 0.1),
        system=kwargs.pop("system", ""),
        **kwargs,
    )


def call_weak(prompt: str, **kwargs) -> LLMResponse:
    """调用弱模型（代码生成器）。"""
    return call(
        prompt,
        model=kwargs.pop("model", None) or os.getenv("WEAK_MODEL", ""),
        max_tokens=kwargs.pop("max_tokens", 2048),
        temperature=kwargs.pop("temperature", 0.3),
        system=kwargs.pop("system", ""),
        **kwargs,
    )
