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
