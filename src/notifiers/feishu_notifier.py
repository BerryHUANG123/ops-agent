"""飞书 Webhook 告警推送"""
import json
import logging
import urllib.request
from typing import List, Optional
from datetime import datetime

from src.models import Issue, Severity, RemediationResult

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """飞书 Webhook 告警推送器"""

    # 严重级别对应的卡片颜色
    SEVERITY_COLORS = {
        Severity.INFO: "blue",
        Severity.WARNING: "orange",
        Severity.CRITICAL: "red",
    }

    SEVERITY_EMOJI = {
        Severity.INFO: "ℹ️",
        Severity.WARNING: "⚠️",
        Severity.CRITICAL: "🚨",
    }

    def __init__(self, webhook_url: str, secret: Optional[str] = None) -> None:
        """
        Args:
            webhook_url: 飞书自定义机器人 Webhook URL
            secret: 签名校验密钥（可选）
        """
        self.webhook_url = webhook_url
        self.secret = secret

    @staticmethod
    def _get_server_ip() -> str:
        """获取服务器 IP"""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "localhost"

    def send_alert(self, issues: List[Issue], server_name: str = "unknown", llm_analysis: Optional[dict] = None) -> bool:
        """发送告警消息（飞书富文本卡片）

        Args:
            issues: 检测到的 Issue 列表
            server_name: 服务器名称
            llm_analysis: LLM 智能分析结果（可选）

        Returns:
            bool: 是否发送成功
        """
        if not issues:
            return True

        card = self._build_alert_card(issues, server_name, llm_analysis=llm_analysis)
        return self._send_card(card)

    def send_remediation_report(
        self,
        results: List[RemediationResult],
        server_name: str = "unknown",
    ) -> bool:
        """发送处置结果通知

        Args:
            results: 处置结果列表
            server_name: 服务器名称

        Returns:
            bool: 是否发送成功
        """
        if not results:
            return True

        card = self._build_remediation_card(results, server_name)
        return self._send_card(card)

    def send_daily_report(self, stats: dict, server_name: str = "unknown") -> bool:
        """发送每日巡检摘要

        Args:
            stats: 统计数据字典
            server_name: 服务器名称

        Returns:
            bool: 是否发送成功
        """
        card = self._build_daily_card(stats, server_name)
        return self._send_card(card)

    def _build_alert_card(self, issues: List[Issue], server_name: str, llm_analysis: Optional[dict] = None) -> dict:
        """构建告警卡片消息

        Args:
            issues: Issue 列表
            server_name: 服务器名称
            llm_analysis: LLM 智能分析结果（可选）

        Returns:
            dict: 飞书卡片消息体
        """
        # 按严重级别排序，CRITICAL 优先
        sorted_issues = sorted(
            issues,
            key=lambda i: list(Severity).index(i.severity),
            reverse=True,
        )

        max_severity = sorted_issues[0].severity
        emoji = self.SEVERITY_EMOJI[max_severity]

        # 构建 Issue 列表文本
        issue_lines: List[str] = []
        for issue in sorted_issues[:10]:  # 最多显示 10 个
            sev_emoji = self.SEVERITY_EMOJI[issue.severity]
            issue_lines.append(f"{sev_emoji} **{issue.title}**\n{issue.description}")

        if len(sorted_issues) > 10:
            issue_lines.append(f"... 还有 {len(sorted_issues) - 10} 个问题")

        issues_text = "\n\n".join(issue_lines)

        # 构建 elements
        elements: list = [
            {
                "tag": "markdown",
                "content": issues_text,
            },
        ]

        # 如果有 LLM 分析结果，插入 AI 分析区块
        if llm_analysis:
            ai_text = "**🤖 AI 分析**\n"
            ai_text += f"**根因:** {llm_analysis.get('root_cause', '未知')}\n"
            ai_text += f"**分类:** {llm_analysis.get('category', '未知')}\n"
            ai_text += f"**风险:** {llm_analysis.get('risk_level', '未知')}\n"
            suggestions = llm_analysis.get('suggestions', [])
            if suggestions:
                ai_text += "**建议:**\n"
                for s in suggestions[:5]:
                    ai_text += f"- {s}\n"
            elements.append({"tag": "markdown", "content": ai_text})

        # 分隔线和时间戳
        elements.extend([
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 已知晓"},
                        "type": "primary",
                        "value": {"action": "ack", "server": server_name},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🔇 静默1小时"},
                        "type": "default",
                        "value": {"action": "mute_1h", "server": server_name},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "📋 查看报告"},
                        "type": "default",
                        "value": {"action": "view_report", "server": server_name},
                        "url": f"http://{self._get_server_ip()}:8080/reports",
                    },
                ],
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"检测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    }
                ],
            },
        ])

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"{emoji} [{server_name}] 运维告警 — {len(issues)} 个异常",
                    },
                    "template": self.SEVERITY_COLORS[max_severity],
                },
                "elements": elements,
            },
        }
        return card

    def _build_remediation_card(
        self, results: List[RemediationResult], server_name: str
    ) -> dict:
        """构建处置结果卡片

        Args:
            results: 处置结果列表
            server_name: 服务器名称

        Returns:
            dict: 飞书卡片消息体
        """
        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count

        lines: List[str] = []
        for r in results:
            status = "✅" if r.success else "❌"
            lines.append(f"{status} {r.action.action_type.value}: {r.action.target}")

        content = "\n".join(lines)

        color = "green" if fail_count == 0 else "orange"
        title = f"🔧 [{server_name}] 自动处置完成 — {success_count}成功/{fail_count}失败"

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": color,
                },
                "elements": [
                    {"tag": "markdown", "content": content},
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"处置时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                            }
                        ],
                    },
                ],
            },
        }
        return card

    def _build_daily_card(self, stats: dict, server_name: str) -> dict:
        """构建每日摘要卡片

        Args:
            stats: 统计数据字典
            server_name: 服务器名称

        Returns:
            dict: 飞书卡片消息体
        """
        content = (
            f"**CPU:** {stats.get('cpu_avg', 'N/A')}%  |  "
            f"**内存:** {stats.get('mem_avg', 'N/A')}%  |  "
            f"**磁盘:** {stats.get('disk_avg', 'N/A')}%\n"
            f"**告警数:** {stats.get('total_alerts', 0)}  |  "
            f"**处置数:** {stats.get('total_actions', 0)}  |  "
            f"**运行时长:** {stats.get('uptime', 'N/A')}"
        )

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"📊 [{server_name}] 每日巡检摘要",
                    },
                    "template": "blue",
                },
                "elements": [
                    {"tag": "markdown", "content": content},
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                            }
                        ],
                    },
                ],
            },
        }
        return card

    def _send_card(self, card: dict) -> bool:
        """通过 Webhook 发送卡片消息

        Args:
            card: 飞书卡片消息体

        Returns:
            bool: 是否发送成功
        """
        try:
            data = json.dumps(card).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                if result.get("code") == 0 or result.get("StatusCode") == 0:
                    logger.info("飞书消息发送成功")
                    return True
                else:
                    logger.error("飞书消息发送失败: %s", result)
                    return False
        except Exception as e:
            logger.error("飞书 Webhook 请求异常: %s", e)
            return False
