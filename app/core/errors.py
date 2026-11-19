"""统一错误码与异常处理。

验收项出现「返回 4xx / 被拒绝 / 错误码」这类措辞时，一律走 AppError，
这样测试可以直接断言 code，下游是否被调用也能用 mock 计数器证明。
"""
from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, detail: dict | None = None):
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}
        super().__init__(message)


class ErrorCode:
    INVALID_PARAM = ("INVALID_PARAM", 400)
    UNAUTHORIZED = ("UNAUTHORIZED", 401)
    FORBIDDEN = ("FORBIDDEN", 403)
    NOT_FOUND = ("NOT_FOUND", 404)
    CONFLICT = ("CONFLICT", 409)          # 幂等重复提交走这个
    PRECONDITION = ("PRECONDITION", 412)  # 状态机不允许的流转走这个
    DOWNSTREAM = ("DOWNSTREAM_ERROR", 502)
    INTERNAL = ("INTERNAL", 500)


def _make(key: tuple[str, int], message: str, detail: dict | None = None) -> AppError:
    return AppError(key[0], message, key[1], detail)


def raise_invalid(message: str, **detail):
    raise _make(ErrorCode.INVALID_PARAM, message, detail)


def raise_conflict(message: str, **detail):
    raise _make(ErrorCode.CONFLICT, message, detail)


def raise_precondition(message: str, **detail):
    raise _make(ErrorCode.PRECONDITION, message, detail)


def raise_forbidden(message: str, **detail):
    raise _make(ErrorCode.FORBIDDEN, message, detail)


async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status,
        content={"code": exc.code, "message": exc.message, "detail": exc.detail},
    )


async def unhandled_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"code": ErrorCode.INTERNAL[0], "message": "internal error", "detail": {}},
    )
