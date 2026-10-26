// Reproducible Playwright CLI browser audit. Run only against a local Worker:
// 1. npm run build --prefix web
// 2. From web: npx wrangler d1 migrations apply cadastre-access --local --persist-to /tmp/cadastre-manager-browser-state
// 3. From web: npx wrangler dev --local --port 8795 --persist-to /tmp/cadastre-manager-browser-state --var PUBLIC_ORIGIN:http://127.0.0.1:8795 --local-upstream 127.0.0.1:8795 --upstream-protocol http
// 4. playwright-cli --session manager open http://127.0.0.1:8795/access
// 5. From repo root: playwright-cli --session manager run-code --filename web/tests/browser/manager-audit.js
// Real API coverage creates only a local pending request. Approved/key cases use
// explicitly synthetic intercepted responses; they do not approve any organization.
async function auditManager(page) {
  const origin = new URL(page.url()).origin;
  if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(origin)) {
    throw new Error("This audit must run against a local Worker.");
  }
  const reports = [];
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const wait = async (check, message, attempt = 0) => {
    if (await check()) return;
    if (attempt >= 100) throw new Error(message);
    await page.waitForTimeout(20);
    return wait(check, message, attempt + 1);
  };
  const button = (name) => page.getByRole("button", { name, exact: true });
  const clearButton = () => button("Clear credentials from this page");
  const claimButton = () => button("Claim one-time research key");
  const fill = async (claim) => {
    await page.getByLabel("Saved request ID").fill(claim.request_id);
    await page.getByLabel("Private claim token").fill(claim.claim_token);
    await button("Check request status").click();
  };
  const clean = async (secret) => {
    const result = await page.evaluate(
      (value) => ({
        url: location.href.includes(value),
        local: JSON.stringify(localStorage).includes(value),
        session: JSON.stringify(sessionStorage).includes(value),
      }),
      secret,
    );
    assert(
      !result.url && !result.local && !result.session,
      "Credentials escaped into URL or persistent browser storage",
    );
  };
  const noClaim = async () =>
    assert(
      (await claimButton().count()) === 0,
      "An ineligible request showed a claim action",
    );
  const gate = () => {
    let release;
    const promise = new Promise((resolve) => {
      release = resolve;
    });
    return { promise, release: () => release() };
  };

  async function beforeJavaScript() {
    const browser = page.context().browser();
    assert(browser, "A browser is required for the JavaScript-disabled audit");
    const context = await browser.newContext({ javaScriptEnabled: false });
    const probe = await context.newPage();
    const fake = {
      request_id: "00000000-0000-0000-0000-000000000000",
      claim_token: "A".repeat(43),
    };
    try {
      await probe.goto(origin + "/access");
      assert(
        await probe.getByLabel("Saved request ID").isDisabled(),
        "SSR request ID was enabled before React mounted",
      );
      assert(
        await probe.getByLabel("Private claim token").isDisabled(),
        "SSR claim token was enabled before React mounted",
      );
      assert(
        await probe
          .getByRole("button", { name: "Preparing request manager…" })
          .isDisabled(),
        "SSR submission was enabled before React mounted",
      );
      assert(
        (await probe.locator("form").getAttribute("method")) === "post",
        "Native form fallback was GET",
      );
      assert(
        (await probe.locator("body").innerText()).includes(
          "Enable JavaScript to manage your request.",
        ),
        "No-script recovery guidance was missing",
      );
      const navigation = probe.waitForResponse(
        (response) =>
          response.request().isNavigationRequest() &&
          response.request().method() === "POST",
      );
      // Force the native fallback even though a visitor cannot interact with the
      // disabled controls. This covers accidental re-enablement without React.
      await probe.evaluate((claim) => {
        const form = document.querySelector("form");
        for (const name of ["request_id", "claim_token"]) {
          const input = form.elements.namedItem(name);
          input.disabled = false;
          input.value = claim[name];
        }
        form.submit();
      }, fake);
      const response = await navigation;
      const url = new URL(response.url());
      assert(
        response.status() === 405,
        "Native POST fallback was not safely rejected by the Worker",
      );
      assert(
        !url.search && !url.hash && !url.href.includes(fake.claim_token),
        "Native fallback exposed credentials in URL",
      );
      assert(
        response.request().postData().includes(fake.claim_token),
        "Forced native fallback did not retain credentials in body",
      );
      reports.push(
        "Before JavaScript: SSR controls disabled; forced native fallback POST rejected405 with no query credentials",
      );
    } finally {
      await context.close();
    }
  }

  async function realPendingWorker() {
    await page.goto(origin + "/access");
    await page.getByLabel("Saved request ID").waitFor();
    const claim = await page.evaluate(async () => {
      const policy = await (await fetch("/v1/policy")).json();
      const response = await fetch("/v1/access-requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          legal_name: "Local browser audit",
          registration_number: "LOCAL-ONLY",
          registration_jurisdiction: "California",
          organization_domain: "example.gov",
          work_email: "local-audit@example.gov",
          applicant_name: "Local Browser Fixture",
          use_case:
            "Exercise the local browser request manager and server-side access gates.",
          attestation: {
            accepted: true,
            version: policy.version,
            applicant_authorized: true,
            legitimate_use: true,
            no_replication: true,
          },
        }),
      });
      if (response.status !== 201)
        throw new Error("Local pending request could not be created");
      return response.json();
    });
    await fill(claim);
    await page
      .getByText("Pending organization and applicant authority review.", {
        exact: false,
      })
      .waitFor();
    await noClaim();
    await clean(claim.claim_token);
    const refused = await page.evaluate(async (value) => {
      const response = await fetch(
        `/v1/access-requests/${value.request_id}/claim-key`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ claim_token: value.claim_token }),
        },
      );
      return response.status;
    }, claim);
    assert(refused === 403, "The actual Worker permitted a pending key claim");
    await clearButton().click();
    assert(
      (await page.getByLabel("Private claim token").inputValue()) === "",
      "Clear retained the claim token",
    );
    reports.push(
      "Actual local Worker: pending restoration, server refusal, memory-only credentials, explicit clear",
    );
  }

  const firstId = "12345678-1234-1234-1234-123456789abc";
  const secondId = "abcdef12-1234-1234-1234-123456789abc";
  const fake = { request_id: firstId, claim_token: "s".repeat(43) };
  const keyId = "a".repeat(24);
  const key = `kl_live_${keyId}_${"b".repeat(43)}`;
  let statusMode = "pending";
  let keyMode = "valid";
  let statusGate = null;
  let keyGate = null;
  let statusRequests = 0;
  let keyRequests = 0;
  let forwarded = 0;
  let keyClaimed = false;
  let domainVerified = false;
  const approved = (id) => ({
    request_id: id,
    status: "approved",
    domain_verified: true,
    key_claimed: keyClaimed,
  });
  const json = (route, body, status = 200) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

  async function statusResponse(route, id) {
    statusRequests++;
    const held = statusGate;
    if (held) await held.promise;
    if (statusMode === "redirect")
      return route.fulfill({
        status: 307,
        headers: { Location: "https://manager-attacker.invalid/stolen" },
      });
    if (statusMode === "malformed")
      return json(route, { request_id: id, status: "approved" });
    if (statusMode === "wrong-request") return json(route, approved(secondId));
    if (statusMode === "approved") return json(route, approved(id));
    if (statusMode === "rejected")
      return json(route, {
        request_id: id,
        status: "rejected",
        domain_verified: false,
        key_claimed: false,
      });
    return json(route, {
      request_id: id,
      status: "pending_review",
      domain_verified: domainVerified,
      key_claimed: false,
    });
  }
  async function mockApi(route) {
    const request = route.request();
    const url = new URL(request.url());
    assert(request.method() === "POST", "Manager used a non-POST operation");
    assert(
      !url.search && !url.hash && !url.href.includes(fake.claim_token),
      "Manager put credentials in URL",
    );
    assert(
      request.postDataJSON().claim_token === fake.claim_token,
      "Claim token missing from JSON body",
    );
    const segments = url.pathname.split("/");
    if (segments.at(-1) === "status")
      return statusResponse(route, segments.at(-2));
    if (segments.at(-1) === "verify-domain") {
      domainVerified = true;
      return json(route, {
        request_id: segments.at(-2),
        status: "pending_review",
        domain_verified: true,
        approval_granted: false,
      });
    }
    keyRequests++;
    if (keyGate) await keyGate.promise;
    keyClaimed = true;
    if (keyMode === "malformed")
      return json(route, {
        api_key: key,
        key_id: "wrong",
        expires_at: "invalid",
      });
    return json(route, {
      api_key: key,
      key_id: keyId,
      expires_at: "2026-11-25T00:00:00.000Z",
    });
  }
  async function fresh(mode) {
    statusMode = mode;
    statusGate = null;
    keyGate = null;
    keyClaimed = false;
    domainVerified = false;
    keyMode = "valid";
    await page.goto(origin + "/access");
    await page.getByLabel("Saved request ID").waitFor();
  }

  async function staleAndDoubleRefresh() {
    await fresh("pending");
    await fill(fake);
    await clearButton().waitFor();
    await button("Verify domain").click();
    await page
      .getByText(
        "Domain control verified. Organization and applicant authority review remain separate.",
        { exact: true },
      )
      .waitFor();
    await noClaim();
    assert(
      (await button("Verify domain").count()) === 0,
      "Verified domain action remained active",
    );
    const before = statusRequests;
    statusGate = gate();
    await button("Refresh status").dblclick();
    await wait(() => statusRequests > before, "Refresh was not sent");
    assert(
      await clearButton().isDisabled(),
      "Clear remained active during a stale response",
    );
    assert(
      await button("Refresh status").isDisabled(),
      "Refresh remained active during its own request",
    );
    await clearButton().evaluate((element) => element.click());
    assert(
      (await page.getByLabel("Saved request ID").count()) === 0,
      "Disabled clear restored the credential form during a request",
    );
    statusGate.release();
    await wait(() => clearButton().isEnabled(), "Refresh did not settle");
    assert(
      statusRequests === before + 1,
      "Double refresh sent duplicate requests",
    );
    await clearButton().click();
    statusGate = null;
    statusMode = "approved";
    await fill({ ...fake, request_id: secondId });
    await claimButton().waitFor();
    assert(
      (await page.getByText(secondId, { exact: true }).count()) === 1,
      "New request restoration was replaced by stale state",
    );
    await clean(fake.claim_token);
    reports.push(
      "Async: busy clear blocked, double refresh coalesced, clear/new restoration kept the new request",
    );
  }
  async function doubleClaimAndClear() {
    const before = keyRequests;
    keyGate = gate();
    await claimButton().dblclick();
    await wait(() => keyRequests > before, "Claim was not sent");
    assert(
      await clearButton().isDisabled(),
      "Clear remained active during key issuance",
    );
    assert(
      await button("Refresh status").isDisabled(),
      "Refresh raced key issuance",
    );
    keyGate.release();
    await page.getByRole("textbox", { name: "Research API key" }).waitFor();
    assert(keyRequests === before + 1, "Double click sent multiple key claims");
    assert(
      (await page
        .getByRole("textbox", { name: "Research API key" })
        .inputValue()) === key,
      "Valid key was not displayed intact",
    );
    await noClaim();
    await clean(key);
    await clearButton().click();
    assert(
      (await page
        .getByRole("textbox", { name: "Research API key" })
        .count()) === 0,
      "Clear retained one-time key DOM",
    );
    assert(
      (await page.getByLabel("Private claim token").inputValue()) === "",
      "Clear retained token after key delivery",
    );
    reports.push(
      "One-time key: double claim coalesced, refresh/clear locked while pending, key and token removed on clear",
    );
  }
  async function malformedAndRedirects() {
    await fresh("malformed");
    await fill(fake);
    await page
      .getByRole("alert")
      .filter({ hasText: "incomplete request status" })
      .waitFor();
    await noClaim();
    await fresh("wrong-request");
    await fill(fake);
    await page
      .getByRole("alert")
      .filter({ hasText: "incomplete request status" })
      .waitFor();
    await noClaim();
    await fresh("redirect");
    await fill(fake);
    await page.getByRole("alert").waitFor();
    assert(forwarded === 0, "Browser forwarded token to redirect destination");
    await noClaim();
    await fresh("rejected");
    await fill(fake);
    await page
      .getByText("This request was rejected.", { exact: false })
      .waitFor();
    await noClaim();
    reports.push(
      "Untrusted responses: malformed status, cross-request response, redirect forwarding, rejected state all fail closed",
    );
  }
  async function malformedOneTimeReceipt() {
    await fresh("approved");
    keyMode = "malformed";
    await fill(fake);
    await claimButton().waitFor();
    await claimButton().click();
    await page
      .getByRole("alert")
      .filter({ hasText: "complete key receipt was not received" })
      .waitFor();
    assert(
      (await page
        .getByRole("textbox", { name: "Research API key" })
        .count()) === 0,
      "Malformed key was displayed",
    );
    await button("Refresh status").click();
    await page
      .getByText("Your key was already claimed", { exact: false })
      .waitFor();
    await noClaim();
    await page.reload();
    assert(
      (await page.getByLabel("Private claim token").inputValue()) === "",
      "Reload restored a private token",
    );
    await clean(fake.claim_token);
    await clean(key);
    reports.push(
      "Ambiguous delivery: malformed key receipt never displayed; status resolves claimed state; reload retains no secret",
    );
  }

  await beforeJavaScript();
  await realPendingWorker();
  await page.route("https://manager-attacker.invalid/**", async (route) => {
    forwarded++;
    await route.abort();
  });
  await page.route(origin + "/v1/access-requests/**", mockApi);
  try {
    await staleAndDoubleRefresh();
    await doubleClaimAndClear();
    await malformedAndRedirects();
    await malformedOneTimeReceipt();
  } finally {
    await page.unroute(origin + "/v1/access-requests/**", mockApi);
    await page.unroute("https://manager-attacker.invalid/**");
  }
  return {
    passed: reports,
    syntheticKeyClaims: keyRequests,
    redirectDestinationsContacted: forwarded,
    productionWrites: 0,
  };
}
