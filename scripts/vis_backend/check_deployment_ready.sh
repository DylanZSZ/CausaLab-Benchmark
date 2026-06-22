#!/bin/bash

# Local visualization smoke-check script

echo "========================================"
echo "  Visualization readiness check"
echo "========================================"
echo ""

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

errors=0
PYTHON_BIN="${PYTHON:-python}"

# 检查必需文件
echo "✓ 检查必需文件..."
files=("requirements.txt" "visualization_server.py" "visualize_causal_graphs_dsl.py")
for file in "${files[@]}"; do
    if [ ! -f "$file" ]; then
        echo "  ✗ 缺少文件: $file"
        ((errors++))
    else
        echo "  ✓ $file"
    fi
done

# 检查前端目录
if [ -d "../vis_frontend" ]; then
    echo "  ✓ vis_frontend 目录存在"
else
    echo "  ✗ vis_frontend 目录不存在"
    ((errors++))
fi

echo ""

sample_dir="../../examples/sample_runs/react_simple-mem/obs_Causal_gpt-5-mini/4nodes/20260223-2134_dsl_right/4nodes_0_53calls/seed_1"
if [ -f "$sample_dir/graph_config.json" ] && ls "$sample_dir"/*_tracking_simple.jsonl >/dev/null 2>&1; then
    echo "  ✓ sample visualization run exists"
else
    echo "  ✗ sample visualization run is missing"
    ((errors++))
fi

echo ""

# 检查 Python 依赖
echo "✓ 检查 Python 依赖..."
if "$PYTHON_BIN" -c "import flask" 2>/dev/null; then
    flask_version=$("$PYTHON_BIN" -c "import importlib.metadata as m; print(m.version('Flask'))")
    echo "  ✓ Flask $flask_version"
else
    echo "  ✗ Flask 未安装"
    ((errors++))
fi

if "$PYTHON_BIN" -c "import flask_cors" 2>/dev/null; then
    flask_cors_version=$("$PYTHON_BIN" -c "import importlib.metadata as m; print(m.version('flask-cors'))")
    echo "  ✓ flask-cors $flask_cors_version"
else
    echo "  ✗ flask-cors 未安装"
    ((errors++))
fi

echo ""

# 显示结果
if [ $errors -eq 0 ]; then
    echo "========================================"
    echo "  ✓ Ready"
    echo "========================================"
    echo ""
    echo "Run locally with:"
    echo "  python scripts/vis_backend/visualization_server.py"
    echo ""
else
    echo "========================================"
    echo "  ✗ 发现 $errors 个问题"
    echo "========================================"
    echo ""
    echo "Install dependencies from the repository root with:"
    echo "  python -m pip install -e ."
    echo ""
    echo "Or install only the visualization backend dependencies with:"
    echo "  python -m pip install -r scripts/vis_backend/requirements.txt"
    echo ""
    echo "Then rerun:"
    echo "  bash scripts/vis_backend/check_deployment_ready.sh"
    echo "  python scripts/vis_backend/visualization_server.py"
    exit 1
fi
