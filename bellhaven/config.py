"""Shared configuration. Reads from environment with sane defaults."""
import os

def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

_load_dotenv()

API_BASE = os.environ.get("BELHAVEN_API_BASE", "https://analyst-assessment-production.up.railway.app")
API_ROOT = f"{API_BASE}/api/v1"
TOKEN = os.environ.get("BELHAVEN_TOKEN", "")
DB_PATH = os.environ.get("BELHAVEN_DB", os.path.join(os.path.dirname(__file__), "..", "decisions.db"))
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# Parents whose children are in scope for Bellhaven reconciliation. Everything
# else (Stonebridge, Juniper Point, Millstone, ...) is a decoy and must not be
# touched. Harborview and Cedar Trail are in scope because Bellhaven acquired
# from them (About page, 2025 and 2026).
IN_SCOPE_PARENTS = {
    "Bellhaven": "Bellhaven Senior Living (Parent Account)",
    "Harborview": "Harborview Care Group (Parent Account)",
    "CedarTrail": "Cedar Trail Communities (Parent Account)",
}
