# OpsAgent 版本记录

> 所有版本变更记录。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [1.0.0] - 2026-05-23

### 🎉 首次发布

OpsAgent V1.0 正式发布 — 轻量级 Linux 服务器无人值守运维监控智能 Agent。

### ✨ 新增功能

#### 数据采集模块（Collectors）
- CPU 使用率、内存、磁盘、系统负载、网络流量、Uptime 采集
- 指定服务进程状态检测（sshd、nginx、docker 等）
- 系统日志增量读取，错误模式匹配（支持多日志文件）
- 基于 psutil 的低资源占用采集

#### 异常判别模块（Detectors）
- CPU/内存/磁盘/负载智能阈值检测（WARNING + CRITICAL 两级）
- 服务宕机检测
- 日志错误聚合去重
- 可配置阈值参数

#### 故障分析模块（Analyzers）
- 基于规则的根因推断（OOM、磁盘满、配置错误等）
- 多 Issue 关联分析（内存+服务宕机→OOM Killer 等）
- 故障分类：资源类、服务类、日志类、网络类
- 趋势分析（基于历史数据）
- 自动生成处置建议

#### 自动处置模块（Remediators）
- 白名单安全机制，只执行允许的操作
- 服务重启（systemctl restart）
- 过大日志清理（rotate 而非删除）
- 僵尸进程终止
- dry_run 模式支持
- 完整操作审计

#### 巡检报表模块（Reporters）
- HTML 可视化巡检报告
- 系统概览卡片（CPU/内存/磁盘/负载）
- CSS 柱状图展示指标趋势
- 告警列表、处置记录、风险建议
- Jinja2 模板引擎

#### 记忆复盘模块（Memory）
- SQLite 持久化事件存储
- 历史事件查询（按类型、关键词）
- 统计分析（总事件、解决率、常见故障类型）
- 自动数据清理（防止无限膨胀）

#### 主控引擎
- 统一主循环：采集 → 检测 → 分析 → 处置 → 记录
- 信号处理（SIGTERM/SIGINT 优雅退出）
- CLI 参数支持（--config, --dry-run, --once）
- 单次检查失败不影响主循环
- 控制台 + 文件双日志

### 📝 文档
- 项目立项文档（PROJECT_CHARTER.md）
- 架构设计文档（ARCHITECTURE.md）
- 模块接口说明（API.md）
- 部署指南（DEPLOYMENT.md）
- 版本记录（CHANGELOG.md）

### 🧪 测试
- 42 个单元测试，覆盖全部核心模块
- 采集器、检测器、分析器、处置器、记忆模块独立测试
- 集成冒烟测试通过（实际 J1900 服务器验证）

### ⚙️ 技术栈
- Python 3.10+
- psutil 5.9+（系统采集）
- SQLite（数据存储，Python 内置）
- Jinja2 3.1+（模板渲染）
- PyYAML 6.0+（配置管理）
- systemd（服务管理）

---

## [2.1.0] - 2026-05-23

### ✨ 新增功能
- **飞书告警推送**：异常检测后通过飞书 Webhook 实时推送告警卡片
  - 支持 CRITICAL/WARNING/INFO 三级颜色区分
  - 处置完成后自动推送处置结果
  - 每日巡检摘要推送
  - 告警合并机制（短时间多告警合并为一条）
  - 通过 YAML 配置开关和 Webhook URL

### ⚙️ 技术
- 新增 `src/notifiers/feishu_notifier.py`
- 新增 `tests/test_notifiers.py`（12 个测试用例）

---

## [2.3.0] - 2026-05-23

### ✨ 新增功能
- **Docker 容器监控**：容器级别状态与资源采集
  - 容器列表采集（运行/停止/暂停/重启）
  - 资源占用采集（CPU/内存/网络/磁盘 I/O）
  - 容器日志采集（支持指定行数）
  - 容器异常检测（状态异常/资源过载/频繁重启/健康检查失败）
  - 无 Docker SDK 依赖，纯 CLI 调用
  - Docker 不可用时自动跳过，不影响其他监控

### ⚙️ 技术
- 新增 `src/collectors/docker_collector.py`
- 新增 `tests/test_docker_collector.py`（8 个测试用例）
- 改造 `src/main.py` 和 `src/detectors/anomaly_detector.py`

---

## [2.5.0] - 2026-05-23

### ✨ 新增功能
- **定时报表生成**：自动按时间生成巡检报告
  - 每日定时模式（指定 HH:MM）
  - 间隔触发模式（自定义分钟数）
  - 后台线程调度，不阻塞主循环
  - 生成后自动推送飞书摘要（需启用 notifier）
  - 优雅启停，支持信号处理

### ⚙️ 技术
- 新增 `src/scheduler/report_scheduler.py`
- 新增 `tests/test_scheduler.py`（7 个测试用例）

---

## [2.6.0] - 2026-05-23

### ✨ 新增功能
- **LLM 智能分析**：接入大模型进行深度告警分析
  - OpenAI 兼容 API，支持多种模型
  - 告警根因推断 + 处置建议
  - 日志片段智能分析
  - 分析结果自动附加到飞书告警卡片
  - JSON 结构化输出，容错解析
  - 无 API key 时自动跳过

### ⚙️ 技术
- 新增 `src/analyzers/llm_analyzer.py`
- 新增 `tests/test_llm_analyzer.py`（10 个测试用例）

---

## [2.4.0] - 2026-05-23

### ✨ 新增功能
- **systemd journal 日志分析**：结构化日志深度采集
  - 支持按 unit 过滤（sshd、nginx 等）
  - 支持按优先级过滤（emerg → debug 8 级）
  - 增量采集（按时间范围）
  - Unit 日志摘要（各级别数量统计）
  - JSON 格式解析，提取时间戳/PID/unit
  - journalctl 不可用时自动跳过

### ⚙️ 技术
- 新增 `src/collectors/journal_collector.py`
- 新增 `tests/test_journal_collector.py`（8 个测试用例）

---

## [2.2.0] - 2026-05-23

### ✨ 新增功能
- **自适应阈值**：基于历史数据动态调整告警阈值
  - 滑动窗口统计（均值、标准差、P95/P99）
  - 动态阈值 = mean + k × std（warning 2σ, critical 3σ）
  - floor/ceiling 约束防止阈值漂移
  - 样本不足时自动回退静态阈值
  - 统计缓存机制，降低计算开销

### ⚙️ 技术
- 新增 `src/detectors/adaptive_threshold.py`
- 新增 `tests/test_adaptive_threshold.py`（10 个测试用例）
- 改造 `src/detectors/anomaly_detector.py` 集成自适应阈值

---

## [未发布] - 路线图

### 计划功能（V2.0）

- [ ] AI 辅助分析：接入 LLM 进行日志分析和根因推断
- [ ] 自适应阈值：基于历史数据动态调整告警阈值
- [ ] Web UI：浏览器端管理界面
- [ ] 多机协同：Agent 间通信、集中式 Dashboard
- [ ] 插件系统：用户自定义检测器和处置器
- [ ] 告警通知集成：飞书 Webhook
- [ ] Docker 容器深度监控
- [ ] systemd journal 日志分析
- [ ] 定时报表生成（cron 调度）

---

*版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/) 规范。*
