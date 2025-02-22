from collections.abc import Iterator
from pathlib import Path

import pytest
from pypi_simple import PyPISimple
from starlette.testclient import TestClient

FILES_REQUIRED = [
    "pytest-8.3.4-py3-none-any.whl",
    "pytest-8.3.4.tar.gz",
    "pytest-8.3.0-py3-none-any.whl",
    "iniconfig-2.0.0-py3-none-any.whl",
    "iniconfig-2.0.0.tar.gz",
    "packaging-24.2-py3-none-any.whl",
    "packaging-24.2.tar.gz",
    "ext/pytest-8.3.0-py3-none-any.whl",
    "ext/iniconfig-2.0.0-py3-none-any.whl",
    "ext/pluggy-1.5.0-py3-none-any.whl",
    "ext/pluggy-1.5.0.tar.gz",
]

FILES_DIR = Path(__file__).with_name("files")


def download(files_missing: dict[str, list[Path]]) -> None:
    with PyPISimple() as client:
        for project, files in files_missing.items():
            page = client.get_project_page(project)
            packages = {package.filename: package for package in page.packages}
            for file in files:
                if file.exists():
                    continue
                print(f"Downloading {file.name}")
                client.download_package(packages[file.name], path=file)


@pytest.fixture(scope="session")
def test_files():
    files_missing = {}
    for entry in FILES_REQUIRED:
        file = FILES_DIR / entry
        if file.exists():
            continue
        project = file.name.partition("-")[0]
        files_missing.setdefault(project, []).append(FILES_DIR / file)
    if files_missing:
        download(files_missing)
    FILES_DIR.joinpath("not-a-dist.txt").touch()
    FILES_DIR.joinpath("invalid-dist.tar.gz").touch()


@pytest.fixture(scope="session")
def client(test_files, tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    from pypi_simple_server import config

    config.CACHE_DIR, orig = tmp_path_factory.mktemp("cache_dir"), config.CACHE_DIR

    from pypi_simple_server.main import app

    with TestClient(app, root_path="/pypi") as client:
        yield client

    config.CACHE_DIR = orig
