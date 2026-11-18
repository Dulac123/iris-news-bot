"""Izvori podataka: Tavily (vesti) i Apify (viralni tvitovi sa X-a)."""
from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from . import config

log = logging.getLogger("iris.sources")

# (tema, upit) - fokus: stvari koje mogu da pomere berzu / kripto / geopolitiku
# Samo 2 upita po pregledu: ~12 pregleda dnevno = ~24 kredita/dan, staje u besplatnih 1000/mesec.
# Ostatak pokrivaju besplatni RSS feedovi (RSS_FEEDOVI).
TAVILY_UPITI = [
    ("svet", "breaking geopolitics war sanctions economy stock market Fed central bank major news"),
    ("kripto/tech", "crypto bitcoin regulation ETF AI big tech chips Nvidia OpenAI major news"),
]

RSS_FEEDOVI = [
    ("svet", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("svet", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("svet", "https://www.theguardian.com/world/rss"),
    ("berza", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("berza", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("kripto", "https://cointelegraph.com/rss"),
    ("kripto", "https://decrypt.co/feed"),
    ("kripto", "https://www.theblock.co/rss.xml"),
    ("tehnologija", "https://feeds.feedburner.com/TechCrunch/"),
    ("tehnologija", "https://feeds.arstechnica.com/arstechnica/index"),
]

TWEET_UPITI = [
    "(bitcoin OR crypto OR ethereum) min_faves:3000 lang:en",
    "(breaking OR geopolitics OR markets OR stocks) min_faves:5000 lang:en",
    "(AI OR OpenAI OR Nvidia OR Anthropic) min_faves:5000 lang:en",
]


async def tavily_vesti(max_po_temi: int = 6) -> list[dict]:
    from tavily import AsyncTavilyClient

    client = AsyncTavilyClient(api_key=config.TAVILY_API_KEY)

    async def jedna(tema: str, upit: str) -> list[dict]:
        try:
            r = await client.search(
                query=upit, topic="news", time_range="day",
                max_results=max_po_temi, search_depth="basic",
            )
        except Exception as e:
            log.warning("Tavily '%s' pao: %s", tema, e)
            return []
        return [
            {
                "tip": "vest", "tema": tema, "naslov": (x.get("title") or "").strip(),
                "url": x.get("url", ""), "tekst": (x.get("content") or "").strip(),
                "score": x.get("score", 0), "izvor": "tavily",
            }
            for x in r.get("results", []) if x.get("url")
        ]

    grupe = await asyncio.gather(*(jedna(t, q) for t, q in TAVILY_UPITI))
    videno, out = set(), []
    for g in grupe:
        for item in g:
            if item["url"] not in videno:
                videno.add(item["url"])
                out.append(item)
    return out


async def pretrazi(upit: str, max_results: int = 5) -> list[dict]:
    """Pretraga na zahtev iz razgovora. Ako pukne - prazna lista, razgovor ide dalje bez nje."""
    from tavily import AsyncTavilyClient

    try:
        r = await AsyncTavilyClient(api_key=config.TAVILY_API_KEY).search(
            query=upit, topic="news", time_range="week", max_results=max_results, search_depth="basic")
        if not r.get("results"):
            r = await AsyncTavilyClient(api_key=config.TAVILY_API_KEY).search(
                query=upit, max_results=max_results, search_depth="basic")
    except Exception as e:
        log.warning("Tavily pretraga '%s' pala: %s", upit, e)
        return []
    return [{"tema": "pretraga", "naslov": (x.get("title") or "").strip(), "url": x.get("url", ""),
             "tekst": (x.get("content") or "").strip()} for x in r.get("results", []) if x.get("url")]


async def x_viralno(max_items: int = 30) -> list[dict]:
    """Viralni tvitovi preko Apify aktora. Ako nema tokena ili pukne - prazna lista, nije kritično."""
    if not config.APIFY_TOKEN:
        return []
    from apify_client import ApifyClientAsync

    try:
        client = ApifyClientAsync(config.APIFY_TOKEN)
        run = await client.actor(config.APIFY_ACTOR).call(
            run_input={"searchTerms": TWEET_UPITI, "maxItems": max_items, "sort": "Top"},
            timeout_secs=150,
        )
        if not run:
            return []
        page = await client.dataset(run["defaultDatasetId"]).list_items(limit=max_items)
    except Exception as e:
        log.warning("Apify pao: %s", e)
        return []

    tvitovi = []
    for t in page.items:
        tekst = (t.get("fullText") or t.get("text") or "").strip()
        url = t.get("url") or t.get("twitterUrl") or ""
        if not tekst or not url:
            continue
        autor = (t.get("author") or {}).get("userName") or "?"
        lajkovi = int(t.get("likeCount") or 0)
        tvitovi.append(
            {
                "tip": "tvit", "tema": "X", "naslov": f"@{autor}: {tekst[:90]}",
                "url": url, "tekst": f"@{autor} ({lajkovi} lajkova, {t.get('retweetCount', 0)} RT, "
                                      f"{t.get('viewCount', '?')} prikaza): {tekst}",
                "score": lajkovi, "izvor": "apify",
            }
        )
    tvitovi.sort(key=lambda x: x["score"], reverse=True)
    return tvitovi[:12]


def _rss_jedan(tema: str, url: str, max_age_h: float, po_feedu: int) -> list[dict]:
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        koren = ET.fromstring(r.content)
    except Exception as e:
        log.info("RSS nije radio (%s): %s", url[:50], e)
        return []
    granica = datetime.now(timezone.utc) - timedelta(hours=max_age_h)
    out = []
    for it in koren.iter("item"):
        naslov = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not naslov or not link:
            continue
        try:
            d = parsedate_to_datetime(it.findtext("pubDate") or "")
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            if d < granica:
                continue
        except Exception:
            pass  # bez datuma: tretiramo kao novo
        opis = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", it.findtext("description") or "")).strip()
        out.append({"tip": "vest", "tema": tema, "naslov": naslov, "url": link, "tekst": opis,
                    "score": 0, "izvor": "rss"})
        if len(out) >= po_feedu:
            break
    return out


async def rss_vesti(max_age_h: float = 3, po_feedu: int = 8) -> list[dict]:
    """Besplatni feedovi, samo skorašnje vesti. Linkovi su direktni pa ih scraper može da pročita."""
    grupe = await asyncio.gather(
        *(asyncio.to_thread(_rss_jedan, t, u, max_age_h, po_feedu) for t, u in RSS_FEEDOVI)
    )
    videno, out = set(), []
    for g in grupe:
        for item in g:
            if item["url"] not in videno:
                videno.add(item["url"])
                out.append(item)
    return out
