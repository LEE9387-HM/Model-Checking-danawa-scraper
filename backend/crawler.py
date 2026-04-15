"""
crawler.py — Playwright 기반 다나와 크롤러 (비동기)
다나와 검색 → 상세 페이지 진입 → 스펙 테이블 파싱 → 경쟁사 탐색
"""
import asyncio
import json
import random
import re
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

SELECTORS_PATH = Path(__file__).parent / "selectors" / "danawa.json"


def _load_selectors() -> dict:
    with open(SELECTORS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _random_delay(min_ms: int = 1000, max_ms: int = 3000) -> float:
    return random.randint(min_ms, max_ms) / 1000


async def _stealth_context(browser: Browser) -> BrowserContext:
    """최소 stealth 설정 컨텍스트 생성"""
    sel = _load_selectors()
    ua = random.choice(sel["anti_bot"]["user_agents"])
    ctx = await browser.new_context(
        user_agent=ua,
        viewport={"width": 1366, "height": 768},
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        extra_http_headers={
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    # JS 자동화 감지 우회
    await ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return ctx


async def _parse_spec_table(page: Page) -> dict[str, str]:
    """다나와 상세 페이지 스펙 테이블 파싱"""
    raw: dict[str, str] = {}
    try:
        rows = await page.query_selector_all(".spec-descr-item, .spec_list tr")
        for row in rows:
            th = await row.query_selector("th, .spec-descr-item__title")
            td = await row.query_selector("td, .spec-descr-item__desc")
            if th and td:
                key = (await th.inner_text()).strip()
                val = (await td.inner_text()).strip()
                if key:
                    raw[key] = val
    except Exception as e:
        print(f"[crawler] 스펙 테이블 파싱 오류: {e}")
    return raw


async def _extract_price(page: Page) -> int:
    """최저가 추출"""
    try:
        el = await page.query_selector(".lowest_price strong, .prc_t")
        if el:
            text = await el.inner_text()
            nums = re.sub(r"[^\d]", "", text)
            return int(nums) if nums else 0
    except Exception:
        pass
    return 0


async def _extract_review_count(page: Page) -> int:
    """리뷰 수 추출"""
    try:
        el = await page.query_selector(".cnt_review, .danawa-review-count")
        if el:
            text = await el.inner_text()
            nums = re.sub(r"[^\d]", "", text)
            return int(nums) if nums else 0
    except Exception:
        pass
    return 0


async def _extract_brand(page: Page) -> str:
    """브랜드(제조사) 추출"""
    try:
        rows = await page.query_selector_all(".spec_list tr")
        for row in rows:
            th = await row.query_selector("th")
            td = await row.query_selector("td")
            if th and td:
                label = (await th.inner_text()).strip()
                if "제조회사" in label or "브랜드" in label:
                    return (await td.inner_text()).strip()
    except Exception:
        pass
    return ""


async def fetch_model_spec(model_name: str) -> dict[str, Any]:
    """
    다나와에서 단일 모델의 스펙을 크롤링.

    Returns:
        {
            "model_name": ...,
            "product_url": ...,
            "raw_spec": {스펙명: 스펙값, ...},
            "price": int,
            "review_count": int,
            "brand": str,
        }
    """
    search_url = f"https://search.danawa.com/dsearch.php?query={model_name}"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await _stealth_context(browser)
        page = await ctx.new_page()

        try:
            # ─ Step 1: 검색 ─
            print(f"[crawler] 검색: {model_name}")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(_random_delay(800, 1500))

            # 첫 번째 검색 결과 클릭
            link = await page.query_selector(
                ".prod-list .prod-item:first-child .prod-name a, "
                ".product_list .prod_item:first-child .prod_name a"
            )
            if not link:
                print(f"[crawler] 검색 결과 없음: {model_name}")
                return {"error": "검색 결과 없음", "model_name": model_name}

            product_url = await link.get_attribute("href") or ""
            await link.click()
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(_random_delay(1000, 2000))

            # ─ Step 2: 상세 페이지 스펙 파싱 ─
            raw_spec = await _parse_spec_table(page)
            price = await _extract_price(page)
            review_count = await _extract_review_count(page)
            brand = await _extract_brand(page)

            # 메타 스펙을 raw에 삽입
            raw_spec["__price__"] = str(price)
            raw_spec["__review_count__"] = str(review_count)
            raw_spec["__brand__"] = brand

            return {
                "model_name": model_name,
                "product_url": page.url,
                "raw_spec": raw_spec,
                "price": price,
                "review_count": review_count,
                "brand": brand,
            }

        except Exception as e:
            print(f"[crawler] 오류: {e}")
            return {"error": str(e), "model_name": model_name}
        finally:
            await ctx.close()
            await browser.close()


async def fetch_competitors(
    category_url: str,
    primary_spec_filter: dict[str, Any],
    exclude_brand: str = "삼성전자",
    max_count: int = 20,
    delay_between_sec: float = 3.0,
) -> list[dict[str, Any]]:
    """
    경쟁사 모델 목록 수집 (다나와 인기순).

    Args:
        category_url: 다나와 카테고리 URL (인기순 정렬 적용)
        primary_spec_filter: 필수 스펙 필터 {spec_name: value}
        exclude_brand: 제외할 브랜드 (삼성전자)
        max_count: 최대 수집 수 (스펙 크롤링은 필터 통과 후)
        delay_between_sec: 모델 간 딜레이

    Returns:
        [{model_name, product_url, raw_spec, price, review_count, brand, popularity_rank}, ...]
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await _stealth_context(browser)
        page = await ctx.new_page()

        try:
            await page.goto(category_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(_random_delay(1000, 2000))

            # 상품 링크 목록 수집
            items = await page.query_selector_all(
                ".product_list .prod_item, .prod-list .prod-item"
            )
            links: list[tuple[str, str, int]] = []  # (name, url, rank)
            for rank, item in enumerate(items[:30], 1):
                name_el = await item.query_selector(".prod_name a, .prod-name a")
                if not name_el:
                    continue
                name = (await name_el.inner_text()).strip()
                href = await name_el.get_attribute("href") or ""
                if exclude_brand in name:
                    continue
                links.append((name, href, rank))

            # 각 모델 상세 스펙 수집
            results = []
            for name, url, rank in links[:max_count]:
                if not url:
                    continue
                try:
                    prod_page = await ctx.new_page()
                    await prod_page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(_random_delay(800, 1500))

                    raw_spec = await _parse_spec_table(prod_page)
                    price = await _extract_price(prod_page)
                    review_count = await _extract_review_count(prod_page)
                    brand = await _extract_brand(prod_page)

                    raw_spec["__price__"] = str(price)
                    raw_spec["__review_count__"] = str(review_count)
                    raw_spec["__brand__"] = brand

                    results.append({
                        "model_name": name,
                        "product_url": url,
                        "raw_spec": raw_spec,
                        "price": price,
                        "review_count": review_count,
                        "brand": brand,
                        "popularity_rank": rank,
                    })

                    await prod_page.close()
                    await asyncio.sleep(delay_between_sec + random.uniform(-1, 1))

                except Exception as e:
                    print(f"[crawler] 경쟁사 수집 오류 {name}: {e}")
                    continue

            return results

        except Exception as e:
            print(f"[crawler] 경쟁사 탐색 오류: {e}")
            return []
        finally:
            await ctx.close()
            await browser.close()
