# OpsAgent — 自动化运维监控智能 Agent

> 无人值守运维监控智能体：数据感知、故障推理、自动处置、报表输出

## 核心能力一览

| 模块 | 功能 | 说明 |
|------|------|------|
| 数据采集 | 系统指标 + 服务进程 + 日志 + Docker | psutil 低占用采集 |
| 异常判别 | 静态阈值 + 自适应动态阈值 | 2σ/3σ 自动学习基线 |
| 故障分析 | 规则引擎 + LLM 深度分析 | 根因推断 + 关联分析 |
| 自动处置 | 白名单安全修复 | 服务重启/日志清理/杀僵尸进程 |
| 巡检报表 | HTML 可视化报告 | 柱状图趋势 + 告警汇总 |
| 飞书告警 | Webhook 实时推送 | 三级颜色 + 告警合并 |
| 定时报表 | 后台调度自动生成 | 每日定时或自定义间隔 |
| 记忆复盘 | SQLite 事件存储 | 历史查询 + 统计分析 |

---

## 快速安装

```bash
cd ops-agent
bash scripts/install.sh
```

安装脚本自动完成：检测 Python 3.10+ → 创建虚拟环境 → 安装依赖 → 创建数据目录

## 使用方式

```bash
cd ops-agent
source venv/bin/activate

# 持续运行（默认每60秒巡检一次）
python -m src.main

# 单次巡检（适合 cron 或手动执行）
python -m src.main --once

# 演练模式（只检测，不执行任何处置）
python -m src.main --dry-run

# 指定配置文件
python -m src.main --config /path/to/my-config.yaml
```

### 作为 systemd 服务运行

```bash
bash scripts/setup_service.sh
sudo systemctl start ops-agent
sudo systemctl status ops-agent
```

---

## 功能详解

### 1. 数据采集（Collectors）

**做什么：** 每隔 N 秒采集一次服务器的完整状态快照。

**采集内容：**

- **系统指标** — CPU 使用率、内存使用率、磁盘使用率、系统负载（1m/5m/15m）、网络流量、Uptime
- **服务进程** — 检查指定服务（sshd、nginx、docker 等）是否在运行
- **系统日志** — 增量读取日志文件，匹配错误关键词（error/critical/fatal/oom/segfault）
- **Docker 容器** — 容器列表、运行状态、CPU/内存/网络/磁盘 IO、容器日志
- **systemd journal** — 按 unit 和优先级过滤结构化日志

**配置示例：**

```yaml
collectors:
  cpu_threshold: 85
  memory_threshold: 90
  disk_threshold: 85

services:
  watch:
    - name: sshd
      process: sshd
    - name: nginx
      process: nginx

logs:
  paths:
    - /var/log/syslog
    - /var/log/auth.log
  error_patterns:
    - "error"
    - "critical"
    - "fatal"
    - "oom"
```

**效果：** Agent 每次巡检时生成一份包含所有指标的快照，为后续异常检测提供数据基础。对系统几乎无负载，psutil 直接读 `/proc`，不产生额外进程。

---

### 2. 异常判别（Detectors）

**做什么：** 对采集到的指标进行阈值判断，识别异常。

**两种模式：**

- **静态阈值** — 在配置文件中直接设定（如 CPU > 85% 告警）
- **自适应阈值** — 基于历史数据自动计算，使用滑动窗口统计（均值 + 2σ 为 WARNING，均值 + 3σ 为 CRITICAL），样本不足时自动回退静态阈值

**检测项目：**

| 指标 | WARNING | CRITICAL |
|------|---------|----------|
| CPU 使用率 | 超过动态阈值（默认 85%） | 超过 95% 或 3σ |
| 内存使用率 | 超过动态阈值（默认 90%） | 超过 95% 或 3σ |
| 磁盘使用率 | 超过动态阈值（默认 85%） | 超过 95% 或 3σ |
| 系统负载 | per CPU 负载 > 2.0 | per CPU 负载 > 4.0 |
| 服务状态 | — | 进程不存在 |
| 日志错误 | 非致命错误关键词 | fatal/oom/segfault |
| Docker 容器 | CPU/内存超限 | 容器停止/频繁重启 |

**效果：** 每次巡检输出一份 Issue 列表，按严重程度分为 INFO / WARNING / CRITICAL。自适应阈值会随着运行时间增长越来越精准，减少误报。

---

### 3. 故障分析（Analyzers）

**做什么：** 对检测到的 Issue 进行根因推断和关联分析。

**规则引擎分析：**
- 内存使用率高 + 服务被 OOM Kill → 判定为 OOM 问题，建议加内存或限制进程
- 磁盘满 + 日志文件过大 → 判定为日志膨胀，建议清理或轮转
- 多个服务同时宕机 → 关联分析，可能是系统级故障
- 趋势分析：对比历史数据，判断是突发还是渐进式恶化

**LLM 深度分析（可选）：**
- 接入 OpenAI 兼容 API（支持 DeepSeek、本地 Ollama 等）
- 对告警信息和日志片段进行智能分析
- 输出结构化 JSON：根因推断 + 处置建议
- 分析结果自动附加到飞书告警卡片

**配置 LLM：**

```yaml
llm:
  enabled: true
  api_key: "sk-xxxx"                    # 或 export OPENAI_API_KEY=sk-xxxx
  base_url: "https://api.openai.com/v1" # 改为 DeepSeek/Ollama 等
  model: "gpt-4o-mini"
```

**效果：** 告警不再是干巴巴的"CPU 过高"，而是附带根因分析和具体处置建议。开启 LLM 后，飞书告警卡片会多出一段 AI 分析结论。

---

### 4. 自动处置（Remediators）

**做什么：** 根据分析结果自动执行修复操作。

**白名单机制：** 只有配置中明确允许的操作才会执行，杜绝误操作。

**支持的处置动作：**

| 动作 | 说明 | 触发条件 |
|------|------|----------|
| `restart_service` | 通过 systemctl 重启服务 | 服务宕机 |
| `clear_logs` | 轮转过大的日志文件（不删除） | 日志超过 max_log_size_mb |
| `kill_process` | 终止僵尸进程 | 检测到僵尸进程 |

**安全特性：**
- `dry_run` 模式：只输出会执行什么操作，不实际执行
- 操作审计：每次处置都记录命令、输出、成功/失败
- 白名单外的操作一律跳过

**配置：**

```yaml
remediation:
  enabled: true
  allowed_actions:
    - restart_service
    - clear_logs
    - kill_process
  max_log_size_mb: 500
```

**效果：** 服务挂了自动拉起来，日志爆了自动轮转。全程有审计日志，干了什么一目了然。

---

### 5. 巡检报表（Reporters）

**做什么：** 生成 HTML 可视化巡检报告。

**报表内容：**
- 系统概览卡片（CPU/内存/磁盘/负载的当前值和阈值）
- CSS 柱状图展示指标趋势
- 告警列表（按严重程度排序）
- 处置记录（执行了什么、成功与否）
- 风险建议（基于当前状态的预防性建议）

**效果：** 每次巡检生成一个独立的 HTML 文件，用浏览器打开即可查看。文件名格式：`inspection_{服务器名}_{时间戳}.html`

**示例报告路径：** `reports/inspection_j1900-server_20260523_003546.html`

---

### 6. 飞书告警（Notifiers）

**做什么：** 检测到异常时实时推送到飞书群聊。

**告警卡片特性：**
- 🔴 CRITICAL / 🟡 WARNING / 🔵 INFO 三级颜色区分
- 告警详情：指标值、阈值、触发原因
- 处置结果：自动修复了什么、成功与否
- LLM 分析结论（如已开启）
- 告警合并：60 秒窗口内的多个告警合并为一条消息，避免刷屏

**配置步骤：**

1. 飞书群聊 → 设置 → 群机器人 → 添加「自定义机器人」
2. 复制 Webhook URL
3. 编辑配置：

```yaml
notifier:
  enabled: true
  feishu:
    webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx"
    secret: ""  # 签名密钥，不验签可留空
  alert_merge:
    enabled: true
    window_seconds: 60
```

**推送时机：**
- 异常检测后立即推送告警
- 处置完成后推送处置结果
- 每日巡检摘要推送（需开启定时报表）

---

### 7. 定时报表（Scheduler）

**做什么：** 后台自动生成巡检报告，不阻塞主循环。

**两种调度模式：**
- **每日定时** — 指定时间点，如每天 08:00 生成
- **间隔触发** — 自定义分钟数，如每 1440 分钟（一天）

**配置：**

```yaml
report:
  schedule: "08:00"        # 每天早上 8 点生成
  # 或
  interval_minutes: 720    # 每 12 小时生成一次
```

**效果：** 自动生成报告文件，开启飞书通知后会同步推送报告摘要。

---

### 8. 记忆复盘（Memory）

**做什么：** 用 SQLite 持久化所有事件记录，支持历史查询和统计分析。

**记录内容：**
- 每个 Issue 的完整信息（类型、严重程度、描述、指标值）
- 根因分析结果
- 处置动作和执行结果
- 事件持续时间
- 经验教训（lessons）

**统计能力：**
- 总事件数、各类型事件分布
- 解决率（resolved / total）
- 常见故障类型排名
- 按时间范围查询历史事件

**效果：** 运行时间越长，积累的故障案例越多。Agent 可以参考历史案例优化后续处理策略。数据库文件：`data/ops_agent.db`

---

## 配置文件完整参考

配置文件位于 `config/default.yaml`，所有字段均有注释。核心配置项：

```yaml
server:
  name: "my-server"              # 服务器名称
  check_interval: 60             # 巡检间隔（秒）

collectors:
  cpu_threshold: 85              # CPU 静态告警阈值（%）
  memory_threshold: 90           # 内存静态告警阈值（%）
  disk_threshold: 85             # 磁盘静态告警阈值（%）
  load_multiplier: 2.0           # 负载告警倍数（per CPU）

services:                        # 监控的服务列表
  watch:
    - name: sshd
      process: sshd

logs:                            # 日志监控
  paths: [/var/log/syslog]
  error_patterns: ["error", "critical", "fatal", "oom"]
  max_lines_per_check: 1000

remediation:                     # 自动处置
  enabled: true
  allowed_actions: [restart_service, clear_logs, kill_process]
  max_log_size_mb: 500

notifier:                        # 飞书告警
  enabled: false
  feishu:
    webhook_url: ""

llm:                             # LLM 智能分析
  enabled: false
  api_key: ""
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o-mini"

report:                          # 巡检报表
  output_dir: ./reports
  schedule: ""
  interval_minutes: 1440

memory:                          # 记忆存储
  db_path: data/ops_agent.db
  max_records: 10000
```

## 运行测试

```bash
python -m pytest tests/ -v
```

42+ 单元测试，覆盖全部核心模块。

## 目录结构

```
ops-agent/
├── config/
│   └── default.yaml             # 默认配置
├── src/
│   ├── collectors/              # 数据采集（系统/Docker/journal/日志）
│   ├── detectors/               # 异常判别（静态阈值/自适应阈值）
│   ├── analyzers/               # 故障分析（规则引擎/LLM）
│   ├── remediators/             # 自动处置
│   ├── reporters/               # 巡检报表 + HTML 模板
│   ├── notifiers/               # 告警通知（飞书）
│   ├── scheduler/               # 定时调度
│   ├── memory/                  # 记忆复盘（SQLite）
│   ├── models.py                # 数据模型定义
│   └── main.py                  # 主入口
├── tests/                       # 单元测试
├── scripts/
│   ├── install.sh               # 一键安装
│   └── setup_service.sh         # systemd 服务安装
├── reports/                     # 报表输出目录
├── data/                        # SQLite 数据存储
├── docs/                        # 项目文档
└── requirements.txt
```

## 技术栈

- Python 3.10+
- psutil — 系统指标采集（读 /proc，极低开销）
- SQLite — 事件存储（Python 内置，无需额外服务）
- Jinja2 — 报表模板渲染
- PyYAML — 配置管理
- systemd — 服务管理
