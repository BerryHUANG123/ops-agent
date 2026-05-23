#!/bin/bash
# OpsAgent 安装脚本：创建 venv、安装依赖、初始化目录
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================="
echo "  OpsAgent 安装脚本"
echo "========================================="
echo "项目目录: $PROJECT_DIR"
echo ""

# 检查 Python 版本
PYTHON_CMD=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "❌ 未找到 Python 3.10+，请先安装"
    exit 1
fi

echo "✅ Python: $($PYTHON_CMD --version)"

# 创建虚拟环境
VENV_DIR="$PROJECT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建虚拟环境..."
    $PYTHON_CMD -m venv "$VENV_DIR"
    echo "✅ 虚拟环境已创建: $VENV_DIR"
else
    echo "✅ 虚拟环境已存在: $VENV_DIR"
fi

# 激活虚拟环境并安装依赖
echo "📥 安装依赖..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$PROJECT_DIR/requirements.txt" -q
echo "✅ 依赖安装完成"

# 创建必要目录
echo "📁 创建数据目录..."
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/reports"
echo "✅ 目录创建完成"

# 验证安装
echo ""
echo "🔍 验证安装..."
cd "$PROJECT_DIR"
python -c "
import psutil
import jinja2
import yaml
print('  psutil:', psutil.__version__)
print('  jinja2:', jinja2.__version__)
print('  pyyaml:', yaml.__version__)
print('✅ 所有依赖验证通过')
"

echo ""
echo "========================================="
echo "  ✅ 安装完成！"
echo "========================================="
echo ""
echo "运行方式:"
echo "  cd $PROJECT_DIR"
echo "  source venv/bin/activate"
echo "  python -m src.main              # 持续运行"
echo "  python -m src.main --once        # 单次检查"
echo "  python -m src.main --dry-run     # 演练模式"
echo ""
echo "运行测试:"
echo "  cd $PROJECT_DIR"
echo "  python -m pytest tests/ -v"
echo ""
