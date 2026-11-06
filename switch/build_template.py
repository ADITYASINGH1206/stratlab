#!/usr/bin/env python3
"""Build switch/stratlab.template.yaml by inlining markdown files."""

from pathlib import Path

import yaml


class LiteralStr(str):
    pass


def literal_str_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, literal_str_representer)


def read_text_strip(path: Path) -> LiteralStr:
    """Read a markdown file and return as LiteralStr for yaml block formatting."""
    return LiteralStr(path.read_text(encoding="utf-8").strip())


def build_template() -> dict:
    switch_dir = Path(__file__).resolve().parent
    agents_dir = switch_dir / "agents"
    rooms_dir = switch_dir / "rooms"

    strategist_md = read_text_strip(agents_dir / "strategist.md")
    pine_coder_md = read_text_strip(agents_dir / "pine-coder.md")
    backtester_md = read_text_strip(agents_dir / "backtester.md")
    skeptic_md = read_text_strip(agents_dir / "skeptic.md")
    scribe_md = read_text_strip(agents_dir / "scribe.md")

    lab_charter_md = read_text_strip(rooms_dir / "lab-charter.md")
    lab_instructions_md = read_text_strip(rooms_dir / "lab-instructions.md")
    ledger_instructions_md = read_text_strip(rooms_dir / "ledger-instructions.md")

    template = {
        "version": 1,
        "params": {
            "bridge": {
                "type": "bridge",
                "description": "Where the lab lives. Discord if connected, else the local Mattermost.",
                "default": ["Discord", "Mattermost", "$first"],
            },
            "provider": {
                "type": "provider",
                "default": ["claude", "codex", "opencode"],
                "input": "advanced",
            },
            "location": {
                "type": "location",
                "default": "local",
                "input": "advanced",
            },
        },
        "agents": [
            {
                "name": "stratlab-strategist",
                "display_name": "Strategist",
                "description": "Turns ideas into specs and runs the loop",
                "addressing": "anyone",
                "provider": "{provider}",
                "location": "{location}",
                "directory": "{$agents_dir}/stratlab-strategist",
                "repo": "https://github.com/ADITYASINGH1206/stratlab",
                "instructions": strategist_md,
            },
            {
                "name": "stratlab-pine-coder",
                "display_name": "Pine Coder",
                "description": "Writes Pine Script v6 strategies matching StrategySpec",
                "addressing": "anyone",
                "provider": "{provider}",
                "location": "{location}",
                "directory": "{$agents_dir}/stratlab-pine-coder",
                "repo": "https://github.com/ADITYASINGH1206/stratlab",
                "instructions": pine_coder_md,
            },
            {
                "name": "stratlab-backtester",
                "display_name": "Backtester",
                "description": "Runs simulations, parameter sweeps, walk-forward tests, and parity checks",
                "addressing": "anyone",
                "provider": "{provider}",
                "location": "{location}",
                "directory": "{$agents_dir}/stratlab-backtester",
                "repo": "https://github.com/ADITYASINGH1206/stratlab",
                "instructions": backtester_md,
            },
            {
                "name": "stratlab-skeptic",
                "display_name": "Skeptic",
                "description": "Adversarial gatekeeper; stress tests strategies and audits promotion gates",
                "addressing": "anyone",
                "provider": "{provider}",
                "location": "{location}",
                "directory": "{$agents_dir}/stratlab-skeptic",
                "repo": "https://github.com/ADITYASINGH1206/stratlab",
                "instructions": skeptic_md,
            },
            {
                "name": "stratlab-scribe",
                "display_name": "Scribe",
                "description": "Maintains Strategy Ledger, logs decisions, and posts strategy cards",
                "addressing": "anyone",
                "provider": "{provider}",
                "location": "{location}",
                "directory": "{$agents_dir}/stratlab-scribe",
                "repo": "https://github.com/ADITYASINGH1206/stratlab",
                "instructions": scribe_md,
            },
        ],
        "group": {
            "name": "StratLab",
            "description": "Strategy research desk — ideas in, verdicts out",
        },
        "rooms": [
            {
                "name": "stratlab-lab",
                "description": "Post an idea; agents spec, code, test and attack it",
                "bridge": "{bridge}",
                "instructions": lab_instructions_md,
                "agents": [
                    "stratlab-strategist",
                    "stratlab-pine-coder",
                    "stratlab-backtester",
                    "stratlab-skeptic",
                    "stratlab-scribe",
                ],
                "users": ["{$creator}"],
                "aliases": {
                    "stratlab-strategist": "strategist",
                    "stratlab-pine-coder": "pine-coder",
                    "stratlab-backtester": "backtester",
                    "stratlab-skeptic": "skeptic",
                    "stratlab-scribe": "scribe",
                },
                "roles": [
                    {
                        "name": "quant-on-call",
                        "instructions": "Answer 'can someone run numbers on X' requests.",
                        "exclusive": True,
                    }
                ],
                "docs": [
                    {
                        "name": "Lab Charter",
                        "description": "Protocol, promotion gates, cost defaults",
                        "instructions": "Read before every review. Gates here override defaults.",
                        "content": lab_charter_md,
                    }
                ],
                "kickoff": (
                    "@stratlab-strategist @stratlab-pine-coder @stratlab-backtester @stratlab-skeptic @stratlab-scribe this is StratLab. "
                    "Each of you: introduce yourself in one line. @stratlab-backtester take the quant-on-call role. "
                    "@stratlab-strategist then run example S-001 end to end."
                ),
            },
            {
                "name": "stratlab-ledger",
                "description": "One card per verdict; ask the Scribe about history",
                "bridge": "{bridge}",
                "instructions": ledger_instructions_md,
                "agents": ["stratlab-scribe", "stratlab-strategist"],
                "users": ["{$creator}"],
                "aliases": {
                    "stratlab-scribe": "scribe",
                    "stratlab-strategist": "strategist",
                },
                "docs": [
                    {
                        "name": "Strategy Ledger",
                        "description": "Rendered table of strategy decisions, metrics, and gate results",
                        "instructions": "Maintained automatically by @scribe using stratlab ledger render.",
                        "content": LiteralStr(
                            "# Strategy Ledger\n\n*Awaiting first recorded strategy decision.*"
                        ),
                    }
                ],
                "kickoff": "@stratlab-scribe introduce the ledger in two lines.",
            },
        ],
        "links": [
            {
                "from": "stratlab-lab",
                "to": "stratlab-ledger",
                "label": "verdicts",
            }
        ],
    }
    return template


def main():
    switch_dir = Path(__file__).resolve().parent
    template = build_template()
    out_path = switch_dir / "stratlab.template.yaml"

    yaml_text = yaml.dump(template, sort_keys=False, width=120, allow_unicode=True)
    out_path.write_text(yaml_text, encoding="utf-8")
    print(f"Generated Switch template -> {out_path} ({len(yaml_text)} bytes)")


if __name__ == "__main__":
    main()
