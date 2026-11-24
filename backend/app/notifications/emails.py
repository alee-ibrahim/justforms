"""Notification emails (DESIGN 11.1): owner notification, respondent receipt, respondent
sign-in code, approval requests and outcomes, and webhook warnings. Rendered as HTML and text
with Jinja2.

All wording is English for every form: system text is never translated. Only form content (the
form title, question labels, answers, the builder's success message, approval step names) can be
Dhivehi, English or both. A form has no language: in HTML each such piece carries its own
``lang``/``dir`` from its text (first strong character) and an ``align`` from the element's
``align`` / ``settings.align`` (``settings.titleAlign`` for the title), or is isolated with
``<bdi>`` inside an English sentence, so Dhivehi reads right to left inside the left-to-right
email. Sensitive answers are never emailed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from jinja2 import DictLoader, Environment, select_autoescape
from markupsafe import Markup, escape

from app.answers import answer_text
from app.config import Settings
from app.logic.index import FormIndex
from app.schemas.direction import (
    bilingual_parts,
    explicit_align,
    has_thaana,
    is_rtl,
    isolate_runs,
    resolve_align,
    text_direction,
    text_lang,
    text_lines,
)
from app.schemas.form import (
    DateField,
    EmailField,
    FieldElement,
    FileField,
    Form,
    NumberField,
    PhoneField,
    RepeaterElement,
    SignatureField,
    SingleChoiceField,
    TimeField,
    YesNoField,
)

# Respondent- and approver-facing wording (English for every form).
WORDS: dict[str, str] = {
    "receipt_subject": "Your response to {title} ({reference})",
    "receipt_intro": "Thank you. We received your response to this form.",
    "reference": "Reference",
    "submitted": "Submitted",
    "your_answers": "Your answers",
    "pdf_attached": "The signed PDF of your response is attached.",
    "code_subject": "Your code for {title}",
    "code_body": "Your code is {code}. It works for {minutes} minutes.",
    "code_ignore": "If you didn't ask for this code, you can ignore this email.",
    "entry": "Entry {n}",
    "approval_subject": "Approval needed: {title} ({reference})",
    "approval_body": "{step}: please approve or reject response {reference} to {title}. "
    "It was submitted on {date}.",
    "approval_step_of": "Step {n} of {total}.",
    "approval_button": "Open the response",
    "approval_approve": "Approve",
    "approval_reject": "Reject",
    "approval_open": "Or open the response to read it first",
    "approval_note": "Each button opens the response. You'll confirm your email with a code, "
    "then confirm your decision there. The link works for {days} days.",
    "notice_subject": "New response to review: {title} ({reference})",
    "notice_kicker": "Waiting for a decision",
    "notice_body": "{step}: response {reference} to {title} is waiting for a decision. "
    "It was submitted on {date}.",
    "notice_button": "Open in {product}",
    "notice_note": "Sign in to approve or reject it. Only people with edit access to the form "
    "can decide.",
    "outcome_subject_approved": "Approved: {title} ({reference})",
    "outcome_subject_rejected": "Not approved: {title} ({reference})",
    "outcome_approved": "Your response {reference} was approved.",
    "outcome_rejected": "Your response {reference} was not approved.",
    "outcome_comment": "Comment",
    "outcome_reference": "Reference",
    "outcome_pdf": "The signed PDF is attached.",
}

LTR_FIELDS = (EmailField, PhoneField, NumberField, DateField, TimeField, YesNoField)


def _iso(text: str) -> str:
    """Form content (a title, a step name) inside a plain-text English line (subject, text
    body): a right-to-left text is wrapped in FSI ... PDI so the reference or punctuation
    after it stays in English order ("(#0042)" not "(0042#)")."""
    return f"\u2068{text}\u2069" if is_rtl(text) else text


_TEMPLATES = {
    "layout.html": """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{{ subject }}</title></head>
<body style="margin:0;padding:24px;background:#F3F5F9;color:#18203A;font-family:Inter,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;font-size:15px;line-height:1.5">
{% if brand.custom %}<div style="max-width:560px;margin:0 auto 12px">{% if brand.logo_url %}<img src="{{ brand.logo_url }}" alt="{{ brand.name }}" height="32" style="display:block;height:32px;max-width:240px;border:0">{% else %}<strong style="font-size:16px;color:#18203A">{{ brand.name }}</strong>{% endif %}</div>
{% endif %}<div style="max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid #DCE0EA;border-radius:6px;padding:28px">
{% block body %}{% endblock %}
</div>
<p style="max-width:560px;margin:16px auto 0;color:#5A6380;font-size:12px">Sent by {{ brand.name }}.{% if brand.support_url %} <a href="{{ brand.support_url }}" style="color:#5A6380">Get help</a>{% endif %}{% if brand.powered_by and brand.name != "JustForms" %} Powered by JustForms.{% endif %}</p>
</body></html>""",
    "answers.html": """{% if answers %}
<table role="presentation" style="width:100%;border-collapse:collapse;margin-top:8px">
{% for a in answers %}
{% set l = a.label_block %}{% set v = a.value_block %}
<tr><td style="padding:8px 0;border-top:1px solid #DCE0EA;text-align:{{ a.cell_align }}" align="{{ a.cell_align }}">
<div lang="{{ l.lang }}" dir="{{ l.dir }}" align="{{ l.align }}" style="color:#3A425E;font-size:{{ l.px }}px;line-height:1.75;text-align:{{ l.align }}{{ l.font }}">{{ a.label|bilingual(l.dir, a.explicit is none) }}</div>
{% if a.value_lines %}<div style="white-space:pre-wrap;font-size:{{ v.px }}px;line-height:1.75">{{ a.value_lines }}</div></td></tr>{% else %}<div lang="{{ v.lang }}" dir="{{ v.dir }}" align="{{ v.align }}" style="white-space:pre-wrap;font-size:{{ v.px }}px;line-height:1.75;text-align:{{ v.align }}{{ v.font }}">{% if a.ltr %}<bdi dir="ltr" style="font-family:Inter,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif">{{ a.value }}</bdi>{% else %}{{ a.value|bilingual(v.dir, a.split_value) }}{% endif %}</div></td></tr>{% endif %}
{% endfor %}
</table>
{% endif %}""",
    "owner.html": """{% extends "layout.html" %}{% block body %}
<p style="margin:0 0 4px;color:#5A6380">New response</p>
<h1 style="margin:0 0 16px;font-size:20px;text-align:{{ align }}{{ font }}" lang="{{ lang }}" dir="{{ dir }}" align="{{ align }}">{{ title|bilingual(dir, split) }}</h1>
{% if message %}<div style="margin:0 0 16px;white-space:pre-wrap" dir="auto">{{ message|paragraphs }}</div>
{% endif %}<p style="margin:0 0 16px">Reference <strong>{{ reference }}</strong>, submitted {{ submitted }}{% if respondent %} by <bdi>{{ respondent }}</bdi>{% endif %}.</p>
<p style="margin:0 0 20px"><a href="{{ url }}" style="display:inline-block;background:{{ brand.button_bg }};color:{{ brand.button_fg }};text-decoration:none;padding:10px 16px;border-radius:6px">Open the submission</a></p>
{% if answers %}{% include "answers.html" %}{% else %}<p style="color:#5A6380;margin:0">Answers are not included in this email. Open the submission to read them.</p>{% endif %}
{% endblock %}""",
    "owner.txt": """New response to {{ title }}

{% if message %}{{ message }}

{% endif %}Reference {{ reference }}, submitted {{ submitted }}{% if respondent %} by {{ respondent }}{% endif %}.

Open the submission: {{ url }}
{% if answers %}
{% for a in answers %}
{{ a.label }}
{{ a.value }}
{% endfor %}{% else %}
Answers are not included in this email.
{% endif %}""",
    "receipt.html": """{% extends "layout.html" %}{% block body %}
<h1 style="margin:0 0 12px;font-size:20px;text-align:{{ align }}{{ font }}" lang="{{ lang }}" dir="{{ dir }}" align="{{ align }}">{{ title|bilingual(dir, split) }}</h1>
{% if message %}<div style="margin:0 0 16px;white-space:pre-wrap" dir="auto">{{ message|paragraphs }}</div>
{% elif success_lines %}<div style="margin:0 0 16px;white-space:pre-wrap">{{ success_lines }}</div>
{% elif success %}<p style="margin:0 0 16px;white-space:pre-wrap;text-align:{{ s.align }}{{ s.font }}" lang="{{ s.lang }}" dir="{{ s.dir }}" align="{{ s.align }}">{{ success|runs(s.dir) }}</p>
{% else %}<p style="margin:0 0 16px">{{ w.receipt_intro }}</p>
{% endif %}
<p style="margin:0 0 4px">{{ w.reference }}: <strong>{{ reference }}</strong></p>
<p style="margin:0 0 16px">{{ w.submitted }}: {{ submitted }}</p>
{% if pdf %}<p style="margin:0 0 16px">{{ w.pdf_attached }}</p>{% endif %}
{% if answers %}<h2 style="margin:16px 0 0;font-size:16px">{{ w.your_answers }}</h2>{% include "answers.html" %}{% endif %}
{% endblock %}""",
    "receipt.txt": """{{ title }}

{{ message or success or w.receipt_intro }}

{{ w.reference }}: {{ reference }}
{{ w.submitted }}: {{ submitted }}
{% if pdf %}
{{ w.pdf_attached }}
{% endif %}{% if answers %}
{{ w.your_answers }}
{% for a in answers %}
{{ a.label }}
{{ a.value }}
{% endfor %}{% endif %}""",
    "code.html": """{% extends "layout.html" %}{% block body %}
<h1 style="margin:0 0 12px;font-size:20px;text-align:{{ align }}{{ font }}" lang="{{ lang }}" dir="{{ dir }}" align="{{ align }}">{{ title|bilingual(dir, split) }}</h1>
<p style="margin:0 0 12px">{{ body }}</p>
<p style="margin:0 0 16px;font-size:28px;letter-spacing:4px;font-family:Inter,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;font-variant-numeric:tabular-nums">{{ code }}</p>
<p style="margin:0;color:#5A6380">{{ w.code_ignore }}</p>
{% endblock %}""",
    "code.txt": """{{ title }}

{{ body }}

{{ w.code_ignore }}
""",
    "approval_request.html": """{% extends "layout.html" %}{% block body %}
<p style="margin:0 0 4px;color:#5A6380">{{ kicker }}</p>
<h1 style="margin:0 0 12px;font-size:20px;text-align:{{ align }}{{ font }}" lang="{{ lang }}" dir="{{ dir }}" align="{{ align }}">{{ title|bilingual(dir, split) }}</h1>
{% if message %}<div style="margin:0 0 16px;white-space:pre-wrap" dir="auto">{{ message|paragraphs }}</div>
{% endif %}<p style="margin:0 0 {{ '8' if step_of else '20' }}px">{{ body }}</p>
{% if step_of %}<p style="margin:0 0 20px;color:#5A6380">{{ step_of }}</p>
{% endif %}
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 12px;border-collapse:separate"><tr>
<td style="padding:0 8px 8px 0"><a href="{{ approve_url }}" style="display:inline-block;min-width:96px;text-align:center;background:{{ brand.button_bg }};color:{{ brand.button_fg }};border:1px solid {{ brand.button_bg }};text-decoration:none;font-weight:bold;padding:10px 18px;border-radius:6px">{{ w.approval_approve }}</a></td>
<td style="padding:0 0 8px 0"><a href="{{ reject_url }}" style="display:inline-block;min-width:96px;text-align:center;background:#FFFFFF;color:#B42318;border:1px solid #B42318;text-decoration:none;font-weight:bold;padding:10px 18px;border-radius:6px">{{ w.approval_reject }}</a></td>
</tr></table>
<p style="margin:0 0 20px"><a href="{{ url }}" style="color:{{ brand.button_bg }}">{{ w.approval_open }}</a></p>
{% if answers %}{% include "answers.html" %}<div style="height:16px"></div>
{% endif %}<p style="margin:0;color:#5A6380">{{ note }}</p>
{% endblock %}""",
    "approval_request.txt": """{{ title }}

{% if message %}{{ message }}

{% endif %}{{ body_text }}
{% if step_of %}{{ step_of }}
{% endif %}

{{ w.approval_approve }}: {{ approve_url }}
{{ w.approval_reject }}: {{ reject_url }}
{{ w.approval_open }}: {{ url }}
{% if answers %}
{% for a in answers %}
{{ a.label }}
{{ a.value }}
{% endfor %}{% endif %}

{{ note }}
""",
    "approval_notice.html": """{% extends "layout.html" %}{% block body %}
<p style="margin:0 0 4px;color:#5A6380">{{ kicker }}</p>
<h1 style="margin:0 0 12px;font-size:20px;text-align:{{ align }}{{ font }}" lang="{{ lang }}" dir="{{ dir }}" align="{{ align }}">{{ title|bilingual(dir, split) }}</h1>
{% if message %}<div style="margin:0 0 12px;white-space:pre-wrap" dir="auto">{{ message|paragraphs }}</div>
<p style="margin:0 0 {{ '8' if step_of else '20' }}px">{{ w.reference }} <strong>{{ reference }}</strong></p>
{% else %}<p style="margin:0 0 {{ '8' if step_of else '20' }}px">{{ body }}</p>
{% endif %}{% if step_of %}<p style="margin:0 0 20px;color:#5A6380">{{ step_of }}</p>
{% endif %}
<p style="margin:0 0 20px"><a href="{{ url }}" style="display:inline-block;background:{{ brand.button_bg }};color:{{ brand.button_fg }};text-decoration:none;font-weight:bold;padding:10px 18px;border-radius:6px">{{ button }}</a></p>
{% if answers %}{% include "answers.html" %}<div style="height:16px"></div>
{% endif %}<p style="margin:0;color:#5A6380">{{ note }}</p>
{% endblock %}""",
    "approval_notice.txt": """{{ title }}

{% if message %}{{ message }}

{{ w.reference }} {{ reference }}
{% else %}{{ body_text }}
{% endif %}{% if step_of %}{{ step_of }}
{% endif %}

{{ button }}: {{ url }}
{% if answers %}
{% for a in answers %}
{{ a.label }}
{{ a.value }}
{% endfor %}{% endif %}

{{ note }}
""",
    "outcome.html": """{% extends "layout.html" %}{% block body %}
<h1 style="margin:0 0 12px;font-size:20px;text-align:{{ align }}{{ font }}" lang="{{ lang }}" dir="{{ dir }}" align="{{ align }}">{{ title|bilingual(dir, split) }}</h1>
{% if message %}<div style="margin:0 0 16px;white-space:pre-wrap" dir="auto">{{ message|paragraphs }}</div>
<p style="margin:0 0 16px">{{ w.outcome_reference }}: <strong>{{ reference }}</strong></p>
{% else %}<p style="margin:0 0 16px">{{ body }}</p>
{% endif %}
{% if comment %}<p style="margin:0 0 4px;color:#5A6380">{{ w.outcome_comment }}</p>
<div style="margin:0 0 16px;white-space:pre-wrap" dir="auto">{{ comment|paragraphs }}</div>{% endif %}
{% if pdf %}<p style="margin:0">{{ w.outcome_pdf }}</p>{% endif %}
{% endblock %}""",
    "outcome.txt": """{{ title }}

{% if message %}{{ message }}

{{ w.outcome_reference }}: {{ reference }}
{% else %}{{ body_text }}
{% endif %}{% if comment %}
{{ w.outcome_comment }}:
{{ comment }}
{% endif %}{% if pdf %}
{{ w.outcome_pdf }}
{% endif %}""",
    "invitation.html": """{% extends "layout.html" %}{% block body %}
<h1 style="margin:0 0 12px;font-size:20px">Join <bdi dir="auto">{{ org_name }}</bdi></h1>
<p style="margin:0 0 16px">{{ intro }}</p>
{% if forms %}<p style="margin:0 0 4px">They shared these forms with you:</p>
{% for f in forms %}<p lang="{{ f.lang }}" dir="{{ f.dir }}" align="{{ f.align }}" style="margin:0 0 4px;font-weight:bold;text-align:{{ f.align }}{{ f.font }}">{{ f.title|runs(f.dir) }}</p>
{% endfor %}<div style="height:12px"></div>
{% endif %}
<p style="margin:0 0 20px"><a href="{{ url }}" style="display:inline-block;background:{{ brand.button_bg }};color:{{ brand.button_fg }};text-decoration:none;padding:10px 16px;border-radius:6px">Accept the invitation</a></p>
<p style="margin:0 0 8px;color:#5A6380">{{ how }}</p>
<p style="margin:0;color:#5A6380">The link works until {{ until }}. If you weren't expecting this, you can ignore this email.</p>
{% endblock %}""",
    "invitation.txt": """Join {{ org_name }}

{{ intro }}
{% if forms %}
They shared these forms with you:
{% for f in forms %}- {{ f.title_text }}
{% endfor %}{% endif %}

Accept the invitation: {{ url }}

{{ how }}
The link works until {{ until }}. If you weren't expecting this, you can ignore this email.
""",
    "form_shared.html": """{% extends "layout.html" %}{% block body %}
<p style="margin:0 0 4px;color:#5A6380">{{ kicker }}</p>
<h1 style="margin:0 0 16px;font-size:20px;text-align:{{ align }}{{ font }}" lang="{{ lang }}" dir="{{ dir }}" align="{{ align }}">{{ title|bilingual(dir, split) }}</h1>
<p style="margin:0 0 16px">{{ body }}</p>
{% if note %}<p style="margin:0 0 4px;color:#5A6380"><bdi dir="auto">{{ sharer }}</bdi> wrote:</p>
<p style="margin:0 0 20px;padding:4px 0 4px 12px;border-left:3px solid #DCE0EA;white-space:pre-wrap" dir="auto">{{ note }}</p>
{% endif %}<p style="margin:0 0 20px"><a href="{{ url }}" style="display:inline-block;background:{{ brand.button_bg }};color:{{ brand.button_fg }};text-decoration:none;padding:10px 16px;border-radius:6px">{{ button }}</a></p>
<p style="margin:0;color:#5A6380">You're getting this email because <bdi dir="auto">{{ sharer }}</bdi> changed who has access to this form. Replies go to them.</p>
{% endblock %}""",
    "form_shared.txt": """{{ title_text }}

{{ body_text }}
{% if note %}

{{ sharer }} wrote:
{{ note }}
{% endif %}

{{ button }}: {{ url }}

You're getting this email because {{ sharer }} changed who has access to this form. Replies go to them.
""",
    "webhook_disabled.txt": """A webhook for "{{ title }}" was turned off

JustForms stopped sending to {{ url }} after {{ failures }} failed deliveries in a row.
Fix the endpoint, then turn the webhook back on in the form's Settings:
{{ settings_url }}
""",
}

_env = Environment(
    loader=DictLoader(_TEMPLATES),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass
class Message:
    subject: str
    text: str
    html: str | None = None
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)
    # Display name in the From header ("Example Office" <address from JUSTFORMS_SMTP_FROM>).
    from_name: str | None = None
    # Where replies go (the rule's Reply-To address).
    reply_to: str | None = None


@dataclass(frozen=True)
class EmailBrand:
    """Who the email is from (the organisation's effective branding, DESIGN 18.2)."""

    name: str = "JustForms"
    logo_url: str | None = None  # absolute URL of a PNG (mail clients don't show SVG)
    support_url: str | None = None
    powered_by: bool = True
    custom: bool = False
    button_bg: str = "#3B3FC1"
    button_fg: str = "#FFFFFF"

    def footer_text(self) -> str:
        parts = [f"Sent by {self.name}."]
        if self.support_url:
            parts.append(f"Get help: {self.support_url}")
        if self.powered_by and self.name != "JustForms":
            parts.append("Powered by JustForms.")
        return "\n\n--\n" + " ".join(parts) + "\n"


def _brand(brand: EmailBrand | None, org_name: str) -> EmailBrand:
    return brand or EmailBrand(name=org_name or "JustForms")


def _message(brand: EmailBrand, subject: str, text: str, html: str | None) -> Message:
    return Message(
        subject=subject, text=text + brand.footer_text(), html=html, from_name=brand.name
    )


@dataclass
class Answer:
    label: str
    value: str
    # Latin data (email, phone, number, date, time) and Yes / No: kept left to right.
    ltr: bool = False
    # The question's ``align`` resolved with the form's (``None``: its label's direction).
    align: str | None = None
    # The explicit left/center/right it resolves to; ``None`` (auto): each paragraph of a
    # multi-line answer aligns to its own direction.
    explicit: str | None = None
    # A chosen option with auto alignment: a bilingual option is shown English left, Dhivehi
    # right.
    split_value: bool = False

    @property
    def cell_align(self) -> str:
        return self.align or ("right" if is_rtl(self.label) else "left")

    @property
    def label_block(self) -> dict[str, str]:
        return _block(self.label, self.cell_align, label=True)

    @property
    def value_lines(self) -> Markup | None:
        """A multi-line answer, one block per line in its own direction (None: one line)."""
        if self.ltr or not (_multiline(self.value) or self.explicit == "justify"):
            return None
        return paragraphs_html(self.value, self.explicit, px=("15", "18"))

    @property
    def value_block(self) -> dict[str, str]:
        return _block("1" if self.ltr else self.value, self.cell_align)


@dataclass(frozen=True)
class Wording:
    """An owner's custom subject and opening text (placeholders already filled) and the
    Reply-To address. ``None`` keeps the built-in wording."""

    subject: str | None = None
    message: str | None = None
    reply_to: str | None = None


# Placeholders in custom wording (DESIGN 11.1): {reference}, {form_title}, {submitted} and
# {answer:<question key>}. Anything else is left as typed (and refused when saving).
PLACEHOLDER = re.compile(r"\{([a-z_]+)(?::([A-Za-z0-9_]+))?\}")
PLACEHOLDERS = ("reference", "form_title", "submitted")


def placeholder_fields(form: Form) -> dict[str, FieldElement]:
    """Questions an ``{answer:key}`` placeholder may name: not in a repeater, not sensitive,
    not a signature or file."""
    out: dict[str, FieldElement] = {}
    for info in FormIndex.build(form).elements.values():
        el = info.element
        if info.kind != "field" or info.repeater_id is not None:
            continue
        if getattr(el, "sensitive", False) or isinstance(el, (SignatureField, FileField)):
            continue
        out[info.id] = el  # type: ignore[assignment]
    return out


def unknown_placeholder(text: str, form: Form) -> str | None:
    """The first placeholder ``text`` uses that can't be filled, or None."""
    fields = placeholder_fields(form)
    for m in PLACEHOLDER.finditer(text):
        name, key = m.groups()
        if key is None and name in PLACEHOLDERS:
            continue
        if name == "answer" and key in fields:
            continue
        return m.group(0)
    return None


def fill(text: str, values: dict[str, str], answers: dict[str, str]) -> str:
    def one(m: re.Match[str]) -> str:
        name, key = m.groups()
        if key is None and name in values:
            return values[name]
        if name == "answer" and key is not None:
            return answers.get(key, "")
        return m.group(0)

    return PLACEHOLDER.sub(one, text)


def placeholder_answers(form: Form, data: dict[str, Any]) -> dict[str, str]:
    return {
        key: answer_text(el, data.get(key), display=True)
        for key, el in placeholder_fields(form).items()
    }


def one_line(text: str, limit: int = 250) -> str:
    """A filled subject: one line (answers can hold newlines), within ``limit``."""
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


# Thaana face for Dhivehi answers (CLAUDE.md "Fonts"); mail clients without it fall back.
THAANA_FONT = ";font-family:'MV Faseyha',Faruma,'Noto Sans Thaana',sans-serif"


def _block(text: str, align: str | None = None, *, label: bool = False) -> dict[str, str]:
    """Template values for one piece of form content (a title, a label, an answer, the success
    message): its own ``lang`` and ``dir`` from its text, and ``align`` (an explicit
    ``left``/``center``/``right``, else the text's direction) repeated as an attribute for
    clients that ignore ``dir`` on blocks. The email itself is English and left to right.
    Thaana text gets the Thaana face and the Thaana scale (16 px labels, 18 px answers,
    DESIGN-SYSTEM 4.2)."""
    direction = text_direction(text)
    thaana = has_thaana(text)
    return {
        "lang": text_lang(text),
        "dir": direction,
        "align": resolve_align(align, None, direction),
        "font": THAANA_FONT if thaana else "",
        "px": ("16" if thaana else "13") if label else ("18" if thaana else "15"),
    }


def _multiline(text: str | None) -> bool:
    return bool(text) and ("\n" in text or "\r" in text)  # type: ignore[operator]


def paragraphs_html(
    text: str, align: str | None = None, *, px: tuple[str, str] | None = None
) -> Markup:
    """Multi-line form content (a long answer, the success message, a custom message) as one
    ``<div>`` per line: each line break-separated paragraph has its own ``lang``/``dir`` from
    its dominant script, so an English paragraph followed by Dhivehi ones reads left to right,
    then right to left. ``align`` (explicit left/center/right) applies to every line; ``None``
    (auto) aligns each line to its own direction; ``justify`` justifies each paragraph's
    wrapped lines with its last line at its own start edge. ``px``: Latin and Thaana sizes."""
    out = []
    for line in text_lines(text):
        own = "right" if line["dir"] == "rtl" else "left"
        side = own if align in (None, "justify") else align
        css = f"justify;text-align-last:{own}" if align == "justify" else side
        thaana = has_thaana(line["text"])
        size = f";font-size:{px[1] if thaana else px[0]}px" if px else ""
        out.append(
            Markup('<div lang="{}" dir="{}" align="{}" style="text-align:{}{}{}">{}</div>').format(
                line["lang"],
                line["dir"],
                side,
                css,
                size,
                Markup(THAANA_FONT if thaana else ""),
                runs_html(line["text"], line["dir"]) if line["text"].strip() else Markup("&nbsp;"),
            )
        )
    return Markup("").join(out)


def runs_html(text: Any, direction: str | None = None) -> Markup:
    """Form content for HTML, escaped, with runs of the other script isolated in ``<bdi>``
    in their own direction and language (``isolate_runs``), so brackets and punctuation next
    to them stay on the side of the surrounding text ("(PPY)" inside Dhivehi)."""
    text = "" if text is None else str(text)
    base = direction if direction in ("ltr", "rtl") else None
    return Markup("").join(
        Markup('<bdi dir="{}" lang="{}">{}</bdi>').format(d, "dv" if d == "rtl" else "en", chunk)
        if d
        else escape(chunk)
        for chunk, d in isolate_runs(text, base)  # type: ignore[arg-type]
    )


def _paragraphs_filter(text: Any) -> Markup | str:
    """Jinja ``paragraphs``: multi-line text per line (auto alignment); one line as is (the
    element around it has ``dir="auto"``)."""
    text = "" if text is None else str(text)
    return paragraphs_html(text) if _multiline(text) else text


def bilingual_html(text: Any, direction: str | None = None, split: bool = False) -> Markup:
    """Form content for HTML (``runs_html``); with ``split`` (auto alignment) a bilingual
    one-line text ("Full name: ފުރިހަމަ ނަން", ``bilingual_parts``) is one row of two cells,
    English at the left and Dhivehi at the right (a table: mail clients ignore flex)."""
    text = "" if text is None else str(text)
    parts = bilingual_parts(text) if split else None
    if parts is None:
        return runs_html(text, direction)
    return Markup(
        '<table role="presentation" width="100%" style="width:100%;border-collapse:collapse">'
        '<tr><td lang="en" dir="ltr" align="left" style="padding:0 12px 0 0;text-align:left;'
        "vertical-align:top;font-family:Inter,'Segoe UI',Roboto,'Helvetica Neue',Arial,"
        'sans-serif">{}</td><td lang="dv" dir="rtl" align="right" style="padding:0;'
        'text-align:right;vertical-align:top{}">{}</td></tr></table>'
    ).format(runs_html(parts["ltr"], "ltr"), Markup(THAANA_FONT), runs_html(parts["rtl"], "rtl"))


_env.filters["paragraphs"] = _paragraphs_filter
_env.filters["runs"] = runs_html
_env.filters["bilingual"] = bilingual_html


def _title(title: str, form: Form | None = None) -> dict[str, Any]:
    """``lang``/``dir``/``align``/``font``/``split`` template values of the form title: aligned by
    ``settings.titleAlign``, else ``settings.align``, else its direction."""
    align = None
    split = True
    if form is not None:
        align = resolve_align(form.settings.title_align, form.settings.align, text_direction(title))
        split = explicit_align(form.settings.title_align, form.settings.align) is None
    block: dict[str, Any] = _block(title, align)
    del block["px"]
    # Auto alignment: a bilingual title is shown as one row, English left and Dhivehi right.
    block["split"] = split
    return block


def _success(form: Form) -> dict[str, str]:
    text = form.settings.success_message or ""
    return _block(text, resolve_align(None, form.settings.align, text_direction(text)))


def _success_lines(form: Form) -> Markup | None:
    text = form.settings.success_message or ""
    if not (_multiline(text) or (text and form.settings.align == "justify")):
        return None
    return paragraphs_html(text, explicit_align(None, form.settings.align))


def field_explicit_align(form: Form, el: Any) -> str | None:
    return explicit_align(getattr(el, "align", None), form.settings.align)


def field_align(form: Form, el: Any) -> str:
    label = str(getattr(el, "label", "") or "")
    return resolve_align(getattr(el, "align", None), form.settings.align, text_direction(label))


def answers_for_email(form: Form, data: dict[str, Any]) -> list[Answer]:
    """Answered, non-sensitive questions in form order; repeaters row by row."""
    out: list[Answer] = []
    index = FormIndex.build(form)
    for info in index.elements.values():
        el = info.element
        if info.repeater_id is not None:
            continue
        if info.kind == "repeater" and isinstance(el, RepeaterElement):
            rows = data.get(info.id)
            if not isinstance(rows, list):
                continue
            children = [
                index.elements[c].element
                for c in _leaf_ids(index, info.id)
                if index.elements[c].kind == "field"
            ]
            for n, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    continue
                parts = []
                for child in children:
                    if getattr(child, "sensitive", False) or isinstance(child, SignatureField):
                        continue
                    text = answer_text(child, row.get(child.id), display=True)  # type: ignore[arg-type,attr-defined]
                    if text:
                        parts.append(f"{child.label}: {text}")  # type: ignore[attr-defined]
                if parts:
                    label = f"{el.label} - {WORDS['entry'].format(n=n)}"
                    out.append(
                        Answer(
                            label,
                            "\n".join(parts),
                            align=field_align(form, el),
                            explicit=field_explicit_align(form, el),
                        )
                    )
            continue
        if info.kind != "field" or getattr(el, "sensitive", False):
            continue
        text = answer_text(el, data.get(info.id), display=True)  # type: ignore[arg-type]
        if text:
            label = getattr(el, "label", info.id) or info.id
            out.append(
                Answer(
                    label,
                    text,
                    ltr=isinstance(el, LTR_FIELDS),
                    align=field_align(form, el),
                    explicit=field_explicit_align(form, el),
                    split_value=isinstance(el, SingleChoiceField)
                    and field_explicit_align(form, el) is None,
                )
            )
    return out


def _leaf_ids(index: FormIndex, repeater_id: str) -> list[str]:
    return [i for i, info in index.elements.items() if info.repeater_id == repeater_id]


def owner_message(
    *,
    org_name: str,
    brand: EmailBrand | None = None,
    form: Form,
    title: str,
    reference: str,
    submitted: datetime,
    tz: Any,
    url: str,
    respondent: str | None,
    answers: list[Answer] | None,
    wording: Wording | None = None,
) -> Message:
    wording = wording or Wording()
    subject = wording.subject or f"New response to {_iso(title)} ({reference})"
    ctx: dict[str, Any] = {
        "message": wording.message,
        "subject": subject,
        "org_name": org_name,
        "brand": _brand(brand, org_name),
        "title": title,
        "reference": reference,
        "submitted": submitted.astimezone(tz).strftime("%d %b %Y %H:%M %Z"),
        "url": url,
        "respondent": respondent,
        "answers": answers or [],
        **_title(title, form),
    }
    msg = _message(
        ctx["brand"],
        subject,
        _env.get_template("owner.txt").render(ctx),
        _env.get_template("owner.html").render(ctx),
    )
    msg.reply_to = wording.reply_to
    return msg


def receipt_message(
    *,
    org_name: str,
    brand: EmailBrand | None = None,
    form: Form,
    title: str,
    reference: str,
    submitted: datetime,
    tz: Any,
    answers: list[Answer],
    pdf: tuple[str, bytes] | None,
    wording: Wording | None = None,
) -> Message:
    w = WORDS
    wording = wording or Wording()
    subject = wording.subject or w["receipt_subject"].format(title=_iso(title), reference=reference)
    ctx: dict[str, Any] = {
        "message": wording.message,
        "subject": subject,
        "org_name": org_name,
        "brand": _brand(brand, org_name),
        "title": title,
        "reference": reference,
        "submitted": submitted.astimezone(tz).strftime("%d %b %Y %H:%M %Z"),
        "success": form.settings.success_message or "",
        "s": _success(form),
        "success_lines": _success_lines(form),
        "answers": answers,
        "pdf": pdf is not None,
        "w": w,
        **_title(title, form),
    }
    msg = _message(
        ctx["brand"],
        subject,
        _env.get_template("receipt.txt").render(ctx),
        _env.get_template("receipt.html").render(ctx),
    )
    msg.reply_to = wording.reply_to
    if pdf is not None:
        msg.attachments.append((pdf[0], pdf[1], "application/pdf"))
    return msg


def code_message(
    *,
    org_name: str,
    title: str,
    code: str,
    minutes: int,
    brand: EmailBrand | None = None,
) -> Message:
    w = WORDS
    subject = w["code_subject"].format(title=_iso(title))
    ctx: dict[str, Any] = {
        "subject": subject,
        "org_name": org_name,
        "brand": _brand(brand, org_name),
        "title": title,
        "body": w["code_body"].format(code=code, minutes=minutes),
        "code": code,
        "w": w,
        **_title(title),
    }
    return _message(
        ctx["brand"],
        subject,
        _env.get_template("code.txt").render(ctx),
        _env.get_template("code.html").render(ctx),
    )


def _sentence_html(template: str, content: set[str], **values: Any) -> Markup:
    """Fill an English ``template`` for HTML: values escaped, the ``content`` ones (form title,
    step name: maybe Dhivehi) isolated with ``<bdi>`` in their own language and direction so
    they don't reorder the English around them."""
    filled = {
        k: Markup('<bdi lang="{}" dir="{}">{}</bdi>').format(
            text_lang(str(v)), text_direction(str(v)), v
        )
        if k in content
        else escape(v)
        for k, v in values.items()
    }
    return Markup(escape(template).format(**filled))


def approval_request_message(
    *,
    org_name: str,
    brand: EmailBrand | None = None,
    form: Form,
    title: str,
    reference: str,
    submitted: datetime,
    tz: Any,
    step_name: str,
    step: int,
    total: int,
    url: str,
    days: int,
    wording: Wording | None = None,
    answers: list[Answer] | None = None,
) -> Message:
    """The approver's email: what to decide, an Approve and a Reject button and the plain
    link. Both buttons only open the approver page with that decision chosen (``?decision=``):
    the approver still confirms their email with a code and then the decision, so a mail
    scanner opening the links changes nothing."""
    w = WORDS
    wording = wording or Wording()
    date = submitted.astimezone(tz).strftime("%d %b %Y %H:%M %Z").strip()
    values = {"step": step_name, "reference": reference, "title": title, "date": date}
    subject = wording.subject or w["approval_subject"].format(
        title=_iso(title), reference=reference
    )
    sep = "&" if "?" in url else "?"
    ctx: dict[str, Any] = {
        "subject": subject,
        "kicker": "Approval needed",
        "message": wording.message,
        "org_name": org_name,
        "brand": _brand(brand, org_name),
        "title": title,
        "body": _sentence_html(w["approval_body"], {"step", "title"}, **values),
        "body_text": w["approval_body"].format(
            **values | {"step": _iso(step_name), "title": _iso(title)}
        ),
        # One step needs no "Step 1 of 1."
        "step_of": w["approval_step_of"].format(n=step, total=total) if total > 1 else "",
        "note": w["approval_note"].format(days=days),
        "url": url,
        "approve_url": f"{url}{sep}decision=approve",
        "reject_url": f"{url}{sep}decision=reject",
        "answers": answers or [],
        "w": w,
        **_title(title, form),
    }
    msg = _message(
        ctx["brand"],
        subject,
        _env.get_template("approval_request.txt").render(ctx),
        _env.get_template("approval_request.html").render(ctx),
    )
    msg.reply_to = wording.reply_to
    return msg


def approval_notice_message(
    *,
    org_name: str,
    product: str,
    brand: EmailBrand | None = None,
    form: Form,
    title: str,
    reference: str,
    submitted: datetime,
    tz: Any,
    step_name: str,
    step: int,
    total: int,
    url: str,
    wording: Wording | None = None,
    answers: list[Answer] | None = None,
) -> Message:
    """ "New response to review" for a step that only people with edit access decide, in the
    studio: a button to the submission (they sign in there), no Approve / Reject buttons, no
    approver link and no code. The form's own message replaces the built-in sentence."""
    w = WORDS
    wording = wording or Wording()
    date = submitted.astimezone(tz).strftime("%d %b %Y %H:%M %Z").strip()
    values = {"step": step_name, "reference": reference, "title": title, "date": date}
    subject = wording.subject or w["notice_subject"].format(title=_iso(title), reference=reference)
    ctx: dict[str, Any] = {
        "subject": subject,
        "kicker": w["notice_kicker"],
        "message": wording.message,
        "org_name": org_name,
        "brand": _brand(brand, org_name),
        "title": title,
        "body": _sentence_html(w["notice_body"], {"step", "title"}, **values),
        "body_text": w["notice_body"].format(
            **values | {"step": _iso(step_name), "title": _iso(title)}
        ),
        "step_of": w["approval_step_of"].format(n=step, total=total) if total > 1 else "",
        "reference": reference,
        "button": w["notice_button"].format(product=product),
        "note": w["notice_note"],
        "url": url,
        "answers": answers or [],
        "w": w,
        **_title(title, form),
    }
    msg = _message(
        ctx["brand"],
        subject,
        _env.get_template("approval_notice.txt").render(ctx),
        _env.get_template("approval_notice.html").render(ctx),
    )
    msg.reply_to = wording.reply_to
    return msg


def outcome_message(
    *,
    org_name: str,
    brand: EmailBrand | None = None,
    form: Form,
    title: str,
    reference: str,
    approved: bool,
    comment: str | None,
    pdf: tuple[str, bytes] | None,
    wording: Wording | None = None,
) -> Message:
    """The outcome for the respondent. ``wording.message`` (the form's own text for this
    outcome) replaces the built-in sentence; the reference, a rejection's comment and the PDF
    note stay. Replies go to ``wording.reply_to`` when set."""
    wording = wording or Wording()
    w = WORDS
    key = "approved" if approved else "rejected"
    subject = w[f"outcome_subject_{key}"].format(title=_iso(title), reference=reference)
    ctx: dict[str, Any] = {
        "subject": subject,
        "org_name": org_name,
        "brand": _brand(brand, org_name),
        "title": title,
        "body": _sentence_html(w[f"outcome_{key}"], set(), reference=reference),
        "body_text": w[f"outcome_{key}"].format(reference=reference),
        "comment": comment if not approved else None,
        "message": wording.message,
        "reference": reference,
        "pdf": pdf is not None,
        "w": w,
        **_title(title, form),
    }
    msg = _message(
        ctx["brand"],
        wording.subject or subject,
        _env.get_template("outcome.txt").render(ctx),
        _env.get_template("outcome.html").render(ctx),
    )
    msg.reply_to = wording.reply_to
    if pdf is not None:
        msg.attachments.append((pdf[0], pdf[1], "application/pdf"))
    return msg


ROLE_PHRASES = {"admin": "an admin", "creator": "a form creator", "member": "a member"}


@dataclass(frozen=True)
class InvitedForm:
    title: str


def invitation_message(
    *,
    org_name: str,
    product: str,
    brand: EmailBrand | None,
    inviter: str | None,
    role: str,
    forms: list[InvitedForm],
    url: str,
    until: datetime,
    tz: Any,
    email: str,
    single_sign_on: bool,
) -> Message:
    """ "You've been invited to {organisation} on {product}" (docs/ux/PEOPLE-SCREENS.md 4)."""
    org = " ".join(org_name.split())
    product = " ".join(product.split())
    subject = (
        f"You've been invited to {org}"
        if not product or product.casefold() == org.casefold()
        else f"You've been invited to {org} on {product}"
    )
    who = " ".join((inviter or "").split()) or "An admin"
    intro = f"{who} invited you to {org} as {ROLE_PHRASES.get(role, 'a member')}."
    how = (
        "You'll sign in with your organisation account."
        if single_sign_on
        else f"You'll sign in with a code we email to {email}."
    )
    listed = []
    for f in forms:
        content = _title(f.title or "Untitled form")
        listed.append(
            {
                "title": f.title or "Untitled form",
                "title_text": _iso(f.title or "Untitled form"),
                "lang": content["lang"],
                "dir": content["dir"],
                "align": content["align"],
                "font": content["font"],
            }
        )
    ctx: dict[str, Any] = {
        "subject": subject,
        "org_name": org,
        "brand": _brand(brand, org),
        "intro": intro,
        "forms": listed,
        "url": url,
        "how": how,
        "until": until.astimezone(tz).strftime("%d %B %Y").lstrip("0"),
    }
    return _message(
        ctx["brand"],
        subject,
        _env.get_template("invitation.txt").render(ctx),
        _env.get_template("invitation.html").render(ctx),
    )


# What each form role can do, in the words of the Share page (DESIGN 7).
FORM_ROLE_WORDS = {
    "viewer": ("a submissions viewer", "you can view and export submissions"),
    "editor": ("an editor", "you can edit the form and manage submissions"),
    "owner": ("an owner", "you can edit the form, manage submissions and decide who has access"),
}


def form_shared_message(
    *,
    org_name: str,
    brand: EmailBrand | None,
    sharer: str,
    sharer_email: str | None,
    title: str,
    role: str,
    upgraded: bool,
    note: str | None,
    url: str,
) -> Message:
    """The email "{sharer} shared "{title}" with you": an organisation member got a role on a form (or a
    higher one, ``upgraded``). ``note`` is the sharer's optional plain-text message, escaped in
    HTML and attributed to them. Replies go to the sharer."""
    sharer = one_line(sharer, 120) or "A colleague"
    title = title or "Untitled form"
    article, can = FORM_ROLE_WORDS.get(role, FORM_ROLE_WORDS["viewer"])
    quoted = f"“{_iso(one_line(title, 150))}”"
    subject = (
        f"{sharer} changed your access to {quoted}"
        if upgraded
        else f"{sharer} shared {quoted} with you"
    )
    action = "changed your access to this form" if upgraded else "shared this form with you"
    sentence = f"{{sharer}} {action}. You're now {article}: {can}."
    content = _title(title)
    ctx: dict[str, Any] = {
        "subject": subject,
        "org_name": org_name,
        "brand": _brand(brand, org_name),
        "kicker": "Access changed" if upgraded else "Shared with you",
        "title": title,
        "title_text": _iso(title),
        "sharer": sharer,
        "body": _sentence_html(sentence, set(), sharer=sharer),
        "body_text": sentence.format(sharer=sharer),
        "note": note,
        "button": "Open the submissions" if role == "viewer" else "Open the form",
        "url": url,
        **content,
    }
    msg = _message(
        ctx["brand"],
        subject,
        _env.get_template("form_shared.txt").render(ctx),
        _env.get_template("form_shared.html").render(ctx),
    )
    msg.reply_to = sharer_email
    return msg


def webhook_disabled_message(*, title: str, url: str, failures: int, settings_url: str) -> Message:
    ctx = {"title": title, "url": url, "failures": failures, "settings_url": settings_url}
    return Message(
        subject=f'A webhook for "{title}" was turned off',
        text=_env.get_template("webhook_disabled.txt").render(ctx),
    )


def settings_url(settings: Settings, form_id: Any) -> str:
    return f"{settings.public_origin}/forms/{form_id}/settings"
