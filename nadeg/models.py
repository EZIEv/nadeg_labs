from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, field_validator, model_validator


def decimal_input(value):
    if isinstance(value, bool):
        raise ValueError("Ожидается число, а не логическое значение")
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Введите корректное число")
    if not number.is_finite() or (number and not -30 <= number.adjusted() <= 12):
        raise ValueError("Число должно быть конечным, в диапазоне 10⁻³⁰ … 10¹² (или 0)")
    if len(number.as_tuple().digits) > 40:
        raise ValueError("Допускается не более 40 значащих цифр")
    return number


Number = Annotated[Decimal, BeforeValidator(decimal_input)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Element(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,23}$")
    name: str = Field(default="", max_length=100)
    rate: Number = Field(ge=0, le=Decimal("1e12"))
    mass: Number = Field(default=Decimal(1), gt=0, le=Decimal("1e12"))
    reserves: int = Field(default=0, ge=0, le=12, strict=True)
    max_reserves: int = Field(default=3, ge=0, le=12, strict=True)
    reservable: bool = True

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if value.upper() in {"AND", "OR"}:
            raise ValueError("AND и OR зарезервированы для операторов")
        return value.upper()

    @model_validator(mode="after")
    def reserve_bounds(self):
        if self.reserves > self.max_reserves:
            raise ValueError("Текущий резерв не должен превышать допустимый максимум")
        return self


class Problem(StrictModel):
    title: str = Field(default="Моя система", max_length=120)
    time: Number = Field(gt=0, le=Decimal("1e12"))
    rate_scale: Literal["1", "1e-4", "1e-6"] = "1e-4"
    model: Literal["methodical"] = "methodical"
    task: Literal[1, 2] = 2
    expression: str = Field(min_length=1, max_length=2400)
    elements: list[Element] = Field(min_length=1, max_length=40)
    target: Number = Field(default=Decimal("0.999"), gt=0, lt=1)
    max_mass: Number | None = Field(default=None, gt=0, le=Decimal("1e12"))
    search_limit: int = Field(default=15000, ge=1, le=50000, strict=True)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [e.id for e in self.elements]
        if len(ids) != len(set(ids)):
            raise ValueError("Идентификаторы элементов должны быть уникальными")
        return self
