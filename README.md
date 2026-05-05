# 牛马 (Niuma)

> Squeeze every idle hardware resource. Waste not a single token.

[English](README.md) | [中文](README.zh-CN.md)

---

**Niuma** is a compiler-driven AI task orchestration system that runs on resource-constrained hardware.
A strong LLM acts as a **compiler** — it translates natural language tasks into typed, verifiable DAGs once.
A fleet of cheap, weak LLMs act as **workers** — they fill in the blanks, run tests, fix failures, and iterate
until every contract is satisfied. The strong model only re-engages as a **reviewer**, checking the final output.

The core idea: strong models are expensive per token but smart. Weak models are dumb but cheap enough
to burn on trial-and-error loops. Niuma splits the work so each model does what it's best at.

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
cp .env.example .env
# Edit .env with your API key and model names
```

### Run

```bash
python main.py tasks/lru-cache.tsk
# or inline:
python main.py --inline "implement a thread-safe LRU cache in TypeScript"
```

### Test

```bash
pip install pytest
python -m pytest system_tests/ -v
```

## Project Structure

```
niuma/
  main.py             # CLI entry point + pipeline orchestrator
  compiler.py          # Strong model: natural language → typed DAG JSON
  worker.py            # Weak model: generate → sandbox → fix → retry loop
  reviewer.py          # Strong model: contract compliance audit
  sandbox.py           # Subprocess execution with resource limits
  llm.py               # OpenAI-compatible API client (exponential backoff)
  metrics.py           # JSONL metrics output
  models.py            # Shared dataclasses (DAGNode, SandboxResult, ...)
  dag_schema.json      # JSON Schema for DAG validation
  tasks/               # Example task descriptions (.tsk files)
  system_tests/        # pytest suite (29 tests)
  docs/                # Design docs and test plans
```

## Language Strategy

The orchestration kernel is written in **Python**. Generated code targets **TypeScript** by default
(Python also supported). The `signature.language` field on each DAG node selects the runtime.
Adding a new language means implementing a new sandbox runtime handler — the compiler and reviewer
don't need to change.

## Status

Prototype — 29 system tests passing. The compiler → worker → reviewer loop is functional with
mocked API calls. To run end-to-end with real LLMs, configure your `.env` file.

## License

MIT — see [LICENSE](LICENSE).
