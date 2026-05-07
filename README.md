# 牛马 (Niuma)

> 闲置的 2GB 云服务器 + 用不完的弱模型 token 套餐 = 一个 AI 开发团队

[English](README.md) | [中文](README.zh-CN.md)

---

我有一台阿里云 2GB Ubuntu 服务器，跑什么都不够，闲置着吃灰。手上有几个便宜的
弱模型 API token 套餐（MiniMax、DeepSeek），额度用不完。还有一个强模型 token
套餐，够聪明但贵，舍不得随便烧。

**牛马就是把这些闲置资源拼成一个能干活的东西。** 强模型当架构师——把自然语言需求
编译成带类型约束的任务 DAG，一次性调用，不再参与执行。弱模型当码农——填空、跑测试、
看报错、修 bug，反复试错直到全绿。强模型最后当审查员，检查产物。核心原则就一条：
**每种模型做自己最擅长的事，在垃圾硬件的物理极限内。**

## 为什么不是 AutoGPT / MetaGPT / CrewAI

现有 AI Agent 框架默认资源富足——最低 16GB 内存，token 预算不设限。牛马反其道而行：
2GB 服务器、弱模型 API 套餐、以及一个信念——**好货能从垃圾硬件里跑出来**。

**学术界和工业界没人尝试低于 16GB 的多 Agent 系统。** 牛马探索的是 AI Agent 编排内核的物理下限。

## Architecture

```
User: "implement a thread-safe LRU cache"
            │
            ▼
     ┌─────────────┐
     │  compiler.py │  Strong model (once): task → typed DAG JSON
     └──────┬──────┘
            │ DAG (nodes with contracts + tests)
            ▼
     ┌─────────────┐
     │   worker.py  │  Weak model loop: generate → test → fix → retry
     │  (sandbox)   │  Subprocess isolation with resource limits
     └──────┬──────┘
            │ all nodes pass
            ▼
     ┌─────────────┐
     │ reviewer.py  │  Strong model (once): audit → PASS/FAIL
     └──────┬──────┘
            │ PASS
            ▼
     ┌─────────────┐
     │  outputs/    │  Final code + metrics
     └─────────────┘
```

Each DAG node carries a **function signature** (typed inputs/outputs), a **contract** (pre/post conditions
and invariants), and a **test skeleton** that the weak model must satisfy. The weak model never needs to
understand the overall task — it only fills in typed blanks.

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+ (for TypeScript sandbox execution)
- An LLM API key (OpenAI-compatible endpoint)

### Setup

```bash
git clone https://github.com/ai-dev-dot/niuma.git
cd niuma
./niuma
```

That's it. The first run auto-installs dependencies, then opens the menu:

```
  ==================================================
  牛马 Niuma
  ==================================================
  1. 配置强模型 | Configure Strong Model
  2. 配置弱模型 | Configure Weak Model
  3. 管理项目 | Manage Projects
  4. 退出 | Exit
```

From the menu, pick a provider (9 vendors supported: OpenAI, DeepSeek, Groq,
OpenRouter, SiliconFlow, ZhipuAI, DashScope, MiniMax, Moonshot/Kimi),
enter your API key, and you're done. Base URL and model list are auto-filled.

### Verify

```bash
python main.py --doctor     # Check prerequisites (Python, Node.js, model config)
python main.py --dry-run    # Dry-run with mocked APIs to verify pipeline structure
```

### Test

```bash
python -m pytest system_tests/ -v
```

## Project Structure

```
niuma/
  cli.py               # Interactive TUI menu (entry point)
  config.py             # Strong/weak model configuration management
  project_manager.py    # Project create/open/delete + git credential setup
  compiler.py           # Strong model: natural language → typed DAG JSON
  worker.py             # Weak model: code gen → compile check → sandbox → fix → retry
  reviewer.py           # Strong model: structured JSON contract compliance audit
  sandbox.py            # Subprocess execution with resource limits
  llm.py                # OpenAI-compatible API client (exponential backoff)
  metrics.py            # JSONL metrics output
  models.py             # Shared dataclasses (DAGNode, SandboxResult, ...)
  main.py               # Pipeline orchestrator (compile → execute → review)
  benchmark.py           # Weak model capability benchmark (18 real-app tasks)
  task_suite/            # Benchmark task definitions (6 dimensions × 3 levels)
  dag_schema.json       # JSON Schema for DAG validation
  requirements.txt      # Python dependencies (pytest, flask, requests)
  niuma                 # One-command launcher (bash) — auto-installs deps
  niuma.bat             # One-command launcher (Windows)
  system_tests/         # pytest suite (34 tests)
  docs/                 # Design docs, test plans, and user guides
```

## Language Strategy

The orchestration kernel is written in **Python**. Generated code targets **TypeScript** by default
(Python also supported). The `signature.language` field on each DAG node selects the runtime.
Adding a new language means implementing a new sandbox runtime handler — the compiler and reviewer
don't need to change.

## Status

v0.4.0 — 34 system tests passing. Conversational requirement clarification, git-driven
architecture, configurable retry limits, and git credential auto-setup are all implemented.
A 18-task benchmark suite measures weak model capability across 6 real-world dimensions.
The compiler → worker → reviewer loop runs end-to-end with real LLMs.
`./niuma` → configure models → new task to get started.

## Docs

- [Design doc](docs/design-20260505.md) — DAG specification, 2 GB verification stack, tool strategy, fault recovery
- [User guide](docs/user-guide.md) — complete workflow, project management, git credential setup
- [Benchmark design](docs/superpowers/specs/2026-05-07-weak-model-benchmark-design.md) — weak model capability measurement

## License

MIT — see [LICENSE](LICENSE).
