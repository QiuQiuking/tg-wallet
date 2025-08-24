# main.py
import asyncio
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from flask import Flask, request
from config import *
from db import init_db, add_watch, remove_watch, list_watch, all_watches
from rpc import get_eth_balance_wei, get_block_number, get_block_with_txs, from_wei, to_checksum
import os

logging.basicConfig(level=logging.INFO)
ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

# 初始化 Flask
app_flask = Flask(__name__)
bot_app = None  # 全局 Application 对象

async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id
    try:
        c = await context.bot.get_chat_member(CHANNEL_ID, uid)
        g = await context.bot.get_chat_member(GROUP_ID, uid)
        return c.status in ["member", "creator", "administrator"] and g.status in ["member", "creator", "administrator"]
    except:
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
    wei = get_eth_balance_wei(INFURA_HTTP, to_checksum(addr))
    await update.message.reply_text(f"{addr} 余额: {from_wei(wei)} ETH")

async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update, context):
        return await update.message.reply_text("请先加入频道和群组。")
    if not context.args:
        return await update.message.reply_text("用法: /watch <地址>")
    addr = context.args[0]
    if not ADDR_RE.match(addr):
        return await update.message.reply_text("无效地址。")
    add_watch(str(update.effective_chat.id), to_checksum(addr))
    await update.message.reply_text(f"已添加监听: {addr}")

async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update, context):
        return await update.message.reply_text("请先加入频道和群组。")
    if not context.args:
        return await update.message.reply_text("用法: /unwatch <地址>")
    addr = context.args[0]
    remove_watch(str(update.effective_chat.id), to_checksum(addr))
    await update.message.reply_text(f"已取消监听: {addr}")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update, context):
        return await update.message.reply_text("请先加入频道和群组。")
    items = list_watch(str(update.effective_chat.id))
    text = "\n".join(items) or "暂无监听地址"
    await update.message.reply_text(text)

async def watcher(app: Application):
    last_block = get_block_number(INFURA_HTTP)
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            latest = get_block_number(INFURA_HTTP)
        except Exception as e:
            logging.warning(f"[Watcher] 区块拉取失败: {e}")
            continue
        if latest > last_block:
            block = get_block_with_txs(INFURA_HTTP, latest)
            txs = block.get("transactions", [])
            for tx in txs:
                frm, to = tx.get("from", "").lower(), (tx.get("to") or "").lower()
                for cid, addrs in all_watches().items():
                    if frm in {a.lower() for a in addrs} or to in {a.lower() for a in addrs}:
                        await app.bot.send_message(cid, f"检测到交易: {tx.get('hash')}")
            last_block = latest

# Flask 路由处理 webhook
@app_flask.route(f'/{BOT_TOKEN}', methods=['POST'])
async def webhook():
    global bot_app
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = Update.de_json(json_string, bot_app.bot)
        await bot_app.process_update(update)
        return 'OK', 200
    return 'Invalid request', 403

@app_flask.route('/setwebhook')
async def set_webhook():
    global bot_app
    bot_app.bot.remove_webhook()
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{BOT_TOKEN}"
    success = await bot_app.bot.set_webhook(url=webhook_url)
    if success:
        return f"Webhook set successfully: {webhook_url}"
    else:
        return "Failed to set webhook"

@app_flask.route('/')
async def index():
    return "TG Wallet Bot is running!"

async def run_bot():
    global bot_app
    init_db()
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(verify_callback, pattern="^verify$"))
    bot_app.add_handler(CommandHandler("balance", balance))
    bot_app.add_handler(CommandHandler("watch", watch))
    bot_app.add_handler(CommandHandler("unwatch", unwatch))
    bot_app.add_handler(CommandHandler("list", list_cmd))
    await asyncio.gather(watcher(bot_app))

def run_flask():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())
    app_flask.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))

if __name__ == "__main__":
    run_flask()
