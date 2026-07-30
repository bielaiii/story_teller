import { create } from "zustand";

export type PageId = "graph" | "story" | "timeline" | "characters" | "entries" | "fragments" | "management";

interface UiState {
  page: PageId;
  selectedCharacterId: string | null;
  selectedGraphCharacterId: string | null;
  selectedPlotId: string | null;
  storyReturnCharacterId: string | null;
  selectedEntryId: string | null;
  selectedFragmentId: string | null;
  graphViewport: { x: number; y: number; scale: number };
  timelineFocusId: string | null;
  filters: Record<string, string[]>;
  notice: { id: number; message: string; tone: "progress" | "success" | "error" } | null;
  navigate: (page: PageId) => void;
  selectCharacter: (id: string | null) => void;
  selectGraphCharacter: (id: string | null) => void;
  selectPlot: (id: string | null) => void;
  openPlotFromCharacter: (plotId: string, characterId: string) => void;
  clearStoryReturn: () => void;
  selectEntry: (id: string | null) => void;
  selectFragment: (id: string | null) => void;
  setGraphViewport: (viewport: UiState["graphViewport"]) => void;
  setTimelineFocus: (id: string | null) => void;
  setFilter: (key: string, values: string[]) => void;
  showNotice: (message: string, tone: "progress" | "success" | "error") => void;
  dismissNotice: (id: number) => void;
}

const hashParts = window.location.hash.replace(/^#\/?/, "").split("/");
const hashPage = hashParts[0] as PageId;
const initialPage: PageId = ["graph", "story", "timeline", "characters", "entries", "fragments", "management"].includes(hashPage)
  ? hashPage
  : "graph";
let initialPlotId: string | null = null;
if (initialPage === "story" && hashParts[1]) {
  try {
    initialPlotId = decodeURIComponent(hashParts.slice(1).join("/"));
  } catch {
    initialPlotId = null;
  }
}
let noticeSequence = 0;

export const useUiStore = create<UiState>((set) => ({
  page: initialPage,
  selectedCharacterId: null,
  selectedGraphCharacterId: null,
  selectedPlotId: initialPlotId,
  storyReturnCharacterId: null,
  selectedEntryId: null,
  selectedFragmentId: null,
  graphViewport: { x: 0, y: 0, scale: 1 },
  timelineFocusId: null,
  filters: {},
  notice: null,
  navigate: (page) => {
    window.history.pushState({}, "", `${window.location.pathname}${window.location.search}#/${page}`);
    set((state) => ({ page, storyReturnCharacterId: page === "story" ? state.storyReturnCharacterId : null }));
  },
  selectCharacter: (selectedCharacterId) => set({ selectedCharacterId }),
  selectGraphCharacter: (selectedGraphCharacterId) => set({ selectedGraphCharacterId }),
  selectPlot: (selectedPlotId) => {
    const currentPage = window.location.hash.replace(/^#\/?/, "").split("/")[0];
    if (currentPage === "story") {
      const nextHash = selectedPlotId ? `#/story/${encodeURIComponent(selectedPlotId)}` : "#/story";
      window.history.replaceState({}, "", `${window.location.pathname}${window.location.search}${nextHash}`);
    }
    set({ selectedPlotId });
  },
  openPlotFromCharacter: (selectedPlotId, storyReturnCharacterId) => set({
    selectedPlotId,
    storyReturnCharacterId,
  }),
  clearStoryReturn: () => set({ storyReturnCharacterId: null }),
  selectEntry: (selectedEntryId) => set({ selectedEntryId }),
  selectFragment: (selectedFragmentId) => set({ selectedFragmentId }),
  setGraphViewport: (graphViewport) => set({ graphViewport }),
  setTimelineFocus: (timelineFocusId) => set({ timelineFocusId }),
  setFilter: (key, values) => set((state) => ({ filters: { ...state.filters, [key]: values } })),
  showNotice: (message, tone) => {
    noticeSequence += 1;
    set({ notice: { id: noticeSequence, message, tone } });
  },
  dismissNotice: (id) => set((state) => state.notice?.id === id ? { notice: null } : state),
}));

window.addEventListener("popstate", () => {
  const page = window.location.hash.replace(/^#\/?/, "").split("/")[0] as PageId;
  if (["graph", "story", "timeline", "characters", "entries", "fragments", "management"].includes(page)) {
    useUiStore.setState({ page });
  }
});
