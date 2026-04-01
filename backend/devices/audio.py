"""
Voice Bridge - 音频传输模块（升级版）
手机端录音 → 上传到服务器 → 持久化存储 → WebSocket 推送给电脑端实时播放

特性：
- 录音文件永久保存（保留最近 N 条，可配置）
- 录音历史持久化到 SQLite
- 完整的控制台输出（INFO/DEBUG/ERROR）
- 支持麦克风设置（存储上限、自动播放等）
"""
import os
import uuid
import time
import asyncio
import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
import logging

logger = logging.getLogger("vb.audio")

router = APIRouter(prefix="/api/audio", tags=["audio"])

# 音频存储目录
AUDIO_DIR = Path(__file__).parent.parent / "audio_uploads"
AUDIO_DIR.mkdir(exist_ok=True)

# 支持的音频格式
AUDIO_MIME_MAP = {
    ".webm": "audio/webm",
    ".mp4":  "audio/mp4",
    ".m4a":  "audio/mp4",
    ".mp3":  "audio/mpeg",
    ".wav":  "audio/wav",
    ".ogg":  "audio/ogg",
    ".aac":  "audio/aac",
    ".3gp":  "audio/3gpp",
    ".amr":  "audio/amr",
}

# 默认设置（可通过 /api/audio/settings 修改）
_DEFAULT_MIC_SETTINGS = {
    "max_recordings": 50,        # 最多保留条数
    "auto_play": True,           # 电脑端自动播放
    "save_recordings": True,     # 是否永久保存（否则只保留本次会话）
    "notify_on_receive": True,   # 收到录音时在控制台输出
    "quality_hint": "medium",    # 录音质量提示（low/medium/high）
}

# 内存缓存（程序内快速访问）
_audio_queue: list[dict] = []


def _load_mic_settings() -> dict:
    """从 SQLite 加载麦克风设置"""
    try:
        from shared.database import get_database
        db = get_database()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'mic_settings'")
            row = cursor.fetchone()
            if row:
                return {**_DEFAULT_MIC_SETTINGS, **json.loads(row["value"])}
    except Exception as e:
        logger.debug(f"[MIC] Load settings fallback: {e}")
    return dict(_DEFAULT_MIC_SETTINGS)


def _save_mic_settings(settings: dict) -> None:
    """保存麦克风设置到 SQLite"""
    try:
        from shared.database import get_database
        db = get_database()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("mic_settings", json.dumps(settings), time.time())
            )
        logger.info(f"[MIC] Settings saved: {settings}")
    except Exception as e:
        logger.error(f"[MIC] Save settings failed: {e}")


def _get_mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return AUDIO_MIME_MAP.get(ext, "audio/webm")


def _init_audio_table() -> None:
    """确保 audio_recordings 表存在"""
    try:
        from shared.database import get_database
        db = get_database()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audio_recordings (
                    audio_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_ext TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    duration_ms INTEGER DEFAULT 0,
                    mime_type TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audio_created
                ON audio_recordings(created_at DESC)
            """)
        logger.info("[MIC] audio_recordings table ready")
    except Exception as e:
        logger.error(f"[MIC] Table init failed: {e}")


def _persist_recording(record: dict) -> None:
    """将录音记录持久化到 SQLite"""
    try:
        from shared.database import get_database
        db = get_database()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO audio_recordings
                (audio_id, device_id, file_path, file_ext, file_size, mime_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                record["audio_id"],
                record["device_id"],
                record["file_path"],
                record["file_ext"],
                record["size"],
                _get_mime("x" + record["file_ext"]),
                record["timestamp"] / 1000,
            ))
    except Exception as e:
        logger.warning(f"[MIC] Persist failed: {e}")


def _load_history_to_cache() -> None:
    """程序启动时从 SQLite 加载历史到内存缓存"""
    global _audio_queue
    try:
        from shared.database import get_database
        mic_settings = _load_mic_settings()
        max_n = mic_settings.get("max_recordings", 50)
        db = get_database()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT audio_id, device_id, file_path, file_ext, file_size, created_at
                FROM audio_recordings
                ORDER BY created_at DESC
                LIMIT ?
            """, (max_n,))
            rows = cursor.fetchall()
        loaded = []
        for row in reversed(rows):
            fp = Path(row["file_path"])
            if fp.exists():
                loaded.append({
                    "audio_id": row["audio_id"],
                    "device_id": row["device_id"],
                    "file_path": row["file_path"],
                    "file_ext": row["file_ext"],
                    "size": row["file_size"],
                    "timestamp": int(row["created_at"] * 1000),
                })
        _audio_queue = loaded
        logger.info(f"[MIC] Loaded {len(loaded)} recordings from database")
    except Exception as e:
        logger.warning(f"[MIC] Load history failed: {e}")
        _audio_queue = []


def _cleanup_old_files(max_n: int) -> None:
    """删除超出上限的旧录音文件及数据库记录"""
    global _audio_queue
    try:
        # 清理内存队列
        if len(_audio_queue) > max_n:
            to_remove = _audio_queue[:-max_n]
            _audio_queue = _audio_queue[-max_n:]
            for old in to_remove:
                try:
                    Path(old["file_path"]).unlink(missing_ok=True)
                    logger.debug(f"[MIC] Deleted old file: {old['audio_id']}")
                except Exception:
                    pass

        # 同步清理数据库
        try:
            from shared.database import get_database
            db = get_database()
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM audio_recordings
                    WHERE audio_id NOT IN (
                        SELECT audio_id FROM audio_recordings
                        ORDER BY created_at DESC
                        LIMIT ?
                    )
                """, (max_n,))
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(f"[MIC] Cleaned {deleted} old records from DB")
        except Exception as e:
            logger.warning(f"[MIC] DB cleanup failed: {e}")

    except Exception as e:
        logger.error(f"[MIC] Cleanup error: {e}")


# ─── 初始化（在 main.py startup 中调用）────────────────────────────────────────

def startup() -> None:
    """音频模块启动初始化"""
    _init_audio_table()
    _load_history_to_cache()
    logger.info(f"[MIC] Audio module started | upload dir: {AUDIO_DIR}")


# ─── 上传接口 ─────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_audio(
    audio: UploadFile = File(...),
    device_id: str = Form(default="unknown"),
):
    """
    手机端上传音频
    - 支持 webm / mp4 / m4a / mp3 / wav / ogg / aac / 3gp / amr
    - 上传成功后通过 WebSocket 实时通知电脑端
    - 录音永久保存到 audio_uploads/，记录写入 SQLite
    """
    global _audio_queue
    mic_settings = _load_mic_settings()

    logger.info(f"[MIC] ⬆️  Upload started | device={device_id} | file={audio.filename} | content-type={audio.content_type}")

    try:
        audio_id = str(uuid.uuid4())[:8]
        timestamp = int(time.time() * 1000)

        # 确定文件扩展名
        orig_name = audio.filename or "recording.webm"
        ext = Path(orig_name).suffix.lower()
        if ext not in AUDIO_MIME_MAP:
            # 从 content_type 推断
            ct = audio.content_type or ""
            if "mp4" in ct or "m4a" in ct:
                ext = ".m4a"
            elif "ogg" in ct:
                ext = ".ogg"
            elif "wav" in ct:
                ext = ".wav"
            elif "mp3" in ct or "mpeg" in ct:
                ext = ".mp3"
            elif "3gp" in ct:
                ext = ".3gp"
            elif "amr" in ct:
                ext = ".amr"
            else:
                ext = ".webm"

        file_path = AUDIO_DIR / f"{audio_id}{ext}"
        content = await audio.read()

        if len(content) == 0:
            logger.warning(f"[MIC] ⚠️  Empty audio from device={device_id}")
            raise HTTPException(status_code=400, detail="Empty audio file")

        size_kb = len(content) / 1024
        logger.info(f"[MIC] 📦 Saving {audio_id}{ext} | {size_kb:.1f} KB | from device={device_id}")

        with open(file_path, "wb") as f:
            f.write(content)

        logger.info(f"[MIC] 💾 Saved to: {file_path}")

        # 加入内存队列
        record = {
            "audio_id": audio_id,
            "device_id": device_id,
            "file_path": str(file_path),
            "file_ext": ext,
            "size": len(content),
            "timestamp": timestamp,
        }
        _audio_queue.append(record)

        # 持久化到 SQLite
        if mic_settings.get("save_recordings", True):
            _persist_recording(record)
            logger.info(f"[MIC] ✅ Persisted to DB: {audio_id}")
        else:
            logger.debug(f"[MIC] ℹ️  save_recordings=false, skipped DB persist")

        # 清理超限文件（异步执行，不阻塞）
        max_n = mic_settings.get("max_recordings", 50)
        if len(_audio_queue) > max_n:
            asyncio.create_task(asyncio.to_thread(_cleanup_old_files, max_n))

        # WebSocket 广播通知其他客户端（排除发送者，避免回音）
        # ⚠️ 重要：发送设备不应该播放自己的录音，否则会形成回音循环
        try:
            from devices.websocket import manager
            await manager.broadcast({
                "type": "new_audio",
                "audio_id": audio_id,
                "audio_url": f"/api/audio/file/{audio_id}",
                "device_id": device_id,
                "timestamp": timestamp,
                "size": len(content),
                "ext": ext,
            }, exclude=device_id)  # 排除发送设备，避免回音
            logger.info(f"[MIC] 📡 WebSocket broadcast sent: new_audio {audio_id} (excluded sender: {device_id})")
        except Exception as e:
            logger.warning(f"[MIC] ⚠️  WebSocket broadcast failed: {e}")

        total = len(_audio_queue)
        logger.info(f"[MIC] ✅ Upload complete: {audio_id} | total recordings: {total}")

        return JSONResponse({
            "success": True,
            "audio_id": audio_id,
            "audio_url": f"/api/audio/file/{audio_id}",
            "size": len(content),
            "ext": ext,
            "total_recordings": total,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MIC] ❌ Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─── 历史列表接口 ─────────────────────────────────────────────────────────────

@router.get("/list")
async def list_audio(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """获取录音历史列表（分页）"""
    items = list(reversed(_audio_queue))  # 最新在前
    total = len(items)
    paged = items[offset:offset + limit]

    result = []
    for r in paged:
        fp = Path(r["file_path"])
        result.append({
            "audio_id": r["audio_id"],
            "audio_url": f"/api/audio/file/{r['audio_id']}",
            "device_id": r["device_id"],
            "timestamp": r["timestamp"],
            "size": r["size"],
            "ext": r["file_ext"],
            "exists": fp.exists(),
        })

    logger.debug(f"[MIC] List: {len(result)} items (offset={offset}, total={total})")
    return JSONResponse({"total": total, "items": result, "offset": offset})


# ─── 删除单条录音 ──────────────────────────────────────────────────────────────

@router.delete("/recording/{audio_id}")
async def delete_recording(audio_id: str):
    """删除指定录音"""
    global _audio_queue
    target = None
    for r in _audio_queue:
        if r["audio_id"] == audio_id:
            target = r
            break

    if not target:
        raise HTTPException(status_code=404, detail="Recording not found")

    # 删除文件
    try:
        Path(target["file_path"]).unlink(missing_ok=True)
        logger.info(f"[MIC] 🗑️  Deleted file: {audio_id}")
    except Exception as e:
        logger.warning(f"[MIC] File delete failed: {e}")

    # 从内存队列移除
    _audio_queue = [r for r in _audio_queue if r["audio_id"] != audio_id]

    # 从数据库移除
    try:
        from shared.database import get_database
        db = get_database()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM audio_recordings WHERE audio_id = ?", (audio_id,))
        logger.info(f"[MIC] 🗑️  Deleted DB record: {audio_id}")
    except Exception as e:
        logger.warning(f"[MIC] DB delete failed: {e}")

    return JSONResponse({"success": True, "audio_id": audio_id})


# ─── 清空所有录音 ──────────────────────────────────────────────────────────────

@router.delete("/all")
async def clear_all_recordings():
    """清空所有录音"""
    global _audio_queue
    count = len(_audio_queue)

    for r in _audio_queue:
        try:
            Path(r["file_path"]).unlink(missing_ok=True)
        except Exception:
            pass

    _audio_queue = []

    try:
        from shared.database import get_database
        db = get_database()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM audio_recordings")
        logger.info(f"[MIC] 🧹 Cleared all {count} recordings")
    except Exception as e:
        logger.warning(f"[MIC] DB clear failed: {e}")

    return JSONResponse({"success": True, "deleted": count})


# ─── 麦克风设置接口 ───────────────────────────────────────────────────────────

@router.get("/settings")
async def get_mic_settings():
    """获取麦克风设置"""
    settings = _load_mic_settings()
    logger.debug(f"[MIC] Settings fetched: {settings}")
    return JSONResponse(settings)


@router.post("/settings")
async def update_mic_settings(body: dict):
    """更新麦克风设置"""
    current = _load_mic_settings()
    # 只更新已知字段
    allowed_keys = set(_DEFAULT_MIC_SETTINGS.keys())
    updates = {k: v for k, v in body.items() if k in allowed_keys}
    current.update(updates)
    _save_mic_settings(current)
    logger.info(f"[MIC] ⚙️  Settings updated: {updates}")
    return JSONResponse({"success": True, "settings": current})


# ─── 轮询降级接口 ──────────────────────────────────────────────────────────────

@router.get("/latest")
async def get_latest_audio(id: str = ""):
    """轮询获取最新音频（WebSocket 不可用时的降级方案）"""
    if not _audio_queue:
        return JSONResponse({"has_new": False})

    latest = _audio_queue[-1]
    if latest["audio_id"] == id:
        return JSONResponse({"has_new": False})

    return JSONResponse({
        "has_new": True,
        "audio_id": latest["audio_id"],
        "audio_url": f"/api/audio/file/{latest['audio_id']}",
        "device_id": latest["device_id"],
        "timestamp": latest["timestamp"],
        "size": latest["size"],
    })


# ─── 文件下载/播放 ────────────────────────────────────────────────────────────

@router.get("/file/{audio_id}")
async def get_audio_file(audio_id: str):
    """获取音频文件（供浏览器播放）"""
    # 优先从内存队列找（快速）
    for r in reversed(_audio_queue):
        if r["audio_id"] == audio_id:
            fp = Path(r["file_path"])
            if fp.exists():
                logger.debug(f"[MIC] 🎵 Serving audio: {audio_id} ({fp.stat().st_size // 1024}KB)")
                return FileResponse(
                    fp,
                    media_type=_get_mime(fp.name),
                    filename=fp.name,
                    headers={"Accept-Ranges": "bytes"},
                )
            break

    # fallback：扫描目录
    for ext in AUDIO_MIME_MAP:
        fp = AUDIO_DIR / f"{audio_id}{ext}"
        if fp.exists():
            logger.debug(f"[MIC] 🎵 Serving (fallback): {audio_id}{ext}")
            return FileResponse(fp, media_type=_get_mime(fp.name), filename=fp.name)

    logger.warning(f"[MIC] ⚠️  Audio not found: {audio_id}")
    raise HTTPException(status_code=404, detail="Audio not found")
