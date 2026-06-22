import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd, numpy as np
from lib.gumloop_trading import compute_rsi, compute_macd, compute_bollinger, compute_adx, compute_obv, validate_ohlcv

def test_validate_ohlcv():
    df = pd.DataFrame({"open":[1],"high":[2],"low":[1],"close":[1.5],"volume":[100]})
    assert validate_ohlcv(df)
    assert not validate_ohlcv(pd.DataFrame({"a":[1]}))

def test_rsi():
    s = pd.Series([10,11,12,13,14,15,16,17,18,19,20,19,18,17,16])
    rsi = compute_rsi(s, 5)
    assert not rsi.isna().all()

def test_macd():
    s = pd.Series(range(1, 101))
    macd, sig, h = compute_macd(s)
    assert len(macd) == 100

def test_bollinger():
    s = pd.Series([float(x) for x in range(1, 50)])
    ma, u, l = compute_bollinger(s, 10)
    assert all(u >= ma)

def test_obv():
    df = pd.DataFrame({"close":[10,11,9,12],"volume":[100,200,150,300]})
    obv = compute_obv(df)
    assert abs(obv.iloc[-1] + 150) < 1

def test_telegram():
    from lib.gumloop_telegram import escape_md, build_alert
    assert "\\_" in escape_md("hello_world")
