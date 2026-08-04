from typing import Any


class RequestException(Exception):
    ...


class ConnectionError(RequestException):
    ...


class Timeout(RequestException):
    ...


class HTTPError(RequestException):
    ...


class Response:
    status_code: int

    def raise_for_status(self) -> None: ...
    def json(self) -> Any: ...


def get(url: str, *, timeout: float | int | None = ...) -> Response: ...
def post(
    url: str,
    *,
    json: Any | None = ...,
    timeout: float | int | None = ...,
) -> Response: ...
