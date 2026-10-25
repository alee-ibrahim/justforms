# Webhooks

A webhook sends form events to another system as they happen. Owners add them on the
form's **Settings** page. Design background: [DESIGN.md §11.2](DESIGN.md).

## Events

| Event | When |
|---|---|
| `submission.created` | A response arrives. |
| `submission.status_changed` | A submission's status changes (`change.from`, `change.to`). When an approval sets it, `change.via` is `"approval"` and the event has no person behind it. |
| `submission.comment_added` | Someone comments (`change.comment`, `change.by`). |
| `submission.pdf_ready` | The signed PDF of a submission is ready (`submission.pdf`). |
| `submission.approval_step` | Something happened in a submission's approval: `change.action` is `requested` (an approver was emailed, or, with `change.approvers: "editors"` and no `approverEmail`, a step that only people with edit access decide in the studio was reached), `approved`, `rejected`, `stopped` (by staff, with `change.reason`) or `waiting` (no approver address in the answers). Also `change.step` (1-based), `change.stepName` and, where known, `change.approverEmail`, `change.approverName` and `change.comment`. Decisions carry `change.decidedVia`: `"email"` (the approver's link) or `"studio"` (a staff member decided the step; `approverName` is theirs). |
| `test` | "Send test event" on the webhook. |

## Request

`POST` to your URL with a JSON body:

```json
{
  "id": "evt_0192f0a1b2c37d4e8f901a2b3c4d5e6f",
  "type": "submission.created",
  "createdAt": "2026-10-23T08:15:02Z",
  "form": { "id": "…", "slug": "youth-programme", "url": "https://forms.example.org/youth-programme", "version": 3 },
  "submission": {
    "id": "…", "seq": 142, "reference": "#0142", "status": "new", "language": "dv",
    "submittedAt": "2026-10-23T08:15:01Z", "contentHash": "sha256:…",
    "respondentEmail": null,
    "data": { "full_name": "Aishath Ali", "national_id": "[redacted]" },
    "url": "https://forms.example.org/forms/…/submissions?open=…"
  }
}
```

- `data` is keyed by question key. Sensitive answers are `"[redacted]"` unless the webhook
  has "Include sensitive answers" on.
- File answers carry a `url` to the app's download endpoint (it needs a signed-in user with
  access to the form). Storage URLs are never sent.
- `respondentEmail` is the confirmed address for forms that ask people to confirm their
  email, or the signed-in user for staff-only forms; otherwise `null`.

## Signature

Every request carries:

```
JustForms-Webhook-Id: evt_…
JustForms-Webhook-Timestamp: 1761207302
JustForms-Webhook-Signature: v1=<hex>
```

`<hex>` is `HMAC-SHA256(secret, "{id}.{timestamp}.{body}")` where the key is the whole
secret string (`whsec_…`) as UTF-8 and `body` is the exact bytes of the request body. Check
it against the raw body before parsing JSON, compare in constant time, and reject timestamps
more than 5 minutes from your clock. After "Rotate secret" the header carries two
signatures (`v1=…,v1=…`, new and old) for 24 hours; accept the request if either matches.

Reference verifiers, tested against [`spec/webhooks/signature-v1.json`](../spec/webhooks/signature-v1.json):

- Python: [`webhooks/verify.py`](webhooks/verify.py)
- Node.js: [`webhooks/verify.mjs`](webhooks/verify.mjs)
- PHP: [`webhooks/verify.php`](webhooks/verify.php)

## Delivery and retries

- 10 second timeout. Any `2xx` answer counts as delivered. Redirects are not followed.
- Failed deliveries are retried after 1 minute, 5 minutes, 30 minutes, 2 hours, 6 hours,
  12 hours and 24 hours (8 attempts), then marked failed. The same event keeps its `id`, so
  use it to ignore duplicates.
- After 20 failed deliveries in a row the webhook is turned off and the form's owners get an
  email. Turn it back on in Settings once the endpoint works.
- The delivery log (Settings → webhook → Open) keeps 30 days of requests with the response
  code, the first 1 KB of the response and the duration, and can redeliver any of them.

## Private addresses

URLs are resolved when each request is sent. Private, loopback, link-local, carrier-grade NAT
and cloud metadata addresses are refused unless they fall inside
`JUSTFORMS_WEBHOOK_ALLOWED_CIDRS`, and the request goes to the address that was checked. Only
`https` is allowed, except `http` to allowlisted ranges.
