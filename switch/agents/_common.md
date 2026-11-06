## Tools and shared workspace (all StratLab agents)
- StratLab is a command-line tool. Call it by its full path, `~/stratlab-home/bin/stratlab` (created by `make setup`). Below it is written `stratlab` for short.
- Every agent shares `~/stratlab-home`: specs, runs, charts, the ledger and `charter.yaml` live there. Refer to specs by reference, like `S-012@v2`, never by a path inside your own folder.
- Numbers come from commands, never from your head. Copy them exactly from the command output and keep each run id with its numbers.
- If a command exits non-zero, post its one-line `Error:` message unchanged, say what you will try next or that you are waiting on a human, and stop.
- Room protocol: one thread per strategy. End every message with exactly one hand-off line, either naming the next agent(s) or `Waiting on a human.` Mention other agents only in that line.
- Discord does not render Markdown tables. Put numbers in a short ```text block, keep messages under 1,500 characters, and attach files instead of pasting them.
- StratLab is a research tool, not financial advice. It never places orders. Never suggest live position sizes.
