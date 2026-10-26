export interface KnowledgeStatement {
  statement_id: string;
  domain: string;
  kind: string;
  subject: string | null;
  content: Readonly<Record<string, unknown>>;
  conditions: readonly string[];
  exceptions: readonly string[];
  effective_wording: string | null;
  interpretation_status: "unreviewed";
  evidence: readonly { page_number: number; url: string | null }[];
}
export interface KnowledgeDocument {
  source_sha256: string;
  title: string;
  publisher: string | null;
  stated_edition?: string | null;
  publication_date_wording?: string | null;
  collection: string;
  source_url: string | null;
  roles: readonly string[];
  statement_count: number;
  interpretation_status: "unreviewed";
  statements: readonly KnowledgeStatement[];
  references?: readonly { id: string; state: string; asset_sha256: string; source_page?: number }[];
}
export interface KnowledgeCatalog {
  schema_version: 1;
  documents: readonly KnowledgeDocument[];
}
export const domainLabels: Readonly<Record<string, string>> = {
  credential_design_security: "Design & security",
  inspection_procedure: "Inspection procedures",
  acceptance_policy: "Acceptance policies",
  issuance_administration: "Issuance guidance",
  technical_standard: "Technical standards",
};
const fieldLabels: Readonly<Record<string, string>> = {
  name: "Feature", presence: "Presence", security_family: "Security family",
  inspection_level: "Inspection level", modalities: "Inspection modality",
  source_location: "Source-stated location", action: "Action",
  expected_observation: "Expected observation", equipment: "Equipment",
  context: "Context", credential_categories: "Credential categories",
  outcome: "Source-stated outcome", conditions: "Source conditions", exceptions: "Source exceptions",
  procedure: "Procedure", required_evidence: "Required evidence", document_stage: "Document stage",
  requirement: "Requirement", authority_reference: "Authority reference",
};
export function readableLabel(value: string): string {
  return domainLabels[value] ?? value.replaceAll("_", " ");
}
function fieldValue(value: unknown): string {
  if (typeof value === "string") return readableLabel(value);
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(fieldValue).filter(Boolean).join(" · ");
  if (value && typeof value === "object") {
    return Object.entries(value).map(([key, item]) => `${readableLabel(key)}: ${fieldValue(item)}`).join("; ");
  }
  return "";
}
export function statementFields(statement: KnowledgeStatement): { label: string; value: string }[] {
  return Object.entries(statement.content).flatMap(([key, value]) => {
    const label = fieldLabels[key];
    const text = label ? fieldValue(value) : "";
    return text ? [{ label, value: text }] : [];
  });
}
export function filterKnowledge(
  documents: readonly KnowledgeDocument[], query: string, domain: string,
): KnowledgeDocument[] {
  const search = query.trim().toLocaleLowerCase("en-US");
  return documents.flatMap((document) => {
    const documentMatch = [document.title, document.publisher, document.collection, ...document.roles]
      .filter(Boolean).join(" ").toLocaleLowerCase("en-US").includes(search);
    const statements = document.statements.filter((statement) => {
      if (domain !== "all" && statement.domain !== domain) return false;
      if (documentMatch) return true;
      return [statement.subject, statement.effective_wording, readableLabel(statement.domain),
        ...statementFields(statement).map((field) => field.value),
        ...statement.conditions, ...statement.exceptions,
      ].filter(Boolean).join(" ").toLocaleLowerCase("en-US").includes(search);
    });
    return statements.length ? [{ ...document, statements }] : [];
  });
}
export function sourcePageUrl(value: string | null, page?: number): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    if (page !== undefined) {
      if (!Number.isSafeInteger(page) || page < 1) return null;
      url.hash = `page=${page}`;
    }
    return url.href;
  } catch {
    return null;
  }
}


export function knowledgeForSource(
  documents: readonly KnowledgeDocument[], sourceSha256: string,
): KnowledgeDocument[] {
  return documents.filter((document) => document.source_sha256 === sourceSha256);
}
export function referenceContextUrl(document: KnowledgeDocument): string | null {
  const reference = document.references?.[0];
  if (!reference || !/^[A-Z]{2}$|^US_FED$/.test(reference.state)
    || !/^[a-zA-Z0-9_-]{1,150}$/.test(reference.id)
    || !/^[a-f0-9]{64}$/.test(document.source_sha256)) return null;
  const collection = reference.state === "US_FED" ? "federal" : reference.state.toLowerCase();
  return `/catalog/${collection}?source=${document.source_sha256}&reference=${reference.id}`;
}
export function requestedReferenceIndex(
  items: readonly { id: string; source_sha256: string }[], search: string,
): number | null {
  const params = new URLSearchParams(search);
  const source = params.get("source");
  const reference = params.get("reference");
  if (!source || !/^[a-f0-9]{64}$/.test(source)) return null;
  const index = items.findIndex((item) => item.source_sha256 === source
    && (!reference || item.id === reference));
  return index < 0 ? null : index;
}


export function statementsByImagePage(
  statements: readonly KnowledgeStatement[], page: number | undefined,
): { samePage: KnowledgeStatement[]; broader: KnowledgeStatement[] } {
  const knownPage = page !== undefined && Number.isSafeInteger(page) && page > 0;
  return {
    samePage: knownPage ? statements.filter((statement) => statement.evidence.some((item) => item.page_number === page)) : [],
    broader: statements.filter((statement) => !knownPage || !statement.evidence.some((item) => item.page_number === page)),
  };
}
