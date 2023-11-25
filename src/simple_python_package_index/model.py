from typing import Annotated

from msgspec import Meta as M
from msgspec import Struct
from packaging.utils import NormalizedName

# https://peps.python.org/pep-0508/#names
ProjectName = Annotated[str, M(pattern=r"^([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9])$")]
NormalizedProjectName = Annotated[NormalizedName, M(pattern=r"^([0-9a-z]+-)*[0-9a-z]+$")]


class Meta(Struct, frozen=True):
    # api_version: str = "1.0"  # PEP-629
    api_version: str = "1.1"  # PEP-700


class File(Struct, omit_defaults=True):
    # PEP-503
    filename: str
    # PEP-700
    size: int
    url: str  # HttpUrl
    # Limited to a len() of 1 in HTML
    hashes: dict[str, str]
    gpg_sig: bool | None = None
    requires_python: str | None = None
    # PEP-592
    yanked: str | None = None
    # PEP-658
    dist_info_metadata: dict[str, str] | None = None

    def __hash__(self) -> int:
        return hash(self.filename)


# Simple Detail page (/simple/$PROJECT/)
class Details(Struct, kw_only=True):
    # PEP-629
    meta: Meta = Meta()

    # PEP-691
    name: NormalizedProjectName

    # PEP-700
    versions: set[str] = set()

    # PEP-503
    files: set[File] = set()

    def __hash__(self) -> int:
        return hash(self.name)


class Project(Struct):
    # PEP-691
    name: ProjectName  # may be normalized

    def __hash__(self) -> int:
        return hash(self.name)


# Simple Index page (/simple/)
class Index(Struct):
    # PEP-629
    meta: Meta = Meta()
    # PEP-503
    projects: set[Project] = set()
