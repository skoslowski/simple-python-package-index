import pytest
from starlette.status import HTTP_200_OK, HTTP_301_MOVED_PERMANENTLY, HTTP_404_NOT_FOUND
from starlette.testclient import TestClient


def test_redirect_url(client: TestClient):
    response = client.get("/simple", follow_redirects=False)
    assert response.is_redirect


def test_redirect_name(client: TestClient):
    response = client.get("/simple/PyTest/", follow_redirects=False)
    assert response.status_code == HTTP_301_MOVED_PERMANENTLY
    assert response.headers["Location"] == "/simple/pytest/"


def test_root_index(client: TestClient):
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


def test_root_project_pytest(client: TestClient):
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


def test_sub_index(client: TestClient):
    response = client.get("/ext/simple/", headers={"Accept": "application/vnd.pypi.simple.latest+json"})
    assert response.status_code == HTTP_200_OK

    projects = {p["name"] for p in response.json()["projects"]}
    assert projects == {"iniconfig", "pluggy", "pytest"}


@pytest.mark.parametrize("index", ["ex", "ext/foo"])
def test_missing_sub_index(client: TestClient, index: str):
    response = client.get("/{index}/simple/")
    assert response.status_code == HTTP_404_NOT_FOUND


def test_sub_project_pytest(client: TestClient):
    response = client.get(
        "/ext/simple/pytest/", headers={"Accept": "application/vnd.pypi.simple.latest+json"}
    )
    assert response.status_code == HTTP_200_OK

    files = {f["filename"] for f in response.json()["files"]}
    assert files == {"pytest-8.3.0-py3-none-any.whl"}
