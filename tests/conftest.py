"""Path setup: faz `compute` importável a partir de tests/."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / ".claude" / "skills" / "_chess_shared"
sys.path.insert(0, str(SHARED))
