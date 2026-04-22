import json

from tv_db.db_manager import TVDatabaseManager, TVProductRecord


def make_record(price: int = 0) -> TVProductRecord:
    return TVProductRecord(
        model_name="TEST-TV-001",
        product_url="https://example.com/tv/1",
        manufacturer="Samsung",
        brand="Samsung",
        release_year=2026,
        screen_size_inch=65.0,
        resolution="4K UHD",
        panel_type="QLED",
        refresh_rate_hz=120.0,
        operating_system="Tizen",
        current_price=price,
        review_count=12,
        other_specs={"hdmi": "4"},
        raw_specs={"화면 크기": "65인치"},
    )


def test_initialize_and_upsert_creates_tables(tmp_path):
    manager = TVDatabaseManager(tmp_path / "tv.db")
    manager.initialize()
    manager.upsert_product(make_record(price=1000), crawled_at="2026-04-22T00:00:00+00:00")

    rows = manager.fetch_products()
    assert len(rows) == 1
    assert rows[0]["model_name"] == "TEST-TV-001"
    assert rows[0]["current_price"] == 1000

    history_count = manager.connection.execute(
        "SELECT COUNT(*) FROM tv_price_history"
    ).fetchone()[0]
    assert history_count == 1
    manager.close()


def test_upsert_updates_current_snapshot_and_keeps_history(tmp_path):
    manager = TVDatabaseManager(tmp_path / "tv.db")
    manager.initialize()
    manager.upsert_product(make_record(price=1000), crawled_at="2026-04-22T00:00:00+00:00")
    manager.upsert_product(make_record(price=1200), crawled_at="2026-04-22T01:00:00+00:00")

    product = manager.connection.execute(
        "SELECT current_price, other_specs FROM tv_products WHERE model_name = ?",
        ("TEST-TV-001",),
    ).fetchone()
    assert product["current_price"] == 1200
    assert json.loads(product["other_specs"]) == {"hdmi": "4"}

    history_count = manager.connection.execute(
        "SELECT COUNT(*) FROM tv_price_history WHERE product_id = 1"
    ).fetchone()[0]
    assert history_count == 2
    manager.close()
