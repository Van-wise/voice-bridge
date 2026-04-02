/**
 * Voice Bridge 前端异常处理工具
 * 
 * 提供三层异常处理机制：
 * 1. ErrorBoundary - 组件级错误边界
 * 2. 全局错误处理器 - window.onerror, unhandledrejection
 * 3. API 错误装饰器 - 统一处理接口异常
 */

import { ref, onMounted, onUnmounted, type ComponentPublicInstance, type VNode } from 'vue'

// ==================== 类型定义 ====================

export interface ErrorInfo {
  message: string
  stack?: string
  componentStack?: string
  timestamp: number
  type: 'vue' | 'js' | 'promise' | 'resource'
}

export interface ErrorBoundaryProps {
  /** 错误回调 */
  onError?: (error: Error, errorInfo: ErrorInfo) => void
  /** 是否显示错误详情 */
  showDetails?: boolean
  /** 自定义 fallback UI */
  fallback?: (error: Error, reset: () => void) => VNode
  /** 错误重试次数（防抖动） */
  maxRetries?: number
}

export interface ApiErrorOptions {
  /** 是否显示 toast 提示 */
  showToast?: boolean
  /** 是否抛出异常（false 则静默处理） */
  throwError?: boolean
  /** 自定义错误消息 */
  customMessage?: string
}

// ==================== 错误收集器 ====================

class ErrorCollector {
  private errors: ErrorInfo[] = []
  private maxSize = 100

  add(error: ErrorInfo) {
    this.errors.unshift(error)
    if (this.errors.length > this.maxSize) {
      this.errors.pop()
    }
    console.error('[ErrorCollector]', error)
  }

  getErrors(): ErrorInfo[] {
    return [...this.errors]
  }

  clear() {
    this.errors = []
  }
}

export const errorCollector = new ErrorCollector()

// ==================== 全局错误处理器 ====================

let _globalErrorHandler: ((error: ErrorInfo) => void) | null = null

export function setGlobalErrorHandler(handler: (error: ErrorInfo) => void) {
  _globalErrorHandler = handler
}

function handleGlobalError(error: Error, type: ErrorInfo['type'], extra?: Partial<ErrorInfo>) {
  const errorInfo: ErrorInfo = {
    message: error.message,
    stack: error.stack,
    timestamp: Date.now(),
    type,
    ...extra
  }
  
  errorCollector.add(errorInfo)
  _globalErrorHandler?.(errorInfo)
}

// ==================== API 错误处理 ====================

export interface ApiResponse<T = any> {
  success?: boolean
  error?: string
  message?: string
  data?: T
  [key: string]: any
}

/**
 * 统一 API 请求错误处理
 * 
 * @example
 * const data = await apiRequest(() => fetch('/api/xxx'), { showToast: true })
 */
export async function apiRequest<T>(
  requestFn: () => Promise<Response>,
  options: ApiErrorOptions = {}
): Promise<T | null> {
  const { showToast = false, throwError = true, customMessage } = options

  try {
    const response = await requestFn()
    
    // HTTP 错误状态码
    if (!response.ok) {
      const error = new Error(customMessage || `请求失败 (${response.status})`)
      handleGlobalError(error, 'js', { message: error.message })
      if (showToast) {
        showErrorToast(error.message)
      }
      if (throwError) throw error
      return null
    }

    const data: ApiResponse<T> = await response.json()
    
    // 业务错误
    if (data.error) {
      const error = new Error(customMessage || data.message || data.error)
      handleGlobalError(error, 'js', { message: error.message })
      if (showToast) {
        showErrorToast(data.message || data.error)
      }
      if (throwError) throw error
      return null
    }

    return data as T
  } catch (err) {
    if (err instanceof Error) {
      handleGlobalError(err, 'promise')
      if (throwError) throw err
    }
    return null
  }
}

/**
 * 带重试的 API 请求
 */
export async function apiRequestWithRetry<T>(
  requestFn: () => Promise<Response>,
  retries = 3,
  delay = 1000
): Promise<T | null> {
  let lastError: Error | null = null
  
  for (let i = 0; i < retries; i++) {
    try {
      const result = await apiRequest<T>(requestFn, { throwError: false })
      if (result !== null) return result
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err))
    }
    
    if (i < retries - 1) {
      await new Promise(resolve => setTimeout(resolve, delay * (i + 1)))
    }
  }
  
  if (lastError) throw lastError
  return null
}

// ==================== Toast 提示（依赖注入） ====================

let _toastFn: ((msg: string, type: string) => void) | null = null

export function setToastFunction(fn: (msg: string, type: string) => void) {
  _toastFn = fn
}

export function showErrorToast(message: string) {
  _toastFn?.(message, 'err')
}

export function showSuccessToast(message: string) {
  _toastFn?.(message, 'ok')
}

export function showWarnToast(message: string) {
  _toastFn?.(message, 'warn')
}

// ==================== Vue ErrorBoundary 组件 ====================

/**
 * Vue 3 ErrorBoundary 组件
 * 
 * @example
 * <ErrorBoundary @error="handleError">
 *   <MyComponent />
 * </ErrorBoundary>
 */
export const ErrorBoundary = {
  name: 'ErrorBoundary',
  
  props: {
    onError: {
      type: Function,
      default: null
    },
    showDetails: {
      type: Boolean,
      default: false
    },
    maxRetries: {
      type: Number,
      default: 3
    },
    fallbackMessage: {
      type: String,
      default: '组件渲染出错'
    }
  },
  
  setup(props: ErrorBoundaryProps, { slots, emit }: any) {
    const error = ref<Error | null>(null)
    const errorInfo = ref<ErrorInfo | null>(null)
    const retryCount = ref(0)
    const isRetrying = ref(false)

    // 获取 Vue 组件实例的错误信息
    function handleError(err: Error, instance: ComponentPublicInstance | null, info: string) {
      const errorInfoData: ErrorInfo = {
        message: err.message,
        stack: err.stack,
        componentStack: info,
        timestamp: Date.now(),
        type: 'vue'
      }
      
      error.value = err
      errorInfo.value = errorInfoData
      
      errorCollector.add(errorInfoData)
      emit('error', err, errorInfoData)
      props.onError?.(err, errorInfoData)
      
      // 自动重试（防止临时性错误）
      if (retryCount.value < (props.maxRetries || 3)) {
        retryCount.value++
        isRetrying.value = true
        
        setTimeout(() => {
          error.value = null
          errorInfo.value = null
          isRetrying.value = false
        }, 100)
      }
    }

    // 手动重置
    function reset() {
      error.value = null
      errorInfo.value = null
      retryCount.value = 0
      isRetrying.value = false
    }

    // 错误详情
    const errorDetails = () => {
      if (!errorInfo.value) return ''
      const parts = [`错误: ${errorInfo.value.message}`]
      if (errorInfo.value.componentStack) {
        parts.push(`\n组件堆栈:\n${errorInfo.value.componentStack}`)
      }
      if (errorInfo.value.stack) {
        parts.push(`\n堆栈:\n${errorInfo.value.stack}`)
      }
      return parts.join('\n')
    }

    return () => {
      // 有错误，显示 fallback
      if (error.value) {
        // 自定义 fallback slot
        if (slots.fallback) {
          return slots.fallback({
            error: error.value,
            errorInfo: errorInfo.value,
            reset
          })
        }
        
        // 内置 fallback UI
        return {
          type: 'div' as const,
          class: 'error-boundary',
          style: {
            padding: '20px',
            background: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: '8px',
            color: '#991b1b',
            fontFamily: 'monospace',
            fontSize: '14px'
          },
          children: [
            {
              type: 'div' as const,
              style: { fontWeight: 'bold', marginBottom: '8px' },
              children: `⚠️ ${props.fallbackMessage}`
            },
            {
              type: 'div' as const,
              style: { marginBottom: '12px', color: '#666' },
              children: error.value.message
            },
            {
              type: 'button' as const,
              style: {
                padding: '6px 12px',
                background: '#dc2626',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                marginRight: '8px'
              },
              onClick: () => reset(),
              children: '重试'
            },
            props.showDetails && {
              type: 'details' as const,
              style: { marginTop: '12px', textAlign: 'left' },
              children: [
                {
                  type: 'summary' as const,
                  style: { cursor: 'pointer' },
                  children: '查看详情'
                },
                {
                  type: 'pre' as const,
                  style: {
                    fontSize: '11px',
                    overflow: 'auto',
                    maxHeight: '200px',
                    background: '#fee2e2',
                    padding: '8px',
                    borderRadius: '4px'
                  },
                  children: errorDetails()
                }
              ]
            }
          ].filter(Boolean)
        }
      }

      // 正常渲染子组件
      return slots.default?.()
    }
  }
}

// ==================== 初始化全局错误处理 ====================

let _initialized = false

export function initGlobalErrorHandler() {
  if (_initialized) return
  _initialized = true

  // Vue 组件错误
  const app = (window as any).__VueApp__
  if (app) {
    app.config.errorHandler = (err: Error, instance: ComponentPublicInstance | null, info: string) => {
      handleError(err, instance, info)
    }
  }

  // JavaScript 运行时错误
  window.onerror = (message, source, lineno, colno, error) => {
    if (error) {
      handleGlobalError(error, 'js', { message: String(message) })
    }
    return false
  }

  // Promise 拒绝
  window.addEventListener('unhandledrejection', (event) => {
    const error = event.reason instanceof Error 
      ? event.reason 
      : new Error(String(event.reason))
    handleGlobalError(error, 'promise')
  })

  // 资源加载错误（图片、脚本等）
  window.addEventListener('error', (event) => {
    if (event.target !== window) {
      const target = event.target as HTMLElement
      const errorInfo: ErrorInfo = {
        message: `资源加载失败: ${target.tagName || 'Unknown'}`,
        timestamp: Date.now(),
        type: 'resource'
      }
      errorCollector.add(errorInfo)
    }
  }, true)

  console.log('[ErrorHandler] 全局错误处理已初始化')
}

// ==================== 便捷组合式函数 ====================

/**
 * 包装异步函数，自动处理错误
 * 
 * @example
 * const data = await withErrorHandler(fetchData, { showToast: true })
 */
export async function withErrorHandler<T>(
  fn: () => Promise<T>,
  options: {
    onError?: (e: Error) => void
    showToast?: boolean
    toastMessage?: string
  } = {}
): Promise<T | null> {
  const { onError, showToast = false, toastMessage } = options
  
  try {
    return await fn()
  } catch (err) {
    if (err instanceof Error) {
      handleGlobalError(err, 'promise')
      onError?.(err)
      if (showToast) {
        showErrorToast(toastMessage || err.message)
      }
    }
    return null
  }
}

/**
 * Vue 组合式错误处理
 * 
 * @example
 * const { error, execute } = useAsyncErrorHandler()
 * const data = await execute(() => api.get('/xxx'))
 */
export function useAsyncErrorHandler(options: ApiErrorOptions = {}) {
  const error = ref<Error | null>(null)
  
  async function execute<T>(fn: () => Promise<T>): Promise<T | null> {
    error.value = null
    try {
      return await fn()
    } catch (err) {
      if (err instanceof Error) {
        error.value = err
        handleGlobalError(err, 'promise')
        if (options.showToast) {
          showErrorToast(options.customMessage || err.message)
        }
        if (options.throwError !== false) {
          throw err
        }
      }
      return null
    }
  }
  
  return { error, execute }
}
