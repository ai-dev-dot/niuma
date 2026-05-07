"""弱模型能力基准测试 — 测量弱模型在真实应用任务上的表现。

18 道题（6 维度 × 3 难度），全部是真实应用（CLI 工具 / API 服务 / 数据处理），
所有验证适配 2GB 环境（subprocess + curl + jq + html.parser，不用浏览器）。
"""

import json
import os
import sys
import time
import subprocess
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import llm
import sandbox
import config as _cfg

# Windows UTF-8 兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_PROJECT_ROOT = Path(__file__).resolve().parent
_SUITE_DIR = _PROJECT_ROOT / "task_suite"
_OUTPUT_DIR = _PROJECT_ROOT / "benchmark_results"


def load_tasks(suite_dir: Path = _SUITE_DIR) -> list[dict]:
    """加载所有任务定义。每个维度目录下的 *.json 文件。"""
    tasks: list[dict] = []
    if not suite_dir.exists():
        return tasks
    for dim_dir in sorted(suite_dir.iterdir()):
        if dim_dir.is_dir():
            for task_file in sorted(dim_dir.glob("*.json")):
                try:
                    task = json.loads(task_file.read_text(encoding="utf-8"))
                    task["_file"] = str(task_file)
                    tasks.append(task)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"  [!!] 跳过无效任务文件 {task_file}: {e}", file=sys.stderr)
    return tasks


def run_task(task: dict, verbose: bool = True) -> dict:
    """运行单个基准测试任务，返回结果记录。"""
    task_id = task["task_id"]
    dimension = task["dimension"]
    difficulty = task["difficulty"]
    judge_cfg = task.get("judge", {})

    if verbose:
        print(f"  [{dimension}/{difficulty}] {task_id} ...", end=" ", flush=True)

    t_start = time.time()
    result: dict[str, Any] = {
        "task_id": task_id,
        "dimension": dimension,
        "difficulty": difficulty,
        "verdict": "FAIL",
        "metrics": {},
        "error": None,
    }

    try:
        # 1. 构造 prompt 并调用弱模型
        prompt = task["prompt"]
        system = task.get("system", f"你是一个 {task.get('language', 'python').upper()} 程序员。"
                          "只输出要求的代码或回答，不要写解释。")

        llm.set_meta({"role": "benchmark", "task_id": task_id})
        resp = llm.call_weak(prompt, system=system, max_tokens=task.get("max_tokens", 0))

        result["metrics"]["tokens_in"] = resp.input_tokens
        result["metrics"]["tokens_out"] = resp.output_tokens
        result["metrics"]["latency_ms"] = int((time.time() - t_start) * 1000)
        result["response"] = resp.content[:4000]

        # 2. 根据判定方法验证
        method = judge_cfg.get("method", "sandbox")

        if method == "sandbox":
            verdict, detail = _judge_sandbox(task, resp.content)
        elif method == "cli":
            verdict, detail = _judge_cli(task, resp.content)
        elif method == "api":
            verdict, detail = _judge_api(task, resp.content)
        elif method == "keyword_match":
            verdict, detail = _judge_keyword(task, resp.content)
        elif method == "file_output":
            verdict, detail = _judge_file_output(task, resp.content)
        else:
            verdict, detail = "FAIL", f"未知判定方法: {method}"

        result["verdict"] = verdict
        result["judge_detail"] = detail

    except Exception as e:
        result["verdict"] = "ERROR"
        result["error"] = f"{type(e).__name__}: {str(e)[:400]}"

    result["metrics"]["duration_s"] = round(time.time() - t_start, 1)

    if verbose:
        status = {"PASS": "[PASS]", "FAIL": "[FAIL]", "ERROR": "[ERR]"}.get(result["verdict"], "?")
        dur = result["metrics"]["duration_s"]
        print(f"{status} ({dur:.1f}s)")

    return result


# ═══════════════════════════════════════════════════════════════
# 判定器 (Judges)
# ═══════════════════════════════════════════════════════════════

def _extract_code(raw: str, lang: str = "python") -> str:
    """从模型响应中提取代码块。复用 worker 的模式。"""
    import re as _re
    text = raw.strip()
    text = _re.sub(r"<think>[\s\S]*?</think>", "", text)

    for fence in [f"```{lang}", "```python", "```typescript", "```ts", "```"]:
        if fence in text:
            parts = text.split(fence, 1)
            if len(parts) > 1:
                inner = parts[1].split("```", 1)[0] if "```" in parts[1] else parts[1]
                return inner.strip()

    # 去掉常见的开头废话
    for prefix in ["好的，", "以下是", "这是", "Here is", "Here's",
                    "The user", "Let me", "I need", "I'll", "First", "We need",
                    "当然", "没问题", "可以的"]:
        if text.lower().startswith(prefix.lower()):
            lines = text.split("\n", 1)
            if len(lines) > 1:
                return lines[1].strip()
    return text


def _judge_sandbox(task: dict, response: str) -> tuple[str, str]:
    """沙箱判定：提取代码 → 跑测试 → 测试通过即 PASS。"""
    lang = task.get("language", "python")
    model_output = _extract_code(response, lang)
    test_skeleton = task.get("test_skeleton", "")

    if not model_output or len(model_output) < 10:
        return "FAIL", "无法从响应中提取有效代码"

    # test_gen 模式：模型写测试，用正确代码验证测试质量
    if task.get("code_source") == "ground_truth":
        sb = sandbox.execute(
            code=task.get("ground_truth_code", ""),
            test_code=model_output,
            language=lang,
        )
        if sb.passed:
            return "PASS", "生成的测试对正确代码全部通过"
        err = (sb.stderr or sb.stdout)[:500]
        return "FAIL", f"生成的测试执行失败: {err}"

    # 正常模式：模型写代码，用测试验证代码正确性
    sb = sandbox.execute(code=model_output, test_code=test_skeleton, language=lang)
    if sb.passed:
        return "PASS", f"测试通过 (exit_code=0)"
    err = (sb.stderr or sb.stdout)[:500]
    return "FAIL", f"测试失败: {err}"


def _judge_cli(task: dict, response: str) -> tuple[str, str]:
    """CLI 判定：提取代码 → 写入文件 → subprocess 运行 → 比对 stdout。"""
    code = _extract_code(response, task.get("language", "python"))
    if not code or len(code) < 10:
        return "FAIL", "无法从响应中提取有效代码"

    test_cases: list = task.get("test_cases", [])
    if not test_cases:
        return "FAIL", "任务未定义 test_cases"

    tmpdir = tempfile.mkdtemp(prefix="niuma_bench_")
    try:
        script = Path(tmpdir) / "app.py"
        script.write_text(code, encoding="utf-8")

        for tc in test_cases:
            args = tc.get("args", [])
            expected = tc.get("expected", "")
            contains_any = tc.get("contains_any", [])
            contains_all = tc.get("contains_all", [])
            contains_not = tc.get("contains_not", [])
            timeout = tc.get("timeout", 10)

            try:
                r = subprocess.run(
                    [sys.executable, str(script)] + [str(a) for a in args],
                    capture_output=True, text=True, timeout=timeout,
                    encoding="utf-8", errors="replace",
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    cwd=tmpdir,
                )
                stdout = r.stdout.strip()
                stderr = r.stderr.strip()
                combined = stdout + "\n" + stderr

                if expected and expected.lower() not in combined.lower():
                    return "FAIL", f"stdout 不含预期文本 '{expected[:100]}'"

                combined_lower = combined.lower()

                # contains_any: 至少匹配一个（忽略大小写）
                if contains_any:
                    if not any(kw.lower() in combined_lower for kw in contains_any):
                        return "FAIL", f"stdout 不含任意关键词: {contains_any}"

                # contains_all: 全部匹配（忽略大小写）
                for kw in contains_all:
                    if kw.lower() not in combined_lower:
                        return "FAIL", f"stdout 不含关键词: '{kw}'"

                # contains_not: 不应出现（忽略大小写）
                for kw in contains_not:
                    if kw.lower() in combined_lower:
                        return "FAIL", f"stdout 不应含: '{kw}'"

                if r.returncode != 0 and tc.get("expect_success", True):
                    return "FAIL", f"进程退出码 {r.returncode}: {stderr[:200]}"

            except subprocess.TimeoutExpired:
                return "FAIL", f"CLI 超时 ({timeout}s)"

        return "PASS", f"全部 {len(test_cases)} 个测试用例通过"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _judge_api(task: dict, response: str) -> tuple[str, str]:
    """API 判定：提取代码 → 启动 Flask 服务 → curl 请求 → 检查 JSON 响应。"""
    code = _extract_code(response, task.get("language", "python"))
    if not code or len(code) < 10:
        return "FAIL", "无法从响应中提取有效代码"

    import threading
    import time as _time

    test_cases: list = task.get("test_cases", [])
    if not test_cases:
        return "FAIL", "任务未定义 test_cases"

    tmpdir = tempfile.mkdtemp(prefix="niuma_bench_")
    port = 18923  # 固定端口，避免冲突

    try:
        script = Path(tmpdir) / "app.py"
        # 确保 flask 可用，替换默认端口
        code_with_port = code.replace("app.run", f"app.run(host='127.0.0.1', port={port})")
        if "app.run" not in code_with_port:
            code_with_port += f"\n\nif __name__ == '__main__':\n    app.run(host='127.0.0.1', port={port})\n"
        script.write_text(code_with_port, encoding="utf-8")

        # 启动服务
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=tmpdir,
        )

        # 等待服务就绪
        ready = False
        for _ in range(30):  # 最多等15秒
            _time.sleep(0.5)
            try:
                import urllib.request as _req
                _req.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
                # 即使404也算服务已启动
                ready = True
                break
            except Exception:
                continue

        if not ready:
            proc.kill()
            return "FAIL", "API 服务启动超时"

        # 执行测试
        for tc in test_cases:
            method = tc.get("method", "GET")
            path = tc.get("path", "/")
            expected_status = tc.get("expected_status", 200)
            expected_keys: list = tc.get("expected_keys", [])
            expected_values: dict = tc.get("expected_values", {})

            try:
                import urllib.request as _req
                import urllib.error as _err

                url = f"http://127.0.0.1:{port}{path}"
                data = None
                if method in ("POST", "PUT", "PATCH"):
                    body = tc.get("body", {})
                    data = json.dumps(body).encode("utf-8") if body else None

                req = _req.Request(url, data=data, method=method)
                if data:
                    req.add_header("Content-Type", "application/json")

                try:
                    with _req.urlopen(req, timeout=5) as resp:
                        status = resp.status
                        body_text = resp.read().decode("utf-8")
                except _err.HTTPError as e:
                    status = e.code
                    body_text = e.read().decode("utf-8", errors="replace")

                if status != expected_status:
                    proc.kill()
                    return "FAIL", f"{method} {path} 返回 {status}，期望 {expected_status}"

                if expected_keys or expected_values:
                    try:
                        data = json.loads(body_text)
                    except json.JSONDecodeError:
                        proc.kill()
                        return "FAIL", f"{method} {path} 返回非 JSON: {body_text[:200]}"

                    for key in expected_keys:
                        if key not in (data if isinstance(data, dict) else data[0] if isinstance(data, list) and data else {}):
                            proc.kill()
                            return "FAIL", f"响应缺少字段 '{key}'"

                    for key, val in expected_values.items():
                        actual = (data if isinstance(data, dict) else {}).get(key)
                        if actual != val:
                            proc.kill()
                            return "FAIL", f"字段 '{key}' 期望 '{val}'，实际 '{actual}'"

            except Exception as e:
                proc.kill()
                return "FAIL", f"API 测试异常: {str(e)[:200]}"

        proc.kill()
        return "PASS", f"全部 {len(test_cases)} 个 API 测试用例通过"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _judge_keyword(task: dict, response: str) -> tuple[str, str]:
    """关键词匹配判定：检查回答中是否包含预期关键词。"""
    keywords: list = task.get("keywords", [])
    if not keywords:
        return "FAIL", "任务未定义 keywords"

    text_lower = response.lower()
    matched = [kw for kw in keywords if kw.lower() in text_lower]

    threshold = task.get("keyword_threshold", max(1, len(keywords) // 2))
    if len(matched) >= threshold:
        return "PASS", f"匹配关键词 {len(matched)}/{len(keywords)}: {matched}"
    else:
        missing = [kw for kw in keywords if kw.lower() not in text]
        return "FAIL", f"仅匹配 {len(matched)}/{len(keywords)}，缺少: {missing}"


def _judge_file_output(task: dict, response: str) -> tuple[str, str]:
    """文件输出判定：运行代码 → 检查输出文件是否存在、内容是否匹配。"""
    code = _extract_code(response, task.get("language", "python"))
    if not code or len(code) < 10:
        return "FAIL", "无法从响应中提取有效代码"

    expected_files: list = task.get("expected_files", [])
    if not expected_files:
        return "FAIL", "任务未定义 expected_files"

    tmpdir = tempfile.mkdtemp(prefix="niuma_bench_")
    try:
        script = Path(tmpdir) / "app.py"
        script.write_text(code, encoding="utf-8")

        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=30,
            cwd=tmpdir,
        )

        for ef in expected_files:
            fpath = Path(tmpdir) / ef["path"]
            if not fpath.exists():
                return "FAIL", f"输出文件不存在: {ef['path']}"

            content = fpath.read_text(encoding="utf-8")
            for kw in ef.get("contains", []):
                if kw not in content:
                    return "FAIL", f"文件 {ef['path']} 不含 '{kw}'"
            if ef.get("min_lines", 0) > 0:
                if len(content.splitlines()) < ef["min_lines"]:
                    return "FAIL", f"文件 {ef['path']} 少于 {ef['min_lines']} 行"

        return "PASS", f"全部 {len(expected_files)} 个输出文件符合预期"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
# 运行与报告
# ═══════════════════════════════════════════════════════════════

def run_all(suite_dir: Path | None = None, output_dir: Path | None = None,
            verbose: bool = True) -> dict:
    """运行全部基准测试，返回 summary dict。"""
    tasks = load_tasks(suite_dir or _SUITE_DIR)
    if not tasks:
        print("未找到任何基准测试任务", file=sys.stderr)
        return {"error": "no tasks found"}

    out = (output_dir or _OUTPUT_DIR) / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    per_task_dir = out / "per_task"
    per_task_dir.mkdir(exist_ok=True)

    print(f"\n  Niuma Benchmark — {len(tasks)} 道题")
    print(f"  弱模型: {_cfg.get_model_config('weak')['model']}")
    print(f"  输出: {out}")
    print()

    results: list[dict] = []
    for task in tasks:
        result = run_task(task, verbose=verbose)
        results.append(result)

        # 每题保存详情
        detail_path = per_task_dir / f"{task['task_id']}.json"
        detail_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # 汇总
    summary = _build_summary(results, out)
    summary_path = out / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 原始指标流
    metrics_path = out / "metrics.jsonl"
    with open(metrics_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 环境快照
    env_path = out / "env.json"
    env_path.write_text(json.dumps({
        "platform": sys.platform,
        "python": sys.version,
        "weak_model": _cfg.get_model_config("weak")["model"],
        "weak_base_url": _cfg.get_model_config("weak")["base_url"],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    if verbose:
        _print_summary(summary)

    return summary


def _build_summary(results: list[dict], output_dir: Path) -> dict:
    """从结果列表构建汇总。"""
    dims: dict[str, dict] = {}
    for r in results:
        dim = r["dimension"]
        if dim not in dims:
            dims[dim] = {"pass": 0, "fail": 0, "error": 0,
                         "tokens_in": 0, "tokens_out": 0, "latency_ms": 0, "count": 0}
        d = dims[dim]
        d["count"] += 1
        d["tokens_in"] += r.get("metrics", {}).get("tokens_in", 0)
        d["tokens_out"] += r.get("metrics", {}).get("tokens_out", 0)
        d["latency_ms"] += r.get("metrics", {}).get("latency_ms", 0)

        verdict = r.get("verdict", "ERROR")
        if verdict == "PASS":
            d["pass"] += 1
        elif verdict == "ERROR":
            d["error"] += 1
        else:
            d["fail"] += 1

    dim_summaries = {}
    total_pass = 0
    total_count = 0
    total_tokens = 0
    total_latency = 0

    for dim, d in sorted(dims.items()):
        total_pass += d["pass"]
        total_count += d["count"]
        total_tokens += d["tokens_in"] + d["tokens_out"]
        total_latency += d["latency_ms"]
        dim_summaries[dim] = {
            "pass": d["pass"], "fail": d["fail"], "error": d["error"],
            "total": d["count"],
            "pass_rate": round(d["pass"] / d["count"], 2) if d["count"] else 0,
            "avg_tokens_in": d["tokens_in"] // d["count"] if d["count"] else 0,
            "avg_tokens_out": d["tokens_out"] // d["count"] if d["count"] else 0,
            "avg_latency_ms": d["latency_ms"] // d["count"] if d["count"] else 0,
        }

    return {
        "run_id": output_dir.name,
        "model": _cfg.get_model_config("weak")["model"],
        "total_tasks": total_count,
        "total_pass": total_pass,
        "overall_pass_rate": round(total_pass / total_count, 2) if total_count else 0,
        "total_tokens": total_tokens,
        "total_latency_ms": total_latency,
        "dimensions": dim_summaries,
    }


def _print_summary(summary: dict) -> None:
    """打印结果摘要。"""
    print()
    print(f"  {'='*50}")
    print(f"  基准测试结果 | Benchmark Results")
    print(f"  {'='*50}")
    print(f"  模型: {summary['model']}")
    print(f"  总题数: {summary['total_tasks']}  通过: {summary['total_pass']}  "
          f"通过率: {summary['overall_pass_rate']:.0%}")
    print(f"  总 token: {summary['total_tokens']}  "
          f"总延迟: {summary['total_latency_ms']}ms")
    print()

    dims = summary.get("dimensions", {})
    if dims:
        print(f"  {'维度':<16} {'通过':>5} {'失败':>5} {'通过率':>7} {'平均token':>10} {'平均延迟':>10}")
        print(f"  {'-'*16} {'-'*5} {'-'*5} {'-'*7} {'-'*10} {'-'*10}")
        for dim, d in sorted(dims.items()):
            print(f"  {dim:<16} {d['pass']:>4}  {d['fail']:>4}  {d['pass_rate']:>6.0%}  "
                  f"{d['avg_tokens_in'] + d['avg_tokens_out']:>9}  {d['avg_latency_ms']:>8}ms")
    print()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Niuma 弱模型能力基准测试")
    p.add_argument("--suite", default=str(_SUITE_DIR), help="任务集目录")
    p.add_argument("--output", default=str(_OUTPUT_DIR), help="输出目录")
    p.add_argument("--task", help="只运行指定 task_id")
    p.add_argument("--dim", help="只运行指定维度")
    args = p.parse_args()

    suite = Path(args.suite)
    out = Path(args.output)

    if args.task:
        tasks = [t for t in load_tasks(suite) if t["task_id"] == args.task]
        if not tasks:
            print(f"未找到任务: {args.task}")
            sys.exit(1)
        result = run_task(tasks[0])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.dim:
        tasks = [t for t in load_tasks(suite) if t["dimension"] == args.dim]
        if not tasks:
            print(f"未找到维度: {args.dim}")
            sys.exit(1)
        # 简化输出
        out_dir = out / datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)
        results = [run_task(t) for t in tasks]
        summary = _build_summary(results, out_dir)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        _print_summary(summary)
    else:
        run_all(suite, out)
