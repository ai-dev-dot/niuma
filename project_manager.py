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

    result = subprocess.run(clone_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
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
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} 失败 | failed:\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def create_task_branch(repo_path: str | Path, task_id: str) -> str:
    """创建任务分支 niuma/<task-id>，始终从 main 分叉。自动清理旧任务分支。"""
    git_run(repo_path, ["checkout", "main"])
    # 删除所有旧 niuma 分支（一个任务 = 一个分支）
    for old in list_task_branches(repo_path):
        git_run(repo_path, ["branch", "-D", old], check=False)
    branch = f"{BRANCH_PREFIX}/{task_id}"
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
    if full_path.exists() and full_path.read_text(encoding="utf-8") == content:
        return
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


def get_niuma_log(repo_path: str | Path, max_count: int = 20) -> list[str]:
    """返回 niuma 任务分支的 git log 摘要。"""
    output = git_run(repo_path, [
        "log", "--oneline", "--all", "--graph",
        f"--max-count={max_count}",
    ], check=False)
    if not output:
        return []
    return output.splitlines()


# ═══════════════════════════════════════════════════════════════
# Git 凭据检测 — 帮助用户配置 HTTPS/SSH 认证
# ═══════════════════════════════════════════════════════════════

def detect_git_protocol(url: str) -> str:
    """检测 git URL 协议类型。返回 'https' | 'ssh' | 'unknown'。"""
    url = url.strip()
    if url.startswith("https://") or url.startswith("http://"):
        return "https"
    if url.startswith("git@") or url.startswith("ssh://"):
        return "ssh"
    return "unknown"


def parse_git_host(url: str) -> dict:
    """从 git URL 解析主机和服务信息。返回 {host, service, is_known}。"""
    import re
    url = url.strip()
    host = ""
    service = "unknown"

    if url.startswith("https://") or url.startswith("http://"):
        m = re.search(r'https?://([^/]+)', url)
        host = m.group(1) if m else ""
    elif url.startswith("git@"):
        m = re.search(r'git@([^:]+)', url)
        host = m.group(1) if m else ""

    if "github.com" in host:
        service = "GitHub"
    elif "gitlab" in host:
        service = "GitLab"
    elif "gitee.com" in host:
        service = "Gitee"
    elif "bitbucket" in host:
        service = "Bitbucket"

    return {"host": host, "service": service, "is_known": service != "unknown"}


def check_git_credential_helper() -> dict:
    """检测 git credential helper 配置。返回 {configured, helper, scope}。"""
    import subprocess as _sp
    result = {"configured": False, "helper": "", "scope": ""}

    for scope in ["--global", "--local", "--system"]:
        try:
            r = _sp.run(
                ["git", "config", scope, "credential.helper"],
                capture_output=True, text=True,
            )
            helper = r.stdout.strip()
            if helper:
                result["configured"] = True
                result["helper"] = helper
                result["scope"] = scope
                break
        except Exception:
            pass

    return result


def check_ssh_keys() -> dict:
    """检测 SSH 密钥状态。返回 {has_key, keys, agent_running}。"""
    from pathlib import Path as _Path
    ssh_dir = _Path.home() / ".ssh"
    result = {"has_key": False, "keys": [], "agent_running": False}

    if ssh_dir.exists():
        for f in ssh_dir.iterdir():
            name = f.name
            # 私钥文件：id_* 但不含 .pub
            if name.startswith("id_") and not name.endswith(".pub") and not name.endswith(".ppk"):
                result["keys"].append(str(f))
                result["has_key"] = True

    # 检查 ssh-agent
    import os as _os
    result["agent_running"] = bool(_os.environ.get("SSH_AUTH_SOCK"))

    return result


def get_credential_setup_guide(protocol: str, host_info: dict) -> list[str]:
    """根据协议和主机返回凭据配置的分步指南。返回步骤列表。"""
    steps: list[str] = []
    service = host_info["service"]
    host = host_info["host"]

    if protocol == "https":
        steps.append(f"检测到 HTTPS 协议 — 需要配置 git 凭据存储")
        steps.append("")

        cred = check_git_credential_helper()
        if cred["configured"]:
            steps.append(f"[OK] 凭据助手已配置: {cred['helper']} ({cred['scope']})")
            steps.append("")
            return steps

        steps.append("[!!] git 凭据存储未配置 — 强弱模型将无法自动提交和推送")
        steps.append("")

        if service == "GitHub":
            steps.append("推荐方案（GitHub Personal Access Token）：")
            steps.append("  1. 打开 https://github.com/settings/tokens")
            steps.append("  2. 点击 'Generate new token (classic)'")
            steps.append("  3. 勾选 'repo' 权限（完整仓库访问）")
            steps.append("  4. 生成后复制 token（只显示一次！）")
            steps.append("  5. 回到这里：用 token 当密码，用户名填你的 GitHub 用户名")
            steps.append("")
        elif service == "GitLab":
            steps.append("推荐方案（GitLab Personal Access Token）：")
            steps.append(f"  1. 打开 https://{host}/-/user_settings/personal_access_tokens")
            steps.append("  2. 勾选 'read_repository' + 'write_repository'")
            steps.append("  3. 生成后复制 token")
            steps.append("")
        elif service == "Gitee":
            steps.append("推荐方案（Gitee 私人令牌）：")
            steps.append(f"  1. 打开 https://gitee.com/profile/personal_access_tokens")
            steps.append("  2. 勾选 'projects' 权限")
            steps.append("  3. 生成后复制 token")
            steps.append("")

        steps.append("配置 git 凭据存储：")
        steps.append("")
        steps.append("  方式 1（推荐 — 长期存储，明文到磁盘）：")
        steps.append("    git config --global credential.helper store")
        steps.append("    # 下次 git clone/push 时输入用户名和 token，系统会记住")
        steps.append("")
        steps.append("  方式 2（内存缓存 1 小时 — 更安全，每次重启需重新输入）：")
        steps.append("    git config --global credential.helper 'cache --timeout=3600'")
        steps.append("")
        steps.append("  方式 3（仅本次会话，最强的安全但最不方便）：")
        steps.append("    # 每次 git clone/push 都需要手动输入用户名和 token")
        steps.append("")

    elif protocol == "ssh":
        steps.append(f"检测到 SSH 协议 — 需要配置 SSH 密钥")
        steps.append("")

        ssh = check_ssh_keys()
        if ssh["has_key"]:
            steps.append(f"[OK] 找到 SSH 密钥: {', '.join(ssh['keys'])}")
            if not ssh["agent_running"]:
                steps.append("[!!] ssh-agent 未运行，建议启动：")
                steps.append("  eval \"$(ssh-agent -s)\" && ssh-add ~/.ssh/id_rsa")
            steps.append("")

        if service in ("GitHub", "GitLab", "Gitee"):
            steps.append(f"确保 SSH 公钥已添加到 {service}：")
            if service == "GitHub":
                steps.append("  https://github.com/settings/keys")
            elif service == "GitLab":
                steps.append(f"  https://{host}/-/user_settings/ssh_keys")
            elif service == "Gitee":
                steps.append("  https://gitee.com/profile/sshkeys")
            steps.append(f"  公钥内容: cat ~/.ssh/id_rsa.pub (或 id_ed25519.pub)")
            steps.append("")

        if not ssh["has_key"]:
            steps.append("[!!] 未找到 SSH 密钥，需要生成：")
            steps.append("  ssh-keygen -t ed25519 -C \"niuma@worker\"")
            steps.append("  eval \"$(ssh-agent -s)\" && ssh-add ~/.ssh/id_ed25519")
            steps.append(f"  然后把公钥添加到 {service}（见上方链接）")
            steps.append("")

    steps.append("配置完成后，牛马会引导你输入凭据并保存。")
    return steps


def seed_git_credentials(host: str, username: str, token: str) -> tuple[bool, str]:
    """用 git credential approve 将凭据写入已配置的 credential helper。
    支持所有 helper（store / cache / osxkeychain / manager）。
    返回 (成功, 详情)。"""
    import subprocess as _sp
    input_data = (
        f"protocol=https\n"
        f"host={host}\n"
        f"username={username}\n"
        f"password={token}\n\n"
    )
    try:
        import os as _os
        env = {**_os.environ, "GIT_TERMINAL_PROMPT": "0"}
        r = _sp.run(
            ["git", "credential", "approve"],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        if r.returncode == 0:
            return True, "凭据已保存到 git 凭据管理器 | Credential saved"
        else:
            err = r.stderr.strip()
            if err:
                return False, f"凭据保存失败 | Failed: {err[:200]}"
            return False, "凭据保存失败: credential helper 可能未配置"
    except _sp.TimeoutExpired:
        return False, "凭据保存超时 — credential helper 可能未正确配置"
    except FileNotFoundError:
        return False, "git 命令不可用 | git not available"
    except Exception as e:
        return False, f"凭据保存异常 | Error: {str(e)[:200]}"


def verify_git_access(url: str, proxy: str = "") -> tuple[bool, str]:
    """通过 git ls-remote 验证能否访问远程仓库。返回 (成功, 详情)。"""
    import subprocess as _sp
    import os as _os
    cmd = ["git", "ls-remote", "--heads", url]
    if proxy:
        cmd = ["git", "-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}", "ls-remote", "--heads", url]
    env = {**_os.environ, "GIT_TERMINAL_PROMPT": "0"}

    try:
        r = _sp.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        if r.returncode == 0:
            return True, r.stderr.strip() or "OK"
        else:
            err = r.stderr.strip()
            if "Could not resolve host" in err:
                return False, f"无法解析主机 | Cannot resolve host — 检查网络或代理设置"
            if "Authentication failed" in err or "403" in err or "fatal: could not read" in err:
                return False, f"认证失败 | Authentication failed — 检查凭据配置"
            if "Permission denied" in err:
                return False, f"权限不足 | Permission denied — 检查 SSH 密钥或 token 权限"
            return False, err[:200]
    except _sp.TimeoutExpired:
        return False, "连接超时 | Connection timed out — 检查网络或代理设置"
    except Exception as e:
        return False, str(e)[:200]


def push_branch(repo_path: str | Path, branch: str, proxy: str = "") -> tuple[bool, str]:
    """Push 指定分支到 origin。返回 (成功与否, 输出信息)。"""
    if proxy:
        cmd = ["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}", "push", "origin", branch]
    else:
        cmd = ["push", "origin", branch]
    result = subprocess.run(
        ["git"] + cmd,
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stderr.strip() or result.stdout.strip()
    return result.returncode == 0, output


def get_all_branches_log(repo_path: str | Path) -> str:
    """返回当前仓库的完整 git log（含所有 niuma 分支）。"""
    output = git_run(repo_path, [
        "log", "--oneline", "--graph", "--all", "--max-count=50",
    ], check=False)
    return output if output else ""


def get_branch_log(repo_path: str | Path, branch: str = "", max_count: int = 20) -> str:
    """返回指定分支的 git log（含时间）。"""
    target = [branch] if branch else []
    output = git_run(repo_path, [
        "log", "--format=%h %ad %s", "--date=format:%m-%d %H:%M", f"--max-count={max_count}",
    ] + target, check=False)
    return output if output else ""


def delete_task_branch(repo_path: str | Path, branch: str) -> bool:
    """删除一个 niuma 任务分支。返回是否成功。"""
    try:
        git_run(repo_path, ["branch", "-D", branch])
        return True
    except RuntimeError:
        return False
