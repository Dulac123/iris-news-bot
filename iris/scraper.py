"""Duboko čitanje: skida ceo članak sa URL-a (requests + BeautifulSoup)."""
from __future__ import annotations

import asyncio
import logging
import re

import requests
from bs4 import BeautifulSoup

from . import config

log = logging.getLogger("iris.scraper")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
SMECE = ["script", "style", "noscript", "nav", "footer", "aside", "form", "header", "iframe", "figure"]


def _izvuci(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(SMECE):
        t.decompose()
    koren = soup.find("article") or soup.find("main") or soup.body or soup
    pasusi = [p.get_text(" ", strip=True) for p in koren.find_all("p")]
    pasusi = [p for p in pasusi if len(p) > 40]  # bez menija, "share" dugmadi i sličnog
    return re.sub(r"\s+", " ", "\n".join(pasusi)).strip()


def _skini(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        if "html" not in r.headers.get("content-type", "html"):
            return ""
        return _izvuci(r.text)[: config.MAX_ARTICLE_CHARS]
    except Exception as e:
        log.info("Scrape nije uspeo (%s): %s", url[:70], e)
        return ""


async def procitaj_clanak(url: str) -> str:
    return await asyncio.to_thread(_skini, url)
