import {
  accessButtonLabel,
  domainVerificationLabel,
  type AccessResult,
} from "../lib/access-model";
import { useAccessRequest } from "../lib/access";
interface AccessReceiptProps {
  result: AccessResult;
  verificationBusy: boolean;
  verificationError: string;
  domainVerified: boolean;
  verifyDomain: () => void;
}
export function AccessReceipt({
  result,
  verificationBusy,
  verificationError,
  domainVerified,
  verifyDomain,
}: AccessReceiptProps) {
  return (
    <div className="access-result">
      <output className="sr-only">
        Request received. Pending organization and authority review.
      </output>
      <span className="result-icon" aria-hidden="true">
        ✓
      </span>
      <p className="eyebrow">REQUEST RECEIVED</p>
      <h3>Pending review.</h3>
      <p>
        Your request is recorded. Domain control and organization eligibility
        are reviewed separately; submitting this form does not grant access.
      </p>
      <dl>
        <dt>Request ID</dt>
        <dd>
          <code>{result.request_id}</code>
        </dd>
      </dl>
      <h4>Prove domain control</h4>
      <p>
        Add this TXT record at your DNS provider. Keep your claim token private.
      </p>
      <dl className="dns-record">
        <dt>Type</dt>
        <dd>TXT</dd>
        <dt>Name</dt>
        <dd>
          <code>{result.domain_challenge.name}</code>
        </dd>
        <dt>Value</dt>
        <dd>
          <code>{result.domain_challenge.value}</code>
        </dd>
      </dl>
      <button
        className="button button-primary"
        type="button"
        onClick={verifyDomain}
        disabled={verificationBusy || domainVerified}
      >
        {domainVerificationLabel(verificationBusy, domainVerified)}
      </button>
      <p className="form-note">
        <output aria-live="polite">
          {domainVerified &&
            "Domain control verified. Organization and authority review are separate; this step does not grant access."}
        </output>
      </p>
      {verificationError && (
        <p className="form-error" role="alert">
          {verificationError}
        </p>
      )}
      <details className="receipt">
        <summary>Save your claim token and attestation receipt</summary>
        <p>Claim token</p>
        <code>{result.claim_token}</code>
        <p>Attestation receipt</p>
        <pre>{JSON.stringify(result.attestation_receipt, null, 2)}</pre>
      </details>
      <p className="form-note">
        Save these details. The token belongs to this request and does not
        authorize access.
      </p>
    </div>
  );
}
export default function AccessForm() {
  const {
    busy,
    error,
    result,
    registrationType,
    setRegistrationType,
    policy,
    submit,
    verifyDomain,
    verificationBusy,
    verificationError,
    domainVerified,
  } = useAccessRequest();
  if (result)
    return (
      <AccessReceipt
        result={result}
        verificationBusy={verificationBusy}
        verificationError={verificationError}
        domainVerified={domainVerified}
        verifyDomain={verifyDomain}
      />
    );
  return (
    <form className="access-form" onSubmit={submit}>
      <div className="form-grid">
        <label>
          Full name{" "}
          <input
            name="name"
            autoComplete="name"
            required
            maxLength={150}
            minLength={2}
            placeholder="Your name"
          />
        </label>
        <label>
          Work email{" "}
          <input
            type="email"
            name="email"
            autoComplete="email"
            required
            maxLength={254}
            placeholder="you@organization.com"
          />
        </label>
        <label>
          Organization{" "}
          <input
            name="organization"
            autoComplete="organization"
            minLength={2}
            required
            maxLength={200}
            placeholder="Legal organization name"
          />
        </label>
        <label>
          Organization domain{" "}
          <input
            name="domain"
            required
            maxLength={253}
            placeholder="organization.com"
            autoCapitalize="none"
            spellCheck={false}
          />
        </label>
        <label>
          Organization registration{" "}
          <select
            name="registration_type"
            value={registrationType}
            onChange={(event) => setRegistrationType(event.target.value)}
          >
            <option value="state_registration">
              State / business registration
            </option>
            <option value="UEI">Unique Entity ID (UEI)</option>
            <option value="CAGE">CAGE code</option>
            <option value="government">Government agency</option>
            <option value="education">Educational institution</option>
          </select>
        </label>
        <label>
          {["government", "education"].includes(registrationType)
            ? "Public entity / charter reference"
            : "Registration ID"}{" "}
          <input
            name="registration_id"
            maxLength={150}
            required
            minLength={2}
            placeholder="Registration identifier"
          />
        </label>
        <label className="registration-wide">
          Registration jurisdiction{" "}
          <input
            name="registration_jurisdiction"
            required
            minLength={2}
            maxLength={150}
            placeholder="e.g. Delaware, United States / SAM.gov"
          />
        </label>
      </div>
      <label>
        Intended use{" "}
        <textarea
          name="use_case"
          required
          minLength={30}
          maxLength={4000}
          rows={3}
          placeholder="Describe your verification, research, or compliance use case."
        />
      </label>
      <label className="checkbox-field">
        <input name="attestation" type="checkbox" required />
        <span>
          I am authorized to represent this organization. I attest to legitimate
          use, no document replication, and the full{" "}
          <a href="/acceptable-use">access policy below</a>, and acknowledge the{" "}
          <a href="/privacy">privacy notice</a>.
        </span>
      </label>
      {policy && (
        <details className="receipt">
          <summary>Read the full access attestation · {policy.version}</summary>
          <p>{policy.text}</p>
        </details>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <button
        className="button button-primary form-submit"
        type="submit"
        disabled={busy || !policy}
      >
        {accessButtonLabel(busy, policy, error)}
        <span aria-hidden="true">↗</span>
      </button>
      <p className="form-note">
        You’ll receive a request receipt and a DNS challenge. Every request
        requires review.
      </p>
    </form>
  );
}
