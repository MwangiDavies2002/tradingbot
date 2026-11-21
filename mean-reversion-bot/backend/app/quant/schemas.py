"""Validated inputs for local automated research, never execution requests."""
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.execution.mt5_demo import DemoConfig
from app.quant.instruments import timeframe_seconds
from app.quant.strategy_identity import EXECUTION_STRATEGY_NAME, EXECUTION_STRATEGY_VERSION

Timeframe = Literal['M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M10', 'M12', 'M15',
                    'M20', 'M30', 'H1', 'H2', 'H3', 'H4', 'H6', 'H8', 'H12',
                    'D1', 'W1']
AssetClass = Literal['forex', 'index', 'metal', 'commodity', 'synthetic',
                     'future', 'equity', 'other', 'unknown']


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


class SessionHours(Record):
    open_minute: int = Field(ge=0, lt=1440)
    close_minute: int = Field(gt=0, le=1440)

    @model_validator(mode='after')
    def valid(self):
        if self.open_minute >= self.close_minute:
            raise ValueError('Special session open must be before its close; split overnight sessions at midnight')
        return self


class Session(Record):
    timezone: str = 'UTC'
    source: str = Field(default='', max_length=500)
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    open_minute: int = Field(default=0, ge=0, lt=1440)
    close_minute: int = Field(default=1440, gt=0, le=1440)
    weekly_hours: dict[int, list[SessionHours]] = Field(default_factory=dict, max_length=7)
    holidays: list[date] = Field(default_factory=list, max_length=366)
    early_closes: dict[date, int] = Field(default_factory=dict, max_length=366)
    special_hours: dict[date, SessionHours] = Field(default_factory=dict, max_length=366)
    confirmed: bool = False

    @model_validator(mode='after')
    def valid(self):
        ZoneInfo(self.timezone)
        if any(d not in range(7) for d in self.weekdays) or (not self.weekly_hours and self.open_minute >= self.close_minute):
            raise ValueError('Use weekdays 0–6 and a same-day session; split overnight sessions at midnight')
        if self.confirmed and not self.weekly_hours and not self.weekdays:
            raise ValueError('Confirmed session calendars require explicit weekly trading days or hours')
        for weekday, windows in self.weekly_hours.items():
            if weekday not in range(7) or not windows:
                raise ValueError('Weekly hours require weekdays 0–6 and at least one open window')
            ordered = sorted(windows, key=lambda window: window.open_minute)
            if windows != ordered or any(
                    previous.close_minute > current.open_minute
                    for previous, current in zip(ordered, ordered[1:])):
                raise ValueError('Weekly session windows must be ordered and non-overlapping')
        for weekday, close in self.early_closes.items():
            if self.weekly_hours:
                windows = self.weekly_hours.get(weekday.weekday(), [])
                valid_close = any(window.open_minute < close <= window.close_minute for window in windows)
            else:
                valid_close = self.open_minute < close <= self.close_minute
            if not valid_close:
                raise ValueError('Invalid early close minute')
        if set(self.holidays) & set(self.special_hours):
            raise ValueError('A date cannot be both a holiday and a special open session')
        if set(self.holidays) & set(self.early_closes):
            raise ValueError('A date cannot be both a holiday and an early close')
        if set(self.early_closes) & set(self.special_hours):
            raise ValueError('Use either an early close or special hours for a date, not both')
        if self.confirmed and not self.source.strip():
            raise ValueError('Confirmed session calendars require a source or broker schedule reference')
        return self


class Profile(Record):
    # Monetary costs are account-currency amounts per lot, never silently assumed known.
    contract_size: float | None = Field(default=None, gt=0, le=1e9)
    tick_size: float | None = Field(default=None, gt=0, le=1e6)
    volume_min: float | None = Field(default=None, gt=0, le=1e6)
    volume_step: float | None = Field(default=None, gt=0, le=1e6)
    volume_max: float | None = Field(default=None, gt=0, le=1e9)
    point: float | None = Field(default=None, gt=0, le=1e6)
    digits: int | None = Field(default=None, ge=0, le=12)
    tick_value: float | None = Field(default=None, gt=0, le=1e9)
    calculation_mode: int | None = Field(default=None, ge=0)
    order_mode: int | None = Field(default=None, ge=0)
    profit_currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    account_currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    commission_per_lot: float | None = Field(default=None, ge=0, le=1e6)
    financing_long: float | None = Field(default=None, ge=-1e6, le=1e6)
    financing_short: float | None = Field(default=None, ge=-1e6, le=1e6)
    rollover_timezone: str = 'UTC'
    rollover_minute: int = Field(default=0, ge=0, lt=1440)
    rollover_weights: list[float] = Field(default_factory=lambda: [1, 1, 1, 1, 1, 1, 1], min_length=7, max_length=7)
    rollover_confirmed: bool = False
    rollover_source: str = Field(default='', max_length=500)
    spread_price: float | None = Field(default=None, ge=0, le=1e6)
    slippage_ticks: float = Field(default=1, ge=0, le=10000)
    market_impact_ticks_per_lot: float = Field(default=0, ge=0, le=10000)
    annualization: int = Field(default=252, ge=1, le=366)
    price_basis: Literal['bid', 'mid'] = 'bid'
    costs_confirmed: bool = False
    specification_confirmed: bool = False
    cost_source: str = Field(default='', max_length=500)
    slippage_confirmed: bool = False
    slippage_source: str = Field(default='', max_length=500)
    asset_class: AssetClass = 'unknown'
    broker_group: str = Field(default='', max_length=256)
    specification_fingerprint: str = Field(default='', pattern=r'^(|[a-f0-9]{64})$')
    session: Session = Field(default_factory=Session)
    # Rate available at each timestamp: profit currency -> account currency.
    fx_rates: dict[int, float] = Field(default_factory=dict, max_length=11000)
    fx_max_age_seconds: int = Field(default=3600, ge=1, le=604800)
    minimum_stop: float | None = Field(default=None, ge=0)
    trade_mode: int | None = Field(default=None, ge=1, le=4)
    specification_source: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def valid(self):
        ZoneInfo(self.rollover_timezone)
        if (self.volume_max is not None and self.volume_min is not None
                and self.volume_max < self.volume_min) or any(v < 0 for v in self.rollover_weights):
            raise ValueError('Invalid lot bounds or rollover weights')
        if any(v <= 0 for v in self.fx_rates.values()):
            raise ValueError('FX rates must be positive')
        if self.costs_confirmed and (not self.cost_source.strip() or any(v is None for v in
                (self.commission_per_lot, self.financing_long, self.financing_short))):
            raise ValueError('Confirmed costs require a source, commission and both financing rates; enter zero only if verified')
        if self.costs_confirmed and (not self.rollover_confirmed or not self.rollover_source.strip()):
            raise ValueError('Confirmed costs require a verified rollover schedule and its source')
        if self.specification_confirmed:
            required = (self.contract_size, self.tick_size, self.tick_value, self.point, self.digits,
                        self.volume_min, self.volume_step, self.volume_max, self.profit_currency,
                        self.account_currency, self.calculation_mode, self.order_mode, self.trade_mode)
            if any(value is None for value in required) or not self.specification_source.strip():
                raise ValueError('Confirmed specifications require complete broker fields and a specification source')
        if self.slippage_confirmed and not self.slippage_source.strip():
            raise ValueError('Confirmed slippage requires a measurement or scenario source')
        return self


class InstrumentIdentity(Record):
    symbol: str = Field(min_length=1, max_length=128, pattern=r'^[^\x00-\x1f\x7f]+$')
    broker_server: str = Field(min_length=1, max_length=128)
    asset_class: AssetClass = 'unknown'
    broker_group: str = Field(default='', max_length=256)


class StrategyDefinition(Record):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    parameters: dict[str, bool | int | float] = Field(max_length=64)


class RiskConfiguration(Record):
    risk_pct: float = Field(gt=0, le=0.01)
    daily_loss_pct: float = Field(gt=0, le=0.05)


class ResearchConfiguration(Record):
    instrument: InstrumentIdentity
    timeframe: Timeframe
    strategy: StrategyDefinition
    risk: RiskConfiguration
    specification_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    profile_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    cost_model_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    session_calendar: Session


class Asset(Record):
    symbol: str = Field(min_length=1, max_length=128, pattern=r'^[^\x00-\x1f\x7f]+$')
    timeframe: Timeframe | None = None
    # Broker class/group are descriptive catalog metadata; unknown remains selectable.
    asset_class: AssetClass = 'unknown'
    broker_group: str = Field(default='', max_length=256)
    profile: Profile = Field(default_factory=Profile)
    bars: list[Bar] | None = Field(default=None, min_length=100, max_length=10000)


class ResearchScope(Record):
    # Empty means all supplied broker-session bars. Presets use local exchange/market clocks.
    sessions: list[Literal['asia', 'london', 'new_york']] = Field(default_factory=list, max_length=3)
    setup: Literal['strategy_signals', 'opening_range_breakout'] = 'strategy_signals'
    opening_range_session: Literal['asia', 'london', 'new_york'] = 'new_york'
    opening_range_minutes: Literal[15, 30, 60] = 15
    opening_range_volume_filter: bool = False
    opening_range_volume_multiple: float = Field(default=1.5, ge=1, le=10)
    opening_range_indicator_confirmation: bool = False


class AnalysisRequest(Record):
    source: Literal['mt5', 'deriv', 'import'] = 'mt5'
    assets: list[Asset] = Field(min_length=1, max_length=8)
    timeframe: Timeframe = 'M5'
    days: int = Field(default=30, ge=1, le=3650)
    rolling_window: int = Field(default=60, ge=20, le=500)
    minimum_overlap: int = Field(default=100, ge=30, le=1000)
    initial_balance: float = Field(default=10000, gt=0, le=1e9)
    strategy: DemoConfig = Field(default_factory=DemoConfig)
    strategy_name: str = Field(default=EXECUTION_STRATEGY_NAME, min_length=1, max_length=128)
    strategy_version: str = Field(default=EXECUTION_STRATEGY_VERSION, min_length=1, max_length=64)
    research_scope: ResearchScope = Field(default_factory=ResearchScope)
    exposures: dict[str, float] = Field(default_factory=dict, max_length=8)

    @model_validator(mode='after')
    def valid(self):
        names = [a.symbol for a in self.assets]
        if len(names) != len(set(names)) or any(s != s.strip() for s in names):
            raise ValueError('Select unique exact symbols')
        # Strategy identity is request-wide metadata; each asset's candidate is
        # assigned its own symbol and this timeframe during validation.
        first_timeframe = self.assets[0].timeframe or self.timeframe
        if self.strategy.symbol != names[0] or self.strategy.timeframe != first_timeframe:
            self.strategy = self.strategy.model_copy(update={
                'symbol': names[0],
                'timeframe': first_timeframe,
            })
        if set(self.exposures) - set(names):
            raise ValueError('Exposure symbols must be selected assets')
        if self.source == 'import' and any(a.bars is None for a in self.assets):
            raise ValueError('Each imported asset requires its own candles')
        if self.source != 'import' and any(a.bars is not None for a in self.assets):
            raise ValueError('Use the import source for supplied candles')
        if len(self.research_scope.sessions) != len(set(self.research_scope.sessions)):
            raise ValueError('Research sessions must be unique')
        if self.research_scope.setup == 'opening_range_breakout' and self.research_scope.sessions:
            raise ValueError('Opening-range research uses its selected opening session; clear the separate entry-session filters')
        for asset in self.assets:
            interval = timeframe_seconds(asset.timeframe or self.timeframe)
            if self.source != 'import' and self.days * 86400 > 10000 * interval:
                max_days = 10000 * interval // 86400
                raise ValueError(f'{asset.symbol}: {asset.timeframe or self.timeframe} supports at most {max_days} lookback days at the 10,000-candle limit')
            if self.research_scope.setup == 'opening_range_breakout':
                range_seconds = self.research_scope.opening_range_minutes * 60
                if interval > range_seconds:
                    raise ValueError(f'{asset.symbol}: opening range must be at least one candle long; choose a shorter timeframe')
                if range_seconds % interval:
                    raise ValueError(f'{asset.symbol}: timeframe must divide the opening range evenly')
        return self

    @property
    def interval(self):
        return timeframe_seconds(self.timeframe)
