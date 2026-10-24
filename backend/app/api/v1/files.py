"""Authorised file downloads (DESIGN 10, step 5).

``GET /files/{id}`` runs the form-role check (viewer and up), then redirects to a short-lived
presigned URL (``s3``) or streams the file (``local``). Files are always sent as attachments
with ``nosniff``. ``?preview=1`` serves raster images inline for thumbnails in the studio,
under a sandboxing CSP so nothing in the file can run.
"""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from app.auth.deps import CurrentUser, DbDep, StorageDep
from app.models import FileRecord, FileState, FormRecord
from app.permissions import effective_form_role

router = APIRouter(tags=["files"])

PREVIEWABLE = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


def content_disposition(kind: str, filename: str) -> str:
    ascii_name = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename)
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


async def load_file(db: DbDep, user: CurrentUser, file_id: uuid.UUID) -> FileRecord:
    rec = await db.get(FileRecord, file_id)
    form = await db.get(FormRecord, rec.form_id) if rec else None
    role = await effective_form_role(db, user, form) if form and form.deleted_at is None else None
    if rec is None or role is None or rec.state != FileState.ATTACHED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file_not_found")
    return rec


@router.get("/files/{file_id}", response_model=None)
async def download_file(
    file_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    storage: StorageDep,
    preview: Annotated[bool, Query()] = False,
) -> Response:
    rec = await load_file(db, user, file_id)
    inline = preview and rec.mime in PREVIEWABLE
    if not inline:
        url = await storage.presign_download(rec.storage_key, filename=rec.original_name)
        if url is not None:
            return RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    headers = {
        "Content-Disposition": content_disposition(
            "inline" if inline else "attachment", rec.original_name
        ),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, no-store",
        "Content-Length": str(rec.size),
    }
    return StreamingResponse(
        storage.iter_chunks(rec.storage_key),
        media_type=rec.mime if inline else "application/octet-stream",
        headers=headers,
    )
