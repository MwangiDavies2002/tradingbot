from fastapi import APIRouter

router = APIRouter()
TV_TRANSLATIONS = {"use_zscore", "use_rsi", "use_bb", "use_vwap", "use_stoch", "use_volume"}
STRATEGIES = [
    ("use_zscore", "Z-Score"), ("use_rsi", "RSI"), ("use_bb", "Bollinger Bands"),
    ("use_vwap", "VWAP"), ("use_stoch", "Stochastic"), ("use_lsl", "LSL Grab"),
    ("use_smc", "SMC Structure"), ("use_volume", "Volume Spike"), ("use_hurst", "Hurst Regime"),
    ("use_linear_regression", "Linear Regression"), ("use_tree_model", "Tree Model"),
    ("use_time_series_nn", "Time-Series Neural Net"), ("use_smt", "SMT Divergence"),
    ("use_day_levels", "Day High / Low"), ("use_candle_reversal", "Candle Reversal"),
    ("use_candle_continuation", "Candle Continuation"), ("use_crt", "CRT"),
]

@router.get("")
def list_strategies():
    return [{"id": key, "label": label, "versions": ["pine"] if key in TV_TRANSLATIONS else ["python_mt5"],
             "default_version": "pine" if key in TV_TRANSLATIONS else "python_mt5"} for key, label in STRATEGIES]
