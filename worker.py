"""弱模型执行器 —— 对单个 DAG 节点: 生成代码 → 跑测试 → 修 → 重试。"""

import json
import time

import config as _cfg
from pathlib import Path

import llm
import sandbox
from models import DAGNode, NodeResult, NodeStatus, SandboxResult


def execute_node(node: DAGNode, completed_context: dict[str, str], task_id: str = "", review_feedback: str = "", verbose: bool = False) -> NodeResult:
    """在沙箱中执行单个 DAG 节点，弱模型循环修复直到测试通过或超限。
    review_feedback: 审核器返回的修改建议，会注入到首次迭代的 prompt 中。"""
    result = NodeResult(node_id=node.node_id)

    if verbose:
        feedback_note = " (含审核反馈)" if review_feedback else ""
        print(f"  [弱模型] 开始执行节点: {node.node_id} — {node.name}{feedback_note}")

    for iteration in range(1, node.max_iterations + 1):
        result.iteration_count = iteration

        llm.set_meta({"role": "worker", "task_id": task_id, "node_id": node.node_id, "iteration": iteration})
        code = _generate_and_extract(node, completed_context, previous=result, review_feedback=review_feedback, verbose=verbose)
        _log_extraction(code, node.signature.language, iteration)

        if not code.strip():
            result.status = NodeStatus.FAILED
            result.test_output = "弱模型未生成有效代码（多次尝试后仍无法提取）"
            if verbose:
                print(f"    第{iteration}轮: 模型未返回有效代码，节点失败")
            return result

        # 编译检查：用沙箱验证代码语法
        if verbose:
            print(f"    [弱模型] 编译检查...")
        if not _compile_check(code, node.signature.language, verbose=verbose):
            result.test_output = "编译检查不通过（语法错误或无法编译）"
            if verbose:
                print(f"    第{iteration}轮: 编译未通过，重新生成...")
            review_feedback = f"你的代码编译未通过。请检查是否有语法错误、缺少函数体、类型不匹配等问题。"
            continue

        result.generated_code = code
        # 构建依赖文件：已完成的节点代码作为独立文件，供 import 使用
        ext = "py" if node.signature.language == "python" else "ts"
        ctx_files: dict[str, str] = {}
        if completed_context:
            for dep_id, dep_code in completed_context.items():
                ctx_files[f"{dep_id}.{ext}"] = dep_code
        sb_result = sandbox.execute(
            code=code,
            test_code=node.test_skeleton,
            language=node.signature.language,
            context_files=ctx_files if ctx_files else None,
        )
        result.test_output = sb_result.stdout + "\n" + sb_result.stderr

        _log_sandbox(code, sb_result, node.signature.language, iteration)

        if verbose:
            status = "PASS" if sb_result.passed else "FAIL"
            code_preview = code[:80].replace('\n', ' ').strip()
            err_preview = sb_result.stderr[:100].replace('\n', ' ').strip() if not sb_result.passed else ""
            print(f"    第{iteration}轮: [{status}] {code_preview}...")
            if err_preview:
                print(f"      错误: {err_preview}")

        if sb_result.passed:
            result.status = NodeStatus.PASSED
            if verbose:
                print(f"    [OK] {node.node_id} 通过 ({iteration} 轮迭代)")
            return result

        # 指数退避处理 429
        if "429" in sb_result.stderr or "rate" in sb_result.stderr.lower():
            time.sleep(min(2 ** (iteration - 1), 60))

    result.status = NodeStatus.FAILED
    if verbose:
        print(f"    [FAIL] {node.node_id} 失败 ({node.max_iterations} 轮迭代后未通过)")
    return result


def _log_extraction(code: str, lang: str, iteration: int) -> None:
    llm.write_process_record({
        "stage": "extraction",
        "iteration": iteration,
        "lang": lang,
        "code_length": len(code),
        "code_preview": code[:200],
        "extraction_ok": bool(code.strip()),
    })


def _log_sandbox(code: str, sb_result: SandboxResult, lang: str, iteration: int) -> None:
    llm.write_process_record({
        "stage": "sandbox",
        "iteration": iteration,
        "lang": lang,
        "code": code,
        "test_stdout": sb_result.stdout[:4000] if sb_result.stdout else "",
        "test_stderr": sb_result.stderr[:4000] if sb_result.stderr else "",
        "test_passed": sb_result.passed,
    })


def _generate_and_extract(node: DAGNode, context: dict[str, str], previous: NodeResult, review_feedback: str = "", verbose: bool = False) -> str:
    """生成代码并提取。如果提取结果不像代码，让弱模型重新输出（最多2次）。"""
    lang = node.signature.language
    code_fence = "python" if lang == "python" else "typescript"

    limits = _cfg.get_retry_limits()
    max_tries = limits["worker_code_extraction"]
    for retry in range(max_tries):
        resp = _call_weak_model(node, context, previous, review_feedback)
        code = _extract_code(resp.content)

        if _looks_like_code(code, lang):
            return code

        if verbose and retry > 0:
            print(f"    [弱模型] 第{retry}次提取失败，重新请求...")
        if retry < max_tries - 1:
            review_feedback = (
                f"你上一次的回复格式不正确——包含了太多解释文字，或者代码没有正确包裹在 "
                f"```{code_fence} 代码块中。\n"
                f"请重新输出：只输出一个 ```{code_fence} 代码块，里面放完整代码。"
            )
            previous = NodeResult(node_id=node.node_id)

    return ""


def _call_weak_model(node: DAGNode, context: dict[str, str], previous: NodeResult, review_feedback: str = "") -> llm.LLMResponse:
    """构造 prompt 并调用弱模型。"""
    sig = node.signature
    lang = sig.language
    comment = "#" if lang == "python" else "//"
    func_kw = "def" if lang == "python" else "function"
    code_fence = "python" if lang == "python" else "typescript"

    prompt = f"""你是一个{lang.upper()}程序员。请实现以下函数并通过所有测试。

函数签名: {func_kw} {sig.function_name}({_fmt_params(sig.params)}){': ' + sig.return_type if lang == 'typescript' else ''}
{f"需要实现的方法: {chr(10).join(f'  - {m.name}({_fmt_params(m.params)}): {m.return_type}' for m in sig.methods)}" if sig.methods else ""}

行为要求:
  前置条件: {_fmt_list(node.contract.preconditions)}
  后置条件: {_fmt_list(node.contract.postconditions)}
  不变式: {_fmt_list(node.contract.invariants)}"""

    if context:
        prompt += f"\n\n依赖节点的代码（你可以直接使用）:\n"
        for dep_id, dep_code in context.items():
            prompt += f"\n{comment} --- {dep_id} ---\n{dep_code}\n"

    if review_feedback:
        prompt += f"\n\n注意: {review_feedback}"

    prompt += f"""

你必须通过的测试:
```{code_fence}
{node.test_skeleton}
```

请把你的{lang.upper()}代码放在一个 ```{code_fence} 代码块中输出。代码块之外不要写任何文字。"""

    if previous.generated_code and previous.test_output:
        err_short = previous.test_output
        if len(err_short) > 2000:
            err_short = err_short[:1000] + "\n...(省略)...\n" + err_short[-1000:]
        code_short = previous.generated_code
        if len(code_short) > 3000:
            code_short = code_short[:1500] + f"\n{comment} ...(省略)...\n" + code_short[-1500:]

        prompt += f"""

你上一次的代码:
```{code_fence}
{code_short}
```

测试报错:
{err_short}

请修复以上错误并重新输出。"""

    return llm.call_weak(prompt, system=f"你是一个{lang.upper()}程序员。只输出一个 ```{code_fence} 代码块，不要写解释、注释或思考过程。代码块之外不要写任何文字。")


def _compile_check(code: str, lang: str, verbose: bool = False) -> bool:
    """用 compile() 或 tsc 验证代码语法，不消耗 API token。"""
    if lang == "python":
        try:
            compile(code, "<worker>", "exec")
            return True
        except SyntaxError:
            return False
    elif lang == "typescript":
        result = sandbox.execute(
            code=code,
            test_code="",
            language="typescript",
        )
        return result.exit_code == 0
    return True


def _extract_code(raw: str) -> str:
    """从弱模型响应中提取纯代码（去掉 think 块、markdown 标记等）。"""
    import re as _re
    text = raw.strip()
    text = _re.sub(r'<think>[\s\S]*?</think>', '', text)

    for fence in ["```typescript", "```ts", "```python", "```"]:
        if fence in text:
            parts = text.split(fence, 1)
            if len(parts) > 1:
                inner = parts[1].split("```", 1)[0] if "```" in parts[1] else parts[1]
                return inner.strip()

    for prefix in ["好的，", "以下是", "这是", "Here is", "Here's", "The user", "Let me", "I need", "I'll", "First", "We need"]:
        if text.lower().startswith(prefix.lower()):
            lines = text.split("\n", 1)
            if len(lines) > 1:
                return lines[1].strip()
    return text


def _looks_like_code(text: str, lang: str = "typescript") -> bool:
    """判断提取的文本是否像代码。"""
    if not text or len(text) < 10:
        return False
    indicators = ["function ", "class ", "def ", "export ", "const ", "let ", "var ", "import ", "return", "if ", "for ", "while ", "async ", "interface ", "type ", "enum ", "=>", "{", "}"]
    if lang == "python":
        indicators = ["def ", "class ", "import ", "return", "if ", "for ", "while ", "async def", "lambda", "="]
    return any(kw in text for kw in indicators)


def _fmt_params(params: list) -> str:
    """格式化参数列表。兼容对象格式 [{name, type}] 和字符串格式 ['name: type']。"""
    result: list[str] = []
    for p in params:
        if isinstance(p, dict):
            result.append(f"{p['name']}: {p['type']}")
        elif isinstance(p, str):
            result.append(p)
    return ", ".join(result)


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
