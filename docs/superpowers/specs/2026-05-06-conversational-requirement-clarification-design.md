# Spec: 对话式需求澄清 + Git 驱动架构

## 现状问题

1. **用户直接写需求，质量不稳定** — 用户不知道怎么写"足够详细"，编译出来的 DAG 经常不对
2. **组件间靠内存传对象** — main.py 串行调 compiler → worker → reviewer，对象在内存里流转。进程挂掉状态丢失，跨机器无法工作
3. **git 只是审计日志** — commit 是事后补的，不是系统运行的真实状态

## 目标

1. 用户通过 TUI 和强模型对话，澄清需求后确认，再编译
2. 所有组件通过 git 交换数据——git 是唯一的真实状态
3. 组件间直接调用（非 main.py 编排），每步"读 git → 做事 → commit → 调下一个"

---

## 设计

### Git 驱动架构

```
cli.py 创分支 niuma/<task_id>
  │
  │ 写 .niuma/requirement.md → commit
  │ 调 compiler
  ▼
compiler.py
  读 .niuma/requirement.md
  生成 DAG → commit .niuma/dag.json
  调 worker(node_1)
  ▼
worker.py
  读 .niuma/dag.json → 找到自己的节点
  生成代码 → commit src/<node_id>.ts
  ├─ 还有下一个节点 → 调 worker(node_next)
  └─ 全部 done → 调 reviewer
  ▼
reviewer.py
  读 .niuma/dag.json + src/<node_id>.ts
  审查 → commit .niuma/review.md
  ├─ PASS → 结束
  └─ FAIL → 调 worker（带上修改建议）
```

### 状态在 git 里，不在内存里

每个组件做的事情统一为三步：
1. **读** — 从文件系统/git 读取上一步的产出
2. **做** — 调 LLM 完成自己的工作
3. **写** — commit 结果，再调下一个组件

不依赖 main.py 持有状态。任何一步的进程挂掉，重启后 git log 和文件系统就是恢复点。

### 对话式需求澄清

澄清阶段发生在 cli.py 写 `.niuma/requirement.md` 之前。

```
TUI "新建任务"
  │
  ▼
用户输入需求描述（自然语言）
  │
  ▼
┌──────────────────────────────────────────┐
│  compiler.clarify_step(history)           │
│  强模型调用，每次返回:                      │
│    {type: "question", question: "..."}     │
│    {type: "summary", summary: "..."}       │
└──────────────┬───────────────────────────┘
               │
       ┌───────┴───────┐
       ▼               ▼
   question          summary
   TUI 展示问题      TUI 展示需求确认摘要
   用户输入回答      用户确认 (Y/n)
   追加到 history        │
   → 回到 clarify    ───┘  确认
                               │
                               ▼
                     写 .niuma/requirement.md → commit → 调 compiler
```

### Prompt 设计

澄清阶段的 system prompt：

```
你是一个需求分析器。用户描述了想做的功能。你的任务是帮他把需求澄清到足够编译的程度。

规则：
- 每次只问一个最关键的问题。不要一次问多个。
- 如果用户表示"够了"、"开始吧"、"不用再问了"之类的意图，不要再追问，直接输出需求摘要。
- 如果需求已经足够清晰，直接输出需求摘要。

输出格式：
- 如果还有疑问：{"type": "question", "question": "你的问题"}
- 如果已清晰：{"type": "summary", "summary": "结构化需求描述..."}

问题应该聚焦在：功能边界、数据类型、约束条件、使用场景。
```

### 会话历史

```python
history = [
    {"role": "user", "content": "实现一个 LRU 缓存"},
    {"role": "assistant", "content": "Q: key 是固定类型还是任意类型？"},
    {"role": "user", "content": "字符串"},
    {"role": "assistant", "content": "Q: 需要 TTL 过期吗？"},
    {"role": "user", "content": "不需要"},
    {"role": "assistant", "content": "Q: 是单线程还是多线程环境？"},
    {"role": "user", "content": "差不多了，开始编译吧"},
    {"role": "assistant", "content": "SUMMARY: 实现一个 LRU 缓存类，key 为字符串类型..."},
]
```

history 按时间顺序追加，compile 阶段将完整 history 作为上下文传给强模型。

### 收束机制

不加 TUI 特殊命令。模型通过自然语言识别用户"已经够了"的意图。软上限 20 轮，超限后拿最后一次 summary 直接编译。

### Git 产物

| 文件 | 产出者 | 作用 |
|------|--------|------|
| `.niuma/requirement.md` | cli.py（强模型生成摘要，用户确认后写入） | 人类可读的需求确认记录 + 编译器输入 |
| `.niuma/dag.json` | compiler.py | 拆解后的任务清单，给 worker 和 reviewer 看的内部协议 |
| `src/<node_id>.ts` | worker.py | 弱模型生成的代码 |
| `.niuma/review.md` | reviewer.py | 审核结论 + 修改建议 |

### TUI 交互示例

```
  新建任务 | New Task — my-project

  请描述你想实现的功能：
  > 实现一个 LRU 缓存，支持 get/put，O(1) 时间复杂度

  [强模型] 正在分析需求...

  Q: 缓存的 key 和 value 分别是什么类型？
  > key 是字符串，value 任意

  Q: 需要支持 TTL 过期吗？
  > 不需要

  Q: 单线程还是多线程？
  > 我觉得差不多了，开始编译吧

  [强模型] 已整理需求确认：

  实现一个 LRU（最近最少使用）缓存类。
  - key: string，value: any
  - get(key): 返回 value 或 null
  - put(key, value): 存入键值对，容量满时淘汰最久未使用项
  - 容量: 构造函数参数 capacity
  - 复杂度: 所有操作 O(1)
  - 不需要 TTL
  - 使用 TypeScript 实现

  确认无误？(Y/n)

  ✓ 需求已确认

  >>> git commit: .niuma/requirement.md
  [强模型] 开始编译 DAG...
  >>> git commit: .niuma/dag.json
  [弱模型] 执行节点 lru_store...
  >>> git commit: src/lru_store.ts (3 轮迭代)
  [弱模型] 执行节点 lru_cache...
  >>> git commit: src/lru_cache.ts (2 轮迭代)
  [强模型] 审核中...
  >>> git commit: .niuma/review.md — PASS

  [OK] 任务完成
  分支 niuma/e3fc810e 就绪，审阅后 push
```

### 改动清单

| 文件 | 改动 |
|------|------|
| `cli.py` | 新增 `_clarify_and_run(project)` — 对话循环 + 确认 + 写 requirement.md → commit → 调 compiler；替换原来的选文件流程 |
| `compiler.py` | 新增 `clarify_step(history)` — 澄清对话；新增 `compile_from_git(repo_path)` — 读 requirement.md 编译 DAG |
| `worker.py` | 新增 `execute_from_git(repo_path, node_id)` — 读 dag.json 找到节点，生成代码，commit，调下一个；原来 `execute_node` 改内部调用 |
| `reviewer.py` | 新增 `review_from_git(repo_path)` — 读 dag.json + src/*.ts，审核，commit review.md |
| `main.py` | 简化为入口函数 `start_pipeline(repo_path, confirmed_summary)` — 创分支、写 requirement.md、调 compiler |
| `models.py` | 可选加 `ClarifyResponse` 数据类 |
| `project_manager.py` | 不改（已有 commit_file） |

### 不改的文件

- `llm.py` — 复用 `call_strong` / `call_weak`
- `sandbox.py` — 不受影响
- `config.py` — 不受影响
- `dag_schema.json` — 不受影响

### 测试要点

- 澄清对话 0 轮（需求一开始就够清晰）→ 直接输出 summary
- 澄清对话 2-4 轮 → 正常收敛
- 用户自然语言说"够了" → 模型停止追问
- 20 轮超限 → 强制编译
- 用户拒绝确认摘要 → 返回澄清继续
- 命令行 `--inline` 路径 → 跳过澄清，直编
- Git 驱动：compiler → worker → reviewer 链式调用全部通过
- 中断恢复：worker commit 后在 reviewer 调用前挂掉 → 重启后能从 git 状态恢复
