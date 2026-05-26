"""PyInstaller 打包脚本 — 生成 WeChat Auto Bot 单文件 exe"""
import PyInstaller.__main__
import os
import sys

# 以下包项目未直接使用，排除以减小体积
EXCLUDE = [
    'scipy', 'pandas', 'openpyxl',       # 大型科学计算/数据处理库（未使用）
    'cv2', 'numpy', 'pytesseract',        # 仅 OCR 模式需要（默认 clipboard）
    'matplotlib', 'sympy', 'tkinterdnd2', # 常见的无关大包
]

# UPX 压缩路径（如有则开启）
UPX_DIR = r"C:\upx"  # 下载 https://github.com/upx/upx/releases 解压到此目录即可
upx_opt = []
if os.path.isdir(UPX_DIR):
    upx_opt = ['--upx-dir', UPX_DIR]

PyInstaller.__main__.run([
    'main.py',
    '--name=WeChatAutoBot',
    '--console',                          # 保留控制台窗口看日志
    '--onefile',                          # 单文件 exe
    '--strip',                            # 去掉调试符号
    '--add-data', 'config.json;.',        # 将 config.json 打包进去
    # 显式隐藏导入（让 PyInstaller 能找到所有模块）
    '--hidden-import', 'wechat_driver_pyautogui',
    '--hidden-import', 'wechat_driver',
    '--hidden-import', 'wechat_driver_hybrid',
    '--add-data', 'uia_sidecar.exe;.',
    '--hidden-import', 'bot_engine',
    '--hidden-import', 'llm_client',
    '--hidden-import', 'anti_detect',
    '--hidden-import', 'conversation',
    '--hidden-import', 'config_manager',
    '--hidden-import', 'gui',
    '--hidden-import', 'win32gui',
    '--hidden-import', 'win32api',
    '--hidden-import', 'win32con',
    '--hidden-import', 'win32process',
    '--hidden-import', 'customtkinter',
    '--collect-all', 'customtkinter',
    # 排除不需要的大包
    *[item for pair in zip(['--exclude-module'] * len(EXCLUDE), EXCLUDE) for item in pair],
    *upx_opt,
    '--noconfirm',
])
