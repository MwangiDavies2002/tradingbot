from app.api.routes.backtest import parse_csv_rows, timeframe_to_seconds


def test_timeframe_to_seconds_maps_common_timeframes():
    assert timeframe_to_seconds("M5") == 300
    assert timeframe_to_seconds("M15") == 900
    assert timeframe_to_seconds("H1") == 3600


def test_parse_csv_rows_handles_ohlcv_data():
    csv_text = """timestamp,open,high,low,close,volume
1710000000,1.000,1.100,0.900,1.050,1200
1710000300,1.050,1.200,1.000,1.150,1400
"""

    rows = parse_csv_rows(csv_text)

    assert len(rows) == 2
    assert rows[0]["close"] == 1.05
    assert rows[1]["volume"] == 1400
