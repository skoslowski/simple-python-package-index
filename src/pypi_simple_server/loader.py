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
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlmodel import Session, select

from .config import settings
from .database import Distribution

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


def _read_project_file(file: Path, url: str) -> Distribution:
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
        url=url,
        hashes=_get_file_hashes(file),
        requires_python=metadata.get("requires_python"),
        core_metadata={"sha256": hashlib.sha256(metadata_content).hexdigest()},
    )


def update_db(session: Session) -> None:
    for file in settings.base_dir.rglob("*.*"):
        url = file.relative_to(settings.base_dir).as_posix()

        try:
            query = select(Distribution.id).where(Distribution.url == url)
            session.exec(query).one()
            continue
        except NoResultFound:
            pass

        try:
            dist = _read_project_file(file, url)
        except UnhandledFileTypeError:
            continue
        except InvalidFileError as e:
            logger.error(e)
            continue

        try:
            session.add(dist)
            session.commit()
        except IntegrityError:
            session.rollback()
