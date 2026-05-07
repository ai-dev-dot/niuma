"""编译器 —— 强模型将自然语言任务描述编译为 DAG JSON，含 Schema 校验和重试。"""

import json
import re

import config as _cfg
from pathlib import Path

import llm
from models import DAG, Contract, DAGNode, FunctionSignature


CLARIFY_SYSTEM = """你是一个需求分析器。用户描述了想做的功能。你的任务是帮他把需求澄清到足够编译的程度。

规则：
- 每次只问一个最关键的问题。不要一次问多个。
- 如果用户表示"够了"、"开始吧"、"不用再问了"之类的意图，不要再追问，直接输出需求摘要。
- 如果需求已经足够清晰，直接输出需求摘要。

输出格式（严格的 JSON，不要加任何其他文字）：
- 如果还有疑问：{"type": "question", "question": "你的问题"}
- 如果已清晰：{"type": "summary", "summary": "结构化需求描述..."}

问题应该聚焦在：功能边界、数据类型、约束条件、使用场景。"""


def clarify_step(history: list[dict]) -> dict:
    """调用强模型，根据对话历史返回下一步: {"type": "question", "question": "..."}
    或 {"type": "summary", "summary": "..."}。"""
    messages = [{"role": "system", "content": CLARIFY_SYSTEM}]
    for entry in history:
        role = entry["role"]
        content = entry["content"]
        messages.append({"role": role, "content": content})

    resp = llm.call_strong_messages(messages, max_tokens=0)

    # 解析 JSON 响应
    text = resp.content.strip()
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = text.strip()
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        text = m.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 容错：如果模型返回的不是纯 JSON
        if any(kw in text for kw in ["确认", "摘要", "总结", "SUMMARY", "summary"]):
            return {"type": "summary", "summary": text}
        return {"type": "question", "question": text.strip().split("\n")[0]}


def compile_task(task_description: str, verbose: bool = False) -> DAG:
    """将任务描述编译为 DAG。强模型调用 -> JSON 解析 -> Schema 校验 -> 重试。"""
    limits = _cfg.get_retry_limits()
    max_tries = limits["compiler_schema_validation"]

    if verbose:
        print("  [强模型] 正在分析任务并分解为 DAG...")

    dag_json_str = _call_compiler(task_description)

    for attempt in range(max_tries):
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
        if attempt < max_tries - 1:
            dag_json_str = _call_compiler_retry(task_description, dag_json_str, errors)

    raise CompilationError(f"DAG Schema 校验失败（{max_tries} 次重试后）: {errors}")


def compile_from_git(repo_path: str, task_id: str, verbose: bool = False) -> DAG:
    """从 git 读取 requirement.md，编译为 DAG，commit dag.json 到 git。"""
    req_path = Path(repo_path) / ".niuma" / "requirement.md"
    if not req_path.exists():
        raise FileNotFoundError(f"requirement.md 不存在: {req_path}")

    requirement = req_path.read_text(encoding="utf-8")
    return compile_task(requirement, verbose=verbose)


def _call_compiler(task_description: str) -> str:
    max_nodes = _cfg.get_retry_limits().get("max_nodes", 8)
    system = """你是一个任务编译器。将复杂任务分解为多个小的、独立的子任务。
分解原则：每个节点聚焦一个关注点（如数据结构、调度逻辑、对外接口），但不必过度拆分——
一个节点可以包含2-4个紧密相关的方法。**关键是把不同性质的职责分开**（比如数据存储和定时调度不要混在同一个节点）。

输出时必须只输出一个有效的 JSON 对象，不要加任何解释或 markdown 标记。
JSON 格式: { "nodes": [...] }

每个节点字段（全部必填）:
- node_id: 字符串，唯一标识
- name: 字符串，节点描述
- signature: { language, function_name, params, return_type, allowed_imports, methods }
  - params 格式: [{"name": "参数名", "type": "类型"}, ...]
  - methods 格式: [{"name": "方法名", "params": [...], "return_type": "类型"}, ...]
- contract: { preconditions, postconditions, invariants } 每个都是字符串数组
- test_skeleton: 字符串，独立可执行的测试代码。沙箱会将每个节点（包括本节点和依赖节点）的代码作为独立源文件放在同一目录下，文件名为 `{node_id}.{ext}`。因此测试代码可以通过目标语言的模块系统引用这些节点。测试框架会按命名约定自动发现并执行测试。
- max_iterations: 整数，默认5
- dependencies: 字符串数组，依赖的 node_id 列表

约束:
- language="typescript" 或 "python"；allowed_imports 仅标准库；最多__MAX_NODES__个节点
- **不同性质的职责要分开**（数据存储、调度逻辑、对外接口各自成节点）
- **test_skeleton 只能引用本节点或已声明的依赖节点**（沙箱中只有这些源文件）
- 2节点示例只是一个参考模式。简单任务可以单节点，复杂任务合理拆分

=== 示例：2节点分解（任务: "实现一个栈，支持 push/pop/peek/size"） ===

{"nodes": [
  {
    "node_id": "stack_store",
    "name": "栈数据容器",
    "signature": {
      "language": "typescript",
      "function_name": "createStackStore",
      "params": [],
      "return_type": "object",
      "methods": [
        {"name": "push", "params": [{"name": "item", "type": "any"}], "return_type": "void"},
        {"name": "pop", "params": [], "return_type": "any"}
      ],
      "allowed_imports": []
    },
    "contract": {
      "preconditions": [],
      "postconditions": ["push 将元素加入栈顶", "pop 移除并返回栈顶元素，空栈返回 undefined"],
      "invariants": ["内部数组保持 LIFO 顺序"]
    },
    "test_skeleton": "test('push and pop', () => { const s = createStackStore(); s.push(1); s.push(2); expect(s.pop()).toBe(2); expect(s.pop()).toBe(1); expect(s.pop()).toBeUndefined(); });",
    "max_iterations": 10,
    "dependencies": []
  },
  {
    "node_id": "stack_helpers",
    "name": "栈辅助方法",
    "signature": {
      "language": "typescript",
      "function_name": "addStackHelpers",
      "params": [{"name": "store", "type": "object"}],
      "return_type": "object",
      "methods": [
        {"name": "peek", "params": [], "return_type": "any"},
        {"name": "size", "params": [], "return_type": "number"}
      ],
      "allowed_imports": []
    },
    "contract": {
      "preconditions": ["store 必须包含 push 和 pop 方法"],
      "postconditions": ["peek 返回栈顶元素但不移除", "size 返回栈中元素数量"],
      "invariants": ["peek 和 size 不修改栈内容"]
    },
    "test_skeleton": "test('peek and size', () => { const store = createStackStore(); const s = addStackHelpers(store); s.push('a'); expect(s.size()).toBe(1); expect(s.peek()).toBe('a'); expect(s.size()).toBe(1); });",
    "max_iterations": 10,
    "dependencies": ["stack_store"]
  }
]}"""

    system = system.replace("__MAX_NODES__", str(max_nodes))
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
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # 截取错误位置前后的内容帮助调试
        pos = e.pos
        snippet = json_str[max(0, pos - 100):pos + 100]
        raise CompilationError(
            f"JSON 解析失败: {e.msg} (第{e.lineno}行, 第{e.colno}列)\n"
            f"错误位置附近: ...{snippet}..."
        )

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

    max_nodes = _cfg.get_retry_limits().get("max_nodes", 8)
    if len(dag.nodes) > max_nodes:
        errors.append(f"节点数 {len(dag.nodes)} 超过上限 {max_nodes}")

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

        # 校验 test_skeleton 中引用的节点 ID：只能引用自己或已声明的依赖
        valid_modules = {node.node_id} | set(node.dependencies)
        for other_id in node_ids:
            if other_id not in valid_modules and other_id in node.test_skeleton:
                errors.append(
                    f"{prefix}test_skeleton 引用了未声明的节点 '{other_id}'——"
                    f"可以引用: 本节点 ({node.node_id}) 或依赖 ({', '.join(node.dependencies) or '无'})"
                )

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
        _pm.msg_compiler(len(dag.nodes)),
    )
    return str(Path(repo_path) / ".niuma" / "dag.json")
