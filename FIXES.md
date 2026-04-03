# Voice Bridge 修复报告

## 问题1：日志重复输出

### 根因
日志系统初始化时未检查进程ID，当同一模块被多次导入或重载时，可能导致日志 handler 重复添加。

### 修复内容
**文件**: `backend/shared/logging.py`

```python
# 添加进程ID跟踪
_init_pid: Optional[int] = None

# 增强幂等检查
if _logging_initialized and _initialized_logger is not None:
    if _init_pid == current_pid:
        return _initialized_logger  # 同一进程，直接返回
    # 不同进程，重新初始化
    _logging_initialized = False
    _initialized_logger = None

_init_pid = current_pid
```

---

## 问题2：自动清空功能逻辑错误

### 根因
1. 清空条件 `should_clear = auto_clear and manual_sync` 过于严格
2. 清空事件广播排除了源设备，导致发起端收不到清空确认

### 修复内容
**文件**: `backend/main.py`

```python
# 修改1：清空条件（移除 manual_sync 限制）
should_clear = auto_clear

# 修改2：广播清空事件给所有设备
state.push_event('clear', {'by': source, 'client_id': client_id})

# 修改3：广播逻辑调整
if etype == 'clear':
    exclude = None  # 不排除任何设备，确保所有端一致
```

**文件**: `frontend/src/App.vue`

```javascript
// 添加 clipboard_clear 消息处理
case 'clipboard_clear':
  if (msg.source !== localStorage.getItem('vb_device_id')) {
    text.value = ''
  }
  break
```

---

## 问题3：频繁操作导致卡死/连接异常

### 根因
1. WebSocket 连接无去重检查，新连接直接覆盖旧连接导致句柄泄漏
2. `disconnect` 方法可能被重复调用
3. `broadcast` 方法在迭代中修改集合

### 修复内容
**文件**: `backend/devices/websocket.py`

```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self._closing_connections: set[str] = set()  # 新增：防止重复关闭
        self._connection_times: dict[str, float] = {}  # 新增：跟踪连接时间

    async def connect(self, device_id: str, websocket: WebSocket):
        # 先关闭旧连接
        if device_id in self.active_connections:
            old_ws = self.active_connections[device_id]
            try:
                await old_ws.close(code=1000, reason="Replaced by new connection")
            except Exception:
                pass
            del self.active_connections[device_id]
        
        await websocket.accept()
        self.active_connections[device_id] = websocket

    async def broadcast(self, message, exclude=None):
        # 使用快照避免迭代中修改
        connections_snapshot = list(self.active_connections.items())
        disconnected = []
        
        for device_id, websocket in connections_snapshot:
            if device_id == exclude:
                continue
            try:
                await websocket.send_json(message)
            except Exception as e:
                disconnected.append(device_id)
        
        # 批量断开失败连接
        for device_id in disconnected:
            self.disconnect(device_id)
```

---

## 工程化改进

### 1. 前端防抖控制
**文件**: `frontend/src/App.vue`

```javascript
const SYNC_DEBOUNCE_MS = 500  // 同步防抖时间

async function doSync() {
  const now = Date.now()
  if (now - lastSyncTime < SYNC_DEBOUNCE_MS) {
    return  // 防抖
  }
  lastSyncTime = now
  // ... 同步逻辑
}
```

### 2. 僵尸连接清理
**文件**: `backend/devices/websocket.py`

```python
async def cleanup_stale_connections() -> int:
    """清理5分钟无活动的僵尸连接"""
    stale_devices = []
    for device_id, connect_time in list(manager._connection_times.items()):
        if time.time() - connect_time > 300:
            stale_devices.append(device_id)
    
    for device_id in stale_devices:
        manager.disconnect(device_id)
    
    return len(stale_devices)
```

---

## 修改文件清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `backend/shared/logging.py` | Bug修复 | 添加进程ID检查，防止日志重复 |
| `backend/main.py` | Bug修复 | 修复自动清空逻辑和广播范围 |
| `backend/devices/websocket.py` | Bug修复+改进 | 连接去重、优雅关闭、防僵尸连接 |
| `frontend/src/App.vue` | Bug修复+改进 | 添加清空事件处理、防抖控制 |

---

## 测试建议

1. **日志重复测试**：重启服务，检查日志是否还有重复
2. **自动清空测试**：
   - 手机同步到电脑 → 两端都应该清空
   - 电脑同步到手机 → 两端都应该清空
3. **频繁操作测试**：快速连续点击同步按钮，观察 WebSocket 连接是否稳定

---

## 日期
2026-04-03
