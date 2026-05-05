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


def delete_project(name: str) -> None:
    """删除项目：从 DB 中移除记录。不删除本地文件（安全考虑）。"""
    db = _get_db()
    db.execute("DELETE FROM projects WHERE name = ?", (name,))
    db.commit()
    db.close()


# ═══════════════════════════════════════════════════════════════
# Git 操作 —— 强/弱模型通过 git 分支通信
# ═══════════════════════════════════════════════════════════════

GIT_AUTHOR_COMPILER = ("Strong Model", "niuma@compiler")
GIT_AUTHOR_WORKER = ("Weak Model", "niuma@worker")
GIT_AUTHOR_REVIEWER = ("Strong Model", "niuma@compiler")
BRANCH_PREFIX = "niuma"


def git_run(repo_path: str | Path, args: list[str], check: bool = True) -> str:
    """在指定仓库中运行 git 命令，返回 stdout。失败时抛出 RuntimeError。"""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} 失败 | failed:\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def create_task_branch(repo_path: str | Path, task_id: str) -> str:
    """创建任务分支 niuma/<task-id> 并切换过去。返回分支名。"""
    branch = f"{BRANCH_PREFIX}/{task_id}"
    # 从当前 HEAD 直接切出新分支（不强制切 main，避免工作区冲突）
    git_run(repo_path, ["checkout", "-b", branch])
    return branch


def get_current_branch(repo_path: str | Path) -> str:
    return git_run(repo_path, ["branch", "--show-current"])


def branch_exists(repo_path: str | Path, branch: str) -> bool:
    try:
        git_run(repo_path, ["rev-parse", "--verify", branch])
        return True
    except RuntimeError:
        return False


def switch_branch(repo_path: str | Path, branch: str) -> None:
    git_run(repo_path, ["checkout", branch])


def commit_file(
    repo_path: str | Path,
    filepath: str,
    content: str,
    author: tuple[str, str],
    message: str,
) -> None:
    """写文件 + git add + git commit --author。filepath 相对于 repo_path。"""
    full_path = Path(repo_path) / filepath
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")

    git_run(repo_path, ["add", filepath])
    git_run(repo_path, [
        "commit",
        "-m", message,
        f"--author={author[0]} <{author[1]}>",
    ])


def commit_existing(
    repo_path: str | Path,
    filepath: str,
    author: tuple[str, str],
    message: str,
) -> None:
    """对已存在的文件执行 git add + git commit。"""
    git_run(repo_path, ["add", filepath])
    git_run(repo_path, [
        "commit",
        "-m", message,
        f"--author={author[0]} <{author[1]}>",
    ])


def read_file_from_branch(repo_path: str | Path, branch: str, filepath: str) -> str:
    """从指定分支读取文件内容。"""
    return git_run(repo_path, ["show", f"{branch}:{filepath}"])


def merge_to_main(repo_path: str | Path, branch: str) -> bool:
    """将分支合并到 main。返回 True 表示成功。不自动 push。"""
    try:
        current = get_current_branch(repo_path)
        git_run(repo_path, ["checkout", "main"])
        git_run(repo_path, ["merge", "--no-ff", branch, "-m", f"Merge {branch}: task completed"])
        git_run(repo_path, ["branch", "-d", branch])
        return True
    except RuntimeError:
        # 合并冲突时恢复原分支
        try:
            git_run(repo_path, ["merge", "--abort"], check=False)
            git_run(repo_path, ["checkout", current], check=False)
        except Exception:
            pass
        return False


def list_task_branches(repo_path: str | Path) -> list[str]:
    """列出所有 niuma/ 开头的分支。"""
    output = git_run(repo_path, ["branch", "--list", f"{BRANCH_PREFIX}/*"], check=False)
    if not output:
        return []
    return [b.strip().lstrip("* ") for b in output.splitlines() if b.strip()]
