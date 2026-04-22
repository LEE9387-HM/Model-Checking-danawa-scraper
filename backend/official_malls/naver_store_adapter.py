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
    
    BRAND_STORES = {
        "삼성전자": "https://brand.naver.com/samsung",
        "LG전자": "https://brand.naver.com/lgebest",
        "위니아": "https://brand.naver.com/winia",
        "쿠쿠": "https://brand.naver.com/cuckoo",
    }

    def __init__(self, brand: str = "") -> None:
        self.brand = brand

    async def search_and_parse(self, model_name: str) -> dict[str, str]:
        sel = _load_selectors()
        
        # 0) 브랜드스토어 전용 URL 확인
        store_base = self.BRAND_STORES.get(self.brand)
        if store_base:
            search_url = f"{store_base}/search?q={model_name.replace(' ', '+')}"
        else:
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
                # 1) 검색 페이지 이동
                await page.goto(search_url, wait_until="networkidle", timeout=40_000)
                await self._random_delay(2.0, 3.5)

                # 2) 상품 링크 추출
                prod_url = None
                
                # 브랜드스토어 검색 결과인 경우 특정 클래스 시도
                if store_base:
                    store_link = await page.query_selector("a[class*='ProductCard_link']")
                    if store_link:
                        prod_url = await store_link.get_attribute("href")
                        if prod_url and not prod_url.startswith("http"):
                            prod_url = "https://brand.naver.com" + prod_url

                if not prod_url:
                    items = await self._try_query_all(page, item_selectors)
                    if items:
                        # 첫 번째 아이템에서 링크 탐색
                        link_el = await self._try_query_first(items[0], link_selectors)  # type: ignore[arg-type]
                        if link_el:
                            prod_url = await link_el.get_attribute("href")
                    
                    if not prod_url:
                        # 전체 페이지에서 직접 링크 탐색
                        link_el_list = await self._try_query_all(page, link_selectors)
                        if link_el_list:
                            prod_url = await link_el_list[0].get_attribute("href")

                # 3) 상세 페이지 이동 및 파싱
                if prod_url:
                    if not prod_url.startswith("http"):
                        prod_url = "https://search.shopping.naver.com" + prod_url
                    await page.goto(prod_url, wait_until="networkidle", timeout=40_000)
                    await self._random_delay(1.5, 2.5)

                # 스펙 탭 클릭 시도
                await self._try_click_first(page, spec_tab_selectors)
                await self._random_delay(1.0, 1.8)

                # 스펙 파싱
                labels = await self._try_query_all(page, label_selectors)
                values = await self._try_query_all(page, value_selectors)

                if labels and len(labels) == len(values):
                    for label_el, value_el in zip(labels, values):
                        k = (await label_el.inner_text()).strip()
                        v = (await value_el.inner_text()).strip()
                        if k and v:
                            result[k] = v
                
                # 결과가 없으면 테이블 기반 파싱 시도
                if not result:
                    result = await self._fallback_table_parse(page)

            except Exception as e:
                print(f"[naver_adapter] 크롤링 오류: {e}")
            finally:
                await ctx.close()
                await browser.close()

        return result

    @staticmethod
    async def _fallback_table_parse(page) -> dict[str, str]:
        """table/th/td 구조 또는 dl/dt/dd 구조로 fallback 파싱."""
        result: dict[str, str] = {}
        try:
            # Table 기반
            rows = await page.query_selector_all("table tr")
            for row in rows:
                th = await row.query_selector("th")
                td = await row.query_selector("td")
                if th and td:
                    k = (await th.inner_text()).strip()
                    v = (await td.inner_text()).strip()
                    if k and v:
                        result[k] = v
            
            # DL 기반 (네이버 상세페이지 단축형)
            if not result:
                dts = await page.query_selector_all("dl dt")
                dds = await page.query_selector_all("dl dd")
                if dts and len(dts) == len(dds):
                    for dt, dd in zip(dts, dds):
                        k = (await dt.inner_text()).strip()
                        v = (await dd.inner_text()).strip()
                        if k and v:
                            result[k] = v
        except Exception:
            pass
        return result
