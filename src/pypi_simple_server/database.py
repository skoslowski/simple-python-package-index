from sqlmodel import JSON, Column, Field, Session, SQLModel, create_engine, select

from .config import settings
from .models import NormalizedName, ProjectDetail, ProjectList, ProjectListEntry

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


class Distribution(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    version: str

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


def get_project_list(index: str, session: Session) -> ProjectList:
    if index and not index[-1] == "/":
        index = f"{index}/"
    results = session.exec(
        select(Distribution.name)
        .distinct()
        .where(Distribution.url.startswith(index))
        .order_by(Distribution.name)
    )
    return ProjectList(projects=[ProjectListEntry(name=name) for name in results])


def get_project_detail(index: str, project: NormalizedName, session: Session) -> ProjectDetail[Distribution]:
    if index and not index[-1] == "/":
        index = f"{index}/"
    results = session.exec(
        select(Distribution)
        .where(Distribution.name == project)
        .where(Distribution.url.startswith(index))
        .order_by(Distribution.filename)
    )

    files = []
    versions = set()
    seen = set()
    for distribution in results:
        if distribution.filename in seen:
            continue
        seen.add(distribution.filename)
        versions.add(distribution.version)
        files.append(distribution)
    return ProjectDetail(name=project, versions=sorted(versions), files=files)
