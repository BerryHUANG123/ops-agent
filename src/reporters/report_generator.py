"""报告生成器 — 基于 Jinja2 生成 HTML 巡检报告"""
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader

from src.models import Issue, RemediationResult, SystemMetrics

logger = logging.getLogger(__name__)

# 模板目录
TEMPLATE_DIR = Path(__file__).parent / "templates"


class ReportGenerator:
    """HTML 巡检报告生成器"""

    def __init__(self) -> None:
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True,
        )

    def generate(
        self,
        metrics_history: List[SystemMetrics],
        issues: List[Issue],
        actions: List[RemediationResult],
        config: dict,
        analysis: Optional[dict] = None,
    ) -> str:
        """生成 HTML 巡检报告

        Args:
            metrics_history: 系统指标历史列表
            issues: 检测到的问题列表
            actions: 处置动作结果列表
            config: 配置字典
            analysis: 故障分析结果（可选）

        Returns:
            str: 生成的 HTML 报告文件路径
        """
        report_cfg = config.get("report", {})
        output_dir = report_cfg.get("output_dir", "reports")
        os.makedirs(output_dir, exist_ok=True)

        # 生成文件名
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        server_name = config.get("server", {}).get("name", "server")
        filename = f"inspection_{server_name}_{timestamp_str}.html"
        output_path = os.path.join(output_dir, filename)

        # 准备模板数据
        latest_metrics = metrics_history[-1] if metrics_history else None
        template_data = self._prepare_template_data(
            latest_metrics, metrics_history, issues, actions, analysis, config
        )

        # 渲染模板
        try:
            template = self.env.get_template("inspection_report.html")
            html_content = template.render(**template_data)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            logger.info("报告已生成: %s", output_path)
            return output_path
        except Exception as e:
            logger.error("生成报告失败: %s", e)
            raise

    def _prepare_template_data(
        self,
        latest: Optional[SystemMetrics],
        history: List[SystemMetrics],
        issues: List[Issue],
        actions: List[RemediationResult],
        analysis: Optional[dict],
        config: dict,
    ) -> dict:
        """准备模板渲染数据

        Args:
            latest: 最新系统指标
            history: 指标历史
            issues: 问题列表
            actions: 处置结果列表
            analysis: 分析结果
            config: 配置

        Returns:
            dict: 模板数据
        """
        now = datetime.now()
        server_name = config.get("server", {}).get("name", "unknown")

        # 计算 uptime 可读格式
        uptime_str = "N/A"
        if latest:
            days = int(latest.uptime_seconds // 86400)
            hours = int((latest.uptime_seconds % 86400) // 3600)
            uptime_str = f"{days}天 {hours}小时"

        # 指标趋势数据（最近 20 个点）
        recent_history = history[-20:] if len(history) > 20 else history
        trend_data = {
            "timestamps": [
                datetime.fromtimestamp(m.timestamp).strftime("%H:%M") for m in recent_history
            ],
            "cpu": [m.cpu_percent for m in recent_history],
            "memory": [m.memory_percent for m in recent_history],
            "disk": [m.disk_percent for m in recent_history],
        }

        # 告警统计
        critical_count = sum(1 for i in issues if i.severity.value == "critical")
        warning_count = sum(1 for i in issues if i.severity.value == "warning")

        # 处置统计
        success_actions = sum(1 for a in actions if a.success)
        failed_actions = sum(1 for a in actions if not a.success)

        # 风险建议
        suggestions = []
        if analysis:
            suggestions = analysis.get("suggestions", [])

        return {
            "report_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "server_name": server_name,
            "uptime": uptime_str,
            "latest": latest,
            "trend_data": trend_data,
            "issues": issues,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "actions": actions,
            "success_actions": success_actions,
            "failed_actions": failed_actions,
            "suggestions": suggestions,
            "analysis": analysis,
        }
