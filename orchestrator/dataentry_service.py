"""Data Entry — per-user dynamic Postgres tables.

This is the ONLY place in the codebase that emits DDL. The spec calls for
"real Postgres tables under a per-user schema", so we create genuine tables via
runtime CREATE/ALTER — but we never derive SQL identifiers from user input.

Security model:
  * Every physical identifier (schema, table, column) is either the fixed
    ``dataentry_`` prefix + a sanitized email, or an opaque generated name
    (``t_<hex>`` / ``c_<hex>``). User-supplied *display* names are stored as
    data in metadata tables and NEVER interpolated into SQL.
  * All generated identifiers are still re-validated with ``_safe_ident`` and
    double-quoted before interpolation (defense in depth).
  * All row *values* go through bound parameters (never string-formatted).

Each user schema holds two metadata tables plus one real table per user table:
  ``_dataentry_tables(id, physical_name, display_name, domain, created_at)``
  ``_dataentry_columns(id, table_id, physical_name, display_name, data_type, order_index)``
"""
import re
import uuid
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

# Whitelisted logical types → Postgres types. Also used to CAST bound values.
_TYPE_MAP = {
    "text": "text",
    "number": "numeric",
    "boolean": "boolean",
    "date": "date",
    "timestamp": "timestamptz",
}


def _safe_ident(ident: str) -> str:
    """Validate an identifier we intend to interpolate into SQL. Raises on any
    identifier that isn't a plain lowercase snake token (defense in depth — all
    call sites already pass generated/sanitized names)."""
    if not ident or len(ident) > 63 or not _IDENT_RE.match(ident):
        raise HTTPException(status_code=400, detail=f"Invalid identifier: {ident!r}")
    return ident


def _qi(ident: str) -> str:
    return '"' + _safe_ident(ident) + '"'


def _qt(schema: str, table: str) -> str:
    return f"{_qi(schema)}.{_qi(table)}"


def _pg_type(data_type: str) -> str:
    if data_type not in _TYPE_MAP:
        raise HTTPException(status_code=400, detail=f"Unsupported column type: {data_type!r}")
    return _TYPE_MAP[data_type]


def _gen_table_name() -> str:
    return "t_" + uuid.uuid4().hex[:12]


def _gen_column_name() -> str:
    return "c_" + uuid.uuid4().hex[:12]


def derive_schema_name(email: str) -> str:
    """`dataentry_` + sanitized email. Deterministic; the caller resolves rare
    collisions (two emails sanitizing alike) via the users.dataentry_schema
    unique constraint by appending a suffix."""
    local = email.strip().lower()
    sanitized = re.sub(r"[^a-z0-9]+", "_", local).strip("_")
    if not sanitized:
        sanitized = "user"
    name = f"dataentry_{sanitized}"[:63].rstrip("_")
    return name


def _coerce(value: Any) -> Optional[str]:
    """Normalize a JSON scalar to a string for a CAST-in-SQL bind (or None).
    Casting in SQL (rather than binding native types) avoids asyncpg's strict
    type inference across our five column types."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ── Schema / metadata bootstrap ──────────────────────────────────────────────

async def ensure_schema(db: AsyncSession, schema: str) -> None:
    """Create the user's schema + metadata tables if absent. Idempotent."""
    s = _qi(schema)
    await db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {s}"))
    await db.execute(text(
        f"CREATE TABLE IF NOT EXISTS {s}.\"_dataentry_tables\" ("
        "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
        "  physical_name TEXT NOT NULL UNIQUE,"
        "  display_name TEXT NOT NULL,"
        "  domain TEXT NOT NULL DEFAULT 'standup',"
        "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    ))
    await db.execute(text(
        f"CREATE TABLE IF NOT EXISTS {s}.\"_dataentry_columns\" ("
        "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
        f"  table_id UUID NOT NULL REFERENCES {s}.\"_dataentry_tables\"(id) ON DELETE CASCADE,"
        "  physical_name TEXT NOT NULL,"
        "  display_name TEXT NOT NULL,"
        "  data_type TEXT NOT NULL DEFAULT 'text',"
        "  order_index INTEGER NOT NULL DEFAULT 0"
        ")"
    ))


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _get_table_meta(db: AsyncSession, schema: str, table_id: str) -> dict:
    s = _qi(schema)
    row = (await db.execute(
        text(f"SELECT id::text AS id, physical_name, display_name, domain, created_at "
             f"FROM {s}.\"_dataentry_tables\" WHERE id = :tid"),
        {"tid": table_id},
    )).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Data Entry table not found")
    return dict(row)


async def _get_columns_meta(db: AsyncSession, schema: str, table_id: str) -> list[dict]:
    s = _qi(schema)
    rows = (await db.execute(
        text(f"SELECT id::text AS id, physical_name, display_name, data_type, order_index "
             f"FROM {s}.\"_dataentry_columns\" WHERE table_id = :tid ORDER BY order_index, display_name"),
        {"tid": table_id},
    )).mappings().all()
    return [dict(r) for r in rows]


# ── Table operations ─────────────────────────────────────────────────────────

async def list_tables(db: AsyncSession, schema: str, domain: Optional[str] = None) -> list[dict]:
    await ensure_schema(db, schema)
    s = _qi(schema)
    if domain:
        rows = (await db.execute(
            text(f"SELECT id::text AS id, physical_name, display_name, domain, created_at "
                 f"FROM {s}.\"_dataentry_tables\" WHERE domain = :d ORDER BY created_at DESC"),
            {"d": domain},
        )).mappings().all()
    else:
        rows = (await db.execute(
            text(f"SELECT id::text AS id, physical_name, display_name, domain, created_at "
                 f"FROM {s}.\"_dataentry_tables\" ORDER BY created_at DESC"),
        )).mappings().all()
    tables = []
    for r in rows:
        cols = await _get_columns_meta(db, schema, r["id"])
        tables.append({**dict(r), "columns": cols})
    return tables


async def get_table(db: AsyncSession, schema: str, table_id: str) -> dict:
    meta = await _get_table_meta(db, schema, table_id)
    meta["columns"] = await _get_columns_meta(db, schema, table_id)
    return meta


async def create_table(db: AsyncSession, schema: str, display_name: str,
                       domain: str, columns: list[dict]) -> dict:
    await ensure_schema(db, schema)
    s = _qi(schema)
    physical = _gen_table_name()

    # The real data table: system id + created_at, plus one column per def.
    col_defs = ['"id" UUID PRIMARY KEY DEFAULT gen_random_uuid()',
                '"created_at" TIMESTAMPTZ NOT NULL DEFAULT now()']
    col_meta = []
    for idx, c in enumerate(columns):
        phys = _gen_column_name()
        pgtype = _pg_type(c["data_type"])
        col_defs.append(f"{_qi(phys)} {pgtype}")
        col_meta.append((phys, c["display_name"], c["data_type"], idx))

    await db.execute(text(f"CREATE TABLE {_qt(schema, physical)} ({', '.join(col_defs)})"))

    table_id = str(uuid.uuid4())
    await db.execute(
        text(f"INSERT INTO {s}.\"_dataentry_tables\" (id, physical_name, display_name, domain) "
             "VALUES (:id, :pn, :dn, :dom)"),
        {"id": table_id, "pn": physical, "dn": display_name, "dom": domain},
    )
    for phys, dn, dt, idx in col_meta:
        await db.execute(
            text(f"INSERT INTO {s}.\"_dataentry_columns\" "
                 "(table_id, physical_name, display_name, data_type, order_index) "
                 "VALUES (:tid, :pn, :dn, :dt, :oi)"),
            {"tid": table_id, "pn": phys, "dn": dn, "dt": dt, "oi": idx},
        )
    await db.commit()
    return await get_table(db, schema, table_id)


async def rename_table(db: AsyncSession, schema: str, table_id: str, display_name: str) -> dict:
    await _get_table_meta(db, schema, table_id)  # 404 guard
    s = _qi(schema)
    await db.execute(
        text(f"UPDATE {s}.\"_dataentry_tables\" SET display_name = :dn WHERE id = :tid"),
        {"dn": display_name, "tid": table_id},
    )
    await db.commit()
    return await get_table(db, schema, table_id)


async def drop_table(db: AsyncSession, schema: str, table_id: str) -> None:
    meta = await _get_table_meta(db, schema, table_id)
    s = _qi(schema)
    await db.execute(text(f"DROP TABLE IF EXISTS {_qt(schema, meta['physical_name'])}"))
    await db.execute(text(f"DELETE FROM {s}.\"_dataentry_tables\" WHERE id = :tid"), {"tid": table_id})
    await db.commit()


# ── Column operations ────────────────────────────────────────────────────────

async def add_column(db: AsyncSession, schema: str, table_id: str,
                     display_name: str, data_type: str) -> dict:
    meta = await _get_table_meta(db, schema, table_id)
    s = _qi(schema)
    phys = _gen_column_name()
    pgtype = _pg_type(data_type)
    await db.execute(text(
        f"ALTER TABLE {_qt(schema, meta['physical_name'])} ADD COLUMN {_qi(phys)} {pgtype}"
    ))
    next_idx = (await db.execute(
        text(f"SELECT COALESCE(MAX(order_index) + 1, 0) FROM {s}.\"_dataentry_columns\" WHERE table_id = :tid"),
        {"tid": table_id},
    )).scalar() or 0
    await db.execute(
        text(f"INSERT INTO {s}.\"_dataentry_columns\" "
             "(table_id, physical_name, display_name, data_type, order_index) "
             "VALUES (:tid, :pn, :dn, :dt, :oi)"),
        {"tid": table_id, "pn": phys, "dn": display_name, "dt": data_type, "oi": next_idx},
    )
    await db.commit()
    return await get_table(db, schema, table_id)


async def drop_column(db: AsyncSession, schema: str, table_id: str, column_id: str) -> dict:
    meta = await _get_table_meta(db, schema, table_id)
    s = _qi(schema)
    col = (await db.execute(
        text(f"SELECT physical_name FROM {s}.\"_dataentry_columns\" WHERE id = :cid AND table_id = :tid"),
        {"cid": column_id, "tid": table_id},
    )).scalar_one_or_none()
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")
    await db.execute(text(
        f"ALTER TABLE {_qt(schema, meta['physical_name'])} DROP COLUMN IF EXISTS {_qi(col)}"
    ))
    await db.execute(text(f"DELETE FROM {s}.\"_dataentry_columns\" WHERE id = :cid"), {"cid": column_id})
    await db.commit()
    return await get_table(db, schema, table_id)


# ── Row operations ───────────────────────────────────────────────────────────

async def list_rows(db: AsyncSession, schema: str, table_id: str) -> list[dict]:
    meta = await _get_table_meta(db, schema, table_id)
    cols = await _get_columns_meta(db, schema, table_id)
    select_cols = ['"id"'] + [_qi(c["physical_name"]) for c in cols] + ['"created_at"']
    rows = (await db.execute(
        text(f"SELECT {', '.join(select_cols)} FROM {_qt(schema, meta['physical_name'])} "
             "ORDER BY created_at")
    )).mappings().all()
    return [dict(r) for r in rows]


def _build_assignments(cols_by_phys: dict, values: dict) -> tuple[list[str], list[str], dict]:
    """Return (column_idents, cast_placeholders, params) for the given values,
    restricted to known columns. Values bound + CAST to the column's type."""
    idents, placeholders, params = [], [], {}
    i = 0
    for phys, value in values.items():
        col = cols_by_phys.get(phys)
        if not col:
            continue  # ignore unknown columns
        pgtype = _pg_type(col["data_type"])
        key = f"p{i}"
        idents.append(_qi(phys))
        placeholders.append(f"CAST(:{key} AS {pgtype})")
        params[key] = _coerce(value)
        i += 1
    return idents, placeholders, params


async def insert_row(db: AsyncSession, schema: str, table_id: str, values: dict) -> dict:
    meta = await _get_table_meta(db, schema, table_id)
    cols = await _get_columns_meta(db, schema, table_id)
    cols_by_phys = {c["physical_name"]: c for c in cols}
    idents, placeholders, params = _build_assignments(cols_by_phys, values)

    row_id = str(uuid.uuid4())
    params["row_id"] = row_id
    if idents:
        sql = (f"INSERT INTO {_qt(schema, meta['physical_name'])} "
               f"(\"id\", {', '.join(idents)}) VALUES (:row_id, {', '.join(placeholders)})")
    else:
        sql = f"INSERT INTO {_qt(schema, meta['physical_name'])} (\"id\") VALUES (:row_id)"
    await db.execute(text(sql), params)
    await db.commit()
    return {"id": row_id}


async def update_row(db: AsyncSession, schema: str, table_id: str, row_id: str, values: dict) -> dict:
    meta = await _get_table_meta(db, schema, table_id)
    cols = await _get_columns_meta(db, schema, table_id)
    cols_by_phys = {c["physical_name"]: c for c in cols}
    idents, placeholders, params = _build_assignments(cols_by_phys, values)
    if not idents:
        return {"id": row_id}
    set_clause = ", ".join(f"{ident} = {ph}" for ident, ph in zip(idents, placeholders))
    params["row_id"] = row_id
    result = await db.execute(
        text(f"UPDATE {_qt(schema, meta['physical_name'])} SET {set_clause} WHERE \"id\" = :row_id"),
        params,
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Row not found")
    return {"id": row_id}


async def delete_row(db: AsyncSession, schema: str, table_id: str, row_id: str) -> None:
    meta = await _get_table_meta(db, schema, table_id)
    result = await db.execute(
        text(f"DELETE FROM {_qt(schema, meta['physical_name'])} WHERE \"id\" = :row_id"),
        {"row_id": row_id},
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Row not found")
