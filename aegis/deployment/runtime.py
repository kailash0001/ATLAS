import threading

import numpy as np
import pandas as pd
from sqlalchemy import select

from aegis.core.errors import AegisError
from aegis.db.models import Model, ModelVersion
from aegis.reliability.workload import context, load_predictor


class Runtime:
    """Version-pinned artifacts; aliases are never followed during a request."""

    def __init__(self, settings, factory):
        self.settings, self.factory = settings, factory
        self.cache = {}
        self.lock = threading.Lock()

    def load(self, version_id):
        with self.lock:
            if version_id not in self.cache:
                with self.factory() as session:
                    version = session.get(ModelVersion, version_id)
                    if version is None:
                        raise AegisError("Unknown runtime version")
                    model = session.get(Model, version.model_id)
                    name, number = model.name, version.version
                config, _, info = context(self.settings, self.factory, name, number)
                predictor = load_predictor(self.settings, config, info)
                signature = predictor.metadata.signature
                if signature is None or signature.inputs.input_names() != config.features.all:
                    raise AegisError("Incompatible runtime signature")
                self.cache[version_id] = (config, predictor)
            return self.cache[version_id]

    def validate(self, version_id, features):
        config, _ = self.load(version_id)
        if set(features) != set(config.features.all):
            raise AegisError("Features must match the model signature exactly")
        for name in config.features.numeric:
            value = features[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not np.isfinite(value)
            ):
                raise AegisError("Numeric features must be finite numbers")
        if any(not isinstance(features[name], str) for name in config.features.categorical):
            raise AegisError("Categorical features must be strings")

    def predict(self, version_id, features):
        self.validate(version_id, features)
        config, predictor = self.load(version_id)
        frame = pd.DataFrame([features], columns=config.features.all)
        frame[config.features.numeric] = frame[config.features.numeric].astype(float)
        values = np.asarray(predictor.predict(frame))
        if config.is_regression:
            if values.shape != (1,) or not np.isfinite(values).all():
                raise AegisError("Invalid regression output")
            return float(values[0])
        if (
            values.shape != (1, 2)
            or not np.isfinite(values).all()
            or not ((values >= 0) & (values <= 1)).all()
        ):
            raise AegisError("Invalid probability output")
        return float(values[0, 1])

    def identity(self, version_id):
        with self.factory() as session:
            version = session.get(ModelVersion, version_id)
            model = session.scalar(select(Model).where(Model.id == version.model_id))
            return {"model": model.name, "version": version.version, "version_id": version.id}
