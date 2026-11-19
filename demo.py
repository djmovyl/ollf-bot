import os, re, requests

TOKEN  = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
HOME = "FC ITPROVIDER"
TOURNAMENT_URL = "https://ollf.ru/tournament/1067343"

def send(text):
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                     params={"chat_id": CHANNEL, "text": text, "parse_mode": "HTML"},
                     timeout=15)
    print(r.text[:200])

# --- Проверка: находит ли бот матч в календаре ---
try:
    html = requests.get(TOURNAMENT_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
    m = re.search(r"FC\s+ITPROVIDER\s*[–-]\s*([^<,\n]+?)\s*,\s*(\d{1,2})\s+([а-яё]+)\s*,\s*(\d{2}:\d{2})",
                  html, flags=re.IGNORECASE)
    if m:
        send(f"🔍 Диагностика: матч найден — <b>{HOME} vs {m.group(1).strip()}</b>, "
             f"{m.group(2)} {m.group(3)}, {m.group(4)}. Работаю по плану!")
    else:
        send("🔍 Диагностика: FC ITPROVIDER в календаре НЕ найден — регулярку будем править.")
except Exception as e:
    send(f"🔍 Диагностика: ошибка доступа к сайту — {e}")

# --- Демо-посты, как будет выглядеть трансляция ---
send("🎆⚽️ <b>Матч начался!</b>\n\n"
     f"🆚 <b>{HOME} vs Напитки вместе</b>\n"
     "⏰ Старт: 22.11 15:20\n\n"
     "Держим кулаки за команду! 👊")

send("🔥⚽️ <b>Г-О-О-О-Л!</b> ⚽️🔥\n\n"
     f"🥅 <b>{HOME}</b> забивает!\n"
     "👤 Гол: <b>Иванов</b>\n"
     "🎯 Ассист: Петров\n"
     "⏱ Время: 35'\n\n"
     "<b>FC ITPROVIDER 1 : 0 Соперник</b>")

send("😢🥅 <b>Пропускаем…</b> 😢🥅\n\n"
     "⏱ На 23' минуте соперник забивает.\n\n"
     "<b>FC ITPROVIDER 0 : 1 Соперник</b>")

send("🏁 <b>Матч завершён!</b>\n\n"
     f"🆚 <b>{HOME} vs Напитки вместе</b>\n"
     "📊 Итоговый счёт: <b>3 : 2</b>\n\n"
     "Спасибо за игру! 🤝")
