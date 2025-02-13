import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from inspect import isawaitable
from pathlib import Path

from anyio import to_thread
from fastapi import Request, Response
from fastapi.exceptions import HTTPException
from httpx._api import head
from starlette.status import HTTP_304_NOT_MODIFIED, HTTP_412_PRECONDITION_FAILED

from .config import settings


@dataclass
class FileMTimeWatcher:
    file: Path
    polling_interval: float = 5
    mtime: float = field(default=0.0, init=False)

    def start(self):
        asyncio.create_task(self.run())

    async def run(self):
        while True:
            stat = await to_thread.run_sync(settings.database_file.stat)
            self.mtime = stat.st_mtime
            await asyncio.sleep(self.polling_interval)

    def __str__(self) -> str:
        return str(self.mtime)


EtagGen = Callable[[Request], str | None | Awaitable[str | None]]


class HeaderType(Enum):
    IF_MATCH = "if-match"
    IF_NONE_MATCH = "if-none-match"


class Etag:
    def __init__(self, etag_gen: EtagGen, weak=True):
        self.etag_gen = etag_gen
        self.weak = weak

    def is_modified(self, etag: str | None, client_etag: str | None):
        if not etag:
            return True
        return not client_etag or etag != client_etag

    async def __call__(self, request: Request, response: Response) -> str | None:
        etag = (await r) if isawaitable(r := self.etag_gen(request)) else r
        if etag and self.weak:
            etag = f'W/"{etag}"'

        client_etag: str | None = None
        header_type: HeaderType | None = None
        if client_etag := request.headers.get("if-none-match"):
            header_type = HeaderType.IF_NONE_MATCH
        elif client_etag := request.headers.get("if-match"):
            header_type = HeaderType.IF_MATCH

        modified = self.is_modified(etag, client_etag)
        headers = {"etag": etag} if etag else {}

        if not modified and header_type == HeaderType.IF_NONE_MATCH:
            raise HTTPException(HTTP_304_NOT_MODIFIED, headers=headers)
        elif modified and header_type == HeaderType.IF_MATCH:
            raise HTTPException(HTTP_412_PRECONDITION_FAILED, headers=headers)

        response.headers.update(headers)
        return etag
