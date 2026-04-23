CREATE TABLE IF NOT EXISTS tv_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL UNIQUE,
    product_url TEXT NOT NULL,
    manufacturer TEXT NOT NULL DEFAULT '',
    brand TEXT NOT NULL DEFAULT '',
    release_year INTEGER,
    screen_size_inch REAL,
    resolution TEXT,
    panel_type TEXT,
    refresh_rate_hz REAL,
    operating_system TEXT,
    current_price INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    other_specs TEXT NOT NULL DEFAULT '{}',
    raw_specs TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'danawa',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    score_total REAL DEFAULT 0.0,
    score_breakdown TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS tv_price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    price INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    crawled_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'danawa',
    FOREIGN KEY(product_id) REFERENCES tv_products(id) ON DELETE CASCADE
);
