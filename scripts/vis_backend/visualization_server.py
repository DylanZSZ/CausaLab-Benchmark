#!/usr/bin/env python3
"""
Flask 服务器用于提供因果图可视化服务
"""

import json
from pathlib import Path
import sys
import os

try:
    from flask import Flask, jsonify, send_from_directory, request
    from flask_cors import CORS
except ModuleNotFoundError as exc:
    missing = exc.name or "required package"
    print(
        f"Missing Python dependency: {missing}\n"
        "Install the visualization backend dependencies from the repository root:\n"
        "  python -m pip install -r scripts/vis_backend/requirements.txt\n"
        "Then run:\n"
        "  python scripts/vis_backend/visualization_server.py",
        file=sys.stderr,
    )
    sys.exit(1)

# 导入可视化脚本
from visualize_causal_graphs_dsl import (
    generate_visualization_data,
    find_all_valid_folders
)

app = Flask(__name__, static_folder='../vis_frontend', static_url_path='')
CORS(app)

# Global configuration. By default the server opens the small anonymized sample
# run shipped with this repository; set BASE_OUTPUT_DIR to inspect new runs.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_OUTPUT_DIR = REPO_ROOT / 'examples' / 'sample_runs' / 'react_simple-mem'
BASE_OUTPUT_DIR = os.environ.get('BASE_OUTPUT_DIR', str(DEFAULT_BASE_OUTPUT_DIR))



@app.route('/')
def index():
    """提供主页"""
    return send_from_directory('../vis_frontend', 'index.html')


@app.route('/api/folders')
def list_folders():
    """列出所有可用的可视化文件夹"""
    try:
        folders = find_all_valid_folders(BASE_OUTPUT_DIR)
        return jsonify({
            'success': True,
            'folders': folders,
            'count': len(folders)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/visualize', methods=['POST'])
def visualize():
    """生成指定文件夹的可视化数据"""
    try:
        data = request.json
        tracking_file = data.get('tracking_file')
        config_file = data.get('config_file')
        
        if not tracking_file or not config_file:
            return jsonify({
                'success': False,
                'error': 'Missing tracking_file or config_file'
            }), 400
        
        # 生成可视化数据
        vis_data = generate_visualization_data(
            tracking_file,
            config_file,
            '/tmp/temp_vis_data.json'  # 临时文件
        )
        
        return jsonify({
            'success': True,
            'data': vis_data
        })
    except Exception as e:
        import traceback
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/config')
def get_config():
    """获取服务器配置"""
    return jsonify({
        'base_output_dir': BASE_OUTPUT_DIR
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_ENV') != 'production'
    
    print("Starting visualization server...")
    print(f"Base output directory: {BASE_OUTPUT_DIR}")
    print(f"Server will be available at: http://0.0.0.0:{port}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
