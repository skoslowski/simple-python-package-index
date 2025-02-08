from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlmodel import JSON, Column, Field, Session, SQLModel, create_engine, select

from .config import settings
from .models import NormalizedName, ProjectDetail, ProjectFile, ProjectList, ProjectListEntry

engine = create_engine(
    url=f"sqlite:///{settings.database_file}",
    connect_args={"check_same_thread": False},
)


def create_db_and_tables():
    settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


class Index(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)


class Distribution(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    index_id: int | None = Field(default=None, foreign_key="index.id")
    name: str = Field(index=True)
    version: str

    # PEP-503
    filename: str
    # PEP-700
    size: int
    # PEP-503
    # url: str  # HttpUrl
    # Limited to a len() of 1 in HTML
    hashes: dict[str, str] = Field(sa_column=Column(JSON))
    # PEP-503 (updated)
    requires_python: str | None = None
    # PEP-592
    yanked: str | None = None
    # PEP-658, renamed from dist_info_metadata in PEP-714
    core_metadata: dict[str, str] | None = Field(sa_column=Column(JSON))


def get_project_list(index: str, session: Session) -> ProjectList:
    if index and not index[-1] == "/":
        index = f"{index}/"
    results = session.exec(
        select(Distribution.name, Index.name)
        .where(Index.id == Distribution.index_id)
        .where(Index.name.startswith(index))
    )
    return ProjectList(projects={ProjectListEntry(name=name) for name, _ in results})


def get_project_detail(index: str, project: NormalizedName, session: Session) -> ProjectDetail:
    if index and not index[-1] == "/":
        index = f"{index}/"
    results = session.exec(
        select(Distribution, Index)
        .where(Index.id == Distribution.index_id)
        .where(Index.name.startswith(index))
        .where(Distribution.name == project)
    )

    detail = ProjectDetail(name=project)
    for distribution, index_data in results:
        detail.versions.add(distribution.version)
        file = ProjectFile(
            filename=distribution.filename,
            size=distribution.size,
            url=f"{index_data.name}{distribution.filename}",
            hashes=distribution.hashes,
            requires_python=distribution.requires_python,
            yanked=distribution.yanked,
            core_metadata=distribution.core_metadata,
        )
        detail.files.add(file)
    return detail


def get_one_or_create[T: SQLModel](session: Session, query: Any, factory: Callable[[], T]) -> tuple[T, bool]:
    try:
        return session.exec(query).one(), False
    except NoResultFound:
        pass

    created = factory()

    try:
        session.add(created)
        session.commit()
    except IntegrityError:
        session.rollback()
        return session.exec(query).one(), False

    session.refresh(created)
    return created, True
