"""入口 | Entry point
CLI 驱动 compiler → worker → reviewer 管线。
Orchestrates the compiler → worker → reviewer pipeline."""

import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

# 强制 UTF-8 输出（Windows 兼容）
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import compiler
import metrics
import reviewer
import worker
from models import (
    DAG,
    MetricsEntry,
    NodeResult,
    NodeStatus,
    ReviewResult,
)

_PROJECT_ROOT = Path(__file__).resolve().parent


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    args = _parse_args()

    if args.doctor:
        _cmd_doctor()
        return

    if args.dry_run:
        _cmd_dry_run()
        return

    _cmd_run(args)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="牛马 Niuma — Compiler-driven AI task orchestration",
    )
    p.add_argument("task_file", nargs="?", help="任务描述文件路径 (.tsk) | Task description file")
    p.add_argument("--inline", "-i", help="直接输入任务描述 | Inline task description")
    p.add_argument("--doctor", action="store_true", help="检查前置条件 | Check prerequisites")
    p.add_argument("--dry-run", action="store_true", help="用 mock 试跑流程 | Dry run with mocks")
    p.add_argument("--verbose", "-v", action="store_true", help="详细输出每一步过程 | Show each step in detail")
    return p.parse_args()


# ═══════════════════════════════════════════════════════════════
# --doctor: 预检命令
# ═══════════════════════════════════════════════════════════════

def _cmd_doctor() -> None:
    print("== Niuma -- Doctor | Environment Check ==\n")
    all_ok = True

    def check(name: str, ok: bool, detail: str = "") -> bool:
        nonlocal all_ok
        if ok:
            print(f"  [OK] {name} {detail}".rstrip())
        else:
            print(f"  [!!] {name} — {detail}")
            all_ok = False
        return ok

    # Python
    py_ver = sys.version_info
    check(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}",
          py_ver >= (3, 10),
          "需要 3.10+ | need 3.10+" if py_ver < (3, 10) else "")

    # Node.js
    node_ver = _run_cmd(["node", "--version"])
    node_ok = node_ver.startswith("v")
    check(f"Node.js {node_ver.strip() if node_ok else '未安装 | not found'}",
          node_ok,
          "" if node_ok else "运行: https://nodejs.org | Install from https://nodejs.org")

    # node_modules / jest
    node_modules = _PROJECT_ROOT / "node_modules"
    jest_bin = node_modules / ".bin" / "jest"

    if node_modules.exists() and jest_bin.exists():
        # npm 可能不在 PATH 上（如 Bash-on-Windows），但 node_modules 存在说明已安装
        check("node_modules (jest, ts-jest, typescript)", True, str(jest_bin))
    elif node_ok:
        check("node_modules (jest, ts-jest, typescript)", False,
              "运行: npm install | Run: npm install")
        all_ok = False
    else:
        check("node_modules (jest, ts-jest, typescript)", False,
              "需要 Node.js | Need Node.js first")
        all_ok = False

    # pytest
    pytest_ver = _run_cmd(["python", "-m", "pytest", "--version"])
    pytest_ok = "pytest" in pytest_ver
    check(f"{pytest_ver.strip() if pytest_ok else 'pytest 未安装 | pytest not found'}",
          pytest_ok,
          "" if pytest_ok else "运行: pip install pytest | Run: pip install pytest")

    # config.json (TUI 配置) 或 .env (手动配置)
    import config as _cfg
    cfg_ok = _cfg.config_exists()
    strong_cfg = _cfg.get_model_config("strong")
    weak_cfg = _cfg.get_model_config("weak")
    cfg_label = f"~/.niuma/config.json" if cfg_ok else "未找到 | not found"

    if cfg_ok:
        check(cfg_label, True, f"强模型={strong_cfg['model'] or '(待设)'} 弱模型={weak_cfg['model'] or '(待设)'}")
        strong_key_ok = bool(strong_cfg["api_key"]) and "your-api-key" not in strong_cfg["api_key"] and "sk-your" not in strong_cfg["api_key"]
        weak_key_ok = bool(weak_cfg["api_key"]) and "your-api-key" not in weak_cfg["api_key"] and "sk-your" not in weak_cfg["api_key"]
        if strong_key_ok and weak_key_ok:
            check("  API Keys", True, "强/弱模型均已设置 | both configured")
        else:
            missing = []
            if not strong_key_ok:
                missing.append("强模型 API Key")
            if not weak_key_ok:
                missing.append("弱模型 API Key")
            check("  API Keys", False, "未设置: " + ", ".join(missing) + " | run ./niuma → 配置模型")
            all_ok = False
    else:
        check(cfg_label, False, "运行 ./niuma → 配置强/弱模型 | Run ./niuma → Configure models")
        # Fallback: 检查 .env
        env_file = _PROJECT_ROOT / ".env"
        if env_file.exists():
            has_key = "LLM_API_KEY" in env_file.read_text(encoding="utf-8")
            check(".env (fallback)", True, "已找到 | found")
            api_key = os.getenv("LLM_API_KEY", "")
            if api_key and "your-api-key" not in api_key and "sk-your" not in api_key:
                check("  LLM_API_KEY", True, "已设置 | set")
            else:
                check("  LLM_API_KEY", False,
                      "未设置或使用示例值 | not set or using placeholder value")
                all_ok = False
        else:
            check(".env (fallback)", False,
                  "运行 ./niuma 配置模型 | Run ./niuma to configure models")
            all_ok = False

    # tasks/
    tasks_dir = _PROJECT_ROOT / "tasks"
    if tasks_dir.exists() and any(tasks_dir.iterdir()):
        tsk_files = list(tasks_dir.glob("*.tsk"))
        check("tasks/", True, f"{len(tsk_files)} 个任务文件 | {len(tsk_files)} task files")
    else:
        check("tasks/", False, "无任务文件 | no task files found")

    print()
    if all_ok:
        print("[OK] 一切就绪 | All checks passed.")
        print("    运行 | Run: ./niuma → 管理项目 → 运行任务")
    else:
        print("[!!] 部分检查未通过，请修复后重试 | Some checks failed. Fix and re-run --doctor.")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# --dry-run: 试运行
# ═══════════════════════════════════════════════════════════════

def _cmd_dry_run() -> None:
    """用 mock 跑一遍完整流程，验证结构正确。"""
    print("== Niuma -- Dry Run (all API calls mocked) ==\n")

    from unittest.mock import patch
    import llm
    import sandbox

    task_desc = "实现一个简单的加法函数 add(a: number, b: number): number"

    mock_dag = DAG(nodes=[_make_mock_node()])
    mock_sandbox = sandbox.SandboxResult(exit_code=0, stdout="PASS", stderr="")
    mock_strong = llm.LLMResponse(content="PASS", input_tokens=100, output_tokens=5)
    mock_weak = llm.LLMResponse(
        content="function add(a: number, b: number): number { return a + b; }",
        input_tokens=200, output_tokens=30,
    )

    with patch.object(compiler, "compile_task", return_value=mock_dag) as mock_comp:
        with patch.object(worker, "execute_node") as mock_exec:
            with patch.object(reviewer, "review") as mock_rev:
                mock_exec.return_value = NodeResult(
                    node_id="add", status=NodeStatus.PASSED,
                    generated_code="function add(a: number, b: number): number { return a + b; }",
                    iteration_count=1,
                )
                mock_rev.return_value = ReviewResult(passed=True)

                # 模拟 main pipeline
                print(f"任务 | Task: {task_desc}")
                print("  编译 | Compiling...")
                dag = compiler.compile_task(task_desc)
                print(f"  [OK] DAG: {len(dag.nodes)} 节点 | nodes")

                print("  执行 | Executing...")
                results: list[NodeResult] = []
                for node in dag.topological_order():
                    nr = worker.execute_node(node, {})
                    results.append(nr)
                    print(f"  [OK] {node.node_id} ({nr.iteration_count} 轮 | iterations)")

                print("  审核 | Reviewing...")
                rv = reviewer.review(task_desc, dag, results)
                print(f"  {'[OK] PASS' if rv.passed else 'X FAIL'}")

                context = {} if not results else {results[0].node_id: results[0].generated_code}
                mock_exec.assert_called()
                mock_rev.assert_called()

    print("\n[OK] 试运行通过 | Dry run passed — 流程结构正确 | pipeline structure valid.")
    print("   运行 ./niuma 配置模型后即可执行真实任务 | Run ./niuma to configure models, then real tasks")


def _make_mock_node() -> "DAGNode":
    from models import Contract, FunctionSignature, DAGNode
    return DAGNode(
        node_id="add",
        name="加法函数",
        signature=FunctionSignature(
            language="typescript",
            function_name="add",
            params=[{"name": "a", "type": "number"}, {"name": "b", "type": "number"}],
            return_type="number",
        ),
        contract=Contract(
            preconditions=["a, b 为数字"],
            postconditions=["返回 a+b 的结果"],
        ),
        test_skeleton="test('adds two numbers', () => { expect(add(1, 2)).toBe(3); });",
        max_iterations=5,
    )


# ═══════════════════════════════════════════════════════════════
# run_task: 供 cli.py 和其他入口调用的核心函数
# ═══════════════════════════════════════════════════════════════

def run_task(task_description: str, project_path: str = "", verbose: bool = False) -> bool:
    """运行一次完整 pipeline：创建 git 分支 → 编译 → 执行 → 审核。
    Each handoff is recorded as a git commit on a task branch.
    返回 True 表示任务成功完成。"""
    import project_manager as _pm
    from config import get_model_config, get_retry_limits

    base = Path(project_path) if project_path else _PROJECT_ROOT
    task_id = str(uuid.uuid4())[:8]
    t_total = time.time()

    # 设置运行日志
    import json as _json
    import datetime as _dt
    from pathlib import Path as _Path
    log_dir = base / ".niuma" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    import llm as _llm

    log_file = log_dir / f"{_dt.date.today().isoformat()}_{task_id}.jsonl"
    _llm.set_log_path(str(log_file))

    def _write_log(entry: dict) -> None:
        entry["ts"] = _dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")

    _llm.set_log_callback(_write_log)
    _write_log({"role": "pipeline", "action": "start", "task_desc": task_description[:200]})

    strong_cfg = get_model_config("strong")
    weak_cfg = get_model_config("weak")

    if verbose:
        print()
        print(f"  ╔{'═'*60}╗")
        print(f"  ║  Niuma Pipeline — {task_id}")
        print(f"  ║  强模型: {strong_cfg['model']} @ {strong_cfg['base_url']}")
        print(f"  ║  弱模型: {weak_cfg['model']} @ {weak_cfg['base_url']}")
        print(f"  ║  任务: {task_description[:50]}{'...' if len(task_description) > 50 else ''}")
        print(f"  ╚{'═'*60}╝")
        print()
        print(f"  >>> git checkout -b niuma/{task_id}")
    else:
        print(f"[{task_id}] 任务 | Task: {task_description[:80]}{'...' if len(task_description) > 80 else ''}")

    # —— 创建任务分支 ——
    try:
        branch = _pm.create_task_branch(base, task_id)
        if not verbose:
            print(f"[{task_id}] 分支 | Branch: {branch}")
    except RuntimeError as e:
        print(f"[{task_id}] X 创建分支失败 | Branch creation failed: {e}")
        return False

    # —— 写需求文档 ——
    _pm.commit_file(
        str(base), ".niuma/requirement.md", task_description,
        _pm.GIT_AUTHOR_COMPILER, f"cli: requirement confirmed for {task_id}",
    )
    _write_log({"role": "cli", "action": "requirement_confirmed"})
    if verbose:
        print(f"  >>> git commit: .niuma/requirement.md ({_pm.GIT_AUTHOR_COMPILER[0]} -> Strong Model)")

    # —— 编译 | Compile ——
    t0 = time.time()
    if verbose:
        print()
        print(f"  ╔═ STEP 1: 强模型编译 | Compile ═╗")
    else:
        print(f"[{task_id}] 编译 | Compiling...")
    try:
        _llm.set_meta({"role": "compiler", "task_id": task_id})
        dag = compiler.compile_task(task_description, verbose=verbose)
    except compiler.CompilationError as e:
        print(f"[{task_id}] X 编译失败 | Compilation failed: {e}")
        _pm.switch_branch(base, "main")
        _pm.git_run(base, ["branch", "-D", branch], check=False)
        return False
    except RuntimeError as e:
        print(f"[{task_id}] X 编译失败 | Compilation failed: {e}")
        _pm.switch_branch(base, "main")
        _pm.git_run(base, ["branch", "-D", branch], check=False)
        return False
    if not verbose:
        print(f"[{task_id}] [OK] DAG: {len(dag.nodes)} 节点 | nodes ({time.time() - t0:.1f}s)")

    # 强模型提交 DAG 到 git
    compiler.commit_dag(dag, str(base), task_id)
    _write_log({"role": "compiler", "action": "done", "dag_nodes": len(dag.nodes)})
    print(f"  >>> git commit: .niuma/dag.json ({_pm.GIT_AUTHOR_COMPILER[0]} → Strong Model)")

    # —— 执行 | Execute ——
    if verbose:
        print()
        print(f"  ╔═ STEP 2: 弱模型执行 | Worker ═╗")

    node_results: list[NodeResult] = []
    completed_context: dict[str, str] = {}

    for i, node in enumerate(dag.topological_order(), 1):
        t_node = time.time()
        if verbose:
            print(f"  节点{i}/{len(dag.nodes)}: {node.node_id} — {node.name}")
        else:
            print(f"[{task_id}] [{i}/{len(dag.nodes)}] {node.node_id} ({node.name[:40]}) ...")
        nr = worker.execute_node(node, completed_context, task_id=task_id, verbose=verbose)
        node_results.append(nr)

        if nr.status == NodeStatus.PASSED:
            completed_context[node.node_id] = nr.generated_code
            _save_output(base, task_id, node, nr)
            _write_log({"role": "worker", "action": "done", "node": node.node_id, "status": "passed", "iterations": nr.iteration_count})
            # 弱模型提交代码到 git
            worker.commit_node(node, nr, str(base))
            if verbose:
                print(f"    >>> git commit: src/{node.node_id}.ts ({_pm.GIT_AUTHOR_WORKER[0]} → Weak Model)")
            else:
                print(f"  [OK] {node.node_id} 通过 | passed ({nr.iteration_count} 轮 | iter, {time.time() - t_node:.1f}s)")
                print(f"    → git commit: src/{node.node_id}.ts (Weak Model)")
        else:
            print(f"  X {node.node_id} 失败 | failed ({nr.iteration_count} 轮 | iter)")

    passed_count = sum(1 for nr in node_results if nr.status == NodeStatus.PASSED)

    # —— 审核 | Review ——
    if verbose:
        print()
        print(f"  ╔═ STEP 3: 强模型审核 | Review ═╗")

    review_passes = False
    limits = get_retry_limits()
    max_review_rounds = limits["reviewer_rounds"]
    for review_round in range(1, max_review_rounds + 1):
        if verbose:
            print(f"  审核轮次 {review_round}/{max_review_rounds}...")
        else:
            print(f"[{task_id}] 审核 | Reviewing (第{review_round}轮 | round {review_round}/{max_review_rounds})...")
        t_rev = time.time()
        _llm.set_meta({"role": "reviewer", "task_id": task_id})
        rv = reviewer.review(task_description, dag, node_results, verbose=verbose)

        # 强模型提交审核结论到 git
        reviewer.commit_review(rv, str(base), task_id)
        verdict = "PASS" if rv.passed else "FAIL"
        print(f"    >>> git commit: .niuma/review.md ({_pm.GIT_AUTHOR_REVIEWER[0]} → Strong Model — {verdict})")

        if rv.passed:
            review_passes = True
            _write_log({"role": "reviewer", "action": "done", "verdict": "PASS", "round": review_round})
            if not verbose:
                print(f"  [OK] PASS ({time.time() - t_rev:.1f}s)")
            break

        print(f"  X FAIL: {rv.suggestions[:200]}")
        print(f"    → git commit: .niuma/review.md (Strong Model — FAIL)")
        for node in dag.topological_order():
            if node.node_id in rv.failed_nodes:
                print(f"    重做 | retry: {node.node_id}...")
                nr = worker.execute_node(node, completed_context, task_id=task_id, review_feedback=rv.suggestions, verbose=verbose)
                for j, old in enumerate(node_results):
                    if old.node_id == node.node_id:
                        node_results[j] = nr
                        break
                if nr.status == NodeStatus.PASSED:
                    completed_context[node.node_id] = nr.generated_code
                    _save_output(base, task_id, node, nr)
                    worker.commit_node(node, nr, str(base))
                    print(f"      → git commit: src/{node.node_id}.ts (Weak Model)")

        passed_count = sum(1 for nr in node_results if nr.status == NodeStatus.PASSED)

    total_time = time.time() - t_total

    # —— Metrics + 清理 ——
    entry = MetricsEntry(
        task_id=task_id,
        strong_tokens=0,
        weak_tokens=0,
        node_iterations={nr.node_id: nr.iteration_count for nr in node_results},
        passed_count=passed_count,
        total_count=len(dag.nodes),
    )
    metrics.record(entry, output_dir=str(base / "outputs"))
    metrics.print_summary(entry)

    if review_passes:
        print(f"[{task_id}] [OK] 产物 | Output: {base / 'outputs' / task_id}/")
        print(f"[{task_id}] 分支 {branch} 就绪，审阅后 merge | Branch ready, review then merge")
        print(f"[{task_id}]   git checkout {branch} && git log --oneline")
        print(f"[{task_id}] 总耗时 | Total: {total_time:.1f}s")
    else:
        print(f"[{task_id}] X 审核 {max_review_rounds} 轮未通过 | Review failed after {max_review_rounds} rounds ({total_time:.1f}s)")
        print(f"[{task_id}]   分支 {branch} 保留供检查 | Branch kept for inspection")

    _write_log({"role": "pipeline", "action": "done", "passed": review_passes, "total_s": round(total_time, 1), "log_file": str(log_file)})

    # 写任务汇总
    summary = {
        "task_id": task_id,
        "passed": review_passes,
        "total_s": round(total_time, 1),
        "strong_model": get_model_config("strong")["model"],
        "weak_model": get_model_config("weak")["model"],
        "nodes_total": len(dag.nodes),
        "nodes_passed": passed_count,
        "node_iterations": {nr.node_id: nr.iteration_count for nr in node_results},
    }
    summary_path = log_file.parent / f"{log_file.stem}_summary.json"
    summary_path.write_text(_json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    _llm.set_log_callback(None)
    return review_passes


# ═══════════════════════════════════════════════════════════════
# run: 真实执行（CLI 入口 — 向后兼容）
# ═══════════════════════════════════════════════════════════════

def _cmd_run(args: argparse.Namespace) -> None:
    """CLI 入口 — 委托给 run_task()。"""
    task_desc, proj_path = _read_task(args)
    success = run_task(task_desc, project_path=proj_path, verbose=args.verbose)
    if not success:
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _read_task(args: argparse.Namespace) -> tuple[str, str]:
    """返回 (任务描述, 项目路径)。"""
    if args.inline:
        return args.inline, ""
    if args.task_file:
        path = Path(args.task_file).resolve()
        if not path.exists():
            print(f"[!!] 文件不存在 | File not found: {args.task_file}")
            print(f"   试试 | Try: python main.py --inline '你的任务描述 | your task description'")
            sys.exit(1)
        # 推导项目根目录：tasks/ 的父目录
        proj_root = str(path.parent.parent) if path.parent.name == "tasks" else ""
        return path.read_text(encoding="utf-8").strip(), proj_root
    print("用法 | Usage: python main.py tasks/<task>.tsk")
    print("      python main.py --inline '任务描述 | task description'")
    print("      python main.py --doctor      检查环境 | check prerequisites")
    print("      python main.py --dry-run    试运行 | dry run with mocks")
    print("      python main.py --verbose    显示每一步详细过程 | show each step")
    sys.exit(1)


def _run_cmd(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def _save_output(base: Path, task_id: str, node: "DAGNode", nr: NodeResult) -> None:
    ext = "ts" if node.signature.language == "typescript" else "py"
    out_dir = base / "outputs" / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    filepath = out_dir / f"{node.node_id}.{ext}"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(nr.generated_code)


if __name__ == "__main__":
    main()
