class RequestException(Exception):
    ...


class ConnectionError(RequestException):
    ...


class Timeout(RequestException):
    ...


class HTTPError(RequestException):
    ...
