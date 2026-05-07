"""配置管理 | Config Manager
读写 ~/.niuma/config.json，替代手动编辑 .env 文件。
Reads/writes ~/.niuma/config.json instead of manual .env editing."""

import json
import os
from pathlib import Path

_CONFIG_DIR = Path.home() / ".niuma"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "strong": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "",
        "reasoning": "",  # "max" | "high" | "" (关闭，仅 DeepSeek 支持)
    },
    "weak": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "",
        "reasoning": "",
    },
    "retry_limits": {
        "clarify_rounds": 20,
        "compiler_schema_validation": 5,
        "worker_code_extraction": 5,
        "reviewer_rounds": 5,
        "llm_api_max_retries": 3,
        "early_abort_fail_ratio": 0.6,
        "worker_max_iterations": 5,
    },
}

# 供应商预设 —— 用户只需选供应商+填API Key，base_url和模型列表自动补全
# 数据来源: https://models.dev (每日自动更新)
PROVIDERS = {
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_hint": "https://platform.openai.com/api-keys",
        "strong_models": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "o4-mini"],
        "weak_models": ["gpt-5.4-mini", "gpt-5.4-nano", "gpt-4.1-mini"],
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "key_hint": "https://platform.deepseek.com/api_keys",
        "strong_models": ["deepseek-v4-pro", "deepseek-reasoner", "deepseek-chat"],
        "weak_models": ["deepseek-chat", "deepseek-v4-flash"],
    },
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "key_hint": "https://console.groq.com/keys",
        "strong_models": ["llama-3.3-70b-versatile", "deepseek-r1-distill-llama-70b"],
        "weak_models": ["llama-3.1-8b-instant", "qwen-qwq-32b", "llama-3.2-3b-preview"],
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_hint": "https://openrouter.ai/keys",
        "strong_models": [
            "anthropic/claude-sonnet-4.6",
            "openai/gpt-5.4-mini",
            "google/gemini-2.5-pro",
            "deepseek/deepseek-chat",
        ],
        "weak_models": [
            "google/gemini-2.5-flash-lite",
            "deepseek/deepseek-chat",
            "qwen/qwen3.5-flash",
        ],
    },
    "siliconflow": {
        "name": "硅基流动 (SiliconFlow)",
        "base_url": "https://api.siliconflow.cn/v1",
        "key_hint": "https://cloud.siliconflow.cn/account/ak",
        "strong_models": [
            "deepseek-ai/DeepSeek-R1",
            "Pro/deepseek-ai/DeepSeek-V3.2",
            "Qwen/Qwen3-235B-A22B-Thinking-2507",
        ],
        "weak_models": [
            "Qwen/Qwen3-8B",
            "deepseek-ai/DeepSeek-V3",
            "Qwen/Qwen3-30B-A3B-Instruct-2507",
        ],
    },
    "zhipu": {
        "name": "智谱AI (ZhipuAI)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "key_hint": "https://open.bigmodel.cn/usercenter/apikeys",
        "strong_models": ["glm-5.1", "glm-4.7", "glm-4.6"],
        "weak_models": ["glm-4.7-flash", "glm-4.7-flashx", "glm-4.5-flash"],
    },
    "dashscope": {
        "name": "阿里百炼 (DashScope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_hint": "https://bailian.console.aliyun.com/",
        "strong_models": ["qwen-max", "qwen-plus", "qwen3-235b-a22b"],
        "weak_models": ["qwen-turbo", "qwen-plus", "qwen3-8b"],
    },
    "minimax": {
        "name": "MiniMax (海螺AI)",
        "base_url": "https://api.minimaxi.com/v1",
        "key_hint": "https://platform.minimaxi.com/user-center/basic-information/interface-key",
        "strong_models": ["MiniMax-M2.7", "MiniMax-M2.5", "MiniMax-M2.1"],
        "weak_models": ["MiniMax-M2.7", "MiniMax-M2.5"],
    },
    "kimi": {
        "name": "月之暗面 (Moonshot/Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "key_hint": "https://platform.moonshot.cn/console/api-keys",
        "strong_models": ["moonshot-v1-128k", "kimi-k2-thinking"],
        "weak_models": ["moonshot-v1-8k", "moonshot-v1-32k"],
    },
}


def _ensure_dir() -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_config() -> dict:
    """读取完整配置，文件不存在则返回默认值。"""
    if not _CONFIG_FILE.exists():
        return DEFAULT_CONFIG
    try:
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # 合并默认值，确保所有键都存在
        for key in ("strong", "weak"):
            if key not in data:
                data[key] = DEFAULT_CONFIG[key]
            for field in ("api_key", "base_url", "model"):
                if field not in data[key]:
                    data[key][field] = DEFAULT_CONFIG[key][field]
        return data
    except (json.JSONDecodeError, OSError):
        return DEFAULT_CONFIG


def save_config(config: dict) -> None:
    """保存完整配置到磁盘。"""
    _ensure_dir()
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_model_config(which: str) -> dict:
    """获取强/弱模型配置。which = 'strong' | 'weak'
    优先 config.json，fallback 到环境变量。"""
    config = get_config()
    model = config.get(which, DEFAULT_CONFIG[which])

    m = model.get("model", "") or os.getenv(f"{which.upper()}_MODEL", "")
    # reasoning: 显式设置优先，否则 DeepSeek 默认 max
    reasoning = model.get("reasoning", "")
    if not reasoning and "deepseek" in m.lower():
        reasoning = "max"

    return {
        "api_key": model.get("api_key", "") or os.getenv("LLM_API_KEY", ""),
        "base_url": model.get("base_url", "https://api.openai.com/v1") or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        "model": m,
        "reasoning": reasoning,
    }


def get_retry_limits() -> dict:
    """获取所有重试/轮次限制配置，缺失字段使用默认值。"""
    config = get_config()
    defaults = DEFAULT_CONFIG["retry_limits"]
    limits = config.get("retry_limits", {})
    return {key: limits.get(key, defaults[key]) for key in defaults}


def set_model_config(which: str, api_key: str = "", base_url: str = "", model: str = "") -> None:
    """更新强/弱模型配置的指定字段。空值表示不修改。"""
    config = get_config()
    if api_key:
        config[which]["api_key"] = api_key
    if base_url:
        config[which]["base_url"] = base_url
    if model:
        config[which]["model"] = model
    save_config(config)


def config_exists() -> bool:
    return _CONFIG_FILE.exists()


def get_config_path() -> str:
    return str(_CONFIG_FILE)


def list_providers() -> list[dict]:
    """返回供应商列表，每个包含 key, name, base_url, key_hint。"""
    return [
        {
            "key": key,
            "name": p["name"],
            "base_url": p["base_url"],
            "key_hint": p["key_hint"],
        }
        for key, p in PROVIDERS.items()
    ]


def get_provider(key: str) -> dict | None:
    """获取单个供应商完整信息。"""
    return PROVIDERS.get(key)


def test_connection(which: str) -> tuple[bool, str]:
    """测试模型 API 连接。返回 (ok, message)。which = 'strong' | 'weak'"""
    import json as _json
    import urllib.request as _req
    import urllib.error as _err

    c = get_model_config(which)
    if not c["api_key"]:
        return False, "未配置 API Key | API Key not set"
    if not c["model"]:
        return False, "未配置模型名称 | Model name not set"

    url = f"{c['base_url'].rstrip('/')}/chat/completions"
    body = _json.dumps({
        "model": c["model"],
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5,
    }).encode("utf-8")

    try:
        req = _req.Request(
            url, data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {c['api_key']}",
            },
        )
        with _req.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        return True, f"✓ {c['model']} — {content[:40]}"
    except _err.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return False, f"HTTP {e.code}: {body_text}"
    except Exception as e:
        return False, f"连接失败 | Connection failed: {e}"


# ---- 旧 .env 自动迁移 ----

def _migrate_from_env() -> bool:
    """检测项目根目录是否有 .env 文件，有则导入到 config.json。返回 True 表示执行了迁移。"""
    from pathlib import Path as _Path
    env_file = _Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return False

    # 读取 .env
    env_vars: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val and "your-api-key" not in val and "sk-your" not in val:
            env_vars[key] = val

    if not env_vars:
        return False

    config = get_config()
    if "LLM_API_KEY" in env_vars:
        config["strong"]["api_key"] = env_vars["LLM_API_KEY"]
        config["weak"]["api_key"] = env_vars["LLM_API_KEY"]
    if "LLM_BASE_URL" in env_vars:
        config["strong"]["base_url"] = env_vars["LLM_BASE_URL"]
        config["weak"]["base_url"] = env_vars["LLM_BASE_URL"]
    if "STRONG_MODEL" in env_vars:
        config["strong"]["model"] = env_vars["STRONG_MODEL"]
    if "WEAK_MODEL" in env_vars:
        config["weak"]["model"] = env_vars["WEAK_MODEL"]
    save_config(config)
    return True
