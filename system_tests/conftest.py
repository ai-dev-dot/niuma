"""pytest 共享 fixtures。"""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# 确保项目根在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_dag():
    from models import DAG, Contract, DAGNode, FunctionSignature

    return DAG(nodes=[
        DAGNode(
            node_id="add",
            name="加法函数",
            signature=FunctionSignature(
                language="python",
                function_name="add",
                params=[{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
                return_type="int",
            ),
            contract=Contract(
                preconditions=["a, b 为整数"],
                postconditions=["返回 a+b 的结果"],
            ),
            test_skeleton="def test_add():\n    assert add(1, 2) == 3\n    assert add(-1, 1) == 0",
            max_iterations=5,
        )
    ])


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_env():
    """确保测试不泄漏真实 API key。"""
    for key in ("LLM_API_KEY", "LLM_BASE_URL", "STRONG_MODEL", "WEAK_MODEL"):
        os.environ.pop(key, None)
