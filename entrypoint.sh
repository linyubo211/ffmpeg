#!/bin/bash
echo "=== IPTV 本地测速容器已启动 ==="
# 如果有传入参数，则执行测试脚本，否则默认运行
python test_script.py "$@"
