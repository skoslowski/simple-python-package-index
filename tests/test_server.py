from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent

import pytest
from pypi_simple import PyPISimple
from starlette.status import HTTP_200_OK, HTTP_301_MOVED_PERMANENTLY, HTTP_404_NOT_FOUND
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


@pytest.fixture(scope="session")
def client(test_files) -> Iterator[TestClient]:
    from pypi_simple_server.main import app

    with TestClient(app, root_path="/pypi") as client:
        yield client


def test_ping(client: TestClient):
    response = client.get("/ping")
    assert response.status_code == HTTP_200_OK


def test_root_index_html(client: TestClient):
    response = client.get("/simple/")
    assert response.status_code == HTTP_200_OK
    assert response.headers.get("content-type") == "application/vnd.pypi.simple.v1+html"
    expected = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8" />
            <meta name="pypi:repository-version" content="1.1" />
            <title>Simple Index</title>
        </head>
        <body>
            <a href="iniconfig/">iniconfig</a>
            <a href="packaging/">packaging</a>
            <a href="pluggy/">pluggy</a>
            <a href="pytest/">pytest</a>
        </body>
        </html>
    """
    assert response.text == dedent(expected).strip()


def test_root_project_pytest_html(client: TestClient):
    response = client.get("/simple/pytest/")
    assert response.status_code == HTTP_200_OK
    assert response.headers.get("content-type") == "application/vnd.pypi.simple.v1+html"
    expected = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8" />
            <meta name="pypi:repository-version" content="1.1" />
            <title>Links for pytest</title>
        </head>
        <body>
            <h1>Links for pytest</h1>
            <a href="http://testserver/pypi/files/pytest-8.3.0-py3-none-any.whl#sha256=a1b30492f2676b476266a87f6551345fb25c0484fb6d09c86aa2eb07b5f71c2f" data-requires-python="&gt;=3.8" data-core_metadata="sha256=cdd29a47b9142b3a3d662c4fa4870139d0c213d3f3853406efc90775b09d06af">pytest-8.3.0-py3-none-any.whl</a><br />
            <a href="http://testserver/pypi/files/pytest-8.3.4-py3-none-any.whl#sha256=50e16d954148559c9a74109af1eaf0c945ba2d8f30f0a3d3335edde19788b6f6" data-requires-python="&gt;=3.8" data-core_metadata="sha256=7f9bf63bf3c20dd4fc7552a8b4708b887cd728c4d2f614ced98b0a43afcfde28">pytest-8.3.4-py3-none-any.whl</a><br />
            <a href="http://testserver/pypi/files/pytest-8.3.4.tar.gz#sha256=965370d062bce11e73868e0335abac31b4d3de0e82f4007408d242b4f8610761" data-requires-python="&gt;=3.8" data-core_metadata="sha256=7f9bf63bf3c20dd4fc7552a8b4708b887cd728c4d2f614ced98b0a43afcfde28">pytest-8.3.4.tar.gz</a><br />
        </body>
        </html>
    """
    assert response.text == dedent(expected).strip()


def test_root_index_json(client: TestClient):
    response = client.get("/simple/", headers={"Accept": "application/vnd.pypi.simple.latest+json"})
    assert response.status_code == HTTP_200_OK
    assert response.headers.get("content-type") == "application/vnd.pypi.simple.v1+json"
    expected = {
        "meta": {"api_version": "1.1"},
        "projects": [
            {"name": "iniconfig"},
            {"name": "packaging"},
            {"name": "pluggy"},
            {"name": "pytest"},
        ],
    }
    assert response.json() == expected
    assert response.headers.get("etag")


def test_root_project_pytest_json(client: TestClient):
    response = client.get("/simple/pytest/", headers={"Accept": "application/vnd.pypi.simple.latest+json"})
    assert response.status_code == HTTP_200_OK
    assert response.headers.get("content-type") == "application/vnd.pypi.simple.v1+json"
    expected = {
        "meta": {"api_version": "1.1"},
        "name": "pytest",
        "versions": ["8.3", "8.3.4"],
        "files": [
            {
                "filename": "pytest-8.3.0-py3-none-any.whl",
                "size": 341630,
                "url": "http://testserver/pypi/files/pytest-8.3.0-py3-none-any.whl",
                "hashes": {"sha256": "a1b30492f2676b476266a87f6551345fb25c0484fb6d09c86aa2eb07b5f71c2f"},
                "requires_python": ">=3.8",
                "core_metadata": {
                    "sha256": "cdd29a47b9142b3a3d662c4fa4870139d0c213d3f3853406efc90775b09d06af"
                },
            },
            {
                "filename": "pytest-8.3.4-py3-none-any.whl",
                "size": 343083,
                "url": "http://testserver/pypi/files/pytest-8.3.4-py3-none-any.whl",
                "hashes": {"sha256": "50e16d954148559c9a74109af1eaf0c945ba2d8f30f0a3d3335edde19788b6f6"},
                "requires_python": ">=3.8",
                "core_metadata": {
                    "sha256": "7f9bf63bf3c20dd4fc7552a8b4708b887cd728c4d2f614ced98b0a43afcfde28"
                },
            },
            {
                "filename": "pytest-8.3.4.tar.gz",
                "size": 1445919,
                "url": "http://testserver/pypi/files/pytest-8.3.4.tar.gz",
                "hashes": {"sha256": "965370d062bce11e73868e0335abac31b4d3de0e82f4007408d242b4f8610761"},
                "requires_python": ">=3.8",
                "core_metadata": {
                    "sha256": "7f9bf63bf3c20dd4fc7552a8b4708b887cd728c4d2f614ced98b0a43afcfde28"
                },
            },
        ],
    }
    assert response.json() == expected
    assert response.headers.get("etag")


def test_sub_index_json(client: TestClient):
    response = client.get("/ext/simple/", headers={"Accept": "application/vnd.pypi.simple.latest+json"})
    assert response.status_code == HTTP_200_OK

    projects = {p["name"] for p in response.json()["projects"]}
    assert projects == {"iniconfig", "pluggy", "pytest"}


@pytest.mark.parametrize("index", ["ex", "ext/foo"])
def test_missing_sub_index(client: TestClient, index: str):
    response = client.get("/{index}/simple/")
    assert response.status_code == HTTP_404_NOT_FOUND


def test_redirect_name(client: TestClient):
    response = client.get("/simple/PyTest/", follow_redirects=False)
    assert response.status_code == HTTP_301_MOVED_PERMANENTLY
    assert response.headers["Location"] == "/simple/pytest/"


def test_sub_project_pytest_json(client: TestClient):
    response = client.get(
        "/ext/simple/pytest/", headers={"Accept": "application/vnd.pypi.simple.latest+json"}
    )
    assert response.status_code == HTTP_200_OK

    files = {f["filename"] for f in response.json()["files"]}
    assert files == {"pytest-8.3.0-py3-none-any.whl"}
