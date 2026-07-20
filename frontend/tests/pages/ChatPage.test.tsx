import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import ChatPage from "@/pages/ChatPage";

const now = "2026-07-20T16:00:00Z";

function renderChat(route = "/chat") {
  return render(
    <Routes>
      <Route path="/chat" element={<ChatPage />} />
      <Route path="/chat/:threadId" element={<ChatPage />} />
    </Routes>,
    { route, useMemoryRouter: true },
  );
}

describe("ChatPage", () => {
  it("directs unconfigured users to AI settings", async () => {
    server.use(
      http.get("/api/ai/status", () =>
        HttpResponse.json({ configured: false, circuit_state: "closed" }),
      ),
      http.get("/api/ai/chat/threads", () =>
        HttpResponse.json({ threads: [], next_cursor: null }),
      ),
    );

    renderChat();

    expect(await screen.findByText("Connect an AI provider")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Open AI Settings" }),
    ).toBeTruthy();
  });

  it("creates a saved thread and renders its streamed answer", async () => {
    let submittedText = "";
    const thread = {
      id: "thread-1",
      title: "Which series are closest to complete?",
      created_at: now,
      updated_at: now,
      message_count: 2,
    };
    const userMessage = {
      id: "message-1",
      thread_id: thread.id,
      role: "user" as const,
      content: "Which series are closest to complete?",
      status: "complete" as const,
      results: [],
      attachments: [],
      created_at: now,
    };
    const assistantMessage = {
      id: "message-2",
      thread_id: thread.id,
      role: "assistant" as const,
      content: "Saga is closest at 98% complete.",
      status: "complete" as const,
      results: [],
      attachments: [],
      created_at: now,
    };

    server.use(
      http.get("/api/ai/status", () =>
        HttpResponse.json({ configured: true, circuit_state: "closed" }),
      ),
      http.get("/api/ai/chat/threads", () =>
        HttpResponse.json({ threads: [], next_cursor: null }),
      ),
      http.get("/api/ai/chat/threads/:threadId", () =>
        HttpResponse.json({
          ...thread,
          messages: [userMessage, assistantMessage],
        }),
      ),
      http.post("/api/ai/chat/turns/stream", async ({ request }) => {
        const form = await request.formData();
        submittedText = String(form.get("content") || "");
        const events = [
          { type: "thread", thread },
          { type: "user_message", message: userMessage },
          { type: "text", content: assistantMessage.content },
          { type: "done", message: assistantMessage },
        ];
        return new HttpResponse(
          events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      }),
    );

    const user = userEvent.setup();
    renderChat();

    await user.click(
      await screen.findByRole("button", { name: /Finish a run/ }),
    );
    await user.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      expect(submittedText).toBe("Which series are closest to complete?");
    });
    expect(
      await screen.findByText("Saga is closest at 98% complete."),
    ).toBeTruthy();
    expect(await screen.findByText(thread.title)).toBeTruthy();
  });

  it("keeps a vision-rejected draft ready for retry", async () => {
    server.use(
      http.get("/api/ai/status", () =>
        HttpResponse.json({ configured: true, circuit_state: "closed" }),
      ),
      http.get("/api/ai/chat/threads", () =>
        HttpResponse.json({ threads: [], next_cursor: null }),
      ),
      http.post(
        "/api/ai/chat/turns/stream",
        () =>
          new HttpResponse(
            [
              {
                type: "error",
                code: "vision_unsupported",
                content: "Choose a vision-capable model.",
                retryable: false,
              },
              { type: "done", message: null },
            ]
              .map((event) => `data: ${JSON.stringify(event)}\n\n`)
              .join(""),
            { headers: { "Content-Type": "text/event-stream" } },
          ),
      ),
    );

    const user = userEvent.setup();
    renderChat();
    const composer = await screen.findByRole("textbox", {
      name: "Message Library Chat",
    });
    await user.type(composer, "Identify this cover");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(
      await screen.findByText("Choose a vision-capable model."),
    ).toBeTruthy();
    expect((composer as HTMLTextAreaElement).value).toBe("Identify this cover");
  });

  it("keeps a persisted draft when the stream ends before done", async () => {
    const thread = {
      id: "thread-truncated",
      title: "Interrupted question",
      created_at: now,
      updated_at: now,
      message_count: 1,
    };
    const userMessage = {
      id: "message-truncated",
      thread_id: thread.id,
      role: "user" as const,
      content: "Interrupted question",
      status: "complete" as const,
      results: [],
      attachments: [],
      created_at: now,
    };
    server.use(
      http.get("/api/ai/status", () =>
        HttpResponse.json({ configured: true, circuit_state: "closed" }),
      ),
      http.get("/api/ai/chat/threads", () =>
        HttpResponse.json({ threads: [], next_cursor: null }),
      ),
      http.get("/api/ai/chat/threads/:threadId", () =>
        HttpResponse.json({ ...thread, messages: [userMessage] }),
      ),
      http.post(
        "/api/ai/chat/turns/stream",
        () =>
          new HttpResponse(
            [
              { type: "thread", thread },
              { type: "user_message", message: userMessage },
              { type: "text", content: "Partial" },
            ]
              .map((event) => `data: ${JSON.stringify(event)}\n\n`)
              .join(""),
            { headers: { "Content-Type": "text/event-stream" } },
          ),
      ),
    );

    const user = userEvent.setup();
    renderChat();
    const composer = await screen.findByRole("textbox", {
      name: "Message Library Chat",
    });
    await user.type(composer, "Interrupted question");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(
      await screen.findByText(
        "The chat response ended before it completed. Send again to retry.",
      ),
    ).toBeTruthy();
    expect((composer as HTMLTextAreaElement).value).toBe(
      "Interrupted question",
    );
  });

  it("does not carry a composer draft into another thread", async () => {
    const threads = [
      {
        id: "thread-a",
        title: "Thread Alpha",
        created_at: now,
        updated_at: now,
        message_count: 0,
      },
      {
        id: "thread-b",
        title: "Thread Beta",
        created_at: now,
        updated_at: now,
        message_count: 0,
      },
    ];
    server.use(
      http.get("/api/ai/status", () =>
        HttpResponse.json({ configured: true, circuit_state: "closed" }),
      ),
      http.get("/api/ai/chat/threads", () =>
        HttpResponse.json({ threads, next_cursor: null }),
      ),
      http.get("/api/ai/chat/threads/:threadId", ({ params }) => {
        const thread = threads.find((item) => item.id === params.threadId)!;
        return HttpResponse.json({ ...thread, messages: [] });
      }),
    );

    const user = userEvent.setup();
    renderChat("/chat/thread-a");
    const composer = await screen.findByRole("textbox", {
      name: "Message Library Chat",
    });
    await user.type(composer, "Only for Alpha");
    await user.click(
      await screen.findByRole("button", { name: /^Thread Beta 0 messages/ }),
    );

    await waitFor(() =>
      expect((composer as HTMLTextAreaElement).value).toBe(""),
    );
  });
});
