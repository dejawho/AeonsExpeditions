import { useEffect } from "react";

/** Era name (lore/timeline.json, as the story shows it) -> its painting in public/art/eras/. */
const ERAS: Record<string, string> = {
  "The Dawn of Breach Magic": "dawn",
  "The World That Was": "world_that_was",
  "The Great Calamity": "calamity",
  "The Descent": "descent",
  "Old Gravehold — The Long Siege": "old_gravehold",
  "The Fall": "fall",
  "New Gravehold": "new_gravehold",
  "The Civil War and the Second Fall": "civil_war",
  "The Scattered Age": "after",
};

/** Puts public/art/<name>-2560.webp (-1280 on phones) behind the page instead of the cover painting. */
function useBackdrop(name: string | undefined) {
  useEffect(() => {
    if (!name) return;
    const root = document.documentElement.style;
    root.setProperty("--art-wide", `url("/art/${name}-2560.webp")`);
    root.setProperty("--art-narrow", `url("/art/${name}-1280.webp")`);
    return () => {
      root.removeProperty("--art-wide");
      root.removeProperty("--art-narrow");
    };
  }, [name]);
}

/** The painting of the expedition's era (the cover painting when the era has none). */
export const useEraBackdrop = (era: string | undefined) => useBackdrop(era && ERAS[era] ? `eras/${ERAS[era]}` : undefined);

/** The planning table behind the new-expedition form. */
export const usePlanningBackdrop = () => useBackdrop("scenes/planning");

/** A painted strip at the top of the battle card: the clash, its outcome, the way home. */
export function SceneBanner({ scene }: { scene: "battle" | "victory" | "defeat" | "ending" }) {
  return (
    <div className={`scene-banner ${scene}`} aria-hidden="true">
      <img
        src={`/art/scenes/${scene}-1280.webp`}
        srcSet={`/art/scenes/${scene}-1280.webp 1280w, /art/scenes/${scene}-2560.webp 2560w`}
        sizes="(max-width: 960px) 100vw, 930px"
        alt=""
        decoding="async"
      />
    </div>
  );
}
