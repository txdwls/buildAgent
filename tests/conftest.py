"""Shared test fixtures. Keep this file small — package-specific
fixtures live next to their tests.
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENAI_API_KEY", "test-openai")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "test-pub")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "test-sec")
os.environ.setdefault("LANGFUSE_HOST", "http://localhost:3000")
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")
