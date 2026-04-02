import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { initErrorHandler } from './utils/errorHandlerInit'
import './utils/debug'  // 引入调试模块

// 获取 Vue 应用实例
const app = createApp(App)

// 保存应用实例到 window，供错误处理使用
;(window as any).__VueApp__ = app

// 初始化全局错误处理
initErrorHandler()

app.mount('#app')
