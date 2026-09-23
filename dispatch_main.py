"""Entry point for SNBR Report Dispatch, the sister app of the SNBR TMS App."""

import sys
from pathlib import Path

# Ensure the SNBR_TMS_App package is importable when running directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dispatch_gui.app import DispatchApp


def main():
    app = DispatchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
