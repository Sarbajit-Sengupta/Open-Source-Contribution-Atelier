import React, { useState, useEffect, useCallback } from "react";
import { fetchApi } from "../lib/api";
import { LanguageSwitcher } from "../components/ui/LanguageSwitcher";

type DigestFrequency = "none" | "daily" | "weekly";
interface NotificationPreferences {
  email: boolean;
  in_app: boolean;
  websocket: boolean;
  receive_weekly_digest?: boolean;
  weekly_digest?: boolean;
  digest_frequency?: DigestFrequency;
  digest_time?: string;
  digest_timezone?: string;
}

export function SettingsPage() {
  const [prefs, setPrefs] = useState<NotificationPreferences>({
    email: true,
    in_app: true,
    websocket: true,
    receive_weekly_digest: true,
  });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [weekly, setWeekly] = useState(false);
  const [digestTime, setDigestTime] = useState("08:00");

  const loadPreferences = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const data = await fetchApi<NotificationPreferences>(
        "/notifications/prefs/",
      );
      setPrefs(data);
      setWeekly(data.digest_frequency === "weekly");
      setDigestTime((data.digest_time || "08:00").slice(0, 5));
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPreferences();
  }, [loadPreferences]);

  const savePreferences = async (changes: Partial<NotificationPreferences>) => {
    setSaving(true);
    setFeedback("");
    setError("");
    try {
      const data = await fetchApi<NotificationPreferences>(
        "/notifications/prefs/",
        {
          method: "PATCH",
          body: JSON.stringify(changes),
        },
      );
      setPrefs(data);
      if ("digest_frequency" in changes) {
        setWeekly(data.digest_frequency === "weekly");
        setDigestTime((data.digest_time || "08:00").slice(0, 5));
      }
      setFeedback("Notification preferences saved.");
    } catch {
      setError(
        "Could not save notification preferences. Your previous settings are unchanged. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  const toggle = (
    key: "email" | "in_app" | "websocket" | "receive_weekly_digest",
  ) => {
    const current =
      key === "receive_weekly_digest"
        ? (prefs.receive_weekly_digest ?? prefs.weekly_digest ?? true)
        : prefs[key];
    void savePreferences({ [key]: !current });
  };

  if (loading)
    return <div role="status">Loading notification preferences...</div>;
  if (loadError)
    return (
      <div className="p-6">
        <p role="alert">Could not load notification preferences.</p>
        <button type="button" onClick={() => void loadPreferences()}>
          Try again
        </button>
      </div>
    );

  return (
    <div className="settings-page p-6 max-w-xl mx-auto bg-white dark:bg-[#111] rounded-2xl border border-black/10 dark:border-white/10 shadow-sm">
      <h2 className="text-xl font-black text-black dark:text-white mb-4 flex items-center gap-2">
        🔔 Notification Preferences
      </h2>
      <div className="settings-group flex flex-col gap-3">
        <label className="flex items-center gap-3 text-sm font-bold text-slate-700 dark:text-slate-200 cursor-pointer">
          <input
            disabled={saving}
            type="checkbox"
            checked={Boolean(prefs.email)}
            onChange={() => toggle("email")}
            className="w-4 h-4 rounded text-indigo-600"
          />
          📧 Email Notifications
        </label>
        <label className="flex items-center gap-3 text-sm font-bold text-slate-700 dark:text-slate-200 cursor-pointer">
          <input
            disabled={saving}
            type="checkbox"
            checked={Boolean(
              prefs.receive_weekly_digest ?? prefs.weekly_digest ?? true,
            )}
            onChange={() => toggle("receive_weekly_digest")}
            className="w-4 h-4 rounded text-indigo-600"
          />
          📊 Weekly Learning Progress Digest Email
        </label>
        <label className="flex items-center gap-3 text-sm font-bold text-slate-700 dark:text-slate-200 cursor-pointer">
          <input
            disabled={saving}
            type="checkbox"
            checked={Boolean(prefs.in_app)}
            onChange={() => toggle("in_app")}
            className="w-4 h-4 rounded text-indigo-600"
          />
          📱 In-App Alerts
        </label>
        <label className="flex items-center gap-3 text-sm font-bold text-slate-700 dark:text-slate-200 cursor-pointer">
          <input
            disabled={saving}
            type="checkbox"
            checked={Boolean(prefs.websocket)}
            onChange={() => toggle("websocket")}
            className="w-4 h-4 rounded text-indigo-600"
          />
          🔄 WebSocket Real-time Updates
        </label>
      </div>

      <form
        className="mt-6 space-y-3 border-t border-black/10 pt-5 dark:border-white/10"
        aria-label="Weekly notification email digest"
        onSubmit={(event) => {
          event.preventDefault();
          void savePreferences({
            digest_frequency: weekly ? "weekly" : "none",
            ...(weekly ? { digest_time: digestTime } : {}),
          });
        }}
      >
        <label className="flex items-center gap-3 text-sm font-bold text-slate-700 dark:text-slate-200">
          <input
            type="checkbox"
            checked={weekly}
            disabled={saving}
            onChange={(event) => setWeekly(event.target.checked)}
            aria-describedby="weekly-notification-description"
            className="h-4 w-4"
          />
          Weekly notification email digest
        </label>
        <p
          id="weekly-notification-description"
          className="text-sm text-slate-600 dark:text-slate-300"
        >
          Group ordinary notification emails into one Monday summary.
          High-priority emails and in-app alerts stay immediate. This is
          separate from your learning progress digest.
        </p>
        {prefs.digest_frequency === "daily" && (
          <p className="text-sm">
            A daily digest is currently configured. Saving this form replaces
            that schedule.
          </p>
        )}
        {!prefs.email && (
          <p className="text-sm text-slate-600 dark:text-slate-300">
            Email notifications are off. The weekly digest will apply when email
            is enabled.
          </p>
        )}
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
          Monday delivery time
          <input
            type="time"
            required={weekly}
            disabled={!weekly || saving}
            value={digestTime}
            onChange={(event) => setDigestTime(event.target.value)}
            aria-describedby="digest-timezone"
            className="ml-3 rounded border border-slate-300 bg-transparent px-2 py-1 dark:border-slate-600"
          />
        </label>
        <p
          id="digest-timezone"
          className="text-sm text-slate-600 dark:text-slate-300"
        >
          Time zone: {prefs.digest_timezone || "your profile time zone"}.
          Delivery starts at the next scheduled worker run after this time.
        </p>
        <button
          type="submit"
          disabled={saving}
          className="rounded bg-indigo-600 px-3 py-2 text-sm font-bold text-white disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save notification digest"}
        </button>
      </form>
      {feedback && (
        <p role="status" className="mt-3 text-sm">
          {feedback}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}

      <div className="mt-8 pt-6 border-t border-black/10 dark:border-white/10">
        <h2 className="text-xl font-black text-black dark:text-white mb-4 flex items-center gap-2">
          🌐 Language & Localization
        </h2>
        <p className="text-xs text-muted dark:text-[#9b8f80] mb-4">
          Select your preferred interface language across the application.
        </p>
        <div className="flex items-center gap-3">
          <LanguageSwitcher buttonClassName="px-3 py-2" />
          <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
            Choose from 9 supported languages (cached and persisted)
          </span>
        </div>
      </div>
    </div>
  );
}
