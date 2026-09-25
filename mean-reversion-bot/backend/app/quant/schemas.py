"""Validated inputs for local automated research, never execution requests."""
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.execution.mt5_demo import DemoConfig


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Bar(Record):
    timestamp: int = Field(ge=0)
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(default=0, ge=0)
    spread: float | None = Field(default=None, ge=0)


class Session(Record):
    timezone: str = 'UTC'
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    open_minute: int = Field(default=0, ge=0, lt=1440)
    close_minute: int = Field(default=1440, gt=0, le=1440)
    holidays: list[date] = Field(default_factory=list, max_length=366)
    early_closes: dict[date, int] = Field(default_factory=dict, max_length=366)
    confirmed: bool = False

    @model_validator(mode='after')
    def valid(self):
        ZoneInfo(self.timezone)
        if any(d not in range(7) for d in self.weekdays) or self.open_minute >= self.close_minute:
            raise ValueError('Use weekdays 0–6 and a same-day session; split overnight sessions at midnight')
        if any(not self.open_minute < v <= self.close_minute for v in self.early_closes.values()):
            raise ValueError('Invalid early close minute')
        return self


class Profile(Record):
    # Monetary costs are account-currency amounts per lot, never silently assumed known.
    contract_size: float = Field(default=1, gt=0, le=1e9)
    tick_size: float = Field(default=.00001, gt=0, le=1e6)
    volume_min: float = Field(default=.01, gt=0, le=1e6)
    volume_step: float = Field(default=.01, gt=0, le=1e6)
    volume_max: float = Field(default=100, gt=0, le=1e9)
    profit_currency: str = Field(default='USD', pattern=r'^[A-Z]{3}$')
    account_currency: str = Field(default='USD', pattern=r'^[A-Z]{3}$')
    commission_per_lot: float | None = Field(default=None, ge=0, le=1e6)
    financing_long: float | None = Field(default=None, ge=-1e6, le=1e6)
    financing_short: float | None = Field(default=None, ge=-1e6, le=1e6)
    rollover_timezone: str = 'UTC'
    rollover_minute: int = Field(default=0, ge=0, lt=1440)
    rollover_weights: list[float] = Field(default_factory=lambda: [1, 1, 3, 1, 1, 0, 0], min_length=7, max_length=7)
    spread_price: float | None = Field(default=None, ge=0, le=1e6)
    slippage_ticks: float = Field(default=1, ge=0, le=10000)
    annualization: int = Field(default=252, ge=1, le=366)
    price_basis: Literal['bid', 'mid'] = 'bid'
    costs_confirmed: bool = False
    specification_confirmed: bool = False
    cost_source: str = Field(default='', max_length=500)
    session: Session = Field(default_factory=Session)
    # Rate available at each timestamp: profit currency -> account currency.
    fx_rates: dict[int, float] = Field(default_factory=dict, max_length=11000)
    fx_max_age_seconds: int = Field(default=3600, ge=1, le=604800)
    minimum_stop: float = Field(default=0, ge=0)
    trade_mode: int = Field(default=4, ge=1, le=4)

    @model_validator(mode='after')
    def valid(self):
        ZoneInfo(self.rollover_timezone)
        if self.volume_max < self.volume_min or any(v < 0 for v in self.rollover_weights):
            raise ValueError('Invalid lot bounds or rollover weights')
        if any(v <= 0 for v in self.fx_rates.values()):
            raise ValueError('FX rates must be positive')
        if self.costs_confirmed and (not self.cost_source.strip() or any(v is None for v in
                (self.commission_per_lot, self.financing_long, self.financing_short))):
            raise ValueError('Confirmed costs require a source, commission and both financing rates; enter zero only if verified')
        return self


class Asset(Record):
    symbol: str = Field(min_length=1, max_length=128, pattern=r'^[^\x00-\x1f\x7f]+$')
    profile: Profile = Field(default_factory=Profile)
    bars: list[Bar] | None = Field(default=None, min_length=100, max_length=10000)


class AnalysisRequest(Record):
    source: Literal['mt5', 'deriv', 'import'] = 'mt5'
    assets: list[Asset] = Field(min_length=1, max_length=8)
    timeframe: Literal['M1', 'M5', 'M15', 'M30', 'H1', 'H4'] = 'M5'
    days: int = Field(default=30, ge=1, le=90)
    rolling_window: int = Field(default=60, ge=20, le=500)
    minimum_overlap: int = Field(default=100, ge=30, le=1000)
    initial_balance: float = Field(default=10000, gt=0, le=1e9)
    strategy: DemoConfig = Field(default_factory=DemoConfig)
    exposures: dict[str, float] = Field(default_factory=dict, max_length=8)

    @model_validator(mode='after')
    def valid(self):
        names = [a.symbol for a in self.assets]
        if len(names) != len(set(names)) or any(s != s.strip() for s in names):
            raise ValueError('Select unique exact symbols')
        if set(self.exposures) - set(names):
            raise ValueError('Exposure symbols must be selected assets')
        if self.source == 'import' and any(a.bars is None for a in self.assets):
            raise ValueError('Each imported asset requires its own candles')
        if self.source != 'import' and any(a.bars is not None for a in self.assets):
            raise ValueError('Use the import source for supplied candles')
        return self

    @property
    def interval(self):
        return int(self.timeframe[1:]) * (60 if self.timeframe[0] == 'M' else 3600)
