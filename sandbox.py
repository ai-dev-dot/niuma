"""沙箱执行引擎 | Sandbox Execution Engine
在受限子进程中运行 AI 生成的代码和测试。
Runs AI-generated code + tests inside limited subprocesses."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import resource as _resource
except ImportError:
    _resource = None  # Windows does not support the resource module

from models import SandboxResult

# 项目根目录 —— 用于定位 node_modules 和 jest 配置
_PROJECT_ROOT = Path(__file__).resolve().parent


def execute(
    code: str,
    test_code: str,
    language: str = "typescript",
    cpu_timeout: int = 30,
    memory_limit_mb: int = 256,
) -> SandboxResult:
    """在受限环境中执行 code + test_code，返回结构化结果。
    Execute code + test_code in a restricted environment."""

    if language not in ("typescript", "python"):
        return SandboxResult(
            exit_code=-1,
            stdout="",
            stderr=_bilingual(
                f"不支持的语言: {language}",
                f"Unsupported language: {language}",
            ),
        )

    tmpdir = tempfile.mkdtemp(prefix="niuma_sandbox_")
    try:
        if language == "typescript":
            return _execute_typescript(tmpdir, code, test_code, cpu_timeout, memory_limit_mb)
        else:
            return _execute_python(tmpdir, code, test_code, cpu_timeout, memory_limit_mb)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _execute_typescript(
    tmpdir: str,
    code: str,
    test_code: str,
    cpu_timeout: int,
    memory_limit_mb: int,
) -> SandboxResult:
    """运行 TypeScript 代码 + Jest 测试。使用项目本地 node_modules。"""
    code_file = Path(tmpdir) / "solution.ts"
    code_file.write_text(code, encoding="utf-8")

    test_file = Path(tmpdir) / "solution.test.ts"
    test_content = f"// Solution\n{code}\n\n// Tests\n{test_code}\n"
    test_file.write_text(test_content, encoding="utf-8")

    # 在临时目录里写一个最小 jest.config，让 jest 能找到 ts-jest preset
    # 将 jest.config 写入临时目录，通过 transform 显式引用 ts-jest
    tsj = str(_PROJECT_ROOT / "node_modules" / "ts-jest").replace(chr(92), '/')
    jest_config = Path(tmpdir) / "jest.config.js"
    jest_config.write_text(f"""module.exports = {{
  transform: {{ '^.+\\\\.ts$': '{tsj}' }},
  testEnvironment: 'node',
  testMatch: ['**/*.test.ts'],
  testTimeout: 30000,
  rootDir: '{tmpdir.replace(chr(92), '/')}',
}};\n""", encoding="utf-8")

    # 找到 npx（Windows 用 npx.cmd，Linux 用 npx）
    import shutil as _shutil
    npx = _shutil.which("npx") or _shutil.which("npx.cmd")
    if not npx:
        return SandboxResult(
            exit_code=-1,
            stdout="",
            stderr=_bilingual(
                "npx 未找到，请安装 Node.js | npx not found, install Node.js",
                "npx not found, install Node.js",
            ),
        )
    return _run_subprocess(
        [
            npx, "--no-install", "jest",
            "--config", str(jest_config),
            "--no-color", "--verbose",
            "--roots", tmpdir,
        ],
        cwd=str(_PROJECT_ROOT),
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
    test_file = Path(tmpdir) / "test_solution.py"
    test_file.write_text(f"{code}\n\n{test_code}\n", encoding="utf-8")

    return _run_subprocess(
        [sys.executable, "-m", "pytest", str(test_file), "-v", "--tb=short"],
        cwd=tmpdir,
        cpu_timeout=cpu_timeout,
        memory_limit_mb=memory_limit_mb,
    )


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
            encoding="utf-8",
            errors="replace",
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
            stderr=_bilingual(
                f"执行超时（{cpu_timeout}s 限制）",
                f"Execution timed out ({cpu_timeout}s limit)",
            ),
            timed_out=True,
        )


def _bilingual(zh: str, en: str) -> str:
    """中英双语错误消息。"""
    return f"{zh} / {en}"
