"""Dev server entry point. Run with: uv run python -m manicure"""

import uvicorn

from manicure.config import get_settings
from manicure.main import LOG_CONFIG

settings = get_settings()
uvicorn.run(
    "manicure.main:app",
    host="127.0.0.1",
    port=settings.web_port,
    reload=True,
    log_config=LOG_CONFIG,
)
