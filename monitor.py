#!/usr/bin/env python3
"""Bitcoin-Turnaround-Monitor: 5-Punkte-Scoring + Telegram-Benachrichtigung."""
import os
import sys
from datetime import datetime, timezone

import requests
import yfinance as yf

# ====================== KONFIGURATION ======================
PRICE_MIN_USD = 62_500          # Technik: Mindestkurs
SMA_DAYS = 21                   # Technik: SMA-Länge
ETF_CONSECUTIVE_INFLOW_DAYS = 2 # ETF: Anzahl Tage mit Netto-Zufluss in Folge
FNG_EXTREME_FEAR = 20           # Stimmung: Extreme-Fear-Grenze (<)
FNG_LOOKBACK_DAYS = 7           # Stimmung: Rückblick
FUNDING_MIN = -0.01             # Derivate: min. Funding in % pro 8h
FUNDING_MAX = 0.015             # Derivate: max. Funding in % pro 8h
DXY_MAX = 101.0                 # Makro: DXY muss darunter liegen
ALERT_THRESHOLD = int(os.getenv("ALERT_THRESHOLD", "3"))  # Mindestscore für Alarm
HTTP_TIMEOUT = 15               # Sekunden
ETF_API_URL = "https://api.cryptoetf.today/v1"
# ===========================================================

OK, FAIL, NA = "✅", "❌", "⚠️"


def check_technical():
    try:
        df = yf.Ticker("BTC-USD").history(period="3mo", interval="1d", timeout=HTTP_TIMEOUT)
        close = df["Close"].dropna()
        if len(close) < SMA_DAYS:
            raise ValueError("zu wenig Kursdaten")
        price = float(close.iloc[-1])
        sma = float(close.tail(SMA_DAYS).mean())
        ok = price > PRICE_MIN_USD and price > sma
        return (OK if ok else FAIL), f"Kurs {price:,.0f} $ | SMA{SMA_DAYS} {sma:,.0f} $ | Min {PRICE_MIN_USD:,} $", price
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
        # Wochenenden entfernen; heutigen Tag ignorieren, solange noch 0 (nicht veröffentlicht)
        days = [d for d in days if datetime.strptime(d["date"], "%Y-%m-%d").weekday() < 5]
        if days and days[-1]["netFlowUsdM"] == 0:
            days = days[:-1]
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


def check_funding():
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
                         params={"symbol": "BTCUSDT", "limit": 3}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        rate = float(r.json()[-1]["fundingRate"]) * 100  # in %
        ok = FUNDING_MIN <= rate <= FUNDING_MAX
        return (OK if ok else FAIL), f"Funding {rate:+.4f} % /8h (Soll {FUNDING_MIN} bis {FUNDING_MAX})"
    except Exception as e:
        return NA, f"Fehler/N/A ({type(e).__name__}: {e})"


def check_macro():
    try:
        df = yf.Ticker("DX-Y.NYB").history(period="1mo", interval="1d", timeout=HTTP_TIMEOUT)
        dxy = float(df["Close"].dropna().iloc[-1])
        return (OK if dxy < DXY_MAX else FAIL), f"DXY {dxy:.2f} (Soll < {DXY_MAX})"
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
    now = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    price_txt = f"{price:,.0f} $" if price else "N/A"

    # Konsolen-Zusammenfassung (GitHub Actions Logs)
    print(f"=== BTC Turnaround Monitor | {now} ===")
    print(f"Score: {score}/5 | BTC: {price_txt}")
    for name, icon, txt in results:
        print(f"{icon} {name}: {txt}")

    lines = [f"*₿ BTC-Turnaround-Monitor*", f"📅 {now}",
             f"📊 Score: *{score}/5*  |  BTC: *{price_txt}*", ""]
    lines += [f"{icon} *{name}*: {txt}" for name, icon, txt in results]
    message = "\n".join(lines)

    always = os.getenv("ALWAYS_NOTIFY", "").strip().lower() == "true"
    if "--dry-run" in sys.argv:
        print("\n--- DRY RUN: Telegram-Nachricht (nicht gesendet) ---\n" + message)
    elif score >= ALERT_THRESHOLD or always:
        print("Sende Telegram-Nachricht …", "OK" if send_telegram(message) else "FEHLGESCHLAGEN")
    else:
        print(f"Score unter Schwelle ({ALERT_THRESHOLD}) – keine Nachricht.")


if __name__ == "__main__":
    main()
