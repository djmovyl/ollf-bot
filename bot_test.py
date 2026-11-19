import os
import re
import requests
import traceback

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
MATCH_URL = "https://ollf.ru/match/5905503"
HOME = "FC ITPROVIDER"

def tg(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", data=params, timeout=20)
    return r.json()

def send(text):
    res = tg("sendMessage", chat_id=CHANNEL, text=text[:3900], parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)

def jina(url):
    try:
        r = requests.get("https://r.jina.ai/" + url, timeout=60)
        print("jina:", url, "->", r.status_code, len(r.text))
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print("jina error:", e)
        return ""

# Парсер событий: собирает строки с минутами и изменения счёта, потом сопоставляет по порядку
def parse_events(md):
    lines = [l.strip() for l in md.splitlines() if l.strip()]
    
    # Шаблон для строк с минутами: NN' SS'' [Имя Фамилия] [Ассист]
    event_pat = re.compile(r"(\d{1,3})'\s*(\d{2})''\s*\[([^\]]+)\](?:\s*\[([^\]]+)\])?")
    
    events = []
    scores = []

    # Сначала собираем все события и все изменения счёта
    for l in lines:
        # Ищем события
        m_ev = event_pat.search(l)
        if m_ev:
            minute_raw = int(m_ev.group(1))
            seconds = int(m_ev.group(2))
            player = m_ev.group(3)
            assist = m_ev.group(4)
            # Твоя логика: если секунды > 0 — это уже следующая минута
            minute = minute_raw + 1 if seconds > 0 else minute_raw
            events.append({
                "minute": minute,
                "player": player,
                "assist": assist,
                "raw": l
            })

        # Ищем изменения счёта: "X : Y"
        m_sc = re.search(r"\b(\d+)\s*[:\-]\s*(\d+)\b", l)
        if m_sc:
            scores.append((int(m_sc.group(1)), int(m_sc.group(2))))

    # Теперь сопоставляем события и счёт по порядку: первое событие — первое изменение счёта и т.д.
    combined = []
    for i, ev in enumerate(events):
        h, a = scores[i] if i < len(scores) else (0, 0)
        combined.append({**ev, "score_home": h, "score_away": a})
    
    return combined

def render_post(ev, our_goal):
    if our_goal:
        assist_line = f"🎯 Голевой пас: {ev['assist']}\n" if ev.get("assist") else ""
        return (f"🔥⚽️ <b>Г-О-О-О-Л! 🔥⚽️</b>\n\n"
                f"⚽ <b>АВТОР ГОЛА: {ev['player']}</b> 🌟\n"
                + assist_line +
                f"⏱ На {ev['minute']}' минуте!\n\n"
                f"Счёт: <b>{ev['score_home']} : {ev['score_away']}</b> в нашу пользу! 🎉")
    return (f"😢 <b>Пропускаем...</b> 😢\n\n"
            f"На {ev['minute']}' минуте соперник забивает.\n\n"
            f"Счёт: <b>{ev['score_home']} : {ev['score_away']}</b>. Не сдаёмся! 💪")

def main():
    md = jina(MATCH_URL)
    if not md:
        send("🧪 ТЕСТ: страница не скачалась")
        return

    # Пытаемся вытащить названия команд из заголовка
    title = md.splitlines()[0] if md else ""
    sides = re.search(r"матча\s+(.+?)\s+\d+\s*[-–]\s*\d+\s+(.+?),", title)
    home_team = sides.group(1).strip() if sides else "?"
    away_team = sides.group(2).strip() if sides else "?"
    we_are_home = "ITPROVIDER" in home_team.upper()

    events = parse_events(md)

    report = [
        f"🧪 <b>ТЕСТ финального парсера</b> — {MATCH_URL}",
        f"Дома: {home_team} | В гостях: {away_team}",
        f"Мы играем: {'дома' if we_are_home else 'в гостях'}",
        f"Событий распознано: {len(events)}\n"
    ]

    sc_h, sc_a = 0, 0
    for ev in events:
        report.append(f"⚽ {ev['minute']}' — {ev['player']}"
                      + (f" (пас: {ev['assist']})" if ev.get("assist") else "")
                      + f" → счёт {ev['score_home']}:{ev['score_away']}")
        sc_h = ev['score_home']
        sc_a = ev['score_away']

    report.append(f"\n<b>Итог по протоколу: {sc_h} : {sc_a}</b>")

    # Пример поста для первого события
    if events:
        ev = events[0]
        our_goal = (ev["score_home"] > 0 and we_are_home) or (ev["score_away"] > 0 and not we_are_home)
        report.append("\n<b>Пример поста в воскресенье:</b>")
        report.append(render_post(ev, our_goal))

    send("\n".join(report))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        send("🚨 Ошибка теста:\n<pre>" +
             traceback.format_exc()[-3000:].replace("&", "&amp;").replace("<", "&lt;") +
             "</pre>")
        raise
