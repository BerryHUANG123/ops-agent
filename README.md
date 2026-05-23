# OpsAgent — 自动化运维监控智能 Agent

> 无人值守运维监控智能体：数据感知、故障推理、自动处置、报表输出

## 核心能力

- **数据采集** — CPU/内存/磁盘/负载/网络/进程/Docker 容器
- **异常判别** — 静态阈值 + 自适应动态阈值（2σ/3σ）
- **故障溯源** — 规则引擎根因推断 + LLM 深度分析
- **自动处置** — 白名单机制，服务重启/日志清理/僵尸进程处理
- **巡检报表** — HTML 可视化报告，柱状图趋势展示
- **飞书告警** — Webhook 实时推送，告警合并，处置结果回传
- **定时报表** — 后台调度自动生成，飞书摘要推送
- **记忆复盘** — SQLite 持久化事件存储，历史查询与统计

## 快速安装

```bash
cd ops-agent
bash scripts/install.sh
```

安装脚本会自动：
- 检测 Python 3.10+
- 创建虚拟环境 (venv)
- 安装依赖（psutil、jinja2、pyyaml）
- 创建 data/ 和 reports/ 目录

## 使用方式

### 激活虚拟环境

```bash
cd ops-agent
source venv/bin/activate
```

### 启动模式

```bash
# 持续运行（默认每60秒检查一次）
python -m src.main

# 单次检查（适合 cron 调度或手动巡检）
python -m src.main --once

# 演练模式（只检测，不执行任何处置操作）
python -m src.main --dry-run

# 指定配置文件
python -m src.main --config /path/to/config.yaml
```

### 作为 systemd 服务运行（推荐生产环境）

```bash
# 安装并启动服务
bash scripts/setup_service.sh

# 管理服务
sudo systemctl start ops-agent
sudo systemctl stop ops-agent
sudo systemctl status ops-agent
sudo journalctl -u ops-agent -f   # 查看日志
```

## 配置说明

配置文件位于 `config/default.yaml`：

```yaml
server:
  name: "my-server"        # 服务器名称（报表和告警中显示）
  check_interval: 60       # 检查间隔（秒）

collectors:
  cpu_threshold: 85        # CPU 告警阈值（%）
  memory_threshold: 90     # 内存告警阈值（%）
  disk_threshold: 85       # 磁盘告警阈值（%）
  load_multiplier: 2.0     # 负载告警倍数（per CPU）

services:                  # 监控的服务列表
  watch:
    - name: sshd
      process: sshd
    - name: nginx
      process: nginx
    - name: docker
      process: dockerd

logs:
  paths:                   # 监控的日志文件
    - /var/log/syslog
    - /var/log/auth.log
  error_patterns:          # 错误关键词
    - "error"
    - "critical"
    - "fatal"
    - "oom"
  max_lines_per_check: 1000

remediation:
  enabled: true            # 是否启用自动处置
  allowed_actions:         # 允许的处置动作白名单
    - restart_service
    - clear_logs
    - kill_process
  max_log_size_mb: 500     # 日志超过此大小触发清理

# ===== 飞书告警 =====
notifier:
  enabled: false           # 改为 true 启用
  feishu:
    webhook_url: ""        # 飞书自定义机器人 Webhook URL
    secret: ""             # 签名密钥（可选）
  alert_merge:
    enabled: true
    window_seconds: 60     # 告警合并窗口

# ===== LLM 智能分析 =====
llm:
  enabled: false           # 改为 true 启用
  api_key: ""              # 或设置环境变量 OPENAI_API_KEY
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o-mini"
  timeout: 30

report:
  output_dir: ./reports    # 报表输出目录
  format: html
  schedule: ""             # 每日定时，如 "08:00"
  interval_minutes: 1440   # 间隔生成（默认每天）
```

## 飞书告警配置

1. 在飞书群聊中添加「自定义机器人」
2. 复制 Webhook URL
3. 编辑 `config/default.yaml`：

```yaml
notifier:
  enabled: true
  feishu:
    webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx"
```

告警会以卡片形式推送，包含：
- 🔴 CRITICAL / 🟡 WARNING / 🔵 INFO 三级颜色
- 告警详情、根因分析、处置结果
- 短时间多告警自动合并

## LLM 智能分析配置

接入大模型进行深度告警分析（根因推断 + 处置建议）：

```yaml
llm:
  enabled: true
  api_key: "sk-xxxx"          # 或 export OPENAI_API_KEY=sk-xxxx
  base_url: "https://api.openai.com/v1"  # 兼容 OpenAI API 的任意服务
  model: "gpt-4o-mini"
```

支持任意 OpenAI 兼容 API（如 DeepSeek、本地 Ollama 等），修改 `base_url` 即可。

## 运行测试

```bash
python -m pytest tests/ -v
```

## 目录结构

```
ops-agent/
├── config/
│   └── default.yaml          # 默认配置
├── docs/                      # 项目文档
│   ├── API.md                 # 模块接口说明
│   ├── ARCHITECTURE.md        # 架构设计
│   ├── CHANGELOG.md           # 版本记录
│   ├── DEPLOYMENT.md          # 部署指南
│   └── PROJECT_CHARTER.md     # 立项文档
├── src/
│   ├── collectors/            # 数据采集（系统/Docker/journal/日志）
│   ├── detectors/             # 异常判别（静态阈值/自适应阈值）
│   ├── analyzers/             # 故障分析（规则引擎/LLM）
│   ├── remediators/           # 自动处置
│   ├── reporters/             # 巡检报表
│   ├── notifiers/             # 告警通知（飞书）
│   ├── scheduler/             # 定时调度
│   ├── memory/                # 记忆复盘
│   ├── models.py              # 数据模型
│   └── main.py                # 主入口
├── tests/                     # 42+ 单元测试
├── scripts/
│   ├── install.sh             # 安装脚本
│   └── setup_service.sh       # systemd 服务安装
├── reports/                   # 报表输出目录
├── data/                      # SQLite 数据存储
└── requirements.txt
```

## 技术栈

- Python 3.10+
- psutil — 系统指标采集
- SQLite — 状态/记忆存储
- Jinja2 — 报表模板渲染
- PyYAML — 配置管理
- systemd — 服务管理
