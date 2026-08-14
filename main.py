#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from nicegui import ui

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.chdir(BASE_DIR)

from ui.dashboard import WebTPM

def main():
    try:
        # Initialize UI application
        WebTPM()



        print("🚀 TPM Command Center running on http://127.0.0.1:8080")

        # Launch NiceGUI Web Server
        ui.run(
            title="TPM Enterprise Command Center",
            port=8080,
            host='127.0.0.1',
            dark=True,
            reload=True,
            show=False
        )
    except Exception as e:
        import traceback
        print("CRITICAL ERROR DURING STARTUP:", file=sys.stderr)
        traceback.print_exc()

if __name__ in {"__main__", "__mp_main__"}:
    main()
