"""
Cloudflare Python Worker for TV DB model listing and matching.
"""
from __future__ import annotations

import json
import math
from js import Headers, Request, Response, URL, caches


DEPRECIATION_RATE = 0.85
MAX_YEAR_DELTA = 2
DEFAULT_SIZE_TOLERANCE = 3.0

TV_GRADING_WEIGHTS = {
    "refresh_rate": 0.20,
    "hdr": 0.20,
    "smart_features": 0.15,
    "speaker_output": 0.15,
    "dolby_atmos": 0.10,
    "energy_rating": 0.10,
    "design_thinness": 0.10,
}

SAMSUNG_WHERE = (
    "(manufacturer IN ('삼성전자', 'Samsung', 'SAMSUNG') "
    "OR brand LIKE '%삼성%' OR brand LIKE '%Samsung%')"
)
NON_SAMSUNG_WHERE = (
    "manufacturer NOT IN ('삼성전자', 'Samsung', 'SAMSUNG') "
    "AND brand NOT LIKE '%삼성%' AND brand NOT LIKE '%Samsung%'"
)


def _make_headers(extra: dict[str, str] | None = None) -> Headers:
    h = Headers.new()
    h.set("Access-Control-Allow-Origin", "*")
    h.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    h.set("Access-Control-Allow-Headers", "Content-Type")
    if extra:
        for k, v in extra.items():
            h.set(k, v)
    return h


def json_response(data: dict, status: int = 200) -> Response:
    return Response.new(
        json.dumps(data, ensure_ascii=False),
        status=status,
        headers=_make_headers({"Content-Type": "application/json"}),
    )


def empty_response(status: int = 204) -> Response:
    return Response.new("", status=status, headers=_make_headers())


def safe_json_loads(raw_value) -> dict:
    if not raw_value:
        return {}
    try:
        value = json.loads(raw_value)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def to_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def to_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def cosine_sim(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_mag = math.sqrt(sum(value * value for value in left))
    right_mag = math.sqrt(sum(value * value for value in right))
    return dot / (left_mag * right_mag) if left_mag and right_mag else 0.0


def year_proximity_weight(samsung_year: int, competitor_year: int) -> float:
    delta = abs(competitor_year - samsung_year)
    return {0: 1.00, 1: 0.70, 2: 0.40}.get(delta, 0.00)


def depreciation_adjusted_price(competitor_price: int, samsung_year: int, competitor_year: int) -> float:
    year_delta = competitor_year - samsung_year
    if year_delta == 0:
        return float(competitor_price)
    factor = DEPRECIATION_RATE ** abs(year_delta)
    return competitor_price / factor if year_delta < 0 else competitor_price * factor


def aggregate_verdict(weighted_cpi: float) -> str:
    if weighted_cpi > 115:
        return "OVERPRICED"
    if weighted_cpi > 105:
        return "SLIGHT_HIGH"
    if weighted_cpi > 95:
        return "FAIR"
    if weighted_cpi > 85:
        return "GOOD_VALUE"
    return "COMPETITIVE"


def get_verdict(adjusted_cpi: float, score_diff: float) -> dict:
    if adjusted_cpi > 115:
        verdict = "OVERPRICED"
    elif adjusted_cpi > 105:
        verdict = "SLIGHT_HIGH"
    elif adjusted_cpi > 95:
        verdict = "FAIR"
    elif adjusted_cpi > 85:
        verdict = "GOOD_VALUE"
    else:
        verdict = "COMPETITIVE"
    return {"verdict": verdict, "reason": f"CPI {adjusted_cpi}, score_diff {score_diff}"}


def row_to_breakdown_vec(row: dict) -> list[float]:
    breakdown = safe_json_loads(row.get("score_breakdown"))
    vector = []
    for key, weight in TV_GRADING_WEIGHTS.items():
        vector.append(to_float(breakdown.get(key), 0.0) * weight)
    return vector


def extract_specs(row: dict) -> dict:
    other = safe_json_loads(row.get("other_specs"))
    return {
        "screen_size_inch": row.get("screen_size_inch"),
        "panel_type": row.get("panel_type"),
        "resolution": row.get("resolution"),
        "refresh_rate_hz": row.get("refresh_rate_hz"),
        "hdr": other.get("hdr") or other.get("HDR"),
    }


async def query_all(statement):
    result = await statement.all()
    return result.results.to_py()


async def query_first(statement):
    result = await statement.first()
    return result.to_py() if result else None


def request_model_name(method: str, request: Request, url: URL, body: dict | None) -> str:
    if method == "GET":
        return (url.searchParams.get("model_name") or "").strip()
    if body is None:
        return ""
    return str(body.get("model_name") or "").strip()


async def handle_ping(env) -> Response:
    return json_response({"status": "ok", "mode": "cloudflare-worker"})


async def handle_tv_models(request: Request, env) -> Response:
    parsed = URL.new(request.url)
    params = parsed.searchParams

    size_value = params.get("size")
    resolution = params.get("resolution")
    year_value = params.get("year")

    size = to_float(size_value, default=None) if size_value else None
    year = to_int(year_value, default=None) if year_value else None

    sizes = [
        row["screen_size_inch"]
        for row in await query_all(
            env.DB.prepare(
                f"SELECT DISTINCT screen_size_inch FROM tv_products "
                f"WHERE {SAMSUNG_WHERE} AND screen_size_inch IS NOT NULL ORDER BY screen_size_inch"
            )
        )
    ]
    resolutions = [
        row["resolution"]
        for row in await query_all(
            env.DB.prepare(
                f"SELECT DISTINCT resolution FROM tv_products "
                f"WHERE {SAMSUNG_WHERE} AND resolution IS NOT NULL ORDER BY resolution"
            )
        )
    ]
    years = [
        row["release_year"]
        for row in await query_all(
            env.DB.prepare(
                f"SELECT DISTINCT release_year FROM tv_products "
                f"WHERE {SAMSUNG_WHERE} AND release_year IS NOT NULL ORDER BY release_year DESC"
            )
        )
    ]

    conditions = [SAMSUNG_WHERE]
    bind_params = []
    if size is not None:
        conditions.append("ABS(screen_size_inch - ?) <= 0.1")
        bind_params.append(size)
    if resolution:
        conditions.append("resolution = ?")
        bind_params.append(resolution)
    if year is not None:
        conditions.append("release_year = ?")
        bind_params.append(year)

    where_clause = " AND ".join(conditions)
    model_statement = env.DB.prepare(
        f"SELECT model_name, screen_size_inch, resolution, release_year, current_price "
        f"FROM tv_products WHERE {where_clause} "
        f"ORDER BY release_year DESC, model_name"
    )
    if bind_params:
        model_statement = model_statement.bind(*bind_params)

    model_rows = await query_all(model_statement)
    models = [
        {
            "model_name": row["model_name"],
            "size": row["screen_size_inch"],
            "resolution": row["resolution"],
            "year": row["release_year"],
            "price": row["current_price"],
        }
        for row in model_rows
    ]

    return json_response(
        {
            "filters": {"sizes": sizes, "resolutions": resolutions, "years": years},
            "models": models,
            "total": len(models),
        }
    )


async def handle_tv_match(request: Request, env) -> Response:
    parsed = URL.new(request.url)
    method = request.method.upper()
    body = None
    if method == "POST":
        try:
            raw_body = await request.json()
            body = raw_body.to_py() if hasattr(raw_body, "to_py") else dict(raw_body)
        except Exception:
            return json_response({"detail": "Invalid JSON body"}, status=400)

    model_name = request_model_name(method, request, parsed, body)
    if not model_name:
        return json_response({"detail": "model_name is required"}, status=400)

    samsung = await query_first(
        env.DB.prepare(
            f"SELECT * FROM tv_products WHERE model_name LIKE ? AND {SAMSUNG_WHERE} "
            f"ORDER BY current_price DESC, review_count DESC, id ASC LIMIT 1"
        ).bind(f"%{model_name}%")
    )
    if not samsung:
        return json_response({"detail": f"DB에 모델 없음: {model_name}"}, status=404)

    target_size = samsung.get("screen_size_inch")
    target_resolution = samsung.get("resolution")
    target_year = samsung.get("release_year")
    target_panel = str(samsung.get("panel_type") or "").strip().lower()
    if target_size is None or not target_resolution or target_year is None:
        return json_response({"detail": "Samsung 모델 스펙 정보 불완전"}, status=422)

    query = (
        "SELECT * FROM tv_products WHERE current_price > 0 "
        "AND ABS(screen_size_inch - ?) <= ? "
        "AND resolution = ? "
        "AND ABS(release_year - ?) <= ? "
    )
    bind_params = [
        target_size,
        DEFAULT_SIZE_TOLERANCE,
        target_resolution,
        target_year,
        MAX_YEAR_DELTA,
    ]
    if target_panel:
        query += "AND (LOWER(TRIM(panel_type)) = ? OR panel_type IS NULL OR panel_type = '') "
        bind_params.append(target_panel)
    query += (
        f"AND {NON_SAMSUNG_WHERE} "
        "ORDER BY ABS(screen_size_inch - ?) ASC, ABS(release_year - ?) ASC, current_price DESC"
    )
    bind_params.extend([target_size, target_year])

    candidates = await query_all(env.DB.prepare(query).bind(*bind_params))
    if not candidates:
        return json_response(
            {
                "samsung": {
                    "model_name": samsung["model_name"],
                    "price": samsung["current_price"],
                    "score": to_float(samsung.get("score_total")),
                    "year": target_year,
                    "size": target_size,
                    "resolution": target_resolution,
                    "panel_type": samsung.get("panel_type"),
                    "brand": samsung.get("brand") or samsung.get("manufacturer"),
                    "specs": extract_specs(samsung),
                },
                "matches": [],
                "aggregate": {
                    "weighted_cpi": 0.0,
                    "overall_verdict": "NO_MATCH",
                    "summary": "DB 내 비교 가능한 경쟁사 모델이 없습니다.",
                },
            }
        )

    samsung_year = to_int(target_year)
    samsung_size = to_float(target_size)
    samsung_price = to_int(samsung.get("current_price"))
    samsung_score = to_float(samsung.get("score_total"))
    samsung_vec = row_to_breakdown_vec(samsung)

    ranked = []
    for candidate in candidates:
        candidate_year = to_int(candidate.get("release_year"))
        year_weight = year_proximity_weight(samsung_year, candidate_year)
        if year_weight <= 0.0:
            continue

        candidate_size = to_float(candidate.get("screen_size_inch"))
        size_gap = abs(candidate_size - samsung_size)
        size_closeness = max(0.0, 1.0 - (size_gap / DEFAULT_SIZE_TOLERANCE))
        candidate_panel = str(candidate.get("panel_type") or "").strip().lower()
        panel_bonus = 1.0 if target_panel and target_panel == candidate_panel else 0.0
        spec_similarity = cosine_sim(samsung_vec, row_to_breakdown_vec(candidate))
        match_score = round(
            spec_similarity * 0.40
            + year_weight * 0.35
            + size_closeness * 0.15
            + panel_bonus * 0.10,
            4,
        )
        ranked.append(
            {
                **candidate,
                "match_score": match_score,
                "year_delta": candidate_year - samsung_year,
                "year_proximity": year_weight,
                "size_closeness": round(size_closeness, 4),
                "panel_type_bonus": panel_bonus,
                "spec_cosine_similarity": round(spec_similarity, 4),
            }
        )

    ranked.sort(
        key=lambda item: (
            item["match_score"],
            to_float(item.get("score_total")),
            -to_int(item.get("current_price")),
        ),
        reverse=True,
    )
    top_matches = ranked[:5]

    matches = []
    weighted_cpi_total = 0.0
    total_weight = 0.0
    for index, candidate in enumerate(top_matches, start=1):
        candidate_price = to_int(candidate.get("current_price"))
        candidate_score = to_float(candidate.get("score_total"))
        candidate_year = to_int(candidate.get("release_year"))
        adjusted_price = depreciation_adjusted_price(candidate_price, samsung_year, candidate_year)
        raw_cpi = round((samsung_price / candidate_price) * 100.0, 2) if candidate_price else 0.0
        adjusted_cpi = round((samsung_price / adjusted_price) * 100.0, 2) if adjusted_price else 0.0
        score_diff = round(samsung_score - candidate_score, 2)
        verdict = get_verdict(adjusted_cpi, score_diff)
        match_weight = to_float(candidate.get("match_score"))

        weighted_cpi_total += adjusted_cpi * match_weight
        total_weight += match_weight
        matches.append(
            {
                "rank": index,
                "model_name": candidate.get("model_name"),
                "brand": candidate.get("brand"),
                "year": candidate_year,
                "price": candidate_price,
                "score": candidate_score,
                "year_delta": candidate.get("year_delta"),
                "match_score": match_weight,
                "spec_cosine_similarity": candidate.get("spec_cosine_similarity"),
                "size_closeness": candidate.get("size_closeness"),
                "year_proximity": candidate.get("year_proximity"),
                "panel_type_bonus": candidate.get("panel_type_bonus"),
                "raw_cpi": raw_cpi,
                "adjusted_price": round(adjusted_price, 2),
                "adjusted_cpi": adjusted_cpi,
                "score_diff": score_diff,
                "verdict": verdict["verdict"],
                "verdict_reason": verdict["reason"],
                "specs": extract_specs(candidate),
            }
        )

    weighted_cpi = round(weighted_cpi_total / total_weight, 2) if total_weight else 0.0
    overall_verdict = aggregate_verdict(weighted_cpi) if matches else "NO_MATCH"
    return json_response(
        {
            "samsung": {
                "model_name": samsung["model_name"],
                "price": samsung_price,
                "score": samsung_score,
                "year": samsung_year,
                "size": samsung_size,
                "resolution": target_resolution,
                "panel_type": samsung.get("panel_type"),
                "brand": samsung.get("brand") or samsung.get("manufacturer"),
                "specs": extract_specs(samsung),
            },
            "matches": matches,
            "aggregate": {
                "weighted_cpi": weighted_cpi,
                "overall_verdict": overall_verdict,
                "summary": (
                    f"{samsung['model_name']} weighted CPI is {weighted_cpi}, "
                    f"classified as {overall_verdict} across {len(matches)} comparable competitors."
                    if matches
                    else "No comparable competitors were found in the TV database."
                ),
            },
        }
    )


async def cached_tv_match(request: Request, env) -> Response:
    """GET /api/tv/match?model_name=... 에 Cache API 6시간 캐싱 적용."""
    cache = await caches.open("tv-match-v1")
    cached = await cache.match(request)
    if cached:
        return cached
    response = await handle_tv_match(request, env)
    if response.status == 200:
        cloned = response.clone()
        h = _make_headers({"Content-Type": "application/json", "Cache-Control": "public, max-age=21600"})
        cached_response = Response.new(await cloned.text(), status=200, headers=h)
        await cache.put(request, cached_response)
    return response


async def on_fetch(request: Request, env) -> Response:
    parsed = URL.new(request.url)
    path = parsed.pathname
    method = request.method.upper()

    try:
        if method == "OPTIONS":
            return empty_response(204)
        if path == "/api/ping" and method == "GET":
            return await handle_ping(env)
        if path == "/api/tv/models" and method == "GET":
            return await handle_tv_models(request, env)
        if path == "/api/tv/match" and method == "GET":
            return await cached_tv_match(request, env)
        if path == "/api/tv/match" and method == "POST":
            return await handle_tv_match(request, env)
        return json_response({"detail": "Not Found"}, status=404)
    except Exception:
        return json_response({"detail": "Internal Server Error"}, status=500)
