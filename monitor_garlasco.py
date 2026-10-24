#!/usr/bin/env python3
"""
monitor_garlasco.py - Monitora fonti pubbliche (feed RSS/Atom) per nuovi
articoli, atti e documenti relativi al caso di Garlasco.

Solo libreria standard, nessuna dipendenza esterna.

Uso:
    python monitor_garlasco.py                 # controlla e stampa le novità
    python monitor_garlasco.py --init          # segna tutto come già visto (primo avvio)
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
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (compatible; garlasco-monitor/1.0)"
STATE_FILE = Path("seen.json")
NEWS_LOG = Path("novita.md")

DEFAULT_CONFIG = {
    # Parole chiave: un articolo viene segnalato se ne contiene almeno una
    "keywords": ["garlasco", "chiara poggi", "alberto stasi", "andrea sempio"],
    # Ricerche su Google News (RSS)
    "google_news_queries": [
        "Garlasco Chiara Poggi",
        "delitto di Garlasco nuove perizie",
        "Garlasco Procura di Pavia",
        "Garlasco Sempio indagine",
    ],
    # Altri feed RSS/Atom a scelta (aggiungi qui le fonti che vuoi seguire)
    "feeds": [
        "https://www.ansa.it/sito/notizie/cronaca/cronaca_rss.xml",
    ],
    # Parole che indicano documenti/atti di particolare interesse
    "highlight": [
        "perizia", "consulenza", "dna", "archiviazione", "ordinanza",
        "sentenza", "revisione", "cassazione", "incidente probatorio",
        "impronta", "intercettazion", "avviso di garanzia",
    ],
}


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
    """Restituisce una lista di dict {id, title, link, summary, date, source}."""
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
            "source": strip_html(it.findtext("source")) or "",
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


def load_state():
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def save_state(seen):
    STATE_FILE.write_text(json.dumps(sorted(seen), indent=0), encoding="utf-8")


def matches(item, keywords):
    blob = f"{item['title']} {item['summary']}".lower()
    return any(k.lower() in blob for k in keywords)


def is_highlight(item, words):
    blob = f"{item['title']} {item['summary']}".lower()
    return [w for w in words if w in blob]


def notify_telegram(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": "true",
    }).encode()
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20
        )
    except Exception as exc:  # la notifica non deve far fallire lo script
        print(f"[!] Telegram non riuscito: {exc}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Monitor caso Garlasco")
    ap.add_argument("--config", help="file JSON di configurazione")
    ap.add_argument("--init", action="store_true",
                    help="primo avvio: registra tutto come già visto senza notificare")
    args = ap.parse_args()

    config = dict(DEFAULT_CONFIG)
    if args.config:
        config.update(json.loads(Path(args.config).read_text(encoding="utf-8")))

    urls = [google_news_url(q) for q in config["google_news_queries"]] + config["feeds"]
    seen = load_state()
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
            seen.add(item["id"])
            new_items.append(item)

    save_state(seen)

    if args.init:
        print(f"Inizializzato: {len(new_items)} elementi registrati come già visti.")
        return

    if not new_items:
        print("Nessuna novità.")
        return

    new_items.sort(key=lambda i: i["date"] or datetime.min.replace(tzinfo=timezone.utc),
                   reverse=True)

    lines = []
    for item in new_items:
        tags = is_highlight(item, config["highlight"])
        date = item["date"].strftime("%d/%m/%Y %H:%M") if item["date"] else "n.d."
        flag = f" [{', '.join(tags)}]" if tags else ""
        src = f" ({item['source']})" if item["source"] else ""
        lines.append(f"- {date}{src}{flag}\n  {item['title']}\n  {item['link']}")

    report = f"Novità caso Garlasco ({len(new_items)}):\n\n" + "\n".join(lines)
    print(report)

    with NEWS_LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n## {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
                + "\n".join(lines) + "\n")

    notify_telegram(report)


if __name__ == "__main__":
    main()
