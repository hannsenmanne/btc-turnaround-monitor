#!/usr/bin/env python3
"""Bitcoin-Turnaround-Monitor: 5-Punkte-Scoring + Telegram-Benachrichtigung."""
import json
import os
import sys
from datetime import datetime, timezone

import requests
import yfinance as yf

# ====================== KONFIGURATION ======================
SMA_DAYS = 21                   # Technik: kurzer SMA
SMA_LONG_DAYS = 50              # Technik: Kurs muss auch über diesem SMA liegen (Reclaim)
ETF_CONSECUTIVE_INFLOW_DAYS = 2 # ETF: Anzahl Tage mit Netto-Zufluss in Folge
FNG_EXTREME_FEAR = 20           # Stimmung: Extreme-Fear-Grenze (<)
FNG_LOOKBACK_DAYS = 7           # Stimmung: Rückblick
FUNDING_FLUSH_MAX = 0.005       # Derivate: Ø-Funding (letzte ~24h) in % pro 8h muss <= sein (Long-Überhebelung abgebaut)
DXY_SMA_DAYS = 20               # Makro: DXY muss unter seinem eigenen SMA liegen (Dollar fällt)
ALERT_THRESHOLD = int(os.getenv("ALERT_THRESHOLD", "3"))  # Mindestscore für Alarm
HEARTBEAT_WEEKDAY = 0           # Wochenbericht: 0 = Montag (Morgenlauf, UTC)
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
HTTP_TIMEOUT = 15               # Sekunden
ETF_API_URL = "https://api.cryptoetf.today/v1"
# ===========================================================

OK, FAIL, NA = "✅", "❌", "⚠️"


def completed_closes(df):
    """Schlusskurse ohne die heutige, noch laufende Tageskerze (Lauf um 07:30/19:30 UTC)."""
    close = df["Close"].dropna()
    if len(close) and close.index[-1].date() >= datetime.now(timezone.utc).date():
        close = close.iloc[:-1]
    return close


def check_technical():
    try:
        df = yf.Ticker("BTC-USD").history(period="6mo", interval="1d", timeout=HTTP_TIMEOUT)
        close = completed_closes(df)
        if len(close) < SMA_LONG_DAYS:
            raise ValueError("zu wenig Kursdaten")
        price = float(close.iloc[-1])
        sma = float(close.tail(SMA_DAYS).mean())
        sma_long = float(close.tail(SMA_LONG_DAYS).mean())
        ok = price > sma and price > sma_long
        return (OK if ok else FAIL), f"Kurs {price:,.0f} $ | SMA{SMA_DAYS} {sma:,.0f} $ | SMA{SMA_LONG_DAYS} {sma_long:,.0f} $", price
    except Exception as e:
        return NA, f"Fehler/N/A ({type(e).__name__}: {e})", None


def check_etf():
    key = os.getenv("ETF_API_KEY")
    if not key:
        return NA, "N/A (kein ETF_API_KEY gesetzt)"
    try:
        r = requests.get(f"{ETF_API_URL}/flows/btc",
                         headers={"Authorization": f"Bearer {key}"}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        days = sorted(r.json()["days"], key=lambda d: d["date"])
        # Tage ohne Flow (Wochenenden, US-Feiertage, heutiger noch nicht veröffentlichter Tag) ignorieren
        days = [d for d in days if d["netFlowUsdM"] != 0]
        last = days[-ETF_CONSECUTIVE_INFLOW_DAYS:]
        if len(last) < ETF_CONSECUTIVE_INFLOW_DAYS:
            raise ValueError("zu wenig Handelstage")
        ok = all(d["netFlowUsdM"] > 0 for d in last)
        txt = ", ".join(f"{d['date'][5:]}: {d['netFlowUsdM']:+,.0f} Mio $" for d in last)
        return (OK if ok else FAIL), f"Netto-Flows {txt}"
    except Exception as e:
        return NA, f"Fehler/N/A ({type(e).__name__}: {e})"


def check_sentiment():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=7", timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        # API liefert neueste zuerst
        vals = [int(d["value"]) for d in r.json()["data"]][:FNG_LOOKBACK_DAYS]
        if not vals:
            raise ValueError("zu wenig Daten")
        current = vals[0]
        was_extreme = any(v < FNG_EXTREME_FEAR for v in vals)
        ok = was_extreme and current > FNG_EXTREME_FEAR
        return (OK if ok else FAIL), f"Aktuell {current} | 7d-Min {min(vals)} | Extreme Fear (<{FNG_EXTREME_FEAR}): {'ja' if was_extreme else 'nein'}"
    except Exception as e:
        return NA, f"Fehler/N/A ({type(e).__name__}: {e})"


def _funding_rates_pct():
    """Letzte Funding-Raten in % pro 8h (neueste zuletzt). Fallback-Kette, da Binance
    US-Server (GitHub) blockt (HTTP 451)."""
    sources = [
        ("Binance", "https://fapi.binance.com/fapi/v1/fundingRate",
         {"symbol": "BTCUSDT", "limit": 3}, lambda j: [float(x["fundingRate"]) for x in j]),
        ("Bybit", "https://api.bybit.com/v5/market/funding/history",
         {"category": "linear", "symbol": "BTCUSDT", "limit": 3},
         lambda j: [float(x["fundingRate"]) for x in reversed(j["result"]["list"])]),
        ("OKX", "https://www.okx.com/api/v5/public/funding-rate-history",
         {"instId": "BTC-USDT-SWAP", "limit": 3},
         lambda j: [float(x["fundingRate"]) for x in reversed(j["data"])]),
    ]
    errors = []
    for name, url, params, parse in sources:
        try:
            r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            rates = [x * 100 for x in parse(r.json())]
            if rates:
                return name, rates
            raise ValueError("leer")
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}")
    raise RuntimeError("; ".join(errors))


def check_funding():
    """Funding-Flush: Ø der letzten Raten <= FUNDING_FLUSH_MAX (Standard-Funding ~0,01 % gilt als überhitzt)."""
    try:
        name, rates = _funding_rates_pct()
        avg = sum(rates) / len(rates)
        ok = avg <= FUNDING_FLUSH_MAX
        return (OK if ok else FAIL), f"Ø Funding {avg:+.4f} % /8h über {len(rates)} Raten ({name}; Soll <= {FUNDING_FLUSH_MAX})"
    except Exception as e:
        return NA, f"Fehler/N/A ({e})"


def check_macro():
    try:
        df = yf.Ticker("DX-Y.NYB").history(period="3mo", interval="1d", timeout=HTTP_TIMEOUT)
        close = completed_closes(df)
        if len(close) < DXY_SMA_DAYS:
            raise ValueError("zu wenig Daten")
        dxy = float(close.iloc[-1])
        sma = float(close.tail(DXY_SMA_DAYS).mean())
        return (OK if dxy < sma else FAIL), f"DXY {dxy:.2f} | SMA{DXY_SMA_DAYS} {sma:.2f} (Soll DXY < SMA)"
    except Exception as e:
        return NA, f"Fehler/N/A ({type(e).__name__}: {e})"


def send_telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram-Variablen fehlen – keine Nachricht gesendet.", file=sys.stderr)
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text, "parse_mode": "Markdown"},
                          timeout=HTTP_TIMEOUT)
        if r.status_code == 400:  # Markdown-Parsing-Fehler -> als Klartext erneut senden
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": text}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return True
    except Exception as e:
        # Token nicht in Logs ausgeben
        print(f"Telegram-Fehler: {type(e).__name__}", file=sys.stderr)
        return False


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def main():
    tech_icon, tech_txt, price = check_technical()
    results = [
        ("Technik", tech_icon, tech_txt),
        ("ETF-Flows", *check_etf()),
        ("Stimmung", *check_sentiment()),
        ("Derivate", *check_funding()),
        ("Makro", *check_macro()),
    ]
    score = sum(1 for _, icon, _ in results if icon == OK)
    failed = [n for n, icon, _ in results if icon == NA]
    now_dt = datetime.now(timezone.utc)
    now = now_dt.strftime("%d.%m.%Y %H:%M UTC")
    price_txt = f"{price:,.0f} $" if price else "N/A"

    state = load_state()
    last_score = state.get("last_score")
    always = os.getenv("ALWAYS_NOTIFY", "").strip().lower() == "true"
    heartbeat = now_dt.weekday() == HEARTBEAT_WEEKDAY and now_dt.hour < 12
    crossed = score >= ALERT_THRESHOLD and score != last_score

    # Konsolen-Zusammenfassung (GitHub Actions Logs)
    print(f"=== BTC Turnaround Monitor | {now} ===")
    print(f"Score: {score}/5 (zuletzt: {last_score}) | BTC: {price_txt}")
    for name, icon, txt in results:
        print(f"{icon} {name}: {txt}")

    if crossed:
        title = "🚨 *BTC-Turnaround-Signal*"
    elif heartbeat:
        title = "📋 *BTC-Wochenbericht*"
    else:
        title = "*₿ BTC-Turnaround-Monitor*"
    lines = [title, f"📅 {now}", f"📊 Score: *{score}/5*  |  BTC: *{price_txt}*", ""]
    lines += [f"{icon} *{name}*: {txt}" for name, icon, txt in results]
    if failed:
        lines += ["", f"⚠️ Ausgefallen: {', '.join(failed)} – Score evtl. zu niedrig."]
    message = "\n".join(lines)

    if "--dry-run" in sys.argv:
        print("\n--- DRY RUN: Telegram-Nachricht (nicht gesendet) ---\n" + message)
        return
    if crossed or heartbeat or always:
        print("Sende Telegram-Nachricht …", "OK" if send_telegram(message) else "FEHLGESCHLAGEN")
    else:
        print(f"Keine Nachricht (Score {score}, Schwelle {ALERT_THRESHOLD}, unverändert/unter Schwelle).")
    if state.get("last_score") != score:
        state["last_score"] = score
        state["updated"] = now
        save_state(state)


if __name__ == "__main__":
    main()
