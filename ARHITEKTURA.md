# Iris - arhitektura

## Šta radi sama (scheduler `tick` na svakih 5 min, vremena u SQLite meta tabeli pa sve preživi restart)
| Šta | Kad | Izvor |
|---|---|---|
| Jutarnji pregled | od 07:00 (samo ako je ujutru) | RSS + Tavily |
| Pregled sveta, do 5 tema sa svih frontova | na ~90 min (07-22h); ako je mirno, kratka opaska u njenom fazonu (najviše na 3h) | RSS + Tavily + (Apify) |
| Skeniranje hitnih vesti | na 30 min (07-23h); javlja samo ako je vaznost >= 8/10 | RSS (besplatno) |
| Kapitulacija | od 22:00 | sve današnje priče iz memorije |
| Razgovor | uvek | istorija dana + današnji članci u kontekstu |

Svaka tema koju javi prvo se pročita CELA (`scraper.py`, requests + BeautifulSoup), pa Gemini piše poruku.
Ako je članak iza paywall-a, koristi se isečak.

## Moduli
`config.py` podešavanja · `memory.py` SQLite · `sources.py` Tavily/RSS/Apify · `scraper.py` duboko čitanje ·
`brain.py` ličnost (`licnost.txt`) + Gemini · `pipeline.py` poslovi i `tick` · `state.py` šifrovanje stanja · `main.py` Telegram + scheduler

## Kvote
- Tavily: 2 upita po pregledu, ~12 pregleda dnevno = ~24 kredita/dan (~720/mesec, besplatno je 1000).
- Gemini: skeniranje zove model samo kad ima novih naslova; ako jedan model vrati 429 prelazi na sledeći.

## Hosting (isto kao Fred: GitHub Actions petlja, javni repo = neograničeni minuti)
`.github/workflows/iris.yml` radi ~5h40min, čuva stanje, pa sam pokrene sledeći ciklus (cron na 6h je rezerva).
Pošto je repo javan, stanje (razgovor, priče) ide šifrovano u `iris.db.enc` (ključ = `STATE_KEY`).
Secrets: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, TAVILY_API_KEY, STATE_KEY, KORISNIK_IME, (APIFY_TOKEN).
VAŽNO: ne pokreći bota lokalno dok radi na Actions - Telegram dozvoljava samo jednu instancu (greška 409).

## Lokalno
```
pip install -r requirements.txt && cp .env.example .env
python3 main.py                  # stalno
python3 main.py --pregled        # jedan posao odmah (test); isto --jutro --skeniraj --kapitulacija
```
