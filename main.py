import asyncio
import logging
import sys

# Critical fix for Windows: prevent aiohttp from attempting to use incompatible aiodns on Windows
if sys.platform == "win32":
    sys.modules["aiodns"] = None
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from database.connection import DatabaseManager
from database.repositories.folder_repo import FolderRepository
from services.expiry_service import ExpiryService
from handlers import (
    user_start_router,
    payments_router,
    join_request_router,
    admin_menu_router,
    folder_crud_router,
    broadcast_router
)

import time
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Configure rich logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("CourseSellBot")

# ==========================================
# FastAPI Web App (Render Port Binding & Health Check)
# ==========================================
web_app = FastAPI(title="CourseSellBot Service", docs_url=None, redoc_url=None)


@web_app.api_route("/", methods=["GET", "HEAD"])
@web_app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    return JSONResponse({
        "status": "healthy",
        "service": "CourseSellBot",
        "timestamp": time.time()
    })


async def run_web_server():
    """Run uvicorn server for Render port binding & healthcheck."""
    config = uvicorn.Config(
        app=web_app,
        host=settings.WEB_HOST,
        port=settings.PORT,
        log_level="warning",
        access_log=False
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    except asyncio.CancelledError:
        pass


async def seed_starter_demo_data_if_empty():
    """Seeds sample courses matching the user's provided catalog if DB is empty."""
    try:
        existing = await FolderRepository.get_all_folders()
        if not existing:
            logger.info("Database is fresh. Seeding starter demo courses matching screenshots...")
            # 1. Hotstar 4K
            await FolderRepository.create_folder(
                title="Jio hotstar ad-free 4kplan",
                button_text="💥 Jio hotstar ad-free 4kplan ₹29",
                description=(
                    "Full 4K Ultra HD Ad-free streaming access.\n"
                    "• All Live Sports, IPL, Movies & Hotstar Specials\n"
                    "• Multi-device support with 4K resolution\n"
                    "• Instant automated activation"
                ),
                target_chat_id=-1000000000000,
                row_width=1,
                plans=[
                    {"plan_id": "7d", "label": "7 Days", "days": 7, "price_inr": 29, "stars": 25, "price_usd": 0.50},
                    {"plan_id": "1m", "label": "1 Month", "days": 30, "price_inr": 69, "stars": 55, "price_usd": 1.20},
                    {"plan_id": "1y", "label": "1 Year", "days": 365, "price_inr": 199, "stars": 150, "price_usd": 3.99}
                ]
            )

            # 2. Prime Video
            await FolderRepository.create_folder(
                title="Prime Video VIP",
                button_text="📺 Prime Video",
                description=(
                    "Amazon Prime Video VIP access.\n"
                    "• Full HD and 4K UHD streaming\n"
                    "• Access to international and regional blockbuster library\n"
                    "• Uninterrupted private streaming"
                ),
                target_chat_id=-1000000000000,
                row_width=2,
                plans=[
                    {"plan_id": "7d", "label": "7 Days", "days": 7, "price_inr": 29, "stars": 25, "price_usd": 0.50},
                    {"plan_id": "1m", "label": "1 Month", "days": 30, "price_inr": 79, "stars": 60, "price_usd": 1.40}
                ]
            )

            # 3. YouTube Premium
            await FolderRepository.create_folder(
                title="YouTube Premium",
                button_text="▶️ Youtube Premium ₹45",
                description=(
                    "Ad-free YouTube & YouTube Music background play.\n"
                    "• Zero advertisements on all devices\n"
                    "• Background playback & offline downloads"
                ),
                target_chat_id=-1000000000000,
                row_width=2,
                plans=[
                    {"plan_id": "1m", "label": "1 Month", "days": 30, "price_inr": 45, "stars": 35, "price_usd": 0.80},
                    {"plan_id": "3m", "label": "3 Month", "days": 90, "price_inr": 119, "stars": 90, "price_usd": 2.00}
                ]
            )

            # 4. Spotify
            await FolderRepository.create_folder(
                title="Spotify Premium",
                button_text="🟢 Spotify ₹45",
                description=(
                    "High quality lossless music streaming.\n"
                    "• Ad-free listening\n"
                    "• Offline downloads on your mobile device"
                ),
                target_chat_id=-1000000000000,
                row_width=2,
                plans=[
                    {"plan_id": "1m", "label": "1 Month", "days": 30, "price_inr": 45, "stars": 35, "price_usd": 0.80},
                    {"plan_id": "3m", "label": "3 Month", "days": 90, "price_inr": 119, "stars": 90, "price_usd": 2.00}
                ]
            )
            logger.info("Demo courses seeded successfully.")
    except Exception as e:
        logger.warning(f"Could not seed demo courses: {e}")


async def main():
    logger.info("Initializing Course & Subscription Selling Bot...")

    if not settings.BOT_TOKEN:
        logger.error(
            "❌ BOT_TOKEN is empty! Please set BOT_TOKEN in d:\\python\\Telegrambots\\CourseSellBot\\.env"
        )
        sys.exit(1)

    # 1. Connect MongoDB
    await DatabaseManager.connect()

    # 2. Seed starter demo courses if database is empty
    await seed_starter_demo_data_if_empty()

    # 3. Initialize Telegram Bot & Dispatcher (with Windows safe resolver)
    bot_session = None
    if sys.platform == "win32":
        try:
            from aiohttp import TCPConnector, ThreadedResolver
            from aiogram.client.session.aiohttp import AiohttpSession
            bot_session = AiohttpSession(
                connector_type=TCPConnector,
                connector_init={"resolver": ThreadedResolver()}
            )
        except Exception as e:
            logger.warning(f"Could not initialize custom ThreadedResolver session: {e}")

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=bot_session
    )
    dp = Dispatcher(storage=MemoryStorage())

    # 4. Register Routers in order
    dp.include_router(admin_menu_router)
    dp.include_router(folder_crud_router)
    dp.include_router(broadcast_router)
    dp.include_router(join_request_router)
    dp.include_router(payments_router)
    dp.include_router(user_start_router)

    # 5. Start background Expiry & Reminder Service
    asyncio.create_task(
        ExpiryService.start(bot=bot, check_interval_seconds=settings.EXPIRY_CHECK_INTERVAL)
    )

    # 6. Delete webhook & begin polling
    bot_info = await bot.get_me()
    logger.info(f"🚀 Bot started successfully as @{bot_info.username} (ID: {bot_info.id})")
    await bot.delete_webhook(drop_pending_updates=True)

    # 7. Start Web Server for Render Health Check
    web_server_task = asyncio.create_task(run_web_server())
    logger.info(f"🌐 Web server listening on {settings.WEB_HOST}:{settings.PORT} for Render healthcheck")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        web_server_task.cancel()
        ExpiryService.stop()
        await bot.session.close()


if __name__ == "__main__":
    # Fix for Windows aiodns issue: use WindowsSelectorEventLoopPolicy
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    if not settings.BOT_TOKEN:
        print("❌ BOT_TOKEN is empty! Please set BOT_TOKEN in d:\\python\\Telegrambots\\CourseSellBot\\.env")
        sys.exit(1)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
