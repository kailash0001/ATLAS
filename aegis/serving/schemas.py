from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FraudFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    amount: float | None = Field(ge=0, le=1000000000)
    hour: int | None = Field(ge=0, le=23)
    distance_from_home: float | None = Field(ge=0, le=50000)
    transactions_24h: int | None = Field(ge=0, le=1000000)
    account_age_days: int | None = Field(ge=0, le=50000)
    merchant_category: str = Field(min_length=1, max_length=80)
    card_present: Literal["yes", "no"]


class MaintenanceFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    temperature: float = Field(ge=-20, le=150)
    vibration: float = Field(ge=0, le=20)
    pressure: float = Field(ge=0, le=250)
    rpm: float = Field(ge=0, le=4000)
    voltage: float = Field(ge=180, le=270)
    current: float = Field(ge=0, le=40)
    operating_hours: float = Field(ge=0, le=100000)
    machine_type: Literal["pump", "compressor", "motor"]


class PredictionResponse(BaseModel):
    prediction_id: str
    request_id: str
    model: str
    version: int
    probability: float
    predicted_class: int
    threshold: float


class LabelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    actual_label: int = Field(ge=0, le=1)


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
