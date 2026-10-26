from fastapi import APIRouter

from app.api.routes import chats, factors, google, items, login, private, users, utils
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(google.router)
api_router.include_router(users.router)
# api_router.include_router(utils.router)
# api_router.include_router(items.router)
api_router.include_router(factors.router)
api_router.include_router(chats.router)


# if settings.ENVIRONMENT == "local":
#     api_router.include_router(private.router)
