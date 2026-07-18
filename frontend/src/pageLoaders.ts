import type { ComponentType } from "react";
import type { PageId } from "./state/ui";

export const pageLoaders: Record<PageId, () => Promise<{ default: ComponentType }>> = {
  graph: () => import("./pages/GraphPage"),
  story: () => import("./pages/StoryPage"),
  timeline: () => import("./pages/TimelinePage"),
  characters: () => import("./pages/CharactersPage"),
  entries: () => import("./pages/EntriesPage"),
  fragments: () => import("./pages/FragmentsPage"),
};

export function preloadPage(page: PageId) {
  return pageLoaders[page]();
}
