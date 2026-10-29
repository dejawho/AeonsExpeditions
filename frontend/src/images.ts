// Local copies of the wiki card images, served by the backend under /images/.
import { useEffect, useState } from "react";

export type ImageInfo = [slug: string, kind: string, width: number, height: number];
export type ImageIndex = Record<string, ImageInfo>;

let index: Promise<ImageIndex> | null = null;

export function loadImages(): Promise<ImageIndex> {
  index ??= fetch("/api/images")
    .then((r) => (r.ok ? r.json() : {}))
    .catch(() => ({}));
  return index;
}

export function useImages(): ImageIndex {
  const [images, setImages] = useState<ImageIndex>({});
  useEffect(() => {
    let live = true;
    loadImages().then((i) => live && setImages(i));
    return () => {
      live = false;
    };
  }, []);
  return images;
}

export const imageUrl = (slug: string, size: "thumb" | "full") => `/images/${size}/${slug}.webp`;
