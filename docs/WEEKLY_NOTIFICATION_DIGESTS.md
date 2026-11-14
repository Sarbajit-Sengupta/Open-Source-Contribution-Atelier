# Weekly notification email digests

Open **Settings → Notification Preferences → Weekly notification email digest**,
choose a Monday delivery time and save. The page shows the effective time zone
and keeps this switch separate from the weekly learning-progress email. Failed
loads offer retry; failed saves retain the draft and report that the previous
saved settings are unchanged.

`PATCH /api/notifications/prefs/` accepts `digest_frequency` (`none`, `daily`,
`weekly`) and `digest_time` (local `HH:MM[:SS]`). GET returns both fields. For example:

```json
{"digest_frequency": "weekly", "digest_time": "08:00"}
```

Use `{"digest_frequency": "none"}` to return future notifications to immediate
email. `email: false` disables all notification email, including high priority.
Changing unrelated preferences preserves the digest settings. Invalid frequency
or time values return HTTP 400 before any preference changes are saved.

The existing `receive_weekly_digest` / `weekly_digest` response fields retain
their earlier meaning: the account's **progress-summary** subscription. They do
not replace the notification-email `digest_frequency` field.

## Delivery behavior

- Only ordinary **email** is deferred. In-app, push and other enabled channels
  retain their existing immediate delivery behavior.
- Internal dispatchers can set `meta.priority` to `high`, `urgent` or `critical`
  (case insensitive) to keep that email immediate.
- A deferred email is a durable `NotificationDelivery` in `digest_pending`,
  including its payload even if in-app notifications are disabled.
- The existing `send_notification_digests` periodic task batches these emails on
  Monday at the user's `digest_time`, interpreted in the account timezone.
  Invalid/missing timezone data falls back to UTC. Missed scheduler runs catch up
  to the latest due Monday; an email created exactly at the cutoff belongs to the
  following period. Configure the periodic task at least hourly; the first run
  after the preferred minute sends the due batch.
- The snapshot includes unread notifications due before the cutoff. Items read
  before batching are cancelled. A digest shows at most 100 previews, reports the
  full total and omitted count, and links to notification history for the rest.
- Every source item is linked to its batch and becomes `batched`, meaning
  **included in a queued summary**, not that its individual email was sent.

## Duplicate protection, retries and opt-out

A per-recipient/channel/Monday dedupe key and a transaction protect batch creation;
the preference row is locked when PostgreSQL schedulers race. Item transitions,
membership links and the batch snapshot commit together. Queueing happens only
after commit. A later change of send time does not send another digest that week.

The batch uses the existing email delivery worker, attempt log, backoff,
dead-letter handling and stale-delivery recovery. Broker unavailability leaves a
pending batch for recovery. Repeated scheduler runs or delivery of a completed
task do not create or send another batch. A failed batch retains its snapshot;
operators should retry that existing delivery, rather than dispatch a new event.

Opt-out cancels unsent queued weekly email without releasing a burst of individual
emails. The delivery worker rechecks the preference before sending a batch,
including changes made outside this API. It cannot recall a message already handed
to the mail provider. As with the existing SMTP ledger, a process dying after SMTP
accepts mail but before the success transaction is saved can cause a retry: SMTP
has no transactional idempotency-key contract. Provider-level exactly-once delivery
is not claimed.

`digest_pending` items are retained for delivery. Completed batch membership and
cancelled items follow the existing delivery-retention window. No unread in-app
notification is marked read or removed by batching.

Apply the notification migration before starting updated workers. This branch
adds `0008_weekly_digest_delivery`; if another notification migration lands first,
merge the migration graph before deployment. Existing daily digest batching and
the separate weekly progress-summary pipeline are unchanged.
