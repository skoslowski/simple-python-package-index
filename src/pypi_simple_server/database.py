from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlmodel import JSON, Column, Field, Session, SQLModel, select
from sqlmodel import create_engine as create_engine

from .models import NormalizedProjectName, ProjectDetail, ProjectList


def create_db_and_tables(engine):
    SQLModel.metadata.create_all(engine)


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    index: str = Field(index=True)
    name: str


class Distribution(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    project_id: int | None = Field(default=None, foreign_key="project.id")
    project_version: str

    # PEP-503
    filename: str
    # PEP-700
    size: int
    # PEP-503
    url: str
    # Limited to a len() of 1 in HTML
    hashes: dict[str, str] = Field(sa_column=Column(JSON))
    # PEP-503 (updated)
    requires_python: str | None = None
    # PEP-592
    yanked: str | None = None
    # PEP-658, renamed from dist_info_metadata in PEP-714
    core_metadata: dict[str, str] | None = Field(sa_column=Column(JSON))


def get_project_list(session: Session, index: str | None) -> ProjectList[dict]:
    query = select(Project.name).distinct().order_by(Project.name)
    if index:
        query = query.where(Project.index == index)
    return ProjectList(projects=[{"name": name} for name in session.exec(query)])


def get_project_detail(
    session: Session, project: NormalizedProjectName, index: str | None
) -> ProjectDetail[Distribution]:

    query = (
        select(Distribution)
        .where(Project.id == Distribution.project_id)
        .where(Project.name == project)
        .order_by(Distribution.filename)
    )
    if index:
        query = query.where(Project.index == index)
    results = session.exec(query)

    files = []
    versions = set()
    seen = set()
    for distribution in results:
        if distribution.filename in seen:
            continue
        seen.add(distribution.filename)
        versions.add(distribution.project_version)
        files.append(distribution)
    return ProjectDetail(name=project, versions=sorted(versions), files=files)


def get_one_or_create[T](session: Session, query: Any, factory: Callable[[], T]) -> T:
    try:
        return session.exec(query).one()
    except NoResultFound:
        pass

    created = factory()

    try:
        session.add(created)
        session.commit()
    except IntegrityError:
        session.rollback()
        return session.exec(query).one()

    session.refresh(created)
    return created
