import os
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.config import settings
from app.api.auth import router as auth_router
from app.api.connectors_router import router as connectors_router
from app.api.ingestion_router import router as ingestion_router
from app.api.webhooks import router as webhooks_router

app = FastAPI(
    title=settings.APP_NAME,
    description="Enterprise Data Ingestion & Storage Engine — Web UI, APIs, and Live Webhooks",
    version="1.0.0",
)

# Enable CORS for local & cloud environments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enable GZip HTTP Compression Middleware (70% smaller web asset load size)
app.add_middleware(GZipMiddleware, minimum_size=500)

# Include API Routers
app.include_router(auth_router)
app.include_router(connectors_router)
app.include_router(ingestion_router)
app.include_router(webhooks_router)

# Serve Static UI Frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
