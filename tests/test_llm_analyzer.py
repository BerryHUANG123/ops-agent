"""LLM 智能分析器单元测试"""
import json
import unittest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from src.models import Issue, Severity, IssueType
from src.analyzers.llm_analyzer import LLMAnalyzer


def _make_issue(title="CPU 过高", severity=Severity.CRITICAL, description="CPU 使用率 95%"):
    """创建测试用 Issue"""
    return Issue(
        id="test-001",
        timestamp=datetime.now(),
        issue_type=IssueType.CPU_HIGH,
        severity=severity,
        title=title,
        description=description,
        details={"cpu_percent": 95},
    )


class TestLLMAnalyzerAvailability(unittest.TestCase):
    """测试 LLM 可用性检测"""

    def test_not_available_no_key(self):
        """无 API key 时不可用"""
        analyzer = LLMAnalyzer(api_key="", base_url="http://localhost")
        self.assertFalse(analyzer.is_available())

    def test_available_with_key(self):
        """有 key 时可用"""
        analyzer = LLMAnalyzer(api_key="sk-test-key", base_url="http://localhost")
        self.assertTrue(analyzer.is_available())

    def test_available_from_env(self):
        """从环境变量读取 key"""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env-key"}):
            analyzer = LLMAnalyzer(base_url="http://localhost")
            self.assertTrue(analyzer.is_available())

    def test_not_available_empty_env(self):
        """环境变量为空时不可用"""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            # 清除缓存
            analyzer = LLMAnalyzer(api_key="", base_url="http://localhost")
            analyzer._available = None
            self.assertFalse(analyzer.is_available())


class TestLLMAnalyzerContext(unittest.TestCase):
    """测试上下文构建"""

    def test_build_context(self):
        """上下文构建正确"""
        analyzer = LLMAnalyzer(api_key="sk-test", base_url="http://localhost")
        issues = [
            _make_issue("CPU 过高", Severity.CRITICAL, "CPU 使用率 95%"),
            _make_issue("内存不足", Severity.WARNING, "内存使用率 92%"),
        ]
        context = analyzer._build_context(issues, "test-server")
        self.assertIn("test-server", context)
        self.assertIn("2", context)  # 告警数量
        self.assertIn("CPU 过高", context)
        self.assertIn("内存不足", context)
        self.assertIn("CRITICAL", context)
        self.assertIn("WARNING", context)
        self.assertIn("cpu_percent", context)


class TestLLMAnalyzerParseResponse(unittest.TestCase):
    """测试响应解析"""

    def test_parse_response_json(self):
        """正常 JSON 解析"""
        analyzer = LLMAnalyzer(api_key="sk-test", base_url="http://localhost")
        text = json.dumps({
            "root_cause": "内存泄漏",
            "category": "资源类",
            "suggestions": ["重启服务"],
            "risk_level": "高",
            "explanation": "详细说明",
        })
        result = analyzer._parse_response(text)
        self.assertEqual(result["root_cause"], "内存泄漏")
        self.assertEqual(result["category"], "资源类")
        self.assertEqual(result["suggestions"], ["重启服务"])

    def test_parse_response_markdown(self):
        """markdown code block 中的 JSON 解析"""
        analyzer = LLMAnalyzer(api_key="sk-test", base_url="http://localhost")
        text = '这是分析结果：\n```json\n{"root_cause": "磁盘满", "category": "资源类", "suggestions": ["清理日志"], "risk_level": "中", "explanation": "..."}\n```\n以上。'
        result = analyzer._parse_response(text)
        self.assertEqual(result["root_cause"], "磁盘满")

    def test_parse_response_markdown_no_lang(self):
        """无语言标记的 code block 解析"""
        analyzer = LLMAnalyzer(api_key="sk-test", base_url="http://localhost")
        text = '```\n{"root_cause": "配置错误", "category": "配置类", "suggestions": [], "risk_level": "低", "explanation": "..."}\n```'
        result = analyzer._parse_response(text)
        self.assertEqual(result["root_cause"], "配置错误")

    def test_parse_response_invalid(self):
        """无效 JSON 返回默认结构"""
        analyzer = LLMAnalyzer(api_key="sk-test", base_url="http://localhost")
        text = "这不是 JSON 格式的回复"
        result = analyzer._parse_response(text)
        self.assertEqual(result["category"], "未知")
        self.assertEqual(result["suggestions"], [])
        self.assertIn("explanation", result)


class TestLLMAnalyzerAnalyzeIssues(unittest.TestCase):
    """测试告警分析"""

    @patch("src.analyzers.llm_analyzer.urllib.request.urlopen")
    def test_analyze_issues_success(self, mock_urlopen):
        """成功分析（mock HTTP）"""
        # mock 响应
        response_data = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "root_cause": "CPU 过载",
                        "category": "资源类",
                        "suggestions": ["检查高 CPU 进程", "考虑扩容"],
                        "risk_level": "高",
                        "explanation": "CPU 使用率持续过高",
                    })
                }
            }]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        analyzer = LLMAnalyzer(api_key="sk-test", base_url="http://localhost")
        issues = [_make_issue()]
        result = analyzer.analyze_issues(issues, "test-server")

        self.assertIsNotNone(result)
        self.assertEqual(result["root_cause"], "CPU 过载")
        self.assertEqual(result["category"], "资源类")
        self.assertEqual(len(result["suggestions"]), 2)

    @patch("src.analyzers.llm_analyzer.urllib.request.urlopen")
    def test_analyze_issues_api_error(self, mock_urlopen):
        """API 错误返回 None"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://localhost", code=401, msg="Unauthorized",
            hdrs=None, fp=None,
        )
        # 给 HTTPError 添加 fp.read
        mock_fp = MagicMock()
        mock_fp.read.return_value = b"invalid key"
        mock_urlopen.side_effect.fp = mock_fp

        analyzer = LLMAnalyzer(api_key="sk-bad-key", base_url="http://localhost")
        result = analyzer.analyze_issues([_make_issue()], "test-server")
        self.assertIsNone(result)

    def test_analyze_issues_empty(self):
        """空 issues 返回 None"""
        analyzer = LLMAnalyzer(api_key="sk-test", base_url="http://localhost")
        result = analyzer.analyze_issues([], "test-server")
        self.assertIsNone(result)

    def test_analyze_issues_no_key(self):
        """无 API key 返回 None"""
        analyzer = LLMAnalyzer(api_key="", base_url="http://localhost")
        result = analyzer.analyze_issues([_make_issue()], "test-server")
        self.assertIsNone(result)


class TestLLMAnalyzerAnalyzeLogs(unittest.TestCase):
    """测试日志分析"""

    @patch("src.analyzers.llm_analyzer.urllib.request.urlopen")
    def test_analyze_logs_success(self, mock_urlopen):
        """成功分析日志"""
        response_data = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "patterns": ["频繁 OOM"],
                        "potential_issues": ["内存泄漏"],
                        "suggestions": ["检查内存使用"],
                    })
                }
            }]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        analyzer = LLMAnalyzer(api_key="sk-test", base_url="http://localhost")
        logs = ["Jan 1 00:00:01 server kernel: Out of memory", "Jan 1 00:00:02 server kernel: Killed process 1234"]
        result = analyzer.analyze_logs(logs, context="测试日志分析")

        self.assertIsNotNone(result)
        self.assertIn("patterns", result)

    def test_analyze_logs_empty(self):
        """空日志返回 None"""
        analyzer = LLMAnalyzer(api_key="sk-test", base_url="http://localhost")
        result = analyzer.analyze_logs([])
        self.assertIsNone(result)

    def test_analyze_logs_no_key(self):
        """无 API key 返回 None"""
        analyzer = LLMAnalyzer(api_key="", base_url="http://localhost")
        result = analyzer.analyze_logs(["some log line"])
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
