# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**牛马 (Niuma)** — 一个分布式 AI 任务调度系统。核心思想：强模型（贵、聪明）当架构师和审查员，弱模型（便宜、能力有限）当码农。强模型把自然语言需求编译成带类型约束的任务 DAG，弱模型在沙箱中填空、跑测试、修 bug，强模型最后审核产物。

目标硬件：2GB 内存的闲置云服务器。

## 常用命令

```bash
# 启动交互式菜单（首次运行自动安装依赖）
./niuma              # Linux/Mac
niuma.bat            # Windows

# 环境检查
python main.py --doctor

# 试运行（mock API，验证流程结构）
python main.py --dry-run

# 运行任务
python main.py --inline "实现一个线程安全的 LRU 缓存"
python main.py tasks/my_task.tsk
python main.py --verbose tasks/my_task.tsk

# 运行测试套件
python -m pytest system_tests/ -v

# 单个测试文件
python -m pytest system_tests/test_compiler.py -v

# TypeScript 编译检查（沙箱用）
npx tsc --noEmit --target ES2020 --module commonjs --strict false file.ts
```

## 架构

```
用户需求（自然语言）
    │
    ▼
cli.py ──── 交互式 TUI 菜单，入口 ./niuma
    │
    ▼
compiler.py ── 强模型：需求澄清 → 自然语言 → DAG JSON（含 Schema 校验+重试）
    │            每个 DAG 节点带：函数签名、合约（前置/后置/不变式）、测试骨架
    ▼
worker.py ─── 弱模型：对每个节点循环「生成代码 → 编译检查 → 沙箱测试 → 修复」
    │            按拓扑序执行，依赖闭包过滤上下文
    ▼
reviewer.py ── 强模型：审核所有节点产物 → PASS/FAIL + 修改建议
    │            FAIL 时自动重做失败节点及其下游
    ▼
outputs/ ──── 最终代码 + metrics
```

### 核心模块

| 文件 | 职责 |
|------|------|
| `cli.py` | TUI 菜单入口，需求澄清对话，项目管理 |
| `main.py` | Pipeline 编排器（编译→执行→审核），CLI 参数解析 |
| `compiler.py` | 强模型编译：自然语言→DAG JSON，含 Schema 校验和重试 |
| `worker.py` | 弱模型执行：代码生成→编译检查→沙箱测试→修复循环 |
| `reviewer.py` | 强模型审核：合约合规性审查，PASS/FAIL 判定 |
| `sandbox.py` | 子进程沙箱：TypeScript(Jest) 和 Python(pytest) 隔离执行 |
| `llm.py` | OpenAI 兼容 API 客户端，指数退避，token 计数，全量日志 |
| `config.py` | `~/.niuma/config.json` 配置管理，9 家供应商预设 |
| `project_manager.py` | Git 项目管理：clone/分支/commit/凭据，SQLite 存储项目元数据 |
| `models.py` | 共享数据类：DAG, DAGNode, Contract, SandboxResult, NodeResult 等 |
| `metrics.py` | JSONL 指标输出 |
| `dag_schema.json` | DAG JSON Schema 校验规则 |

### 关键设计决策

- **Git 驱动通信**：每个任务创建 `niuma/<task-id>` 分支，强/弱模型通过 git commit 传递产物（`--author` 区分角色）
- **依赖闭包过滤**：worker 执行节点时只传递该节点传递依赖闭包中已完成的代码，不传全部上下文
- **编译检查先于沙箱**：worker 先用 `compile()`(Python) 或 `tsc --noEmit`(TS) 检查语法，不消耗 API token
- **审核重做级联**：审核失败的节点 + 依赖它们的下游节点全部重做
- **早期终止**：失败节点比例超过 `early_abort_fail_ratio`(默认 0.6) 时跳过剩余节点
- **双语错误消息**：sandbox 模块的错误消息中英双语

### 数据流

- 配置：`~/.niuma/config.json`（模型 API 密钥、重试限制）
- 项目：`~/.niuma/projects/` + `~/.niuma/niuma.db`（SQLite）
- 任务日志：`<project>/.niuma/logs/<date>_<task_id>.jsonl`
- DAG 定义：`<project>/.niuma/dag.json`
- 需求文档：`<project>/.niuma/requirement.md`
- 审核报告：`<project>/.niuma/review.md`
- 节点产物：`<project>/outputs/<task_id>/<node_id>.ts`
- 代码提交：`<project>/src/<node_id>.ts`

## 语言和技术栈

- **编排内核**：Python 3.10+（纯标准库，零第三方运行时依赖）
- **生成代码目标**：TypeScript（默认）或 Python，由 DAG 节点的 `signature.language` 决定
- **TypeScript 测试**：Jest + ts-jest（项目根目录 `node_modules/`）
- **Python 测试**：pytest
- **系统测试**：`system_tests/` 下 34 个 pytest 用例
- **数据存储**：SQLite（项目元数据）、JSONL（日志和指标）

## 开发注意事项

- `llm.py` 的日志输出到 stderr，不污染 stdout 管道
- `config.py` 支持旧 `.env` 自动迁移到 `~/.niuma/config.json`
- `sandbox.py` 在 Windows 上不支持 `resource` 模块的内存/CPU 限制（优雅降级）
- `compiler.py` 的 `_parse_dag` 有多层容错：去掉 think 块、markdown 标记、类型强制
- `worker.py` 的 `_extract_code` 会尝试多种方式从弱模型响应中提取代码
- 所有 LLM 调用通过 `llm.py` 的 `call_strong`/`call_weak`，自动读取配置中的模型和 API key
- DeepSeek reasoning 模型：`content` 为空时自动取 `reasoning_content`

