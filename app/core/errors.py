from dataclasses import dataclass


@dataclass
class ErrorInfo:
    code: str
    title: str
    message: str
    details: str = ""


class AppError(Exception):
    def __init__(self, code: str, title: str, message: str, details: str = ""):
        super().__init__(message)
        self.info = ErrorInfo(code=code, title=title, message=message, details=details)


def wrap_exception(code: str, title: str, exc: Exception) -> AppError:
    return AppError(code=code, title=title, message=str(exc), details=repr(exc))

