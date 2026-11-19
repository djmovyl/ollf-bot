import os, json, re, requests, time
from datetime import datetime, timedelta

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
TOURNAMENT_URL = "https://ollf.ru/tournament/1067343"
HOME_TEAM = "FC ITPROVIDER"
STATE_FILE = "state.json"

def send(text, html=False):
    params = {"chat_id": CHANNEL, "text": text}
    if html:
        params["parse_mode"] = "HTML"
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage", params=params, timeout=15)
        if not r.json().get("ok"):
            print("Telegram error:", r.text)
    except Exception as e:
        print("Send error:", e)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"next_match": None, "started": False, "final_posted": False}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# Парсим турнирную страницу: ищем ближайший будущий матч с FC ITPROVIDER
def find_next_match(html):
    # Ищем строки вида: «FC ITPROVIDER – Напитки вместе, воскресенье 22 ноября, 15:20»
    pattern = r"FC\s+ITPROVIDER\s*[–-]\s*([^<]+?)\s*,\s*(\d{1,2})\s+(\w+)\s*,\s*(\d{2}:\d{2})"
    m = re.search(pattern, html, flags=re.IGNORECASE)
    if not m:
        # Пробуем обратный порядок: соперник – FC ITPROVIDER
        pattern = r"([^<]+?)\s*[–-]\s*FC\s+ITPROVIDER\s*,\s*(\d{1,2})\s+(\w+)\s*,\s*(\d{2}:\d{2})"
        m = re.search(pattern, html, flags=re.IGNORECASE)
        if not m:
            return None
        opponent = m.group(1).strip()
    else:
        opponent = m.group(1).strip()

    day, month_ru, time_str = m.group(2), m.group(3), m.group(4)
    # Простой маппинг месяцев (можно расширить)
    months = {"ноября": 11, "октября": 10, "декабря": 12, "сентября": 9}
    month = months.get(month_ru.lower(), 11)
    year = 2026  # можно брать из даты запуска, пока фиксим

    try:
        dt = datetime(year, month, int(day), int(time_str.split(":")[0]), int(time_str.split(":")[1]))
        # Ссылка на матч: ищем /match/\d+ в HTML
        match_link = re.search(r'/match/(\d+)', html)
        match_url = f"https://ollf.ru{match_link.group(0)}" if match_link else None
        return {
            "opponent": opponent,
            "start_time": dt,
            "match_url": match_url
        }
    except Exception:
        return None

def celebrate_goal(scorer, assist, minute):
    msg = (
        "🔥⚽️ Г-О-О-О-Л! 🔥⚽️\n\n"
        f"🥅 <b>{HOME_TEAM}</b> забивает!\n"
        f"👤 Гол: <b>{scorer}</b>\n"
    )
    if assist:
        msg += f"🎯 Ассист: {assist}\n"
    msg += f"⏱ Время: {minute}'\n\n{STATE['match_url']}"
    send(msg, html=True)

def concede_goal(minute):
    msg = (
        "😢🥅 Пропускаем… 😢🥅\n\n"
        f"⏱ На {minute}' минуте соперник забивает.\n\n{STATE['match_url']}"
    )
    send(msg, html=True)

def card_event(player, card_type, minute):
    icon = "🟨" if card_type == "ЖК" else "🟥"
    msg = f"{icon} <b>{player}</b> получает {card_type} на {minute}' минуте.\n{STATE['match_url']}"
    send(msg, html=True)

def post_start(match):
    STATE["next_match"] = match
    STATE["started"] = True
    STATE["match_url"] = match["match_url"]
    save_state(STATE)
    msg = (
        f"⚽️🗓 Матч начался!\n\n"
        f"🆚 <b>{HOME_TEAM} vs {match['opponent']}</b>\n"
        f"⏰ Старт: {match['start_time'].strftime('%d.%m %H:%M')}\n"
        f"🔗 {match['match_url']}\n\n"
        "Держим кулаки за команду! 👊"
    )
    send(msg, html=True)

def post_final(match, final_score):
    STATE["final_posted"] = True
    save_state(STATE)
    msg = (
        f"🏁 Матч завершён!\n\n"
        f"🆚 <b>{HOME_TEAM} vs {match['opponent']}</b>\n"
        f"📊 Итоговый счёт: <b>{final_score}</b>\n"
        f"🔗 {match['match_url']}\n\n"
        "Спасибо за игру! 🤝"
    )
    send(msg, html=True)

STATE = load_state()

def main():
    global STATE
    try:
        html = requests.get(TOURNAMENT_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
    except Exception as e:
        print("Tournament page error:", e)
        return

    next_match = find_next_match(html)
    if not next_match:
        print("Next match not found")
        return

    # Если нашли другой матч — сбрасываем состояние
    if STATE.get("next_match") != next_match:
        STATE = {"next_match": next_match, "started": False, "final_posted": False, "match_url": next_match["match_url"]}
        save_state(STATE)

    now = datetime.now()
    start = next_match["start_time"]

    # Старт матча: за 1–2 минуты до времени
    if not STATE["started"] and now >= start - timedelta(minutes=1):
        post_start(next_match)

    # Финал: через 85 минут после старта
    end_time = start + timedelta(minutes=85)
    if STATE["started"] and not STATE["final_posted"] and now >= end_time:
        # Здесь можно подтянуть итоговый счёт из календаря, если он уже обновился
        final_score = "?"  # пока заглушка; можно дописать парсинг счёта из строки матча
        post_final(next_match, final_score)

if __name__ == "__main__":
    main()
