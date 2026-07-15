import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "ingestion"))
sys.path.insert(0, str(ROOT / "analytics"))
sys.path.insert(0, str(ROOT))  # so `import api...` resolves as a package
