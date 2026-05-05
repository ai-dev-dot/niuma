"""弱模型执行器 —— 对单个 DAG 节点: 生成代码 → 跑测试 → 修 → 重试。"""

import json
import time

import llm
import sandbox
from models import DAGNode, NodeResult, NodeStatus, SandboxResult


def execute_node(node: DAGNode, completed_context: dict[str, str]) -> NodeResult:
    """在沙箱中执行单个 DAG 节点，弱模型循环修复直到测试通过或超限。"""
    result = NodeResult(node_id=node.node_id)

    for iteration in range(1, node.max_iterations + 1):
        result.iteration_count = iteration

        code = _generate_code(node, completed_context, previous=result)
        if not code.strip():
            result.status = NodeStatus.FAILED
            result.test_output = "弱模型未生成有效代码"
            return result

        result.generated_code = code
        sb_result = sandbox.execute(
            code=code,
            test_code=node.test_skeleton,
            language=node.signature.language,
        )
        result.test_output = sb_result.stdout + "\n" + sb_result.stderr

        if sb_result.passed:
            result.status = NodeStatus.PASSED
            return result

        # 指数退避处理 429
        if "429" in sb_result.stderr or "rate" in sb_result.stderr.lower():
            time.sleep(min(2 ** (iteration - 1), 60))

    result.status = NodeStatus.FAILED
    return result


def _generate_code(node: DAGNode, context: dict[str, str], previous: NodeResult) -> str:
    sig = node.signature
    prompt = f"""实现以下 TypeScript 函数，使其通过所有测试。

签名: function {sig.function_name}({_fmt_params(sig.params)}): {sig.return_type}
{f"方法: {chr(10).join(f'{m.name}({_fmt_params(m.params)}): {m.return_type}' for m in sig.methods)}" if sig.methods else ""}
合约:
  前置条件: {_fmt_list(node.contract.preconditions)}
  后置条件: {_fmt_list(node.contract.postconditions)}
  不变式: {_fmt_list(node.contract.invariants)}"""

    if context:
        prompt += f"\n\n已完成依赖节点的代码:\n"
        for dep_id, dep_code in context.items():
            prompt += f"\n// --- {dep_id} ---\n{dep_code}\n"

    prompt += f"""

测试（你的代码必须通过）:
```typescript
{node.test_skeleton}
```

只输出 TypeScript 代码。不要输出解释或 markdown 标记。"""

    if previous.generated_code and previous.test_output:
        prompt += f"""

上一次生成的代码:
```typescript
{previous.generated_code}
```

上一次测试失败:
{previous.test_output}

请修复以上错误。"""

    resp = llm.call_weak(prompt)
    return _extract_code(resp.content)


def _extract_code(raw: str) -> str:
    """从弱模型响应中提取纯代码（去掉 markdown 标记等）。"""
    text = raw.strip()
    for fence in ["```typescript", "```ts", "```python", "```"]:
        if fence in text:
            parts = text.split(fence, 1)
            if len(parts) > 1:
                inner = parts[1].split("```", 1)[0] if "```" in parts[1] else parts[1]
                return inner.strip()
    # 去掉常见的前缀废话
    for prefix in ["好的，", "以下是", "这是", "Here is", "Here's"]:
        if text.startswith(prefix):
            lines = text.split("\n", 1)
            if len(lines) > 1:
                return lines[1].strip()
    return text


def _fmt_params(params: list[dict[str, str]]) -> str:
    return ", ".join(f"{p['name']}: {p['type']}" for p in params)


def _fmt_list(items: list[str]) -> str:
    if not items:
        return "(无)"
    return "; ".join(items)


def commit_node(node: DAGNode, result: NodeResult, repo_path: str) -> str:
    """将通过测试的节点代码 git commit 到仓库。返回文件路径。"""
    import project_manager as _pm

    ext = "ts" if node.signature.language == "typescript" else "py"
    filepath = f"src/{node.node_id}.{ext}"

    _pm.commit_file(
        repo_path,
        filepath,
        result.generated_code,
        _pm.GIT_AUTHOR_WORKER,
        f"worker: implement {node.node_id} ({result.iteration_count} iterations)",
    )
    return filepath
