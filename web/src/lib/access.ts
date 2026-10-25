import { useEffect, useRef, useState, type SubmitEvent } from "react";
import {
  applicationPayload,
  parsePolicy,
  sendApplication,
  submissionError,
  sendDomainVerification,
  domainVerificationError,
  type AccessPolicy,
  type AccessResult,
} from "./access-model";
export function useAccessRequest() {
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AccessResult | null>(null);
  const [registrationType, setRegistrationType] =
    useState("state_registration");
  const [policy, setPolicy] = useState<AccessPolicy | null>(null);
  const verifying = useRef(false);
  const [verificationBusy, setVerificationBusy] = useState(false);
  const [verificationError, setVerificationError] = useState("");
  const [domainVerified, setDomainVerified] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/v1/policy", { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Policy unavailable");
        return response.json();
      })
      .then((value) => setPolicy(parsePolicy(value)))
      .catch((error) => {
        if (error.name !== "AbortError")
          setError(
            "The current access policy could not load. Please refresh before submitting.",
          );
      });
    return () => controller.abort();
  }, []);
  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || result) return;
    if (!policy) {
      setError("The current access policy must load before submitting.");
      return;
    }
    submitting.current = true;
    setError("");
    setBusy(true);
    try {
      const payload = applicationPayload(
        new FormData(event.currentTarget),
        registrationType,
        policy,
      );
      setResult(await sendApplication(payload));
    } catch (error) {
      setError(submissionError(error));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  async function verifyDomain() {
    if (!result || verifying.current || domainVerified) return;
    verifying.current = true;
    setVerificationBusy(true);
    setVerificationError("");
    try {
      await sendDomainVerification(result);
      setDomainVerified(true);
    } catch (error) {
      setVerificationError(domainVerificationError(error));
    } finally {
      verifying.current = false;
      setVerificationBusy(false);
    }
  }
  return {
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
  };
}
