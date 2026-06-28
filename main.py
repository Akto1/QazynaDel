from __future__ import annotations

from aiohttp import web

import os

import asyncio

import logging

import signal


import bot as bot_module

from api import build_app

from database import init_db


logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",

)

logger = logging.getLogger(__name__)



async def _polling(bot, dp):

    """Запуск polling бота. Ошибки тут НЕ должны ронять API."""

    logger.info("Bot polling started")

    try:

        await dp.start_polling(bot)

    except asyncio.CancelledError:

        raise

    except Exception as e:

        logger.exception("Bot polling crashed: %s", e)

    finally:

        logger.info("Bot polling stopped")



async def _api(bot):

    """Запуск HTTP API + Mini App на порту $PORT (или 8080)."""

    port = int(os.getenv("PORT", "8080"))

    # Пробуем забиндить порт, иначе Amvera не сможет ничего отдать

    app = build_app(bot)

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)

    try:

        await site.start()

    except OSError as e:

        logger.error("Failed to bind port %s: %s", port, e)

        raise

    logger.info("API + Mini App started at http://0.0.0.0:%s", port)

    # держим корутину живой

    try:

        while True:

            await asyncio.sleep(3600)

    except asyncio.CancelledError:

        logger.info("API task cancelled, cleaning up")

        await runner.cleanup()



async def main() -> None:

    await init_db()

    logger.info("Database initialized")


    bot, dp = bot_module.build_bot_and_dispatcher()


    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()


    def _signal_handler():

        logger.info("Shutdown signal received")

        stop_event.set()


    # Graceful shutdown на SIGTERM/SIGINT (Amvera шлёт SIGTERM)

    for sig in (signal.SIGTERM, signal.SIGINT):

        try:

            loop.add_signal_handler(sig, _signal_handler)

        except NotImplementedError:

            # Windows / некоторые среды не поддерживают add_signal_handler

            pass


    bot_task = asyncio.create_task(_polling(bot, dp), name="bot-polling")

    api_task = asyncio.create_task(_api(bot), name="api-server")

    stop_task = asyncio.create_task(stop_event.wait(), name="stop-wait")


    logger.info("All tasks started, awaiting first completion…")


    # Ждём первого завершения или сигнала

    done, pending = await asyncio.wait(

        [bot_task, api_task, stop_task],

        return_when=asyncio.FIRST_COMPLETED,

    )


    # Если упала одна из задач — логируем

    for t in done:

        if t is stop_task:

            continue

        if t.cancelled():

            logger.warning("%s cancelled", t.get_name())

        elif t.exception():

            logger.error("%s crashed: %s", t.get_name(), t.exception())

        else:

            logger.info("%s finished normally", t.get_name())


    if stop_event.is_set():

        logger.info("Stopping all tasks (signal)…")

    else:

        logger.info("One of tasks finished, stopping the others…")


    for t in pending:

        t.cancel()

    for t in pending:

        try:

            await t

        except (asyncio.CancelledError, Exception):

            pass


    try:

        await bot.session.close()

    except Exception:

        pass

    logger.info("Shutdown complete")



if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info("Interrupted by user")
