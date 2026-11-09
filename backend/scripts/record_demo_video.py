"""Запасное видео демо: Playwright проходит сценарий docs/DEMO.md в интерфейсе и пишет экран.

    uv run python scripts/record_demo_video.py [папка]   # по умолчанию ~/projects/imfit_concurs/demo

Нужны: docker compose up, npm run dev (http://localhost:5173), сид. Сбрасывает демо кнопкой интерфейса.
Результат: snabzhenets-demo.webm и, если есть ffmpeg, snabzhenets-demo.mp4.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

WEB = "http://localhost:5173"
ACCOUNTS = Path(__file__).resolve().parents[1] / "demo_accounts.txt"
SIZE = {"width": 1440, "height": 900}


def password(email: str) -> str:
    for line in ACCOUNTS.read_text("utf-8").splitlines():
        parts = line.split("\t")
        if parts[0] == email:
            return parts[2]
    raise SystemExit("Нет демо-учётки: python -m app.seed")


def pause(s: float) -> None:
    time.sleep(s)


def scroll_to(page: Page, text: str) -> None:
    page.get_by_text(text, exact=True).first.scroll_into_view_if_needed()
    page.mouse.wheel(0, -120)
    pause(1.2)


def glide(page: Page, px: int, steps: int = 10) -> None:
    for _ in range(steps):
        page.mouse.wheel(0, px / steps)
        pause(0.12)


def run(page: Page) -> None:
    page.goto(WEB)
    page.locator("#email").fill("zakupki@chesu.demo")
    page.locator("#password").fill(password("zakupki@chesu.demo"))
    page.get_by_role("button", name="Войти").click()
    page.get_by_text("Заявки", exact=True).first.wait_for()
    pause(1)
    page.get_by_role("button", name="Сбросить демо").click()
    page.get_by_role("dialog").get_by_role("button", name="Сбросить").click()
    pause(2)

    page.get_by_role("button", name="Новая заявка").first.click()
    pause(1)
    page.get_by_role("button", name="Вставить пример").click()
    pause(2)
    page.get_by_role("button", name="Разобрать заявку").click()
    page.get_by_text("Агенту нужно уточнение").wait_for(timeout=120_000)
    pause(3)
    page.locator(".ant-select", has=page.get_by_text("Выберите код")).click()
    pause(1)
    page.locator(".ant-select-item-option", has_text="тип: портативный").click()
    pause(2)
    page.get_by_role("button", name="Подтвердить спецификацию").click()
    pause(1.5)
    page.get_by_role("dialog").get_by_role("button", name="Подтвердить", exact=True).click()

    page.get_by_text("Запрос отправлен 5 из 7").wait_for(timeout=120_000)
    pause(2)
    scroll_to(page, "Поставщики")
    page.get_by_text("Исключён", exact=True).first.hover()
    pause(3)
    page.get_by_text("Решает человек", exact=True).first.hover()
    pause(3)
    scroll_to(page, "Цены")
    pause(1)
    page.get_by_role("button", name="Доказательство").first.click()
    pause(5)
    page.keyboard.press("Escape")
    pause(1)
    page.wait_for_function("document.body.innerText.includes('ИП Мусаев А. (демо)') && "
                           "document.body.innerText.includes('Похоже на команду агенту')", timeout=120_000)
    scroll_to(page, "Переписка")
    page.locator(".ant-collapse-header", has_text="Похоже на команду агенту").first.click()
    pause(5)
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    pause(1.5)
    page.get_by_role("button", name="Ускорить время +24 ч").click()
    page.get_by_text("Цен в расчёте").wait_for(timeout=180_000)
    pause(1)
    scroll_to(page, "Проверка по методике")
    pause(4)
    row = page.locator("tr", has_text="70 710")
    row.scroll_into_view_if_needed()
    pause(2)
    row.get_by_role("button", name="Исключить").click()
    page.get_by_role("dialog").locator("textarea").fill("Цена вдвое выше рынка, поставщик не обосновал — выброс")
    pause(2)
    page.get_by_role("dialog").get_by_role("button", name="Исключить").click()
    page.get_by_role("button", name="Утвердить обоснование").wait_for(timeout=60_000)
    scroll_to(page, "Проверка по методике")
    pause(4)
    page.get_by_role("button", name="Утвердить обоснование").click()
    pause(1.5)
    page.get_by_role("dialog").get_by_role("button", name="Утвердить", exact=True).click()
    page.get_by_text("Обоснование (DOCX)").wait_for(timeout=60_000)
    pause(3)
    journal = page.locator(".ant-collapse-header", has_text="Журнал действий")
    journal.scroll_into_view_if_needed()
    journal.click()
    pause(1)
    page.locator("button", has_text="Проверить цепочку хешей").click()
    pause(2)
    glide(page, 600)
    pause(4)
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    pause(3)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "projects" / "imfit_concurs" / "demo"
    raw = out / "_raw"
    raw.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=SIZE, record_video_dir=str(raw), record_video_size=SIZE, locale="ru-RU")
        page = ctx.new_page()
        ok = False
        try:
            run(page)
            ok = True
        finally:
            video = page.video
            ctx.close()  # видео дописывается при закрытии контекста
            path = video.path() if video is not None else None
            browser.close()
    if not ok or path is None:
        return 1
    webm = out / "snabzhenets-demo.webm"
    shutil.move(path, webm)
    shutil.rmtree(raw, ignore_errors=True)
    print(f"видео: {webm}")
    if shutil.which("ffmpeg"):
        mp4 = webm.with_suffix(".mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-pix_fmt",
                        "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
        print(f"видео: {mp4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
