"""审核器 —— 强模型审查所有节点产物，判断 pass/fail 并给出修改建议。"""

from pathlib import Path

import llm
from models import DAG, NodeResult, ReviewResult


def review(task_description: str, dag: DAG, node_results: list[NodeResult], verbose: bool = False) -> ReviewResult:
    """强模型审核所有节点输出。返回 PASS 或 FAIL + 具体建议。"""
    if verbose:
        passed = sum(1 for nr in node_results if nr.status.value == "passed")
        total = len(node_results)
        print(f"  [强模型] 开始审核 {total} 个节点 (通过: {passed})...")

    prompt = _build_review_prompt(task_description, dag, node_results)
    resp = llm.call_strong(prompt, max_tokens=1500)
    rv = _parse_review(resp.content, node_results)

    if verbose:
        if rv.passed:
            print(f"  [强模型] 审核结论: PASS — 所有合约满足")
        else:
            print(f"  [强模型] 审核结论: FAIL — {len(rv.failed_nodes)} 个节点需修复")
            if rv.suggestions:
                print(f"    建议: {rv.suggestions[:200]}")

    return rv


def _build_review_prompt(task_description: str, dag: DAG, node_results: list[NodeResult]) -> str:
    nodes_text = ""
    for nr in node_results:
        nodes_text += f"\n--- 节点: {nr.node_id} (状态: {nr.status.value}, 迭代: {nr.iteration_count}) ---\n"
        nodes_text += f"代码:\n```\n{nr.generated_code}\n```\n"
        nodes_text += f"测试输出:\n{nr.test_output}\n"

    dag_text = "\n".join(
        f"- {n.node_id}: {n.name} (依赖: {n.dependencies or '无'})"
        for n in dag.nodes
    )

    return f"""审查所有节点的代码是否满足原始任务和合约规范。

原始任务: {task_description}

DAG 结构:
{dag_text}

各节点输出:
{nodes_text}

审查范围: 合约合规性、签名匹配、节点间数据流连贯性。
不要审查: 代码风格、性能优化、文档。

输出:
- 如果所有节点满足要求: PASS
- 如果有问题: FAIL: <节点ID> — <合约违规描述> — <修改建议>"""


def _parse_review(raw: str, node_results: list[NodeResult]) -> ReviewResult:
    import re
    text = raw.strip()
    # 去掉模型的思考过程和 markdown 标记
    text = re.sub(r'<think>[\s\S]*?</think>', '', text)
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = text.strip()
    # 在全文搜索 PASS/FAIL（不仅仅行首）
    is_pass = "PASS" in text.upper().split("\n")[0] if text else False
    if not is_pass and text.upper().startswith("PASS"):
        is_pass = True
    # 更宽松的判断：如果包含 PASS 且不包含 FAIL，认为是 PASS
    if not is_pass:
        has_fail = bool(re.search(r'\bFAIL\b', text, re.IGNORECASE))
        has_pass = bool(re.search(r'\bPASS\b', text, re.IGNORECASE))
        is_pass = has_pass and not has_fail

    failed_nodes: list[str] = []
    if not is_pass:
        # 提取被提及的节点 ID
        all_ids = {nr.node_id for nr in node_results}
        for line in text.split("\n"):
            for nid in all_ids:
                if nid in line:
                    failed_nodes.append(nid)

    return ReviewResult(
        passed=is_pass,
        failed_nodes=list(set(failed_nodes)) if failed_nodes else [],
        suggestions=text if not is_pass else "",
    )


def commit_review(result: ReviewResult, repo_path: str, task_id: str) -> str:
    """将审核结论写入 .niuma/review.md 并 git commit。返回文件路径。"""
    import project_manager as _pm

    status = "PASS" if result.passed else "FAIL"
    content = f"# Review: {task_id}\n\n**Verdict:** {status}\n\n"
    if not result.passed:
        content += f"## Failed Nodes\n\n"
        for nid in result.failed_nodes:
            content += f"- {nid}\n"
        content += f"\n## Suggestions\n\n{result.suggestions}\n"

    _pm.commit_file(
        repo_path,
        ".niuma/review.md",
        content,
        _pm.GIT_AUTHOR_REVIEWER,
        f"reviewer: {status} for task {task_id}",
    )
    return str(Path(repo_path) / ".niuma" / "review.md")
