"""Poslovi: skeniranje (30 min), pregled sveta (~90 min), jutarnji pregled, kapitulacija. `tick` odlučuje šta je na redu.

Sva vremena poslednjih poslova su u SQLite meta tabeli, pa sve radi i posle restarta (GitHub Actions petlja).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from telegram.ext import Application

from . import brain, config, memory, scraper, sources
from .telegram_util import delovi

log = logging.getLogger("iris.pipeline")
_lock = asyncio.Lock()


async def posalji(app: Application, tekst: str):
    memory.add_message("assistant", tekst)  # da kasnije može da priča o onome što je sama poslala
    for deo in delovi(tekst):
        await app.bot.send_message(config.TELEGRAM_CHAT_ID, deo, disable_web_page_preview=True)


# ------------------------------------------------------------------ pomoćno
async def _kandidati(max_age_h: float) -> list[dict]:
    rss, tavily, tvitovi = await asyncio.gather(
        sources.rss_vesti(max_age_h=max_age_h, po_feedu=6), sources.tavily_vesti(), sources.x_viralno()
    )
    poslato = memory.sent_urls()
    videno, out = set(), []
    for k in tavily + rss + tvitovi:
        if k["url"] not in poslato and k["url"] not in videno:
            videno.add(k["url"])
            out.append(k)
    log.info("Kandidata: %d (rss %d, tavily %d, tvitova %d)", len(out), len(rss), len(tavily), len(tvitovi))
    return out


async def _objavi(app: Application, izbor: list[dict], vrsta: str):
    """Duboko čitanje: ceo tekst članka (ako scrape ne uspe ostaje isečak), pa analiza i slanje."""
    async def obogati(p: dict) -> dict:
        if p["tip"] == "vest":
            pun = await scraper.procitaj_clanak(p["url"])
            if len(pun) > 400:
                p = {**p, "tekst": pun}
        return p

    izbor = list(await asyncio.gather(*(obogati(p) for p in izbor)))
    poruka = await brain.objavi_price(izbor, vrsta)
    for p in izbor:  # čuvamo tek kad je analiza uspela
        memory.save_story(p["url"], p["naslov"], p["tema"], p["izvor"], p["tekst"])
    await posalji(app, poruka)


async def _tiho(app: Application, kandidati: list[dict], povod: str, force: bool):
    if force or time.time() - memory.meta_ts("tiho_ts") >= config.QUIET_PAUSE_MIN * 60:
        await posalji(app, await brain.tihi_komentar([k["naslov"] for k in kandidati], povod))
        memory.set_meta("tiho_ts", time.time())
    else:
        log.info("Ništa posebno, a nedavno sam već javila - ćutim.")


# ------------------------------------------------------------------- poslovi
async def skeniraj(app: Application):
    """Svakih ~30 min: besplatni RSS, javi samo ako je nešto stvarno veliko."""
    memory.set_meta("scan_ts", time.time())
    poslato = memory.sent_urls()
    skenirano = memory.scanned_urls()
    nove = [i for i in await sources.rss_vesti(max_age_h=3, po_feedu=8)
            if i["url"] not in skenirano and i["url"] not in poslato][:50]
    if not nove:
        return
    hitno = await brain.oceni_hitno(nove, memory.today_titles())
    memory.mark_scanned([i["url"] for i in nove])  # tek posle uspešne ocene
    log.info("Skeniranje: %d novih, hitnih %d", len(nove), len(hitno))
    if hitno:
        await _objavi(app, hitno[:2], "hitno")


async def pregled(app: Application, force: bool = False):
    """Svakih ~90 min: do 5 najbitnijih tema sa svih frontova, ili kratka opaska ako je mirno."""
    memory.set_meta("pregled_ts", time.time())
    kandidati = await _kandidati(max_age_h=6)
    izbor = await brain.izaberi_price(kandidati, config.STORIES_PER_CYCLE, memory.today_titles())
    if izbor:
        await _objavi(app, izbor, "pregled")
    else:
        await _tiho(app, kandidati, "redovan pregled", force)


async def jutro(app: Application):
    memory.set_meta("pregled_ts", time.time())
    kandidati = await _kandidati(max_age_h=12)
    izbor = await brain.izaberi_price(kandidati, config.STORIES_PER_CYCLE, memory.today_titles())
    if izbor:
        await _objavi(app, izbor, "jutro")
    else:
        await _tiho(app, kandidati, "jutarnji pregled", True)


async def kapitulacija(app: Application):
    log.info("Kapitulacija...")
    await posalji(app, await brain.kapitulacija(memory.today_stories()))


# ---------------------------------------------------------------------- tick
async def sa_lockom(korutina_fn, *args, **kw):
    async with _lock:
        return await korutina_fn(*args, **kw)


async def tick(app: Application):
    """Poziva se na ~5 min. Odlučuje šta je na redu (jedan posao po tick-u)."""
    if _lock.locked():
        return
    async with _lock:
        now = time.time()
        if now < memory.meta_ts("pauza_do"):
            return
        t = datetime.now(config.TZ)
        h, dan = t.hour, memory.danas()
        try:
            if h >= config.MORNING_HOUR and memory.get_meta("jutro_dan") != dan:
                memory.set_meta("jutro_dan", dan)
                if h < 12:  # ako je bot bio ugašen cele jutro, ne šaljemo "dobro jutro" u 15h
                    await jutro(app)
                    return
            if h >= config.DIGEST_HOUR and memory.get_meta("veče_dan") != dan:
                memory.set_meta("veče_dan", dan)
                await kapitulacija(app)
                return
            if config.MORNING_HOUR <= h < config.DIGEST_HOUR and \
                    now - memory.meta_ts("pregled_ts") >= config.DIGEST_MIN * 60:
                await pregled(app)
                return
            if config.MORNING_HOUR <= h < config.ACTIVE_TO and \
                    now - memory.meta_ts("scan_ts") >= config.SCAN_MIN * 60:
                await skeniraj(app)
        except Exception:
            log.exception("Posao pao")
            memory.set_meta("pauza_do", now + 15 * 60)  # ne udaramo u istu grešku svakih 5 min
            if now - memory.meta_ts("greska_javljena") > 3 * 3600:
                memory.set_meta("greska_javljena", now)
                try:
                    await app.bot.send_message(config.TELEGRAM_CHAT_ID,
                                               "Zapela mi je pretraga. Probaću opet za 15 minuta, ne moraš ništa da radiš.")
                except Exception:
                    pass
