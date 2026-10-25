#!/usr/bin/env python3
"""
monitor_garlasco.py - Monitora fonti pubbliche (feed RSS/Atom) per nuovi
articoli relativi al caso di Garlasco e li archivia.

File prodotti:
  archivio.json        archivio completo, non viene mai potato
  archivio/AAAA-MM.md  archivio leggibile, un file per mese
  novita.md            solo gli ultimi N giorni (default 7)

Se trova notizie nuove e recenti scrive un testo nel file indicato dalla
variabile d'ambiente NOTIFY_FILE: il workflow lo usa per aprire una issue
GitHub, che genera la notifica sul telefono.

Solo libreria standard, Python 3.9+.

Uso:
    python monitor_garlasco.py
    python monitor_garlasco.py --init     # archivia senza notificare
    python monitor_garlasco.py --config altro.json
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
except Exception:  # tzdata mancante
    TZ = timezone.utc

USER_AGENT = "Mozilla/5.0 (compatible; garlasco-monitor/3.0)"
ARCHIVE_FILE = Path("archivio.json")
ARCHIVE_DIR = Path("archivio")
NEWS_MD = Path("novita.md")
LEGACY_FILES = [Path("novita.json"), Path("seen.json")]  # vecchie versioni

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
    "keep_days": 7,  # giorni mostrati in novita.md e considerati "recenti"
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
    ns = "{http://www.w3.org/2005/Atom}"

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

    for en in root.iter(ns + "entry"):  # Atom
        link_el = en.find(ns + "link")
        link = link_el.get("href", "") if link_el is not None else ""
        items.append({
            "id": (en.findtext(ns + "id") or link).strip(),
            "title": strip_html(en.findtext(ns + "title")),
            "link": link,
            "summary": strip_html(en.findtext(ns + "summary")
                                  or en.findtext(ns + "content")),
            "date": parse_date(en.findtext(ns + "updated")
                               or en.findtext(ns + "published")),
            "source": "",
        })
    return items


def google_news_url(query):
    q = urllib.parse.quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl=it&gl=IT&ceid=IT:it"


# ------------------------------ dati e utilità -----------------------------

def now_utc():
    return datetime.now(timezone.utc)


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def local(dt):
    return dt.astimezone(TZ)


def entry_time(entry):
    """Data dell'articolo, altrimenti quella della rilevazione."""
    for key in ("date", "seen_at"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
    return now_utc()


def matches(item, keywords):
    blob = f"{item['title']} {item['summary']}".lower()
    return any(k.lower() in blob for k in keywords)


def make_entry(item, highlight):
    blob = f"{item['title']} {item['summary']}".lower()
    return {
        "id": item["id"],
        "title": item["title"],
        "link": item["link"],
        "source": item["source"],
        "date": item["date"].isoformat() if item["date"] else None,
        "seen_at": now_utc().isoformat(),
        "tags": [w for w in highlight if w in blob],
    }


def line_for(entry, with_day=False):
    dt = local(entry_time(entry))
    when = dt.strftime("%d/%m %H:%M") if with_day else dt.strftime("%H:%M")
    title = entry["title"].replace("[", "(").replace("]", ")")
    src = f" · {entry['source']}" if entry.get("source") else ""
    flag = f" · `{', '.join(entry['tags'])}`" if entry.get("tags") else ""
    return f"- **{when}**{src}{flag} · [{title}]({entry['link']})"


def render_md(entries, title, subtitle):
    lines = [f"# {title}", "", subtitle]
    current_day = None
    for e in entries:
        dt = local(entry_time(e))
        day = f"{GIORNI[dt.weekday()]} {dt.day} {MESI[dt.month - 1]} {dt.year}"
        if day != current_day:
            lines += ["", f"## {day}", ""]
            current_day = day
        lines.append(line_for(e))
    return "\n".join(lines) + "\n"


def write_monthly(entries):
    months = {}
    for e in entries:
        dt = local(entry_time(e))
        months.setdefault((dt.year, dt.month), []).append(e)
    ARCHIVE_DIR.mkdir(exist_ok=True)
    for (year, month), items in months.items():
        text = render_md(
            items,
            f"Archivio caso Garlasco · {MESI[month - 1]} {year}",
            f"{len(items)} {'notizia' if len(items) == 1 else 'notizie'}"
            " · orari in ora italiana",
        )
        (ARCHIVE_DIR / f"{year}-{month:02d}.md").write_text(text, encoding="utf-8")


def write_notification(new_recent):
    path = os.getenv("NOTIFY_FILE")
    if not path or not new_recent:
        return
    stamp = local(now_utc()).strftime("%d/%m/%Y %H:%M")
    lines = [f"Nuove notizie trovate il {stamp} (ora italiana):", ""]
    lines += [line_for(e, with_day=True) for e in new_recent]
    lines += ["", "Archivio completo: cartella `archivio/` del repository."]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------- main ----------------------------------

def main():
    ap = argparse.ArgumentParser(description="Monitor caso Garlasco")
    ap.add_argument("--config", help="file JSON di configurazione")
    ap.add_argument("--init", action="store_true",
                    help="archivia tutto senza generare la notifica")
    args = ap.parse_args()

    config = dict(DEFAULT_CONFIG)
    if args.config:
        config.update(json.loads(Path(args.config).read_text(encoding="utf-8")))

    keep_days = int(config["keep_days"])
    cutoff = now_utc() - timedelta(days=keep_days)
    notify_path = os.getenv("NOTIFY_FILE")
    if notify_path and Path(notify_path).exists():
        Path(notify_path).unlink()

    # archivio esistente + dati delle versioni precedenti (migrazione)
    archive = {}
    for source in (load_json(ARCHIVE_FILE, []), load_json(Path("novita.json"), [])):
        for e in source:
            if e.get("id"):
                archive.setdefault(e["id"], e)

    urls = [google_news_url(q) for q in config["google_news_queries"]] + config["feeds"]
    new_recent = []

    for url in urls:
        try:
            items = parse_feed(fetch(url))
        except Exception as exc:
            print(f"[!] Errore su {url}: {exc}", file=sys.stderr)
            continue
        for item in items:
            if not item["id"] or item["id"] in archive:
                continue
            if not matches(item, config["keywords"]):
                continue
            entry = make_entry(item, config["highlight"])
            archive[entry["id"]] = entry
            if entry_time(entry) >= cutoff:  # solo le recenti fanno notifica
                new_recent.append(entry)

    entries = sorted(archive.values(), key=entry_time, reverse=True)
    ARCHIVE_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    write_monthly(entries)

    recent = [e for e in entries if entry_time(e) >= cutoff]
    stamp = local(now_utc()).strftime("%d/%m/%Y %H:%M")
    NEWS_MD.write_text(
        render_md(recent, "Novità caso Garlasco",
                  f"Ultimi {keep_days} giorni · orari in ora italiana · "
                  f"aggiornato il {stamp}"),
        encoding="utf-8",
    )

    for legacy in LEGACY_FILES:  # dati ormai migrati nell'archivio
        legacy.unlink(missing_ok=True)

    print(f"Archivio: {len(entries)} notizie in totale.")
    if args.init or not new_recent:
        print("Nessuna novità." if not new_recent else "Init: nessuna notifica.")
        return

    new_recent.sort(key=entry_time, reverse=True)
    print(f"Novità: {len(new_recent)}")
    for e in new_recent:
        print(line_for(e, with_day=True))
    write_notification(new_recent)


if __name__ == "__main__":
    main()
