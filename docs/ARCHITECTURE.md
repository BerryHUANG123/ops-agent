# OpsAgent 架构设计文档

> 版本：V1.0 | 更新日期：2026-05-23 | 状态：已批准

---

## 一、整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        OpsAgent 进程                             │
│                   systemd 守护 + 自动重启                         │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    调度引擎 (Scheduler)                     │  │
│  │              APScheduler 周期任务 + 信号处理                 │  │
│  └────────┬──────────┬──────────┬──────────┬─────────────────┘  │
│           │          │          │          │                     │
│  ┌────────▼───┐ ┌────▼─────┐ ┌─▼────────┐ ┌──────────────┐     │
│  │  采集器     │ │  检测器   │ │  执行器   │ │   记忆模块    │     │
│  │ Collector  │ │ Detector │ │ Executor │ │   Memory     │     │
│  │            │ │          │ │          │ │              │     │
│  │ • CPU      │ │ • 阈值   │ │ • 清理   │ │ • SQLite     │     │
│  │ • 内存     │ │ • 趋势   │ │ • 重启   │ │ • 事件表     │     │
│  │ • 磁盘     │ │ • 异常   │ │ • 脚本   │ │ • 指标表     │     │
│  │ • 网络     │ │ • 规则   │ │ • dry-run│ │ • 清理       │     │
│  │ • 进程     │ │          │ │          │ │              │     │
│  └────────────┘ └──────────┘ └──────────┘ └──────────────┘     │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    报表模块 (Reporter)                      │  │
│  │              Jinja2 模板渲染 → HTML 报告文件                 │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    配置管理 (config.py)                     │  │
│  │              YAML 加载 + 环境变量 + 校验 + 热更新            │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │                    │                    │
    ┌────▼────┐          ┌───▼───┐          ┌────▼────┐
    │  /proc  │          │SQLite │          │  HTML   │
    │  /sys   │          │ .db   │          │ 报告文件 │
    │ psutil  │          │       │          │         │
    └─────────┘          └───────┘          └─────────┘
```

---

## 二、六大核心模块

### 2.1 采集器（Collector）

**职责：** 定期采集系统指标，输出标准化数据结构。

| 采集项 | 数据源 | 采集频率 | 说明 |
|--------|--------|----------|------|
| CPU 使用率 | `psutil.cpu_percent()` | 30s | 支持多核细分 |
| 内存使用 | `psutil.virtual_memory()` | 30s | 总量/可用/使用率/Swap |
| 磁盘使用 | `psutil.disk_usage()` | 60s | 按挂载点分别采集 |
| 磁盘 I/O | `psutil.disk_io_counters()` | 30s | 读写速率、IOPS |
| 网络流量 | `psutil.net_io_counters()` | 30s | 按网卡分别采集 |
| 网络连接 | `psutil.net_connections()` | 60s | TCP/UDP 连接数 |
| 进程列表 | `psutil.process_iter()` | 30s | TOP N 进程（按 CPU/内存排序） |
| 系统负载 | `os.getloadavg()` | 30s | 1/5/15 分钟负载 |
| 系统启动时间 | `psutil.boot_time()` | 300s | 用于计算运行时长 |

**输出格式：**

```python
@dataclass
class MetricPoint:
    name: str           # 指标名称，如 "cpu_percent"
    value: float        # 指标值
    unit: str           # 单位，如 "%", "MB", "count"
    tags: dict          # 标签，如 {"mountpoint": "/"}
    timestamp: float    # Unix 时间戳
```

### 2.2 检测器（Detector）

**职责：** 根据规则评估指标数据，判定是否触发告警。

**规则模型：**

```python
@dataclass
class Rule:
    name: str               # 规则名称
    metric: str             # 关联指标名
    condition: str          # 条件表达式，如 "> 90"
    severity: str           # 严重级别: info / warning / critical
    cooldown: int           # 冷却时间（秒），避免重复告警
    action: str             # 触发的执行器动作名
    enabled: bool           # 是否启用
```

**检测流程：**

```
指标数据 → 加载规则集 → 逐条评估 → 超限？ → 冷却期检查 → 触发告警/动作
                              │
                              └─ 正常 → 记录状态
```

**告警级别：**

| 级别 | 颜色 | 含义 | 示例 |
|------|------|------|------|
| `info` | 🔵 蓝 | 信息记录 | 系统重启、服务状态变更 |
| `warning` | 🟡 黄 | 需关注 | CPU > 80%、磁盘 > 70% |
| `critical` | 🔴 红 | 需立即处理 | 磁盘 > 95%、内存 > 95%、服务宕机 |

### 2.3 执行器（Executor）

**职责：** 接收检测器触发的动作指令，执行预定义的修复操作。

**内置动作：**

| 动作名 | 功能 | 风险等级 | 需要 root |
|--------|------|----------|-----------|
| `cleanup_logs` | 清理过期日志文件 | 🟡 中 | 是 |
| `cleanup_tmp` | 清理 /tmp 临时文件 | 🟢 低 | 是 |
| `cleanup_docker` | Docker prune 清理 | 🟡 中 | 是 |
| `restart_service` | 重启指定 systemd 服务 | 🔴 高 | 是 |
| `kill_process` | 终止指定进程 | 🔴 高 | 是 |
| `send_alert` | 发送告警通知 | 🟢 低 | 否 |
| `custom_script` | 执行用户自定义脚本 | 🔴 高 | 视脚本而定 |

**执行模型：**

```python
@dataclass
class ActionResult:
    action: str             # 动作名
    success: bool           # 是否成功
    message: str            # 执行结果描述
    output: str             # 命令输出
    duration: float         # 执行耗时（秒）
    timestamp: float        # 执行时间
    dry_run: bool           # 是否为 dry-run 模式
```

**安全机制：**
- 默认 `dry_run=True`，仅记录不执行
- 所有动作记录审计日志
- 超时保护（默认 30 秒）
- 动作白名单控制

### 2.4 记忆模块（Memory）

**职责：** 持久化存储事件、指标、动作记录，支持查询和统计。

**数据库表结构：**

```sql
-- 告警事件表
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    threshold REAL NOT NULL,
    message TEXT,
    action_taken TEXT,
    action_success BOOLEAN,
    acknowledged BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 指标数据表
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    tags TEXT,  -- JSON 格式
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 动作执行记录表
CREATE TABLE actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    message TEXT,
    output TEXT,
    duration REAL,
    dry_run BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**数据管理策略：**
- 默认保留 30 天历史数据
- 每日自动清理过期数据
- 支持手动调整保留天数
- SQLite WAL 模式提升并发读性能

### 2.5 报表模块（Reporter）

**职责：** 从记忆模块读取数据，生成可读的 HTML 报告。

**报表类型：**

| 报表 | 频率 | 内容 |
|------|------|------|
| 每日汇总 | 每天 00:00 | 当日告警统计、指标趋势、动作记录 |
| 实时快照 | 按需 | 当前系统状态一览 |
| 周报 | 每周一 | 7 天趋势分析、TOP 问题、改进建议 |

**模板结构：**

```
templates/
├── daily_report.html    # 每日汇总模板
├── weekly_report.html   # 周报模板
├── snapshot.html        # 实时快照模板
└── components/
    ├── header.html      # 页头组件
    ├── metric_chart.html # 指标图表组件
    └── alert_table.html  # 告警表格组件
```

**输出目录：** `reports/` 目录，文件名格式 `report_YYYY-MM-DD.html`

### 2.6 调度引擎（Scheduler）

**职责：** 统一管理所有模块的执行周期，处理信号和生命周期。

**调度策略：**

| 任务 | 间隔 | 说明 |
|------|------|------|
| 指标采集 | 30s | 核心循环 |
| 规则检测 | 30s | 采集后立即检测 |
| 日报生成 | 每天 00:00 | 汇总前一日数据 |
| 数据清理 | 每天 03:00 | 清理过期数据 |
| 健康自检 | 300s | 检查自身运行状态 |

**信号处理：**

| 信号 | 行为 |
|------|------|
| `SIGTERM` | 优雅关闭：完成当前任务 → 保存状态 → 退出 |
| `SIGHUP` | 热重载：重新加载配置文件 |
| `SIGUSR1` | 立即生成快照报告 |

---

## 三、数据流

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  采集     │    │  检测     │    │  处置     │    │  记录     │    │  报表     │
│ Collector │───▶│ Detector │───▶│ Executor │───▶│ Memory   │───▶│ Reporter │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │                │               │               │               │
     ▼                ▼               ▼               ▼               ▼
  系统指标         告警判定        修复执行        持久化存储       HTML 报告
  (MetricPoint)   (Alert)        (ActionResult)  (SQLite)        (report.html)
```

**详细数据流：**

1. **采集阶段**
   - Scheduler 每 30 秒触发 Collector
   - Collector 调用 psutil 读取 /proc、/sys
   - 输出 `List[MetricPoint]`

2. **检测阶段**
   - Detector 接收 MetricPoint 列表
   - 逐条匹配 Rules（从 config.yaml 加载）
   - 超限规则生成 Alert 对象
   - 冷却期检查：同规则 N 秒内不重复触发

3. **处置阶段**
   - Executor 接收 Alert
   - 查找对应 Action（规则中定义）
   - 执行修复脚本（或 dry-run 记录）
   - 输出 ActionResult

4. **记录阶段**
   - Memory 模块写入 SQLite：
     - 指标 → metrics 表
     - 告警 → alerts 表
     - 动作 → actions 表
   - 自动清理过期数据

5. **报表阶段**
   - Reporter 从 SQLite 查询当日数据
   - Jinja2 渲染 HTML 模板
   - 输出到 reports/ 目录

---

## 四、模块间接口

### 4.1 Collector 接口

```python
class Collector:
    def collect_all(self) -> list[MetricPoint]:
        """采集所有指标，返回 MetricPoint 列表"""

    def collect_cpu(self) -> list[MetricPoint]:
        """采集 CPU 相关指标"""

    def collect_memory(self) -> list[MetricPoint]:
        """采集内存相关指标"""

    def collect_disk(self) -> list[MetricPoint]:
        """采集磁盘相关指标"""

    def collect_network(self) -> list[MetricPoint]:
        """采集网络相关指标"""

    def collect_process(self) -> list[MetricPoint]:
        """采集进程相关指标"""
```

### 4.2 Detector 接口

```python
class Detector:
    def __init__(self, config: Config):
        """初始化检测器，加载规则集"""

    def evaluate(self, metrics: list[MetricPoint]) -> list[Alert]:
        """评估指标列表，返回触发的告警列表"""

    def reload_rules(self) -> None:
        """重新加载规则配置"""

    def get_rule_status(self) -> list[dict]:
        """获取所有规则的状态摘要"""
```

### 4.3 Executor 接口

```python
class Executor:
    def __init__(self, config: Config, dry_run: bool = True):
        """初始化执行器，dry_run 模式下仅记录不执行"""

    def execute(self, action_name: str, params: dict = None) -> ActionResult:
        """执行指定动作，返回执行结果"""

    def list_actions(self) -> list[str]:
        """列出所有可用动作"""

    def register_action(self, name: str, func: callable) -> None:
        """注册自定义动作"""
```

### 4.4 Memory 接口

```python
class Memory:
    def __init__(self, db_path: str = "ops_agent.db"):
        """初始化数据库连接"""

    def save_metrics(self, metrics: list[MetricPoint]) -> None:
        """批量保存指标数据"""

    def save_alert(self, alert: Alert) -> int:
        """保存告警记录，返回记录 ID"""

    def save_action(self, result: ActionResult) -> int:
        """保存动作执行记录，返回记录 ID"""

    def get_alerts(self, since: float = None, severity: str = None) -> list[dict]:
        """查询告警记录"""

    def get_metrics(self, name: str, since: float = None) -> list[dict]:
        """查询指标历史"""

    def get_actions(self, since: float = None) -> list[dict]:
        """查询动作记录"""

    def cleanup(self, days: int = 30) -> int:
        """清理过期数据，返回清理记录数"""

    def get_stats(self) -> dict:
        """获取数据库统计信息"""
```

### 4.5 Reporter 接口

```python
class Reporter:
    def __init__(self, memory: Memory, template_dir: str = "templates"):
        """初始化报表模块"""

    def generate_daily_report(self, date: str = None) -> str:
        """生成每日汇总报告，返回报告文件路径"""

    def generate_snapshot(self) -> str:
        """生成实时快照报告，返回报告文件路径"""

    def get_latest_report(self) -> str:
        """获取最新报告文件路径"""
```

### 4.6 Scheduler 接口

```python
class Scheduler:
    def __init__(self, config: Config):
        """初始化调度引擎"""

    def start(self) -> None:
        """启动调度器，注册所有定时任务"""

    def stop(self) -> None:
        """优雅停止调度器"""

    def reload(self) -> None:
        """重新加载配置"""

    def run_once(self) -> None:
        """手动执行一次完整采集-检测-处置流程"""

    def get_status(self) -> dict:
        """获取调度器状态"""
```

---

## 五、技术选型

| 组件 | 选型 | 版本要求 | 选型理由 |
|------|------|----------|----------|
| **语言** | Python | ≥ 3.10 | 生态成熟、运维工具链丰富、开发效率高 |
| **系统采集** | psutil | ≥ 5.9 | 跨平台、API 完善、性能优秀 |
| **数据存储** | SQLite | 内置 | 零配置、单文件、适合嵌入式场景 |
| **模板引擎** | Jinja2 | ≥ 3.1 | 模板语法强大、性能好、安全 |
| **任务调度** | APScheduler | ≥ 3.10 | 轻量、灵活、支持 cron/interval/date |
| **进程管理** | systemd | — | Linux 标准、自动重启、日志集成 |
| **配置格式** | YAML | — | 可读性好、支持注释、Python 生态支持完善 |
| **日志** | logging | 内置 | 标准库、可配置级别和输出 |

**不引入的依赖：**
- ❌ 数据库服务器（MySQL/PostgreSQL）— SQLite 够用
- ❌ 消息队列（Redis/RabbitMQ）— 单进程无需
- ❌ Web 框架（Flask/FastAPI）— V1.0 无 Web UI
- ❌ ORM（SQLAlchemy）— 轻量场景直接 SQL

---

## 六、运行环境规范

### 6.1 硬件要求

| 资源 | 最低要求 | 推荐配置 |
|------|----------|----------|
| CPU | x86_64 / ARM64 | 任意 |
| 内存 | 512MB | 1GB+ |
| 磁盘 | 100MB（程序+数据库） | 1GB+（含历史数据） |
| 网络 | 无特殊要求 | 可选：用于告警推送 |

### 6.2 软件要求

| 组件 | 要求 |
|------|------|
| 操作系统 | Linux（CentOS 7+/Ubuntu 18.04+/Debian 10+） |
| Python | ≥ 3.10 |
| systemd | 任意版本 |
| 磁盘文件系统 | ext4 / xfs / btrfs |

### 6.3 权限要求

| 操作 | 权限 | 说明 |
|------|------|------|
| 指标采集 | 普通用户 | psutil 读取 /proc |
| 服务管理 | root / sudo | systemd 操作 |
| 日志清理 | root / sudo | 删除系统日志文件 |
| 进程管理 | root / sudo | kill 进程 |
| 数据库读写 | 普通用户 | SQLite 文件权限 |

**推荐：** 以专用用户 `opsagent` 运行，通过 sudoers 授权特定命令。

---

*本文档为 OpsAgent 架构设计依据，如有变更需更新版本号并通知相关干系人。*
