import datetime
import logging

import pandas as pd
import peewee
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import rapidfuzz
from plotly.subplots import make_subplots
from prettytable import PrettyTable
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config

DBPATH = "db/sqlite.db"
db = peewee.SqliteDatabase(DBPATH)


class Transazione(peewee.Model):
    timestamp = peewee.IntegerField()
    date = peewee.DateField()
    user_id = peewee.IntegerField()
    importo = peewee.IntegerField()
    descrizione = peewee.TextField(null=True)
    categoria = peewee.TextField(null=True)

    class Meta:
        database = db
        table_name = "transazioni"
        primary_key = peewee.CompositeKey("user_id", "timestamp", "importo")


class Categoria(peewee.Model):
    user_id = peewee.IntegerField()
    name = peewee.TextField()
    parent = peewee.TextField(null=True)
    times_used = peewee.IntegerField(default=0)

    class Meta:
        database = db
        table_name = "categorie"
        primary_key = peewee.CompositeKey("user_id", "name")


class Setting(peewee.Model):
    user_id = peewee.IntegerField()
    setting1 = peewee.TextField(null=True)  # Valuta
    setting2 = peewee.TextField(null=True)  # TBD
    setting3 = peewee.TextField(null=True)  # TBD
    setting4 = peewee.TextField(null=True)  # TBD
    setting5 = peewee.TextField(null=True)  # TBD

    class Meta:
        database = db
        table_name = "settings"
        primary_key = peewee.CompositeKey("user_id")


logger = logging.getLogger(__name__)


def load_user_settings(context, user_id):
    logger.info("Conversation handler: load_user_settings.")
    query = Setting.select().where(Setting.user_id == user_id)

    # setting1 = valuta
    # setting2 = TBD
    # setting3 = TBD
    # setting4 = TBD
    # setting5 = TBD

    if not query:  # Defaults?
        context.user_data["valuta"] = config.DEFAULT_CURRENCY
    else:
        context.user_data["valuta"] = query[0].setting1


def is_first_word_number(s: str) -> bool:
    try:
        # Split the string into words
        words = s.split()
        # Try to convert the first word to a float
        float(words[0])
        # If no exception is raised, the first word is a number
        return True
    except (ValueError, IndexError):
        # If a ValueError or IndexError is raised, the first word is not a number
        return False


def make_editing_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🏷️ Cambia categoria", callback_data="cambia_data"),
            InlineKeyboardButton("🗓️ Cambia data", callback_data="cambia_categoria"),
        ],
        [
            InlineKeyboardButton("📋 Cambia descrizione", callback_data="cambia_descrizione"),
            InlineKeyboardButton("💸 Cambia importo", callback_data="cambia_importo"),
        ],
        [
            InlineKeyboardButton("❌ Annulla", callback_data="annulla_transazione"),
            InlineKeyboardButton("✅ Salva", callback_data="salva_transazione"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    return reply_markup


def current_transaction(context, return_dict=False):
    transaction = context.user_data["transazione_corrente"]
    valuta = context.user_data["valuta"]
    if return_dict:
        return transaction
    datetime_str = datetime.date.strftime(transaction["data"], "%Y-%m-%d")
    transazione = f"<b>Data:</> {datetime_str}\n<b>Importo:</b> {transaction['importo']} {valuta}\n"
    if transaction["categoria"]:
        transazione += f"<b>Categoria:</b> {transaction['categoria']}\n"
    if transaction["descrizione"]:
        transazione += f"<b>Descrizione:</b> {transaction['descrizione']}\n"
    return transazione


def create_default_categories(user_id):
    default_cats = [
        "🍔 Cibo",
        "📨 Bollette",
        "📱 Telefono",
        "👔 Abbigliamento",
        "🏠 Casa",
        "🕹️ Svago",
        "🚗 Auto",
        "⛽ Benzina",
        "🪁 Tempo libero",
        "🎁 Regali",
        "💰 Altro",
    ]

    for cat in default_cats:
        Categoria.create(user_id=user_id, name=cat, parent=None)
    return [[cat, 0] for cat in default_cats]


def get_categories(user_id):
    logger.info("Conversation handler: get_categories.")
    query = Categoria.select().where(Categoria.user_id == user_id).order_by(Categoria.times_used.desc())
    if not query:
        return create_default_categories(user_id)
    else:
        return [[cat.name, cat.times_used] for cat in query]


def try_categorize(user_id, description):
    logger.info("Conversation handler: try_categorize.")
    # get list of transaction, desc, cat from newer. first desc that matchs, return category
    query = Transazione.select().where(Transazione.user_id == user_id).order_by(Transazione.timestamp.desc())
    lista_desc = {}
    for q in query:
        if q.descrizione:
            lista_desc[q.descrizione] = q.categoria
    for desc in lista_desc.keys():
        similarity = rapidfuzz.fuzz.ratio(description, desc)
        print(f"{description} -> {desc} - {similarity}")
        if similarity > 90:
            return lista_desc[desc]
    return None


def analyze_transactions(user_id=None, start_date=None, end_date=None, days=120, month=None):
    days = days or 180

    end_date = end_date or datetime.date.today()
    start_date = start_date or end_date - datetime.timedelta(days)
    user_id = user_id or 456481297
    if month:
        month = str(datetime.datetime.strptime(month, "%Y-%m").date().month)
        transazioni = (
            Transazione.select()
            .where(Transazione.user_id == user_id, peewee.fn.strftime("%m", Transazione.date) == month)
            .order_by(Transazione.date.desc())
        )
    else:
        transazioni = (
            Transazione.select()
            .where(Transazione.user_id == user_id, Transazione.date >= start_date, Transazione.date <= end_date)
            .order_by(Transazione.timestamp.desc())
        )

    if not transazioni:
        return None, None, None

    spending_by_cat = {}
    spending_by_month = {}
    spending_by_month_by_cat = {}

    for t in transazioni:
        spending_by_cat[t.categoria] = spending_by_cat.get(t.categoria, 0) + t.importo
        spending_by_month[t.date.strftime("%Y-%m")] = spending_by_month.get(t.date.strftime("%Y-%m"), 0) + t.importo
        spending_by_month_by_cat.setdefault(t.date.strftime("%Y-%m"), {})
        spending_by_month_by_cat[t.date.strftime("%Y-%m")][t.categoria] = (
            spending_by_month_by_cat[t.date.strftime("%Y-%m")].get(t.categoria, 0) + t.importo
        )

    spending_by_cat = sorted(spending_by_cat.items(), key=lambda x: x[1], reverse=True)
    spending_by_month = sorted(spending_by_month.items(), key=lambda x: x[0], reverse=False)
    spending_by_month_by_cat = sorted(spending_by_month_by_cat.items(), key=lambda x: x[0], reverse=False)
    spending_by_month_by_cat = [
        (month, dict(sorted(categories.items(), key=lambda item: item[1], reverse=True)))
        for month, categories in spending_by_month_by_cat
    ]

    return spending_by_cat, spending_by_month, spending_by_month_by_cat


def get_user_valuta(context, user_id):
    logger.info("Conversation handler: get_user_valuta.")
    valuta = context.user_data["valuta"]
    if not valuta:
        query = Setting.select().where(Setting.user_id == user_id)
        if not query:
            return config.DEFAULT_CURRENCY
        else:
            return query[0].setting1


def generate_sample_data():
    import random
    from datetime import datetime, timedelta

    import pandas as pd

    # Define categories
    categories = ["Cibo", "Spesa", "Affitto", "Bollette", "Trasporto", "Intrattenimento", "Salute", "Altro"]

    # Define start and end dates
    start_date = datetime(2023, 5, 1)
    end_date = datetime(2023, 10, 31)

    # Generate dates
    dates = [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]

    # Generate data
    data = {"timestamp": [], "date": [], "user_id": [], "amount": [], "description": [], "category": []}

    for _ in range(200):
        date = random.choice(dates)
        category = random.choice(categories)
        data["timestamp"].append(int((date - datetime(1970, 1, 1)).total_seconds()))
        data["date"].append(date.strftime("%Y-%m-%d"))
        data["user_id"].append(456481297)
        data["amount"].append(round(random.uniform(1, 100), 2))
        data["description"].append(f"Transazione per {category}")
        data["category"].append(category)

    # Create DataFrame
    df = pd.DataFrame(data)

    # Save to CSV
    df.to_csv("transactions.csv", index=False)


def insert_data():
    data = """
1683417600,2023-05-07,456481297,19.58,Transazione per Altro,Altro
1683244800,2023-05-05,456481297,59.43,Transazione per Intrattenimento,Intrattenimento
1691884800,2023-08-13,456481297,84.95,Transazione per Altro,Altro
1686873600,2023-06-16,456481297,58.95,Transazione per Bollette,Bollette
1683676800,2023-05-10,456481297,18.81,Transazione per Cibo,Cibo
1694563200,2023-09-13,456481297,31.57,Transazione per Intrattenimento,Intrattenimento
1684022400,2023-05-14,456481297,41.17,Transazione per Trasporto,Trasporto
1693094400,2023-08-27,456481297,6.5,Transazione per Intrattenimento,Intrattenimento
1696636800,2023-10-07,456481297,53.58,Transazione per Intrattenimento,Intrattenimento
1690502400,2023-07-28,456481297,25.54,Transazione per Altro,Altro
1683244800,2023-05-05,456481297,68.47,Transazione per Affitto,Affitto
1694131200,2023-09-08,456481297,95.25,Transazione per Bollette,Bollette
1695772800,2023-09-27,456481297,37.84,Transazione per Intrattenimento,Intrattenimento
1693699200,2023-09-03,456481297,90.56,Transazione per Salute,Salute
1696982400,2023-10-11,456481297,29.6,Transazione per Trasporto,Trasporto
1683936000,2023-05-13,456481297,3.09,Transazione per Trasporto,Trasporto
1696896000,2023-10-10,456481297,99.75,Transazione per Intrattenimento,Intrattenimento
1687910400,2023-06-28,456481297,87.74,Transazione per Affitto,Affitto
1684800000,2023-05-23,456481297,4.01,Transazione per Salute,Salute
1691366400,2023-08-07,456481297,38.56,Transazione per Spesa,Spesa
1684108800,2023-05-15,456481297,4.85,Transazione per Intrattenimento,Intrattenimento
1687219200,2023-06-20,456481297,47.77,Transazione per Salute,Salute
1696377600,2023-10-04,456481297,79.75,Transazione per Salute,Salute
1696982400,2023-10-11,456481297,13.96,Transazione per Altro,Altro
1686873600,2023-06-16,456481297,86.3,Transazione per Salute,Salute
1697500800,2023-10-17,456481297,94.6,Transazione per Spesa,Spesa
1687478400,2023-06-23,456481297,24.92,Transazione per Spesa,Spesa
1689638400,2023-07-18,456481297,35.0,Transazione per Trasporto,Trasporto
1696291200,2023-10-03,456481297,78.17,Transazione per Salute,Salute
1690675200,2023-07-30,456481297,34.64,Transazione per Altro,Altro
1691971200,2023-08-14,456481297,47.19,Transazione per Trasporto,Trasporto
1687219200,2023-06-20,456481297,49.87,Transazione per Cibo,Cibo
1687651200,2023-06-25,456481297,69.72,Transazione per Trasporto,Trasporto
1691452800,2023-08-08,456481297,67.92,Transazione per Altro,Altro
1692921600,2023-08-25,456481297,91.67,Transazione per Affitto,Affitto
1685836800,2023-06-04,456481297,26.33,Transazione per Salute,Salute
1693094400,2023-08-27,456481297,44.38,Transazione per Bollette,Bollette
1692921600,2023-08-25,456481297,33.88,Transazione per Affitto,Affitto
1690761600,2023-07-31,456481297,34.52,Transazione per Intrattenimento,Intrattenimento
1687132800,2023-06-19,456481297,97.28,Transazione per Intrattenimento,Intrattenimento
1685404800,2023-05-30,456481297,31.09,Transazione per Salute,Salute
1684713600,2023-05-22,456481297,61.72,Transazione per Intrattenimento,Intrattenimento
1696982400,2023-10-11,456481297,81.25,Transazione per Affitto,Affitto
1686355200,2023-06-10,456481297,22.24,Transazione per Cibo,Cibo
1694304000,2023-09-10,456481297,10.77,Transazione per Affitto,Affitto
1687996800,2023-06-29,456481297,7.27,Transazione per Salute,Salute
1691798400,2023-08-12,456481297,74.76,Transazione per Salute,Salute
1690588800,2023-07-29,456481297,72.53,Transazione per Altro,Altro
1685664000,2023-06-02,456481297,76.98,Transazione per Trasporto,Trasporto
1691712000,2023-08-11,456481297,53.02,Transazione per Intrattenimento,Intrattenimento
1695340800,2023-09-22,456481297,92.7,Transazione per Trasporto,Trasporto
1685145600,2023-05-27,456481297,71.71,Transazione per Bollette,Bollette
1688169600,2023-07-01,456481297,46.23,Transazione per Spesa,Spesa
1690416000,2023-07-27,456481297,67.5,Transazione per Trasporto,Trasporto
1694563200,2023-09-13,456481297,16.27,Transazione per Trasporto,Trasporto
1695859200,2023-09-28,456481297,16.9,Transazione per Intrattenimento,Intrattenimento
1693699200,2023-09-03,456481297,11.61,Transazione per Salute,Salute
1690502400,2023-07-28,456481297,8.46,Transazione per Trasporto,Trasporto
1688515200,2023-07-05,456481297,92.28,Transazione per Affitto,Affitto
1686873600,2023-06-16,456481297,50.38,Transazione per Affitto,Affitto
1687305600,2023-06-21,456481297,76.61,Transazione per Salute,Salute
1696118400,2023-10-01,456481297,24.01,Transazione per Altro,Altro
1694304000,2023-09-10,456481297,92.45,Transazione per Bollette,Bollette
1690329600,2023-07-26,456481297,62.52,Transazione per Trasporto,Trasporto
1686873600,2023-06-16,456481297,29.28,Transazione per Affitto,Affitto
1692576000,2023-08-21,456481297,18.8,Transazione per Bollette,Bollette
1690934400,2023-08-02,456481297,5.92,Transazione per Salute,Salute
1689206400,2023-07-13,456481297,10.52,Transazione per Altro,Altro
1684368000,2023-05-18,456481297,37.95,Transazione per Bollette,Bollette
1684368000,2023-05-18,456481297,80.13,Transazione per Intrattenimento,Intrattenimento
1683849600,2023-05-12,456481297,95.07,Transazione per Intrattenimento,Intrattenimento
1688083200,2023-06-30,456481297,18.34,Transazione per Affitto,Affitto
1694563200,2023-09-13,456481297,30.18,Transazione per Bollette,Bollette
1696118400,2023-10-01,456481297,22.41,Transazione per Spesa,Spesa
1689033600,2023-07-11,456481297,11.34,Transazione per Intrattenimento,Intrattenimento
1687996800,2023-06-29,456481297,13.25,Transazione per Salute,Salute
1694131200,2023-09-08,456481297,99.15,Transazione per Salute,Salute
1684540800,2023-05-20,456481297,96.19,Transazione per Altro,Altro
1686268800,2023-06-09,456481297,56.13,Transazione per Affitto,Affitto
1698710400,2023-10-31,456481297,53.85,Transazione per Cibo,Cibo
1683849600,2023-05-12,456481297,28.89,Transazione per Affitto,Affitto
1684454400,2023-05-19,456481297,46.56,Transazione per Altro,Altro
1690243200,2023-07-25,456481297,20.05,Transazione per Altro,Altro
1693699200,2023-09-03,456481297,91.96,Transazione per Bollette,Bollette
1684627200,2023-05-21,456481297,35.86,Transazione per Trasporto,Trasporto
1690761600,2023-07-31,456481297,60.59,Transazione per Bollette,Bollette
1691280000,2023-08-06,456481297,48.45,Transazione per Bollette,Bollette
1685836800,2023-06-04,456481297,95.36,Transazione per Salute,Salute
1686182400,2023-06-08,456481297,45.04,Transazione per Trasporto,Trasporto
1696291200,2023-10-03,456481297,61.55,Transazione per Salute,Salute
1696809600,2023-10-09,456481297,52.58,Transazione per Trasporto,Trasporto
1697500800,2023-10-17,456481297,86.04,Transazione per Altro,Altro
1689206400,2023-07-13,456481297,18.33,Transazione per Spesa,Spesa
1688169600,2023-07-01,456481297,54.09,Transazione per Spesa,Spesa
1686960000,2023-06-17,456481297,77.08,Transazione per Spesa,Spesa
1683331200,2023-05-06,456481297,68.7,Transazione per Intrattenimento,Intrattenimento
1694217600,2023-09-09,456481297,62.43,Transazione per Trasporto,Trasporto
1689897600,2023-07-21,456481297,61.12,Transazione per Affitto,Affitto
1684972800,2023-05-25,456481297,38.24,Transazione per Spesa,Spesa
1688515200,2023-07-05,456481297,97.57,Transazione per Altro,Altro
1691539200,2023-08-09,456481297,25.47,Transazione per Spesa,Spesa
1698019200,2023-10-23,456481297,99.81,Transazione per Cibo,Cibo
1685404800,2023-05-30,456481297,28.81,Transazione per Cibo,Cibo
1698278400,2023-10-26,456481297,7.84,Transazione per Affitto,Affitto
1696291200,2023-10-03,456481297,70.89,Transazione per Affitto,Affitto
1687478400,2023-06-23,456481297,96.96,Transazione per Affitto,Affitto
1692748800,2023-08-23,456481297,16.32,Transazione per Bollette,Bollette
1685664000,2023-06-02,456481297,44.98,Transazione per Trasporto,Trasporto
1694217600,2023-09-09,456481297,16.3,Transazione per Intrattenimento,Intrattenimento
1691539200,2023-08-09,456481297,17.6,Transazione per Altro,Altro
1692835200,2023-08-24,456481297,34.24,Transazione per Salute,Salute
1685836800,2023-06-04,456481297,83.25,Transazione per Intrattenimento,Intrattenimento
1687305600,2023-06-21,456481297,48.99,Transazione per Intrattenimento,Intrattenimento
1698278400,2023-10-26,456481297,67.64,Transazione per Cibo,Cibo
1696636800,2023-10-07,456481297,96.7,Transazione per Spesa,Spesa
1688601600,2023-07-06,456481297,15.9,Transazione per Intrattenimento,Intrattenimento
1685577600,2023-06-01,456481297,3.47,Transazione per Altro,Altro
1696377600,2023-10-04,456481297,5.92,Transazione per Affitto,Affitto
1687996800,2023-06-29,456481297,6.14,Transazione per Spesa,Spesa
1685577600,2023-06-01,456481297,6.33,Transazione per Intrattenimento,Intrattenimento
1695686400,2023-09-26,456481297,19.38,Transazione per Salute,Salute
1684972800,2023-05-25,456481297,55.29,Transazione per Cibo,Cibo
1697760000,2023-10-20,456481297,32.05,Transazione per Affitto,Affitto
1691971200,2023-08-14,456481297,4.06,Transazione per Trasporto,Trasporto
1684800000,2023-05-23,456481297,6.38,Transazione per Spesa,Spesa
1691712000,2023-08-11,456481297,94.84,Transazione per Altro,Altro
1696550400,2023-10-06,456481297,54.45,Transazione per Trasporto,Trasporto
1689292800,2023-07-14,456481297,95.86,Transazione per Cibo,Cibo
1686009600,2023-06-06,456481297,51.27,Transazione per Cibo,Cibo
1689897600,2023-07-21,456481297,89.71,Transazione per Affitto,Affitto
1685232000,2023-05-28,456481297,66.07,Transazione per Affitto,Affitto
1688774400,2023-07-08,456481297,65.04,Transazione per Salute,Salute
1685750400,2023-06-03,456481297,70.69,Transazione per Bollette,Bollette
1693612800,2023-09-02,456481297,51.17,Transazione per Salute,Salute
1690588800,2023-07-29,456481297,13.53,Transazione per Spesa,Spesa
1694044800,2023-09-07,456481297,79.83,Transazione per Spesa,Spesa
1695513600,2023-09-24,456481297,39.13,Transazione per Intrattenimento,Intrattenimento
1694822400,2023-09-16,456481297,50.65,Transazione per Trasporto,Trasporto
1684281600,2023-05-17,456481297,43.8,Transazione per Cibo,Cibo
1692662400,2023-08-22,456481297,9.09,Transazione per Bollette,Bollette
1692144000,2023-08-16,456481297,70.37,Transazione per Affitto,Affitto
1695600000,2023-09-25,456481297,90.01,Transazione per Altro,Altro
1693785600,2023-09-04,456481297,34.17,Transazione per Spesa,Spesa
1694304000,2023-09-10,456481297,33.21,Transazione per Affitto,Affitto
1697587200,2023-10-18,456481297,50.08,Transazione per Salute,Salute
1687824000,2023-06-27,456481297,36.35,Transazione per Spesa,Spesa
1684108800,2023-05-15,456481297,50.05,Transazione per Affitto,Affitto
1687392000,2023-06-22,456481297,97.17,Transazione per Spesa,Spesa
1684800000,2023-05-23,456481297,60.29,Transazione per Intrattenimento,Intrattenimento
1688774400,2023-07-08,456481297,90.42,Transazione per Altro,Altro
1690070400,2023-07-23,456481297,94.52,Transazione per Altro,Altro
1682985600,2023-05-02,456481297,30.93,Transazione per Trasporto,Trasporto
1693440000,2023-08-31,456481297,10.28,Transazione per Salute,Salute
1687824000,2023-06-27,456481297,43.02,Transazione per Bollette,Bollette
1683417600,2023-05-07,456481297,93.34,Transazione per Trasporto,Trasporto
1685923200,2023-06-05,456481297,14.23,Transazione per Cibo,Cibo
1692489600,2023-08-20,456481297,1.19,Transazione per Cibo,Cibo
1695686400,2023-09-26,456481297,56.01,Transazione per Intrattenimento,Intrattenimento
1687046400,2023-06-18,456481297,61.8,Transazione per Cibo,Cibo
1695340800,2023-09-22,456481297,46.55,Transazione per Altro,Altro
1692489600,2023-08-20,456481297,83.25,Transazione per Cibo,Cibo
1696723200,2023-10-08,456481297,47.78,Transazione per Intrattenimento,Intrattenimento
1682899200,2023-05-01,456481297,43.03,Transazione per Trasporto,Trasporto
1692662400,2023-08-22,456481297,48.63,Transazione per Spesa,Spesa
1698451200,2023-10-28,456481297,80.76,Transazione per Salute,Salute
1687132800,2023-06-19,456481297,11.2,Transazione per Bollette,Bollette
1692144000,2023-08-16,456481297,50.3,Transazione per Spesa,Spesa
1687305600,2023-06-21,456481297,10.49,Transazione per Salute,Salute
1693785600,2023-09-04,456481297,64.53,Transazione per Trasporto,Trasporto
1694304000,2023-09-10,456481297,11.4,Transazione per Trasporto,Trasporto
1690329600,2023-07-26,456481297,51.55,Transazione per Intrattenimento,Intrattenimento
1697760000,2023-10-20,456481297,74.8,Transazione per Trasporto,Trasporto
1689724800,2023-07-19,456481297,43.9,Transazione per Spesa,Spesa
1683417600,2023-05-07,456481297,71.18,Transazione per Bollette,Bollette
1683849600,2023-05-12,456481297,23.0,Transazione per Bollette,Bollette
1688947200,2023-07-10,456481297,81.48,Transazione per Bollette,Bollette
1695081600,2023-09-19,456481297,28.62,Transazione per Affitto,Affitto
1697500800,2023-10-17,456481297,89.73,Transazione per Salute,Salute
1688169600,2023-07-01,456481297,48.49,Transazione per Trasporto,Trasporto
1690588800,2023-07-29,456481297,85.07,Transazione per Intrattenimento,Intrattenimento
1697587200,2023-10-18,456481297,59.04,Transazione per Spesa,Spesa
1692230400,2023-08-17,456481297,62.2,Transazione per Intrattenimento,Intrattenimento
1698105600,2023-10-24,456481297,98.8,Transazione per Salute,Salute
1692057600,2023-08-15,456481297,32.68,Transazione per Affitto,Affitto
1696809600,2023-10-09,456481297,49.6,Transazione per Altro,Altro
1696377600,2023-10-04,456481297,63.98,Transazione per Bollette,Bollette
1693872000,2023-09-05,456481297,77.35,Transazione per Altro,Altro
1689984000,2023-07-22,456481297,76.16,Transazione per Affitto,Affitto
1690934400,2023-08-02,456481297,83.4,Transazione per Bollette,Bollette
1694476800,2023-09-12,456481297,21.64,Transazione per Salute,Salute
1697846400,2023-10-21,456481297,45.25,Transazione per Altro,Altro
1683244800,2023-05-05,456481297,60.92,Transazione per Affitto,Affitto
1693267200,2023-08-29,456481297,28.24,Transazione per Trasporto,Trasporto
1697932800,2023-10-22,456481297,56.56,Transazione per Trasporto,Trasporto
1688169600,2023-07-01,456481297,44.67,Transazione per Salute,Salute
1685750400,2023-06-03,456481297,43.96,Transazione per Trasporto,Trasporto
1693785600,2023-09-04,456481297,87.0,Transazione per Intrattenimento,Intrattenimento
1691366400,2023-08-07,456481297,77.89,Transazione per Spesa,Spesa
1691884800,2023-08-13,456481297,58.51,Transazione per Intrattenimento,Intrattenimento
1684368000,2023-05-18,456481297,1.89,Transazione per Altro,Altro
"""

    categories = ["Cibo", "Spesa", "Affitto", "Bollette", "Trasporto", "Intrattenimento", "Salute", "Altro"]
    cat_count = {}
    for cat in categories:
        cat_count[cat] = 0
        # Categoria.create(user_id=456481297, name=cat, parent=None)
    data = data.strip().split("\n")
    for d in data:
        d = d.split(",")
        Transazione.create(timestamp=d[0], date=d[1], user_id=d[2], importo=d[3], descrizione=d[4], categoria=d[5])
        cat_count[d[5]] += 1
    for cat in categories:
        Categoria.create(user_id=456481297, name=cat, parent=None, times_used=cat_count[cat])


def elenco_transazioni(context, user_id, month: str = None):
    month = month or datetime.now().strftime("%Y-%m")
    month = str(datetime.datetime.strptime(month, "%Y-%m").date().month)
    transactions = (
        Transazione.select()
        .where(Transazione.user_id == user_id, peewee.fn.strftime("%m", Transazione.date) == month)
        .order_by(Transazione.date.desc())
    )
    if not transactions:
        return None

    t = PrettyTable()
    load_user_settings(context, user_id)
    currency = context.user_data["valuta"]

    t.field_names = ["DATA", "DESCRIZIONE", currency, "CATEGORIA"]
    total = 0
    for x in transactions:
        t.add_row(
            [
                x.date.strftime("%m-%d"),
                x.descrizione[:15],
                f"{round(float(x.importo)*-1, 2)} {currency}",
                x.categoria[:10],
            ]
        )
        total += float(x.importo)

    # tab.add_divider()
    if len(t._dividers) > 0:
        t._dividers[-1] = True
    t.add_row(["", "", f"{round(total*-1, 2)} {currency}", "TOTAL"])
    t.align = "l"
    t.align[currency] = "r"
    t.align["Data"] = "l"
    return t.get_string()


def plotly_by_cat(data, file_name="plot_by_cat.jpg"):
    # Convert to DataFrame
    df = pd.DataFrame(data, columns=["Category", "Spending"])

    # Create a horizontal bar chart with pastel colors
    fig = go.Figure(
        data=[
            go.Bar(
                name="Spending",
                y=df["Category"].str.upper(),
                x=df["Spending"],
                orientation="h",
                marker_color=px.colors.qualitative.Bold,
            )
        ]
    )

    # Add annotations
    for i, (category, spending) in enumerate(data):
        fig.add_annotation(
            dict(
                font=dict(color="black", size=14),
                x=spending,
                y=category.upper(),
                showarrow=False,
                text=str(spending) + " EUR",
                xanchor="left",
                yanchor="middle",
            )
        )

    # Customize the chart
    fig.update_layout(
        title={
            "text": "SPENDING BY CATEGORY",
            "y": 0.9,
            "x": 0.5,
            "xanchor": "center",
            "yanchor": "top",
            "font": dict(size=24),
        },
        xaxis_title="",
        yaxis_title="",
        barmode="stack",
        autosize=False,
        width=800,
        height=500,
        margin=dict(l=50, r=50, b=50, t=100, pad=4),
        template="simple_white",
        # paper_bgcolor="LightSteelBlue",
    )

    # Save the plot
    pio.write_image(fig, file_name)


def plotly_by_month(data, file_name="plot_by_cat.jpg"):
    # Convert to DataFrame
    df = pd.DataFrame(data, columns=["Month", "Spending"])

    # Extract month name from 'Month'
    df["Month"] = pd.to_datetime(df["Month"]).dt.strftime("%B %Y")

    # Create a vertical bar chart with pastel colors
    fig = go.Figure(
        data=[
            go.Bar(
                name="Spending", x=df["Month"], y=df["Spending"], marker_color=px.colors.qualitative.Bold
            )  # Adjust bar width here
        ]
    )

    # Add annotations
    for i, row in df.iterrows():
        fig.add_annotation(
            dict(
                font=dict(color="black", size=14),
                x=row["Month"],
                y=row["Spending"],
                showarrow=False,
                text=str(row["Spending"]) + " EUR",
                xanchor="center",
                yanchor="bottom",
            )
        )

    # Customize the chart
    fig.update_layout(
        title={
            "text": "SPENDING BY MONTH",
            "y": 0.95,
            "x": 0.5,
            "xanchor": "center",
            "yanchor": "top",
            "font": dict(size=24),
        },
        xaxis_title="",
        yaxis_title="",
        width=800,
        height=500,
        margin=dict(l=50, r=50, b=50, t=50, pad=4),
        template="simple_white",
    )
    # Save the plot
    pio.write_image(fig, file_name)


def plotly_by_month_and_category(data, file_name="plot_by_cat.jpg"):
    # Convert to DataFrame
    data_expanded = [(month, cat, spending) for month, categories in data for cat, spending in categories.items()]
    df = pd.DataFrame(data_expanded, columns=["Month", "Category", "Spending"])

    # Extract month name and year from 'Month'
    df["Month"] = pd.to_datetime(df["Month"]).dt.strftime("%B %Y")

    # Convert 'Category' to uppercase
    df["Category"] = df["Category"].str.upper()

    # Create a color map for categories
    categories = df["Category"].unique()
    colors = px.colors.qualitative.Bold
    color_map = {cat: colors[i % len(colors)] for i, cat in enumerate(categories)}

    # Create a pattern map for categories
    patterns = ["", "/", "\\", "x", "-", "|", "+", "."]
    pattern_map = {cat: patterns[i % len(patterns)] for i, cat in enumerate(categories)}

    # Create 2x2 subplots with increased vertical spacing
    fig = make_subplots(
        rows=2,
        cols=2,
        vertical_spacing=0.1,
        horizontal_spacing=0.2,
        subplot_titles=[month.upper() for month in df["Month"].unique()],
    )

    # Create a horizontal bar chart for each month
    for i, month in enumerate(df["Month"].unique()):
        df_month = df[df["Month"] == month]
        for _, row in df_month.iterrows():
            fig.add_trace(
                go.Bar(
                    name=row["Category"],
                    x=[row["Spending"]],
                    y=[row["Category"]],
                    marker_color=color_map[row["Category"]],
                    marker_pattern={"shape": pattern_map[row["Category"]]},
                    orientation="h",
                    showlegend=False,
                ),  # Use color map
                row=i // 2 + 1,
                col=i % 2 + 1,
            )

        # Add annotations with aligned labels
        for _, row in df_month.iterrows():
            fig.add_annotation(
                dict(
                    font=dict(color="black", size=12),
                    x=row["Spending"],
                    y=row["Category"],
                    showarrow=False,
                    text=str(row["Spending"]) + " EUR",
                    xanchor="left",  # Align labels
                    yanchor="middle",
                ),
                row=i // 2 + 1,
                col=i % 2 + 1,
            )

    # Customize the chart
    fig.update_layout(
        title={
            "text": "SPENDING BY MONTH AND CATEGORY",
            "y": 0.98,
            "x": 0.5,
            "xanchor": "center",
            "yanchor": "top",
            "font": dict(size=24),
        },
        xaxis_title="",
        yaxis_title="",
        height=1000,
        width=900,
        margin=dict(l=50, r=50, b=50, t=100, pad=4),
        template="simple_white",
        showlegend=False,  # Hide legend
    )

    # Save the plot
    pio.write_image(fig, file_name)
