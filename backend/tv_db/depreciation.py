"""
depreciation.py - TV yearly depreciation helpers.
"""

DEPRECIATION_RATE: float = 0.85
MAX_YEAR_DELTA: int = 2


def year_proximity_weight(samsung_year: int, competitor_year: int) -> float:
    """
    Return a year-distance weight used by the candidate matcher.
    """
    delta = abs(competitor_year - samsung_year)
    return {0: 1.00, 1: 0.70, 2: 0.40}.get(delta, 0.00)


def depreciation_adjusted_price(
    competitor_price: int,
    samsung_year: int,
    competitor_year: int,
) -> float:
    """
    Normalize a competitor price onto the Samsung model year baseline.
    """
    year_delta = competitor_year - samsung_year
    if year_delta == 0:
        return float(competitor_price)

    factor = DEPRECIATION_RATE ** abs(year_delta)
    if year_delta < 0:
        return competitor_price / factor
    return competitor_price * factor
