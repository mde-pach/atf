"""The application's data: three tables, as SQLAlchemy models. Not part of ATF."""

from __future__ import annotations

from sqlalchemy import ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True)


class TodoList(Base):
    __tablename__ = "lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("owners.id"), default=None)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True)
    done: Mapped[bool] = mapped_column(default=False)
    todo_list_id: Mapped[int] = mapped_column(ForeignKey("lists.id"))


def open_database(path: str = "todo.db"):
    """Open the database, creating the tables the first time. Returns a session factory."""
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return sessionmaker(engine)
