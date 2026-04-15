"""
base_adapter.py — 공식몰 어댑터 추상 기본 클래스
모든 제조사 어댑터는 이 클래스를 상속해서 구현한다.
"""
import asyncio
import random
import sys
from abc import ABC, abstractmethod

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


class BaseAdapter(ABC):
    """공식몰 크롤링 어댑터 기본 클래스."""

    # 서브클래스에서 재정의
    ADAPTER_NAME: str = "base"

    # ─── Playwright 공통 유틸 ────────────────────────────────────────────────

    @staticmethod
    async def _stealth_context(browser: Browser) -> BrowserContext:
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 900},
        )
        # webdriver 플래그 숨기기
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        return ctx

    @staticmethod
    async def _random_delay(lo: float = 1.5, hi: float = 3.0) -> None:
        await asyncio.sleep(random.uniform(lo, hi))

    @staticmethod
    async def _try_click_first(page: Page, selectors: list[str]) -> bool:
        """selector 목록을 순서대로 시도해 첫 번째로 찾은 요소를 클릭."""
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    async def _try_query_all(page: Page, selectors: list[str]) -> list:
        """selector 목록을 순서대로 시도해 첫 번째로 결과가 있는 것을 반환."""
        for sel in selectors:
            try:
                els = await page.query_selector_all(sel)
                if els:
                    return els
            except Exception:
                continue
        return []

    # ─── 서브클래스 구현 필수 ────────────────────────────────────────────────

    @abstractmethod
    async def search_and_parse(self, model_name: str) -> dict[str, str]:
        """
        공식몰에서 모델명을 검색하고 스펙을 파싱해 반환.

        Returns:
            {"스펙라벨": "값", ...}  — 빈 dict이면 모델 없음/파싱 실패
        """
        ...

    # ─── 공통 진입점 ────────────────────────────────────────────────────────

    async def fetch(self, model_name: str) -> dict[str, str]:
        """Windows ProactorEventLoop 스레드에서 실행. 에러 발생 시 빈 dict 반환."""
        adapter = self

        def _run():
            if sys.platform == "win32":
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(adapter.search_and_parse(model_name))
            except Exception as e:
                print(f"[{adapter.ADAPTER_NAME}] fetch 오류: {e}")
                return {}
            finally:
                loop.close()

        return await asyncio.to_thread(_run)
