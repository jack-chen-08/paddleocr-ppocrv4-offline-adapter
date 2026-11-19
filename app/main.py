from fastapi import FastAPI

from app.core.config import settings
from app.core.errors import AppError, app_error_handler, unhandled_handler
from app.core.logging import setup_logging
from app.routers import _template, health

setup_logging(settings.log_level)

app = FastAPI(title=settings.app_name)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_handler)
app.include_router(health.router)
app.include_router(_template.router)
