import { useState } from "react";
import { catalogApiUrl } from "../core/edge-catalog";
import {
  domainLabels, filterKnowledge, readableLabel, referenceContextUrl, sourcePageUrl, statementFields,
  type KnowledgeDocument, type KnowledgeStatement,
} from "../lib/knowledge-model";

export function KnowledgeStatementView({ statement }: Readonly<{ statement: KnowledgeStatement }>) {
  const pages = [...new Map(statement.evidence.map((item) => [
    `${item.page_number}:${item.url}`, item,
  ])).values()];
  return <li className="knowledge-statement">
    <div className="knowledge-statement-heading"><h3>{readableLabel(statement.domain)}</h3><span>{statement.kind}</span></div>
    {statement.subject && <p className="knowledge-subject">{statement.subject}</p>}
    <dl className="knowledge-fields">{statementFields(statement).map((field) => <div key={field.label}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>
    {!!statement.conditions.length && <div className="knowledge-qualifier"><h4>Applies when</h4><ul>{statement.conditions.map((condition) => <li key={condition}>{condition}</li>)}</ul></div>}
    {!!statement.exceptions.length && <div className="knowledge-qualifier"><h4>Exceptions</h4><ul>{statement.exceptions.map((exception) => <li key={exception}>{exception}</li>)}</ul></div>}
    {statement.effective_wording && <p className="knowledge-period"><strong>Source period:</strong> {statement.effective_wording}</p>}
    <div className="knowledge-evidence"><span>Source evidence</span>{pages.map((item) => {
      const url = sourcePageUrl(item.url, item.page_number);
      return url ? <a key={`${item.page_number}:${item.url}`} href={url} target="_blank" rel="noopener noreferrer">PDF page {item.page_number} <span aria-hidden="true">↗</span></a> : <span key={`${item.page_number}:${item.url}`}>Page {item.page_number} · source link unavailable</span>;
    })}<small>Unreviewed interpretation</small></div>
  </li>;
}
export default function KnowledgeLibrary({ documents }: Readonly<{ documents: readonly KnowledgeDocument[] }>) {
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("all");
  const visible = filterKnowledge(documents, query, domain);
  const statementCount = visible.reduce((sum, document) => sum + document.statements.length, 0);
  const total = documents.reduce((sum, document) => sum + document.statements.length, 0);
  const domains = [...new Set(documents.flatMap((document) => document.statements.map((statement) => statement.domain)))].sort((a, b) => a.localeCompare(b));
  return <div className="knowledge-library">
    <div className="knowledge-controls">
      <label>Search the knowledge library<input type="search" value={query} placeholder="Try ultraviolet, temporary, or a state" onChange={(event) => setQuery(event.target.value)} /></label>
      <label>Knowledge domain<select value={domain} onChange={(event) => setDomain(event.target.value)}><option value="all">All domains</option>{domains.map((value) => <option key={value} value={value}>{domainLabels[value] ?? readableLabel(value)}</option>)}</select></label>
    </div>
    <div className="knowledge-results"><output aria-live="polite">{visible.length} of {documents.length} publications · {statementCount} of {total} statements</output>{(query || domain !== "all") && <button type="button" onClick={() => { setQuery(""); setDomain("all"); }}>Clear filters</button>}</div>
    <div className="knowledge-documents">{visible.map((document) => {
      const source = sourcePageUrl(document.source_url);
      const context = referenceContextUrl(document);
      const reference = document.references?.[0];
      return <article className="knowledge-document" key={document.source_sha256}>
        <div className="knowledge-document-meta"><span>{document.collection}</span><span>{document.roles.map(readableLabel).join(" · ")}</span><span className="knowledge-review">Unreviewed interpretation</span></div>
        {context && reference && <a className="knowledge-reference-preview" href={context} aria-label={`Inspect reference image with guidance from ${document.title}`}><img src={`${catalogApiUrl(`/v1/specimens/${reference.state}/${reference.id}`)}?view=thumbnail&v=${reference.asset_sha256}`} alt="Reference image extracted from this source publication" loading="lazy" decoding="async"/><span>Inspect card with source guidance <span aria-hidden="true">↗</span></span></a>}
        <h2>{document.title}</h2>
        <div className="knowledge-document-source">{document.publisher && <span>{document.publisher}</span>}{document.stated_edition && <span>Edition: {document.stated_edition}</span>}{document.publication_date_wording && <span>Published: {document.publication_date_wording}</span>}{source && <a href={source} target="_blank" rel="noopener noreferrer">Read source publication <span aria-hidden="true">↗</span></a>}</div>
        <details className="knowledge-document-details"><summary>Explore {document.statements.length} {document.statements.length === 1 ? "statement" : "statements"}<span aria-hidden="true">＋</span></summary><ol className="knowledge-statements">{document.statements.map((statement) => <KnowledgeStatementView key={statement.statement_id} statement={statement} />)}</ol></details>
      </article>;
    })}</div>
    {!visible.length && <div className="knowledge-empty"><h2>No matching statements.</h2><p>Try another term or choose all domains.</p></div>}
  </div>;
}
