"""审核器 —— 强模型审查所有节点产物，判断 pass/fail 并给出修改建议。"""

from pathlib import Path

import llm
from models import DAG, NodeResult, ReviewResult
import config as _cfg


def review(task_description: str, dag: DAG, node_results: list[NodeResult], verbose: bool = False) -> ReviewResult:
    """强模型审核所有节点输出。返回 PASS 或 FAIL + 具体建议。"""
    if verbose:
        passed = sum(1 for nr in node_results if nr.status.value == "passed")
        total = len(node_results)
        print(f"  [强模型] 开始审核 {total} 个节点 (通过: {passed})...")

    prompt = _build_review_prompt(task_description, dag, node_results)
    resp = llm.call_strong(prompt)
    rv = _parse_review(resp.content, node_results)

    if verbose:
        G = "\033[32m"; R = "\033[31m"; X = "\033[0m"
        if rv.passed:
            print(f"  [强模型] 审核结论: {G}PASS{X} — 所有合约满足")
        else:
            print(f"  [强模型] 审核结论: {R}FAIL{X} — {len(rv.failed_nodes)} 个节点需修复")
            if rv.suggestions:
                print(f"    建议: {rv.suggestions[:200]}")

    return rv


def _collect_node_results(repo_path: str, dag: "DAG") -> list["NodeResult"]:
    """从文件系统收集所有节点的执行结果。"""
    from models import NodeResult, NodeStatus

    results = []
    for node in dag.nodes:
        ext = "ts" if node.signature.language == "typescript" else "py"
        code_file = Path(repo_path) / "src" / f"{node.node_id}.{ext}"

        nr = NodeResult(node_id=node.node_id)
        if code_file.exists():
            nr.status = NodeStatus.PASSED
            nr.generated_code = code_file.read_text(encoding="utf-8")
            nr.iteration_count = 1  # 从文件系统无法得知具体迭代数
        else:
            nr.status = NodeStatus.FAILED
            nr.test_output = "文件不存在 | file not found"
        results.append(nr)
    return results


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

你必须只输出一个 JSON 对象，不要加任何解释或 markdown 标记：

{{"verdict": "PASS", "score": 8, "summary": "一句话总结"}}
或者
{{"verdict": "FAIL", "score": 3, "failed_nodes": ["<节点ID>", ...], "suggestions": "<违规描述>", "summary": "一句话总结"}}

score 是 1-10 整体质量评分。summary 是一句话（20字内）。"""


def _parse_review(raw: str, node_results: list[NodeResult]) -> ReviewResult:
    import json as _json
    import re as _re
    text = raw.strip()
    text = _re.sub(r'<think>[\s\S]*?</think>', '', text)
    text = _re.sub(r'```(?:json)?\s*', '', text)
    text = text.strip()

    # 优先尝试 JSON 解析
    m = _re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            data = _json.loads(m.group(0))
            verdict = data.get("verdict", "").upper()
            return ReviewResult(
                passed=verdict == "PASS",
                failed_nodes=data.get("failed_nodes", []),
                suggestions=data.get("suggestions", ""),
                score=data.get("score", 0),
                summary=data.get("summary", ""),
            )
        except (_json.JSONDecodeError, KeyError):
            pass

    # 容错：旧格式文本解析
    is_pass = "PASS" in text.upper().split("\n")[0] if text else False
    has_fail = bool(_re.search(r'\bFAIL\b', text, _re.IGNORECASE))
    has_pass = bool(_re.search(r'\bPASS\b', text, _re.IGNORECASE))
    if not is_pass:
        is_pass = has_pass and not has_fail

    failed_nodes: list[str] = []
    if not is_pass:
        all_ids = {nr.node_id for nr in node_results}
        for line in text.split("\n"):
            for nid in all_ids:
                if nid in line:
                    failed_nodes.append(nid)

    return ReviewResult(
        passed=is_pass,
        failed_nodes=list(set(failed_nodes)) if failed_nodes else [],
        suggestions=text,
    )


def commit_review(result: ReviewResult, repo_path: str, task_id: str, task_desc: str = "") -> str:
    """将审核结论写入 .niuma/review.md 并 git commit。返回文件路径。"""
    import project_manager as _pm

    status = "PASS" if result.passed else "FAIL"
    score_str = f" [{result.score}/10]" if result.score > 0 else ""
    content = f"# Review: {task_id}\n\n**Verdict:** {status}{score_str}\n\n"
    if result.summary:
        content += f"**Summary:** {result.summary}\n\n"
    if result.suggestions:
        content += f"{result.suggestions}\n\n"
    if not result.passed:
        content += f"## Failed Nodes\n\n"
        for nid in result.failed_nodes:
            content += f"- {nid}\n"

    _pm.commit_file(
        repo_path,
        ".niuma/review.md",
        content,
        _pm.GIT_AUTHOR_REVIEWER,
        _pm.msg_review(result.passed, result.score, result.summary),
    )
    return str(Path(repo_path) / ".niuma" / "review.md")


def review_from_git(repo_path: str, task_id: str, verbose: bool = False) -> "ReviewResult":
    """从 git 读取所有节点产物，审核，commit review.md。"""
    import json as _json
    from compiler import _parse_dag

    dag_file = Path(repo_path) / ".niuma" / "dag.json"
    if not dag_file.exists():
        raise FileNotFoundError(f"dag.json 不存在: {dag_file}")

    dag = _parse_dag(_json.dumps(_json.loads(dag_file.read_text(encoding="utf-8"))))

    # 读取 requirement.md 作为 task_description
    req_file = Path(repo_path) / ".niuma" / "requirement.md"
    task_desc = req_file.read_text(encoding="utf-8") if req_file.exists() else ""

    # 从文件系统收集节点结果
    node_results = _collect_node_results(repo_path, dag)

    return review(task_desc, dag, node_results, verbose=verbose)
