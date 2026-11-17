"""
Iris - sarkastična asistentkinja za vesti (Telegram + Gemini + Tavily + RSS + Apify).

  python3 main.py            radi stalno (lokalno / server)
  python3 main.py --sati 5.6 radi N sati pa završi (GitHub Actions ga posle sam ponovo pokrene)
  python3 main.py --pregled | --jutro | --skeniraj | --kapitulacija    jedan posao odmah, pa kraj (test)

Komande na Telegramu: /start, /now (pregled odmah), /kapitulacija, /reset (briše današnji razgovor)
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from iris import brain, config, memory, pipeline
from iris.telegram_util import delovi

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("iris")


def moj_chat(update: Update) -> bool:
    return bool(update.effective_chat) and str(update.effective_chat.id) == config.TELEGRAM_CHAT_ID


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if not config.TELEGRAM_CHAT_ID:
        await update.message.reply_text(
            f"Tvoj chat id je {cid}. Upiši ga u .env kao TELEGRAM_CHAT_ID pa me restartuj. "
            "Dotle ti ne šaljem ništa, da se ne bih obraćala pogrešnim ljudima."
        )
    elif moj_chat(update):
        await update.message.reply_text(
            "Tu sam. Jutarnji pregled u 07:00, pregled sveta na oko sat i po, hitne vesti čim se desi nešto veliko, a u 22:00 kapitulacija. "
            "/now - pregled odmah, /kapitulacija - rezime odmah, /reset - brišem današnji razgovor."
        )


async def cmd_now(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not moj_chat(update):
        return
    await update.message.reply_text("Dobro, dobro, kopam po internetu...")
    await _bezbedno(ctx.application, pipeline.sa_lockom(pipeline.pregled, ctx.application, True))


async def cmd_kapitulacija(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not moj_chat(update):
        return
    await _bezbedno(ctx.application, pipeline.sa_lockom(pipeline.kapitulacija, ctx.application))


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not moj_chat(update):
        return
    memory.clear_today()
    await update.message.reply_text("Obrisano. Današnji razgovor nikad nije ni postojao.")


async def poruka(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not moj_chat(update) or not update.message or not update.message.text:
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    memory.add_message("user", update.message.text)
    try:
        odgovor = await brain.odgovori(memory.today_messages(), memory.today_stories(config.MAX_CONTEXT_STORIES))
    except Exception:
        log.exception("Razgovor pao")
        await update.message.reply_text("Nešto je pukao na mojoj strani. Pokušaj ponovo za minut.")
        return
    memory.add_message("assistant", odgovor)
    for deo in delovi(odgovor):
        await update.message.reply_text(deo, disable_web_page_preview=True)


async def _bezbedno(app: Application, koroutina):
    """Ručno pokrenut posao nikad ne sme da obori bota."""
    try:
        await koroutina
    except Exception:
        log.exception("Posao pao")
        try:
            await app.bot.send_message(config.TELEGRAM_CHAT_ID, "Pukla mi je pretraga. Probaj ponovo za koji minut.")
        except Exception:
            pass


async def stani(app: Application):
    log.info("Vreme je isteklo, završavam ciklus (Actions pokreće sledeći).")
    app.stop_running()


def pokreni_scheduler(app: Application, sati: float | None):
    sch = AsyncIOScheduler(timezone=config.TZ)
    sch.add_job(pipeline.tick, IntervalTrigger(minutes=5), args=[app], id="tick", coalesce=True, max_instances=1,
                next_run_time=datetime.now(config.TZ) + timedelta(seconds=15))
    if sati:
        sch.add_job(stani, DateTrigger(run_date=datetime.now(config.TZ) + timedelta(hours=sati)), args=[app])
    sch.start()
    app.bot_data["scheduler"] = sch
    log.info("Iris radi. Skeniranje na %d min, pregled na %d min, jutro %d:00, kapitulacija %d:00.%s",
             config.SCAN_MIN, config.DIGEST_MIN, config.MORNING_HOUR, config.DIGEST_HOUR,
             f" Radim još {sati} h." if sati else "")


async def post_shutdown(app: Application):
    sch = app.bot_data.get("scheduler")
    if sch:
        sch.shutdown(wait=False)


def build_app(sati: float | None = None) -> Application:
    async def post_init(app: Application):
        memory.init()
        pokreni_scheduler(app, sati)

    app = Application.builder().token(config.TELEGRAM_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("now", cmd_now))
    app.add_handler(CommandHandler("kapitulacija", cmd_kapitulacija))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, poruka))
    return app


JEDNOKRATNO = {"--pregled": lambda a: pipeline.pregled(a, True), "--jutro": pipeline.jutro,
               "--skeniraj": pipeline.skeniraj, "--kapitulacija": pipeline.kapitulacija}


async def jednokratno(posao):
    memory.init()
    app = build_app()
    async with app:
        await posao(app)


def main():
    config.proveri()
    for flag, posao in JEDNOKRATNO.items():
        if flag in sys.argv:
            if not config.TELEGRAM_CHAT_ID:
                raise SystemExit("Za test režim treba TELEGRAM_CHAT_ID u .env")
            asyncio.run(jednokratno(posao))
            return
    sati = float(sys.argv[sys.argv.index("--sati") + 1]) if "--sati" in sys.argv else None
    build_app(sati).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
