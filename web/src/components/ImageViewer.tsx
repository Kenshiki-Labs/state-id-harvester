import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { specimenUrl, type PublicSpecimen } from "../lib/specimens";

function ViewerImage({ item, name, number }: Readonly<{ item: PublicSpecimen; name: string; number: number }>) {
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  if (failed) return <div className="viewer-image-error" role="alert"><p>This reference image could not be loaded.</p><button type="button" onClick={() => { setFailed(false); setLoading(true); setAttempt((value) => value + 1); }}>Try again</button></div>;
  return <>
    {loading && <p className="viewer-loading" role="status">Loading image…</p>}
    <img key={attempt} src={specimenUrl(item)} alt={`${name} reference ${number}; research specimen, review pending`} decoding="async" onLoad={() => setLoading(false)} onError={() => { setLoading(false); setFailed(true); }} />
  </>;
}
function keepDialogFocus(event: KeyboardEvent<HTMLDialogElement>) {
  if (event.key !== "Tab") return;
  const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled), a[href]"))
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
export default function ImageViewer({ items, index, name, onNavigate, onClose }: Readonly<{ items: PublicSpecimen[]; index: number; name: string; onNavigate: (index: number) => void; onClose: () => void }>) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const title = useId();
  const caption = useId();
  const [zoom, setZoom] = useState(0);
  const item = items[index];
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
  function navigate(next: number) {
    if (next < 0 || next >= items.length) return;
    setZoom(0);
    canvasRef.current?.scrollTo(0, 0);
    onNavigate(next);
  }
  function changeZoom(next: number) {
    setZoom(Math.max(0, Math.min(zoomLevels.length - 1, next)));
    canvasRef.current?.scrollTo(0, 0);
  }
  if (!item) return null;
  return <dialog ref={dialogRef} className="image-viewer" aria-labelledby={title} aria-describedby={caption} onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => {
    if (event.target !== event.currentTarget) return;
    const box = event.currentTarget.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onClose();
  }} onKeyDown={(event) => {
    keepDialogFocus(event);
    if (event.key === "ArrowLeft") { event.preventDefault(); navigate(index - 1); }
    if (event.key === "ArrowRight") { event.preventDefault(); navigate(index + 1); }
  }}>
    <header className="viewer-header"><h2 id={title}>{name} <span>Reference {index + 1} of {items.length}</span></h2><button className="viewer-close" type="button" onClick={onClose} aria-label="Close image viewer">Close <span aria-hidden="true">×</span></button></header>
    <div className="viewer-toolbar" aria-label="Image controls">
      <div className="viewer-paging"><button type="button" aria-label="Previous reference" disabled={index === 0} onClick={() => navigate(index - 1)}>← Previous</button><button type="button" aria-label="Next reference" disabled={index === items.length - 1} onClick={() => navigate(index + 1)}>Next →</button></div>
      <div className="viewer-zoom"><button type="button" aria-label="Zoom out" disabled={zoom === 0} onClick={() => changeZoom(zoom - 1)}>−</button><output aria-live="polite">{zoom === 0 ? "Fit" : `${zoomLevels[zoom] * 100}%`}</output><button type="button" aria-label="Zoom in" disabled={zoom === zoomLevels.length - 1} onClick={() => changeZoom(zoom + 1)}>+</button><button type="button" disabled={zoom === 0} onClick={() => changeZoom(0)}>Fit</button></div>
    </div>
    <div ref={canvasRef} className="viewer-canvas" data-zoom={zoomLevels[zoom]}><ViewerImage key={`${item.state}/${item.id}`} item={item} name={name} number={index + 1} /></div>
    <footer className="viewer-footer"><p id={caption}>Research reference · review pending</p><a href={specimenUrl(item)} download={`${item.state}-${item.id}.png`}>Download PNG ↓</a></footer>
  </dialog>;
}
