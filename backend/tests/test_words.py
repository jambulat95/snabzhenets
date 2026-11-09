from decimal import Decimal

from app.documents.words import number_words, rubles


def test_numbers() -> None:
    assert number_words(1) == "один"
    assert number_words(21) == "двадцать один"
    assert number_words(1000) == "одна тысяча"
    assert number_words(2002) == "две тысячи два"
    assert number_words(11000) == "одиннадцать тысяч"
    assert number_words(1_000_000) == "один миллион"


def test_rubles() -> None:
    assert rubles(Decimal("353780.67")) == "Триста пятьдесят три тысячи семьсот восемьдесят рублей 67 копеек"
    assert rubles(Decimal("1.01")) == "Один рубль 01 копейка"
    assert rubles(Decimal("22.5")) == "Двадцать два рубля 50 копеек"
    assert rubles(Decimal("111")) == "Сто одиннадцать рублей 00 копеек"
