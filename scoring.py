"""Accumulation-Score (0-100) für BTC/ETH: wie günstig ist der Einstieg historisch gesehen?

Bewertung (70 %): Preis/200-Wochen-SMA, Preis/200-Tage-SMA (Mayer), Abstand zum ATH.
  Jede Kennzahl wird als *rollierendes Perzentil* (4 Jahre ≈ ein Halving-Zyklus) gegen die eigene
  Historie gerankt (kein Look-ahead, keine festen Preisgrenzen) -> niedrig = günstig.
Stimmung (30 %): 100 - Fear&Greed.
"""
import pandas as pd

W_VALUATION = 0.70
W_SENTIMENT = 0.30
MIN_HISTORY = 365            # Tage Historie, bevor ein Perzentil gilt
PCT_WINDOW = 1460            # Perzentil-Fenster in Tagen (4 Jahre)
SMA_WEEKS200 = 1400          # 200 Wochen in Tagen
SMA_DAYS200 = 200

# Zonen (Untergrenzen des Scores) – aus dem Backtest abgeleitet, siehe backtest.py
ZONES = [(75, "🟢 Starker Kaufbereich"), (55, "🟡 Kaufbereich"),
         (35, "⚪ Neutral"), (0, "🔴 Teuer – zurückhalten")]


def zone_name(score):
    return next(name for lo, name in ZONES if score >= lo)


def _expanding_pct(s):
    """Anteil der Werte im Fenster (inkl. heute), die <= heutigem Wert sind."""
    return s.rolling(PCT_WINDOW, min_periods=MIN_HISTORY).apply(lambda x: (x <= x[-1]).mean(), raw=True)


def metrics(price: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({
        "x200w": price / price.rolling(SMA_WEEKS200, min_periods=SMA_WEEKS200 // 2).mean(),
        "mayer": price / price.rolling(SMA_DAYS200).mean(),
        "drawdown": price / price.cummax() - 1,
    })


def accumulation_score(price: pd.Series, fng: pd.Series | None = None) -> pd.DataFrame:
    m = metrics(price)
    cheap = pd.DataFrame({c: 1 - _expanding_pct(m[c].dropna()).reindex(m.index) for c in m})
    valuation = cheap.mean(axis=1, skipna=True) * 100
    out = m.copy()
    out["valuation"] = valuation
    if fng is not None:
        sent = (100 - fng.reindex(price.index))
        out["sentiment"] = sent
        score = (W_VALUATION * valuation + W_SENTIMENT * sent).where(sent.notna(), valuation)
    else:
        score = valuation
    out["score"] = score
    return out
