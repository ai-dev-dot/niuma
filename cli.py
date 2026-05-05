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

        choice = _ask("请选择 | Select [1-4]", "1")
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
            new_key = _ask_text("API Key")
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
    key = _ask_text("API Key")
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
    key = _ask_text("API Key")
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

        choice = _ask("请选择 | Select", "B").lower()
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

    proxy = _ask_text("HTTP 代理 (不需要则留空) | HTTP proxy (leave empty if not needed)", "")
    print()

    try:
        project_manager.create_project(name, git_url, proxy)
    except RuntimeError as e:
        print(f"  [!!] {e}")
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

        print("  1. 运行任务 | Run Task")
        print("  2. 新建任务文件 | New Task File")
        print("  D. 删除项目 | Delete Project")
        print("  3. 返回 | Back")
        print()

        choice = _ask("请选择 | Select [1-3]", "3").lower()
        if choice == "1":
            _run_task_in_project(project)
        elif choice == "2":
            _create_task_file(project)
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
                success = _main.run_task(task_desc, str(proj_path))
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


def _ask(prompt: str, default: str = "") -> str:
    """显示提示并读取用户输入。"""
    result = input(f"  {prompt}: ").strip()
    return result if result else default


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
