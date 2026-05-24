#!/usr/bin/env python3

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.skills_fit.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
