"""LLM API 调用封装 | LLM API client
支持 OpenAI 兼容接口，含指数退避、token 计数、进度反馈、全量日志。
OpenAI-compatible with exponential backoff, token counting, progress feedback, full logging."""

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

import config as _cfg


@dataclass
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int
    seq: int = 0


# 模块级日志状态
_log_path: str | None = None
_log_seq: int = 0
_meta: dict | None = None
_log_callback: object = None


def set_log_path(path: str) -> None:
    global _log_path, _log_seq
    _log_path = path
    _log_seq = 0


def set_log_callback(cb) -> None:
    global _log_callback
    _log_callback = cb


def set_meta(meta: dict) -> None:
    """设置当前调用上下文（task_id, node_id, iteration 等），call() 内部消费后清空。"""
    global _meta
    _meta = meta


def _write_record(record: dict) -> int:
    global _log_seq
    _log_seq += 1
    record["seq"] = _log_seq
    record["ts"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    if _log_path:
        record["log_file"] = _log_path
        try:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return _log_seq


def call(
    prompt: str,
    *,
    model: str = "",
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    api_key: str = "",
    base_url: str = "",
    max_retries: int | None = None,
    messages: list[dict] | None = None,
    log_callback=None,
) -> LLMResponse:
    """调用 LLM API，含指数退避重试。每次调用自动写全量日志到 _log_path。"""

    if not api_key:
        raise RuntimeError(
            "未配置 API Key | API key not configured.\n"
            "运行 niuma 进入菜单 → 配置模型 | Run niuma → Configure model"
        )
    if not model:
        raise RuntimeError(
            "未配置模型 | No model configured.\n"
            "运行 niuma 进入菜单 → 配置模型 | Run niuma → Configure model"
        )

    url = f"{base_url.rstrip('/')}/chat/completions"

    if max_retries is None:
        limits = _cfg.get_retry_limits()
        max_retries = limits["llm_api_max_retries"]

    if messages is None:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

    body_data: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens > 0:
        body_data["max_tokens"] = max_tokens
    body = json.dumps(body_data).encode("utf-8")

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
            with urllib.request.urlopen(req, timeout=300) as resp:
                last_status = resp.status
                data = json.loads(resp.read().decode("utf-8"))

            choice = data["choices"][0]
            content = choice["message"]["content"]
            usage = data.get("usage", {})
            elapsed = time.time() - t_start
            in_tok = usage.get("prompt_tokens", 0)
            out_tok = usage.get("completion_tokens", 0)
            _log(f"\r  [OK] {model} ({elapsed:.1f}s, {in_tok}+{out_tok} tokens)")

            # 写全量调用日志
            global _meta
            ctx = _meta or {}
            _meta = None
            seq = _write_record({
                "type": "llm_call",
                "role": ctx.get("role", "unknown"),
                "task_id": ctx.get("task_id", ""),
                "node_id": ctx.get("node_id", ""),
                "iteration": ctx.get("iteration", 0),
                "model": model,
                "duration_s": round(elapsed, 1),
                "attempt": attempt + 1,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "system_prompt": system,
                "user_prompt": prompt,
                "raw_response": content,
                "error": None,
            })

            result = LLMResponse(
                content=content.strip(),
                input_tokens=in_tok,
                output_tokens=out_tok,
                seq=seq,
            )
            log_data = {
                "model": model,
                "prompt_chars": len(prompt),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "duration_s": round(elapsed, 1),
                "content_preview": content.strip()[:200],
            }
            if log_callback:
                log_callback(log_data)
            if _log_callback:
                _log_callback(log_data)
            return result
        except urllib.error.HTTPError as e:
            last_error = e
            last_status = e.code
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            _log(f"\r  [ERR] HTTP {e.code} ({model}), 尝试 {attempt + 1}/{max_retries + 1}")
            if e.code in (401, 403):
                raise RuntimeError(
                    f"API 认证失败 ({e.code}) | Authentication failed.\n"
                    f"请检查模型配置 | Check model config: ./niuma → 配置模型\n"
                    f"{body_text}"
                ) from e
        except (urllib.error.URLError, OSError) as e:
            last_error = e
            _log(f"\r  [ERR] 网络错误 ({model}), 尝试 {attempt + 1}/{max_retries + 1} | Network error")

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
    import config as _cfg
    c = _cfg.get_model_config("strong")
    return call(
        prompt,
        model=kwargs.pop("model", None) or c["model"],
        api_key=kwargs.pop("api_key", None) or c["api_key"],
        base_url=kwargs.pop("base_url", None) or c["base_url"],
        max_tokens=kwargs.pop("max_tokens", 0),
        temperature=kwargs.pop("temperature", 0.1),
        system=kwargs.pop("system", ""),
        **kwargs,
    )


def call_weak(prompt: str, **kwargs) -> LLMResponse:
    """调用弱模型（代码生成器）| Call weak model (code generator)."""
    import config as _cfg
    c = _cfg.get_model_config("weak")
    return call(
        prompt,
        model=kwargs.pop("model", None) or c["model"],
        api_key=kwargs.pop("api_key", None) or c["api_key"],
        base_url=kwargs.pop("base_url", None) or c["base_url"],
        max_tokens=kwargs.pop("max_tokens", 0),
        temperature=kwargs.pop("temperature", 0.3),
        system=kwargs.pop("system", ""),
        **kwargs,
    )


def call_strong_messages(messages: list[dict], max_tokens: int = 0) -> "LLMResponse":
    """直接传 messages 调用强模型（用于对话式需求澄清等需要完整消息历史的场景）。"""
    cfg = _cfg.get_model_config("strong")
    return call(
        prompt="",
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        max_tokens=max_tokens,
        messages=messages,
    )


def write_process_record(record: dict) -> None:
    """写入处理层日志（代码提取、沙箱结果等）。"""
    _write_record({
        "type": "worker_process",
        **record,
    })


def _log(msg: str, end: str = "\n", flush: bool = True) -> None:
    """输出到 stderr，不污染 stdout 管道。"""
    print(msg, end=end, file=sys.stderr, flush=flush)
