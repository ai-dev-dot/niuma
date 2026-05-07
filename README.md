# 牛马 (Niuma)

> Squeeze every idle hardware resource. Waste not a single token.

[English](README.md) | [中文](README.zh-CN.md)

---

**Niuma** is a compiler-driven AI task orchestration system that runs on resource-constrained hardware.
A strong LLM acts as a **compiler** — it translates natural language tasks into typed, verifiable DAGs once.
A fleet of cheap, weak LLMs act as **workers** — they fill in the blanks, run tests, fix failures, and iterate
until every contract is satisfied. The strong model only re-engages as a **reviewer**, checking the final output.

The core idea: strong models are expensive per token but smart. Weak models are cheap enough
to burn on trial-and-error loops, and their real constraint is the **2 GB deployment environment** —
not intelligence (they're API-called, Haiku/Flash tier). Niuma splits the work so each model
does what it's best at, within the physical limits of trash hardware.

## Why

Existing AI agent frameworks (AutoGPT, MetaGPT, CrewAI) assume resource abundance — 16 GB RAM minimum,
unbounded token budgets, cloud-scale LLMs. Niuma is designed for the opposite: a 2 GB Ubuntu server,
a leftover weak-model API subscription, and the belief that good things can come from trash hardware.

**No one in the literature is attempting sub-16 GB multi-agent systems.** Niuma explores the physical
lower bound of an AI agent orchestration kernel.

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
