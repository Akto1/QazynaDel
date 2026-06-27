
from __future__ import annotations
from aiohttp import web
import os
import asyncio
import logging
import signal


import bot as bot_module
from api import run_api, build_app
from database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_api(bot):
    try:

        app = build_app(bot)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        await site.start()

        print("DEBUG: API сервер успешно запущен на порту 8080!")
        await asyncio.Event().wait()

    except Exception as e:
        import traceback
        print("--- ОШИБКА В RUN_API ---")
        traceback.print_exc()
        raise e
async def main() -> None:
    await init_db()
    logger.info("Database initialized")

    bot, dp = bot_module.build_bot_and_dispatcher()
    
    await asyncio.gather(
        dp.start_polling(bot),
        run_api(bot)
    )
    async def _polling():
        logger.info("Bot polling started")
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logger.error("Bot polling crashed: %s", e)
        finally:
            logger.info("Bot polling stopped")

    async def _api():
        try:
            await run_api(bot)
        except Exception as e:
            logger.error("API crashed: %s", e)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    bot_task = asyncio.create_task(_polling(), name="bot-polling")
    api_task = asyncio.create_task(_api(), name="api-server")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop-wait")

    # Ждём первого завершения или сигнала. _polling/_api ловят свои исключения,
    # поэтому падение одного из них корректно глушится — а finish самого факта
    # завершения — это сигнал остановить второй.
    done, pending = await asyncio.wait(
        [bot_task, api_task, stop_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if stop_event.is_set():
        logger.info("Stopping all tasks (signal)…")
    else:
        logger.info("One of tasks finished, stopping the other…")

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
