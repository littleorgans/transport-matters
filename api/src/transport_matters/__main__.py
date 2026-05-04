"""Dev server entry point. Run with: uv run python -m transport_matters."""

import uvicorn

from transport_matters.config import get_settings
from transport_matters.main import LOG_CONFIG

settings = get_settings()
uvicorn.run(
    "transport_matters.main:app",
    host="127.0.0.1",
    port=settings.web_port,
    reload=True,
    log_config=LOG_CONFIG,
)
