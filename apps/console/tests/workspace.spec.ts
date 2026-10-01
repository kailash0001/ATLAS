import { test, expect } from "@playwright/test";
test("landing, visible demo access, authenticated workspace and sign out", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Every model. Under control." }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Demo access", exact: true }).click();
  await expect(page.locator(".credential-fields")).toContainText("atlas_local");
  await page.getByRole("link", { name: "Open login", exact: true }).click();
  await page.getByLabel("Username", { exact: true }).fill("atlas");
  await page.getByLabel("Password", { exact: true }).fill("wrong");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page.getByRole("alert")).toContainText("incorrect");
  await page.getByRole("button", { name: "Use demo credentials" }).click();
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page).toHaveURL(/overview/);
  await expect(
    page.getByRole("heading", { name: "Platform overview" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Models", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Registered workloads" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open command palette" }).click();
  await page
    .getByRole("dialog")
    .getByRole("link", { name: "Settings", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Workspace configuration" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/login/);
  await page.goto("/models");
  await expect(page).toHaveURL(/login/);
});
test("scroll illustration changes with progress and mobile has no page overflow", async ({
  page,
}) => {
  await page.goto("/");
  const scene = page.locator(".scene-3d");
  const before = await scene.evaluate((el) => getComputedStyle(el).transform);
  await page.locator("#workloads").scrollIntoViewIfNeeded();
  await expect
    .poll(() => scene.evaluate((el) => getComputedStyle(el).transform))
    .not.toBe(before);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBeTruthy();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(
    page.getByRole("link", { name: "Skip animation" }),
  ).toBeAttached();
});
test("API proxy rejects unauthenticated reads and cross-origin login", async ({
  request,
}) => {
  expect((await request.get("/api/state")).status()).toBe(401);
  expect(
    (
      await request.post("/api/auth/login", {
        headers: { Origin: "https://untrusted.example" },
        data: { username: "atlas", password: "atlas_local" },
      })
    ).status(),
  ).toBe(403);
});
