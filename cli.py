"""入口 | Entry Point
niuma 命令 → 交互式文字菜单。
The `niuma` command → interactive text menu."""

import os
import sys
from pathlib import Path

# 强制 UTF-8 输出（Windows 兼容）
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config
import project_manager


def main() -> None:
    """niuma 命令入口。"""
    _check_first_run()
    _main_menu()


# ═══════════════════════════════════════════════════════════════
# 首次运行：迁移旧数据
# ═══════════════════════════════════════════════════════════════

def _check_first_run() -> None:
    """检测并迁移旧 .env 和 state.sqlite。"""
    migrated = config._migrate_from_env()
    if migrated:
        print("  已从 .env 导入配置 | Config imported from .env")

    # 迁移旧的 state.sqlite
    old_db = Path(__file__).resolve().parent / "state.sqlite"
    if old_db.exists():
        print(f"  检测到旧数据库 | old database found: {old_db}")
        print(f"  新数据位置 | new location: {project_manager._DB_PATH}")
        print(f"  如需迁移，请手动将 {old_db} 复制到 {project_manager._DB_PATH}")
        print(f"  (旧数据库中的历史任务记录无法自动合并到新的多项目结构中)")


# ═══════════════════════════════════════════════════════════════
# 主菜单
# ═══════════════════════════════════════════════════════════════

def _main_menu() -> None:
    while True:
        _clear()
        _title("牛马 Niuma")
        print("  1. 配置强模型 | Configure Strong Model")
        print("  2. 配置弱模型 | Configure Weak Model")
        print("  3. 管理项目 | Manage Projects")
        print("  4. 退出 | Exit")
        print()

        choice = _ask("请选择 | Select [1-4, ESC=退出]", "1", esc="4")
        if choice == "1":
            _config_menu("strong")
        elif choice == "2":
            _config_menu("weak")
        elif choice == "3":
            _projects_menu()
        elif choice == "4":
            print("再见 | Goodbye.")
            sys.exit(0)


# ═══════════════════════════════════════════════════════════════
# 模型配置菜单
# ═══════════════════════════════════════════════════════════════

def _config_menu(which: str) -> None:
    label = "强模型 (编译器/审核器)" if which == "strong" else "弱模型 (代码生成器)"
    eng = "Strong Model (Compiler/Reviewer)" if which == "strong" else "Weak Model (Code Generator)"
    model_field = "strong_models" if which == "strong" else "weak_models"

    while True:
        c = config.get_model_config(which)
        _clear()
        _title(f"配置 {label} | Configure {eng}")
        print(f"  API Key:  {_mask(c['api_key'])}")
        print(f"  Base URL: {c['base_url']}")
        print(f"  模型名称: {c['model'] or '(未设置 | not set)'}")
        print()
        print("  1. 快速配置（选供应商，仅需填 API Key）| Quick Setup (pick provider)")
        print("  2. 修改 API Key")
        print("  3. 修改模型名称")
        print("  4. 修改 Base URL（高级）")
        print("  5. 测试连接 | Test Connection")
        print("  6. 返回 | Back")
        print()

        choice = _ask("请选择 | Select [1-6]", "6")
        if choice == "1":
            _provider_setup(which, model_field)
        elif choice == "2":
            new_key = _ask_secret("API Key")
            if new_key:
                config.set_model_config(which, api_key=new_key)
                print("  [OK] 已更新 | Updated.")
                _wait()
        elif choice == "3":
            new_model = _ask_text("模型名称 | Model Name")
            if new_model:
                config.set_model_config(which, model=new_model)
                print("  [OK] 已更新 | Updated.")
                _wait()
        elif choice == "4":
            new_url = _ask_text("Base URL", c["base_url"])
            if new_url:
                config.set_model_config(which, base_url=new_url)
                print("  [OK] 已更新 | Updated.")
                _wait()
        elif choice == "5":
            print()
            print(f"  测试连接中 | Testing connection...")
            ok, msg = config.test_connection(which)
            print(f"  {'[OK]' if ok else '[!!]'} {msg}")
            _wait()
        elif choice == "6":
            return


def _provider_setup(which: str, model_field: str) -> None:
    """快速配置：选供应商 → 填API Key → 选模型。三步搞定。"""
    providers = config.list_providers()
    # 计算页数
    per_page = 9
    page = 0
    total_pages = (len(providers) + per_page - 1) // per_page

    while True:
        _clear()
        _title("选择供应商 | Select Provider")
        if total_pages > 1:
            print(f"  (第 {page + 1}/{total_pages} 页 | Page {page + 1}/{total_pages})")
        print()

        start = page * per_page
        end = min(start + per_page, len(providers))
        for i, p in enumerate(providers[start:end], 1):
            print(f"  {i}. {p['name']}")
        print()
        print(f"  C. 自定义（手动输入全部信息）| Custom (manual input)")
        if total_pages > 1:
            print(f"  N. 下一页 | Next Page")
        print(f"  B. 返回 | Back")
        print()

        choice = _ask("请选择 | Select", "B").lower()
        if choice == "b":
            return
        elif choice == "c":
            _manual_setup(which)
            return
        elif choice == "n" and total_pages > 1:
            page = (page + 1) % total_pages
            continue
        else:
            try:
                idx = int(choice) - 1 + start
                if 0 <= idx < len(providers):
                    _provider_detail(which, providers[idx], model_field)
                    return
            except ValueError:
                pass


def _provider_detail(which: str, provider: dict, model_field: str) -> None:
    """填写所选供应商的配置详情。"""
    full = config.get_provider(provider["key"])
    if not full:
        return

    _clear()
    _title(f"配置 {provider['name']}")

    # Step 1: API Key
    print(f"  供应商 | Provider: {provider['name']}")
    print(f"  接口地址 | Base URL: {provider['base_url']}")
    print(f"  获取 Key | Get Key: {provider['key_hint']}")
    print()
    key = _ask_secret("API Key")
    if not key:
        print("  已取消 | Cancelled.")
        _wait()
        return

    # Step 2: 选模型
    models = full.get(model_field, [])
    _clear()
    _title(f"选择模型 | Select Model — {provider['name']}")
    print(f"  API Key: {_mask(key)}")
    print()
    for i, m in enumerate(models, 1):
        print(f"  {i}. {m}")
    print(f"  M. 手动输入模型名 | Manual input")
    print(f"  B. 返回 | Back")
    print()

    choice = _ask("请选择 | Select", "1").lower()
    if choice == "b":
        return
    elif choice == "m":
        model = _ask_text("模型名称 | Model Name")
        if not model:
            return
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                model = models[idx]
            else:
                return
        except ValueError:
            return

    # 保存配置
    config.set_model_config(which, api_key=key, base_url=provider["base_url"], model=model)
    print()
    print(f"  [OK] {provider['name']} — {model}")
    _wait()


def _manual_setup(which: str) -> None:
    """自定义手动配置（原有流程）。"""
    _clear()
    _title("自定义配置 | Custom Setup")

    c = config.get_model_config(which)
    key = _ask_secret("API Key")
    if key:
        config.set_model_config(which, api_key=key)
    url = _ask_text("Base URL", c["base_url"])
    if url:
        config.set_model_config(which, base_url=url)
    model = _ask_text("模型名称 | Model Name")
    if model:
        config.set_model_config(which, model=model)
    print()
    print("  [OK] 已保存 | Saved.")
    _wait()


# ═══════════════════════════════════════════════════════════════
# 项目管理菜单
# ═══════════════════════════════════════════════════════════════

def _projects_menu() -> None:
    while True:
        projects = project_manager.list_projects()
        _clear()
        _title("管理项目 | Manage Projects")

        if not projects:
            print("  (暂无项目) | (no projects yet)")
            print()

        for i, p in enumerate(projects, 1):
            print(f"  {i}. {p['name']}")
            print(f"     {p['git_url']}")
            print()

        print(f"  N. 新建项目 | New Project")
        print(f"  B. 返回 | Back")
        print()

        choice = _ask("请选择 | Select [N=新建/B=返回]", "B").lower()
        if choice == "b":
            return
        elif choice == "n":
            _create_project()
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(projects):
                    _project_menu(projects[idx])
            except ValueError:
                pass


def _create_project() -> None:
    _clear()
    _title("新建项目 | New Project")
    print("  项目将基于 Git 仓库创建 | Project will be created from a Git repository")
    print()

    name = _ask_text("项目名称 | Project name")
    if not name:
        return

    git_url = _ask_text("Git 仓库地址 | Git repository URL")
    if not git_url:
        return

    protocol = project_manager.detect_git_protocol(git_url)
    host_info = project_manager.parse_git_host(git_url)
    service = host_info["service"]
    host = host_info["host"]
    cred_seeded = False

    # ── HTTPS: 凭据配置 + 播种 ──
    if protocol == "https":
        cred = project_manager.check_git_credential_helper()

        if not cred["configured"]:
            _clear()
            _title("Git 认证配置 | Git Authentication Setup")
            print(f"  检测到 HTTPS 协议 — 需要配置 git 凭据存储")
            print(f"  目标: {host} ({service})")
            print()

            if service == "GitHub":
                print("  Step 1: 创建 Personal Access Token（如果还没有的话）")
                print("    → 打开 https://github.com/settings/tokens")
                print("    → 点击 'Generate new token (classic)'")
                print("    → 勾选 'repo' 权限（完整仓库访问）")
                print("    → 生成后复制 token（只显示一次！）")
                print()
            elif service == "GitLab":
                print(f"  Step 1: 创建 Personal Access Token（如果还没有的话）")
                print(f"    → 打开 https://{host}/-/user_settings/personal_access_tokens")
                print(f"    → 勾选 'read_repository' + 'write_repository'")
                print(f"    → 生成后复制 token")
                print()
            elif service == "Gitee":
                print(f"  Step 1: 创建私人令牌（如果还没有的话）")
                print(f"    → 打开 https://gitee.com/profile/personal_access_tokens")
                print(f"    → 勾选 'projects' 权限")
                print(f"    → 生成后复制 token")
                print()

            print("  Step 2: 配置 git 凭据存储（只做一次，全局生效）")
            print()
            print("    这是为了让 git 记住你的账号密码，后续强弱模型才能自动提交。")
            print()
            print("    牛马可以帮你自动配置，执行：")
            print("      git config --global credential.helper store")
            print("    （凭据明文存到 ~/.git-credentials，重启后仍然有效）")
            print()
            print("    备选（更安全但 1 小时后过期）：")
            print("      git config --global credential.helper 'cache --timeout=3600'")
            print()
            print("  ═══════════════════════════════════════")
            auto_cfg = _ask("  是否让牛马自动配置？(Y=是/n=我要手动配置)", "Y").lower()
            if auto_cfg in ("y", "yes", ""):
                import subprocess as _sp
                r = _sp.run(
                    ["git", "config", "--global", "credential.helper", "store"],
                    capture_output=True, text=True,
                )
                if r.returncode == 0:
                    print("  [OK] 已自动配置 credential.helper = store")
                else:
                    err = r.stderr.strip()
                    print(f"  [!!] 自动配置失败: {err}")
                    print("  请手动执行: git config --global credential.helper store")
                    _wait()
                    return
            else:
                print()
                print("  请手动执行（另开终端或这里都行）：")
                print("    git config --global credential.helper store")
                print("  完成后回到这里继续。")
            print("  ═══════════════════════════════════════")
            print()
            _ask("  按回车继续... | Press Enter when ready...")

            # 重新检测 credential.helper 是否已配置
            cred = project_manager.check_git_credential_helper()

            if not cred["configured"]:
                _clear()
                _title("Git 认证配置 | Git Authentication Setup")
                print(f"  [!!] 仍未检测到 credential.helper 配置")
                print()
                print("  请在终端执行后重试:")
                print("    git config --global credential.helper store")
                print()
                _wait()
                return
        else:
            _clear()
            _title("Git 认证配置 | Git Authentication Setup")
            print(f"  [OK] HTTPS 凭据存储已配置: {cred['helper']} ({cred['scope']})")
            print()

        # 播种凭据 — 不管 helper 是刚配的还是早就配的
        print("  Step 3: 输入账号凭据（仅此一次，保存后自动使用）")
        print(f"  用户名: 你的 {service} 用户名")
        if service == "GitHub":
            print(f"  密码:   Personal Access Token（不是登录密码！）")
        elif service in ("GitLab", "Gitee"):
            print(f"  密码:   个人访问令牌（不是登录密码！）")
        print()

        git_username = _ask_text(f"  {service} 用户名 | Username")
        if not git_username:
            print("  已取消 | Cancelled.")
            _wait()
            return

        git_token = _ask_secret(f"  Token / 密码（输入时不回显）| Token (hidden)")
        if not git_token:
            print("  已取消 | Cancelled.")
            _wait()
            return

        ok, msg = project_manager.seed_git_credentials(host, git_username, git_token)
        if ok:
            print(f"  [OK] {msg}")
            cred_seeded = True
        else:
            print(f"  [!!] {msg}")
            print(f"  将跳过凭据播种，直接尝试 clone（可能会提示输入密码）")
            print()
            _ask("  按回车继续... | Press Enter...")
        print()

    # ── SSH: 密钥检查 ──
    elif protocol == "ssh":
        _clear()
        _title("Git 认证配置 | Git Authentication Setup")
        print(f"  检测到 SSH 协议 — 需要 SSH 密钥")
        print()

        ssh = project_manager.check_ssh_keys()
        if not ssh["has_key"]:
            print("  [!!] 未找到 SSH 密钥")
            print()
            print("  生成密钥:")
            print("    ssh-keygen -t ed25519 -C \"niuma@worker\"")
            print()
            print(f"  添加公钥到 {service}:")
            if service == "GitHub":
                print("    https://github.com/settings/keys")
            elif service == "GitLab":
                print(f"    https://{host}/-/user_settings/ssh_keys")
            elif service == "Gitee":
                print("    https://gitee.com/profile/sshkeys")
            print(f"    公钥: cat ~/.ssh/id_ed25519.pub")
            print()
            _wait()
            return

        if not ssh["agent_running"]:
            print("  [!!] ssh-agent 未运行")
            print("  请在终端执行:")
            print('    eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519')
            print()
            _wait()
            return

        print(f"  [OK] SSH 密钥就绪: {', '.join(ssh['keys'])}")
        print()

    proxy = _ask_text("HTTP 代理 (不需要则留空) | HTTP proxy (leave empty if not needed)", "")
    print()

    # 验证 git 访问
    print(f"  测试连接到 {host}...")
    ok, msg = project_manager.verify_git_access(git_url, proxy)
    if not ok:
        # 区分认证失败和网络失败
        is_auth_error = any(kw in msg.lower() for kw in
            ["authentication", "permission denied", "could not read", "403"])
        print(f"  [!!] 无法访问仓库 | Cannot access repository:")
        print(f"  {msg}")
        if is_auth_error and cred_seeded:
            print()
            print(f"  凭据可能不正确。请检查：")
            print(f"  - 用户名是否拼写正确（注意大小写）")
            print(f"  - Token 是否完整复制（没有多余空格）")
            print(f"  - Token 是否有 'repo' 权限")
        print()
        print(f"  是否仍然尝试克隆？(y/N)")
        if _ask("  > ", "N").lower() not in ("y", "yes"):
            print("  已取消 | Cancelled.")
            _wait()
            return
        print()

    try:
        project_manager.create_project(name, git_url, proxy)
        print()

        # clone 成功 — 确认凭据生效
        if protocol == "https":
            cred = project_manager.check_git_credential_helper()
            if cred["configured"]:
                if "store" in cred["helper"]:
                    print(f"  [OK] 凭据已持久化 — 强弱模型可以自动提交和推送")
                elif "cache" in cred["helper"]:
                    print(f"  [OK] 凭据已缓存 — 注意超时后可能需重新输入")
                elif "manager" in cred["helper"] or "osxkeychain" in cred["helper"]:
                    print(f"  [OK] 凭据已存入系统密钥链 — 强弱模型可以自动提交和推送")

    except RuntimeError as e:
        err_msg = str(e)
        print(f"  [!!] {err_msg}")

        # 如果是认证失败，给具体建议
        if "could not read" in err_msg.lower() or "authentication" in err_msg.lower():
            print()
            if protocol == "https":
                print("  认证失败。可能原因:")
                print(f"  1. Token 权限不足 — 确保勾选了 repo 权限")
                print(f"  2. Token 复制不完整 — 尝试重新生成")
                print(f"  3. 手动验证: git clone {git_url}")
                print(f"     （手动 clone 成功后，重新运行 ./niuma 创建项目）")

    _wait()


def _project_menu(project: dict) -> None:
    while True:
        _clear()
        _title(f"项目 | Project: {project['name']}")
        print(f"  Git:  {project['git_url']}")
        print(f"  路径: {project['local_path']}")
        print()

        proj_path = project_manager.get_project_path(project["name"])
        if proj_path:
            # 列出任务文件
            tasks_dir = proj_path / "tasks"
            tsk_files = list(tasks_dir.glob("*.tsk")) if tasks_dir.exists() else []
            if tsk_files:
                print(f"  任务文件 | Task files ({len(tsk_files)}):")
                for tf in tsk_files:
                    print(f"    - {tf.name}")
            else:
                print(f"  (无任务文件 | no task files — 在 {tasks_dir}/ 下创建 .tsk 文件)")
            print()

        print("  1. 新建任务 | New Task")
        print("  2. Git 提交记录 | Git Commits")
        print("  D. 删除项目 | Delete Project")
        print("  3. 返回 | Back")
        print()

        choice = _ask("请选择 | Select [1-3]", "3").lower()
        if choice == "1":
            _clarify_and_run(project)
        elif choice == "2":
            _git_menu(project)
        elif choice == "d":
            confirm = _ask(f"  确认删除 '{project['name']}'? (输入项目名确认 | type name to confirm)")
            if confirm == project["name"]:
                project_manager.delete_project(project["name"])
                print(f"\n  [OK] 项目 '{project['name']}' 已从列表中移除 | removed from list")
                print(f"  本地文件保留在: {project['local_path']}")
                print(f"  (如需删除本地文件请手动操作 | Manually delete local files if needed)")
                _wait()
                return
            else:
                print("  已取消 | Cancelled.")
                _wait()
        elif choice == "3":
            return


def _git_menu(project: dict) -> None:
    """Git 提交记录查看和推送。"""
    proj_path = project_manager.get_project_path(project["name"])
    if not proj_path:
        print(f"  [!!] 项目路径不存在 | Project path not found")
        _wait()
        return

    while True:
        _clear()
        _title(f"Git 记录 | Git Log — {project['name']}")

        # 显示当前分支 git log
        log_lines = project_manager.get_branch_log(proj_path)
        if log_lines:
            for line in log_lines.splitlines()[:15]:
                print(f"  {line}")
        else:
            print("  (无提交记录 | no commits)")

        # 当前分支
        current_branch = project_manager.git_run(proj_path, ["branch", "--show-current"], check=False).strip()
        branches = project_manager.list_task_branches(proj_path)
        print()
        print(f"  当前分支 | Current: {current_branch}")
        if branches:
            print(f"  niuma 任务分支 | task branches: {', '.join(branches[:10])}")
        print()

        if branches:
            print(f"  P. Push 当前分支到远程 | Push current branch to remote")
        print(f"  B. 返回 | Back")
        print()

        choice = _ask("请选择 | Select", "B").lower()
        if choice == "b":
            return
        elif choice == "p" and branches:
            target = current_branch if current_branch.startswith("niuma") else branches[0]
            if not current_branch.startswith("niuma"):
                print(f"  当前不在 niuma 分支，将 push: {target}")
            proxy = _ask_text("代理 (不需要则留空) | Proxy", "")
            print(f"  Pushing {target}...")
            ok, msg = project_manager.push_branch(proj_path, target, proxy=proxy)
            if ok:
                print(f"  [OK] Push 完成 | Done — {msg}" if msg else "  [OK] Push 完成 | Done")
            else:
                print(f"  [!!] Push 失败 | Failed: {msg}")
            _wait()


def _clarify_and_run(project: dict) -> None:
    """对话式需求澄清 + 运行。"""
    import compiler as _compiler
    import main as _main
    import project_manager as _pm
    from config import get_retry_limits

    proj_path = _pm.get_project_path(project["name"])
    if not proj_path:
        print(f"  [!!] 项目路径不存在 | Project path not found")
        _wait()
        return

    _clear()
    _title(f"新建任务 | New Task — {project['name']}")
    print("  请描述你想实现的功能（自然语言）:")
    print()

    initial = _ask_text("  > ")
    if not initial:
        return

    _clear()
    _title(f"需求澄清 | Requirement Clarification — {project['name']}")
    preview = initial[:100] + ("..." if len(initial) > 100 else "")
    print(f"  你的描述: {preview}")
    print()
    print("  [强模型] 正在分析需求...")

    history = [{"role": "user", "content": initial}]
    limits = get_retry_limits()
    max_rounds = limits["clarify_rounds"]

    resp = None
    for round_num in range(1, max_rounds + 1):
        try:
            resp = _compiler.clarify_step(history)
        except Exception as e:
            print(f"\n  [!!] 强模型调用失败: {e}")
            print("  是否直接用当前描述开始编译？(Y/n)")
            if _ask("  > ", "Y").lower() in ("y", "yes", ""):
                break
            _wait()
            return

        if resp.get("type") == "summary" or "summary" in resp:
            summary = resp.get("summary", str(resp))
            _clear()
            _title(f"需求确认 | Confirmation — {project['name']}")
            print(f"  [强模型] 已整理需求确认：")
            print()
            for line in summary.strip().split("\n"):
                print(f"  {line}")
            print()
            confirm = _ask("  确认无误？(Y/n/ESC=取消)", "Y", esc="n").lower()
            if confirm in ("y", "yes", ""):
                break
            else:
                history.append({"role": "user", "content": "还需要继续澄清，请多问几个问题"})
                continue

        question = resp.get("question", str(resp))
        print(f"\n  Q: {question}")
        print("  (直接回车=退出 | Enter to exit)")
        answer = _ask("  > ")
        history.append({"role": "assistant", "content": f"Q: {question}"})
        history.append({"role": "user", "content": answer})
    else:
        print(f"\n  已达最大澄清轮数 ({max_rounds})，使用当前结果编译。")

    final_summary = resp.get("summary", initial) if resp else initial

    print()
    print(f"  ✓ 需求已确认，开始编译...")
    print()

    # 调用 pipeline
    orig_dir = os.getcwd()
    try:
        os.chdir(str(proj_path))
        success = _main.start_pipeline(final_summary, str(proj_path), verbose=True)
    except Exception as e:
        os.chdir(orig_dir)
        print(f"  [!!] {e}")
        _wait()
        return

    # 显示 git 状态
    import project_manager as __pm
    current_branch = __pm.get_current_branch(proj_path)
    branches = __pm.list_task_branches(proj_path)
    os.chdir(orig_dir)

    print()
    if success:
        print(f"  [OK] 分支 {current_branch} 就绪，审阅后 push")
        print(f"  审阅: cd {proj_path} && git log --oneline {current_branch}")
        if branches:
            print(f"  niuma 任务分支: {', '.join(branches)}")
    else:
        print(f"  [!!] 分支 {current_branch} 保留供检查")
    print()
    _wait()


def _run_task_in_project(project: dict) -> None:
    proj_path = project_manager.get_project_path(project["name"])
    if not proj_path:
        print(f"  [!!] 项目路径不存在 | Project path not found: {project['local_path']}")
        print(f"  尝试 git pull 或重新创建项目 | Try git pull or recreate the project")
        _wait()
        return

    tasks_dir = proj_path / "tasks"
    tsk_files = list(tasks_dir.glob("*.tsk")) if tasks_dir.exists() else []
    if not tsk_files:
        print("  [!!] 项目中没有 .tsk 任务文件 | No .tsk task files in project")
        print(f"  请在 {tasks_dir}/ 下创建 .tsk 文件 | Create .tsk files in {tasks_dir}/")
        _wait()
        return

    _clear()
    _title(f"运行任务 | Run Task — {project['name']}")
    for i, tf in enumerate(tsk_files, 1):
        print(f"  {i}. {tf.name}")
    print(f"  B. 返回 | Back")
    print()

    choice = _ask("请选择 | Select", "B").lower()
    if choice == "b":
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(tsk_files):
            task_file = tsk_files[idx]
            task_desc = task_file.read_text(encoding="utf-8").strip()
            _clear()
            print(f"  项目 | Project: {project['name']}")
            print(f"  任务 | Task: {task_file.name}")
            print(f"  {'-'*40}")

            # 调用管道
            import main as _main
            import project_manager as _pm
            orig_dir = os.getcwd()
            try:
                os.chdir(str(proj_path))
                success = _main.run_task(task_desc, str(proj_path), verbose=True)
            except RuntimeError as e:
                os.chdir(orig_dir)
                print(f"  [!!] {e}")
                _wait()
                return
            except Exception as e:
                os.chdir(orig_dir)
                print(f"  [!!] 运行任务时出错 | Error running task: {e}")
                print(f"  请检查模型配置 | Check model configuration: ./niuma → 配置模型")
                _wait()
                return

            # 显示 git 分支状态
            current_branch = _pm.get_current_branch(proj_path)
            branches = _pm.list_task_branches(proj_path)
            os.chdir(orig_dir)
            print()
            if success:
                print(f"  [OK] 分支 {current_branch} 就绪，人类审阅后 merge | Branch ready for human review")
                print(f"  审阅 | review: cd {proj_path} && git log --oneline {current_branch}")
                if branches:
                    print(f"  niuma 任务分支 | task branches: {', '.join(branches)}")
            else:
                print(f"  [!!] 分支 {current_branch} 保留供检查 | Branch kept for inspection")
            print()
            _wait()
    except ValueError:
        pass


def _create_task_file(project: dict) -> None:
    proj_path = project_manager.get_project_path(project["name"])
    if not proj_path:
        print(f"  [!!] 项目路径不存在 | Project path not found")
        _wait()
        return

    _clear()
    _title(f"新建任务 | New Task — {project['name']}")
    filename = _ask_text("文件名 (不含扩展名) | Filename (without extension)")
    if not filename:
        return

    if not filename.endswith(".tsk"):
        filename += ".tsk"

    tasks_dir = proj_path / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task_path = tasks_dir / filename

    print()
    print(f"  请输入任务描述 | Enter task description")
    print(f"  (输入空行结束 | Enter empty line to finish)")
    print()

    lines = []
    while True:
        line = input("  > ")
        if not line:
            break
        lines.append(line)

    if lines:
        task_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  [OK] 任务已保存 | Task saved: {task_path}")
    _wait()


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _clear() -> None:
    """清屏。"""
    os.system("cls" if os.name == "nt" else "clear")


def _title(text: str) -> None:
    print(f"  {'='*50}")
    print(f"  {text}")
    print(f"  {'='*50}")
    print()


def _getch() -> str:
    """读取单个按键（跨平台）。ESC 返回 '\x1b'。"""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getch()
        if ch == b'\xe0':  # Windows 扩展键前缀
            ch = msvcrt.getch()
        return ch.decode("utf-8", errors="replace") if isinstance(ch, bytes) else ch
    else:
        import tty, termios, select
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                # 非阻塞检查是否是转义序列（如箭头键）
                rest = ""
                while select.select([sys.stdin], [], [], 0.05)[0]:
                    c = sys.stdin.read(1)
                    if not c:
                        break
                    rest += c
                if rest:
                    ch += rest
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _input_line(prompt: str, default: str = "") -> str | None:
    """逐字符读取输入。ESC 返回 None（表示取消），Enter 返回字符串。"""
    sys.stdout.write(f"  {prompt}: ")
    sys.stdout.flush()
    chars: list[str] = []
    while True:
        ch = _getch()
        if ch == "\x1b":  # ESC = 取消
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None
        elif ch in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            result = "".join(chars).strip()
            return result if result else default
        elif ch in ("\x7f", "\x08"):  # Backspace
            if chars:
                chars.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        elif len(ch) == 1 and ord(ch) >= 32:  # 可打印字符
            chars.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()


_ESC = object()  # ESC 键取消的标记


def _ask(prompt: str, default: str = "", esc: str = "") -> str:
    """显示提示并读取用户输入。ESC=取消，esc 参数为 ESC 时的返回值。"""
    result = _input_line(prompt, default)
    if result is None:
        return esc if esc else default  # ESC 时: 有 esc 用 esc, 否则用 default
    return result


def _ask_secret(prompt: str) -> str:
    """读取敏感输入（API Key / Token），不回显。"""
    import getpass
    result = getpass.getpass(f"  {prompt}: ").strip()
    return result


def _ask_text(prompt: str, default: str = "") -> str:
    """请求用户输入文本，显示默认值。"""
    if default:
        result = input(f"  {prompt} [{default}]: ").strip()
        return result if result else default
    else:
        result = input(f"  {prompt}: ").strip()
        return result


def _mask(value: str) -> str:
    """遮蔽 API key 中间部分。"""
    if not value:
        return "(未设置 | not set)"
    if len(value) <= 8:
        return value[:2] + "***" + value[-2:]
    return value[:4] + "****" + value[-4:]


def _wait() -> None:
    """等待用户按回车。"""
    input("\n  按回车继续... | Press Enter to continue...")


if __name__ == "__main__":
    main()
