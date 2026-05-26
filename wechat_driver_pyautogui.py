"""PyAutoGUI 微信驱动层 — 模拟真人操作，防微信检测

核心原则：
  - 所有鼠标移动带缓动曲线（非瞬移）
  - 所有点击带位置抖动（非精确坐标）
  - 所有操作间随机延迟（非固定间隔）
  - 优先点击系统托盘图标激活窗口（非强制置前）
"""

import os
import random
import re
import time
import logging
from typing import Optional

import pyautogui
import win32gui
import win32api
import win32process
import win32con
import ctypes

logger = logging.getLogger("wechat_bot")

# ── DPI 感知 ────────────────────────────────────────────

def _enable_dpi_awareness():
    """启用 DPI 感知，使 GetWindowRect 返回物理像素而非缩放后虚拟像素。

    PyAutoGUI 操作（鼠标、截图）使用物理像素坐标，若不启用 DPI 感知，
    GetWindowRect 在高 DPI 下可能返回缩放后的坐标，导致点击偏移。
    尝试 Per-Monitor DPI Aware → System DPI Aware → 旧版 API，静默忽略失败。
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # System
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()  # 旧版
            except (AttributeError, OSError):
                pass

_enable_dpi_awareness()

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0  # 手动控制延迟


# ── 工具函数 ─────────────────────────────────────────────

def _rand(a: float, b: float) -> float:
    return random.uniform(a, b)


def _jitter(pos: tuple[int, int], radius: int = 4) -> tuple[int, int]:
    """给坐标加随机抖动"""
    return (pos[0] + random.randint(-radius, radius),
            pos[1] + random.randint(-radius, radius))


def _human_move_click(x: int, y: int, clicks: int = 1):
    """模拟人类：移动鼠标（缓动）+ 点击（带抖动）"""
    tx, ty = _jitter((x, y), radius=6)
    duration = _rand(0.15, 0.45)
    pyautogui.moveTo(tx, ty, duration=duration, tween=pyautogui.easeOutQuad)
    time.sleep(_rand(0.05, 0.15))
    for _ in range(clicks):
        pyautogui.click()
        time.sleep(_rand(0.03, 0.08))


def _human_type(text: str):
    """模拟人类逐字输入（含随机间隔）"""
    for ch in text:
        pyautogui.write(ch, interval=_rand(0.02, 0.08))
        # 偶尔停顿一下
        if random.random() < 0.1:
            time.sleep(_rand(0.1, 0.3))


def _human_press(key: str):
    """按一个键（有随机前摇）"""
    time.sleep(_rand(0.05, 0.15))
    pyautogui.press(key)


def _human_hotkey(*keys: str):
    """组合键（有随机前摇）"""
    time.sleep(_rand(0.08, 0.2))
    pyautogui.hotkey(*keys)


# ══════════════════════════════════════════════════════════

class WeChatDriverPyAutoGUI:
    WECHAT_CLASS = "Qt51514QWindowIcon"

    TARGET_LEFT = 50
    TARGET_TOP = 50
    TARGET_WIDTH = 900
    TARGET_HEIGHT = 700

    def __init__(self, contacts: Optional[list[str]] = None,
                 reading_method: str = "clipboard",
                 llm: Optional[object] = None,
                 mention_trigger: str = "qwen",
                 fuzzy_match_threshold: float = 0.5):
        """
        Args:
            contacts: 联系人白名单
            reading_method: 消息读取方式 - "clipboard"(默认) / "ocr" / "llm_vision"
            llm: LLM 客户端实例（仅 llm_vision 模式需要）
            mention_trigger: @提及触发词，消息包含 @{trigger} 才回复
        """
        self._contacts = contacts or []
        self._hwnd: Optional[int] = None
        self._window_rect: tuple[int, int, int, int] | None = None
        self._nickname = "WeChat"
        self._mention_trigger = mention_trigger
        self._fuzzy_threshold = fuzzy_match_threshold
        self._last_chat_text: dict[str, str] = {}  # 已处理的消息文本快照
        self._last_screenshot_hash: dict[str, str] = {}  # 截图 MD5 变化检测
        self._reading_method = reading_method
        self._llm = llm
        self._calibrated_coords: dict[str, int | None] = {}  # UI 校准坐标缓存

        # OCR 初始化（仅需要时）
        if reading_method == "ocr":
            self._init_ocr()

        self._find_and_prepare_window()
        logger.info("初始化完成, 微信窗口: %s, 联系人: %s",
                     self._window_rect, self._contacts)

    # ── DPI 缩放辅助 ─────────────────────────────────────

    @staticmethod
    def _get_dpi_scale(hwnd: int) -> float:
        """获取窗口所在显示器的 DPI 缩放比（1.0 = 100%）。"""
        try:
            shcore = ctypes.windll.shcore
            monitor = shcore.MonitorFromWindow(hwnd, 2)
            dpi_x = ctypes.c_uint()
            dpi_y = ctypes.c_uint()
            shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
            return dpi_x.value / 96.0
        except Exception:
            try:
                caption = win32api.GetSystemMetrics(win32con.SM_CYCAPTION)
                if caption > 0:
                    return caption / 31.0
            except Exception:
                pass
            return 1.0

    # ══════════════════════════════════════════════════════
    #  窗口管理
    # ══════════════════════════════════════════════════════

    def _find_and_prepare_window(self) -> bool:
        if not self._find_window():
            return False
        # 固定窗口尺寸，确保坐标计算一致性（跨屏幕/DPI）
        self._resize_window()
        self._update_window_rect()
        logger.info("微信窗口已定位到 (%d, %d) %dx%d",
                     self._window_rect[0], self._window_rect[1],
                     self.TARGET_WIDTH, self.TARGET_HEIGHT)
        return True

    def _find_window(self) -> bool:
        """查找微信主窗口（优先可见窗口）"""
        def enum_cb(hwnd, hwnds):
            try:
                if self.WECHAT_CLASS in win32gui.GetClassName(hwnd):
                    hwnds.append((hwnd, win32gui.IsWindowVisible(hwnd)))
            except Exception:
                pass
            return True

        results = []
        win32gui.EnumWindows(enum_cb, results)

        if not results:
            logger.error("未找到微信窗口 (class: %s)", self.WECHAT_CLASS)
            return False

        # 优先取可见窗口，次选任意
        visible = [hwnd for hwnd, v in results if v]
        self._hwnd = (visible or [hwnd for hwnd, _ in results])[0]
        self._update_window_rect()
        logger.info("找到微信窗口, HWND: %d, 位置: %s, 标题: %s",
                     self._hwnd, self._window_rect,
                     win32gui.GetWindowText(self._hwnd))
        return True

    def _update_window_rect(self):
        if self._hwnd and win32gui.IsWindow(self._hwnd):
            self._window_rect = win32gui.GetWindowRect(self._hwnd)

    def _resize_window(self):
        """将微信窗口设为固定尺寸（900x700），确保百分比坐标精度。

        统一窗口尺寸后，所有基于窗口宽高比的坐标计算（70%W / 45%H 等）
        在不同屏幕上行为一致。不改变窗口位置（保留原始左上角坐标）。
        """
        if not self._hwnd or not win32gui.IsWindow(self._hwnd):
            return
        try:
            l, t, _, _ = win32gui.GetWindowRect(self._hwnd)
            win32gui.MoveWindow(self._hwnd, l, t,
                                self.TARGET_WIDTH, self.TARGET_HEIGHT, True)
            time.sleep(0.5)
        except Exception as e:
            logger.warning("调整窗口大小失败: %s", e)

    def _calibrate_ui(self):
        """通过像素方差自动定位输入框边界。

        输入框区域背景颜色相对均匀（低方差），消息区域有文字/气泡（高方差）。
        从底部向上扫描方差突变点即为输入框顶部边界。
        坐标缓存后供 send_message 优先使用，失败回退百分比。
        """
        if not self._window_rect:
            return
        try:
            import cv2
            import numpy as np
        except ImportError:
            logger.info("OpenCV 未安装，跳过视觉校准")
            return

        try:
            l, t, r, b = self._window_rect
            ww, wh = r - l, b - t

            # 切换到输入框所在的聊天——需要一个已知联系人做截图锚点
            # 截取右侧底部区域（55%-100% 高度）
            region_x = l + ww // 3
            region_y = t + int(wh * 0.55)
            region_w = ww * 2 // 3
            region_h = int(wh * 0.45)

            screenshot = pyautogui.screenshot(region=(region_x, region_y, region_w, region_h))
            gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)

            # 从底部向上计算每行像素方差，找到方差跳变点
            h, w = gray.shape
            var_history = []
            for y in range(h):
                row = gray[y, :].astype(np.float32)
                var_history.append(np.var(row))

            # 底部行均值（输入框区域 - 低方差）
            bottom_mean = np.mean(var_history[h * 3 // 4:]) if h > 10 else 0
            # 顶部行均值（消息区域 - 高方差）
            top_mean = np.mean(var_history[h // 4:h // 2]) if h > 10 else 0
            threshold = (top_mean + bottom_mean) / 2

            # 从底部往上找到方差首次超过阈值的位置 = 输入框顶部
            input_box_top = None
            for y in range(h - 1, h // 3, -1):
                if var_history[y] > threshold:
                    input_box_top = region_y + y + 5  # +5 偏移到输入框内部
                    break

            if (input_box_top and input_box_top > region_y
                    and input_box_top < t + int(wh * 0.92)):
                self._calibrated_coords["input_box_y"] = input_box_top
                logger.info("视觉校准: 输入框 Y=%d", input_box_top)
            else:
                logger.info("视觉校准: 未检测到输入框边界")
        except Exception as e:
            logger.warning("视觉校准异常: %s", e)

    def _activate(self, max_retries: int = 3) -> bool:
        """将微信窗口带到前台（多策略确保成功）"""
        import ctypes
        user32 = ctypes.windll.user32

        for attempt in range(max_retries):
            if not self._hwnd or not win32gui.IsWindow(self._hwnd):
                if not self._find_and_prepare_window():
                    continue

            try:
                if win32gui.IsIconic(self._hwnd):
                    win32gui.ShowWindow(self._hwnd, win32con.SW_RESTORE)
                    time.sleep(_rand(0.2, 0.4))

                # 策略1: SwitchToThisWindow（最可靠，免限制）
                user32.SwitchToThisWindow(self._hwnd, True)
                time.sleep(_rand(0.2, 0.4))

                # 验证
                if win32gui.GetForegroundWindow() == self._hwnd:
                    return True

                # 策略2: SetForegroundWindow
                win32gui.SetForegroundWindow(self._hwnd)
                time.sleep(_rand(0.2, 0.4))

                if win32gui.GetForegroundWindow() == self._hwnd:
                    return True

                # 策略3: AttachThreadInput + SetForegroundWindow
                fore_hwnd = win32gui.GetForegroundWindow()
                if fore_hwnd and fore_hwnd != self._hwnd:
                    fore_tid = win32process.GetWindowThreadProcessId(fore_hwnd)[0]
                    self_tid = win32process.GetWindowThreadProcessId(self._hwnd)[0]
                    user32.AttachThreadInput(fore_tid, self_tid, True)
                    win32gui.SetForegroundWindow(self._hwnd)
                    user32.AttachThreadInput(fore_tid, self_tid, False)
                    time.sleep(_rand(0.2, 0.4))

                if win32gui.GetForegroundWindow() == self._hwnd:
                    return True

                logger.warning("激活尝试 %d 失败", attempt + 1)
            except Exception as e:
                logger.warning("激活异常 [%d]: %s", attempt + 1, e)

            time.sleep(_rand(0.5, 1.0))

        logger.error("激活微信窗口失败（已重试 %d 次）", max_retries)
        return False

    # ══════════════════════════════════════════════════════
    #  基础属性
    # ══════════════════════════════════════════════════════

    @property
    def nickname(self) -> str:
        return self._nickname

    @property
    def raw_wx(self):
        return _RawWxStub()

    def is_online(self) -> bool:
        return self._hwnd is not None and win32gui.IsWindow(self._hwnd)

    def _verify_foreground(self) -> bool:
        """验证微信窗口是否在前台，记录日志"""
        if win32gui.GetForegroundWindow() != self._hwnd:
            logger.error("微信窗口不在前台，跳过操作")
            return False
        return True

    def is_window_visible(self) -> bool:
        """检查微信窗口是否可用（窗口存在、未销毁、位置有效）"""
        if not self._hwnd or not win32gui.IsWindow(self._hwnd):
            return False
        # 刷新窗口矩形确保坐标准确
        self._update_window_rect()
        l, t, r, b = self._window_rect
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            return False
        # 检查窗口是否在屏幕范围内（至少部分可见）
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        if l >= screen_w or t >= screen_h or r <= 0 or b <= 0:
            return False
        return True

    # ══════════════════════════════════════════════════════
    #  会话列表
    # ══════════════════════════════════════════════════════

    def get_sessions(self) -> list[dict]:
        return [{"name": c} for c in self._contacts if c]

    # ══════════════════════════════════════════════════════
    #  切换聊天（模拟真人搜索流程）
    # ══════════════════════════════════════════════════════

    def switch_chat(self, who: str) -> bool:
        """模拟真人：点击搜索栏 → 输入名称 → 键盘选择 → 打开（窗口必须已在前台）"""
        if not self.is_window_visible():
            logger.warning("微信窗口不可见，无法切换聊天")
            return False
        if not self._verify_foreground():
            return False

        # 刷新窗口位置，防止坐标偏移
        self._update_window_rect()
        if not self._window_rect:
            return False

        try:
            l, t, r, b = self._window_rect
            ww = r - l

            # 搜索栏位置（左侧面板顶部，按 DPI 缩放）
            sx = l + ww // 6
            dpi_scale = self._get_dpi_scale(self._hwnd)
            sy = t + int(45 * dpi_scale)

            # 点击搜索栏
            _human_move_click(sx, sy)
            time.sleep(_rand(0.3, 0.6))

            # 全选→删除已有文字
            _human_hotkey("ctrl", "a")
            time.sleep(_rand(0.1, 0.3))

            # 逐字输入联系人名
            _human_type(who)
            time.sleep(_rand(0.8, 1.5))  # 等搜索结果

            # 键盘选择（默认第一个结果已高亮，直接 Enter）
            _human_press("enter")
            time.sleep(_rand(0.5, 0.8))

            # 点击右侧消息区域确保焦点（同时自然取消搜索遮罩）
            # 注意：不能用 Escape！微信中 Escape 会最小化窗口到托盘
            # x=70% 避开左侧图标栏，y=45% 避开顶部标题栏/标签栏
            msg_x = l + int(ww * 0.7)
            msg_y = t + int((b - t) * 0.45)
            _human_move_click(msg_x, msg_y)
            time.sleep(_rand(0.2, 0.4))

            # 验证窗口没有被意外关闭/最小化
            if not self.is_window_visible():
                logger.error("切换聊天后微信窗口消失")
                return False

            return True
        except Exception as e:
            logger.error("切换聊天 [%s] 失败: %s", who, e)
            return False

    # ══════════════════════════════════════════════════════
    #  读取消息
    # ══════════════════════════════════════════════════════

    def _init_ocr(self):
        """初始化 Tesseract OCR 引擎"""
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        user_tessdata = os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tessdata")
        if os.path.isdir(user_tessdata):
            os.environ.setdefault("TESSDATA_PREFIX", user_tessdata)
        self._ocr_lang = "chi_sim+eng"
        logger.info("Tesseract OCR 已初始化 (lang: %s)", self._ocr_lang)

    def _click_message_area(self):
        """点击右侧消息区域确保焦点（窗口必须已在前台，否则跳过）"""
        self._update_window_rect()
        if not self._window_rect:
            return
        if not self._verify_foreground():
            return

        l, t, r, b = self._window_rect
        ww, wh = r - l, b - t

        # 只点右侧消息区中部偏下（x=70% 在聊天区域，y=45% 在消息列表而非顶部标题栏）
        # 注意：不要点左侧聊天列表，否则会选中其他联系人取消 switch_chat 的结果
        mx = l + int(ww * 0.7)
        my = t + int(wh * 0.45)
        _human_move_click(mx, my, clicks=1)
        time.sleep(_rand(0.15, 0.3))

    def _get_chat_text(self) -> str:
        """获取聊天文本（根据 reading_method 选择方式）"""
        if self._reading_method == "ocr":
            return self._get_chat_text_ocr()
        if self._reading_method == "llm_vision":
            return self._get_chat_text_llm_vision()
        return self._get_chat_text_clipboard()

    def _get_chat_text_clipboard(self) -> str:
        """通过 Ctrl+A → Ctrl+C 获取聊天文本"""
        try:
            self._click_message_area()
            time.sleep(_rand(0.1, 0.2))

            # 验证微信仍在最前才操作剪贴板
            if not self._verify_foreground():
                return ""

            _human_hotkey("ctrl", "a")
            time.sleep(_rand(0.15, 0.3))
            _human_hotkey("ctrl", "c")
            time.sleep(_rand(0.15, 0.3))

            import pyperclip
            return pyperclip.paste()
        except Exception as e:
            logger.error("剪贴板获取聊天文本失败: %s", e)
            return ""

    def _get_chat_text_ocr(self) -> str:
        """实验性: 通过截图 + OCR 获取聊天文本"""
        try:
            import pytesseract
        except ImportError:
            logger.error("pytesseract 未安装，请执行: pip install pytesseract")
            return ""

        try:
            self._click_message_area()
            time.sleep(_rand(0.2, 0.4))

            l, t, r, b = self._window_rect
            ww, wh = r - l, b - t

            region_x = l + ww // 3 + 5
            dpi_scale = self._get_dpi_scale(self._hwnd)
            region_y = t + int(70 * dpi_scale)
            region_w = (ww * 2) // 3 - 15
            region_h = wh - int(70 * dpi_scale) - int(165 * dpi_scale)

            screenshot = pyautogui.screenshot(region=(region_x, region_y, region_w, region_h))
            # 预处理：灰度→反转→Otsu 二值化（适配暗色主题）
            gray = screenshot.convert("L")
            import cv2
            import numpy as np
            img_cv = np.array(gray)
            _, bw = cv2.threshold(255 - img_cv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            from PIL import Image
            bw_pil = Image.fromarray(bw)

            text = pytesseract.image_to_string(bw_pil, lang=self._ocr_lang, config="--psm 6")
            return text.strip()
        except Exception as e:
            logger.error("OCR 获取聊天文本失败: %s", e)
            return ""

    def _get_chat_text_llm_vision(self) -> str:
        """通过 LLM 视觉模型识别截图中的文字"""
        if not self._llm:
            logger.error("LLM 视觉模式需要 LLM 客户端，请检查配置")
            return ""

        try:
            self._click_message_area()
            time.sleep(_rand(0.3, 0.5))

            l, t, r, b = self._window_rect
            ww, wh = r - l, b - t

            # 截图区域：右侧聊天面板，去除顶部标题栏和底部输入框
            region_x = l + int(ww * 0.32)
            region_y = t + int(wh * 0.12)
            region_w = int(ww * 0.62)
            region_h = int(wh * 0.60)

            import io
            import pyautogui
            screenshot = pyautogui.screenshot(region=(region_x, region_y, region_w, region_h))
            buf = io.BytesIO()
            screenshot.save(buf, format="PNG")
            image_bytes = buf.getvalue()

            text = self._llm.chat_with_image(
                image_bytes,
                "逐字提取这张聊天截图中的所有对话文本，包括每条消息的发送者和内容。只输出文字本身，不要添加任何解释。"
            )
            return text.strip() if text else ""
        except Exception as e:
            logger.error("LLM 视觉识别聊天文本失败: %s", e)
            return ""

    # 桌面内容标记 — 如果剪贴板读到这些关键词，说明操作到了桌面
    _DESKTOP_CONTENT_MARKERS = [
        ".lnk", "快捷方式", "此电脑", "回收站", "控制面板",
        "我的电脑", "This PC", "Recycle Bin",
    ]

    def _get_chat_area_hash(self) -> str:
        """截取聊天消息区域底部一小块，计算 MD5 用于快速变化检测"""
        import hashlib
        l, t, r, b = self._window_rect
        ww, wh = r - l, b - t
        # 只截取消息区域中部偏下（避开顶部时钟/标题和底部输入框）
        rx = l + int(ww * 0.32)
        ry = t + int(wh * 0.42)
        rw = int(ww * 0.62)
        rh = int(wh * 0.30)
        screenshot = pyautogui.screenshot(region=(rx, ry, rw, rh))
        return hashlib.md5(screenshot.tobytes()).hexdigest()

    def get_new_messages(self, contact: str) -> list[dict]:
        """读取聊天消息，仅当包含 @{trigger} 时返回"""
        if not self.is_window_visible():
            logger.warning("微信窗口不可见，跳过消息读取")
            return []
        if not self._verify_foreground():
            return []
        if not self.switch_chat(contact):
            return []

        time.sleep(_rand(0.3, 0.6))

        # 快速截图哈希检测 — 没变化则跳过 LLM Vision
        current_hash = self._get_chat_area_hash()
        last_hash = self._last_screenshot_hash.get(contact)
        self._last_screenshot_hash[contact] = current_hash
        if last_hash is not None and current_hash == last_hash:
            logger.debug("截图哈希未变化，跳过 Vision [%s]", contact)
            return []

        # LLM Vision 读取全部可见文本
        current_text = self._get_chat_text()
        if not current_text:
            return []

        # 检测桌面内容
        if any(marker in current_text for marker in self._DESKTOP_CONTENT_MARKERS):
            logger.error("检测到桌面内容而非微信聊天，停止所有任务")
            return "DESKTOP"

        # 检查是否包含 @提及（支持模糊匹配）
        mention = f"@{self._mention_trigger}"
        if "@" not in current_text:
            self._last_chat_text[contact] = current_text
            return []

        # 提取当前文本中所有包含 @提及 的行（模糊匹配）
        current_mention_lines = self._find_fuzzy_mention_lines(current_text)
        if not current_mention_lines:
            return []

        # 对比上次记录，找出真正新增的 @提及 行
        last_text = self._last_chat_text.get(contact, "")
        self._last_chat_text[contact] = current_text

        if last_text:
            last_mention_lines = set(self._find_fuzzy_mention_lines(last_text))
        else:
            last_mention_lines = set()

        new_mention_lines = [l for l in current_mention_lines if l not in last_mention_lines]
        if not new_mention_lines:
            logger.debug("无新增 @%s 行，跳过 [%s]", self._mention_trigger, contact)
            return []

        # 取最后一条新增的 @提及 消息
        clean_msg = new_mention_lines[-1]

        # 归一化 @变体 → 标准触发词，防 Vision 非确定性导致去重失败
        clean_msg = re.sub(
            rf'@{re.escape(self._mention_trigger)}[\w一-鿿]*',
            f'@{self._mention_trigger}',
            clean_msg
        )

        return [{"sender": contact, "content": clean_msg,
                 "type": "friend", "raw": clean_msg,
                 "id": clean_msg[:40]}]

    def _find_fuzzy_mention_lines(self, text: str) -> list[str]:
        """提取包含 @触发词（含模糊匹配，支持 1 字差异）的行"""
        import difflib
        import re

        lines = text.split("\n")
        result = []
        for line in lines:
            line = line.strip()
            if "@" not in line:
                continue
            # 精确匹配直接通过
            if f"@{self._mention_trigger}" in line:
                result.append(line)
                continue
            # 查找 @ 后面的词进行模糊匹配
            for at_idx in [i for i, c in enumerate(line) if c == "@"]:
                after_at = line[at_idx + 1:]
                match = re.match(r'([\w一-鿿＀-￯]+)', after_at)
                if match:
                    word = match.group(1)
                    ratio = difflib.SequenceMatcher(None, word, self._mention_trigger).ratio()
                    if ratio >= self._fuzzy_threshold:
                        result.append(line)
                        break
        return result

    def acknowledge_message(self, contact: str) -> None:
        """发送回复后更新截图哈希，使下轮不再因 bot 自己的回复触发 Vision 调用"""
        try:
            time.sleep(_rand(0.3, 0.6))
            current_hash = self._get_chat_area_hash()
            self._last_screenshot_hash[contact] = current_hash
            # @mention 过滤也足以防止重复回复
        except Exception:
            pass

    # ══════════════════════════════════════════════════════
    #  发送消息
    # ══════════════════════════════════════════════════════

    def send_message(self, who: str, text: str, skip_switch: bool = False) -> bool:
        """模拟真人粘贴消息并发送"""
        if not self.is_window_visible():
            logger.warning("微信窗口不可见，无法发送消息")
            return False
        if not skip_switch and not self.switch_chat(who):
            return False

        # 刷新窗口位置，防止坐标偏移
        self._update_window_rect()
        if not self._window_rect:
            return False
        if not self._verify_foreground():
            return False

        try:
            import pyperclip

            # 复制到剪贴板
            pyperclip.copy(text)
            time.sleep(_rand(0.1, 0.2))

            # 聚焦输入框（优先使用校准坐标，回退百分比）
            l, t, r, b = self._window_rect
            ww, wh = r - l, b - t
            input_x = l + int(ww * 0.6)
            # 首次发送时尝试视觉校准（此时窗口已激活，截图内容准确）
            if "input_box_y" not in self._calibrated_coords:
                self._calibrate_ui()
            calibrated_y = self._calibrated_coords.get("input_box_y")
            if calibrated_y:
                input_y = calibrated_y
            else:
                input_y = t + int(wh * 0.75)  # 回退百分比坐标
            _human_move_click(input_x, input_y)
            time.sleep(_rand(0.2, 0.4))

            # 粘贴
            _human_hotkey("ctrl", "v")
            time.sleep(_rand(0.15, 0.3))

            # 按回车发送
            _human_press("enter")
            time.sleep(_rand(0.3, 0.6))
            return True
        except Exception as e:
            logger.error("发送消息失败 [%s]: %s", who, e)
            return False

    def send_message_slowly(self, who, text, char_delay=(0.08, 0.2),
                            chunk_size=300, chunk_delay=(1.0, 2.5)):
        """分多段发送长消息，段间随机延迟"""
        if len(text) <= chunk_size:
            return self.send_message(who, text)

        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        ok = True
        for i, chunk in enumerate(chunks):
            if not self.send_message(who, chunk):
                ok = False
                break
            if i < len(chunks) - 1:
                time.sleep(_rand(*chunk_delay))
        return ok

    # ══════════════════════════════════════════════════════
    #  消息去重
    # ══════════════════════════════════════════════════════

    @staticmethod
    def is_new_message(contact: str, msg_id: str) -> bool:
        return True


class _RawWxStub:
    @staticmethod
    def SwitchToChat():
        logger.debug("PyAutoGUI: SwitchToChat (stub)")

    @staticmethod
    def SwitchToContact():
        logger.debug("PyAutoGUI: SwitchToContact (stub)")
