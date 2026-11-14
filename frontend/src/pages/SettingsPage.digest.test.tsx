import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchApi } from "../lib/api";
import { SettingsPage } from "./SettingsPage";

vi.mock("../lib/api", () => ({ fetchApi: vi.fn() }));
vi.mock("../components/ui/LanguageSwitcher", () => ({
  LanguageSwitcher: () => <button type="button">Language</button>,
}));

const defaults = {
  email: true,
  in_app: true,
  websocket: true,
  receive_weekly_digest: true,
  digest_frequency: "none",
  digest_time: "08:00:00",
  digest_timezone: "Asia/Kolkata",
};
const api = vi.mocked(fetchApi);
const weeklyCheckbox = () =>
  screen.getByRole("checkbox", { name: "Weekly notification email digest" });
const saveButton = () =>
  screen.getByRole("button", { name: "Save notification digest" });

beforeEach(() => {
  cleanup();
  api.mockReset();
});

describe("weekly notification digest preferences", () => {
  it("loads the timezone and saves the schedule without changing the progress digest", async () => {
    api.mockResolvedValueOnce(defaults).mockResolvedValueOnce({
      ...defaults,
      digest_frequency: "weekly",
      digest_time: "09:30:00",
    });
    render(<SettingsPage />);
    await screen.findByText(/Time zone: Asia\/Kolkata/);
    expect(weeklyCheckbox()).not.toBeChecked();
    fireEvent.click(weeklyCheckbox());
    fireEvent.change(screen.getByLabelText("Monday delivery time"), {
      target: { value: "09:30" },
    });
    expect(api).toHaveBeenCalledTimes(1);
    fireEvent.click(saveButton());
    await screen.findByText("Notification preferences saved.");
    expect(api.mock.calls[1][1]?.method).toBe("PATCH");
    expect(JSON.parse(String(api.mock.calls[1][1]?.body))).toEqual({
      digest_frequency: "weekly",
      digest_time: "09:30",
    });
    expect(
      screen.getByRole("checkbox", {
        name: /Weekly Learning Progress Digest Email/,
      }),
    ).toBeChecked();
    expect(weeklyCheckbox()).toBeChecked();
  });

  it("opts out without overwriting the stored delivery time", async () => {
    api
      .mockResolvedValueOnce({ ...defaults, digest_frequency: "weekly" })
      .mockResolvedValueOnce(defaults);
    render(<SettingsPage />);
    await screen.findByText(/Time zone: Asia\/Kolkata/);
    expect(weeklyCheckbox()).toBeChecked();
    fireEvent.click(weeklyCheckbox());
    expect(screen.getByLabelText("Monday delivery time")).toBeDisabled();
    fireEvent.click(saveButton());
    await screen.findByText("Notification preferences saved.");
    expect(JSON.parse(String(api.mock.calls[1][1]?.body))).toEqual({
      digest_frequency: "none",
    });
  });

  it("reports failed saves and allows retrying the same draft", async () => {
    api
      .mockResolvedValueOnce(defaults)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        ...defaults,
        digest_frequency: "weekly",
      });
    render(<SettingsPage />);
    await screen.findByText(/Time zone: Asia\/Kolkata/);
    fireEvent.click(weeklyCheckbox());
    fireEvent.click(saveButton());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /previous settings are unchanged/,
    );
    expect(screen.queryByText("Notification preferences saved.")).toBeNull();
    expect(weeklyCheckbox()).toBeChecked();
    fireEvent.click(saveButton());
    await screen.findByText("Notification preferences saved.");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(api.mock.calls[1][1]?.body).toBe(api.mock.calls[2][1]?.body);
  });

  it("does not offer editable defaults after a failed load", async () => {
    api
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(defaults);
    render(<SettingsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Could not load/,
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText(/Time zone: Asia\/Kolkata/);
    expect(weeklyCheckbox()).not.toBeChecked();
  });

  it("preserves a digest draft while changing a different preference", async () => {
    api
      .mockResolvedValueOnce(defaults)
      .mockResolvedValueOnce({ ...defaults, email: false });
    render(<SettingsPage />);
    await screen.findByText(/Time zone: Asia\/Kolkata/);
    fireEvent.click(weeklyCheckbox());
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Email Notifications/ }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("checkbox", { name: /Email Notifications/ }),
      ).not.toBeChecked(),
    );
    expect(JSON.parse(String(api.mock.calls[1][1]?.body))).toEqual({
      email: false,
    });
    expect(weeklyCheckbox()).toBeChecked();
    expect(screen.getByText(/Email notifications are off/)).toBeInTheDocument();
  });
});
