#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Задание 5. Доказательства.

Запускать из корня репозитория:
    bash stand/run.sh                 # в первом терминале
    python3 src/ex05.py              # во втором терминале

Используется только стандартная библиотека Python.
"""
import csv
import hashlib
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("PANEL_URL", "http://127.0.0.1:8013")
SERVICE_TOKEN = "EXP-9f3a7c21b8e4"
TOKEN_COMMIT = "c4d9e1a"
TOKEN_AUTHOR = "Константин Ефимов <k.efimov@privalshop.ru>"
TOKEN_DATE = "2026-07-28 14:22:37 +0300"


def section(number, title):
    print("\n" + "=" * 78)
    print("ПРОВЕРКА {}. {}".format(number, title))
    print("=" * 78)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def request(url, headers=None):
    """Возвращает код и тело в том числе для HTTP 4xx/5xx."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (OSError, urllib.error.URLError) as exc:
        return None, str(exc).encode("utf-8")


def sha256_record(record):
    payload = json.dumps(record["payload"], sort_keys=True, ensure_ascii=False)
    material = "{}|{}|{}|{}|{}|{}".format(
        record["seq"], record["ts"], record["actor"], record["action"],
        payload, record["prev_hash"]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def print_record(record, prefix=""):
    print(prefix + json.dumps(record, ensure_ascii=False, sort_keys=True))


def check_leak():
    section(1, "Состав утёкшего файла")
    path = "data/leaked_sample.csv"
    rows = read_csv(path)
    if not rows:
        print("Файл пуст или не содержит строк данных.")
        return

    # У двух источников разные поля имени и разные форматы даты.
    current = [r for r in rows if (r.get("full_name") or "").strip()]
    archive = [r for r in rows if (r.get("fio") or "").strip()]
    unknown = [r for r in rows if not (r.get("full_name") or "").strip()
               and not (r.get("fio") or "").strip()]
    ids = [r.get("client_id", "").strip() for r in rows if r.get("client_id", "").strip()]
    unique_ids = set(ids)

    print("Источник A (поле full_name заполнено): {} строк.".format(len(current)))
    print("Источник B (поле fio заполнено): {} строк.".format(len(archive)))
    print("Строк без признака источника: {}.".format(len(unknown)))
    print("Всего строк данных: {}.".format(len(rows)))
    print("Различных client_id (оценка числа людей после устранения дублей): {}.".format(
        len(unique_ids)))
    print("Повторных строк сверх числа уникальных client_id: {}.".format(
        len(rows) - len(unique_ids)))
    print("Признаки склейки: в одной группе заполнено full_name и пусто fio; "
          "в другой — наоборот. Также различается формат created_at.")
    print("Воспроизведение: python3 src/ex05.py (этот раздел читает data/leaked_sample.csv).")


def check_archive():
    section(2, "Какая резервная копия соответствует архивной половине")
    leaked = read_csv("data/leaked_sample.csv")
    archive_ids = {
        r.get("client_id", "").strip()
        for r in leaked if (r.get("fio") or "").strip()
        and r.get("client_id", "").strip()
    }
    if not archive_ids:
        print("Архивная половина не найдена: поле fio пусто во всех строках.")
        return

    print("Архивная половина утечки: {} уникальных client_id.".format(len(archive_ids)))
    for month in ("06", "07", "08", "09"):
        path = "stand/storage/clients_2026-{}.csv".format(month)
        if not os.path.exists(path):
            print("{}: файла нет в локальной копии.".format(path))
            continue
        backup = read_csv(path)
        backup_ids = {
            r.get("client_id", "").strip() for r in backup
            if r.get("client_id", "").strip()
        }
        matched = archive_ids & backup_ids
        pct_archive = 100.0 * len(matched) / len(archive_ids)
        pct_backup = 100.0 * len(matched) / len(backup_ids) if backup_ids else 0.0
        print("{}: совпало {} ID; это {:.2f}% архивной половины и {:.2f}% ID копии "
              "(архивных ID={}, ID в копии={}).".format(
                  path, len(matched), pct_archive, pct_backup,
                  len(archive_ids), len(backup_ids)))
    print("Совпадение проверяется по client_id, а не по именам или строкам целиком.")


def check_stand():
    section(3, "Ответы стенда: резервная копия и endpoint выгрузки")
    backup_url = BASE_URL + "/backup/clients_2026-06.csv"
    export_url = BASE_URL + "/api/export"
    backup_status, backup_body = request(backup_url)
    export_status, export_body = request(export_url)

    print("GET {} без авторизации -> HTTP {} (тело: {} байт).".format(
        backup_url, backup_status if backup_status is not None else "нет ответа",
        len(backup_body)))
    print("GET {} без сессии -> HTTP {}.".format(
        export_url, export_status if export_status is not None else "нет ответа"))
    if backup_status == 200 and export_status == 401:
        print("Вывод: резервная копия доступна без авторизации, а API выгрузки "
              "требует сессию. Разницу подтверждают два запроса к работающему стенду.")
    else:
        print("Результаты отличаются от ожидаемой пары 200/401. Проверьте, что стенд "
              "запущен из этой копии репозитория и PANEL_URL указывает на верный порт.")
    print("Воспроизведение: curl -i {} и curl -i {}.".format(backup_url, export_url))


def check_token():
    section(4, "Сервисный токен из истории export_tool")
    print("Токен: {}".format(SERVICE_TOKEN))
    print("Коммит: {}.".format(TOKEN_COMMIT))
    print("Автор: {}.".format(TOKEN_AUTHOR))
    print("Дата коммита: {}.".format(TOKEN_DATE))
    status, body = request(BASE_URL + "/api/config", {"X-Auth-Token": SERVICE_TOKEN})
    print("Проверка токена запросом GET {}/api/config -> HTTP {}.".format(
        BASE_URL, status if status is not None else "нет ответа"))
    if status == 200:
        try:
            config = json.loads(body.decode("utf-8"))
            print("Ответ панели: instance={!r}, auth_required_paths={!r}.".format(
                config.get("instance"), config.get("auth_required_paths")))
            print("Токен действует на стенде для чтения конфигурации; это не означает, "
                  "что он даёт право на /api/export.")
        except (ValueError, UnicodeDecodeError):
            print("Тело ответа не удалось разобрать как JSON: {!r}".format(body[:200]))
    else:
        print("Ответ: {}".format(body.decode("utf-8", errors="replace")[:500].strip()))
    print("Использование токена зафиксировано в data/access.csv:907 "
          "(api_auth, /api/config, token_id={}) и :908 "
          "(read_config, /api/config, bytes_out=1841).".format(SERVICE_TOKEN))
    print("История секрета: data/export_tool/history.log, коммит {}.".format(TOKEN_COMMIT))


def check_audit():
    section(5, "Проверка хеш-цепочки журнала ИИ-ассистента")
    path = "data/audit.jsonl"
    records = []
    with open(path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            if line.strip():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    print("Строка {} не является корректным JSON: {}".format(line_number, exc))
                    continue
                record["_line"] = line_number
                records.append(record)

    if not records:
        print("В журнале нет читаемых записей.")
        return

    mismatches = []
    link_errors = []
    previous = None
    for record in records:
        expected = sha256_record(record)
        if expected != record.get("hash"):
            mismatches.append(record)
        if previous is not None and record.get("prev_hash") != previous.get("hash"):
            link_errors.append((record, previous))
        previous = record

    print("Проверено записей: {}.".format(len(records)))
    print("Записи, чьё содержимое не совпадает с собственным hash: {}.".format(
        len(mismatches)))
    print("Нарушения ссылки prev_hash на предыдущую запись: {}.".format(len(link_errors)))
    for record in mismatches:
        idx = records.index(record)
        print("\nНесходящаяся запись (строка {}):".format(record["_line"]))
        print_record({k: v for k, v in record.items() if k != "_line"})
        if idx > 0:
            print("Предыдущая запись:")
            print_record({k: v for k, v in records[idx - 1].items() if k != "_line"})
        if idx + 1 < len(records):
            print("Следующая запись:")
            print_record({k: v for k, v in records[idx + 1].items() if k != "_line"})
        print("Рабочая гипотеза: на месте этой записи могло быть другое событие "
              "watcher/ассистента, которое заменили правдоподобным heartbeat. "
              "Это только гипотеза: хеш не хранит исходный текст, поэтому точное "
              "действие и payload нельзя восстановить без независимой копии журнала. "
              "Соседи задают временной контекст, но не доказывают содержание.")
    if not mismatches:
        print("Все вычисленные hash совпали с записями.")
    if link_errors:
        for record, previous in link_errors:
            print("Разрыв цепочки перед seq={} (строка {}): prev_hash не равен hash "
                  "предыдущей записи seq={}.".format(
                      record.get("seq"), record.get("_line"), previous.get("seq")))
    print("Правило проверки: sha256('seq|ts|actor|action|payload|prev_hash'), "
          "payload сериализуется через json.dumps(sort_keys=True, ensure_ascii=False).")


def main():
    check_leak()
    check_archive()
    check_stand()
    check_token()
    check_audit()


if __name__ == "__main__":
    main()
