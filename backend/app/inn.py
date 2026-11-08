W10 = [2, 4, 10, 3, 5, 9, 4, 6, 8]
W11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
W12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]


def _check(digits: list[int], weights: list[int]) -> int:
    return sum(d * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def is_valid_inn(inn: str) -> bool:
    """Проверка контрольной суммы ИНН: 10 цифр (организация) или 12 (ИП)."""
    if not inn.isdigit() or len(inn) not in (10, 12):
        return False
    d = [int(c) for c in inn]
    if len(d) == 10:
        return d[9] == _check(d, W10)
    return d[10] == _check(d, W11) and d[11] == _check(d, W12)