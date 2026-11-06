# StratLab Charter

Welcome to **StratLab**, an adversarial quant research desk operating inside Switch.

StratLab turns informal trading ideas into validated, production-grade Pine Script v6 strategies through rigorous quantitative testing and adversarial scrutiny.

---

## 1. The Research Protocol

1. **Ideation**: A trader proposes a concept in `#lab`.
2. **Specification**: `@strategist` converts the idea into a formal `StrategySpec` YAML.
3. **Pine Translation**: `@pine-coder` compiles the spec into pure Pine Script v6 code.
4. **Quantitative Simulation**: `@backtester` runs in-sample / out-of-sample backtests, parameter sweeps, and rolling walk-forward analysis.
5. **Adversarial Gatekeeping**: `@skeptic` attacks the results using Monte Carlo bootstrapping, 2x cost stress tests, and checks all 6 promotion gates.
6. **Human Decision**: If all gates pass, humans vote to **PROMOTE**, **KILL**, or **PARK**.
7. **Ledger Recording**: `@scribe` records the verdict in the persistent Strategy Ledger.

---

## 2. Hard Promotion Gates

To achieve production readiness, a strategy must clear all 6 quantitative gates without exception:

| Gate | Criterion | Threshold | Rationale |
| :--- | :--- | :--- | :--- |
| **G1** | Sample Size | $\ge 30$ trades OOS, $\ge 100$ trades total | Eliminates small-sample regime illusions. |
| **G2** | Walk-Forward Efficiency (WFE) | $\ge 0.50$ ($50\%$) | Asserts out-of-sample performance holds up to in-sample fit. |
| **G3** | Parameter Stability | Peak / Neighbor profit drop $\le 30\%$ | Rejects isolated "knife-edge" overfitted parameter spikes. |
| **G4** | Cost Stress Test | Profit Factor $\ge 1.05$ under 2x costs | Ensures profitability survives real-world slippage & fees. |
| **G5** | Monte Carlo 5th Percentile | Drawdown $\le 25\%$ across 1,000 resamples | Proves sequence risk won't blow up the account. |
| **G6** | TradingView Parity | $\ge 95\%$ matched entries, $\le 5\%$ net profit drift | Verifies simulation matches Pine Script v6 execution. |

---

## 3. Standard Cost Assumptions

Unless explicitly overridden in a `StrategySpec`, all simulations enforce:
- **Exchange**: Binance Spot / Perpetual
- **Commission**: $0.10\%$ ($0.0010$) per trade side (maker/taker blend)
- **Slippage**: $1$ minimum tick ($0.01$ USD on BTCUSDT)
- **Position Sizing**: $100\%$ equity per trade, 0 pyramiding (1 active position at a time)

---

## 4. Regulatory & Ethical Disclaimer

StratLab is strictly an educational and quantitative research environment.
**StratLab does not provide financial advice, investment recommendations, or execution guarantees.** Never risk capital you cannot afford to lose.
