# Script temporaneo: sostituisce gli "except:" nudi con "except Exception:"
import re
import sys

FILES = [
    r"app\hardware\fluke_esa612.py",
    r"app\ui\main_window.py",
    r"app\ui\dialogs\advanced_search_dialog.py",
    r"app\ui\dialogs\audit_log_dialog.py",
    r"app\ui\dialogs\expiring_devices_dialog.py",
    r"app\ui\dialogs\manager_dialogs.py",
    r"app\ui\dialogs\qr_device_scanner_dialog.py",
]

PATTERN = re.compile(r"(?m)^(\s*)except\s*:")

total = 0
for path in FILES:
    with open(path, encoding="utf-8", newline="") as f:
        src = f.read()
    fixed, n = PATTERN.subn(r"\1except Exception:", src)
    if n:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(fixed)
    print(f"{path}: {n} sostituzioni")
    total += n

print(f"TOTALE: {total}")
sys.exit(0 if total > 0 else 1)
