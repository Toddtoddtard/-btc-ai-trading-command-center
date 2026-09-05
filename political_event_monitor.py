#!/usr/bin/env python3
"""Automated public political-event watcher for the BTC command center.

Runs without paid API keys. It watches fast public news/RSS discovery for major
presidential remarks and public-account references, including @realDonaldTrump and
the verified-but-historically-inactive @BARRONTRUMP handle. It never treats an
unverified impersonator as Barron Trump.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

QUERIES = [
    ("presidential_event", 'Donald Trump president speech remarks address press conference White House bitcoin crypto tariff sanctions when:1h'),
    ("trump_x", 'site:x.com/realDonaldTrump (bitcoin OR crypto OR tariff OR sanctions OR treasury OR fed) when:1h'),
    ("barron_x", 'site:x.com/BARRONTRUMP (bitcoin OR crypto) when:1h'),
    ("white_house", 'White House Trump remarks speech executive order bitcoin crypto tariff sanctions when:1h'),
]

EVENT_TERMS = {
    "speech": 0.18, "remarks": 0.14, "address": 0.20, "press conference": 0.18,
    "executive order": 0.28, "announcement": 0.12, "tariff": 0.28, "tariffs": 0.28,
    "sanction": 0.25, "sanctions": 0.25, "treasury": 0.16, "federal reserve": 0.16,
    "fed": 0.12, "bitcoin": 0.35, "crypto": 0.30, "digital asset": 0.30,
    "strategic reserve": 0.38, "war": 0.30, "attack": 0.30, "emergency": 0.28,
}
POSITIVE = {
    "bitcoin reserve": 0.65, "strategic bitcoin": 0.60, "strategic reserve": 0.45,
    "pro-crypto": 0.45, "support crypto": 0.38, "support bitcoin": 0.42,
    "deregulation": 0.25, "innovation": 0.12, "digital asset stockpile": 0.38,
    "crypto friendly": 0.35, "approve": 0.12, "adoption": 0.22,
}
NEGATIVE = {
    "ban bitcoin": -0.75, "ban crypto": -0.70, "crackdown": -0.42,
    "seize": -0.25, "fraud": -0.15, "tariff": -0.18, "tariffs": -0.18,
    "sanctions": -0.18, "war": -0.30, "attack": -0.28, "emergency": -0.20,
    "tax crypto": -0.25, "restrict": -0.22, "prohibit": -0.45,
}


def fetch(url, timeout=8):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 BTC-AI-Political-Watch/1.0", "Accept": "application/rss+xml,application/xml,text/xml,*/*"})
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def google_news(query):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    root = ET.fromstring(fetch(url))
    items = []
    for node in root.findall(".//item")[:20]:
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        pub = (node.findtext("pubDate") or "").strip()
        source = (node.findtext("source") or "Google News").strip()
        try:
            dt = parsedate_to_datetime(pub).astimezone(timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)
        items.append({"title": title, "url": link, "published_at": dt.isoformat(), "source": source})
    return items


def nitter_account(handle):
    """Best-effort direct public X-account RSS mirrors; failures are reported, never fabricated."""
    instances = ["https://nitter.poast.org", "https://nitter.privacydev.net"]
    last_error = None
    for base in instances:
        try:
            root = ET.fromstring(fetch(f"{base}/{handle}/rss", timeout=5))
            out = []
            for node in root.findall(".//item")[:8]:
                title = re.sub(r"\s+", " ", (node.findtext("title") or "")).strip()
                pub = node.findtext("pubDate") or ""
                try:
                    dt = parsedate_to_datetime(pub).astimezone(timezone.utc)
                except Exception:
                    dt = datetime.now(timezone.utc)
                out.append({"title": title, "url": node.findtext("link") or f"https://x.com/{handle}", "published_at": dt.isoformat(), "source": f"X @{handle}"})
            return out, "OK"
        except Exception as exc:
            last_error = str(exc)
    return [], f"UNAVAILABLE: {last_error or 'public mirror unavailable'}"


def age_minutes(item, now):
    try:
        dt = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        return max(0.0, (now - dt).total_seconds() / 60.0)
    except Exception:
        return 10**6


def relevance(text):
    t = text.lower()
    raw = sum(weight for term, weight in EVENT_TERMS.items() if term in t)
    return min(1.0, raw)


def direction(text):
    t = text.lower()
    score = sum(weight for term, weight in POSITIVE.items() if term in t)
    score += sum(weight for term, weight in NEGATIVE.items() if term in t)
    return max(-1.0, min(1.0, score))


def build_state():
    now = datetime.now(timezone.utc)
    all_items = []
    health = {}

    for key, query in QUERIES:
        try:
            rows = google_news(query)
            health[f"google_news:{key}"] = "OK"
            for row in rows:
                row["channel"] = key
                all_items.append(row)
        except Exception as exc:
            health[f"google_news:{key}"] = f"UNAVAILABLE: {str(exc)[:100]}"

    for handle, channel in [("realDonaldTrump", "trump_x_direct"), ("BARRONTRUMP", "barron_x_direct")]:
        rows, status = nitter_account(handle)
        health[f"x:{handle}"] = status
        for row in rows:
            row["channel"] = channel
            all_items.append(row)

    unique = {}
    for item in all_items:
        key = hashlib.sha1((item.get("title", "") + item.get("url", "")).encode()).hexdigest()
        unique[key] = item

    candidates = []
    for item in unique.values():
        age = age_minutes(item, now)
        if age > 75:
            continue
        rel = relevance(item["title"])
        # Direct account posts get a relevance floor only when BTC/macro terms are present.
        lower = item["title"].lower()
        direct = item.get("channel") in {"trump_x_direct", "barron_x_direct", "trump_x", "barron_x"}
        crypto_or_macro = any(x in lower for x in ("bitcoin", "crypto", "tariff", "sanction", "treasury", "fed", "reserve", "war", "emergency"))
        if direct and crypto_or_macro:
            rel = max(rel, 0.58)
        if rel < 0.22:
            continue
        d = direction(item["title"])
        freshness = max(0.15, 1.0 - age / 90.0)
        impact = min(1.0, rel * (0.70 + 0.30 * freshness))
        item.update(age_minutes=round(age, 1), relevance=round(rel, 3), impact=round(impact, 3), direction_score=round(d, 3))
        candidates.append(item)

    candidates.sort(key=lambda x: (x["impact"], -x["age_minutes"]), reverse=True)
    top = candidates[:8]
    active_items = [x for x in top if x["age_minutes"] <= 45 and x["impact"] >= 0.32]
    active = bool(active_items)

    if active:
        weights = [max(0.05, x["impact"]) for x in active_items]
        dscore = sum(x["direction_score"] * w for x, w in zip(active_items, weights)) / sum(weights)
        impact = max(x["impact"] for x in active_items)
        # Pure volatility events can be direction-neutral; do not force a trade direction.
        confidence = min(0.88, 0.48 + impact * 0.32 + min(abs(dscore), 0.5) * 0.16)
        status = "ACTIVE"
        lead = active_items[0]
        reason = f"{lead['source']}: {lead['title'][:180]}"
    else:
        dscore, impact, confidence = 0.0, 0.0, 0.0
        status = "WATCHING"
        reason = "No qualifying high-impact political/crypto event in the active window"

    return {
        "version": 1,
        "generated_at": now.isoformat(),
        "active": active,
        "status": status,
        "impact_score": round(float(impact), 4),
        "direction_score": round(float(dscore), 4),
        "confidence": round(float(confidence), 4),
        "reason": reason,
        "events": top,
        "source_health": health,
        "watched_accounts": {
            "Donald Trump": "@realDonaldTrump",
            "Barron Trump": "@BARRONTRUMP (official/verified handle; impersonator accounts excluded)",
        },
        "policy": "Zero voting influence unless a qualifying recent event is active.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="political_event_watch.json")
    args = parser.parse_args()
    state = build_state()
    Path(args.output).write_text(json.dumps(state, indent=2, sort_keys=True))
    print(json.dumps({k: state[k] for k in ("generated_at", "active", "status", "impact_score", "direction_score", "confidence")}, indent=2))


if __name__ == "__main__":
    main()
