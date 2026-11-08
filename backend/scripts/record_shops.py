"""Записать страницы магазинов для офлайн-демо (replay): uv run python scripts/record_shops.py

Источники выбраны в docs/SOURCES.md: Регард (цена в JSON-LD) и НИКС (microdata, windows-1251,
региональная версия max.nix.ru). Запросы последовательные, пауза DELAY_S, честный User-Agent,
robots.txt сохраняется рядом. Капчу и вход не обходим: страница без цены — помечается, не повторяется.

Результат: data/replay/shops/<магазин>/<позиция>.html (байты как пришли) и manifest.json:
URL, время, HTTP-статус, sha256, кодировка, цена, которую код нашёл в разметке (для контроля записи).
"""

import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

UA = "Mozilla/5.0 (compatible; snabzhenets-demo/0.1; student project)"
DELAY_S = 3.0
OUT = Path(__file__).resolve().parents[2] / "data" / "replay" / "shops"

PAGES: dict[str, dict[str, str]] = {
    "regard": {
        "cartridge": "https://www.regard.ru/product/322723/kartridz-hp-cf259a-59a-black",
        "projector": "https://www.regard.ru/product/42625/proektor-acer-x1123hp",
        "paper": "https://www.regard.ru/product/105108/bumaga-svetocopy-a4-80-g-m2-500-listov",
        "robots": "https://www.regard.ru/robots.txt",
    },
    "nix": {
        "cartridge": "https://www.nix.ru/autocatalog/supplies_hp_original/Kartridzh-HP-CF259A-dlya-HP-LJ-MFP-M304-404-428_441217.html",
        "projector": "https://www.nix.ru/autocatalog/projector_acer/Acer-Projector-X1123HP_694238.html",
        "paper": "https://www.nix.ru/autocatalog/paper/SvetoCopy-Classic-A4-bumaga-500-listov-80-g-m2-Rossiya_7143.html",
        "robots": "https://www.nix.ru/robots.txt",
    },
    "nix_makhachkala": {
        "cartridge": "https://max.nix.ru/autocatalog/supplies_hp_original/Kartridzh-HP-CF259A-dlya-HP-LJ-MFP-M304-404-428_441217.html",
        "projector": "https://max.nix.ru/autocatalog/projector_acer/Acer-Projector-X1123HP_694238.html",
        "paper": "https://max.nix.ru/autocatalog/paper/SvetoCopy-Classic-A4-bumaga-500-listov-80-g-m2-Rossiya_7143.html",
    },
}

BLOCK_MARKERS = ("smartcaptcha", "g-recaptcha", "hcaptcha", "captcha-container", "ddos-guard", "Доступ ограничен")
_JSONLD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_MICRO = re.compile(r'itemprop="price"[^>]*content="([0-9.]+)"|content="([0-9.]+)"[^>]*itemprop="price"')


def charset(resp: httpx.Response) -> str:
    m = re.search(rb'charset=["\']?([\w-]+)', resp.content[:4000])
    return resp.charset_encoding or (m.group(1).decode() if m else "utf-8")


def markup_price(text: str) -> tuple[str | None, str | None]:
    """Цена из разметки — тем же способом, что будет в WebPricePort: JSON-LD Offer, потом microdata."""
    for block in _JSONLD.findall(text):
        m = re.search(r'"price"\s*:\s*"?([0-9.]+)', block)
        if m and ('"Offer"' in block or "offers" in block):
            return m.group(1), "json-ld"
    m = _MICRO.search(text)
    if m:
        return m.group(1) or m.group(2), "microdata"
    return None, None


def main() -> int:
    manifest: list[dict[str, object]] = []
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        for shop, pages in PAGES.items():
            (OUT / shop).mkdir(parents=True, exist_ok=True)
            for key, url in pages.items():
                resp = client.get(url)
                enc = charset(resp)
                text = resp.content.decode(enc, errors="replace")
                ext = "txt" if key == "robots" else "html"
                path = OUT / shop / f"{key}.{ext}"
                path.write_bytes(resp.content)
                blocked = any(b.lower() in text.lower() for b in BLOCK_MARKERS)
                price, how = (None, None) if key == "robots" else markup_price(text)
                row = {
                    "shop": shop, "item": key, "url": str(resp.url), "status": resp.status_code,
                    "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "sha256": hashlib.sha256(resp.content).hexdigest(), "encoding": enc,
                    "bytes": len(resp.content), "file": str(path.relative_to(OUT.parent)),
                    "markup_price": price, "markup": how, "blocked": blocked,
                }
                manifest.append(row)
                print(f"{shop:16} {key:10} {resp.status_code} {len(resp.content):>8} б  цена={price} ({how})"
                      f"{'  БЛОК' if blocked else ''}")
                time.sleep(DELAY_S)
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    bad = [r for r in manifest if r["item"] != "robots" and (r["status"] != 200 or r["blocked"])]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
