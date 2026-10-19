"""Command line wrapper for the L1 entity lookup runtime."""

import soc.l1.__main__ as cli


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
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "build_runtime", lambda _settings: runtime)

    assert cli.main(["--all"]) == 0

    assert runtime.all_alerts is True
    assert runtime.closed is True
    assert capsys.readouterr().out == "Processed 3 L1 item(s)\n"


def test_cli_without_all_processes_one_page(monkeypatch):
    runtime = RuntimeStub()
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "build_runtime", lambda _settings: runtime)

    cli.main([])

    assert runtime.all_alerts is False
    assert runtime.closed is True
