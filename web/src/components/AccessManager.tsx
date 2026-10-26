import {
  canClaim,
  statusMessage,
  type ClaimedKey,
  type RequestStatus,
} from "../lib/manager-model";
import { useRequestManager } from "../lib/manager";
import { useEffect, useState } from "react";

export function KeyReceipt({ receipt }: Readonly<{ receipt: ClaimedKey }>) {
  return (
    <section className="access-result" aria-label="One-time key receipt">
      <h2>Save your key now.</h2>
      <p>
        This is its only display. Save it in your organization’s secret manager
        before leaving or clearing this page. Do not post it in an issue, URL,
        or message.
      </p>
      <label>
        Research API key{" "}
        <textarea
          readOnly
          rows={3}
          value={receipt.api_key}
          autoComplete="off"
          spellCheck={false}
          aria-label="Research API key"
        />
      </label>
      <p>
        Expires: <time dateTime={receipt.expires_at}>{receipt.expires_at}</time>
        . Revocation or a change in eligibility can end access earlier; each API
        request is checked by the server.
      </p>
    </section>
  );
}

export function AccessManagerView({
  manager,
  ready,
}: Readonly<{
  manager: ReturnType<typeof useRequestManager>;
  ready: boolean;
}>) {
  const submitLabel = ready
    ? "Check request status"
    : "Preparing request manager…";
  return (
    <section className="access-form" aria-label="Manage research request">
      {!manager.claim && (
        <form
          method="post"
          action="/access"
          onSubmit={manager.submit}
          autoComplete="off"
        >
          <div className="form-grid">
            <label>
              Saved request ID{" "}
              <input
                name="request_id"
                required
                maxLength={36}
                minLength={36}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                disabled={manager.busy || !ready}
              />
            </label>
            <label>
              Private claim token{" "}
              <input
                name="claim_token"
                type="password"
                required
                minLength={43}
                maxLength={43}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                disabled={manager.busy || !ready}
              />
            </label>
          </div>
          <button
            className="button button-primary"
            type="submit"
            disabled={manager.busy || !ready}
          >
            {manager.busy ? "Checking request…" : submitLabel}
          </button>
          <noscript>
            <p>
              Enable JavaScript to manage your request. Keep your saved receipt
              private.
            </p>
          </noscript>
        </form>
      )}
      {manager.status && (
        <RequestStatusPanel manager={manager} status={manager.status} />
      )}
      {manager.notice && (
        <p>
          <output aria-live="polite">{manager.notice}</output>
        </p>
      )}
      {manager.error && (
        <p className="form-error" role="alert">
          {manager.error}
        </p>
      )}
      {manager.key && <KeyReceipt receipt={manager.key} />}
      {manager.claim && (
        <div>
          <p className="form-note">
            Save any displayed key before clearing. Clearing removes this page’s
            in-memory credentials; it does not revoke a key or withdraw a
            request.
          </p>
          <button
            className="button button-secondary"
            type="button"
            disabled={manager.busy}
            onClick={manager.clear}
          >
            Clear credentials from this page
          </button>
        </div>
      )}
    </section>
  );
}

function RequestStatusPanel({
  manager,
  status,
}: Readonly<{
  manager: ReturnType<typeof useRequestManager>;
  status: RequestStatus;
}>) {
  return (
    <div>
      <h2>Request status</h2>
      <p>
        <code>{status.request_id}</code>
      </p>
      <output aria-live="polite">{statusMessage(status)}</output>
      <p className="form-note">
        This is the server’s last reported status. Refresh to check for a review
        decision.
      </p>
      <button
        className="button button-secondary"
        type="button"
        disabled={manager.busy}
        onClick={() => manager.act("status")}
      >
        Refresh status
      </button>
      {status.status !== "rejected" && !status.domain_verified && (
        <div>
          <p>
            Add the DNS TXT name and value from your original receipt before
            checking. Proving domain control does not approve an organization or
            applicant.
          </p>
          <button
            className="button button-secondary"
            type="button"
            disabled={manager.busy}
            onClick={() => manager.act("verify")}
          >
            Verify domain
          </button>
        </div>
      )}
      {canClaim(status) && !manager.key && (
        <div>
          <p>
            Your key is displayed only once. Be ready to save it before
            continuing.
          </p>
          <button
            className="button button-primary"
            type="button"
            disabled={manager.busy}
            onClick={() => manager.act("claim")}
          >
            Claim one-time research key
          </button>
        </div>
      )}
    </div>
  );
}

export default function AccessManager() {
  const manager = useRequestManager();
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  return <AccessManagerView manager={manager} ready={ready} />;
}
