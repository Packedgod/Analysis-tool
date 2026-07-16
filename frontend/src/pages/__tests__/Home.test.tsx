import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Home } from "@/pages/Home";

vi.mock("@/lib/api", () => ({
  api: {
    startAnalysis: vi.fn(),
    uploadFile: vi.fn(),
  },
}));

describe("Home", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends only the user-facing brief to the private analysis endpoint", async () => {
    vi.mocked(api.startAnalysis).mockResolvedValue({
      session_id: "session-1",
      attempt_id: "attempt-1",
      message_id: "message-1",
      status: "started",
    });

    render(<MemoryRouter><Home /></MemoryRouter>);

    fireEvent.change(screen.getByPlaceholderText("Reliance Industries"), {
      target: { value: "Reliance Industries" },
    });
    fireEvent.change(screen.getByPlaceholderText("RELIANCE.NS"), {
      target: { value: "RELIANCE.NS" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start analysis" }));

    await waitFor(() => expect(api.startAnalysis).toHaveBeenCalledWith(expect.objectContaining({
      company: "Reliance Industries",
      ticker: "RELIANCE.NS",
      history_years: 3,
    })));
  });
});

