import os, re, json, time, requests
from datetime import datetime, timedelta, timezone

TOKEN   = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
TOURNAMENT_URL = "https://ollf.ru/tournament/1067343"
HOME = "FC ITPROVIDER"
STATE_FILE = "state.json"

MSK = timezone(timedelta(hours=3))
POLL_SECONDS = 60   # опрос страницы матча внутри окна
LOOP_MINUTES = 4    # сколько минут живёт один запуск (меньше 5, чтобы не резалось расписанием)

MONTHS = {"января":1,"февраля":2,"марта":3,"апреля":4,"мая":5,"июня":6,
          "июля":7,"августа":8,"сентября":9,"октября":10,"ноября":11,"декабря":12}

def tg(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
                      data=params, timeout=20)
    return r.json()

def send(text):
    res = tg("sendMessage", chat_id=CHANNEL, text=text[:3900], parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"seen_events": [], "score_home": 0, "score_away": 0,
                "started": False, "final_posted": False, "match_id": None}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

def jina(url):
    try:
        r = requests.get("https://r.jina.ai/" + url, timeout=60)
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print("jina error:", e)
        return ""

# --- Автопоиск ближайшего матча в календаре ---
def find_next_match():
    md = jina(TOURNAMENT_URL)
    if not md:
        return None
    for m in re.finditer(r"ITPROVIDER", md):
        chunk = md[max(0, m.start() - 200): m.start() + 300]
        dm = re.search(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")", chunk)
        tm = re.search(r"(\d{1,2}:\d{2})", chunk)
        link = re.search(r"/match/(\d+)", chunk)
        if dm and tm:
            day, mon = int(dm.group(1)), MONTHS[dm.group(2)]
            hh, mm = map(int, tm.group(1).split(":"))
            year = datetime.now(MSK).year
            start = datetime(year, mon, day, hh, mm, tzinfo=MSK)
            opp = re.search(r"ITPROVIDER\s*[—–-]\s*([A-Za-zА-Яа-яЁё' \.\-]+)", chunk)
            opponent = opp.group(1).strip() if opp else "соперник"
            url = f"https://ollf.ru/match/{link.group(1)}" if link else None
            return {"start": start, "url": url, "opponent": opponent}
    return None

def parse_events(html):
    events = []
    pattern = (r'<span[^>]*class="time"[^>]*>(\d+)\'</span>\s*'
               r'<span[^>]*class="type"[^>]*>([^<]+)</span>\s*'
               r'<span[^>]*class="player"[^>]*>([^<]+)</span>\s*'
               r'<span[^>]*class="team"[^>]*>([^<]+)</span>'
               r'(?:\s*<span[^>]*class="assist"[^>]*>([^<]+)</span>)?')
    for m in re.finditer(pattern, html, re.IGNORECASE | re.DOTALL):
        minute, etype, player, team, assist = m.groups()
        events.append({"id": f"{minute}-{etype}-{player}",
                       "minute": int(minute), "type": etype.strip(),
                       "player": player.strip(), "team": team.strip(),
                       "assist": (assist or "").strip() or None})
    return events

def is_home(team_name):
    return "ITPROVIDER" in team_name.upper()

def post_event(ev, st):
    if ev["type"] in ("Гол", "Goal"):
        if is_home(ev["team"]):
            st["score_home"] += 1
            text = (f"🔥⚽️ <b>Г-О-О-О-Л! 🔥⚽️</b>\n\n"
                    f"⚽ <b>АВТОР ГОЛА: {ev['player']}</b> 🌟\n"
                    + (f"🎯 Ассист: {ev['assist']}\n" if ev["assist"] else "")
                    + f"⏱ На {ev['minute']}' минуте!\n\n"
                    f"Счёт: <b>{st['score_home']} : {st['score_away']}</b> в нашу пользу! 🎉")
        else:
            st["score_away"] += 1
            text = (f"😢 <b>Пропускаем...</b> 😢\n\n"
                    f"На {ev['minute']}' минуте соперник забивает.\n\n"
                    f"Счёт: <b>{st['score_home']} : {st['score_away']}</b>. Не сдаёмся! 💪")
    elif ev["type"] in ("ЖК", "Жёлтая", "Yellow"):
        text = f"🟨 <b>{ev['player']}</b> получает жёлтую карточку на {ev['minute']}' минуте."
    elif ev["type"] in ("КК", "Красная", "Red"):
        text = f"🟥 <b>{ev['player']}</b> получает красную карточку на {ev['minute']}' минуте."
    else:
        return
    send(text)

def post_final(st):
    st["final_posted"] = True
    send(f"🏁 <b>МАТЧ ЗАВЕРШЁН!</b> 🏁\n\n"
         f"📊 Итоговый счёт: <b>{st['score_home']} : {st['score_away']}</b>\n\n"
         f"Спасибо за игру, команда! 🤝")

def main():
    st = load_state()
    nxt = find_next_match()
    if not nxt or not nxt["url"]:
        print("Матч не найден или нет ссылки — выходим")
        return

    match_id = nxt["url"].rstrip("/").split("/")[-1]
    if st.get("match_id") != match_id:      # новый матч — сбрасываем состояние
        st = {"seen_events": [], "score_home": 0, "score_away": 0,
              "started": False, "final_posted": False, "match_id": match_id}
        save_state(st)

    now = datetime.now(MSK)
    start = nxt["start"]
    in_window = start - timedelta(minutes=10) <= now <= start + timedelta(minutes=115)

    deadline = now + timedelta(minutes=LOOP_MINUTES)
    while True:
        now = datetime.now(MSK)
        html = jina(nxt["url"])
        if html:
            # Старт матча
            if not st["started"] and now >= start:
                st["started"] = True
                send(f"🏟️ <b>МАТЧ НАЧАЛСЯ!</b> 🏟️\n\n"
                     f"🆚 <b>{HOME} vs {nxt['opponent']}</b>\n\n"
                     f"Держим кулаки за команду! 👊")

            events = parse_events(html)
            for ev in events:
                if ev["id"] in st["seen_events"]:
                    continue
                if st["started"]:          # до старта события молча запоминаем
                    post_event(ev, st)
                st["seen_events"].append(ev["id"])

            if st["started"] and not st["final_posted"] and "матч завершён" in html.lower():
                post_final(st)

        save_state(st)
        if in_window and datetime.now(MSK) < deadline and not st.get("final_posted"):
            time.sleep(POLL_SECONDS)
        else:
            break

if __name__ == "__main__":
    main()
