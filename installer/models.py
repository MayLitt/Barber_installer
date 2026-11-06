"""Modèle de la configuration v1.0 : chaque donnée garde sa provenance."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field

# found = 2 sources indépendantes d'accord ; suggested = 1 source ; conflict = sources contradictoires
# confirmed = validé par le commerçant ; missing = rien trouvé
Status = Literal["found", "suggested", "conflict", "confirmed", "missing"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Prov(BaseModel):
    source: str                    # google_places, site, planity, registre, import, defaut_metier, commercant
    url: str | None = None
    collected_at: str = Field(default_factory=now)
    confidence: float = 0.7


class Fact(BaseModel):
    value: Any = None
    status: Status = "missing"
    prov: list[Prov] = Field(default_factory=list)
    alternatives: list[Any] = Field(default_factory=list)
    note: str | None = None


class Service(BaseModel):
    name: str
    price_eur: float | None = None
    duration_min: int | None = None
    duration_status: Status = "missing"
    duration_source: str | None = None   # page, defaut_metier, commercant
    staff: list[str] = Field(default_factory=list)
    bookable_online: bool | None = None
    status: Status = "suggested"
    alt_prices: list[float] = Field(default_factory=list)
    prov: list[Prov] = Field(default_factory=list)


class StaffMember(BaseModel):
    first_name: str                # prénom seul, jamais de nom de famille
    specialties: list[str] = Field(default_factory=list)
    prov: list[Prov] = Field(default_factory=list)


class Question(BaseModel):
    id: str
    kind: str
    field: str
    text: str
    options: list[str] = Field(default_factory=list)


class BusinessConfig(BaseModel):
    name: Fact = Field(default_factory=Fact)
    address: Fact = Field(default_factory=Fact)
    phone: Fact = Field(default_factory=Fact)
    category: Fact = Field(default_factory=Fact)
    trade: str | None = None       # coiffeur, restaurant... (déduit de NAF / catégorie)
    hours: Fact = Field(default_factory=Fact)
    legal: Fact = Field(default_factory=Fact)
    staff: list[StaffMember] = Field(default_factory=list)
    services: list[Service] = Field(default_factory=list)
    rules: dict[str, Fact] = Field(default_factory=dict)
    rush_delay_min: Fact = Field(default_factory=Fact)
    rating: Fact = Field(default_factory=Fact)
    missing_info: list[str] = Field(default_factory=list)
    pending_questions: list[Question] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
