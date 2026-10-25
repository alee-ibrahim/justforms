"""A form's approval settings and their checks (DESIGN 15.3).

Stored in ``forms.settings["approvals"]``, not in the form schema: the public form receives
the schema, and fixed approver addresses must not reach respondents. Steps that take the
approver's address from an email question are checked against the draft whenever the
settings are saved and again at publish.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints
from pydantic.alias_generators import to_camel

from app.logic.index import FormIndex
from app.schemas.form import EmailField, Form

MAX_STEPS = 3
# Addresses told about a step decided in the studio ("editors" steps).
MAX_NOTIFY = 10

StepName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
FieldId = Annotated[str, StringConstraints(max_length=63)]
Subject = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Message = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]


class ApiModel(BaseModel):
    """camelCase JSON like the API models (kept here to avoid importing the API package)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


class StepConfig(ApiModel):
    name: StepName
    # "field": the approver's address is the answer to an email question; "fixed": always this
    # address. Both get an emailed link and confirm with a code. "editors": no approver link at
    # all; only people with edit access to the form decide, signed in to the studio, and
    # ``notify`` (plus, with ``notify_editors``, those people) only get told about it.
    source: Literal["field", "fixed", "editors"]
    field_id: FieldId | None = None
    email: EmailStr | None = None
    notify: Annotated[list[EmailStr], Field(max_length=MAX_NOTIFY)] = Field(default_factory=list)
    notify_editors: bool = False


class ApprovalConfig(ApiModel):
    enabled: bool = False
    steps: Annotated[list[StepConfig], Field(max_length=MAX_STEPS)] = Field(default_factory=list)
    # Email the respondent the final outcome (with the signed PDF).
    notify_respondent: bool = True
    # The email question to send the outcome to; None = the confirmed (email code/staff) address.
    respondent_email_field: FieldId | None = None
    # Custom wording (plain text with the notification placeholders, DESIGN 11.1); empty or
    # missing = the built-in text. The request email can also list the non-sensitive answers.
    request_subject: Subject | None = None
    request_message: Message | None = None
    request_include_answers: bool = False
    outcome_approved_message: Message | None = None
    outcome_rejected_message: Message | None = None
    outcome_reply_to: EmailStr | None = None


def load_config(form_settings: dict[str, Any] | None) -> ApprovalConfig:
    raw = (form_settings or {}).get("approvals")
    if not raw:
        return ApprovalConfig()
    try:
        return ApprovalConfig.model_validate(raw)
    except ValueError:  # pragma: no cover - only valid configs are stored
        return ApprovalConfig()


def active(config: ApprovalConfig) -> bool:
    return config.enabled and bool(config.steps)


@dataclass(frozen=True)
class StepIssue:
    """A problem with one step (``step`` is 1-based; 0 for the outcome email)."""

    step: int
    code: str
    level: Literal["error", "warning"]
    message: str
    # The setting the issue is about, for issues that aren't about a step's approver.
    field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _always_on_path(form: Form, index: FormIndex, field_id: str) -> bool:
    """True when the question is shown to every respondent: no show-if on it, its sections
    or its page, and no earlier page can jump past its page."""
    info = index.elements[field_id]
    node: str | None = field_id
    while node is not None:
        if getattr(index.elements[node].element, "visible_if", None) is not None:
            return False
        node = index.elements[node].parent_id
    page_i = info.page_index
    if form.pages[page_i].visible_if is not None:
        return False
    for i in range(page_i):
        for rule in form.pages[i].next:
            target = (
                len(form.pages) if rule.goto == "submit" else index.page_index.get(rule.goto, -1)
            )
            if target > page_i:
                return False
    return True


def email_questions(form: Form) -> list[EmailField]:
    """Top-level email questions (not inside repeaters), in form order."""
    return [
        info.element
        for info in FormIndex.build(form).elements.values()
        if isinstance(info.element, EmailField) and info.repeater_id is None
    ]


def check_config(config: ApprovalConfig, form: Form, live: Form | None = None) -> list[StepIssue]:
    """Errors block saving and publishing; warnings are shown next to the step."""
    if not config.enabled:
        return []
    issues: list[StepIssue] = []
    if not config.steps:
        issues.append(StepIssue(0, "no_steps", "error", "Add at least one approval step"))
    index = FormIndex.build(form)
    live_ids = set(FormIndex.build(live).elements) if live is not None else None
    for n, step in enumerate(config.steps, start=1):
        if step.source == "editors":
            continue
        if step.source == "fixed":
            if not step.email:
                issues.append(
                    StepIssue(
                        n, "email_missing", "error", "Enter an email address like name@example.org"
                    )
                )
            continue
        if not step.field_id:
            issues.append(StepIssue(n, "field_missing", "error", "Choose a question"))
            continue
        info = index.elements.get(step.field_id)
        if info is None:
            issues.append(
                StepIssue(
                    n,
                    "source_missing",
                    "error",
                    f"Approval step {n} uses a question that isn't in the form",
                )
            )
            continue
        if not isinstance(info.element, EmailField) or info.repeater_id is not None:
            issues.append(
                StepIssue(
                    n,
                    "source_not_email",
                    "error",
                    f"Approval step {n} uses a question that isn't an email question",
                )
            )
            continue
        if not info.element.required:
            issues.append(
                StepIssue(
                    n,
                    "source_optional",
                    "warning",
                    "This question is optional. Responses without an answer wait until someone "
                    "stops the approval. Make it required.",
                )
            )
        elif not _always_on_path(form, index, step.field_id):
            issues.append(
                StepIssue(
                    n,
                    "source_conditional",
                    "warning",
                    "This question is only shown to some respondents. Responses that skip it "
                    "wait until someone stops the approval.",
                )
            )
        if live_ids is not None and step.field_id not in live_ids:
            issues.append(
                StepIssue(
                    n,
                    "source_unpublished",
                    "warning",
                    "This question isn't in the published form yet. Publish the form to use it.",
                )
            )
    if config.notify_respondent and config.respondent_email_field is not None:
        info = index.elements.get(config.respondent_email_field)
        if info is None or not isinstance(info.element, EmailField) or info.repeater_id:
            issues.append(
                StepIssue(
                    0,
                    "outcome_field_missing",
                    "error",
                    "The question for the outcome email isn't in the form. Choose another.",
                )
            )
    issues += _wording_issues(config, form)
    return issues


WORDING_FIELDS = (
    "request_subject",
    "request_message",
    "outcome_approved_message",
    "outcome_rejected_message",
)


def _wording_issues(config: ApprovalConfig, form: Form) -> list[StepIssue]:
    """Custom wording may only use placeholders that can be filled (DESIGN 11.1)."""
    from app.notifications.emails import unknown_placeholder

    issues: list[StepIssue] = []
    for name in WORDING_FIELDS:
        text = getattr(config, name) or ""
        if name == "request_subject" and ("\n" in text or "\r" in text):
            issues.append(
                StepIssue(0, "subject_one_line", "error", "Keep the subject on one line.", name)
            )
            continue
        bad = unknown_placeholder(text, form)
        if bad is not None:
            issues.append(
                StepIssue(
                    0,
                    "unknown_placeholder",
                    "error",
                    f"{bad} can't be filled in. You can use {{reference}}, {{form_title}}, "
                    "{submitted} and {answer:question_key}. Sensitive, signature and file "
                    "questions can't be used.",
                    name,
                )
            )
    return issues


def publish_problems(config: ApprovalConfig, form: Form) -> list[StepIssue]:
    """Errors that stop a form with approvals from being published."""
    return [
        i
        for i in check_config(config, form)
        if i.level == "error" and i.code in ("source_missing", "source_not_email")
    ]
