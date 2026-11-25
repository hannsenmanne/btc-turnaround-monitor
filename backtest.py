#!/usr/bin/env python3
"""Backtest der 4 historisch verfügbaren Signale (ETF-Flows: Free-API nur 30 Tage -> nicht testbar).
Nutzung: python backtest.py   (lokal; Binance-Funding-Historie, in den USA evtl. geblockt)"""
import time
import pandas as pd
import requests
import yfinance as yf
from monitor import (SMA_DAYS, SMA_LONG_DAYS, FNG_EXTREME_FEAR, FNG_LOOKBACK_DAYS,
                     FUNDING_FLUSH_MAX, DXY_SMA_DAYS)

HORIZONS = (14, 30, 60)   # Tage nach dem Signal


def btc():
    df = yf.Ticker("BTC-USD").history(start="2018-03-01", interval="1d")
    s = df["Close"].dropna(); s.index = s.index.tz_localize(None).normalize()
    return s


def dxy():
    df = yf.Ticker("DX-Y.NYB").history(start="2018-01-01", interval="1d")
    s = df["Close"].dropna(); s.index = s.index.tz_localize(None).normalize()
    return s


def fng():
    j = requests.get("https://api.alternative.me/fng/?limit=0", timeout=30).json()["data"]
    s = pd.Series({pd.Timestamp(int(d["timestamp"]), unit="s").normalize(): int(d["value"]) for d in j})
    return s.sort_index()


def funding():
    rows, start = [], int(pd.Timestamp("2019-09-10").timestamp() * 1000)
    while True:
        r = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
                         params={"symbol": "BTCUSDT", "limit": 1000, "startTime": start}, timeout=30)
        r.raise_for_status(); j = r.json()
        if not j: break
        rows += j; start = j[-1]["fundingTime"] + 1
        if len(j) < 1000: break
        time.sleep(0.2)
    s = pd.Series({pd.Timestamp(x["fundingTime"], unit="ms"): float(x["fundingRate"]) * 100 for x in rows})
    return s.sort_index().resample("D").mean()


def main():
    p = btc()
    idx = p.index
    sma, sma_l = p.rolling(SMA_DAYS).mean(), p.rolling(SMA_LONG_DAYS).mean()
    tech = (p > sma) & (p > sma_l)

    f = fng().reindex(idx)
    sent = (f.rolling(FNG_LOOKBACK_DAYS).min() < FNG_EXTREME_FEAR) & (f > FNG_EXTREME_FEAR)

    d = dxy().reindex(idx).ffill()
    macro = d < d.rolling(DXY_SMA_DAYS).mean()

    fr = funding().reindex(idx)
    deriv = fr.rolling(1).mean() <= FUNDING_FLUSH_MAX

    sig = pd.DataFrame({"Technik": tech, "Stimmung": sent, "Derivate": deriv, "Makro": macro})
    valid = f.notna() & d.notna() & fr.notna() & sma_l.notna()
    sig, p = sig[valid], p[valid]
    score = sig.sum(axis=1)
    print(f"Zeitraum {sig.index[0].date()} – {sig.index[-1].date()} ({len(sig)} Tage), max. Score 4 (ohne ETF)\n")
    print("Trefferquote je Signal (% der Tage aktiv):")
    print((sig.mean() * 100).round(1).to_string(), "\n")

    fwd = {h: p.shift(-h) / p - 1 for h in HORIZONS}
    base = {h: fwd[h].dropna() for h in HORIZONS}
    print("Ø Rendite nach Score  (n = Tage | Ø Rendite | Anteil im Plus):")
    hdr = "Score  n    " + "".join(f"{h:>3}d Ø / +%    " for h in HORIZONS)
    print(hdr)
    for sc in range(0, 5):
        m = score == sc
        line = f"{sc:>3} {m.sum():>5}  "
        for h in HORIZONS:
            r = fwd[h][m].dropna()
            line += f"{(r.mean()*100 if len(r) else float('nan')):>6.1f}% /{(r.gt(0).mean()*100 if len(r) else float('nan')):>4.0f}%   "
        print(line)
    print("Alle Tage      " + "".join(f"{base[h].mean()*100:>6.1f}% /{base[h].gt(0).mean()*100:>4.0f}%   " for h in HORIZONS))

    print("\nAlarm-Ereignisse (Score steigt auf >= Schwelle, wie im Monitor), je Schwelle:")
    for th in (2, 3, 4):
        ev = (score >= th) & (score.shift(1).fillna(0) < th)
        # Cluster: Events mit <14 Tagen Abstand zusammenfassen
        dates, last = [], None
        for t in score.index[ev]:
            if last is None or (t - last).days >= 14: dates.append(t)
            last = t
        line = f"Schwelle {th}: {len(dates)} unabhängige Alarme in {len(sig)/365:.1f} Jahren"
        for h in HORIZONS:
            r = fwd[h].reindex(dates).dropna()
            if len(r): line += f" | {h}d Ø {r.mean()*100:+.1f}% ({r.gt(0).mean()*100:.0f}% im Plus, n={len(r)})"
        print(line)


if __name__ == "__main__":
    main()
