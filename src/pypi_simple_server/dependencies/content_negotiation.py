from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.status import HTTP_406_NOT_ACCEPTABLE


class MediaType(StrEnum):
    JSON_V1 = "application/vnd.pypi.simple.v1+json"
    HTML_V1 = "application/vnd.pypi.simple.v1+html"


_ACCEPTABLE = {
    MediaType.JSON_V1: {
        MediaType.JSON_V1,
        "application/vnd.pypi.simple.latest+json",
    },
    MediaType.HTML_V1: {
        MediaType.HTML_V1,
        "application/vnd.pypi.simple.latest+html",
        "text/html",
        "*/*",
    },
}


class SimpleV1JSONResponse(JSONResponse):
    media_type = MediaType.JSON_V1


def get_response_media_type(request: Request) -> MediaType:
    accept = set(request.headers.get("accept", "*/*").split(","))
    for media_type, acceptable in _ACCEPTABLE.items():
        if acceptable & accept:
            return media_type
    raise HTTPException(HTTP_406_NOT_ACCEPTABLE)


ResponseMediaTypeDep = Annotated[MediaType, Depends(get_response_media_type)]
