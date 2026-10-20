"""
Centralized configuration loader.
Reads from .env at project root and exposes typed constants.
"""
import os
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_BASE_DIR, ".env"))
except ImportError:
    env_file = os.path.join(_BASE_DIR, ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
        except Exception:
            pass

# ──── Neo4j ────
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "osint_admin123")

# ──── Ollama ────
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "15m")

# ──── AI Thresholds ────
ZERO_SHOT_THRESHOLD = float(os.getenv("ZERO_SHOT_THRESHOLD", "0.50"))
ENTITY_JW_THRESHOLD = float(os.getenv("ENTITY_JW_THRESHOLD", "0.91"))
ENTITY_VECTOR_THRESHOLD = float(os.getenv("ENTITY_VECTOR_THRESHOLD", "0.91"))

# ──── Derived Paths ────
BASE_DIR = _BASE_DIR
DB_PATH = os.path.join(BASE_DIR, "tracking.db")
