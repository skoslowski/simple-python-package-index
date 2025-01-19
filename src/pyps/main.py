from enum import StrEnum
import logging
from pathlib import Path
from typing import Annotated, Any, Final

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import HTTPException
from fastapi.params import Depends
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from starlette.status import HTTP_404_NOT_FOUND, HTTP_406_NOT_ACCEPTABLE
from fastapi.templating import Jinja2Templates
from packaging.utils import canonicalize_name
from pydantic import DirectoryPath
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import __version__, loader
from .models import ProjectList, ProjectDetail
from .templates import jinja_env


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PYPS_", env_file=".env")

    files_dir: DirectoryPath = Path.cwd()
    metadata_dir: Path = Path.cwd()
    files_url: str = "/files"
    root_path: str = ""  # setting through uvicorn wouldn't allow us to pre-compute file urls


settings = Settings()
app = FastAPI(title=__package__ or "", version=__version__, root_path=settings.root_path)
logger = logging.getLogger(__name__)
templates = Jinja2Templates(env=jinja_env)


GENERATOR: Final = f"{app.title} v{app.version}"

index_data = loader.SimpleIndexTree(
    files_dir=settings.files_dir,
    metadata_dir=settings.metadata_dir,
    files_url=f"{settings.root_path}/{settings.files_url}".replace("//", "/"),
)


@app.on_event("startup")
def startup_event():
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("Wheels files are searched in %s", settings.files_dir)
    logger.info("Root path is %s", settings.root_path)

    result = reload_index_data()
    for name, stats in result["stats"].items():
        name = f"Index '{name}'" if name else "Root index"
        logger.info(
            f"{name} with {stats['projects']} projects and " f"{stats['distributions']} distributions"
        )


@app.get("/reload")
def reload_index_data():
    index_data.reload()
    return {
        "stats": {
            name: {
                "projects": len(index.project_details),
                "distributions": sum(len(d.files) for d in index.project_details.values()),
            }
            for name, index in sorted(index_data.indexes.items())
        }
    }


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


def get_response(request: Request, model: Any, media_type: MediaType, template_name: str) -> Response:
    match media_type:
        case MediaType.JSON_V1:
            return SimpleV1JSONResponse(model)
        case MediaType.HTML_V1:
            context = {"model": model, "generator": GENERATOR}
            return templates.TemplateResponse(
                request=request, name=template_name, context=context, media_type=media_type
            )

    raise HTTPException(HTTP_406_NOT_ACCEPTABLE)


@app.get(
    "/simple/",
    summary="Root Project Index",
    response_class=SimpleV1JSONResponse,
    response_model=ProjectList,
    response_model_exclude_none=True,
)
@app.get(
    "/{collection}/simple/",
    summary="Collection Project Index",
    response_class=SimpleV1JSONResponse,
    response_model=ProjectList,
    response_model_exclude_none=True,
)
async def index(
    request: Request,
    media_type: Annotated[MediaType, Depends(get_response_media_type)],
    collection: str = "",
):
    project_list = index_data.indexes[collection].project_list
    return get_response(request, project_list, media_type, "index.html")


@app.get(
    "/simple/{project_name}/",
    summary="Root Project Detail",
    response_class=SimpleV1JSONResponse,
    response_model=ProjectDetail,
    response_model_exclude_none=True,
)
@app.get(
    "/{collection}/simple/{project_name}/",
    summary="Collection Project Detail",
    response_class=SimpleV1JSONResponse,
    response_model=ProjectDetail,
    response_model_exclude_none=True,
)
async def project_detail(
    request: Request,
    media_type: Annotated[MediaType, Depends(get_response_media_type)],
    project_name: str,
    collection: str = "",
):
    name = canonicalize_name(project_name)
    if name != project_name:
        return RedirectResponse(
            url=request.url.path.replace(project_name, name),
            status_code=301,
        )

    try:
        project_details = index_data.indexes[collection].project_details[name]
    except KeyError:
        raise HTTPException(HTTP_404_NOT_FOUND, detail="Can't find this project")

    return get_response(request, project_details, media_type, "detail.html")


def get_path(file: Path) -> Path | None:
    if file.is_absolute():
        file = file.relative_to("/")
    file_on_disk = settings.files_dir.joinpath(file).resolve()
    if settings.files_dir in file_on_disk.parents:
        return file_on_disk
    return None


@app.get(settings.files_url + "/{file:path}")
def files(request: Request, file: Path):
    if file.suffix == ".metadata" and (content := index_data.get_meta_data(request.url.path)):
        return PlainTextResponse(
            content, headers={"Content-Disposition": f"attachment; filename={file.name}"}
        )
    elif (filepath := get_path(file)) and filepath.is_file():
        return FileResponse(filepath)

    raise HTTPException(404)


@app.get("/ping")
async def ping():
    return {}  # docker health-check
