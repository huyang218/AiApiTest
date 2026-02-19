#!/bin/bash

# AI API 测试平台停止脚本

cd "$(dirname "$0")"

if [ -f "app.pid" ]; then
    PID=$(cat app.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo ">>> 停止应用 (PID: $PID)..."
        kill $PID
        rm -f app.pid
        echo ">>> 应用已停止"
    else
        echo ">>> 应用未在运行"
        rm -f app.pid
    fi
else
    echo ">>> 未找到 PID 文件，应用可能未运行"
    
    # 尝试查找并停止进程
    PID=$(pgrep -f "python3 app.py")
    if [ -n "$PID" ]; then
        echo ">>> 找到进程 (PID: $PID)，正在停止..."
        kill $PID
        echo ">>> 应用已停止"
    fi
fi
