# niuma — 牛马

榨干所有闲置的硬件，不浪费1个token。

## 项目概述

一个分布式任务调度与执行系统，核心思想：让能力强的大模型（调度者/评审者）给能力弱的小模型（执行者）分配任务，小模型在资源受限的环境中不断测试、修复、校验，直到产出合格结果，提交给大模型审核。

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
