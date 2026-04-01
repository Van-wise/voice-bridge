# Voice Bridge 📱↔️💻

> 把手机变成电脑的扩展外设 —— 用手机语音输入，文字实时同步到电脑并自动粘贴。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.x-green.svg)](https://flask.palletsprojects.com)

---

## 功能特点

| 功能 | 说明 |
|------|------|
| 📱 **手机语音输入** | 用手机系统语音输入法打字，内容自动同步到电脑 |
| ⚡ **自动粘贴** | 自动模式下，同步后直接粘贴到当前光标位置（Ctrl+V） |
| 📋 **双向同步** | 手机和电脑可以互相同步文本 |
| 📜 **历史记录** | 最多保存 200 条历史，支持搜索和一键恢复 |
| 🔄 **系统托盘** | 最小化到系统托盘，不占用任务栏 |
| 🌙 **休眠模式** | 长时间无操作自动降低资源占用 |
| 📱 **扫码连接** | 网页内点击二维码图标，手机扫码即连 |
| 🔌 **多设备** | 同时支持多台手机、多个浏览器标签页连接 |

---

## 快速开始

### 环境要求

- Windows 10/11（macOS/Linux 可运行但不支持自动粘贴）
- Python 3.8+

### 安装

```bash
# 克隆项目
git clone https://github.com/your-username/voice-bridge.git
cd voice-bridge

# 安装依赖
pip install -r requirements.txt
```

### 启动

**方式一：双击启动（推荐）**

直接双击项目根目录的 `启动.bat`：
- 自动检查并安装依赖
- 启动 Flask 服务（默认端口 8888）
- 创建系统托盘图标
- 自动打开浏览器控制台

**方式二：命令行**

```bash
python server/main.py
```

### 连接手机

1. 打开电脑端网页（`http://127.0.0.1:8888`）
2. 点击右上角 📱 二维码图标
3. 手机扫码，进入手机端页面
4. 在手机端输入框里用语音输入法说话，点击同步

---

## 使用说明

### 同步模式

**自动模式（默认）**

```
手机输入 → 同步 → 自动复制到剪贴板 → 自动粘贴（Ctrl+V）→ 清空输入框
```
适合：打字场景，同步后直接粘贴到正在编辑的地方。

**手动模式**

```
手机输入 → 同步 → （可选）复制到剪贴板
```
适合：只想把文字发过来，不需要自动粘贴。

### 设置项说明

| 设置 | 说明 |
|------|------|
| 同步模式 | 自动 / 手动 |
| 自动复制 | 同步后是否复制到剪贴板（手动模式下可选） |
| 自动清空 | 同步成功后自动清空输入框 |
| 历史记录 | 永久保存 / 仅本次会话 |
| 端口 | 服务监听端口（默认 8888，修改后需重启） |

> **注意**：开启自动清空时，"自动复制"会被同步锁定开启。

### 系统托盘

| 操作 | 功能 |
|------|------|
| 单击图标 | 显示 / 隐藏控制台窗口 |
| 双击图标 | 打开网页 |
| 右键菜单 | 显示/隐藏、打开网页、重启服务、退出 |

---

## 项目结构

```
voice-bridge/
├── launcher/
│   ├── launcher.py        # 托盘管理 + 服务启动 + 自动重启
│   └── icon.ico           # 系统托盘图标
├── server/
│   ├── main.py            # Flask 入口，启动参数处理
│   ├── app.py             # 全局状态管理（AppState）
│   ├── routes.py          # REST API 路由
│   ├── utils.py           # 日志工具
│   ├── logs/              # 运行日志（本地，不提交）
│   └── static/
│       ├── index.html     # 前端主页（含手机端/电脑端 UI）
│       └── qrcode.min.js  # 二维码生成库
├── 启动.bat               # Windows 一键启动脚本
├── requirements.txt       # Python 依赖
├── .gitignore
├── README.md
└── LICENSE
```

---

## API 文档

服务启动后监听 `http://127.0.0.1:8888`（端口可在设置中修改）。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/sync` | 同步文本（核心接口） |
| `GET/POST` | `/api/settings` | 读取 / 更新设置 |
| `GET` | `/api/poll` | 长轮询，获取最新事件和状态 |
| `POST` | `/api/clear` | 手动清空当前文本 |
| `GET` | `/api/history` | 获取历史记录（支持分页） |
| `POST` | `/api/history/clear` | 清空历史记录 |
| `GET` | `/api/stats` | 统计信息（同步次数、字符数等） |
| `GET` | `/api/info` | 服务信息（IP、端口） |
| `POST` | `/api/restart` | 重启服务 |

**同步接口示例**

```bash
curl -X POST http://127.0.0.1:8888/api/sync \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello World", "mode": "auto", "manual": true}'
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | Python + Flask |
| 前端 | 原生 HTML / CSS / JavaScript（无框架） |
| 通信 | HTTP 轮询（事件版本号追踪） |
| 托盘 | pystray + Pillow |
| 自动粘贴 | pyperclip + pyautogui |
| 日志 | colorama |

---

## 常见问题

**Q：自动粘贴不工作？**  
A：确认当前焦点在需要粘贴的输入框里，同步前不要切换窗口。macOS/Linux 不支持自动粘贴，只能手动 Ctrl+V。

**Q：手机无法访问？**  
A：确认手机和电脑在同一 Wi-Fi 下。防火墙需放行端口 8888（或你设置的端口）。

**Q：端口被占用？**  
A：在设置中修改端口号，点击重启生效。

**Q：依赖安装失败？**  
A：尝试 `pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`（国内镜像）。

---

## License

[MIT](LICENSE) © 2026
