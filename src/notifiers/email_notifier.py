"""邮件告警通知"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import List, Optional

from src.models import Issue, Severity

logger = logging.getLogger(__name__)


class EmailNotifier:
    """SMTP 邮件告警通知"""

    SEVERITY_EMOJI = {
        Severity.INFO: "ℹ️",
        Severity.WARNING: "⚠️",
        Severity.CRITICAL: "🚨",
    }

    def __init__(self, smtp_host: str, smtp_port: int, username: str,
                 password: str, from_addr: str, to_addrs: list,
                 use_tls: bool = True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.use_tls = use_tls

    def send_alert(self, issues: List[Issue], server_name: str = "unknown") -> bool:
        """发送告警邮件"""
        if not issues:
            return True

        try:
            max_severity = max(issues, key=lambda i: list(Severity).index(i.severity)).severity
            emoji = self.SEVERITY_EMOJI[max_severity]

            subject = f"{emoji} [{server_name}] 运维告警 — {len(issues)} 个异常"

            # 构建 HTML 邮件内容
            html = f"""
            <html><body style="font-family: sans-serif; padding: 20px;">
            <h2 style="color: {'#dc2626' if max_severity == Severity.CRITICAL else '#d97706'}">
                {emoji} {server_name} 运维告警
            </h2>
            <p>检测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <hr>
            """
            for issue in issues[:20]:
                sev = self.SEVERITY_EMOJI.get(issue.severity, "")
                color = '#dc2626' if issue.severity == Severity.CRITICAL else '#d97706'
                html += f"""
                <div style="margin: 10px 0; padding: 10px; border-left: 4px solid {color}; background: #f9f9f9;">
                    <strong>{sev} {issue.title}</strong><br>
                    <span style="color: #666; font-size: 13px;">{issue.description}</span>
                </div>
                """
            html += """
            <hr>
            <p style="color: #999; font-size: 12px;">OpsAgent 自动告警</p>
            </body></html>
            """

            return self._send(subject, html)
        except Exception as e:
            logger.error("邮件告警发送失败: %s", e)
            return False

    def _send(self, subject: str, html_body: str) -> bool:
        """发送邮件"""
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            if self.use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)

            server.login(self.username, self.password)
            server.sendmail(self.from_addr, self.to_addrs, msg.as_string())
            server.quit()
            logger.info("告警邮件已发送至 %s", ", ".join(self.to_addrs))
            return True
        except Exception as e:
            logger.error("邮件发送失败: %s", e)
            return False
