"""main.py 全流水线集成测试。"""

from unittest.mock import patch

import project_manager
import llm
import sandbox
from models import DAGNode, DAG, NodeResult, NodeStatus, ReviewResult, Contract, FunctionSignature


def _make_dag() -> DAG:
    return DAG(nodes=[
        DAGNode(
            node_id="add", name="加法",
            signature=FunctionSignature(language="python", function_name="add",
                                         params=[{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
                                         return_type="int"),
            contract=Contract(preconditions=["整数输入"], postconditions=["返回 a+b"]),
            test_skeleton="def test_add():\n    assert add(1, 2) == 3",
            max_iterations=3,
        ),
        DAGNode(
            node_id="mul", name="乘法",
            signature=FunctionSignature(language="python", function_name="mul",
                                         params=[{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
                                         return_type="int"),
            contract=Contract(preconditions=["整数输入"], postconditions=["返回 a*b"]),
            test_skeleton="def test_mul():\n    assert mul(2, 3) == 6",
            max_iterations=3,
            dependencies=["add"],  # mul 依赖 add，add 被修复后 mul 也需重做
        ),
    ])


class TestFullPipeline:
    def test_pipeline_all_pass(self):
        """全流程：编译→全部执行通过→审核 PASS。"""
        import compiler
        import reviewer
        import worker
        import main

        dag = _make_dag()

        with patch.object(compiler, "compile_task", return_value=dag), \
             patch.object(compiler, "commit_dag"), \
             patch.object(main, "_save_output"), \
             patch.object(project_manager, "create_task_branch", return_value="niuma/test"), \
             patch.object(project_manager, "commit_file"), \
             patch.object(project_manager, "switch_branch"), \
             patch.object(worker, "execute_node") as mock_exec, \
             patch.object(worker, "commit_node"), \
             patch.object(sandbox, "execute", return_value=sandbox.SandboxResult(exit_code=0, stdout="", stderr="")), \
             patch.object(reviewer, "review") as mock_rev, \
             patch.object(reviewer, "commit_review"):
            mock_exec.side_effect = [
                NodeResult(node_id="add", status=NodeStatus.PASSED,
                           generated_code="def add(a,b): return a+b", iteration_count=1),
                NodeResult(node_id="mul", status=NodeStatus.PASSED,
                           generated_code="def mul(a,b): return a*b", iteration_count=1),
            ]
            mock_rev.return_value = ReviewResult(passed=True)

            result = main.run_task("add and mul", verbose=False)
            assert result is True
            assert mock_exec.call_count == 2
            mock_rev.assert_called_once()

    def test_pipeline_review_fail_then_pass(self):
        """审核 FAIL → 重做失败节点 → 下游重做 → 审核 PASS。"""
        import compiler
        import reviewer
        import worker
        import main

        dag = _make_dag()

        with patch.object(compiler, "compile_task", return_value=dag), \
             patch.object(compiler, "commit_dag"), \
             patch.object(main, "_save_output"), \
             patch.object(project_manager, "create_task_branch", return_value="niuma/test"), \
             patch.object(project_manager, "commit_file"), \
             patch.object(project_manager, "switch_branch"), \
             patch.object(worker, "execute_node") as mock_exec, \
             patch.object(worker, "commit_node"), \
             patch.object(sandbox, "execute", return_value=sandbox.SandboxResult(exit_code=0, stdout="", stderr="")), \
             patch.object(reviewer, "review") as mock_rev, \
             patch.object(reviewer, "commit_review"):
            mock_exec.side_effect = [
                # 首次执行
                NodeResult(node_id="add", status=NodeStatus.PASSED,
                           generated_code="def add(a,b): return a-b", iteration_count=1),
                NodeResult(node_id="mul", status=NodeStatus.PASSED,
                           generated_code="def mul(a,b): return a*b", iteration_count=1),
                # 审核 FAIL 后重做 (add 失败 + mul 是依赖 add 的下游)
                NodeResult(node_id="add", status=NodeStatus.PASSED,
                           generated_code="def add(a,b): return a+b", iteration_count=2),
                NodeResult(node_id="mul", status=NodeStatus.PASSED,
                           generated_code="def mul(a,b): return a*b", iteration_count=1),
            ]
            mock_rev.side_effect = [
                ReviewResult(passed=False, failed_nodes=["add"],
                             suggestions="FAIL: add — 返回 a-b 而非 a+b"),
                ReviewResult(passed=True),
            ]

            result = main.run_task("add and mul", verbose=False)
            assert result is True
            assert mock_exec.call_count == 4  # 2 initial + 2 retry (add + downstream mul)
            assert mock_rev.call_count == 2

    def test_pipeline_compile_failure_cleanup(self):
        """编译失败时清理分支并返回 False。"""
        import compiler
        import main

        with patch.object(compiler, "compile_task", side_effect=compiler.CompilationError("bad")), \
             patch.object(project_manager, "create_task_branch", return_value="niuma/test"), \
             patch.object(project_manager, "commit_file"), \
             patch.object(project_manager, "switch_branch") as mock_switch, \
             patch.object(project_manager, "git_run") as mock_git:
            result = main.run_task("bad task", verbose=False)
            assert result is False
            mock_switch.assert_called()

    def test_pipeline_early_abort(self):
        """多节点失败 → 达到早期终止阈值 → 跳过剩余节点。"""
        import compiler
        import config
        import reviewer
        import worker
        import main

        dag = DAG(nodes=[
            DAGNode(node_id="a", name="A",
                    signature=FunctionSignature(language="python", function_name="fa", params=[], return_type="void"),
                    contract=Contract(), test_skeleton="def test_a(): pass", max_iterations=2),
            DAGNode(node_id="b", name="B",
                    signature=FunctionSignature(language="python", function_name="fb", params=[], return_type="void"),
                    contract=Contract(), test_skeleton="def test_b(): pass", max_iterations=2),
            DAGNode(node_id="c", name="C",
                    signature=FunctionSignature(language="python", function_name="fc", params=[], return_type="void"),
                    contract=Contract(), test_skeleton="def test_c(): pass", max_iterations=2),
        ])

        with patch.object(compiler, "compile_task", return_value=dag), \
             patch.object(compiler, "commit_dag"), \
             patch.object(main, "_save_output"), \
             patch.object(project_manager, "create_task_branch", return_value="niuma/test"), \
             patch.object(project_manager, "commit_file"), \
             patch.object(project_manager, "switch_branch"), \
             patch.object(worker, "execute_node") as mock_exec, \
             patch.object(worker, "commit_node"), \
             patch.object(sandbox, "execute", return_value=sandbox.SandboxResult(exit_code=0, stdout="", stderr="")), \
             patch.object(reviewer, "review") as mock_rev, \
             patch.object(reviewer, "commit_review"), \
             patch("config.get_retry_limits", return_value={
                 "clarify_rounds": 20, "compiler_schema_validation": 5,
                 "worker_code_extraction": 5, "reviewer_rounds": 1,
                 "llm_api_max_retries": 3, "early_abort_fail_ratio": 0.6,
             }):
            mock_exec.side_effect = [
                NodeResult(node_id="a", status=NodeStatus.FAILED, iteration_count=2),
                NodeResult(node_id="b", status=NodeStatus.FAILED, iteration_count=2),
                # 审核 FAIL 后重做 a 和 b（都在 failed_nodes 中）
                NodeResult(node_id="a", status=NodeStatus.FAILED, iteration_count=2),
                NodeResult(node_id="b", status=NodeStatus.FAILED, iteration_count=2),
            ]
            mock_rev.return_value = ReviewResult(passed=False, failed_nodes=["a", "b"])

            result = main.run_task("test", verbose=False)
            assert result is False
            assert mock_exec.call_count == 4  # 2 initial (a,b) + 2 retry (a,b) — c 被早期终止跳过
