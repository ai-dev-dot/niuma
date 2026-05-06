"""compiler.py 编译器测试。"""

import json
from unittest.mock import patch

import compiler
import llm


VALID_DAG_JSON = json.dumps({
    "nodes": [
        {
            "node_id": "add",
            "name": "加法函数",
            "signature": {
                "language": "python",
                "function_name": "add",
                "params": [{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
                "return_type": "int",
                "allowed_imports": [],
                "methods": [],
            },
            "contract": {
                "preconditions": ["a, b 为整数"],
                "postconditions": ["返回 a+b 的结果"],
                "invariants": [],
            },
            "test_skeleton": "def test_add():\n    assert add(1, 2) == 3",
            "max_iterations": 5,
            "dependencies": [],
        }
    ]
}, ensure_ascii=False)


class TestCompiler:
    def test_valid_dag_returns_parsed(self):
        with patch.object(llm, "call_strong") as mock_call:
            mock_call.return_value = llm.LLMResponse(
                content=VALID_DAG_JSON,
                input_tokens=500,
                output_tokens=200,
            )
            dag = compiler.compile_task("实现 add 函数")
            assert len(dag.nodes) == 1
            assert dag.nodes[0].node_id == "add"
            assert dag.nodes[0].signature.language == "python"

    def test_invalid_json_retries_then_succeeds(self):
        invalid_json = '{"nodes": [{"node_id": "x"}]}'  # 缺必填字段
        with patch.object(llm, "call_strong") as mock_call:
            mock_call.side_effect = [
                llm.LLMResponse(content=invalid_json, input_tokens=100, output_tokens=50),
                llm.LLMResponse(content=VALID_DAG_JSON, input_tokens=100, output_tokens=200),
            ]
            dag = compiler.compile_task("实现 add 函数")
            assert len(dag.nodes) == 1
            assert dag.nodes[0].node_id == "add"
            assert mock_call.call_count == 2

    def test_invalid_json_exhausts_retries(self):
        invalid = '{"nodes": [{"node_id": "x"}]}'
        with patch('compiler._cfg.get_retry_limits', return_value={
            "compiler_schema_validation": 2,
            "clarify_rounds": 20,
            "worker_code_extraction": 5,
            "reviewer_rounds": 5,
            "llm_api_max_retries": 3,
        }):
            with patch.object(llm, "call_strong") as mock_call:
                mock_call.side_effect = [
                    llm.LLMResponse(content=invalid, input_tokens=100, output_tokens=50),
                    llm.LLMResponse(content=invalid, input_tokens=100, output_tokens=50),
                    llm.LLMResponse(content=invalid, input_tokens=100, output_tokens=50),
                ]
                with pytest.raises(compiler.CompilationError, match="Schema 校验失败"):
                    compiler.compile_task("实现 add 函数")

    def test_json_with_markdown_wrapper(self):
        wrapped = f"好的，这是 DAG JSON:\n```json\n{VALID_DAG_JSON}\n```\n希望满足要求。"
        with patch.object(llm, "call_strong") as mock_call:
            mock_call.return_value = llm.LLMResponse(
                content=wrapped, input_tokens=100, output_tokens=300,
            )
            dag = compiler.compile_task("实现 add 函数")
            assert len(dag.nodes) == 1

    def test_cycle_dependency_rejected(self):
        cycle_json = json.dumps({
            "nodes": [
                {"node_id": "a", "name": "A", "signature": {"language": "python", "function_name": "fa", "params": [], "return_type": "void", "allowed_imports": [], "methods": []}, "contract": {}, "test_skeleton": "def test_a(): pass", "dependencies": ["b"]},
                {"node_id": "b", "name": "B", "signature": {"language": "python", "function_name": "fb", "params": [], "return_type": "void", "allowed_imports": [], "methods": []}, "contract": {}, "test_skeleton": "def test_b(): pass", "dependencies": ["a"]},
            ]
        })
        with patch('compiler._cfg.get_retry_limits', return_value={
            "compiler_schema_validation": 2,
            "clarify_rounds": 20,
            "worker_code_extraction": 5,
            "reviewer_rounds": 5,
            "llm_api_max_retries": 3,
        }):
            with patch.object(llm, "call_strong") as mock_call:
                mock_call.side_effect = [
                    llm.LLMResponse(content=cycle_json, input_tokens=100, output_tokens=100),
                    llm.LLMResponse(content=cycle_json, input_tokens=100, output_tokens=100),
                    llm.LLMResponse(content=cycle_json, input_tokens=100, output_tokens=100),
                ]
                with pytest.raises(compiler.CompilationError):
                    compiler.compile_task("实现循环依赖")

    def test_empty_nodes_rejected(self):
        with patch('compiler._cfg.get_retry_limits', return_value={
            "compiler_schema_validation": 2,
            "clarify_rounds": 20,
            "worker_code_extraction": 5,
            "reviewer_rounds": 5,
            "llm_api_max_retries": 3,
        }):
            with patch.object(llm, "call_strong") as mock_call:
                mock_call.side_effect = [
                    llm.LLMResponse(content='{"nodes": []}', input_tokens=50, output_tokens=20),
                    llm.LLMResponse(content='{"nodes": []}', input_tokens=50, output_tokens=20),
                    llm.LLMResponse(content='{"nodes": []}', input_tokens=50, output_tokens=20),
                ]
                with pytest.raises(compiler.CompilationError):
                    compiler.compile_task("空的")


import pytest
