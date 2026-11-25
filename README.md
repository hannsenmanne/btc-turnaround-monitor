# Bitcoin-Turnaround-Monitor

Prüft 2x täglich (07:30 / 19:30 UTC) fünf Signale (Technik, ETF-Flows, Stimmung, Derivate, Makro) und sendet bei Score ≥ 3/5 eine Telegram-Nachricht. Schwellenwerte stehen oben in `monitor.py`.

## 1. Telegram-Bot
1. In Telegram `@BotFather` öffnen → `/newbot` → Token notieren (`TELEGRAM_BOT_TOKEN`).
2. Deinem Bot eine beliebige Nachricht schreiben.
3. `https://api.telegram.org/bot<TOKEN>/getUpdates` aufrufen → `chat.id` notieren (`TELEGRAM_CHAT_ID`).

## 2. GitHub
1. Repo anlegen und alle Dateien pushen.
2. *Settings → Secrets and variables → Actions* → Secrets anlegen: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, optional `ETF_API_KEY`.
3. *Actions → BTC Turnaround Monitor → Run workflow* (mit `always_notify` für einen Test).

## 3. Lokaler Test
```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... ALWAYS_NOTIFY=true
python monitor.py
```
Ohne `ETF_API_KEY` wird die ETF-Kategorie als ⚠️ N/A markiert.


Mit `python monitor.py --dry-run` wird die Telegram-Nachricht nur ausgegeben, nicht gesendet.

## Alarm-Logik
- Alarm (🚨) nur, wenn der Score >= `ALERT_THRESHOLD` ist **und** sich seit dem letzten Lauf geändert hat (letzter Score in `state.json`).
- Jeden Montagmorgen (UTC) kommt ein Wochenbericht als Lebenszeichen.
- Schlägt der Workflow fehl, kommt eine Telegram-Warnung.
- Fällt eine Datenquelle aus, steht das in der Nachricht.
