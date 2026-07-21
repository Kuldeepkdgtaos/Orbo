"""Data Entry REST — user-facing CRUD over per-user dynamic tables.

Every route is scoped to the caller's ``dataentry_schema`` (resolved from the
JWT by ``current_user``). All DDL/DML is delegated to ``dataentry_service``,
the single place allowed to emit dynamic SQL.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_db
from shared.schemas import (
    DataEntryColumnAdd,
    DataEntryTableCreate,
    DataEntryTableRead,
    DataEntryTableRename,
    DataEntryRowWrite,
)

from ..auth import current_user
from .. import dataentry_service as des

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dataentry", tags=["dataentry"])


def _schema(request: Request) -> str:
    return current_user(request).dataentry_schema


# ── Tables ───────────────────────────────────────────────────────────────────

@router.get("/tables", response_model=list[DataEntryTableRead])
async def list_tables(request: Request, domain: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    return await des.list_tables(db, _schema(request), domain)


@router.post("/tables", response_model=DataEntryTableRead, status_code=201)
async def create_table(payload: DataEntryTableCreate, request: Request, db: AsyncSession = Depends(get_db)):
    return await des.create_table(
        db, _schema(request), payload.display_name, payload.domain,
        [c.model_dump() for c in payload.columns],
    )


@router.get("/tables/{table_id}", response_model=DataEntryTableRead)
async def get_table(table_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await des.get_table(db, _schema(request), table_id)


@router.patch("/tables/{table_id}", response_model=DataEntryTableRead)
async def rename_table(table_id: str, payload: DataEntryTableRename, request: Request, db: AsyncSession = Depends(get_db)):
    return await des.rename_table(db, _schema(request), table_id, payload.display_name)


@router.delete("/tables/{table_id}", status_code=204)
async def delete_table(table_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await des.drop_table(db, _schema(request), table_id)


# ── Columns ──────────────────────────────────────────────────────────────────

@router.post("/tables/{table_id}/columns", response_model=DataEntryTableRead)
async def add_column(table_id: str, payload: DataEntryColumnAdd, request: Request, db: AsyncSession = Depends(get_db)):
    return await des.add_column(db, _schema(request), table_id, payload.display_name, payload.data_type)


@router.delete("/tables/{table_id}/columns/{column_id}", response_model=DataEntryTableRead)
async def drop_column(table_id: str, column_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await des.drop_column(db, _schema(request), table_id, column_id)


# ── Rows ─────────────────────────────────────────────────────────────────────

@router.get("/tables/{table_id}/rows")
async def list_rows(table_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await des.list_rows(db, _schema(request), table_id)


@router.post("/tables/{table_id}/rows", status_code=201)
async def insert_row(table_id: str, payload: DataEntryRowWrite, request: Request, db: AsyncSession = Depends(get_db)):
    return await des.insert_row(db, _schema(request), table_id, payload.values)


@router.patch("/tables/{table_id}/rows/{row_id}")
async def update_row(table_id: str, row_id: str, payload: DataEntryRowWrite, request: Request, db: AsyncSession = Depends(get_db)):
    return await des.update_row(db, _schema(request), table_id, row_id, payload.values)


@router.delete("/tables/{table_id}/rows/{row_id}", status_code=204)
async def delete_row(table_id: str, row_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await des.delete_row(db, _schema(request), table_id, row_id)
