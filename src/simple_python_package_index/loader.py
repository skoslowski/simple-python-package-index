import hashlib
import logging
import urllib.parse
from collections import defaultdict
from collections.abc import ItemsView
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from tarfile import TarFile
from typing import Self
from zipfile import ZipFile

from furl import furl
from packaging.metadata import parse_email
from packaging.utils import (
    NormalizedName,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)

from .model import ProjectDetail, ProjectFile, ProjectList, ProjectListEntry

logger = logging.getLogger()

RESERVED_COLLECTION_NAMES = {"files"}
RESERVED_PROJECT_NAMES = {"simple"}


@dataclass
class FileExt:
    project_name: NormalizedName
    version: str
    distribution: ProjectFile
    collection: str

    metadata: bytes

    @classmethod
    def from_file(cls, file: Path, base: Path, base_url: furl) -> Self:
        if file.suffix == ".whl":
            name_from_file, version_from_file, *_ = parse_wheel_filename(file.name)
            metadata_content = _get_wheel_metadata(file)

        elif file.suffixes[-2:] == [".tar", ".gz"]:
            name_from_file, version_from_file = parse_sdist_filename(file.name)
            metadata_content = _get_sdist_metadata(file)

        else:
            raise ValueError(f"Can't handle type {file.name}")

        metadata, _ = parse_email(metadata_content)

        distribution = ProjectFile(
            filename=file.name,
            size=file.stat().st_size,
            url=str(base_url / file.relative_to(base).as_posix()),
            hashes=_get_file_hashes(file),
            requires_python=metadata.get("requires_python"),
            core_metadata={"sha256": hashlib.sha256(metadata_content).hexdigest()},
        )
        return cls(
            project_name=canonicalize_name(metadata.get("name", name_from_file)),
            version=metadata.get("version", str(version_from_file)),
            distribution=distribution,
            collection=file.relative_to(base).parent.as_posix(),
            metadata=metadata_content,
        )


@dataclass
class SimpleIndex:
    projects: dict[NormalizedName, ProjectDetail] = field(default_factory=dict)

    @cached_property
    def index(self) -> ProjectList:
        return ProjectList(projects={ProjectListEntry(name=name) for name in self.projects})

    def __getitem__(self, name: NormalizedName) -> ProjectDetail:
        return self.projects[name]

    def add_distribution(self, file: FileExt) -> None:
        try:
            project_details = self.projects[file.project_name]
        except KeyError:
            project_details = self.projects[file.project_name] = ProjectDetail(name=file.project_name)
        project_details.files.add(file.distribution)
        project_details.versions.add(file.version)


@dataclass
class SimpleIndexTree:
    def __init__(self, data_dir: Path, url: str) -> None:
        self.data_dir = data_dir
        self.url = furl(url)

        self._indexes: dict[str, SimpleIndex] = {}
        self._metadata: dict[str, bytes] = {}

    def reload(self) -> None:
        indexes = defaultdict(SimpleIndex)

        for entry in self.data_dir.rglob("*.*"):
            try:
                file = FileExt.from_file(entry, self.data_dir, self.url)
            except ValueError as e:
                logger.error(e)
                continue

            collections = (
                name
                for c in entry.relative_to(self.data_dir).parents
                if _check_collection_name(name := c.as_posix())
            )
            for collection in collections:
                indexes[collection].add_distribution(file)

            self._metadata[f"{file.distribution.url}.metadata"] = file.metadata

        self._indexes.clear()
        self._indexes.update(indexes)

    def __getitem__(self, key: str) -> SimpleIndex:
        return self._indexes[key]

    def indexes(self) -> ItemsView[str, SimpleIndex]:
        return self._indexes.items()

    def meta_data(self, url: str) -> bytes | None:
        return self._metadata.get(url)


def _check_collection_name(name: str) -> bool:
    if name in RESERVED_COLLECTION_NAMES:
        logger.error("Ignoring collection '{collection_name}': reserved name")
        return False
    if name != urllib.parse.quote(name):
        logger.error("Ignoring collection '{collection_name}': characters with quoting")
        return False
    return True


def _get_file_hashes(filename: Path, blocksize: int = 1 << 20) -> dict[str, str]:
    hash_obj = hashlib.sha256()
    with open(filename, "rb") as fp:
        while fb := fp.read(blocksize):
            hash_obj.update(fb)
    return {hash_obj.name: hash_obj.hexdigest()}


def _get_wheel_metadata(file: Path) -> bytes:
    # https://packaging.python.org/en/latest/specifications/binary-distribution-format/
    distribution, version = file.name.split("-", 2)[:-1]
    subdir = f"{distribution}-{version}.dist-info"
    with ZipFile(file) as zip, zip.open(f"{subdir}/METADATA") as fp:
        return fp.read()


def _get_sdist_metadata(file: Path) -> bytes:
    # https://packaging.python.org/en/latest/specifications/source-distribution-format/
    subdir = file.name.removesuffix(".tar.gz")
    with TarFile.open(file) as tar_file:
        pkg_info = tar_file.extractfile(f"{subdir}/PKG-INFO")
        assert pkg_info
        with pkg_info as fp:
            return fp.read()

def open_metadata(file: Path) -> bytes | None:
    if file.suffix == ".whl":
        return _get_wheel_metadata(file)
    if file.suffixes[-2:] == [".tar", ".gz"]:
        return _get_sdist_metadata(file)
