"""Streamlit Community Cloud entry point for the PUBBA Power dashboard."""

from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from dashboard.app import main


if __name__ == "__main__":
    main()
