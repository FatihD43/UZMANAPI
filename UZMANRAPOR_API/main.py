from __future__ import annotations

import base64
import os
import re
from typing import Any, Iterable

import pyodbc
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="UzmanRapor API", version="1.0")


class SqlRequest(BaseModel):
    query: str = Field(..., description="Parametreli SQL (?), veya EXEC dbo.sp_X @p=?")
    params: list[Any] = Field(default_factory=list)


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v.strip() if v else default


def _require_token(x_token: str | None) -> None:
    expected = _env("UZMANRAPOR_API_TOKEN", "")
    if expected:
        if not x_token or x_token != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")


def _sql_conn_str() -> str:
    # Tek satır connection string (tercih)
    raw = _env("UZMANRAPOR_SQL_CONN_STR", "")
    if raw:
        return raw

    # Parça parça (alternatif)
    driver = _env("UZMANRAPOR_SQL_DRIVER", "{SQL Server}")
    server = _env("UZMANRAPOR_SQL_SERVER", "10.30.9.14,1433")
    database = _env("UZMANRAPOR_SQL_DATABASE", "UzmanRaporDB")
    uid = _env("UZMANRAPOR_SQL_UID", "")
    pwd = _env("UZMANRAPOR_SQL_PWD", "")
    trusted = _env("UZMANRAPOR_SQL_TRUSTED", "")

    parts = [f"Driver={driver};", f"Server={server};", f"Database={database};"]
    if trusted.lower() in {"1", "true", "yes"}:
        parts.append("Trusted_Connection=yes;")
    elif uid and pwd:
        parts.append(f"UID={uid};")
        parts.append(f"PWD={pwd};")
    else:
        # Varsayılan: trusted dene
        parts.append("Trusted_Connection=yes;")
    return "".join(parts)


_FORBIDDEN = re.compile(
    r"\b(create|alter|drop|truncate|grant|revoke|xp_|sp_configure|openrowset|openquery)\b",
    re.IGNORECASE,
)

_ALLOWED_OBJECTS = {
    # core
    "dbo.AppMeta",
    "dbo.Snapshots",
    "dbo.NoteRules",
    "dbo.AppUsers",
    "dbo.AppLookupValues",
    "dbo.UstaDefteri",
    "dbo.TipBuzulmeModel",
    "dbo.LoomCutMap",
    "dbo.TypeSelvedgeMap",
    "dbo.BlockedLooms",
    "dbo.DummyLooms",
    # itema
    "dbo.ItemaAyar",
}

_ALLOWED_PROCS = {
    "dbo.sp_ItemaOtomatikAyar",
    "dbo.sp_ItemaTipOzelAyar",
}

# yakalanacak obje referansları: dbo.X
_OBJ_REF = re.compile(r"\bdbo\.(\w+)\b", re.IGNORECASE)
# exec dbo.sp_x
_EXEC_REF = re.compile(r"\bexec\s+(dbo\.(\w+))\b", re.IGNORECASE)


def _validate_query(query: str) -> None:
    q = query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty query")

    if _FORBIDDEN.search(q):
        raise HTTPException(status_code=403, detail="Forbidden SQL keyword")

    # izinli komutlar
    head = q.split(None, 1)[0].lower()
    if head not in {"select", "insert", "update", "delete", "exec", "with"}:
        raise HTTPException(status_code=403, detail="Only SELECT/INSERT/UPDATE/DELETE/EXEC are allowed")

    # obje whitelist kontrolü
    objs = {f"dbo.{m.group(1)}" for m in _OBJ_REF.finditer(q)}
    for obj in objs:
        if obj not in _ALLOWED_OBJECTS and obj not in _ALLOWED_PROCS:
            raise HTTPException(status_code=403, detail=f"Object not allowed: {obj}")

    if head == "exec":
        m = _EXEC_REF.search(q)
        if not m:
            raise HTTPException(status_code=403, detail="EXEC only allowed for dbo stored procedures")
        proc = m.group(1)
        if proc not in _ALLOWED_PROCS:
            raise HTTPException(status_code=403, detail=f"Procedure not allowed: {proc}")


def _adapt_params(query: str, params: list[Any]) -> list[Any]:
    # NoteRules varbinary için base64 -> bytes (heuristic)
    q = query.lower()
    if "insert into dbo.noterules" in q and params:
        out = params[:]
        for i, p in enumerate(out):
            if isinstance(p, str):
                try:
                    out[i] = base64.b64decode(p)
                except Exception:
                    pass
        return out
    return params


def _encode_value(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(v)).decode("ascii")
    return v


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sql")
def sql(req: SqlRequest, x_token: str | None = Header(default=None)) -> dict[str, Any]:
    _require_token(x_token)
    _validate_query(req.query)

    conn_str = _sql_conn_str()
    params = _adapt_params(req.query, list(req.params or []))

    try:
        conn = pyodbc.connect(conn_str, timeout=10)
        cur = conn.cursor()
        cur.execute(req.query, params)

        # SELECT / WITH: description dolu olur
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            data_rows = [[_encode_value(v) for v in row] for row in rows]
            return {"columns": cols, "rows": data_rows, "rowcount": len(data_rows)}
        else:
            conn.commit()
            rc = cur.rowcount if cur.rowcount is not None else -1
            return {"columns": [], "rows": [], "affected_rows": rc}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            conn.close()
        except Exception:
            pass
