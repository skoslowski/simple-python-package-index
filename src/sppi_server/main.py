import logging
import os
import sys
from enum import StrEnum
from importlib import metadata
from pathlib import Path
from typing import Any

from litestar import Controller, Litestar, Request, Response, Router, get
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.di import Provide
from litestar.response import Redirect, Template
from litestar.static_files import create_static_files_router
from litestar.status_codes import HTTP_301_MOVED_PERMANENTLY, HTTP_404_NOT_FOUND, HTTP_406_NOT_ACCEPTABLE
from litestar.template.config import TemplateConfig
from packaging.utils import canonicalize_name

from .loader import SimpleIndex, SimpleIndexTree

GENERATOR = f"{__package__} v{metadata.version(__package__ or "")}"
FILES_DIR = Path(os.getenv("SPPI_FILES_DIR", ".")).absolute()
CACHE_DIR = Path(os.getenv("SPPI_CACHE_DIR", ".")).absolute()

logger = logging.getLogger(__name__)


class MediaType(StrEnum):
    JSON_V1 = "application/vnd.pypi.simple.v1+json"
    HTML_V1 = "application/vnd.pypi.simple.v1+html"


def get_response_type(request: Request) -> MediaType | None:
    supported = {
        MediaType.HTML_V1: MediaType.HTML_V1,
        MediaType.JSON_V1: MediaType.JSON_V1,
        "application/vnd.pypi.simple.latest+json": MediaType.JSON_V1,
        "application/vnd.pypi.simple.latest+html": MediaType.HTML_V1,
    }
    if match := request.accept.best_match(list(supported)):
        return supported[match]
    return None


def get_response(request: Request, content: Any, template_name: str) -> Response:
    match get_response_type(request):
        case MediaType.JSON_V1:
            return Response(content, media_type=MediaType.JSON_V1)
        case MediaType.HTML_V1:
            context = {"content": content, "generator": GENERATOR}
            return Template(template_name, context=context, media_type=MediaType.HTML_V1)
    return Response("No acceptable format found", status_code=HTTP_406_NOT_ACCEPTABLE)


class SimpleIndexView(Controller):
    path = "simple"

    @get("/", sync_to_thread=False)
    def index(self, request: Request, simple_index: SimpleIndex | None) -> Response:
        if not simple_index:
            return Response("Index can not be found", status_code=HTTP_404_NOT_FOUND)
        return get_response(request, simple_index.project_list, "index.html")

    @get("{project_name:str}/", sync_to_thread=False)
    def project_detail(
        self,
        request: Request,
        project_name: str,
        simple_index: SimpleIndex | None,
    ) -> Response:
        name = canonicalize_name(project_name)
        if name != project_name:
            path = request.url.path.replace(project_name, name)
            return Redirect(path, status_code=HTTP_301_MOVED_PERMANENTLY)

        try:
            if not simple_index:
                raise KeyError
            project_details = simple_index.project_details[name]
        except KeyError:
            return Response("Project can not be found", status_code=HTTP_404_NOT_FOUND)

        return get_response(request, project_details, "details.html")


@get("/ping")
async def ping() -> None:
    return  # docker health-check


@get("/reload")
async def reload(index_tree: SimpleIndexTree) -> None:
    index_tree.reload()


def get_project_list(index_tree: SimpleIndexTree, path: str = "", subpath: str = "") -> SimpleIndex | None:
    return index_tree.get(f"{path}/{subpath}".strip("/"))


def get_index_tree(request: Request) -> SimpleIndexTree:
    index_tree = SimpleIndexTree(
        files_dir=FILES_DIR,
        metadata_dir=CACHE_DIR,
        files_url=request.url_for("files", file_path="/"),  # includes root_path
    )
    index_tree.reload()
    for name, index_ in sorted(index_tree.items()):
        name = f"Index '{name}'" if name else "Root index"
        logger.info(f"{name} with {len(index_.project_details)} projects")

    return index_tree


def main() -> Litestar:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    files = create_static_files_router(
        path="/files",
        directories=[FILES_DIR, CACHE_DIR],
        name="files",
    )
    app = Litestar(
        route_handlers=[
            ping,
            files,
            reload,
        ],
        dependencies={
            "index_tree": Provide(get_index_tree, use_cache=True, sync_to_thread=True),
        },
        template_config=TemplateConfig(
            directory=Path(__file__).with_name("templates"),
            engine=JinjaTemplateEngine,
        ),
        debug=True,
    )

    for path in ["/", "/{path:str}/", "/{path:str}/{subpath:str}/"]:
        router = Router(
            path,
            route_handlers=[SimpleIndexView],
            dependencies={"simple_index": Provide(get_project_list, sync_to_thread=True)},
        )
        app.register(router)

    return app


app = main()
