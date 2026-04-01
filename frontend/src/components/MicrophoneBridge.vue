<template>
  <div class="microphone-bridge">
    <div class="bridge-header">
      <span class="bridge-icon">🎤</span>
      <span class="bridge-title">麦克风桥接</span>
      <span class="bridge-status" :class="{ active: isActive }">
        {{ isActive ? '工作中' : '待机' }}
      </span>
    </div>

    <div class="bridge-content">
      <!-- 手机端：发送麦克风音频 -->
      <div class="mode-section" v-if="isMobile">
        <div class="section-title">发送麦克风</div>
        <div class="mic-control">
          <button
            class="mic-button"
            :class="{ streaming: micState.isStreaming, connecting: micState.isConnecting }"
            @click="toggleMic"
            :disabled="micState.isConnecting"
          >
            <span class="mic-icon">{{ micState.isStreaming ? '🔴' : '🎤' }}</span>
          </button>
          <div class="mic-info">
            <div class="mic-status">
              {{ micState.isConnecting ? '连接中...' : micState.isStreaming ? '正在传输' : '点击开始' }}
            </div>
            <div class="mic-duration" v-if="micState.isStreaming">
              {{ formatDuration(micState.duration) }}
            </div>
          </div>
        </div>
        <!-- 音量指示器 -->
        <div class="level-meter" v-if="micState.isStreaming">
          <div class="level-bar" :style="{ width: micLevel + '%' }"></div>
        </div>
        <!-- 错误提示 -->
        <div class="error-message" v-if="micState.error">
          {{ micState.error }}
        </div>
      </div>

      <!-- 电脑端：接收麦克风音频 -->
      <div class="mode-section" v-else>
        <div class="section-title">接收麦克风</div>
        <div class="audio-control">
          <button
            class="audio-button"
            :class="{ playing: playerState.isPlaying, connected: playerState.isConnected }"
            @click="togglePlayer"
          >
            <span class="audio-icon">{{ playerState.isConnected ? '🔊' : '🔇' }}</span>
          </button>
          <div class="audio-info">
            <div class="audio-status">
              {{ playerState.isConnected ? '已连接' : '点击连接' }}
            </div>
            <div class="audio-source" v-if="playerState.currentSource">
              来自: {{ playerState.currentSource }}
            </div>
          </div>
        </div>
        <!-- 音量控制 -->
        <div class="volume-control" v-if="playerState.isConnected">
          <label>音量</label>
          <input
            type="range"
            min="0"
            max="100"
            v-model="volume"
            @input="updateVolume"
          />
          <span>{{ volume }}%</span>
        </div>
        <!-- 活动源列表 -->
        <div class="active-sources" v-if="playerState.activeSources.length > 0">
          <div class="sources-label">活动设备:</div>
          <div class="source-tags">
            <span class="source-tag" v-for="source in playerState.activeSources" :key="source">
              {{ source }}
            </span>
          </div>
        </div>
        <!-- 错误提示 -->
        <div class="error-message" v-if="playerState.error">
          {{ playerState.error }}
        </div>
      </div>
    </div>

    <div class="bridge-footer">
      <div class="bridge-tip">
        {{ isMobile ? '将手机变成电脑的无线麦克风' : '接收来自手机的麦克风音频' }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMicrophone } from '../composables/useMicrophone'
import { useAudioPlayer } from '../composables/useAudioPlayer'

// Props
const props = defineProps<{
  deviceId: string
}>()

// 检测是否为移动设备
const isMobile = computed(() => {
  const ua = navigator.userAgent.toLowerCase()
  return /android|iphone|ipad|ipod|mobile/i.test(ua)
})

// 麦克风（手机端）
const micState = ref({
  isStreaming: false,
  isConnecting: false,
  error: null as string | null,
  duration: 0,
})
const micLevel = ref(0)

const {
  state: micStateFull,
  isStreaming: micStreaming,
  isConnecting: micConnecting,
  duration: micDuration,
  audioLevel: micAudioLevel,
  startStreaming: startMic,
  stopStreaming: stopMic,
  toggle: toggleMicFn,
} = useMicrophone(props.deviceId)

// 监听麦克风状态变化
onMounted(() => {
  // 更新麦克风状态
  const updateMicState = () => {
    micState.value = {
      isStreaming: micStateFull.value.isStreaming,
      isConnecting: micStateFull.value.isConnecting,
      error: micStateFull.value.error,
      duration: micStateFull.value.duration,
    }
    micLevel.value = micAudioLevel.value
    requestAnimationFrame(updateMicState)
  }
  updateMicState()
})

const toggleMic = async () => {
  try {
    await toggleMicFn()
  } catch (e) {
    console.error('Mic toggle failed:', e)
  }
}

// 音频播放器（电脑端）
const volume = ref(100)

const {
  state: playerStateFull,
  isPlaying: playerPlaying,
  isConnected: playerConnected,
  activeSources,
  currentSource,
  startReceiving,
  stopReceiving,
  setVolume,
} = useAudioPlayer(props.deviceId)

const playerState = computed(() => ({
  isPlaying: playerStateFull.value.isPlaying,
  isConnected: playerStateFull.value.isConnected,
  error: playerStateFull.value.error,
  activeSources: playerStateFull.value.activeSources,
  currentSource: currentSource.value,
}))

const isActive = computed(() => {
  return isMobile.value
    ? micStateFull.value.isStreaming
    : playerStateFull.value.isPlaying
})

const togglePlayer = async () => {
  try {
    if (playerStateFull.value.isConnected) {
      stopReceiving()
    } else {
      await startReceiving()
    }
  } catch (e) {
    console.error('Player toggle failed:', e)
  }
}

const updateVolume = () => {
  setVolume(volume.value / 100)
}

// 格式化时长
const formatDuration = (seconds: number): string => {
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

// 组件卸载时自动停止
onUnmounted(() => {
  if (isMobile.value && micStateFull.value.isStreaming) {
    stopMic()
  } else if (!isMobile.value && playerStateFull.value.isConnected) {
    stopReceiving()
  }
})
</script>

<style scoped>
.microphone-bridge {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 16px;
  padding: 20px;
  color: white;
  box-shadow: 0 4px 20px rgba(102, 126, 234, 0.4);
}

.bridge-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.bridge-icon {
  font-size: 24px;
}

.bridge-title {
  font-size: 18px;
  font-weight: 600;
  flex: 1;
}

.bridge-status {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  background: rgba(255, 255, 255, 0.2);
}

.bridge-status.active {
  background: #10b981;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.bridge-content {
  min-height: 120px;
}

.mode-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-title {
  font-size: 14px;
  opacity: 0.8;
}

/* 麦克风按钮 */
.mic-control,
.audio-control {
  display: flex;
  align-items: center;
  gap: 16px;
}

.mic-button,
.audio-button {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.2);
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mic-button:hover,
.audio-button:hover {
  background: rgba(255, 255, 255, 0.3);
  transform: scale(1.05);
}

.mic-button.streaming {
  background: #ef4444;
  animation: glow 1.5s ease-in-out infinite;
}

.mic-button.connecting {
  background: #f59e0b;
  animation: spin 1s linear infinite;
}

.audio-button.connected {
  background: #10b981;
}

@keyframes glow {
  0%, 100% { box-shadow: 0 0 10px #ef4444; }
  50% { box-shadow: 0 0 30px #ef4444, 0 0 50px #ef4444; }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.mic-icon,
.audio-icon {
  font-size: 28px;
}

.mic-info,
.audio-info {
  flex: 1;
}

.mic-status,
.audio-status {
  font-size: 16px;
  font-weight: 500;
}

.mic-duration {
  font-size: 24px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  opacity: 0.9;
}

/* 音量指示器 */
.level-meter {
  height: 6px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 3px;
  overflow: hidden;
}

.level-bar {
  height: 100%;
  background: linear-gradient(90deg, #10b981, #f59e0b, #ef4444);
  transition: width 0.1s ease;
}

/* 音量控制 */
.volume-control {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 8px;
}

.volume-control label {
  font-size: 12px;
  opacity: 0.8;
}

.volume-control input[type="range"] {
  flex: 1;
  height: 4px;
  -webkit-appearance: none;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 2px;
}

.volume-control input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: white;
  cursor: pointer;
}

.volume-control span {
  font-size: 12px;
  min-width: 36px;
  text-align: right;
}

/* 活动源 */
.active-sources {
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 8px;
}

.sources-label {
  font-size: 12px;
  opacity: 0.8;
  margin-bottom: 6px;
}

.source-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.source-tag {
  padding: 4px 10px;
  background: #10b981;
  border-radius: 12px;
  font-size: 12px;
}

/* 错误提示 */
.error-message {
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.8);
  border-radius: 8px;
  font-size: 12px;
}

.bridge-footer {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.2);
}

.bridge-tip {
  font-size: 12px;
  opacity: 0.7;
  text-align: center;
}
</style>
