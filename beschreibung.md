# Prompt: Bitcoin-Turnaround-Monitor (Python + GitHub Actions + Telegram)

Erstelle ein vollständiges, produktionsreifes Python-Projekt inklusive GitHub-Actions-Workflow, das täglich prüft, ob erste Anzeichen für einen Bitcoin-Turnaround vorliegen, und mir bei Erreichen einer Schwelle eine strukturierte Nachricht per Telegram sendet.

## Projektstruktur

Erstelle folgende Dateien mit vollständigem Code:

1. `monitor.py` – Hauptskript für Datenabruf, 5-Punkte-Scoring und Telegram-Versand
2. `requirements.txt` – benötigte Python-Pakete
3. `.github/workflows/btc_monitor.yml` – GitHub-Actions-Workflow (Cronjob 2x täglich um 07:30 und 19:30 UTC + manueller Start per `workflow_dispatch`)
4. `README.md` – kurze Schritt-für-Schritt-Anleitung für Einrichtung von Telegram-Bot (`@BotFather`), GitHub Secrets und lokalem Test

## Datenquellen & 5-Punkte-Scoring-Logik

Definiere alle Schwellenwerte gut sichtbar als Konstanten am Anfang von `monitor.py`, damit ich sie später leicht anpassen kann. Vergib maximal 5 Punkte (je 1 Punkt pro Kategorie):

1. **Technik (+1):**
   - Quelle: `yfinance` (`BTC-USD`)
   - Bedingung: Aktueller BTC-Tagesschlusskurs > 62.500 USD UND über dem 21-Tage-SMA.
2. **ETF-Flows (+1):**
   - Quelle: Crypto ETF Flows API (`https://api.cryptoetf.today/v1`, authentifiziert über Umgebungsvariable `ETF_API_KEY`; falls kein Key gesetzt oder API nicht erreichbar, sauber überspringen und als `N/A` markieren).
   - Bedingung: US-Spot-Bitcoin-ETFs verzeichnen an mindestens 2 aufeinanderfolgenden Handelstagen Nettozuflüsse (> 0 USD).
3. **Stimmung (+1):**
   - Quelle: FearGreedChart API (`https://crypto.feargreedchart.com/api-docs` bzw. kostenlose Alternative.me API `https://api.alternative.me/fng/?limit=7` ohne API-Key).
   - Bedingung: Fear & Greed Index lag in den letzten 7 Tagen mindestens einmal im Bereich „Extreme Fear“ (< 20) und steigt aktuell wieder über 20.
4. **Derivate (+1):**
   - Quelle: Öffentliche Funding-Rate-API (z. B. Binance Futures `https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3` oder FearGreedChart `funding_ann_pct`).
   - Bedingung: Aktuelle Funding-Rate liegt im gesunden, nicht überhitzten Bereich (z. B. zwischen -0,01 % und +0,015 % pro 8h) ohne extreme Long-Überhebelung.
5. **Makro (+1):**
   - Quelle: `yfinance` (`DX-Y.NYB` für den US-Dollar-Index DXY).
   - Bedingung: DXY notiert unter 101,0.

## Benachrichtigungs- & Fehlerlogik

- Nutze die Telegram Bot API (`sendMessage` mit `parse_mode="Markdown"`) über die Umgebungsvariablen `TELEGRAM_BOT_TOKEN` und `TELEGRAM_CHAT_ID`.
- Sende eine Nachricht, wenn der Gesamtscore >= `ALERT_THRESHOLD` (Standard: 3 von 5) ist ODER wenn die Umgebungsvariable `ALWAYS_NOTIFY=true` gesetzt ist (z. B. für tägliche Statusberichte oder Tests).
- Die Nachricht soll übersichtlich anzeigen: Datum, Gesamtscore (z. B. `3/5`), BTC-Kurs, sowie für jede der 5 Kategorien ein Status-Icon (✅ / ❌ / ⚠️) mit dem jeweiligen konkreten Messwert.
- Baue robustes Error-Handling mit Timeouts ein: Wenn eine einzelne API ausfällt, darf das Skript nicht abstürzen, sondern soll diese Kategorie mit ⚠️ (`Fehler/N/A`) markieren und die übrigen Kategorien trotzdem auswerten.

## GitHub Actions

- Nutze `ubuntu-latest` und Python 3.11.
- Lade `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` und optional `ETF_API_KEY` aus GitHub Secrets.
- Gib beim Ausführen auch eine kurze Konsolen-Zusammenfassung für die GitHub-Actions-Logs aus.
