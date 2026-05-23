"""OpsAgent 主入口 — 轻量级无人值守运维监控智能 Agent"""
import logging
import os
import signal
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml

from src.models import IncidentRecord, LogEntry, Severity, SystemMetrics
from src.collectors.system_collector import SystemCollector
from src.collectors.log_collector import LogCollector
from src.collectors.docker_collector import DockerCollector
from src.collectors.journal_collector import JournalCollector
from src.detectors.anomaly_detector import AnomalyDetector
from src.analyzers.fault_analyzer import FaultAnalyzer
from src.analyzers.llm_analyzer import LLMAnalyzer
from src.remediators.auto_remediator import AutoRemediator
from src.reporters.report_generator import ReportGenerator
from src.memory.incident_memory import IncidentMemory
from src.notifiers.feishu_notifier import FeishuNotifier
from src.scheduler.report_scheduler import ReportScheduler

# 默认配置路径
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "default.yaml"

logger = logging.getLogger("ops_agent")


class OpsAgent:
    """运维监控 Agent 主类

    职责：
    1. 初始化所有子模块
    2. 主循环：采集 → 检测 → 分析 → 处置 → 记录
    3. 定时生成报表
    4. 优雅退出
    """

    def __init__(self, config_path: Optional[str] = None, dry_run: bool = False) -> None:
        """初始化 Agent

        Args:
            config_path: 配置文件路径，为 None 则使用默认配置
            dry_run: 是否为演练模式（不实际执行处置）
        """
        # 加载配置
        self.config = self._load_config(config_path or str(DEFAULT_CONFIG_PATH))

        # 初始化日志
        self._setup_logging()

        logger.info("=" * 50)
        logger.info("OpsAgent 启动中...")
        logger.info("服务器: %s", self.config.get("server", {}).get("name", "unknown"))
        logger.info("检查间隔: %ds", self.config.get("server", {}).get("check_interval", 60))
        logger.info("Dry Run: %s", dry_run)
        logger.info("=" * 50)

        # 初始化各模块
        self.system_collector = SystemCollector()
        self.log_collector = LogCollector()
        self.docker_collector = DockerCollector()
        self.journal_collector = JournalCollector()
        self.anomaly_detector = AnomalyDetector()
        self.fault_analyzer = FaultAnalyzer()
        self.auto_remediator = AutoRemediator(dry_run=dry_run)
        self.report_generator = ReportGenerator()

        # 初始化记忆存储
        db_path = self.config.get("memory", {}).get("db_path", "data/ops_agent.db")
        self.memory = IncidentMemory(db_path)

        # 初始化 LLM 智能分析器
        self.llm_analyzer: Optional[LLMAnalyzer] = None
        llm_cfg = self.config.get("llm", {})
        if llm_cfg.get("enabled", False):
            self.llm_analyzer = LLMAnalyzer(
                api_key=llm_cfg.get("api_key") or None,
                base_url=llm_cfg.get("base_url", "https://api.openai.com/v1"),
                model=llm_cfg.get("model", "gpt-4o-mini"),
                timeout=llm_cfg.get("timeout", 30),
                max_tokens=llm_cfg.get("max_tokens", 1000),
            )
            if self.llm_analyzer.is_available():
                logger.info("LLM 智能分析已启用 (模型=%s)", llm_cfg.get("model", "gpt-4o-mini"))
            else:
                logger.warning("LLM 已启用但 API key 为空，智能分析不可用")
        else:
            logger.info("LLM 智能分析已禁用")

        # 初始化飞书通知器
        self.notifier: Optional[FeishuNotifier] = None
        notifier_cfg = self.config.get("notifier", {})
        if notifier_cfg.get("enabled", False):
            feishu_cfg = notifier_cfg.get("feishu", {})
            webhook_url = feishu_cfg.get("webhook_url", "")
            if webhook_url:
                self.notifier = FeishuNotifier(
                    webhook_url=webhook_url,
                    secret=feishu_cfg.get("secret") or None,
                )
                logger.info("飞书告警推送已启用")
            else:
                logger.warning("notifier.enabled=true 但 webhook_url 为空，飞书推送未启用")
        else:
            logger.info("飞书告警推送已禁用")

        # 初始化定时报表调度器
        report_cfg = self.config.get("report", {})
        schedule_str = report_cfg.get("schedule", "") or None
        interval_min = report_cfg.get("interval_minutes", 1440)
        self.scheduler = ReportScheduler(
            interval_minutes=interval_min,
            daily_at=schedule_str,
            on_report=self._generate_report,
        )
        logger.info(
            "定时报表调度器已配置 (模式=%s, 间隔=%d分钟)",
            "每日定时 " + schedule_str if schedule_str else "间隔触发",
            interval_min,
        )

        # 状态
        self._running = False
        self._metrics_history: List[SystemMetrics] = []
        self._last_report_time: float = 0
        self._check_count: int = 0

        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("OpsAgent 初始化完成")

    @staticmethod
    def _load_config(config_path: str) -> dict:
        """加载 YAML 配置文件

        Args:
            config_path: 配置文件路径

        Returns:
            dict: 配置字典
        """
        path = Path(config_path)
        if not path.exists():
            logger.warning("配置文件不存在: %s，使用空配置", config_path)
            return {}

        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        logger.info("配置已加载: %s", config_path)
        return config

    def _setup_logging(self) -> None:
        """配置日志：文件 + 控制台"""
        log_dir = Path(__file__).parent.parent / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "ops_agent.log"

        # 根日志器配置
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        # 格式
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 文件 handler
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # 控制台 handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    def _signal_handler(self, signum: int, frame: object) -> None:
        """信号处理：优雅退出

        Args:
            signum: 信号编号
            frame: 栈帧
        """
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("收到退出信号 %s，准备优雅退出...", sig_name)
        self._running = False

    def run(self) -> None:
        """启动主循环"""
        self._running = True
        check_interval = self.config.get("server", {}).get("check_interval", 60)

        logger.info("主循环启动，检查间隔: %ds", check_interval)

        # 启动定时报表调度器
        self.scheduler.start()

        while self._running:
            try:
                self._run_check_cycle()
                self._check_count += 1

                # 检查是否需要生成报告（每 10 个周期或每天至少一次）
                self._maybe_generate_report()

            except Exception as e:
                # 单次检查失败不影响主循环
                logger.error("检查周期异常，继续运行: %s", e)
                logger.debug("异常详情:\n%s", traceback.format_exc())

            # 等待下一个周期
            self._interruptible_sleep(check_interval)

        # 停止定时报表调度器
        self.scheduler.stop()

        # 退出清理
        self._cleanup()

    def _run_check_cycle(self) -> None:
        """执行一次完整的检查周期：采集 → 检测 → 分析 → 处置 → 记录"""
        logger.info("----- 检查周期 #%d 开始 -----", self._check_count + 1)
        start_time = time.time()

        # 1. 采集
        try:
            metrics = self.system_collector.collect_metrics()
            self._metrics_history.append(metrics)
            # 限制历史长度
            max_history = 1440  # 24 小时（每分钟一个点）
            if len(self._metrics_history) > max_history:
                self._metrics_history = self._metrics_history[-max_history:]
        except Exception as e:
            logger.error("系统指标采集失败: %s", e)
            return

        try:
            services = self.system_collector.collect_services(self.config)
        except Exception as e:
            logger.error("服务状态采集失败: %s", e)
            services = []

        try:
            logs = self.log_collector.collect_errors(self.config)
        except Exception as e:
            logger.error("日志采集失败: %s", e)
            logs = []

        # 采集 Docker 容器状态
        containers = []
        try:
            if self.docker_collector.is_available():
                docker_cfg = self.config.get("docker", {})
                skip_stopped = docker_cfg.get("skip_stopped", False)
                ignore_list = set(docker_cfg.get("ignore_containers", []))

                container_infos = self.docker_collector.collect_containers()
                containers = []
                for c in container_infos:
                    # 跳过忽略的容器
                    if c.name in ignore_list:
                        continue
                    # 跳过已停止的容器
                    if skip_stopped and c.status != "running":
                        continue
                    containers.append({
                        "id": c.id,
                        "name": c.name,
                        "image": c.image,
                        "status": c.status,
                        "health": c.health,
                        "cpu_percent": c.cpu_percent,
                        "memory_usage_mb": c.memory_usage_mb,
                        "memory_limit_mb": c.memory_limit_mb,
                        "memory_percent": c.memory_percent,
                        "net_rx_bytes": c.net_rx_bytes,
                        "net_tx_bytes": c.net_tx_bytes,
                        "restart_count": c.restart_count,
                    })
                logger.info("采集到 %d 个 Docker 容器", len(containers))
        except Exception as e:
            logger.error("Docker 容器采集失败: %s", e)
            containers = []

        # 采集 systemd journal 错误日志
        journal_logs: list = []
        try:
            if self.journal_collector.is_available():
                journal_units = self.config.get("logs", {}).get("journal_units", None)
                journal_entries = self.journal_collector.collect_errors(
                    units=journal_units,
                    max_priority=3,
                    since_minutes=60,
                    max_entries=500,
                )
                journal_logs = [
                    LogEntry(
                        timestamp=e.timestamp if hasattr(e, 'timestamp') else datetime.now(),
                        source=f"journal:{e.unit}" if hasattr(e, 'unit') else "journal",
                        level=e.priority_name if hasattr(e, 'priority_name') else "ERROR",
                        message=f"[{e.priority_name}] {e.message}" if hasattr(e, 'message') else str(e),
                    )
                    for e in journal_entries
                ]
                if journal_logs:
                    logger.info("journal 采集到 %d 条错误日志", len(journal_logs))
        except Exception as e:
            logger.error("journal 日志采集失败: %s", e)
            journal_logs = []

        # 合并所有日志
        logs = logs + journal_logs

        # 2. 检测
        try:
            issues = self.anomaly_detector.detect(metrics, services, logs, self.config, containers=containers)
        except Exception as e:
            logger.error("异常检测失败: %s", e)
            issues = []

        if not issues:
            logger.info("本轮检查未发现异常")
            return

        logger.info("检测到 %d 个问题", len(issues))

        # 3. 分析
        try:
            analysis = self.fault_analyzer.analyze(issues)
        except Exception as e:
            logger.error("故障分析失败: %s", e)
            analysis = {"root_causes": [], "suggestions": [], "correlated": False}

        # 4. 处置
        actions = []
        try:
            actions = self.auto_remediator.remediate(analysis, self.config)
        except Exception as e:
            logger.error("自动处置失败: %s", e)

        # 5. 记录到记忆
        try:
            self._record_incidents(issues, analysis, actions, time.time() - start_time)
        except Exception as e:
            logger.error("事件记录失败: %s", e)

        # 6. LLM 智能分析（在告警推送之前）
        llm_analysis: Optional[dict] = None
        if self.llm_analyzer is not None and self.llm_analyzer.is_available():
            non_info_issues_for_llm = [i for i in issues if i.severity != Severity.INFO]
            if non_info_issues_for_llm:
                server_name = self.config.get("server", {}).get("name", "unknown")
                try:
                    llm_analysis = self.llm_analyzer.analyze_issues(non_info_issues_for_llm, server_name)
                    if llm_analysis:
                        logger.info("LLM 分析结果: 风险=%s, 根因=%s",
                                   llm_analysis.get("risk_level"),
                                   llm_analysis.get("root_cause", "")[:80])
                except Exception as e:
                    logger.error("LLM 分析失败: %s", e)

        # 7. 飞书告警推送（通知失败不影响主循环）
        if self.notifier is not None:
            server_name = self.config.get("server", {}).get("name", "unknown")
            # 有非 INFO 级别的 Issue 时推送告警
            non_info_issues = [i for i in issues if i.severity != Severity.INFO]
            if non_info_issues:
                try:
                    self.notifier.send_alert(non_info_issues, server_name, llm_analysis=llm_analysis)
                except Exception as e:
                    logger.error("飞书告警推送失败: %s", e)
            # 处置完成后推送处置结果
            if actions:
                try:
                    self.notifier.send_remediation_report(actions, server_name)
                except Exception as e:
                    logger.error("飞书处置结果推送失败: %s", e)

        elapsed = time.time() - start_time
        logger.info("----- 检查周期 #%d 完成，耗时 %.1fs -----", self._check_count + 1, elapsed)

    def _record_incidents(
        self,
        issues: list,
        analysis: dict,
        actions: list,
        duration: float,
    ) -> None:
        """将事件记录到 SQLite 记忆存储

        Args:
            issues: 检测到的问题列表
            analysis: 分析结果
            actions: 处置结果列表
            duration: 本轮检查耗时
        """
        root_causes = analysis.get("root_causes", [])
        suggestions = analysis.get("suggestions", [])

        for issue in issues:
            # 找到对应的根因
            root_cause = "未分析"
            for rc in root_causes:
                if isinstance(rc, dict):
                    if rc.get("issue_id") == issue.id or rc.get("issue_type") == issue.issue_type.value:
                        root_cause = rc.get("root_cause", str(rc.get("possible_causes", ["未知"])))
                        break

            # 找到对应的处置动作
            action_taken = None
            for action_result in actions:
                if action_result.action.issue_id == issue.id:
                    action_taken = action_result
                    break

            record = IncidentRecord(
                issue=issue,
                root_cause=root_cause,
                action_taken=action_taken,
                resolved=action_taken.success if action_taken else False,
                duration_seconds=duration,
                lessons="; ".join(suggestions[:3]) if suggestions else "",
            )
            self.memory.save_incident(record)

        # 定期清理过期记录
        max_records = self.config.get("memory", {}).get("max_records", 10000)
        self.memory.cleanup(max_records)

    def _generate_report(self) -> None:
        """定时报表调度器回调：生成报表并可选推送飞书"""
        try:
            report_path = self.report_generator.generate(
                metrics_history=self._metrics_history[-100:],
                issues=[],
                actions=[],
                config=self.config,
            )
            logger.info("定时报表已生成: %s", report_path)
        except Exception as e:
            logger.error("定时报表生成失败: %s", e)
            return

        # 飞书推送摘要
        if self.notifier is not None:
            try:
                self.notifier.send_daily_report(
                    server_name=self.config.get("server", {}).get("name", "unknown"),
                    metrics=self._metrics_history[-1] if self._metrics_history else None,
                )
                logger.info("定时报表摘要已推送到飞书")
            except Exception as e:
                logger.error("飞书报表摘要推送失败: %s", e)

    def _maybe_generate_report(self) -> None:
        """检查是否需要生成报告"""
        now = time.time()
        # 每 10 个周期或距上次报告超过 1 小时
        if self._check_count % 10 != 0 and (now - self._last_report_time) < 3600:
            return

        try:
            # 收集最近的问题和处置（简化：使用记忆中的统计）
            report_path = self.report_generator.generate(
                metrics_history=self._metrics_history[-100:],
                issues=[],  # 实际可从最近周期收集
                actions=[],
                config=self.config,
            )
            self._last_report_time = now
            logger.info("定期报告已生成: %s", report_path)
        except Exception as e:
            logger.error("生成报告失败: %s", e)

    def _interruptible_sleep(self, seconds: int) -> None:
        """可中断的睡眠，每秒检查 _running 标志

        Args:
            seconds: 睡眠秒数
        """
        for _ in range(seconds):
            if not self._running:
                break
            time.sleep(1)

    def _cleanup(self) -> None:
        """退出清理：关闭数据库、生成最终报告"""
        logger.info("OpsAgent 正在退出...")

        # 生成最终报告
        try:
            if self._metrics_history:
                report_path = self.report_generator.generate(
                    metrics_history=self._metrics_history,
                    issues=[],
                    actions=[],
                    config=self.config,
                )
                logger.info("最终报告: %s", report_path)
        except Exception as e:
            logger.error("生成最终报告失败: %s", e)

        # 关闭数据库
        try:
            self.memory.close()
        except Exception as e:
            logger.error("关闭数据库失败: %s", e)

        logger.info("OpsAgent 已退出")

    def run_once(self) -> dict:
        """执行单次检查（用于调试或外部调用）

        Returns:
            dict: 检查结果摘要
        """
        self._run_check_cycle()

        # 生成报告
        try:
            if self._metrics_history:
                report_path = self.report_generator.generate(
                    metrics_history=self._metrics_history,
                    issues=[],
                    actions=[],
                    config=self.config,
                )
                logger.info("巡检报告已生成: %s", report_path)
        except Exception as e:
            logger.error("生成报告失败: %s", e)

        stats = self.memory.get_stats()
        return {
            "check_count": self._check_count,
            "metrics_count": len(self._metrics_history),
            "memory_stats": stats,
        }


def main() -> None:
    """CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="OpsAgent 轻量级运维监控 Agent")
    parser.add_argument(
        "-c", "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="配置文件路径",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="演练模式，不实际执行处置动作",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="只执行一次检查后退出",
    )
    args = parser.parse_args()

    agent = OpsAgent(config_path=args.config, dry_run=args.dry_run)

    if args.once:
        result = agent.run_once()
        print(f"单次检查完成: {result}")
    else:
        agent.run()


if __name__ == "__main__":
    main()
