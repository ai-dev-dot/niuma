# 牛马 (Niuma)

> 榨干所有闲置的硬件资源，不浪费 1 个 token。

[English](README.md) | [中文](README.zh-CN.md)

---

**牛马**是一个运行在资源受限硬件上的编译器驱动的 AI 任务调度系统。
强模型充当**编译器**——将自然语言任务一次性编译为带类型约束和可验证契约的 DAG。
便宜的弱模型充当**执行器**——填空、跑测试、修 bug、迭代到全绿。强模型最后以**审核器**身份介入，检查最终产物。

核心思想：强模型 token 贵但聪明，弱模型便宜到可以随便烧 token 试错。弱模型的真正瓶颈不是智力（API 调用，Haiku/Flash 级别），而是 **2GB 的部署环境**。牛马把工作拆开，让每种模型在垃圾硬件的物理极限内做自己最擅长的事。

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
./niuma
```

就这一条命令。首次运行自动安装依赖，然后打开菜单：

```
  ==================================================
  牛马 Niuma
  ==================================================
  1. 配置强模型 | Configure Strong Model
  2. 配置弱模型 | Configure Weak Model
  3. 管理项目 | Manage Projects
  4. 退出 | Exit
```

在菜单里选择供应商（支持 9 家：OpenAI、DeepSeek、Groq、OpenRouter、硅基流动、
智谱AI、阿里百炼、MiniMax、月之暗面），填入 API Key，就配置完了。接口地址和模型列表自动补全。

### 环境检查

```bash
python main.py --doctor     # 检查前置条件（Python、Node.js、模型配置）
python main.py --dry-run    # 用 mock API 试跑流程，验证 pipeline 结构
```

### 测试

```bash
python -m pytest system_tests/ -v
```

## 项目结构

```
niuma/
  cli.py               # 交互式 TUI 菜单（入口）
  config.py             # 强/弱模型配置管理
  project_manager.py    # 项目创建/打开/删除 + git 凭据配置引导
  compiler.py           # 强模型: 自然语言 → 带类型的 DAG JSON
  worker.py             # 弱模型: 生成 → 编译检查 → 沙箱测试 → 修复 → 重试
  reviewer.py           # 强模型: 结构化 JSON 合约合规性审核
  sandbox.py            # 子进程沙箱（CPU/内存限制 + 临时目录隔离）
  llm.py                # OpenAI 兼容 API 客户端（指数退避重试）
  metrics.py            # JSONL 格式的 token 消耗 + 成功率数据
  models.py             # 共享数据类（DAGNode, SandboxResult, ...）
  main.py               # Pipeline 编排器（编译 → 执行 → 审核）
  benchmark.py           # 弱模型能力基准测试（18 道真实应用任务）
  task_suite/            # 基准测试任务集（6 维度 × 3 难度）
  dag_schema.json       # DAG 节点的 JSON Schema 校验规则
  requirements.txt      # Python 依赖（pytest, flask, requests）
  niuma                 # 一键启动脚本（bash）— 自动装依赖
  niuma.bat             # 一键启动脚本（Windows）
  system_tests/         # pytest 测试套件（34 个测试）
  docs/                 # 设计文档 + 测试计划 + 用户手册
```

## 语言策略

编排内核用 **Python** 写。弱模型生成的目标语言默认是 **TypeScript**（Python 也支持）。
DAG 节点的 `signature.language` 字段决定用哪个运行时。加新语言只需要在 sandbox.py 里加一个 Runtime handler——编译器和审核器不需要改。

## 当前状态

v0.4.0 — 34 个系统测试全部通过。对话式需求澄清、Git 驱动架构、可配置重试次数、git 凭据自动配置均已实现。18 道题目的基准测试套件覆盖 6 个真实应用维度。compiler → worker → reviewer 闭环支持真实 LLM 端到端运行。`./niuma` → 配置模型 → 新建任务即可开始。

## 设计决策记录

详细设计文档见 [docs/design-20260505.zh-CN.md](docs/design-20260505.zh-CN.md)，包含 DAG 节点规范、2GB 验证栈、工具策略、故障恢复和架构审查记录。  
用户手册见 [docs/user-guide.zh-CN.md](docs/user-guide.zh-CN.md)，包含操作流程、项目管理、git 凭据配置。  
基准测试方案见 [docs/superpowers/specs/2026-05-07-weak-model-benchmark-design.md](docs/superpowers/specs/2026-05-07-weak-model-benchmark-design.md)。

## License

MIT — 见 [LICENSE](LICENSE)。
