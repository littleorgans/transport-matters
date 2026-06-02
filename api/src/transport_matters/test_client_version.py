from transport_matters.client_version import detect_client_version


class _Headers:
    """Case-insensitive header map mirroring mitmproxy Headers `.get`."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = {name.lower(): value for name, value in values.items()}

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._values.get(name.lower(), default)


def test_detect_claude_cli_user_agent() -> None:
    headers = _Headers({"user-agent": "claude-cli/2.1.154 (external, cli)"})
    assert detect_client_version(headers) == "claude-cli/2.1.154"


def test_detect_user_agent_is_case_insensitive() -> None:
    headers = _Headers({"User-Agent": "claude-cli/2.1.154 (external, cli)"})
    assert detect_client_version(headers) == "claude-cli/2.1.154"


def test_detect_codex_user_agent() -> None:
    headers = _Headers({"user-agent": "codex_cli_rs/0.5.0 (Mac OS 15.0; arm64)"})
    assert detect_client_version(headers) == "codex_cli_rs/0.5.0"


def test_detect_first_token_when_user_agent_has_no_parens() -> None:
    headers = _Headers({"user-agent": "openai-python/1.2.3"})
    assert detect_client_version(headers) == "openai-python/1.2.3"


def test_x_app_used_when_user_agent_is_not_name_version() -> None:
    headers = _Headers({"user-agent": "Mozilla", "x-app": "cli/1.0"})
    assert detect_client_version(headers) == "cli/1.0"


def test_falls_back_to_stainless_package_version() -> None:
    headers = _Headers({"x-stainless-package-version": "0.39.0"})
    assert detect_client_version(headers) == "0.39.0"


def test_returns_none_when_nothing_recognizable() -> None:
    headers = _Headers({"content-type": "application/json"})
    assert detect_client_version(headers) is None


def test_returns_none_for_empty_user_agent() -> None:
    headers = _Headers({"user-agent": "   "})
    assert detect_client_version(headers) is None


def test_accepts_plain_dict() -> None:
    assert detect_client_version({"user-agent": "claude-cli/2.1.154"}) == ("claude-cli/2.1.154")


def test_returns_none_for_none_headers() -> None:
    assert detect_client_version(None) is None
