# OpsAgent — 自动化运维监控智能 Agent

> 无人值守运维监控智能体：数据感知、故障推理、自动处置、报表输出

> 🚀 **在线演示**: https://treasure-lion-consequences-leads.trycloudflare.com/
> 账号: `admin` / 密码: `424709`

## 核心能力一览

| 模块 | 功能 | 说明 |
|------|------|------|
| 数据采集 | 系统指标 + 服务进程 + 日志 + Docker + SMART + 网络 | psutil 低占用采集 |
| 异常判别 | 静态阈值 + 自适应动态阈值 + 告警去重 + 自动解决 | 2σ/3σ 自动学习基线 |
| 故障分析 | 规则引擎 + LLM 深度分析 | 根因推断 + 关联分析 |
| 自动处置 | 白名单安全修复 + 审计日志 | 服务重启/日志清理/杀僵尸进程 |
| 巡检报表 | HTML 可视化报告 | 柱状图趋势 + 告警汇总 |
| 飞书告警 | Webhook 实时推送 | 三级颜色 + 告警合并 + 交互按钮 |
| 邮件通知 | SMTP HTML 邮件 | 飞书备用通道 |
| 定时报表 | 后台调度自动生成 | 每日定时或自定义间隔 |
| 记忆复盘 | SQLite 事件存储 | 历史查询 + 统计分析 |
| Web UI | 浏览器管理界面 | 7 个页面 + 6 套主题 + RBAC 权限 |
| SMART 监控 | 磁盘健康检测 | 坏扇区/温度/通电时间 |
| 网络监控 | 监听端口 + 活跃连接 | 可疑端口/进程检测 |
| 进程监控 | Top N 资源占用 | CPU/内存排序 |
| 磁盘预测 | 增长趋势分析 | 线性回归预测满盘日期 |
| 告警静默 | 时间段/类型静默规则 | 深夜不刷屏 |
| 自身健康 | Agent/Web 进程监控 | 内存超限自告警 |
| 审计日志 | 操作全程记录 | 谁/何时/做了什么 |
| RBAC | 角色权限控制 | admin/viewer 两级 |

---

## 快速安装

```bash
cd ops-agent
bash scripts/install.sh
```

安装脚本自动完成：检测 Python 3.10+ → 创建虚拟环境 → 安装依赖 → 创建数据目录

## 使用方式

### 命令行启动

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

### 作为 systemd 服务运行（推荐生产环境）

```bash
bash scripts/setup_service.sh
sudo systemctl start ops-agent
sudo systemctl status ops-agent
```

---

### Web UI 管理界面

OpsAgent 内置轻量 Web UI，提供浏览器端可视化管理。

```bash
# 启动 Web UI
python3 -m src.web.run --port 8080

# 自定义地址和端口
python3 -m src.web.run --host 127.0.0.1 --port 9090
```

启动后访问 `http://服务器IP:8080`

**功能页面：**

- **📊 仪表盘** — 实时系统指标（CPU/内存/磁盘/负载/网络），服务状态，Docker 容器状态，事件统计，10 秒自动刷新
- **🚨 告警记录** — 所有历史告警，支持标记解决/删除/全部解决
- **📋 巡检报告** — 报告列表，点击直接在浏览器中查看 HTML 报告
- **⚙️ 配置** — 查看当前运行配置（敏感信息自动脱敏）
- **📝 审计日志** — 所有自动处置操作记录（需登录）
- **💚 健康状态** — 进程资源/监听端口/活跃连接/磁盘预测（需登录）
- **🔐 登录** — RBAC 权限控制，admin/viewer 两级角色

**特性：**
- 暗色主题，6 套主题可切换（暗色/亮色/赛博朋克/海洋蓝/森林绿/樱花粉）
- 全局 Toast 提示 + 现代化确认弹窗
- API 端点：`/api/metrics`、`/api/incidents`、`/api/processes`、`/api/network`、`/api/health`
- 内存占用 ~22MB

**作为 systemd 服务运行：**

```bash
systemctl --user start ops-agent-web
systemctl --user status ops-agent-web
systemctl --user stop ops-agent-web
```

---

## 功能详解

### 1. 数据采集（Collectors）

**做什么：** 每隔 N 秒采集一次服务器的完整状态快照。

**采集内容：**

- **系统指标** — CPU 使用率、内存使用率、磁盘使用率、系统负载（1m/5m/15m）、网络流量、Uptime
- **服务进程** — 检查指定服务（sshd、docker 等）是否在运行
- **系统日志** — 增量读取日志文件，匹配错误关键词，支持忽略模式过滤噪音
- **Docker 容器** — 容器列表、运行状态、CPU/内存/网络/磁盘 IO、容器日志
- **systemd journal** — 按 unit 和优先级过滤结构化日志
- **SMART 磁盘** — 健康状态、待重映射扇区、温度、通电时间
- **网络连接** — 监听端口、活跃连接、可疑端口检测

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
    - name: docker
      process: dockerd

logs:
  paths:
    - /var/log/syslog
    - /var/log/auth.log
  error_patterns:
    - "error"
    - "critical"
    - "fatal"
    - "oom"
  ignore_patterns:
    - "node["
    - "ignoring stale"

docker:
  skip_stopped: true
  ignore_containers:
    - hello-world
```

---

### 2. 异常判别（Detectors）

**两种模式：**

- **静态阈值** — 在配置文件中直接设定（如 CPU > 85% 告警）
- **自适应阈值** — 基于历史数据自动计算，使用滑动窗口统计（均值 + 2σ 为 WARNING，均值 + 3σ 为 CRITICAL）

**告警去重：** 相同类型+标题的问题只记录一次，不重复入库。连续出现 10 次自动升级为 CRITICAL。问题消失后自动标记 resolved。

---

### 3. 故障分析（Analyzers）

**规则引擎分析：**
- 内存使用率高 + 服务被 OOM Kill → 判定为 OOM 问题
- 磁盘满 + 日志文件过大 → 判定为日志膨胀
- 多个服务同时宕机 → 关联分析

**LLM 深度分析（可选）：**

```yaml
llm:
  enabled: true
  api_key: "sk-xxxx"
  base_url: "https://api.openai.com/v1"  # 支持 DeepSeek/Ollama 等
  model: "gpt-4o-mini"
```

---

### 4. 自动处置（Remediators）

**白名单机制：** 只有配置中明确允许的操作才会执行。

| 动作 | 说明 | 触发条件 |
|------|------|----------|
| `restart_service` | 通过 systemctl 重启服务 | 服务宕机 |
| `clear_logs` | 轮转过大的日志文件 | 日志超过 max_log_size_mb |
| `kill_process` | 终止僵尸进程 | 检测到僵尸进程 |

所有处置操作自动记录到审计日志。

---

### 5. SMART 磁盘监控

```yaml
# 自动检测：
# - 磁盘健康状态 PASSED/FAILED
# - 待重映射扇区 > 0 → 告警
# - 重映射扇区 > 0 → 告警
# - 温度 > 60°C → 告警
```

需要 `smartmontools` 已安装，且 sudo 免密配置。

---

### 6. 告警静默规则

```yaml
silence:
  enabled: true
  rules:
    - name: "夜间静默"
      start_hour: 23
      end_hour: 7
      min_severity: "critical"
    - name: "已知噪音过滤"
      issue_type: "log_error"
      title_contains: ["cloudflared", "WRN"]
      action: "suppress"
```

---

### 7. RBAC 权限控制

```yaml
webui:
  auth:
    enabled: true
    users:
      admin:
        password: "your-strong-password"
        role: "admin"
      guest:
        password: "guest"
        role: "viewer"
```

**权限模型：**

| 页面/接口 | 未登录 | viewer | admin |
|-----------|--------|--------|-------|
| 仪表盘/告警/报告 | ✅ | ✅ | ✅ |
| 配置（脱敏） | ✅ | ✅ | ✅ |
| 健康/进程/网络 | ❌ | ❌ | ✅ |
| 审计日志 | ❌ | ❌ | ✅ |
| 解决/删除告警 | ❌ | ❌ | ✅ |

---

### 8. 飞书告警

```yaml
notifier:
  enabled: true
  feishu:
    webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx"
  alert_merge:
    enabled: true
    window_seconds: 60
```

告警卡片包含交互按钮：已知晓 / 静默1小时 / 查看报告。

---

### 9. 邮件告警

```yaml
notifier:
  email:
    enabled: true
    smtp_host: "smtp.qq.com"
    smtp_port: 465
    username: "your-email@qq.com"
    password: "your-auth-code"
    from_addr: "your-email@qq.com"
    to_addrs: ["admin@example.com"]
```

---

## 公网访问

OpsAgent 支持通过 Cloudflare Tunnel 暴露到公网：

```bash
# 安装 cloudflared
# 启动快速隧道
cloudflared tunnel --url http://localhost:8080
```

**安全建议：**
- 启用 RBAC 登录
- 修改默认密码
- 健康/进程等敏感页面需登录才能访问
- 配置页面敏感信息自动脱敏

---

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
│   ├── collectors/              # 数据采集（系统/Docker/journal/日志/SMART/网络）
│   ├── detectors/               # 异常判别（静态阈值/自适应阈值/去重）
│   ├── analyzers/               # 故障分析（规则引擎/LLM）
│   ├── remediators/             # 自动处置
│   ├── reporters/               # 巡检报表 + HTML 模板
│   ├── notifiers/               # 告警通知（飞书/邮件）
│   ├── scheduler/               # 定时调度
│   ├── memory/                  # 记忆复盘（SQLite）
│   ├── web/                     # Web UI（Flask）
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

## 快速部署

### 环境要求

- Python 3.10+
- Linux（Ubuntu/Debian/CentOS）
- sudo 权限（SMART 监控需要）

### 一键安装

```bash
# 1. 克隆项目
git clone <repo-url> /opt/ops-agent
cd /opt/ops-agent

# 2. 安装依赖
pip install -r requirements.txt

# 3. 创建数据目录
mkdir -p data reports

# 4. 启动服务
python3 -m src.main &           # Agent 后台巡检
python3 -m src.web.run --port 8080 &  # Web UI

# 5. 访问
# http://localhost:8080
# 默认账号: admin / 424709
```

### systemd 服务部署（推荐）

```bash
# 安装服务
./scripts/setup_service.sh

# 常用命令
systemctl --user status ops-agent       # 查看 Agent 状态
systemctl --user status ops-agent-web   # 查看 Web UI 状态
systemctl --user restart ops-agent-web  # 重启 Web UI
journalctl --user -u ops-agent-web -f   # 查看日志
```

### 迁移到其他机器

```bash
# 在源机器打包（不需要历史数据）
./scripts/migrate.sh

# 在目标机器安装
tar xzf /tmp/ops-agent-*.tar.gz
cd ops-agent
./scripts/setup.sh
```

### 项目结构

```
ops-agent/
├── src/
│   ├── main.py                  # Agent 主入口（采集→检测→分析→处置）
│   ├── models.py                # 数据模型
│   ├── collectors/              # 数据采集器
│   │   ├── system_collector.py  # CPU/内存/磁盘/负载
│   │   ├── log_collector.py     # 日志错误检测
│   │   ├── docker_collector.py  # Docker 容器监控
│   │   ├── journal_collector.py # systemd journal
│   │   ├── smart_collector.py   # 磁盘 SMART
│   │   └── network_collector.py # 网络连接监控
│   ├── detectors/               # 异常检测
│   │   ├── anomaly_detector.py  # 静态阈值 + 自适应阈值
│   │   └── adaptive_threshold.py
│   ├── analyzers/               # 故障分析
│   │   ├── fault_analyzer.py    # 规则引擎
│   │   └── llm_analyzer.py      # LLM 智能分析
│   ├── remediators/             # 自动处置
│   │   └── auto_remediator.py
│   ├── reporters/               # 报表生成
│   │   └── report_generator.py
│   ├── notifiers/               # 告警通知
│   │   ├── feishu_notifier.py   # 飞书 Webhook
│   │   └── email_notifier.py    # 邮件通知
│   ├── memory/                  # 事件记忆
│   │   └── incident_memory.py
│   ├── incidents/               # 事件生命周期管理
│   │   └── incident_manager.py
│   ├── trackers/                # 变更追踪
│   │   └── change_tracker.py
│   ├── slo/                     # SLO 管理
│   │   ├── slo_manager.py
│   │   ├── sli_collectors.py
│   │   └── error_budget.py
│   ├── scheduler/               # 定时报表
│   │   └── report_scheduler.py
│   └── web/                     # Web UI
│       ├── app.py               # Flask 应用 + API
│       ├── run.py               # 启动入口
│       ├── templates/           # Jinja2 模板
│       │   ├── base.html        # 布局（侧边栏/主题/公共组件）
│       │   ├── dashboard.html   # 仪表盘（概览/资源/服务 tab）
│       │   ├── health.html      # 健康状态
│       │   ├── incidents_v2.html # 事件管理（搜索/筛选/时间线）
│       │   ├── slo.html         # SLO 管理（在线编辑）
│       │   ├── changes.html     # 变更记录
│       │   ├── config.html      # 配置编辑器（yaml 实时校验）
│       │   ├── reports.html     # 巡检报告（一键生成/对比）
│       │   ├── audit.html       # 审计日志
│       │   └── login.html       # 登录页
│       └── static/              # 静态资源
│           ├── themes.css       # 6 套主题
│           ├── chart.umd.min.js # Chart.js
│           └── favicon.svg
├── config/
│   └── default.yaml             # 主配置文件
├── runbooks/                    # 处理手册（每个告警类型）
│   ├── cpu_high.md
│   ├── memory_high.md
│   ├── disk_high.md
│   ├── load_high.md
│   ├── service_down.md
│   ├── log_error.md
│   └── disk_smart.md
├── scripts/
│   ├── install.sh               # 一键安装
│   ├── setup_service.sh         # systemd 服务安装
│   ├── setup.sh                 # 目标机器安装向导
│   └── migrate.sh               # 迁移打包脚本
├── reports/                     # 报表输出目录
├── data/                        # SQLite 数据存储
├── docs/                        # 项目文档
├── requirements.txt             # Python 依赖
└── README.md
```

### 配置说明

配置文件: `config/default.yaml`

```yaml
server:
  name: "my-server"
  check_interval: 60  # 巡检间隔（秒）

# 告警阈值
collectors:
  cpu_threshold: 85
  memory_threshold: 90
  disk_threshold: 85

# 监控服务
services:
  watch:
    - name: sshd
      process: sshd
    - name: docker
      process: dockerd

# SLO 目标
slo:
  enabled: true
  services:
    - name: sshd
      sli_type: uptime
      target: 99.9
      window_days: 30
```

## 技术栈

- Python 3.10+
- psutil — 系统指标采集（读 /proc，极低开销）
- SQLite — 事件存储（Python 内置，无需额外服务）
- Jinja2 — 报表模板渲染
- PyYAML — 配置管理
- Flask + Flask-SocketIO — Web UI + WebSocket
- Chart.js — 趋势图表
- systemd — 服务管理
- smartmontools — SMART 磁盘监控

## Web UI 功能

| 页面 | 功能 |
|------|------|
| 仪表盘 | 健康状态 Banner + 系统指标 + CPU/内存/磁盘趋势 + SLO + 告警 |
| 健康状态 | Agent 进程/内存/CPU + 系统资源 + 端口/连接/进程 Top N |
| 事件管理 | 搜索/筛选 + 级别分级 + 时间线 + Runbook 处理手册 |
| SLO 管理 | 在线编辑目标值 + Error Budget 趋势图 |
| 变更记录 | 配置变更追踪 + yaml diff 对比 |
| 配置 | yaml 在线编辑器 + 实时语法校验 + Ctrl+S 保存 |
| 巡检报告 | 一键生成 + 两份报告 diff 对比 |
| 审计日志 | 操作记录查询 |

## 运维命令速查

```bash
# 服务管理
systemctl --user start ops-agent ops-agent-web
systemctl --user stop ops-agent ops-agent-web
systemctl --user restart ops-agent-web

# 查看日志
journalctl --user -u ops-agent -f           # Agent 日志
journalctl --user -u ops-agent-web -f       # Web UI 日志

# 手动生成报告
python3 -m src.main --report-only

# 只执行一次巡检
python3 -m src.main --once

# 只执行 SLO 检查
python3 -m src.main --slo-check

# 查看数据库
sqlite3 data/ops_agent.db ".tables"
sqlite3 data/ops_agent.db "SELECT * FROM incidents_v2 ORDER BY created_at DESC LIMIT 10;"
```
