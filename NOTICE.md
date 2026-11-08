# NOTICE — перенесённый код

Часть кода перенесена из проекта **«A2A Маркет»** (агентный B2B-маркетплейс), разработанного в октябре 2026 года командой проекта для конкурса RLT.Startup (Росэлторг), в которую входил автор «Снабженца». Код используется с согласия соавторов.

Источник: репозиторий `TseiDero/A2AB2Bmarketplace`, ветка `main`, коммит `de767e2` (01.11.2026).

| Модуль «Снабженца» | Откуда в A2A Маркет |
|---|---|
| `backend/app/ai/gateway/` | `backend/app/agents/ml/gateway/` |
| `backend/app/ai/parse/` | `backend/app/agents/ml/parse/` |
| `backend/app/ai/search/` (кроме `catalog.py`) | `backend/app/agents/ml/search/` |
| `backend/app/ai/email_offer.py`, `price_columns.py`, `injection.py`, `runtime.py` | `backend/app/agents/ml/` |
| `backend/app/ai/prompts/` (разбор заявки, писем, колонок прайса) | `backend/app/agents/ml/prompts/` |
| `backend/app/inn.py` | `backend/app/inn.py` |
| `backend/tests/ai/` | `backend/tests/ml/` (часть) |
| `backend/eval/` | `ml/src/ml_eval/`, `ml/scripts/eval_*.py`, `ml/eval/{parse,email,attacks}/` |
| `frontend/` (каркас: конфиги, тема, раскладка, API-клиент, авторизация, часть компонентов) | `frontend/` |
| `backend/app/auth/`, `security.py`, `journal.py` (адаптирован), миграция `0002` | `backend/app/auth/`, `security.py`, `journal/service.py`, миграция триггера журнала |

Перенос сделан отдельными коммитами «перенос из A2A Маркет: …» без правок; все изменения — в следующих коммитах.
