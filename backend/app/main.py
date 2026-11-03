"""FastAPI application factory."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(
        title="Marea Seguros · Asistente de pólizas",
        version="0.1.0",
        # Docs live under /api so they are reachable through the frontend's /api proxy too.
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        """The process is up. Dependencies are checked by /health/ready."""
        return {"status": "ok"}

    return app


app = create_app()
