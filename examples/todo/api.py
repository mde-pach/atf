"""The product under test: a Todo API over the models. Not part of ATF.

`python api.py` serves it on 8801. Every route is a few lines of SQLAlchemy, which is the point —
the suite beside it is testing this, and there is nothing here that knows a test exists.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from models import Owner, Task, TodoList, open_database
from pydantic import BaseModel
from sqlalchemy import select

Session = open_database()
app = FastAPI(title="todo")

TABLES = {"owners": Owner, "lists": TodoList, "tasks": Task}


class NewOwner(BaseModel):
    email: str


class NewList(BaseModel):
    slug: str
    owner_id: int | None = None


def shown(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


@app.get("/{table}")
def listing(table: str, email: str | None = None, slug: str | None = None) -> dict[str, Any]:
    """Every record, narrowed by the fields this API takes as query parameters."""
    model = TABLES.get(table)
    if model is None:
        raise HTTPException(404, "no such collection")
    query = select(model)
    for field, wanted in (("email", email), ("slug", slug)):
        if wanted is not None and hasattr(model, field):
            query = query.where(getattr(model, field) == wanted)
    with Session() as session:
        return {"items": [shown(row) for row in session.scalars(query)]}


@app.get("/owners/{owner_id}/lists")
def lists_of(owner_id: int) -> dict[str, Any]:
    """What the suite is really about: a person's lists."""
    with Session() as session:
        found = session.scalars(select(TodoList).where(TodoList.owner_id == owner_id))
        return {"items": [shown(row) for row in found]}


@app.post("/owners", status_code=201)
def add_owner(body: NewOwner) -> dict[str, Any]:
    with Session() as session:
        owner = Owner(email=body.email)
        session.add(owner)
        session.commit()
        return shown(owner)


@app.post("/lists", status_code=201)
def add_list(body: NewList) -> dict[str, Any]:
    with Session() as session:
        made = TodoList(slug=body.slug, owner_id=body.owner_id)
        session.add(made)
        session.commit()
        return shown(made)


@app.patch("/{table}/{row_id}")
def change(table: str, row_id: int, body: dict[str, Any]) -> dict[str, Any]:
    model = TABLES.get(table)
    if model is None:
        raise HTTPException(404, "no such collection")
    with Session() as session:
        row = session.get(model, row_id)
        if row is None:
            raise HTTPException(404, "no such record")
        for field, value in body.items():
            setattr(row, field, value)
        session.commit()
        return shown(row)


@app.delete("/{table}/{row_id}", status_code=204)
def remove(table: str, row_id: int) -> None:
    model = TABLES.get(table)
    if model is None:
        raise HTTPException(404, "no such collection")
    with Session() as session:
        row = session.get(model, row_id)
        if row is not None:
            session.delete(row)
            session.commit()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8801, log_level="warning")
