"""Report startup failures when launched without a console."""
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import sys

from pixel_paths import APP_HOME as HERE


def main():
    try:
        logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
            HERE / "perfect_pixel.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")])
        if "--legacy" in sys.argv:
            from perfect_pixel_gui import App
            App().mainloop()
        else:
            from pixel_desktop import run
            run()
    except Exception as exc:
        logging.exception("Application startup failed")
        text = (f"Perfect Pixel 启动失败：\n{exc}\n\n"
                "请确认已安装 python/requirements.txt 中的依赖，并构建 frontend 界面。\n"
                "Windows 还需要 Microsoft Edge WebView2 Runtime。\n"
                f"详情见 {HERE / 'perfect_pixel.log'}")
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, text, "Perfect Pixel", 0x10)
        else:
            print(text, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
