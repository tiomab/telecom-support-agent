"""Paths and settings. Everything can be overridden with environment variables."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
KB_DIR = DATA_DIR / "kb"
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", ROOT / ".chroma"))
COLLECTION = "novatel_kb"

# Backend service: customer accounts + outages (REST for auth, MCP for the agent's tools)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
MCP_URL = os.getenv("MCP_URL", f"{BACKEND_URL}/mcp/")

# Model: a small, fast model is enough for a support agent. Override with MODEL_ID.
MODEL_ID = os.getenv("MODEL_ID", "claude-haiku-5-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1024"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

# Reliability limits
MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", "8"))
SEARCH_TOP_K = int(os.getenv("SEARCH_TOP_K", "4"))
