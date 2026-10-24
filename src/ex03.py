"""Задание 3. Хронология и алиби.
Запуск из корня репозитория: python3 src/ex03.py
В access.csv время записано в UTC; ночная хронология отображается в MSK (UTC+3).
"""
import csv
import math
from datetime import datetime, timedelta

START_MSK = datetime(2026, 9, 11, 18, 0, 0)
END_MSK = datetime(2026, 9, 12, 6, 0, 0)
MSK_OFFSET = timedelta(hours=3)
IMPOSSIBLE_SPEED_KMH = 900.0


def parse_time(value):
    """Разбирает оба формата времени, встречающиеся в access.csv."""
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError("Неизвестный формат времени: {!r}".format(value))


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def distance_km(lat1, lon1, lat2, lon2):
    """Расстояние по формуле гаверсинуса; локальное время на него не влияет."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    a = min(1.0, max(0.0, a))
    return 2 * radius * math.asin(math.sqrt(a))


def fmt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def main():
    events = read_csv("data/access.csv")
    geo = {
        row["ip"]: {
            "city": row["city"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "org": row["org"],
        }
        for row in read_csv("data/geoip.csv")
    }

    # Часть 1. Отбираем интервал в UTC, отображаем время в московском часовом поясе.
    start_utc = START_MSK - MSK_OFFSET
    end_utc = END_MSK - MSK_OFFSET
    chronology = []
    for event in events:
        timestamp = parse_time(event["ts"])
        if start_utc <= timestamp <= end_utc:
            location = geo.get(event["ip"], {})
            chronology.append((timestamp, event, location))
    chronology.sort(key=lambda item: (item[0], item[1]["login"], item[1]["action"]))

    print("1. Хронология (11.09 18:00 — 12.09 06:00 MSK)")
    print("Время MSK | Учётная запись | Город | IP | Действие | Объект | Результат | Метод | Сессия | Детали")
    for timestamp, event, location in chronology:
        print("{} | {} | {} | {} | {} | {} | {} | {} | {} | {}".format(
            fmt(timestamp + MSK_OFFSET), event["login"],
            location.get("city", "нет в справочнике"), event["ip"],
            event["action"], event["object"], event["result"],
            event["auth_method"], event["session_id"], event["detail"]
        ))
    if not chronology:
        print("В заданном интервале событий нет.")

    # Часть 2. Соседние успешные входы каждой учётной записи во всём журнале.
    successful_logins = []
    for event in events:
        if event["action"] != "login" or event["result"].strip().lower() != "ok":
            continue
        location = geo.get(event["ip"])
        if location is None:
            # Без координат расстояние вычислить нельзя — такие строки не угадываем.
            continue
        successful_logins.append({
            "time": parse_time(event["ts"]),
            "login": event["login"],
            "ip": event["ip"],
            "city": location["city"],
            "lat": location["lat"],
            "lon": location["lon"],
            "session": event["session_id"],
        })
    successful_logins.sort(key=lambda item: (item["login"], item["time"]))

    pairs = []
    previous_by_login = {}
    for current in successful_logins:
        previous = previous_by_login.get(current["login"])
        if previous is not None:
            seconds = (current["time"] - previous["time"]).total_seconds()
            if seconds > 0:
                km = distance_km(previous["lat"], previous["lon"], current["lat"], current["lon"])
                hours = seconds / 3600.0
                pairs.append({
                    "login": current["login"],
                    "previous": previous,
                    "current": current,
                    "distance": km,
                    "hours": hours,
                    "speed": km / hours,
                })
        previous_by_login[current["login"]] = current

    impossible = [pair for pair in pairs if pair["speed"] > IMPOSSIBLE_SPEED_KMH]
    print("\n2. Невозможные перемещения (скорость выше {:.0f} км/ч)".format(IMPOSSIBLE_SPEED_KMH))
    print("Учётная запись | Первый вход UTC / город / IP | Второй вход UTC / город / IP | Км | Минуты | Км/ч")
    for pair in impossible:
        a, b = pair["previous"], pair["current"]
        print("{} | {} / {} / {} | {} / {} / {} | {:.1f} | {:.1f} | {:.1f}".format(
            pair["login"], fmt(a["time"]), a["city"], a["ip"],
            fmt(b["time"]), b["city"], b["ip"], pair["distance"],
            pair["hours"] * 60, pair["speed"]
        ))
    if not impossible:
        print("Пар выше заданного порога не найдено.")

    # Часть 3. Связываем аномалии с конкретными сессиями и событием выгрузки.
    print("\n3. Итог по сессиям")
    for login in sorted({pair["login"] for pair in impossible}):
        related = [pair for pair in impossible if pair["login"] == login]
        cities = sorted({city for pair in related for city in
                         (pair["previous"]["city"], pair["current"]["city"])})
        print("- Учётная запись {}: географически несовместимые входы из {}; это признак использования учётной записи более чем одним человеком или компрометации доступа.".format(
            login, ", ".join(cities)
        ))
        for pair in related:
            a, b = pair["previous"], pair["current"]
            print("  Сессии {} -> {}: {} ({}) -> {} ({}), {:.1f} км за {:.1f} мин ({:.1f} км/ч).".format(
                a["session"], b["session"], a["city"], fmt(a["time"]),
                b["city"], fmt(b["time"]), pair["distance"],
                pair["hours"] * 60, pair["speed"]
            ))

    exports = [(timestamp, event) for timestamp, event, _ in chronology
               if event["action"] == "export"]
    if exports:
        for timestamp, event in exports:
            print("- Выгрузка выполнена сессией {} под учётной записью {} в {} MSK; IP={}, объект={}, детали={!r}.".format(
                event["session_id"], event["login"], fmt(timestamp + MSK_OFFSET),
                event["ip"], event["object"], event["detail"]
            ))
    else:
        print("- В выбранном временном окне событие export не найдено.")

    # Часть 4. Проверяем основания отчёта, не приравнивая логин к личности.
    print("\n4. Опровержение отчёта")
    sokolov_pairs = [pair for pair in impossible if pair["login"] == "a.sokolov"]
    if sokolov_pairs:
        print("Опровергнуто основание 2: успешный вход с password+mfa не доказывает, что за обеими сессиями был один и тот же человек.")
        for pair in sokolov_pairs:
            a, b = pair["previous"], pair["current"]
            print("Журнальная улика: {} ({}, сессия {}) -> {} ({}, сессия {}): {:.1f} км за {:.1f} мин, требуемая скорость {:.1f} км/ч.".format(
                a["city"], fmt(a["time"]), a["session"],
                b["city"], fmt(b["time"]), b["session"],
                pair["distance"], pair["hours"] * 60, pair["speed"]
            ))
    else:
        print("Для a.sokolov в расчёте не обнаружено пары входов выше порога; выводы отчёта нельзя ни подтвердить, ни опровергнуть только этой проверкой.")

    kotov_events = [(timestamp, event) for timestamp, event, _ in chronology
                    if event["login"] == "p.kotov"]
    if kotov_events:
        print("Также в ночном окне есть события p.kotov, поэтому основание 4 отчёта («учётная запись администратора не активна») противоречит журналу:")
        for timestamp, event in kotov_events:
            print("  {} MSK | {} | IP {} | сессия {} | {}".format(
                fmt(timestamp + MSK_OFFSET), event["action"], event["ip"],
                event["session_id"], event["detail"]
            ))
    else:
        print("В выбранном окне нет событий p.kotov. Это говорит только об отсутствии таких записей в данной выборке.")

    # Сохраняем оговорку о границах вывода: скорость указывает на невозможность,
    # но не сама по себе устанавливает конкретного физического человека.
    print("Примечание: невозможная скорость доказывает несогласованность географии и времени входов, но сама по себе не устанавливает личность пользователя.")


if __name__ == "__main__":
    main()
