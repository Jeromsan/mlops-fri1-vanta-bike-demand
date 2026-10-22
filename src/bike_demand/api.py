"""Serve a trusted, previously evaluated artifact; never train in this service."""

import hashlib
import io
import json
import logging
import math
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bike_demand.validate import FEATURES

EVENTS = logging.getLogger("bike_demand.events")
if not EVENTS.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    EVENTS.addHandler(handler)
EVENTS.setLevel(logging.INFO)
EVENTS.propagate = False


def event(name: str, **fields):
    EVENTS.info(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": name,
                **fields,
            },
            allow_nan=False,
        )
    )


Normalised = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class PredictionInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    season: Annotated[int, Field(ge=1, le=4)]
    yr: Annotated[int, Field(ge=0, le=1)]
    mnth: Annotated[int, Field(ge=1, le=12)]
    hr: Annotated[int, Field(ge=0, le=23)]
    holiday: Annotated[int, Field(ge=0, le=1)]
    weekday: Annotated[int, Field(ge=0, le=6)]
    workingday: Annotated[int, Field(ge=0, le=1)]
    weathersit: Annotated[int, Field(ge=1, le=4)]
    temp: Normalised
    atemp: Normalised
    hum: Normalised
    windspeed: Normalised


class PredictionOutput(BaseModel):
    prediction: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    model_version: str


@dataclass(frozen=True)
class LoadedModel:
    model: Any
    version: str
    sha256: str


def infer(loaded: LoadedModel, payload: PredictionInput) -> float:
    # No new scaling: the training predictors already contain normalised weather.
    frame = pd.DataFrame([payload.model_dump()], columns=list(FEATURES))
    predictions = np.asarray(loaded.model.predict(frame), dtype=float)
    if predictions.shape != (1,):
        raise ValueError("model must return exactly one prediction")
    prediction = float(predictions[0])
    if not math.isfinite(prediction) or prediction < 0:
        raise ValueError("model prediction must be finite and nonnegative")
    return prediction


def load_artifact(directory: Path) -> LoadedModel:
    metadata = json.loads((directory / "model-metadata.json").read_text())
    version = metadata["model_version"]
    if not isinstance(version, str) or not version.strip():
        raise ValueError("metadata must contain a nonempty model_version")
    if metadata["features"] != list(FEATURES):
        raise ValueError("metadata feature order differs from the training contract")
    path = directory / "model.joblib"
    model_bytes = path.read_bytes()
    digest = hashlib.sha256(model_bytes).hexdigest()
    if digest != metadata["model_sha256"]:
        raise ValueError("model checksum differs from metadata")
    # joblib is executable serialization: load only trusted team artifacts.
    model = joblib.load(io.BytesIO(model_bytes))
    if list(getattr(model, "feature_names_in_", [])) != list(FEATURES):
        raise ValueError("model feature order differs from metadata")
    loaded = LoadedModel(model=model, version=version, sha256=digest)
    probe = PredictionInput(
        season=1,
        yr=0,
        mnth=1,
        hr=0,
        holiday=0,
        weekday=0,
        workingday=0,
        weathersit=1,
        temp=0.5,
        atemp=0.5,
        hum=0.5,
        windspeed=0.0,
    )
    infer(loaded, probe)
    return loaded


def create_app(artifact_dir: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.loaded_model = None
        app.state.source_commit = os.environ.get("SOURCE_COMMIT", "unknown")
        directory = artifact_dir or Path(os.environ.get("MODEL_DIR", "artifacts"))
        try:
            app.state.loaded_model = load_artifact(directory)
        except Exception as error:
            # Keep the HTTP service alive so readiness and valid requests return 503.
            event(
                "model_unavailable",
                reason=type(error).__name__,
                action="Check trusted model, metadata, checksum and feature contract; restart",
                source_commit=app.state.source_commit,
            )
        try:
            yield
        finally:
            app.state.loaded_model = None

    app = FastAPI(title="Bike Demand Prediction API", lifespan=lifespan)

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        loaded = app.state.loaded_model
        status = 500
        try:
            try:
                response = await call_next(request)
            except Exception:
                response = JSONResponse(
                    status_code=500, content={"detail": "Internal server error"}
                )
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route = request.scope.get("route")
            event(
                "request_completed",
                request_id=request_id,
                method=request.method,
                route=getattr(route, "path", "<unmatched>"),
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                model_version=loaded.version if loaded else None,
                model_sha256=loaded.sha256 if loaded else None,
                source_commit=app.state.source_commit,
            )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        # Exclude raw input/ctx: NaN and infinity cannot be encoded as JSON errors.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: item[key] for key in ("loc", "msg", "type")}
                    for item in error.errors()
                ]
            },
        )

    def available() -> LoadedModel:
        loaded = app.state.loaded_model
        if loaded is None:
            raise HTTPException(status_code=503, detail="Model unavailable")
        return loaded

    @app.get("/health")
    def health():
        loaded = available()
        return {
            "status": "ok",
            "model_version": loaded.version,
            "model_sha256": loaded.sha256,
            "source_commit": app.state.source_commit,
        }

    @app.post("/predict", response_model=PredictionOutput)
    def predict(payload: PredictionInput):
        loaded = available()
        try:
            prediction = infer(loaded, payload)
        except Exception as error:
            app.state.loaded_model = None
            event(
                "model_inference_failed",
                reason=type(error).__name__,
                source_commit=app.state.source_commit,
            )
            raise HTTPException(status_code=503, detail="Model unavailable") from error
        return PredictionOutput(prediction=prediction, model_version=loaded.version)

    return app


app = create_app()
