from typing import Annotated

from packaging.utils import NormalizedName
from pydantic import BaseModel, Field

# https://peps.python.org/pep-0508/#names
ProjectName = Annotated[
    str, Field(pattern=r"^([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9])$")
]
NormalizedProjectName = Annotated[NormalizedName, Field(pattern=r"^([0-9a-z]+-)*[0-9a-z]+$")]


class Meta(BaseModel):
    # api_version: str = "1.0"  # PEP-629
    api_version: str = "1.1"  # PEP-700


class ProjectFile(BaseModel):
    # PEP-503
    filename: str
    # PEP-700
    size: int
    # PEP-503
    url: str  # HttpUrl
    # Limited to a len() of 1 in HTML
    hashes: dict[str, str]
    # not used here
    gpg_sig: bool | None = None
    # PEP-503 (updated)
    requires_python: str | None = None
    # PEP-592
    yanked: str | None = None
    # PEP-658, renamed from dist_info_metadata in PEP-714
    core_metadata: dict[str, str] | None = None


# Simple Detail page (/simple/$PROJECT/)
class ProjectDetail[File](BaseModel):
    # PEP-629
    meta: Meta = Meta()
    # PEP-691
    name: NormalizedProjectName
    # PEP-700
    versions: list[str] = list()
    # PEP-503
    files: list[File] = list()


class ProjectListEntry(BaseModel):
    # PEP-691
    name: ProjectName  # may be normalized


# Simple Index page (/simple/)
class ProjectList[Project](BaseModel):
    """list of project names, a.k.a. project index - /simple/"""

    # PEP-629
    meta: Meta = Meta()
    # PEP-503
    projects: list[Project] = []
