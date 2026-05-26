# WeChat Auto Bot

花了几块大洋用 deepseek flash 搓了一个基于本地模型自动回复消息的机器人，主要诉求是放在群聊里大家一起玩。反正跑的本地小模型不耗分。跑的模型用的 qwen 3.5 9B，把 thinking 模式关了能快很多，基本可用状态。

当前支持 **PyAutoGUI**（图像识别+模拟操作）和 **UIA hybrid**（后台自动化）两种驱动模式。

## 功能特性

### 核心功能
- **智能回复** — 集成 LM Studio / OpenAI 兼容 API，支持多模型切换
- **三种消息读取方式**（PyAutoGUI 模式）：
  - `llm_vision` — LLM 视觉模型截图识别（默认，推荐）
  - `clipboard` — 剪贴板读取
  - `ocr` — Tesseract OCR 识别（实验性）
- **UIA 后台读取**（hybrid 模式）— 通过 Windows UIA 接口直接读取，无需前台焦点
- **@提及触发** — 群聊中通过 `@触发词` 激活回复，支持模糊匹配
- **联系人白名单/黑名单** — 控制哪些联系人可以触发自动回复
- **GUI 控制面板** — 基于 CustomTkinter 的可视化管理界面

### 反检测机制
- **真人鼠标模拟** — 缓动曲线 + 位置抖动
- **随机时间延迟** — 阅读/思考/逐字输入延迟可配置
- **分段发送** — 长消息拆分为多条逐条发送
- **随机跳过** — 概率性不回复
- **后台活动模拟** — 随机滚动/切换等操作
- **空闲时段/免打扰** — 可配置

### 系统健壮性
- **截图哈希检测** — MD5 比较避免重复触发 LLM Vision
- **智能去重** — @mention 归一化，防止非确定性重复回复
- **窗口状态监控** — 窗口消失自动停止
- **桌面内容检测** — 读取到桌面内容时立即停止

## 驱动模式

### Hybrid 驱动（推荐）
`uia_sidecar.exe`（C# UIA 客户端）后台读取/发送消息，无需前台焦点。

**首次使用前需开启一次 Windows 讲述人**：
1. 按 `Win+Ctrl+Enter` 启动讲述人
2. 完全退出并重启微信
3. 运行 `python main.py --test-wechat` 确认 UIA 正常
4. 确认后可关闭讲述人（后续无需再开）

**配置方式**：编辑 `config.json`，设置 `"driver": "hybrid"`

### PyAutoGUI 驱动
传统图像识别 + 剪贴板方案，需微信窗口在前台。

**配置方式**：编辑 `config.json`，设置 `"driver": "pyautogui"`

## 快速开始

### 前置条件
1. **微信** — 已安装并登录（需微信 4.x 版本）
2. **LM Studio** — 运行 LLM 模型并开启 API 服务
3. **Python 3.9+**

### 安装
```bash
git clone https://github.com/akiyou/wechat-auto-bot.git
cd wechat-auto-bot
pip install -r requirements.txt
cp config.example.json config.json
# 编辑 config.json 填写配置
```

### 运行
```bash
# GUI 模式
python main.py --gui

# CLI 模式
python main.py

# 测试微信连接
python main.py --test-wechat

# 测试 LLM 连接
python main.py --test-llm

# 查看当前配置
python main.py --show-config
```

### 打包为 exe
```bash
pip install pyinstaller
python build.py
```

## 配置说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `bot.driver` | 驱动模式：`hybrid` / `pyautogui` / `wxauto` | `hybrid` |
| `bot.mode` | 回复模式：`whitelist` / `all` | `whitelist` |
| `bot.mention_trigger` | @触发词 | `豆咪` |
| `bot.poll_interval_seconds` | 轮询间隔(秒) | `2` |
| `llm.base_url` | LLM API 地址 | `http://localhost:1234/v1` |
| `llm.model` | 模型名 | `""` |

完整配置项见 [config.example.json](config.example.json)。

## 问题修复记录

### 修复：UIA 树无法读取（v3）
**现象：** hybrid 模式下 UIA 只能看到窗口框架，找不到消息列表和输入框。
**根因：** 微信 4.0+ 使用 Qt 自绘框架，默认不暴露完整 UIA 控件树。
**修复：** 开启 Windows 讲述人后重启微信即可。后续 sidecar 作为 UIA 客户端会自动维持连接。

### 修复：重复回复 Bug（v2）
**现象：** 同一 `@豆咪` 消息被回复两次。
**根因：** LLM Vision 非确定性导致截图读取结果不一致。
**修复：** @mention 归一化正则替换。

### 修复：Bot 不读取消息（v1）
**现象：** Bot 启动后始终收不到新消息。
**根因：** `_create_driver()` 在 `_init_llm()` 之前调用。
**修复：** 交换初始化顺序。

## 项目结构

```
wechat-auto-bot/
├── main.py                       # 入口
├── gui.py                        # CustomTkinter 控制面板
├── bot_engine.py                 # 对话引擎主循环
├── wechat_driver_hybrid.py       # UIA 混合驱动
├── wechat_driver_pyautogui.py    # PyAutoGUI 驱动
├── wechat_driver.py              # wxauto 驱动
├── uia_sidecar.cs / .exe        # C# UIA 客户端
├── llm_client.py                 # LLM API 客户端
├── anti_detect.py                # 反检测控制器
├── conversation.py               # 对话上下文管理
├── config_manager.py             # 配置读写
├── build.py                      # PyInstaller 打包脚本
├── config.example.json           # 配置模板
├── requirements.txt              # 依赖列表
└── WeChatAutoBot.spec            # PyInstaller spec
```

## 技术栈
- Python 3.9+
- PyAutoGUI / Windows UIA (C#)
- CustomTkinter
- OpenAI Python SDK
- PyWin32
- Pillow
- PyInstaller

## 许可
MIT License
