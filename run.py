"""
run.py — 一键启动脚本
运行方式：python run.py
会自动打开浏览器 http://localhost:7860
"""

import os

# 排除本地地址不走系统代理
# 如果系统配置了代理，会拦截 Gradio 对 127.0.0.1 的自检请求，导致 503 启动失败
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

from app.ui.gradio_app import launch

if __name__ == "__main__":
    launch()
