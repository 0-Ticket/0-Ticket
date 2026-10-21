"""Command line wrapper for the L1 entity lookup runtime."""

import soc.l1.__main__ as cli
from soc.plugins import PluginRegistry


class RuntimeStub:
    def __init__(self):
        self.all_alerts = None
        self.closed = False

    def run(self, *, all_alerts):
        self.all_alerts = all_alerts
        return 3

    def close(self):
        self.closed = True


def test_cli_passes_all_flag_and_closes_runtime(monkeypatch, capsys):
    runtime = RuntimeStub()
    monkeypatch.setattr(cli, "load_config", lambda **_kwargs: object())
    monkeypatch.setattr(cli, "build_runtime", lambda _settings, _environ, **_kwargs: runtime)

    assert cli.main(["--all"]) == 0

    assert runtime.all_alerts is True
    assert runtime.closed is True
    assert capsys.readouterr().out == "Processed 3 L1 item(s)\n"


def test_cli_without_all_processes_one_page(monkeypatch):
    runtime = RuntimeStub()
    monkeypatch.setattr(cli, "load_config", lambda **_kwargs: object())
    monkeypatch.setattr(cli, "build_runtime", lambda _settings, _environ, **_kwargs: runtime)

    cli.main([])

    assert runtime.all_alerts is False
    assert runtime.closed is True


def test_cli_passes_environment_and_registries_to_the_runtime(monkeypatch):
    """#81: a test runs the command with fake plugins, as it does soc.ingest or soc.branch."""
    runtime = RuntimeStub()
    settings = object()
    environ = {"DATABASE_URL": "postgresql://localhost/zt"}
    seen = {}
    registries = {
        name: PluginRegistry(group)
        for name, group in (
            ("stores", "stores"),
            ("lookups", "lookups"),
            ("siem", "siem_mcp_adapters"),
            ("providers", "llm_providers"),
            ("vectors", "vector_stores"),
            ("embedders", "embedders"),
        )
    }

    def load(**kwargs):
        seen["load"] = kwargs
        return settings

    def build(given_settings, given_environ, **kwargs):
        seen["build"] = (given_settings, given_environ, kwargs)
        return runtime

    monkeypatch.setattr(cli, "load_config", load)
    monkeypatch.setattr(cli, "build_runtime", build)

    cli.main([], environ=environ, **registries)

    assert seen["load"] == {"environ": environ}
    assert seen["build"] == (
        settings,
        environ,
        {
            "store_registry": registries["stores"],
            "lookup_registry": registries["lookups"],
            "siem_registry": registries["siem"],
            "provider_registry": registries["providers"],
            "vector_registry": registries["vectors"],
            "embedder_registry": registries["embedders"],
        },
    )
    assert runtime.closed is True
