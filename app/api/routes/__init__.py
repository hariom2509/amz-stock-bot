"""API routes router package"""
from fastapi import APIRouter
from app.api.routes.auth import router as auth_router
from app.api.routes.telegram import router as telegram_router
from app.api.routes.products import router as products_router
from app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(telegram_router)
api_router.include_router(products_router)
