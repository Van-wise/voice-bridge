/**
 * Voice Bridge 前端调试工具
 * 功能：
 * 1. 通过 URL 参数 ?debug=1 开启调试模式
 * 2. 分级日志（DEBUG/INFO/WARN/ERROR）
 * 3. Trace ID 全链路追踪
 * 4. 自动上报日志到后端
 */

// 生成唯一 Trace ID
function generateTraceId() {
  return 'trace_' + Math.random().toString(36).substr(2, 9);
}

// 当前 Trace ID
let currentTraceId = generateTraceId();

// 当前 Device ID（从 localStorage 或 cookie 获取）
function getDeviceId() {
  return localStorage.getItem('device_id') || '';
}

// 判断是否开启调试模式
function isDebugMode() {
  const params = new URLSearchParams(window.location.search);
  return params.get('debug') === '1';
}

// 上报日志到后端
async function reportLog(level, message) {
  try {
    const response = await fetch('/api/log', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Trace-ID': VBLogger.getTraceId()
      },
      body: JSON.stringify({
        level: level,
        message: message,
        trace_id: VBLogger.getTraceId(),
        device_id: getDeviceId()
      })
    });
    return await response.json();
  } catch (e) {
    // 上报失败不影响正常功能
    console.debug('[VBLogger] 上报失败:', e);
  }
}

// VBLogger 对象
const VBLogger = {
  debug: function(...args) {
    const msg = args.map(a => typeof a === 'object' ? JSON.stringify(a) : a).join(' ');
    const debug = isDebugMode();
    
    if (debug) {
      console.debug(`[DEBUG] [${currentTraceId}] ${msg}`);
    }
    
    if (debug) {
      reportLog('DEBUG', msg);
    }
  },
  
  info: function(...args) {
    const msg = args.map(a => typeof a === 'object' ? JSON.stringify(a) : a).join(' ');
    console.info(`[INFO] [${currentTraceId}] ${msg}`);
    
    if (isDebugMode()) {
      reportLog('INFO', msg);
    }
  },
  
  warn: function(...args) {
    const msg = args.map(a => typeof a === 'object' ? JSON.stringify(a) : a).join(' ');
    console.warn(`[WARN] [${currentTraceId}] ${msg}`);
    reportLog('WARN', msg); // 警告也上报
  },
  
  error: function(...args) {
    const msg = args.map(a => typeof a === 'object' ? JSON.stringify(a) : a).join(' ');
    console.error(`[ERROR] [${currentTraceId}] ${msg}`);
    reportLog('ERROR', msg); // 错误始终上报
  },
  
  // 获取当前 Trace ID
  getTraceId: function() {
    return currentTraceId;
  },
  
  // 生成新的 Trace ID（用于新的用户操作）
  newTraceId: function() {
    currentTraceId = generateTraceId();
    console.info(`[VBLogger] 新 Trace ID: ${currentTraceId}`);
    return currentTraceId;
  },
  
  // 检查调试模式
  isDebug: function() {
    return isDebugMode();
  },
  
  // 手动上报
  report: function(level, message) {
    return reportLog(level, message);
  }
};

// 全局挂载
if (typeof window !== 'undefined') {
  window.VBLogger = VBLogger;
  
  // 初始化日志
  if (isDebugMode()) {
    console.info('%c[VBLogger] 调试模式已开启', 'color: #ff6b6b; font-weight: bold; font-size: 14px;');
    console.info(`[VBLogger] Trace ID: ${currentTraceId}`);
    console.info('[VBLogger] 提示: 使用 VBLogger.getTraceId() 获取当前追踪 ID');
    
    // 拦截 fetch 请求，自动添加 Trace ID
    const originalFetch = window.fetch;
    window.fetch = async function(url, options = {}) {
      const traceId = VBLogger.getTraceId();
      
      // 添加 Trace ID 到请求头
      if (!options.headers) {
        options.headers = {};
      }
      if (typeof options.headers === 'object' && !Array.isArray(options.headers)) {
        options.headers['X-Trace-ID'] = traceId;
      }
      
      VBLogger.debug(`[Fetch] ${options.method || 'GET'} ${url}`);
      
      try {
        const response = await originalFetch(url, options);
        VBLogger.debug(`[Fetch] ${url} -> ${response.status}`);
        return response;
      } catch (e) {
        VBLogger.error(`[Fetch] ${url} 失败:`, e);
        throw e;
      }
    };
    
    // 挂载到 window 以便 Vue 组件使用
    window.__VB_DEBUG__ = {
      traceId: currentTraceId,
      newTraceId: VBLogger.newTraceId,
      logger: VBLogger
    };
  }
}

// 导出
export default VBLogger;
export { VBLogger, isDebugMode };
