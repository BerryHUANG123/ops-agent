"""OpsAgent Web UI — Flask 轻量管理界面"""
import glob
import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from functools import wraps

import psutil
import yaml
from flask import Flask, jsonify, redirect, render_template, request, url_for, session

logger = logging.getLogger(__name__)

# 路径
BASE_DIR = Path(__file__).parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "default.yaml"
REPORTS_DIR = BASE_DIR / "reports"
DB_PATH = BASE_DIR / "data" / "ops_agent.db"


def create_app() -> Flask:
    """创建 Flask 应用"""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    # 加载配置
    cfg = _load_config()
    auth_cfg = cfg.get("webui", {}).get("auth", {})
    app.config["SECRET_KEY"] = auth_cfg.get("secret_key", "ops-agent-secret")
    app.config["AUTH_ENABLED"] = auth_cfg.get("enabled", False)
    app.config["USERS"] = auth_cfg.get("users", {})

    # 登录频率限制
    login_attempts = {}  # ip -> {count, blocked_until}

    # 登录检查装饰器：viewer 角色可直接访问，admin 操作需登录
    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not app.config["AUTH_ENABLED"]:
                return f(*args, **kwargs)
            # 已登录用户正常访问
            if "user" in session:
                return f(*args, **kwargs)
            # 未登录 = guest 角色，允许只读访问
            session["user"] = "guest"
            session["role"] = "viewer"
            return f(*args, **kwargs)
        return decorated

    def admin_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not app.config["AUTH_ENABLED"]:
                return f(*args, **kwargs)
            if "user" not in session or session.get("role") != "admin":
                return jsonify({"error": "forbidden", "message": "需要管理员权限，请先登录"}), 403
            return f(*args, **kwargs)
        return decorated

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not app.config["AUTH_ENABLED"]:
            return redirect(url_for("index"))
        error = None
        ip = request.remote_addr
        now = time.time()

        # 检查频率限制
        if ip in login_attempts:
            attempt = login_attempts[ip]
            if attempt.get("blocked_until", 0) > now:
                remain = int(attempt["blocked_until"] - now)
                error = f"登录失败次数过多，请 {remain} 秒后再试"
                return render_template("login.html", error=error)
            elif attempt.get("blocked_until", 0) and attempt["blocked_until"] <= now:
                login_attempts.pop(ip, None)

        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            users = app.config["USERS"]
            if username in users and users[username]["password"] == password:
                session["user"] = username
                session["role"] = users[username]["role"]
                login_attempts.pop(ip, None)  # 登录成功清除计数
                next_url = request.args.get("next", url_for("index"))
                return redirect(next_url)

            # 登录失败，记录次数
            if ip not in login_attempts:
                login_attempts[ip] = {"count": 0}
            login_attempts[ip]["count"] += 1
            count = login_attempts[ip]["count"]
            if count >= 5:
                login_attempts[ip]["blocked_until"] = now + 300  # 5次失败锁定5分钟
                error = "登录失败 5 次，已锁定 5 分钟"
            else:
                error = f"用户名或密码错误（{5 - count} 次机会剩余）"
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.pop("user", None)
        session.pop("role", None)
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def index():
        """仪表盘首页"""
        metrics = _get_system_metrics()
        services = _get_service_status()
        docker = _get_docker_status()
        recent_incidents = _get_recent_incidents(limit=10)
        stats = _get_memory_stats()
        return render_template(
            "dashboard.html",
            metrics=metrics,
            services=services,
            docker=docker,
            incidents=recent_incidents,
            stats=stats,
            server_name=_get_server_name(),
        )

    @app.route("/incidents")
    @login_required
    def incidents():
        """告警列表"""
        page = request.args.get("page", 1, type=int)
        per_page = 20
        offset = (page - 1) * per_page
        incidents_list, total = _get_incidents_paginated(offset, per_page)
        total_pages = (total + per_page - 1) // per_page
        return render_template(
            "incidents.html",
            incidents=incidents_list,
            page=page,
            total_pages=total_pages,
            total=total,
            server_name=_get_server_name(),
        )

    @app.route("/api/incidents/resolve", methods=["POST"])
    @admin_required
    def api_resolve_incident():
        """API: 标记事件为已解决"""
        data = request.get_json() or {}
        incident_id = data.get("id")
        if not incident_id:
            return jsonify({"ok": False, "error": "missing id"}), 400
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE incidents SET resolved=1, updated_at=? WHERE id=?",
            (time.time(), incident_id),
        )
        conn.commit()
        changed = cursor.rowcount
        conn.close()
        return jsonify({"ok": True, "resolved": changed})

    @app.route("/api/incidents/resolve-all", methods=["POST"])
    @admin_required
    def api_resolve_all():
        """API: 标记所有未解决事件为已解决"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE incidents SET resolved=1, updated_at=? WHERE resolved=0",
            (time.time(),),
        )
        conn.commit()
        changed = cursor.rowcount
        conn.close()
        return jsonify({"ok": True, "resolved": changed})

    @app.route("/api/incidents/delete", methods=["POST"])
    @admin_required
    def api_delete_incident():
        """API: 删除单个事件"""
        data = request.get_json() or {}
        incident_id = data.get("id")
        if not incident_id:
            return jsonify({"ok": False, "error": "missing id"}), 400
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM incidents WHERE id=?", (incident_id,))
        conn.commit()
        changed = cursor.rowcount
        conn.close()
        return jsonify({"ok": True, "deleted": changed})

    @app.route("/reports")
    @login_required
    def reports():
        """巡检报告列表"""
        report_files = _get_report_files()
        return render_template(
            "reports.html",
            reports=report_files,
            server_name=_get_server_name(),
        )

    @app.route("/reports/<filename>")
    def view_report(filename):
        """查看单个报告"""
        report_path = REPORTS_DIR / filename
        if not report_path.exists():
            return "报告不存在", 404
        return report_path.read_text(encoding="utf-8")

    @app.route("/health")
    @login_required
    def health_page():
        """健康状态页面"""
        return render_template("health.html", server_name=_get_server_name())

    @app.route("/audit")
    @login_required
    def audit():
        """审计日志"""
        page = request.args.get("page", 1, type=int)
        per_page = 30
        offset = (page - 1) * per_page
        if DB_PATH.exists():
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM audit_log")
            total = cursor.fetchone()[0]
            cursor.execute("""
                SELECT id, timestamp, action, target, command, result, success, operator, details
                FROM audit_log ORDER BY timestamp DESC LIMIT ? OFFSET ?
            """, (per_page, offset))
            logs = []
            for row in cursor.fetchall():
                ts = row["timestamp"]
                if isinstance(ts, (int, float)):
                    ts = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                logs.append({
                    "id": row["id"], "timestamp": ts, "action": row["action"],
                    "target": row["target"], "command": row["command"],
                    "result": row["result"], "success": bool(row["success"]),
                    "operator": row["operator"], "details": row["details"],
                })
            conn.close()
        else:
            logs, total = [], 0
        total_pages = (total + per_page - 1) // per_page
        return render_template("audit.html", logs=logs, page=page,
                               total_pages=total_pages, total=total,
                               server_name=_get_server_name())

    @app.route("/config")
    @login_required
    def config():
        """配置查看"""
        cfg = _load_config()
        return render_template(
            "config.html",
            config=cfg,
            config_yaml=yaml.dump(cfg, allow_unicode=True, default_flow_style=False),
            server_name=_get_server_name(),
        )

    @app.route("/api/network")
    def api_network():
        """API: 网络连接信息"""
        from src.collectors.network_collector import NetworkCollector
        nc = NetworkCollector()
        ports = nc.collect_listening_ports()
        conns = nc.collect_connections(max_connections=50)
        return jsonify({
            "listening": [{
                "port": p.port, "protocol": p.protocol,
                "process": p.process_name, "pid": p.pid, "address": p.address,
            } for p in ports],
            "connections": [{
                "local": f"{c.local_addr}:{c.local_port}",
                "remote": f"{c.remote_addr}:{c.remote_port}",
                "status": c.status, "process": c.process_name, "pid": c.pid,
            } for c in conns],
        })

    @app.route("/api/processes")
    def api_processes():
        """API: 进程资源占用 Top N"""
        n = request.args.get("limit", 15, type=int)
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'username']):
            try:
                info = p.info
                cpu = p.cpu_percent(interval=0)
                mem = p.memory_info()
                procs.append({
                    "pid": info["pid"],
                    "name": info["name"],
                    "user": info["username"] or "-",
                    "cpu": cpu,
                    "mem_mb": round(mem.rss / 1024 / 1024, 1),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x["cpu"], reverse=True)
        return jsonify(procs[:n])

    @app.route("/api/disk/prediction")
    def api_disk_prediction():
        """API: 磁盘增长趋势预测"""
        if not DB_PATH.exists():
            return jsonify({"error": "no data"})
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, disk_percent FROM metrics_history
            WHERE disk_percent IS NOT NULL
            ORDER BY timestamp ASC
        """)
        rows = cursor.fetchall()
        conn.close()

        if len(rows) < 2:
            return jsonify({"error": "insufficient data", "points": len(rows)})

        # 线性回归预测磁盘增长
        timestamps = [r["timestamp"] for r in rows]
        disk_values = [r["disk_percent"] for r in rows]
        n = len(timestamps)
        t0 = timestamps[0]
        x = [(t - t0) / 3600 for t in timestamps]  # 转为小时
        y = disk_values

        # 最小二乘法
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi * xi for xi in x)
        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0:
            return jsonify({"error": "no variance", "points": n})

        slope = (n * sum_xy - sum_x * sum_y) / denom  # %/小时
        intercept = (sum_y - slope * sum_x) / n
        current = disk_values[-1]

        # 预测何时到达 90% 和 95%
        result = {
            "current_percent": current,
            "growth_rate_per_hour": round(slope, 4),
            "growth_rate_per_day": round(slope * 24, 2),
            "data_points": n,
            "data_hours": round(x[-1], 1),
        }
        if slope > 0:
            hours_to_90 = (90 - current) / slope
            hours_to_95 = (95 - current) / slope
            from datetime import timedelta
            try:
                if hours_to_90 > 0 and hours_to_90 < 876000:
                    days_to_90 = hours_to_90 / 24
                    eta_90 = datetime.now() + timedelta(hours=min(hours_to_90, 876000))
                    result["days_to_90"] = round(days_to_90, 1)
                    result["eta_90"] = eta_90.strftime("%Y-%m-%d")
                if hours_to_95 > 0 and hours_to_95 < 876000:
                    days_to_95 = hours_to_95 / 24
                    eta_95 = datetime.now() + timedelta(hours=min(hours_to_95, 876000))
                    result["days_to_95"] = round(days_to_95, 1)
                    result["eta_95"] = eta_95.strftime("%Y-%m-%d")
            except (OverflowError, ValueError):
                result["days_to_90"] = ">100年"
                result["trend"] = "very_slow_growth"
        else:
            result["trend"] = "stable_or_decreasing"

        return jsonify(result)

    @app.route("/api/health")
    def api_health():
        """API: OpsAgent 自身健康状态"""
        import psutil as _psutil
        agent_proc = None
        web_proc = None
        for proc in _psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info.get('cmdline') or [])
                if 'src.main' in cmdline and 'python' in cmdline:
                    agent_proc = proc
                elif 'src.web.run' in cmdline and 'python' in cmdline:
                    web_proc = proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        def proc_info(proc):
            if not proc:
                return {"running": False}
            try:
                mem = proc.memory_info()
                return {
                    "running": True,
                    "pid": proc.pid,
                    "memory_mb": round(mem.rss / 1024 / 1024, 1),
                    "cpu_percent": proc.cpu_percent(interval=0.1),
                    "uptime_seconds": round(time.time() - proc.create_time(), 0),
                }
            except Exception:
                return {"running": True, "pid": proc.pid}

        return jsonify({
            "agent": proc_info(agent_proc),
            "web": proc_info(web_proc),
            "system": {
                "cpu_percent": psutil.cpu_percent(interval=0.3),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent,
            },
            "timestamp": datetime.now().isoformat(),
        })

    @app.route("/api/metrics")
    def api_metrics():
        """API: 实时系统指标"""
        return jsonify(_get_system_metrics())

    @app.route("/api/metrics/history")
    def api_metrics_history():
        """API: 指标历史数据"""
        hours = request.args.get("hours", 24, type=int)
        if not DB_PATH.exists():
            return jsonify([])
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        since = time.time() - hours * 3600
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, cpu_percent, memory_percent, disk_percent,
                   load_1m, load_5m, load_15m
            FROM metrics_history WHERE timestamp > ?
            ORDER BY timestamp ASC LIMIT 500
        """, (since,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify(rows)

    @app.route("/api/incidents")
    def api_incidents():
        """API: 告警列表"""
        limit = request.args.get("limit", 50, type=int)
        return jsonify(_get_recent_incidents(limit=limit))

    @app.route("/api/stats")
    def api_stats():
        """API: 统计数据"""
        return jsonify(_get_memory_stats())

    return app


# ========== 数据采集函数 ==========


def _get_server_name() -> str:
    """获取服务器名称"""
    cfg = _load_config()
    return cfg.get("server", {}).get("name", "unknown")


def _load_config() -> dict:
    """加载配置文件"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _get_system_metrics() -> dict:
    """获取当前系统指标"""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        try:
            load_1m, load_5m, load_15m = psutil.getloadavg()
        except (OSError, AttributeError):
            load_1m = load_5m = load_15m = 0.0

        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        mins = int((uptime_seconds % 3600) // 60)

        net = psutil.net_io_counters()

        return {
            "cpu_percent": cpu_percent,
            "cpu_count": psutil.cpu_count(logical=True),
            "memory_percent": mem.percent,
            "memory_used_mb": round(mem.used / (1024 * 1024), 1),
            "memory_total_mb": round(mem.total / (1024 * 1024), 1),
            "memory_used_gb": round(mem.used / (1024 ** 3), 2),
            "memory_total_gb": round(mem.total / (1024 ** 3), 2),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024 ** 3), 1),
            "disk_total_gb": round(disk.total / (1024 ** 3), 1),
            "load_1m": round(load_1m, 2),
            "load_5m": round(load_5m, 2),
            "load_15m": round(load_15m, 2),
            "uptime": f"{days}天 {hours}小时 {mins}分钟",
            "net_sent_gb": round(net.bytes_sent / (1024 ** 3), 2),
            "net_recv_gb": round(net.bytes_recv / (1024 ** 3), 2),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        logger.error("获取系统指标失败: %s", e)
        return {}


def _get_service_status() -> list:
    """获取监控服务状态"""
    cfg = _load_config()
    services = cfg.get("services", {}).get("watch", [])
    results = []
    for svc in services:
        name = svc.get("name", "unknown")
        process_name = svc.get("process", name)
        running = any(
            process_name in p.info["name"]
            for p in psutil.process_iter(["name"])
        )
        results.append({"name": name, "process": process_name, "running": running})
    return results


def _get_docker_status() -> list:
    """获取 Docker 容器状态"""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return []
        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                containers.append({
                    "name": parts[0],
                    "status": parts[1],
                    "image": parts[2],
                    "running": "Up" in parts[1],
                })
        return containers
    except Exception:
        return []


def _get_recent_incidents(limit: int = 10) -> list:
    """获取最近的告警事件"""
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, issue_id, issue_type, severity, title, description,
                      resolved, created_at
               FROM incidents
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
        incidents = []
        for row in rows:
            ts = row["created_at"]
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            incidents.append({
                "id": row["id"],
                "issue_id": row["issue_id"],
                "issue_type": row["issue_type"],
                "severity": row["severity"],
                "title": row["title"],
                "description": row["description"],
                "resolved": bool(row["resolved"]),
                "created_at": ts,
            })
        return incidents
    except Exception as e:
        logger.error("查询告警失败: %s", e)
        return []


def _get_incidents_paginated(offset: int, limit: int) -> tuple:
    """分页查询告警"""
    if not DB_PATH.exists():
        return [], 0
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM incidents")
        total = cursor.fetchone()[0]

        cursor.execute(
            """SELECT id, issue_id, issue_type, severity, title, description,
                      resolved, created_at
               FROM incidents
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        rows = cursor.fetchall()
        conn.close()

        incidents = []
        for row in rows:
            ts = row["created_at"]
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            incidents.append({
                "id": row["id"],
                "issue_id": row["issue_id"],
                "issue_type": row["issue_type"],
                "severity": row["severity"],
                "title": row["title"],
                "description": row["description"],
                "resolved": bool(row["resolved"]),
                "created_at": ts,
            })
        return incidents, total
    except Exception as e:
        logger.error("分页查询告警失败: %s", e)
        return [], 0


def _get_memory_stats() -> dict:
    """获取记忆存储统计"""
    if not DB_PATH.exists():
        return {"total_incidents": 0, "resolved_count": 0, "resolution_rate": 0}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM incidents")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM incidents WHERE resolved = 1")
        resolved = cursor.fetchone()[0]
        cursor.execute(
            """SELECT severity, COUNT(*) FROM incidents GROUP BY severity"""
        )
        by_severity = dict(cursor.fetchall())
        cursor.execute(
            """SELECT issue_type, COUNT(*) FROM incidents GROUP BY issue_type"""
        )
        by_type = dict(cursor.fetchall())
        conn.close()
        return {
            "total_incidents": total,
            "resolved_count": resolved,
            "resolution_rate": round(resolved / total * 100, 1) if total > 0 else 0,
            "by_severity": by_severity,
            "by_type": by_type,
        }
    except Exception as e:
        logger.error("获取统计失败: %s", e)
        return {}


def _get_report_files() -> list:
    """获取报告文件列表"""
    if not REPORTS_DIR.exists():
        return []
    files = sorted(REPORTS_DIR.glob("inspection_*.html"), reverse=True)
    reports = []
    for f in files:
        size_kb = f.stat().st_size / 1024
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        reports.append({
            "filename": f.name,
            "size_kb": round(size_kb, 1),
            "created_at": mtime,
        })
    return reports


def main():
    """Web UI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="OpsAgent Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    app = create_app()
    print(f"🚀 OpsAgent Web UI 启动: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
