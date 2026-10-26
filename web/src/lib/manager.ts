import { useState, type SubmitEvent } from "react";
import { AccessSubmissionError } from "./access-model";
import {
  claimKey,
  requestStatus,
  savedClaim,
  verifySavedDomain,
  type ClaimedKey,
  type RequestStatus,
  type SavedClaim,
} from "./manager-model";

export function useRequestManager() {
  const [claim, setClaim] = useState<SavedClaim | null>(null);
  const [status, setStatus] = useState<RequestStatus | null>(null);
  const [key, setKey] = useState<ClaimedKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function run(
    current: SavedClaim,
    action: "status" | "verify" | "claim",
  ) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (action === "claim") {
        setKey(await claimKey(current));
        setNotice("Key issued. Save it now; it cannot be displayed again.");
      } else {
        if (action === "verify") {
          await verifySavedDomain(current);
          setNotice(
            "Domain control verified. Organization and applicant authority review remain separate.",
          );
        }
        setStatus(await requestStatus(current));
      }
      setClaim(current);
    } catch (failure) {
      const fallback =
        action === "claim"
          ? "A complete key receipt was not received. Check status before retrying; a claimed key cannot be displayed again."
          : "The access service is unavailable. Please try again.";
      setError(
        failure instanceof AccessSubmissionError ? failure.message : fallback,
      );
    } finally {
      setBusy(false);
    }
  }
  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const current = savedClaim(
        String(data.get("request_id") ?? ""),
        String(data.get("claim_token") ?? ""),
      );
      void run(current, "status");
    } catch (failure) {
      setError(
        failure instanceof AccessSubmissionError
          ? failure.message
          : "Check your saved receipt.",
      );
    }
  }
  function act(action: "status" | "verify" | "claim") {
    if (claim && !busy) void run(claim, action);
  }
  function clear() {
    setClaim(null);
    setStatus(null);
    setKey(null);
    setError("");
    setNotice("");
  }
  return { claim, status, key, busy, error, notice, submit, act, clear };
}
