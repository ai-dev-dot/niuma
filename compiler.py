"""编译器 —— 强模型将自然语言任务描述编译为 DAG JSON，含 Schema 校验和重试。"""

import json
import re

import llm
from models import DAG, Contract, DAGNode, FunctionSignature


def compile_task(task_description: str, verbose: bool = False) -> DAG:
    """将任务描述编译为 DAG。强模型调用 → JSON 解析 → Schema 校验 → 重试。"""
    if verbose:
        print("  [强模型] 正在分析任务并分解为 DAG...")

    dag_json_str = _call_compiler(task_description)

    for attempt in range(2):
        dag = _parse_dag(dag_json_str)
        errors = _validate_dag(dag)
        if not errors:
            if verbose:
                print(f"  [强模型] DAG 编译完成: {len(dag.nodes)} 个节点")
                for i, node in enumerate(dag.nodes, 1):
                    deps = f" (依赖: {', '.join(str(d) for d in node.dependencies)})" if node.dependencies else ""
                    print(f"    节点{i}: {node.node_id} — {node.name}{deps}")
                    print(f"      语言: {node.signature.language}, 最多{node.max_iterations}轮迭代")
            return dag
        if attempt < 1:
            dag_json_str = _call_compiler_retry(task_description, dag_json_str, errors)

    raise CompilationError(f"DAG Schema 校验失败（2 次重试后）: {errors}")


def _call_compiler(task_description: str) -> str:
    system = """你是一个任务编译器。将任务描述分解为带类型约束和可自动验证测试的子任务。

输出时必须只输出一个有效的 JSON 对象，不要加任何解释或 markdown 标记。
JSON 格式: { "nodes": [...] }

每个节点字段（全部必填）:
- node_id: 字符串，唯一标识
- name: 字符串，节点描述
- signature: { language, function_name, params, return_type, allowed_imports, methods }
  - params 格式: [{"name": "参数名", "type": "类型"}, ...]
  - methods 格式: [{"name": "方法名", "params": [...], "return_type": "类型"}, ...]
- contract: { preconditions, postconditions, invariants } 每个都是字符串数组
- test_skeleton: 字符串，独立可执行的测试代码
- max_iterations: 整数，默认10
- dependencies: 字符串数组，依赖的 node_id 列表

约束: language="typescript" 或 "python"；allowed_imports 仅标准库；最多5个节点。

=== 示例（任务: "实现一个计数器，支持增减和重置"） ===

{"nodes": [
  {
    "node_id": "counter_core",
    "name": "计数器核心逻辑",
    "signature": {
      "language": "typescript",
      "function_name": "createCounter",
      "params": [{"name": "initialValue", "type": "number"}],
      "return_type": "object",
      "methods": [
        {"name": "increment", "params": [], "return_type": "number"},
        {"name": "decrement", "params": [], "return_type": "number"},
        {"name": "reset", "params": [], "return_type": "void"}
      ],
      "allowed_imports": []
    },
    "contract": {
      "preconditions": ["initialValue 必须是整数"],
      "postconditions": ["increment 返回当前值+1", "decrement 返回当前值-1", "reset 将值恢复为 initialValue"],
      "invariants": ["计数值始终为整数"]
    },
    "test_skeleton": "test('counter', () => { const c = createCounter(0); expect(c.increment()).toBe(1); expect(c.decrement()).toBe(0); c.reset(); expect(c.increment()).toBe(1); });",
    "max_iterations": 10,
    "dependencies": []
  }
]}"""

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
    """解析模型返回的 JSON。具备多层容错：去掉思考块/markdown、类型强制、格式兼容。"""
    json_str = raw.strip()
    json_str = re.sub(r'<think>[\s\S]*?</think>', '', json_str)
    json_str = re.sub(r'```(?:json)?\s*', '', json_str)
    json_str = json_str.strip()
    m = re.search(r'\{[\s\S]*\}', json_str)
    if m:
        json_str = m.group(0)
    data = json.loads(json_str)

    from models import MethodSignature

    nodes = []
    for n in data.get("nodes", []):
        sig_data = n.get("signature", {})
        contract_data = n.get("contract", {})

        # 容错：methods 支持 dict 和 string 两种格式
        methods_raw = sig_data.get("methods", [])
        methods: list[MethodSignature] = []
        if isinstance(methods_raw, list):
            for m in methods_raw:
                if isinstance(m, dict):
                    methods.append(MethodSignature(
                        name=str(m.get("name", "")),
                        params=_safe_list(m.get("params", [])),
                        return_type=str(m.get("return_type", "void")),
                    ))
                elif isinstance(m, str):
                    try:
                        name_part = m.split("(")[0].strip()
                        return_type = m.split("):")[1].strip() if "):" in m else "void"
                        methods.append(MethodSignature(name=name_part, params=[], return_type=return_type))
                    except (IndexError, ValueError):
                        pass

        # 容错：test_skeleton 可能为非字符串
        tsk = n.get("test_skeleton", "")
        if isinstance(tsk, list):
            tsk = "\n".join(str(x) for x in tsk)
        elif not isinstance(tsk, str):
            tsk = str(tsk)

        nodes.append(DAGNode(
            node_id=str(n.get("node_id", "")),
            name=str(n.get("name", "")),
            signature=FunctionSignature(
                language=str(sig_data.get("language", "typescript")),
                function_name=str(sig_data.get("function_name", "")),
                params=_safe_list(sig_data.get("params", [])),
                return_type=str(sig_data.get("return_type", "void")),
                allowed_imports=_safe_list(sig_data.get("allowed_imports", [])),
                methods=methods,
            ),
            contract=Contract(
                preconditions=_safe_list(contract_data.get("preconditions", [])),
                postconditions=_safe_list(contract_data.get("postconditions", [])),
                invariants=_safe_list(contract_data.get("invariants", [])),
            ),
            test_skeleton=tsk,
            max_iterations=int(n.get("max_iterations", 10)),
            dependencies=[str(d) for d in _safe_list(n.get("dependencies", []))],
        ))
    return DAG(nodes=nodes)


def _safe_list(val) -> list:
    """确保值是一个 list；None → 空列表，非列表 → 包裹为单元素列表。"""
    if isinstance(val, list):
        return val
    if val is None:
        return []
    return [val]


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
