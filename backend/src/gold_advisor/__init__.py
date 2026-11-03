import sys
from pathlib import Path

# Vercel imports the API as "src.gold_advisor.api" (pyproject [tool.vercel]); the code itself
# imports "gold_advisor.*", so make src/ importable in that case.
if __name__ == "src.gold_advisor":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
