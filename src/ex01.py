"""Задание 1. Журнал доступа в SQLite.

Запуск из корня репозитория:
    python3 src/ex01.py

Данные загружаются во временную базу SQLite в памяти. Исходные CSV-файлы
не изменяются; используются только стандартные библиотеки Python.
"""

import csv
import re
import sqlite3
from datetime import datetime


# Сначала перечислены форматы, встречающиеся в выданном журнале. Остальные
# распространённые варианты поддержаны на случай расширения учебных данных.
TIMESTAMP_FORMATS = (
    ("%Y-%m-%d %H:%M:%S", "YYYY-MM-DD HH:MM:SS"),
    ("%d.%m.%Y %H:%M:%S", "DD.MM.YYYY HH:MM:SS"),
    ("%Y-%m-%d %H:%M", "YYYY-MM-DD HH:MM"),
    ("%d.%m.%Y %H:%M", "DD.MM.YYYY HH:MM"),
    ("%Y-%m-%dT%H:%M:%S", "ISO 8601 с T"),
    ("%d/%m/%Y %H:%M:%S", "DD/MM/YYYY HH:MM:SS"),
    ("%Y/%m/%d %H:%M:%S", "YYYY/MM/DD HH:MM:SS"),
)

ISO_WITH_ZONE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$"
)


def parse_timestamp(value):
    """Разобрать поддерживаемое представление даты и времени."""
    if value is None:
        return None

    raw = value.strip()
    if not raw:
        return None

    # fromisoformat поддерживает ISO 8601, включая варианты с часовым поясом.
    iso_value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        pass

    for date_format, _label in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(raw, date_format)
        except ValueError:
            continue

    raise ValueError("неизвестный формат времени: {!r}".format(value))


def portm(value):
    """Привести время к формату ГГГГ-ММ-ДД ЧЧ:ММ:СС."""
    parsed = parse_timestamp(value)
    if parsed is None:
        return None

    # Задача нормализует написание времени, но не меняет часовой пояс.
    return parsed.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def timestamp_format(value):
    """Определить исходный формат времени для группировки строк."""
    if value is None or not value.strip():
        return "пустое значение"

    raw = value.strip()
    for date_format, label in TIMESTAMP_FORMATS:
        try:
            datetime.strptime(raw, date_format)
            return label
        except ValueError:
            continue

    if ISO_WITH_ZONE.fullmatch(raw):
        return "ISO 8601 с часовым поясом"

    try:
        datetime.fromisoformat(raw)
        return "другой формат ISO 8601"
    except ValueError:
        return "нераспознанный формат"


def load_csv(cur, table, path):
    """Загрузить CSV в заранее созданную таблицу."""
    with open(path, encoding="utf-8", newline="") as source:
        rows = [tuple(row.values()) for row in csv.DictReader(source)]

    if not rows:
        raise ValueError("файл {} не содержит строк данных".format(path))

    placeholders = ",".join("?" for _ in rows[0])
    cur.executemany(
        "INSERT INTO {} VALUES ({})".format(table, placeholders), rows
    )


def print_section(number, title):
    print("\n{}. {}".format(number, title))
    print("-" * (len(str(number)) + len(title) + 2))


def print_rows(rows, empty_message="Совпадений нет."):
    rows = list(rows)
    if not rows:
        print(empty_message)
        return

    for row in rows:
        print(" | ".join("" if value is None else str(value) for value in row))


def main():
    con = sqlite3.connect(":memory:")
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE access (
            ts TEXT, login TEXT, ip TEXT, action TEXT, object TEXT,
            result TEXT, auth_method TEXT, session_id TEXT, detail TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE geoip (
            ip TEXT, city TEXT, lat REAL, lon REAL, org TEXT
        )
        """
    )

    # Скрипт запускается из корня репозитория, как указано в README.
    load_csv(cur, "access", "data/access.csv")
    load_csv(cur, "geoip", "data/geoip.csv")

    con.create_function("portm", 1, portm)
    con.create_function("ts_format", 1, timestamp_format)
    con.commit()

    # 1. Сколько всего строк в журнале доступа.
    print_section(1, "Количество строк в журнале доступа")
    row_count = cur.execute("SELECT COUNT(*) FROM access").fetchone()[0]
    print("Всего строк: {}".format(row_count))

    # 2. Сколько различных значений встречается в поле login.
    print_section(2, "Количество различных значений login")
    login_count = cur.execute(
        "SELECT COUNT(DISTINCT login) FROM access"
    ).fetchone()[0]
    print("Различных значений login: {}".format(login_count))

    # 3. Количество строк для каждого встречающегося исходного формата времени.
    print_section(3, "Количество строк в каждом формате времени")
    formats = cur.execute(
        """
        SELECT ts_format(ts) AS исходный_формат, COUNT(*) AS количество
        FROM access
        GROUP BY исходный_формат
        ORDER BY исходный_формат
        """
    )
    print_rows(formats)

    # 4. Проверка portm на двух строках с разными форматами времени.
    print_section(4, "Нормализация времени функцией portm")
    examples = {}
    for (raw_timestamp,) in cur.execute("SELECT ts FROM access ORDER BY rowid"):
        label = timestamp_format(raw_timestamp)
        if label not in examples and label != "пустое значение":
            examples[label] = raw_timestamp
        if len(examples) == 2:
            break

    if len(examples) < 2:
        print("Не удалось найти две строки с разными форматами времени.")
    else:
        for label, raw_timestamp in examples.items():
            normalized = cur.execute(
                "SELECT portm(?)", (raw_timestamp,)
            ).fetchone()[0]
            print(
                "Формат {}: {!r} -> {}".format(
                    label, raw_timestamp, normalized
                )
            )

    # 5. Все события выгрузки с нормализованным временем и полем detail.
    print_section(5, "Все события выгрузки данных")
    export_events = cur.execute(
        """
        SELECT portm(ts) AS время, login AS учётная_запись,
               ip AS адрес, detail
        FROM access
        WHERE lower(coalesce(action, '')) = 'export'
        ORDER BY portm(ts), login, ip
        """
    )
    print("Время | Учётная запись | Адрес | detail")
    print_rows(export_events)

    # 6. Сначала показываем наблюдаемые значения, как просит README.
    print_section(6, "События с нестандартным способом аутентификации")
    print("Распределение значений auth_method:")
    auth_summary = cur.execute(
        """
        SELECT coalesce(nullif(trim(auth_method), ''), '(пусто)') AS метод,
               COUNT(*) AS количество
        FROM access
        GROUP BY coalesce(nullif(trim(auth_method), ''), '(пусто)')
        ORDER BY метод
        """
    )
    print_rows(auth_summary)

    # В README встречается password+mpfa, а в заготовке и исходных данных —
    # password+mfa. Оба написания считаются обычным входом с MFA.
    print("\nСобытия, где auth_method не MFA и не session:")
    unusual_auth_events = cur.execute(
        """
        SELECT portm(ts) AS время, login, ip, action, object, result,
               auth_method, session_id, detail
        FROM access
        WHERE lower(trim(coalesce(auth_method, ''))) NOT IN (
            'password+mfa', 'password+mpfa', 'session'
        )
        ORDER BY portm(ts), login, action
        """
    )
    print(
        "Время | login | ip | action | object | result | auth_method | "
        "session_id | detail"
    )
    print_rows(unusual_auth_events)

    con.close()


if __name__ == "__main__":
    main()
