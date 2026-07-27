import { expect, test } from "@playwright/test";

const now = "2026-07-20T16:00:00Z";
const thread = {
  id: "thread-e2e",
  title: "Identify this cover",
  created_at: now,
  updated_at: now,
  message_count: 2,
};

test("creates, reopens, and deletes an image-aware saved chat", async ({
  page,
}) => {
  let saved = false;
  let deleted = false;
  const messages = [
    {
      id: "message-user-e2e",
      thread_id: thread.id,
      role: "user",
      content: "Identify this cover",
      status: "complete",
      results: [],
      attachments: [
        {
          id: "attachment-e2e",
          filename: "cover.png",
          media_type: "image/webp",
          byte_size: 68,
          width: 1,
          height: 1,
          url: `/api/ai/chat/threads/${thread.id}/attachments/attachment-e2e`,
        },
      ],
      created_at: now,
    },
    {
      id: "message-assistant-e2e",
      thread_id: thread.id,
      role: "assistant",
      content: "This looks like a Saga cover in your library.",
      status: "complete",
      results: [],
      attachments: [],
      created_at: now,
    },
  ];

  await page.route("**/api/ai/status", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ configured: true, circuit_state: "closed" }),
    }),
  );
  await page.route("**/api/ai/chat/threads?**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        threads: saved && !deleted ? [thread] : [],
        next_cursor: null,
      }),
    }),
  );
  await page.route(`**/api/ai/chat/threads/${thread.id}`, async (route) => {
    if (route.request().method() === "DELETE") {
      deleted = true;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...thread, messages }),
    });
  });
  await page.route(
    `**/api/ai/chat/threads/${thread.id}/attachments/attachment-e2e`,
    (route) =>
      route.fulfill({
        contentType: "image/webp",
        body: Buffer.from(
          "UklGRkoAAABXRUJQVlA4ID4AAADwAQCdASoBAAEAAUAmJQBOgCHwAP7/EAAA",
          "base64",
        ),
      }),
  );
  await page.route("**/api/ai/chat/turns/stream", async (route) => {
    saved = true;
    const events = [
      { type: "thread", thread },
      { type: "user_message", message: messages[0] },
      { type: "text", content: messages[1].content },
      { type: "done", message: messages[1] },
    ];
    await route.fulfill({
      contentType: "text/event-stream",
      body: events
        .map((event) => `data: ${JSON.stringify(event)}\n\n`)
        .join(""),
    });
  });

  await page.goto("/chat");
  await expect(
    page.getByRole("button", { name: "Back to Comicarr" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Dashboard" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "New chat" })).toBeVisible();

  await page.getByLabel("Attach images").click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "cover.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await expect(page.getByText("cover.png", { exact: true })).toBeVisible();
  await page.getByLabel("Message Chat").fill("Identify this cover");
  await page.getByLabel("Send message").click();

  await expect(page).toHaveURL(/\/chat\/thread-e2e$/);
  await expect(page.getByText(messages[1].content)).toBeVisible();

  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await page
    .getByRole("button", { name: /^Identify this cover 2 msgs/ })
    .click();
  await expect(page.getByText(messages[1].content)).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByLabel(`Actions for ${thread.title}`).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(
    page.getByText("Saved conversations appear here."),
  ).toBeVisible();
});
