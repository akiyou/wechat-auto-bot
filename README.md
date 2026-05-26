# WeChat Auto Bot — 微信自动对话机器人

基于 UIA (hybrid) 驱动的微信自动回复机器人，支持 LLM 对话、反检测模拟。

## 环境要求

- Windows 10+
- Python 3.9+
- 微信 PC 版 4.0+（使用 Qt 框架的版本）
- （可选）LM Studio 或其他 OpenAI 兼容 API

## 安装

```bash
pip install -r requirements.txt
```

注意 `uia_sidecar.exe` 是预编译的 C# UIA 客户端。如需重新编译：

```bash
csc -target:exe -out:uia_sidecar.exe -reference:UIAutomationClient -reference:UIAutomationTypes -reference:UIAutomationProvider -reference:WindowsBase uia_sidecar.cs
```

## UIA 初始化（重要）

微信 4.0+ 使用 Qt 自绘框架，默认不暴露完整 UIA 控件树。**首次使用前需要执行以下操作一次**：

1. 按 `Win+Ctrl+Enter` 启动 **Windows 讲述人 (Narrator)**
2. **完全退出微信并重新启动、登录**
3. 运行测试确认 UIA 正常：`python main.py --test-wechat`
4. 确认消息列表和输入框都能读取后，可关闭讲述人

> 此后 sidecar 作为 UIA 客户端会保持连接，无需再次开启讲述人。

## 使用方式

```bash
# 图形界面
python main.py --gui

# CLI 模式（直接启动机器人）
python main.py

# 测试微信连接
python main.py --test-wechat

# 测试 LLM 连接
python main.py --test-llm

# 查看当前配置
python main.py --show-config
```

## 配置

编辑 `config.json`，主要配置项：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `bot.driver` | 驱动模式: `hybrid`(推荐), `pyautogui`, `wxauto` | `hybrid` |
| `bot.mode` | 回复模式: `whitelist`(白名单), `all`(全部) | `whitelist` |
| `bot.contacts` | 联系人白名单 | `[]` |
| `bot.mention_trigger` | @触发词 | `豆咪` |
| `bot.poll_interval_seconds` | 轮询间隔(秒) | `2` |
| `llm.base_url` | LLM API 地址 | `http://192.168.110.242:1234/v1` |
| `llm.model` | 模型名称 | `qwen/qwen3.5-9b` |
| `anti_detect` | 阅读/回复延迟、打字速度等反检测参数 | — |

## 驱动说明

### Hybrid 驱动（推荐）

`uia_sidecar.exe`（C# UIA 客户端）+ `win32gui` 混合方案：
- **读取消息**：UIA 后台读取当前聊天窗口
- **发送消息**：UIA ValuePattern 设置文字 + InvokePattern 点击发送
- **切换聊天**：UIA 搜索框 + 会话列表点击
- **会话列表**：UIA 实时获取

优点：无需前台焦点，完全后台运行。

### PyAutoGUI 驱动

传统图像识别 + 剪贴板方案，作为 hybrid 的备选。

## 反检测

支持模拟人类行为：
- 随机阅读/回复延迟
- 逐字模拟打字速度
- 分段发送长消息
- 随机跳过率
- 活动模拟（后台随机操作）
- 随机空闲时段
- 免打扰时段

## 项目结构

```
wechat-auto-bo3t/
├── main.py                  # 入口
├── gui.py                   # CustomTkinter 图形界面
├── bot_engine.py            # 对话引擎主循环
├── config_manager.py        # 配置管理
├── llm_client.py            # LLM API 客户端
├── anti_detect.py           # 反检测逻辑
├── conversation.py          # 对话记忆管理
├── wechat_driver_hybrid.py  # UIA 混合驱动
├── wechat_driver_pyautogui.py # PyAutoGUI 驱动
├── wechat_driver.py         # wxauto 驱动
├── uia_sidecar.cs / .exe   # C# UIA 客户端
└── config.json              # 配置文件
```
