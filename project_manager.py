"""项目管理 | Project Manager
管理 git-based 项目：创建（clone）、列表、查询。
Stores project metadata in ~/.niuma/niuma.db."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

_PROJECTS_DIR = Path.home() / ".niuma" / "projects"
_DB_PATH = Path.home() / ".niuma" / "niuma.db"


def _ensure_dirs() -> None:
    _PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _get_db() -> sqlite3.Connection:
    _ensure_dirs()
    db = sqlite3.connect(str(_DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            name TEXT PRIMARY KEY,
            git_url TEXT NOT NULL,
            local_path TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    db.commit()
    return db


def list_projects() -> list[dict]:
    """返回所有项目的 [{name, git_url, local_path, created_at}, ...]。"""
    db = _get_db()
    rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_project(name: str) -> dict | None:
    """获取单个项目信息，不存在返回 None。"""
    db = _get_db()
    row = db.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    db.close()
    return dict(row) if row else None


def create_project(name: str, git_url: str, proxy: str = "") -> dict:
    """创建新项目：git clone → 写入 DB。返回项目 dict。失败时抛出 RuntimeError。"""
    _ensure_dirs()

    # 检查名称是否重复
    existing = get_project(name)
    if existing:
        raise RuntimeError(
            f"项目 '{name}' 已存在 | Project '{name}' already exists.\n"
            f"路径 | path: {existing['local_path']}"
        )

    # 检查 git URL 是否已被其他项目使用
    db = _get_db()
    dup = db.execute("SELECT name FROM projects WHERE git_url = ?", (git_url,)).fetchone()
    db.close()
    if dup:
        raise RuntimeError(
            f"该 git 地址已被项目 '{dup['name']}' 使用 | "
            f"Git URL already used by project '{dup['name']}'"
        )

    local_path = _PROJECTS_DIR / name

    # git clone
    print(f"  Cloning {git_url} ...")
    clone_cmd = ["git", "clone", git_url, str(local_path)]
    if proxy:
        clone_cmd = ["git", "clone", "-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}", git_url, str(local_path)]

    result = subprocess.run(clone_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # 清理失败的克隆目录
        if local_path.exists():
            import shutil
            shutil.rmtree(local_path, ignore_errors=True)
        raise RuntimeError(
            f"Git clone 失败 | failed:\n{result.stderr.strip()}\n"
            f"如果是网络问题，尝试设置代理后重试 | If network issue, retry with proxy"
        )

    # 写入 DB
    db = _get_db()
    db.execute(
        "INSERT INTO projects (name, git_url, local_path) VALUES (?, ?, ?)",
        (name, git_url, str(local_path)),
    )
    db.commit()
    db.close()

    print(f"  [OK] 项目已创建 | project created: {local_path}")
    return {"name": name, "git_url": git_url, "local_path": str(local_path)}


def get_project_path(name: str) -> Path | None:
    """返回项目本地路径，不存在返回 None。"""
    proj = get_project(name)
    if not proj:
        return None
    p = Path(proj["local_path"])
    return p if p.exists() else None
