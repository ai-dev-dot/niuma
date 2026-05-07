"""reviewer.py 审核器测试。"""

from unittest.mock import patch

import llm
import reviewer
from models import DAGNode, DAG, NodeResult, NodeStatus, Contract, FunctionSignature


class TestBuildReviewPrompt:
    def test_small_node_fits_in_budget(self):
        dag = DAG(nodes=[DAGNode(node_id="a", name="A")])
        results = [NodeResult(node_id="a", status=NodeStatus.PASSED,
                              generated_code="def f(): pass", test_output="ok", iteration_count=1)]
        prompt = reviewer._build_review_prompt("test task", dag, results)
        assert "def f(): pass" in prompt
        assert "ok" in prompt
        assert "截断" not in prompt

    def test_large_code_truncated(self):
        dag = DAG(nodes=[DAGNode(node_id="a", name="A")])
        huge_code = "x" * 20000
        results = [NodeResult(node_id="a", status=NodeStatus.PASSED,
                              generated_code=huge_code, test_output="ok", iteration_count=1)]
        with patch('reviewer._cfg.get_retry_limits', return_value={
            "reviewer_rounds": 5, "reviewer_prompt_budget": 2000,
        }):
            prompt = reviewer._build_review_prompt("test task", dag, results)
            assert "截断" in prompt
            assert len(prompt) < 15000

    def test_empty_results_no_crash(self):
        dag = DAG(nodes=[DAGNode(node_id="a", name="A")])
        results: list[NodeResult] = []
        prompt = reviewer._build_review_prompt("test task", dag, results)
        assert "test task" in prompt

    def test_many_nodes_split_budget(self):
        nodes = [DAGNode(node_id=f"n{i}", name=f"N{i}") for i in range(4)]
        dag = DAG(nodes=nodes)
        code = "function f() { return 1; }" * 40  # ~1.2K chars
        results = [NodeResult(node_id=f"n{i}", status=NodeStatus.PASSED,
                              generated_code=code, test_output="all pass", iteration_count=1)
                   for i in range(4)]
        with patch('reviewer._cfg.get_retry_limits', return_value={
            "reviewer_rounds": 5, "reviewer_prompt_budget": 5000,
        }):
            prompt = reviewer._build_review_prompt("test task", dag, results)
            # 每个节点都应该出现（header 部分），但代码可能被截断
            for i in range(4):
                assert f"n{i}" in prompt


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
