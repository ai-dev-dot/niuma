"""沙箱执行引擎 —— 在受限子进程中运行 AI 生成的代码和测试。"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    import resource as _resource
except ImportError:
    _resource = None  # Windows 不支持 resource 模块

from models import SandboxResult


def execute(
    code: str,
    test_code: str,
    language: str = "typescript",
    cpu_timeout: int = 30,
    memory_limit_mb: int = 256,
) -> SandboxResult:
    """在受限环境中执行 code + test_code，返回结构化结果。"""
    tmpdir = tempfile.mkdtemp(prefix="niuma_sandbox_")
    try:
        if language == "typescript":
            return _execute_typescript(tmpdir, code, test_code, cpu_timeout, memory_limit_mb)
        elif language == "python":
            return _execute_python(tmpdir, code, test_code, cpu_timeout, memory_limit_mb)
        else:
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=f"不支持的语言: {language}",
            )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _execute_typescript(
    tmpdir: str,
    code: str,
    test_code: str,
    cpu_timeout: int,
    memory_limit_mb: int,
) -> SandboxResult:
    """运行 TypeScript 代码 + Jest 测试。"""
    # 写出代码文件
    code_file = Path(tmpdir) / "solution.ts"
    code_file.write_text(code, encoding="utf-8")

    # 写出测试文件
    test_file = Path(tmpdir) / "solution.test.ts"
    test_content = _build_jest_test(code, test_code, code_file.name)
    test_file.write_text(test_content, encoding="utf-8")

    # 写出 jest.config
    jest_config = Path(tmpdir) / "jest.config.js"
    jest_config.write_text(
        """module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  testMatch: ['**/*.test.ts'],
  testTimeout: 30000,
};\n""",
        encoding="utf-8",
    )

    # 写 package.json（Jest 需要）
    pkg = Path(tmpdir) / "package.json"
    pkg.write_text('{"type": "commonjs"}\n', encoding="utf-8")

    return _run_subprocess(
        ["npx", "jest", "--no-color", "--verbose"],
        cwd=tmpdir,
        cpu_timeout=cpu_timeout,
        memory_limit_mb=memory_limit_mb,
    )


def _execute_python(
    tmpdir: str,
    code: str,
    test_code: str,
    cpu_timeout: int,
    memory_limit_mb: int,
) -> SandboxResult:
    """运行 Python 代码 + pytest。"""
    # 写出代码 + 测试到同一个文件
    test_file = Path(tmpdir) / "test_solution.py"
    test_content = f"{code}\n\n{test_code}\n"
    test_file.write_text(test_content, encoding="utf-8")

    return _run_subprocess(
        ["python", "-m", "pytest", str(test_file), "-v", "--tb=short"],
        cwd=tmpdir,
        cpu_timeout=cpu_timeout,
        memory_limit_mb=memory_limit_mb,
    )


def _build_jest_test(code: str, test_code: str, module_path: str) -> str:
    """构建 Jest 测试文件模板。"""
    return f"""// 被测代码
{code}

// 测试
{test_code}
"""


def _run_subprocess(
    cmd: list[str],
    cwd: str,
    cpu_timeout: int,
    memory_limit_mb: int,
) -> SandboxResult:
    def set_limits() -> None:
        if _resource is None:
            return
        try:
            _resource.setrlimit(_resource.RLIMIT_CPU, (cpu_timeout, cpu_timeout))
            mem_bytes = memory_limit_mb * 1024 * 1024
            _resource.setrlimit(_resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            _resource.setrlimit(_resource.RLIMIT_NPROC, (64, 64))
        except (ValueError, _resource.error):
            pass

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=cpu_timeout,
            preexec_fn=set_limits if os.name != "nt" else None,
        )
        return SandboxResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(
            exit_code=-1,
            stdout="",
            stderr="执行超时",
            timed_out=True,
        )
