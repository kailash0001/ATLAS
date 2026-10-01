import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from aegis.core.config import Settings
from aegis.db.session import make_engine, sessions
from aegis.deployment.runtime import Runtime


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, float | str]


def create_app():
    settings = Settings()
    engine = make_engine(settings.database_url)
    runtime = Runtime(settings, sessions(engine))
    version_id = os.environ["AEGIS_RUNTIME_VERSION_ID"]

    @asynccontextmanager
    async def lifespan(app):
        from starlette.concurrency import run_in_threadpool

        await run_in_threadpool(runtime.load, version_id)
        yield
        engine.dispose()

    app = FastAPI(title="Aegis version runtime", lifespan=lifespan)

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        runtime.load(version_id)
        return {"version_id": version_id}

    @app.post("/predict")
    def predict(body: Input):
        return {"version_id": version_id, "prediction": runtime.predict(version_id, body.features)}

    return app
