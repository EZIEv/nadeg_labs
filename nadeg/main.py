from decimal import localcontext
from pathlib import Path
from threading import BoundedSemaphore
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import Field

from .errors import response_error, validation_payload
from . import lab3_ai
from .lab3 import Analysis
from .lab3_io import csv_analysis, pdf_analysis

from .diagram import svg
from .engine import Calculator, ModelError, calculate, optimize
from .export import csv_report, pdf_report
from .models import Problem, StrictModel
from .maintenance import MaintenanceSettings, MaintenanceProblem, calculate_maintenance
from .maintenance_io import ImportRegulation, import_regulation, csv_maintenance, pdf_maintenance

ROOT = Path(__file__).parent
app = FastAPI(title="NADEG", version="0.4.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
search_slots = BoundedSemaphore(2)


@app.middleware("http")
async def limits_and_headers(request: Request, call_next):
    if request.method == "POST":
        limit = 10 * 1024 * 1024 if request.url.path.startswith("/api/lab3/") else 131072
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > limit:
                return JSONResponse(response_error(f"Запрос слишком большой (максимум {limit // 1024} КБ)"), status_code=413)
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; object-src 'none'; frame-ancestors 'self'; base-uri 'self'"
    return response


@app.exception_handler(ModelError)
async def model_error(request, error):
    try:
        body = await request.json()
    except Exception:
        body = {}
    path = error.path
    if isinstance(body, dict) and "problem" in body:
        path = ["problem", *path]
    return JSONResponse(response_error(str(error), path=path, body=body), status_code=422)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    return JSONResponse(validation_payload(error), status_code=422)


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"lab": 1})


@app.get("/lab2")
def lab2(request: Request):
    return templates.TemplateResponse(request=request, name="lab2.html", context={"lab": 2})


@app.post("/api/lab2/calculate")
def maintenance_calculation(problem: MaintenanceProblem):
    return calculate_maintenance(problem)


@app.post("/api/lab2/validate")
def maintenance_settings(problem: MaintenanceSettings):
    return {"status": "ok"}


@app.post("/api/lab2/import")
def maintenance_import(payload: ImportRegulation):
    return import_regulation(payload)


@app.post("/api/lab2/export/{format}")
def maintenance_export(format: Literal["pdf", "csv"], problem: MaintenanceProblem):
    result = calculate_maintenance(problem)
    if format == "pdf":
        content, media = pdf_maintenance(problem, result), "application/pdf"
    else:
        content, media = csv_maintenance(problem, result), "text/csv; charset=utf-8"
    return Response(content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="nadeg-lab2.{format}"'})


@app.get("/health")
def health():
    return {"status": "ok"}


def response_with_diagram(problem, result):
    from .engine import parse
    result["svg"] = svg(parse(problem.expression, {e.id for e in problem.elements}), result["elements"])
    return result


@app.post("/api/lab1/validate")
def validate_lab1(problem: Problem):
    with localcontext() as ctx:
        ctx.prec = 60
        Calculator(problem)
    return {"status": "ok"}


@app.post("/api/analyze")
def analyze(problem: Problem):
    if "task" not in problem.model_fields_set:
        problem = problem.model_copy(update={"task": 1})
    return response_with_diagram(problem, calculate(problem))


@app.post("/api/optimize")
def optimize_system(problem: Problem):
    if "task" not in problem.model_fields_set:
        problem = problem.model_copy(update={"task": 2})
    if not search_slots.acquire(blocking=False):
        return JSONResponse(response_error("Сервер выполняет другие подборы. Повторите запрос немного позже"), status_code=429)
    try:
        return response_with_diagram(problem, optimize(problem))
    finally:
        search_slots.release()


class ExportRequest(StrictModel):
    problem: Problem
    allocation: list[Annotated[int, Field(strict=True, ge=0, le=12)]] | None = Field(default=None, max_length=40)


@app.post("/api/export/{format}")
def export(format: Literal["pdf", "csv", "svg"], payload: ExportRequest):
    problem = payload.problem
    if "task" not in problem.model_fields_set:
        problem = problem.model_copy(update={"task": 1})
    with localcontext() as context:
        context.prec = 60
        calculator = Calculator(problem)
        allocation = payload.allocation if payload.allocation is not None else [e.reserves for e in problem.elements]
        if len(allocation) != len(problem.elements) or any(isinstance(k, bool) or not isinstance(k, int) or not e.reserves <= k <= (e.max_reserves if e.reservable else e.reserves) for e, k in zip(problem.elements, allocation)):
            raise ModelError("Недопустимое распределение резервов для экспорта")
        result = calculator.summarize(tuple(allocation))
    if format == "pdf":
        content, media = pdf_report(problem, result), "application/pdf"
    elif format == "csv":
        content, media = csv_report(result), "text/csv; charset=utf-8"
    else:
        content, media = svg(calculator.tree, result["elements"]), "image/svg+xml"
    return Response(content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="nadeg-report.{format}"'})


@app.get("/lab3")
def lab3(request: Request):
    return templates.TemplateResponse(request=request, name="lab3.html", context={"lab": 3})


@app.get("/api/lab3/status")
def lab3_status():
    try:
        enabled = bool(lab3_ai.Settings.load().api_key)
    except lab3_ai.ReviewError:
        enabled = False
    return {"enabled": enabled}


@app.post("/api/lab3/validate")
def lab3_validate(analysis: Analysis):
    return {"status": "ok"}


@app.post("/api/lab3/analyze")
def lab3_analyze(analysis: Analysis, request: Request):
    try:
        return lab3_ai.analyze(analysis, request.client.host if request.client else "unknown")
    except lab3_ai.ReviewError as error:
        return JSONResponse(response_error(error.message), status_code=error.status)


@app.post("/api/lab3/export/{format}")
def lab3_export(format: Literal["pdf", "csv"], analysis: Analysis):
    if format == "pdf":
        content, media = pdf_analysis(analysis), "application/pdf"
    else:
        content, media = csv_analysis(analysis), "text/csv; charset=utf-8"
    return Response(content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="nadeg-lab3.{format}"'})
