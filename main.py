from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackContext, ContextTypes, CallbackQueryHandler
from telegram.update import Update
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
import requests
import re
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, MetaData, delete
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import utc
import os
import logging
import traceback
import html
import json
from telegram import ParseMode

bot_token = os.environ['API_KEY']
engine = create_engine(
    "postgresql://postgres:FZhUGGddoZb4R1NydutM@containers-us-west-42.railway.app:5809/railway")
metadata_obj = MetaData(bind=engine)
MetaData.reflect(metadata_obj)
prices = metadata_obj.tables["track-prices"]
amazonRegex = "^https://www.amazon.in"
flipKartRegex = "^https://www.flipkart.com"
HEADERS = ({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 Safari/537.36',
           'Accept-Language': 'en-US, en;q=0.5'})
bot = Bot(token=bot_token)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DEVELOPER_CHAT_ID = 846380174


def error_handler(update: Update, context):
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error(msg="Exception while handling an update:",
                 exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(
        None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
        "</pre>\n\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    # Finally, send the message
    context.bot.send_message(
        chat_id=DEVELOPER_CHAT_ID, text=message, parse_mode=ParseMode.HTML
    )


def check_in_db(chat_id, product_link):
    with Session(engine) as session:
        q = session.query(prices).filter(prices.c.chat_id == chat_id).filter(
            prices.c.product_link == product_link)
        return session.query(q.exists()).scalar()


def check_valid_data(chat_id, message_id):
    with Session(engine) as session:
        q = session.query(prices).filter(prices.c.chat_id == chat_id).filter(
            prices.c.message_id == message_id)
        return session.query(q.exists()).scalar()


def insertInDb(user_name, chat_id, product_name, product_link, product_price, lowest_price, message_id, availability=False):
    with Session(engine) as session:
        insert_stmnt = prices.insert().values(user_name=user_name,
                                              chat_id=chat_id,
                                              product_name=product_name,
                                              product_link=product_link,
                                              product_price=product_price,
                                              lowest_price=lowest_price,
                                              availability=availability,
                                              message_id=message_id)
        session.execute(insert_stmnt)

        session.commit()


def deleteFromDb(chat_id, message_id):
    with Session(engine) as session:
        delete_stmt = delete(prices).where(prices.c.chat_id == chat_id).where(
            prices.c.message_id == message_id)
        session.execute(delete_stmt)

        session.commit()


def updateInDb(chat_id, product_link, product_price, lowest_price):
    with Session(engine) as session:
        update_stmt = prices.update().where(prices.c.chat_id == chat_id).where(prices.c.product_link ==
                                                                               product_link).values(product_price=product_price, lowest_price=lowest_price)
        session.execute(update_stmt)
        print("🤔")

        session.commit()


def check_price_drop():
    items = []
    with Session(engine) as session:
        select_stmnt = prices.select()
        for row in session.execute(select_stmnt):
            items.append(row)
    for item in items:
        current_price, title, availability = get_price(item.product_link)
        if availability == False:
            return
        if current_price < item.lowest_price:
            print("😚")
            lowest_price = current_price
            keyboard = [[InlineKeyboardButton(
                "Product Page", url=item.product_link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            bot.send_message(
                item.chat_id, f'Price for {title} has dropped to ₹ {current_price}.\nClick /stop_{item.message_id} to stop alerts for this product', reply_markup=reply_markup)
            updateInDb(item.chat_id, item.product_link,
                       current_price, lowest_price)
        else:
            print("😔")


def alert():
    check_price_drop()
    print("alert")


def isValidLink(link):
    response = requests.get(link, headers=HEADERS, allow_redirects=True)
    # create the soup object
    soup = BeautifulSoup(response.content, 'lxml')
    soup.encode('utf-8')
    valid = soup.find(id='imgTagWrapperId')
    isValid = True
    if valid is None:
        isValid = False
    return isValid


def get_price(link):
    '''
        This function returns title and price of any given product
    '''
    response = requests.get(link, headers=HEADERS, allow_redirects=True)
    # create the soup object
    soup = BeautifulSoup(response.content, 'lxml')
    soup.encode('utf-8')
    title = soup.find("span", {"id": "productTitle"}).get_text().strip()
    price = soup.find_all("span", {"class": "a-price-whole"})[0].get_text().replace(
        ',', '').replace('₹', '').replace(' ', '').replace('.', '').strip()
    converted_price = int(price)
    avail = soup.find(id="availability")
    available = True
    for child in avail.children:
        if child.name == "span":
            if child.get_text().strip() == "Currently unavailable.":
                available = False
    return converted_price, title, available


def onMsgReceived(update: Update, context: CallbackContext):
    if update.message.text:
        msg = update.message.text
        # check if message starts with stop
        if msg.startswith("/stop_"):
            msg_id = msg.split("_")[1]
            if check_valid_data(update.message.chat_id, int(msg_id)):
                deleteFromDb(update.message.chat_id, int(msg_id))
                reply = "👍 You will no longer receive alerts for this product."
                context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=reply,
                )
            else:
                reply = "🤔 It seems that you don't have any valid product for this command."
                context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=reply,
                )
            return
        user_name = update.message.from_user.username or update.message.from_user.first_name
        chat_id = update.message.chat_id
        message_id = update.message.message_id
        msg_id = context.bot.send_message(
            chat_id, "Looking for a valid Amazon link in your message 🔍").message_id
        if re.search("(?P<url>https?://[^\s]+)", msg) is None:
            reply = "It seems that you haven't sent a valid product link. Please try again with a valid link😅."
            context.bot.edit_message_text(
                chat_id=update.message.chat_id,
                text=reply,
                message_id=msg_id,
            )
            return
        link = re.search("(?P<url>https?://[^\s]+)", msg).group("url")
        if isValidLink(link):
            current_price, title, available = get_price(link)
            context.bot.edit_message_text(
                chat_id=update.message.chat_id,
                text="Valid link found👍.Checking product's price😁",
                message_id=msg_id,
            )
            if not available:
                reply = f'Hi {user_name}! {title} is currently unavailable😓. Try again later.'
                context.bot.edit_message_text(
                    chat_id=update.message.chat_id,
                    text=reply,
                    message_id=msg_id,
                )
                return
            if check_in_db(chat_id, link):
                reply = f'Hi {user_name}! You are already tracking {title} 😅.'
                context.bot.edit_message_text(
                    chat_id=update.message.chat_id,
                    message_id=msg_id,
                    text=reply,
                )
                return

            insertInDb(user_name=user_name, chat_id=chat_id, product_link=link, product_name=title,
                       product_price=current_price, lowest_price=current_price, message_id=message_id, availability=available)
            reply = f'Hi {user_name}! {title} is currently available at ₹ {current_price}. I will send you a message when the price drops😉.'
            context.bot.edit_message_text(
                chat_id=update.message.chat_id,
                message_id=msg_id,
                text=reply,
            )
        else:
            context.bot.send_message(
                update.message.chat_id,
                "I'm sorry 😓.As of now I can only track prices on Amazon. Please send a valid Amazon product link.Support for other sites coming soon.",
                # To preserve the markdown, we attach entities (bold, italic...)
                entities=update.message.entities
            )
    else:
        context.bot.send_message(
            update.message.chat_id,
            "I'm sorry.As of now I can only track prices on Amazon. Please send a valid Amazon product link.Support for other sites coming soon.",
            # To preserve the markdown, we attach entities (bold, italic...)
            entities=update.message.entities
        )


def start(update: Update, context: CallbackContext):
    context.bot.send_message(
        update.message.chat_id,
        "Hi! I can send you alerts when the price of a product drops. Just send me the Amazon link of the product you want to track and I will do the rest. I will send you a message when the price drops. Support for flipkart and other sites coming soon.",
        # To preserve the markdown, we attach entities (bold, italic...)
        entities=update.message.entities
    )


def help(update: Update, context: CallbackContext):
    context.bot.send_message(
        update.message.chat_id,
        "Hi! I can help you track the price of any product on Amazon. Just send me the Amazon link of the product you want to track and I will do the rest. I will send you a message when the price drops. Support for flipkart and other sites coming soon. Following are some commands which you can use:\n\n/start - Start the bot\n/help - Get help",
    )

def main():
    updater = Updater(bot=bot)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('help', help))
    dp.add_handler(MessageHandler(None, onMsgReceived))
    dp.add_error_handler(error_handler)
    updater.start_polling()
    scheduler = BackgroundScheduler(timezone=utc)
    scheduler.add_job(alert, 'interval', hours=3)
    scheduler.start()
    updater.idle()


if __name__ == '__main__':
    main()
