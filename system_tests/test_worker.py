"""worker.py 执行器测试。"""

from unittest.mock import patch

import pytest
import worker
from models import Contract, DAGNode, FunctionSignature, NodeStatus


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


class TestWorker:
    def test_pass_on_first_try(self):
        import llm
        import sandbox
        with patch.object(llm, "call_weak") as mock_llm, patch.object(sandbox, "execute") as mock_sandbox:
            mock_llm.return_value = llm.LLMResponse(
                content="def add(a, b): return a + b",
                input_tokens=100, output_tokens=30,
            )
            mock_sandbox.return_value = sandbox.SandboxResult(exit_code=0, stdout=".", stderr="")
            node = _make_node()
            result = worker.execute_node(node, {})
            assert result.status == NodeStatus.PASSED
            assert result.iteration_count == 1

    def test_pass_after_retries(self):
        import llm
        import sandbox
        with patch.object(llm, "call_weak") as mock_llm, patch.object(sandbox, "execute") as mock_sandbox:
            mock_llm.return_value = llm.LLMResponse(
                content="def add(a, b): return a + b",
                input_tokens=100, output_tokens=30,
            )
            # 前两次失败，第三次通过
            mock_sandbox.side_effect = [
                sandbox.SandboxResult(exit_code=1, stdout="", stderr="AssertionError"),
                sandbox.SandboxResult(exit_code=1, stdout="", stderr="AssertionError"),
                sandbox.SandboxResult(exit_code=0, stdout=".", stderr=""),
            ]
            node = _make_node()
            result = worker.execute_node(node, {})
            assert result.status == NodeStatus.PASSED
            assert result.iteration_count == 3
            assert mock_llm.call_count == 3

    def test_fail_after_max_iterations(self):
        import llm
        import sandbox
        with patch.object(llm, "call_weak") as mock_llm, patch.object(sandbox, "execute") as mock_sandbox:
            mock_llm.return_value = llm.LLMResponse(
                content="def add(a, b): return a - b",
                input_tokens=100, output_tokens=30,
            )
            mock_sandbox.return_value = sandbox.SandboxResult(exit_code=1, stdout="", stderr="AssertionError")
            node = _make_node(max_iterations=3)
            result = worker.execute_node(node, {})
            assert result.status == NodeStatus.FAILED
            assert result.iteration_count == 3

    def test_empty_code_response(self):
        import llm
        with patch.object(llm, "call_weak") as mock_llm:
            mock_llm.return_value = llm.LLMResponse(
                content="  ", input_tokens=100, output_tokens=1,
            )
            node = _make_node(max_iterations=3)
            result = worker.execute_node(node, {})
            assert result.status == NodeStatus.FAILED

    def test_extracts_code_from_markdown(self):
        code = worker._extract_code("```python\ndef add(a, b): return a + b\n```")
        assert "def add" in code
        assert "```" not in code
