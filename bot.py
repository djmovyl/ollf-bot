import os, json, time, re, requests
from datetime import datetime

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
HOME_TEAM = "FC ITPROVIDER"  # название нашей команды точно как на сайте
AWAY_TEAM = ""               # соперника не задаём — будем определять по протоколу
MATCH_URL = ""                # ссылку на матч будем передавать через секрет
STATE_FILE = "state.json"

def send(text, html=False):
    params = {"chat_id": CHANNEL, "text": text}
    if html:
        params["parse_mode"] = "HTML"
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage", params=params, timeout=15)
    if not r.json().get("ok"):
        print("Telegram error:", r.text)

def celebrate_goal(scorer, assist, minute):
    msg = (
        "🔥⚽️ Г-О-О-О-Л! 🔥⚽️\n\n"
        f"🥅 <b>{HOME_TEAM}</b> забивает!\n"
        f"👤 Гол: <b>{scorer}</b>\n"
    )
    if assist:
        msg += f"🎯 Ассист: {assist}\n"
    msg += f"⏱ Время: {minute}'\n\n{MATCH_URL}"
    send(msg, html=True)

def concede_goal(minute):
    msg = (
        "😢🥅 Пропускаем… 😢🥅\n\n"
        f"⏱ На {minute}' минуте соперник забивает.\n\n{MATCH_URL}"
    )
    send(msg, html=True)

def card_event(player, card_type, minute):
    # card_type: 'ЖК' или 'КК'
    icon = "🟨" if card_type == "ЖК" else "🟥"
    msg = f"{icon} <b>{player}</b> получает {card_type} на {minute}' минуте.\n{MATCH_URL}"
    send(msg, html=True)

def get_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"score": None, "goals": [], "cards": []}

def save_state(score, goals, cards):
    with open(STATE_FILE, "w") as f:
        json.dump({"score": score, "goals": goals, "cards": cards}, f)

# --- Парсинг страницы матча (упрощённо) ---
# Важно: сайт подгружает протокол скриптом. Ниже — попытка вытащить текст из HTML.
# Если протокол не виден — позже сделаем отдельный шаг, чтобы найти API.
def parse_match_page(url):
    html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
    # Убираем теги, оставляем текст
    text = re.sub(r"<[^>]+>", " ", html)
    
    # Ищем счёт: ищем паттерн «команда 1 — команда 2» и цифры рядом
    # Это очень упрощённо — под сайт ОЛЛФ нужно будет точнее
    score_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", text)
    score = None
    if score_match:
        score = (int(score_match.group(1)), int(score_match.group(2)))

    # Протокол (голы, карточки) — ищем по ключевым словам
    # Примерный формат: «Иванов (гол, 23')», «Петров (ассист)», «Сидоров (ЖК, 45')»
    goals = []
    cards = []

    # Голы: ищем строки с «гол» и временем
    for m in re.finditer(r"([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)+)\s+\(гол(?:,\s*(\d+))?\)", text):
        player = m.group(1)
        minute = m.group(2) or "?"
        goals.append((player, minute))

    # Ассисты: ищем «ассист» рядом с именем
    for m in re.finditer(r"([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)+)\s+\(ассист\)", text):
        player = m.group(1)
        # Привязываем к последнему голу по времени — это упрощение
        if goals:
            goals[-1] = (goals[-1][0], goals[-1][1], player)  # (scorer, minute, assist)

    # Карточки: ищем «ЖК» или «КК»
    for m in re.finditer(r"([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)+)\s+\(([ЖК]{2})(?:,\s*(\d+))?\)", text):
        player = m.group(1)
        card = m.group(2)
        minute = m.group(3) or "?"
        cards.append((player, card, minute))

    return score, goals, cards

def poll():
    global MATCH_URL
    url = os.environ.get("MATCH_URL")
    if url:
        MATCH_URL = url
    else:
        print("MATCH_URL не задан!")
        return

    now_score, now_goals, now_cards = parse_match_page(MATCH_URL)
    prev = get_state()
    prev_score = prev["score"]
    prev_goals = prev["goals"]
    prev_cards = prev["cards"]

    # Старт матча: если счёт был None, а теперь есть — матч начался
    if prev_score is None and now_score is not None:
        send("🎆⚽️ Матч начался! FC ITPROVIDER в игре! 🎆⚽️\n" + MATCH_URL, html=True)

    # Голы
    # Сравниваем списки: если в now_goals есть новые — это голы
    new_goals = [g for g in now_goals if g not in prev_goals]
    for g in new_goals:
        scorer = g[0]
        minute = g[1]
        assist = g[2] if len(g) > 2 else None
        # Определяем, наша команда или соперник: если HOME_TEAM в протоколе — считаем, что это наш гол
        # Здесь упрощение: если в протоколе есть «FC ITPROVIDER» — считаем гол нашим
        # В реальности нужно смотреть, какая команда забила — это решается по протоколу матча
        celebrate_goal(scorer, assist, minute)

    # Пропущенные голы: если счёт изменился, а новых голов за нашу команду нет — значит, пропустили
    if prev_score and now_score:
        home_prev, away_prev = prev_score
        home_now, away_now = now_score
        if home_now == home_prev and away_now > away_prev:
            # Пропустили: ищем время последнего гола соперника (в упрощении — просто время из протокола)
            concede_goal("?")  # пока ставим ?, позже уточним

    # Карточки
    new_cards = [c for c in now_cards if c not in prev_cards]
    for c in new_cards:
        player, card, minute = c
        card_event(player, card, minute)

    # Финал: если прошло больше 85 минут и счёт не меняется 2 цикла — можно считать матч завершённым
    # Но это эвристика. Лучше финал публиковать вручную или по флагу.
    save_state(now_score, now_goals, now_cards)

if __name__ == "__main__":
    poll()
