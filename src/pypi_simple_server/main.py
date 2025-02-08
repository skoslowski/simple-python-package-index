import logging
from contextlib import asynccontextmanager
from enum import StrEnum
from importlib.metadata import version
from typing import Annotated, Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import HTTPException
from fastapi.params import Depends
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from packaging.utils import canonicalize_name
from sqlmodel import Session
from starlette.status import HTTP_404_NOT_FOUND, HTTP_406_NOT_ACCEPTABLE

from .config import settings
from .database import create_db_and_tables, get_project_detail, get_project_list, get_session
from .loader import update_db
from .models import ProjectDetail, ProjectList
from .templates import jinja_env
from .utils import Etag, FileMTimeWatcher

SessionDep = Annotated[Session, Depends(get_session)]

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Create and init database")
    create_db_and_tables()
    reload_index_data()
    watcher = FileMTimeWatcher(settings.database_file)
    watcher.start()
    yield {"dbfile_watcher": watcher}


class MediaType(StrEnum):
    JSON_V1 = "application/vnd.pypi.simple.v1+json"
    HTML_V1 = "application/vnd.pypi.simple.v1+html"


class SimpleV1JSONResponse(JSONResponse):
    media_type = MediaType.JSON_V1


templates = Jinja2Templates(env=jinja_env)


app = FastAPI(
    title=__package__ or "",
    version=version("pyps"),
    lifespan=lifespan,
    default_response_class=SimpleV1JSONResponse,
)


@app.get("/reload", response_class=PlainTextResponse)
def reload_index_data():
    logger.info("Scan files and update database")
    with next(get_session()) as session:
        update_db(session)


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


def get_response_media_type(request: Request) -> MediaType:
    accept = set(request.headers.get("accept", "*/*").split(","))
    for media_type, acceptable in _ACCEPTABLE.items():
        if acceptable & accept:
            return media_type
    raise HTTPException(HTTP_406_NOT_ACCEPTABLE)


def get_response(
    request: Request, model: Any, media_type: MediaType, etag: str, template_name: str
) -> Response:
    match media_type:
        case MediaType.JSON_V1:
            response = SimpleV1JSONResponse(model)
        case MediaType.HTML_V1:
            context = {"model": model, "generator": f"{app.title} v{app.version}"}
            response = templates.TemplateResponse(
                request=request, name=template_name, context=context, media_type=media_type
            )
        case _:
            raise HTTPException(HTTP_406_NOT_ACCEPTABLE)

    response.headers["etag"] = etag
    return response


etag_handler = Etag(lambda r: str(r.state.dbfile_watcher.mtime))


def index_get(path: str, summary: str):
    return app.get(
        path,
        summary=summary,
        response_model=ProjectList,
        response_model_exclude_none=True,
    )


@index_get("/simple/", summary="Root Project Index")
@index_get("/{index}/simple/", summary="Namespace Project Index")
async def index(
    request: Request,
    media_type: Annotated[MediaType, Depends(get_response_media_type)],
    session: SessionDep,
    etag: Annotated[str, Depends(etag_handler)],
    index: str = "",
):
    project_list = get_project_list(index, session)

    if not project_list.projects:
        raise HTTPException(HTTP_404_NOT_FOUND, detail="Can't find this index")

    return get_response(request, project_list, media_type, etag, "index.html")


def detail_get(path: str, summary: str):
    return app.get(
        path,
        summary=summary,
        response_model=ProjectDetail,
        response_model_exclude_none=True,
        dependencies=[Depends(Etag(lambda r: str(r.state.dbfile_watcher.mtime)))],
    )


@detail_get("/simple/{project}/", summary="Root Project Detail")
@detail_get("/{index}/simple/{project}/", summary="Namespaced Project Detail")
async def project_detail(
    request: Request,
    media_type: Annotated[MediaType, Depends(get_response_media_type)],
    session: SessionDep,
    etag: Annotated[str, Depends(etag_handler)],
    project: str,
    index: str = "",
):
    project_canonical = canonicalize_name(project)
    if project != project_canonical:
        return RedirectResponse(
            url=request.url.path.replace(project, project_canonical),
            status_code=301,
        )

    project_details = get_project_detail(index, project_canonical, session)
    for project_file in project_details.files:
        project_file.url = str(request.url_for("files", path=project_file.url))

    if not project_details.files:
        raise HTTPException(HTTP_404_NOT_FOUND, detail="Can't find this project")

    return get_response(request, project_details, media_type, etag, "detail.html")


staticfiles = StaticFiles()
staticfiles.all_directories += [settings.base_dir, settings.cache_dir_]
app.mount(settings.files_url, staticfiles, name="files")


@app.get("/ping")
async def ping():
    return {}  # docker health-check
