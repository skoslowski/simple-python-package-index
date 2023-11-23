import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from furl import furl
from packaging.utils import canonicalize_name
from pydantic import DirectoryPath
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import __version__, html, loader, model


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PYPI_SERVER_")

    files_dir: DirectoryPath = Path.cwd()
    files_url: str = "/files"
    root_path: str = ""  # setting through uvicorn wouldn't allow us to pre-compute file urls


settings = Settings()
logger = logging.getLogger(__name__)

index_data = loader.SimpleIndexCollection(
    data_dir=settings.files_dir,
    url=str(furl(settings.root_path) / settings.files_url),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("Wheels files are searched in %s", settings.files_dir)
    logger.info("Root path is %s", settings.root_path)

    index_data.reload()
    for name, index in sorted(index_data.indexes()):
        name = f"Index '{name}'" if name else "Root index"
        logger.info(
            f"{name} with {len(index.projects)} projects and {len(index.metadata)} distributions"
        )

    yield

app = FastAPI(
    name=__package__,
    version=__version__,
    root_path=settings.root_path,
    lifespan=lifespan,
)


class PyPISimpleV1JSONResponse(JSONResponse):
    media_type = "application/vnd.pypi.simple.v1+json"
    acceptable_types = {media_type, "application/vnd.pypi.simple.latest+json"}


class PyPISimpleV1HTMLResponse(HTMLResponse):
    media_type = "application/vnd.pypi.simple.v1+html"
    acceptable_types = {
        media_type,
        "application/vnd.pypi.simple.latest+html",
        "text/html",
        "*/*",
    }


class NotAcceptableResponse(HTMLResponse):
    def __init__(self) -> None:
        super().__init__(status_code=406)


def content_negotiation(request: Request) -> type[Response]:
    accept = set(request.headers.get("accept", "*/*").split(","))
    for cls in (PyPISimpleV1JSONResponse, PyPISimpleV1HTMLResponse):
        if cls.acceptable_types & accept:
            return cls
    return NotAcceptableResponse


@app.get(
    "/simple/",
    response_class=PyPISimpleV1JSONResponse,
    response_model=model.Index,
    response_model_exclude_none=True,
)
@app.get(
    "/{collection}/simple/",
    response_class=PyPISimpleV1JSONResponse,
    response_model=model.Index,
    response_model_exclude_none=True,
)
def index(request: Request, collection: str = ""):
    response_type = content_negotiation(request)
    if response_type is NotAcceptableResponse:
        return NotAcceptableResponse()

    index = index_data[collection].index
    if response_type is PyPISimpleV1HTMLResponse:
        return PyPISimpleV1HTMLResponse(str(html.generate_index(index, request.url.path)))

    return index


@app.get(
    "/simple/{project_name}/",
    response_class=PyPISimpleV1JSONResponse,
    response_model=model.Details,
    response_model_exclude_none=True,
)
@app.get(
    "/{collection}/simple/{project_name}/",
    response_class=PyPISimpleV1JSONResponse,
    response_model=model.Details,
    response_model_exclude_none=True,
)
def project_detail(request: Request, project_name: str, collection: str = ""):
    name = canonicalize_name(project_name)
    if name != project_name:
        return RedirectResponse(
            url=request.url.path.replace(project_name, name),
            status_code=301,
        )

    response_type = content_negotiation(request)
    if response_type is NotAcceptableResponse:
        return NotAcceptableResponse()

    try:
        project_details = index_data[collection][name]
    except KeyError:
        return HTMLResponse("Can't find this project", status_code=404)

    if response_type is PyPISimpleV1HTMLResponse:
        content = str(html.generate_project_page(project_details))
        return PyPISimpleV1HTMLResponse(content)

    return project_details


def get_path(file: Path) -> Path | None:
    if file.is_absolute():
        file = file.relative_to("/")
    file_on_disk = settings.files_dir.joinpath(file).resolve()
    if settings.files_dir in file_on_disk.parents:
        return file_on_disk


@app.get(settings.files_url + "/{file:path}")
def files(request: Request, file: Path):
    if file.suffix == ".metadata" and (content := index_data.get_meta_data(request.url.path)):
        return PlainTextResponse(
            content, headers={"Content-Disposition": f"attachment; filename={file.name}"}
        )
    elif (filepath := get_path(file)) and filepath.is_file():
        return FileResponse(filepath)

    return HTMLResponse(status_code=404)


@app.get("/ping")
async def ping():
    return {}  # docker health-check
