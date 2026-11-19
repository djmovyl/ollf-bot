import os, re, requests, traceback
from datetime import datetime, timedelta, timezone

TOKEN   = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
MATCH_URL = "https://ollf.ru/match/5905503"
HOME = "FC ITPROVIDER"

MSK = timezone(timedelta(hours=3))

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

MONTHS = {"ЯНВ":1,"ФЕВ":2,"МАР":3,"АПР":4,"МАЙ":5,"ИЮН":6,
          "ИЮЛ":7,"АВГ":8,"СЕН":9,"ОКТ":10,"НОЯ":11,"ДЕК":12}

# Попытка 1: строка вида «23' Бакиров Ленар (Кажев Марат) FC ITPROVIDER»
# Попытка 2: любой фрагмент «NN' ... имя ... команда»
def try_patterns(md):
    found = []
    # P1: минута в кавычках, потом всё до конца строки/ссылки
    p1 = re.compile(r"(\d{1,3})'\s+([^\n]{5,120})")
    for m in p1.finditer(md):
        found.append({"pat": "P1", "minute": int(m.group(1)), "rest": m.group(2).strip()})
    # P2: «гол» на строке — ловим контекст
    for m in re.finditer(r"[^\n]*[Гг]ол[^\n]*", md):
        found.append({"pat": "P2-гол-строка", "minute": None, "rest": m.group(0).strip()[:150]})
    return found

def main():
    md = jina(MATCH_URL)
    if not md:
        send("🧪 ТЕСТ: страница матча не скачалась (Jina вернул пусто)")
        return

    report = [f"🧪 <b>ТЕСТ парсера</b> на матче {MATCH_URL}",
              f"Размер текста: {len(md)} символов\n"]

    # Что вообще есть на странице про счёт и события
    score_hits = re.findall(r"\d+\s*[-–:]\s*\d+", md)[:10]
    report.append("🔢 Вхождения счёта: " + (", ".join(score_hits) if score_hits else "не найдено"))

    events = try_patterns(md)
    if events:
        report.append(f"\n📋 Найдено {len(events)} кандидатов в события (первые 15):")
        for e in events[:15]:
            report.append(f"[{e['pat']}] {e['minute'] if e['minute'] is not None else '—'}' {e['rest'][:100]}")
    else:
        report.append("\n⚠️ Кандидатов в события не найдено — нужен сырой текст")

    # Сырой фрагмент вокруг каждого упоминания «гол» и вокруг ITPROVIDER — чтобы увидеть реальный формат
    frags = []
    for kw in ["гол", "Гол", "ГОЛ", "забил", "автогол", "ITPROVIDER"]:
        i = md.find(kw)
        if i > 0:
            frags.append(f"--- вокруг «{kw}» ---\n{md[max(0,i-200):i+300]}")
    body = "\n\n".join(frags[:3]) if frags else md[:1500]

    send("\n".join(report) + "\n\n<b>Сырые фрагменты:</b>\n<pre>" +
         body.replace("&", "&amp;").replace("<", "&lt;")[:2500] + "</pre>")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        send("🚨 Ошибка тест-бота:\n<pre>" +
             traceback.format_exc()[-3000:].replace("&", "&amp;").replace("<", "&lt;") +
             "</pre>")
        raise
