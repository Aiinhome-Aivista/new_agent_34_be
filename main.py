import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.auth_routes import router as auth_router
from app.api.trigger_routes import router as trigger_router
from app.api.case_routes import router as case_router
from app.api.decision_routes import router as decision_router
from app.api.action_routes import router as action_router
from app.api.policy_routes import router as policy_router
from app.api.audit_routes import router as audit_router

app = FastAPI(
    title="Agent 34 — Merchant & User Fraud Investigation System",
    description="Production-grade AI agent system for post-trigger fraud investigation, evidence correlation, policy RAG, deterministic decision gateway, and authorized action execution.",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(trigger_router, prefix=settings.API_V1_PREFIX)
app.include_router(case_router, prefix=settings.API_V1_PREFIX)
app.include_router(decision_router, prefix=settings.API_V1_PREFIX)
app.include_router(action_router, prefix=settings.API_V1_PREFIX)
app.include_router(policy_router, prefix=settings.API_V1_PREFIX)
app.include_router(audit_router, prefix=settings.API_V1_PREFIX)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Agent 34 Fraud Investigation Backend",
        "version": "1.0.0",
        "database": "MySQL (Agent_34)"
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
