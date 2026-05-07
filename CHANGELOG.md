# Changelog

## 0.4.0 (2026-05-07)

### Engineering Quality

- **Compile-check replaces self-check:** the worker no longer asks the weak model "is your code OK?"
  (a gate that never failed). Instead, generated code is compile-checked through the sandbox
  (`py_compile` / `tsc --noEmit`) — zero additional API tokens, zero false positives.
- **Downstream retry on review FAIL:** when the reviewer rejects a node, all dependent
  downstream nodes are now re-executed with the updated context — no more stale integration.
- **Structured reviewer output:** reviewer now outputs `{"verdict": "PASS"/"FAIL", ...}` JSON.
  Eliminates fragile regex-based PASS/FAIL parsing.
- **Configurable early abort:** if the ratio of failed nodes exceeds a threshold
  (`early_abort_fail_ratio`, default 0.6), remaining nodes are skipped to save tokens.
- **Full pipeline integration tests:** 4 new tests cover the complete compiler→worker→reviewer
  loop including review retry, compilation failure cleanup, and early abort. 34 tests total.

### Developer Experience

- **Git credential auto-setup:** when creating a project, the TUI auto-detects HTTPS vs SSH,
  guides you through credential setup, and seeds credentials via `git credential approve`.
  Strong and weak models can now push without manual intervention.
- **`--doctor` now checks:** git credential helper, SSH keys, curl, jq, sqlite3.
- **Tool strategy implemented:** built-in tools (pytest, flask, requests, curl, jq, sqlite3)
  documented in `requirements.txt`. Weak models can install additional packages with
  environment-aware pre-flight checks.

### Benchmark Suite

- **18 real-world application tasks** across 6 dimensions (code generation, test generation,
  error diagnosis, code fixing, code review, output verification). Every task is a real app
  (CLI tool, API endpoint, data processor) — not an algorithm exercise.
- **5 judge methods** adapted for 2 GB: CLI subprocess, API server + curl, keyword match,
  sandbox test, file output comparison. No browser required.

## 0.3.0 (2026-05-06)

### Core Engine

- **Conversational requirement clarification:** describe what you want in plain language.
  The strong model asks one question at a time to nail down the details, then produces a
  confirmed requirement summary before compiling the DAG.
- **Git-driven architecture:** components exchange data via git commits, not in-memory
  objects. Each step reads from git, does its work, commits, and calls the next component.
  The pipeline is recoverable from any crash — git is the single source of truth.
- **Configurable retry limits:** all hardcoded retry counts moved to `~/.niuma/config.json`
  under `retry_limits`. Tune `compiler_schema_validation`, `reviewer_rounds`,
  `worker_code_extraction`, `clarify_rounds`, and `llm_api_max_retries` to match your models.

### User Experience

- **No more .tsk files:** you no longer write task files by hand. Start a new task from the
  TUI, describe what you want, and let the strong model clarify through conversation.
- **LLM timeout to 5 minutes:** increased from 2 minutes to handle slow models like MiniMax.
- **Full API logging:** every LLM call is recorded in `.niuma/logs/` with complete
  prompts and responses for debugging.
- **Human-readable git commits:** requirement and review commits now include task
  summaries instead of opaque IDs. `review.md` always shows the model's full review
  text, not just PASS/FAIL. Git log tells the whole story at a glance.

## 0.2.0 (2026-05-05)

### Core Engine

- **Verbose mode:** `python main.py --verbose` shows each pipeline step in detail —
  compiler DAG structure, worker iterations with pass/fail, reviewer verdict
- **Robust worker:** weak model self-checks code before sandbox, regenerates on bad
  extraction, language-aware prompt (TypeScript / Python)
- **Compiler improvements:** few-shot example prompt for reliable JSON output,
  multi-layer response parsing (think blocks, markdown fences, type coercion)

### User Experience

- **Git management in TUI:** view commit history and push task branches from project menu
- **Pipeline logs:** `.niuma/logs/<date>_<task>.jsonl` records every API call
  (model, tokens, duration, preview) for audit and debugging
- **DeepSeek presets:** deepseek-v4-pro as primary strong model

## 0.1.0 (2026-05-05)

Initial prototype release.

### Core Engine

- Compiler: strong model translates natural language tasks into typed DAG JSON with schema validation
- Worker: weak model generates code in a sandbox, runs tests, reads errors, fixes, and retries
- Reviewer: strong model audits all node outputs, returns PASS/FAIL with specific suggestions
- Sandbox: subprocess execution with resource limits, supports TypeScript (Jest) and Python (pytest)
- Git protocol: strong-weak model communication via `niuma/<task-id>` branches — compiler commits DAG, worker commits code, reviewer commits verdict

### User Experience

- **One-command setup:** `./niuma` auto-installs dependencies and opens the TUI menu
- **Provider presets:** 9 vendors pre-configured — pick a provider, enter your API key, done
  - OpenAI, DeepSeek, Groq, OpenRouter, SiliconFlow, ZhipuAI, DashScope, MiniMax, Kimi
- **Project management:** create/open/delete projects backed by git repositories
- **Quick configure:** test connection button to verify API credentials
- `--doctor` checks all prerequisites, `--dry-run` validates pipeline structure with mocks

### In the Box

- 29 system tests covering compiler, worker, sandbox, reviewer, and models
- Bilingual README (English + 中文) and design documentation
- Windows and Linux support (bash + bat launchers)
