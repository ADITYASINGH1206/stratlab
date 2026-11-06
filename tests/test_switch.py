"""Tests for Switch integration, room documents, template builder, and ledger."""

from pathlib import Path

import yaml
from typer.testing import CliRunner

from stratlab.cli import app
from stratlab.engine.ledger import add_ledger_entry, query_ledger, render_ledger_markdown
from switch.build_template import build_template

runner = CliRunner()
SWITCH_DIR = Path(__file__).resolve().parent.parent / "switch"


def test_switch_markdown_files_exist():
    """Verify all agent and room markdown source files exist and have content."""
    agent_files = [
        "strategist.md",
        "pine-coder.md",
        "backtester.md",
        "skeptic.md",
        "scribe.md",
    ]
    for af in agent_files:
        p = SWITCH_DIR / "agents" / af
        assert p.exists(), f"Missing agent file: {p}"
        content = p.read_text()
        assert len(content) > 100
        assert "Responsibilities" in content or "Role" in content

    room_files = [
        "lab-charter.md",
        "lab-instructions.md",
        "ledger-instructions.md",
    ]
    for rf in room_files:
        p = SWITCH_DIR / "rooms" / rf
        assert p.exists(), f"Missing room file: {p}"
        content = p.read_text()
        assert len(content) > 100


def test_build_template_structure():
    """Verify build_template produces complete and valid Switch template dict."""
    tmpl = build_template()
    assert tmpl["version"] == 1
    assert "params" in tmpl
    assert "bridge" in tmpl["params"]

    # Agents
    agents = tmpl["agents"]
    assert len(agents) == 5
    agent_names = {a["name"] for a in agents}
    assert agent_names == {
        "stratlab-strategist",
        "stratlab-pine-coder",
        "stratlab-backtester",
        "stratlab-skeptic",
        "stratlab-scribe",
    }
    for a in agents:
        assert a["repo"] == "https://github.com/ADITYASINGH1206/stratlab"
        assert len(a["instructions"]) > 100

    # Rooms
    rooms = tmpl["rooms"]
    assert len(rooms) == 2
    lab_room = next(r for r in rooms if r["name"] == "stratlab-lab")
    ledger_room = next(r for r in rooms if r["name"] == "stratlab-ledger")

    # Lab room details
    assert len(lab_room["agents"]) == 5
    assert "quant-on-call" in [role["name"] for role in lab_room.get("roles", [])]
    assert "Lab Charter" in [doc["name"] for doc in lab_room.get("docs", [])]

    # Ledger room details
    assert len(ledger_room["agents"]) == 2
    assert "Strategy Ledger" in [doc["name"] for doc in ledger_room.get("docs", [])]

    # Links
    assert len(tmpl["links"]) >= 1
    assert tmpl["links"][0]["from"] == "stratlab-lab"
    assert tmpl["links"][0]["to"] == "stratlab-ledger"


def test_stratlab_template_yaml_file():
    """Verify that committed switch/stratlab.template.yaml is valid YAML and matches template."""
    template_file = SWITCH_DIR / "stratlab.template.yaml"
    assert template_file.exists()
    content = template_file.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    assert parsed["version"] == 1
    assert len(parsed["agents"]) == 5
    assert len(parsed["rooms"]) == 2


def test_ledger_add_render_query():
    """Verify adding, querying, and rendering strategy ledger entries."""
    entry = add_ledger_entry(
        target="S-001@v1",
        verdict="kill",
        decided_by="TestTrader",
        note="Too few trades on 4h timeframe",
    )
    assert entry["spec_id"] == "S-001"
    assert entry["verdict"] == "KILL"
    assert entry["decided_by"] == "TestTrader"

    entries = query_ledger(spec_id="S-001")
    assert len(entries) >= 1
    assert entries[-1]["verdict"] == "KILL"

    md = render_ledger_markdown()
    assert "# Strategy Ledger" in md
    assert "S-001" in md
    assert "KILL" in md


def test_cli_ledger_commands():
    """Verify CLI interface for stratlab ledger."""
    res_add = runner.invoke(
        app,
        [
            "ledger",
            "add",
            "S-020@v1",
            "--verdict",
            "park",
            "--by",
            "Bob",
            "--note",
            "Needs regime filter",
        ],
    )
    assert res_add.exit_code == 0
    assert "Ledger Updated" in res_add.stdout

    res_render = runner.invoke(app, ["ledger", "render"])
    assert res_render.exit_code == 0
    assert "# Strategy Ledger" in res_render.stdout
    assert "S-020" in res_render.stdout

    res_query = runner.invoke(app, ["ledger", "query", "--spec", "S-020"])
    assert res_query.exit_code == 0
    assert "PARK" in res_query.stdout
