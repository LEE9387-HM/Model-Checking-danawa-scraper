"""
lg_adapter.py — LG전자 공식몰(lge.co.kr) 크롤링 어댑터
"""
import json
from pathlib import Path

from playwright.async_api import async_playwright

from official_malls.base_adapter import BaseAdapter

SELECTORS_PATH = Path(__file__).parent.parent / "selectors" / "lg.json"


def _load_selectors() -> dict:
    with open(SELECTORS_PATH, encoding="utf-8") as f:
        return json.load(f)


class LgAdapter(BaseAdapter):
    """LG전자 공식몰(lge.co.kr) 어댑터."""

    ADAPTER_NAME = "lg"

    async def search_and_parse(self, model_name: str) -> dict[str, str]:
        sel = _load_selectors()
        search_url = sel["search_url"].format(model=model_name)
        search_selectors: list[str] = sel["selectors"]["search_result"]
        spec_tab_selectors: list[str] = sel["selectors"]["spec_section_trigger"]
        label_selectors: list[str] = sel["selectors"]["spec_label"]
        value_selectors: list[str] = sel["selectors"]["spec_value"]

        result: dict[str, str] = {}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await self._stealth_context(browser)
            page = await ctx.new_page()

            try:
                # 1) 검색 페이지
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
                await self._random_delay(2.0, 3.5)

                # 2) 첫 번째 결과 클릭
                clicked = await self._try_click_first(page, search_selectors)
                if not clicked:
                    print(f"[lg_adapter] 검색 결과 없음: {model_name}")
                    return {}

                await page.wait_for_load_state("domcontentloaded")
                await self._random_delay(1.5, 2.5)

                # 3) 제품 사양 탭 클릭 시도
                await self._try_click_first(page, spec_tab_selectors)
                await self._random_delay(1.0, 2.0)

                # 4) 스펙 파싱
                labels = await self._try_query_all(page, label_selectors)
                values = await self._try_query_all(page, value_selectors)

                if not labels:
                    result = await self._fallback_text_parse(page)
                else:
                    for label_el, value_el in zip(labels, values):
                        k = (await label_el.inner_text()).strip()
                        v = (await value_el.inner_text()).strip()
                        if k and v:
                            result[k] = v

            except Exception as e:
                print(f"[lg_adapter] 크롤링 오류: {e}")
            finally:
                await ctx.close()
                await browser.close()

        return result

    @staticmethod
    async def _fallback_text_parse(page) -> dict[str, str]:
        """dl/dt/dd 구조로 fallback 파싱."""
        result: dict[str, str] = {}
        try:
            dts = await page.query_selector_all("dt")
            dds = await page.query_selector_all("dd")
            for dt, dd in zip(dts, dds):
                k = (await dt.inner_text()).strip()
                v = (await dd.inner_text()).strip()
                if k and v:
                    result[k] = v
        except Exception:
            pass
        return result
