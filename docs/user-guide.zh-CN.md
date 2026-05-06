# 牛马用户手册

## 产品思路

牛马是一个**人和 AI 模型协作写代码**的工具。理解它的核心设计只需要三句话：

1. **项目 = Git 仓库** — 你在牛马里创建的每个项目，背后就是一个 git 仓库。Git 是系统运行的唯一真实状态，所有工作和通信都通过 git 完成。
2. **模型负责干活** — 强模型先和你对话澄清需求，再把需求拆成可执行计划（DAG），弱模型填空写代码、跑测试、修 bug，强模型最后审核。组件之间做完 commit 后直接调用下一个。
3. **人负责决策** — 你通过 Git 菜单看模型的提交记录，判断产出质量，决定 push 还是退回。

你不是在"用 AI 写代码"，你是在**管理一个 AI 开发团队**——你的工作是布置任务、审核结果、拍板发布。

---

## 前置条件

- Python 3.10+
- Node.js（弱模型生成 TypeScript 代码需要）
- Git
- 至少配置了一个强模型和一个弱模型的 API（见下方配置）

首次运行 `./niuma`（或 `./niuma.bat`）会自动检查环境。

---

## 模型配置

配置文件位于 `~/.niuma/config.json`（用户目录下的 `.niuma` 文件夹）：

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

- **强模型**：负责澄清需求、编译任务和审核结果，需要推理能力强，token 消耗少但贵
- **弱模型**：负责写代码和修 bug，需要便宜且 token 充裕，可以反复试错

---

## 核心工作流

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  创建项目     │ → │  布置任务     │ → │  自动执行     │ → │  审核 + Push │
│  (git clone)  │    │  (对话澄清)   │    │  (无人值守)   │    │  (人做决定)  │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

### 1. 创建项目

启动 TUI：`./niuma`

在主菜单选择 **N → 新建项目**，输入：
- 项目名称（任意命名）
- Git 仓库地址（如 `https://github.com/ai-dev-dot/niuma-test.git`）
- HTTP 代理（不需要则留空）

TUI 会自动 clone 仓库，项目即创建完成。

> **设计原则**：一个项目绑定一个 git 仓库。模型产出的所有内容都以 git commit 的形式落在这个仓库里。Git 是系统运行的唯一真实状态。

### 2. 布置任务（对话式需求澄清）

进入项目菜单，选择 **1 → 新建任务**。直接输入你的需求描述，像和人说话一样：

```
  请描述你想实现的功能：
  > 实现一个 LRU 缓存，支持 get/put，O(1) 时间复杂度
```

强模型会分析你的需求，逐条追问来帮你补全细节：

```
  Q: 缓存的 key 和 value 分别是什么类型？
  > key 是字符串，value 任意

  Q: 需要支持 TTL 过期吗？
  > 不需要
```

当你觉得需求够清晰了，直接说"开始吧"或"差不多了"，强模型会生成一份需求确认摘要：

```
  [强模型] 已整理需求确认：

  实现一个 LRU（最近最少使用）缓存类。
  - key: string，value: any
  - get(key): 返回 value 或 null
  - put(key, value): 存入键值对，容量满时淘汰最久未使用项
  - 容量: 构造函数参数 capacity
  - 复杂度: 所有操作 O(1)
  - 使用 TypeScript 实现

  确认无误？(Y/n)
```

确认后，需求自动存入 `.niuma/requirement.md` 并 commit，然后自动开始编译执行。

> **不需要自己写任务文件**。你只需要用自然语言描述需求，强模型会帮你聊清楚。任何时候觉得够了就说"开始编译吧"。

### 3. 自动执行（无人值守）

需求确认后，系统自动串行执行，每步都在 git 里留记录：

```
compiler 读 requirement.md → commit dag.json → 调 worker
worker 读 dag.json → commit src/<node>.ts → 调 worker（下一个节点）
worker 全部完成 → 调 reviewer
reviewer 读所有产物 → commit review.md → PASS 或 FAIL
```

组件之间通过 git 交换数据，做完 commit 后直接调用下一个。不需要中间人。

### 4. 审核模型的工作

任务运行完成后，进入项目菜单选择 **3 → Git 提交记录**，查看模型产出的所有 commit：

```
19499fb cli: requirement confirmed for e3fc810e
29a3845 compiler: DAG for task e3fc810e (2 nodes)
0011c0d worker: implement lru_store (3 iterations)
4e871de worker: implement lru_cache (2 iterations)
55e446e reviewer: PASS for task e3fc810e
```

你应该关注：
- **Compiler** 把任务拆成了几个子任务？粒度合理吗？
- **Worker** 每个节点用了多少轮迭代？（迭代多的节点可能设计有问题）
- **Reviewer** 最终结论是什么？

### 5. Push 或丢弃

- 如果对产出满意：**P → Push 当前分支到远程**
- 如果不满意：不 push，直接在项目内删除分支，回到第 2 步重新描述需求

> **核心理念**：Git 是人和模型之间的界面。模型负责 commit，人负责 review 和 push。不要盲目信任模型的产出——你是最终决策者。

---

## Git 驱动架构

牛马的核心机制：所有组件通过 git 交换数据，而非内存传对象。

```
cli.py 创分支
  │ 写 .niuma/requirement.md → commit → 调 compiler
  ▼
compiler.py
  读 requirement.md → 生成 DAG → commit dag.json → 调 worker
  ▼
worker.py
  读 dag.json → 生成代码 → commit src/<node>.ts
  还有下一个节点 → 调 worker（下一个）
  全部 done → 调 reviewer
  ▼
reviewer.py
  读 dag.json + 所有代码 → 审查 → commit review.md → 结束
```

### 为什么这样设计

- **一致性** — git 是唯一的真实状态，不存在"内存里有但 git 里没有"的东西
- **可恢复** — 进程在任何一步挂了，重启后从 git 当前状态继续
- **分布式自然** — 另一台机器的 worker 只需 git pull/push
- **人和模型看同一份数据** — git log 就是全部，没有隐藏的内部状态

### Git 产物一览

| 文件 | 产出者 | 作用 |
|------|--------|------|
| `.niuma/requirement.md` | 用户确认 + 强模型生成 | 需求确认记录，人类可读 |
| `.niuma/dag.json` | compiler（强模型） | 任务清单，给 worker 看的内部协议 |
| `src/<node_id>.ts` | worker（弱模型） | 生成的代码 |
| `.niuma/review.md` | reviewer（强模型） | 审核结论 + 修改建议 |

### Git 作为通信协议

| 角色 | Author commit | 触发方式 |
|------|-------------|---------|
| 需求澄清 | User（cli 写入） | TUI 确认后 |
| 编译器 | Strong Model | cli 直接调用 compiler |
| Worker | Weak Model | compiler 调用 worker，worker 间链式调用 |
| 审核器 | Strong Model | 最后一个 worker 调用 reviewer |

---

## 日志系统

每次运行自动在 `.niuma/logs/` 下归档，一个任务一个 jsonl 文件。每条记录分两种类型：

- `llm_call` — 每次 API 调用：完整 prompt、response、token 消耗、耗时
- `worker_process` — 弱模型代码提取和沙箱执行结果

日志用于诊断模型问题（如 MiniMax 的 `<think>` 块消耗 token、API 超时频率等），不需要用户日常查看。

---

## 常见问题

**Q: 审核 PASS 了但代码有 bug 怎么办？**

审核器看的是合约合规性，不是穷举测试。如果需求阶段聊得不够细，合约本身可能不够完整。改进方式是对话澄清时尽量覆盖边界条件。

**Q: 弱模型一直不收敛怎么办？**

查看 `.niuma/logs/` 找到对应任务的 jsonl，看弱模型的 prompt 和 response。常见原因：DAG 拆分太粗（子任务过大）、弱模型本身能力不足（换一个）、API 不稳定（超时导致）。

**Q: 能同时跑多个任务吗？**

当前版本串行执行。并行 Worker 在长期规划中。

**Q: dag.json 是什么？我需要看吗？**

dag.json 是编译器把需求拆成子任务清单的内部格式，给弱模型看的。你不需要直接看它——看 `requirement.md`（需求）和 `review.md`（审核结论）就够了。
