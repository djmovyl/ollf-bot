import os, re, requests

TOKEN  = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
HOME = "FC ITPROVIDER"
TOURNAMENT_URL = "https://ollf.ru/tournament/1067343"

def send(text):
    # parse_mode="HTML" позволяет делать жирный текст
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                     params={"chat_id": CHANNEL, "text": text, "parse_mode": "HTML"},
                     timeout=15)
    # Выводим статус в лог Actions, чтобы видеть успех/ошибку
    print(r.json().get("ok", False))

# --- Диагностика: находит ли бот матч ---
try:
    html = requests.get(TOURNAMENT_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
    # Ищем матч
    m = re.search(r"FC\s+ITPROVIDER\s*[–-]\s*([^<,\n]+?)\s*,\s*(\d{1,2})\s+([а-яё]+)\s*,\s*(\d{2}:\d{2})",
                  html, flags=re.IGNORECASE)
    
    if m:
        opponent = m.group(1).strip()
        date_str = f"{m.group(2)} {m.group(3)}"
        time_str = m.group(4)
        send(f"✅ <b>Диагностика пройдена!</b>\n\n"
             f"🔍 Нашёл матч: <b>{HOME} vs {opponent}</b>\n"
             f"🗓 Дата: {date_str}, ⏰ Время: {time_str}\n\n"
             f"Готов к трансляции! 🚀")
    else:
        send("❌ <b>Ошибка диагностики:</b>\n\n"
             f"Не удалось найти упоминание <b>{HOME}</b> в календаре.\n"
             f"Нужно править регулярку под верстку сайта.")
except Exception as e:
    send(f"❌ <b>Ошибка доступа к сайту:</b>\n{e}")

# --- 1. Старт матча (без хоккейных ворот, со стадионом) ---
send(f"🏟️ <b>МАТЧ НАЧАЛСЯ!</b> 🏟️\n\n"
     f"🆚 <b>{HOME} vs Напитки вместе</b>\n"
     f"⏰ Старт: 22.11 15:20\n\n"
     f"Держим кулаки за команду! 👊\n"
     f"#ITPROVIDER #Вперёд")

# --- 2. Гол (акцент на игроке, без ворот) ---
# Обратите внимание: имя игрока выделено жирным и стоит первым
send(f"🔥⚽️ <b>Г-О-О-О-Л! 🔥⚽️</b>\n\n"
     f"🥅 <b>{HOME}</b> забивает!\n"
     f"👤 <b>АВТОР ГОЛА: Иванов</b> 🌟\n"
     f"🎯 Ассист: Петров\n"
     f"⏱ Время: 35'\n\n"
     f"Счёт: <b>1 : 0</b> в нашу пользу! 🎉")

# --- 3. Пропущенный мяч (эмоции) ---
send(f"😢 <b>Пропускаем...</b> 😢\n\n"
     f"На 23' минуте соперник сравнивает счёт.\n"
     f"⏱ Время: 23'\n\n"
     f"Счёт: <b>1 : 1</b>. Не сдаёмся! 💪")

# --- 4. Финал (итоги) ---
send(f"🏁 <b>МАТЧ ЗАВЕРШЁН!</b> 🏁\n\n"
     f"🆚 <b>{HOME} vs Напитки вместе</b>\n"
     f"📊 Итоговый счёт: <b>3 : 2</b>\n\n"
     f"Спасибо за игру, команда! 🤝\n"
     f"До новых встреч! 👋")
