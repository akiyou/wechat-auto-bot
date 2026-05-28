"""WeChat Auto Bot — 微信自动对话机器人

基于 wxauto4 + LM Studio 的轻量级自动回复系统

用法:
    python main.py                    # CLI 模式启动
    python main.py --gui              # 启动图形界面
    python main.py --test-wechat      # 仅测试微信连接
    python main.py --test-llm         # 仅测试 LM Studio 连接
    python main.py --show-config      # 显示当前配置
"""

import argparse
import logging
import sys
from pathlib import Path

from config_manager import Config
from llm_client import LLMClient
from bot_engine import BotEngine

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def setup_logging():
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # Windows GBK 控制台无法输出某些 Unicode 字符
    import sys, io
    if sys.stdout and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "bot.log", encoding="utf-8"),
        ],
    )
    return logging.getLogger("wechat_bot")


def test_wechat(driver_type: str = "pyautogui"):
    """测试微信连接"""
    print("=" * 50)
    print(f"测试微信连接 (driver: {driver_type})...")
    print("=" * 50)
    try:
        if driver_type == "wxauto":
            from wechat_driver import WeChatDriver as Driver
            wx = Driver()
            print(f"[OK] 微信已登录，昵称: {wx.nickname}")
            print(f"[OK] 在线状态: {wx.is_online()}")
        elif driver_type == "hybrid":
            from wechat_driver_hybrid import WeChatDriverHybrid as Driver
            wx = Driver()
            print(f"[OK] 混合驱动初始化成功，昵称: {wx.nickname}")
            print(f"[OK] 在线状态: {wx.is_online()}")

            # 运行诊断
            print("\n--- UIA 诊断 ---")
            import subprocess, os
            sidecar = os.path.join(os.path.dirname(__file__), "uia_sidecar.exe")
            if not os.path.isfile(sidecar):
                print(f"[ERR] 侧载程序不存在: {sidecar}")
            else:
                # 测试读取
                r = subprocess.run([sidecar, "read"], capture_output=True, timeout=15)
                out = r.stdout.decode("utf-8", errors="replace").strip()
                err = r.stderr.decode("utf-8", errors="replace").strip()
                if err:
                    print(f"[!] 读取 stderr: {err}")
                if out:
                    print(f"[OK] 读取结果: {out[:200]}")
                else:
                    print(f"[!] 读取无返回 (exit: {r.returncode})")

                # 检测已知元素
                r3 = subprocess.run([sidecar, "find", "chat_input_field"], capture_output=True, timeout=10)
                find_out = r3.stdout.decode("utf-8", errors="replace").strip()
                if find_out:
                    print(f"[OK] 输入框: {find_out[:100]}")
                else:
                    find_err = r3.stderr.decode("utf-8", errors="replace").strip()
                    print(f"[!] 输入框未找到: {find_err}")

                # 测试 UIA 树（深度 4）
                r2 = subprocess.run([sidecar, "dump", "4"], capture_output=True, timeout=15)
                tree = r2.stdout.decode("utf-8", errors="replace").strip()
                if tree:
                    print(f"[OK] UIA 树 (depth=4):\n{tree[:800]}")
        else:
            from wechat_driver_pyautogui import WeChatDriverPyAutoGUI as Driver
            wx = Driver()
            print(f"[OK] 微信已登录，昵称: {wx.nickname}")
            print(f"[OK] 在线状态: {wx.is_online()}")
        return True
    except Exception as e:
        print(f"[ERR] 微信连接失败: {e}")
        return False


def test_llm(config: Config):
    """测试 LLM 连接"""
    print("=" * 50)
    llm_cfg = config.llm
    provider = llm_cfg.get("provider", "openai_compatible")
    print(f"测试 {provider} 连接...")
    print("=" * 50)

    if not llm_cfg.get("enabled", False):
        print("[!] LLM 功能未启用 (config.json 中 llm.enabled = false)")
        print("    是否仍要测试？(y/n): ", end="", flush=True)
        choice = input().strip().lower()
        if choice != "y":
            return False

    client = LLMClient(
        provider=provider,
        base_url=llm_cfg.get("base_url", ""),
        api_key=llm_cfg.get("api_key", ""),
        model=llm_cfg.get("model", ""),
        temperature=llm_cfg.get("temperature", 0.7),
        max_tokens=llm_cfg.get("max_tokens", 1024),
        system_prompt=llm_cfg.get("system_prompt", ""),
    )

    ok = client.test_connection()
    if ok:
        models = client.list_models()
        print(f"[OK] {provider} 连接成功!")
        if models:
            print(f"[OK] 可用模型: {models}")
        else:
            print("[!] 未获取到模型列表")

        print("\n测试对话:")
        try:
            reply = client.chat("你好，请用一句话介绍你自己")
            print(f"回复: {reply}")
        except Exception as e:
            print(f"[ERR] 对话测试失败: {e}")
        return True
    else:
        print(f"[ERR] {provider} 连接失败")
        print(f"    请检查配置中的 api_key 和 network 连接")
        return False


def show_config(config: Config):
    """显示当前配置"""
    print("=" * 50)
    print("当前配置:")
    print("=" * 50)
    print(config.show_config())


def main():
    parser = argparse.ArgumentParser(
        description="WeChat Auto Bot — 微信自动对话机器人"
    )
    parser.add_argument("--test-wechat", action="store_true",
                        help="测试微信连接")
    parser.add_argument("--test-llm", action="store_true",
                        help="测试 LM Studio 连接")
    parser.add_argument("--show-config", action="store_true",
                        help="显示当前配置")
    parser.add_argument("--config", type=str, default=None,
                        help="配置文件路径 (默认: config.json)")
    parser.add_argument("--gui", action="store_true",
                        help="启动图形界面")
    parser.add_argument("--cli", action="store_true",
                        help="启动命令行模式（默认 GUI）")

    args = parser.parse_args()

    # 无参数时默认启动 GUI（双击 exe 时）
    has_action = args.gui or args.cli or args.test_wechat or args.test_llm or args.show_config
    if not has_action:
        args.gui = True

    # 加载配置
    config = Config(args.config)
    logger = setup_logging()

    if args.show_config:
        show_config(config)
        return

    if args.test_wechat:
        test_wechat(config.bot.get("driver", "hybrid"))
        return

    if args.test_llm:
        test_llm(config)
        return

    if args.gui:
        from gui import launch_gui
        launch_gui(args.config)
        return

    # ── 正常启动 ──────────────────────────────────────
    print("=" * 50)
    print("微信自动对话机器人")
    print("=" * 50)
    print(f"模式: {config.bot.get('mode', 'whitelist')}")
    print(f"LLM: {'已启用' if config.llm.get('enabled') else '未启用'}")
    if config.bot.get("contacts"):
        print(f"联系人白名单: {config.bot['contacts']}")
    print(f"反检测: {'已启用' if config.anti_detect.get('enabled') else '未启用'}")
    print("-" * 50)
    print("按 Ctrl+C 停止")
    print("=" * 50)

    engine = BotEngine(config)
    engine.run()


if __name__ == "__main__":
    main()
