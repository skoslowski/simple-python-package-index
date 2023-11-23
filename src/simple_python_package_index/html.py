from html import escape
from typing import TYPE_CHECKING

from airium import Airium
from furl import furl
from natsort import natsorted

from . import __version__

if TYPE_CHECKING:
    from .model import Details, Index, Meta


def generate_index(index: "Index", url: str = "") -> Airium:
    project_base = furl(url)
    page = Airium()
    page("<!DOCTYPE html>")
    with page.html(lang="en"):
        with page.head():
            get_meta_tags(page, index.meta)

            with page.title():
                page("Simple Package Repository")

        with page.body():
            for project in natsorted(index.projects, key=lambda p: p.name):
                with page.a(href=project_base / f"{project.name}/"):
                    page(project.name)
                page.br()

    return page


def generate_project_page(project: "Details") -> Airium:
    page = Airium()

    page("<!DOCTYPE html>")
    with page.html(lang="en"):
        with page.head():
            get_meta_tags(page, project.meta)
            with page.title():
                page(f"Links for {project.name}")

        with page.body():
            with page.h1():
                # Not part of the spec, but allowed
                page(f"Links for {project.name}")

            for dist in project.files:
                hash_name, hex_digest = next(iter(dist.hashes.items()))
                kwargs = {"href": f"{dist.url}#{hash_name}={hex_digest}"}

                if dist.requires_python is not None:
                    kwargs["data-requires-python"] = escape(dist.requires_python)

                if dist.yanked is not None:
                    kwargs["data-yanked"] = escape(dist.yanked)

                if dist.dist_info_metadata:
                    hash_name, hex_digest = next(iter(dist.dist_info_metadata.items()))
                    kwargs["data-dist-info-metadata"] = f"{hash_name}={hex_digest}"
                elif dist.dist_info_metadata is not None:
                    kwargs["data-dist-info-metadata"] = "true"

                with page.a(**kwargs):
                    page(dist.filename)
                page.br()

    return page


def get_meta_tags(page: Airium, meta_data: "Meta") -> None:
    page.meta(charset="UTF-8")
    page.meta(name="pypi:repository-version", content=meta_data.api_version)  # PEP-629

    # Not part of the spec, but allowed
    page.meta(name="generator", content=f"{__package__} v{__version__}")
