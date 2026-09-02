import { expect, test } from "@playwright/test";

async function openDashboard(page) {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await expect(page.locator("#repository-intelligence")).toBeVisible();
}

test("the Charter has a readable, contained hierarchy", async ({ page }) => {
  await openDashboard(page);
  const charter = page.locator("#repository-intelligence");

  await expect(charter.locator(".charter-state")).toHaveText(/current|provisional|stale/i);
  await expect(charter.locator(".charter-section")).toHaveCount(7);
  await expect(charter.locator(".charter-section h3")).toHaveText([
    "Observable capabilities",
    "Responsibility areas",
    "Important flows",
    "Safe extension points",
    "Coherence concerns",
    "Unknowns and conflicts",
    "Declared context",
  ]);

  const typeSizes = await charter.evaluate((element) => ({
    title: Number.parseFloat(getComputedStyle(element.querySelector("h2")).fontSize),
    section: Number.parseFloat(getComputedStyle(element.querySelector("h3")).fontSize),
    content: Number.parseFloat(getComputedStyle(element.querySelector("li")).fontSize),
  }));
  expect(typeSizes.title).toBeGreaterThan(typeSizes.section);
  expect(typeSizes.section).toBeGreaterThan(typeSizes.content);
  expect(await charter.locator(".charter-section").evaluateAll((sections) => (
    sections.every((section) => section.scrollWidth <= section.clientWidth + 1)
  ))).toBe(true);
});

test("long finding tags wrap inside phone cards", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openDashboard(page);
  await page.locator("#finding-preview").evaluate((preview) => {
    let list = preview.querySelector(".tag-list");
    if (!list) {
      list = document.createElement("div");
      list.className = "tag-list";
      preview.querySelector(".finding-card > div")?.append(list);
    }
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = "a-very-long-unbroken-real-repository-tag-that-must-stay-inside-its-finding-card";
    list.append(tag);
  });

  const layout = await page.evaluate(() => ({
    documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    previewFits: document.querySelector("#finding-preview").scrollWidth
      <= document.querySelector("#finding-preview").clientWidth + 1,
  }));
  expect(layout).toEqual({ documentFits: true, previewFits: true });
});

test("long metric values stay inside their cards", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openDashboard(page);
  const metric = page.locator(".metric").first();
  await metric.locator("strong").evaluate((value) => {
    value.textContent = "No-internal-references-found-for-this-module";
  });

  const layout = await metric.evaluate((card) => {
    const value = card.querySelector("strong");
    return {
      cardFits: card.scrollWidth <= card.clientWidth + 1,
      valueFits: value.scrollWidth <= value.clientWidth + 1,
    };
  });
  expect(layout).toEqual({ cardFits: true, valueFits: true });
});

test("every dashboard journey stays inside desktop and phone viewports", async ({ browser }) => {
  const views = [
    ["overview", null],
    ["modules", "[data-subview=modules]"],
    ["graph", "[data-subview=graph]"],
    ["agents", "[data-view=agents]"],
    ["architecture", "[data-view=architecture]"],
    ["patterns", "[data-subview=patterns]"],
    ["fresh-eyes", "[data-subview=fresh-eyes]"],
    ["history", "[data-view=history]"],
    ["settings", "[data-view=settings]"],
  ];

  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport });
    await openDashboard(page);
    for (const [name, selector] of views) {
      if (selector) await page.locator(selector).first().click();
      await expect(page.locator(`#view-${name}`)).toBeVisible();
      const layout = await page.evaluate(() => {
        const view = document.querySelector(".view.active");
        const overflow = [...view.querySelectorAll("*")].filter((element) => {
          const style = getComputedStyle(element);
          const rendered = style.display !== "none"
            && style.visibility !== "hidden"
            && element.getClientRects().length > 0
            && element.clientWidth > 0
            && element.clientHeight > 0;
          const intentionallyScrollable = ["auto", "scroll"].includes(style.overflowX);
          return rendered
            && !intentionallyScrollable
            && element.scrollWidth > element.clientWidth + 2;
        });
        return {
          documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
          viewFits: view.scrollWidth <= view.clientWidth + 1,
          overflow: overflow.map((element) => {
            const identity = element.id
              ? `#${element.id}`
              : [...element.classList].map((name) => `.${name}`).join("");
            const content = (element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 50);
            return `${element.tagName.toLowerCase()}${identity} `
              + `"${content}" (${element.clientWidth}px box, ${element.scrollWidth}px content)`;
          }).slice(0, 5),
        };
      });
      expect(layout, `${name} at ${viewport.width}px`).toEqual({
        documentFits: true,
        viewFits: true,
        overflow: [],
      });
    }
    await page.close();
  }
});
