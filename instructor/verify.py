#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка комплекта дня 13. Запускать при поднятом стенде:

    bash stand/run.sh &
    python3 instructor/verify.py

Проверяет три вещи: что все улики в данных сходятся между собой и с эталоном
(instructor/solution-key.md), что клиентские данные согласованы между файлами
(один client_id — один человек), и что README не ссылается на несуществующие
файлы, а файлов без упоминания нет.
Скрипт сам переходит в корень проекта, откуда бы его ни запустили.
"""
import csv, sqlite3, json, hashlib, math, os, re, email, sys, zipfile
import urllib.request, urllib.error
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(os.path.dirname(_HERE) if os.path.basename(_HERE) == "instructor" else _HERE)

FAILS = []

def ok(name, got, exp):
    good = got == exp
    if not good:
        FAILS.append(name)
    print(("OK   " if good else "FAIL ") + name + ": " + str(got) +
          ("" if good else "   ожидалось " + str(exp)))

def norm(s):
    for f in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    raise ValueError(s)

def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

print("=== Журнал доступа ===")
con = sqlite3.connect(":memory:")
con.create_function("norm", 1, lambda s: norm(s).strftime("%Y-%m-%d %H:%M:%S"))
con.create_function("msk", 1, lambda s: (norm(s) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"))
con.execute("CREATE TABLE access (ts,login,ip,action,object,result,auth_method,session_id,detail)")
con.execute("CREATE TABLE geoip (ip,city,lat REAL,lon REAL,org)")
for t, p in (("access", "data/access.csv"), ("geoip", "data/geoip.csv")):
    rows = [tuple(r.values()) for r in read_csv(p)]
    con.executemany("INSERT INTO %s VALUES (%s)" % (t, ",".join("?" * len(rows[0]))), rows)
one = lambda q: con.execute(q).fetchone()[0]

ok("строк журнала", one("SELECT COUNT(*) FROM access"), 1001)
ok("различных login", one("SELECT COUNT(DISTINCT login) FROM access"), 8)
ok("формат ГГГГ-ММ-ДД", one("SELECT COUNT(*) FROM access WHERE ts LIKE '____-%'"), 858)
ok("формат ДД.ММ.ГГГГ", one("SELECT COUNT(*) FROM access WHERE ts LIKE '__.__.____%'"), 143)
ok("различных action", one("SELECT COUNT(DISTINCT action) FROM access"), 14)
ok("auth_method", dict(con.execute("SELECT auth_method, COUNT(*) FROM access GROUP BY 1").fetchall()),
   {"session": 796, "password+mfa": 146, "service": 42, "password": 14, "token": 2, "none": 1})
ok("выгрузок", one("SELECT COUNT(*) FROM access WHERE action='export'"), 2)
ok("12 сент по UTC", one("SELECT COUNT(*) FROM access WHERE norm(ts) LIKE '2026-09-12%'"), 5)
ok("12 сент по UTC без norm", one("SELECT COUNT(*) FROM access WHERE ts LIKE '2026-09-12%'"), 4)
ok("12 сент по MSK", one("SELECT COUNT(*) FROM access WHERE msk(ts) LIKE '2026-09-12%'"), 9)
ok("ночь инцидента (MSK 18:00–06:00)", one("SELECT COUNT(*) FROM access WHERE msk(ts) "
   "BETWEEN '2026-09-11 18:00:00' AND '2026-09-12 06:00:00'"), 10)
ok("k.efimov событий", one("SELECT COUNT(*) FROM access WHERE login='k.efimov'"), 0)
ok("p.kotov в ночь", one("SELECT COUNT(*) FROM access WHERE login='p.kotov' AND norm(ts)>'2026-09-11 15:00:00'"), 0)
ok("пустых ip", one("SELECT COUNT(*) FROM access WHERE ip=''"), 0)
ok("адресов без справочника", one("SELECT COUNT(DISTINCT ip) FROM access WHERE ip NOT IN (SELECT ip FROM geoip)"), 0)
ok("новые адреса с 09.09", con.execute("SELECT ip, COUNT(*) FROM access GROUP BY ip "
   "HAVING MIN(norm(ts)) >= '2026-09-09' ORDER BY MIN(norm(ts))").fetchall(),
   [("45.132.19.88", 2), ("176.59.208.33", 3), ("185.220.101.45", 5)])
ok("config_change", con.execute("SELECT norm(ts), login, detail FROM access WHERE action='config_change'").fetchall(),
   [("2026-08-05 08:07:41", "p.kotov", "removed /backup/ from auth_required")])
ok("mfa_reset", con.execute("SELECT norm(ts), login, object, detail FROM access WHERE action='mfa_reset'").fetchall(),
   [("2026-09-11 20:31:18", "d.kravets", "a.sokolov", "ticket=T-4471")])
ok("второй фактор в Сочи", one("SELECT detail FROM access WHERE session_id='s09980' AND action='login'"),
   "mfa=remembered_device")
ok("второй фактор в Москве", one("SELECT detail FROM access WHERE session_id='s09981' AND action='login'"),
   "mfa_enrolled_at=2026-09-11T20:31:18Z")

def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2 * 6371 * math.asin(math.sqrt(h))

def fast_pairs(where):
    """Пары соседних событий одной учётки быстрее 900 км/ч: (login, город1, город2, км/ч)."""
    out, by = [], {}
    for t, lg, city, lat, lon, sid in con.execute(
            "SELECT norm(a.ts), a.login, g.city, g.lat, g.lon, a.session_id FROM access a "
            "JOIN geoip g ON g.ip=a.ip WHERE a.login NOT IN ('-','watcher') AND " + where):
        by.setdefault(lg, []).append((datetime.fromisoformat(t), city, lat, lon, sid))
    for lg, ev in sorted(by.items()):
        ev.sort()
        for p, c in zip(ev, ev[1:]):
            km = hav(p[2:4], c[2:4])
            h = (c[0] - p[0]).total_seconds() / 3600
            if km > 0 and km / h > 900:
                out.append((lg, p[1], c[1], round(km / h), p[4], c[4]))
    return out

ok("быстрые пары, удачные входы", fast_pairs("a.action='login' AND a.result='ok'"),
   [("a.sokolov", "Сочи", "Москва", 13248, "s09980", "s09981")])
ok("быстрые пары, все входы (пограничная у Кравец)", [x[:4] for x in fast_pairs("a.action='login'")],
   [("a.sokolov", "Сочи", "Москва", 13248), ("d.kravets", "Москва", "Екатеринбург", 929)])

print("\n=== Почта и заявки ===")
ph = [f for f in sorted(os.listdir("data/mail"))
      if "spf=fail" in email.message_from_string(
          open("data/mail/" + f, encoding="utf-8").read()).get("Authentication-Results", "")]
ok("фишинговых писем", ph, ["m03.eml"])
m03 = email.message_from_string(open("data/mail/m03.eml", encoding="utf-8").read())
ok("адрес релея в верхней строке Received", "[45.132.19.88]" in m03.get_all("Received")[0], True)

tk = read_csv("data/tickets.csv")
res = [t for t in tk if t["action_taken"].startswith("mfa_reset")]
ok("сбросов MFA", [(t["id"], t["assignee"], t["callback_verified"]) for t in res],
   [("T-4402", "d.kravets", "yes"), ("T-4418", "d.kravets", "yes"), ("T-4437", "d.kravets", "yes"),
    ("T-4455", "s.raifa", "yes"), ("T-4471", "d.kravets", "no")])

print("\n=== Утечка и копии ===")
lk = read_csv("data/leaked_sample.csv")
fresh = [r for r in lk if r["full_name"]]
arch = [r for r in lk if r["fio"]]
ok("строк утечки", len(lk), 10412)
ok("субъектов", len({r["client_id"] for r in lk}), 9380)
ok("половины", (len(fresh), len(arch)), (6900, 3512))
ok("пересечение половин", len({r["client_id"] for r in fresh} & {r["client_id"] for r in arch}), 1032)
ok("потолок дат архивной половины", max(datetime.strptime(r["created_at"], "%d.%m.%Y") for r in arch).date().isoformat(), "2026-06-30")
ok("потолок дат свежей половины", max(r["last_order_at"] for r in fresh), "2026-09-11")
ok("«С.-Петербург» только в архиве", (sum(r["city"] == "С.-Петербург" for r in fresh),
                                      sum(r["city"] == "С.-Петербург" for r in arch) > 0), (0, True))

aid = {r["client_id"] for r in arch}
backups = {fn: read_csv("stand/storage/" + fn) for fn in sorted(os.listdir("stand/storage"))}
ok("покрытие архивной половины, %", {fn: round(100 * len(aid & {r["client_id"] for r in rows}) / len(aid), 1)
                                     for fn, rows in backups.items()},
   {"clients_2026-06.csv": 100.0, "clients_2026-07.csv": 16.1,
    "clients_2026-08.csv": 21.3, "clients_2026-09.csv": 24.5})
F = ("fio", "phone", "email", "city", "created_at")
b06 = {r["client_id"]: r for r in backups["clients_2026-06.csv"]}
ok("архивные строки совпадают с июньской копией целиком", sum(all(r[k] == b06[r["client_id"]][k] for k in F) for r in arch), 3512)

def person(r):
    return ((r.get("full_name") or r["fio"]), re.sub(r"\D", "", r["phone"]),
            "Санкт-Петербург" if r["city"] == "С.-Петербург" else r["city"], r["email"])
seen, clash = {}, 0
for rows in [lk] + list(backups.values()):
    for r in rows:
        clash += seen.setdefault(r["client_id"], person(r)) != person(r)
ok("один client_id — один человек во всех файлах", clash, 0)

http_bytes = int(re.search(r"bytes=(\d+)", one("SELECT detail FROM access WHERE action='http_get'")).group(1))
ok("байт в журнале = размер июньской копии", http_bytes, os.path.getsize("stand/storage/clients_2026-06.csv"))

print("\n=== Репозиторий и журнал ассистента ===")
hist = open("data/export_tool/history.log", encoding="utf-8").read()
tok = re.search(r'SERVICE_TOKEN = "([^"]+)"', hist)
ok("токен из репозитория", tok.group(1), "EXP-9f3a7c21b8e4")
ok("коммит", re.findall(r"commit (\w+)", hist[:tok.start()])[-1], "c4d9e1a")
ok("токен в журнале доступа", one("SELECT norm(ts) FROM access WHERE detail='token_id=" + tok.group(1) + "'"),
   "2026-09-09 01:17:09")

au = [json.loads(l) for l in open("data/audit.jsonl", encoding="utf-8")]
def rh(r, sort_keys=True):
    raw = "%s|%s|%s|%s|%s|%s" % (r["seq"], r["ts"], r["actor"], r["action"],
                                 json.dumps(r["payload"], sort_keys=sort_keys, ensure_ascii=False),
                                 r["prev_hash"])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
ok("записей журнала", len(au), 126)
ok("разрывов цепочки", [r["seq"] for r in au if rh(r) != r["hash"]], [91])
ok("разрывов без sort_keys (ловушка)", [r["seq"] for r in au if rh(r, False) != r["hash"]], [91, 92])
ok("связи prev_hash", [au[i]["seq"] for i in range(1, len(au)) if au[i]["prev_hash"] != au[i-1]["hash"]], [])

print("\n=== Стенд ===")
def code(url, hdr=None):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=hdr or {}), timeout=5)
        return r.status, len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, 0
    except Exception as e:
        return "нет связи (%s)" % type(e).__name__, 0

base = "http://127.0.0.1:%s" % os.environ.get("PANEL_PORT", "8013")
s1, n1 = code(base + "/backup/clients_2026-06.csv")
if isinstance(s1, str):
    print("   стенд не поднят — раздел пропущен. Запустите: bash stand/run.sh")
else:
    ok("бэкап без авторизации", s1, 200)
    ok("байт отдано = байт в журнале", n1, http_bytes)
    ok("export без сессии", code(base + "/api/export")[0], 401)
    ok("config без токена", code(base + "/api/config")[0], 401)
    ok("config по токену", code(base + "/api/config", {"X-Auth-Token": tok.group(1)})[0], 200)
    ok("config по чужому токену", code(base + "/api/config", {"X-Auth-Token": "nope"})[0], 403)

print("\n=== Ссылки в README ===")
def readme_text():
    for name in sorted(os.listdir(".")):
        if name.startswith("README") and name.endswith(".md"):
            return name, open(name, encoding="utf-8").read()
    for name in sorted(os.listdir(".")):
        if name.startswith("README") and name.endswith(".docx"):
            xml = zipfile.ZipFile(name).read("word/document.xml").decode("utf-8")
            xml = re.sub(r"</w:p>", "\n", xml)
            return name, re.sub(r"<[^>]+>", "", xml)
    return None, ""
name, readme = readme_text()
ok("README найден", name is not None, True)
mentioned = {m.rstrip(".,;:") for m in re.findall(
    r"(?<![A-Za-z0-9_/-])((?:data|materials|stand)/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)", readme)}
missing = sorted(m for m in mentioned if not os.path.exists(m))
ok("упомянутых, но отсутствующих файлов", missing, [])

on_disk = set()
for root, dirs, files in os.walk("."):
    if any(x in root for x in (".git", "instructor", "__pycache__", "storage", "mail")):
        continue
    for f in files:
        rel = os.path.relpath(os.path.join(root, f), ".").replace(os.sep, "/")
        if rel.split("/")[0] in ("data", "materials", "stand"):
            on_disk.add(rel)
unreferenced = sorted(f for f in on_disk if f not in mentioned)
ok("файлов без упоминания в README", unreferenced, [])
ok("заглушек в README", re.findall(r"\[[А-ЯЁ_]{4,}\]", readme), [])

print()
print("ИТОГ: " + ("все проверки прошли" if not FAILS else "провалено: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
