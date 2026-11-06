# StratLab (Strategy Lab Room)

> **"Describe a strategy in plain English in Discord. A team of agents codes it in Pine, backtests and optimizes it, then tries to break it. You and your friends decide if it lives."**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Flip the Switch](https://img.shields.io/badge/Hackathon-Flip%20the%20Switch%20Track%202-purple.svg)](https://wemakedevs.org)

**StratLab** turns a chat room (Discord or Switch-bundled local Mattermost) into an adversarial quantitative trading research desk. Five AI agents (`strategist`, `pine-coder`, `backtester`, `skeptic`, and `scribe`) collaborate with human traders inside a single shared Switch room.

*Disclaimer: StratLab is a research and backtesting tool. Not financial advice. It never places live orders.*

---

## Architecture Overview

```
                      +-----------------------------+
                      |   Discord / Mattermost      |
                      |   #lab   #ledger   #journal |
                      +--------------+--------------+
                                     |
                           Switch Agent Bridge
                                     |
               +---------------------+---------------------+
               |                     |                     |
        @strategist             @pine-coder           @backtester
     (Idea -> Spec YAML)    (Pine Script v6)       (IS / Sweep / WF)
               |                     |                     |
               +---------------------+---------------------+
                                     |
                                  @skeptic
                           (Adversarial Gates)
                                     |
                               [Human Vote]
                            promote / kill / park
                                     |
                                  @scribe
                          (Strategy Ledger Doc)
```

---

## Roadmap & Implementation Phases

- [ ] **Phase 1: Scaffold, Data & Spec** - Typer CLI skeleton, StrategySpec Pydantic schema, CCXT market data caching, sample data, and example specs.
- [ ] **Phase 2: Engine Core & Numba Sim** - TV-parity indicators (Wilder RMA, EMA seeded with SMA), condition evaluator, intrabar broker emulator fill model, metrics calculator.
- [ ] **Phase 3: Research Tools, Robustness & Gates** - Parameter sweep (grid/random), rolling walk-forward analysis, Monte Carlo bootstrap, cost stress, 6 promotion gates, matplotlib charts.
- [ ] **Phase 4: Pine Script v6 & TV Parity** - Jinja2 Pine v6 templates, TradingView "List of Trades" CSV parser, trade-by-trade parity matcher report.
- [ ] **Phase 5: Switch Integration & Room Template** - Switch template YAML (`switch/stratlab.template.yaml`), agent instructions, Lab Charter and Strategy Ledger room documents.
- [ ] **Phase 6: Hardening, Replay & Edge Cases** - Loop guards, failure recovery, offline replay (`make demo`), clean clone setup.
- [ ] **Phase 7: Shipping & Demo Video** - Video recording, documentation, blog post, submission.
