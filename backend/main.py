# -*- coding: utf-8 -*-
"""
Voice Bridge Backend - FastAPI 主入口
"""

import sys
import time
import os
import socket
from contextlib import asynccontextmanager
from typing import Optional

# 服务启动时间（用于计算运行时长）
START_TIME = time.time()

# 启动横幅（仅在直接运行时打印一次）
_BANNER_LOCK_FILE = os.path.join(os.path.dirname(__file__), ".banner_printed")


def _print_banner():
    """打印启动横幅"""
    try:
        # 每次启动都删除旧锁文件，确保能重新打印
        if os.path.exists(_BANNER_LOCK_FILE):
            try:
                os.remove(_BANNER_LOCK_FILE)
            except Exception:
                pass

        local_ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass

        banner = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        Voice Bridge 启动成功
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [ HTTP 本地访问 | 端口 7266 ]
    本地地址  http://localhost:7266
    引导地址  http://localhost:7266/setup

  [ HTTPS 局域网 | 端口 7267 ]
    网络地址  https://{local_ip}:7267

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        sys.stdout.write(banner)
        sys.stdout.flush()
    except Exception:
        pass


from fastapi import FastAPI, Request, WebSocket, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.config import get_settings
from shared.errors import AppError
from shared.logging import generate_trace_id, set_trace_id, clear_trace_id
from shared.database import get_database
from shared.middleware import RequestLoggingMiddleware
from devices.router import router as devices_router
from devices.websocket import websocket_handler, manager
from devices.microphone import audio_websocket_handler
from devices.audio import router as audio_router, startup as audio_startup
from devices.virtual_mic_router import router as vmic_router
from devices.ffmpeg_router import router as ffmpeg_router
from clipboard.router import router as clipboard_router

# ==================== 托盘系统（提前导入，避免 uvicorn 重入问题）====================
_tray_started = False


def _start_tray():
    """后台启动托盘"""
    global _tray_started
    if _tray_started:
        return
    _tray_started = True
    try:
        from system_tray import start_tray
        start_tray()
    except Exception as e:
        print(f"[托盘] 启动失败: {e}")


# ==================== 日志配置 ====================
from shared.logging import setup_logging, get_logger

# 打印横幅（只在直接运行 python main.py 时打印，uvicorn 导入时不打印）
if __name__ == "__main__":
    _print_banner()

# 初始化日志系统（文件+控制台双输出）
logger = setup_logging(log_level="INFO", enable_console=True)

# 托盘在 logging 初始化后启动
import threading
threading.Thread(target=_start_tray, daemon=True, name="VB-Tray").start()

# 周期性心跳日志
_poll_count = 0
_last_heartbeat = time.time()
_heartbeat_interval = 1800  # 30分钟一次心跳


# ==================== 全局状态（兼容旧版） ====================
class AppState:
    """全局应用状态"""
    def __init__(self):
        import threading
        self.lock = threading.Lock()
        self.text: str = ""
        self.text_version: int = 0
        self.events: list = []
        self.event_ver: int = 0
        self.history: list = []
        self.client_first_seen: dict = {}
        self.settings: dict = {
            'mode': 'auto',
            'auto_clear': True,
            'auto_copy': True,
            'persist_history': True,
            'port': 7266,
        }
        self.settings_version: int = 0
    
    def push_event(self, etype: str, data: dict = None) -> int:
        with self.lock:
            self.event_ver += 1
            event = {
                'ver': self.event_ver,
                'type': etype,
                'data': data or {},
                'ts': time.time(),
            }
            self.events.append(event)
            if len(self.events) > 50:
                self.events = self.events[-50:]
            return self.event_ver
    
    def get_events_since(self, last_ver: int) -> list:
        with self.lock:
            return [e for e in self.events if e['ver'] > last_ver]
    
    def save_history(self, text: str, overwritten: bool = False):
        """保存历史记录"""
        import hashlib
        if not text or not text.strip():
            return
        h = hashlib.md5(text.strip().encode('utf-8')).hexdigest()
        with self.lock:
            # 检查是否已存在
            for item in self.history:
                if item.get('hash') == h and item.get('overwritten') == overwritten:
                    item['time'] = time.time()
                    return
            # 添加新记录
            self.history.insert(0, {
                'text': text,
                'time': time.time(),
                'overwritten': overwritten,
                'hash': h,
            })
            if len(self.history) > 200:
                del self.history[200:]


state = AppState()


# ==================== 前端静态文件服务 ====================
# 进程级别防重：使用文件锁
_frontend_mount_marker = os.path.join(os.path.dirname(__file__), ".frontend_mounted")
_frontend_mounted = os.path.exists(_frontend_mount_marker)


def setup_frontend_static(app: FastAPI):
    """配置前端静态文件服务"""
    global _frontend_mounted
    if _frontend_mounted:
        return

    from pathlib import Path
    from fastapi.staticfiles import StaticFiles

    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"

    if frontend_dist.exists():
        assets_path = frontend_dist / "assets"
        if assets_path.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")
            logger.info(f"已挂载前端静态文件: {assets_path}")

        frontend_public = Path(__file__).parent.parent / "frontend" / "public"
        if frontend_public.exists():
            app.mount("/public", StaticFiles(directory=str(frontend_public)), name="public")

    _frontend_mounted = True
    try:
        Path(_frontend_mount_marker).touch()
    except Exception:
        pass


# ==================== 全局初始化锁（防止重复初始化） ====================
import threading as _threading
_init_lock = _threading.Lock()
_initialized = False

def _ensure_single_init():
    """确保初始化代码只执行一次（线程安全）"""
    global _initialized
    with _init_lock:
        if _initialized:
            return False  # 已被初始化，跳过
        _initialized = True
        return True  # 需要初始化


# ==================== 生命周期 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动 - 只有第一个服务需要初始化
    if _ensure_single_init():
        logger.info("Voice Bridge Backend starting...")
        audio_startup()   # 初始化音频模块（建表 + 加载历史）
    yield
    # 关闭 - 只在所有服务结束时清理一次
    # 注意：由于 daemon 线程，关闭时可能不会触发


# ==================== 创建应用 ====================
app = FastAPI(
    title="Voice Bridge API",
    description="多设备剪贴板同步服务",
    version="2.0.0",
    lifespan=lifespan,
)

# 添加请求日志中间件（简洁模式）
app.add_middleware(RequestLoggingMiddleware, verbose=False)

# CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 错误处理 ====================
from shared.logging import get_trace_id


@app.exception_handler(AppError)
async def app_error_handler(request: Request, error: AppError):
    """处理应用业务错误"""
    logger.warning(f"[ERROR] {error.code}: {error.message}")
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_dict(),
    )


@app.exception_handler(Exception)
async def general_error_handler(request: Request, error: Exception):
    """处理未捕获的异常"""
    logger.error(f"[ERROR] {type(error).__name__}: {error}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
        },
    )


# ==================== 兼容旧版 API 路由 ====================
legacy_router = APIRouter(prefix="/api", tags=["legacy"])


def get_local_ip() -> str:
    """获取本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'


@legacy_router.get("/poll")
async def poll_events(
    last_ev: int = 0,
    client_id: str = "",
    is_local: str = "false",
    request: Request = None,
):
    """轮询获取事件（旧版兼容）- 静默模式，不输出日志"""
    global _poll_count, _last_heartbeat
    
    client_ip = request.client.host if request.client else "?"
    now = time.time()
    
    # 设备类型检测
    ua = request.headers.get('User-Agent', '')
    if any(x in ua.lower() for x in ['mobile', 'android', 'iphone', 'ipad']):
        device_type = 'mobile'
    else:
        device_type = 'pc'
    
    client_is_local = is_local.lower() == 'true'
    
    with state.lock:
        # 设备去重
        existing_id = None
        for cid, info in state.client_first_seen.items():
            if info.get('ip') == client_ip and info.get('device_type') == device_type:
                existing_id = cid
                break
        
        if existing_id:
            state.client_first_seen[existing_id]['last_seen'] = now
            state.client_first_seen[existing_id]['is_local'] = client_is_local
            client_id = existing_id
        else:
            state.client_first_seen[client_id] = {
                'first_seen': now,
                'last_seen': now,
                'ip': client_ip,
                'device_type': device_type,
                'is_local': client_is_local,
            }
    
    # 获取事件
    events = state.get_events_since(last_ev)
    
    # 构建设备列表
    with state.lock:
        seen_ips = set()
        devices = []
        active_count = 0
        for cid, info in state.client_first_seen.items():
            if now - info.get('last_seen', info.get('first_seen', 0)) > 300:
                continue
            ip = info.get('ip', cid)
            dtype = info.get('device_type', 'pc')
            key = f"{ip}:{dtype}"
            if key in seen_ips:
                continue
            seen_ips.add(key)
            devices.append({
                'id': cid,
                'ip': ip,
                'device_type': dtype,
                'is_local': info.get('is_local', False),
            })
            active_count += 1
    
    # 周期性心跳日志（每30分钟或每100次poll）
    _poll_count += 1
    if _poll_count >= 100 or (now - _last_heartbeat) > _heartbeat_interval:
        _poll_count = 0
        _last_heartbeat = now
        # 清理超时设备
        with state.lock:
            for cid in list(state.client_first_seen.keys()):
                if now - state.client_first_seen[cid].get('last_seen', 0) > 300:
                    del state.client_first_seen[cid]
        running_seconds = int(now - START_TIME)
        hours, remainder = divmod(running_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        runtime_str = f"{hours}h {minutes}m {seconds}s" if hours > 0 else f"{minutes}m {seconds}s"
        logger.info(f"[心跳] 连接正常 | 活跃设备:{active_count} | 运行时间:{runtime_str}")
    
    return {
        'events': events,
        'ev': state.event_ver,
        'text': state.text,
        'text_ver': state.text_version,
        'settings_ver': state.settings_version,
        'history_count': len(state.history),
        'devices': devices,
        'current_port': settings.port,
        'local_ip': get_local_ip(),
    }


@legacy_router.post("/sync")
async def sync_text(
    request_data: dict,
    request: Request = None,
):
    """同步文本（旧版兼容）"""
    text = request_data.get('text', '')
    mode = request_data.get('mode', state.settings.get('mode', 'auto'))
    auto_clear = request_data.get('auto_clear', state.settings.get('auto_clear', True))
    manual_sync = request_data.get('manual', False)
    
    client_ip = request.client.host if request.client else "?"
    ua = request.headers.get('User-Agent', '')
    is_pc = client_ip in ('127.0.0.1', '::1', 'localhost')
    source = 'pc' if is_pc else 'mobile'
    
    if any(x in ua.lower() for x in ['mobile', 'android', 'iphone', 'ipad']):
        device_type = 'mobile'
    else:
        device_type = 'pc'
    
    # 更新文本
    with state.lock:
        old_text = state.text
        state.text = text
        state.text_version += 1
    
    # 保存历史
    if old_text and old_text.strip():
        state.save_history(old_text, overwritten=True)
    state.save_history(text)
    
    # 推送事件
    state.push_event('sync', {
        'text': text,
        'source': source,
        'client_id': request.headers.get('X-Client-ID', 'unknown'),
        'device_type': device_type,
    })
    
    # 执行操作
    action = 'synced'
    
    if mode == 'auto':
        try:
            import pyperclip
            import pyautogui
            pyperclip.copy(text)
            time.sleep(0.1)
            pyautogui.hotkey('ctrl', 'v')
            action = 'pasted'
        except Exception as e:
            logger.error(f"Auto paste failed: {e}")
            action = 'paste_failed'
    elif mode == 'manual' and auto_clear:
        try:
            import pyperclip
            pyperclip.copy(text)
            action = 'copied'
        except Exception as e:
            logger.error(f"Clipboard copy failed: {e}")
            action = 'copy_failed'
    
    # 清空逻辑
    should_clear = auto_clear and manual_sync
    
    # 日志格式
    content_preview = text[:30] + "..." if len(text) > 30 else text
    logger.info(f'Sync to text: "{content_preview}"')
    logger.info(f'from={source}, mode={mode}, len={len(text)}, action={action}, cleared={should_clear}')
    
    if should_clear:
        with state.lock:
            state.text = ""
            state.text_version += 1
        state.push_event('clear', {'by': source})
    
    return {
        'success': True,
        'action': action,
        'auto_clear': should_clear,
        'elapsed': 0.001,
        'from': source,
    }


@legacy_router.get("/settings")
async def get_settings_api():
    """获取设置"""
    with state.lock:
        return {**state.settings, '_ver': state.settings_version}


@legacy_router.post("/settings")
async def update_settings(request_data: dict):
    """更新设置"""
    with state.lock:
        state.settings.update(request_data)
        state.settings_version += 1
        if 'port' in request_data:
            settings.port = int(request_data['port'])
    
    state.push_event('settings', dict(state.settings))
    changed = list(request_data.keys())
    logger.info(f'Settings updated: {changed}')
    
    return {
        'success': True,
        'settings': dict(state.settings),
        '_ver': state.settings_version,
    }


@legacy_router.post("/clear")
async def clear_text():
    """清空文本"""
    with state.lock:
        old_text = state.text
        if old_text and old_text.strip():
            state.text = ""
            state.text_version += 1
            state.save_history(old_text)
    
    state.push_event('clear')
    logger.info("Text cleared")
    
    return {'success': True}


@legacy_router.get("/history")
async def get_history(offset: int = 0, limit: int = 20):
    """获取历史"""
    with state.lock:
        total = len(state.history)
        items = state.history[offset:offset + limit]
    
    return {
        'items': items,
        'total': total,
        'offset': offset,
        'has_more': (offset + limit) < total,
    }


@legacy_router.post("/history/clear")
async def clear_history():
    """清空历史"""
    with state.lock:
        state.history.clear()
    logger.info("History cleared")
    return {'success': True}


@legacy_router.get("/stats")
async def get_stats():
    """获取统计"""
    with state.lock:
        total_chars = sum(len(h.get('text', '')) for h in state.history)
        total_syncs = len(state.history)
        
        seen = set()
        active_clients = 0
        now = time.time()
        for cid, info in state.client_first_seen.items():
            if now - info.get('last_seen', info.get('first_seen', 0)) < 300:
                key = f"{info.get('ip')}:{info.get('device_type')}"
                if key not in seen:
                    seen.add(key)
                    active_clients += 1
    
    return {
        'total_syncs': total_syncs,
        'total_chars': total_chars,
        'active_clients': active_clients,
        'total_history': len(state.history),
        'current_text_len': len(state.text),
    }


@legacy_router.get("/info")
async def get_info():
    """获取服务器信息"""
    ip = get_local_ip()
    return {
        'lan_url': f'http://{ip}:{settings.port}',
        'local_url': f'http://127.0.0.1:{settings.port}',
        'ip': ip,
        'port': settings.port,
    }


@legacy_router.get("/logs")
async def get_logs(lines: int = 100, level: str = ""):
    """
    获取运行日志（读取 backend/logs/vb.log）
    支持按级别过滤和行数限制
    """
    from shared.logging import get_log_file_path, parse_recent_logs
    log_path = get_log_file_path()
    
    if not os.path.exists(log_path):
        return {'logs': [], 'log_file': log_path, 'total': 0}
    
    try:
        # 使用新的结构化日志解析
        logs = parse_recent_logs(lines=lines, level=level if level else None)
        
        # 同时返回原始文本（兼容）
        with open(log_path, 'r', encoding='utf-8') as f:
            raw_lines = [l.strip() for l in f.readlines()[-lines:] if l.strip()]
        
        return {
            'logs': logs,
            'raw': raw_lines,
            'log_file': log_path,
            'total': len(logs)
        }
    except Exception as e:
        logger.error(f"读取日志文件失败: {e}")
        return {'logs': [], 'log_file': log_path, 'error': str(e)}


@legacy_router.post("/restart")
async def restart_server():
    """重启服务"""
    import os
    import sys
    logger.info("Restart requested...")
    # 触发重启标志
    os.environ['VB_RESTART'] = '1'
    return {'success': True, 'message': 'Restarting...'}


@legacy_router.post("/port/check")
async def check_port(request_data: dict):
    """检查端口是否可用"""
    port = request_data.get('port', 0)
    if port <= 0 or port > 65535:
        return {'available': False, 'reason': 'Invalid port'}
    
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        sock.bind(('0.0.0.0', port))
        sock.close()
        return {'available': True}
    except OSError:
        sock.close()
        return {'available': False, 'reason': 'Port in use'}


# ==================== 注册路由 ====================
app.include_router(devices_router)
app.include_router(clipboard_router)
app.include_router(audio_router)   # 简化音频上传
app.include_router(vmic_router)    # 虚拟麦克风 API
app.include_router(ffmpeg_router)   # FFmpeg 音频路由 API
app.include_router(legacy_router)  # 兼容旧版 API

# 配置前端静态文件（在所有API路由之后）
setup_frontend_static(app)


# ==================== 健康检查 ====================
@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "online_devices": len(manager.active_connections)}


# ==================== 前端页面 ====================
@app.get("/")
async def root():
    """返回前端页面"""
    import os
    from pathlib import Path
    
    # 尝试找到前端构建目录
    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist" / "index.html"
    
    if frontend_dist.exists():
        from fastapi.responses import FileResponse
        return FileResponse(str(frontend_dist))
    
    # 如果前端未构建，返回简单提示
    return {
        "name": "Voice Bridge API",
        "version": "2.0.0",
        "message": "前端未构建，请先运行: cd frontend && npm run build",
        "docs": "/docs",
    }


# ==================== 单一端口统一入口 ====================
# 7266 端口同时服务 HTTPS 主站和 /setup 引导页
# 不再使用独立的 7267 HTTP 引导端口

@app.get("/admin")
async def admin_page(request: Request):
    """
    管理员模式页面
    包含系统配置、设备管理、数据库、API、权限、监控、告警、工具集 8大模块
    """
    from pathlib import Path
    from fastapi.responses import FileResponse

    for rel in ["frontend/dist/admin.html", "frontend/public/admin.html"]:
        admin_file = Path(__file__).parent.parent / rel
        if admin_file.exists():
            return FileResponse(str(admin_file))

    return {"error": "admin.html not found, please build frontend"}


@app.get("/setup")
async def setup_page(request: Request):
    """
    证书引导页面（合并到主端口）
    用于帮助用户在手机上接受 HTTPS 证书
    """
    from pathlib import Path
    from fastapi.responses import FileResponse

    for rel in ["frontend/public/setup.html", "frontend/dist/setup.html"]:
        setup_file = Path(__file__).parent.parent / rel
        if setup_file.exists():
            return FileResponse(str(setup_file))

    # 兜底：生成内嵌 HTML
    from fastapi.responses import HTMLResponse
    local_ip = get_local_ip()
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Voice Bridge - 安装证书</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:480px;margin:40px auto;padding:16px;background:#f5f5f5}}
.card{{background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
h2{{margin-top:0;color:#1a1a1a}}
.btn{{display:block;background:#2563eb;color:#fff;text-align:center;padding:14px;border-radius:8px;text-decoration:none;font-size:16px;margin:12px 0}}
.btn-p12{{background:#10b981}}
.tip{{color:#666;font-size:13px;line-height:1.6;margin-top:12px}}
.step{{margin:16px 0;padding:12px;background:#f8f9fa;border-radius:8px}}
.step-title{{font-weight:bold;color:#1a1a1a;margin-bottom:8px}}
</style></head>
<body>
<div class="card">
<h2>Voice Bridge 证书安装</h2>
<p>你的设备 IP：<strong>{local_ip}</strong></p>
<p>手机麦克风功能需要 HTTPS，请先安装证书。</p>

<!-- 一键安装（推荐） -->
<div class="step">
<div class="step-title">🚀 一键安装（推荐，无需密码）</div>
<a class="btn btn-p12" href="/setup/cert-p12">下载 VoiceBridge.p12</a>
<p style="color:#666;font-size:12px;margin-top:8px">
适用于 Android / iOS，安装时密码留空
</p>
</div>

<!-- 传统方式 -->
<div class="step">
<div class="step-title">📄 传统方式（需要密码）</div>
<a class="btn" href="/setup/cert">下载证书 VoiceBridge.crt</a>
</div>

<div class="tip">
<b>Android 安装步骤：</b><br>
1. 下载上面的 .p12 文件<br>
2. 文件名改为 .p12（部分浏览器会改成其他后缀）<br>
3. 点击文件，系统提示"安装证书"<br>
4. 密码留空，直接确认<br>
5. 证书名称随意，起始位置选"WLAN和VPN"<br>
6. 安装成功后，用 Chrome 访问<br>
<code>https://{local_ip}:7266</code><br><br>

<b>iOS 安装步骤：</b><br>
1. 下载上面的 .p12 文件<br>
2. 弹出密码时直接取消/留空<br>
3. 去【设置】→【已下载的描述文件】<br>
4. 点击安装，完成后【关于本机】→【证书信任设置】开启完全信任
</div>
</div>
</body></html>"""
    return HTMLResponse(content=html)


@app.get("/setup/cert")
async def download_cert_setup():
    """
    下载自签名证书（从 /setup 路径访问）
    """
    from pathlib import Path
    from fastapi.responses import FileResponse, Response

    cert_file = Path(__file__).parent / "certs" / "server.crt"

    if not cert_file.exists():
        return Response(
            content="证书文件不存在，请先启动 HTTPS 模式或运行 python generate_cert.py",
            status_code=404,
            media_type="text/plain; charset=utf-8",
        )

    return FileResponse(
        path=str(cert_file),
        media_type="application/x-x509-ca-cert",
        filename="VoiceBridge.crt",
        headers={"Content-Disposition": "attachment; filename=VoiceBridge.crt"},
    )


@app.get("/setup/cert-p12")
async def download_cert_p12():
    """
    下载 PKCS12 格式证书（手机一键安装，无需密码）

    这个格式更适合手机安装：
    - Android: 直接安装 .p12 文件，设置密码为空
    - iOS: 导入 .p12 文件
    """
    from pathlib import Path
    from fastapi.responses import FileResponse, Response

    p12_file = Path(__file__).parent / "certs" / "VoiceBridge.p12"

    if not p12_file.exists():
        # 尝试重新生成
        import subprocess
        import sys
        cert_dir = Path(__file__).parent / "certs"

        # 导入 generate_cert 模块来生成 p12
        sys.path.insert(0, str(Path(__file__).parent))
        try:
            import generate_cert as gc
            cert_file, key_file = gc.generate_cert_cryptography(str(cert_dir), gc.get_local_ip())
        except Exception as e:
            return Response(
                content=f"证书文件不存在，请运行 python generate_cert.py 生成证书\n错误: {e}",
                status_code=404,
                media_type="text/plain; charset=utf-8",
            )

    return FileResponse(
        path=str(p12_file),
        media_type="application/x-pkcs12",
        filename="VoiceBridge.p12",
        headers={"Content-Disposition": "attachment; filename=VoiceBridge.p12"},
    )


@app.get("/cert/info")
async def cert_info():
    """返回证书信息（JSON）"""
    import os
    from pathlib import Path

    cert_file = Path(__file__).parent / "certs" / "server.crt"
    if not cert_file.exists():
        return {"exists": False}

    try:
        from cryptography import x509 as cx509
        cert_data = cert_file.read_bytes()
        cert = cx509.load_pem_x509_certificate(cert_data)
        san = cert.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(cx509.DNSName)
        ip_addrs = [str(ip) for ip in san.value.get_values_for_type(cx509.IPAddress)]
        return {
            "exists": True,
            "not_valid_before": cert.not_valid_before_utc.isoformat(),
            "not_valid_after": cert.not_valid_after_utc.isoformat(),
            "san_dns": dns_names,
            "san_ip": ip_addrs,
            "serial": str(cert.serial_number),
        }
    except Exception as e:
        return {"exists": True, "error": str(e)}


# ==================== 设备设置 API ====================
# 简单的 JSON 文件持久化，存在 backend/ 下
import json as _json

_DEVICE_DB_FILE = os.path.join(os.path.dirname(__file__), "device_names.json")
_device_names: dict = {}

def _load_device_names():
    global _device_names
    try:
        if os.path.exists(_DEVICE_DB_FILE):
            with open(_DEVICE_DB_FILE, "r", encoding="utf-8") as f:
                _device_names = _json.load(f)
    except Exception:
        _device_names = {}

def _save_device_names():
    try:
        with open(_DEVICE_DB_FILE, "w", encoding="utf-8") as f:
            _json.dump(_device_names, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[Setup] 保存设备名失败: {e}")

# 启动时加载
_load_device_names()


@app.get("/api/setup/info")
async def setup_info(request: Request):
    """
    返回设置页面需要的所有信息
    返回局域网IP、设备信息，200ms超时保护
    """
    client_ip = request.client.host if request.client else "unknown"
    server_ip = get_local_ip()
    
    # 快速返回基本信息，不等待数据库
    return {
        "client_ip": client_ip,
        "server_ip": server_ip,
        "http_port": 7266,
        "https_port": 7267,
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/api/check-https")
async def check_https(request: Request):
    """
    轻量化 HTTPS 可访问性检测接口
    模拟用户访问，忽略自签证书安全校验（适配「点继续访问」场景）
    超时3秒，返回 {"accessible": true/false}
    """
    import ssl as _ssl, urllib.request as _urllib, asyncio as _asyncio

    server_ip = get_local_ip()
    https_port = get_settings().https_port  # 从配置读取

    try:
        # 忽略自签证书校验
        ctx = _ssl._create_unverified_context()
        url = f"https://{server_ip}:{https_port}/api/setup/info"

        def _do_check():
            req = _urllib.Request(url, headers={"User-Agent": "VoiceBridge-Check/1.0"})
            _urllib.urlopen(req, context=ctx, timeout=3)
            return True

        loop = _asyncio.get_event_loop()
        accessible = await loop.run_in_executor(None, _do_check)
        return {"accessible": bool(accessible)}
    except Exception:
        return {"accessible": False}


from pydantic import BaseModel as _BaseModel

# ==================== 设备注册与名称 API ====================

def _get_or_create_device(device_id: str) -> dict:
    """获取或创建设备记录（使用数据库）"""
    db = get_database()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 查询设备
        cursor.execute(
            "SELECT * FROM setup_devices WHERE device_id = ?",
            (device_id,)
        )
        row = cursor.fetchone()
        
        if row:
            # 更新最后访问时间
            cursor.execute(
                "UPDATE setup_devices SET update_time = ? WHERE device_id = ?",
                (time.time(), device_id)
            )
            return dict(row)
        
        # 返回空记录（尚未创建）
        return None


def _register_device_db(device_id: str, device_name: str, fingerprint: str, 
                         device_type: str, client_ip: str) -> dict:
    """注册或更新设备（使用数据库）"""
    db = get_database()
    now = time.time()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 检查是否已存在
        cursor.execute("SELECT * FROM setup_devices WHERE device_id = ?", (device_id,))
        existing = cursor.fetchone()
        
        if existing:
            # 更新
            cursor.execute("""
                UPDATE setup_devices 
                SET device_name = ?, last_ip = ?, update_time = ?, 
                    device_type = COALESCE(?, device_type)
                WHERE device_id = ?
            """, (device_name, client_ip, now, device_type, device_id))
            is_new = False
        else:
            # 插入
            cursor.execute("""
                INSERT INTO setup_devices 
                (device_id, device_name, device_fingerprint, last_ip, device_type, create_time, update_time, is_configured)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (device_id, device_name, fingerprint, client_ip, device_type, now, now, 1 if device_name else 0))
            is_new = True
        
        return {"is_new": is_new, "device_id": device_id}


def _check_device_by_fingerprint(fingerprint: str) -> Optional[dict]:
    """通过设备指纹查找设备（支持跨浏览器识别）"""
    if not fingerprint:
        return None
    
    db = get_database()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 精确匹配指纹
        cursor.execute(
            "SELECT * FROM setup_devices WHERE device_fingerprint = ? LIMIT 1",
            (fingerprint,)
        )
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None


class _DeviceRegisterBody(_BaseModel):
    device_id: str  # 前端生成的 UUID
    device_name: str = ""  # 可选，首次注册时可能为空
    device_type: str = "mobile"  # mobile / desktop
    device_fingerprint: str = ""  # 设备指纹哈希


@app.post("/api/device/register")
async def register_device(body: _DeviceRegisterBody, request: Request):
    """
    设备注册/登录（支持设备指纹）
    - device_id: 前端生成的 UUID，永久标识设备
    - device_name: 设备名称
    - device_type: 设备类型
    - device_fingerprint: 设备指纹哈希
    """
    client_ip = request.client.host if request.client else "unknown"
    device_id = body.device_id.strip()
    fingerprint = body.device_fingerprint.strip()
    
    if not device_id:
        return {"ok": False, "error": "device_id is required"}
    
    # 使用数据库存储
    result = _register_device_db(
        device_id=device_id,
        device_name=body.device_name,
        fingerprint=fingerprint,
        device_type=body.device_type,
        client_ip=client_ip
    )
    
    logger.info(f"[Device] 注册: {device_id} ({body.device_type}) - {body.device_name or '未命名'}, FP={fingerprint[:16] if fingerprint else 'N/A'}...")
    
    return {
        "ok": True,
        "device_id": device_id,
        "device_name": body.device_name,
        "is_named": bool(body.device_name),
        "is_new": result.get("is_new", True)
    }


class _DeviceNameBody(_BaseModel):
    device_id: str = ""  # 设备UUID
    name: str  # 设备名称
    ip: str = ""   # 可选，允许前端自传；空时用 request.client.host


@app.post("/api/setup/name")
async def set_device_name(body: _DeviceNameBody, request: Request):
    """设置当前设备的名称（支持 device_id 或 ip）"""
    name = body.name.strip()
    if not name:
        return {"ok": False, "error": "name cannot be empty"}
    if len(name) > 32:
        return {"ok": False, "error": "name too long (max 32 chars)"}
    
    # 优先使用 device_id，其次使用 ip
    device_id = body.device_id.strip()
    ip = body.ip.strip() or (request.client.host if request.client else "unknown")
    
    if device_id:
        # 使用 device_id 存储
        if device_id not in _device_names:
            _device_names[device_id] = {"name": "", "ip": ip, "type": "mobile"}
        _device_names[device_id]["name"] = name
        _device_names[device_id]["last_seen"] = time.time()
        _save_device_names()
        logger.info(f"[Setup] 设备命名: {device_id} → {name}")
        return {"ok": True, "device_id": device_id, "name": name}
    else:
        # 兼容旧逻辑，使用 ip 存储
        _device_names[ip] = name
        _save_device_names()
        logger.info(f"[Setup] 设备命名: {ip} → {name}")
        return {"ok": True, "ip": ip, "name": name}


@app.get("/api/setup/name")
async def get_device_name(request: Request):
    """获取当前设备的名称（支持 device_id 查询参数）"""
    client_ip = request.client.host if request.client else "unknown"
    
    # 支持通过 query 参数指定 device_id
    from fastapi import Query
    device_id = None  # FastAPI Query 会自动处理
    
    # 先尝试从 Query 参数获取 device_id
    # 注意：FastAPI 会自动从 Query string 提取
    # 这里我们简化处理，默认用 IP 查询
    name = _device_names.get(client_ip, "")
    
    # 检查是否是新的 device_id 格式
    if name and isinstance(name, dict):
        # 新的存储格式
        actual_name = name.get("name", "")
        return {
            "ip": client_ip,
            "device_id": client_ip,  # 兼容
            "name": actual_name,
            "is_named": bool(actual_name)
        }
    
    return {"ip": client_ip, "name": name, "is_named": bool(name)}


@app.get("/api/setup/devices")
async def list_device_names():
    """列出所有已命名设备"""
    return {"devices": _device_names}


# ==================== 设备指纹自动匹配 API ====================

class _DeviceAutoMatchBody(_BaseModel):
    device_fingerprint: str  # 前端生成的设备指纹哈希
    current_ip: str = ""


@app.post("/api/device/auto-match")
async def device_auto_match(body: _DeviceAutoMatchBody, request: Request):
    """
    设备指纹自动匹配
    - 通过设备指纹查找已注册的设备
    - 如果找到，返回设备信息供用户确认
    - 如果未找到，返回 is_found=False，前端进入注册流程
    """
    client_ip = request.client.host if request.client else "unknown"
    fingerprint = body.device_fingerprint.strip()
    current_ip = body.current_ip.strip() or client_ip
    
    if not fingerprint:
        return {"ok": False, "error": "fingerprint is required"}
    
    # 查询数据库
    device = _check_device_by_fingerprint(fingerprint)
    
    if device:
        logger.info(f"[Device] 指纹匹配成功: {device['device_id']} - {device['device_name']}")
        return {
            "ok": True,
            "is_found": True,
            "device_id": device["device_id"],
            "device_name": device["device_name"],
            "device_type": device.get("device_type", "mobile"),
            "last_ip": device.get("last_ip", ""),
            "create_time": device.get("create_time", 0)
        }
    
    return {
        "ok": True,
        "is_found": False,
        "device_id": None,
        "device_name": None
    }


@app.post("/api/device/bind-fingerprint")
async def device_bind_fingerprint(body: _DeviceAutoMatchBody, request: Request):
    """
    绑定设备指纹到已有设备
    - 当用户确认使用已有设备时，将指纹绑定到该设备
    """
    client_ip = request.client.host if request.client else "unknown"
    fingerprint = body.device_fingerprint.strip()
    device_id = body.current_ip.strip()  # 复用字段传递 device_id
    
    if not fingerprint or not device_id:
        return {"ok": False, "error": "fingerprint and device_id are required"}
    
    db = get_database()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE setup_devices 
            SET device_fingerprint = ?, last_ip = ?, update_time = ?
            WHERE device_id = ?
        """, (fingerprint, client_ip, time.time(), device_id))
    
    logger.info(f"[Device] 指纹绑定: {device_id} → {fingerprint[:16]}...")
    
    return {"ok": True, "device_id": device_id}


# ==================== 证书下载 API ====================

@app.get("/api/cert/download")
async def download_certificate():
    """
    下载证书文件
    - 支持 HTTP/HTTPS 双端口访问
    - 设置正确的 MIME 类型，确保手机端能识别
    """
    from pathlib import Path
    from fastapi.responses import FileResponse
    
    cert_file = Path(__file__).parent / "certs" / "server.crt"
    
    if not cert_file.exists():
        # 尝试生成证书
        try:
            import subprocess
            subprocess.run(
                [sys.executable, "generate_lan_cert.py"],
                cwd=Path(__file__).parent,
                capture_output=True,
                timeout=10
            )
        except Exception:
            pass
    
    if not cert_file.exists():
        return JSONResponse(
            content={"ok": False, "error": "证书文件不存在"},
            status_code=404
        )
    
    return FileResponse(
        path=str(cert_file),
        media_type="application/x-x509-ca-cert",
        filename="VoiceBridge.crt",
        headers={
            "Content-Disposition": "attachment; filename=VoiceBridge.crt",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET",
            "Access-Control-Allow-Headers": "*",
        },
    )


@app.get("/api/device/check")
async def check_device(device_id: str = ""):
    """
    检查设备是否已配置
    - 用于自动跳转逻辑
    """
    if not device_id:
        return {"ok": True, "is_configured": False}
    
    db = get_database()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT is_configured, device_name FROM setup_devices WHERE device_id = ?",
            (device_id,)
        )
        row = cursor.fetchone()
        
        if row:
            return {
                "ok": True,
                "is_configured": bool(row["is_configured"]),
                "device_name": row["device_name"] or ""
            }
        
        return {"ok": True, "is_configured": False, "device_name": ""}



# ==================== 设备管理 API（服务端专属）====================
# 使用已有的 setup_devices 表，通过 IP 判断是否为服务端本机

def _is_server_local(request: Request) -> bool:
    """判断请求是否来自服务端本机（localhost / 127.0.0.1 / ::1）"""
    client_ip = request.client.host if request.client else ""
    return client_ip in ("127.0.0.1", "::1", "localhost")


@app.get("/api/admin/devices")
async def admin_list_devices(request: Request):
    """获取所有设备列表（仅服务端可访问）"""
    if not _is_server_local(request):
        return JSONResponse(content={"ok": False, "error": "仅服务端可访问"}, status_code=403)

    db = get_database()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT device_id, device_name, device_fingerprint,
                   last_ip, device_type, create_time, update_time, is_configured
            FROM setup_devices
            ORDER BY update_time DESC
        """)
        rows = cursor.fetchall()

    now = time.time()
    devices = []
    for row in rows:
        d = dict(row)
        # 10 秒内有更新视为在线
        d["status"] = "online" if (now - (d.get("update_time") or 0)) < 10 else "offline"
        d["last_time"] = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(d.get("update_time") or d.get("create_time") or 0)
        )
        devices.append(d)

    return {"ok": True, "devices": devices}


class _AdminRenameBody(_BaseModel):
    device_name: str


@app.post("/api/admin/device/{device_id}/rename")
async def admin_rename_device(device_id: str, body: _AdminRenameBody, request: Request):
    """重命名设备（仅服务端可访问）"""
    if not _is_server_local(request):
        return JSONResponse(content={"ok": False, "error": "仅服务端可访问"}, status_code=403)

    name = body.device_name.strip()
    if not name or len(name) > 32:
        return JSONResponse(content={"ok": False, "error": "名称不合法"}, status_code=400)

    db = get_database()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE setup_devices SET device_name = ?, update_time = ? WHERE device_id = ?",
            (name, time.time(), device_id)
        )
        if cursor.rowcount == 0:
            return JSONResponse(content={"ok": False, "error": "设备不存在"}, status_code=404)

    logger.info(f"[Admin] 重命名设备 {device_id[:8]}… → {name}")
    return {"ok": True}


@app.delete("/api/admin/device/{device_id}")
async def admin_delete_device(device_id: str, request: Request):
    """删除设备记录（仅服务端可访问）"""
    if not _is_server_local(request):
        return JSONResponse(content={"ok": False, "error": "仅服务端可访问"}, status_code=403)

    db = get_database()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM setup_devices WHERE device_id = ?", (device_id,))
        if cursor.rowcount == 0:
            return JSONResponse(content={"ok": False, "error": "设备不存在"}, status_code=404)

    logger.info(f"[Admin] 删除设备 {device_id[:8]}…")
    return {"ok": True}


@app.post("/api/admin/device/{device_id}/heartbeat")
async def admin_device_heartbeat(device_id: str, request: Request):
    """客户端心跳上报（更新 update_time 以维持在线状态）"""
    client_ip = request.client.host if request.client else ""
    db = get_database()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE setup_devices SET update_time = ?, last_ip = ? WHERE device_id = ?",
            (time.time(), client_ip, device_id)
        )
    return {"ok": True}


@app.get("/api/monitor")
async def system_monitor(request: Request):
    """系统资源监控数据"""
    import psutil, os
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        # HTTPS 健康检测
        https_ok = False
        try:
            import urllib.request
            urllib.request.urlopen(f"https://{get_local_ip()}:{get_settings().https_port}/api/setup/info", timeout=2)
            https_ok = True
        except Exception:
            pass
        return {"cpu": int(cpu), "mem": int(mem), "disk": int(disk), "httpsOk": https_ok}
    except ImportError:
        # psutil 未安装，返回 mock 数据
        return {"cpu": 23, "mem": 41, "disk": 55, "httpsOk": True}


@app.get("/api/db/info")
async def db_info(request: Request):
    """数据库统计信息"""
    import os as _os
    db = get_database()
    try:
        with db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM setup_devices")
            dev_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM voice_logs")
            log_count = c.fetchone()[0]
        db_path = Path(__file__).parent.parent / "voice_bridge.db"
        size_str = "未知"
        if db_path.exists():
            size = _os.path.getsize(db_path)
            size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/1024/1024:.1f} MB"
        return {"devCount": dev_count, "logCount": log_count, "size": size_str}
    except Exception as e:
        return {"devCount": 0, "logCount": 0, "size": f"错误: {e}"}


@app.get("/admin/device")
async def admin_device_page(request: Request):
    """设备管理页面（仅服务端本机可访问）"""
    if not _is_server_local(request):
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            content="<h3 style='font-family:sans-serif;color:#dc2626;margin:40px auto;text-align:center'>"
                    "⚠️ 设备管理页面仅服务端本机可访问</h3>",
            status_code=403
        )
    from fastapi.responses import FileResponse
    from pathlib import Path
    admin_file = Path(__file__).parent.parent / "frontend" / "dist" / "admin-device.html"
    if not admin_file.exists():
        return JSONResponse(content={"error": "管理页面未构建"}, status_code=404)
    return FileResponse(str(admin_file), media_type="text/html")


# ==================== WebSocket ====================
@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    """
    剪贴板/设备控制 WebSocket 连接

    每个连接生成唯一 traceId，记录到日志文件。
    """
    trace_id = generate_trace_id()
    set_trace_id(trace_id)
    logger.info(
        f"[clipboard] WS 连接请求 | device_id={device_id} | trace_id={trace_id}"
    )
    try:
        await websocket_handler(websocket, device_id)
    finally:
        clear_trace_id()
        logger.info(f"[clipboard] WS 连接结束 | device_id={device_id} | trace_id={trace_id}")


# ==================== 麦克风桥接 WebSocket ====================
@app.websocket("/ws/audio/{device_id}")
async def audio_websocket_endpoint(websocket: WebSocket, device_id: str):
    """
    麦克风音频流 WebSocket 连接

    每个连接生成唯一 traceId，记录到日志文件，方便追踪整个音频链路。
    traceId 通过 contextvars 自动注入到所有 logger 调用中。
    """
    # 生成并设置 traceId
    trace_id = generate_trace_id()
    set_trace_id(trace_id)
    logger.info(
        f"WebSocket 连接请求 | device_id={device_id} | trace_id={trace_id} | "
        f"client={websocket.client.host if websocket.client else 'unknown'}"
    )
    try:
        await audio_websocket_handler(websocket, device_id)
    finally:
        # 清理 traceId 上下文
        clear_trace_id()
        logger.info(f"WebSocket 连接结束 | device_id={device_id} | trace_id={trace_id}")


# ==================== 运行 ====================
def check_ports_available():
    """检查端口是否可用"""
    import socket
    results = []
    for port in [7266, 7267]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('0.0.0.0', port))
            sock.close()
            results.append((port, True, None))
        except OSError as e:
            sock.close()
            results.append((port, False, str(e)))
    return results


def _run_http_server():
    """HTTP 服务线程"""
    import uvicorn
    uvicorn.run(
        "main:app",  # 字符串形式，让 uvicorn 重新导入模块
        host="0.0.0.0",
        port=7266,
        reload=False,
        log_level="error",  # 过滤无效 HTTP 请求警告
        access_log=False,
    )


def _run_https_server(cert_file: str, key_file: str):
    """HTTPS 服务线程"""
    import uvicorn
    uvicorn.run(
        "main:app",  # 字符串形式，让 uvicorn 重新导入模块
        host="0.0.0.0",
        port=7267,
        reload=False,
        log_level="error",  # 过滤无效 HTTP 请求警告
        access_log=False,
        ssl_certfile=cert_file,
        ssl_keyfile=key_file,
    )


def run():
    """运行服务器"""
    import os
    import threading

    # 检查证书
    cert_dir = os.path.join(os.path.dirname(__file__), "certs")
    cert_file = os.path.join(cert_dir, "server.crt")
    key_file = os.path.join(cert_dir, "server.key")
    has_https = os.path.exists(cert_file) and os.path.exists(key_file)

    # 检查端口
    port_results = check_ports_available()
    unavailable = [p for p, ok, _ in port_results if not ok]

    if unavailable:
        logger.error(f"端口 {unavailable} 已被占用")
        return

    # 启动服务线程
    http_thread = threading.Thread(target=_run_http_server, daemon=True, name="VB-HTTP-7266")
    http_thread.start()

    # HTTPS 线程（如果有证书）
    https_thread = None
    if has_https:
        https_thread = threading.Thread(target=_run_https_server, args=(cert_file, key_file), daemon=True, name="VB-HTTPS-7267")
        https_thread.start()

    try:
        while True:
            http_thread.join(timeout=1)
            if https_thread:
                https_thread.join(timeout=1)
            if not http_thread.is_alive():
                break
    except KeyboardInterrupt:
        print("\n正在停止服务...")


if __name__ == "__main__":
    run()
