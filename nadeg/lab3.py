"""Student-authored qualitative analysis and source-bound review contracts."""
import base64
import binascii
from io import BytesIO
from typing import Annotated, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import Field, StringConstraints, field_validator, model_validator

from .models import StrictModel

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
SourceId = Annotated[str, StringConstraints(pattern=r'^S[1-9][0-9]{0,2}$')]
RowId = Annotated[str, StringConstraints(pattern=r'^R[1-9][0-9]{0,2}$')]
ROW_FIELDS = ('condition', 'shortcoming', 'consequence', 'measure', 'justification')
LABELS = ('Условие воздействия', 'Конструктивный недостаток', 'Последствие', 'Мероприятие', 'Обоснование')


class Material(StrictModel):
    id: SourceId
    name: str = Field(min_length=1, max_length=160)
    text: str = Field(default='', max_length=10000)
    image: str = Field(default='', max_length=2800000)

    @field_validator('image')
    @classmethod
    def valid_image(cls, value):
        if not value:
            return value
        prefix, separator, encoded = value.partition(',')
        formats = {'data:image/png;base64': 'PNG', 'data:image/jpeg;base64': 'JPEG'}
        if not separator or prefix not in formats:
            raise ValueError('Допустимы только изображения PNG и JPEG в формате data URL')
        try:
            data = base64.b64decode(encoded, validate=True)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('Изображение больше 2 МБ')
            with Image.open(BytesIO(data)) as image:
                if image.format != formats[prefix] or image.width * image.height > 4_000_000:
                    raise ValueError('Изображение должно иметь не более 4 миллионов пикселей и соответствовать формату')
                image.verify()
        except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValueError('Не удалось прочитать изображение')
        return value

    @model_validator(mode='after')
    def has_content(self):
        if not self.text.strip() and not self.image:
            raise ValueError('Добавьте текст или изображение материала')
        return self


class AnalysisRow(StrictModel):
    id: RowId
    condition: Text = ''
    shortcoming: Text = ''
    consequence: Text = ''
    measure: Text = ''
    justification: Text = ''


class Analysis(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    purpose: str = Field(default='', max_length=4000)
    construction: str = Field(default='', max_length=6000)
    placement: str = Field(default='', max_length=4000)
    materials: list[Material] = Field(default_factory=list, max_length=8)
    rows: list[AnalysisRow] = Field(min_length=1, max_length=20)
    conclusion: str = Field(default='', max_length=6000)
    limitations: str = Field(default='', max_length=6000)

    @model_validator(mode='after')
    def unique_and_bounded(self):
        for items in (self.materials, self.rows):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError('Идентификаторы строк и материалов должны быть уникальными')
        images = [m.image for m in self.materials if m.image]
        if len(images) > 4 or sum(len(s) for s in images) > 8_400_000:
            raise ValueError('Не более 4 изображений, суммарно до 6 МБ')
        return self

    def require_student_work(self):
        if not any(any(getattr(row, field).strip() for field in ROW_FIELDS) for row in self.rows):
            raise ValueError('Сначала заполните хотя бы одну строку собственного анализа')


class Evidence(StrictModel):
    source_id: SourceId
    # Text quotes are verified literally. Image observations remain hypotheses.
    quote: str = Field(max_length=600)


class TechnicalBasis(StrictModel):
    kind: Literal['source', 'physical_principle', 'insufficient_data']
    explanation: str = Field(min_length=1, max_length=1600)
    assumptions: list[Annotated[str, StringConstraints(min_length=1, max_length=400)]] = Field(max_length=6)
    check: str = Field(min_length=1, max_length=1000)


class Suggestion(StrictModel):
    row_id: RowId | None
    field: Literal['condition', 'shortcoming', 'consequence', 'measure', 'justification']
    status: Literal['supported', 'hypothesis', 'missing_data']
    comment: str = Field(min_length=1, max_length=1600)
    replacement: str = Field(max_length=2000)
    evidence: list[Evidence] = Field(max_length=4)
    basis: TechnicalBasis


class Review(StrictModel):
    summary: str = Field(min_length=1, max_length=3000)
    suggestions: list[Suggestion] = Field(max_length=25)
    missing_information: list[Annotated[str, StringConstraints(max_length=800)]] = Field(max_length=12)


def validate_references(review: Review, analysis: Analysis):
    """Reject invented row/source links; downgrade claims without verifiable quotes."""
    sources = {m.id: m for m in analysis.materials}
    rows = {row.id for row in analysis.rows}
    for suggestion in review.suggestions:
        if suggestion.row_id is not None and suggestion.row_id not in rows:
            raise ValueError('Модель сослалась на несуществующую строку')
        for evidence in suggestion.evidence:
            if evidence.source_id not in sources:
                raise ValueError('Модель сослалась на несуществующий материал')
        verified = []
        for evidence in suggestion.evidence:
            source = sources[evidence.source_id]
            quote = evidence.quote.strip()
            if quote and quote in source.text:
                verified.append(evidence)
        if suggestion.status == 'supported' and not verified:
            suggestion.status = 'hypothesis'
        suggestion.evidence = verified
    return review


class Assessment(StrictModel):
    index: int = Field(ge=0, le=24, strict=True)
    verdict: Literal['consistent', 'uncertain', 'contradictory', 'unsupported']
    reason: str = Field(min_length=1, max_length=1200)


class GroundingReview(StrictModel):
    assessments: list[Assessment] = Field(max_length=25)
