"""编译器 —— 强模型将自然语言任务描述编译为 DAG JSON，含 Schema 校验和重试。"""

import json
import re

import llm
from models import DAG, Contract, DAGNode, FunctionSignature


def compile_task(task_description: str) -> DAG:
    """将任务描述编译为 DAG。强模型调用 → JSON 解析 → Schema 校验 → 重试。"""
    dag_json_str = _call_compiler(task_description)

    for attempt in range(2):
        dag = _parse_dag(dag_json_str)  # noqa: F823
        errors = _validate_dag(dag)
        if not errors:
            return dag
        if attempt < 1:
            dag_json_str = _call_compiler_retry(task_description, dag_json_str, errors)

    raise CompilationError(f"DAG Schema 校验失败（2 次重试后）: {errors}")


def _call_compiler(task_description: str) -> str:
    system = """你是一个任务编译器。将任务描述分解为带类型约束和可自动验证测试的子任务。
输出时必须只输出一个有效的 JSON 对象，内容为 { "nodes": [...] }。
不要输出任何 JSON 之外的内容。
每个节点包含: node_id, name, signature(language/function_name/params/return_type/allowed_imports/methods),
contract(preconditions/postconditions/invariants), test_skeleton, max_iterations(默认10), dependencies(数组)。
约束: language 取 "typescript" 或 "python"；allowed_imports 仅标准库；test_skeleton 是独立可执行的测试代码；最多5个节点。"""

    resp = llm.call_strong(task_description, system=system)
    return resp.content


def _call_compiler_retry(task_description: str, prev_json: str, errors: list[str]) -> str:
    system = f"""你之前产出的 DAG JSON 在校验中失败。请修复以下错误后重新输出。
错误列表:
{chr(10).join(f'- {e}' for e in errors)}

之前输出的 JSON（含错误）:
{prev_json}

请只输出修复后的完整 JSON。"""

    resp = llm.call_strong(task_description, system=system)
    return resp.content


def _parse_dag(raw: str) -> DAG:
    json_str = raw.strip()
    # 去掉 <｜end▁of▁thinking｜>模型的响应可能包含思考过程，需要先提取出纯JSON部分
    # Strip thinking blocks and markdown fences before finding JSON
    # 去掉 <think>...</think> 思考块
    json_str = re.sub(r'<think>[\s\S]*?</think>', '', json_str)
    # 去掉 markdown 代码围栏标记
    json_str = re.sub(r'```(?:json)?\s*', '', json_str)
    json_str = json_str.strip()
    m = re.search(r'\{[\s\S]*\}', json_str)
    if m:
        json_str = m.group(0)
    data = json.loads(json_str)

    nodes = []
    for n in data.get("nodes", []):
        sig_data = n.get("signature", {})
        methods = sig_data.get("methods", [])
        if isinstance(methods, list):
            from models import MethodSignature
            methods = [
                MethodSignature(
                    name=m.get("name", ""),
                    params=m.get("params", []),
                    return_type=m.get("return_type", "void"),
                )
                for m in methods
            ]

        contract_data = n.get("contract", {})
        nodes.append(DAGNode(
            node_id=n["node_id"],
            name=n.get("name", ""),
            signature=FunctionSignature(
                language=sig_data.get("language", "typescript"),
                function_name=sig_data.get("function_name", ""),
                params=sig_data.get("params", []),
                return_type=sig_data.get("return_type", "void"),
                allowed_imports=sig_data.get("allowed_imports", []),
                methods=methods,
            ),
            contract=Contract(
                preconditions=contract_data.get("preconditions", []),
                postconditions=contract_data.get("postconditions", []),
                invariants=contract_data.get("invariants", []),
            ),
            test_skeleton=n.get("test_skeleton", ""),
            max_iterations=n.get("max_iterations", 10),
            dependencies=n.get("dependencies", []),
        ))
    return DAG(nodes=nodes)


def _validate_dag(dag: DAG) -> list[str]:
    errors: list[str] = []
    node_ids = {n.node_id for n in dag.nodes}

    if not dag.nodes:
        errors.append("DAG 必须包含至少 1 个节点")
        return errors

    if len(dag.nodes) > 5:
        errors.append(f"节点数 {len(dag.nodes)} 超过上限 5")

    for node in dag.nodes:
        prefix = f"节点 '{node.node_id}': "
        if not node.node_id:
            errors.append("节点 ID 不能为空")
        if not node.name:
            errors.append(f"{prefix}name 不能为空")
        if not node.signature.function_name:
            errors.append(f"{prefix}signature.function_name 不能为空")
        if not node.test_skeleton:
            errors.append(f"{prefix}test_skeleton 不能为空")
        for dep_id in node.dependencies:
            if dep_id not in node_ids:
                errors.append(f"{prefix}依赖未知节点 '{dep_id}'")

    # 检查循环依赖
    try:
        dag.topological_order()
    except ValueError as e:
        errors.append(str(e))

    return errors


class CompilationError(Exception):
    pass


def commit_dag(dag: DAG, repo_path: str, task_id: str) -> str:
    """将 DAG 序列化为 .niuma/dag.json 并 git commit。返回文件路径。"""
    import json as _json
    from pathlib import Path

    import project_manager as _pm

    dag_data = {
        "task_id": task_id,
        "nodes": []
    }
    for n in dag.nodes:
        dag_data["nodes"].append({
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

    content = _json.dumps(dag_data, indent=2, ensure_ascii=False)
    _pm.commit_file(
        repo_path,
        ".niuma/dag.json",
        content,
        _pm.GIT_AUTHOR_COMPILER,
        f"compiler: DAG for task {task_id} ({len(dag.nodes)} nodes)",
    )
    return str(Path(repo_path) / ".niuma" / "dag.json")
