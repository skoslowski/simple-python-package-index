import hashlib
import logging
import os
from pathlib import Path
from tarfile import TarFile
from zipfile import ZipFile

from packaging.metadata import parse_email
from packaging.utils import (
    canonicalize_name,
    canonicalize_version,
    parse_sdist_filename,
    parse_wheel_filename,
)
from sqlmodel import Session, select

from .config import settings
from .database import Distribution, Index, get_one_or_create

logger = logging.getLogger(__name__)


class LoaderError(Exception):
    pass


class UnhandledFileTypeError(LoaderError):
    pass


class InvalidFileError(ValueError):
    pass


def read_project_metadata(file: Path) -> bytes:
    if file.suffix == ".whl":
        parse_wheel_filename(file.name)
        # https://packaging.python.org/en/latest/specifications/binary-distribution-format/
        distribution, version, _ = file.name.split("-", 2)
        subdir = f"{distribution}-{version}.dist-info"
        with ZipFile(file) as zip, zip.open(f"{subdir}/METADATA") as fp:
            return fp.read()

    elif file.suffixes[-2:] == [".tar", ".gz"]:
        parse_sdist_filename(file.name)
        # https://packaging.python.org/en/latest/specifications/source-distribution-format/
        subdir = file.name.removesuffix(".tar.gz")
        with TarFile.open(file) as tar_file:
            pkg_info = tar_file.extractfile(f"{subdir}/PKG-INFO")
            assert pkg_info
            with pkg_info as fp:
                return fp.read()

    raise UnhandledFileTypeError(f"Can't handle type {file.name}")


def _get_file_hashes(filename: Path, blocksize: int = 2 << 13) -> dict[str, str]:
    hash_obj = hashlib.sha256()
    with open(filename, "rb") as fp:
        while fb := fp.read(blocksize):
            hash_obj.update(fb)
    return {hash_obj.name: hash_obj.hexdigest()}


def _read_project_file(file: Path) -> Distribution:
    metadata_content = read_project_metadata(file)

    try:
        metadata, _ = parse_email(metadata_content)
        name = canonicalize_name(metadata["name"])  # type: ignore
        version = canonicalize_version(metadata["version"])  # type: ignore
    except Exception as e:
        raise InvalidFileError from e

    metadata_file = settings.cache_dir_.joinpath(file.relative_to(settings.base_dir)).with_name(
        file.name + ".metadata"
    )
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_file.write_bytes(metadata_content)
    file_stat = file.stat()
    os.utime(metadata_file, (file_stat.st_atime, file_stat.st_mtime))

    return Distribution(
        name=name,
        version=version,
        filename=file.name,
        size=file.stat().st_size,
        hashes=_get_file_hashes(file),
        requires_python=metadata.get("requires_python"),
        core_metadata={"sha256": hashlib.sha256(metadata_content).hexdigest()},
    )


def update_db(session: Session) -> set[Path]:
    added = set()

    for file in settings.base_dir.rglob("*.*"):
        index_name = Path("/").joinpath(file.relative_to(settings.base_dir)).parent.as_posix()
        index_name = index_name.strip("/") + "/"

        index, _ = get_one_or_create(
            session,
            select(Index).where(Index.name == index_name),
            lambda: Index(name=index_name),
        )

        try:

            def new_file():
                dist = _read_project_file(file)
                dist.index_id = index.id
                return dist

            dist, new = get_one_or_create(
                session,
                select(Distribution)
                .where(Distribution.index_id == index.id)
                .where(Distribution.filename == file.name),
                new_file,
            )
        except UnhandledFileTypeError:
            continue
        except InvalidFileError as e:
            logger.error(e)
            continue

        if new:
            added.add(file)
            print(index.name, dist.filename)

    session.commit()
    return added
