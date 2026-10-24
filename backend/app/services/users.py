"""User and organisation bookkeeping shared by login flows, the API and the CLI."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import AuditLog, Organization, OrgMembership, OrgRole, User


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def ensure_default_org(db: AsyncSession, settings: Settings) -> Organization:
    org = await db.scalar(
        select(Organization).where(Organization.slug == settings.default_org_slug)
    )
    if org is None:
        org = Organization(name=settings.default_org_name, slug=settings.default_org_slug)
        db.add(org)
        await db.flush()
    return org


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == normalize_email(email)))


async def set_membership(
    db: AsyncSession, org: Organization, user: User, role: OrgRole
) -> OrgMembership:
    membership = await db.get(OrgMembership, (org.id, user.id))
    if membership is None:
        membership = OrgMembership(org_id=org.id, user_id=user.id, role=role)
        db.add(membership)
    else:
        membership.role = role
    await db.flush()
    return membership


async def audit(
    db: AsyncSession,
    action: str,
    *,
    org_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    ip: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            org_id=org_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            meta=meta or {},
        )
    )


def mark_login(user: User) -> None:
    user.last_login_at = datetime.now(UTC)


async def create_admin(
    db: AsyncSession, settings: Settings, email: str, display_name: str = ""
) -> User:
    """Create (or promote) the first admin: superadmin plus admin of the default org."""
    org = await ensure_default_org(db, settings)
    user = await get_user_by_email(db, email)
    if user is None:
        user = User(email=normalize_email(email), display_name=display_name)
        db.add(user)
        await db.flush()
    elif display_name:
        user.display_name = display_name
    user.is_superadmin = True
    await set_membership(db, org, user, OrgRole.ADMIN)
    await audit(db, "user.create_admin", org_id=org.id, target_type="user", target_id=user.id)
    return user
