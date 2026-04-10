"""Dev server entry point. Run with: uv run python -m manicure"""

import uvicorn

from manicure.main import LOG_CONFIG

uvicorn.run(
    "manicure.main:app",
    host="127.0.0.1",
    port=8000,
    reload=True,
    log_config=LOG_CONFIG,
)
