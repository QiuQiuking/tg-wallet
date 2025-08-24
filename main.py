from gevent import monkey
monkey.patch_all()  # 必须在任何导入前调用

import asyncio
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from flask import Flask, request
import os
import threading
from config import *
from db import init_db, add_watch, remove_watch, list_watch, all_watches
from rpc import get_eth_balance_wei, get_block_number, get_block_with_txs, from_wei, to_checksum

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 初始化 Flask 和 bot
app_flask = Flask(__name__)
bot_app = None
bot_initialized = False

# 正则表达式
ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id
    try:
        c = await context.bot.get_chat_member(CHANNEL_ID, uid)
        g = await context.bot.get_chat_member(GROUP_ID, uid)
        return c.status in ["member", "creator", "administrator"] and g.status in ["member", "creator", "administrator"]
    except Exception as e:
        logger.error(f"Membership check failed: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📢 加入频道", url=CHANNEL_URL)],
        [InlineKeyboardButton("👥 加入群组", url=GROUP_URL)],
        [InlineKeyboardButton("✅ 我已加入，点击验证", callback_data="verify")]
    ]
    await update.message.reply_text("欢迎使用 TG Wallet，请先加入频道和群组：", reply_markup=InlineKeyboardMarkup(keyboard))

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if await check_membership(update, context):
        await update.callback_query.edit_message_text("✅ 验证成功！")
    else:
        await update.callback_query.edit_message_text("❌ 请先加入频道或群组。")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update, context):
        return await update.message.reply_text("请先加入频道和群组。")
    if not context.args:
        return await update.message.reply_text("用法: /balance <地址>")
    addr = context.args[0]
    if not ADDR_RE.match(addr):
        return await update.message.reply_text("无效地址。")
    try:
        wei = get_eth_balance_wei(INFURA_HTTP, to_checksum(addr))
        await update.message.reply_text(f"{addr} 余额: {from_wei(wei)} ETH")
    except Exception as e:
        logger.error(f"Balance query failed for {addr}: {e}")
        await update.message.reply_text("查询余额失败，请稍后重试。")

async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update, context):
        return await update.message.reply_text("请先加入频道和群组。")
    if not context.args:
        return await update.message.reply_text("用法: /watch <地址>")
    addr = context.args[0]
    if not ADDR_RE.match(addr):
        return await update.message.reply_text("无效地址。")
    try:
        add_watch(str(update.effective_chat.id), to_checksum(addr))
        await update.message.reply_text(f"已添加监听: {addr}")
    except Exception as e:
        logger.error(f"Watch failed for {addr}: {e}")
        await update.message.reply_text("添加监听失败，请稍后重试。")

async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update, context):
        return await update.message.reply_text("请先加入频道和群组。")
    if not context.args:
        return await update.message.reply_text("用法: /unwatch <地址>")
    addr = context.args[0]
    try:
        remove_watch(str(update.effective_chat.id), to_checksum(addr))
        await update.message.reply_text(f"已取消监听: {addr}")
    except Exception as e:
        logger.error(f"Unwatch failed for {addr}: {e}")
        await update.message.reply_text("取消监听失败，请稍后重试。")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update, context):
        return await update.message.reply_text("请先加入频道和群组。")
    try:
        items = list_watch(str(update.effective_chat.id))
        text = "\n".join(items) or "暂无监听地址"
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"List command failed: {e}")
        await update.message.reply_text("获取监听列表失败，请稍后重试。")

async def watcher(app: Application):
    logger.info("Watcher task started")
    try:
        last_block = get_block_number(INFURA_HTTP)
        logger.info(f"Initial block number: {last_block}")
    except Exception as e:
        logger.error(f"Failed to get initial block number: {e}")
        return
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            latest = get_block_number(INFURA_HTTP)
            logger.info(f"Checking block: {latest}")
            if latest > last_block:
                block = get_block_with_txs(INFURA_HTTP, latest)
                txs = block.get("transactions", [])
                for tx in txs:
                    frm, to = tx.get("from", "").lower(), (tx.get("to") or "").lower()
                    for cid, addrs in all_watches().items():
                        if frm in {a.lower() for a in addrs} or to in {a.lower() for a in addrs}:
                            await app.bot.send_message(cid, f"检测到交易: {tx.get('hash')}")
                last_block = latest
            else:
                logger.debug("No new blocks")
        except Exception as e:
            logger.warning(f"[Watcher] 区块拉取失败: {e}")
            continue

@app_flask.route(f'/{BOT_TOKEN}', methods=['POST'])
async def webhook():
    global bot_app, bot_initialized
    logger.info("Received webhook request")
    if not bot_initialized or bot_app is None:
        logger.error("bot_app not initialized")
        return 'Bot not initialized', 500
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            logger.info(f"Webhook update: {json_string[:100]}...")
            update = Update.de_json(json_string, bot_app.bot)
            if update:
                await bot_app.process_update(update)
                return 'OK', 200
            else:
                logger.warning("Invalid update received")
                return 'Invalid update', 400
        except Exception as e:
            logger.error(f"Webhook processing failed: {e}")
            return 'Webhook error', 500
    logger.warning("Invalid webhook request")
    return 'Invalid request', 403

@app_flask.route('/setwebhook')
async def set_webhook():
    global bot_app, bot_initialized
    logger.info("Setting webhook")
    if not bot_initialized or bot_app is None:
        logger.error("bot_app not initialized")
        return 'Bot not initialized', 500
    try:
        await bot_app.bot.delete_webhook()
        webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'tg-wallet-1-0-1.onrender.com')}/{BOT_TOKEN}"
        success = await bot_app.bot.set_webhook(url=webhook_url)
        if success:
            logger.info(f"Webhook set successfully: {webhook_url}")
            return f"Webhook set successfully: {webhook_url}"
        else:
            logger.error("Failed to set webhook")
            return "Failed to set webhook", 500
    except Exception as e:
        logger.error(f"Webhook setup failed: {e}")
        return f"Webhook setup failed: {e}", 500

@app_flask.route('/')
async def index():
    logger.info("Root endpoint accessed")
    return "TG Wallet Bot is running!"

@app_flask.route('/favicon.ico')
async def favicon():
    logger.info("Favicon requested")
    return '', 204

@app_flask.route('/debug')
async def debug():
    return f"bot_initialized: {bot_initialized}, bot_app: {bot_app is not None}"

async def init_bot():
    global bot_app, bot_initialized
    logger.info("Initializing bot and database")
    try:
        init_db()
        logger.info(f"BOT_TOKEN: {BOT_TOKEN[:10]}...")  # 隐藏部分 Token
        bot_app = Application.builder().token(BOT_TOKEN).build()
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(CallbackQueryHandler(verify_callback, pattern="^verify$"))
        bot_app.add_handler(CommandHandler("balance", balance))
        bot_app.add_handler(CommandHandler("watch", watch))
        bot_app.add_handler(CommandHandler("unwatch", unwatch))
        bot_app.add_handler(CommandHandler("list", list_cmd))
        bot_initialized = True
        logger.info("Bot initialized successfully")
    except Exception as e:
        logger.error(f"Bot initialization failed: {e}")
        bot_initialized = False
        raise

# 手动初始化 bot
try:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_bot())
    if bot_initialized:
        threading.Thread(target=lambda: asyncio.run(watcher(bot_app)), daemon=True).start()
        logger.info("Watcher thread started")
except Exception as e:
    logger.error(f"Application startup failed: {e}")

if __name__ == "__main__":
    logger.info("Starting application in debug mode")
    app_flask.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))