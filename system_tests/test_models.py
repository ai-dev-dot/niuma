"""types.py 数据类测试。"""

import pytest
from models import (
    DAG,
    Contract,
    DAGNode,
    FunctionSignature,
    NodeResult,
    NodeStatus,
    SandboxResult,
    TaskStatus,
)


class TestSandboxResult:
    def test_passed_when_exit_zero(self):
        r = SandboxResult(exit_code=0, stdout="ok", stderr="")
        assert r.passed

    def test_failed_when_nonzero_exit(self):
        r = SandboxResult(exit_code=1, stdout="", stderr="assert error")
        assert not r.passed

    def test_failed_when_timed_out(self):
        r = SandboxResult(exit_code=0, stdout="", stderr="", timed_out=True)
        assert not r.passed

    def test_failed_when_memory_exceeded(self):
        r = SandboxResult(exit_code=0, stdout="", stderr="", memory_exceeded=True)
        assert not r.passed


class TestDAGTopologicalOrder:
    def test_single_node(self):
        dag = DAG(nodes=[DAGNode(node_id="a", name="A")])
        order = dag.topological_order()
        assert [n.node_id for n in order] == ["a"]

    def test_linear_chain(self):
        dag = DAG(nodes=[
            DAGNode(node_id="a", name="A"),
            DAGNode(node_id="b", name="B", dependencies=["a"]),
            DAGNode(node_id="c", name="C", dependencies=["b"]),
        ])
        order = dag.topological_order()
        ids = [n.node_id for n in order]
        assert ids.index("a") < ids.index("b") < ids.index("c")

    def test_diamond_dependency(self):
        dag = DAG(nodes=[
            DAGNode(node_id="a", name="A"),
            DAGNode(node_id="b", name="B", dependencies=["a"]),
            DAGNode(node_id="c", name="C", dependencies=["a"]),
            DAGNode(node_id="d", name="D", dependencies=["b", "c"]),
        ])
        order = dag.topological_order()
        ids = [n.node_id for n in order]
        assert ids[0] == "a"
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")

    def test_cycle_detection(self):
        dag = DAG(nodes=[
            DAGNode(node_id="a", name="A", dependencies=["b"]),
            DAGNode(node_id="b", name="B", dependencies=["a"]),
        ])
        with pytest.raises(ValueError, match="循环依赖"):
            dag.topological_order()

    def test_unknown_dependency(self):
        dag = DAG(nodes=[
            DAGNode(node_id="a", name="A", dependencies=["nonexistent"]),
        ])
        with pytest.raises(ValueError, match="依赖未知节点"):
            dag.topological_order()


class TestTaskStatus:
    def test_all_statuses_defined(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.COMPILING.value == "compiling"
        assert TaskStatus.EXECUTING.value == "executing"
        assert TaskStatus.REVIEWING.value == "reviewing"
        assert TaskStatus.DONE.value == "done"
        assert TaskStatus.FAILED.value == "failed"
