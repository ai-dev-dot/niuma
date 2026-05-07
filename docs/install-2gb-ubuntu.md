# 2GB Ubuntu 服务器安装指南

2026-05-07 实测记录 — 阿里云 2GB Ubuntu 24.04 云服务器

## 环境

- OS: Ubuntu 24.04 (Noble)
- RAM: 2 GB
- Python: 3.12.3（系统自带 `python3`，无 `python` 命令）
- 预装: curl, jq（系统自带），git

## 安装步骤

### 1. clone 项目

```bash
git clone https://github.com/ai-dev-dot/niuma.git
cd niuma
chmod +x niuma
```

### 2. 系统工具

```bash
sudo apt-get install -y sqlite3
# curl 和 jq 通常已预装，没有则: sudo apt-get install -y curl jq
```

### 3. 首次启动

```bash
./niuma
```

首次运行会自动：
- 检测 `python3`（Ubuntu 无 `python` 命令）
- 安装 pip 依赖（pytest, flask, requests）—— 使用 `--break-system-packages` 绕过 PEP 668 限制
- 安装 npm 依赖（jest, ts-jest, typescript）
- 检查系统工具（curl, jq, sqlite3）

如果 pip 安装失败，手动执行：
```bash
pip install --break-system-packages pytest flask requests
```

### 4. 配置模型

按 TUI 菜单：
1. 配置强模型 — 选供应商、填 API Key、选模型
2. 配置弱模型 — 同上

API Key 和 Token 输入时不再回显（使用 getpass）。

### 5. 创建项目

TUI 菜单 → 3 管理项目 → N 新建项目：
- 输入项目名称
- 输入 Git 仓库地址
- 根据协议类型（HTTPS / SSH）自动引导凭据配置
- HTTPS: 引导创建 Personal Access Token → 自动配置 `credential.helper store` → 播种凭据
- SSH: 检查密钥 → 引导生成 + 添加公钥

### 6. 验证环境

```bash
python3 main.py --doctor
```

检查项：Python、Node.js、node_modules、pytest、config、git 凭据、SSH 密钥、curl、jq、sqlite3。

### 7. 运行基准测试

```bash
PYTHONIOENCODING=utf-8 python3 benchmark.py --dim output_check   # 最快，验证环境
PYTHONIOENCODING=utf-8 python3 benchmark.py                       # 全量 18 题
```

## 已知问题

| 问题 | 状态 |
|------|------|
| Ubuntu 无 `python` 命令，只有 `python3` | 已修复 — niuma 脚本自动检测 `python3` |
| `pip install` 被 PEP 668 限制 | 已修复 — 自动加 `--break-system-packages` |
| `chmod +x niuma` 后 `git pull` 冲突 | 临时修复 `git checkout -- niuma && git pull` |
| Flask API 任务在 2GB 下启动超时 | 标记为环境限制，不扣分 |
| 基准测试 ERR 不显示在「失败」列 | 已修复 — ERR 合并到 FAIL 计数 |

## 注意事项

- 所有 Python 命令用 `python3`，不要用 `python`
- `git pull` 前如果 `chmod` 或手动改过文件，先 `git checkout -- niuma`
- pip 安装如果提示 `externally-managed-environment`，加 `--break-system-packages`
