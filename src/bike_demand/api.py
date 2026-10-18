"""Serve a trusted, previously evaluated artifact; never train in this service."""

import json
import logging
import math
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bike_demand.preflight import sha256
from bike_demand.validate import FEATURES

LOGGER = logging.getLogger(__name__)
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
    if sha256(path) != metadata["model_sha256"]:
        raise ValueError("model checksum differs from metadata")
    # joblib is executable serialization: load only trusted team artifacts.
    model = joblib.load(path)
    if list(getattr(model, "feature_names_in_", [])) != list(FEATURES):
        raise ValueError("model feature order differs from metadata")
    loaded = LoadedModel(model=model, version=version)
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
        directory = artifact_dir or Path(os.environ.get("MODEL_DIR", "artifacts"))
        try:
            app.state.loaded_model = load_artifact(directory)
        except Exception:
            # Keep the HTTP service alive so readiness and valid requests return 503.
            LOGGER.exception("Model unavailable from %s", directory)
        try:
            yield
        finally:
            app.state.loaded_model = None

    app = FastAPI(title="Bike Demand Prediction API", lifespan=lifespan)

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
        return {"status": "ok", "model_version": loaded.version}

    @app.post("/predict", response_model=PredictionOutput)
    def predict(payload: PredictionInput):
        loaded = available()
        try:
            prediction = infer(loaded, payload)
        except Exception as error:
            app.state.loaded_model = None
            LOGGER.exception("Model inference failed")
            raise HTTPException(status_code=503, detail="Model unavailable") from error
        return PredictionOutput(prediction=prediction, model_version=loaded.version)

    return app


app = create_app()
