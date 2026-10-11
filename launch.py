"""Keep the original Python launch command after organizing the sources."""
from pathlib import Path
import runpy
import sys


if __name__ == "__main__":
    source = Path(__file__).resolve().parent / "python"
    sys.path.insert(0, str(source))
    runpy.run_path(str(source / "launch.py"), run_name="__main__")
