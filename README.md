# WeChat Auto Bot

一些话：
花了几块大洋用deepseek flash 搓了个基于本地模型自动回复消息的机器人（登录一个小号），主要诉求是放在群聊里大家一起玩。反正是跑的本地小模型不耗分。
跑的模型是用的qwen 3.5 9B， 把thingking模式关了能快很多。基本可用状态。

刚开始写了很多bug，现在刚好能用。联系人切换功能还未实现，现在实现的就是单一群聊自动回复，只要自定义触发名字就行。

其他的功能再看吧，我先玩玩再说，加入人设之后可玩性很多。模型是支持图像识别的，还不知道怎么添加识别发送的图像。

有啥bug可以先聊一聊，我代码就学了个基础，主要还是靠deepseek来改，有啥不对的地方大佬可以多提，谢谢大家了。以下都是ai自己写的了。


<img width="506" height="344" alt="20d85bf0-984c-4a0e-88f7-92c3f16c6818" src="https://github.com/user-attachments/assets/7ff2d3dd-3e06-45c1-a57b-b70d98ce6884" />

基于 **PyAutoGUI** + **LLM Vision** 的微信自动对话机器人。通过模拟真人操作（鼠标缓动、随机延迟、逐字输入）绕过微信检测，利用大语言模型实现智能回复。

## 功能特性

### 核心功能
- **智能回复** — 集成 LM Studio / OpenAI 兼容 API，支持多模型切换
- **三种消息读取方式**：
  - `llm_vision` — LLM 视觉模型截图识别（默认，推荐）
  - XXXXXXX`clipboard` — 剪贴板读取（最快速）无法使用
  - XXXXXXX`ocr` — Tesseract OCR 识别（实验性）效果不好
- **@提及触发** — 群聊中通过 `@触发词` 激活回复，支持模糊匹配（如 `@豆咪` 可匹配 `@豆味`）
- **联系人白名单/黑名单** — 控制哪些联系人可以触发自动回复
- **GUI 控制面板** — 基于 CustomTkinter 的可视化管理界面

### 反检测机制
- **真人鼠标模拟** — 缓动曲线（easeOutQuad）+ 位置抖动，非瞬移非精确点击
- **随机时间延迟** — 阅读延迟 1-3s、思考延迟 2-8s、逐字输入间隔可配置
- **分段发送** — 长消息拆分为多条逐条发送，段间随机暂停
- **随机跳过** — 概率性不回复，模拟真人遗漏消息的行为
- **后台活动模拟** — 随机执行滚动/切换会话等操作，避免长时间无操作被检测
- **空闲时段** — 可配置免打扰时段，期间不响应

### 系统健壮性
- **截图哈希快速检测** — MD5 比较避免重复触发 LLM Vision
- **智能去重** — `_last_replied` 内容追踪 + @mention 归一化，防止非确定性重复回复
- **窗口状态监控** — 窗口消失自动停止，恢复后继续运行
- **桌面内容检测** — 读取到桌面内容时立即停止所有任务

## 问题修复记录

### 修复：重复回复 Bug（v2）

**现象：** 同一 `@豆咪` 消息被回复两次。

**根因：** LLM Vision 非确定性导致截图读取结果不一致。同一张截图在一次调用中识别为 `@豆味 能不能接受图片`，下一次识别为 `@豆咪 能不能接受图片`。`_last_replied` 精确对比因 `豆咪 ≠ 豆味` 而失效。

**修复：** 在 `wechat_driver_pyautogui.py` 的 `get_new_messages()` 返回前，通过正则将模糊匹配到的 `@变体词` 归一化为标准触发词：

```python
clean_msg = re.sub(
    rf'@{re.escape(self._mention_trigger)}[\w一-鿿]*',
    f'@{self._mention_trigger}',
    clean_msg
)
```

效果：`@豆味` → `@豆咪`，两次读取结果一致 → 去重成功。

### 修复：Bot 不读取消息（v1）

**现象：** Bot 启动后始终收不到新消息。

**根因：** `bot_engine.py` 中 `_create_driver()` 在 `_init_llm()` 之前调用，传入了 `None` 作为 `llm` 参数。驱动依赖 LLM 进行 Vision 识别，为 `None` 时跳过消息读取。

**修复：** 交换初始化顺序：

```python
# 修复前
self.driver = self._create_driver()
self._init_llm()

# 修复后
self._init_llm()
self.driver = self._create_driver()
```

### 修复：读取旧消息（v1）

**现象：** 每次轮询都重复处理已回复过的消息。

**根因：** 全文本 diff 比较（`_extract_new_content`）在 LLM 非确定性输出下不稳定。

**修复：** 改用 @mention 行集合比较 + 截图哈希变化检测。

### 修复：模糊匹配双重触发（v2）

**现象：** 设置模糊匹配后，同一条 `@豆味` 消息触发两次回复。

**根因：** 同上 Vision 非确定性问题。`_last_replied` 精确字符串比较无法识别。

**修复：** 同上 @mention 归一化正则替换。

## 项目结构

```
wechat-auto-bot/
├── main.py                       # 入口：CLI/GUI 启动器
├── bot_engine.py                 # 对话引擎主循环
├── wechat_driver_pyautogui.py    # PyAutoGUI 驱动层（核心）
├── wechat_driver.py              # wxauto 驱动层（备用）
├── llm_client.py                 # LLM API 客户端
├── anti_detect.py                # 反检测控制器
├── conversation.py               # 对话上下文管理
├── config_manager.py             # 配置读写
├── gui.py                        # CustomTkinter 控制面板
├── build.py                      # PyInstaller 打包脚本
├── config.example.json           # 配置模板（拷贝为 config.json 使用）
├── requirements.txt              # 依赖列表
└── dist/                         # 打包输出目录
    └── WeChatAutoBot.exe         # 单文件可执行文件
```

## 快速开始

### 前置条件

1. **微信** — 已安装并登录（需微信 4.x 版本）
2. **LM Studio** — 运行 LLM 模型并开启 API 服务（或其他 OpenAI 兼容 API）
3. **Python 3.9+**

### 安装

```bash
# 克隆仓库
git clone https://github.com/YOUR_USERNAME/wechat-auto-bot.git
cd wechat-auto-bot

# 安装依赖
pip install -r requirements.txt

# 创建配置文件
cp config.example.json config.json
# 编辑 config.json 填写你的配置（LM Studio 地址、触发词、联系人等）
```

### 运行

```bash
# CLI 模式
python main.py

# GUI 模式
python main.py --gui

# 测试微信连接
python main.py --test-wechat

# 测试 LLM 连接
python main.py --test-llm
```

### 打包为 exe

```bash
pip install pyinstaller
python build.py
```

生成的 exe 在 `dist/WeChatAutoBot.exe`，拷贝到任意电脑即可运行（无需 Python）。

**可选：UPX 压缩** — 从 https://github.com/upx/upx/releases 下载 UPX，解压到 `C:\upx`，build.py 会自动使用 UPX 减少 exe 体积（约 80MB → 24MB）。

## 配置说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `llm.base_url` | LM Studio API 地址 | `http://localhost:1234/v1` |
| `llm.model` | 使用的模型名 | `""`（服务端默认） |
| `bot.mention_trigger` | @触发词 | `"bot"` |
| `bot.contacts` | 白名单联系人列表 | `[]` |
| `bot.reading_method` | 消息读取方式：`clipboard` / `llm_vision` / `ocr` | `"llm_vision"` |
| `bot.poll_interval_seconds` | 轮询间隔 | `3` |
| `anti_detect.enabled` | 反检测总开关 | `true` |

完整配置项见 [config.example.json](config.example.json)。

## 技术栈

- **Python 3.9+**
- **PyAutoGUI** — GUI 自动化操作
- **CustomTkinter** — 图形界面
- **OpenAI Python SDK** — LLM API 调用
- **PyWin32** — Windows 窗口管理
- **Pillow** — 截图处理
- **PyInstaller** — 打包为单文件 exe

## 许可

MIT License
