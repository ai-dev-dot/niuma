"""共享数据类 —— 编译器/Worker/审核器/编排器之间的约定接口。"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    COMPILING = "compiling"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    DONE = "done"
    FAILED = "failed"


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


@dataclass
class MethodSignature:
    name: str
    params: list[dict[str, str]]
    return_type: str


@dataclass
class FunctionSignature:
    language: str = "typescript"
    function_name: str = ""
    params: list[dict[str, str]] = field(default_factory=list)
    return_type: str = "void"
    allowed_imports: list[str] = field(default_factory=list)
    methods: list[MethodSignature] = field(default_factory=list)


@dataclass
class Contract:
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)


@dataclass
class DAGNode:
    node_id: str
    name: str
    signature: FunctionSignature = field(default_factory=FunctionSignature)
    contract: Contract = field(default_factory=Contract)
    test_skeleton: str = ""
    max_iterations: int = 10
    dependencies: list[str] = field(default_factory=list)


@dataclass
class DAG:
    nodes: list[DAGNode] = field(default_factory=list)

    def transitive_deps(self, node_id: str) -> set[str]:
        """返回 node_id 的传递依赖闭包（不含自身）。"""
        deps: set[str] = set()
        node_map = {n.node_id: n for n in self.nodes}

        def collect(nid: str, visited: set[str]) -> None:
            if nid in visited:
                return
            visited.add(nid)
            node = node_map.get(nid)
            if node:
                for dep_id in node.dependencies:
                    deps.add(dep_id)
                    collect(dep_id, visited)

        collect(node_id, set())
        return deps

    def topological_order(self) -> list[DAGNode]:
        """按拓扑序返回节点列表（依赖在前）。"""
        resolved: set[str] = set()
        order: list[DAGNode] = []
        node_map = {n.node_id: n for n in self.nodes}

        def resolve(node_id: str, visited: set[str]) -> None:
            if node_id in resolved:
                return
            if node_id in visited:
                raise ValueError(f"DAG 包含循环依赖: {node_id}")
            visited.add(node_id)
            node = node_map[node_id]
            for dep_id in node.dependencies:
                if dep_id not in node_map:
                    raise ValueError(f"节点 {node_id} 依赖未知节点 {dep_id}")
                resolve(dep_id, visited)
            resolved.add(node_id)
            order.append(node)

        for node_id in node_map:
            resolve(node_id, set())

        return order


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    memory_exceeded: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.memory_exceeded


@dataclass
class NodeResult:
    node_id: str
    iteration_count: int = 0
    status: NodeStatus = NodeStatus.PENDING
    generated_code: str = ""
    test_output: str = ""


@dataclass
class ReviewResult:
    passed: bool
    failed_nodes: list[str] = field(default_factory=list)
    suggestions: str = ""
    score: int = 0
    summary: str = ""


@dataclass
class TaskRecord:
    id: str
    task_description: str
    dag_json: str = ""
    status: TaskStatus = TaskStatus.PENDING
    strong_tokens_used: int = 0
    weak_tokens_used: int = 0

    def to_db_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_description": self.task_description,
            "dag_json": self.dag_json,
            "status": self.status.value,
            "strong_tokens_used": self.strong_tokens_used,
            "weak_tokens_used": self.weak_tokens_used,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "TaskRecord":
        return cls(
            id=row["id"],
            task_description=row["task_description"],
            dag_json=row.get("dag_json", ""),
            status=TaskStatus(row["status"]),
            strong_tokens_used=row.get("strong_tokens_used", 0),
            weak_tokens_used=row.get("weak_tokens_used", 0),
        )


@dataclass
class MetricsEntry:
    task_id: str
    strong_tokens: int
    weak_tokens: int
    node_iterations: dict[str, int]  # node_id → iteration_count
    passed_count: int
    total_count: int
    timestamp: str = ""
