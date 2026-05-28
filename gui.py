"""WeChat Auto Bot — CustomTkinter 图形界面"""

import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog
from typing import Optional

import customtkinter as ctk

from config_manager import Config
from bot_engine import BotEngine
from llm_client import LLMClient

logger = logging.getLogger("wechat_bot")


# ═══════════════════════════════════════════════════════
#  Log Handler — 将日志管道到 UI 队列
# ═══════════════════════════════════════════════════════

class LogQueueHandler(logging.Handler):
    """将日志记录通过线程安全队列发给 GUI"""

    def __init__(self, level_filter: str = "ALL"):
        super().__init__()
        self.queue: queue.Queue = queue.Queue()
        self._level_filter = level_filter

    def emit(self, record: logging.LogRecord) -> None:
        levels = {"ALL": 0, "DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
        min_level = levels.get(self._level_filter, 0)
        if record.levelno >= min_level:
            self.queue.put(self.format(record))

    def set_level_filter(self, name: str) -> None:
        self._level_filter = name


# ═══════════════════════════════════════════════════════
#  Main Application
# ═══════════════════════════════════════════════════════

class BotGUI(ctk.CTk):
    """微信自动对话机器人主窗口"""

    # ── 主题色 ────────────────────────────────────────
    GREEN = "#2ecc71"
    RED = "#e74c3c"
    GRAY = "#7f8c8d"
    ORANGE = "#f39c12"

    def __init__(self, config_path: Optional[str] = None):
        super().__init__()

        # ── 窗口基础 ──
        self.title("WeChat Auto Bot — 控制面板")
        self.geometry("1020x760")
        self.minsize(800, 600)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── 配置 ──
        self._config_path = config_path
        self.config = Config(config_path)

        # ── Bot 引擎 ──
        self._engine: Optional[BotEngine] = None
        self._engine_thread: Optional[threading.Thread] = None

        # ── 数据 ──
        self._contacts: list[str] = []
        self._models: list[str] = []

        # ── 日志 ──
        self._log_handler = LogQueueHandler()
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )
        logging.getLogger("wechat_bot").addHandler(self._log_handler)

        # ── 构建界面 ──
        self._build_ui()
        self._load_config_to_ui()
        self._update_status()

        # ── 日志轮询 ──
        self.after(100, self._poll_logs)

        # ── 全局快捷键 ──
        self.bind_all("<Control-Shift-s>", self._hotkey_stop)
        self.bind_all("<Escape>", self._hotkey_escape)

    # ═══════════════════════════════════════════════════
    #  UI 构建
    # ═══════════════════════════════════════════════════

    def _build_ui(self) -> None:
        """构建完整界面"""
        # ── 顶部状态栏 ──
        self._build_status_bar()

        # ── 标签页 ──
        self.tab_view = ctk.CTkTabview(self, anchor="nw")
        self.tab_view.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        tab_control = self.tab_view.add("控制面板")
        tab_llm = self.tab_view.add("LLM 设置")
        tab_anti = self.tab_view.add("反检测")
        tab_logs = self.tab_view.add("日志")

        self._build_control_panel(tab_control)
        self._build_llm_settings(tab_llm)
        self._build_anti_detect(tab_anti)
        self._build_logs(tab_logs)

    # ── 状态栏 ────────────────────────────────────────

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, height=40, corner_radius=0,
                           fg_color=("gray90", "gray20"))
        bar.pack(fill="x", padx=0, pady=0)
        bar.pack_propagate(False)

        ctk.CTkLabel(bar, text="状态:", font=("", 13, "bold")).pack(side="left", padx=(15, 5))

        self._badge_bot = ctk.CTkLabel(bar, text="● STOPPED", fg_color=self.RED,
                                        text_color="white", corner_radius=6,
                                        width=100)
        self._badge_bot.pack(side="left", padx=5)

        self._badge_wechat = ctk.CTkLabel(bar, text="● ?", fg_color=self.GRAY,
                                           text_color="white", corner_radius=6,
                                           width=100)
        self._badge_wechat.pack(side="left", padx=5)

        self._badge_llm = ctk.CTkLabel(bar, text="● ?", fg_color=self.GRAY,
                                        text_color="white", corner_radius=6,
                                        width=100)
        self._badge_llm.pack(side="left", padx=5)

    def _update_status(self, bot_status: str = "STOPPED",
                       wechat_status: str = "?",
                       llm_status: str = "?") -> None:
        colors = {"RUNNING": self.GREEN, "STOPPED": self.RED,
                   "CONNECTED": self.GREEN, "DISCONNECTED": self.RED,
                   "ENABLED": self.GREEN, "DISABLED": self.GRAY}
        self._badge_bot.configure(text=f"● {bot_status}",
                                  fg_color=colors.get(bot_status, self.GRAY))
        self._badge_wechat.configure(text=f"● {wechat_status}",
                                     fg_color=colors.get(wechat_status, self.GRAY))
        self._badge_llm.configure(text=f"● {llm_status}",
                                  fg_color=colors.get(llm_status, self.GRAY))

    # ── Tab 0: 控制面板 ──────────────────────────────

    def _build_control_panel(self, parent: ctk.CTkFrame) -> None:
        # 左列
        left = ctk.CTkFrame(parent)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5), pady=5)

        ctk.CTkLabel(left, text="机器人控制", font=("", 15, "bold")).pack(anchor="w", padx=10, pady=(10, 5))

        self._btn_toggle = ctk.CTkButton(left, text="▶ 启动 Bot", fg_color=self.GREEN,
                                          hover_color="#27ae60", command=self._toggle_bot,
                                          height=40, font=("", 14, "bold"))
        self._btn_toggle.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(left, text="快捷键: Ctrl+Shift+S 停止 Bot",
                     font=("", 11), text_color="gray").pack(anchor="w", padx=12, pady=(0, 5))

        # 模式
        frame_mode = ctk.CTkFrame(left)
        frame_mode.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_mode, text="回复模式:").pack(side="left")
        self._mode_var = tk.StringVar(value="whitelist")
        ctk.CTkOptionMenu(frame_mode, variable=self._mode_var,
                          values=["whitelist", "all"]).pack(side="right")

        # 轮询间隔
        frame_poll = ctk.CTkFrame(left)
        frame_poll.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_poll, text="轮询间隔(秒):").pack(side="left")
        self._poll_var = tk.StringVar(value="3")
        ctk.CTkEntry(frame_poll, textvariable=self._poll_var, width=60).pack(side="right")

        # 触发词
        frame_trigger = ctk.CTkFrame(left)
        frame_trigger.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_trigger, text="@触发词:").pack(anchor="w")
        self._trigger_var = tk.StringVar(value="豆咪")
        ctk.CTkEntry(frame_trigger, textvariable=self._trigger_var).pack(fill="x", pady=(2, 0))

        # 回复前缀
        frame_prefix = ctk.CTkFrame(left)
        frame_prefix.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_prefix, text="回复前缀:").pack(anchor="w")
        self._prefix_var = tk.StringVar(value="")
        ctk.CTkEntry(frame_prefix, textvariable=self._prefix_var).pack(fill="x", pady=(2, 0))

        # 消息读取方式
        frame_read = ctk.CTkFrame(left)
        frame_read.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_read, text="消息读取方式:").pack(side="left")
        self._reading_method_var = tk.StringVar(value="llm_vision")
        ctk.CTkOptionMenu(frame_read, variable=self._reading_method_var,
                          values=["clipboard", "ocr", "llm_vision"]).pack(side="right")

        # 免打扰时段
        frame_quiet = ctk.CTkFrame(left)
        frame_quiet.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_quiet, text="免打扰时段:").pack(anchor="w")
        row = ctk.CTkFrame(frame_quiet, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text="开始").pack(side="left")
        self._quiet_start_var = tk.StringVar(value="")
        ctk.CTkEntry(row, textvariable=self._quiet_start_var, width=70).pack(side="left", padx=5)
        ctk.CTkLabel(row, text="结束").pack(side="left")
        self._quiet_end_var = tk.StringVar(value="")
        ctk.CTkEntry(row, textvariable=self._quiet_end_var, width=70).pack(side="left", padx=5)

        # 测试按钮
        frame_tests = ctk.CTkFrame(left)
        frame_tests.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkButton(frame_tests, text="🔌 测试微信", command=self._test_wechat).pack(
            side="left", padx=(0, 5), expand=True, fill="x")
        ctk.CTkButton(frame_tests, text="🤖 测试 LLM", command=self._test_llm).pack(
            side="left", expand=True, fill="x")

        ctk.CTkButton(left, text="💾 保存配置", command=self._save_config,
                      fg_color="#2980b9", hover_color="#2471a3").pack(
            fill="x", padx=10, pady=(5, 10))

        # 右列 — 联系人管理
        right = ctk.CTkFrame(parent)
        right.pack(side="right", fill="both", expand=True, padx=(5, 0), pady=5)

        ctk.CTkLabel(right, text="联系人白名单", font=("", 15, "bold")).pack(anchor="w", padx=10, pady=(10, 5))

        self._contact_listbox = tk.Listbox(right, height=10, exportselection=False)
        self._contact_listbox.pack(fill="both", expand=True, padx=10)

        frame_add = ctk.CTkFrame(right)
        frame_add.pack(fill="x", padx=10, pady=5)
        self._contact_entry = ctk.CTkEntry(frame_add, placeholder_text="输入联系人名称")
        self._contact_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(frame_add, text="添加", width=50, command=self._add_contact).pack(side="right", padx=(5, 0))

        frame_ctrl = ctk.CTkFrame(right)
        frame_ctrl.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(frame_ctrl, text="删除选中", command=self._remove_contact).pack(side="left", padx=(0, 5))
        ctk.CTkButton(frame_ctrl, text="从微信加载", command=self._load_contacts_from_wechat).pack(side="left")

    # ── Tab 1: LLM 设置 ──────────────────────────────

    def _build_llm_settings(self, parent: ctk.CTkFrame) -> None:
        # 需要 scrollable 因为内容较多
        scroll = ctk.CTkScrollableFrame(parent)
        scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # 启用
        frame_enable = ctk.CTkFrame(scroll)
        frame_enable.pack(fill="x", padx=10, pady=5)
        self._llm_enabled_var = tk.BooleanVar(value=False)
        ctk.CTkSwitch(frame_enable, text="启用 LLM", variable=self._llm_enabled_var,
                       command=self._on_llm_enabled_toggle).pack(side="left")
        self._llm_enabled_label = ctk.CTkLabel(frame_enable, text="(关闭后将使用 echo 回复)")
        self._llm_enabled_label.pack(side="left", padx=10)

        # Provider 选择
        frame_provider = ctk.CTkFrame(scroll)
        frame_provider.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_provider, text="Provider:").pack(anchor="w")
        self._llm_provider_var = tk.StringVar(value="openai_compatible")
        self._llm_provider_menu = ctk.CTkOptionMenu(
            frame_provider, variable=self._llm_provider_var,
            values=["openai_compatible", "deepseek", "deepseek-anthropic"],
            command=self._on_provider_change)
        self._llm_provider_menu.pack(fill="x", pady=(2, 0))
        self._llm_provider_hint = ctk.CTkLabel(
            frame_provider, text="", font=("", 11), text_color="gray")
        self._llm_provider_hint.pack(anchor="w", pady=(2, 0))

        # Base URL
        frame_url = ctk.CTkFrame(scroll)
        frame_url.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_url, text="Base URL:").pack(anchor="w")
        self._llm_url_var = tk.StringVar(value="http://localhost:1234/v1")
        self._llm_url_var.trace_add("write", lambda *a: self.after(500, self._fetch_models))
        self._llm_url_entry = ctk.CTkEntry(frame_url, textvariable=self._llm_url_var)
        self._llm_url_entry.pack(fill="x", pady=(2, 0))

        # API Key
        frame_key = ctk.CTkFrame(scroll)
        frame_key.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_key, text="API Key:").pack(anchor="w")
        self._llm_key_var = tk.StringVar(value="")
        self._llm_key_entry = ctk.CTkEntry(frame_key, textvariable=self._llm_key_var, show="*")
        self._llm_key_entry.pack(fill="x", pady=(2, 0))

        # 模型选择
        frame_model = ctk.CTkFrame(scroll)
        frame_model.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_model, text="模型:").pack(anchor="w")
        row = ctk.CTkFrame(frame_model, fg_color="transparent")
        row.pack(fill="x")
        self._llm_model_var = tk.StringVar(value="")
        self._model_menu = ctk.CTkOptionMenu(row, variable=self._llm_model_var,
                                              values=["(自动)"], dynamic_resizing=False)
        self._model_menu.pack(side="left", fill="x", expand=True)
        self._btn_refresh_models = ctk.CTkButton(row, text="🔄 刷新", width=70,
                                                   command=self._fetch_models)
        self._btn_refresh_models.pack(side="right", padx=(5, 0))

        # Temperature
        frame_temp = ctk.CTkFrame(scroll)
        frame_temp.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_temp, text="Temperature:").pack(anchor="w")
        row = ctk.CTkFrame(frame_temp, fg_color="transparent")
        row.pack(fill="x")
        self._llm_temp_var = tk.DoubleVar(value=0.7)
        self._llm_temp_slider = ctk.CTkSlider(row, variable=self._llm_temp_var, from_=0, to=2,
                                               number_of_steps=40)
        self._llm_temp_slider.pack(side="left", fill="x", expand=True)
        self._llm_temp_label = ctk.CTkLabel(row, text="0.70", width=40)
        self._llm_temp_label.pack(side="right", padx=(10, 0))

        # Max Tokens
        frame_maxtok = ctk.CTkFrame(scroll)
        frame_maxtok.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_maxtok, text="Max Tokens:").pack(anchor="w")
        row = ctk.CTkFrame(frame_maxtok, fg_color="transparent")
        row.pack(fill="x")
        self._llm_maxtok_var = tk.IntVar(value=1024)
        self._llm_maxtok_slider = ctk.CTkSlider(row, variable=self._llm_maxtok_var, from_=64, to=8192,
                                                 number_of_steps=128)
        self._llm_maxtok_slider.pack(side="left", fill="x", expand=True)
        self._llm_maxtok_label = ctk.CTkLabel(row, text="1024", width=50)
        self._llm_maxtok_label.pack(side="right", padx=(10, 0))

        # System Prompt
        frame_sys = ctk.CTkFrame(scroll)
        frame_sys.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_sys, text="System Prompt:").pack(anchor="w")
        self._llm_sysprompt = ctk.CTkTextbox(frame_sys, height=100)
        self._llm_sysprompt.pack(fill="x", pady=(2, 0))
        self._llm_sysprompt.insert("1.0", "")

        # 对话记忆
        frame_conv = ctk.CTkFrame(scroll)
        frame_conv.pack(fill="x", padx=10, pady=5)
        self._conv_enabled_var = tk.BooleanVar(value=False)
        ctk.CTkSwitch(frame_conv, text="对话记忆", variable=self._conv_enabled_var).pack(side="left")

        row = ctk.CTkFrame(frame_conv, fg_color="transparent")
        row.pack(side="right")
        self._conv_history_var = tk.StringVar(value="6")
        ctk.CTkEntry(row, textvariable=self._conv_history_var, width=40).pack(side="left")
        ctk.CTkLabel(row, text="轮").pack(side="left", padx=(2, 10))
        self._conv_tokens_var = tk.StringVar(value="2048")
        ctk.CTkEntry(row, textvariable=self._conv_tokens_var, width=50).pack(side="left")
        ctk.CTkLabel(row, text="token").pack(side="left", padx=(2, 0))

        # 灰化初始状态
        self._set_llm_widgets_state(False)

    def _on_llm_enabled_toggle(self) -> None:
        self._set_llm_widgets_state(self._llm_enabled_var.get())

    def _set_llm_widgets_state(self, enabled: bool) -> None:
        """启用/灰化 LLM 设置区的所有控件"""
        state = "normal" if enabled else "disabled"
        for w in [self._llm_provider_menu, self._llm_url_entry, self._llm_key_entry,
                  self._model_menu, self._btn_refresh_models,
                  self._llm_temp_slider, self._llm_maxtok_slider,
                  self._llm_sysprompt]:
            try:
                w.configure(state=state)
            except Exception:
                pass
        # Provider 特定状态
        if enabled:
            self._apply_provider_ui()

    def _on_provider_change(self, choice: str = None) -> None:
        """Provider 切换时调整 UI"""
        self._apply_provider_ui()
        p = self._llm_provider_var.get()
        models_preset = {
            "deepseek": "deepseek-chat",
            "deepseek-anthropic": "deepseek-v4-flash",
        }
        if p in models_preset:
            self._llm_model_var.set(models_preset[p])
        elif p == "openai_compatible":
            self._llm_model_var.set("")
            self.after(500, self._fetch_models)

    def _apply_provider_ui(self) -> None:
        """根据当前 provider 调整控件状态"""
        p = self._llm_provider_var.get()
        url_enabled = self._llm_enabled_var.get()
        hints = {
            "openai_compatible": "适用于 LM Studio、OpenAI、Groq、DeepSeek 等 OpenAI 兼容 API",
            "deepseek": "DeepSeek OpenAI 兼容接口 → https://api.deepseek.com/v1",
            "deepseek-anthropic": "DeepSeek Anthropic 兼容接口 → https://api.deepseek.com/anthropic",
        }
        self._llm_provider_hint.configure(text=hints.get(p, ""))

        if p in ("deepseek", "deepseek-anthropic"):
            self._llm_url_entry.configure(state="disabled")
        else:
            self._llm_url_entry.configure(state="normal" if url_enabled else "disabled")

    # ── Tab 2: 反检测 ────────────────────────────────

    def _build_anti_detect(self, parent: ctk.CTkFrame) -> None:
        scroll = ctk.CTkScrollableFrame(parent)
        scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # 总开关
        self._ad_enabled_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(scroll, text="启用反检测", variable=self._ad_enabled_var,
                       command=self._on_ad_toggle).pack(anchor="w", padx=10, pady=5)

        self._ad_frame = ctk.CTkFrame(scroll)
        self._ad_frame.pack(fill="x", padx=10, pady=5)

        # Helper to create min/max slider pairs
        def make_slider_pair(parent_frame, label, var_min, var_max,
                             from_=0, to=10, step=0.1, digits=1):
            frame = ctk.CTkFrame(parent_frame)
            frame.pack(fill="x", pady=3)
            ctk.CTkLabel(frame, text=label, width=180).pack(side="left")

            var_min.trace_add("write", lambda *a: _sync_pair(var_min, var_max))
            var_max.trace_add("write", lambda *a: _sync_pair(var_min, var_max))

            ctk.CTkLabel(frame, text="min").pack(side="left")
            s_min = ctk.CTkSlider(frame, variable=var_min, from_=from_, to=to,
                                   number_of_steps=int((to - from_) / step))
            s_min.pack(side="left", fill="x", expand=True, padx=5)

            min_label = ctk.CTkLabel(frame, text=f"{var_min.get():.{digits}f}", width=40)
            min_label.pack(side="left")

            ctk.CTkLabel(frame, text="max").pack(side="left", padx=(10, 0))
            s_max = ctk.CTkSlider(frame, variable=var_max, from_=from_, to=to,
                                   number_of_steps=int((to - from_) / step))
            s_max.pack(side="left", fill="x", expand=True, padx=5)

            max_label = ctk.CTkLabel(frame, text=f"{var_max.get():.{digits}f}", width=40)
            max_label.pack(side="left")

            # 实时更新标签
            def update_labels(*a):
                min_label.configure(text=f"{var_min.get():.{digits}f}")
                max_label.configure(text=f"{var_max.get():.{digits}f}")
            var_min.trace_add("write", update_labels)
            var_max.trace_add("write", update_labels)

        def make_single_slider(parent_frame, label, var, from_=0, to=100,
                               step=1, fmt=".0f"):
            frame = ctk.CTkFrame(parent_frame)
            frame.pack(fill="x", pady=3)
            ctk.CTkLabel(frame, text=label, width=180).pack(side="left")
            s = ctk.CTkSlider(frame, variable=var, from_=from_, to=to,
                               number_of_steps=int((to - from_) / step))
            s.pack(side="left", fill="x", expand=True, padx=5)
            lbl = ctk.CTkLabel(frame, text=f"{var.get():{fmt}}", width=50)
            lbl.pack(side="right")
            var.trace_add("write", lambda *a: lbl.configure(text=f"{var.get():{fmt}}"))

        def make_entry_row(parent_frame, label, var, width=70):
            frame = ctk.CTkFrame(parent_frame)
            frame.pack(fill="x", pady=3)
            ctk.CTkLabel(frame, text=label, width=180).pack(side="left")
            ctk.CTkEntry(frame, textvariable=var, width=width).pack(side="right")

        # 收集变量供 _save_config 使用
        self._ad_read_min = tk.DoubleVar(value=1.0)
        self._ad_read_max = tk.DoubleVar(value=3.0)
        self._ad_reply_min = tk.DoubleVar(value=2.0)
        self._ad_reply_max = tk.DoubleVar(value=8.0)
        self._ad_type_min = tk.DoubleVar(value=0.08)
        self._ad_type_max = tk.DoubleVar(value=0.2)
        self._ad_interval_min = tk.DoubleVar(value=1.0)
        self._ad_interval_max = tk.DoubleVar(value=2.5)
        self._ad_max_chars = tk.IntVar(value=300)
        self._ad_skip_rate = tk.DoubleVar(value=0.0)
        self._ad_sim_interval = tk.StringVar(value="0")
        self._ad_idle_min = tk.StringVar(value="0")
        self._ad_idle_max = tk.StringVar(value="0")

        def _sync_pair(vmin, vmax):
            if vmin.get() > vmax.get():
                vmax.set(vmin.get())
            elif vmax.get() < vmin.get():
                vmin.set(vmax.get())

        # 成对滑块
        make_slider_pair(self._ad_frame, "阅读延迟(秒)",
                         self._ad_read_min, self._ad_read_max, 0, 10, 0.1)
        make_slider_pair(self._ad_frame, "回复延迟(秒)",
                         self._ad_reply_min, self._ad_reply_max, 0, 30, 0.5)
        make_slider_pair(self._ad_frame, "打字速度(秒/字)",
                         self._ad_type_min, self._ad_type_max, 0.01, 1.0, 0.01)
        make_slider_pair(self._ad_frame, "消息间隔(秒)",
                         self._ad_interval_min, self._ad_interval_max, 0, 10, 0.1)

        # 单值滑块
        make_single_slider(self._ad_frame, "每段最大字数",
                           self._ad_max_chars, 50, 1000, 10)
        make_single_slider(self._ad_frame, "随机跳过率",
                           self._ad_skip_rate, 0, 1, 0.01, ".2f")

        # 输入框
        make_entry_row(self._ad_frame, "活动模拟间隔(秒,0=关)",
                       self._ad_sim_interval)
        make_entry_row(self._ad_frame, "空闲时间 min(分钟)",
                       self._ad_idle_min)
        make_entry_row(self._ad_frame, "空闲时间 max(分钟)",
                       self._ad_idle_max)

    def _on_ad_toggle(self) -> None:
        state = "normal" if self._ad_enabled_var.get() else "disabled"
        for child in self._ad_frame.winfo_children():
            try:
                child.configure(state=state)
            except Exception:
                pass
        for slider in self._ad_frame.winfo_children():
            try:
                for sub in slider.winfo_children():
                    if isinstance(sub, (ctk.CTkSlider, ctk.CTkEntry)):
                        sub.configure(state=state)
            except Exception:
                pass

    # ── Tab 3: 日志 ──────────────────────────────────

    def _build_logs(self, parent: ctk.CTkFrame) -> None:
        # 顶部控制
        top = ctk.CTkFrame(parent)
        top.pack(fill="x", padx=5, pady=(5, 0))

        self._log_autoscroll = tk.BooleanVar(value=True)
        ctk.CTkSwitch(top, text="自动滚动", variable=self._log_autoscroll).pack(side="left", padx=5)

        self._log_level_var = tk.StringVar(value="ALL")
        ctk.CTkOptionMenu(top, variable=self._log_level_var,
                           values=["ALL", "DEBUG", "INFO", "WARNING", "ERROR"],
                           command=self._on_log_level_change).pack(side="left", padx=5)

        ctk.CTkButton(top, text="清空日志", command=self._clear_logs).pack(side="right", padx=5)

        # 日志文本框
        self._log_text = ctk.CTkTextbox(parent, font=("Consolas", 11), state="disabled")
        self._log_text.pack(fill="both", expand=True, padx=5, pady=5)

    def _on_log_level_change(self, level: str) -> None:
        self._log_handler.set_level_filter(level)

    def _clear_logs(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _poll_logs(self) -> None:
        try:
            while True:
                msg = self._log_handler.queue.get_nowait()
                self._log_text.configure(state="normal")
                self._log_text.insert("end", msg + "\n")
                # 限制行数防内存泄漏
                if float(self._log_text.index("end-1c")) > 10000:
                    self._log_text.delete("1.0", "2.0")
                self._log_text.configure(state="disabled")
                if self._log_autoscroll.get():
                    self._log_text.see("end")
        except queue.Empty:
            pass
        self.after(100, self._poll_logs)

    # ═══════════════════════════════════════════════════
    #  配置加载/保存
    # ═══════════════════════════════════════════════════

    def _load_config_to_ui(self) -> None:
        """从 config 填充 UI 控件"""
        cfg = self.config

        # Bot
        self._mode_var.set(cfg.bot.get("mode", "whitelist"))
        self._poll_var.set(str(cfg.bot.get("poll_interval_seconds", 3)))
        self._trigger_var.set(cfg.bot.get("mention_trigger", "豆咪"))
        self._prefix_var.set(cfg.bot.get("reply_prefix", ""))
        self._reading_method_var.set(cfg.bot.get("reading_method", "clipboard"))
        self._quiet_start_var.set(cfg.bot.get("quiet_hours_start", ""))
        self._quiet_end_var.set(cfg.bot.get("quiet_hours_end", ""))

        # Contacts
        self._contacts = list(cfg.bot.get("contacts", []))
        self._refresh_contact_listbox()

        # LLM
        self._llm_enabled_var.set(cfg.llm.get("enabled", False))
        self._llm_provider_var.set(cfg.llm.get("provider", "openai_compatible"))
        self._llm_url_var.set(cfg.llm.get("base_url", ""))
        self._llm_key_var.set(cfg.llm.get("api_key", ""))
        self._llm_model_var.set(cfg.llm.get("model", ""))
        self._llm_temp_var.set(cfg.llm.get("temperature", 0.7))
        self._llm_maxtok_var.set(cfg.llm.get("max_tokens", 1024))
        self._llm_sysprompt.delete("1.0", "end")
        self._llm_sysprompt.insert("1.0", cfg.llm.get("system_prompt", ""))

        # Conversation
        self._conv_enabled_var.set(cfg.conversation.get("enabled", False))
        self._conv_history_var.set(str(cfg.conversation.get("max_history", 6)))
        self._conv_tokens_var.set(str(cfg.conversation.get("max_tokens", 2048)))

        # Anti-detect
        ad = cfg.anti_detect
        self._ad_enabled_var.set(ad.get("enabled", True))
        self._ad_read_min.set(ad.get("read_delay_min", 1.0))
        self._ad_read_max.set(ad.get("read_delay_max", 3.0))
        self._ad_reply_min.set(ad.get("reply_delay_min", 2.0))
        self._ad_reply_max.set(ad.get("reply_delay_max", 8.0))
        self._ad_type_min.set(ad.get("typing_speed_min", 0.08))
        self._ad_type_max.set(ad.get("typing_speed_max", 0.2))
        self._ad_interval_min.set(ad.get("message_interval_min", 1.0))
        self._ad_interval_max.set(ad.get("message_interval_max", 2.5))
        self._ad_max_chars.set(ad.get("max_chars_per_message", 300))
        self._ad_skip_rate.set(ad.get("random_skip_rate", 0.0))
        self._ad_sim_interval.set(str(ad.get("simulate_activity_interval", 0)))
        self._ad_idle_min.set(str(ad.get("idle_minutes_min", 0)))
        self._ad_idle_max.set(str(ad.get("idle_minutes_max", 0)))

        # Update LLM widgets state
        self._on_llm_enabled_toggle()
        self._on_provider_change()

    def _save_config(self) -> None:
        """将 UI 控件值写入 config 并保存"""
        cfg = self.config

        # Bot
        cfg.bot["mode"] = self._mode_var.get()
        cfg.bot["poll_interval_seconds"] = int(self._poll_var.get())
        cfg.bot["mention_trigger"] = self._trigger_var.get()
        cfg.bot["reply_prefix"] = self._prefix_var.get()
        cfg.bot["reading_method"] = self._reading_method_var.get()
        cfg.bot["quiet_hours_start"] = self._quiet_start_var.get()
        cfg.bot["quiet_hours_end"] = self._quiet_end_var.get()
        cfg.bot["contacts"] = list(self._contacts)

        # LLM
        cfg.llm["enabled"] = self._llm_enabled_var.get()
        cfg.llm["provider"] = self._llm_provider_var.get()
        cfg.llm["base_url"] = self._llm_url_var.get()
        cfg.llm["api_key"] = self._llm_key_var.get()
        cfg.llm["model"] = self._llm_model_var.get()
        cfg.llm["temperature"] = round(self._llm_temp_var.get(), 2)
        cfg.llm["max_tokens"] = self._llm_maxtok_var.get()
        cfg.llm["system_prompt"] = self._llm_sysprompt.get("1.0", "end-1c").strip()

        # Conversation
        cfg.conversation["enabled"] = self._conv_enabled_var.get()
        try:
            cfg.conversation["max_history"] = int(self._conv_history_var.get())
            cfg.conversation["max_tokens"] = int(self._conv_tokens_var.get())
        except ValueError:
            pass

        # Anti-detect
        ad = cfg.anti_detect
        ad["enabled"] = self._ad_enabled_var.get()
        ad["read_delay_min"] = round(self._ad_read_min.get(), 1)
        ad["read_delay_max"] = round(self._ad_read_max.get(), 1)
        ad["reply_delay_min"] = round(self._ad_reply_min.get(), 1)
        ad["reply_delay_max"] = round(self._ad_reply_max.get(), 1)
        ad["typing_speed_min"] = round(self._ad_type_min.get(), 2)
        ad["typing_speed_max"] = round(self._ad_type_max.get(), 2)
        ad["message_interval_min"] = round(self._ad_interval_min.get(), 1)
        ad["message_interval_max"] = round(self._ad_interval_max.get(), 1)
        ad["max_chars_per_message"] = self._ad_max_chars.get()
        ad["random_skip_rate"] = round(self._ad_skip_rate.get(), 2)
        try:
            ad["simulate_activity_interval"] = int(self._ad_sim_interval.get())
            ad["idle_minutes_min"] = int(self._ad_idle_min.get())
            ad["idle_minutes_max"] = int(self._ad_idle_max.get())
        except ValueError:
            pass

        cfg.save()
        logger.info("配置已保存")

    # ═══════════════════════════════════════════════════
    #  联系人管理
    # ═══════════════════════════════════════════════════

    def _refresh_contact_listbox(self) -> None:
        self._contact_listbox.delete(0, "end")
        for name in self._contacts:
            self._contact_listbox.insert("end", name)

    def _add_contact(self) -> None:
        name = self._contact_entry.get().strip()
        if not name:
            return
        if name in self._contacts:
            messagebox.showinfo("提示", "联系人已存在")
            return
        self._contacts.append(name)
        self._refresh_contact_listbox()
        self._contact_entry.delete(0, "end")

    def _remove_contact(self) -> None:
        sel = self._contact_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._contacts):
            del self._contacts[idx]
            self._refresh_contact_listbox()

    def _create_driver(self):
        """根据配置创建微信驱动实例"""
        driver_type = self.config.bot.get("driver", "hybrid")
        if driver_type == "wxauto":
            from wechat_driver import WeChatDriver
            return WeChatDriver()
        elif driver_type == "hybrid":
            from wechat_driver_hybrid import WeChatDriverHybrid
            return WeChatDriverHybrid(self.config.bot.get("contacts", []))
        else:
            from wechat_driver_pyautogui import WeChatDriverPyAutoGUI
            return WeChatDriverPyAutoGUI(self.config.bot.get("contacts", []))

    def _load_contacts_from_wechat(self) -> None:
        def work():
            driver_type = self.config.bot.get("driver", "hybrid")
            if driver_type != "wxauto":
                label = "PyAutoGUI" if driver_type == "pyautogui" else "混合"
                self.after(0, lambda: messagebox.showinfo(
                    "提示", f"{label} 模式无法从微信加载联系人\n\n"
                    "请在「控制面板」手动输入联系人名称"))
                return
            try:
                from wechat_driver import WeChatDriver
                wx = WeChatDriver()
                sessions = wx.get_sessions()
                names = [s["name"] for s in sessions
                         if s["name"] != wx.nickname]
                self.after(0, lambda: self._on_contacts_loaded(names))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("加载失败", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_contacts_loaded(self, names: list[str]) -> None:
        self._contacts = [n for n in names if n not in self._contacts]
        for n in names:
            if n not in self._contacts:
                self._contacts.append(n)
        self._refresh_contact_listbox()
        messagebox.showinfo("完成", f"已加载 {len(names)} 个会话")

    # ═══════════════════════════════════════════════════
    #  Bot 启停
    # ═══════════════════════════════════════════════════

    def _toggle_bot(self) -> None:
        if self._engine and self._engine._running.is_set():
            self._stop_engine()
        else:
            self._start_engine()

    def _start_engine(self) -> None:
        # 先保存配置
        self._save_config()

        # 重新加载配置到引擎
        self.config.load()
        self._engine = BotEngine(self.config)

        def run():
            ok = self._engine.initialize()
            if not ok:
                self.after(0, lambda: messagebox.showerror(
                    "启动失败", "微信驱动初始化失败。\n请确保微信已打开并登录。"))
                self.after(0, lambda: self._update_status("STOPPED", "DISCONNECTED", "?"))
                return

            # 检查 LLM 状态
            llm_status = "ENABLED" if self._engine.llm else "DISABLED"

            self.after(0, lambda: self._update_status("RUNNING", "CONNECTED", llm_status))
            self.after(0, lambda: self._btn_toggle.configure(
                text="■ 停止 Bot", fg_color=self.RED, hover_color="#c0392b"))

            try:
                self._engine.run()
            except Exception as e:
                logger.error("引擎异常退出: %s", e)
            finally:
                self.after(0, lambda: self._update_status("STOPPED", "CONNECTED",
                                                           "ENABLED" if self._engine and self._engine.llm else "DISABLED"))
                self.after(0, lambda: self._btn_toggle.configure(
                    text="▶ 启动 Bot", fg_color=self.GREEN, hover_color="#27ae60"))

        self._update_status("RUNNING", "?", "?")
        self._engine_thread = threading.Thread(target=run, daemon=True)
        self._engine_thread.start()

    def _stop_engine(self) -> None:
        if self._engine:
            self._engine.stop()
            if self._engine_thread:
                self._engine_thread.join(timeout=5)
            self._engine.shutdown()
        self._engine = None
        self._engine_thread = None

    def _hotkey_stop(self, event=None) -> None:
        """Ctrl+Shift+S / Escape 快捷键停止 Bot（立即响应）"""
        if self._engine is None:
            return
        # 立即清 Event，引擎循环会在下次检查时退出
        self._engine.stop()
        # 立即更新 UI（bind_all 回调在主线程执行）
        self._update_status("STOPPED", "?", "?")
        self._btn_toggle.configure(text="▶ 启动 Bot", fg_color=self.GREEN,
                                   hover_color="#27ae60")
        # 后台等待引擎线程退出 + 清理
        threading.Thread(target=self._cleanup_engine, daemon=True).start()

    def _hotkey_escape(self, event=None) -> None:
        """Escape 也触发停止"""
        self._hotkey_stop(event)

    def _cleanup_engine(self) -> None:
        """等待引擎线程退出并清理资源（后台线程调用）"""
        if self._engine_thread and self._engine_thread.is_alive():
            self._engine_thread.join(timeout=5)
        if self._engine:
            self._engine.shutdown()
            # 恢复状态灯（主线程安全）
            self.after(0, lambda: self._update_status("STOPPED", "CONNECTED", "?"))
        self._engine = None
        self._engine_thread = None

    # ═══════════════════════════════════════════════════
    #  测试功能
    # ═══════════════════════════════════════════════════

    def _test_wechat(self) -> None:
        def work():
            try:
                wx = self._create_driver()
                driver_type = self.config.bot.get("driver", "pyautogui")
                sessions = wx.get_sessions()
                msg = (f"微信已连接 (driver: {driver_type})\n"
                       f"昵称: {wx.nickname}\n"
                       f"当前会话数: {len(sessions)}")
                for s in sessions[:5]:
                    msg += f"\n  · {s.get('name', '?')}"
                if len(sessions) > 5:
                    msg += f"\n  ... 及其他 {len(sessions) - 5} 个"
                if not sessions:
                    msg += "\n\n提示: PyAutoGUI 模式的会话列表\n来自配置白名单"
                self.after(0, lambda: messagebox.showinfo("测试微信", msg))
                self.after(0, lambda: self._update_status(
                    self._badge_bot.cget("text")[2:], "CONNECTED",
                    self._badge_llm.cget("text")[2:]))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("测试微信", f"连接失败:\n{e}"))
                self.after(0, lambda: self._update_status(
                    self._badge_bot.cget("text")[2:], "DISCONNECTED",
                    self._badge_llm.cget("text")[2:]))

        threading.Thread(target=work, daemon=True).start()

    def _test_llm(self) -> None:
        def work():
            url = self._llm_url_var.get()
            key = self._llm_key_var.get()
            model = self._llm_model_var.get()
            try:
                client = LLMClient(
                    provider=self._llm_provider_var.get(),
                    base_url=url, api_key=key, model=model)
                ok = client.test_connection()
                if ok:
                    reply = client.chat("你好，请用一句话简单介绍你自己")
                    pname = self._llm_provider_var.get()
                    msg = (f"{pname} 连接成功!\n\n"
                           f"回复: {reply}")
                    self.after(0, lambda: messagebox.showinfo("测试 LLM", msg))
                    self.after(0, lambda: self._update_status(
                        self._badge_bot.cget("text")[2:],
                        self._badge_wechat.cget("text")[2:], "ENABLED"))
                else:
                    self.after(0, lambda: messagebox.showerror("测试 LLM", "连接失败"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("测试 LLM", f"错误:\n{e}"))

        threading.Thread(target=work, daemon=True).start()

    def _fetch_models(self) -> None:
        def work():
            url = self._llm_url_var.get()
            key = self._llm_key_var.get()
            try:
                client = LLMClient(
                    provider=self._llm_provider_var.get(),
                    base_url=url, api_key=key)
                models = client.list_models()
                self.after(0, lambda: self._on_models_fetched(models))
            except Exception as e:
                self.after(0, lambda: self._model_menu.configure(
                    values=["(获取失败)"]))
                logger.warning("获取模型列表失败: %s", e)

        threading.Thread(target=work, daemon=True).start()

    def _on_models_fetched(self, models: list[str]) -> None:
        if not models:
            self._model_menu.configure(values=["(无可用模型)"])
            return
        self._models = models
        self._model_menu.configure(values=models)
        current = self._llm_model_var.get()
        if current and current in models:
            self._model_menu.set(current)
        else:
            self._model_menu.set(models[0])

    # ═══════════════════════════════════════════════════
    #  窗口关闭
    # ═══════════════════════════════════════════════════

    def _on_close(self) -> None:
        logger.info("正在关闭...")
        self._stop_engine()
        self._save_config()
        self.destroy()


# ═══════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════

def launch_gui(config_path: Optional[str] = None) -> None:
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = BotGUI(config_path)
    app.mainloop()
