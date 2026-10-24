"""The optional API-key path (DESIGN 13.4): list an account's forms and read one form.

The key is used for the calls of one request and never stored or logged. Only Jotform's own
API hosts are called, so no user-supplied address is ever fetched here.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

import httpx

from app.importers.dom import clean_space, parse_html
from app.importers.jotform.logo import api_logo_url
from app.importers.jotform.model import JfCondition, JfOption, JfQuestion, JfSource
from app.importers.jotform.text import single_heading, to_markdown

Region = Literal["us", "eu", "hipaa"]
HOSTS: dict[str, str] = {
    "us": "https://api.jotform.com",
    "eu": "https://eu-api.jotform.com",
    "hipaa": "https://hipaa-api.jotform.com",
}
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class JotformApiError(Exception):
    """``code``: ``bad_key`` | ``not_found`` | ``rate_limited`` | ``unavailable``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def _get(
    region: Region,
    api_key: str,
    path: str,
    params: dict[str, str] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Any:
    try:
        async with httpx.AsyncClient(
            base_url=HOSTS[region], timeout=TIMEOUT, follow_redirects=False, transport=transport
        ) as client:
            res = await client.get(path, params=params, headers={"APIKEY": api_key})
    except httpx.HTTPError as exc:
        raise JotformApiError("unavailable") from exc
    if res.status_code in (401, 403):
        raise JotformApiError("bad_key")
    if res.status_code == 404:
        raise JotformApiError("not_found")
    if res.status_code == 429:
        raise JotformApiError("rate_limited")
    if res.status_code != 200 or len(res.content) > MAX_RESPONSE_BYTES:
        raise JotformApiError("unavailable")
    try:
        body = res.json()
    except ValueError as exc:
        raise JotformApiError("unavailable") from exc
    return body.get("content") if isinstance(body, dict) else None


async def list_forms(
    region: Region, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> list[dict[str, Any]]:
    content = await _get(
        region,
        api_key,
        "/user/forms",
        {"limit": "1000", "orderby": "updated_at"},
        transport=transport,
    )
    out = []
    for f in content or []:
        if not isinstance(f, dict) or f.get("status") == "DELETED":
            continue
        out.append(
            {
                "id": str(f.get("id", "")),
                "title": str(f.get("title", "")),
                "count": int(f.get("count") or 0),
                "status": str(f.get("status", "")),
                "updatedAt": f.get("updated_at") or f.get("created_at"),
            }
        )
    return out


async def read_form(
    region: Region,
    api_key: str,
    form_id: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> JfSource:
    if not re.fullmatch(r"\d{1,24}", form_id):
        raise JotformApiError("not_found")
    form = await _get(region, api_key, f"/form/{form_id}", transport=transport)
    questions = await _get(region, api_key, f"/form/{form_id}/questions", transport=transport)
    properties = await _get(region, api_key, f"/form/{form_id}/properties", transport=transport)
    return source_from_api(form or {}, questions or {}, properties or {})


# -- mapping API JSON onto JfQuestion --------------------------------------------------------


def _yes(value: Any) -> bool:
    return str(value).strip().lower() in ("yes", "true", "1")


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return clean_space(parse_html(str(value or "")).text())


def _options(raw: Any) -> list[str]:
    return [o.strip() for o in str(raw or "").split("|") if o.strip()]


def question_from_api(data: dict[str, Any]) -> JfQuestion:
    qid = str(data.get("qid", ""))
    type_ = str(data.get("type", ""))
    q = JfQuestion(
        qid=qid,
        type=type_,
        label=_text(data.get("text")),
        name=str(data.get("name", "")),
        required=_yes(data.get("required")),
        description=_text(data.get("description")),
        placeholder=_text(data.get("hint")),
        half=str(data.get("labelAlign", "")) == "Top" and _yes(data.get("shrink")),
    )
    sub = _text(data.get("subLabel"))
    if sub:
        q.sublabels["main"] = sub
    props = q.props
    max_len = _num(data.get("maxsize") if type_ != "control_fileupload" else None)
    if max_len and type_ in ("control_textbox", "control_textarea"):
        props["max_length"] = int(max_len)

    if type_ == "control_head":
        q.text = _text(data.get("text"))
        q.subtext = _text(data.get("subHeader"))
        props["level"] = {"large": "h1", "default": "h2", "small": "h3"}.get(
            str(data.get("headerType", "default")).lower(), "h2"
        )
    elif type_ == "control_collapse":
        q.text = _text(data.get("text"))
    elif type_ == "control_text":
        root = parse_html(str(data.get("text") or ""))
        q.text = to_markdown(root)
        q.label = ""
        heading = single_heading(root)
        if heading:
            props["heading"] = heading
    elif type_ == "control_textbox":
        validation = str(data.get("validation") or "None")
        props["validations"] = [] if validation == "None" else [validation]
        props["mask"] = _yes(data.get("inputMask"))
    elif type_ == "control_textarea":
        props["rich"] = str(data.get("entryLimit", "")).startswith("Rich") or _yes(
            data.get("wysiwyg")
        )
    elif type_ == "control_email":
        props["confirm"] = _yes(data.get("confirmation"))
    elif type_ == "control_phone":
        mask = str(data.get("inputMaskValue") or "")
        m = re.search(r"\+\s*(\d{1,4})", mask)
        if m:
            props["country_code"] = m.group(1)
        props["split"] = not _yes(data.get("inputMask")) and _yes(data.get("countryCode"))
    elif type_ in ("control_number", "control_spinner"):
        for key, names in (
            ("min", ("minValue", "minimum", "minNum")),
            ("max", ("maxValue", "maximum", "maxNum")),
            ("step", ("stepValue", "addAmount")),
        ):
            for name in names:
                value = _num(data.get(name))
                if value is not None and str(data.get(name)).strip() != "":
                    props[key] = value
                    break
    elif type_ in ("control_datetime", "control_time"):
        props["time"] = type_ == "control_time" or _yes(data.get("allowTime"))
        limits = data.get("limitDate")
        if isinstance(limits, str):
            try:
                limits = json.loads(limits)
            except ValueError:
                limits = {}
        props["calendar"] = limits if isinstance(limits, dict) else {}
        props["format"] = str(data.get("format", ""))
    elif type_ in ("control_dropdown", "control_radio", "control_checkbox"):
        q.options = [JfOption(label=o) for o in _options(data.get("options"))]
        if _yes(data.get("allowOther")):
            q.options.append(JfOption(label=_text(data.get("otherText")) or "Other", other=True))
        props["multiple"] = _yes(data.get("multipleSelections"))
        for key, name in (("min", "minSelection"), ("max", "maxSelection")):
            value = _num(data.get(name))
            if value:
                props[key] = int(value)
    elif type_ in ("control_rating", "control_scale"):
        high = _num(data.get("stars") or data.get("scaleAmount"))
        if high:
            props["low"], props["high"] = 1, high
    elif type_ == "control_fileupload":
        props["accept"] = [
            e.strip().lstrip(".").lower()
            for e in re.split(r"[,\s]+", str(data.get("extensions") or ""))
            if e.strip() and e.strip() != "*"
        ]
        maxsize = _num(data.get("maxFileSize") or data.get("maxsize"))
        if maxsize:
            props["max_kb"] = maxsize
        props["multiple"] = _yes(data.get("allowMultiple"))
        limit = _num(data.get("maxFiles") or data.get("fileLimit"))
        if limit:
            props["limit"] = int(limit)
    elif type_ in ("control_fullname", "control_address"):
        if type_ == "control_fullname":
            parts = ["first", "last"]
            if _yes(data.get("prefix")):
                parts.insert(0, "prefix")
            if _yes(data.get("middle")):
                parts.insert(-1, "middle")
            if _yes(data.get("suffix")):
                parts.append("suffix")
        else:
            parts = ["addr_line1", "addr_line2", "city", "state", "postal", "country"]
            hidden = str(data.get("hiddenFields") or "")
            parts = [p for p in parts if p not in hidden]
        props["parts"] = parts
        sublabels = data.get("sublabels")
        if isinstance(sublabels, str):
            try:
                sublabels = json.loads(sublabels)
            except ValueError:
                sublabels = {}
        if isinstance(sublabels, dict):
            q.sublabels.update({str(k): _text(v) for k, v in sublabels.items() if v})
    elif type_ == "control_button":
        q.text = _text(data.get("text"))
    return q


def source_from_api(
    form: dict[str, Any], questions: dict[str, Any], properties: dict[str, Any]
) -> JfSource:
    out = JfSource(title=str(form.get("title") or properties.get("title") or ""))
    out.form_id = str(form.get("id") or "") or None
    out.logo_url = api_logo_url(properties)
    out.cover_image = out.logo_url is not None
    items = [q for q in questions.values() if isinstance(q, dict)]
    items.sort(key=lambda q: int(_num(q.get("order")) or 0))
    out.questions = [question_from_api(q) for q in items]
    raw = properties.get("conditions") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    for cond in raw if isinstance(raw, list) else []:
        if not isinstance(cond, dict):
            continue
        cond = dict(cond)
        for key in ("action", "terms"):
            if isinstance(cond.get(key), str):
                try:
                    cond[key] = json.loads(cond[key])
                except ValueError:
                    cond[key] = []
        out.conditions.append(JfCondition(raw=cond))
    return out
