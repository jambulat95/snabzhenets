"""Сквозной демо-сценарий через API (как на защите): uv run python scripts/check_scenario.py

Нужны: docker compose up (API :8010, воркер, GreenMail), сид (python -m app.seed), ключи моделей в .env.
Шаги: вход → заявка → разбор → КТРУ проектора → подтверждение → поставщики, цены сайтов, письма →
«Ускорить время» → все ответили → анализ по методике → (выброс по проектору исключить) → обоснование готово.
Код выхода 0 — сценарий прошёл.
"""

import sys
import time
from pathlib import Path
from typing import Any

import httpx

API = "http://localhost:8010/api"
ACCOUNTS = Path(__file__).resolve().parents[1] / "demo_accounts.txt"
TEXT = """Нужно для учебного корпуса к началу семестра:
1. Картриджи для HP LaserJet Pro M428, оригинальные — 20 шт.
2. Проектор для аудитории — 2 шт.
3. Бумага А4 80 г/м2 — 50 пачек"""


def password(email: str) -> str:
    for line in ACCOUNTS.read_text("utf-8").splitlines():
        parts = line.split("\t")
        if parts[0] == email:
            return parts[2]
    raise SystemExit(f"Нет учётки {email} в {ACCOUNTS.name}: запустите python -m app.seed")


def wait(c: httpx.Client, pid: int, cond: Any, what: str, timeout: float = 180) -> dict[str, Any]:
    start = time.time()
    while time.time() - start < timeout:
        p: dict[str, Any] = c.get(f"{API}/procurements/{pid}").json()
        if cond(p):
            print(f"  ✓ {what} ({time.time() - start:.0f} с)")
            return p
        time.sleep(3)
    raise SystemExit(f"  ✗ не дождались: {what}; статус {p['status']}")


def main() -> int:
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={"email": "zakupki@chesu.demo", "password": password("zakupki@chesu.demo")})
    r.raise_for_status()
    print("1. Вход:", r.json()["full_name"])

    p = c.post(f"{API}/procurements", json={"text": TEXT}).json()
    pid = p["id"]
    print(f"2. Заявка {p['number']}")
    p = wait(c, pid, lambda x: x["status"] == "spec_review", "разбор и подбор КТРУ")
    assert len(p["items"]) == 3, p["items"]
    for it in p["items"]:
        if it["ktru_code"] is None:
            portable = next(k["code"] for k in c.get(f"{API}/ktru").json() if "портативный" in k["name"])
            c.patch(f"{API}/procurements/{pid}/items/{it['id']}", json={"ktru_code": portable}).raise_for_status()
            print(f"  · КТРУ позиции {it['line_no']} выбран человеком: {portable}")
    c.post(f"{API}/procurements/{pid}/confirm-spec").raise_for_status()
    print("3. Спецификация подтверждена")

    p = wait(c, pid, lambda x: x["status"] == "collecting" and len(x["quotes"]) >= 9, "поставщики и цены сайтов")
    sel = [x for x in p["candidates"] if x["selected"]]
    print(f"  · поставщиков {len(p['candidates'])}, выбрано {len(sel)}, исключено "
          f"{[x['name'] for x in p['candidates'] if not x['selected']]}")
    p = wait(c, pid, lambda x: sum(1 for m in x["messages"] if m["direction"] == "in") >= 4, "первые ответы")
    c.post(f"{API}/procurements/{pid}/accelerate", json={"hours": 24}).raise_for_status()
    print("4. Ускорено время +24 ч")
    p = wait(c, pid, lambda x: x["status"] in ("analysis", "justification_review"), "сбор завершён, анализ")

    a = p["analysis"]
    for it in a["items"]:
        print(f"  · поз. {it['line_no']}: цен в расчёте {it['admitted']}/{it['quotes']}, средняя {it['mean']}, "
              f"CV {it['cv_pct']} %, НМЦК {it['nmck']}, {'ок' if it['ok'] else [v['code'] for v in it['verdicts']]}")
    if not a["ready"]:
        bad = next(it for it in a["items"] if not it["ok"])
        mine = [q for q in p["quotes"] if q["spec_item_id"] == bad["item_id"] and a["quotes"][str(q["id"])]["admitted"]]
        outlier = max(mine, key=lambda q: float(q["unit_price"]))
        c.post(f"{API}/procurements/{pid}/quotes/{outlier['id']}/decision",
               json={"decision": "exclude", "reason": "предложен проектор другого класса — несопоставимо"}
               ).raise_for_status()
        print(f"5. Человек исключил выброс: {outlier['source_name']} {outlier['unit_price']} ₽")
        p = c.get(f"{API}/procurements/{pid}").json()
    a = p["analysis"]
    print(f"6. Итог: {p['status_title']}, НМЦК {a['total_nmck']} ₽")
    chain = c.get(f"{API}/journal/verify").json()
    print(f"7. Журнал: {'цел' if chain['ok'] else 'НАРУШЕН'}, записей {chain['checked']}")
    ok = p["status"] == "justification_review" and a["ready"] and chain["ok"]
    print("СЦЕНАРИЙ ПРОШЁЛ" if ok else "СЦЕНАРИЙ НЕ ПРОШЁЛ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
