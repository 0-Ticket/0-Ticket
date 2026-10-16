"""Plugin registry: name-based registration, lookup, and external entry point discovery."""

import importlib
import shutil
import sys
from pathlib import Path

import pytest

from soc.plugins import DuplicatePluginError, PluginNotFoundError, PluginRegistry

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/plugins"
WORKING = "[zero_ticket_soc.siem]\nacme_siem = acme_demo:AcmeSiemAdapter\n"


class FakeAdapter:
    """Stand-in a test swaps in for the default implementation."""


@pytest.fixture
def installed_plugin(tmp_path, monkeypatch):
    """Install the sample plugin as a real distribution so discovery goes through metadata."""

    def install(entry_points_text):
        site = tmp_path / "site-packages"
        site.mkdir(exist_ok=True)
        for module in FIXTURES.glob("*.py"):
            shutil.copy(module, site / module.name)
        dist = site / "acme_demo_plugin-0.1.0.dist-info"
        dist.mkdir(exist_ok=True)
        dist.joinpath("METADATA").write_text(
            "Metadata-Version: 2.1\nName: acme-demo-plugin\nVersion: 0.1.0\n", encoding="utf-8"
        )
        dist.joinpath("entry_points.txt").write_text(entry_points_text, encoding="utf-8")
        monkeypatch.syspath_prepend(str(site))
        importlib.invalidate_caches()
        return site

    before = set(sys.modules)
    yield install
    for name in set(sys.modules) - before:
        del sys.modules[name]


def test_new_registry_has_no_builtins():
    assert PluginRegistry("siem").names() == ()


def test_get_returns_registered_implementation():
    registry = PluginRegistry("siem")
    registry.register("direct", FakeAdapter)
    assert registry.get("direct") is FakeAdapter
    assert registry.names() == ("direct",)


def test_unknown_name_lists_available():
    registry = PluginRegistry("siem")
    registry.register("direct", FakeAdapter)
    with pytest.raises(PluginNotFoundError) as caught:
        registry.get("missing")
    message = str(caught.value)
    assert "missing" in message
    assert "direct" in message


def test_duplicate_name_rejected():
    registry = PluginRegistry("siem")
    registry.register("direct", FakeAdapter)
    registry.register("direct", FakeAdapter)
    with pytest.raises(DuplicatePluginError):
        registry.register("direct", object())
    assert registry.get("direct") is FakeAdapter


def test_fake_implementation_replaces_default():
    registry = PluginRegistry("siem")
    registry.register("direct", FakeAdapter)
    registry.register("fake", object)
    # Only the selected name changes; the core keeps calling get().
    assert registry.get("direct") is FakeAdapter
    assert registry.get("fake") is object


def test_entry_point_plugin_loads_without_core_import(installed_plugin):
    installed_plugin(WORKING)
    assert "acme_demo" not in sys.modules
    registry = PluginRegistry("siem")
    assert registry.get("acme_siem").name == "acme_siem"
    assert registry.load_errors == {}
    core = [path.read_text(encoding="utf-8") for path in (ROOT / "src").rglob("*.py")]
    assert not [text for text in core if "acme" in text]


def test_broken_entry_point_is_skipped(installed_plugin):
    installed_plugin(
        WORKING + "broken_import = acme_broken:Adapter\nbroken_attr = acme_demo:Missing\n"
    )
    registry = PluginRegistry("siem")
    assert registry.get("acme_siem").name == "acme_siem"
    assert sorted(registry.load_errors) == ["broken_attr", "broken_import"]
    with pytest.raises(PluginNotFoundError):
        registry.get("broken_import")


def test_entry_point_does_not_shadow_registered_implementation(installed_plugin):
    installed_plugin(WORKING)
    registry = PluginRegistry("siem")
    registry.register("acme_siem", FakeAdapter)
    assert registry.get("acme_siem") is FakeAdapter
    assert "acme_siem" in registry.load_errors
