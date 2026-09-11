"""
Single entry point for the invoice intake system.

Usage:
    python scripts/start.py              # Run pipeline, then open review UI
    python scripts/start.py --headless   # Pipeline only (no UI)
    python scripts/start.py --ui-only    # Skip pipeline, open review UI directly
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check_api_running() -> bool:
    """Return True if the accounting API responds."""
    try:
        import requests  # noqa: PLC0415
        r = requests.get("http://localhost:8080/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def run_pipeline():
    print("\n[PIPELINE] Starting pipeline...")
    from src.pipeline import run_pipeline as _run
    results = _run()
    return results


def run_ui():
    print("\n[UI] Starting review UI at http://localhost:5000 ...")
    print("    Press Ctrl+C to stop.\n")

    # Open browser after a short delay
    def open_browser():
        time.sleep(1.5)
        webbrowser.open("http://localhost:5000")

    import threading
    t = threading.Thread(target=open_browser, daemon=True)
    t.start()

    # Run Flask
    from src.review.app import app
    app.run(host="0.0.0.0", port=5000, debug=False)


def main():
    parser = argparse.ArgumentParser(description="Invoice Intake — start script")
    parser.add_argument("--headless", action="store_true", help="Run pipeline only, no UI")
    parser.add_argument("--ui-only", action="store_true", help="Open review UI without running pipeline")
    args = parser.parse_args()

    print("=" * 60)
    print("  Invoice Intake Automation System")
    print("=" * 60)

    # Check accounting API
    if not check_api_running():
        print("\n[WARNING] Accounting API is NOT running at http://localhost:8080")
        print("   Start it in another terminal with:")
        print("   python accounting_api.py")
        print()
        if not args.ui_only and not args.headless:
            ans = input("Continue anyway? Partner matching will be limited. [y/N] ").strip().lower()
            if ans != "y":
                sys.exit(0)
        else:
            print("   Continuing in headless mode (partner matching limited).")
    else:
        print("\n[OK] Accounting API is running.")

    if args.ui_only:
        run_ui()
        return

    run_pipeline()

    if not args.headless:
        print("\n" + "=" * 60)
        try:
            ans = input("\nPipeline complete. Open review UI now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans in ("", "y", "yes"):
            run_ui()


if __name__ == "__main__":
    main()
