"""Виды задач ИИ-слоя, бюджеты токенов и пороги (значения — как в A2A Маркет, agents/contract.py)."""

from enum import StrEnum


class Kind(StrEnum):
    PARSE_REQUEST = "parse_request"  # текст заявки → позиции
    PARSE_EMAIL_OFFER = "parse_email_offer"  # ответ поставщика письмом → цены по позициям
    IMPORT_PRICE = "import_price"  # Excel-вложение → колонки прайса
    PICK_KTRU = "pick_ktru"  # позиция → код КТРУ из кандидатов
    MATCH_PAGE = "match_page"  # страница магазина ↔ позиция спецификации
    SUPPLIER_QUESTION = "supplier_question"  # вопрос поставщика → на что можно ответить


TOKEN_BUDGET: dict[Kind, int] = {
    Kind.PARSE_REQUEST: 8000,
    Kind.PARSE_EMAIL_OFFER: 8000,
    Kind.IMPORT_PRICE: 4000,
    Kind.PICK_KTRU: 3000,
    Kind.MATCH_PAGE: 4000,
    Kind.SUPPLIER_QUESTION: 2000,
}

# Ниже этой уверенности цены из письма проверяет человек
EMAIL_CONFIDENCE_MIN = 0.8
