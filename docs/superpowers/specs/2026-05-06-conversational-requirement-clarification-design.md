# Spec: 对话式需求澄清

## 现状

用户通过 TUI 输入自然语言任务描述，直接传给强模型编译 DAG。需求质量完全依赖用户写需求的能力，没有需求澄清环节。

## 目标

用户通过 TUI 直接输入自然语言需求描述，强模型通过多轮对话澄清模糊点，确认后的需求摘要再编译为 DAG。用户不需要知道 `.tsk` 是什么。

## 设计

### 数据流

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
                     compiler.compile_task(summary)
                               │
                               ▼
                         DAG → worker → reviewer
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
    {"role": "assistant", "content": "SUMMARY: 实现一个 LRU 缓存类，key 为字符串类型，不需要 TTL..."},
]
```

history 按时间顺序追加，compile 阶段将完整 history 作为上下文传给强模型。

### 收束机制

不加任何 TUI 特殊命令（如 `/done`）。模型通过自然语言识别用户"已经够了"的意图。软上限 20 轮，超限后拿最后一次 summary 直接编译。

### 产物保存

用户确认需求摘要后，强模型 commit `.niuma/requirement.md`（和 `.niuma/review.md`、`.niuma/dag.json` 并列）。这一份文件既是人类可读的需求确认记录，也是编译器的输入。

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

  ✓ 需求已确认，开始编译...
  [强模型] 正在分析任务并分解为 DAG...
```

### 向后兼容

- 命令行 `python main.py --inline "..."` 路径保持不变，跳过澄清阶段直接编译
- TUI 项目菜单中"运行任务"选项直接进入对话式需求澄清

### 改动清单

| 文件 | 改动 |
|------|------|
| `compiler.py` | 新增 `clarify_step(history)` — 调用强模型，解析返回 JSON，返回 question 或 summary |
| `cli.py` | 新增 `_clarify_and_run(project)` — 对话循环 + 确认 + 调用 main.run_task；替换原来的选 `.tsk` 文件流程；调整项目菜单 |
| `project_manager.py` | 新增 `commit_file` 调用写 `.niuma/requirement.md`（已有，直接复用）|
| `models.py` | 可选加 `ClarifyResponse` 数据类（`type: Literal["question","summary"]` + 内容字段），也可直接用 dict |

### 不改的文件

- `main.py` — `run_task` 不变，接收的是确认后的需求描述
- `worker.py` — 不受影响
- `reviewer.py` — 不受影响
- `llm.py` — 复用 `call_strong`
- `sandbox.py` — 不受影响

### 测试要点

- 澄清对话 0 轮（需求一开始就够清晰）→ 直接输出 summary
- 澄清对话 2-4 轮 → 正常收敛
- 用户自然语言说"够了" → 模型停止追问
- 20 轮超限 → 强制编译
- 用户拒绝确认摘要 → 返回澄清继续
- 命令行 `--inline` 路径 → 跳过澄清直编
