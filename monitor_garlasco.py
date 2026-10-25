#!/usr/bin/env python3
"""
monitor_garlasco.py - Monitora fonti pubbliche (feed RSS/Atom) per nuovi
articoli relativi al caso di Garlasco.

Novità rispetto alla prima versione:
- orari convertiti in ora italiana (Europe/Rome, con ora legale)
- novita.md tiene solo gli ultimi N giorni (default 7), raggruppati per giorno
- seen.json si ripulisce da solo (voci più vecchie di 90 giorni)
- le notizie più vecchie della finestra non vengono nemmeno segnalate

Solo libreria standard, Python 3.9+.

Uso:
    python monitor_garlasco.py            # controlla le novità
    python monitor_garlasco.py --init     # primo avvio: segna tutto come già visto
    python monitor_garlasco.py --config altro.json

Notifiche opzionali (variabili d'ambiente):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Rome")
except Exception:  # tzdata mancante (es. Windows senza pacchetto tzdata)
    TZ = timezone.utc

USER_AGENT = "Mozilla/5.0 (compatible; garlasco-monitor/2.0)"
SEEN_FILE = Path("seen.json")        # id già visti -> data prima rilevazione
ENTRIES_FILE = Path("novita.json")   # dati strutturati degli ultimi giorni
NEWS_MD = Path("novita.md")          # versione leggibile

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]

DEFAULT_CONFIG = {
    "keywords": ["garlasco", "chiara poggi", "alberto stasi", "andrea sempio"],
    "google_news_queries": [
        "Garlasco Chiara Poggi",
        "delitto di Garlasco nuove perizie",
        "Garlasco Procura di Pavia",
        "Garlasco Sempio indagine",
    ],
    "feeds": [
        "https://www.ansa.it/sito/notizie/cronaca/cronaca_rss.xml",
    ],
    "highlight": [
        "perizia", "consulenza", "dna", "archiviazione", "ordinanza",
        "sentenza", "revisione", "cassazione", "incidente probatorio",
        "impronta", "intercettazion", "avviso di garanzia",
    ],
    "keep_days": 7,    # giorni di novità conservati in novita.md
    "seen_days": 90,   # giorni di memoria degli articoli già visti
}


# ----------------------------- rete e parsing -----------------------------

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def strip_html(text):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def parse_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_feed(raw):
    root = ET.fromstring(raw)
    items = []
    ns_atom = "{http://www.w3.org/2005/Atom}"

    for it in root.iter("item"):  # RSS
        link = (it.findtext("link") or "").strip()
        items.append({
            "id": (it.findtext("guid") or link).strip(),
            "title": strip_html(it.findtext("title")),
            "link": link,
            "summary": strip_html(it.findtext("description")),
            "date": parse_date(it.findtext("pubDate")),
            "source": strip_html(it.findtext("source")),
        })

    for en in root.iter(ns_atom + "entry"):  # Atom
        link_el = en.find(ns_atom + "link")
        link = link_el.get("href", "") if link_el is not None else ""
        items.append({
            "id": (en.findtext(ns_atom + "id") or link).strip(),
            "title": strip_html(en.findtext(ns_atom + "title")),
            "link": link,
            "summary": strip_html(en.findtext(ns_atom + "summary")
                                  or en.findtext(ns_atom + "content")),
            "date": parse_date(en.findtext(ns_atom + "updated")
                               or en.findtext(ns_atom + "published")),
            "source": "",
        })
    return items


def google_news_url(query):
    q = urllib.parse.quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl=it&gl=IT&ceid=IT:it"


# ------------------------------- stato e dati ------------------------------

def now_utc():
    return datetime.now(timezone.utc)


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def load_seen():
    data = load_json(SEEN_FILE, {})
    if isinstance(data, list):  # vecchio formato: solo elenco di id
        stamp = now_utc().isoformat()
        return {i: stamp for i in data}
    return data


def prune_seen(seen, days):
    cutoff = now_utc() - timedelta(days=days)
    kept = {}
    for item_id, stamp in seen.items():
        try:
            if datetime.fromisoformat(stamp) >= cutoff:
                kept[item_id] = stamp
        except (TypeError, ValueError):
            kept[item_id] = now_utc().isoformat()
    return kept


def entry_time(entry):
    """Data usata per ordinare e potare: quella dell'articolo, altrimenti la rilevazione."""
    for key in ("date", "seen_at"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
    return now_utc()


# ------------------------------- formattazione -----------------------------

def local(dt):
    return dt.astimezone(TZ)


def matches(item, keywords):
    blob = f"{item['title']} {item['summary']}".lower()
    return any(k.lower() in blob for k in keywords)


def tags_for(item, words):
    blob = f"{item['title']} {item['summary']}".lower()
    return [w for w in words if w in blob]


def render_md(entries, keep_days):
    stamp = local(now_utc()).strftime("%d/%m/%Y %H:%M")
    lines = [
        "# Novità caso Garlasco",
        "",
        f"Ultimi {keep_days} giorni · orari in ora italiana · aggiornato il {stamp}",
    ]
    current_day = None
    for e in entries:
        dt = local(entry_time(e))
        day = f"{GIORNI[dt.weekday()]} {dt.day} {MESI[dt.month - 1]} {dt.year}"
        if day != current_day:
            lines += ["", f"## {day}", ""]
            current_day = day
        title = e["title"].replace("[", "(").replace("]", ")")
        src = f" · {e['source']}" if e.get("source") else ""
        flag = f" · `{', '.join(e['tags'])}`" if e.get("tags") else ""
        lines.append(f"- **{dt.strftime('%H:%M')}**{src}{flag} · [{title}]({e['link']})")
    return "\n".join(lines) + "\n"


def notify_telegram(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    # Telegram accetta max 4096 caratteri: spezzo il messaggio per righe
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > 3800:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    for chunk in chunks:
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": "true",
        }).encode()
        try:
            urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20
            )
        except Exception as exc:
            print(f"[!] Telegram non riuscito: {exc}", file=sys.stderr)
            break


# ----------------------------------- main ----------------------------------

def main():
    ap = argparse.ArgumentParser(description="Monitor caso Garlasco")
    ap.add_argument("--config", help="file JSON di configurazione")
    ap.add_argument("--init", action="store_true",
                    help="primo avvio: registra tutto come già visto senza notificare")
    args = ap.parse_args()

    config = dict(DEFAULT_CONFIG)
    if args.config:
        config.update(json.loads(Path(args.config).read_text(encoding="utf-8")))

    keep_days = int(config["keep_days"])
    cutoff = now_utc() - timedelta(days=keep_days)
    urls = [google_news_url(q) for q in config["google_news_queries"]] + config["feeds"]

    seen = load_seen()
    new_items = []

    for url in urls:
        try:
            items = parse_feed(fetch(url))
        except Exception as exc:
            print(f"[!] Errore su {url}: {exc}", file=sys.stderr)
            continue
        for item in items:
            if not item["id"] or item["id"] in seen:
                continue
            if not matches(item, config["keywords"]):
                continue
            seen[item["id"]] = now_utc().isoformat()
            if item["date"] and item["date"] < cutoff:
                continue  # fuori finestra: lo ricordo ma non lo segnalo
            new_items.append(item)

    seen = prune_seen(seen, int(config["seen_days"]))
    SEEN_FILE.write_text(json.dumps(seen, indent=0, sort_keys=True), encoding="utf-8")

    if args.init:
        print(f"Inizializzato: {len(seen)} elementi registrati come già visti.")
        return

    # aggiorno l'archivio degli ultimi giorni
    entries = load_json(ENTRIES_FILE, [])
    known = {e["id"] for e in entries}
    for item in new_items:
        if item["id"] in known:
            continue
        entries.append({
            "id": item["id"],
            "title": item["title"],
            "link": item["link"],
            "source": item["source"],
            "date": item["date"].isoformat() if item["date"] else None,
            "seen_at": now_utc().isoformat(),
            "tags": tags_for(item, config["highlight"]),
        })
    entries = [e for e in entries if entry_time(e) >= cutoff]
    entries.sort(key=entry_time, reverse=True)

    ENTRIES_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    NEWS_MD.write_text(render_md(entries, keep_days), encoding="utf-8")

    if not new_items:
        print("Nessuna novità.")
        return

    lines = []
    for item in sorted(new_items, key=lambda i: i["date"] or now_utc(), reverse=True):
        when = local(item["date"]).strftime("%d/%m %H:%M") if item["date"] else "n.d."
        tags = tags_for(item, config["highlight"])
        flag = f" [{', '.join(tags)}]" if tags else ""
        src = f" ({item['source']})" if item["source"] else ""
        lines.append(f"- {when}{src}{flag}\n  {item['title']}\n  {item['link']}")

    report = f"Novità caso Garlasco ({len(new_items)}):\n\n" + "\n".join(lines)
    print(report)
    notify_telegram(report)


if __name__ == "__main__":
    main()
