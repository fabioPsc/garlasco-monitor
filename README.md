# Garlasco Monitor

Script Python che controlla fonti pubbliche (Google News RSS e altri feed RSS/Atom), archivia le notizie sul caso di Garlasco e avvisa quando ne compaiono di nuove.

## Cosa produce

| File | Contenuto |
|---|---|
| `novita.md` | Notizie degli ultimi 7 giorni, raggruppate per giorno, in ora italiana |
| `archivio/AAAA-MM.md` | Archivio leggibile, un file per mese |
| `archivio.json` | Archivio completo, non viene mai potato |

## Come funziona

Il workflow in `.github/workflows/monitor.yml` gira ogni 3 ore:

1. esegue `monitor_garlasco.py`;
2. salva archivio e novità nel repository;
3. se ci sono notizie nuove e recenti, apre una **issue** assegnata a te. GitHub ti manda la notifica per email e, con l'app GitHub installata e le notifiche attive, anche sul telefono.

Le notizie più vecchie di 7 giorni vengono archiviate ma non generano notifica.

## Uso locale

```bash
python monitor_garlasco.py
```

Richiede Python 3.9 o superiore e non ha dipendenze.

## Configurazione

Le impostazioni predefinite sono in `DEFAULT_CONFIG` nello script. Per cambiarle senza toccare il codice crea un file JSON con le sole chiavi da modificare:

```json
{
  "feeds": ["https://esempio.it/feed.xml"],
  "keep_days": 14
}
```

e avvia con `python monitor_garlasco.py --config config.json`.

## Impostazioni GitHub necessarie

- *Settings → Actions → General → Workflow permissions*: **Read and write permissions**.
- Notifiche: nell'app GitHub abilita le notifiche push; in *Settings → Notifications* dell'account verifica che siano attive per le issue assegnate a te.

## Note

Lo script legge solo fonti pubbliche e non raccoglie dati personali. I titoli degli aggregatori possono essere imprecisi: verifica sempre le notizie sulla fonte originale.
