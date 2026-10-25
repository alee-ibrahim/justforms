from fastapi import APIRouter

from app.api.v1 import (
    access,
    ai,
    approvals,
    auth,
    branding,
    files,
    forms,
    imports,
    meta,
    notify,
    orgs,
    people,
    public,
    sharing,
    submissions,
    themes,
    verify,
)

router = APIRouter(prefix="/v1")
router.include_router(meta.router)
router.include_router(auth.router)
router.include_router(orgs.router)
router.include_router(people.router)
router.include_router(people.public)
router.include_router(forms.router)
router.include_router(imports.router)
router.include_router(public.router)
router.include_router(submissions.router)
router.include_router(files.router)
router.include_router(access.router)
router.include_router(notify.router)
router.include_router(verify.router)
router.include_router(approvals.router)
router.include_router(approvals.public)
router.include_router(ai.router)
router.include_router(branding.router)
router.include_router(branding.public)
router.include_router(branding.site)
router.include_router(themes.router)
router.include_router(themes.public)
router.include_router(sharing.router)
router.include_router(sharing.public)
