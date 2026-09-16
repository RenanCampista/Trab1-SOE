"""Configuração por ambiente e arquivo .env."""

import math
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    latitude: float
    longitude: float
    radius_km: float

    def bounds(self) -> dict[str, float]:
        """Retorne a bounding box em graus que contém o círculo monitorado.

        Levanta ValueError se a área alcançar ou cruzar o antimeridiano.
        """
        # Bounding box esférica que contém o círculo; limitado a latitudes até 80°.
        angular = self.radius_km / 6371
        dlat = math.degrees(angular)
        dlon = math.degrees(math.asin(math.sin(angular) / math.cos(math.radians(self.latitude))))
        if abs(self.longitude) + dlon >= 180:
            raise ValueError("Regiões que cruzam o antimeridiano não são suportadas.")
        return {
            "lamin": self.latitude - dlat,
            "lamax": self.latitude + dlat,
            "lomin": self.longitude - dlon,
            "lomax": self.longitude + dlon,
        }


AIRPORTS = {
    "vitoria": ("Vitória / SBVT", -20.258, -40.286),
    "guarulhos": ("Guarulhos / SBGR", -23.4356, -46.4731),
    "galeao": ("Rio de Janeiro / SBGL", -22.81, -43.2506),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    region: Literal["vitoria", "guarulhos", "galeao", "custom"] = "vitoria"
    custom_name: str = "Minha cidade"
    custom_latitude: float = Field(default=-20.258, ge=-80, le=80)
    custom_longitude: float = Field(default=-40.286, ge=-180, le=180)
    radius_km: float = Field(default=50, gt=0, le=200)
    kafka_bootstrap_servers: str = "localhost:9092"
    poll_interval_seconds: float = Field(default=240, ge=10)
    opensky_client_id: str = ""
    opensky_client_secret: SecretStr = SecretStr("")
    max_position_age_seconds: int = Field(default=90, gt=0)
    proximity_km: float = Field(default=15, gt=0)
    low_altitude_m: float = Field(default=1000, gt=0)
    vertical_rate_threshold_ms: float = Field(default=8, gt=0)
    approach_samples: int = Field(default=3, ge=2, le=50)
    approach_max_gap_seconds: int = Field(default=300, gt=0)
    approach_min_distance_drop_km: float = Field(default=0.2, gt=0)
    approach_min_altitude_drop_m: float = Field(default=20, gt=0)
    alert_cooldown_seconds: int = Field(default=600, ge=0)
    database_path: str = "data/alerts.db"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def validate_settings(self):
        """Valide credenciais, raios e limites geográficos e retorne a configuração.

        Levanta ValueError para credenciais incompletas ou região incompatível.
        """
        if bool(self.opensky_client_id) != bool(self.opensky_client_secret.get_secret_value()):
            raise ValueError("Informe OPENSKY_CLIENT_ID e OPENSKY_CLIENT_SECRET juntos.")
        if self.proximity_km > self.radius_km:
            raise ValueError("PROXIMITY_KM deve ser menor ou igual a RADIUS_KM.")
        self.monitored_region().bounds()
        return self

    def monitored_region(self) -> Region:
        """Resolva o preset ou centro personalizado em uma região com ID estável.

        O ID inclui centro e raio para separar históricos de áreas diferentes.
        """
        name, lat, lon = AIRPORTS.get(
            self.region, (self.custom_name, self.custom_latitude, self.custom_longitude)
        )
        # Identifica também mudanças de centro/raio para não misturar históricos.
        key = f"{self.region}:{lat}:{lon}:{self.radius_km}"
        return Region(key, name, lat, lon, self.radius_km)
