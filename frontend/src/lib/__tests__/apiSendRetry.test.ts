import { ApiError, api } from "@/lib/api";

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ "content-type": "application/json" }),
    text: async () => JSON.stringify(payload),
  } as Response;
}

describe("message send recovery", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("retries network failures with one stable idempotency key", async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError("connection refused"))
      .mockRejectedValueOnce(new TypeError("connection refused"))
      .mockResolvedValue(jsonResponse({ message_id: "m1", attempt_id: "a1" }));
    vi.stubGlobal("fetch", fetchMock);

    const pending = api.sendMessage("session1", "run the backtest");
    await vi.runAllTimersAsync();
    await expect(pending).resolves.toEqual({ message_id: "m1", attempt_id: "a1" });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const bodies = fetchMock.mock.calls.map((call) => JSON.parse(String(call[1]?.body)));
    expect(new Set(bodies.map((body) => body.client_request_id)).size).toBe(1);
    expect(bodies.every((body) => body.content === "run the backtest")).toBe(true);
  });

  it("returns an actionable local-service error after retry exhaustion", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("connection refused"));
    vi.stubGlobal("fetch", fetchMock);

    const pending = api.sendMessage("session1", "run the backtest");
    const assertion = expect(pending).rejects.toMatchObject<Partial<ApiError>>({
      name: "ApiError",
      status: 0,
    });
    await vi.runAllTimersAsync();
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });
});
