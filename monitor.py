#!/usr/bin/env python3
"""Accumulation-Monitor für BTC & ETH: Wie gut ist der Einstieg heute? (Langfrist-Käufer)

Score 0-100 aus Bewertung (200W-SMA, Mayer, ATH-Abstand) + Stimmung, siehe scoring.py.
Telegram bei Zonenwechsel, jeden Montag als Wochenbericht, oder mit ALWAYS_NOTIFY=true.
`--dry-run` gibt die Nachricht nur aus.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf

from scoring import accumulation_score, zone_name

# ====================== KONFIGURATION ======================
COINS = {   # Name: (yfinance-Ticker, ETF-API-Asset, Futures-Symbol, OKX-Instrument)
    "BTC": ("BTC-USD", "btc", "BTCUSDT", "BTC-USDT-SWAP"),
    "ETH": ("ETH-USD", "eth", "ETHUSDT", "ETH-USDT-SWAP"),
}
HISTORY_START = {"BTC": "2014-09-17", "ETH": "2017-11-09"}
# Kaufmultiplikator auf deinen normalen Sparbetrag je Zone (Untergrenze des Scores)
BUY_MULTIPLIER = [(75, 2.5), (55, 1.5), (35, 1.0), (0, 0.5)]
ETF_CONSECUTIVE_INFLOW_DAYS = 2
FUNDING_FLUSH_MAX = 0.005       # Info: Ø-Funding in % pro 8h; darüber = Longs überhitzt
HEARTBEAT_WEEKDAY = 0           # Wochenbericht: 0 = Montag (Morgenlauf, UTC)
HTTP_TIMEOUT = 15
ETF_API_URL = "https://api.cryptoetf.today/v1"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
# ===========================================================


def multiplier(score):
    return next(m for lo, m in BUY_MULTIPLIER if score >= lo)


def completed_closes(df):
    """Schlusskurse ohne die heutige, noch laufende Tageskerze."""
    close = df["Close"].dropna()
    close.index = close.index.tz_localize(None).normalize()
    if len(close) and close.index[-1].date() >= datetime.now(timezone.utc).date():
        close = close.iloc[:-1]
    return close


def fetch_fng():
    r = requests.get("https://api.alternative.me/fng/?limit=0", timeout=30)
    r.raise_for_status()
    return pd.Series({pd.Timestamp(int(d["timestamp"]), unit="s").normalize(): int(d["value"])
                      for d in r.json()["data"]}).sort_index()


def coin_score(name, fng):
    ticker = COINS[name][0]
    df = yf.Ticker(ticker).history(start=HISTORY_START[name], interval="1d", timeout=30)
    price = completed_closes(df)
    res = accumulation_score(price, fng).iloc[-1]
    if pd.isna(res["score"]):
        raise ValueError("zu wenig Historie")
    return float(price.iloc[-1]), res


def etf_info(asset):
    key = os.getenv("ETF_API_KEY")
    if not key:
        return "N/A (kein ETF-Key)"
    try:
        r = requests.get(f"{ETF_API_URL}/flows/{asset}", headers={"Authorization": f"Bearer {key}"},
                         timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        days = sorted(r.json()["days"], key=lambda d: d["date"])
        days = [d for d in days if d["netFlowUsdM"] != 0][-ETF_CONSECUTIVE_INFLOW_DAYS:]  # nur Handelstage
        icon = "↗️" if days and all(d["netFlowUsdM"] > 0 for d in days) else "↘️"
        return f"{icon} " + ", ".join(f"{d['netFlowUsdM']:+,.0f} Mio $" for d in days)
    except Exception as e:
        return f"N/A ({type(e).__name__})"


def funding_info(binance_sym, okx_inst):
    """Ø der letzten 3 Funding-Raten in % pro 8h. Binance blockt US-Server -> Bybit/OKX-Fallback."""
    sources = [
        ("https://fapi.binance.com/fapi/v1/fundingRate", {"symbol": binance_sym, "limit": 3},
         lambda j: [float(x["fundingRate"]) for x in j]),
        ("https://api.bybit.com/v5/market/funding/history",
         {"category": "linear", "symbol": binance_sym, "limit": 3},
         lambda j: [float(x["fundingRate"]) for x in j["result"]["list"]]),
        ("https://www.okx.com/api/v5/public/funding-rate-history", {"instId": okx_inst, "limit": 3},
         lambda j: [float(x["fundingRate"]) for x in j["data"]]),
    ]
    for url, params, parse in sources:
        try:
            r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            rates = [x * 100 for x in parse(r.json())]
            avg = sum(rates) / len(rates)
            return f"{avg:+.4f} %/8h " + ("(erhöht)" if avg > FUNDING_FLUSH_MAX else "(entspannt)")
        except Exception:
            continue
    return "N/A"


def send_telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram-Variablen fehlen – keine Nachricht gesendet.", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat, "text": text, "parse_mode": "Markdown"},
                          timeout=HTTP_TIMEOUT)
        if r.status_code == 400:  # Markdown-Parsing-Fehler -> Klartext
            r = requests.post(url, json={"chat_id": chat, "text": text}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"Telegram-Fehler: {type(e).__name__}", file=sys.stderr)  # Token nie loggen
        return False


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    now_dt = datetime.now(timezone.utc)
    now = now_dt.strftime("%d.%m.%Y %H:%M UTC")
    state = load_state()
    last_zones = state.get("zones", {})

    try:
        fng = fetch_fng()
        fng_now = int(fng.iloc[-1])
    except Exception as e:
        print(f"Fear&Greed nicht verfügbar: {type(e).__name__}", file=sys.stderr)
        fng, fng_now = None, None

    blocks, changes, zones, failed = [], [], {}, []
    for name, (_, etf_asset, fsym, okx) in COINS.items():
        try:
            price, r = coin_score(name, fng)
        except Exception as e:
            failed.append(name)
            blocks.append(f"⚠️ *{name}*: Fehler/N/A ({type(e).__name__}: {e})")
            continue
        score = float(r["score"])
        zone = zone_name(score)
        zones[name] = zone
        if name in last_zones and last_zones[name] != zone:
            changes.append(f"{name}: {last_zones[name]} → {zone}")
        blocks.append("\n".join([
            f"*{name}*  {price:,.0f} $",
            f"{zone}  |  Score *{score:.0f}/100*  |  Kauf: *{multiplier(score)}x* Sparbetrag",
            f"Preis/200W-SMA {r['x200w']:.2f} | Mayer {r['mayer']:.2f} | ATH {r['drawdown']*100:.0f} %",
            f"ETF-Flows: {etf_info(etf_asset)} | Funding: {funding_info(fsym, okx)}",
        ]))

    heartbeat = now_dt.weekday() == HEARTBEAT_WEEKDAY and now_dt.hour < 12
    always = os.getenv("ALWAYS_NOTIFY", "").strip().lower() == "true"
    title = "🚨 *Zonenwechsel*" if changes else "📋 *Wochenbericht*" if heartbeat else "*Accumulation-Monitor*"
    lines = [title, f"📅 {now}"]
    if fng_now is not None:
        lines.append(f"😱 Fear & Greed: {fng_now}")
    if changes:
        lines += ["", *changes]
    lines += ["", *[b + "\n" for b in blocks]]
    lines.append("_Kein Anlagerat. Score = historische Günstigkeit, keine Prognose._")
    message = "\n".join(lines)

    print(f"=== Accumulation-Monitor | {now} ===")
    print(message.replace("*", "").replace("_", ""))

    if "--dry-run" in sys.argv:
        return
    if changes or heartbeat or always:
        print("Sende Telegram-Nachricht …", "OK" if send_telegram(message) else "FEHLGESCHLAGEN")
    else:
        print("Keine Nachricht (kein Zonenwechsel, kein Wochenbericht).")
    # Ausgefallene Coins behalten ihre letzte Zone, damit der nächste Lauf korrekt vergleicht
    new_zones = {**last_zones, **zones}
    if new_zones != last_zones:
        state = {"zones": new_zones, "updated": now}
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    if failed and len(failed) == len(COINS):
        sys.exit(1)


if __name__ == "__main__":
    main()
