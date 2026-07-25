"""Server-authoritative age eligibility (ADR 0021).

Age is completed years using the UTC calendar date of the evaluation moment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.core.errors import AppError

AGE_BANDS: tuple[tuple[int, int | None, str], ...] = (
    (18, 20, "18-20"),
    (21, 24, "21-24"),
    (25, 29, "25-29"),
    (30, 34, "30-34"),
    (35, None, "35+"),
)


@dataclass(frozen=True)
class AgeEvaluation:
    age_years: int
    eligible: bool
    age_band: str | None


def parse_date_of_birth(value: date) -> date:
    today = datetime.now(UTC).date()
    if value > today:
        raise AppError(
            "INVALID_DATE_OF_BIRTH",
            "Date of birth cannot be in the future.",
            status_code=400,
        )
    if value.year < today.year - 120:
        raise AppError(
            "INVALID_DATE_OF_BIRTH",
            "Date of birth is not plausible.",
            status_code=400,
        )
    return value


def age_years_on(dob: date, *, on: date) -> int:
    years = on.year - dob.year
    if (on.month, on.day) < (dob.month, dob.day):
        years -= 1
    return years


def age_band_for(age_years: int) -> str | None:
    for low, high, label in AGE_BANDS:
        if age_years < low:
            continue
        if high is None or age_years <= high:
            return label
    return None


def evaluate_age(
    dob: date, *, minimum_age_years: int, now: datetime | None = None
) -> AgeEvaluation:
    dob = parse_date_of_birth(dob)
    on = (now or datetime.now(UTC)).astimezone(UTC).date()
    years = age_years_on(dob, on=on)
    if years < 0:
        raise AppError(
            "INVALID_DATE_OF_BIRTH",
            "Date of birth is not plausible.",
            status_code=400,
        )
    eligible = years >= minimum_age_years
    band = age_band_for(years) if eligible else None
    return AgeEvaluation(age_years=years, eligible=eligible, age_band=band)
