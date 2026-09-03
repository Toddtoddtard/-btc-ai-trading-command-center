# ---------- live BTC market data ----------
import requests

def get_btc_data():
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": "BTCUSDT",
        "interval": "1m",
        "limit": 240
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    rows = []

    for candle in data:
        rows.append({
            "time": pd.to_datetime(candle[0], unit="ms", utc=True),
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5])
        })

    return pd.DataFrame(rows)


try:
    df = get_btc_data()
    data_status = "🟢 LIVE BTC DATA — BINANCE"
    data_error = None

except Exception as e:
    # Safe fallback so the dashboard doesn't crash
    rng = np.random.default_rng(7)
    now = pd.Timestamp.now(tz="UTC")
    times = pd.date_range(end=now, periods=240, freq="1min")

    price = 77500 + np.cumsum(
        rng.normal(0, 38, len(times))
    )

    price[-1] = price[-2] + 22

    open_ = np.r_[price[0], price[:-1]]
    high = np.maximum(open_, price) + rng.uniform(3, 28, len(price))
    low = np.minimum(open_, price) - rng.uniform(3, 28, len(price))
    volume = rng.lognormal(9.1, 0.45, len(price))

    df = pd.DataFrame({
        "time": times,
        "open": open_,
        "high": high,
        "low": low,
        "close": price,
        "volume": volume
    })

    data_status = "🟡 DEMO DATA — BINANCE CONNECTION FAILED"
    data_error = str(e)