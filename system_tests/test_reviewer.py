"""reviewer.py 审核器测试。"""

from unittest.mock import patch

import llm
import reviewer
from models import DAGNode, DAG, NodeResult, NodeStatus, Contract, FunctionSignature


class TestReviewer:
    def test_pass_review(self):
        dag = DAG(nodes=[DAGNode(node_id="a", name="Add", signature=FunctionSignature(language="python", function_name="add", params=[], return_type="int"))])
        results = [NodeResult(node_id="a", status=NodeStatus.PASSED, generated_code="def add(a,b): return a+b", iteration_count=1)]
        with patch.object(llm, "call_strong") as mock_call:
            mock_call.return_value = llm.LLMResponse(content="PASS", input_tokens=200, output_tokens=5)
            rv = reviewer.review("实现 add", dag, results)
            assert rv.passed
            assert rv.failed_nodes == []

    def test_fail_review(self):
        dag = DAG(nodes=[DAGNode(node_id="a", name="Add", signature=FunctionSignature(language="python", function_name="add", params=[], return_type="int"))])
        results = [NodeResult(node_id="a", status=NodeStatus.PASSED, generated_code="def add(a,b): return a-b", iteration_count=5)]
        with patch.object(llm, "call_strong") as mock_call:
            mock_call.return_value = llm.LLMResponse(
                content="FAIL: a — 返回 a-b 而非 a+b — 修复逻辑错误",
                input_tokens=200, output_tokens=30,
            )
            rv = reviewer.review("实现 add", dag, results)
            assert not rv.passed
            assert "a" in rv.failed_nodes

    def test_pass_with_lowercase(self):
        dag = DAG(nodes=[DAGNode(node_id="x", name="X", signature=FunctionSignature(language="python", function_name="f", params=[], return_type="void"))])
        results = [NodeResult(node_id="x", status=NodeStatus.PASSED, generated_code="def f(): pass")]
        with patch.object(llm, "call_strong") as mock_call:
            mock_call.return_value = llm.LLMResponse(content="pass — 所有节点满足要求", input_tokens=100, output_tokens=10)
            rv = reviewer.review("test", dag, results)
            assert rv.passed
