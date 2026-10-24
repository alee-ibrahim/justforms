"""JustForms form schema, spec format ``schemaVersion: "1"`` (docs/DESIGN.md section 4).

These Pydantic models are the **canonical** definition of a form. Everything else derives
from them: ``spec/form-schema.v1.json`` is exported from here (``uv run python -m
app.schemas.export``), the frontend TS types and zod schemas are generated from that file,
and the database stores documents that validate against :class:`Form`.

JSON field names are camelCase (``visibleIf``, ``patternMessage``); Python attributes are
snake_case. Always dump with ``by_alias=True`` (the default here via ``serialize_by_alias``).

A form is written in exactly one language (``settings.language``: ``en`` or ``dv``); every
user-facing text is a plain string in that language and the text direction derives from it
(``dv`` is right-to-left). There are no per-language translations.

Structural rules (unique ids, nesting limits, logic references, forward-only
``goto``, dependency cycles) are enforced by :func:`app.schemas.rules.check_form`, which
runs as the :class:`Form` model validator.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

SCHEMA_VERSION: Literal["1"] = "1"

ID_PATTERN = r"^[a-z][a-z0-9_]{0,62}$"

ElementId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]


class SchemaModel(BaseModel):
    """Base for every schema object: camelCase JSON, unknown keys rejected."""

    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


FormLanguage = Literal["en", "dv"]
"""Language of a form's content. ``dv`` (Dhivehi, Thaana script) is right-to-left."""

Text = Annotated[str, StringConstraints(max_length=10_000)]
"""User-facing text in the form's language (``settings.language``)."""


# --------------------------------------------------------------------------------------
# Conditions (section 5.1)
# --------------------------------------------------------------------------------------


class Op(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EMPTY = "empty"
    NOT_EMPTY = "not_empty"
    COUNT_EQ = "count_eq"
    COUNT_GTE = "count_gte"
    COUNT_LTE = "count_lte"


UNARY_OPS = frozenset({Op.EMPTY, Op.NOT_EMPTY})
LIST_OPS = frozenset({Op.IN, Op.NOT_IN})
COUNT_OPS = frozenset({Op.COUNT_EQ, Op.COUNT_GTE, Op.COUNT_LTE})
# Ops allowed when a condition references a repeater (its value is the list of rows).
REPEATER_OPS = UNARY_OPS | COUNT_OPS


class FieldCondition(SchemaModel):
    """Leaf condition: compare one value-producing field with ``value``."""

    field: ElementId
    op: Op
    value: JsonValue = None

    @model_validator(mode="after")
    def _value_matches_op(self) -> Self:
        given = "value" in self.model_fields_set
        if self.op in UNARY_OPS:
            if given:
                raise ValueError(f"op '{self.op}' takes no value")
        elif not given:
            raise ValueError(f"op '{self.op}' requires a value")
        elif self.op in LIST_OPS:
            if not isinstance(self.value, list):
                raise ValueError(f"op '{self.op}' requires an array value")
        elif self.op in COUNT_OPS and (
            isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < 0
        ):
            raise ValueError(f"op '{self.op}' requires a non-negative integer value")
        return self


class AllCondition(SchemaModel):
    """AND. An empty list is true."""

    all_: list[Condition] = Field(alias="all")


class AnyCondition(SchemaModel):
    """OR. An empty list is false."""

    any_: list[Condition] = Field(alias="any")


class NotCondition(SchemaModel):
    not_: Condition = Field(alias="not")


class Condition(RootModel[AllCondition | AnyCondition | NotCondition | FieldCondition]):
    root: AllCondition | AnyCondition | NotCondition | FieldCondition


# --------------------------------------------------------------------------------------
# Elements (section 4.2 / 4.3)
# --------------------------------------------------------------------------------------


class InputScript(StrEnum):
    AUTO = "auto"
    LATIN = "latin"
    THAANA = "thaana"


class Option(SchemaModel):
    value: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    label: Text


class ElementBase(SchemaModel):
    id: ElementId
    visible_if: Condition | None = None


class FieldBase(ElementBase):
    kind: Literal["field"]
    label: Text
    description: Text | None = None
    placeholder: Text | None = None
    required: bool = False
    required_if: Condition | None = None
    prefill_param: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")] | None = (
        None
    )
    sensitive: bool = False
    width: Literal["full", "half"] = "full"


class ShortTextField(FieldBase):
    type: Literal["short_text"]
    input_script: InputScript = InputScript.AUTO
    max_length: Annotated[int, Field(ge=1, le=10_000)] | None = None
    pattern: Annotated[str, StringConstraints(max_length=500)] | None = None
    pattern_message: Text | None = None


class LongTextField(FieldBase):
    type: Literal["long_text"]
    input_script: InputScript = InputScript.AUTO
    max_length: Annotated[int, Field(ge=1, le=100_000)] | None = None
    rows: Annotated[int, Field(ge=2, le=30)] | None = None


class EmailField(FieldBase):
    type: Literal["email"]


class PhoneField(FieldBase):
    type: Literal["phone"]
    default_country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] | None = None


class NumberField(FieldBase):
    type: Literal["number"]
    min: float | None = None
    max: float | None = None
    step: Annotated[float, Field(gt=0)] | None = None
    integer: bool = False

    @model_validator(mode="after")
    def _range(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"field '{self.id}': min must not exceed max")
        return self


DateBound = Annotated[str, StringConstraints(pattern=r"^(\d{4}-\d{2}-\d{2}|today([+-]\d{1,4})?)$")]


class DateField(FieldBase):
    type: Literal["date"]
    min_date: DateBound | None = None
    max_date: DateBound | None = None


class TimeField(FieldBase):
    type: Literal["time"]


class ChoiceFieldBase(FieldBase):
    options: Annotated[list[Option], Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def _unique_option_values(self) -> Self:
        values = [o.value for o in self.options]
        if len(values) != len(set(values)):
            raise ValueError(f"field '{self.id}': option values must be unique")
        return self


class SingleChoiceField(ChoiceFieldBase):
    type: Literal["single_choice"]
    display: Literal["radio", "dropdown"] = "radio"
    allow_other: bool = False


class MultiChoiceField(ChoiceFieldBase):
    type: Literal["multi_choice"]
    min_selected: Annotated[int, Field(ge=0)] | None = None
    max_selected: Annotated[int, Field(ge=1)] | None = None
    allow_other: bool = False

    @model_validator(mode="after")
    def _selection_range(self) -> Self:
        lo, hi = self.min_selected, self.max_selected
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"field '{self.id}': minSelected must not exceed maxSelected")
        return self


class YesNoField(FieldBase):
    type: Literal["yes_no"]


class RatingField(FieldBase):
    type: Literal["rating"]
    max: Annotated[int, Field(ge=3, le=10)] = 5


class FileField(FieldBase):
    type: Literal["file"]
    accept: list[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = Field(
        default_factory=list
    )
    max_files: Annotated[int, Field(ge=1, le=50)] = 1
    max_size_mb: Annotated[int, Field(ge=1, le=10_000)] | None = None


class SignatureField(FieldBase):
    type: Literal["signature"]
    attestation: Text | None = None


class HiddenField(FieldBase):
    type: Literal["hidden"]


FieldElement = Annotated[
    ShortTextField
    | LongTextField
    | EmailField
    | PhoneField
    | NumberField
    | DateField
    | TimeField
    | SingleChoiceField
    | MultiChoiceField
    | YesNoField
    | RatingField
    | FileField
    | SignatureField
    | HiddenField,
    Field(discriminator="type"),
]

FIELD_TYPES: tuple[str, ...] = (
    "short_text",
    "long_text",
    "email",
    "phone",
    "number",
    "date",
    "time",
    "single_choice",
    "multi_choice",
    "yes_no",
    "rating",
    "file",
    "signature",
    "hidden",
)


class ContentElement(ElementBase):
    kind: Literal["content"]
    content_type: Literal["heading", "paragraph", "divider", "image"]
    text: Text | None = None
    image_file_id: Annotated[str, StringConstraints(max_length=100)] | None = None

    @model_validator(mode="after")
    def _text_for_type(self) -> Self:
        if self.content_type in ("heading", "paragraph") and self.text is None:
            raise ValueError(f"content '{self.id}': {self.content_type} requires text")
        return self


class SectionElement(ElementBase):
    kind: Literal["section"]
    title: Text | None = None
    description: Text | None = None
    elements: list[Element] = Field(default_factory=list)


class RepeaterElement(ElementBase):
    kind: Literal["repeater"]
    label: Text
    description: Text | None = None
    min_rows: Annotated[int, Field(ge=0, le=1000)] = 0
    max_rows: Annotated[int, Field(ge=1, le=1000)] | None = None
    add_label: Text | None = None
    elements: list[Element] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rows(self) -> Self:
        if self.max_rows is not None and self.min_rows > self.max_rows:
            raise ValueError(f"repeater '{self.id}': minRows must not exceed maxRows")
        return self


Element = Annotated[
    FieldElement | ContentElement | SectionElement | RepeaterElement,
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------------------
# Pages, settings, form
# --------------------------------------------------------------------------------------


class NavigationRule(SchemaModel):
    """``{"if": Condition, "goto": PageId | "submit"}``. ``goto`` may only jump forward."""

    if_: Condition = Field(alias="if")
    goto: ElementId


class Page(SchemaModel):
    id: ElementId
    title: Text | None = None
    description: Text | None = None
    visible_if: Condition | None = None
    elements: list[Element] = Field(default_factory=list)
    next: list[NavigationRule] = Field(default_factory=list)


HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class Theme(SchemaModel):
    accent: HexColor | None = None
    logo_file_id: Annotated[str, StringConstraints(max_length=100)] | None = None


class Settings(SchemaModel):
    language: FormLanguage = "en"
    title: Text
    description: Text | None = None
    submit_label: Text | None = None
    # The wizard's Next and Back buttons; English "Next"/"Back" when empty.
    next_label: Text | None = None
    back_label: Text | None = None
    success_message: Text | None = None
    theme: Theme = Field(default_factory=Theme)


RTL_LANGUAGES: frozenset[str] = frozenset({"dv"})


def text_direction(language: str) -> Literal["ltr", "rtl"]:
    """Text direction for a form language: ``dv`` is right-to-left, ``en`` left-to-right."""
    return "rtl" if language in RTL_LANGUAGES else "ltr"


class Form(SchemaModel):
    """A complete form document (draft or published version)."""

    model_config = ConfigDict(title="JustFormsForm")

    schema_version: Literal["1"] = SCHEMA_VERSION
    settings: Settings
    pages: Annotated[list[Page], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def _structure_and_logic(self) -> Self:
        from app.schemas.rules import check_form

        check_form(self)
        return self

    def dump(self) -> dict[str, Any]:
        """JSON-ready dict with camelCase keys and defaults omitted where unset."""
        return self.model_dump(mode="json", by_alias=True, exclude_unset=True)


for _model in (AllCondition, AnyCondition, NotCondition, SectionElement, RepeaterElement, Page):
    _model.model_rebuild()
Condition.model_rebuild()
