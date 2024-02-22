import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

from furl import furl
from litestar import Controller, Litestar, MediaType, Request, Response, Router, get
from litestar.di import Provide
from litestar.response import File, Redirect
from litestar.serialization import default_serializer
from litestar.types import Serializer
from packaging.utils import canonicalize_name
from pydantic import DirectoryPath
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import html, loader


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PYPI_SERVER_")

    files_dir: DirectoryPath = Path.cwd()
    files_url: str = "/files"
    root_path: str = ""  # setting through uvicorn wouldn't allow us to pre-compute file urls


settings = Settings()
logger = logging.getLogger(__name__)


class PyPISimpleResponse[T](Response[T]):
    def render(self, content: Any, media_type: str, enc_hook: Serializer = default_serializer) -> bytes:
        media_type = {"json": MediaType.JSON, "html": MediaType.HTML}.get(
            media_type.rpartition("+")[-1], media_type
        )
        return super().render(content, media_type, enc_hook)


class PPSMediaType(StrEnum):
    JSON_V1 = "application/vnd.pypi.simple.v1+json"
    HTML_V1 = "application/vnd.pypi.simple.v1+html"


def get_response_type(request: Request) -> PPSMediaType | None:
    html = {
        PPSMediaType.HTML_V1,
        "application/vnd.pypi.simple.latest+html",
        MediaType.HTML,
    }
    if html.intersection(request.accept):
        return PPSMediaType.HTML_V1

    json = {
        PPSMediaType.JSON_V1,
        "application/vnd.pypi.simple.latest+json",
    }
    if json.intersection(request.accept):
        return PPSMediaType.JSON_V1


class SimpleIndexView(Controller):
    path = "simple"

    @get("/", sync_to_thread=False)
    def index(self, request: Request, simple_index: loader.SimpleIndex) -> Response[loader.Index | str]:
        media_type = get_response_type(request)
        match media_type:
            case PPSMediaType.JSON_V1:
                content = simple_index.index
            case PPSMediaType.HTML_V1:
                content = str(html.generate_index(simple_index.index, request.url.path))
            case _:
                return Response("No acceptable format found", status_code=406)

        return PyPISimpleResponse(content=content, media_type=media_type)

    @get("{project_name:str}/", sync_to_thread=False)
    def project_detail(
        self, request: Request, project_name: str, simple_index: loader.SimpleIndex
    ) -> Response[loader.Details | str]:
        name = canonicalize_name(project_name)
        if name != project_name:
            return Redirect(path=request.url.path.replace(project_name, name), status_code=301)

        try:
            project_details = simple_index[name]
        except KeyError:
            return Response("Project can not be found", status_code=404)

        media_type = get_response_type(request)
        match media_type:
            case PPSMediaType.JSON_V1:
                content = project_details
            case PPSMediaType.HTML_V1:
                content = str(html.generate_project_page(project_details))
            case _:
                return Response("No acceptable format found", status_code=406)

        return PyPISimpleResponse(content=content, media_type=media_type)


def get_path(file: Path) -> Path | None:
    if file.is_absolute():
        file = file.relative_to("/")
    files_dir = settings.files_dir.resolve()
    file_on_disk = files_dir.joinpath(file).resolve()
    if files_dir in file_on_disk.parents:
        return file_on_disk


@get("/{file:path}")
async def files(request: Request, file: Path, index_tree: loader.SimpleIndexTree) -> Response:
    if file.suffix == ".metadata" and (content := index_tree.meta_data(request.url.path)):
        return Response(content, media_type="binary/octet-stream")
    elif (filepath := get_path(file)) and filepath.is_file():
        return File(filepath)

    return Response("File not found", status_code=404)


@get("/ping")
async def ping() -> None:
    return  # docker health-check


def provide(obj: Any) -> Provide:
    provider = Provide(lambda: None, use_cache=True, sync_to_thread=True)
    provider.value = obj
    return provider


def main() -> Litestar:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("Wheels files are searched in %s", settings.files_dir)
    logger.info("Root path is %s", settings.root_path)

    index_tree = loader.SimpleIndexTree(
        data_dir=settings.files_dir,
        url=str(furl(settings.root_path) / settings.files_url),
    )
    index_tree.reload()

    app = Litestar(
        route_handlers=[ping, files],
        dependencies={"index_tree": provide(index_tree)},
        debug=True,
    )
    app.register(Router(settings.files_url, route_handlers=[files]))

    for name, index_ in sorted(index_tree.indexes()):
        logger.info((f"Index '{name}'" if name else "Root index") + f" with {len(index_.projects)} projects")

        router = Router(
            name if name != "." else "",
            route_handlers=[SimpleIndexView],
            dependencies={"simple_index": provide(index_)},
        )
        app.register(router)

    return app


app = main()
