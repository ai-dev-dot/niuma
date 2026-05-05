"""入口 —— CLI 驱动 compiler → worker → reviewer 管线。"""

import argparse
import os
import sqlite3
import sys
import uuid

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
    TaskRecord,
    TaskStatus,
)


def main() -> None:
    args = _parse_args()
    task_desc = _read_task(args)
    task_id = str(uuid.uuid4())[:8]

    db = _init_db()
    _ensure_schema(db)

    print(f"[{task_id}] 任务: {task_desc[:80]}...")

    # -- 编译 --
    record = TaskRecord(id=task_id, task_description=task_desc)
    record.status = TaskStatus.COMPILING
    _upsert_task(db, record)

    print(f"[{task_id}] 编译中...")
    try:
        dag = compiler.compile_task(task_desc)
    except compiler.CompilationError as e:
        print(f"[{task_id}] 编译失败: {e}")
        record.status = TaskStatus.FAILED
        _upsert_task(db, record)
        db.close()
        sys.exit(1)

    record.dag_json = _dag_to_json(dag)
    _upsert_task(db, record)
    print(f"[{task_id}] DAG 编译完成: {len(dag.nodes)} 个节点")

    # -- 执行 --
    record.status = TaskStatus.EXECUTING
    _upsert_task(db, record)

    node_results: list[NodeResult] = []
    completed_context: dict[str, str] = {}

    for node in dag.topological_order():
        print(f"[{task_id}] 执行节点 {node.node_id} ({node.name})...")
        nr = worker.execute_node(node, completed_context)
        node_results.append(nr)
        _save_node_result(db, task_id, nr)

        if nr.status == NodeStatus.PASSED:
            completed_context[node.node_id] = nr.generated_code
            _save_output(task_id, node, nr)
            print(f"  ✓ {node.node_id} 通过 ({nr.iteration_count} 轮)")
        else:
            print(f"  ✗ {node.node_id} 失败 ({nr.iteration_count} 轮, 已达上限)")

    passed_count = sum(1 for nr in node_results if nr.status == NodeStatus.PASSED)

    # -- 审核 --
    record.status = TaskStatus.REVIEWING
    _upsert_task(db, record)

    review_passes = False
    for review_round in range(1, 4):
        print(f"[{task_id}] 审核中 (第 {review_round} 轮)...")
        rv = reviewer.review(task_desc, dag, node_results)
        if rv.passed:
            review_passes = True
            print(f"[{task_id}] 审核 PASS")
            break

        print(f"[{task_id}] 审核 FAIL: {rv.suggestions[:200]}")
        # 重新执行失败的节点
        for node in dag.topological_order():
            if node.node_id in rv.failed_nodes:
                print(f"  重做节点 {node.node_id}...")
                nr = worker.execute_node(node, completed_context)
                # 更新结果
                for i, old in enumerate(node_results):
                    if old.node_id == node.node_id:
                        node_results[i] = nr
                        break
                _save_node_result(db, task_id, nr)
                if nr.status == NodeStatus.PASSED:
                    completed_context[node.node_id] = nr.generated_code
                    _save_output(task_id, node, nr)

        passed_count = sum(1 for nr in node_results if nr.status == NodeStatus.PASSED)

    if review_passes:
        record.status = TaskStatus.DONE
        _upsert_task(db, record)

        # 记录 metrics
        entry = MetricsEntry(
            task_id=task_id,
            strong_tokens=record.strong_tokens_used,
            weak_tokens=record.weak_tokens_used,
            node_iterations={nr.node_id: nr.iteration_count for nr in node_results},
            passed_count=passed_count,
            total_count=len(dag.nodes),
        )
        metrics.record(entry)
        metrics.print_summary(entry)
        print(f"[{task_id}] 产物已保存到 outputs/{task_id}/")
    else:
        record.status = TaskStatus.FAILED
        _upsert_task(db, record)
        print(f"[{task_id}] 审核 3 轮未通过, 任务失败")
        sys.exit(1)

    db.close()


# -- CLI --

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="牛马 — AI 任务调度编译器")
    p.add_argument("task_file", nargs="?", help="任务描述文件路径 (.tsk)")
    p.add_argument("--inline", "-i", help="直接输入任务描述（替代文件）")
    return p.parse_args()


def _read_task(args: argparse.Namespace) -> str:
    if args.inline:
        return args.inline
    if args.task_file:
        with open(args.task_file, encoding="utf-8") as f:
            return f.read().strip()
    print("用法: python main.py tasks/example.tsk  或  python main.py --inline '任务描述'")
    sys.exit(1)


# -- SQLite --

def _init_db() -> sqlite3.Connection:
    db = sqlite3.connect("state.sqlite")
    db.execute("PRAGMA journal_mode=WAL")
    db.row_factory = sqlite3.Row
    return db


def _ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            task_description TEXT NOT NULL,
            dag_json TEXT,
            status TEXT DEFAULT 'pending',
            strong_tokens_used INTEGER DEFAULT 0,
            weak_tokens_used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS node_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT REFERENCES tasks(id),
            node_id TEXT NOT NULL,
            iteration_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            generated_code TEXT,
            test_output TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)


def _upsert_task(db: sqlite3.Connection, record: TaskRecord) -> None:
    db.execute(
        """INSERT INTO tasks (id, task_description, dag_json, status, strong_tokens_used, weak_tokens_used, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(id) DO UPDATE SET
             dag_json=excluded.dag_json,
             status=excluded.status,
             strong_tokens_used=excluded.strong_tokens_used,
             weak_tokens_used=excluded.weak_tokens_used,
             updated_at=datetime('now')""",
        (record.id, record.task_description, record.dag_json,
         record.status.value, record.strong_tokens_used, record.weak_tokens_used),
    )
    db.commit()


def _save_node_result(db: sqlite3.Connection, task_id: str, nr: NodeResult) -> None:
    db.execute(
        """INSERT INTO node_results (task_id, node_id, iteration_count, status, generated_code, test_output)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (task_id, nr.node_id, nr.iteration_count, nr.status.value,
         nr.generated_code, nr.test_output),
    )
    db.commit()


def _save_output(task_id: str, node: object, nr: NodeResult) -> None:
    """将通过审核的产物写入 outputs/{task_id}/{node_id}.ts。"""
    ext = "ts" if node.signature.language == "typescript" else "py"  # type: ignore[union-attr]
    out_dir = os.path.join("outputs", task_id)
    os.makedirs(out_dir, exist_ok=True)
    filepath = os.path.join(out_dir, f"{node.node_id}.{ext}")  # type: ignore[union-attr]
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(nr.generated_code)


def _dag_to_json(dag: DAG) -> str:
    import json as _json
    nodes_data = []
    for n in dag.nodes:
        nodes_data.append({
            "node_id": n.node_id,
            "name": n.name,
            "signature": {
                "language": n.signature.language,
                "function_name": n.signature.function_name,
                "params": n.signature.params,
                "return_type": n.signature.return_type,
                "allowed_imports": n.signature.allowed_imports,
                "methods": [
                    {"name": m.name, "params": m.params, "return_type": m.return_type}
                    for m in n.signature.methods
                ],
            },
            "contract": {
                "preconditions": n.contract.preconditions,
                "postconditions": n.contract.postconditions,
                "invariants": n.contract.invariants,
            },
            "test_skeleton": n.test_skeleton,
            "max_iterations": n.max_iterations,
            "dependencies": n.dependencies,
        })
    return _json.dumps({"nodes": nodes_data}, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
