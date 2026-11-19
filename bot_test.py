import os, re, requests, traceback

TOKEN   = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
MATCH_URL = "https://ollf.ru/match/5905503"
HOME = "FC ITPROVIDER"

def tg(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
                      data=params, timeout=20)
    return r.json()

def send(text):
    res = tg("sendMessage", chat_id=CHANNEL, text=text[:3900], parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)

def jina(url):
    r = requests.get("https://r.jina.ai/" + url, timeout=60)
    print("jina:", url, "->", r.status_code, len(r.text))
    return r.text if r.status_code == 200 else ""

# Тот же парсер, что пойдёт в финальный бот
def parse_events(md):
    raw_lines = [l.strip() for l in md.splitlines()
                 if re.search(r"\d{1,3}'\s*\d{2}''", l)]
    events = []
    pending = []          # голы, чья минута есть, а счёт ещё не пришёл
    prev_h = prev_a = 0
    for l in raw_lines:
        names = re.findall(r"
$$
([^
$$
]+)\]", l)
        sm = re.search(r"(\d+)\s*:\s*(\d+)", l)
        if sm:
            h, a = int(sm.group(1)), int(sm.group(2))
            dh, da = h - prev_h, a - prev_a
            team = "home" if dh > 0 else ("away" if da > 0 else "unknown")
            for p in pending:
                events.append({**p, "team": team})
            pending = []
            prev_h, prev_a = h, a
        if names:
            pending.append({"player": names[0],
                            "assist": names[1] if len(names) > 1 else None,
                            "raw": l[:60]})
    # не resolved — отмечаем как unknown
    for p in pending:
        events.append({**p, "team": "unknown"})
    return events

def render_post(ev, sc_h, sc_a, our_goal):
    if our_goal:
        assist_line = f"🎯 Голевой пас: {ev['assist']}\n" if ev.get("assist") else ""
        return (f"🔥⚽️ <b>Г-О-О-О-Л! 🔥⚽️</b>\n\n"
                f"⚽ <b>АВТОР ГОЛА: {ev['player']}</b> 🌟\n"
                + assist_line +
                f"⏱ На {ev['minute']}' минуте!\n\n"
                f"Счёт: <b>{sc_h} : {sc_a}</b> в нашу пользу! 🎉")
    return (f"😢 <b>Пропускаем...</b> 😢\n\n"
            f"На {ev['minute']}' минуте соперник забивает.\n\n"
            f"Счёт: <b>{sc_h} : {sc_a}</b>. Не сдаёмся! 💪")

def main():
    md = jina(MATCH_URL)
    if not md:
        send("🧪 ТЕСТ: страница не скачалась")
        return

    # Кто дома, кто в гостях — из заголовка страницы
    title = md.splitlines()[0] if md else ""
    sides = re.search(r"матча\s+(.+?)\s+\d+\s*[-–]\s*\d+\s+(.+?),", title)
    if not sides:
        sides = re.search(r"матча\s+(.+?)\s+(FC ITPROVIDER)\b", title)
    home_team = sides.group(1).strip() if sides else "?"
    away_team = sides.group(2).strip() if sides else "?"
    we_are_home = "ITPROVIDER" in home_team.upper()

    events = parse_events(md)

    # Разбираем минуту по твоей логике: NN' SS'' → +1, если SS > 00
    for ev in events:
        rm = re.search(r"(\d{1,3})'\s*(\d{2})''", ev.get("raw", ""))
        m_raw = int(rm.group(1)) if rm else 0
        s_raw = int(rm.group(2)) if rm else 0
        ev["minute"] = m_raw + 1 if s_raw > 0 else m_raw

    report = [f"🧪 <b>ТЕСТ финального парсера</b> — {MATCH_URL}",
              f"Дома: {home_team} | В гостях: {away_team}",
              f"Мы играем: {'дома' if we_are_home else 'в гостях'}",
              f"Событий распознано: {len(events)}\n"]

    sc_h, sc_a = 0, 0
    for ev in events:
        our = (ev["team"] == "home") == we_are_home and ev["team"] != "unknown"
        if ev["team"] == "home":
            sc_h += 1
        elif ev["team"] == "away":
            sc_a += 1
        if our:
            sc_h = sc_h if ev["team"] == "home" else sc_h
            sc_a = sc_a if ev["team"] == "away" else sc_a
        report.append(f"⚽ {ev['minute']}' — {ev['player']}"
                      + (f" (пас: {ev['assist']})" if ev.get("assist") else "")
                      + f" → счёт {sc_h}:{sc_a} [{ev['team']}]")

    report.append(f"\n<b>Итог по протоколу: {sc_h} : {sc_a}</b>")

    # Показываем, как будет выглядеть пост про гол
    if events:
        ev = events[0]
        sc_h, sc_a = 0, 0
        our = (ev["team"] == "home") == we_are_home and ev["team"] != "unknown"
        if ev["team"] == "home":
            sc_h = 1
        elif ev["team"] == "away":
            sc_a = 1
        report.append("\n<b>Пример поста в воскресенье:</b>")
        report.append(render_post(ev, sc_h, sc_a, our))

    send("\n".join(report))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        send("🚨 Ошибка теста:\n<pre>" +
             traceback.format_exc()[-3000:].replace("&", "&amp;").replace("<", "&lt;") +
             "</pre>")
        raise
