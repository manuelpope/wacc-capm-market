"""FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR, Settings
from .db import Store
from .models import AnalysisResult, Overrides
from .providers.base import ProviderError, TickerNotFoundError
from .providers.yahoo import YahooProvider
from .service import AnalysisService


def build_service(settings: Settings | None = None) -> AnalysisService:
    settings = settings or Settings.from_env()
    store = Store(settings.db_path)
    provider = YahooProvider()
    return AnalysisService(store=store, provider=provider, ttl_hours=settings.ttl_hours)


def create_app(service: AnalysisService | None = None) -> FastAPI:
    settings = Settings.from_env()
    active_service = service or build_service(settings)

    app = FastAPI(
        title="WACC Lab",
        version="0.1.0",
        description=(
            "Computes WACC, g and a simple DCF for Yahoo Finance tickers and "
            "stores the results in SQLite."
        ),
    )
    app.state.service = active_service
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "database": str(settings.db_path),
            "ttl_hours": settings.ttl_hours,
        }

    @app.get("/api/tickers")
    def tickers() -> dict[str, object]:
        items = active_service.store.list_universe()
        return {"count": len(items), "tickers": items}

    @app.get("/api/analysis/{ticker}", response_model=AnalysisResult)
    def analysis(
        ticker: str,
        refresh: bool = Query(default=False, description="Recompute from Yahoo"),
    ) -> AnalysisResult:
        try:
            return active_service.analyze(ticker, refresh=refresh)
        except TickerNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/analysis/{ticker}/overrides", response_model=AnalysisResult)
    def set_overrides(ticker: str, overrides: Overrides) -> AnalysisResult:
        try:
            return active_service.set_overrides(ticker, overrides)
        except TickerNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.delete("/api/analysis/{ticker}/overrides", response_model=AnalysisResult)
    def clear_overrides(ticker: str) -> AnalysisResult:
        try:
            return active_service.clear_overrides(ticker)
        except TickerNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
