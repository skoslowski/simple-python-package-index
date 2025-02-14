import logging
from contextlib import asynccontextmanager
from enum import StrEnum
from importlib.metadata import version
from typing import Annotated

from anyio import to_thread
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.params import Depends
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from packaging.utils import canonicalize_name
from sqlmodel import Session
from starlette.status import HTTP_404_NOT_FOUND, HTTP_406_NOT_ACCEPTABLE

from .config import Settings
from .database import (
    create_db_and_tables,
    create_engine,
    get_project_detail,
    get_project_list,
)
from .loader import update_db
from .models import ProjectDetail, ProjectFile, ProjectList, ProjectListEntry
from .templates import jinja_env
from .utils import Etag, FileMTimeWatcher

logger = logging.getLogger(__name__)
settings = Settings()
engine = create_engine(
    url=f"sqlite:///{settings.database_file}",
    connect_args={"check_same_thread": False},
)
templates = Jinja2Templates(env=jinja_env)
get_etag = Etag(lambda r: str(getattr(r.state, "dbfile_watcher", "")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Create and init database")
    settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    create_db_and_tables(engine)

    with Session(engine) as session:
        await reload_index_data(session)

    watcher = FileMTimeWatcher(settings.database_file)
    watcher.start()
    yield {"dbfile_watcher": watcher}


class MediaType(StrEnum):
    JSON_V1 = "application/vnd.pypi.simple.v1+json"
    HTML_V1 = "application/vnd.pypi.simple.v1+html"


_ACCEPTABLE = {
    MediaType.JSON_V1: {
        MediaType.JSON_V1,
        "application/vnd.pypi.simple.latest+json",
    },
    MediaType.HTML_V1: {
        MediaType.HTML_V1,
        "application/vnd.pypi.simple.latest+html",
        "text/html",
        "*/*",
    },
}


class SimpleV1JSONResponse(JSONResponse):
    media_type = MediaType.JSON_V1


def get_response_media_type(request: Request) -> MediaType:
    accept = set(request.headers.get("accept", "*/*").split(","))
    for media_type, acceptable in _ACCEPTABLE.items():
        if acceptable & accept:
            return media_type
    raise HTTPException(HTTP_406_NOT_ACCEPTABLE)


get_etag = Etag(lambda r: str(getattr(r.state, "dbfile_watcher", "")))


def get_session():
    with Session(engine) as session:
        yield session


app = FastAPI(title=__package__ or "", version=version(__package__ or ""), lifespan=lifespan)


@app.get("/ping")
async def ping():
    return {}  # docker health-check


@app.get("/reload", response_class=PlainTextResponse)
async def reload_index_data(session: Annotated[Session, Depends(get_session)]):
    logger.info("Scan files and update database")
    await to_thread.run_sync(update_db, session, settings.base_dir, settings.cache_dir_)


def index_get(path: str, summary: str):
    return app.get(
        path,
        summary=summary,
        response_class=SimpleV1JSONResponse,
        response_model=ProjectList[ProjectListEntry],
        response_model_exclude_none=True,
    )


@index_get("/simple/", summary="Root Project Index")
@index_get("/{index}/simple/", summary="Namespace Project Index")
async def index(
    request: Request,
    media_type: Annotated[MediaType, Depends(get_response_media_type)],
    session: Annotated[Session, Depends(get_session)],
    etag: Annotated[str, Depends(get_etag)],
    index: str | None = None,
):
    project_list = await to_thread.run_sync(get_project_list, session, index)

    if not project_list.projects:
        raise HTTPException(HTTP_404_NOT_FOUND, detail="Can't find this index")

    match media_type:
        case MediaType.JSON_V1:
            return project_list
        case MediaType.HTML_V1:
            return templates.TemplateResponse(
                request,
                name="index.html",
                context={"model": project_list, "generator": f"{app.title} v{app.version}"},
                media_type=media_type,
                headers={"etag": etag},
            )

    raise HTTPException(HTTP_406_NOT_ACCEPTABLE)


def detail_get(path: str, summary: str):
    return app.get(
        path,
        summary=summary,
        response_class=SimpleV1JSONResponse,
        response_model=ProjectDetail[ProjectFile],
        response_model_exclude_none=True,
        dependencies=[Depends(Etag(lambda r: str(r.state.dbfile_watcher.mtime)))],
    )


@detail_get("/simple/{project}/", summary="Root Project Detail")
@detail_get("/{index}/simple/{project}/", summary="Namespaced Project Detail")
async def project_detail(
    request: Request,
    media_type: Annotated[MediaType, Depends(get_response_media_type)],
    session: Annotated[Session, Depends(get_session)],
    etag: Annotated[str, Depends(get_etag)],
    project: str,
    index: str = "",
):
    project_canonical = canonicalize_name(project)
    if project != project_canonical:
        return RedirectResponse(
            url=request.url.path.replace(project, project_canonical),
            status_code=301,
        )

    project_details = await to_thread.run_sync(
        get_project_detail, session, project_canonical, index
    )
    for project_file in project_details.files:
        project_file.url = str(request.url_for("files", path=project_file.url))

    if not project_details.files:
        raise HTTPException(HTTP_404_NOT_FOUND, detail="Can't find this project")

    match media_type:
        case MediaType.JSON_V1:
            return project_details
        case MediaType.HTML_V1:
            return templates.TemplateResponse(
                request=request,
                name="detail.html",
                context={"model": project_details, "generator": f"{app.title} v{app.version}"},
                media_type=media_type,
                headers={"etag": etag},
            )
    raise HTTPException(HTTP_406_NOT_ACCEPTABLE)


staticfiles = StaticFiles()
staticfiles.all_directories += [settings.base_dir, settings.cache_dir_]
app.mount(settings.files_url, staticfiles, name="files")
