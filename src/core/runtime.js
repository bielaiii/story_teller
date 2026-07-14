const state = {
  selected: "",
  selectedCharacter: "",
  selectedPlotId: null,
  editingPlotId: null,
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
  characterCategory: "all",
  characterGroup: "all",
  characterViewMode: "cards",
  characterAppearanceChapter: "all",
  placeSearch: "",
  entryTypes: [],
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
const plotCreateTrigger = document.querySelector("#plotCreateTrigger");
const plotCreateDialog = document.querySelector("#plotCreateDialog");
const plotCreateForm = document.querySelector("#plotCreateForm");
const plotCreateSettings = document.querySelector("#plotCreateSettings");
const plotCreateClose = document.querySelector("#plotCreateClose");
const plotCreateCancel = document.querySelector("#plotCreateCancel");
const plotCreateSubmit = document.querySelector("#plotCreateSubmit");
const plotCreateName = document.querySelector("#plotCreateName");
const plotCreateChapter = document.querySelector("#plotCreateChapter");
const plotCreatePositionField = document.querySelector("#plotCreatePositionField");
const plotCreatePosition = document.querySelector("#plotCreatePosition");
const plotCreateStatusField = document.querySelector("#plotCreateStatusField");
const plotCreateAccent = document.querySelector("#plotCreateAccent");
const plotCreateSummary = document.querySelector("#plotCreateSummary");
const plotCreateLanes = document.querySelector("#plotCreateLanes");
const plotCreateTags = document.querySelector("#plotCreateTags");
const plotCreatePeople = document.querySelector("#plotCreatePeople");
const plotCreateEntries = document.querySelector("#plotCreateEntries");
const plotCreateKey = document.querySelector("#plotCreateKey");
const plotCreateClimax = document.querySelector("#plotCreateClimax");
const plotCreateBody = document.querySelector("#plotCreateBody");
const plotCreatePreview = document.querySelector("#plotCreatePreview");
const plotInsertImpact = document.querySelector("#plotInsertImpact");
const plotCreateMessage = document.querySelector("#plotCreateMessage");
const plotTrashWorkspace = document.querySelector("#plotTrashWorkspace");
const plotTrashTrigger = document.querySelector("#plotTrashTrigger");
const plotTrashCount = document.querySelector("#plotTrashCount");
const plotTrashDialog = document.querySelector("#plotTrashDialog");
const plotTrashClose = document.querySelector("#plotTrashClose");
const plotTrashList = document.querySelector("#plotTrashList");
const plotTrashPreview = document.querySelector("#plotTrashPreview");
const plotTrashStatus = document.querySelector("#plotTrashStatus");
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
const timelineEditTrigger = document.querySelector("#timelineEditTrigger");
const timelineEditorDialog = document.querySelector("#timelineEditorDialog");
const timelineEditorClose = document.querySelector("#timelineEditorClose");
const timelineEditorCancel = document.querySelector("#timelineEditorCancel");
const timelineEditorSave = document.querySelector("#timelineEditorSave");
const timelineEditorAddLine = document.querySelector("#timelineEditorAddLine");
const timelineEditorLineList = document.querySelector("#timelineEditorLineList");
const timelineEditorLineCount = document.querySelector("#timelineEditorLineCount");
const timelineEditorUnassigned = document.querySelector("#timelineEditorUnassigned");
const timelineEditorUnassignedCount = document.querySelector("#timelineEditorUnassignedCount");
const timelineEditorEventList = document.querySelector("#timelineEditorEventList");
const timelineEditorInspector = document.querySelector("#timelineEditorInspector");
const timelineEditorSearch = document.querySelector("#timelineEditorSearch");
const timelineEditorStatus = document.querySelector("#timelineEditorStatus");
const characterList = document.querySelector("#characterList");
const characterDetail = document.querySelector("#characterDetail");
const profileDetailBtn = document.querySelector("#profileDetailBtn");
const characterSearch = document.querySelector("#characterSearch");
const temporaryCharacterToggle = document.querySelector("#temporaryCharacterToggle");
const temporaryCharacterCount = document.querySelector("#temporaryCharacterCount");
const characterOverview = document.querySelector("#characterOverview");
const characterLibraryTitle = document.querySelector("#characterLibraryTitle");
const characterVisibleCount = document.querySelector("#characterVisibleCount");
const characterCategoryFilter = document.querySelector("#characterCategoryFilter");
const characterGroupArchiveFilter = document.querySelector("#characterGroupArchiveFilter");
const characterViewSwitch = document.querySelector("#characterViewSwitch");
const characterCreateTrigger = document.querySelector("#characterCreateTrigger");
const characterCreateDialog = document.querySelector("#characterCreateDialog");
const characterCreateForm = document.querySelector("#characterCreateForm");
const characterCreateClose = document.querySelector("#characterCreateClose");
const characterCreateCancel = document.querySelector("#characterCreateCancel");
const characterCreateSubmit = document.querySelector("#characterCreateSubmit");
const characterCreateStatus = document.querySelector("#characterCreateStatus");
const characterCreateName = document.querySelector("#characterCreateName");
const characterCreateRole = document.querySelector("#characterCreateRole");
const characterCreateScope = document.querySelector("#characterCreateScope");
const characterCreateSide = document.querySelector("#characterCreateSide");
const characterCreateGroup = document.querySelector("#characterCreateGroup");
const characterCreateImpact = document.querySelector("#characterCreateImpact");
const characterCreateColor = document.querySelector("#characterCreateColor");
const characterCreateAliases = document.querySelector("#characterCreateAliases");
const characterCreateMarkers = document.querySelector("#characterCreateMarkers");
const characterCreateIntro = document.querySelector("#characterCreateIntro");
const characterGroupSuggestions = document.querySelector("#characterGroupSuggestions");
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
const relationshipManagerList = document.querySelector("#relationshipManagerList");
