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


# ─── 설정 로드 ────────────────────────────────────────────────────────────────

def _load_selectors() -> dict:
    with open(SELECTORS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_category_url(category: str) -> str:
    """카테고리 이름 → 다나와 인기순 URL"""
    sel = _load_selectors()
    code = sel["category_codes"].get(category, "112")
    return sel["category_list_url"].format(cate_code=code)


# ─── Playwright 유틸 ─────────────────────────────────────────────────────────

async def _stealth_context(browser: Browser) -> BrowserContext:
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
    await ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return ctx


def _rand_delay(min_ms: int = 1000, max_ms: int = 3000) -> float:
    return random.randint(min_ms, max_ms) / 1000


async def _query_first(page: Page, selectors: list[str]):
    """여러 셀렉터를 순서대로 시도해 첫 번째 매칭 요소 반환."""
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                return el
        except Exception:
            continue
    return None


async def _query_all(page: Page, selectors: list[str]) -> list:
    """여러 셀렉터를 순서대로 시도해 첫 번째로 결과가 있는 목록 반환."""
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            if els:
                return els
        except Exception:
            continue
    return []


# ─── 스펙 파싱 헬퍼 ──────────────────────────────────────────────────────────

async def _parse_spec_table(page: Page) -> dict[str, str]:
    """다나와 상세 페이지 스펙 테이블 파싱."""
    raw: dict[str, str] = {}
    try:
        rows = await _query_all(page, [".spec-descr-item", ".spec_list tr"])
        for row in rows:
            th = await _query_first(row, [".spec-descr-item__title", "th"])
            td = await _query_first(row, [".spec-descr-item__desc", "td"])
            if th and td:
                key = (await th.inner_text()).strip()
                val = (await td.inner_text()).strip()
                if key and val:
                    raw[key] = val
    except Exception as e:
        print(f"[crawler] 스펙 테이블 파싱 오류: {e}")
    return raw


async def _extract_price(page: Page) -> int:
    sel_list = [".lowest_price strong", ".pricelist-item__price-link", ".prc_t"]
    el = await _query_first(page, sel_list)
    if el:
        text = await el.inner_text()
        nums = re.sub(r"[^\d]", "", text)
        return int(nums) if nums else 0
    return 0


async def _extract_review_count(page: Page) -> int:
    sel_list = [".cnt_review", ".cmt_count", ".danawa-review-count"]
    el = await _query_first(page, sel_list)
    if el:
        text = await el.inner_text()
        nums = re.sub(r"[^\d]", "", text)
        return int(nums) if nums else 0
    return 0


async def _extract_brand(page: Page, spec_table: dict[str, str]) -> str:
    """스펙 테이블에서 브랜드 추출 (already parsed raw_spec 활용)."""
    for key in ("제조회사", "브랜드", "제조사"):
        if key in spec_table:
            return spec_table[key]
    # fallback: 직접 셀렉터
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


async def _extract_release_year(page: Page, spec_table: dict[str, str]) -> int | None:
    """출시년도 추출. 스펙 테이블 우선, 없으면 셀렉터 시도."""
    for key in ("출시년월", "출시연도", "출시 연도", "출시년도"):
        if key in spec_table:
            val = spec_table[key]
            m = re.search(r"(\d{4})", val)
            if m:
                return int(m.group(1))
    return None


def _passes_primary_filter(raw_spec: dict[str, str], primary_filter: dict[str, Any]) -> bool:
    """
    필수 스펙 필터 통과 여부.
    primary_filter: {spec_label: expected_value, ...}
    값이 없는 필터는 통과로 처리.
    """
    for label, expected in primary_filter.items():
        if not expected:
            continue
        actual = raw_spec.get(label, "")
        if str(expected).lower() not in actual.lower():
            return False
    return True


def _passes_year_filter(release_year: int | None, samsung_year: int | None, window: int = 2) -> bool:
    """출시년도 ±window년 필터."""
    if samsung_year is None or release_year is None:
        return True  # 년도 정보 없으면 통과
    return abs(release_year - samsung_year) <= window


# ─── 공개 API ────────────────────────────────────────────────────────────────

async def fetch_model_spec(model_name: str) -> dict[str, Any]:
    """
    다나와에서 단일 모델의 스펙을 크롤링.

    Returns:
        {
            "model_name", "product_url", "raw_spec", "price",
            "review_count", "brand", "release_year", "category"
        }
    """
    search_url = f"https://search.danawa.com/dsearch.php?query={model_name}"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await _stealth_context(browser)
        page = await ctx.new_page()

        try:
            print(f"[crawler] 검색: {model_name}")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(_rand_delay(800, 1500))

            link = await _query_first(page, [
                ".prod-list .prod-item:first-child .prod-name a",
                ".prod_list .prod_item:first-child .prod_name a",
                ".product_list .prod_item:first-child .prod_name a",
            ])
            if not link:
                return {"error": "검색 결과 없음", "model_name": model_name}

            await link.click()
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(_rand_delay(1000, 2000))

            raw_spec = await _parse_spec_table(page)
            price = await _extract_price(page)
            review_count = await _extract_review_count(page)
            brand = await _extract_brand(page, raw_spec)
            release_year = await _extract_release_year(page, raw_spec)

            # 메타 삽입
            raw_spec["__price__"] = str(price)
            raw_spec["__review_count__"] = str(review_count)
            raw_spec["__brand__"] = brand
            if release_year:
                raw_spec["__release_year__"] = str(release_year)

            # 카테고리 추출 (빵부스러기 마지막 항목)
            category = ""
            try:
                crumbs = await page.query_selector_all(".breadcrumb a, .bread_nav a")
                if crumbs:
                    category = (await crumbs[-1].inner_text()).strip()
            except Exception:
                pass

            return {
                "model_name": model_name,
                "product_url": page.url,
                "raw_spec": raw_spec,
                "price": price,
                "review_count": review_count,
                "brand": brand,
                "release_year": release_year,
                "category_label": category,
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
    samsung_release_year: int | None = None,
    year_window: int = 2,
    delay_between_sec: float = 3.0,
) -> list[dict[str, Any]]:
    """
    경쟁사 모델 목록 수집 (다나와 인기순).

    Args:
        category_url: 다나와 카테고리 URL (인기순 정렬)
        primary_spec_filter: 필수 스펙 필터 {다나와_스펙명: 기대값}
        exclude_brand: 제외할 브랜드 (삼성전자)
        max_count: 스펙 크롤링할 최대 후보 수
        samsung_release_year: 삼성 모델 출시년도 (±year_window 필터용)
        year_window: 출시년도 허용 범위
        delay_between_sec: 모델 간 기본 딜레이(초)

    Returns:
        [{model_name, product_url, raw_spec, price, review_count,
          brand, release_year, popularity_rank}, ...]
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await _stealth_context(browser)
        page = await ctx.new_page()

        try:
            print(f"[crawler] 경쟁사 탐색: {category_url}")
            await page.goto(category_url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(_rand_delay(1500, 2500))

            # 상품 목록 수집
            items = await _query_all(page, [
                ".prod_list .prod_item",
                ".product_list .prod_item",
                ".prod-list .prod-item",
            ])

            links: list[tuple[str, str, int]] = []  # (name, url, rank)
            for rank, item in enumerate(items[:40], 1):
                name_el = await _query_first(item, [".prod_name a", ".prod-name a"])
                if not name_el:
                    continue
                name = (await name_el.inner_text()).strip()
                href = await name_el.get_attribute("href") or ""
                # 삼성 제외
                brand_el = await _query_first(item, [".brand_name", ".mfr_name"])
                item_brand = (await brand_el.inner_text()).strip() if brand_el else ""
                if exclude_brand in name or exclude_brand in item_brand:
                    continue
                if href:
                    links.append((name, href, rank))

            print(f"[crawler] 경쟁사 후보 {len(links)}개 (삼성 제외)")

            # 각 모델 상세 크롤링
            results = []
            crawled = 0
            for name, url, rank in links:
                if crawled >= max_count:
                    break
                try:
                    prod_page = await ctx.new_page()
                    await prod_page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await asyncio.sleep(_rand_delay(800, 1500))

                    raw_spec = await _parse_spec_table(prod_page)
                    price = await _extract_price(prod_page)
                    review_count = await _extract_review_count(prod_page)
                    brand = await _extract_brand(prod_page, raw_spec)
                    release_year = await _extract_release_year(prod_page, raw_spec)

                    await prod_page.close()

                    # ─ 필수 스펙 필터 ─
                    if primary_spec_filter and not _passes_primary_filter(raw_spec, primary_spec_filter):
                        print(f"[crawler] 필터 탈락 (필수스펙): {name}")
                        continue

                    # ─ 출시년도 필터 ─
                    if not _passes_year_filter(release_year, samsung_release_year, year_window):
                        print(f"[crawler] 필터 탈락 (출시년도 {release_year} vs {samsung_release_year}): {name}")
                        continue

                    raw_spec["__price__"] = str(price)
                    raw_spec["__review_count__"] = str(review_count)
                    raw_spec["__brand__"] = brand
                    if release_year:
                        raw_spec["__release_year__"] = str(release_year)

                    results.append({
                        "model_name": name,
                        "product_url": url,
                        "raw_spec": raw_spec,
                        "price": price,
                        "review_count": review_count,
                        "brand": brand,
                        "release_year": release_year,
                        "popularity_rank": rank,
                    })
                    crawled += 1
                    print(f"[crawler] 수집 완료 ({crawled}/{max_count}): {name}")

                    await asyncio.sleep(delay_between_sec + random.uniform(-1.0, 1.0))

                except Exception as e:
                    print(f"[crawler] 경쟁사 수집 오류 {name}: {e}")
                    try:
                        await prod_page.close()
                    except Exception:
                        pass
                    continue

            return results

        except Exception as e:
            print(f"[crawler] 경쟁사 탐색 오류: {e}")
            return []
        finally:
            await ctx.close()
            await browser.close()
