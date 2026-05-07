# Niuma User Guide

## Product Philosophy

Niuma is a tool for **human-model collaborative coding**. Three sentences capture its core design:

1. **Project = Git repo** — Every project you create in Niuma is backed by a git repository. Git is the single source of truth — all work and communication flows through git.
2. **Models do the work** — A strong model first clarifies your requirements through conversation, then compiles them into an executable plan (DAG). A cheap weak model fills in the blanks, tests, and fixes bugs. The strong model does a final review. Components call each other directly after committing.
3. **You make the decisions** — Use the Git menu to inspect commit history, judge output quality, and decide whether to push or discard.

You're not "using AI to write code" — you're **managing an AI dev team**. Your job is to assign tasks, review results, and ship.

---

## Prerequisites

- Python 3.10+（Ubuntu 用 `python3`）
- Node.js 18+（TypeScript 沙箱需要）
- Git
- curl, jq, sqlite3（`sudo apt-get install -y curl jq sqlite3`）
- 至少配置一个强模型和一个弱模型 API（见下文）

详细安装步骤见 [2GB Ubuntu 安装指南](install-2gb-ubuntu.md)。首次运行 `./niuma` 会自动安装依赖并检查环境。

---

## Model Configuration

Configuration lives at `~/.niuma/config.json`:

```json
{
  "strong": {
    "model": "deepseek-v4-pro",
    "api_key": "sk-xxx",
    "base_url": "https://api.deepseek.com/v1"
  },
  "weak": {
    "model": "MiniMax-M2.7",
    "api_key": "sk-xxx",
    "base_url": "https://api.minimaxi.com/v1"
  }
}
```

- **Strong model**: Clarifies requirements, compiles tasks, and reviews results. Needs strong reasoning; tokens are expensive but used sparingly.
- **Weak model**: Writes code and fixes bugs. Needs to be cheap and have generous token limits for trial-and-error loops.

---

## Core Workflow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Create       │ → │  Assign task │ → │  Auto-execute│ → │  Review+Push │
│  project      │    │  (conversation)│  │  (unattended)│    │  (you decide)│
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

### 1. Create a Project

Launch the TUI: `./niuma`

From the main menu, select **N → New Project** and enter:
- Project name (any label you want)
- Git repository URL (e.g. `https://github.com/your-name/my-project.git`)
- HTTP proxy (leave blank if not needed)

The TUI clones the repo and the project is ready.

> **Design principle**: One project = one git repo. All model output lands as git commits. Git is the single source of truth for the entire system.

### 2. Assign a Task (Conversational Clarification)

Enter the project menu and select **1 → New Task**. Describe what you want to build in plain language — like talking to a colleague:

```
  What do you want to build?
  > Implement an LRU cache with get/put, O(1) time complexity
```

The strong model analyzes your description and asks one question at a time to fill in the gaps:

```
  Q: What types are the keys and values?
  > keys are strings, values can be anything

  Q: Do you need TTL expiration?
  > no
```

When you feel the requirements are clear enough, just say "let's start" or "that's enough." The strong model produces a confirmed requirement summary:

```
  [Strong model] Requirement summary:

  Implement an LRU (Least Recently Used) cache class.
  - key: string, value: any
  - get(key): returns value or null
  - put(key, value): stores key-value pair, evicts LRU item at capacity
  - Capacity: constructor parameter
  - Complexity: all operations O(1)
  - Language: TypeScript

  Confirm? (Y/n)
```

After confirmation, the summary is saved as `.niuma/requirement.md` and committed. Compilation begins automatically.

> **You never need to write task files.** Just describe what you want in plain language. The strong model clarifies through conversation. Say "let's start" whenever you're satisfied.

### 3. Auto-Execution (Unattended)

After requirement confirmation, the system runs automatically. Each step leaves a git record:

```
compiler reads requirement.md → commits dag.json → calls worker
worker reads dag.json → commits src/<node>.ts → calls next worker
all workers done → calls reviewer
reviewer reads all output → commits review.md → PASS or FAIL
```

Components exchange data via git and call the next component directly after committing. No middleman.

### 4. Review the Model's Work

After execution, go to the project menu and select **3 → Git Commits** to inspect every commit:

```
19499fb cli: requirement confirmed for e3fc810e
29a3845 compiler: DAG for task e3fc810e (2 nodes)
0011c0d worker: implement lru_store (3 iterations)
4e871de worker: implement lru_cache (2 iterations)
55e446e reviewer: PASS for task e3fc810e
```

Things to look for:
- **Compiler**: Did it split the task into the right number of subtasks?
- **Worker**: How many iterations per node? (High counts may signal a design problem.)
- **Reviewer**: Final verdict?

### 5. Push or Discard

- If satisfied: **P → Push current branch to remote**
- If not: don't push. Delete the branch, go back to step 2 and describe the task differently.

> **Core philosophy**: Git is the interface between humans and models. Models commit; you review and ship. Never blindly trust model output — you make the final call.

---

## Git-Driven Architecture

Niuma's core mechanism: all components exchange data via git, not in-memory objects.

```
cli.py creates branch
  │ writes .niuma/requirement.md → commit → calls compiler
  ▼
compiler.py
  reads requirement.md → generates DAG → commits dag.json → calls worker
  ▼
worker.py
  reads dag.json → generates code → commits src/<node>.ts
  has next node → calls worker(next)
  all done → calls reviewer
  ▼
reviewer.py
  reads dag.json + all code → reviews → commits review.md → done
```

### Why This Design

- **Consistency** — Git is the single source of truth. Nothing exists "in memory but not in git."
- **Recoverability** — If the process dies at any step, restart from the current git state.
- **Distributed-ready** — A worker on another machine just needs git pull/push.
- **Humans and models share the same view** — git log shows everything. No hidden state.

### Git Artifacts

| File | Producer | Purpose |
|------|----------|---------|
| `.niuma/requirement.md` | User confirmed + strong model summary | Human-readable requirement record |
| `.niuma/dag.json` | compiler (strong model) | Task breakdown — internal protocol for worker |
| `src/<node_id>.ts` | worker (weak model) | Generated code |
| `.niuma/review.md` | reviewer (strong model) | Review verdict + suggestions |

### Git as Communication Protocol

| Role | Author | Triggered by |
|------|--------|-------------|
| Requirement | User (cli writes it) | After TUI confirmation |
| Compiler | Strong Model | cli calls compiler directly |
| Worker | Weak Model | compiler calls worker; workers chain-call each other |
| Reviewer | Strong Model | Last worker calls reviewer |

---

## Logging

Every run is automatically archived under `.niuma/logs/`, one jsonl file per task. Each record falls into one of two types:

- `llm_call` — per API invocation: full prompt, response, token counts, duration
- `worker_process` — code extraction and sandbox execution results

Logs are for diagnosing model issues. You won't need them day to day.

---

## FAQ

**Q: The review passed but the code has a bug. What happened?**

The reviewer checks contract compliance, not exhaustive correctness. If the requirement conversation didn't cover enough edge cases, the contract might be incomplete. Cover boundary conditions during clarification.

**Q: The weak model keeps failing to converge. Now what?**

Check `.niuma/logs/` for the task's jsonl file. Common causes: DAG subtasks are too coarse, the weak model isn't capable enough (try another), or API instability (timeouts).

**Q: Can I run multiple tasks in parallel?**

The current version is serial. Parallel workers are on the long-term roadmap.

**Q: What is dag.json? Do I need to read it?**

dag.json is the compiler's internal task breakdown for the weak model. You don't need to read it — focus on `requirement.md` (requirements) and `review.md` (review verdict) instead.
