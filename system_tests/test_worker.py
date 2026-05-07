"""worker.py 执行器测试。"""

from unittest.mock import patch

import pytest
import worker
from models import Contract, DAGNode, FunctionSignature, NodeStatus
import llm
import sandbox


def _make_node(**kwargs) -> DAGNode:
    defaults = dict(
        node_id="test_node",
        name="测试节点",
        signature=FunctionSignature(
            language="python",
            function_name="add",
            params=[{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
            return_type="int",
        ),
        contract=Contract(
            preconditions=["a, b 为整数"],
            postconditions=["返回 a+b"],
        ),
        test_skeleton="def test_add():\n    assert add(1, 2) == 3",
        max_iterations=5,
    )
    defaults.update(kwargs)
    return DAGNode(**defaults)

# shared: test failure
_TEST_FAIL = sandbox.SandboxResult(exit_code=1, stdout="", stderr="AssertionError")
_TEST_PASS = sandbox.SandboxResult(exit_code=0, stdout=".", stderr="")


class TestWorker:
    def test_pass_on_first_try(self):
        with patch.object(llm, "call_weak") as mock_llm, patch.object(sandbox, "execute") as mock_sandbox:
            mock_llm.return_value = llm.LLMResponse(content="def add(a, b): return a + b", input_tokens=100, output_tokens=30)
            mock_sandbox.return_value = _TEST_PASS
            node = _make_node()
            result = worker.execute_node(node, {})
            assert result.status == NodeStatus.PASSED
            assert result.iteration_count == 1

    def test_pass_after_retries(self):
        with patch.object(llm, "call_weak") as mock_llm, patch.object(sandbox, "execute") as mock_sandbox:
            mock_llm.side_effect = [
                llm.LLMResponse(content="def add(a, b): return a - b", input_tokens=100, output_tokens=30),
                llm.LLMResponse(content="def add(a, b): return a * b", input_tokens=100, output_tokens=30),
                llm.LLMResponse(content="def add(a, b): return a + b", input_tokens=100, output_tokens=30),
            ]
            mock_sandbox.side_effect = [_TEST_FAIL, _TEST_FAIL, _TEST_PASS]
            node = _make_node()
            result = worker.execute_node(node, {})
            assert result.status == NodeStatus.PASSED
            assert result.iteration_count == 3

    def test_fail_after_max_iterations(self):
        with patch.object(llm, "call_weak") as mock_llm, patch.object(sandbox, "execute") as mock_sandbox:
            mock_llm.side_effect = [
                llm.LLMResponse(content="def add(a, b): return a - b", input_tokens=100, output_tokens=30),
                llm.LLMResponse(content="def add(a, b): return a * b", input_tokens=100, output_tokens=30),
                llm.LLMResponse(content="def add(a, b): return a / b", input_tokens=100, output_tokens=30),
            ]
            mock_sandbox.side_effect = [_TEST_FAIL, _TEST_FAIL, _TEST_FAIL]
            node = _make_node(max_iterations=3)
            result = worker.execute_node(node, {})
            assert result.status == NodeStatus.FAILED
            assert result.iteration_count == 3

    def test_fail_on_compile_check(self):
        """编译检查不通过时直接重做，不跑测试。"""
        with patch.object(llm, "call_weak") as mock_llm, patch.object(sandbox, "execute") as mock_sandbox:
            # compile() 会拦截 Python 语法错误；代码必须通过 _looks_like_code
            mock_llm.side_effect = [
                llm.LLMResponse(content="def add(a, b):\n    return a + \n", input_tokens=100, output_tokens=30),
                llm.LLMResponse(content="def add(a, b): return a + b", input_tokens=100, output_tokens=30),
            ]
            mock_sandbox.return_value = _TEST_PASS
            node = _make_node()
            result = worker.execute_node(node, {})
            assert result.status == NodeStatus.PASSED
            assert result.iteration_count == 2

    def test_empty_code_response(self):
        with patch.object(llm, "call_weak") as mock_llm:
            # 5 次提取重试全部返回空 → 直接失败（单轮迭代即终止）
            mock_llm.side_effect = [
                llm.LLMResponse(content="  ", input_tokens=100, output_tokens=1),
            ] * 5
            node = _make_node(max_iterations=3)
            result = worker.execute_node(node, {})
            assert result.status == NodeStatus.FAILED

    def test_extracts_code_from_markdown(self):
        code = worker._extract_code("```python\ndef add(a, b): return a + b\n```")
        assert "def add" in code
        assert "```" not in code
