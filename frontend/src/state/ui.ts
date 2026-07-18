import { create } from "zustand";

export type PageId = "graph" | "story" | "timeline" | "characters" | "entries" | "fragments";

interface UiState {
  page: PageId;
  selectedCharacterId: string | null;
  selectedGraphCharacterId: string | null;
  selectedPlotId: string | null;
  selectedEntryId: string | null;
  graphViewport: { x: number; y: number; scale: number };
  timelineFocusId: string | null;
  filters: Record<string, string[]>;
  navigate: (page: PageId) => void;
  selectCharacter: (id: string | null) => void;
  selectGraphCharacter: (id: string | null) => void;
  selectPlot: (id: string | null) => void;
  selectEntry: (id: string | null) => void;
  setGraphViewport: (viewport: UiState["graphViewport"]) => void;
  setTimelineFocus: (id: string | null) => void;
  setFilter: (key: string, values: string[]) => void;
}

const hashPage = window.location.hash.replace(/^#\/?/, "").split("/")[0] as PageId;
const initialPage: PageId = ["graph", "story", "timeline", "characters", "entries", "fragments"].includes(hashPage)
  ? hashPage
  : "graph";

export const useUiStore = create<UiState>((set) => ({
  page: initialPage,
  selectedCharacterId: null,
  selectedGraphCharacterId: null,
  selectedPlotId: null,
  selectedEntryId: null,
  graphViewport: { x: 0, y: 0, scale: 1 },
  timelineFocusId: null,
  filters: {},
  navigate: (page) => {
    window.history.pushState({}, "", `${window.location.pathname}${window.location.search}#/${page}`);
    set({ page });
  },
  selectCharacter: (selectedCharacterId) => set({ selectedCharacterId }),
  selectGraphCharacter: (selectedGraphCharacterId) => set({ selectedGraphCharacterId }),
  selectPlot: (selectedPlotId) => set({ selectedPlotId }),
  selectEntry: (selectedEntryId) => set({ selectedEntryId }),
  setGraphViewport: (graphViewport) => set({ graphViewport }),
  setTimelineFocus: (timelineFocusId) => set({ timelineFocusId }),
  setFilter: (key, values) => set((state) => ({ filters: { ...state.filters, [key]: values } })),
}));

window.addEventListener("popstate", () => {
  const page = window.location.hash.replace(/^#\/?/, "").split("/")[0] as PageId;
  if (["graph", "story", "timeline", "characters", "entries", "fragments"].includes(page)) {
    useUiStore.setState({ page });
  }
});
