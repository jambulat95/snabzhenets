"""Снимки страниц товаров для доказательного пакета: uv run python scripts/snapshot_shops.py

Берёт URL из data/replay/shops/manifest.json (его пишет record_shops.py), открывает каждую страницу
в Chromium (Playwright), сохраняет снимок всей страницы <позиция>.jpg рядом с HTML и дописывает
в манифест sha256 и время снимка. Запросы последовательные, пауза DELAY_S; капчу не обходим.
"""

import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from playwright.async_api import async_playwright

UA = "Mozilla/5.0 (compatible; snabzhenets-demo/0.1; student project)"
DELAY_S = 3.0
SHOPS = Path(__file__).resolve().parents[2] / "data" / "replay" / "shops"


async def main() -> int:
    manifest = json.loads((SHOPS / "manifest.json").read_text("utf-8"))
    failed = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900}, locale="ru-RU")
        for row in manifest:
            if row["item"] == "robots":
                continue
            page = await ctx.new_page()
            try:
                await page.goto(row["url"], wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2500)  # дорисовать цену и картинки
                out = SHOPS / row["shop"] / f"{row['item']}.jpg"
                data = await page.screenshot(full_page=True, type="jpeg", quality=60)
                out.write_bytes(data)
                row["screenshot"] = {
                    "file": str(out.relative_to(SHOPS.parent)),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "taken_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "bytes": len(data),
                }
                print(f"{row['shop']:16} {row['item']:10} снимок {len(data) // 1024} КБ")
            except Exception as e:  # noqa: BLE001 — одна страница не должна ронять запись остальных
                failed += 1
                print(f"{row['shop']:16} {row['item']:10} ОШИБКА {type(e).__name__}: {e}"[:200])
            finally:
                await page.close()
            await asyncio.sleep(DELAY_S)
        await browser.close()
    (SHOPS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
