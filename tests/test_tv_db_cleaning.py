from tv_db.crawler import clean_raw_specs, clean_spec_value, normalize_product_url


def test_normalize_product_url_drops_noise_query_params():
    url = "https://prod.danawa.com/info/?pcode=123&cate=10248425&keyword=TV&adinflow=Y"
    assert normalize_product_url(url) == "https://prod.danawa.com/info/?pcode=123&cate=10248425"


def test_clean_spec_value_drops_large_noise_blob():
    noisy = "제품명 최저가 자세히보기 판매점 : 12개 콘텐츠산업 진흥법에 의한 보호"
    assert clean_spec_value(noisy) is None


def test_clean_raw_specs_preserves_short_valid_values():
    raw = {
        "해상도": "4K UHD",
        "KC인증": "R-R-ABC-123 인증번호 확인",
        "추가단자": "제품명 최저가 자세히보기 판매점 : 12개",
    }
    cleaned = clean_raw_specs(raw)
    assert cleaned["해상도"] == "4K UHD"
    assert cleaned["KC인증"] == "R-R-ABC-123 인증번호 확인"
    assert "추가단자" not in cleaned
