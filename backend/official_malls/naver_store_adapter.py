"""
naver_store_adapter.py — 네이버 쇼핑 검색 기반 스펙 크롤링 어댑터
LG·삼성 외 브랜드의 공식 스펙 교차검증에 사용.
"""
import json
from pathlib import Path

from playwright.async_api import async_playwright

from official_malls.base_adapter import BaseAdapter

SELECTORS_PATH = Path(__file__).parent.parent / "selectors" / "naver.json"


def _load_selectors() -> dict:
    with open(SELECTORS_PATH, encoding="utf-8") as f:
        return json.load(f)


class NaverStoreAdapter(BaseAdapter):
    """네이버 쇼핑 검색 기반 어댑터."""

    ADAPTER_NAME = "naver"

    def __init__(self, brand: str = "") -> None:
        self.brand = brand

    async def search_and_parse(self, model_name: str) -> dict[str, str]:
        sel = _load_selectors()
        brand_enc = self.brand.replace(" ", "+")
        search_url = sel["search_url"].format(
            model=model_name.replace(" ", "+"),
            brand=brand_enc,
        )
        item_selectors: list[str] = sel["selectors"]["product_item"]
        link_selectors: list[str] = sel["selectors"]["product_link"]
        spec_tab_selectors: list[str] = sel["selectors"]["spec_section_trigger"]
        label_selectors: list[str] = sel["selectors"]["spec_label"]
        value_selectors: list[str] = sel["selectors"]["spec_value"]

        result: dict[str, str] = {}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await self._stealth_context(browser)
            page = await ctx.new_page()

            try:
                # 1) 네이버 쇼핑 검색
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
                await self._random_delay(2.0, 3.5)

                # 2) 첫 번째 상품 링크 추출 후 이동
                #    product_item 안의 product_link를 찾거나, 직접 link_selectors로 시도
                prod_url = None
                items = await self._try_query_all(page, item_selectors)
                if items:
                    link_el = await self._try_click_first(items[0], link_selectors)  # type: ignore[arg-type]
                    if not link_el:
                        # fallback: 직접 페이지에서 링크 탐색
                        link_el_raw = await self._try_query_all(page, link_selectors)
                        if link_el_raw:
                            prod_url = await link_el_raw[0].get_attribute("href")
                else:
                    link_el_raw = await self._try_query_all(page, link_selectors)
                    if link_el_raw:
                        prod_url = await link_el_raw[0].get_attribute("href")

                # 새 URL로 이동
                if prod_url:
                    await page.goto(prod_url, wait_until="domcontentloaded", timeout=30_000)
                    await self._random_delay(1.5, 2.5)

                # 3) 스펙 탭 클릭 시도
                await self._try_click_first(page, spec_tab_selectors)
                await self._random_delay(1.0, 1.8)

                # 4) 스펙 파싱
                labels = await self._try_query_all(page, label_selectors)
                values = await self._try_query_all(page, value_selectors)

                if not labels:
                    result = await self._fallback_table_parse(page)
                else:
                    for label_el, value_el in zip(labels, values):
                        k = (await label_el.inner_text()).strip()
                        v = (await value_el.inner_text()).strip()
                        if k and v:
                            result[k] = v

            except Exception as e:
                print(f"[naver_adapter] 크롤링 오류: {e}")
            finally:
                await ctx.close()
                await browser.close()

        return result

    @staticmethod
    async def _fallback_table_parse(page) -> dict[str, str]:
        """table/th/td 구조로 fallback 파싱."""
        result: dict[str, str] = {}
        try:
            rows = await page.query_selector_all("table tr")
            for row in rows:
                th = await row.query_selector("th")
                td = await row.query_selector("td")
                if th and td:
                    k = (await th.inner_text()).strip()
                    v = (await td.inner_text()).strip()
                    if k and v:
                        result[k] = v
        except Exception:
            pass
        return result
