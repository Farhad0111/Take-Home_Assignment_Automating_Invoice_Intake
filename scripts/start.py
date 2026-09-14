"""
Single entry point for the invoice intake system.

Usage:
    python scripts/start.py   # Run the pipeline
"""

from __future__ import annotations

import sys
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


def main():
    print("=" * 60)
    print("  Invoice Intake Automation System")
    print("=" * 60)

    # Check accounting API
    if not check_api_running():
        print("\n[WARNING] Accounting API is NOT running at http://localhost:8080")
        print("   Start it in another terminal with:")
        print("   python accounting_api.py")
        print()
        ans = input("Continue anyway? Partner matching will be limited. [y/N] ").strip().lower()
        if ans != "y":
            sys.exit(0)
    else:
        print("\n[OK] Accounting API is running.")

    from src.pipeline import run_pipeline
    run_pipeline()


if __name__ == "__main__":
    main()
