from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent

import pytest
from fastapi.testclient import TestClient
from pypi_simple import PyPISimple

FILES_REQUIRED = [
    "pytest-8.3.4-py3-none-any.whl",
    "pytest-8.3.4.tar.gz",
    "iniconfig-2.0.0-py3-none-any.whl",
    "iniconfig-2.0.0.tar.gz",
    "packaging-24.2-py3-none-any.whl",
    "packaging-24.2.tar.gz",
    "pluggy-1.5.0-py3-none-any.whl",
    "pluggy-1.5.0.tar.gz",
    "ext/pytest-8.3.0-py3-none-any.whl",
    "ext/pytest-8.3.0.tar.gz",
    "ext/iniconfig-2.0.0-py3-none-any.whl",
    "ext/iniconfig-2.0.0.tar.gz",
    "ext/packaging-24.2-py3-none-any.whl",
    "ext/packaging-24.2.tar.gz",
    "ext/pluggy-1.5.0-py3-none-any.whl",
    "ext/pluggy-1.5.0.tar.gz",
    "ext/pydantic-2.10.6-py3-none-any.whl",
    "ext/pydantic-2.10.6.tar.gz",
    "ext/annotated_types-0.7.0-py3-none-any.whl",
    "ext/annotated_types-0.7.0.tar.gz",
    "ext/pydantic_core-2.27.2-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
    "ext/pydantic_core-2.27.2-cp312-cp312-win32.whl",
    "ext/pydantic_core-2.27.2.tar.gz",
    "ext/typing_extensions-4.12.2-py3-none-any.whl",
    "ext/typing_extensions-4.12.2.tar.gz",
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


@pytest.fixture(scope="session")
def client(test_files) -> Iterator[TestClient]:
    from pypi_simple_server.main import app

    with TestClient(app) as client:
        yield client


def test_ping(client: TestClient):
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {}


def test_root_index_html(client: TestClient):
    response = client.get("/simple/")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/vnd.pypi.simple.v1+html"
    expected = """
        <!DOCTYPE html>
        <html lang="en">

        <head>
            <meta charset="UTF-8" />
            <meta name="pypi:repository-version" content="1.1" />
            <meta name="generator" content="pypi_simple_server v0.0.1" />
            <title>Simple Python Package Index Server</title>
        </head>

        <body>
            <a href="annotated-types">annotated-types</a>
            <a href="iniconfig">iniconfig</a>
            <a href="packaging">packaging</a>
            <a href="pluggy">pluggy</a>
            <a href="pydantic">pydantic</a>
            <a href="pydantic-core">pydantic-core</a>
            <a href="pytest">pytest</a>
            <a href="typing-extensions">typing-extensions</a>
        </body>

        </html>
    """
    assert response.text == dedent(expected).strip()

def test_root_project_pytest_html(client: TestClient):
    response = client.get("/simple/pytest/")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/vnd.pypi.simple.v1+html"
    expected = """
        <!DOCTYPE html>
        <html lang="en">

        <head>
            <meta charset="UTF-8" />
            <meta name="pypi:repository-version" content="1.1" />
            <meta name="generator" content="pypi_simple_server v0.0.1" />
            <title>Links for pytest</title>
        </head>

        <body>
            <h1>Links for pytest</h1>
            <a href="http://testserver/files/pytest-8.3.4.tar.gz#sha256=965370d062bce11e73868e0335abac31b4d3de0e82f4007408d242b4f8610761" data-requires-python=">=3.8" data-core_metadata="sha256=7f9bf63bf3c20dd4fc7552a8b4708b887cd728c4d2f614ced98b0a43afcfde28">pytest-8.3.4.tar.gz</a><br />
            <a href="http://testserver/files/ext/pytest-8.3.0.tar.gz#sha256=0fe75465746a643f2485f642edf5eb7af7918135177230471150409343f84a6b" data-requires-python=">=3.8" data-core_metadata="sha256=200173d29293466681e0efbe47a2e11fc79ac279986fd58721b37202beab6101">pytest-8.3.0.tar.gz</a><br />
            <a href="http://testserver/files/pytest-8.3.4-py3-none-any.whl#sha256=50e16d954148559c9a74109af1eaf0c945ba2d8f30f0a3d3335edde19788b6f6" data-requires-python=">=3.8" data-core_metadata="sha256=7f9bf63bf3c20dd4fc7552a8b4708b887cd728c4d2f614ced98b0a43afcfde28">pytest-8.3.4-py3-none-any.whl</a><br />
            <a href="http://testserver/files/ext/pytest-8.3.0-py3-none-any.whl#sha256=a1b30492f2676b476266a87f6551345fb25c0484fb6d09c86aa2eb07b5f71c2f" data-requires-python=">=3.8" data-core_metadata="sha256=cdd29a47b9142b3a3d662c4fa4870139d0c213d3f3853406efc90775b09d06af">pytest-8.3.0-py3-none-any.whl</a><br />
        </body>

        </html>
    """
    print(response.text)
    assert response.text == dedent(expected).strip()


def test_root_index_json(client: TestClient):
    response = client.get("/simple/", headers={"Accept": "application/vnd.pypi.simple.latest+json"})
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/vnd.pypi.simple.v1+json"
    expected = {
        "meta": {"api_version": "1.1"},
        "projects": [
            {"name": "annotated-types"},
            {"name": "iniconfig"},
            {"name": "packaging"},
            {"name": "pluggy"},
            {"name": "pydantic"},
            {"name": "pydantic-core"},
            {"name": "pytest"},
            {"name": "typing-extensions"},
        ],
    }
    assert response.json() == expected
