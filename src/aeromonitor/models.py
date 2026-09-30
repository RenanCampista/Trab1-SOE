"""Contratos JSON e conversão dos vetores posicionais da OpenSky."""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aeromonitor.config import Region


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula a distância esférica em quilômetros entre coordenadas em graus.

    Aplica a fórmula de haversine com raio terrestre de 6.371 km.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, a))))


class Position(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    schema_version: Literal[1] = 1
    event_id: str
    region_id: str
    region_name: str
    icao24: str
    callsign: str | None
    observed_at: int
    collected_at: int
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float | None
    on_ground: bool
    velocity_ms: float | None
    vertical_rate_ms: float | None
    distance_km: float = Field(ge=0)


class Alert(BaseModel):
    schema_version: Literal[1] = 1
    event_id: str
    kind: str
    region_id: str
    region_name: str
    icao24: str
    callsign: str | None
    observed_at: int
    message: str
    source_event_ids: list[str]


class CollectionStatus(BaseModel):
    """Resultado de uma tentativa de coleta, mesmo sem posições publicáveis."""

    schema_version: Literal[1] = 1
    region_id: str
    observed_at: int
    success: bool
    valid_positions: int = Field(default=0, ge=0)
    detail: str
    next_attempt_at: int


def normalize(row: list, region: Region, collected_at: int, max_age: int) -> Position | None:
    """Converte um vetor OpenSky em posição válida dentro da região.

    collected_at é o instante de coleta em segundos Unix e max_age é a idade
    máxima em segundos. Retorna None para vetores incompletos, valores inválidos,
    posições futuras, antigas ou fora do raio. Preserva metros e m/s da fonte.
    """
    if len(row) < 12 or any(row[i] is None for i in (0, 3, 5, 6)):
        return None
    try:
        observed = int(row[3])
        if not 0 <= collected_at - observed <= max_age:
            return None
        distance = distance_km(region.latitude, region.longitude, row[6], row[5])
        if distance > region.radius_km:
            return None
        return Position(
            event_id=f"{region.id}:{row[0]}:{observed}",
            region_id=region.id,
            region_name=region.name,
            icao24=row[0],
            callsign=row[1].strip() if row[1] else None,
            observed_at=observed,
            collected_at=collected_at,
            latitude=row[6],
            longitude=row[5],
            altitude_m=row[7],
            on_ground=row[8],
            velocity_ms=row[9],
            vertical_rate_ms=row[11],
            distance_km=distance,
        )
    except (ValueError, TypeError, ValidationError):
        return None
