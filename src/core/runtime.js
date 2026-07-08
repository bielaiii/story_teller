const state = {
  selected: "",
  selectedCharacter: "",
  selectedPlotId: null,
  hasSelection: false,
  chapter: "all",
  plotStatus: "all",
  plotTags: [],
  plotShelf: "all",
  fragmentTags: [],
  plotPage: 1,
  fragmentPage: 1,
  highlightPlotId: null,
  view: "graph",
  dragging: null,
  panning: null,
  suppressClickId: "",
  suppressClickUntil: 0,
  graphScale: 1,
  graphPanX: 0,
  graphPanY: 0,
  search: "",
  group: "all",
  relationType: "all",
  characterSearch: "",
  characterShelf: "main",
  characterAppearanceChapter: "all",
  placeSearch: "",
  entryType: "all",
  entryTags: [],
  selectedPlace: "",
  globalSearch: "",
  highlightedReferenceType: "",
  highlightedReferenceId: "",
  detailReturnContext: null,
  plotReadingPositions: {},
  timelineReversed: false,
  width: 0,
  height: 0,
};

const graphWrap = document.querySelector("#graphWrap");
const graphGpuCanvas = document.querySelector("#graphGpuCanvas");
const graphFallbackCanvas = document.querySelector("#graphFallbackCanvas");
function createGraphRenderer() {
  if (!graphGpuCanvas || !graphFallbackCanvas || !window.GraphRenderer) return null;
  try {
    return new window.GraphRenderer(graphGpuCanvas, graphFallbackCanvas);
  } catch (error) {
    console.info("Graph effects unavailable; character nodes will still render.", error);
    return null;
  }
}
const graphRenderer = createGraphRenderer();
const nodeLayer = document.querySelector("#nodeLayer");
const graphStage = document.querySelector(".graph-stage");
const storyEyebrow = document.querySelector("#storyEyebrow");
const storyTitle = document.querySelector("#storyTitle");
const chapterSwitch = document.querySelector("#chapterSwitch");
const plotStrip = document.querySelector("#plotStrip");
const plotPagination = document.querySelector("#plotPagination");
const statusFilter = document.querySelector("#statusFilter");
const tagFilter = document.querySelector("#tagFilter");
const sideTaskToggle = document.querySelector("#sideTaskToggle");
const sideTaskCount = document.querySelector("#sideTaskCount");
const fragmentBoard = document.querySelector("#fragmentBoard");
const fragmentPagination = document.querySelector("#fragmentPagination");
const fragmentTagFilter = document.querySelector("#fragmentTagFilter");
const plotPeopleRail = document.querySelector("#plotPeopleRail");
const plotDetail = document.querySelector("#plotDetail");
const eventList = document.querySelector("#eventList");
const personName = document.querySelector("#personName");
const personIntro = document.querySelector("#personIntro");
const personAvatar = document.querySelector("#selectedAvatar");
const profileFloat = document.querySelector("#profileFloat");
const graphSearch = document.querySelector("#graphSearch");
const groupFilter = document.querySelector("#groupFilter");
const relationFilter = document.querySelector("#relationFilter");
const timelineList = document.querySelector("#timelineList");
const timelineDirectionBtn = document.querySelector("#timelineDirectionBtn");
const timelineLegend = document.querySelector("#timelineLegend");
const characterList = document.querySelector("#characterList");
const characterDetail = document.querySelector("#characterDetail");
const profileDetailBtn = document.querySelector("#profileDetailBtn");
const characterSearch = document.querySelector("#characterSearch");
const temporaryCharacterToggle = document.querySelector("#temporaryCharacterToggle");
const temporaryCharacterCount = document.querySelector("#temporaryCharacterCount");
const placeList = document.querySelector("#placeList");
const placeDetail = document.querySelector("#placeDetail");
const placeSearch = document.querySelector("#placeSearch");
const entryTypeFilter = document.querySelector("#entryTypeFilter");
const entryTagFilter = document.querySelector("#entryTagFilter");
const globalSearchContainer = document.querySelector("#globalSearchDock");
const globalSearchToggle = document.querySelector("#globalSearchToggle");
const globalSearch = document.querySelector("#globalSearch");
const globalSearchResults = document.querySelector("#globalSearchResults");
const diagnosticSummary = document.querySelector("#diagnosticSummary");
const diagnosticList = document.querySelector("#diagnosticList");
const diagnosticNavCount = document.querySelector("#diagnosticNavCount");
const diagnosticRefreshBtn = document.querySelector("#diagnosticRefreshBtn");
const refactorWorkspace = document.querySelector("#refactorWorkspace");
const refactorMode = document.querySelector("#refactorMode");
const refactorType = document.querySelector("#refactorType");
const refactorTarget = document.querySelector("#refactorTarget");
const refactorNewName = document.querySelector("#refactorNewName");
const refactorPreviewBtn = document.querySelector("#refactorPreviewBtn");
const refactorUndoBtn = document.querySelector("#refactorUndoBtn");
const refactorPreview = document.querySelector("#refactorPreview");
const refactorPreviewSummary = document.querySelector("#refactorPreviewSummary");
const refactorChangeList = document.querySelector("#refactorChangeList");
const refactorCancelBtn = document.querySelector("#refactorCancelBtn");
const refactorApplyBtn = document.querySelector("#refactorApplyBtn");
const relationshipWorkspace = document.querySelector("#relationshipWorkspace");
const relationshipCreateForm = document.querySelector("#relationshipCreateForm");
const relationshipFirstPerson = document.querySelector("#relationshipFirstPerson");
const relationshipFirstRole = document.querySelector("#relationshipFirstRole");
const relationshipSecondPerson = document.querySelector("#relationshipSecondPerson");
const relationshipSecondRole = document.querySelector("#relationshipSecondRole");
const relationshipLabel = document.querySelector("#relationshipLabel");
const relationshipType = document.querySelector("#relationshipType");
const relationshipColor = document.querySelector("#relationshipColor");
const relationshipCreateStatus = document.querySelector("#relationshipCreateStatus");
const relationshipCreateBtn = document.querySelector("#relationshipCreateBtn");
