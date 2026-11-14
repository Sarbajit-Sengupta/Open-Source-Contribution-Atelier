"""Weekly digest delivery, immediate priorities and authenticated preferences."""

import datetime as dt
from contextlib import AbstractContextManager
from typing import Any, cast
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.notifications import tasks
from apps.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
)

pytestmark = pytest.mark.django_db
UTC = dt.timezone.utc
MONDAY = dt.datetime(2026, 11, 9, 8, tzinfo=UTC)
deliver: Any = tasks.process_notification_delivery
recover: Any = tasks.recover_stale_deliveries
send_digests: Any = tasks.send_notification_digests


@pytest.fixture
def client(digest_subscriber):
    value = APIClient()
    value.force_authenticate(digest_subscriber.user)
    return value


def notify(pref, title="Ordinary", kind="badge", **kwargs):
    deliveries = tasks.dispatch_notification(
        pref.user, kind, title, "Message", **kwargs
    )
    return next(d for d in deliveries if d.channel == "email")


def test_api_round_trip_and_partial_updates(client, digest_subscriber):
    response = client.get("/api/notifications/prefs/")
    assert response.status_code == 200
    assert response.data["digest_frequency"] == "weekly"
    assert response.data["digest_time"] == "08:00:00"
    response = client.patch(
        "/api/notifications/prefs/",
        {"digest_frequency": "none", "digest_time": "10:45"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["digest_frequency"] == "none"
    assert response.data["digest_time"] == "10:45:00"
    assert response.data["in_app"] is True
    digest_subscriber.refresh_from_db()
    assert digest_subscriber.digest_frequency == "none"
    assert digest_subscriber.digest_time == dt.time(10, 45)
    assert (
        client.patch(
            "/api/notifications/prefs/", {"digest_frequency": "weekly"}, format="json"
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"digest_frequency": "monthly"},
        {"digest_frequency": None},
        {"digest_frequency": 7},
        {"digest_time": "25:00"},
        {"digest_time": "not-a-time"},
        {"digest_time": None},
        {"digest_time": "08:00+05:30"},
        {"digest_time": "08:00Z"},
    ],
)
def test_api_rejects_invalid_digest_settings_atomically(
    client, digest_subscriber, invalid
):
    response = client.patch(
        "/api/notifications/prefs/", {"email": False, **invalid}, format="json"
    )
    assert response.status_code == 400
    digest_subscriber.refresh_from_db()
    assert digest_subscriber.email_enabled is True
    assert digest_subscriber.digest_frequency == "weekly"


def test_preference_change_is_scoped_to_authenticated_user(client, digest_subscriber):
    other = get_user_model().objects.create_user(username="other-weekly")
    other_pref, _ = NotificationPreference.objects.get_or_create(user=other)
    client.patch(
        "/api/notifications/prefs/", {"digest_frequency": "none"}, format="json"
    )
    other_pref.refresh_from_db()
    assert other_pref.digest_frequency == "none"


def test_ordinary_mail_is_deferred_but_in_app_is_immediate(
    digest_subscriber, mailoutbox
):
    row = notify(digest_subscriber)
    assert row.status == "digest_pending"
    assert Notification.objects.filter(recipient=digest_subscriber.user).count() == 1
    assert NotificationDelivery.objects.get(channel="in_app").status == "sent"
    assert len(mailoutbox) == 0
    assert deliver(row.pk) is False
    assert len(mailoutbox) == 0


@pytest.mark.parametrize("priority", ["high", "urgent", "critical", " HIGH "])
def test_high_priority_mail_remains_immediate(digest_subscriber, priority, mailoutbox):
    row = notify(digest_subscriber, meta={"priority": priority})
    assert row.status == "sent"
    assert len(mailoutbox) == 1


def test_batch_snapshot_is_durable_and_not_sent_twice(
    digest_subscriber, digest_clock, digest_batch, mailoutbox
):
    first = notify(digest_subscriber, title="<script>unsafe</script>")
    second = notify(digest_subscriber, title="Comment", kind="comment")
    digest_clock.now = MONDAY
    delivery = digest_batch()
    assert delivery is not None
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == second.status == "batched"
    assert first.digest_batch_id == second.digest_batch_id == delivery.pk
    assert delivery.payload["digest"]["total_count"] == 2
    assert set(delivery.payload["digest"]["grouped_notifications"]) == {
        "badge",
        "comment",
    }
    assert len(mailoutbox) == 1
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in mailoutbox[0].alternatives[0][0]
    assert digest_batch().pk == delivery.pk
    assert deliver(delivery.pk) is True
    assert len(mailoutbox) == 1
    with (
        pytest.raises(IntegrityError),
        cast(AbstractContextManager, transaction.atomic()),
    ):
        NotificationDelivery.objects.create(
            recipient=digest_subscriber.user,
            channel="email",
            dedupe_key=delivery.dedupe_key,
        )


def test_cutoff_and_next_week_do_not_drop_new_items(
    digest_subscriber, digest_clock, digest_batch, mailoutbox
):
    old = notify(digest_subscriber, "Sunday")
    assert digest_batch() is None  # before Monday's scheduled time
    digest_clock.now = MONDAY
    boundary = notify(digest_subscriber, "Exactly at cutoff")
    assert digest_batch().payload["digest"]["total_count"] == 1
    boundary.refresh_from_db()
    assert boundary.status == "digest_pending"
    digest_clock.now += dt.timedelta(days=7)
    assert digest_batch().payload["digest"]["total_count"] == 1
    boundary.refresh_from_db()
    old.refresh_from_db()
    assert boundary.digest_batch_id != old.digest_batch_id
    assert len(mailoutbox) == 2


def test_changing_send_time_does_not_create_another_batch_that_week(
    digest_subscriber, digest_clock, digest_batch, mailoutbox
):
    notify(digest_subscriber)
    digest_clock.now = MONDAY
    first = digest_batch()
    digest_subscriber.digest_time = dt.time(10)
    digest_subscriber.save(update_fields=["digest_time"])
    digest_clock.now = MONDAY + dt.timedelta(hours=1)
    new = notify(digest_subscriber, "Later")
    digest_clock.now += dt.timedelta(hours=1)
    assert digest_batch().pk == first.pk
    new.refresh_from_db()
    assert new.status == "digest_pending"
    assert len(mailoutbox) == 1


def test_broker_failure_leaves_batch_for_existing_recovery_worker(
    digest_subscriber, digest_clock, digest_batch, settings, mailoutbox
):
    notify(digest_subscriber)
    digest_clock.now = MONDAY
    settings.CELERY_TASK_ALWAYS_EAGER = False
    with patch.object(
        tasks.process_notification_delivery,
        "apply_async",
        side_effect=OSError("broker unavailable"),
    ):
        row = digest_batch()
    row.refresh_from_db()
    assert row.status == "pending"
    assert len(mailoutbox) == 0
    digest_clock.now += dt.timedelta(minutes=6)
    settings.CELERY_TASK_ALWAYS_EAGER = True
    recover()
    row.refresh_from_db()
    assert row.status == "sent"
    assert len(mailoutbox) == 1
    assert digest_batch().pk == row.pk


def test_transient_provider_retry_keeps_one_batch(
    digest_subscriber, digest_clock, digest_batch
):
    source = notify(digest_subscriber)
    digest_clock.now = MONDAY
    with patch(
        "django.core.mail.EmailMultiAlternatives.send",
        side_effect=[ConnectionError("mail unavailable"), 1],
    ) as send:
        row = digest_batch()
        row.refresh_from_db()
        assert row.status == "pending" and row.retry_count == 1
        assert deliver(row.pk) is True
        assert deliver(row.pk) is True
        assert send.call_count == 2
    source.refresh_from_db()
    assert source.status == "batched" and source.digest_batch_id == row.pk


def test_opt_out_cancels_deferred_items_without_burst_sending(
    client, digest_subscriber, digest_clock, digest_batch, mailoutbox
):
    row = notify(digest_subscriber)
    client.patch(
        "/api/notifications/prefs/", {"digest_frequency": "none"}, format="json"
    )
    row.refresh_from_db()
    assert row.status == "cancelled"
    digest_clock.now = MONDAY
    assert digest_batch() is None
    assert len(mailoutbox) == 0
    digest_subscriber.refresh_from_db()
    assert notify(digest_subscriber, "Future immediate mail").status == "sent"


def test_opt_out_after_queueing_cancels_unsent_batch(
    client, digest_subscriber, digest_clock, digest_batch, mailoutbox
):
    notify(digest_subscriber)
    digest_clock.now = MONDAY
    row = digest_batch(execute=False)
    client.patch(
        "/api/notifications/prefs/", {"digest_frequency": "none"}, format="json"
    )
    row.refresh_from_db()
    assert row.status == "cancelled"
    assert deliver(row.pk) is True
    assert len(mailoutbox) == 0


def test_worker_rechecks_preference_even_if_changed_outside_api(
    digest_subscriber, digest_clock, digest_batch, mailoutbox
):
    notify(digest_subscriber)
    digest_clock.now = MONDAY
    row = digest_batch(execute=False)
    NotificationPreference.objects.filter(pk=digest_subscriber.pk).update(
        email_enabled=False
    )
    assert deliver(row.pk) is True
    row.refresh_from_db()
    assert row.status == "cancelled"
    assert len(mailoutbox) == 0


def test_global_email_disable_also_applies_to_high_priority(
    digest_subscriber, mailoutbox
):
    digest_subscriber.email_enabled = False
    digest_subscriber.save(update_fields=["email_enabled"])
    tasks.dispatch_notification(
        digest_subscriber.user, "badge", "Urgent", "M", meta={"priority": "high"}
    )
    assert not NotificationDelivery.objects.filter(channel="email").exists()
    assert len(mailoutbox) == 0


def test_source_dedupe_survives_deferral(digest_subscriber, digest_clock, digest_batch):
    first = notify(digest_subscriber, dedupe_key="event:1")
    second = notify(digest_subscriber, dedupe_key="event:1")
    assert first.pk == second.pk
    digest_clock.now = MONDAY
    assert digest_batch().payload["digest"]["total_count"] == 1


def test_email_only_preferences_still_retain_digest_payload(
    digest_subscriber, digest_clock, digest_batch, mailoutbox
):
    digest_subscriber.channel_preferences = {"badge": {"email": True, "in_app": False}}
    digest_subscriber.save(update_fields=["channel_preferences"])
    row = notify(digest_subscriber, "Email only")
    assert row.notification_id is None
    digest_clock.now = MONDAY
    assert digest_batch().payload["digest"]["total_count"] == 1
    assert "Email only" in mailoutbox[0].body


def test_large_batch_bounds_preview_but_links_every_eligible_item(
    digest_subscriber, digest_clock, digest_batch, mailoutbox
):
    NotificationDelivery.objects.bulk_create(
        [
            NotificationDelivery(
                recipient=digest_subscriber.user,
                channel="email",
                status="digest_pending",
                payload={"title": str(i)},
            )
            for i in range(105)
        ]
    )
    digest_clock.now = MONDAY
    row = digest_batch()
    snapshot = row.payload["digest"]
    assert snapshot["total_count"] == 105
    assert snapshot["omitted_count"] == 5
    assert sum(map(len, snapshot["grouped_notifications"].values())) == 100
    assert row.digest_items.count() == 105
    assert "5 more" in mailoutbox[0].body


def test_periodic_worker_integrates_weekly_batching(
    digest_subscriber, digest_clock, django_capture_on_commit_callbacks, mailoutbox
):
    notify(digest_subscriber)
    digest_clock.now = MONDAY
    with django_capture_on_commit_callbacks(execute=True):
        send_digests()
        send_digests()
    assert len(mailoutbox) == 1
    assert mailoutbox[0].subject == "Your Weekly Notification Digest"


def test_recipient_batches_never_consume_another_users_items(
    digest_subscriber, digest_clock, digest_batch, mailoutbox
):
    notify(digest_subscriber, "Mine")
    other = get_user_model().objects.create_user(
        username="isolated-weekly", email="other@example.test"
    )
    pref, _ = NotificationPreference.objects.get_or_create(user=other)
    pref.digest_frequency = "weekly"
    pref.channel_preferences = {"badge": {"email": True, "in_app": False}}
    pref.save()
    other_item = notify(pref, "Private other user")
    digest_clock.now = MONDAY
    row = digest_batch()
    assert row.payload["digest"]["total_count"] == 1
    other_item.refresh_from_db()
    assert other_item.status == "digest_pending"
    assert other_item.digest_batch_id is None
    assert "Private other user" not in mailoutbox[0].body
