# Accumulation-Monitor für BTC & ETH

Für Langfrist-Käufer: Der Bot bewertet täglich (07:30 / 19:30 UTC), **wie günstig der Einstieg historisch gesehen ist**, und schickt dir jeden Morgen (07:30 UTC) einen Tagesbericht per Telegram, montags als Wochenbericht, sowie abends bei Zonenwechsel eine Warnung. Er sagt keine Kurse voraus.

## Score (0-100, je Coin)
- **Bewertung (70 %):** Preis/200-Wochen-SMA, Preis/200-Tage-SMA (Mayer-Multiple), Abstand zum ATH. Jede Kennzahl wird als rollierendes 4-Jahres-Perzentil gegen die eigene Historie gerankt (keine festen Preisgrenzen).
- **Stimmung (30 %):** 100 − Fear & Greed.
- **Zonen:** ≥75 🟢 Starker Kaufbereich (2,5x Sparbetrag), ≥55 🟡 Kaufbereich (1,5x), ≥35 ⚪ Neutral (1x), darunter 🔴 Teuer (0,5x). Multiplikatoren in `BUY_MULTIPLIER`.
- Nur zur Info (nicht im Score, da nicht historisch testbar): ETF-Flows der letzten 2 Handelstage, Funding-Rate.

## Backtest (`python backtest.py`, lokal)
- Je höher der Score, desto besser die Trefferquote. BTC, 1 Jahr halten: Score 75-100 → 88 % im Plus (schlechtester Fall −56 %), Score <35 → 66 % (−83 %). ETH: 83 % vs. 45 %.
- Monatlich kaufen und nach Score gewichten senkte den Ø-Kaufpreis seit 2022 um 17 % (BTC) bzw. 7 % (ETH) gegenüber gleichem Betrag jeden Monat.
- **Grenzen:** Nur etwa drei Marktzyklen, überlappende Zeiträume, BTCs Historie war außergewöhnlich bullisch. Vor 2018 schnitt die Gewichtung bei BTC *schlechter* ab als normales Sparen (BTC galt als „teuer“, stieg aber weiter um das 100-Fache). Bewertungssignale können bei strukturellen Neubewertungen lange „zu teuer“ melden. Deshalb kauft man auch in der teuersten Zone mit 0,5x weiter.
- Kein Anlagerat. Der Score beschreibt historische Günstigkeit, keine Prognose.

## Einrichtung
1. **Telegram:** `@BotFather` → `/newbot` → Token. Dem Bot schreiben, dann `https://api.telegram.org/bot<TOKEN>/getUpdates` → `chat.id`.
2. **GitHub Secrets** (*Settings → Secrets and variables → Actions*): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, optional `ETF_API_KEY` (cryptoetf.today).
3. *Actions → Run workflow* (`always_notify` für einen Test).

## Lokaler Test
```bash
pip install -r requirements.txt
python monitor.py --dry-run          # nur ausgeben
ALWAYS_NOTIFY=true TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python monitor.py
```

## Betrieb
- Tagesbericht jeden Morgen, Alarm (🚨) bei Zonenwechsel (letzte Zone je Coin in `state.json`), Warnung bei fehlgeschlagenem Workflow.
- Fällt eine Datenquelle aus, steht das in der Nachricht. GitHub pausiert geplante Workflows nach 60 Tagen ohne Repo-Aktivität.
