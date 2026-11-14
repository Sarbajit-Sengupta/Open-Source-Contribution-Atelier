from rest_framework import serializers

from .models import Notification, PushSubscription


class NotificationSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(
        source="sender.username", read_only=True, allow_null=True
    )

    class Meta:
        model = Notification
        fields = [
            "id",
            "notif_type",
            "title",
            "message",
            "is_read",
            "created_at",
            "sender_username",
            "meta",
        ]


class PushSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushSubscription
        fields = ["endpoint", "p256dh", "auth"]


class NotificationDigestPreferencesSerializer(serializers.Serializer):
    digest_frequency = serializers.ChoiceField(
        choices=["none", "daily", "weekly"], required=False
    )
    digest_time = serializers.TimeField(
        required=False, input_formats=["%H:%M", "%H:%M:%S"]
    )
    digest_timezone = serializers.SerializerMethodField()

    def get_digest_timezone(self, pref):
        from .digests import recipient_timezone

        return str(recipient_timezone(pref))

    def validate_digest_time(self, value):
        if value.tzinfo is not None:
            raise serializers.ValidationError("Use a local time without a UTC offset.")
        return value
