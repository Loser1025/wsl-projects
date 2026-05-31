"""mimic_tui エントリポイント — python -m mimic_tui で起動。"""
from __future__ import annotations

import sys


def main() -> None:
    from .app import MimicApp

    app = MimicApp()
    app.run()


if __name__ == "__main__":
    main()
