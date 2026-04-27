import asyncio
import random
from datetime import datetime, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from groq import Groq
import config
import json
import os

groq_client = Groq(api_key=config.GROQ_API_KEY)
pending_posts = {}
user_settings = {}
SETTINGS_FILE = "user_settings.json"

def load_settings():
    """Загрузка настроек пользователя"""
    global user_settings
    default_settings = {
        "morning_start": 8,
        "morning_end": 10,
        "news_per_day": 2,
        "variants_per_slot": 3,
        "news_slots": [
            {"start": 10, "end": 14},
            {"start": 16, "end": 20}
        ]
    }

    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            user_settings = json.load(f)
        # Добавляем отсутствующие поля из дефолтных настроек
        for key, value in default_settings.items():
            if key not in user_settings:
                user_settings[key] = value
        save_settings()
    else:
        user_settings = default_settings
        save_settings()

def save_settings():
    """Сохранение настроек"""
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(user_settings, f, ensure_ascii=False, indent=2)

def get_fresh_news():
    """Получение свежих новостей через Groq"""
    try:
        today = datetime.now().strftime("%d.%m.%Y")
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": f"Ты новостной аналитик крипторынка. Сегодня {today}. Найди ТОЛЬКО свежие новости за последние 24 часа."},
                {"role": "user", "content": config.FRESH_NEWS_PROMPT}
            ],
            temperature=0.7,
            max_tokens=600
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return None

def check_breaking_news():
    """Проверка срочных новостей (ФРС, Трамп, важные события)"""
    try:
        today = datetime.now().strftime("%d.%m.%Y")
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": f"Ты аналитик срочных новостей. Сегодня {today}. Проверь есть ли СРОЧНЫЕ новости за последний час."},
                {"role": "user", "content": config.BREAKING_NEWS_PROMPT}
            ],
            temperature=0.5,
            max_tokens=400
        )
        result = response.choices[0].message.content.strip()
        if "НЕТ СРОЧНЫХ" in result.upper() or "NO BREAKING" in result.upper():
            return None
        return result
    except:
        return None

def generate_post(prompt_type):
    """Генерация поста через Groq API"""
    try:
        if prompt_type == "morning":
            prompt = config.MORNING_POST_PROMPT
        elif prompt_type == "news":
            news_data = get_fresh_news()
            if news_data:
                prompt = f"{config.NEWS_POST_PROMPT}\n\nСвежие новости:\n{news_data}"
            else:
                prompt = config.NEWS_POST_PROMPT
        else:
            prompt = config.NEWS_POST_PROMPT

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Ты опытный трейдер криптовалют и фьючерсов. Пишешь естественно, по-человечески, без AI-штампов."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка генерации: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    if update.effective_user.id != config.ADMIN_ID:
        await update.message.reply_text("У вас нет доступа к этому боту.")
        return

    await update.message.reply_text(
        "🤖 Бот для автопостинга запущен!\n\n"
        "Команды:\n"
        "/morning - Сгенерировать утренний пост\n"
        "/news - Сгенерировать новостной пост\n"
        "/settings - Настроить расписание постов\n"
        "/status - Статус бота"
    )

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки расписания"""
    if update.effective_user.id != config.ADMIN_ID:
        return

    keyboard = [
        [InlineKeyboardButton("⏰ Время утренних постов", callback_data="set_morning_time")],
        [InlineKeyboardButton("📊 Количество новостных слотов", callback_data="set_news_count")],
        [InlineKeyboardButton("🔢 Вариантов постов на слот", callback_data="set_variants")],
        [InlineKeyboardButton("⏱️ Настроить временные слоты", callback_data="set_slots")],
        [InlineKeyboardButton("📋 Показать текущие настройки", callback_data="show_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "⚙️ Настройки расписания постов:",
        reply_markup=reply_markup
    )

async def morning_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация утреннего поста по команде"""
    if update.effective_user.id != config.ADMIN_ID:
        return

    await update.message.reply_text("⏳ Генерирую утренний пост...")
    post_text = generate_post("morning")
    await send_for_approval(update, context, post_text, "morning")

async def news_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация новостного поста по команде"""
    if update.effective_user.id != config.ADMIN_ID:
        return

    await update.message.reply_text("⏳ Генерирую новостной пост...")
    post_text = generate_post("news")
    await send_for_approval(update, context, post_text, "news")

async def send_for_approval(update, context, post_text, post_type):
    """Отправка поста на модерацию"""
    post_id = f"{post_type}_{datetime.now().timestamp()}"
    pending_posts[post_id] = {"text": post_text, "photo": None}

    keyboard = [
        [InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{post_id}"),
         InlineKeyboardButton("✏️ Переписать", callback_data=f"rewrite_{post_id}")],
        [InlineKeyboardButton("📷 Добавить фото", callback_data=f"photo_{post_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=config.ADMIN_ID,
        text=f"📝 Новый пост:\n\n{post_text}",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок"""
    query = update.callback_query
    await query.answer()

    # Обработка настроек
    if query.data == "show_settings":
        slots_text = "\n".join([f"   Слот {i+1}: {slot['start']}:00 - {slot['end']}:00"
                                for i, slot in enumerate(user_settings['news_slots'])])
        settings_text = (
            f"📋 Текущие настройки:\n\n"
            f"⏰ Утренние посты: {user_settings['morning_start']}:00 - {user_settings['morning_end']}:00\n"
            f"📊 Новостных слотов в день: {user_settings['news_per_day']}\n"
            f"🔢 Вариантов постов на слот: {user_settings['variants_per_slot']}\n\n"
            f"⏱️ Временные слоты:\n{slots_text}"
        )
        await query.edit_message_text(settings_text)
        return

    if query.data == "set_morning_time":
        await query.edit_message_text(
            "⏰ Введите время для утренних постов в формате: ЧАС_НАЧАЛА ЧАС_КОНЦА\n"
            "Например: 8 10 (с 8 до 10 утра)"
        )
        context.user_data['waiting_for'] = 'morning_time'
        return

    if query.data == "set_news_time":
        await query.edit_message_text(
            "📰 Введите время для новостных постов в формате: ЧАС_НАЧАЛА ЧАС_КОНЦА\n"
            "Например: 11 20 (с 11 до 20 часов)"
        )
        context.user_data['waiting_for'] = 'news_time'
        return

    if query.data == "set_news_count":
        await query.edit_message_text(
            "📊 Введите количество новостных слотов в день (1-5):\n"
            "Например: 2 (будет 2 временных слота для новостей)"
        )
        context.user_data['waiting_for'] = 'news_count'
        return

    if query.data == "set_variants":
        await query.edit_message_text(
            "🔢 Введите количество вариантов постов на каждый слот (1-5):\n"
            "Например: 3 (бот пришлет 3 разных варианта поста, вы выберете лучший)"
        )
        context.user_data['waiting_for'] = 'variants_count'
        return

    if query.data == "set_slots":
        slots_info = "\n".join([f"Слот {i+1}: {slot['start']}-{slot['end']}"
                                for i, slot in enumerate(user_settings['news_slots'])])
        await query.edit_message_text(
            f"⏱️ Текущие слоты:\n{slots_info}\n\n"
            f"Введите номер слота и новое время в формате: НОМЕР ЧАС_НАЧАЛА ЧАС_КОНЦА\n"
            f"Например: 1 10 14 (изменить слот 1 на 10:00-14:00)"
        )
        context.user_data['waiting_for'] = 'edit_slot'
        return

    # Обработка постов
    if "_" not in query.data:
        return

    action, post_id = query.data.split("_", 1)

    if post_id not in pending_posts:
        await query.edit_message_text("❌ Пост не найден или уже обработан.")
        return

    if action == "approve":
        post_data = pending_posts[post_id]
        try:
            if post_data["photo"]:
                await context.bot.send_photo(
                    chat_id=config.CHANNEL_ID,
                    photo=post_data["photo"],
                    caption=post_data["text"]
                )
            else:
                await context.bot.send_message(
                    chat_id=config.CHANNEL_ID,
                    text=post_data["text"]
                )
            await query.edit_message_text(f"✅ Пост опубликован в канале!\n\n{post_data['text']}")
            del pending_posts[post_id]
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка публикации: {str(e)}")

    elif action == "rewrite":
        post_type = post_id.split("_")[0]
        await query.edit_message_text("⏳ Переписываю пост...")
        new_post = generate_post(post_type)
        del pending_posts[post_id]
        await send_for_approval(update, context, new_post, post_type)

    elif action == "photo":
        await query.edit_message_text(
            f"📷 Отправьте фото для этого поста:\n\n{pending_posts[post_id]['text']}\n\n"
            "После отправки фото, пост будет готов к публикации."
        )
        context.user_data['waiting_photo_for'] = post_id

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений для настроек"""
    if update.effective_user.id != config.ADMIN_ID:
        return

    waiting_for = context.user_data.get('waiting_for')
    if not waiting_for:
        return

    text = update.message.text.strip()

    try:
        if waiting_for == 'morning_time':
            start, end = map(int, text.split())
            if 0 <= start < end <= 23:
                user_settings['morning_start'] = start
                user_settings['morning_end'] = end
                save_settings()
                await update.message.reply_text(f"✅ Утренние посты будут приходить с {start}:00 до {end}:00")
                del context.user_data['waiting_for']
            else:
                await update.message.reply_text("❌ Неверный формат. Часы должны быть от 0 до 23.")

        elif waiting_for == 'news_time':
            start, end = map(int, text.split())
            if 0 <= start < end <= 23:
                user_settings['news_start'] = start
                user_settings['news_end'] = end
                save_settings()
                await update.message.reply_text(f"✅ Новостные посты будут приходить с {start}:00 до {end}:00")
                del context.user_data['waiting_for']
            else:
                await update.message.reply_text("❌ Неверный формат. Часы должны быть от 0 до 23.")

        elif waiting_for == 'news_count':
            count = int(text)
            if 1 <= count <= 5:
                user_settings['news_per_day'] = count
                # Автоматически создаем слоты
                user_settings['news_slots'] = []
                if count == 1:
                    user_settings['news_slots'] = [{"start": 12, "end": 18}]
                elif count == 2:
                    user_settings['news_slots'] = [{"start": 10, "end": 14}, {"start": 16, "end": 20}]
                elif count == 3:
                    user_settings['news_slots'] = [{"start": 10, "end": 13}, {"start": 14, "end": 17}, {"start": 18, "end": 21}]
                elif count == 4:
                    user_settings['news_slots'] = [{"start": 10, "end": 12}, {"start": 13, "end": 15}, {"start": 16, "end": 18}, {"start": 19, "end": 21}]
                elif count == 5:
                    user_settings['news_slots'] = [{"start": 9, "end": 11}, {"start": 12, "end": 14}, {"start": 15, "end": 17}, {"start": 18, "end": 20}, {"start": 21, "end": 23}]

                save_settings()
                slots_text = "\n".join([f"Слот {i+1}: {slot['start']}:00-{slot['end']}:00"
                                       for i, slot in enumerate(user_settings['news_slots'])])
                await update.message.reply_text(
                    f"✅ Теперь будет {count} новостных слотов в день:\n\n{slots_text}\n\n"
                    f"Используйте /settings → 'Настроить временные слоты' для изменения времени"
                )
                del context.user_data['waiting_for']
            else:
                await update.message.reply_text("❌ Количество должно быть от 1 до 5")

        elif waiting_for == 'variants_count':
            count = int(text)
            if 1 <= count <= 5:
                user_settings['variants_per_slot'] = count
                save_settings()
                await update.message.reply_text(
                    f"✅ Теперь в каждый слот будет приходить {count} вариантов постов\n"
                    f"Вы сможете выбрать лучший из них"
                )
                del context.user_data['waiting_for']
            else:
                await update.message.reply_text("❌ Количество должно быть от 1 до 5")

        elif waiting_for == 'edit_slot':
            parts = text.split()
            if len(parts) == 3:
                slot_num, start, end = map(int, parts)
                if 1 <= slot_num <= len(user_settings['news_slots']) and 0 <= start < end <= 23:
                    user_settings['news_slots'][slot_num - 1] = {"start": start, "end": end}
                    save_settings()
                    await update.message.reply_text(f"✅ Слот {slot_num} изменен на {start}:00-{end}:00")
                    del context.user_data['waiting_for']
                else:
                    await update.message.reply_text("❌ Неверный номер слота или время")
            else:
                await update.message.reply_text("❌ Неверный формат. Используйте: НОМЕР ЧАС_НАЧАЛА ЧАС_КОНЦА")
    except:
        await update.message.reply_text("❌ Неверный формат. Попробуйте еще раз.")

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото от админа"""
    if update.effective_user.id != config.ADMIN_ID:
        return

    post_id = context.user_data.get('waiting_photo_for')
    if not post_id or post_id not in pending_posts:
        return

    photo = update.message.photo[-1].file_id
    pending_posts[post_id]["photo"] = photo

    keyboard = [
        [InlineKeyboardButton("✅ Одобрить с фото", callback_data=f"approve_{post_id}"),
         InlineKeyboardButton("✏️ Переписать", callback_data=f"rewrite_{post_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"📷 Фото добавлено!\n\n{pending_posts[post_id]['text']}",
        reply_markup=reply_markup
    )
    del context.user_data['waiting_photo_for']

async def scheduled_morning_post(context: ContextTypes.DEFAULT_TYPE):
    """Автоматический утренний пост"""
    post_text = generate_post("morning")
    await send_for_approval(None, context, post_text, "morning")

async def scheduled_news_post(context: ContextTypes.DEFAULT_TYPE):
    """Автоматический новостной пост - генерирует несколько вариантов"""
    variants_count = user_settings.get('variants_per_slot', 3)

    for i in range(variants_count):
        await asyncio.sleep(2)  # Небольшая задержка между вариантами
        post_text = generate_post("news")
        await send_for_approval(None, context, post_text, "news", is_urgent=False)

async def send_for_approval(update, context, post_text, post_type, is_urgent=False):
    """Отправка поста на модерацию"""
    post_id = f"{post_type}_{datetime.now().timestamp()}"
    pending_posts[post_id] = {"text": post_text, "photo": None}

    keyboard = [
        [InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{post_id}"),
         InlineKeyboardButton("✏️ Переписать", callback_data=f"rewrite_{post_id}")],
        [InlineKeyboardButton("📷 Добавить фото", callback_data=f"photo_{post_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    prefix = "🚨 СРОЧНАЯ НОВОСТЬ:\n\n" if is_urgent else "📝 Новый пост:\n\n"

    await context.bot.send_message(
        chat_id=config.ADMIN_ID,
        text=f"{prefix}{post_text}",
        reply_markup=reply_markup
    )

async def check_breaking_news_task(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая проверка срочных новостей"""
    breaking = check_breaking_news()
    if breaking:
        await send_for_approval(None, context, breaking, "breaking", is_urgent=True)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статус бота"""
    if update.effective_user.id != config.ADMIN_ID:
        return

    await update.message.reply_text(
        f"✅ Бот работает\n"
        f"📊 Ожидающих постов: {len(pending_posts)}\n"
        f"⏰ Утренние: {user_settings['morning_start']}:00-{user_settings['morning_end']}:00\n"
        f"📰 Новости: {user_settings['news_start']}:00-{user_settings['news_end']}:00\n"
        f"📊 Новостей/день: {user_settings['news_per_day']}\n"
        f"🕐 Время: {datetime.now().strftime('%H:%M:%S')}"
    )

def main():
    """Запуск бота"""
    load_settings()

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("morning", morning_post_command))
    app.add_handler(CommandHandler("news", news_post_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Планировщик утренних постов
    job_queue = app.job_queue
    morning_hour = random.randint(user_settings['morning_start'], user_settings['morning_end'] - 1)
    morning_minute = random.randint(0, 59)
    job_queue.run_daily(
        scheduled_morning_post,
        time=time(hour=morning_hour, minute=morning_minute)
    )

    # Планировщик новостных постов для каждого слота
    for slot in user_settings['news_slots']:
        slot_hour = random.randint(slot['start'], slot['end'] - 1)
        slot_minute = random.randint(0, 59)
        job_queue.run_daily(
            scheduled_news_post,
            time=time(hour=slot_hour, minute=slot_minute)
        )

    # Проверка срочных новостей каждые 30 минут
    job_queue.run_repeating(check_breaking_news_task, interval=1800, first=10)

    slots_info = ", ".join([f"{slot['start']}-{slot['end']}" for slot in user_settings['news_slots']])
    print("🤖 Бот запущен!")
    print(f"⏰ Утренние посты: {user_settings['morning_start']}:00-{user_settings['morning_end']}:00")
    print(f"📰 Новостные слоты: {slots_info}")
    print(f"🔢 Вариантов на слот: {user_settings['variants_per_slot']}")
    app.run_polling()

if __name__ == "__main__":
    main()
