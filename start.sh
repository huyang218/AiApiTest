#!/bin/bash

# AI API 测试平台启动脚本（后台运行）

cd "$(dirname "$0")"

# 检查是否已在运行
if [ -f "app.pid" ]; then
    PID=$(cat app.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo ">>> 应用已在运行 (PID: $PID)"
        echo ">>> 如需重启，请先运行: ./stop.sh"
        exit 1
    fi
fi

# 检查 python3-venv 是否安装
if ! python3 -m venv --help > /dev/null 2>&1; then
    echo ">>> 需要安装 python3-venv，请运行："
    echo "    sudo apt update && sudo apt install python3-venv python3-full -y"
    exit 1
fi

# 检查虚拟环境是否存在
if [ ! -d "venv" ]; then
    echo ">>> 首次运行，创建虚拟环境..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo ">>> 虚拟环境创建失败"
        exit 1
    fi
    echo ">>> 虚拟环境创建成功"
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo ">>> 检查并安装依赖..."
pip install -r requirements.txt -q

# 后台启动应用
echo ">>> 后台启动应用..."
nohup python3 app.py > app.log 2>&1 &
echo $! > app.pid

sleep 2

# 检查是否启动成功
if ps -p $(cat app.pid) > /dev/null 2>&1; then
    echo ""
    echo "==========================================="
    echo "  AI API 测试平台已启动"
    echo "  访问地址: http://0.0.0.0:5001"
    echo "  默认密钥: admin123"
    echo "  进程 PID: $(cat app.pid)"
    echo ""
    echo "  查看日志: tail -f app.log"
    echo "  停止服务: ./stop.sh"
    echo "==========================================="
else
    echo ">>> 启动失败，查看日志: cat app.log"
    exit 1
fi
