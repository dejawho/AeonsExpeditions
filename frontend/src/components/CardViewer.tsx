import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { imageUrl, useImages } from "../images";

const short = (title: string) => title.replace(/ \(.*\)$/, "");

const ViewerContext = createContext<(title: string) => void>(() => {});

/** Wrap the app once: any CardChip can then open the full-size image. */
export function CardViewerProvider({ children }: { children: ReactNode }) {
  const [title, setTitle] = useState<string | null>(null);
  const images = useImages();
  const close = useCallback(() => setTitle(null), []);

  useEffect(() => {
    if (!title) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [title, close]);

  const info = title ? images[title] : undefined;
  return (
    <ViewerContext.Provider value={setTitle}>
      {children}
      {title && (
        <div className="viewer" role="dialog" aria-modal="true" aria-label={title} onClick={close}>
          <figure onClick={(e) => e.stopPropagation()}>
            {info ? (
              <img
                src={imageUrl(info[0], "full")}
                alt={title}
                width={info[2] > info[3] ? 720 : Math.round((720 * info[2]) / info[3])}
                className={info[2] > info[3] ? "wide" : "tall"}
              />
            ) : (
              <p className="muted">No image for this card.</p>
            )}
            <figcaption>
              <strong>{short(title)}</strong>
              <span className="muted small"> · image: Aeon's End Wiki</span>
            </figcaption>
            <button className="btn small viewer-close" onClick={close} aria-label="Close">
              ✕
            </button>
          </figure>
        </div>
      )}
    </ViewerContext.Provider>
  );
}

/** A card name with its thumbnail; tap to see the card. */
export function CardChip({ title, label }: { title: string; label?: string }) {
  const open = useContext(ViewerContext);
  const images = useImages();
  const info = images[title];
  return (
    <button type="button" className="chip card-chip" onClick={() => open(title)} title={`Show ${short(title)}`}>
      {info && <img src={imageUrl(info[0], "thumb")} alt="" loading="lazy" className={info[2] > info[3] ? "wide" : ""} />}
      <span>{label ?? title}</span>
    </button>
  );
}

/** The full image inline (e.g. the nemesis mat once it has been faced). */
export function CardImage({ title }: { title: string }) {
  const open = useContext(ViewerContext);
  const info = useImages()[title];
  if (!info) return null;
  return (
    <button type="button" className="card-image" onClick={() => open(title)} aria-label={`Show ${short(title)}`}>
      <img src={imageUrl(info[0], "full")} alt={short(title)} loading="lazy" />
    </button>
  );
}
