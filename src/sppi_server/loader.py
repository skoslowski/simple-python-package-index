import hashlib
import logging
import urllib.parse
from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from tarfile import TarFile
from zipfile import ZipFile

from natsort import natsorted
from packaging.metadata import parse_email
from packaging.utils import (
    NormalizedName,
    canonicalize_name,
    canonicalize_version,
    parse_sdist_filename,
    parse_wheel_filename,
)

from .model import ProjectDetail, ProjectFile, ProjectList, ProjectListEntry

logger = logging.getLogger()

RESERVED_COLLECTION_NAMES = {"files"}
RESERVED_PROJECT_NAMES = {"simple"}


@dataclass
class SimpleIndex:
    project_details: dict[NormalizedName, ProjectDetail] = field(default_factory=dict)

    @cached_property
    def project_list(self) -> ProjectList:
        return ProjectList(projects={ProjectListEntry(name=name) for name in natsorted(self.project_details)})


@dataclass
class SimpleIndexTree(Mapping[str, SimpleIndex]):
    files_dir: Path
    metadata_dir: Path
    files_url: str

    def __post_init__(self) -> None:
        self._indexes: dict[str, SimpleIndex] = {}
        if not self.files_url.endswith("/"):
            self.files_url += "/"

    def reload(self) -> None:
        indexes = defaultdict[str, SimpleIndex](SimpleIndex)

        for file in self.files_dir.rglob("*.*"):
            if not file.is_file():
                continue
            url = self.files_url + file.relative_to(self.files_dir).as_posix()
            try:
                file_info = _read_project_file(file, url)
            except ValueError as e:
                logger.error(e)
                continue

            parents = (c.as_posix() for c in file.relative_to(self.files_dir).parents[-3:])
            for index in (indexes[c if c != "." else ""] for c in parents):
                try:
                    details = index.project_details[file_info.project_name]
                except KeyError:
                    details = ProjectDetail(name=file_info.project_name)
                    index.project_details[file_info.project_name] = details
                details.files.add(file_info.distribution)
                details.versions.add(file_info.version)

            self._save_metadata_file(file, file_info.metadata)

        self._indexes = {n: i for n, i in indexes.items() if _check_collection_name(n)}

    def _save_metadata_file(self, dist: Path, metadata: bytes) -> None:
        path = self.metadata_dir / dist.parent.relative_to(self.files_dir)
        path.mkdir(parents=True, exist_ok=True)
        path.joinpath(f"{dist.name}.metadata").write_bytes(metadata)

    def __len__(self) -> int:
        return len(self._indexes)

    def __iter__(self) -> Iterator[str]:
        return iter(self._indexes)

    def __getitem__(self, key: str) -> SimpleIndex:
        return self._indexes[key]


@dataclass(slots=True)
class ProjectFileInfo:
    project_name: NormalizedName
    version: str
    distribution: ProjectFile
    metadata: bytes


def _read_project_file(file: Path, url: str) -> ProjectFileInfo:
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
        url=url,
        hashes=_get_file_hashes(file),
        requires_python=metadata.get("requires_python"),
        core_metadata={"sha256": hashlib.sha256(metadata_content).hexdigest()},
    )
    return ProjectFileInfo(
        project_name=canonicalize_name(metadata.get("name", name_from_file)),
        version=canonicalize_version(metadata.get("version", str(version_from_file))),
        distribution=distribution,
        metadata=metadata_content,
    )


def _check_collection_name(name: str) -> bool:
    if RESERVED_COLLECTION_NAMES.intersection(name.split("/")):
        logger.error("Ignoring collection '{collection_name}': reserved name")
        return False
    if name != urllib.parse.quote(name):
        logger.error("Ignoring collection '{collection_name}': characters with quoting")
        return False
    return True


def _get_file_hashes(filename: Path, blocksize: int = 2 << 13) -> dict[str, str]:
    hash_obj = hashlib.sha256()
    with open(filename, "rb") as fp:
        while fb := fp.read(blocksize):
            hash_obj.update(fb)
    return {hash_obj.name: hash_obj.hexdigest()}


def _get_wheel_metadata(file: Path) -> bytes:
    # https://packaging.python.org/en/latest/specifications/binary-distribution-format/
    distribution, version, _ = file.name.split("-", 2)
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
