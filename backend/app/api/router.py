from app.api.conflicts import router as conflicts_router
from app.api.package_imports import router as package_imports_router
from app.api.documents import router as documents_router
from fastapi import APIRouter

from app.api.assets import router as assets_router
from app.api.demo import router as demo_router
from app.api.imports import router as imports_router
from app.api.projects import router as projects_router
from app.api.review import router as review_router
from app.api.pdf_pole_extractions import router as pdf_pole_extractions_router
from app.api.pole_entities import router as pole_entities_router
from app.api.pole_relationships import router as pole_relationships_router

api_router = APIRouter()
api_router.include_router(projects_router)
api_router.include_router(assets_router)
api_router.include_router(review_router)
api_router.include_router(demo_router)
api_router.include_router(imports_router)

api_router.include_router(documents_router)
api_router.include_router(package_imports_router)
api_router.include_router(conflicts_router)
api_router.include_router(pdf_pole_extractions_router)
api_router.include_router(pole_entities_router)
api_router.include_router(pole_relationships_router)
