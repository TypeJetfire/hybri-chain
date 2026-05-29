#!/bin/bash
# 简化演示脚本：仅运行策略引擎生成配置

set -e

OUTPUT_DIR="demo_output"
NODES_FILE="tests/test_nodes.yml"
POLICIES_FILE="tests/policies.yml"

# 清理旧的输出
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# 运行策略引擎生成配置
python3 main.py "$NODES_FILE" "$POLICIES_FILE" -o "$OUTPUT_DIR"

echo "配置已生成到: $OUTPUT_DIR/"

