"""sandbox.py 执行引擎测试。"""

import pytest
import sandbox


class TestSandboxPython:
    def test_passing_code(self):
        code = "def add(a, b):\n    return a + b\n"
        test = "def test_add():\n    assert add(1, 2) == 3\n    assert add(-1, 1) == 0\n"
        result = sandbox.execute(code, test, language="python")
        assert result.passed, f"应通过但失败了: {result.stdout}\n{result.stderr}"

    def test_failing_test(self):
        code = "def add(a, b):\n    return a - b\n"
        test = "def test_add():\n    assert add(1, 2) == 3\n"
        result = sandbox.execute(code, test, language="python")
        assert not result.passed
        assert "FAILED" in result.stdout or "assert" in result.stderr.lower()

    def test_syntax_error(self):
        code = "def add(a, b)\n    return a + b\n"  # 缺冒号
        test = "def test_add():\n    assert add(1, 2) == 3\n"
        result = sandbox.execute(code, test, language="python")
        assert not result.passed
        # pytest 收集阶段的语法错误可能在 stdout 或 stderr 中
        assert "SyntaxError" in result.stderr + result.stdout

    def test_timeout_code(self):
        code = "def add(a, b):\n    while True: pass\n    return a + b\n"
        test = "def test_add():\n    assert add(1, 2) == 3\n"
        result = sandbox.execute(code, test, language="python", cpu_timeout=2)
        assert not result.passed
        # 在非 Windows 上应被 setrlimit 杀死
        import os
        if os.name != "nt":
            assert result.timed_out or result.exit_code != 0

    def test_unsupported_language(self):
        result = sandbox.execute("x=1", "print(1)", language="java")
        assert result.exit_code == -1
        assert "不支持" in result.stderr
