"""Report startup failures when launched without a console."""
import ctypes
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def main():
    try:
        logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
            HERE / "perfect_pixel.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")])
        from perfect_pixel_gui import App
        App().mainloop()
    except Exception as exc:
        logging.exception("Application startup failed")
        text = f"Perfect Pixel 启动失败：\n{exc}\n\n请保留项目的 .venv 文件夹。\n详情见 {HERE / 'perfect_pixel.log'}"
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, text, "Perfect Pixel", 0x10)
        else:
            print(text, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
