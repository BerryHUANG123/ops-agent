# OpsAgent 模块接口说明（API Reference）

> 版本：V1.0 | 更新日期：2026-05-23

---

## 目录

- [公共数据结构](#公共数据结构)
- [1. Collector（采集器）](#1-collector采集器)
- [2. Detector（检测器）](#2-detector检测器)
- [3. Executor（执行器）](#3-executor执行器)
- [4. Memory（记忆模块）](#4-memory记忆模块)
- [5. Reporter（报表模块）](#5-reporter报表模块)
- [6. Scheduler（调度引擎）](#6-scheduler调度引擎)

---

## 公共数据结构

### MetricPoint

指标数据点，贯穿采集→检测→记录的完整链路。

```python
@dataclass
class MetricPoint:
    name: str           # 指标名称
    value: float        # 指标值
    unit: str           # 单位
    tags: dict          # 标签（如 mountpoint、interface）
    timestamp: float    # Unix 时间戳
```

**字段说明：**

| 字段 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `name` | `str` | ✅ | 指标标识符 | `"cpu_percent"`, `"disk_usage"` |
| `value` | `float` | ✅ | 指标值 | `85.3`, `1073741824` |
| `unit` | `str` | ✅ | 度量单位 | `"%"`, `"MB"`, `"count"` |
| `tags` | `dict` | ❌ | 附加标签 | `{"mountpoint": "/"}` |
| `timestamp` | `float` | ✅ | 采集时间戳 | `1716393600.0` |

---

### Alert

告警对象，由检测器生成。

```python
@dataclass
class Alert:
    rule_name: str      # 触发的规则名
    severity: str       # 告警级别
    metric_name: str    # 关联指标名
    metric_value: float # 指标当前值
    threshold: float    # 阈值
    message: str        # 告警描述
    action: str         # 建议执行的动作名
    timestamp: float    # 触发时间戳
```

**字段说明：**

| 字段 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `rule_name` | `str` | ✅ | 规则标识 | `"disk_critical"` |
| `severity` | `str` | ✅ | 告警级别 | `"info"`, `"warning"`, `"critical"` |
| `metric_name` | `str` | ✅ | 触发指标 | `"disk_usage"` |
| `metric_value` | `float` | ✅ | 当前值 | `95.2` |
| `threshold` | `float` | ✅ | 阈值 | `90.0` |
| `message` | `str` | ✅ | 人类可读描述 | `"磁盘 / 使用率 95.2% 超过阈值 90%"` |
| `action` | `str` | ❌ | 建议动作 | `"cleanup_logs"` |
| `timestamp` | `float` | ✅ | 触发时间 | `1716393600.0` |

---

### ActionResult

执行器动作结果。

```python
@dataclass
class ActionResult:
    action: str         # 动作名
    success: bool       # 是否成功
    message: str        # 结果描述
    output: str         # 命令输出
    duration: float     # 执行耗时（秒）
    timestamp: float    # 执行时间戳
    dry_run: bool       # 是否为 dry-run
```

**字段说明：**

| 字段 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `action` | `str` | ✅ | 动作标识 | `"cleanup_logs"` |
| `success` | `bool` | ✅ | 执行是否成功 | `True` |
| `message` | `str` | ✅ | 结果描述 | `"清理完成，释放 1.2GB"` |
| `output` | `str` | ❌ | 命令输出 | `"/var/log/syslog.1 已删除"` |
| `duration` | `float` | ✅ | 耗时（秒） | `2.35` |
| `timestamp` | `float` | ✅ | 执行时间 | `1716393600.0` |
| `dry_run` | `bool` | ✅ | 是否模拟执行 | `False` |

---

## 1. Collector（采集器）

**模块路径：** `ops_agent/collector.py`

### Collector

```python
class Collector:
    """系统指标采集器"""

    def __init__(self, config: Config) -> None
```

#### `collect_all()`

采集所有系统指标。

```python
def collect_all(self) -> list[MetricPoint]
```

| 参数 | 类型 | 说明 |
|------|------|------|
| 返回值 | `list[MetricPoint]` | 所有采集到的指标数据点列表 |

**示例：**

```python
collector = Collector(config)
metrics = collector.collect_all()
for m in metrics:
    print(f"{m.name} = {m.value} {m.unit}")
```

---

#### `collect_cpu()`

采集 CPU 相关指标。

```python
def collect_cpu(self) -> list[MetricPoint]
```

**返回指标：**

| 指标名 | 单位 | 说明 |
|--------|------|------|
| `cpu_percent` | `%` | 总体 CPU 使用率 |
| `cpu_percent_per_core` | `%` | 每核 CPU 使用率（tags: `{"core": N}`） |
| `load_avg_1m` | — | 1 分钟负载 |
| `load_avg_5m` | — | 5 分钟负载 |
| `load_avg_15m` | — | 15 分钟负载 |

---

#### `collect_memory()`

采集内存相关指标。

```python
def collect_memory(self) -> list[MetricPoint]
```

**返回指标：**

| 指标名 | 单位 | 说明 |
|--------|------|------|
| `memory_total` | `MB` | 物理内存总量 |
| `memory_available` | `MB` | 可用内存 |
| `memory_used` | `MB` | 已用内存 |
| `memory_percent` | `%` | 内存使用率 |
| `swap_total` | `MB` | Swap 总量 |
| `swap_used` | `MB` | Swap 已用 |
| `swap_percent` | `%` | Swap 使用率 |

---

#### `collect_disk()`

采集磁盘相关指标。

```python
def collect_disk(self) -> list[MetricPoint]
```

**返回指标：**

| 指标名 | 单位 | 标签 | 说明 |
|--------|------|------|------|
| `disk_total` | `GB` | `mountpoint` | 分区总容量 |
| `disk_used` | `GB` | `mountpoint` | 已用空间 |
| `disk_free` | `GB` | `mountpoint` | 可用空间 |
| `disk_percent` | `%` | `mountpoint` | 使用率 |
| `disk_read_bytes` | `B/s` | `device` | 磁盘读速率 |
| `disk_write_bytes` | `B/s` | `device` | 磁盘写速率 |

---

#### `collect_network()`

采集网络相关指标。

```python
def collect_network(self) -> list[MetricPoint]
```

**返回指标：**

| 指标名 | 单位 | 标签 | 说明 |
|--------|------|------|------|
| `net_bytes_sent` | `B/s` | `interface` | 发送速率 |
| `net_bytes_recv` | `B/s` | `interface` | 接收速率 |
| `net_connections_tcp` | `count` | — | TCP 连接数 |
| `net_connections_udp` | `count` | — | UDP 连接数 |

---

#### `collect_process()`

采集进程相关指标。

```python
def collect_process(self) -> list[MetricPoint]
```

**返回指标：**

| 指标名 | 单位 | 说明 |
|--------|------|------|
| `process_count` | `count` | 总进程数 |
| `process_top_cpu` | `%` | TOP N 进程 CPU 占用（tags: `{"pid", "name"}`） |
| `process_top_memory` | `%` | TOP N 进程内存占用（tags: `{"pid", "name"}`） |
| `process_zombie_count` | `count` | 僵尸进程数 |

---

## 2. Detector（检测器）

**模块路径：** `ops_agent/detector.py`

### Detector

```python
class Detector:
    """规则检测引擎"""

    def __init__(self, config: Config) -> None
```

#### `evaluate()`

评估指标列表，返回触发的告警。

```python
def evaluate(self, metrics: list[MetricPoint]) -> list[Alert]
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `metrics` | `list[MetricPoint]` | 待评估的指标数据 |
| 返回值 | `list[Alert]` | 触发的告警列表（空列表表示无异常） |

**示例：**

```python
detector = Detector(config)
alerts = detector.evaluate(metrics)
for alert in alerts:
    print(f"[{alert.severity}] {alert.message}")
```

---

#### `reload_rules()`

重新加载规则配置（热更新）。

```python
def reload_rules(self) -> None
```

---

#### `get_rule_status()`

获取所有规则的状态摘要。

```python
def get_rule_status(self) -> list[dict]
```

| 返回值字段 | 类型 | 说明 |
|-----------|------|------|
| `name` | `str` | 规则名称 |
| `enabled` | `bool` | 是否启用 |
| `last_triggered` | `float` | 最后触发时间 |
| `trigger_count` | `int` | 累计触发次数 |

---

### Rule（规则配置）

```python
@dataclass
class Rule:
    name: str               # 规则名称
    metric: str             # 关联指标名
    condition: str          # 条件表达式（如 "> 90"）
    severity: str           # 告警级别
    cooldown: int           # 冷却时间（秒）
    action: str             # 触发的动作名
    enabled: bool           # 是否启用
```

**config.yaml 中的规则示例：**

```yaml
detector:
  rules:
    - name: disk_critical
      metric: disk_percent
      condition: "> 90"
      severity: critical
      cooldown: 300
      action: cleanup_logs
      enabled: true

    - name: memory_warning
      metric: memory_percent
      condition: "> 80"
      severity: warning
      cooldown: 600
      action: send_alert
      enabled: true
```

---

## 3. Executor（执行器）

**模块路径：** `ops_agent/executor.py`

### Executor

```python
class Executor:
    """动作执行引擎"""

    def __init__(self, config: Config, dry_run: bool = True) -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config` | `Config` | — | 配置对象 |
| `dry_run` | `bool` | `True` | 是否为模拟模式（仅记录不执行） |

#### `execute()`

执行指定动作。

```python
def execute(self, action_name: str, params: dict = None) -> ActionResult
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action_name` | `str` | ✅ | 动作名称 |
| `params` | `dict` | ❌ | 动作参数 |
| 返回值 | `ActionResult` | — | 执行结果 |

**示例：**

```python
executor = Executor(config, dry_run=False)
result = executor.execute("cleanup_logs", {"max_age_days": 7})
print(f"{'成功' if result.success else '失败'}: {result.message}")
```

---

#### `list_actions()`

列出所有可用动作。

```python
def list_actions(self) -> list[str]
```

| 返回值 | 说明 |
|--------|------|
| `list[str]` | 动作名称列表 |

**内置动作列表：**

| 动作名 | 功能 | 参数 |
|--------|------|------|
| `cleanup_logs` | 清理过期日志 | `max_age_days: int` |
| `cleanup_tmp` | 清理临时文件 | `max_age_days: int` |
| `cleanup_docker` | Docker 垃圾清理 | — |
| `restart_service` | 重启服务 | `service_name: str` |
| `kill_process` | 终止进程 | `pid: int` 或 `name: str` |
| `send_alert` | 发送告警 | `message: str` |
| `custom_script` | 自定义脚本 | `script: str`, `args: list` |

---

#### `register_action()`

注册自定义动作。

```python
def register_action(self, name: str, func: Callable) -> None
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 动作名称 |
| `func` | `Callable` | 执行函数，签名为 `(params: dict) -> ActionResult` |

**示例：**

```python
def my_custom_action(params: dict) -> ActionResult:
    # 自定义逻辑
    return ActionResult(
        action="my_custom_action",
        success=True,
        message="自定义动作执行成功",
        output="",
        duration=0.1,
        timestamp=time.time(),
        dry_run=False
    )

executor.register_action("my_custom_action", my_custom_action)
```

---

## 4. Memory（记忆模块）

**模块路径：** `ops_agent/memory.py`

### Memory

```python
class Memory:
    """数据持久化模块"""

    def __init__(self, db_path: str = "ops_agent.db") -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `db_path` | `str` | `"ops_agent.db"` | SQLite 数据库文件路径 |

#### `save_metrics()`

批量保存指标数据。

```python
def save_metrics(self, metrics: list[MetricPoint]) -> None
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `metrics` | `list[MetricPoint]` | 指标数据点列表 |

**注意：** 使用事务批量插入，tags 字段序列化为 JSON 字符串存储。

---

#### `save_alert()`

保存告警记录。

```python
def save_alert(self, alert: Alert) -> int
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `alert` | `Alert` | 告警对象 |
| 返回值 | `int` | 插入记录的 ID |

---

#### `save_action()`

保存动作执行记录。

```python
def save_action(self, result: ActionResult) -> int
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `result` | `ActionResult` | 执行结果 |
| 返回值 | `int` | 插入记录的 ID |

---

#### `get_alerts()`

查询告警记录。

```python
def get_alerts(self, since: float = None, severity: str = None) -> list[dict]
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `since` | `float` | ❌ | 起始时间戳（不传则查全部） |
| `severity` | `str` | ❌ | 过滤告警级别 |
| 返回值 | `list[dict]` | — | 告警记录列表 |

**返回字典字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `int` | 记录 ID |
| `rule_name` | `str` | 规则名 |
| `severity` | `str` | 告警级别 |
| `metric_name` | `str` | 指标名 |
| `metric_value` | `float` | 指标值 |
| `threshold` | `float` | 阈值 |
| `message` | `str` | 告警描述 |
| `action_taken` | `str` | 执行的动作 |
| `action_success` | `bool` | 动作是否成功 |
| `created_at` | `str` | 创建时间 |

---

#### `get_metrics()`

查询指标历史。

```python
def get_metrics(self, name: str, since: float = None) -> list[dict]
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | `str` | ✅ | 指标名称 |
| `since` | `float` | ❌ | 起始时间戳 |
| 返回值 | `list[dict]` | — | 指标记录列表 |

---

#### `get_actions()`

查询动作执行记录。

```python
def get_actions(self, since: float = None) -> list[dict]
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `since` | `float` | ❌ | 起始时间戳 |
| 返回值 | `list[dict]` | — | 动作记录列表 |

---

#### `cleanup()`

清理过期数据。

```python
def cleanup(self, days: int = 30) -> int
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `days` | `int` | `30` | 保留天数 |
| 返回值 | `int` | — | 清理的记录总数 |

---

#### `get_stats()`

获取数据库统计信息。

```python
def get_stats(self) -> dict
```

| 返回值字段 | 类型 | 说明 |
|-----------|------|------|
| `metrics_count` | `int` | 指标记录总数 |
| `alerts_count` | `int` | 告警记录总数 |
| `actions_count` | `int` | 动作记录总数 |
| `db_size_mb` | `float` | 数据库文件大小（MB） |
| `oldest_record` | `str` | 最早记录时间 |
| `newest_record` | `str` | 最新记录时间 |

---

## 5. Reporter（报表模块）

**模块路径：** `ops_agent/reporter.py`

### Reporter

```python
class Reporter:
    """报表生成模块"""

    def __init__(self, memory: Memory, template_dir: str = "templates") -> None
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `memory` | `Memory` | — | Memory 模块实例 |
| `template_dir` | `str` | `"templates"` | 模板目录路径 |

#### `generate_daily_report()`

生成每日汇总报告。

```python
def generate_daily_report(self, date: str = None) -> str
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `date` | `str` | ❌ | 日期（格式 `YYYY-MM-DD`），默认昨天 |
| 返回值 | `str` | — | 报告文件路径 |

**报告内容：**
- 告警统计（按级别分组）
- 指标趋势图（CPU/内存/磁盘）
- 动作执行记录汇总
- 系统运行时长

**示例：**

```python
reporter = Reporter(memory)
path = reporter.generate_daily_report("2026-05-23")
print(f"报告已生成: {path}")
# 输出: 报告已生成: reports/report_2026-05-23.html
```

---

#### `generate_snapshot()`

生成实时系统快照报告。

```python
def generate_snapshot(self) -> str
```

| 返回值 | 说明 |
|--------|------|
| `str` | 报告文件路径 |

**报告内容：**
- 当前系统状态概览
- 实时指标值
- 最近 24 小时告警
- 活跃进程 TOP 10

---

#### `get_latest_report()`

获取最新报告文件路径。

```python
def get_latest_report(self) -> str
```

| 返回值 | 说明 |
|--------|------|
| `str` | 最新报告文件路径，无报告时返回 `None` |

---

## 6. Scheduler（调度引擎）

**模块路径：** `ops_agent/scheduler.py`

### Scheduler

```python
class Scheduler:
    """任务调度引擎"""

    def __init__(self, config: Config) -> None
```

#### `start()`

启动调度器，注册所有定时任务。

```python
def start(self) -> None
```

**注册的定时任务：**

| 任务 | 间隔 | 函数 |
|------|------|------|
| 指标采集+检测 | 30s | `_collect_and_detect()` |
| 日报生成 | 每天 00:00 | `_generate_daily_report()` |
| 数据清理 | 每天 03:00 | `_cleanup_data()` |
| 健康自检 | 300s | `_health_check()` |

**示例：**

```python
scheduler = Scheduler(config)
try:
    scheduler.start()  # 阻塞运行
except KeyboardInterrupt:
    scheduler.stop()
```

---

#### `stop()`

优雅停止调度器。

```python
def stop(self) -> None
```

**行为：**
1. 停止接受新任务
2. 等待当前任务完成（最多 10 秒）
3. 关闭数据库连接
4. 写入停止日志

---

#### `reload()`

重新加载配置（热更新）。

```python
def reload(self) -> None
```

**行为：**
1. 重新读取 config.yaml
2. 更新检测规则
3. 更新采集间隔
4. 不重启调度器

---

#### `run_once()`

手动执行一次完整的采集-检测-处置流程。

```python
def run_once(self) -> dict
```

| 返回值字段 | 类型 | 说明 |
|-----------|------|------|
| `metrics_count` | `int` | 采集指标数 |
| `alerts_count` | `int` | 触发告警数 |
| `actions_count` | `int` | 执行动作数 |
| `duration` | `float` | 总耗时（秒） |

**示例：**

```python
scheduler = Scheduler(config)
result = scheduler.run_once()
print(f"采集 {result['metrics_count']} 指标, "
      f"{result['alerts_count']} 告警, "
      f"耗时 {result['duration']:.2f}s")
```

---

#### `get_status()`

获取调度器状态。

```python
def get_status(self) -> dict
```

| 返回值字段 | 类型 | 说明 |
|-----------|------|------|
| `running` | `bool` | 是否运行中 |
| `uptime` | `float` | 运行时长（秒） |
| `last_collect` | `float` | 最后采集时间 |
| `last_cleanup` | `float` | 最后清理时间 |
| `total_cycles` | `int` | 累计采集周期数 |
| `total_alerts` | `int` | 累计告警数 |
| `config_path` | `str` | 配置文件路径 |
| `db_path` | `str` | 数据库路径 |

---

*本文档与代码保持同步，如有变更请同步更新。*
