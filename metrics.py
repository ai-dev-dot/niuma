"""数据记录 —— 输出 JSONL 格式的 metrics 到 outputs/ 目录。"""

import json
import os
from datetime import datetime, timezone

from models import MetricsEntry


def record(entry: MetricsEntry, output_dir: str = "outputs") -> str:
    """追加一行 JSONL 到 outputs/metrics.jsonl。返回文件路径。"""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "metrics.jsonl")

    entry.timestamp = datetime.now(timezone.utc).isoformat()
    line = json.dumps({
        "task_id": entry.task_id,
        "strong_tokens": entry.strong_tokens,
        "weak_tokens": entry.weak_tokens,
        "node_iterations": entry.node_iterations,
        "passed_count": entry.passed_count,
        "total_count": entry.total_count,
        "timestamp": entry.timestamp,
    }, ensure_ascii=False)

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    return filepath


def print_summary(entry: MetricsEntry) -> None:
    """打印人类可读的汇总。"""
    print(f"\n{'='*50}")
    print(f"任务 {entry.task_id} 完成")
    print(f"  强模型 token: {entry.strong_tokens}")
    print(f"  弱模型 token: {entry.weak_tokens}")
    print(f"  Token 比 (弱/强): {entry.weak_tokens / max(entry.strong_tokens, 1):.1f}x")
    print(f"  通过节点: {entry.passed_count}/{entry.total_count}")
    for nid, iters in sorted(entry.node_iterations.items()):
        print(f"    节点 {nid}: {iters} 轮迭代")
    print(f"{'='*50}\n")
