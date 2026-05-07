# 弱模型能力基准测试方案

由 /plan-ceo-review 产出 | 2026-05-07 | 分支: main | 模式: HOLD SCOPE

## 背景

牛马系统的弱模型通过 API 调用（能力相当于 Haiku/Flash 级别，不算差），但它运行在 **2GB 内存的 Ubuntu 服务器**上——不能本地推理、不能并行多 worker、不能跑重工具链。当前对弱模型在真实 2GB 环境中的能力边界只有印象没有数据：`_quick_self_check` 形同虚设，MiniMax 两次拒绝修改是孤例。

**决策：先做系统化基准测试，拿数据再动架构。**

## 核心约束

- 弱模型 API 调用，不本地推理
- Worker 进程 ~64-128MB，沙箱 ~256MB
- 2GB 总内存，1-2 个并行 worker 上限
- 基准测试本身也必须在 2GB 内运行
- 零强模型 token 消耗（保持 O(1) 原则）

## 测试维度矩阵（6 维度 × 3 难度 = 18 题）

| # | 维度 | 简单 | 中等 | 困难 |
|---|------|------|------|------|
| 1 | 代码生成 | 填空式单函数 | 多方法类 | 跨文件模块 |
| 2 | 测试生成 | 单函数测试 | 多方法测试 | 集成测试 |
| 3 | 错误诊断 | 语法错误 | 类型错误 | 逻辑错误 |
| 4 | 代码修复 | 加 import | 改签名 | 重构 |
| 5 | 代码审查 | 审查代码 | 审查 DAG | 审查依赖关系 |
| 6 | 输出验证 | 单值比对 | 结构化输出 | 边界条件 |

预估运行时间：~30-60 分钟 / 轮。

## 判定逻辑

纯自动化判定，零强模型参与：

| 题目类型 | 判定方式 | PASS 条件 |
|---------|---------|----------|
| 代码生成 | 沙箱跑 Jest/pytest | 测试全部通过 |
| 测试生成 | 沙箱跑生成的测试 + 预设的正确实现 | 测试不报错且覆盖关键用例 |
| 错误诊断 | 关键词匹配 | 模型指出的根因包含预设关键 token |
| 代码修复 | 沙箱跑修复后代码 + 原测试 | 测试全部通过 |
| 代码审查 | 计数匹配 | 找到的 bug 数 ≥ 预设 bug 数的 50% |
| 输出验证 | 字符串匹配 | 模型判断与 ground truth 一致 |

## 数据输出结构

```
benchmark_results/2026-05-07_143000/
├── summary.json        # 总览：每维度通过率、平均token、平均延迟、内存峰值
├── per_task/
│   ├── code_gen_easy_01.json     # 每题：完整 prompt + 响应 + 判定 + 指标
│   ├── code_gen_medium_02.json
│   └── ... (18 题)
├── metrics.jsonl        # 原始指标流，支持 jq/awk 自定义分析
└── env.json             # 环境快照：OS/内存/CPU/Python版本
```

### summary.json 结构

```json
{
  "run_id": "2026-05-07_143000",
  "model": "minimax-m2.1",
  "environment": { "os": "Ubuntu 22.04", "ram_mb": 2048, "python": "3.12" },
  "results": {
    "code_gen":     { "pass": 2, "fail": 1, "pass_rate": 0.67, "avg_tokens": 450, "avg_latency_s": 12.3 },
    "test_gen":     { "pass": 1, "fail": 2, "pass_rate": 0.33, "avg_tokens": 380, "avg_latency_s": 10.1 },
    "error_diag":   { "pass": 3, "fail": 0, "pass_rate": 1.0,  "avg_tokens": 120, "avg_latency_s": 3.2 },
    "code_fix":     { "pass": 2, "fail": 1, "pass_rate": 0.67, "avg_tokens": 520, "avg_latency_s": 14.5 },
    "code_review":  { "pass": 1, "fail": 2, "pass_rate": 0.33, "avg_tokens": 200, "avg_latency_s": 5.1 },
    "output_check": { "pass": 3, "fail": 0, "pass_rate": 1.0,  "avg_tokens": 80,  "avg_latency_s": 2.8 }
  },
  "overall_pass_rate": 0.67,
  "total_tokens": 3150,
  "total_duration_s": 870,
  "peak_memory_mb": 312
}
```

### per_task/{task_id}.json 结构

```json
{
  "task_id": "code_gen_easy_01",
  "dimension": "code_gen",
  "difficulty": "easy",
  "verdict": "PASS",
  "iteration_count": 2,
  "prompt": "你是一个 TypeScript 程序员...",
  "response": "```typescript\nfunction add(a: number, b: number): number {\n  return a + b;\n}\n```",
  "judge": {
    "method": "sandbox",
    "test_result": { "exit_code": 0, "stdout": "1 passed", "stderr": "" }
  },
  "metrics": {
    "tokens_in": 320,
    "tokens_out": 45,
    "latency_ms": 8234,
    "memory_delta_mb": 12
  }
}
```

## 错误处理

| 故障 | 救援策略 | 标记 |
|------|---------|------|
| 弱模型 API 超时 | 指数退避 3 次 | `api_timeout` |
| 响应非 JSON/无代码块 | 重试提取 2 次 | `parse_error` |
| 沙箱 OOM | 跳过此题 | `env_oom`（不扣分） |
| 沙箱超时 | 跳过此题 | `env_timeout`（不扣分） |
| 网络中断 | 等 30s 重试 3 次 | `network_error` |

**关键：区分「模型失败」和「环境失败」。** 沙箱 OOM/超时不扣分——这是 2GB 环境的限制，不是模型的问题。

## 文件结构

```
niuma/
├── benchmark.py                # 基准测试调度器（新增）
├── task_suite/                 # 题目集（新增）
│   ├── code_gen/
│   │   ├── easy_01.yaml
│   │   ├── medium_02.yaml
│   │   └── hard_03.yaml
│   ├── test_gen/
│   │   └── ...
│   ├── error_diag/
│   ├── code_fix/
│   ├── code_review/
│   └── output_check/
├── benchmark_results/          # 结果输出（新增，.gitignore）
└── llm.py / sandbox.py / ...   # 复用现有基础设施
```

## 决策框架：数据如何驱动后续架构决策

| 数据信号 | 触发决策 |
|---------|---------|
| code_gen 通过率 > 80% | 考虑下放 test_skeleton 生成给弱模型（方案 A） |
| test_gen 通过率 > 60% | 弱模型可以自己写测试——compiler 不再生成 test_skeleton |
| error_diag 通过率 > 80% | 替换 _quick_self_check 为实际错误诊断 |
| code_review 通过率 > 50% | 探索弱模型审查 dag.json 和 review.md |
| output_check 通过率 > 70% | 添加到 worker 流水线：代码产出后自动验证输出 |
| 3+ 维度通过率 > 60% | 方案 B（Worker 多任务化）具备可行性 |
| 所有维度 < 40% | 保持当前架构，专注提升代码生成可靠性 |

## NOT in scope（本阶段不做）

| 项目 | 原因 |
|------|------|
| 修改 worker.py / compiler.py / reviewer.py | 先拿数据再动产品代码 |
| 多弱模型并行基准测试 | 2GB 不支持并行 |
| 强模型参与判定 | 保持 O(1) token 原则 |
| 可视化 HTML 报告 | summary.json 直接可消费 |
