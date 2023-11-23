import hashlib
import logging
import urllib.parse
from collections import defaultdict
from collections.abc import ItemsView
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from tarfile import TarFile
from zipfile import ZipFile

from furl import furl
from packaging.metadata import parse_email
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    NormalizedName,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)

from .model import Details, File, Index, Project

logger = logging.getLogger()

RESERVED_COLLECTION_NAMES = {"files"}
RESERVED_PROJECT_NAMES = {"simple"}


@dataclass
class SimpleIndex:
    projects: dict[NormalizedName, Details] = field(default_factory=dict)

    metadata: dict[str, bytes] = field(default_factory=dict)

    @cached_property
    def index(self) -> Index:
        return Index(projects={Project(name=name) for name in self.projects})

    def __getitem__(self, name: NormalizedName) -> Details:
        return self.projects[name]

    def add_file(self, file: File, project_name: str) -> None:
        name = canonicalize_name(project_name)
        project_details = self.projects.setdefault(name, Details(name=name))
        project_details.files.add(file)
        project_details.versions.add(file.version_)

    def add_dist(self, file: Path, url: str):
        if file.suffix == ".whl":
            # print(f"wheel {file.name}")
            try:
                name_from_file, version_from_file, *_ = parse_wheel_filename(file.name)
            except InvalidWheelFilename as e:
                logger.error(e)
                return

            metadata_content = _get_wheel_metadata(file)

        elif file.suffixes[-2:] == [".tar", ".gz"]:
            # print(f"sdist {file.name}")
            try:
                name_from_file, version_from_file = parse_sdist_filename(file.name)
            except InvalidSdistFilename as e:
                logger.error(e)
                return

            metadata_content = _get_sdist_metadata(file)

        else:
            print(f"ignoring {file.name}")
            return

        metadata, _ = parse_email(metadata_content)
        project_name = metadata.get("name", name_from_file)
        version = metadata.get("version", str(version_from_file))

        distribution = File(
            filename=file.name,
            size=file.stat().st_size,
            url=url,
            hashes=_get_file_hashes(file),
            requires_python=metadata.get("requires_python"),
            version_=version,
            dist_info_metadata={"sha256": hashlib.sha256(metadata_content).hexdigest()},
        )
        self.add_file(distribution, project_name)
        self.metadata[f"{url}.metadata"] = metadata_content


@dataclass
class SimpleIndexCollection:
    def __init__(self, data_dir: Path, url: str) -> None:
        self.data_dir = data_dir
        self.url = furl(url)

        self._indexes: dict[str, SimpleIndex] = {}

    def reload(self) -> None:
        indexes = defaultdict(SimpleIndex)

        for entry in self.data_dir.glob("*"):
            if entry.is_dir():
                if not self._check_collection_name(entry.name):
                    continue
                for file in entry.glob("*.*"):
                    indexes[entry.name].add_dist(file, self._get_file_url(file))
            else:
                indexes[""].add_dist(entry, self._get_file_url(entry))

        self._merge_all_indexes_into_root(indexes)
        self._indexes.clear()
        self._indexes.update(indexes)

    def _merge_all_indexes_into_root(self, indexes: dict[str, SimpleIndex]) -> None:
        base_index = indexes[""]
        for simple_index in indexes.values():
            if simple_index is base_index:
                continue
            for project_name, project_details in simple_index.projects.items():
                for distribution in project_details.files:
                    base_index.add_file(distribution, project_name)
                base_index.metadata.update(simple_index.metadata)

    def _check_collection_name(self, name: str) -> bool:
        if name in RESERVED_COLLECTION_NAMES:
            logger.error("Ignoring collection '{collection_name}': reserved name")
            return False
        if name != urllib.parse.quote(name):
            logger.error("Ignoring collection '{collection_name}': characters with quoting")
            return False
        return True

    def _get_file_url(self, file: Path) -> str:
        return str(self.url / file.relative_to(self.data_dir).as_posix())

    def __getitem__(self, key: str) -> SimpleIndex:
        return self._indexes[key]

    def indexes(self) -> ItemsView[str, SimpleIndex]:
        return self._indexes.items()

    def get_meta_data(self, url: str) -> bytes | None:
        for project_index in self._indexes.values():
            if value := project_index.metadata.get(url):
                return value
        return None


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
