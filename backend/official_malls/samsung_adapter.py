"""
samsung_adapter.py — 삼성 공식몰(samsung.com/sec) 크롤링 어댑터
"""
import json
from pathlib import Path

from playwright.async_api import async_playwright

from official_malls.base_adapter import BaseAdapter

SELECTORS_PATH = Path(__file__).parent.parent / "selectors" / "samsung.json"


def _load_selectors() -> dict:
    with open(SELECTORS_PATH, encoding="utf-8") as f:
        return json.load(f)


class SamsungAdapter(BaseAdapter):
    """삼성 공식몰(samsung.com/sec) 어댑터."""

    ADAPTER_NAME = "samsung"

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
                # 1) 검색 페이지 진입
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
                await self._random_delay(2.0, 3.5)

                # 2) 첫 번째 검색 결과 클릭
                clicked = await self._try_click_first(page, search_selectors)
                if not clicked:
                    print(f"[samsung_adapter] 검색 결과 없음: {model_name}")
                    return {}

                await page.wait_for_load_state("domcontentloaded")
                await self._random_delay(1.5, 2.5)

                # 3) 스펙 탭 클릭 (있을 경우)
                await self._try_click_first(page, spec_tab_selectors)
                await self._random_delay(1.0, 1.8)

                # 4) 스펙 라벨 / 값 파싱
                labels = await self._try_query_all(page, label_selectors)
                values = await self._try_query_all(page, value_selectors)

                if not labels:
                    # fallback: 페이지 텍스트 기반 파싱
                    result = await self._fallback_text_parse(page)
                else:
                    for label_el, value_el in zip(labels, values):
                        k = (await label_el.inner_text()).strip()
                        v = (await value_el.inner_text()).strip()
                        if k and v:
                            result[k] = v

                # 5) 가격 추출 (신규)
                price_selectors: list[str] = sel["selectors"].get("price", [])
                for p_sel in price_selectors:
                    try:
                        p_el = await page.query_selector(p_sel)
                        if p_el:
                            p_text = await p_el.inner_text()
                            nums = "".join(filter(str.isdigit, p_text))
                            if nums:
                                result["__price__"] = nums
                                break
                    except Exception:
                        continue

            except Exception as e:
                print(f"[samsung_adapter] 크롤링 오류: {e}")
            finally:
                await ctx.close()
                await browser.close()

        return result

    @staticmethod
    async def _fallback_text_parse(page) -> dict[str, str]:
        """
        셀렉터 미매칭 시 <dl>/<dt>/<dd> 구조로 fallback 파싱.
        """
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
