import logging
import sys
from enum import StrEnum
from importlib import metadata
from pathlib import Path
from typing import Any

from furl import furl
from litestar import Controller, Litestar, Request, Response, Router, get
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.di import Provide
from litestar.response import File, Redirect, Template
from litestar.serialization import encode_json
from litestar.status_codes import HTTP_301_MOVED_PERMANENTLY, HTTP_404_NOT_FOUND, HTTP_406_NOT_ACCEPTABLE
from litestar.template.config import TemplateConfig
from packaging.utils import canonicalize_name
from pydantic import DirectoryPath
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import loader

GENERATOR = f"{__package__} v{metadata.version(__package__)}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PYPI_SERVER_")

    files_dir: DirectoryPath = Path.cwd()
    files_url: str = "/files"
    root_path: str = ""  # setting through uvicorn wouldn't allow us to pre-compute file urls


settings = Settings()
logger = logging.getLogger(__name__)


class PPSMediaType(StrEnum):
    JSON_V1 = "application/vnd.pypi.simple.v1+json"
    HTML_V1 = "application/vnd.pypi.simple.v1+html"


def get_response_type(request: Request) -> PPSMediaType | None:
    supported = {
        PPSMediaType.HTML_V1: PPSMediaType.HTML_V1,
        PPSMediaType.JSON_V1: PPSMediaType.JSON_V1,
        "application/vnd.pypi.simple.latest+json": PPSMediaType.JSON_V1,
        "application/vnd.pypi.simple.latest+html": PPSMediaType.HTML_V1,
    }
    if match := request.accept.best_match(list(supported)):
        return supported[match]
    return None


def _handle(request: Request, content: Any, template_name: str) -> Response:
    match get_response_type(request):
        case PPSMediaType.JSON_V1:
            return Response(encode_json(content), media_type=PPSMediaType.JSON_V1)
        case PPSMediaType.HTML_V1:
            context = {"content": content, "generator": GENERATOR}
            return Template(template_name, context=context, media_type=PPSMediaType.HTML_V1)
    return Response("No acceptable format found", status_code=HTTP_406_NOT_ACCEPTABLE)


# @get(["/simple/", "/{path:str}/simple/" "/{path:str}/{subpath:str}/simple/"], sync_to_thread=False)
# def project_list(request: Request, index_tree: loader.SimpleIndexTree, path: str = "") -> Response:
#     return Response(f"{path} {type(path)}")
#     try:
#         simple_index = index_tree[path]
#     except KeyError:
#         return Response("Project list can not be found", status_code=404)
#     return _handle(request, simple_index.project_list, "index.html")


class SimpleIndexView(Controller):
    path = "simple"

    @get("/", sync_to_thread=False)
    def index(
        self,
        request: Request,
        index_tree: loader.SimpleIndexTree,
        path: str = "",
        subpath: str = "",
    ) -> Response:
        try:
            simple_index = index_tree[f"{path}/{subpath}".strip("/") or "."]
        except KeyError:
            return Response("Project can not be found", status_code=HTTP_404_NOT_FOUND)

        return _handle(request, simple_index.project_list, "index.html")

    @get("{project_name:str}/", sync_to_thread=False)
    def project_detail(
        self, request: Request, project_name: str, simple_index: loader.SimpleIndex
    ) -> Response[loader.ProjectDetail | str]:
        name = canonicalize_name(project_name)
        if name != project_name:
            return Redirect(
                path=request.url.path.replace(project_name, name),
                status_code=HTTP_301_MOVED_PERMANENTLY,
            )

        try:
            project_details = simple_index[name]
        except KeyError:
            return Response("Project can not be found", status_code=HTTP_404_NOT_FOUND)

        return _handle(request, project_details, "details.html")


def get_path(file: Path) -> Path | None:
    if file.is_absolute():
        file = file.relative_to("/")
    files_dir = settings.files_dir.resolve()
    file_on_disk = files_dir.joinpath(file).resolve()
    if files_dir in file_on_disk.parents:
        return file_on_disk


@get("/files/{file:path}")
async def files(request: Request, file: Path, index_tree: loader.SimpleIndexTree) -> Response:
    if file.suffix == ".metadata" and (content := index_tree.meta_data(request.url.path)):
        return Response(content, media_type="binary/octet-stream")
    elif (filepath := get_path(file)) and filepath.is_file():
        return File(filepath)

    return Response("File not found", status_code=HTTP_404_NOT_FOUND)


@get("/ping")
async def ping() -> None:
    return  # docker health-check


def provide(obj: Any) -> Provide:
    provider = Provide(lambda: None, use_cache=True, sync_to_thread=True)
    provider.value = obj
    return provider


def main() -> Litestar:
    handler = logging.StreamHandler(sys.stderr)
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
    for name, index_ in sorted(index_tree.indexes()):
        logger.info((f"Index '{name}'" if name else "Root index") + f" with {len(index_.projects)} projects")

    app = Litestar(
        route_handlers=[ping],
        dependencies={"index_tree": provide(index_tree)},
        template_config=TemplateConfig(
            directory=Path(__file__).with_name("templates"),
            engine=JinjaTemplateEngine,
        ),
        debug=True,
    )
    app.register(Router(settings.files_url, route_handlers=[files]))

    for path in ["/", "/{path:str}/", "/{path:str}/{subpath:str}/"]:
        app.register(Router(path, route_handlers=[SimpleIndexView]))

    return app

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
