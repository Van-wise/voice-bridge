# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - 快速启动脚本
支持自动重启功能，启动成功后自动打开浏览器
"""

import sys
import os
import time
import socket
import webbrowser
import threading

# 添加 backend 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def get_lan_ip():
    """获取局域网IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def open_browser(url):
    """在新线程中打开浏览器"""
    time.sleep(0.5)  # 等待服务完全启动
    webbrowser.open(url)

def main():
    from main import run
    from shared.config import get_settings
    
    settings = get_settings()
    lan_ip = get_lan_ip()
    local_url = f"http://127.0.0.1:{settings.port}"
    
    print("正在启动后端服务...")
    print("正在启动前端服务...")
    
    # 启动浏览器
    threading.Thread(target=open_browser, args=(local_url,), daemon=True).start()
    
    try:
        run()
    except KeyboardInterrupt:
        print("\n✅ 服务已停止")
    except Exception as e:
        print(f"❌ 服务异常: {e}")
        print("5秒后重启...")
        time.sleep(5)

if __name__ == "__main__":
    main()
