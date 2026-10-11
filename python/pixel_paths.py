"""Locate shared resources and preserve Python settings across source moves."""
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
APP_HOME = (Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False) else PROJECT_ROOT)
