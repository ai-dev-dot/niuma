# Niuma User Guide

## Product Philosophy

Niuma is a tool for **human-model collaborative coding**. Three sentences capture its core design:

1. **Project = Git repo** — Every project you create in Niuma is backed by a git repository. All work products are git commits.
2. **Models do the work** — A strong model compiles requirements into an executable plan (DAG), a cheap weak model fills in the blanks, runs tests, and fixes bugs, and the strong model does a final review.
3. **You make the decisions** — Use the Git menu to inspect commit history, judge output quality, and decide whether to push or discard.

You're not "using AI to write code" — you're **managing an AI dev team**. Your job is to assign tasks, review results, and ship.

---

## Prerequisites

- Python 3.10+
- Node.js (required for TypeScript code generation by the weak model)
- Git
- At least one strong model and one weak model API configured (see below)

Run `./niuma` (or `./niuma.bat` on Windows) to auto-check the environment on first launch.

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

- **Strong model**: Compiles tasks and reviews results. Needs strong reasoning; tokens are expensive but used sparingly.
- **Weak model**: Writes code and fixes bugs. Needs to be cheap and have generous token limits for trial-and-error loops.

---

## Core Workflow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Create       │ →  │  Assign task │ →  │  Run pipeline│ →  │  Review+Push │
│  project      │    │  (.tsk file) │    │  (automatic) │    │  (you decide)│
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

### 1. Create a Project

Launch the TUI: `./niuma`

From the main menu, select **N → New Project** and enter:
- Project name (any label you want)
- Git repository URL (e.g. `https://github.com/your-name/my-project.git`)
- HTTP proxy (leave blank if not needed)

The TUI clones the repo and the project is ready.

> **Design principle**: One project = one git repo. All model output — code, DAGs, review reports — lands as git commits in this repo.

### 2. Create a Task

Inside the project menu, select **2 → New Task File**. A task file is a `.tsk` plain-text file that describes what you want to build, in natural language.

The quality of the task description directly impacts the output. A good one includes:
- The goal ("Implement an LRU cache class")
- Constraints ("O(1) time complexity")
- Specific requirements ("get(key) returns the cached value or null if not found")
- Target language

Example (`tasks/lru-cache.tsk`):
```
Implement a thread-safe LRU (Least Recently Used) cache class.

Requirements:
- Constructor takes a capacity parameter for max size
- get(key) returns the cached value, or null if absent
- put(key, value) stores a key-value pair; evicts the LRU item when at capacity
- All operations must be O(1)
- Implement in TypeScript
```

### 3. Run the Task

From the project menu, select **1 → Run Task** and pick the `.tsk` file. The pipeline runs automatically:

```
Strong model compiles → Weak model executes → Strong model reviews
```

Progress and token usage are displayed in real time. The review result is PASS or FAIL (up to 3 rounds).

### 4. Review the Model's Work

After the pipeline finishes, **don't blindly trust the result**. Go to the project menu, select **3 → Git Commits**, and inspect every commit the models produced:

```
19499fb compiler: DAG for task e3fc810e (2 nodes)
0011c0d worker: implement doubly_linked_list (3 iterations)
4e871de worker: implement lru_cache (2 iterations)
004c75c reviewer: FAIL for task e3fc810e
29a3845 reviewer: PASS for task e3fc810e
```

Things to look for:
- **Compiler**: Did it split the task into the right number of subtasks? Is the granularity reasonable?
- **Worker**: How many iterations did each node take? (High iteration counts may signal a design problem.)
- **Reviewer**: How many times did it reject the work? What finally convinced it?

### 5. Push or Discard

- If you're satisfied: **P → Push current branch to remote**
- If not: don't push. Delete the branch in the project, then go back to step 2 to rewrite the task description or adjust model settings.

> **Core philosophy**: Git is the interface between humans and models. Models commit their work; you review and decide whether to ship. Never blindly trust model output — you are the final decision-maker.

---

## Pipeline Deep Dive

```
User task (.tsk)
      │
      ▼
┌─────────────┐
│  compiler.py │  Strong model (single call)
│              │  Task description → DAG JSON (typed signatures, contracts, test skeletons)
└──────┬──────┘
       │ DAG (subtask list + dependency graph)
       ▼
┌─────────────┐
│  worker.py   │  Weak model loop (per subtask)
│   + sandbox  │  Generate → self-check → sandbox test → read errors → fix → retry
│              │  >10 iterations without passing → marked FAILED, back to compiler
└──────┬──────┘
       │ All subtasks pass
       ▼
┌─────────────┐
│ reviewer.py  │  Strong model audit (up to 3 rounds)
│              │  Contract compliance check → PASS / FAIL
└──────┬──────┘
       │ PASS
       ▼
  outputs/ dir + git branch ready
```

### Build Artifacts

- `outputs/<task_id>/` — one `.ts` file per subtask
- `.niuma/logs/<date>_<task_id>.jsonl` — complete API call log
- `.niuma/logs/<date>_<task_id>_summary.json` — task summary (token usage, iterations, etc.)
- git branch `niuma/<task_id>` — chronological commits from every pipeline step

---

## Git as a Communication Protocol

Each participant in Niuma leaves a record via git commits:

| Role | Author | Produces |
|------|--------|----------|
| Compiler | Strong Model | `.niuma/dag.json` |
| Worker | Weak Model | `src/<node_id>.ts` |
| Reviewer | Strong Model | `.niuma/review.md` |

You don't need to read every line of generated code. The git log tells you how the run went:
- A reasonable number of commits (not dozens of fix-up patches)
- Reviewer's final verdict is PASS
- Worker commits show iteration counts (low iterations = the model got it right quickly, which means both the model and the DAG design are solid)

---

## Logging

Every run is automatically archived under `.niuma/logs/`, one jsonl file per task. Each record falls into one of two types:

- `llm_call` — per API invocation: full prompt, response, token counts, duration
- `worker_process` — code extraction and sandbox execution results

Logs are primarily for diagnosing model issues (e.g. MiniMax `<think>` blocks eating tokens, API timeout frequency). You won't need them day to day.

---

## Planned Features

### Conversational Requirement Clarification

Currently, users write `.tsk` files directly. The compilation quality depends entirely on how well the user can write requirements. The problem: most people don't know how to write requirements that are "detailed enough."

Planned: before compiling, the strong model asks the user 2-3 clarifying questions ("What kind of workload is this for? What type are the keys? Do you need TTL support?"). After a brief Q&A, the strong model produces a confirmed requirement summary and only then starts compiling.

Benefit: a tiny cost (1-2 strong model calls) to prevent the weak model from burning tokens on a poorly-designed DAG.

---

## FAQ

**Q: The review passed but the code has a bug. What happened?**

The reviewer checks contract compliance, not exhaustive correctness. If the contract itself isn't comprehensive enough, the reviewer may miss edge cases. The fix: include boundary conditions in your task description.

**Q: The weak model keeps failing to converge. Now what?**

Check `.niuma/logs/` for the task's jsonl file. Look at the weak model's prompts and responses. Common causes: DAG subtasks are too coarse (too much for one node), the weak model itself isn't capable enough (try a different one), or API instability (timeouts).

**Q: Can I run multiple tasks in parallel?**

The current version is serial. Parallel workers are on the long-term roadmap, constrained by the 2GB memory target.
