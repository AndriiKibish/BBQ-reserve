# coding: utf-8

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, filters
from telegram_bot_calendar import DetailedTelegramCalendar
from datetime import datetime
import re
import sqlite3
import os


TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

# Создаем и инициализируем базу данных
conn = sqlite3.connect('bbq_bookings.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apartment_number TEXT NOT NULL,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL
)''')
conn.commit()

# Константы этапов
(APARTMENT, DATE_TIME, CONFIRM, CANCEL) = range(4)

# Команды
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Бронювати"],
        ["Мої бронювання", "Усі бронювання"],
        ["Скасувати бронювання"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Привіт! Я бот бронювання мангалу. Виберіть дію:",
        reply_markup=reply_markup
    )

async def book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введіть номер вашої квартири (від 1 до 120):")
    return APARTMENT

async def get_apartment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        apartment_number = int(update.message.text)
        if 1 <= apartment_number <= 120:
            context.user_data['apartment_number'] = apartment_number
            calendar, step = DetailedTelegramCalendar().build()
            await update.message.reply_text(f"Виберіть {step}:", reply_markup=calendar)
            return DATE_TIME
        else:
            await update.message.reply_text("Такого номера квартири у нашому будинку не існує. Введіть номер від 1 до 120.")
            return APARTMENT
    except ValueError:
        await update.message.reply_text("Будь ласка, введіть коректний номер квартири (число від 1 до 120).")
        return APARTMENT

async def handle_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result, key, step = DetailedTelegramCalendar(min_date=datetime.today().date()).process(update.callback_query.data)
    if not result and key:
        await update.callback_query.message.edit_text(f"Виберіть {step}:", reply_markup=key)
    elif result:
        formatted_date = result.strftime("%d.%m.%Y")
        context.user_data['date'] = formatted_date
        await update.callback_query.message.edit_text(
            f"Ви обрали дату: {formatted_date}. Тепер введіть час (у форматі ГГ:ХХ ГГ:ХХ):")
        return CONFIRM

async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        input_text = update.message.text.strip()

        # Обработка кнопок
        if input_text == "Выбрать другое время":
            await update.message.reply_text(
                "Пожалуйста, введите время в формате ЧЧ:ММ ЧЧ:ММ, где ЧЧ — часы (00–24), ММ — минуты (00–59)."
            )
            return CONFIRM
        elif input_text == "Выбрать другую дату":
            calendar, step = DetailedTelegramCalendar(min_date=datetime.today()).build()
            await update.message.reply_text(
                f"Выберите {step}:",
                reply_markup=calendar
            )
            return DATE_TIME
        elif input_text == "Посмотреть все бронирования":
            return await all_bookings(update, context)

        # Проверка формата времени
        time_pattern = r"^(?:[01]\d|2[0-3]):[0-5]\d (?:[01]\d|2[0-3]):[0-5]\d$"
        if not re.match(time_pattern, input_text):
            await update.message.reply_text(
                "Ошибка формата. Укажите время в формате ЧЧ:ММ ЧЧ:ММ, где ЧЧ — часы (00–24), ММ — минуты (00–59)."
            )
            return CONFIRM

        start_time, end_time = input_text.split()
        context.user_data['start_time'] = start_time
        context.user_data['end_time'] = end_time

        # Проверка на пересечение бронирований
        date = context.user_data['date']
        start_time_input = f"{date} {start_time}"
        end_time_input = f"{date} {end_time}"

        start_datetime = datetime.strptime(start_time_input, "%d.%m.%Y %H:%M")
        end_datetime = datetime.strptime(end_time_input, "%d.%m.%Y %H:%M")

        # SQL-запрос для проверки конфликтов
        cursor.execute('''
            SELECT * FROM bookings
            WHERE date = ?
            AND (
                (datetime(?, 'localtime') < datetime(end_time, 'localtime') AND datetime(?, 'localtime') >= datetime(start_time, 'localtime')) OR
                (datetime(?, 'localtime') > datetime(start_time, 'localtime') AND datetime(?, 'localtime') <= datetime(end_time, 'localtime'))
            )
        ''', (date, start_time_input, start_time_input, end_time_input, end_time_input))

        conflicting_bookings = cursor.fetchall()

        # Обработка результата
        if conflicting_bookings:
            keyboard = [
                ["Выбрать другое время"],
                ["Выбрать другую дату"],
                ["Посмотреть все бронирования"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "Выбранное время уже занято. Попробуйте другое время или дату:",
                reply_markup=reply_markup
            )
            return CONFIRM

        # Сохранение нового бронирования
        cursor.execute(
            'INSERT INTO bookings (apartment_number, user_id, date, start_time, end_time) VALUES (?, ?, ?, ?, ?)',
            (
                context.user_data['apartment_number'],
                update.effective_user.id,
                date,
                start_time,
                end_time
            )
        )
        conn.commit()
        await update.message.reply_text("Бронирование подтверждено!")
    except Exception as e:
        await update.message.reply_text("Произошла ошибка. Попробуйте еще раз.")
        print(e)
        return CONFIRM
    return ConversationHandler.END


async def my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute('SELECT * FROM bookings WHERE user_id = ?', (user_id,))
    bookings = cursor.fetchall()
    if bookings:
        response = "Ваші бронювання:\n"
        for booking in bookings:
            response += f"Дата: {booking[3]}, Час: {booking[4]}-{booking[5]}\n"
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("У вас немає бронювань.")

async def all_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute('SELECT * FROM bookings')
    bookings = cursor.fetchall()
    if bookings:
        response = "Усі бронювання:\n"
        for booking in bookings:
            response += f"Квартира: {booking[1]}, Дата: {booking[3]}, Час: {booking[4]}-{booking[5]}\n"
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("Бронювань немає.")

async def cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute('SELECT * FROM bookings WHERE user_id = ?', (user_id,))
    bookings = cursor.fetchall()
    if bookings:
        keyboard = [
            [InlineKeyboardButton(f"{booking[3]} {booking[4]}-{booking[5]}", callback_data=str(booking[0]))]
            for booking in bookings
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Виберіть бронювання для скасування:", reply_markup=reply_markup)
        return CANCEL
    else:
        await update.message.reply_text("У вас немає бронювань для скасування.")
        return ConversationHandler.END

async def cancel_specific(update: Update, context: ContextTypes.DEFAULT_TYPE):
    booking_id = update.callback_query.data
    user_id = update.effective_user.id

    cursor.execute('DELETE FROM bookings WHERE id = ? AND user_id = ?', (booking_id, user_id))
    conn.commit()

    await update.callback_query.message.edit_text("Бронювання скасовано.")
    return ConversationHandler.END

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "Бронювати":
        return await book(update, context)
    elif text == "Мої бронювання":
        return await my_bookings(update, context)
    elif text == "Усі бронювання":
        return await all_bookings(update, context)
    elif text == "Скасувати бронювання":
        return await cancel_booking(update, context)

# Основной код
application = Application.builder().token(TELEGRAM_TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(Бронювати|Мої бронювання|Усі бронювання|Скасувати бронювання)$"), handle_buttons)],
    states={
        APARTMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_apartment)],
        DATE_TIME: [
            CallbackQueryHandler(handle_calendar),
            MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_booking)
        ],
        CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_booking)],
        CANCEL: [CallbackQueryHandler(cancel_specific)]
    },
    fallbacks=[]
)

application.add_handler(CommandHandler('start', start))
application.add_handler(conv_handler)

print("Бот запущен...")
application.run_polling()
