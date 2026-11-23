# -*- coding: utf-8 -*-
"""postgen.py — генератор постов FC ITPROVIDER (голы, ассисты, милстоуны,
карточки, автоголы) + кэш сезонной статистики со страницы заявки ОЛЛФ."""

import re
import random
from datetime import date

SEP = "─" * 40
EARLY_MIN = 3    # до 3-й минуты включительно — ранний гол
LATE_MIN = 35    # с 35-й минуты — концовка (матч 2x20)

TEAM_STATS_URL = ("https://ollf.ru/tournament/1067343/teams/"
                  "application?team_id=1381365")

# ================= КЛИШЕ (финальные строки) =================
CLOSERS = {
    # --- мы забили ---
    "pride_goal": [
        "Гол престижа — но мы не об этом думаем. Играем!",
        "Одно в счёт, второе — в борьбу. Вернёмся!",
        "Такие мячи придают веры. Продолжаем!",
        "Записали — и не останавливаемся!"],
    "comeback_level": [
        "Кто верил — тот не зря верил!",
        "Счёт равный — и всё ещё в наших руках!",
        "Отыгрались? Теперь забираем больше!",
        "Равный счёт — наш стиль. Дальше — вперёд!"],
    "comeback_ahead": [
        "Отыгрались — и вышли вперёд! Это наш матч!",
        "Такие камбэки запоминаются на сезон!",
        "Не оставляем сопернику шансов на спокойствие!",
        "Вели тяжёлую игру — теперь ведём счёт!"],
    "closing_gap": [
        "Каждый гол — шаг к победе!",
        "Сократили разрыв? Теперь его закроем!",
        "Продолжаем давить — пока не выйдем вперёд!",
        "Идём по счёту дальше — и не останавливаемся!"],
    "fresh": [
        "Затишье закончилось — и в нашу пользу!",
        "Очнулись в нужный момент!",
        "Тишина на поле — но не в счёте!",
        "Держали удар — и ответили!"],
    "early_lead": [
        "Первый гол — самый важный. Есть!",
        "Быстрый гол — хороший знак!",
        "Забрали инициативу с первых минут!",
        "Начало положено — продолжаем в том же духе!"],
    "leading_mid": [
        "Контроль в наших руках. Продолжаем давить!",
        "Держим темп — не расслабляемся!",
        "Игра идёт по нашему плану!",
        "Разница небольшая, но инициатива наша!"],
    "dominating": [
        "Контролируем всё — поле, темп, счёт!",
        "Соперник уже не верит в камбэк!",
        "Разрываем игру на части!",
        "Так и живём — в чужой штрафной!"],
    "ahead_late": [
        "Держим счёт до сирены!",
        "Последние минуты — наше время!",
        "Ни секунды расслабления — но счёт за нами!",
        "Дожимаем — и не отдаём!"],
    "lead_restored": [
        "Вернули своё! И не отдаём!",
        "Счёт снова наш — так и должно быть!",
        "Быстро исправились!",
        "Ответили моментально!"],
    # --- пропустили ---
    "early_trail": [
        "Впускаем первым — и отыгрываемся красиво. Классика.",
        "Рано волноваться — матч только начался!",
        "Первый гол не решает исход!",
        "Спокойно! Это первая строчка сценария — и сюжет ещё наш!"],
    "mid_trail": [
        "Один мяч — не проблема. Это задача на ближайшие минуты.",
        "Отстаём — значит, пора прибавить!",
        "Пропустили — не значит проиграли!",
        "Время есть. План тот же: забивать!"],
    "pushing": [
        "Хватит дарить. Дальше — только наша игра!",
        "Собираемся и играем смелее!",
        "Пока не поздно — возвращаемся в матч!",
        "Два пропущенных — сигнал проснуться!"],
    "angry": [
        "Счёт горит — значит, играть можно смелее.",
        "Время злости закончилось — время борьбы началось!",
        "Пропускаем, но не сдаёмся!",
        "Хватит смотреть — надо отвечать!"],
    "crushed": [
        "Мяч за мячом. До последней секунды.",
        "Пропускаем, но не сдаёмся. Каждый гол — это бой.",
        "Тяжело — но продолжаем играть!",
        "Счёт не приговор, пока звучит сирена!"],
    "behind_late": [
        "Догоняем до финальной сирены. До самой сирены!",
        "Концовка — наше время. Ищем гол!",
        "Пока звучит свисток — есть шанс!",
        "Последние минуты — самая наша музыка!"],
    "lost_lead": [
        "Вели — и упустили. Вернём!",
        "Ничего не потеряно — всё ещё в наших руках!",
        "Быстро исправим эту ошибку!",
        "Счёт равный — но характер наш!"],
    "restoring_lead": [
        "Опасно близко. Соберёмся!",
        "Отрыв тает — прибавляем!",
        "Соперник кусается — держим удар!",
        "Держим счёт — и не отдаём!"],
    "exchange_c": [
        "Соперник отвечает быстро — ответим быстрее!",
        "Качели продолжаются — кто выдержит?",
        "Обмен голами — но последнее слово за нами!",
        "Такие матчи любят зрители — а мы любим побеждать!"],
    "fresh_c": [
        "Затишье закончилось — и не в нашу пользу.",
        "Очнулись — а счёт уже не наш. Возвращаем!",
        "Долгая пауза сыграла с нами шутку. Исправим!",
        "Пора просыпаться — играем!"],
}

# ================= КЛАССИФИКАТОР СИТУАЦИЙ =================
def classify_goal(scored, our, opp, prev_our, prev_opp, minute,
                  prev_goal, we_led_before, minutes_since):
    """scored: True — забили, False — пропустили.
    minutes_since: минут с прошлого гола; None — первое событие матча
    (fresh не применяется)."""
    diff = our - opp
    prev_diff = prev_our - prev_opp
    early = minute <= EARLY_MIN
    late = minute >= LATE_MIN

    if scored:
        if diff > 0 or (diff == 0 and prev_goal == "conceded"
                        and prev_diff < diff):
            # отыгрыш после пропущенного (проверяется первым)
            if prev_goal == "conceded" and prev_diff < diff:
                if prev_our == 0 and diff <= -3:
                    return "pride_goal"
                if prev_diff <= -2 and diff == 0:
                    return "comeback_level"
                if prev_diff <= -2 and diff > 0:
                    return "comeback_ahead"
                return "closing_gap"
            if late:
                return "ahead_late"
            if diff >= 3:
                return "dominating"
            if early:
                return "early_lead"
            if we_led_before and prev_diff < diff and prev_diff <= 0:
                return "lead_restored"
            return "leading_mid"
        return "fresh"
    # --- пропустили ---
    if prev_goal is None:
        # первый гол матча: соперник открывает счёт
        return "behind_late" if late else "early_trail"
    if we_led_before and diff <= 0:
        return "lost_lead"
    if prev_goal == "scored" and diff > 0:
        return "restoring_lead"
    if prev_goal == "scored" and minutes_since is not None \
            and minutes_since < 5:
        return "exchange_c"
    if diff > 0:
        return "restoring_lead"
    if late:
        return "behind_late"
    if diff <= -4:
        return "crushed"
    if diff == -3:
        return "angry"
    if diff == -2:
        return "pushing"
    if minutes_since is not None and minutes_since >= 10:
        return "fresh_c"
    if early:
        return "early_trail"
    return "mid_trail"

# ================= СТАТИСТИКА СТРАНИЦЫ ЗАЯВКИ =================
# ВАЖНО: скобки собираются из кодов символов, чтобы строка не обрывалась
# при копировании кода из чата (квадратные скобки там съедались как
# маркдаун-ссылка — отсюда были SyntaxError на этой строке).
LB = chr(91)
RB = chr(93)
LP = chr(40)
RP = chr(41)

def _flatten_md(s):
    """Маркдаун в плоский текст: ссылки -> текст, таблицные | -> пробелы.
    Цикл вместо регэкспа — без квадратных скобок в исходнике."""
    s = s.replace("|", " ")
    while True:
        a = s.find(LB)
        if a < 0:
            break
        b = s.find(RB, a + 1)
        if b < 0:
            break
        c = s.find(LP, b + 1)
        d = s.find(RP, c + 1) if c >= 0 else -1
        if c < 0 or d < 0:
            break
        start = a - 1 if a > 0 and s[a - 1] == chr(33) else a
        s = s[:start] + s[a + 1:b] + s[d + 1:]
    return s

def _num(s):
    s = (s or "").strip()
    return int(s) if s.isdigit() else 0

# Строка заявки: 'Фамилия Имя ДД.ММ.ГГГГ, N лет(год/года) И Г П ЖК КК'.
# Возраст пропускаем опционально, прочерки (в т.ч. длинные тире) в цифрах
NUMCLS = LP + LB + r"\d\-\u2013\u2014" + RB + RP
SQUAD_ROW_RE = re.compile(
    LP + LB + "А-ЯЁ" + RB + LB + "а-яё" + RB + "+ " + LB + "А-ЯЁ" + RB
    + LB + "а-яё" + RB + "+" + RP + r"\s+"
    + r"\d{2}\.\d{2}\.\d{4}\s*(?:,\s*\d+\s*год\S*)?\s*"
    + NUMCLS + r"\s+" + NUMCLS + r"\s+" + NUMCLS + r"\s+"
    + NUMCLS + r"\s+" + NUMCLS)

def parse_squad_stats(text):
    flat = _flatten_md(text or "")
    players = {}
    for m in SQUAD_ROW_RE.finditer(flat):
        players[m.group(1)] = {
            "games": _num(m.group(2)), "goals": _num(m.group(3)),
            "assists": _num(m.group(4)), "yellow": _num(m.group(5)),
            "red": _num(m.group(6))}
    return players

def sync_season_stats(state, fetch, force=False, match_url=""):
    """Синк кэша со страницы заявки: раз в день; force — после матча.
    fetch — jina(url, must_contain=...). При сбое кэш не затираем."""
    today = date.today().isoformat()
    if not force and state.get("stats_synced_at") == today:
        return state.get("season_stats", {})
    try:
        text = fetch(TEAM_STATS_URL, must_contain="teams/application")
    except Exception:
        return state.get("season_stats", {})
    fresh = parse_squad_stats(text or "")
    if fresh:
        state["season_stats"] = fresh
        state["stats_synced_at"] = today
        print("Заявка:", len(fresh), "игроков распознано")
    if force and match_url:
        lst = state.setdefault("stats_synced_match_urls", [])
        if match_url not in lst:
            lst.append(match_url)
    return state.get("season_stats", {})

def find_player(season_stats, protocol_name):
    if not protocol_name:
        return None
    if protocol_name in season_stats:
        return protocol_name
    surname = protocol_name.split()[0]
    matches = [n for n in season_stats if n.startswith(surname)]
    return matches[0] if len(matches) == 1 else None

def season_count(state, player, kind, match_extra, match_url=""):
    base = find_player(state.get("season_stats", {}), player)
    if base is None:
        return None
    n = state["season_stats"][base].get(kind, 0)
    if match_url and match_url in state.get("stats_synced_match_urls", []):
        return n
    return n + match_extra

# ================= КАРКАСЫ: НАШ ГОЛ =================
SCORED_TEMPLATES = [
    "🔥 ГО-О-О-Л!\n\nНа {minute}' минуте отличился {scorer}!{scorer_stat}\n"
    "🎯 Голевой пас: {assister}{assist_stat}\nСчёт: <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}",
    "⚽ ЕСТЬ ГОЛ!\n\n{scorer} забивает на {minute}' минуте!{scorer_stat}\n"
    "🎯 Голевой пас: {assister}{assist_stat}\nСчёт: <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}",
    "💥 ЗАБИВАЕМ!\n\nАвтор мяча — {scorer}.{scorer_stat}\n"
    "🎯 Голевой пас: {assister}{assist_stat}\n"
    "На {minute}' минуте счёт стал <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}",
    "🎉 ТАБЛО ОБНОВЛЯЕТСЯ!\n\nГол на счету {scorer} — {minute}' минута."
    "{scorer_stat}\n🎯 Голевой пас: {assister}{assist_stat}\n"
    "Счёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "✨ ОТЛИЧНОЕ ИСПОЛНЕНИЕ!\n\nНа {minute}' минуте мяч в воротах соперника."
    "\n⚽ Автор: {scorer}{scorer_stat}\n🎯 Ассист: {assister}{assist_stat}\n"
    "Счёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "🚀 ЕЩЁ ОДИН В НАШУ КОПИЛКУ!\n\n{scorer} забивает — {minute}' минута."
    "{scorer_stat}\n🎯 Пас отдал: {assister}{assist_stat}\n"
    "Счёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "⚡ ТОЧНО В ЦЕЛЬ!\n\nНа {minute}' минуте {scorer} записывает гол."
    "{scorer_stat}\n🎯 Голевой пас: {assister}{assist_stat}\n"
    "Счёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "💪 НАШ ГОЛ!\n\n{scorer} отличился на {minute}' минуте.{scorer_stat}\n"
    "🎯 Голевой пас: {assister}{assist_stat}\nТабло: <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}",
    "🔥 ОЧЕРЕДНОЙ МЯЧ!\n\nГол забит на {minute}' минуте.\n"
    "⚽ Автор: {scorer}{scorer_stat}\n"
    "🎯 Голевой пас: {assister}{assist_stat}\nСчёт: <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}",
    "🎯 В СЕТКУ!\n\n{scorer} забивает — {minute}' минута матча."
    "{scorer_stat}\n🎯 Голевой пас: {assister}{assist_stat}\n"
    "Счёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "💥 СНОВА В ДЕЛЕ!\n\nНа {minute}' минуте отличился {scorer}."
    "{scorer_stat}\n🎯 Голевой пас: {assister}{assist_stat}\n"
    "Табло: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "⚽ МЯЧ В ВОРОТАХ СОПЕРНИКА!\n\nГол на {minute}' минуте — автор "
    "{scorer}.{scorer_stat}\n🎯 Голевой пас: {assister}{assist_stat}\n"
    "Счёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}"]

SCORED_SOLO_TEMPLATES = [
    "⚽ ГОЛ!\n\nНа {minute}' минуте отличился {scorer}!{scorer_stat}\n"
    "Счёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "🎯 ТОЧНО В ЦЕЛЬ!\n\n{scorer} записывает мяч на свой счёт."
    "{scorer_stat}\nМинута: {minute}'. Счёт: <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}",
    "⚡ ГОЛ! Есть!\n\n{scorer} забивает на {minute}' минуте.{scorer_stat}\n"
    "Счёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "💥 ЗАНОСИМ В АКТИВ!\n\nГол на счету {scorer}.{scorer_stat}\n"
    "Минута: {minute}'. Счёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "🔥 ОЧЕРЕДНОЙ ГОЛ!\n\n{scorer} снова в списке авторов.{scorer_stat}\n"
    "На {minute}' минуте счёт стал <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}",
    "🎉 ТАБЛО ОБНОВЛЯЕТСЯ!\n\nГол забит: {scorer}.{scorer_stat}\n"
    "Минута: {minute}'. Теперь на табло <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}",
    "✨ ЕСТЬ МЯЧ!\n\nАвтор — {scorer}.{scorer_stat}\n"
    "На {minute}' минуте счёт стал <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}",
    "🚀 ГОЛ В НАШУ КОПИЛКУ!\n\n{scorer} делает счёт <b>{our}:{opp}</b> "
    "на {minute}' минуте.{scorer_stat}\n" + SEP + "\n\n{closer}"]

CONCEDED_TEMPLATES = {
    "early_trail": [
        "🥅 ПРОПУСКАЕМ ПЕРВЫМИ.\n\nНа {minute}' минуте соперник открывает "
        "счёт.\nСчёт: <b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}",
        "🥅 ПЕРВЫЙ ГОЛ В НАШЕЙ СЕТКЕ.\n\nСоперник забивает на {minute}' — "
        "счёт становится <b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}"],
    "mid_trail": [
        "🥅 ПРОПУСКАЕМ.\n\nНа {minute}' соперник делает счёт "
        "<b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}",
        "🥅 ГОЛ В НАШИ ВОРОТА.\n\nНа {minute}' счёт становится "
        "<b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}"],
    "pushing": [
        "🥅 ВТОРОЙ ПОДРЯД — НЕ ПО ПЛАНУ.\n\nНа {minute}' соперник делает "
        "счёт <b>{our}:{opp}</b>. Нужно перехватывать инициативу.\n"
        + SEP + "\n\n{closer}",
        "🥅 НЕ ДАЁМ СЕБЕ РАССЛАБИТЬСЯ.\n\nГол на {minute}' — счёт "
        "<b>{our}:{opp}</b>. Дальше играем только вперёд.\n"
        + SEP + "\n\n{closer}"],
    "angry": [
        "🥅 СЧЁТ РАСТЁТ — ВРЕМЯ ДЕЙСТВОВАТЬ.\n\nНа {minute}' соперник "
        "делает счёт <b>{our}:{opp}</b>. Нужно отвечать голами.\n"
        + SEP + "\n\n{closer}",
        "🥅 НЕ ВРЕМЯ СДАВАТЬСЯ.\n\nГол на {minute}' — счёт "
        "<b>{our}:{opp}</b>. Играем до конца.\n" + SEP + "\n\n{closer}"],
    "crushed": [
        "🥅 ТЯЖЁЛЫЙ МОМЕНТ.\n\nНа {minute}' соперник делает счёт "
        "<b>{our}:{opp}</b>. Не опускаем руки — впереди ещё минуты.\n"
        + SEP + "\n\n{closer}",
        "🥅 МЯЧ В СЕТКЕ — СОБИРАЕМСЯ.\n\nГол на {minute}' — счёт "
        "<b>{our}:{opp}</b>. Продолжаем бороться.\n" + SEP + "\n\n{closer}"],
    "behind_late": [
        "🥅 ДО КОНЦА ОСТАЛИСЬ МИНУТЫ.\n\nНа {minute}' соперник делает счёт "
        "<b>{our}:{opp}</b>. Доигрываем до финальной сирены.\n"
        + SEP + "\n\n{closer}",
        "🥅 ПОСЛЕДНИЕ МИНУТЫ — НЕ СДАЁМСЯ.\n\nГол на {minute}' — счёт "
        "<b>{our}:{opp}</b>. До конца матча ещё есть время.\n"
        + SEP + "\n\n{closer}"],
    "lost_lead": [
        "🥅 УПУСТИЛИ ПРЕИМУЩЕСТВО.\n\nНа {minute}' соперник меняет картину "
        "матча. Счёт: <b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}",
        "🥅 ОБИДНЫЙ ПОВОРОТ.\n\nГол соперника на {minute}' — счёт "
        "<b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}"],
    "restoring_lead": [
        "🥅 СОПЕРНИК СОКРАЩАЕТ ОТРЫВ.\n\nНа {minute}' счёт становится "
        "<b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}",
        "🥅 НЕ РАССЛАБЛЯЕМСЯ.\n\nГол на {minute}' — счёт "
        "<b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}"],
    "exchange_c": [
        "🥅 МГНОВЕННЫЙ ОТВЕТ СОПЕРНИКА.\n\nНа {minute}' счёт становится "
        "<b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}",
        "🥅 КАЧЕЛИ ПРОДОЛЖАЮТСЯ.\n\nГол на {minute}' — счёт "
        "<b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}"],
    "fresh_c": [
        "🥅 ЗАТИШЬЕ ЗАКОНЧИЛОСЬ ГОЛОМ СОПЕРНИКА.\n\nНа {minute}' счёт "
        "становится <b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}",
        "🥅 ОЧНУЛИСЬ — А СЧЁТ УЖЕ НЕ НАШ.\n\nГол на {minute}' — счёт "
        "<b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}"]}

# ================= МИЛСТОУНЫ =================
MILESTONE_GOAL_NAMES = {2: "ДУБЛЬ", 3: "ХЕТ-ТРИК", 4: "ПОКЕР",
                        5: "ПЕНТА-ТРИК"}
MILESTONE_GOAL_LOWER = {2: "дубль", 3: "хет-трик", 4: "покер",
                        5: "пента-трик"}
MILESTONE_ASSIST_LOWER = {2: "ассистентский дубль",
                          3: "ассистентский хет-трик",
                          4: "ассистентский покер",
                          5: "ассистентский пента-трик"}

CLOSERS["milestone_g2"] = [
    "Дубль оформлен — но матч ещё не закончен!",
    "Два мяча — это характер!",
    "Один мяч — хорошо, два — лучше!"]
CLOSERS["milestone_g3"] = [
    "Хет-трик! Легенда этого вечера!",
    "Три мяча — это уже история!",
    "Шляпа надета — продолжаем!"]
CLOSERS["milestone_g4"] = [
    "Покер! Фантастика на поле!",
    "Четыре мяча — вне всяких рамок!",
    "Это уже не матч — это шоу!"]
CLOSERS["milestone_g5"] = [
    "Пента-трик! Легенда вечера!",
    "Пять мячей — это уже легенда!",
    "Пять — и это не предел!"]
CLOSERS["milestone_g6"] = ["Шесть и больше — пусть пишут в протоколе!"]
CLOSERS["milestone_a2"] = [
    "Ассистентский дубль — партнёрам повезло с пасом!",
    "Две передачи — мозг команды!"]
CLOSERS["milestone_a3"] = [
    "Ассистентский хет-трик! Маэстро паса!",
    "Не забивает — но решает всё!"]
CLOSERS["milestone_a4"] = ["Покер ассистента — фантастика!"]
CLOSERS["milestone_a5"] = ["Пента-ассист — легенда вечера!"]

MILESTONE_G_TEMPLATES = [
    "🎩 {ms_name}!\n\n{scorer} оформляет {ms_lower} — {n}-й мяч в этом "
    "матче!{scorer_stat}{assist_line}\nСчёт: <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}",
    "💥 {ms_name}!\n\n{n}-й мяч в этом матче на счету {scorer}!"
    "{scorer_stat}{assist_line}\nМинута: {minute}'. "
    "Счёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "🔥 {ms_name}!\n\n{scorer} продолжает поражать — теперь {n} {n_word} "
    "за матч!{scorer_stat}{assist_line}\nТабло: <b>{our}:{opp}</b>\n"
    + SEP + "\n\n{closer}"]

MILESTONE_A_TEMPLATES = [
    "🎯 ГОЛЕВОЙ ПАС В ДЕЛЕ!\n\n{scorer} забивает на "
    "{minute}' минуте — а {assister} раздаёт: {assist_ms} в этом матче!"
    "{assist_stat}\nСчёт: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}",
    "🧠 РАЗДАЮТ МЯЧИ!\n\n{scorer} оформляет гол на {minute}' минуте, "
    "{assist_ms} — на счету {assister}!{assist_stat}\n"
    "Табло: <b>{our}:{opp}</b>\n" + SEP + "\n\n{closer}"]

# ================= КАРТОЧКИ =================
CARD_TEMPLATES = {
    "yellow_our": [
        "🟡 ЖЁЛТАЯ КАРТОЧКА У НАС.\n\n{player} получает предупреждение "
        "на {minute}' минуте.\n\n{closer}",
        "🟡 ПРЕДУПРЕЖДЕНИЕ.\n\nНа {minute}' минуте жёлтую карточку "
        "получает {player}.\n\n{closer}"],
    "yellow_opp": [
        "🟡 ЖЁЛТАЯ КАРТОЧКА У СОПЕРНИКА.\n\nПредупреждение на "
        "{minute}' минуте.\n\n{closer}",
        "🟡 СОПЕРНИК ПОЛУЧАЕТ ЖЁЛТУЮ.\n\nМинута: {minute}'.\n\n{closer}"],
    "red_our": [
        "🚨 КРАСНАЯ КАРТОЧКА У НАС.\n\n{player} покидает поле на "
        "{minute}' минуте.\n\n{closer}",
        "🚨 УДАЛЕНИЕ.\n\n{player} получает красную на {minute}' минуте."
        "\n\n{closer}"],
    "red_opp": [
        "🚨 КРАСНАЯ КАРТОЧКА У СОПЕРНИКА!\n\nУдаление на {minute}' "
        "минуте.\n\n{closer}"],
    "two_yellows": [
        "🟥 ДВЕ ЖЁЛТЫЕ — КРАСНАЯ.\n\n{player} покидает поле: вторая "
        "жёлтая на {minute}' минуте.\n\n{closer}"]}
CLOSERS["card_yellow_our"] = [
    "Держим голову холодной — впереди ещё игра!",
    "Дисциплина важнее эмоций!",
    "Аккуратнее в следующих эпизодах!"]
CLOSERS["card_yellow_opp"] = [
    "Сопернику тоже горячо — используем!",
    "Давим, пока они нервничают!"]
CLOSERS["card_red_our"] = [
    "Соберёмся ещё крепче — играем в меньшинстве!",
    "Тяжело, но не отступаем!",
    "Играем компактнее — держим оборону!"]
CLOSERS["card_red_opp"] = [
    "Наш шанс — дожимаем!",
    "Численный перевес — используем на максимум!"]
CLOSERS["card_two_yellows"] = [
    "Учимся на ошибках — и играем дальше!"]

# ================= АВТОГОЛЫ =================
AUTOGOAL_OUR_TEMPLATES = [
    "⚽ АВТОГОЛ — В НАШУ ПОЛЬЗУ!\n\nНа {minute}' минуте соперник срезает "
    "мяч в свои ворота.\nСчёт: <b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}",
    "🔄 ПОДАРОК ОТ СОПЕРНИКА!\n\nАвтогол на {minute}' минуте — счёт "
    "становится <b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}",
    "🎉 ГОЛ ЗАСЧИТАН В НАШУ ПОЛЬЗУ!\n\nНа {minute}' минуте мяч после "
    "рикошета оказывается в сетке ворот соперника. "
    "Счёт: <b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}"]
AUTOGOAL_AGAINST_TEMPLATES = [
    "🥅 НЕУДАЧНЫЙ РИКОШЕТ.\n\nАвтогол в наши ворота на {minute}' минуте."
    "\nСчёт: <b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}",
    "🥅 МЯЧ В СЕТКЕ — АВТОГОЛ.\n\nНа {minute}' минуте гол засчитан "
    "сопернику.\nСчёт: <b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}",
    "🥅 ТАКОЕ БЫВАЕТ.\n\nАвтогол на {minute}' минуте — счёт становится "
    "<b>{our}:{opp}</b>.\n" + SEP + "\n\n{closer}"]
CLOSERS["autogoal_our"] = [
    "Гол есть гол — записываем!",
    "Удача сегодня на нашей стороне!",
    "Не важно как — важно что! Засчитано!"]
CLOSERS["autogoal_against"] = [
    "Бывает. Никого не виним — идём дальше!",
    "Собираемся и продолжаем борьбу!",
    "Такие мячи случаются у всех. Двигаемся вперёд!"]

# ================= ВЫБОР БЕЗ ПОВТОРОВ =================
def pick_tpl(state, pool):
    pool = list(pool)
    last = state.get("last_tpl")
    if last in pool and len(pool) > 1:
        pool.remove(last)
    tpl = random.choice(pool)
    state["last_tpl"] = tpl
    return tpl

def pick_closer(state, key):
    pool = list(CLOSERS.get(key) or [""])
    last = state.get("last_closer")
    if last in pool and len(pool) > 1:
        pool.remove(last)
    c = random.choice(pool)
    state["last_closer"] = c
    return c

def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;") \
        .replace(">", "&gt;")

def plural(n, one, few, many):
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many

# ================= СБОРКА ПОСТОВ =================
def _stat_goals(n):
    return ("\n📊 " + str(n) + "-й гол в чемпионате") if n is not None else ""

def _stat_assists(n):
    return (" (" + str(n) + "-я передача в сезоне)") \
        if n is not None else ""

def build_goal_post(state, scored, scorer, assister, minute, our, opp,
                    prev_our, prev_opp, prev_goal, we_led_before,
                    minutes_since, scorer_match_goals=0,
                    assister_match_assists=0, match_url=""):
    key = classify_goal(scored, our, opp, prev_our, prev_opp, minute,
                        prev_goal, we_led_before, minutes_since)
    closer = pick_closer(state, key)
    # счётчики уже включают текущее событие — так их отдаёт bot.py
    g_n = scorer_match_goals if scored else 0
    a_n = assister_match_assists if assister else 0
    scorer_ms = g_n if (scored and g_n >= 2) else None
    assist_ms = a_n if (assister and a_n >= 2) else None

    if scored:
        sg = season_count(state, scorer, "goals", scorer_match_goals,
                          match_url)
        scorer_stat = _stat_goals(sg)
        scorer = esc(scorer)
        assist_line = ""
        if assister:
            aa = season_count(state, assister, "assists",
                              assister_match_assists, match_url)
            assist_stat = _stat_assists(aa)
            if assist_ms:
                assist_line = ("\n🎯 Голевой пас: " + esc(assister)
                               + " — "
                               + MILESTONE_ASSIST_LOWER.get(assist_ms,
                                 str(assist_ms) + " передач в этом матче")
                               + " в этом матче!")
            else:
                assist_line = "\n🎯 Голевой пас: " + esc(assister) \
                    + assist_stat
        # милстоун забившего — приоритет перед пас-милстоуном
        if scorer_ms:
            if scorer_ms > 5:
                ms_name = str(g_n) + " МЯЧЕЙ"
                ms_lower = str(g_n) + " мячей"
            else:
                ms_name = MILESTONE_GOAL_NAMES.get(scorer_ms)
                ms_lower = MILESTONE_GOAL_LOWER[scorer_ms]
            closer = pick_closer(state,
                                 "milestone_g" + str(min(scorer_ms, 6)))
            tpl = pick_tpl(state, MILESTONE_G_TEMPLATES)
            return tpl.format(ms_name=ms_name, ms_lower=ms_lower, n=g_n,
                              n_word=plural(g_n, "мяч", "мяча", "мячей"),
                              scorer=scorer, scorer_stat=scorer_stat,
                              assist_line=assist_line, minute=minute,
                              our=our, opp=opp, closer=closer)
        if assist_ms:
            closer = pick_closer(state,
                                 "milestone_a" + str(min(assist_ms, 5)))
            tpl = pick_tpl(state, MILESTONE_A_TEMPLATES)
            return tpl.format(scorer=scorer, assister=esc(assister),
                              minute=minute, our=our, opp=opp,
                              assist_ms=MILESTONE_ASSIST_LOWER.get(
                                  assist_ms,
                                  str(assist_ms) + " передач"),
                              assist_stat="", closer=closer)
        if assister:
            tpl = pick_tpl(state, SCORED_TEMPLATES)
            return tpl.format(minute=minute, our=our, opp=opp,
                              scorer=scorer, assister=esc(assister),
                              scorer_stat=scorer_stat,
                              assist_stat=assist_stat, closer=closer)
        tpl = pick_tpl(state, SCORED_SOLO_TEMPLATES)
        return tpl.format(minute=minute, our=our, opp=opp, scorer=scorer,
                          scorer_stat=scorer_stat, closer=closer)
    # пропустили
    pool = CONCEDED_TEMPLATES.get(key) or CONCEDED_TEMPLATES["mid_trail"]
    tpl = pick_tpl(state, pool)
    return tpl.format(minute=minute, our=our, opp=opp, closer=closer)

def build_card_post(state, ctype, ours, player, minute, yellow_before=0):
    if ctype == "red" and ours and yellow_before >= 1:
        tpl = pick_tpl(state, CARD_TEMPLATES["two_yellows"])
        return tpl.format(player=esc(player), minute=minute,
                          closer=pick_closer(state, "card_two_yellows"))
    if ctype == "red":
        if ours:
            tpl = pick_tpl(state, CARD_TEMPLATES["red_our"])
            closer = pick_closer(state, "card_red_our")
        else:
            tpl = pick_tpl(state, CARD_TEMPLATES["red_opp"])
            closer = pick_closer(state, "card_red_opp")
        return tpl.format(player=esc(player), minute=minute, closer=closer)
    if ours:
        tpl = pick_tpl(state, CARD_TEMPLATES["yellow_our"])
        closer = pick_closer(state, "card_yellow_our")
    else:
        tpl = pick_tpl(state, CARD_TEMPLATES["yellow_opp"])
        closer = pick_closer(state, "card_yellow_opp")
    return tpl.format(player=esc(player), minute=minute, closer=closer)

def build_autogoal_post(state, ours, minute, our, opp):
    if ours:
        tpl = pick_tpl(state, AUTOGOAL_OUR_TEMPLATES)
        closer = pick_closer(state, "autogoal_our")
    else:
        tpl = pick_tpl(state, AUTOGOAL_AGAINST_TEMPLATES)
        closer = pick_closer(state, "autogoal_against")
    return tpl.format(minute=minute, our=our, opp=opp, closer=closer)

# ================= ДЕМО =================
def run_demo():
    st = {"season_stats": {
              "Харисов Алмаз": {"games": 4, "goals": 3, "assists": 1,
                                "yellow": 0, "red": 0},
              "Ираев Максим": {"games": 6, "goals": 2, "assists": 1,
                               "yellow": 1, "red": 0},
              "Закиров Ильнар": {"games": 4, "goals": 0, "assists": 1,
                                 "yellow": 1, "red": 0}},
          "stats_synced_at": "2026-11-24",
          "stats_synced_match_urls": []}
    # события матча (et, ours, minute, player, assist, our, opp)
    evs = [
        ("goal", False, 2, "?", None, 0, 1),
        ("goal", True, 6, "Калякулин Даниил", None, 1, 1),
        ("goal", False, 8, "?", None, 1, 2),
        ("goal", True, 21, "Харисов Алмаз", "Закиров Ильнар", 2, 2),
        ("goal", False, 30, "?", None, 2, 3),
        ("goal", True, 35, "Харисов Алмаз", "Калякулин Даниил", 3, 3),
        ("goal", True, 38, "Ираев Максим", "Харисов Алмаз", 4, 3),
        ("goal", False, 40, "?", None, 4, 4),
        ("autogoal", True, 12, "автогол", None, 0, 0),
        ("yellow", True, 18, "Закиров Ильнар", None, 0, 0),
        ("red", True, 39, "Семёнов Александр", None, 0, 0)]
    prev_our = prev_opp = 0
    prev_goal = None
    prev_min = None
    we_led = False
    counts = {}
    for et, ours, minute, player, assist, our, opp in evs:
        if et == "goal":
            # счётчики матча обновляем ДО поста: цифра в посте
            # включает и текущий гол/пас — как в bot.py
            if ours:
                counts.setdefault(player, {"goals": 0, "assists": 0,
                                           "yellow": 0})
                counts[player]["goals"] += 1
                if assist:
                    counts.setdefault(assist, {"goals": 0, "assists": 0,
                                               "yellow": 0})
                    counts[assist]["assists"] += 1
            post = build_goal_post(
                st, ours, player, assist, minute, our, opp,
                prev_our, prev_opp, prev_goal, we_led,
                (minute - prev_min) if prev_min is not None else None,
                counts.get(player, {}).get("goals", 0),
                counts.get(assist, {}).get("assists", 0) if assist else 0,
                match_url="demo")
            prev_our, prev_opp = our, opp
            prev_goal = "scored" if ours else "conceded"
            prev_min = minute
            if our > opp:
                we_led = True
        elif et == "autogoal":
            post = build_autogoal_post(st, ours, minute, our, opp)
        elif et in ("yellow", "red"):
            post = build_card_post(st, et, ours, player, minute,
                                   counts.get(player, {}).get("yellow", 0))
            if et == "yellow":
                counts.setdefault(player, {"goals": 0, "assists": 0,
                                           "yellow": 0})
                counts[player]["yellow"] += 1
        print("=" * 60)
        print(post.replace("<b>", "").replace("</b>", ""))

if __name__ == "__main__":
    run_demo()
