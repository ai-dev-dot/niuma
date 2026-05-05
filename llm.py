"""LLM API 调用封装 | LLM API client
支持 OpenAI 兼容接口，含指数退避、token 计数、进度反馈。
OpenAI-compatible with exponential backoff, token counting, and progress feedback."""

import json
import os
import sys
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
    model = model or os.getenv("LLM_MODEL", "")
    if not model:
        raise RuntimeError(
            "未配置模型 | No model configured. "
            "请在 .env 中设置 STRONG_MODEL / WEAK_MODEL | Set STRONG_MODEL/WEAK_MODEL in .env"
        )

    if not api_key:
        raise RuntimeError(
            "LLM_API_KEY 未设置 | LLM_API_KEY not set. "
            "请复制 .env.example 为 .env 并填入你的 API key | "
            "Copy .env.example to .env and add your API key."
        )

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

    _log(f"  → {model} ({len(prompt)} chars) ...", end="", flush=True)
    t_start = time.time()

    last_error: Exception | None = None
    last_status: int = 0
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
                last_status = resp.status
                data = json.loads(resp.read().decode("utf-8"))

            choice = data["choices"][0]
            content = choice["message"]["content"]
            usage = data.get("usage", {})
            elapsed = time.time() - t_start
            in_tok = usage.get("prompt_tokens", 0)
            out_tok = usage.get("completion_tokens", 0)
            _log(f"\r  ✓ {model} ({elapsed:.1f}s, {in_tok}+{out_tok} tokens)")

            return LLMResponse(
                content=content.strip(),
                input_tokens=in_tok,
                output_tokens=out_tok,
            )
        except urllib.error.HTTPError as e:
            last_error = e
            last_status = e.code
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            _log(f"\r  ✗ HTTP {e.code} ({model}), 尝试 {attempt + 1}/{max_retries + 1}")
            if e.code in (401, 403):
                raise RuntimeError(
                    f"API 认证失败 ({e.code}) | Authentication failed.\n"
                    f"请检查 .env 中的 LLM_API_KEY | Check LLM_API_KEY in .env\n"
                    f"{body_text}"
                ) from e
        except (urllib.error.URLError, OSError) as e:
            last_error = e
            _log(f"\r  ✗ 网络错误 ({model}), 尝试 {attempt + 1}/{max_retries + 1} | Network error")

        if attempt < max_retries:
            delay = 2 ** attempt
            time.sleep(delay)

    elapsed = time.time() - t_start
    raise RuntimeError(
        f"LLM API 调用失败 | API call failed: {model} "
        f"({max_retries} 次重试后 | after {max_retries} retries, "
        f"最后状态 | last status: HTTP {last_status}, "
        f"耗时 | duration: {elapsed:.1f}s)\n"
        f"错误 | error: {last_error}"
    )


def call_strong(prompt: str, **kwargs) -> LLMResponse:
    """调用强模型（编译器/审核器）| Call strong model (compiler/reviewer)."""
    return call(
        prompt,
        model=kwargs.pop("model", None) or os.getenv("STRONG_MODEL", ""),
        max_tokens=kwargs.pop("max_tokens", 4096),
        temperature=kwargs.pop("temperature", 0.1),
        system=kwargs.pop("system", ""),
        **kwargs,
    )


def call_weak(prompt: str, **kwargs) -> LLMResponse:
    """调用弱模型（代码生成器）| Call weak model (code generator)."""
    return call(
        prompt,
        model=kwargs.pop("model", None) or os.getenv("WEAK_MODEL", ""),
        max_tokens=kwargs.pop("max_tokens", 2048),
        temperature=kwargs.pop("temperature", 0.3),
        system=kwargs.pop("system", ""),
        **kwargs,
    )


def _log(msg: str, end: str = "\n", flush: bool = True) -> None:
    """输出到 stderr，不污染 stdout 管道。"""
    print(msg, end=end, file=sys.stderr, flush=flush)
