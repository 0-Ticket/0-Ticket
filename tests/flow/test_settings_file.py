"""The settings file the demo flow test writes by hand (#104).

``test_demo_flow`` appends an ``[agent_log]`` section with the temporary
directory pytest gave it, so whatever that path contains has to come back out of
the file unchanged. This has broken three times: a Windows path read as escapes,
a quote in a folder name, and a surrogate pair for a character outside the BMP.
No database is needed to check that, so these tests are not marked ``db``.
"""

import tomllib

import pytest
from fakes import toml_string

PATHS = [
    pytest.param("/tmp/pytest-1/agent_log", id="plain"),
    pytest.param("C:\\Users\\juhye\\AppData\\Local\\Temp\\pytest-1\\agent_log", id="windows"),
    pytest.param("/tmp/John D'Angelo/agent_log", id="single-quote"),
    pytest.param('/tmp/we"ird/agent_log', id="double-quote"),
    pytest.param("/tmp/we\nird/agent_log", id="newline"),
    pytest.param("/tmp/we\tird/agent_log", id="tab"),
    pytest.param("/tmp/\u3053\u3093/agent_log", id="non-ascii"),
    pytest.param("/tmp/\U0001f600/agent_log", id="outside-bmp"),
]


@pytest.mark.parametrize("path", PATHS)
def test_the_artifact_path_survives_the_settings_file(path):
    """The quoted path parses back as itself, whatever is in it."""
    settings = f"[agent_log]\nartifact_dir = {toml_string(path)}\n"
    assert tomllib.loads(settings)["agent_log"]["artifact_dir"] == path


@pytest.mark.parametrize("path", PATHS)
def test_the_quoted_path_is_one_toml_basic_string(path):
    """No raw newline or quote escapes the value and breaks the rest of the file."""
    quoted = toml_string(path)
    assert quoted.startswith('"') and quoted.endswith('"')
    assert "\n" not in quoted
    assert '"' not in quoted[1:-1].replace('\\"', "")
