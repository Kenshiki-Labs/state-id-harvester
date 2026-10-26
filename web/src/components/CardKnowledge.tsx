import { KnowledgeStatementView } from "./KnowledgeLibrary";
import { sourcePageUrl, statementsByImagePage, type KnowledgeDocument } from "../lib/knowledge-model";

export default function CardKnowledge({ documents, reference }: Readonly<{ documents: readonly KnowledgeDocument[]; reference: { id: string; state: string } }>) {
  return <aside className="viewer-knowledge" aria-label="Guidance from this image’s source publication">
    <div className="viewer-knowledge-intro"><p className="eyebrow">CARD + SOURCE GUIDANCE</p><h3>Read this card in context.</h3><p>Guidance from the same PDF. Check each statement’s subject and period; applicability to this image remains unreviewed.</p></div>
    {documents.map((document) => {
      const url = sourcePageUrl(document.source_url);
      const page = document.references?.find((item) => item.id === reference.id && item.state === reference.state)?.source_page;
      const grouped = statementsByImagePage(document.statements, page);
      return <section key={document.source_sha256} className="viewer-knowledge-source">
        <h4>{document.title}</h4>
        {(document.stated_edition || document.publication_date_wording) && <p className="knowledge-period">{[document.stated_edition, document.publication_date_wording].filter(Boolean).join(" · ")}</p>}
        {url && <a className="viewer-source-link" href={url} target="_blank" rel="noopener noreferrer">Open source PDF ↗</a>}
        <p className="viewer-knowledge-status">{document.statements.length} statements · Unreviewed interpretations</p>
        {page !== undefined && <p className="viewer-image-page">Image extracted from PDF page {page}</p>}
        {grouped.samePage.length > 0 && <><h5 className="viewer-page-heading">Guidance citing this page</h5><ol className="knowledge-statements">{grouped.samePage.map((statement) => <KnowledgeStatementView key={statement.statement_id} statement={statement}/>)}</ol></>}
        {page !== undefined && grouped.samePage.length === 0 && <p className="knowledge-period">No extracted statements cite this image’s page. Explore the broader publication below.</p>}
        {grouped.broader.length > 0 && <details className="viewer-broader-guidance" open={page === undefined}><summary>Broader publication context · {grouped.broader.length} statements</summary><ol className="knowledge-statements">{grouped.broader.map((statement) => <KnowledgeStatementView key={statement.statement_id} statement={statement}/>)}</ol></details>}
      </section>;
    })}
  </aside>;
}
