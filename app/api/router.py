from fastapi import APIRouter

from app.api.routes.ambiguity import router as ambiguity_router
from app.api.routes.architecture import router as architecture_router
from app.api.routes.assumptions import router as assumptions_router
from app.api.routes.chunks import router as chunks_router
from app.api.routes.conflicts import router as conflicts_router
from app.api.routes.copilot import router as copilot_router
from app.api.routes.engineering import router as engineering_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.missing_requirements import router as missing_requirements_router
from app.api.routes.requirements import router as requirements_router
from app.api.routes.spec_health import router as spec_health_router
from app.api.routes.specification_dna import router as specification_dna_router
from app.api.routes.traceability import router as traceability_router
from app.api.routes.understanding import router as understanding_router
from app.api.routes.upload import router as upload_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(knowledge_router)
api_router.include_router(missing_requirements_router)
api_router.include_router(upload_router)
api_router.include_router(chunks_router)
api_router.include_router(understanding_router)
api_router.include_router(requirements_router)
api_router.include_router(ambiguity_router)
api_router.include_router(conflicts_router)
api_router.include_router(assumptions_router)
api_router.include_router(engineering_router)
api_router.include_router(architecture_router)
api_router.include_router(copilot_router)
api_router.include_router(traceability_router)
api_router.include_router(spec_health_router)
api_router.include_router(specification_dna_router)
