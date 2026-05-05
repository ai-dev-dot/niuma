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
    },
    "weak": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "",
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

    return {
        "api_key": model.get("api_key", "") or os.getenv("LLM_API_KEY", ""),
        "base_url": model.get("base_url", "https://api.openai.com/v1") or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        "model": model.get("model", "") or os.getenv(f"{which.upper()}_MODEL", ""),
    }


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
