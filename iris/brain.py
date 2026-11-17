"""Iris mozak: ličnost + pozivi ka Gemini API-ju (izbor priča, analiza, kapitulacija, razgovor)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import httpx

from . import config

log = logging.getLogger("iris.brain")

_OSNOVA = (Path(__file__).parent / "licnost.txt").read_text(encoding="utf-8").strip() + """

ČEMU SLUŽIŠ: javljaš stvari koje mogu da utiču na berzu, akcije, kripto, geopolitiku i tehnologiju - na svim frontovima. Uz svaku
važnu temu odgovori na pitanje "i šta to znači za tržište/novac?", kao opasku, ne kao finansijski savet."""


def sistem() -> str:
    t = _OSNOVA
    if config.KORISNIK_IME:
        t += (f"\n\nMoje ime je {config.KORISNIK_IME}. Znaš me, oslovljavaj me imenom povremeno (ne u svakoj poruci), "
              "kao neko ko me poznaje.")
    t += f"\n\nSada je {datetime.now(config.TZ).strftime('%d.%m.%Y, %H:%M')} (vreme u Srbiji)."
    return t


async def _pozovi(system: str, messages: list[dict], max_tokens: int = 1500) -> str:
    """Gemini REST. Probamo modele redom; 429/5xx ponovimo, ostalo -> sledeći model."""
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages
        ],
        # "thinking" modeli troše deo budžeta na razmišljanje, pa dajemo rezervu
        "generationConfig": {"maxOutputTokens": max_tokens + 4000, "temperature": 0.9},
    }
    poslednja = ""
    async with httpx.AsyncClient(timeout=90) as http:
        for model in config.GEMINI_MODELI:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            for pokusaj in range(2):
                try:
                    r = await http.post(url, json=body, headers={"x-goog-api-key": config.GEMINI_API_KEY})
                    if r.status_code == 200:
                        parts = r.json()["candidates"][0]["content"]["parts"]
                        tekst = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                        if tekst:
                            return tekst
                        poslednja = f"{model}: prazan odgovor"
                    else:
                        poslednja = f"{model}: HTTP {r.status_code}"
                        if r.status_code not in (429, 500, 503):
                            break
                except Exception as e:
                    poslednja = f"{model}: {type(e).__name__}: {e}"
                log.warning("Gemini problem (%s), pokušaj %d", poslednja, pokusaj + 1)
                await asyncio.sleep(4)
    raise RuntimeError(f"Nijedan Gemini model nije odgovorio ({poslednja})")


# ---------------------------------------------------------------- ocena i izbor
def _json(out: str) -> dict:
    return json.loads(re.search(r"\{.*\}", out, re.S).group(0))


def _lista(k: list[dict]) -> str:
    return "\n".join(f"[{i}] ({x['tema']}/{x['tip']}) {x['naslov']} :: {x['tekst'][:200]}" for i, x in enumerate(k))


async def oceni_hitno(nove: list[dict], poslato: list[str]) -> list[dict]:
    """30-minutno skeniranje: koje od novih naslova su zaista velike/breaking vesti (vaznost >= ALERT_MIN)."""
    prompt = (
        "Ispod su sveže vesti. Oceni vaznost svake od 1 do 10 po tome koliko odmah može da pomeri berzu, kripto, "
        "geopolitiku ili tehnološki sektor. 1-5 je rutina (većina). 8+ je velika/breaking stvar: rat ili velika eskalacija, "
        "krah ili skok tržišta, odluka centralne banke, velika regulativa, veliki hak/bankrot, veliko tehnološko otkriće. "
        "Ne računaj iste događaje koje sam već javila.\n"
        f"Već javljeno danas: {json.dumps(poslato[-15:], ensure_ascii=False)}\n\n"
        f'Vrati SAMO JSON sa onima čija je vaznost >= {config.ALERT_MIN}: {{"hitno":[{{"id":indeks,"v":ocena}}]}} '
        '(prazna lista ako nema ničeg).\n\n' + _lista(nove)
    )
    out = await _pozovi("Ti si strogi urednik vesti. Odgovaraš samo validnim JSON-om.", [{"role": "user", "content": prompt}], 300)
    try:
        ids = [(int(h["id"]), int(h.get("v", 0))) for h in _json(out)["hitno"]]
    except Exception as e:
        log.warning("Ocena hitnosti nije parsirana (%s): %s", e, out[:100])
        return []
    ids = [(i, v) for i, v in ids if 0 <= i < len(nove) and v >= config.ALERT_MIN]
    ids.sort(key=lambda x: -x[1])
    return [nove[i] for i, _ in ids]


async def izaberi_price(kandidati: list[dict], koliko: int, poslato: list[str]) -> list[dict]:
    """Bira do `koliko` najbitnijih tema. Može da vrati i praznu listu ako se ništa posebno ne dešava."""
    if not kandidati:
        return []
    prompt = (
        f"Izaberi do {koliko} NAJBITNIJIH tema na svim frontovima (geopolitika/svet, berza i ekonomija, kripto, tehnologija/AI), "
        "one koje mogu da utiču na tržišta ili su zaista velike i viralne. Pokrij različite fronte i ne biraj dve stavke o istom "
        "događaju. NE biraj ništa što je suštinski isti događaj kao nešto što sam već javila. Ako se ništa zaista "
        "značajno ne dešava, vrati manje stavki ili praznu listu - ne puni kvotu na silu.\n"
        f"Već javljeno danas: {json.dumps(poslato[-20:], ensure_ascii=False)}\n"
        'Odgovori SAMO JSON-om: {"izbor":[indeksi]}\n\n' + _lista(kandidati)
    )
    out = await _pozovi("Ti si urednik vesti. Odgovaraš samo validnim JSON-om.", [{"role": "user", "content": prompt}], 300)
    try:
        ids = _json(out)["izbor"]
        return [kandidati[int(i)] for i in ids if 0 <= int(i) < len(kandidati)][:koliko]
    except Exception as e:
        log.warning("Izbor priča nije parsiran (%s), uzimam prve po redu", e)
        return kandidati[:koliko]


# ------------------------------------------------------------------- tekstovi
def _blok_prica(price: list[dict], limit: int) -> str:
    return "\n\n".join(
        f"=== PRIČA {i} [{p['tema']}] ===\nNaslov: {p['naslov']}\nLink: {p['url']}\nTekst:\n{p['tekst'][:limit]}"
        for i, p in enumerate(price, 1)
    )


_VRSTE = {
    "pregled": "Ovo je redovan pregled sveta (na oko sat i po). Uvod: jedna rečenica u tvom stilu.",
    "jutro": "Ovo je JUTARNJI pregled: šta se desilo preko noći i dok sam spavao. Počni jutarnjim pozdravom u tvom stilu. "
             "Na kraju jedna rečenica: šta vredi pratiti danas (samo ako iz priča proizilazi).",
    "hitno": "Ovo je HITNO javljanje, nešto veliko se upravo desilo. Počni kratkim upozorenjem u tvom stilu (jedna rečenica, "
             "bez panike), pa odmah suština. Kratko.",
}


async def objavi_price(price: list[dict], vrsta: str = "pregled") -> str:
    prompt = (
        f"{_VRSTE[vrsta]} Napiši JEDNU Telegram poruku o temama ispod (sa punim tekstom članaka ili tvitom):\n"
        "- za svaku temu: prvo najvažnije, šta se ZAISTA desilo (iz teksta, ne samo iz naslova) i zašto je bitno / šta znači za "
        "tržište ili novac; najviše 3-4 kratke rečenice; pa tvoje zapažanje; na kraju link\n"
        "- grupiši po frontovima ako ima više tema; numeriši ih\n"
        "- ako je tekst slab ili je samo tvit, reci da je to samo tvit/nepotvrđeno\n"
        "- na kraju, SAMO ako ti se uklapa (otprilike u svakoj trećoj poruci), jedno podbadajuće pitanje ili izazov koji me tera da "
        "sam razmislim o posledicama; ne objašnjavaj sve umesto mene\n\n" + _blok_prica(price, 4500)
    )
    return await _pozovi(sistem(), [{"role": "user", "content": prompt}], 2200)


async def tihi_komentar(naslovi: list[str], povod: str = "pregled") -> str:
    prompt = (
        f"Upravo sam proverila svet ({povod}) i NIŠTA posebno se ne dešava, ništa što vredi punog pregleda. Napiši kratku poruku "
        "(1-3 rečenice) u svom stilu koja to kaže: sarkastično, možda sa podbadanjem, bez izmišljanja. "
        "Ne ponavljaj formulacije od ranije. Ako ti pomaže, ovo su naslovi koje sam prošla (ne moraš ih pominjati): "
        + json.dumps(naslovi[:8], ensure_ascii=False)
    )
    return await _pozovi(sistem(), [{"role": "user", "content": prompt}], 300)


async def kapitulacija(price: list[dict]) -> str:
    if not price:
        return await _pozovi(
            sistem(),
            [{"role": "user", "content": "Danas nisam poslala nijednu vest. Napiši kratku večernju 'kapitulaciju' "
                                          "koja to sarkastično priznaje i kaže laku noć."}],
            400,
        )
    prompt = (
        "Vreme je za večernju KAPITULACIJU: sveobuhvatni rezime dana. Ispod su sve priče koje sam danas pratila. "
        "Struktura:\n1. Uvod u jednoj rečenici (kakav je dan bio).\n"
        "2. Po oblastima (svet, kripto, tehnologija, berza - samo one koje imaju sadržaja): šta se desilo i "
        "kako to može da utiče na tržišta. Poveži priče međusobno gde ima veze.\n"
        "3. 'Šta pratiti sutra' - 1-3 stvari (samo ako iz priča to proizilazi, ne izmišljaj).\n"
        "4. Zaključak za laku noć u tvom stilu (svaki put drugačiji): sarkastičan, malo zavodljiv, i jedno pitanje na kom ću razmišljati do sutra.\n\n"
        + _blok_prica(price, 1500)
    )
    return await _pozovi(sistem(), [{"role": "user", "content": prompt}], 2500)


# ------------------------------------------------------------------ razgovor
def _spoji_istoriju(istorija: list[dict]) -> list[dict]:
    """Uloge moraju naizmenično i prva mora biti 'user' - spajamo uzastopne iste uloge."""
    out: list[dict] = []
    for m in istorija:
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n\n" + m["content"]
        else:
            out.append({"role": m["role"], "content": m["content"]})
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": "[početak današnjeg razgovora]"})
    return out


async def odgovori(istorija: list[dict], price: list[dict]) -> str:
    system = sistem()
    if price:
        system += (
            "\n\nDANAS SI PRATILA OVE PRIČE (koristi ih kad te pitam za detalje; ako pitanje izlazi iz ovoga, "
            "reci da nemaš taj podatak ili da bi trebalo dodatno da potražiš):\n\n"
            + _blok_prica(price, config.MAX_CONTEXT_CHARS)
        )
    return await _pozovi(system, _spoji_istoriju(istorija), 1500)
