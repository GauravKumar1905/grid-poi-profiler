"""Database layer: schema, insert, and query helpers.

Supports two modes:
- Remote (Turso): when TURSO_DATABASE_URL is set, connects via libsql with embedded replica.
- Local (dev): when TURSO_DATABASE_URL is empty, uses a local SQLite file via libsql.
"""

import json
import os
import libsql_experimental as libsql

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")


def get_conn():
    if TURSO_DATABASE_URL:
        conn = libsql.connect(
            "local.db",
            sync_url=TURSO_DATABASE_URL,
            auth_token=TURSO_AUTH_TOKEN,
        )
        conn.sync()
    else:
        conn = libsql.connect("grid.db")
    return conn


def _rows_to_dicts(cursor) -> list[dict]:
    """Convert cursor results to list of dicts using cursor.description."""
    if cursor.description is None:
        return []
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _row_to_dict(cursor) -> dict | None:
    """Convert single cursor result to dict."""
    if cursor.description is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip(columns, row))


def init_db() -> None:
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS grid_points (
            id   TEXT PRIMARY KEY,
            i    INTEGER NOT NULL,
            j    INTEGER NOT NULL,
            lat  REAL NOT NULL,
            lon  REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pois (
            place_id           TEXT PRIMARY KEY,
            name               TEXT,
            lat                REAL NOT NULL,
            lon                REAL NOT NULL,
            types              TEXT,
            rating             REAL,
            user_ratings_total INTEGER,
            raw_json           TEXT,
            last_updated       TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            grid_point_id TEXT PRIMARY KEY REFERENCES grid_points(id),
            geo_attrs     TEXT,
            audience      TEXT,
            poi_summary   TEXT,
            last_updated  TEXT,
            version       INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    if TURSO_DATABASE_URL:
        conn.sync()
    conn.close()


# ---- Grid points ----

def upsert_grid_points(points: list[dict]) -> None:
    conn = get_conn()
    for p in points:
        conn.execute(
            "INSERT OR REPLACE INTO grid_points (id, i, j, lat, lon) VALUES (?, ?, ?, ?, ?)",
            (p["id"], p["i"], p["j"], p["lat"], p["lon"]),
        )
    conn.commit()
    if TURSO_DATABASE_URL:
        conn.sync()
    conn.close()


def get_all_grid_points() -> list[dict]:
    conn = get_conn()
    cursor = conn.execute("SELECT * FROM grid_points ORDER BY j, i")
    result = _rows_to_dicts(cursor)
    conn.close()
    return result


# ---- POIs ----

def upsert_pois(pois: list[dict]) -> None:
    conn = get_conn()
    for p in pois:
        conn.execute(
            """INSERT OR REPLACE INTO pois
               (place_id, name, lat, lon, types, rating, user_ratings_total, raw_json, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p["place_id"], p["name"], p["lat"], p["lon"], p["types"],
             p["rating"], p["user_ratings_total"], p["raw_json"], p["last_updated"]),
        )
    conn.commit()
    if TURSO_DATABASE_URL:
        conn.sync()
    conn.close()


def get_all_pois() -> list[dict]:
    conn = get_conn()
    cursor = conn.execute("SELECT * FROM pois")
    rows = _rows_to_dicts(cursor)
    conn.close()
    result = []
    for d in rows:
        d["types"] = json.loads(d["types"]) if d["types"] else []
        return_d = {k: v for k, v in d.items() if k != "raw_json"}
        result.append(return_d)
    return result


# ---- Profiles ----

def upsert_profile(grid_point_id: str, geo_attrs: dict, audience: dict, poi_summary: dict) -> None:
    conn = get_conn()
    from datetime import datetime, timezone
    conn.execute(
        """INSERT OR REPLACE INTO profiles
           (grid_point_id, geo_attrs, audience, poi_summary, last_updated, version)
           VALUES (?, ?, ?, ?, ?, COALESCE((SELECT version FROM profiles WHERE grid_point_id = ?), 0) + 1)""",
        (
            grid_point_id,
            json.dumps(geo_attrs),
            json.dumps(audience),
            json.dumps(poi_summary),
            datetime.now(timezone.utc).isoformat(),
            grid_point_id,
        ),
    )
    conn.commit()
    if TURSO_DATABASE_URL:
        conn.sync()
    conn.close()


def get_profile(grid_point_id: str) -> dict | None:
    conn = get_conn()
    cursor = conn.execute("SELECT * FROM profiles WHERE grid_point_id = ?", (grid_point_id,))
    d = _row_to_dict(cursor)
    conn.close()
    if not d:
        return None
    d["geo_attrs"] = json.loads(d["geo_attrs"]) if d["geo_attrs"] else {}
    d["audience"] = json.loads(d["audience"]) if d["audience"] else {}
    d["poi_summary"] = json.loads(d["poi_summary"]) if d["poi_summary"] else {}
    return d


def get_all_profiles() -> list[dict]:
    conn = get_conn()
    cursor = conn.execute("SELECT * FROM profiles")
    rows = _rows_to_dicts(cursor)
    conn.close()
    result = []
    for d in rows:
        d["geo_attrs"] = json.loads(d["geo_attrs"]) if d["geo_attrs"] else {}
        d["audience"] = json.loads(d["audience"]) if d["audience"] else {}
        d["poi_summary"] = json.loads(d["poi_summary"]) if d["poi_summary"] else {}
        result.append(d)
    return result
