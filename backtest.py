#!/usr/bin/env python3
"""Backtest des Accumulation-Scores für BTC und ETH (lokal ausführen: python backtest.py)."""
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scoring import accumulation_score, ZONES


def prices(ticker, start):
    s = yf.Ticker(ticker).history(start=start, interval="1d")["Close"].dropna()
    s.index = s.index.tz_localize(None).normalize()
    return s


def fng():
    j = requests.get("https://api.alternative.me/fng/?limit=0", timeout=30).json()["data"]
    return pd.Series({pd.Timestamp(int(d["timestamp"]), unit="s").normalize(): int(d["value"])
                      for d in j}).sort_index()


def buckets(name, p, sc):
    print(f"\n===== {name}  ({sc.dropna().index[0].date()} – {sc.dropna().index[-1].date()}) =====")
    fw = {h: p.shift(-h) / p - 1 for h in (365, 730)}
    edges = [z[0] for z in ZONES][::-1] + [101]
    print(f"{'Score':<9}{'Tage':>6} | " + " | ".join(f"{h//365}J: Ø / im Plus / schlechtester" for h in fw))
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (sc >= lo) & (sc < hi)
        line = f"{lo:>3}-{min(hi,100):<5}{m.sum():>6} | "
        parts = []
        for h in fw:
            r = fw[h][m].dropna()
            parts.append(f"{r.mean()*100:>5.0f}% / {r.gt(0).mean()*100:>3.0f}% / {r.min()*100:>5.0f}%  (n={len(r)})" if len(r) else "n/a")
        print(line + " | ".join(parts))
    allr = {h: fw[h][sc.notna()].dropna() for h in fw}
    print(f"{'Alle':<9}{sc.notna().sum():>6} | " + " | ".join(
        f"{allr[h].mean()*100:>5.0f}% / {allr[h].gt(0).mean()*100:>3.0f}% / {allr[h].min()*100:>5.0f}%  (n={len(allr[h])})" for h in fw))


def dca(name, p, sc, mult):
    """Monatlicher Kauf: Standard-DCA (1x) vs. Score-gewichtet. Vergleich Ø-Kaufpreis & Rendite."""
    buys = p[sc.notna()].resample("MS").first()
    s = sc.reindex(buys.index)
    res = {}
    for label, f in (("Plain DCA", lambda x: 1.0), ("Score-DCA", lambda x: mult(x))):
        amt = s.map(f)
        coins = (amt / buys).sum()
        spent = amt.sum()
        res[label] = (spent / coins, coins * p.iloc[-1] / spent - 1, spent)
    print(f"\n{name} monatlich seit {buys.index[0].date()}:")
    for k, (avg, ret, spent) in res.items():
        print(f"  {k:<10} Ø-Kaufpreis {avg:>9,.0f} $ | Rendite auf eingesetztes Kapital {ret*100:>6.0f}%")


def main():
    f = fng()
    for name, tick, start in (("BTC", "BTC-USD", "2014-09-17"), ("ETH", "ETH-USD", "2017-11-09")):
        p = prices(tick, start)
        sc = accumulation_score(p, f)["score"]
        buckets(name, p, sc)
        mult = lambda x: 2.5 if x >= 75 else 1.5 if x >= 55 else 1.0 if x >= 35 else 0.5
        dca(name, p, sc, mult)
        # nur seit 2021 (200W-SMA für ETH erst ab dann verfügbar)
        dca(name + " (ab 2022)", p["2022":], sc["2022":], mult)


if __name__ == "__main__":
    main()
