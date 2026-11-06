"""Pydantic v2 models defining the single source of truth: StrategySpec."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MarketConfig(BaseModel):
    symbol: str = Field(description="Trading pair symbol, e.g. BTCUSDT")
    exchange: str = Field(default="binance", description="Exchange identifier")
    tv_symbol: str = Field(description="TradingView symbol notation, e.g. BINANCE:BTCUSDT")
    timeframe: str = Field(default="4h", description="Candle timeframe, e.g. 1h, 4h, 1d")


class PeriodConfig(BaseModel):
    start: date | str = Field(description="Backtest start date, YYYY-MM-DD")
    end: date | str = Field(description="Backtest end date, YYYY-MM-DD")
    oos_fraction: float = Field(
        default=0.3, ge=0.0, le=0.9, description="Fraction reserved for out-of-sample test"
    )

    @model_validator(mode="after")
    def format_dates(self) -> "PeriodConfig":
        if isinstance(self.start, date):
            self.start = self.start.strftime("%Y-%m-%d")
        if isinstance(self.end, date):
            self.end = self.end.strftime("%Y-%m-%d")
        return self


class ParamConfig(BaseModel):
    default: float | int
    range: list[float | int] | None = Field(
        default=None,
        description="Optimization range [min, max, step]",
    )
    fixed: bool = Field(default=False, description="Whether parameter is frozen during sweeps")

    @model_validator(mode="after")
    def validate_range(self) -> "ParamConfig":
        if self.range is not None:
            if len(self.range) != 3:
                raise ValueError("param range must have exactly 3 values: [min, max, step]")
            min_val, max_val, step = self.range
            if min_val >= max_val:
                raise ValueError(f"param range min ({min_val}) must be strictly less than max ({max_val})")
            if step <= 0:
                raise ValueError(f"param range step ({step}) must be positive")
        return self


class IndicatorConfig(BaseModel):
    fn: str = Field(
        description="Indicator function: sma, ema, wma, rsi, atr, macd, bb, donchian, stoch, adx, vwap, highest, lowest, expr"
    )
    src: str | None = Field(default="close", description="Input price series (open/high/low/close/volume or indicator)")
    len: int | str | None = Field(default=None, description="Length / period or $param reference")
    expr: str | None = Field(default=None, description="Arithmetic expression on series for fn=expr")
    fast: int | str | None = Field(default=None, description="Fast period for MACD or $param reference")
    slow: int | str | None = Field(default=None, description="Slow period for MACD or $param reference")
    signal: int | str | None = Field(default=None, description="Signal period for MACD or $param reference")
    mult: float | str | None = Field(default=None, description="Multiplier for BB or $param reference")


class StopConfig(BaseModel):
    atr_mult: float | str | None = None
    pct: float | str | None = None
    price: float | str | None = None


class TargetConfig(BaseModel):
    atr_mult: float | str | None = None
    pct: float | str | None = None
    price: float | str | None = None


class TimeExitConfig(BaseModel):
    bars: int | str = Field(description="Max bars in trade before forced close")


class ExitConfig(BaseModel):
    stop: StopConfig | None = None
    target: TargetConfig | None = None
    time: TimeExitConfig | None = None
    opposite_signal: bool = False


class EntryConfig(BaseModel):
    long: dict[str, Any] | None = None
    short: dict[str, Any] | None = None


class RiskConfig(BaseModel):
    sizing: Literal["percent_equity", "fixed_qty", "fixed_cash"] = "percent_equity"
    value: float = Field(default=100.0, description="100% equity or fixed quantity/cash")
    initial_capital: float = Field(default=10000.0, description="Starting portfolio capital")
    pyramiding: int = Field(default=0, description="Max open positions in same direction (0 = single position)")


class CostsConfig(BaseModel):
    commission_pct: float = Field(default=0.1, description="Commission percentage per side, e.g. 0.1 for 0.1%")
    slippage_ticks: int = Field(default=1, description="Slippage in price ticks")
    tick_size: float = Field(default=0.01, description="Minimum price movement increment")


class StrategySpec(BaseModel):
    id: str = Field(description="Unique strategy identifier, e.g. S-012")
    version: int = Field(default=1, ge=1, description="Sequential version number")
    name: str = Field(description="Human readable name of the strategy")
    market: MarketConfig
    period: PeriodConfig
    direction: Literal["long", "short", "both"] = "long"
    params: dict[str, ParamConfig] = Field(default_factory=dict)
    indicators: dict[str, IndicatorConfig] = Field(default_factory=dict)
    entry: EntryConfig
    exit: ExitConfig = Field(default_factory=ExitConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    costs: CostsConfig = Field(default_factory=CostsConfig)

    @model_validator(mode="after")
    def validate_direction_entries(self) -> "StrategySpec":
        if self.direction in ("long", "both") and not self.entry.long:
            raise ValueError(f"direction '{self.direction}' requires entry.long condition")
        if self.direction in ("short", "both") and not self.entry.short:
            raise ValueError(f"direction '{self.direction}' requires entry.short condition")
        return self
