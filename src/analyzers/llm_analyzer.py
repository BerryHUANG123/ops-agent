"""LLM 智能分析器 — 通过大模型进行日志分析和根因推断"""
import json
import logging
import os
import urllib.request
from typing import Dict, List, Optional

from src.models import Issue, Severity, IssueType

logger = logging.getLogger(__name__)


class LLMAnalyzer:
    """LLM 智能分析器
    
    通过 OpenAI 兼容 API 调用大模型，
    对告警和日志进行深度分析，给出根因推断和处置建议。
    """

    # 默认分析 prompt
    SYSTEM_PROMPT = """你是一个 Linux 服务器运维专家。请分析以下服务器告警信息，给出：
1. 最可能的根因（1-2 句话）
2. 故障分类（资源类/服务类/日志类/网络类/配置类）
3. 具体处置建议（按优先级排列，最多 5 条）
4. 风险等级评估（低/中/高/紧急）

请用 JSON 格式回复：
{
  "root_cause": "...",
  "category": "...",
  "suggestions": ["...", "..."],
  "risk_level": "...",
  "explanation": "..."}"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout: int = 30,
        max_tokens: int = 1000,
    ):
        """
        Args:
            api_key: API 密钥，None 时从环境变量 OPENAI_API_KEY 读取
            base_url: API 基础 URL（兼容 OpenAI 格式）
            model: 模型名称
            timeout: 请求超时（秒）
            max_tokens: 最大输出 token 数
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """检测 LLM 是否可用（有 API key）"""
        if self._available is not None:
            return self._available
        self._available = bool(self.api_key)
        if not self._available:
            logger.info("LLM 分析器未配置 API key，跳过智能分析")
        return self._available

    def analyze_issues(self, issues: List[Issue], server_name: str = "unknown") -> Optional[dict]:
        """用 LLM 分析告警问题
        
        Args:
            issues: 检测到的 Issue 列表
            server_name: 服务器名称
            
        Returns:
            dict: 分析结果，包含 root_cause, category, suggestions, risk_level, explanation
                  失败时返回 None
        """
        if not self.is_available() or not issues:
            return None

        # 构建分析上下文
        context = self._build_context(issues, server_name)
        
        try:
            result = self._call_llm(self.SYSTEM_PROMPT, context)
            if result:
                parsed = self._parse_response(result)
                logger.info("LLM 分析完成: 风险=%s, 分类=%s", 
                           parsed.get("risk_level"), parsed.get("category"))
                return parsed
        except Exception as e:
            logger.error("LLM 分析异常: %s", e)
        
        return None

    def analyze_logs(self, log_lines: List[str], context: str = "") -> Optional[dict]:
        """用 LLM 分析日志片段
        
        Args:
            log_lines: 日志行列表
            context: 额外上下文信息
            
        Returns:
            dict: 分析结果
        """
        if not self.is_available() or not log_lines:
            return None

        prompt = f"""请分析以下服务器日志，找出异常模式和潜在问题：

{context}

日志片段（最近 {len(log_lines)} 条）：
```
{chr(10).join(log_lines[:50])}
```

请用 JSON 格式回复：
{{
  "patterns": ["发现的异常模式"],
  "potential_issues": ["潜在问题"],
  "suggestions": ["建议"]}}"""

        try:
            result = self._call_llm("你是日志分析专家。", prompt)
            if result:
                return self._parse_response(result)
        except Exception as e:
            logger.error("LLM 日志分析异常: %s", e)

        return None

    def _build_context(self, issues: List[Issue], server_name: str) -> str:
        """构建分析上下文"""
        lines = [f"服务器: {server_name}", f"告警数量: {len(issues)}", "", "告警详情："]
        
        for i, issue in enumerate(issues, 1):
            lines.append(f"{i}. [{issue.severity.value.upper()}] {issue.title}")
            lines.append(f"   描述: {issue.description}")
            if issue.details:
                lines.append(f"   详情: {json.dumps(issue.details, ensure_ascii=False)}")
            lines.append("")

        return "\n".join(lines)

    def _call_llm(self, system: str, user: str) -> Optional[str]:
        """调用 LLM API"""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.3,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode())
                return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            logger.error("LLM API HTTP 错误 %d: %s", e.code, body[:200])
            return None
        except Exception as e:
            logger.error("LLM API 请求异常: %s", e)
            return None

    def _parse_response(self, text: str) -> dict:
        """解析 LLM 返回的 JSON"""
        # 尝试从 markdown code block 中提取 JSON
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 解析失败，返回原始文本
            return {
                "root_cause": text[:200],
                "category": "未知",
                "suggestions": [],
                "risk_level": "未知",
                "explanation": text,
            }
