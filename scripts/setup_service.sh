#!/bin/bash
# OpsAgent systemd user service 设置脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="ops-agent"
CURRENT_USER="$(whoami)"

echo "========================================="
echo "  OpsAgent Systemd Service 设置"
echo "========================================="
echo "用户: $CURRENT_USER"
echo "项目: $PROJECT_DIR"
echo ""

# 确保虚拟环境存在
if [ ! -d "$PROJECT_DIR/venv" ]; then
    echo "❌ 虚拟环境不存在，请先运行 install.sh"
    exit 1
fi

# 创建 user service 目录
SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"

# 生成 service 文件
SERVICE_FILE="$SERVICE_DIR/${SERVICE_NAME}.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=OpsAgent 轻量级运维监控 Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/venv/bin/python -m src.main
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

# 资源限制（J1900 低功耗友好）
MemoryMax=256M
CPUQuota=50%

[Install]
WantedBy=default.target
EOF

echo "✅ Service 文件已创建: $SERVICE_FILE"

# 检查 lingering（允许非登录时运行服务）
if [ "$(loginctl show-user "$CURRENT_USER" 2>/dev/null | grep -c 'Linger=yes')" -eq 0 ]; then
    echo "⏳ 启用 lingering（允许非登录时运行）..."
    sudo loginctl enable-linger "$CURRENT_USER" 2>/dev/null || {
        echo "⚠️  无法启用 lingering（需要 sudo），service 可能在注销后停止"
    }
fi

# 启用并启动服务
echo "🔄 重载 systemd 配置..."
systemctl --user daemon-reload

echo "🔛 启用开机自启..."
systemctl --user enable "${SERVICE_NAME}.service"

echo "🚀 启动服务..."
systemctl --user start "${SERVICE_NAME}.service"

# 检查状态
sleep 2
if systemctl --user is-active --quiet "${SERVICE_NAME}.service"; then
    echo ""
    echo "========================================="
    echo "  ✅ OpsAgent 服务已启动！"
    echo "========================================="
    echo ""
    echo "常用命令:"
    echo "  systemctl --user status ${SERVICE_NAME}    # 查看状态"
    echo "  systemctl --user stop ${SERVICE_NAME}      # 停止"
    echo "  systemctl --user restart ${SERVICE_NAME}   # 重启"
    echo "  journalctl --user -u ${SERVICE_NAME} -f    # 查看日志"
    echo ""
else
    echo ""
    echo "⚠️  服务可能未正常启动，请检查日志:"
    echo "  journalctl --user -u ${SERVICE_NAME} -n 50"
    echo ""
fi
