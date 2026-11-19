import os, re, json, time, requests

TOKEN   = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
MATCH_URL = os.environ.get("MATCH_URL", "https://ollf.ru/match/5905503")
STATE_FILE = "state.json"

def tg(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
                      data=params, timeout=20)
    return r.json()

def send(text):
    # Telegram ограничивает длину сообщения 4096 символами
    text = text[:3900]
    res = tg("sendMessage", chat_id=CHANNEL, text=text, parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"seen_events": , "score_home": 0, "score_away": 0, "finished": False}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

def fetch_page(url):
    # Получаем отрендеренную страницу через Jina
    r = requests.get(f"https://r.jina.ai/{url}", timeout=60)
    return r.text if r.status_code == 200 else ""

def parse_events(html):
    events = 
    # Ищем блоки событий в HTML (адаптировано под верстку ollf.ru)
    # Примерный паттерн: время, тип, игрок, команда, ассист
    # Регулярка упрощена для демонстрации — при необходимости докрутим точность
    pattern = r'<span[^>]*class="time"[^>]*>(\d+)\'</span>\s*<span[^>]*class="type"[^>]*>([^<]+)</span>\s*<span[^>]*class="player"[^>]*>([^<]+)</span>\s*<span[^>]*class="team"[^>]*>([^<]+)</span>(?:\s*<span[^>]*class="assist"[^>]*>([^<]+)</span>)?'
    for m in re.finditer(pattern, html, re.IGNORECASE | re.DOTALL):
        minute, etype, player, team, assist = m.groups()
        events.append({
            "id": f"{minute}-{etype}-{player}",
            "minute": int(minute),
            "type": etype.strip(),
            "player": player.strip(),
            "team": team.strip(),
            "assist": assist.strip() if assist else None
        })
    return events

def is_home_team(team_name):
    return "ITPROVIDER" in team_name.upper() or "FC ITPROVIDER" in team_name.upper()

def post_event(ev, st):
    home = is_home_team(ev["team"])
    text = ""

    if ev["type"] in ("Гол", "Goal"):
        if home:
            st["score_home"] += 1
            text = (f"🔥⚽️ <b>Г-О-О-О-Л! 🔥⚽️</b>\n\n"
                    f"⚽ <b>АВТОР ГОЛА: {ev['player']}</b> 🌟")
            if ev["assist"]:
                text += f"\n🎯 Ассист: {ev['assist']}"
            text += f"\n⏱ На {ev['minute']}' минуте!\n\n"
            text += f"Счёт: <b>{st['score_home']} : {st['score_away']}</b> в нашу пользу! 🎉"
        else:
            st["score_away"] += 1
            text = (f"😢 <b>Пропускаем...</b> 😢\n\n"
                    f"На {ev['minute']}' минуте соперник забивает.\n\n"
                    f"Счёт: <b>{st['score_home']} : {st['score_away']}</b>. Не сдаёмся! 💪")

    elif ev["type"] in ("ЖК", "Жёлтая", "Yellow"):
        icon = "🟨"
        name = "жёлтую"
        text = f"{icon} <b>{ev['player']}</b> получает {name} карточку на {ev['minute']}' минуте."

    elif ev["type"] in ("КК", "Красная", "Red"):
        icon = "🟥"
        name = "красную"
        text = f"{icon} <b>{ev['player']}</b> получает {name} карточку на {ev['minute']}' минуте."

    if text:
        send(text)

def post_final(st):
    if st["finished"]:
        return
    st["finished"] = True
    send(f"🏁 <b>МАТЧ ЗАВЕРШЁН!</b> 🏁\n\n"
         f"📊 Итоговый счёт: <b>{st['score_home']} : {st['score_away']}</b>\n\n"
         f"Спасибо за игру, команда! 🤝")

def main():
    st = load_state()
    html = fetch_page(MATCH_URL)
    if not html:
        print("Не удалось получить страницу матча")
        return

    events = parse_events(html)
    new_events = [e for e in events if e["id"] not in st["seen_events"]]

    for ev in new_events:
        post_event(ev, st)
        st["seen_events"].append(ev["id"])

    # Проверка на завершение матча (ищем маркер финала в HTML)
    if "матч завершён" in html.lower() or "final" in html.lower():
        post_final(st)

    save_state(st)

if __name__ == "__main__":
    main()
