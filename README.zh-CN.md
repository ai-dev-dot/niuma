# 牛马 (Niuma)

> 榨干所有闲置的硬件资源，不浪费 1 个 token。

[English](README.md) | [中文](README.zh-CN.md)

---

**牛马**是一个运行在资源受限硬件上的编译器驱动的 AI 任务调度系统。
强模型充当**编译器**——将自然语言任务一次性编译为带类型约束和可验证契约的 DAG。
便宜的弱模型充当**执行器**——填空、跑测试、修 bug、迭代到全绿。强模型最后以**审核器**身份介入，检查最终产物。

核心思想：强模型 token 贵但聪明，弱模型笨但便宜到可以随便烧 token 试错。牛马把工作拆开，让每种模型做自己最擅长的事。

## 为什么要做

现有 AI Agent 框架（AutoGPT、MetaGPT、CrewAI）默认资源富足——最低 16GB 内存，token 预算不设限。牛马反其道而行：一台 2GB Ubuntu 服务器、一份用不完的弱模型 API 套餐、以及一个信念——**好货能从垃圾硬件里跑出来**。

**学术界和工业界没人尝试低于 16GB 的多 Agent 系统。** 牛马探索的是 AI Agent 编排内核的物理下限。

## 架构

```
用户: "实现一个线程安全的 LRU 缓存"
            │
            ▼
     ┌─────────────┐
     │  compiler.py │  强模型（一次调用）: 任务描述 → 带类型的 DAG JSON
     └──────┬──────┘
            │ DAG（每个节点: 类型签名 + 合约 + 测试骨架）
            ▼
     ┌─────────────┐
     │   worker.py  │  弱模型循环: 生成代码 → 沙箱跑测试 → 看报错 → 修 → 重试
     │  (sandbox)   │  子进程隔离 + 资源限制（CPU/内存）
     └──────┬──────┘
            │ 全部节点通过测试
            ▼
     ┌─────────────┐
     │ reviewer.py  │  强模型（一次调用）: 合约合规性审核 → PASS / FAIL
     └──────┬──────┘
            │ PASS
            ▼
     ┌─────────────┐
     │  outputs/    │  最终产物代码 + Token 消耗数据
     └─────────────┘
```

每个 DAG 节点携带：**函数签名**（带类型的输入输出）、**合约**（前置/后置条件 + 不变式）、**测试骨架**（弱模型必须通过）。弱模型永远不需要理解整体任务意图——它只在强类型约束的格子里填空。

## 为什么是"编译器架构"

传统的 Agent 系统每次任务都要让强模型参与——分配任务要调、中间检查要调、最终审核要调。
强模型 token 消耗是 O(n)。

牛马的编译器架构：强模型一次性把任务描述编译成 DAG，之后**同类型任务可以复用缓存的 DAG 模板**。
强模型只在编译和最终审核时调用——token 消耗降到 O(1)。

这个想法来自 `/office-hours` 的独立子代理审查。文献里几乎没人探索这个方向。

## 快速开始

### 前置条件

- Python 3.10+
- Node.js 18+（TypeScript 沙箱需要）
- LLM API key（兼容 OpenAI 接口）

### 安装

```bash
git clone https://github.com/ai-dev-dot/niuma.git
cd niuma
cp .env.example .env
# 编辑 .env，填入 API key 和模型名
```

### 运行

```bash
python main.py tasks/lru-cache.tsk
# 或者直接输入:
python main.py --inline "用 TypeScript 实现一个线程安全的 LRU 缓存"
```

### 测试

```bash
pip install pytest
python -m pytest system_tests/ -v
```

## 项目结构

```
niuma/
  main.py             # CLI 入口 + pipeline 编排器
  compiler.py          # 强模型: 自然语言 → 带类型的 DAG JSON
  worker.py            # 弱模型: 生成 → 沙箱执行 → 修复 → 重试循环
  reviewer.py          # 强模型: 合约合规性审核
  sandbox.py           # 子进程沙箱（CPU/内存限制 + 临时目录隔离）
  llm.py               # OpenAI 兼容 API 客户端（指数退避重试）
  metrics.py           # JSONL 格式的 token 消耗 + 成功率数据
  models.py            # 共享数据类（DAGNode, SandboxResult, ...）
  dag_schema.json      # DAG 节点的 JSON Schema 校验规则
  tasks/               # 示例任务描述文件（.tsk）
  system_tests/        # pytest 测试套件（29 个测试）
  docs/                # 设计文档 + 测试计划
```

## 语言策略

编排内核用 **Python** 写。弱模型生成的目标语言默认是 **TypeScript**（Python 也支持）。
DAG 节点的 `signature.language` 字段决定用哪个运行时。加新语言只需要在 sandbox.py 里加一个 Runtime handler——编译器和审核器不需要改。

## 当前状态

原型阶段——29 个系统测试全部通过。compiler → worker → reviewer 闭环在用 mock API 的情况下跑通。
要用真实 LLM 端到端运行，配置 `.env` 文件即可。

## 设计决策记录

详细设计文档见 `docs/design-20260505.zh-CN.md`，包含完整的 DAG 节点规范、故障恢复策略、Prompt 模板和架构审查记录。

## License

MIT — 见 [LICENSE](LICENSE)。
