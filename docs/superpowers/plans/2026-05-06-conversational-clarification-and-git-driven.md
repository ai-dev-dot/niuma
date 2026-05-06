# Conversational Requirement Clarification & Git-Driven Architecture

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace .tsk files with conversational requirement clarification in TUI, and refactor the pipeline to use git as the primary data exchange between components (not in-memory objects).

**Architecture:** cli.py drives a Q&A loop with the strong model to clarify requirements, then writes the confirmed summary as .niuma/requirement.md. Each pipeline component reads from git/filesystem, does its work, commits output, and calls the next component. main.py becomes a thin entry point. All retry limits are configurable in config.json.

**Tech Stack:** Python 3.10+, urllib (existing LLM client), git (existing project_manager)

---

### Task 1: Add configurable retry limits to config.py

**Files:**
- Modify: `config.py:12-23` (DEFAULT_CONFIG)

- [ ] **Step 1: Add retry_limits to DEFAULT_CONFIG**

```python
DEFAULT_CONFIG = {
    "strong": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "",
    },
    "weak": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "",
    },
    "retry_limits": {
        "clarify_rounds": 20,
        "compiler_schema_validation": 5,
        "worker_code_extraction": 5,
        "reviewer_rounds": 5,
        "llm_api_max_retries": 3,
    },
}
```

- [ ] **Step 2: Add get_retry_limits() function**

Add after `get_model_config()`:

```python
def get_retry_limits() -> dict:
    """获取所有重试/轮次限制配置，缺失字段使用默认值。"""
    config = get_config()
    defaults = DEFAULT_CONFIG["retry_limits"]
    limits = config.get("retry_limits", {})
    return {key: limits.get(key, defaults[key]) for key in defaults}
```

- [ ] **Step 3: Run existing tests to verify nothing broke**

```
cd D:/APP/niuma && python -m pytest system_tests/ -v -x
```
Expected: all 29 tests pass

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "feat: add configurable retry limits via config.get_retry_limits()"
```

---

### Task 2: Refactor compiler.py — add clarify_step and compile_from_git

**Files:**
- Modify: `compiler.py`

- [ ] **Step 1: Add import for config and pathlib at top of compiler.py**

```python
"""编译器 —— 强模型将自然语言任务描述编译为 DAG JSON，含 Schema 校验和重试。"""

import json
import re
from pathlib import Path

import config as _cfg
import llm
from models import DAG, Contract, DAGNode, FunctionSignature
```

- [ ] **Step 2: Add clarify_step() function**

Insert after the imports and before `compile_task()`:

```python
CLARIFY_SYSTEM = """你是一个需求分析器。用户描述了想做的功能。你的任务是帮他把需求澄清到足够编译的程度。

规则：
- 每次只问一个最关键的问题。不要一次问多个。
- 如果用户表示"够了"、"开始吧"、"不用再问了"之类的意图，不要再追问，直接输出需求摘要。
- 如果需求已经足够清晰，直接输出需求摘要。

输出格式（严格的 JSON，不要加任何其他文字）：
- 如果还有疑问：{"type": "question", "question": "你的问题"}
- 如果已清晰：{"type": "summary", "summary": "结构化需求描述..."}

问题应该聚焦在：功能边界、数据类型、约束条件、使用场景。"""


def clarify_step(history: list[dict]) -> dict:
    """调用强模型，根据对话历史返回下一步: {"type": "question", "question": "..."}
    或 {"type": "summary", "summary": "..."}。"""
    # 构建 messages: system + history
    messages = [{"role": "system", "content": CLARIFY_SYSTEM}]
    for entry in history:
        role = entry["role"]
        content = entry["content"]
        messages.append({"role": role, "content": content})

    resp = llm.call_strong_messages(messages, max_tokens=800)

    # 解析 JSON 响应
    text = resp.content.strip()
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = text.strip()
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        text = m.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 容错：如果模型返回的不是纯 JSON，尝试判断意图
        if any(kw in text for kw in ["确认", "摘要", "总结", "SUMMARY", "summary", "以下"]):
            return {"type": "summary", "summary": text}
        # 否则视为一个问题
        return {"type": "question", "question": text.strip().split("\n")[0]}
```

- [ ] **Step 3: Add call_strong_messages() to llm.py**

This compiler step needs a new LLM function that accepts raw messages. Let me add it.

First, read `llm.py` around the `call_strong` and `call` functions:

```python
# In llm.py, add after call_weak():
def call_strong_messages(messages: list[dict], max_tokens: int = 0) -> LLMResponse:
    """直接传 messages 调用强模型（用于对话式需求澄清）。"""
    cfg = _config.get_model_config("strong")
    return call(
        prompt="",  # not used when messages is passed
        system="",  # not used
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        max_tokens=max_tokens,
        messages=messages,
    )
```

Wait — the current `call()` function takes `prompt` and `system` and builds messages internally. We need to add a `messages` parameter. Let me check the call signature.

Actually, looking at llm.py, the `call()` function builds messages from `system` and `prompt`. Let me add a `messages` kwarg that overrides this:

```python
def call(*, prompt: str, system: str = "", model: str = "", api_key: str = "",
         base_url: str = "", max_tokens: int = 0, temperature: float = 0.2,
         max_retries: int = None, messages: list[dict] = None, **kwargs) -> LLMResponse:
```

And in the body:
```python
    if messages is None:
        # existing logic that builds messages from system + prompt
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
    # rest of the function uses messages variable
```

- [ ] **Step 3: Add compile_from_git() function**

```python
def compile_from_git(repo_path: str, task_id: str, verbose: bool = False) -> DAG:
    """从 git 读取 requirement.md，编译为 DAG，commit dag.json 到 git。
    返回 DAG 对象供调用者决定下一个节点。（调用者负责调 worker）"""
    req_path = Path(repo_path) / ".niuma" / "requirement.md"
    if not req_path.exists():
        raise FileNotFoundError(f"requirement.md 不存在: {req_path}")

    requirement = req_path.read_text(encoding="utf-8")
    return compile_task(requirement, verbose=verbose)
```

- [ ] **Step 4: Make schema validation retries use config**

In `compile_task()`, replace hardcoded `range(2)`:

```python
def compile_task(task_description: str, verbose: bool = False) -> DAG:
    limits = _cfg.get_retry_limits()
    max_tries = limits["compiler_schema_validation"]

    if verbose:
        print("  [强模型] 正在分析任务并分解为 DAG...")

    dag_json_str = _call_compiler(task_description)

    for attempt in range(max_tries):
        dag = _parse_dag(dag_json_str)
        errors = _validate_dag(dag)
        if not errors:
            if verbose:
                print(f"  [强模型] DAG 编译完成: {len(dag.nodes)} 个节点")
                for i, node in enumerate(dag.nodes, 1):
                    deps = f" (依赖: {', '.join(str(d) for d in node.dependencies)})" if node.dependencies else ""
                    print(f"    节点{i}: {node.node_id} — {node.name}{deps}")
                    print(f"      语言: {node.signature.language}, 最多{node.max_iterations}轮迭代")
            return dag
        if attempt < max_tries - 1:
            dag_json_str = _call_compiler_retry(task_description, dag_json_str, errors)

    raise CompilationError(f"DAG Schema 校验失败（{max_tries} 次重试后）: {errors}")
```

Also update the error message at line 31 to use `max_tries`.

- [ ] **Step 5: Run compiler tests**

```
cd D:/APP/niuma && python -m pytest system_tests/test_compiler.py -v
```
Expected: all compiler tests pass (the retry count change may break test_invalid_json_exhausts_retries — fix the test if needed)

- [ ] **Step 6: Commit**

```bash
git add compiler.py llm.py system_tests/test_compiler.py
git commit -m "feat: add clarify_step, compile_from_git; schema retries from config"
```

---

### Task 3: Add call_strong_messages and messages support to llm.py

**Files:**
- Modify: `llm.py`

- [ ] **Step 1: Add `messages` parameter to `call()` function**

Read the current `call()` signature and add `messages` parameter. In the function body, use the passed messages if provided, otherwise build from system+prompt as before.

Current call() signature (line ~55-73):
```python
def call(
    prompt: str,
    system: str = "",
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    max_tokens: int = 0,
    temperature: float = 0.2,
    max_retries: int = 3,
    **kwargs,
) -> "LLMResponse":
```

Change to:
```python
def call(
    prompt: str,
    system: str = "",
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    max_tokens: int = 0,
    temperature: float = 0.2,
    max_retries: int | None = None,
    messages: list[dict] | None = None,
    **kwargs,
) -> "LLMResponse":
```

In the body, around line 90 where body_data is built:
```python
    if max_retries is None:
        limits = _cfg.get_retry_limits()
        max_retries = limits["llm_api_max_retries"]

    if messages is None:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

    body_data = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
```

- [ ] **Step 2: Add call_strong_messages() function**

```python
def call_strong_messages(messages: list[dict], max_tokens: int = 0) -> "LLMResponse":
    """直接传 messages 调用强模型（用于对话式需求澄清等需要完整消息历史的场景）。"""
    cfg = _config.get_model_config("strong")
    return call(
        prompt="",
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        max_tokens=max_tokens,
        messages=messages,
    )
```

Also need to add `import config as _cfg` at the top of llm.py.

- [ ] **Step 3: Run a quick smoke test**

```
cd D:/APP/niuma && python -c "import llm; print('llm module loads OK')"
```

- [ ] **Step 4: Commit**

```bash
git add llm.py
git commit -m "feat: llm.call() accepts pre-built messages, add call_strong_messages()"
```

---

### Task 4: Refactor worker.py — execute_from_git, configurable extraction retries

**Files:**
- Modify: `worker.py`

- [ ] **Step 1: Add import for config**

```python
import config as _cfg
```

- [ ] **Step 2: Make code extraction retries use config**

In `_generate_and_extract()`, replace `for retry in range(3):` and related `retry < 2`:

```python
def _generate_and_extract(node: DAGNode, context: dict[str, str], previous: NodeResult, review_feedback: str = "", verbose: bool = False) -> str:
    """生成代码并提取。如果提取结果不像代码，让弱模型重新输出。"""
    lang = node.signature.language
    code_fence = "python" if lang == "python" else "typescript"
    limits = _cfg.get_retry_limits()
    max_tries = limits["worker_code_extraction"]

    for retry in range(max_tries):
        resp = _call_weak_model(node, context, previous, review_feedback)
        code = _extract_code(resp.content)

        if _looks_like_code(code, lang):
            return code

        if verbose and retry > 0:
            print(f"    [弱模型] 第{retry}次提取失败，重新请求...")
        if retry < max_tries - 1:
            review_feedback = (
                f"你上一次的回复格式不正确——包含了太多解释文字，或者代码没有正确包裹在 "
                f"```{code_fence} 代码块中。\n"
                f"请重新输出：只输出一个 ```{code_fence} 代码块，里面放完整代码。"
            )
            previous = NodeResult(node_id=node.node_id)

    return ""
```

- [ ] **Step 3: Add execute_from_git() function**

Add at the end of worker.py:

```python
def execute_from_git(repo_path: str, node_id: str | None = None, task_id: str = "",
                     review_feedback: str = "", verbose: bool = False) -> NodeResult | None:
    """从 git 读取 dag.json，执行指定节点（或第一个未完成节点）。
    生成代码，commit src/<node_id>.ts，调下一个节点或调 reviewer。
    
    返回 NodeResult（如果还有下一个节点，则已经自动调用了；返回 None 表示全部完成）。"""
    import project_manager as _pm
    dag_path = Path(repo_path) / ".niuma" / "dag.json"
    if not dag_path.exists():
        raise FileNotFoundError(f"dag.json 不存在: {dag_path}")

    # 读取 DAG
    dag = _read_dag_from_file(dag_path)
    if dag is None:
        raise RuntimeError("无法解析 dag.json")

    # 找到要执行的节点
    if node_id:
        nodes_to_run = [n for n in dag.nodes if n.node_id == node_id]
    else:
        # 默认取第一个
        nodes_to_run = dag.nodes[:1]

    if not nodes_to_run:
        return None

    node = nodes_to_run[0]

    # 读已完成节点的代码作为 context
    completed_context = _read_completed_code(repo_path, dag)

    # 执行节点
    nr = execute_node(node, completed_context, task_id=task_id, review_feedback=review_feedback, verbose=verbose)

    if nr.status == NodeStatus.PASSED:
        commit_node(node, nr, repo_path)
        if verbose:
            print(f"    >>> git commit: src/{node.node_id}.ts ({_pm.GIT_AUTHOR_WORKER[0]} → Weak Model)")

    # 找下一个待执行节点
    passed_ids = {n.node_id for n in dag.nodes if (Path(repo_path) / "src" / f"{n.node_id}.ts").exists()}
    pending = [n for n in dag.topological_order() if n.node_id not in passed_ids]

    return NodeResult(node_id=node.node_id)  # placeholder for caller
```

Actually, wait — the chain-calling design needs more thought. The spec says "worker calls next worker, then reviewer". But in the current prototype, we're still on a single machine. Let me simplify: for now, `execute_from_git` handles one node and returns its result. The orchestration (calling the next node or reviewer) stays in main.py/cli.py. The key change is that everything reads from git/filesystem, not from passed memory objects.

Let me REDO this step:

- [ ] **Step 3: Add helper functions for reading from git**

```python
def _read_dag_from_file(repo_path: str) -> DAG | None:
    """从文件系统读取 dag.json 并解析为 DAG 对象。"""
    import json as _json
    dag_file = Path(repo_path) / ".niuma" / "dag.json"
    if not dag_file.exists():
        return None
    try:
        data = _json.loads(dag_file.read_text(encoding="utf-8"))
        return _json_to_dag(data)
    except (json.JSONDecodeError, KeyError):
        return None


def _json_to_dag(data: dict) -> DAG:
    """将 dag.json 的 dict 转回 DAG 对象。（复用 compiler._parse_dag 中的逻辑）"""
    from compiler import _parse_dag as _pd
    import json as _json
    return _pd(_json.dumps(data))


def _read_completed_code(repo_path: str, dag: DAG) -> dict[str, str]:
    """读取已通过节点的代码。"""
    context: dict[str, str] = {}
    for node in dag.nodes:
        ext = "ts" if node.signature.language == "typescript" else "py"
        code_file = Path(repo_path) / "src" / f"{node.node_id}.{ext}"
        if code_file.exists():
            context[node.node_id] = code_file.read_text(encoding="utf-8")
    return context
```

- [ ] **Step 4: Run worker tests**

```
cd D:/APP/niuma && python -m pytest system_tests/test_worker.py -v
```
Expected: all worker tests pass

- [ ] **Step 5: Commit**

```bash
git add worker.py
git commit -m "feat: worker uses configurable retries, add git-based helpers"
```

---

### Task 5: Refactor reviewer.py — review_from_git, configurable review rounds

**Files:**
- Modify: `reviewer.py`

- [ ] **Step 1: Add import for config**

```python
import config as _cfg
from pathlib import Path
```

- [ ] **Step 2: Add review_from_git() function**

```python
def review_from_git(repo_path: str, task_id: str, verbose: bool = False) -> ReviewResult:
    """从 git 读取所有节点产物，审核，commit review.md。"""
    # 读取 dag.json
    dag_file = Path(repo_path) / ".niuma" / "dag.json"
    if not dag_file.exists():
        raise FileNotFoundError(f"dag.json 不存在: {dag_file}")

    import json as _json
    from compiler import _parse_dag

    dag = _parse_dag(_json.dumps(_json.loads(dag_file.read_text(encoding="utf-8"))))

    # 读取 requirement.md 作为 task_description
    req_file = Path(repo_path) / ".niuma" / "requirement.md"
    task_desc = req_file.read_text(encoding="utf-8") if req_file.exists() else ""

    # 构建 node_results（收集已通过节点的代码和测试输出）
    node_results = _collect_node_results(repo_path, dag)

    return review(task_desc, dag, node_results, verbose=verbose)


def _collect_node_results(repo_path: str, dag: DAG) -> list:
    """从文件系统收集所有节点的执行结果。"""
    from models import NodeResult, NodeStatus

    results = []
    for node in dag.nodes:
        ext = "ts" if node.signature.language == "typescript" else "py"
        code_file = Path(repo_path) / "src" / f"{node.node_id}.{ext}"

        nr = NodeResult(node_id=node.node_id)
        if code_file.exists():
            nr.status = NodeStatus.PASSED
            nr.generated_code = code_file.read_text(encoding="utf-8")
            nr.iteration_count = 1  # 从文件系统无法得知具体迭代数，近似
        else:
            nr.status = NodeStatus.FAILED
            nr.test_output = "文件不存在 | file not found"
        results.append(nr)
    return results
```

- [ ] **Step 3: Run reviewer tests**

```
cd D:/APP/niuma && python -m pytest system_tests/test_reviewer.py -v
```
Expected: tests pass

- [ ] **Step 4: Commit**

```bash
git add reviewer.py
git commit -m "feat: reviewer review_from_git reads from filesystem"
```

---

### Task 6: Simplify main.py — start_pipeline()

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Rename run_task to start_pipeline and simplify**

Replace the monolithic `run_task()` function with a simplified version that:
1. Creates the task branch
2. Writes requirement.md
3. Sets up logging
4. Calls compiler, then worker chain, then reviewer

Keep the existing logic but restructure to read from/write to git between steps.

The `start_pipeline` function should take the confirmed requirement summary (from the clarification phase) and the repo path:

```python
def start_pipeline(repo_path: str, confirmed_requirement: str, task_id: str = "", verbose: bool = False) -> bool:
    """入口：创分支，写 requirement.md，调 compiler，再链式调 worker → reviewer。
    返回 True 表示任务成功通过审核。"""
    import project_manager as _pm
    from config import get_model_config, get_retry_limits
    from pathlib import Path as _Path
    import json as _json
    import datetime as _dt

    base = _Path(repo_path)
    if not task_id:
        task_id = str(uuid.uuid4())[:8]
    t_total = time.time()

    # 日志
    log_dir = base / ".niuma" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    import llm as _llm
    log_file = log_dir / f"{_dt.date.today().isoformat()}_{task_id}.jsonl"
    _llm.set_log_path(str(log_file))

    def _write_log(entry: dict) -> None:
        entry["ts"] = _dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")

    _llm.set_log_callback(_write_log)
    _write_log({"role": "pipeline", "action": "start", "task_desc": confirmed_requirement[:200]})

    # 显示信息
    strong_cfg = get_model_config("strong")
    weak_cfg = get_model_config("weak")
    if verbose:
        print()
        print(f"  ╔{'═'*60}╗")
        print(f"  ║  Niuma Pipeline — {task_id}")
        print(f"  ║  强模型: {strong_cfg['model']} @ {strong_cfg['base_url']}")
        print(f"  ║  弱模型: {weak_cfg['model']} @ {weak_cfg['base_url']}")
        print(f"  ╚{'═'*60}╝")
        print()

    # 1. 创建分支
    try:
        branch = _pm.create_task_branch(base, task_id)
        if verbose:
            print(f"  >>> git checkout -b {branch}")
    except RuntimeError as e:
        print(f"[{task_id}] X 创建分支失败: {e}")
        return False

    # 2. 写 requirement.md
    _pm.commit_file(
        str(base), ".niuma/requirement.md", confirmed_requirement,
        _pm.GIT_AUTHOR_COMPILER, f"cli: requirement confirmed for {task_id}",
    )
    _write_log({"role": "cli", "action": "requirement_confirmed"})
    if verbose:
        print(f"  >>> git commit: .niuma/requirement.md")

    # 3. 编译
    if verbose:
        print(f"  ╔═ STEP 1: 强模型编译 ═╗")
    try:
        _llm.set_meta({"role": "compiler", "task_id": task_id})
        dag = compiler.compile_task(confirmed_requirement, verbose=verbose)
    except (compiler.CompilationError, RuntimeError) as e:
        print(f"[{task_id}] X 编译失败: {e}")
        _pm.switch_branch(base, "main")
        _pm.git_run(base, ["branch", "-D", branch], check=False)
        return False

    compiler.commit_dag(dag, str(base), task_id)
    _write_log({"role": "compiler", "action": "done", "dag_nodes": len(dag.nodes)})
    if verbose:
        print(f"  >>> git commit: .niuma/dag.json ({_pm.GIT_AUTHOR_COMPILER[0]} → Strong Model)")

    # 4. Worker（链式，每个节点读 git）
    limits = get_retry_limits()
    if verbose:
        print(f"  ╔═ STEP 2: 弱模型执行 ═╗")

    node_results: list[NodeResult] = []
    completed_context: dict[str, str] = {}

    for i, node in enumerate(dag.topological_order(), 1):
        if verbose:
            print(f"  节点{i}/{len(dag.nodes)}: {node.node_id} — {node.name}")
        nr = worker.execute_node(node, completed_context, task_id=task_id, verbose=verbose)
        node_results.append(nr)

        if nr.status == NodeStatus.PASSED:
            completed_context[node.node_id] = nr.generated_code
            ext = "ts" if node.signature.language == "typescript" else "py"
            _save_output(base, task_id, node, nr)
            worker.commit_node(node, nr, str(base))
            if verbose:
                print(f"    >>> git commit: src/{node.node_id}.{ext} ({_pm.GIT_AUTHOR_WORKER[0]} → Weak Model)")
        else:
            if verbose:
                print(f"    [FAIL] {node.node_id} 未通过")
            # 仍然尝试继续其他节点（无依赖的）

    # 5. Reviewer
    if verbose:
        print(f"  ╔═ STEP 3: 强模型审核 ═╗")

    review_passes = False
    max_review_rounds = limits["reviewer_rounds"]

    for review_round in range(1, max_review_rounds + 1):
        if verbose:
            print(f"  审核轮次 {review_round}/{max_review_rounds}...")
        _llm.set_meta({"role": "reviewer", "task_id": task_id})
        rv = reviewer.review(confirmed_requirement, dag, node_results, verbose=verbose)
        reviewer.commit_review(rv, str(base), task_id)

        if rv.passed:
            review_passes = True
            _write_log({"role": "reviewer", "action": "done", "verdict": "PASS", "round": review_round})
            break

        # FAIL: 回传 worker
        _write_log({"role": "reviewer", "action": "retry", "verdict": "FAIL", "round": review_round})
        for node in dag.nodes:
            if node.node_id in rv.failed_nodes:
                if verbose:
                    print(f"    重做: {node.node_id}...")
                nr = worker.execute_node(node, completed_context, task_id=task_id, review_feedback=rv.suggestions, verbose=verbose)
                for j, old in enumerate(node_results):
                    if old.node_id == node.node_id:
                        node_results[j] = nr
                        break
                if nr.status == NodeStatus.PASSED:
                    completed_context[node.node_id] = nr.generated_code
                    _save_output(base, task_id, node, nr)
                    worker.commit_node(node, nr, str(base))

    # 6. 汇总
    passed_count = sum(1 for nr in node_results if nr.status == NodeStatus.PASSED)
    total_time = time.time() - t_total

    entry = MetricsEntry(...)  # (keep existing metrics logic)
    metrics.record(entry, output_dir=str(base / "outputs"))
    metrics.print_summary(entry)

    if review_passes:
        print(f"[{task_id}] [OK] 产物: {base / 'outputs' / task_id}/")
        print(f"[{task_id}] 分支 {branch} 就绪，审阅后 push")
    else:
        print(f"[{task_id}] X 审核 {max_review_rounds} 轮未通过")

    _write_log({"role": "pipeline", "action": "done", "passed": review_passes, "total_s": round(total_time, 1)})
    return review_passes
```

Note: This function is essentially the current `run_task()` but with the `requirement.md` write step added at the beginning and configurable review rounds. The git-driven aspect is that each component writes its output via git commit.

- [ ] **Step 2: Keep _cmd_run and --inline path working**

The `_cmd_run` function should call `start_pipeline` directly (no clarification phase).
The existing `run_task` function name should be kept as an alias for backward compatibility or renamed to `start_pipeline`.

Add alias:
```python
run_task = start_pipeline  # backward compatibility
```

- [ ] **Step 3: Run system tests**

```
cd D:/APP/niuma && python -m pytest system_tests/ -v -x
```

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "refactor: main.py start_pipeline writes requirement.md; configurable review rounds"
```

---

### Task 7: Add conversational clarification to cli.py

**Files:**
- Modify: `cli.py`

- [ ] **Step 1: Add _clarify_and_run() function**

Add before `_run_task_in_project`:

```python
def _clarify_and_run(project: dict) -> None:
    """对话式需求澄清 + 运行。"""
    import compiler as _compiler
    import main as _main
    import project_manager as _pm
    from config import get_retry_limits

    proj_path = _pm.get_project_path(project["name"])
    if not proj_path:
        print(f"  [!!] 项目路径不存在")
        _wait()
        return

    _clear()
    _title(f"新建任务 | New Task — {project['name']}")
    print("  请描述你想实现的功能（自然语言，像和人说话一样）:")
    print()

    initial = _ask_text("  > ")
    if not initial:
        return

    _clear()
    _title(f"需求澄清 | Requirement Clarification — {project['name']}")
    print(f"  你的描述: {initial[:100]}{'...' if len(initial) > 100 else ''}")
    print()
    print("  [强模型] 正在分析需求...")

    history = [{"role": "user", "content": initial}]
    limits = get_retry_limits()
    max_rounds = limits["clarify_rounds"]

    for round_num in range(1, max_rounds + 1):
        try:
            resp = _compiler.clarify_step(history)
        except Exception as e:
            print(f"\n  [!!] 强模型调用失败: {e}")
            print("  是否直接用当前描述开始编译？(Y/n)")
            if _ask("  > ", "Y").lower() in ("y", "yes", ""):
                break
            _wait()
            return

        if resp.get("type") == "summary" or "summary" in resp:
            summary = resp.get("summary", resp.get("content", str(resp)))
            # 展示需求确认摘要
            _clear()
            _title(f"需求确认 | Confirmation — {project['name']}")
            print(f"  [强模型] 已整理需求确认：")
            print()
            for line in summary.strip().split("\n"):
                print(f"  {line}")
            print()
            confirm = _ask("  确认无误？(Y/n)  (n=继续澄清)", "Y").lower()
            if confirm in ("y", "yes", ""):
                break
            else:
                history.append({"role": "user", "content": "还需要继续澄清"})
                continue

        # 是问题
        question = resp.get("question", str(resp))
        print(f"\n  Q: {question}")
        answer = _ask("  > ")
        if not answer:
            return
        history.append({"role": "assistant", "content": f"Q: {question}"})
        history.append({"role": "user", "content": answer})
    else:
        # 超限
        print(f"\n  已达最大澄清轮数 ({max_rounds})，使用最后一次结果编译。")

    # 确认后的 summary
    final_summary = resp.get("summary", "") if resp else initial

    print()
    print(f"  ✓ 需求已确认，开始编译...")
    print()

    # 调用 pipeline
    orig_dir = os.getcwd()
    try:
        os.chdir(str(proj_path))
        success = _main.start_pipeline(str(proj_path), final_summary, verbose=True)
    except Exception as e:
        os.chdir(orig_dir)
        print(f"  [!!] {e}")
        _wait()
        return

    # 显示 git 状态
    import project_manager as __pm
    current_branch = __pm.get_current_branch(proj_path)
    branches = __pm.list_task_branches(proj_path)
    os.chdir(orig_dir)

    print()
    if success:
        print(f"  [OK] 分支 {current_branch} 就绪，审阅后 push")
        print(f"  审阅: cd {proj_path} && git log --oneline {current_branch}")
        if branches:
            print(f"  niuma 任务分支: {', '.join(branches)}")
    else:
        print(f"  [!!] 分支 {current_branch} 保留供检查")
    print()
    _wait()
```

- [ ] **Step 2: Update project menu to use _clarify_and_run**

In `_project_menu`, change the menu items. Find the line with option "1" and change from `_run_task_in_project`:

```python
# Old:
# if choice == "1":
#     _run_task_in_project(project)

# New:
if choice == "1":
    _clarify_and_run(project)
```

And update the menu text. Find where it prints "1. 运行任务 | Run Task" and change to "1. 新建任务 | New Task".

Remove the "2. 新建任务文件 | New Task File" option (no more .tsk files).

The menu becomes:
```python
print("  1. 新建任务 | New Task")
print("  2. Git 提交记录 | Git Commits")
print("  D. 删除项目 | Delete Project")
print("  3. 返回 | Back")
```

And adjust the choice numbers:
```python
if choice == "1":
    _clarify_and_run(project)
elif choice == "2":
    _git_menu(project)
elif choice == "d":
    # delete project
    ...
elif choice == "3":
    return
```

- [ ] **Step 3: Remove _run_task_in_project and _create_task_file**

These functions are no longer needed in the TUI flow. Can be deleted or kept with deprecation warning.

Keep `_run_task_in_project` for potential reuse but remove from menu. Remove `_create_task_file`.

- [ ] **Step 4: Import os at top of cli.py if not already there**

Check that `import os` is at the top.

- [ ] **Step 5: Commit**

```bash
git add cli.py
git commit -m "feat: conversational requirement clarification in TUI"
```

---

### Task 8: Update system tests

**Files:**
- Modify: `system_tests/test_compiler.py` (retry count change)
- Modify: `system_tests/conftest.py` (if needed)

- [ ] **Step 1: Fix test_invalid_json_exhausts_retries**

The test currently expects 2 retries. With the new config default of 5, the test will have more retry attempts. Update the test to either:
a) Mock `get_retry_limits` to return `compiler_schema_validation: 2`
b) Or update the expected behavior for 5 retries

Option (a) is cleaner:

```python
def test_invalid_json_exhausts_retries(self):
    from unittest.mock import patch
    with patch('compiler._cfg.get_retry_limits', return_value={"compiler_schema_validation": 2}):
        with patch('compiler._call_compiler', return_value="not valid json at all {{{"):
            with pytest.raises(CompilationError, match="2 次重试"):
                compiler.compile_task("test", verbose=False)
```

- [ ] **Step 2: Run all tests**

```
cd D:/APP/niuma && python -m pytest system_tests/ -v
```
Expected: all 29 tests pass

- [ ] **Step 3: Commit**

```bash
git add system_tests/
git commit -m "test: update compiler retry test to mock config limits"
```

---

### Task 9: End-to-end manual test

- [ ] **Step 1: Verify config.json has retry_limits**

```
python -c "from config import get_retry_limits; print(get_retry_limits())"
```
Expected: `{'clarify_rounds': 20, 'compiler_schema_validation': 5, ...}`

- [ ] **Step 2: Verify --inline path still works**

```
cd D:/APP/test_space/niuma && python main.py --inline "实现一个 add(a,b) 函数" --verbose
```
Expected: skips clarification, compiles directly

- [ ] **Step 3: Verify doctor check passes**

```
python main.py --doctor
```

- [ ] **Step 4: Commit any final fixes**

---

### Implementation Order

```
Task 1 (config) → Task 3 (llm messages) → Task 2 (compiler) → Task 4 (worker)
                                                                    ↓
                                                               Task 5 (reviewer)
                                                                    ↓
                                                               Task 6 (main.py)
                                                                    ↓
                                                               Task 7 (cli.py)
                                                                    ↓
                                                               Task 8 (tests)
                                                                    ↓
                                                               Task 9 (manual e2e)
```

Tasks 1 and 3 are independent and can run in parallel.
Tasks 4 and 5 are independent after Task 2.
