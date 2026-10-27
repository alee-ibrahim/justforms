"""ORM models. Every model module is imported here so ``Base.metadata`` is complete."""

from app.db import Base
from app.models.ai import AiMessage, AiMode, AiSession, AiSessionStatus
from app.models.approval import ApprovalState, ApprovalStep, StepState
from app.models.audit import AuditLog
from app.models.file import FileRecord, FileState, ScanStatus
from app.models.form import (
    AccessMode,
    ActorType,
    FormDraftHistory,
    FormPermission,
    FormRecord,
    FormRole,
    FormSlugAlias,
    FormStatus,
    FormVersion,
)
from app.models.imports import Import, ImportKind, ImportStatus
from app.models.notify import (
    DeliveryStatus,
    EmailDelivery,
    EmailStatus,
    NotificationRule,
    RuleType,
    Webhook,
    WebhookDelivery,
)
from app.models.org import (
    Appearance,
    InvitationStatus,
    InviteEmailStatus,
    Organization,
    OrgInvitation,
    OrgMembership,
    OrgRole,
    SuperadminSource,
    User,
)
from app.models.signing import SigningKey
from app.models.submission import (
    EventType,
    Export,
    ExportStatus,
    PdfStatus,
    Signature,
    Submission,
    SubmissionEvent,
    SubmissionSource,
    SubmissionStatus,
)

__all__ = [
    "AccessMode",
    "ActorType",
    "AiMessage",
    "AiMode",
    "AiSession",
    "AiSessionStatus",
    "Appearance",
    "ApprovalState",
    "ApprovalStep",
    "AuditLog",
    "Base",
    "DeliveryStatus",
    "EmailDelivery",
    "EmailStatus",
    "EventType",
    "Export",
    "ExportStatus",
    "FileRecord",
    "FileState",
    "FormDraftHistory",
    "FormPermission",
    "FormRecord",
    "FormRole",
    "FormSlugAlias",
    "FormStatus",
    "FormVersion",
    "Import",
    "ImportKind",
    "ImportStatus",
    "InvitationStatus",
    "InviteEmailStatus",
    "NotificationRule",
    "OrgInvitation",
    "OrgMembership",
    "OrgRole",
    "Organization",
    "PdfStatus",
    "RuleType",
    "ScanStatus",
    "Signature",
    "SigningKey",
    "StepState",
    "Submission",
    "SubmissionEvent",
    "SubmissionSource",
    "SubmissionStatus",
    "SuperadminSource",
    "User",
    "Webhook",
    "WebhookDelivery",
]
