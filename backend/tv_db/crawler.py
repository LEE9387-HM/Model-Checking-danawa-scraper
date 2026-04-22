from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import Browser, BrowserContext, Page, TimeoutError, async_playwright

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tv_db.db_manager import TVDatabaseManager, TVProductRecord, utc_now_iso
else:
    from tv_db.db_manager import TVDatabaseManager, TVProductRecord, utc_now_iso

SELECTORS_PATH = Path(__file__).resolve().parent.parent / "selectors" / "danawa.json"
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "tv_products.db"
DEFAULT_REPORTS_DIR = Path(__file__).resolve().parent / "monthly_runs"
DEFAULT_PREFLIGHT_SAMPLE_PAGES = 5
DEFAULT_DETAIL_PAGES_PER_MINUTE = 3.0
DEFAULT_STARTUP_OVERHEAD_MINUTES = 1.0
DEFAULT_LIST_PAGE_OVERHEAD_MINUTES = 0.15
OPTIMISTIC_FACTOR = 0.88
PESSIMISTIC_FACTOR = 1.25
RUN_REPORT_GLOBS = ("monthly-run-*.json", "calibration-run-*.json")

BRAND_LABELS = ("제조회사", "제조사", "브랜드", "제조국")
SCREEN_SIZE_LABELS = ("화면 크기", "화면크기", "크기")
RESOLUTION_LABELS = ("해상도",)
PANEL_TYPE_LABELS = ("패널 종류", "디스플레이 종류", "디스플레이", "패널", "화면종류")
REFRESH_RATE_LABELS = ("주사율", "화면재생빈도")
OS_LABELS = ("운영체제", "OS", "스마트TV", "스마트 기능", "게임종류")
RELEASE_YEAR_LABELS = ("출시연도", "출시 년도", "출시월", "출시일", "등록년월", "년형")
NOISY_VALUE_MARKERS = (
    "최저가",
    "자세히보기",
    "판매점 :",
    "콘텐츠산업 진흥법",
    "콘텐츠 제작:",
    "콘텐츠 갱신일:",
)


@dataclass(slots=True)
class CrawlCandidate:
    model_name: str
    product_url: str
    list_rank: int
    source_page: int
    source_type: str


@dataclass(slots=True)
class CrawlResult:
    model_name: str
    product_url: str
    brand: str
    release_year: int | None
    price: int
    review_count: int
    raw_specs: dict[str, Any]
    other_specs: dict[str, Any]
    screen_size_inch: float | None
    resolution: str | None
    panel_type: str | None
    refresh_rate_hz: float | None
    operating_system: str | None
    list_rank: int
    source_page: int
    source_type: str


@dataclass(slots=True)
class CrawlFailure:
    model_name: str
    product_url: str
    error: str
    source_page: int
    source_type: str


@dataclass(slots=True)
class CrawlRun:
    results: list[CrawlResult]
    failures: list[CrawlFailure]
    candidates_seen: int
    pages_visited: int
    source_used: str
    progress_updates: list[dict[str, Any]]


@dataclass(slots=True)
class ThroughputEstimate:
    detail_pages_per_minute: float
    source: str
    note: str | None = None


@dataclass(slots=True)
class PreflightPageSample:
    page_number: int
    raw_count: int
    unique_count: int


@dataclass(slots=True)
class PreflightRun:
    category_url: str
    sampled_pages: int
    sampled_page_numbers: list[int]
    estimated_list_pages: int
    estimated_products: int
    avg_products_per_page: float
    min_products_per_page: int
    max_products_per_page: int
    duplicate_rate_estimate: float
    estimated_detail_fetches: int
    throughput_source: str
    observed_detail_pages_per_minute: float
    eta_optimistic_minutes: int
    eta_baseline_minutes: int
    eta_pessimistic_minutes: int
    estimated_finish_time_kst: str
    estimate_status: str
    notes: list[str]
    source_used: str


@dataclass(slots=True)
class CrawlProgressEstimate:
    processed_candidates: int
    estimated_total_candidates: int
    remaining_candidates: int
    observed_detail_pages_per_minute: float
    eta_optimistic_minutes: int
    eta_baseline_minutes: int
    eta_pessimistic_minutes: int
    estimated_finish_time_kst: str


def load_selector_config() -> dict[str, Any]:
    with open(SELECTORS_PATH, encoding="utf-8") as file:
        return json.load(file)


def build_category_page_url(page_number: int) -> str:
    del page_number
    return "https://prod.danawa.com/list/?cate=10248425"


def build_search_page_url(query_text: str, page_number: int) -> str:
    config = load_selector_config()
    parsed = urlparse(config["search_url"])
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[config["search_param"]] = query_text
    query["page"] = str(page_number)
    return urlunparse(parsed._replace(query=urlencode(query)))


def run_in_event_loop(coro: Any) -> Any:
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def normalize_limit(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value


def should_stop(count: int, limit: int | None) -> bool:
    return limit is not None and count >= limit


def clamp_ratio(value: float) -> float:
    return max(0.0, min(value, 0.95))


def compute_duplicate_rate(raw_count: int, unique_count: int) -> float:
    if raw_count <= 0:
        return 0.0
    duplicates = max(0, raw_count - unique_count)
    return clamp_ratio(duplicates / raw_count)


def estimate_total_products(estimated_list_pages: int, avg_products_per_page: float) -> int:
    if estimated_list_pages <= 0 or avg_products_per_page <= 0:
        return 0
    return max(1, round(estimated_list_pages * avg_products_per_page))


def estimate_detail_fetches(estimated_products: int, duplicate_rate_estimate: float) -> int:
    if estimated_products <= 0:
        return 0
    return max(1, round(estimated_products * (1 - clamp_ratio(duplicate_rate_estimate))))


def estimate_eta_minutes(
    estimated_detail_fetches_value: int,
    detail_pages_per_minute: float,
    estimated_list_pages: int,
    *,
    startup_overhead_minutes: float = DEFAULT_STARTUP_OVERHEAD_MINUTES,
    list_page_overhead_minutes: float = DEFAULT_LIST_PAGE_OVERHEAD_MINUTES,
) -> tuple[int, int, int]:
    safe_throughput = max(detail_pages_per_minute, 0.1)
    baseline = (
        startup_overhead_minutes
        + (estimated_list_pages * list_page_overhead_minutes)
        + (estimated_detail_fetches_value / safe_throughput)
    )
    optimistic = max(1, round(baseline * OPTIMISTIC_FACTOR))
    baseline_rounded = max(1, round(baseline))
    pessimistic = max(1, round(baseline * PESSIMISTIC_FACTOR))
    return optimistic, baseline_rounded, pessimistic


def format_duration_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(max(0, total_minutes), 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def estimate_finish_time_kst(
    baseline_minutes: int,
    *,
    now: datetime | None = None,
) -> str:
    dt = now or datetime.now().astimezone()
    return (dt + timedelta(minutes=baseline_minutes)).isoformat(timespec="minutes")


def compute_observed_throughput(
    processed_candidates: int,
    *,
    started_at: datetime,
    now: datetime | None = None,
) -> float:
    if processed_candidates <= 0:
        return 0.0
    current_time = now or datetime.now().astimezone()
    elapsed_minutes = max((current_time - started_at).total_seconds() / 60, 0.0)
    if elapsed_minutes <= 0:
        return 0.0
    return processed_candidates / elapsed_minutes


def build_progress_estimate(
    *,
    processed_candidates: int,
    estimated_total_candidates: int,
    started_at: datetime,
    now: datetime | None = None,
) -> CrawlProgressEstimate:
    observed_throughput = compute_observed_throughput(
        processed_candidates,
        started_at=started_at,
        now=now,
    )
    safe_total = max(estimated_total_candidates, processed_candidates)
    remaining_candidates = max(0, safe_total - processed_candidates)
    optimistic, baseline, pessimistic = estimate_eta_minutes(
        remaining_candidates,
        detail_pages_per_minute=max(observed_throughput, 0.1),
        estimated_list_pages=0,
        startup_overhead_minutes=0,
        list_page_overhead_minutes=0,
    )
    return CrawlProgressEstimate(
        processed_candidates=processed_candidates,
        estimated_total_candidates=safe_total,
        remaining_candidates=remaining_candidates,
        observed_detail_pages_per_minute=round(observed_throughput, 2),
        eta_optimistic_minutes=optimistic,
        eta_baseline_minutes=baseline,
        eta_pessimistic_minutes=pessimistic,
        estimated_finish_time_kst=estimate_finish_time_kst(baseline, now=now),
    )


def build_preflight_notes(
    *,
    estimate_status: str,
    throughput: ThroughputEstimate,
    duplicate_rate_estimate: float,
) -> list[str]:
    notes: list[str] = ["Estimate only."]
    if estimate_status != "exact":
        notes.append("Pagination estimate is partial and may increase during the live crawl.")
    if throughput.source == "default":
        notes.append("ETA uses fallback throughput assumptions because no recent completed run history was found.")
    if duplicate_rate_estimate > 0:
        notes.append("Estimated detail fetch count includes a duplicate discount based on sampled product URLs.")
    if throughput.note:
        notes.append(throughput.note)
    return notes


def default_throughput_estimate() -> ThroughputEstimate:
    return ThroughputEstimate(
        detail_pages_per_minute=DEFAULT_DETAIL_PAGES_PER_MINUTE,
        source="default",
        note=f"Fallback throughput set to {DEFAULT_DETAIL_PAGES_PER_MINUTE:.1f} detail pages per minute.",
    )


def iter_recent_run_reports(reports_dir: str | Path) -> list[Path]:
    reports_path = Path(reports_dir)
    if not reports_path.exists():
        return []
    paths: list[Path] = []
    for pattern in RUN_REPORT_GLOBS:
        paths.extend(reports_path.glob(pattern))
    return sorted(set(paths), key=lambda path: path.stat().st_mtime, reverse=True)


def load_recent_throughput(reports_dir: str | Path) -> ThroughputEstimate:
    report_paths = iter_recent_run_reports(reports_dir)
    if not report_paths:
        return default_throughput_estimate()

    for report_path in report_paths:
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("status") != "completed":
            continue

        started_at = payload.get("started_at")
        ended_at = payload.get("ended_at")
        saved_count = int(payload.get("saved_count") or 0)
        if not started_at or not ended_at or saved_count <= 0:
            continue
        try:
            started_dt = datetime.fromisoformat(started_at)
            ended_dt = datetime.fromisoformat(ended_at)
        except ValueError:
            continue
        elapsed_minutes = max((ended_dt - started_dt).total_seconds() / 60, 0.0)
        if elapsed_minutes <= 0:
            continue
        throughput = saved_count / elapsed_minutes
        if throughput <= 0:
            continue
        report_type = payload.get("report_type") or "monthly"
        return ThroughputEstimate(
            detail_pages_per_minute=throughput,
            source="calibration_runs" if report_type == "calibration" else "monthly_runs",
            note=f"Based on {report_path.name}.",
        )

    return default_throughput_estimate()


def random_delay(config: dict[str, Any], extra_min_ms: int = 0, extra_max_ms: int = 0) -> float:
    anti_bot = config["anti_bot"]
    minimum = anti_bot["min_delay_ms"] + extra_min_ms
    maximum = anti_bot["max_delay_ms"] + extra_max_ms
    return random.randint(minimum, maximum) / 1000


async def create_context(browser: Browser, config: dict[str, Any]) -> BrowserContext:
    user_agent = random.choice(config["anti_bot"]["user_agents"])
    context = await browser.new_context(
        user_agent=user_agent,
        viewport={"width": 1440, "height": 900},
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"},
    )
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return context


async def query_first(page_or_element: Any, selectors: list[str]):
    for selector in selectors:
        try:
            element = await page_or_element.query_selector(selector)
        except Exception:
            element = None
        if element is not None:
            return element
    return None


async def query_all(page_or_element: Any, selectors: list[str]) -> list[Any]:
    for selector in selectors:
        try:
            elements = await page_or_element.query_selector_all(selector)
        except Exception:
            elements = []
        if elements:
            return elements
    return []


def parse_number(text: str) -> float | None:
    if not text:
        return None
    matched = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    return float(matched.group()) if matched else None


def normalize_product_url(url: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    kept: dict[str, str] = {}
    for key in ("pcode", "cate"):
        value = query.get(key, "").strip()
        if value:
            kept[key] = value
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(kept), ""))


def clean_spec_value(value: str) -> str | None:
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        return None
    if any(marker in normalized for marker in NOISY_VALUE_MARKERS):
        return None
    if len(normalized) > 180:
        return None
    return normalized


def clean_raw_specs(raw_specs: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in raw_specs.items():
        clean_value = clean_spec_value(value)
        if clean_value is None:
            continue
        cleaned[key] = clean_value
    return cleaned


def extract_first_value(raw_specs: dict[str, str], labels: tuple[str, ...]) -> str:
    for label in labels:
        value = raw_specs.get(label, "").strip()
        if value:
            return value
    return ""


def normalize_resolution(raw_value: str) -> str | None:
    if not raw_value:
        return None
    if "8K" in raw_value:
        return "8K"
    if "4K" in raw_value or "UHD" in raw_value:
        return "4K UHD"
    if "QHD" in raw_value:
        return "QHD"
    if "FHD" in raw_value or "1080" in raw_value:
        return "FHD"
    if "HD" in raw_value:
        return "HD"
    return raw_value.strip()


def normalize_panel_type(raw_value: str) -> str | None:
    if not raw_value:
        return None
    return raw_value.split("/")[0].strip() or None


def parse_release_year(raw_specs: dict[str, str]) -> int | None:
    for label in RELEASE_YEAR_LABELS:
        matched = re.search(r"(20\d{2})", raw_specs.get(label, ""))
        if matched:
            return int(matched.group(1))
    return None


def split_other_specs(raw_specs: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    screen_size = parse_number(extract_first_value(raw_specs, SCREEN_SIZE_LABELS))
    refresh_rate = parse_number(extract_first_value(raw_specs, REFRESH_RATE_LABELS))
    normalized = {
        "manufacturer": extract_first_value(raw_specs, BRAND_LABELS),
        "brand": extract_first_value(raw_specs, BRAND_LABELS),
        "release_year": parse_release_year(raw_specs),
        "screen_size_inch": screen_size,
        "resolution": normalize_resolution(extract_first_value(raw_specs, RESOLUTION_LABELS)),
        "panel_type": normalize_panel_type(extract_first_value(raw_specs, PANEL_TYPE_LABELS)),
        "refresh_rate_hz": refresh_rate,
        "operating_system": extract_first_value(raw_specs, OS_LABELS) or None,
    }
    handled_labels = {
        *BRAND_LABELS,
        *SCREEN_SIZE_LABELS,
        *RESOLUTION_LABELS,
        *PANEL_TYPE_LABELS,
        *REFRESH_RATE_LABELS,
        *OS_LABELS,
        *RELEASE_YEAR_LABELS,
    }
    other_specs = {key: value for key, value in raw_specs.items() if key not in handled_labels}
    return normalized, other_specs


def extract_model_name(raw_name: str) -> str:
    collapsed = " ".join(raw_name.split())
    return collapsed[:255]


async def parse_spec_table(page: Page, selectors: dict[str, Any]) -> dict[str, str]:
    raw_specs: dict[str, str] = {}
    rows = await query_all(page, selectors["spec_row"])
    for row in rows:
        label_element = await query_first(row, selectors["spec_label"])
        value_element = await query_first(row, selectors["spec_value"])
        if label_element is None or value_element is None:
            continue
        label = (await label_element.inner_text()).strip()
        value = (await value_element.inner_text()).strip()
        if label and value:
            raw_specs[label] = value

    if raw_specs:
        return clean_raw_specs(raw_specs)

    labels = await query_all(page, selectors["spec_label"])
    values = await query_all(page, selectors["spec_value"])
    for label_element, value_element in zip(labels, values):
        label = (await label_element.inner_text()).strip()
        value = (await value_element.inner_text()).strip()
        if label and value:
            raw_specs[label] = value
    return clean_raw_specs(raw_specs)


async def extract_price(page: Page, selectors: list[str]) -> int:
    element = await query_first(page, selectors)
    if element is None:
        return 0
    numbers = re.sub(r"[^\d]", "", await element.inner_text())
    return int(numbers) if numbers else 0


async def extract_review_count(page: Page, selectors: list[str]) -> int:
    element = await query_first(page, selectors)
    if element is None:
        return 0
    numbers = re.sub(r"[^\d]", "", await element.inner_text())
    return int(numbers) if numbers else 0


async def collect_candidates_from_source(
    page: Page,
    selectors: dict[str, Any],
    *,
    limit: int | None,
    max_pages: int | None,
    max_empty_pages: int,
    build_url: Callable[[int], str],
    source_type: str,
) -> tuple[list[CrawlCandidate], int]:
    candidates: list[CrawlCandidate] = []
    seen_urls: set[str] = set()
    pages_visited = 0
    empty_pages = 0
    page_number = 1

    while True:
        if max_pages is not None and page_number > max_pages:
            break

        pages_visited += 1
        await page.goto(build_url(page_number), wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(random_delay(load_selector_config()))

        items = await query_all(page, selectors["product_list_item"])
        new_count = 0
        for item in items:
            link = await query_first(item, selectors["product_list_name"])
            if link is None:
                continue

            href = await link.get_attribute("href") or ""
            if not href:
                continue
            if href.startswith("/"):
                href = f"https://prod.danawa.com{href}"
            if href in seen_urls:
                continue

            name = extract_model_name((await link.inner_text()).strip())
            candidates.append(
                CrawlCandidate(
                    model_name=name,
                    product_url=href,
                    list_rank=len(candidates) + 1,
                    source_page=page_number,
                    source_type=source_type,
                )
            )
            seen_urls.add(href)
            new_count += 1

            if should_stop(len(candidates), limit):
                return candidates, pages_visited

        if new_count == 0:
            empty_pages += 1
        else:
            empty_pages = 0

        if empty_pages >= max_empty_pages:
            break

        page_number += 1

    return candidates, pages_visited


async def go_to_next_category_page(page: Page, next_page_number: int) -> bool:
    next_locator = page.locator("a.num").filter(has_text=str(next_page_number)).first
    if await next_locator.count() > 0:
        await next_locator.click(timeout=10000)
    else:
        next_button = page.locator("a.edge_nav.nav_next").first
        if await next_button.count() == 0:
            return False
        await next_button.click(timeout=10000)

    await page.wait_for_function(
        "(expected) => { const el = document.querySelector('a.num.now_on'); return el && el.textContent.trim() === String(expected); }",
        arg=next_page_number,
        timeout=20000,
    )
    await page.wait_for_timeout(1500)
    return True


async def extract_visible_page_numbers(page: Page) -> list[int]:
    page_numbers: list[int] = []
    anchors = await page.query_selector_all("a.num")
    for anchor in anchors:
        try:
            text = (await anchor.inner_text()).strip()
        except Exception:
            continue
        if text.isdigit():
            page_numbers.append(int(text))
    current_anchor = page.locator("a.num.now_on").first
    if await current_anchor.count() > 0:
        text = (await current_anchor.inner_text()).strip()
        if text.isdigit():
            page_numbers.append(int(text))
    return sorted(set(page_numbers))


async def has_next_category_page(page: Page) -> bool:
    next_button = page.locator("a.edge_nav.nav_next").first
    return await next_button.count() > 0


async def sample_category_pages_for_preflight(
    page: Page,
    selectors: dict[str, Any],
    *,
    sample_pages: int,
    max_pages: int | None,
) -> tuple[list[PreflightPageSample], int, str]:
    page_limit = max_pages if max_pages is None else max(1, max_pages)
    samples: list[PreflightPageSample] = []
    seen_urls: set[str] = set()
    estimate_status = "exact"
    current_page_number = 1
    estimated_list_pages = 1

    await page.goto(build_category_page_url(1), wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(random_delay(load_selector_config()))

    while True:
        if page_limit is not None and current_page_number > page_limit:
            break

        items = await query_all(page, selectors["product_list_item"])
        raw_count = 0
        unique_count = 0
        for item in items:
            link = await query_first(item, selectors["product_list_name"])
            if link is None:
                continue
            href = await link.get_attribute("href") or ""
            if not href:
                continue
            raw_count += 1
            if href.startswith("/"):
                href = f"https://prod.danawa.com{href}"
            if href in seen_urls:
                continue
            seen_urls.add(href)
            unique_count += 1

        if raw_count == 0 and current_page_number == 1:
            return [], 0, "degraded"

        samples.append(
            PreflightPageSample(
                page_number=current_page_number,
                raw_count=raw_count,
                unique_count=unique_count,
            )
        )

        visible_page_numbers = await extract_visible_page_numbers(page)
        max_visible_page = max(visible_page_numbers) if visible_page_numbers else current_page_number
        next_exists = await has_next_category_page(page)
        estimated_list_pages = max(estimated_list_pages, max_visible_page)

        if len(samples) >= sample_pages:
            if next_exists and (page_limit is None or current_page_number < page_limit):
                estimate_status = "partial"
                estimated_list_pages = max(estimated_list_pages, current_page_number + 1)
            break

        if not next_exists:
            estimated_list_pages = max(estimated_list_pages, current_page_number)
            estimate_status = "exact"
            break

        next_page_number = current_page_number + 1
        moved = await go_to_next_category_page(page, next_page_number)
        if not moved:
            estimated_list_pages = max(estimated_list_pages, current_page_number)
            estimate_status = "exact"
            break
        current_page_number = next_page_number

    if page_limit is not None:
        estimated_list_pages = min(estimated_list_pages, page_limit)

    return samples, estimated_list_pages, estimate_status


async def collect_candidates_from_category(
    page: Page,
    selectors: dict[str, Any],
    *,
    limit: int | None,
    max_pages: int | None,
    max_empty_pages: int,
) -> tuple[list[CrawlCandidate], int]:
    candidates: list[CrawlCandidate] = []
    seen_urls: set[str] = set()
    pages_visited = 0
    empty_pages = 0
    current_page_number = 1

    await page.goto(build_category_page_url(1), wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(random_delay(load_selector_config()))

    while True:
        if max_pages is not None and current_page_number > max_pages:
            break

        pages_visited += 1
        items = await query_all(page, selectors["product_list_item"])
        new_count = 0
        for item in items:
            link = await query_first(item, selectors["product_list_name"])
            if link is None:
                continue

            href = await link.get_attribute("href") or ""
            if not href:
                continue
            if href.startswith("/"):
                href = f"https://prod.danawa.com{href}"
            if href in seen_urls:
                continue

            name = extract_model_name((await link.inner_text()).strip())
            candidates.append(
                CrawlCandidate(
                    model_name=name,
                    product_url=href,
                    list_rank=len(candidates) + 1,
                    source_page=current_page_number,
                    source_type="category",
                )
            )
            seen_urls.add(href)
            new_count += 1

            if should_stop(len(candidates), limit):
                return candidates, pages_visited

        if new_count == 0:
            empty_pages += 1
        else:
            empty_pages = 0

        if empty_pages >= max_empty_pages:
            break

        next_page_number = current_page_number + 1
        moved = await go_to_next_category_page(page, next_page_number)
        if not moved:
            break
        current_page_number = next_page_number

    return candidates, pages_visited


async def collect_candidates(
    page: Page,
    selectors: dict[str, Any],
    *,
    max_items: int,
    max_pages: int,
    search_query: str,
    max_empty_pages: int,
) -> tuple[list[CrawlCandidate], int, str]:
    limit = normalize_limit(max_items)
    page_limit = normalize_limit(max_pages)
    category_candidates, category_pages = await collect_candidates_from_category(
        page,
        selectors,
        limit=limit,
        max_pages=page_limit,
        max_empty_pages=max_empty_pages,
    )
    if category_candidates:
        return category_candidates, category_pages, "category"

    search_candidates, search_pages = await collect_candidates_from_source(
        page,
        selectors,
        limit=limit,
        max_pages=page_limit,
        max_empty_pages=max_empty_pages,
        build_url=lambda page_number: build_search_page_url(search_query, page_number),
        source_type="search",
    )
    if search_candidates:
        return search_candidates, search_pages, "search"

    return [], 0, "none"


def summarize_preflight_samples(
    samples: list[PreflightPageSample],
    *,
    estimated_list_pages: int,
    estimate_status: str,
    throughput: ThroughputEstimate,
) -> PreflightRun:
    raw_counts = [sample.raw_count for sample in samples]
    unique_counts = [sample.unique_count for sample in samples]
    sampled_pages = len(samples)
    total_raw = sum(raw_counts)
    total_unique = sum(unique_counts)
    avg_products_per_page = (total_raw / sampled_pages) if sampled_pages else 0.0
    duplicate_rate_estimate = compute_duplicate_rate(total_raw, total_unique)
    estimated_products = estimate_total_products(estimated_list_pages, avg_products_per_page)
    estimated_detail_fetches_value = estimate_detail_fetches(estimated_products, duplicate_rate_estimate)
    eta_optimistic_minutes, eta_baseline_minutes, eta_pessimistic_minutes = estimate_eta_minutes(
        estimated_detail_fetches_value,
        throughput.detail_pages_per_minute,
        estimated_list_pages,
    )
    return PreflightRun(
        category_url=build_category_page_url(1),
        sampled_pages=sampled_pages,
        sampled_page_numbers=[sample.page_number for sample in samples],
        estimated_list_pages=estimated_list_pages,
        estimated_products=estimated_products,
        avg_products_per_page=round(avg_products_per_page, 2),
        min_products_per_page=min(raw_counts) if raw_counts else 0,
        max_products_per_page=max(raw_counts) if raw_counts else 0,
        duplicate_rate_estimate=round(duplicate_rate_estimate, 4),
        estimated_detail_fetches=estimated_detail_fetches_value,
        throughput_source=throughput.source,
        observed_detail_pages_per_minute=round(throughput.detail_pages_per_minute, 2),
        eta_optimistic_minutes=eta_optimistic_minutes,
        eta_baseline_minutes=eta_baseline_minutes,
        eta_pessimistic_minutes=eta_pessimistic_minutes,
        estimated_finish_time_kst=estimate_finish_time_kst(eta_baseline_minutes),
        estimate_status=estimate_status,
        notes=build_preflight_notes(
            estimate_status=estimate_status,
            throughput=throughput,
            duplicate_rate_estimate=duplicate_rate_estimate,
        ),
        source_used="category",
    )


async def run_preflight_estimate(
    *,
    max_pages: int,
    reports_dir: str | Path,
    sample_pages: int,
) -> PreflightRun:
    config = load_selector_config()
    selectors = config["selectors"]
    page_limit = normalize_limit(max_pages)
    throughput = load_recent_throughput(reports_dir)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await create_context(browser, config)
        page = await context.new_page()
        try:
            samples, estimated_list_pages, estimate_status = await sample_category_pages_for_preflight(
                page,
                selectors,
                sample_pages=max(1, sample_pages),
                max_pages=page_limit,
            )
            if not samples:
                fallback_estimate = summarize_preflight_samples(
                    [],
                    estimated_list_pages=0,
                    estimate_status="degraded",
                    throughput=throughput,
                )
                return PreflightRun(
                    **{
                        **asdict(fallback_estimate),
                        "source_used": "none",
                        "notes": [
                            "Estimate only.",
                            "Category sampling returned no candidates.",
                            *fallback_estimate.notes[1:],
                        ],
                    }
                )
            return summarize_preflight_samples(
                samples,
                estimated_list_pages=estimated_list_pages,
                estimate_status=estimate_status,
                throughput=throughput,
            )
        finally:
            await page.close()
            await context.close()
            await browser.close()


def should_keep_result(result: CrawlResult, *, brand_keywords: list[str], release_year: int | None) -> bool:
    if brand_keywords:
        haystack = f"{result.brand} {result.model_name}".lower()
        if not any(keyword.lower() in haystack for keyword in brand_keywords):
            return False
    if release_year is not None and result.release_year != release_year:
        return False
    return True


async def scrape_product_detail_once(
    context: BrowserContext,
    selectors: dict[str, Any],
    candidate: CrawlCandidate,
    *,
    detail_timeout_ms: int,
) -> CrawlResult:
    page = await context.new_page()
    try:
        await page.goto(candidate.product_url, wait_until="domcontentloaded", timeout=detail_timeout_ms)
        await asyncio.sleep(random_delay(load_selector_config(), extra_min_ms=500, extra_max_ms=1500))

        raw_specs = await parse_spec_table(page, selectors)
        normalized, other_specs = split_other_specs(raw_specs)
        price = await extract_price(page, selectors["price"])
        review_count = await extract_review_count(page, selectors["review_count"])
        brand = normalized["brand"] or ""

        return CrawlResult(
            model_name=candidate.model_name,
            product_url=normalize_product_url(page.url),
            brand=brand,
            release_year=normalized["release_year"],
            price=max(0, price),
            review_count=max(0, review_count),
            raw_specs=raw_specs,
            other_specs=other_specs,
            screen_size_inch=normalized["screen_size_inch"],
            resolution=normalized["resolution"],
            panel_type=normalized["panel_type"],
            refresh_rate_hz=normalized["refresh_rate_hz"],
            operating_system=normalized["operating_system"],
            list_rank=candidate.list_rank,
            source_page=candidate.source_page,
            source_type=candidate.source_type,
        )
    finally:
        await page.close()


async def scrape_product_detail(
    context: BrowserContext,
    selectors: dict[str, Any],
    candidate: CrawlCandidate,
    *,
    detail_timeout_ms: int,
    detail_retries: int,
) -> tuple[CrawlResult | None, CrawlFailure | None]:
    last_error = "unknown error"
    for attempt in range(detail_retries + 1):
        try:
            result = await scrape_product_detail_once(
                context,
                selectors,
                candidate,
                detail_timeout_ms=detail_timeout_ms,
            )
            return result, None
        except TimeoutError as error:
            last_error = f"timeout: {error}"
        except Exception as error:
            last_error = str(error)

        if attempt < detail_retries:
            await asyncio.sleep(1.5 + attempt)

    return None, CrawlFailure(
        model_name=candidate.model_name,
        product_url=candidate.product_url,
        error=last_error,
        source_page=candidate.source_page,
        source_type=candidate.source_type,
    )


async def crawl_tv_database(
    *,
    db_path: str | Path,
    max_items: int,
    max_pages: int,
    brand_keywords: list[str],
    release_year: int | None,
    search_query: str,
    detail_retries: int = 2,
    detail_timeout_ms: int = 45000,
    max_empty_pages: int = 1,
    progress_every: int = 0,
    progress_enabled: bool = False,
) -> CrawlRun:
    config = load_selector_config()
    selectors = config["selectors"]
    database = TVDatabaseManager(db_path)
    database.initialize()
    crawled_at = utc_now_iso()
    crawl_started_at = datetime.now().astimezone()

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await create_context(browser, config)
            list_page = await context.new_page()

            try:
                candidates, pages_visited, source_used = await collect_candidates(
                    list_page,
                    selectors,
                    max_items=max_items,
                    max_pages=max_pages,
                    search_query=search_query,
                    max_empty_pages=max_empty_pages,
                )
            finally:
                await list_page.close()

            results: list[CrawlResult] = []
            failures: list[CrawlFailure] = []
            limit = normalize_limit(max_items)
            progress_updates: list[dict[str, Any]] = []
            estimated_total_candidates = len(candidates)

            for candidate in candidates:
                detail, failure = await scrape_product_detail(
                    context,
                    selectors,
                    candidate,
                    detail_timeout_ms=detail_timeout_ms,
                    detail_retries=max(0, detail_retries),
                )
                if failure is not None:
                    print(f"[tv_db] failed to scrape {candidate.product_url}: {failure.error}")
                    failures.append(failure)
                    continue
                if detail is None:
                    continue
                if not should_keep_result(detail, brand_keywords=brand_keywords, release_year=release_year):
                    continue

                record = TVProductRecord(
                    model_name=detail.model_name,
                    product_url=detail.product_url,
                    manufacturer=detail.brand,
                    brand=detail.brand,
                    release_year=detail.release_year,
                    screen_size_inch=detail.screen_size_inch,
                    resolution=detail.resolution,
                    panel_type=detail.panel_type,
                    refresh_rate_hz=detail.refresh_rate_hz,
                    operating_system=detail.operating_system,
                    current_price=detail.price,
                    review_count=detail.review_count,
                    other_specs=detail.other_specs,
                    raw_specs=detail.raw_specs,
                )
                database.upsert_product(record, crawled_at=crawled_at)
                results.append(detail)

                if progress_enabled and progress_every > 0 and len(results) % progress_every == 0:
                    progress = build_progress_estimate(
                        processed_candidates=len(results),
                        estimated_total_candidates=estimated_total_candidates,
                        started_at=crawl_started_at,
                    )
                    payload = {
                        "processed_candidates": progress.processed_candidates,
                        "estimated_total_candidates": progress.estimated_total_candidates,
                        "remaining_candidates": progress.remaining_candidates,
                        "observed_detail_pages_per_minute": progress.observed_detail_pages_per_minute,
                        "eta_minutes": {
                            "optimistic": progress.eta_optimistic_minutes,
                            "baseline": progress.eta_baseline_minutes,
                            "pessimistic": progress.eta_pessimistic_minutes,
                        },
                        "eta_human": {
                            "optimistic": format_duration_minutes(progress.eta_optimistic_minutes),
                            "baseline": format_duration_minutes(progress.eta_baseline_minutes),
                            "pessimistic": format_duration_minutes(progress.eta_pessimistic_minutes),
                        },
                        "estimated_finish_time_kst": progress.estimated_finish_time_kst,
                    }
                    progress_updates.append(payload)
                    print(f"[tv_db][progress] {json.dumps(payload, ensure_ascii=False)}")

                if should_stop(len(results), limit):
                    break

            await context.close()
            await browser.close()
            return CrawlRun(
                results=results,
                failures=failures,
                candidates_seen=len(candidates),
                pages_visited=pages_visited,
                source_used=source_used,
                progress_updates=progress_updates,
            )
    finally:
        database.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Danawa TV SQLite crawler")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--preflight", action="store_true", help="estimate crawl scope without writing to the database")
    parser.add_argument("--preflight-sample-pages", type=int, default=DEFAULT_PREFLIGHT_SAMPLE_PAGES)
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR))
    parser.add_argument("--output-json", default=None, help="optional path for a preflight JSON report")
    parser.add_argument("--max-items", type=int, default=0, help="0 means no item cap")
    parser.add_argument("--max-pages", type=int, default=0, help="0 means keep paging until empty pages")
    parser.add_argument("--brand", action="append", dest="brands", default=[])
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--query", default="TV")
    parser.add_argument("--detail-retries", type=int, default=2)
    parser.add_argument("--detail-timeout-ms", type=int, default=45000)
    parser.add_argument("--max-empty-pages", type=int, default=1)
    parser.add_argument("--progress-every", type=int, default=0, help="emit in-run ETA progress every N saved products")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.preflight:
        preflight = run_in_event_loop(
            run_preflight_estimate(
                max_pages=args.max_pages,
                reports_dir=args.reports_dir,
                sample_pages=args.preflight_sample_pages,
            )
        )
        summary = {
            "mode": "preflight",
            "category_url": preflight.category_url,
            "sampled_pages": preflight.sampled_pages,
            "sampled_page_numbers": preflight.sampled_page_numbers,
            "estimated_list_pages": preflight.estimated_list_pages,
            "estimated_products": preflight.estimated_products,
            "avg_products_per_page": preflight.avg_products_per_page,
            "min_products_per_page": preflight.min_products_per_page,
            "max_products_per_page": preflight.max_products_per_page,
            "duplicate_rate_estimate": preflight.duplicate_rate_estimate,
            "estimated_detail_fetches": preflight.estimated_detail_fetches,
            "throughput_source": preflight.throughput_source,
            "observed_detail_pages_per_minute": preflight.observed_detail_pages_per_minute,
            "eta_minutes": {
                "optimistic": preflight.eta_optimistic_minutes,
                "baseline": preflight.eta_baseline_minutes,
                "pessimistic": preflight.eta_pessimistic_minutes,
            },
            "eta_human": {
                "optimistic": format_duration_minutes(preflight.eta_optimistic_minutes),
                "baseline": format_duration_minutes(preflight.eta_baseline_minutes),
                "pessimistic": format_duration_minutes(preflight.eta_pessimistic_minutes),
            },
            "estimated_finish_time_kst": preflight.estimated_finish_time_kst,
            "estimate_status": preflight.estimate_status,
            "source_used": preflight.source_used,
            "notes": preflight.notes,
        }
        rendered = json.dumps(summary, ensure_ascii=False, indent=2)
        if args.output_json:
            output_path = Path(args.output_json)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
        print(rendered)
        return 0

    run = run_in_event_loop(
        crawl_tv_database(
            db_path=args.db_path,
            max_items=args.max_items,
            max_pages=args.max_pages,
            brand_keywords=args.brands,
            release_year=args.year,
            search_query=args.query,
            detail_retries=args.detail_retries,
            detail_timeout_ms=args.detail_timeout_ms,
            max_empty_pages=max(1, args.max_empty_pages),
            progress_every=max(0, args.progress_every),
            progress_enabled=args.progress_every > 0,
        )
    )
    summary = {
        "db_path": str(Path(args.db_path).resolve()),
        "saved_count": len(run.results),
        "failed_count": len(run.failures),
        "candidate_count": run.candidates_seen,
        "pages_visited": run.pages_visited,
        "source_used": run.source_used,
        "progress_updates": run.progress_updates[-5:],
        "items": [asdict(result) for result in run.results[:5]],
        "failures": [asdict(failure) for failure in run.failures[:5]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
