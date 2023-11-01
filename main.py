import datetime
import logging
import tempfile
import time
from warnings import filterwarnings

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.warnings import PTBUserWarning

import config
from utils import (
    Categoria,
    Setting,
    Transazione,
    analyze_transactions,
    current_transaction,
    elenco_transazioni,
    get_categories,
    is_first_word_number,
    load_user_settings,
    make_editing_keyboard,
    plotly_by_cat,
    plotly_by_month,
    plotly_by_month_and_category,
    try_categorize,
)

filterwarnings(action="ignore", message=r".*CallbackQueryHandler", category=PTBUserWarning)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info("User %s started the conversation.", user.first_name)
    user_id = update.effective_user.id
    load_user_settings(context, user_id)

    if not is_first_word_number(update.message.text):
        logger.info("Not a number, ending.")
        return ConversationHandler.END

    testo = update.message.text.split()
    importo, categoria, descrizione = None, None, None
    timestamp = int(time.time())
    data = datetime.date.today()

    if len(testo) >= 2:
        importo, descrizione = testo[0], " ".join(testo[1:])
        categoria = try_categorize(update.effective_user.id, descrizione.lower())
        context.user_data["transazione_corrente"] = {
            "importo": float(importo),
            "categoria": categoria,
            "descrizione": descrizione,
            "timestamp": timestamp,
            "data": data,
        }
    else:
        importo = testo[0]
        context.user_data["transazione_corrente"] = {
            "importo": importo,
            "categoria": None,
            "descrizione": None,
            "timestamp": timestamp,
            "data": data,
        }
    transazione = current_transaction(context)

    reply_markup = make_editing_keyboard()

    # Send message with text and appended InlineKeyboard
    await update.message.reply_html(f"La tua transazione:\n\n{transazione}", reply_markup=reply_markup)
    return "SHOW"


async def show_transazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: show_transazione.")
    query = update.callback_query
    if query:
        await query.answer()

    reply_markup = make_editing_keyboard()
    transazione = current_transaction(context)
    if query:
        await query.edit_message_text(
            text=f"{transazione}\n\nCosa vuoi fare?",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    else:
        await update.message.reply_html(text=f"{transazione}\n\nCosa vuoi fare?", reply_markup=reply_markup)
    return "SHOW"


async def cambia_descrizione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: cambia_descrizione.")
    query = update.callback_query
    await query.answer()

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Indietro", callback_data="back")]])
    transazione = current_transaction(context)
    await query.edit_message_text(
        text=f"{transazione}\n\nInserisci una nuova descrizione:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return "EDIT_DESC"


async def cambia_descrizione_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: cambia_descrizione_actual.")
    nuova_descrizione = update.message.text
    context.user_data["transazione_corrente"]["descrizione"] = nuova_descrizione
    reply_markup = make_editing_keyboard()
    transazione = current_transaction(context)
    await update.message.reply_html(text=f"Descrizione cambiata!\n\n{transazione}", reply_markup=reply_markup)
    return "SHOW"


async def cambia_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: cambia_categoria.")
    query = update.callback_query
    await query.answer()
    user_id = int(update.effective_user.id)

    categorie = get_categories(user_id)  # (cat.name, cat.times_used)
    categorie_inline = [
        InlineKeyboardButton(f"{cat[0]} ({cat[1]})", callback_data=f"cat_{cat[0]}") for cat in categorie
    ]
    categorie_x2 = [categorie_inline[i : i + 2] for i in range(0, len(categorie_inline), 2)]
    categorie_x2.append([InlineKeyboardButton("Nuova categoria", callback_data="menu_categorie_nuovacat")])
    categorie_x2.append([InlineKeyboardButton("🔙 Indietro", callback_data="back")])

    reply_markup = InlineKeyboardMarkup(categorie_x2)

    transazione = current_transaction(context)
    await query.edit_message_text(
        text=f"{transazione}\n\nInserisci una nuova categoria:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return "EDIT_CAT"


async def cambia_categoria_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: cambia_categoria_actual.")
    nuova_categoria = update.message.text
    context.user_data["transazione_corrente"]["categoria"] = nuova_categoria

    reply_markup = make_editing_keyboard()
    transazione = current_transaction(context)
    await update.message.reply_html(text=f"Categoria cambiata!\n\n{transazione}", reply_markup=reply_markup)
    return "SHOW"


async def cambia_categoria_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: cambia_categoria_buttons.")
    query = update.callback_query
    await query.answer()

    nuova_categoria = query.data.split("_")[1]
    context.user_data["transazione_corrente"]["categoria"] = nuova_categoria

    reply_markup = make_editing_keyboard()
    transazione = current_transaction(context)
    await query.edit_message_text(
        text=f"Categoria cambiata!\n\n{transazione}",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return "SHOW"


async def cambia_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: cambia_data.")
    query = update.callback_query
    await query.answer()

    oggi = datetime.datetime.now().strftime("%Y-%m-%d")
    ieri = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    reply_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Oggi", callback_data=f"data_{oggi}"),
                InlineKeyboardButton("Ieri", callback_data=f"data_{ieri}"),
            ],
            [InlineKeyboardButton("📅 Data specifica", callback_data="data_custom")],
            [InlineKeyboardButton("🔙 Indietro", callback_data="back")],
        ]
    )

    transazione = current_transaction(context)
    await query.edit_message_text(
        text=f"{transazione}\n\nSeleziona una nuova data:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return "EDIT_DATA"


async def cambia_data_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: cambia_data_actual.")
    data = datetime.date.fromisoformat(update.message.text)
    context.user_data["transazione_corrente"]["data"] = data

    reply_markup = make_editing_keyboard()
    transazione = current_transaction(context)
    await update.message.reply_html(text=f"Data cambiata!\n\n{transazione}", reply_markup=reply_markup)
    return "SHOW"


async def cambia_data_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: cambia_data_buttons.")
    query = update.callback_query
    await query.answer()

    if query.data == "data_custom":
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Indietro", callback_data="back")]])
        await query.edit_message_text(
            text="Inserisci una data nel formato YYYY-MM-DD:",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return "EDIT_DATA"

    nuova_data_str = query.data.split("_")[1]
    try:
        nuova_data_datetime = datetime.date.strptime(nuova_data_str, "%Y-%m-%d")
        context.user_data["transazione_corrente"]["data"] = nuova_data_datetime
    except ValueError:
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Indietro", callback_data="back")]])
        await query.edit_message_text(
            text="Data non valida, inserisci una data nel formato YYYY-MM-DD:",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return "EDIT_DATA"

    reply_markup = make_editing_keyboard()
    transazione = current_transaction(context)
    await query.edit_message_text(
        text=f"Data cambiata!\n\n{transazione}",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return "SHOW"


async def cambia_importo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: cambia_importo.")
    query = update.callback_query
    await query.answer()

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Indietro", callback_data="back")]])
    transazione = current_transaction(context)
    await query.edit_message_text(
        text=f"{transazione}\n\nInserisci un nuovo importo:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return "EDIT_IMPORTO"


async def cambia_importo_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: cambia_importo_actual.")
    nuovo_importo = update.message.text
    context.user_data["transazione_corrente"]["importo"] = float(nuovo_importo)
    reply_markup = make_editing_keyboard()
    transazione = current_transaction(context)
    await update.message.reply_html(text=f"Importo cambiato!\n\n{transazione}", reply_markup=reply_markup)
    return "SHOW"


async def annulla_transazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: annulla_transazione.")
    query = update.callback_query
    await query.answer()

    context.user_data["transazione_corrente"] = {}

    await query.delete_message()
    return ConversationHandler.END


async def save_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: save_transaction.")
    query = update.callback_query
    await query.answer()

    transazione_str = current_transaction(context)
    transaction = current_transaction(context, return_dict=True)

    datetime_str = datetime.datetime.utcfromtimestamp(transaction["timestamp"]).strftime("%Y-%m-%d")
    user_id = int(update.effective_user.id)
    Transazione.create(
        timestamp=transaction["timestamp"],
        date=datetime_str,
        user_id=user_id,
        importo=transaction["importo"],
        descrizione=transaction["descrizione"],
        categoria=transaction["categoria"],
    )
    logger.info("Transazione creata.")
    dbquery = Categoria.select().where(Categoria.user_id == user_id, Categoria.name == transaction["categoria"])
    if dbquery:
        old_used = dbquery[0].times_used
    else:
        old_used = 0
    Categoria.update(times_used=old_used + 1).where(
        Categoria.user_id == user_id, Categoria.name == transaction["categoria"]
    ).execute()
    logger.info(f'Categoria {transaction["categoria"]} aggiornata.')

    await query.edit_message_text(text=f"Transazione salvata!\n\n{transazione_str}", parse_mode="HTML")
    return ConversationHandler.END


async def menu_categorie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_categorie.")
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📃 Nuova Lista", callback_data="menu_categorie_nuovalista")],
        [InlineKeyboardButton("➕ Nuova Categoria", callback_data="menu_categorie_nuovacat")],
        [
            InlineKeyboardButton("🔙 Indietro", callback_data="goto_menu"),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    user_id = int(update.effective_user.id)
    categorie = get_categories(user_id)  # (cat.name, cat.times_used)
    cats = "\n".join(cat[0] for cat in categorie)
    await query.edit_message_text(text=f"🏷️ CATEGORIE\n\n{cats}", parse_mode="HTML", reply_markup=reply_markup)


async def menu_categorie_nuovalista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_categorie_nuovalista.")
    query = update.callback_query
    await query.answer()
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Indietro", callback_data="back")]])

    await query.message.reply_html(text="Inviami una nuova lista:", reply_markup=reply_markup)
    return "CAT_NEWLIST"


async def menu_categorie_nuovalista_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_categorie_nuovalista_actual.")

    if update.message.text:
        user_id = update.effective_user.id
        new_cat = update.message.text.split("\n")
        new_cat_list = [(cat, 0) for cat in new_cat]
        old_cat_list = get_categories(user_id)

        Categoria.delete().where(Categoria.user_id == user_id).execute()
        for new_cat in new_cat_list:
            if new_cat[0] in [cat[0] for cat in old_cat_list]:
                times_used = [old_cat[1] for old_cat in old_cat_list if old_cat[0] == new_cat[0]][0]
                Categoria.create(user_id=user_id, name=new_cat[0], times_used=times_used)
            else:
                Categoria.create(user_id=user_id, name=new_cat[0], times_used=0)

        new_cats = "\n".join([cat[0] for cat in get_categories(user_id)])
        await update.message.reply_html(text=f"Lista salvata!\n\n{new_cats}")
        await menu(update, context)
        return ConversationHandler.END

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Indietro", callback_data="back")]])
    await update.message.reply_html(text="Inviami una nuova lista:", reply_markup=reply_markup)
    return "CAT_NEWLIST"


async def menu_categorie_nuovacat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_categorie_nuovacat.")
    query = update.callback_query
    await query.answer()
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Indietro", callback_data="back")]])

    await query.message.reply_html(text="Scrivi una nuova categoria:", reply_markup=reply_markup)
    return "CAT_NEW"


async def menu_categorie_nuovacat_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_categorie_nuovacat_actual.")

    if update.message.text:
        user_id = update.effective_user.id
        Categoria.create(user_id=user_id, name=update.message.text, times_used=0)
        new_cats = "\n".join([cat[0] for cat in get_categories(user_id)])
        await update.message.reply_html(text=f"Categoria creata!\n\n{new_cats}")
        if not context.user_data["transazione_corrente"]:
            await menu(update, context)
            return ConversationHandler.END
        else:
            context.user_data["transazione_corrente"]["categoria"] = update.message.text
            await show_transazione(update, context)
            return "SHOW"

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Indietro", callback_data="back")]])
    await update.message.reply_html(text="Scrivi una nuova categoria:", reply_markup=reply_markup)
    return "CAT_NEW"


async def menu_transazioni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_transazioni.")
    query = update.callback_query
    await query.answer()
    current_month = datetime.date.today().strftime("%Y-%m")
    last_month = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y-%m")

    keyboard = [
        [
            InlineKeyboardButton("Mese corrente", callback_data=f"transazioni_{current_month}"),
        ],
        [
            InlineKeyboardButton("Mese scorso", callback_data=f"transazioni_{last_month}"),
        ],
        [
            InlineKeyboardButton("🔙 Indietro", callback_data="back"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="💼 TRANSAZIONI", parse_mode="HTML", reply_markup=reply_markup)
    return "TRANSAZIONI"


async def menu_transazioni_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_transazioni_button.")
    query = update.callback_query
    await query.answer()

    month = query.data.split("_")[1]

    table = elenco_transazioni(context, update.effective_user.id, month)
    if not table:
        await query.edit_message_text(
            text="Non ho trovato niente.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await query.edit_message_text(
        text=f'<pre><code class="text">{table}</code></pre>',
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def menu_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_reports.")
    query = update.callback_query
    await query.answer()
    current_month = datetime.date.today().strftime("%Y-%m")
    last_month = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y-%m")

    keyboard = [
        [
            InlineKeyboardButton("Mese corrente", callback_data=f"reports_{current_month}"),
        ],
        [
            InlineKeyboardButton("Mese scorso", callback_data=f"reports_{last_month}"),
        ],
        [
            InlineKeyboardButton("🔙 Indietro", callback_data="back"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="📊 REPORTS", parse_mode="HTML", reply_markup=reply_markup)
    return "REPORTS"


async def menu_reports_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_reports_button.")
    query = update.callback_query
    await query.answer()

    month = query.data.split("_")[1]

    spending_by_cat, spending_by_month, spending_by_month_by_cat = analyze_transactions(
        month=month, user_id=update.effective_user.id
    )

    if not spending_by_cat or not spending_by_month or not spending_by_month_by_cat:
        await query.edit_message_text(
            text="Non ho trovato niente.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await query.message.delete()

    newmsg = await query.message.reply_text("Sto elaborando i dati, attendi.")

    DO_BYCAT = True
    DO_BYMONTH = False
    DO_BYMONTH_BYCAT = False

    if DO_BYCAT:
        with tempfile.NamedTemporaryFile(suffix=".jpg") as by_cat_photo:
            plotly_by_cat(spending_by_cat, by_cat_photo.name)
            await newmsg.reply_photo(photo=open(by_cat_photo.name, "rb"), quote=False)

    if DO_BYMONTH:
        with tempfile.NamedTemporaryFile(suffix=".jpg") as by_month_photo:
            plotly_by_month(spending_by_month, by_month_photo.name)
            await newmsg.reply_photo(photo=open(by_month_photo.name, "rb"), quote=False)

    if DO_BYMONTH_BYCAT:
        with tempfile.NamedTemporaryFile(suffix=".jpg") as by_month_by_cat_photo:
            plotly_by_month_and_category(spending_by_month_by_cat, by_month_by_cat_photo.name)
            await newmsg.reply_photo(photo=open(by_month_by_cat_photo.name, "rb"), quote=False)

    return ConversationHandler.END


async def menu_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_settings.")
    query = update.callback_query
    await query.answer()

    valuta_corrente = context.user_data.get("valuta")
    if not valuta_corrente:
        context.user_data["valuta"] = "€"
        valuta_corrente = "€"
    keyboard = [
        [InlineKeyboardButton(f"📃 Cambia Valuta ({valuta_corrente})", callback_data="menu_setting_valuta")],
        [
            InlineKeyboardButton("🔙 Indietro", callback_data="goto_menu"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="⚙️ SETTINGS", parse_mode="HTML", reply_markup=reply_markup)


async def menu_setting_valuta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_setting_valuta.")
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("€", callback_data="valuta_€"), InlineKeyboardButton("EUR", callback_data="valuta_EUR")],
        [InlineKeyboardButton("$", callback_data="valuta_$"), InlineKeyboardButton("USD", callback_data="valuta_USD")],
        [
            InlineKeyboardButton("❌", callback_data="valuta_none"),
        ],
        [InlineKeyboardButton("🔙 Indietro", callback_data="back")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    valuta_corrente = context.user_data.get("valuta")
    if not valuta_corrente:
        context.user_data["valuta"] = "€"
        valuta_corrente = "€"

    await query.edit_message_text(
        text=f"Valuta corrente: {valuta_corrente}",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return "SET_VALUTA"


async def menu_setting_valuta_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Conversation handler: menu_setting_valuta_buttons.")
    query = update.callback_query
    await query.answer()

    nuova_valuta = query.data.split("_")[1]
    if nuova_valuta == "none":
        nuova_valuta = None

    context.user_data["valuta"] = nuova_valuta
    Setting.replace(user_id=update.effective_user.id, setting1=nuova_valuta).execute()
    await menu_settings(update, context)
    return ConversationHandler.END


async def menu_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Conversation handler: menu_help.")
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    messaggio_list = [
        "Ciao! Questo bot ti permette di salvare le tue transazioni e di tenerne traccia.",
        "Per salvare una transazione, invia un messaggio con il seguente formato:",
        "<code>importo descrizione</code>",
        "",
        "Ad esempio:",
        "<code>12 Kebab da ciccio</code>",
        "",
        "Se la descrizione è simile a qualcosa che hai già inserito prima, verrà automaticamente selezionata la categoria corrispondente.",
        "Altrimenti, puoi usare i bottoni per selezionare una categoria esistente, crearne una nuova, cambiare l'importo, la descrizione e la data.",
        "",
        "Per vedere gli altri comandi, usa /menu",
        "Ciao!",
    ]
    messaggio = "\n".join(messaggio_list)
    await update.effective_chat.send_message(messaggio, parse_mode="HTML")


async def goto_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Conversation handler: goto_menu.")
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    await menu(update, context)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Conversation handler: menu.")
    user_id = update.effective_user.id
    load_user_settings(context, user_id)
    keyboard = [
        [
            InlineKeyboardButton("❓ Help", callback_data="goto_help"),
            InlineKeyboardButton("🏷️ Categorie", callback_data="goto_categories"),
        ],
        [
            InlineKeyboardButton("💼 Transazioni", callback_data="goto_transactions"),
            InlineKeyboardButton("📊 Reports", callback_data="goto_reports"),
        ],
        [
            InlineKeyboardButton("⚙️ Impostazioni", callback_data="goto_settings"),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_chat.send_message("Cosa vuoi fare?", reply_markup=reply_markup)
    return


async def post_init(app: Application) -> None:
    logger.info("Conversation handler: post_init.")
    Transazione.create_table()
    Categoria.create_table()
    Setting.create_table()


def main() -> None:
    builder = ApplicationBuilder()
    builder.token(config.TOKEN)
    builder.post_init(post_init)

    application = builder.build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("menu", menu),
            CommandHandler("start", menu),
            MessageHandler(~filters.UpdateType.EDITED & filters.TEXT, start),
            CallbackQueryHandler(goto_menu, pattern="^goto_menu$"),
            CallbackQueryHandler(menu_help, pattern="^goto_help$"),
            CallbackQueryHandler(menu_categorie, pattern="^goto_categories$"),
            CallbackQueryHandler(menu_categorie_nuovalista, pattern="^menu_categorie_nuovalista$"),
            CallbackQueryHandler(menu_categorie_nuovacat, pattern="^menu_categorie_nuovacat$"),
            CallbackQueryHandler(menu_transazioni, pattern="^goto_transactions$"),
            CallbackQueryHandler(menu_reports, pattern="^goto_reports$"),
            CallbackQueryHandler(menu_settings, pattern="^goto_settings$"),
            CallbackQueryHandler(menu_setting_valuta, pattern="^menu_setting_valuta$"),
        ],
        states={
            "SHOW": [
                CallbackQueryHandler(cambia_data, pattern="^cambia_categoria$"),
                CallbackQueryHandler(cambia_categoria, pattern="^cambia_data$"),
                CallbackQueryHandler(cambia_descrizione, pattern="^cambia_descrizione$"),
                CallbackQueryHandler(cambia_importo, pattern="^cambia_importo$"),
                CallbackQueryHandler(save_transaction, pattern="^salva_transazione$"),
                CallbackQueryHandler(annulla_transazione, pattern="^annulla_transazione$"),
            ],
            "EDIT_DESC": [
                MessageHandler(~filters.UpdateType.EDITED & filters.TEXT, cambia_descrizione_actual),
                CallbackQueryHandler(show_transazione, pattern="^back$"),
            ],
            "EDIT_CAT": [
                MessageHandler(~filters.UpdateType.EDITED & filters.TEXT, cambia_categoria_actual),
                CallbackQueryHandler(menu_categorie_nuovacat, pattern="^menu_categorie_nuovacat$"),
                CallbackQueryHandler(cambia_categoria_buttons, pattern="^cat_"),
                CallbackQueryHandler(show_transazione, pattern="^back$"),
            ],
            "EDIT_DATA": [
                MessageHandler(~filters.UpdateType.EDITED & filters.TEXT, cambia_data_actual),
                CallbackQueryHandler(cambia_data_buttons, pattern="^data_"),
                CallbackQueryHandler(show_transazione, pattern="^back$"),
            ],
            "EDIT_IMPORTO": [
                MessageHandler(~filters.UpdateType.EDITED & filters.TEXT, cambia_importo_actual),
                CallbackQueryHandler(show_transazione, pattern="^back$"),
            ],
            "CAT_NEWLIST": [
                MessageHandler(~filters.UpdateType.EDITED & filters.TEXT, menu_categorie_nuovalista_actual),
                CallbackQueryHandler(goto_menu, pattern="^back$"),
            ],
            "CAT_NEW": [
                MessageHandler(~filters.UpdateType.EDITED & filters.TEXT, menu_categorie_nuovacat_actual),
                CallbackQueryHandler(goto_menu, pattern="^back$"),
            ],
            "SET_VALUTA": [
                CallbackQueryHandler(menu_setting_valuta_buttons, pattern="^valuta_"),
                CallbackQueryHandler(goto_menu, pattern="^back$"),
            ],
            "TRANSAZIONI": [
                CallbackQueryHandler(menu_transazioni_button, pattern="^transazioni_"),
                CallbackQueryHandler(goto_menu, pattern="^back$"),
            ],
            "REPORTS": [
                CallbackQueryHandler(menu_reports_button, pattern="^reports_"),
                CallbackQueryHandler(goto_menu, pattern="^back$"),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(conv_handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
