"""Lab 2: exact rational counts and labour, with nested periodic forms."""
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from .models import Number, StrictModel, decimal_input

OPERATIONAL = [
    ("preliminary", "Предварительная подготовка"),
    ("preflight", "Предполётная подготовка"),
    ("turnaround", "Подготовка к повторному вылету"),
    ("postflight", "Послеполётная подготовка"),
]
MAX_OPERATIONS = 100


class Period(StrictModel):
    id: str = Field(pattern=r"^P[1-9][0-9]{0,3}$")
    interval: Number = Field(gt=0, le=Decimal("1e12"))


def validate_periods(periods):
    if len({p.id for p in periods}) != len(periods):
        raise ValueError("Идентификаторы регламентов должны быть уникальны")
    for smaller, larger in zip(periods, periods[1:]):
        ratio = Fraction(larger.interval) / Fraction(smaller.interval)
        if ratio <= 1 or ratio.denominator != 1:
            raise ValueError("Периоды должны возрастать; каждый следующий должен быть кратен предыдущему")
    return periods


Periods = Annotated[list[Period], Field(min_length=1, max_length=8)]


class Operation(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    labor: dict[str, Annotated[Number, Field(ge=0, le=Decimal("1e12"))]] = Field(max_length=12)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value):
        if not value.strip():
            raise ValueError("Укажите название операции")
        return value.strip()


class MaintenanceSettings(StrictModel):
    title: str = Field(default="Моя система", max_length=120)
    resource: Number = Field(gt=0, le=Decimal("1e12"))
    flight_time: Number = Field(gt=0, le=Decimal("1e12"))
    flights_per_day: int = Field(ge=1, le=1000)
    periods: Periods

    @field_validator("flights_per_day", mode="before")
    @classmethod
    def integer_flights(cls, value):
        number = decimal_input(value)
        if number != number.to_integral_value():
            raise ValueError("Число полётов за день должно быть целым")
        return int(number)

    @field_validator("periods")
    @classmethod
    def nested_periods(cls, value):
        return validate_periods(value)


class MaintenanceProblem(MaintenanceSettings):
    operations: list[Operation] = Field(min_length=1, max_length=MAX_OPERATIONS)

    @model_validator(mode="after")
    def known_labor_columns(self):
        expected = {key for key, _ in OPERATIONAL} | {p.id for p in self.periods}
        for operation in self.operations:
            if set(operation.labor) != expected:
                raise ValueError(f"«{operation.name}»: трудоёмкости должны быть заданы для всех текущих форм и только для них")
        return self


def number(value):
    """Round only serialization; intermediate arithmetic stays exact."""
    value = Fraction(value)
    with localcontext() as context:
        context.prec = 60
        return str(Decimal(value.numerator) / Decimal(value.denominator))


def period_label(interval):
    text = format(interval, "f").rstrip("0").rstrip(".") if "." in format(interval, "f") else format(interval, "f")
    return f"Регламент {text} ч"


def forms(problem):
    return ([{"id": key, "label": label, "interval": None} for key, label in OPERATIONAL]
            + [{"id": p.id, "label": period_label(p.interval), "interval": str(p.interval)} for p in problem.periods])


def calculate_maintenance(problem: MaintenanceProblem):
    resource, duration = Fraction(problem.resource), Fraction(problem.flight_time)
    days = resource / (duration * problem.flights_per_day)
    counts = {"preliminary": days / 2, "preflight": days,
              "turnaround": days * (problem.flights_per_day - 1), "postflight": days}
    cumulative = []
    for period in problem.periods:
        ratio = resource / Fraction(period.interval)
        # Events p, 2p, ... strictly before the repair time, without iteration.
        cumulative.append((ratio.numerator - 1) // ratio.denominator)
    for i, period in enumerate(problem.periods):
        counts[period.id] = Fraction(cumulative[i] - (cumulative[i + 1] if i + 1 < len(cumulative) else 0))

    definitions = forms(problem)
    per_service = {f["id"]: sum((Fraction(op.labor[f["id"]]) for op in problem.operations), Fraction(0)) for f in definitions}
    totals = {key: per_service[key] * count for key, count in counts.items()}
    total = sum(totals.values(), Fraction(0))
    output_forms = []
    for i, f in enumerate(definitions):
        key = f["id"]
        if i < len(OPERATIONAL):
            expression = {"preliminary": "Nпредв = Nлд / 2", "preflight": "Nпредпол = Nлд",
                          "turnaround": "Nповт = Nлд × (n − 1)", "postflight": "Nпослепол = Nлд"}[key]
            schedule_total = None
        else:
            j = i - len(OPERATIONAL)
            schedule_total = cumulative[j]
            expression = f"C({f['interval']}) = ceil(t₁ / {f['interval']}) − 1; N = {schedule_total} − {cumulative[j + 1] if j + 1 < len(cumulative) else 0}"
        output_forms.append({**f, "count": number(counts[key]), "count_exact": str(counts[key]),
                             "cumulative_count": schedule_total, "per_service": number(per_service[key]),
                             "total": number(totals[key]), "share_percent": number(totals[key] / total * 100) if total else "0",
                             "formula": expression})
    output_operations = []
    for op in problem.operations:
        by_form = {key: Fraction(norm) * counts[key] for key, norm in op.labor.items()}
        op_total = sum(by_form.values(), Fraction(0))
        output_operations.append({"name": op.name, "labor": {k: str(v) for k, v in op.labor.items()},
                                  "by_form": {k: number(v) for k, v in by_form.items()}, "total": number(op_total),
                                  "share_percent": number(op_total / total * 100) if total else "0"})
    warnings = []
    if days.denominator != 1:
        warnings.append("Число лётных дней дробное: это расчётный показатель по среднему режиму эксплуатации; в вычислениях он не округляется")
    if not total:
        warnings.append("В пределах заданного ресурса получилась нулевая трудоёмкость. Проверьте регламент и нормативы")
    return {"title": problem.title, "resource": str(problem.resource), "flight_time": str(problem.flight_time),
            "flights_per_day": problem.flights_per_day, "flight_days": number(days), "flight_days_exact": str(days),
            "flights": number(resource / duration), "total_labor": number(total), "specific_labor": number(total / resource),
            "forms": output_forms, "operations": output_operations, "warnings": warnings,
            "rules": ["Старшая периодическая форма заменяет совпадающие младшие; нормы каждой формы задаются полностью",
                      "В момент первого ремонта периодическое обслуживание не учитывается",
                      "Промежуточные значения не округляются; трудоёмкости вводятся в чел·ч"]}
