import { useCallback, useEffect, useId, useRef, useState } from "react";
import knowledgeData from "../../public/data/knowledge.json";
import CardKnowledge from "./CardKnowledge";
import { knowledgeForSource, type KnowledgeCatalog, type KnowledgeDocument } from "../lib/knowledge-model";
import { browserImageUrl, normalizationUrl, specimenUrl, type PublicSpecimen } from "../lib/specimens";

function ViewerImage({ url, name, number }: Readonly<{ url: string; name: string; number: number }>) {
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  if (failed) return <div className="viewer-image-error" role="alert"><p>This reference image could not be loaded.</p><button type="button" onClick={() => { setFailed(false); setLoading(true); setAttempt((value) => value + 1); }}>Try again</button></div>;
  return <>
    {loading && <output className="viewer-loading">Loading image…</output>}
    <img key={attempt} src={url} alt={`${name} reference ${number}; research specimen, review pending`} decoding="async" onLoad={() => setLoading(false)} onError={() => { setLoading(false); setFailed(true); }} />
  </>;
}
function keepDialogFocus(event: KeyboardEvent, dialog: HTMLDialogElement) {
  if (event.key !== "Tab") return;
  const controls = Array.from(dialog.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], summary"))
    .filter((element) => element.getClientRects().length > 0);
  const first = controls[0], last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}
const zoomLevels = [0, 1, 1.5, 2, 3, 4];
const publishedKnowledge = (knowledgeData as KnowledgeCatalog).documents;
export default function ImageViewer({ items, index, name, onNavigate, onClose, knowledge = publishedKnowledge }: Readonly<{ items: PublicSpecimen[]; index: number; name: string; onNavigate: (index: number) => void; onClose: () => void; knowledge?: readonly KnowledgeDocument[] }>) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const title = useId();
  const caption = useId();
  const [zoom, setZoom] = useState(0);
  const item = items[index];
  const guidance = item ? knowledgeForSource(knowledge, item.source_sha256) : [];
  const identity = item ? `${item.state}/${item.id}` : "";
  const [originalSelection, setOriginalSelection] = useState<string | null>(null);
  const normalized = Boolean(item?.normalization) && originalSelection !== identity;
  let fullImageUrl = "";
  if (item) fullImageUrl = normalized ? normalizationUrl(item) : specimenUrl(item);
  const imageUrl = item && zoom === 0 ? browserImageUrl(item, "display", normalized) : fullImageUrl;
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const opener = document.activeElement;
    const originalOverflow = document.documentElement.style.overflow;
    dialog.showModal();
    document.documentElement.style.overflow = "hidden";
    return () => {
      dialog.close();
      document.documentElement.style.overflow = originalOverflow;
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);
  const navigate = useCallback((next: number) => {
    if (next < 0 || next >= items.length) return;
    setZoom(0);
    setOriginalSelection(null);
    canvasRef.current?.scrollTo(0, 0);
    onNavigate(next);
  }, [items.length, onNavigate]);
  function changeZoom(next: number) {
    setZoom(Math.max(0, Math.min(zoomLevels.length - 1, next)));
    canvasRef.current?.scrollTo(0, 0);
  }
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    function cancel(event: Event) {
      event.preventDefault();
      onClose();
    }
    function click(event: MouseEvent) {
      if (!dialog || event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onClose();
    }
    function keyDown(event: KeyboardEvent) {
      if (!dialog) return;
      keepDialogFocus(event, dialog);
      if (event.key === "ArrowLeft") { event.preventDefault(); navigate(index - 1); }
      if (event.key === "ArrowRight") { event.preventDefault(); navigate(index + 1); }
    }
    dialog.addEventListener("cancel", cancel);
    dialog.addEventListener("click", click);
    dialog.addEventListener("keydown", keyDown);
    return () => {
      dialog.removeEventListener("cancel", cancel);
      dialog.removeEventListener("click", click);
      dialog.removeEventListener("keydown", keyDown);
    };
  }, [index, navigate, onClose]);
  if (!item) return null;
  return <dialog ref={dialogRef} className="image-viewer" aria-labelledby={title} aria-describedby={caption}>
    <header className="viewer-header"><h2 id={title}>{name} <span>Reference {index + 1} of {items.length}</span></h2><button className="viewer-close" type="button" onClick={onClose} aria-label="Close image viewer">Close <span aria-hidden="true">×</span></button></header>
    <div className="viewer-toolbar" aria-label="Image controls">
      <div className="viewer-paging"><button type="button" aria-label="Previous reference" disabled={index === 0} onClick={() => navigate(index - 1)}>← Previous</button><button type="button" aria-label="Next reference" disabled={index === items.length - 1} onClick={() => navigate(index + 1)}>Next →</button></div>
      {item.normalization && <fieldset className="viewer-variants" aria-label="Image version"><button type="button" aria-pressed={normalized} onClick={() => { setOriginalSelection(null); changeZoom(0); }}>ID-1</button><button type="button" aria-pressed={!normalized} onClick={() => { setOriginalSelection(identity); changeZoom(0); }}>Original</button></fieldset>}
      <div className="viewer-zoom"><button type="button" aria-label="Zoom out" disabled={zoom === 0} onClick={() => changeZoom(zoom - 1)}>−</button><output aria-live="polite">{zoom === 0 ? "Fit" : `${zoomLevels[zoom] * 100}%`}</output><button type="button" aria-label="Zoom in" disabled={zoom === zoomLevels.length - 1} onClick={() => changeZoom(zoom + 1)}>+</button><button type="button" disabled={zoom === 0} onClick={() => changeZoom(0)}>Fit</button></div>
    </div>
    <div className={`viewer-body${guidance.length ? " viewer-body-paired" : ""}`}>
      <div ref={canvasRef} className="viewer-canvas" data-zoom={zoomLevels[zoom]}><ViewerImage key={imageUrl} url={imageUrl} name={name} number={index + 1} /></div>
      {guidance.length > 0 && <CardKnowledge documents={guidance} reference={item} />}
    </div>
    <footer className="viewer-footer"><p id={caption}>{normalized ? "ID-1 normalized" : "Original reference"} · review pending</p><a href={fullImageUrl} download={`${item.state}-${item.id}${normalized ? "-id1" : ""}.png`}>Download PNG ↓</a></footer>
  </dialog>;
}
