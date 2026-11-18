"""FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR, Settings
from .db import Store
from .models import AnalysisResult, Overrides, SensitivityGridModel
from .providers.analyst import AnalystExtractor
from .providers.base import ProviderError, TickerNotFoundError
from .providers.llm import LLMConfig, OpenAICompatibleClient
from .providers.news import YahooNewsProvider
from .providers.yahoo import YahooProvider
from .service import AnalysisService


def build_service(settings: Settings | None = None) -> AnalysisService:
    settings = settings or Settings.from_env()
    store = Store(settings.db_path)
    provider = YahooProvider()

    analyst: AnalystExtractor | None = None
    if settings.llm.enabled:
        client = OpenAICompatibleClient(
            LLMConfig(
                base_url=settings.llm.base_url,
                model=settings.llm.model,
                api_key=settings.llm.api_key,
                timeout=settings.llm.timeout,
                mode=settings.llm.mode,
            )
        )
        analyst = AnalystExtractor(
            client, model_label=f"the analyst model ({settings.llm.model})"
        )

    return AnalysisService(
        store=store,
        provider=provider,
        ttl_hours=settings.ttl_hours,
        analyst=analyst,
        news_provider=YahooNewsProvider(),
        news_ttl_hours=settings.news_ttl_hours,
        news_limit=settings.news_limit,
    )


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
        analyst = active_service.analyst
        return {
            "status": "ok",
            "database": str(active_service.store.path),
            "ttl_hours": active_service.ttl_hours,
            "news": {
                "enabled": active_service.news_provider is not None,
                "ttl_hours": active_service.news_ttl_hours,
                "limit": active_service.news_limit,
            },
            "analyst": {
                "enabled": analyst is not None,
                "model": analyst.model_label if analyst else None,
                "base_url": settings.llm.base_url,
                "mode": settings.llm.mode,
            },
        }

    @app.get("/api/tickers")
    def tickers() -> dict[str, object]:
        items = active_service.store.list_universe()
        return {"count": len(items), "tickers": items}

    @app.get("/api/analysis/{ticker}", response_model=AnalysisResult)
    def analysis(
        ticker: str,
        refresh: bool = Query(default=False, description="Recompute from Yahoo"),
        use_llm: bool = Query(
            default=True, description="Let the analyst model fill the missing inputs"
        ),
    ) -> AnalysisResult:
        try:
            return active_service.analyze(ticker, refresh=refresh, use_llm=use_llm)
        except TickerNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get(
        "/api/analysis/{ticker}/sensitivity", response_model=SensitivityGridModel
    )
    def sensitivity(
        ticker: str,
        span: float = Query(default=0.02, description="Half width of the grid"),
        step: float = Query(default=0.005, description="Distance between two points"),
        use_llm: bool = Query(default=True),
    ) -> SensitivityGridModel:
        try:
            return active_service.sensitivity(
                ticker, use_llm=use_llm, span=span, step=step
            )
        except TickerNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/analysis/{ticker}/overrides", response_model=AnalysisResult)
    def set_overrides(
        ticker: str, overrides: Overrides, use_llm: bool = Query(default=True)
    ) -> AnalysisResult:
        try:
            return active_service.set_overrides(ticker, overrides, use_llm=use_llm)
        except TickerNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.delete("/api/analysis/{ticker}/overrides", response_model=AnalysisResult)
    def clear_overrides(ticker: str, use_llm: bool = Query(default=True)) -> AnalysisResult:
        try:
            return active_service.clear_overrides(ticker, use_llm=use_llm)
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
