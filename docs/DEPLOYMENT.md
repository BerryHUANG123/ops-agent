# OpsAgent 部署指南

> 版本：V1.0 | 更新日期：2026-05-23

---

## 目录

- [环境要求](#环境要求)
- [快速部署](#快速部署)
- [手动部署](#手动部署)
- [配置说明](#配置说明)
- [systemd 管理](#systemd-管理)
- [验证部署](#验证部署)
- [常见问题](#常见问题)
- [卸载](#卸载)

---

## 环境要求

### 硬件

| 资源 | 最低要求 | 推荐 |
|------|----------|------|
| 架构 | x86_64 / ARM64 | x86_64 |
| 内存 | 512MB | 1GB+ |
| 磁盘 | 100MB 可用空间 | 1GB+ |
| CPU | 任意 | 任意 |

### 软件

| 组件 | 要求 |
|------|------|
| 操作系统 | CentOS 7+ / Ubuntu 18.04+ / Debian 10+ |
| Python | ≥ 3.10 |
| pip | 任意版本 |
| systemd | 任意版本 |

### 权限

- 安装阶段：需要 root 或 sudo 权限
- 运行阶段：以专用用户 `opsagent` 运行，通过 sudoers 授权特定命令

---

## 快速部署

适用于全新环境，一键完成所有步骤。

```bash
# 1. 克隆项目
git clone <repo-url> /opt/ops-agent
cd /opt/ops-agent

# 2. 执行安装脚本
sudo bash scripts/install.sh
```

安装脚本自动完成：
- ✅ 检查 Python 版本
- ✅ 创建专用用户 `opsagent`
- ✅ 安装 Python 依赖
- ✅ 创建必要目录（logs、reports、data）
- ✅ 生成默认配置文件
- ✅ 安装 systemd service
- ✅ 启动服务

---

## 手动部署

适用于需要自定义安装路径或配置的场景。

### 步骤 1：安装系统依赖

**CentOS / RHEL：**

```bash
sudo yum install -y python3 python3-pip
```

**Ubuntu / Debian：**

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
```

### 步骤 2：创建专用用户

```bash
sudo useradd -r -s /bin/false -d /opt/ops-agent opsagent
```

### 步骤 3：部署代码

```bash
# 复制项目文件
sudo mkdir -p /opt/ops-agent
sudo cp -r . /opt/ops-agent/
cd /opt/ops-agent

# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

**requirements.txt 内容：**

```
psutil>=5.9.0
jinja2>=3.1.0
apscheduler>=3.10.0
pyyaml>=6.0
```

### 步骤 4：创建目录结构

```bash
sudo mkdir -p /opt/ops-agent/{logs,reports,data}
```

**目录说明：**

```
/opt/ops-agent/
├── ops_agent/          # 源代码
│   ├── __init__.py
│   ├── collector.py    # 采集模块
│   ├── detector.py     # 检测模块
│   ├── executor.py     # 执行模块
│   ├── memory.py       # 记忆模块
│   ├── reporter.py     # 报表模块
│   ├── scheduler.py    # 调度引擎
│   └── config.py       # 配置管理
├── templates/          # Jinja2 模板
│   └── daily_report.html
├── config.yaml         # 配置文件
├── scripts/            # 辅助脚本
│   └── install.sh
├── logs/               # 日志目录
├── reports/            # 报表输出目录
├── data/               # 数据目录（SQLite）
│   └── ops_agent.db
├── venv/               # Python 虚拟环境
├── requirements.txt
└── README.md
```

### 步骤 5：配置文件

复制默认配置：

```bash
cp config.yaml.example config.yaml
```

详见 [配置说明](#配置说明) 章节。

### 步骤 6：设置权限

```bash
sudo chown -R opsagent:opsagent /opt/ops-agent
sudo chmod 750 /opt/ops-agent
sudo chmod 640 /opt/ops-agent/config.yaml
```

### 步骤 7：配置 sudoers

允许 opsagent 用户执行特定管理命令：

```bash
sudo visudo -f /etc/sudoers.d/opsagent
```

添加以下内容：

```
# OpsAgent 允许的命令
opsagent ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *
opsagent ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *
opsagent ALL=(ALL) NOPASSWD: /usr/bin/journalctl
opsagent ALL=(ALL) NOPASSWD: /usr/bin/docker system prune -f
opsagent ALL=(ALL) NOPASSWD: /bin/rm -f /var/log/*.gz
opsagent ALL=(ALL) NOPASSWD: /bin/rm -f /var/log/*.old
opsagent ALL=(ALL) NOPASSWD: /bin/rm -rf /tmp/ops-cleanup-*
```

### 步骤 8：安装 systemd 服务

```bash
sudo cp scripts/ops-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ops-agent
sudo systemctl start ops-agent
```

---

## 配置说明

配置文件路径：`/opt/ops-agent/config.yaml`

### 完整配置示例

```yaml
# OpsAgent 配置文件

# 通用设置
general:
  log_level: INFO              # 日志级别: DEBUG/INFO/WARNING/ERROR
  log_file: logs/ops-agent.log # 日志文件路径
  db_path: data/ops_agent.db   # SQLite 数据库路径
  report_dir: reports/         # 报表输出目录

# 采集模块配置
collector:
  interval: 30                 # 采集间隔（秒）
  metrics:                     # 启用的采集项
    cpu: true
    memory: true
    disk: true
    network: true
    process: true
  process_top_n: 10            # 进程 TOP N 数量
  disk_mountpoints:            # 监控的磁盘挂载点（空 = 全部）
    - /
    - /data

# 检测模块配置
detector:
  rules:
    # CPU 告警
    - name: cpu_warning
      metric: cpu_percent
      condition: "> 80"
      severity: warning
      cooldown: 300
      action: send_alert
      enabled: true

    - name: cpu_critical
      metric: cpu_percent
      condition: "> 95"
      severity: critical
      cooldown: 60
      action: send_alert
      enabled: true

    # 内存告警
    - name: memory_warning
      metric: memory_percent
      condition: "> 80"
      severity: warning
      cooldown: 300
      action: send_alert
      enabled: true

    - name: memory_critical
      metric: memory_percent
      condition: "> 95"
      severity: critical
      cooldown: 60
      action: send_alert
      enabled: true

    # 磁盘告警
    - name: disk_warning
      metric: disk_percent
      condition: "> 70"
      severity: warning
      cooldown: 600
      action: cleanup_logs
      enabled: true

    - name: disk_critical
      metric: disk_percent
      condition: "> 90"
      severity: critical
      cooldown: 300
      action: cleanup_logs
      enabled: true

    # 负载告警
    - name: load_warning
      metric: load_avg_5m
      condition: "> 4"
      severity: warning
      cooldown: 300
      action: send_alert
      enabled: true

    # 僵尸进程
    - name: zombie_process
      metric: process_zombie_count
      condition: "> 5"
      severity: warning
      cooldown: 600
      action: send_alert
      enabled: true

# 执行器配置
executor:
  dry_run: false               # 是否模拟模式（true = 仅记录不执行）
  timeout: 30                  # 动作超时时间（秒）
  cleanup_logs:
    paths:                     # 日志清理路径
      - /var/log/*.gz
      - /var/log/*.old
      - /var/log/*.[0-9]*
    max_age_days: 7            # 保留天数
  cleanup_tmp:
    paths:
      - /tmp
    max_age_days: 3
  custom_scripts_dir: scripts/custom/  # 自定义脚本目录

# 报表模块配置
reporter:
  enabled: true
  daily_report_time: "00:00"   # 日报生成时间
  keep_reports_days: 30        # 报表保留天数

# 记忆模块配置
memory:
  cleanup_days: 30             # 数据保留天数
  cleanup_time: "03:00"        # 数据清理时间
```

### 环境变量覆盖

支持通过环境变量覆盖配置项：

```bash
export OPSAGENT_LOG_LEVEL=DEBUG
export OPSAGENT_DB_PATH=/var/lib/ops-agent/ops_agent.db
export OPSAGENT_DRY_RUN=true
```

---

## systemd 管理

### 服务单元文件

路径：`/etc/systemd/system/ops-agent.service`

```ini
[Unit]
Description=OpsAgent - Linux Server Operations Assistant
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=opsagent
Group=opsagent
WorkingDirectory=/opt/ops-agent
ExecStart=/opt/ops-agent/venv/bin/python -m ops_agent.scheduler
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ops-agent

# 安全加固
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/ops-agent/logs /opt/ops-agent/reports /opt/ops-agent/data
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 常用命令

```bash
# 启动服务
sudo systemctl start ops-agent

# 停止服务
sudo systemctl stop ops-agent

# 重启服务
sudo systemctl restart ops-agent

# 查看状态
sudo systemctl status ops-agent

# 查看日志
sudo journalctl -u ops-agent -f

# 开机自启
sudo systemctl enable ops-agent

# 禁用开机自启
sudo systemctl disable ops-agent

# 热重载配置（不重启服务）
sudo systemctl reload ops-agent
```

---

## 验证部署

### 1. 检查服务状态

```bash
sudo systemctl status ops-agent
```

预期输出：

```
● ops-agent.service - OpsAgent - Linux Server Operations Assistant
     Loaded: loaded (/etc/systemd/system/ops-agent.service; enabled)
     Active: active (running) since ...
   Main PID: 12345 (python)
     Memory: 30.0M
        CPU: 1.234s
```

### 2. 检查日志

```bash
sudo journalctl -u ops-agent --since "5 minutes ago"
```

预期看到：

```
[INFO] OpsAgent started
[INFO] Scheduler initialized
[INFO] Collector: collecting metrics...
[INFO] Memory: database connected
[INFO] All modules loaded successfully
```

### 3. 检查数据库

```bash
sqlite3 /opt/ops-agent/data/ops_agent.db "SELECT count(*) FROM metrics;"
```

### 4. 检查报表

```bash
ls -la /opt/ops-agent/reports/
```

### 5. 手动执行一次采集

```bash
cd /opt/ops-agent
source venv/bin/activate
python -c "
from ops_agent.collector import Collector
from ops_agent.config import Config
config = Config()
collector = Collector(config)
metrics = collector.collect_all()
print(f'采集到 {len(metrics)} 个指标')
for m in metrics[:5]:
    print(f'  {m.name} = {m.value} {m.unit}')
"
```

---

## 常见问题

### Q1: Python 版本过低

**错误：** `SyntaxError: invalid syntax` 或 `requires Python >= 3.10`

**解决：**

```bash
# CentOS 7 安装 Python 3.10
sudo yum install -y epel-release
sudo yum install -y python310 python310-pip

# Ubuntu 18.04 安装 Python 3.10
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3.10-dev
```

### Q2: 权限不足

**错误：** `PermissionError: [Errno 13] Permission denied`

**解决：**

```bash
sudo chown -R opsagent:opsagent /opt/ops-agent
# 检查 sudoers 配置
sudo visudo -c -f /etc/sudoers.d/opsagent
```

### Q3: 端口冲突

**说明：** OpsAgent 不监听任何网络端口，不存在端口冲突问题。

### Q4: 内存占用过高

**排查：**

```bash
# 查看进程内存
ps aux | grep ops-agent

# 减少采集频率
# 编辑 config.yaml，将 interval 从 30 改为 60
```

### Q5: 数据库锁定

**错误：** `sqlite3.OperationalError: database is locked`

**解决：**

```bash
# 检查是否有多个实例运行
ps aux | grep ops-agent

# 重启服务
sudo systemctl restart ops-agent
```

### Q6: 日志文件过大

**解决：**

```bash
# 配置 logrotate
sudo cat > /etc/logrotate.d/ops-agent << 'EOF'
/opt/ops-agent/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 opsagent opsagent
}
EOF
```

---

## 卸载

```bash
# 1. 停止并禁用服务
sudo systemctl stop ops-agent
sudo systemctl disable ops-agent

# 2. 删除服务文件
sudo rm /etc/systemd/system/ops-agent.service
sudo systemctl daemon-reload

# 3. 删除 sudoers 配置
sudo rm /etc/sudoers.d/opsagent

# 4. 删除项目文件
sudo rm -rf /opt/ops-agent

# 5. 删除用户
sudo userdel opsagent

echo "OpsAgent 已完全卸载"
```

---

*如遇本文档未覆盖的问题，请查看项目 Issue 或联系维护者。*
