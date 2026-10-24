# Garlasco Monitor

Script Python che monitora fonti pubbliche (Google News RSS e altri feed RSS/Atom) e segnala nuovi articoli e documenti relativi al caso di Garlasco.

- Solo libreria standard, nessuna dipendenza da installare
- Ricorda ciò che ha già visto (`seen.json`) e segnala solo le novità
- Evidenzia le notizie con termini rilevanti (perizia, DNA, sentenza, archiviazione, ecc.)
- Registra le novità in `novita.md`
- Notifiche Telegram opzionali
- Esecuzione automatica ogni 3 ore tramite GitHub Actions

## Uso locale

```bash
python monitor_garlasco.py --init   # primo avvio: registra lo storico come già visto
python monitor_garlasco.py          # controlla le novità
```

Richiede Python 3.9 o superiore.

## Configurazione

Le impostazioni predefinite (parole chiave, ricerche, feed) sono in `DEFAULT_CONFIG` dentro lo script. Per personalizzarle senza modificare il codice, crea un file JSON con le sole chiavi da cambiare:

```json
{
  "feeds": ["https://esempio.it/feed.xml"],
  "google_news_queries": ["Garlasco perizia"]
}
```

e avvialo con:

```bash
python monitor_garlasco.py --config config.json
```

## Notifiche Telegram (opzionale)

1. Crea un bot con [@BotFather](https://t.me/BotFather) e ottieni il token.
2. Ricava il tuo `chat_id` (ad esempio con [@userinfobot](https://t.me/userinfobot)).
3. Imposta le variabili d'ambiente `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.

## Esecuzione automatica su GitHub

Il workflow in `.github/workflows/monitor.yml` esegue lo script ogni 3 ore e fa commit di `seen.json` e `novita.md`.

1. Carica il repository su GitHub.
2. Esegui una volta `--init` in locale e fai commit di `seen.json`.
3. Per le notifiche, aggiungi i secret `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` in *Settings → Secrets and variables → Actions*.
4. In *Settings → Actions → General → Workflow permissions* abilita "Read and write permissions".

## Note

Lo script legge solo fonti pubbliche e non raccoglie dati personali. Verifica sempre le notizie sulle fonti originali: i titoli aggregati possono essere imprecisi.
