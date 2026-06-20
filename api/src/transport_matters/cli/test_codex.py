"""Tests for the `manicure codex` launch path."""

import json
import os
import tomllib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from transport_matters import env_keys
from transport_matters.cli import BindFailure, main, workspace_root
from transport_matters.cli.codex_cmd import _reset_codex_ca_certificate_cache_for_tests
from transport_matters.cli.trust import (
    ConfiguredCACertificateMissingError,
    MitmproxyCAMissingError,
    SystemTrustSnapshotError,
    TrustBundleWriteError,
)

from ._helpers import _which_by_name

runner = CliRunner()


@pytest.fixture
def spy_run_client_children(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the generic client runner so `codex` never forks."""
    spy = MagicMock()
    monkeypatch.setattr("transport_matters.cli.runner._run_client_children", spy)
    return spy


def test_codex_print_command_uses_explicit_proxy_mode(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["codex", "--proxy-port", "9000", "--web-port", "9001", "--print-command"],
    )
    assert result.exit_code == 0, result.output
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert any("--mode regular" in line for line in lines)
    assert any("--listen-port 9000" in line for line in lines)
    assert any(line.startswith("/bin/codex -c shell_environment_policy.exclude=") for line in lines)


def test_codex_channel_flag_uses_preview_defaults(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv(env_keys.CHANNEL, raising=False)

    result = runner.invoke(
        main,
        ["codex", "--channel", "preview", "--no-codex", "--print-command"],
    )

    assert result.exit_code == 0, result.output
    assert "--listen-port 8797" in result.stdout
    assert os.environ[env_keys.CHANNEL] == "preview"


def test_codex_channel_env_reaches_launch_environment(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(main, ["codex", "--channel", "preview", "--no-codex"])

    assert result.exit_code == 0, result.output
    kwargs = spy_run_client_children.call_args.kwargs
    assert kwargs["proxy_port"] == 8797
    assert kwargs["web_port"] == 8798
    assert kwargs["mitmdump_env"][env_keys.CHANNEL] == "preview"


def test_codex_print_command_does_not_create_workspace_run_dir(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)
    workdir = tmp_path / "project"
    workdir.mkdir()
    home_dir = tmp_path / "codex-home"

    result = runner.invoke(
        main,
        ["codex", "--work-dir", str(workdir), "--agent-home-dir", str(home_dir), "--print-command"],
    )

    assert result.exit_code == 0, result.output
    assert "mitmdump" in result.stdout
    spy_run_client_children.assert_not_called()
    assert not workspace_root(workdir).exists()
    assert not home_dir.exists()


def test_codex_sets_proxy_env_on_managed_child(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    bundle_path = tmp_path / "ca.pem"
    bundle_path.write_text("bundle", encoding="utf-8")
    monkeypatch.setattr(
        "transport_matters.cli.resolve_codex_ca_certificate",
        lambda *, env, bundle_dir: bundle_path,
    )

    result = runner.invoke(
        main,
        [
            "codex",
            ".",
            "--proxy-port",
            "9000",
            "--web-port",
            "9001",
            "--",
            "exec",
            "ping",
        ],
    )
    assert result.exit_code == 0, result.output

    kwargs = spy_run_client_children.call_args.kwargs
    client = kwargs["client"]
    assert client is not None
    assert client.name == "codex"
    assert client.argv[0] == "/bin/codex"
    assert client.argv[1] == "-c"
    assert client.argv[2].startswith("shell_environment_policy.exclude=")
    assert client.argv[-2:] == ["exec", "ping"]
    assert client.env["HTTP_PROXY"] == "http://127.0.0.1:9000"
    assert client.env["HTTPS_PROXY"] == "http://127.0.0.1:9000"
    assert client.env["http_proxy"] == "http://127.0.0.1:9000"
    assert client.env["https_proxy"] == "http://127.0.0.1:9000"
    assert client.env["CODEX_NETWORK_PROXY_ACTIVE"] == "1"
    assert client.env["CODEX_CA_CERTIFICATE"] == str(bundle_path)
    assert "localhost" in client.env["NO_PROXY"]
    assert "127.0.0.1" in client.env["NO_PROXY"]
    assert kwargs["mitmdump_argv"][:3] == ["/bin/mitmdump", "--mode", "regular"]


def test_codex_managed_mint_seeds_rollout_and_resumes(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    # Managed-mint (§5.2b): the launcher mints the native uuid, pre-seeds the rollout, hands the
    # addon the owned native id + source_descriptor via env, and launches `codex resume <native>`.
    # tmp_storage points $HOME at tmp_path, so the seed lands under tmp_path/.codex (isolated).
    from transport_matters.index.adapters.base import FileTailSource, decode_source_descriptor

    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.setattr(
        "transport_matters.cli.resolve_codex_ca_certificate",
        lambda *, env, bundle_dir: tmp_path / "ca.pem",
    )

    result = runner.invoke(main, ["codex", "--work-dir", ".", "--", "exec", "ping"])
    assert result.exit_code == 0, result.output

    kwargs = spy_run_client_children.call_args.kwargs
    env = kwargs["mitmdump_env"]
    client = kwargs["client"]

    # the addon learns the owned codex identity through the env contract
    assert env["TRANSPORT_MATTERS_HARNESS"] == "codex"
    native = env["TRANSPORT_MATTERS_OWNED_NATIVE_SESSION_ID"]
    source = decode_source_descriptor(env["TRANSPORT_MATTERS_OWNED_SOURCE_DESCRIPTOR"])
    assert isinstance(source, FileTailSource)
    assert source.format == "codex_rollout"
    assert native in Path(source.path).name  # the rollout filename carries the owned uuid

    # the codex child is launched to RESUME the owned session (head + passthrough tail preserved)
    assert client.argv[0] == "/bin/codex"
    assert client.argv[1] == "-c"
    resume_at = client.argv.index("resume")
    assert client.argv[resume_at + 1] == native
    assert client.argv[-2:] == ["exec", "ping"]

    # the rollout is pre-seeded with exactly the minimal session_meta keyed on the owned uuid
    seeded = Path(source.path)
    assert seeded.exists()
    (line,) = seeded.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["payload"]["id"] == native


def test_codex_home_dir_sets_codex_home_manifest_and_keeps_ca(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.setenv("CODEX_HOME", "/parent/codex")
    monkeypatch.chdir(tmp_path)
    bundle_path = tmp_path / "ca.pem"
    bundle_path.write_text("bundle", encoding="utf-8")
    monkeypatch.setattr(
        "transport_matters.cli.resolve_codex_ca_certificate",
        lambda *, env, bundle_dir: bundle_path,
    )
    captured: dict[str, Any] = {}

    def _capture_manifest(**kwargs: Any) -> None:
        client = kwargs["client"]
        assert client is not None
        manifest_path = (
            workspace_root(client.cwd) / client.env["TRANSPORT_MATTERS_RUN_ID"] / "manifest.json"
        )
        captured["raw"] = json.loads(manifest_path.read_text(encoding="utf-8"))

    spy_run_client_children.side_effect = _capture_manifest

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(
        main,
        [
            "codex",
            str(workdir),
            "--agent-home-dir",
            "homes/codex",
            "--proxy-port",
            "9000",
            "--web-port",
            "9001",
        ],
    )
    assert result.exit_code == 0, result.output
    expected_home = (tmp_path / "homes" / "codex").resolve()
    assert expected_home.is_dir()
    client_env = spy_run_client_children.call_args.kwargs["client"].env
    assert client_env["CODEX_HOME"] == str(expected_home)
    assert client_env["CODEX_CA_CERTIFICATE"] == str(bundle_path)
    assert captured["raw"]["home_dir"] == str(expected_home)


def test_codex_unset_home_dir_omits_codex_home(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    bundle_path = tmp_path / "ca.pem"
    bundle_path.write_text("bundle", encoding="utf-8")
    monkeypatch.setattr(
        "transport_matters.cli.resolve_codex_ca_certificate",
        lambda *, env, bundle_dir: bundle_path,
    )

    result = runner.invoke(main, ["codex", "--work-dir", "."])
    assert result.exit_code == 0, result.output
    client_env = spy_run_client_children.call_args.kwargs["client"].env
    assert "CODEX_HOME" not in client_env


def test_codex_writes_workspace_manifest_visible_to_managed_child(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_STORAGE_DIR", raising=False)
    bundle_path = tmp_path / "ca.pem"
    bundle_path.write_text("bundle", encoding="utf-8")
    monkeypatch.setattr(
        "transport_matters.cli.resolve_codex_ca_certificate",
        lambda *, env, bundle_dir: bundle_path,
    )
    captured: dict[str, Any] = {}

    def _capture_manifest(**kwargs: Any) -> None:
        client = kwargs["client"]
        assert client is not None
        run_id = client.env["TRANSPORT_MATTERS_RUN_ID"]
        manifest_path = workspace_root(client.cwd) / run_id / "manifest.json"
        captured["exists_mid_run"] = manifest_path.exists()
        captured["raw"] = json.loads(manifest_path.read_text(encoding="utf-8"))

    spy_run_client_children.side_effect = _capture_manifest

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(
        main,
        ["codex", "--work-dir", str(workdir), "--proxy-port", "9000", "--web-port", "9001"],
    )
    assert result.exit_code == 0, result.output

    kwargs = spy_run_client_children.call_args.kwargs
    client_env = kwargs["client"].env
    raw = captured["raw"]
    expected_storage = workspace_root(workdir) / raw["run_id"]
    assert captured["exists_mid_run"] is True
    assert raw["cwd"] == str(workdir)
    assert raw["proxy_port"] == 9000
    assert raw["web_port"] == 9001
    assert raw["storage_dir"] == str(expected_storage)
    assert raw["run_id"] == kwargs["mitmdump_env"]["TRANSPORT_MATTERS_RUN_ID"]
    assert raw["run_id"] == client_env["TRANSPORT_MATTERS_RUN_ID"]
    assert client_env["TRANSPORT_MATTERS_STORAGE_DIR"] == str(expected_storage)


def test_codex_channel_default_bind_failure_fails_without_reallocation(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    bundle_path = tmp_path / "ca.pem"
    bundle_path.write_text("bundle", encoding="utf-8")
    monkeypatch.setattr(
        "transport_matters.cli.resolve_codex_ca_certificate",
        lambda *, env, bundle_dir: bundle_path,
    )
    log_path = tmp_path / "mitmdump.log"

    def _side_effect(**kwargs: Any) -> None:
        raise BindFailure(
            proxy_port=kwargs["proxy_port"],
            web_port=kwargs["web_port"],
            failing_ports=(8797,),
            log_path=log_path,
        )

    spy_run_client_children.side_effect = _side_effect

    result = runner.invoke(main, ["codex", "--channel", "preview", "--no-codex"])

    assert result.exit_code == 2
    assert "pinned port in use: --proxy-port 8797" in result.output
    assert spy_run_client_children.call_count == 1


def test_codex_excludes_manicure_proxy_env_from_shell_commands(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    bundle_path = tmp_path / "ca.pem"
    bundle_path.write_text("bundle", encoding="utf-8")
    monkeypatch.setattr(
        "transport_matters.cli.resolve_codex_ca_certificate",
        lambda *, env, bundle_dir: bundle_path,
    )

    result = runner.invoke(
        main,
        [
            "codex",
            ".",
            "--proxy-port",
            "9000",
            "--web-port",
            "9001",
            "--",
            "exec",
            "ping",
        ],
    )
    assert result.exit_code == 0, result.output

    client = spy_run_client_children.call_args.kwargs["client"]
    assert client.env["HTTP_PROXY"] == "http://127.0.0.1:9000"
    assert client.env["CODEX_CA_CERTIFICATE"] == str(bundle_path)
    assert client.argv[-2:] == ["exec", "ping"]
    policy_args = [
        arg
        for index, arg in enumerate(client.argv)
        if index > 0
        and client.argv[index - 1] == "-c"
        and arg.startswith("shell_environment_policy.exclude=")
    ]
    assert len(policy_args) == 1
    excluded = set(tomllib.loads(policy_args[0])["shell_environment_policy"]["exclude"])
    assert {
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "CODEX_CA_CERTIFICATE",
        "CURL_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
    }.issubset(excluded)
    assert "CODEX_NETWORK_PROXY_ACTIVE" not in excluded


def test_codex_sanitizes_managed_child_proxy_and_trust_env(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.setenv("HTTP_PROXY", "http://corp-proxy:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy:8080")
    monkeypatch.setenv("ALL_PROXY", "socks5://corp-proxy:1080")
    monkeypatch.setenv("NO_PROXY", "internal.example")
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/custom.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/tmp/requests.pem")
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", "/tmp/node-extra.pem")
    monkeypatch.setenv("NODE_TLS_REJECT_UNAUTHORIZED", "0")
    monkeypatch.setenv("npm_config_proxy", "http://corp-proxy:8080")
    monkeypatch.setenv("npm_config_cafile", "/tmp/npm-ca.pem")
    bundle_path = tmp_path / "ca.pem"
    bundle_path.write_text("bundle", encoding="utf-8")
    monkeypatch.setattr(
        "transport_matters.cli.resolve_codex_ca_certificate",
        lambda *, env, bundle_dir: bundle_path,
    )

    result = runner.invoke(
        main,
        [
            "codex",
            ".",
            "--proxy-port",
            "9000",
            "--web-port",
            "9001",
            "--",
            "exec",
            "ping",
        ],
    )
    assert result.exit_code == 0, result.output

    client_env = spy_run_client_children.call_args.kwargs["client"].env
    assert client_env["HTTP_PROXY"] == "http://127.0.0.1:9000"
    assert client_env["HTTPS_PROXY"] == "http://127.0.0.1:9000"
    assert client_env["ALL_PROXY"] == "http://127.0.0.1:9000"
    assert client_env["CODEX_NETWORK_PROXY_ACTIVE"] == "1"
    assert client_env["WS_PROXY"] == "http://127.0.0.1:9000"
    assert client_env["WSS_PROXY"] == "http://127.0.0.1:9000"
    assert client_env["NO_PROXY"] == "127.0.0.1,localhost"
    assert client_env["no_proxy"] == "127.0.0.1,localhost"
    assert client_env["CODEX_CA_CERTIFICATE"] == str(bundle_path)
    for key in (
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "NODE_TLS_REJECT_UNAUTHORIZED",
        "npm_config_proxy",
        "npm_config_cafile",
    ):
        assert key not in client_env


def test_codex_no_codex_plus_passthrough_fails(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )

    result = runner.invoke(main, ["codex", "--no-codex", "--", "exec", "ping"])
    assert result.exit_code == 2
    assert "--no-codex is incompatible" in result.output
    spy_run_client_children.assert_not_called()


def test_codex_refuses_when_codex_missing(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )

    result = runner.invoke(main, ["codex"])
    assert result.exit_code == 2
    assert "`codex` was not found" in result.output
    spy_run_client_children.assert_not_called()


def test_codex_no_codex_print_command_omits_child(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(main, ["codex", "--no-codex", "--print-command"])
    assert result.exit_code == 0, result.output
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("/bin/mitmdump --mode regular")


def test_codex_no_codex_skips_trust_bootstrap_failures(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("CODEX_CA_CERTIFICATE", raising=False)

    def raise_error(*, env: dict[str, str], bundle_dir: Path | None) -> Path:
        raise MitmproxyCAMissingError(Path("/missing/mitmproxy-ca-cert.pem"))

    monkeypatch.setattr("transport_matters.cli.resolve_codex_ca_certificate", raise_error)

    result = runner.invoke(main, ["codex", "--no-codex"])
    assert result.exit_code == 0, result.output
    assert "point your client at the proxy:" in result.output
    assert "HTTP_PROXY=http://127.0.0.1:" in result.output
    assert "Set CODEX_CA_CERTIFICATE to a PEM bundle" in result.output
    spy_run_client_children.assert_called_once()
    assert spy_run_client_children.call_args.kwargs["client"] is None


def test_codex_no_codex_uses_existing_ca_hint_when_present(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    bundle_path = tmp_path / "ca.pem"
    bundle_path.write_text("bundle", encoding="utf-8")
    monkeypatch.setenv("CODEX_CA_CERTIFICATE", str(bundle_path))

    def fail_if_called(*, env: dict[str, str], bundle_dir: Path | None) -> Path:
        raise AssertionError("proxy-only mode should not resolve trust bundles")

    monkeypatch.setattr("transport_matters.cli.resolve_codex_ca_certificate", fail_if_called)

    result = runner.invoke(main, ["codex", "--no-codex"])
    assert result.exit_code == 0, result.output
    assert f"CODEX_CA_CERTIFICATE={bundle_path.resolve()} codex" in result.output
    spy_run_client_children.assert_called_once()
    assert spy_run_client_children.call_args.kwargs["client"] is None


def test_codex_reuses_generated_bundle_after_exit(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    _reset_codex_ca_certificate_cache_for_tests()
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("CODEX_CA_CERTIFICATE", raising=False)
    captured: list[str] = []

    def fake_resolve(*, env: dict[str, str], bundle_dir: Path | None) -> Path:
        assert bundle_dir is not None
        bundle_path = bundle_dir / "codex-ca-bundle.pem"
        bundle_path.write_text("generated", encoding="utf-8")
        captured.append(str(bundle_path))
        return bundle_path

    monkeypatch.setattr("transport_matters.cli.resolve_codex_ca_certificate", fake_resolve)

    result = runner.invoke(main, ["codex", "--proxy-port", "9000", "--web-port", "9001"])
    assert result.exit_code == 0, result.output
    second = runner.invoke(main, ["codex", "--proxy-port", "9000", "--web-port", "9001"])
    assert second.exit_code == 0, second.output

    assert len(captured) == 1
    bundle_path = Path(captured[0])
    assert spy_run_client_children.call_args.kwargs["client"].env["CODEX_CA_CERTIFICATE"] == str(
        bundle_path
    )
    assert bundle_path.exists()


@pytest.mark.parametrize(
    ("error", "needle"),
    [
        (
            ConfiguredCACertificateMissingError(Path("/missing/codex-ca.pem")),
            "CODEX_CA_CERTIFICATE points to a missing file.",
        ),
        (
            MitmproxyCAMissingError(Path("/missing/mitmproxy-ca-cert.pem")),
            "mitmproxy CA missing for Codex trust bootstrap.",
        ),
        (
            SystemTrustSnapshotError("snapshot failed"),
            "could not snapshot the active system trust roots.",
        ),
        (
            TrustBundleWriteError(Path("/tmp/codex-ca-bundle.pem"), "permission denied"),
            "could not expose CODEX_CA_CERTIFICATE for Codex.",
        ),
    ],
)
def test_codex_surfaces_trust_bootstrap_failures(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
    error: RuntimeError,
    needle: str,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    def raise_error(*, env: dict[str, str], bundle_dir: Path | None) -> Path:
        raise error

    monkeypatch.setattr("transport_matters.cli.resolve_codex_ca_certificate", raise_error)

    result = runner.invoke(main, ["codex"])
    assert result.exit_code == 2
    assert needle in result.output
    spy_run_client_children.assert_not_called()
