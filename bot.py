import requests, re

TOKEN = os.environ["BOT_TOKEN"]
CHAT  = os.environ["CHANNEL"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

def send(text):
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                     params={"chat_id": CHAT, "text": text[:3900]}, timeout=20)
    print(r.text)

report = []

def check(name, url, ua=None):
    h = dict(HEADERS)
    if ua:
        h["User-Agent"] = ua
    try:
        r = requests.get(url, headers=h, timeout=25)
        body = r.text
        clean = re.sub(r"<[^>]+>", " ", body)
        report.append(
            f"{name}\n  статус: {r.status_code}, размер: {len(body)}\n"
            f"  есть ITPROVIDER: {'ITPROVIDER' in body}\n"
            f"  есть счёт 3-4: {bool(re.search(r'3\\s*[–-]\\s*4', body))}\n"
            f"  есть слово «События»: {'События' in body}\n"
            f"  есть слово «Протокол»: {'Протокол' in body}"
        )
        i = clean.find("События")
        if i > 0:
            report.append("  фрагмент: " + clean[i:i+300])
    except Exception as e:
        report.append(f"{name}\n  ОШИБКА: {e}")

check("1. Матч, браузерный UA",  "https://ollf.ru/match/5905503")
check("2. Матч, UA поисковика",  "https://ollf.ru/match/5905503",
      ua="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")
check("3. Матч с вкладкой События", "https://ollf.ru/match/5905503?active=broadcast")
check("4. Страница турнира",     "https://ollf.ru/tournament/1067343")

send("📋 Отчёт диагностики ОЛЛФ:\n\n" + "\n\n".join(report))
