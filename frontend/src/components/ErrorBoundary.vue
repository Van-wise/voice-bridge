<script setup lang="ts">
/**
 * ErrorBoundary.vue - Vue 3 错误边界组件
 * 
 * 用法：
 * <ErrorBoundary @error="handleError">
 *   <YourComponent />
 * </ErrorBoundary>
 * 
 * 带 fallback slot：
 * <ErrorBoundary>
 *   <YourComponent />
 *   <template #fallback="{ error, reset }">
 *     <div class="custom-error">出错了：{{ error.message }}</div>
 *     <button @click="reset">重试</button>
 *   </template>
 * </ErrorBoundary>
 */
import { ref, defineEmits } from 'vue'

interface ErrorInfo {
  message: string
  stack?: string
  componentStack?: string
  timestamp: number
  type: string
}

const emit = defineEmits<{
  (e: 'error', error: Error, errorInfo: ErrorInfo): void
}>()

// Props
const props = defineProps<{
  maxRetries?: number
  showDetails?: boolean
  fallbackMessage?: string
}>()

// 状态
const hasError = ref(false)
const currentError = ref<Error | null>(null)
const currentErrorInfo = ref<ErrorInfo | null>(null)
const retryCount = ref(0)
const maxRetries = props.maxRetries ?? 3

// 错误处理
function handleError(err: Error, instance: any, info: string) {
  hasError.value = true
  currentError.value = err
  currentErrorInfo.value = {
    message: err.message,
    stack: err.stack,
    componentStack: info,
    timestamp: Date.now(),
    type: 'vue'
  }
  
  emit('error', err, currentErrorInfo.value)
  
  // 记录到控制台
  console.error('[ErrorBoundary] 捕获到组件错误:', err, info)
}

// 重置
function reset() {
  hasError.value = false
  currentError.value = null
  currentErrorInfo.value = null
  
  // 防抖动：如果连续错误，延迟重置
  if (retryCount.value < maxRetries) {
    retryCount.value++
  }
}

// 暴露给父组件
defineExpose({
  hasError,
  reset,
  error: currentError
})

// Vue 3.2+ 错误处理
const errorCaptured = (err: Error, instance: any, info: string) => {
  handleError(err, instance, info)
  // 返回 false 阻止错误继续传播
  return false
}
</script>

<template>
  <!-- Fallback slot -->
  <slot v-if="hasError && $slots.fallback" name="fallback" :error="currentError" :reset="reset" />
  
  <!-- 错误提示 UI -->
  <div v-else-if="hasError" class="error-boundary">
    <div class="error-icon">⚠️</div>
    <div class="error-title">{{ fallbackMessage || '组件渲染出错' }}</div>
    <div class="error-message">{{ currentError?.message }}</div>
    
    <div class="error-actions">
      <button class="btn-retry" @click="reset">
        {{ retryCount >= maxRetries ? '忽略错误' : '重试' }}
      </button>
      <button v-if="retryCount >= maxRetries" class="btn-ignore" @click="hasError = false">
        继续使用
      </button>
    </div>
    
    <!-- 错误详情 -->
    <details v-if="showDetails && currentErrorInfo" class="error-details">
      <summary>查看详情</summary>
      <pre class="error-stack">{{ currentErrorInfo.componentStack || currentError?.stack || '无堆栈信息' }}</pre>
    </details>
  </div>
  
  <!-- 正常内容 -->
  <slot v-else />
</template>

<style scoped>
.error-boundary {
  padding: 20px;
  background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
  border: 1px solid #fecaca;
  border-radius: 12px;
  text-align: center;
  color: #991b1b;
}

.error-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.error-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
}

.error-message {
  font-size: 14px;
  color: #b91c1c;
  margin-bottom: 16px;
  padding: 8px;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 6px;
}

.error-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-bottom: 12px;
}

.btn-retry {
  padding: 8px 20px;
  background: #dc2626;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
  transition: background 0.2s;
}

.btn-retry:hover {
  background: #b91c1c;
}

.btn-ignore {
  padding: 8px 20px;
  background: transparent;
  color: #666;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-ignore:hover {
  background: rgba(0, 0, 0, 0.05);
}

.error-details {
  text-align: left;
  margin-top: 12px;
}

.error-details summary {
  cursor: pointer;
  font-size: 13px;
  color: #666;
  padding: 4px 0;
}

.error-stack {
  margin-top: 8px;
  padding: 12px;
  background: #fee2e2;
  border-radius: 6px;
  font-size: 11px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  color: #7f1d1d;
  max-height: 200px;
}
</style>
