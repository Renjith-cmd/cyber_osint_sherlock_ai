/**
 * Sherlock AI — Mobile-First Warm Cream & Deep Plum Investigation SPA
 * Fully integrates all 9 investigation screens with existing FastAPI endpoints.
 */

(function () {
  "use strict";

  const PREFERENCES_KEY = "sherlock_preferences_v1";
  const DEFAULT_PREFERENCES = {
    resolutionThreshold: 0.55,
    graphDepth: "2",
    graphNodes: "50",
    graphZoom: { k: 1, x: 0, y: 0 },
    entitiesPageSize: 9,
    entitiesViewMode: "grid",
    evidencePageSize: 8,
    evidenceViewMode: "cards",
    activeTab: "tab-dashboard",
  };

  function readPreferences() {
    try {
      const stored = JSON.parse(localStorage.getItem(PREFERENCES_KEY) || "{}");
      const prefs = { ...DEFAULT_PREFERENCES, ...stored };
      prefs.graphZoom = { ...DEFAULT_PREFERENCES.graphZoom, ...(stored.graphZoom || {}) };
      if (!Number.isFinite(Number(prefs.resolutionThreshold)) || Number(prefs.resolutionThreshold) < 0.1 || Number(prefs.resolutionThreshold) > 0.95) prefs.resolutionThreshold = DEFAULT_PREFERENCES.resolutionThreshold;
      if (!/^[1-5]$/.test(String(prefs.graphDepth))) prefs.graphDepth = DEFAULT_PREFERENCES.graphDepth;
      if (!/^(10|25|50|100)$/.test(String(prefs.graphNodes))) prefs.graphNodes = DEFAULT_PREFERENCES.graphNodes;
      if (!Number.isFinite(Number(prefs.graphZoom.k)) || prefs.graphZoom.k < 0.3 || prefs.graphZoom.k > 3.5) prefs.graphZoom = { ...DEFAULT_PREFERENCES.graphZoom };
      if (![6, 9, 12, 18].includes(Number(prefs.entitiesPageSize))) prefs.entitiesPageSize = DEFAULT_PREFERENCES.entitiesPageSize;
      if (![6, 8, 12, 18].includes(Number(prefs.evidencePageSize))) prefs.evidencePageSize = DEFAULT_PREFERENCES.evidencePageSize;
      if (!["grid", "table"].includes(prefs.entitiesViewMode)) prefs.entitiesViewMode = DEFAULT_PREFERENCES.entitiesViewMode;
      if (!["cards", "table"].includes(prefs.evidenceViewMode)) prefs.evidenceViewMode = DEFAULT_PREFERENCES.evidenceViewMode;
      if (!["tab-dashboard", "tab-investigations", "tab-documents", "tab-resolution", "tab-entities", "tab-graph", "tab-claims", "tab-report", "tab-settings"].includes(prefs.activeTab)) prefs.activeTab = DEFAULT_PREFERENCES.activeTab;
      return prefs;
    } catch (_) {
      return { ...DEFAULT_PREFERENCES, graphZoom: { ...DEFAULT_PREFERENCES.graphZoom } };
    }
  }

  let preferences = readPreferences();

  function savePreferences() {
    try {
      localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences));
    } catch (err) {
      showToast("Unable to save preferences: " + err.message, "warning");
    }
  }

  // Application State
  const state = {
    activeInvestigationId: null,
    investigations: [],
    activeTab: preferences.activeTab,
    selectedFile: null,
    currentDoc: null,
    entities: [],
    claims: [],
    evidence: [],
    proposals: [],
    graphData: { nodes: [], links: [] },
    graphZoom: { ...preferences.graphZoom },
    healthInfo: null,
    activeEntityProfile: null,
    activeEvidenceItem: null,
    apiAuthPrompted: false,
    // Workspaces Pagination, Filter & View State
    entitiesCurrentPage: 1,
    entitiesPageSize: Number(preferences.entitiesPageSize),
    entitiesViewMode: preferences.entitiesViewMode,
    entitiesSort: "name_asc",
    evidenceCurrentPage: 1,
    evidencePageSize: Number(preferences.evidencePageSize),
    evidenceViewMode: preferences.evidenceViewMode,
  };

  // DOM Elements Cache
  const els = {
    // Header & Global Selectors
    activeInvSelect: document.getElementById("active-inv-select"),
    btnQuickNewHeader: document.getElementById("btn-quick-new-header"),
    btnLoadDemoHeader: document.getElementById("btn-load-demo-header"),
    backendBadge: document.getElementById("backend-badge"),
    persistenceBadge: document.getElementById("persistence-badge"),
    storageNoticeBanner: document.getElementById("storage-notice-banner"),
    storageNoticeText: document.getElementById("storage-notice-text"),
    btnDismissBanner: document.getElementById("btn-dismiss-banner"),
    toastContainer: document.getElementById("toast-container"),

    // Navigation Buttons
    navTabBtns: document.querySelectorAll(".nav-tab-btn"),
    mobileNavBtns: document.querySelectorAll(".mobile-nav-btn"),
    screenViews: document.querySelectorAll(".screen-view"),

    // Counters
    navCountCases: document.getElementById("nav-count-cases"),
    navCountDocs: document.getElementById("nav-count-docs"),
    navCountProposals: document.getElementById("nav-count-proposals"),
    navCountEntities: document.getElementById("nav-count-entities"),
    navCountClaims: document.getElementById("nav-count-claims"),

    // Screen 1: Dashboard
    dashboardInvDesc: document.getElementById("dashboard-inv-desc"),
    dashboardStatusTag: document.getElementById("dashboard-status-tag"),
    btnRefreshDashboard: document.getElementById("btn-refresh-dashboard"),
    mDocsVal: document.getElementById("m-docs-val"),
    mDocsSub: document.getElementById("m-docs-sub"),
    mEntitiesVal: document.getElementById("m-entities-val"),
    mEntitiesSub: document.getElementById("m-entities-sub"),
    mClaimsVal: document.getElementById("m-claims-val"),
    mClaimsSub: document.getElementById("m-claims-sub"),
    mRelsVal: document.getElementById("m-rels-val"),
    mRelsSub: document.getElementById("m-rels-sub"),
    mReviewVal: document.getElementById("m-review-val"),
    mReviewSub: document.getElementById("m-review-sub"),
    mEvidenceVal: document.getElementById("m-evidence-val"),
    mEvidenceSub: document.getElementById("m-evidence-sub"),
    btnQuickUploadDoc: document.getElementById("btn-quick-upload-doc"),
    btnQuickRunResolution: document.getElementById("btn-quick-run-resolution"),
    btnQuickViewGraph: document.getElementById("btn-quick-view-graph"),
    btnQuickGenReport: document.getElementById("btn-quick-gen-report"),
    dashboardWarningsCard: document.getElementById("dashboard-warnings-card"),
    dashboardWarningsList: document.getElementById("dashboard-warnings-list"),
    btnGotoInvestigations: document.getElementById("btn-goto-investigations"),
    tbodyRecentInvestigations: document.getElementById("tbody-recent-investigations"),

    // Screen 2: Investigations
    btnModalCreateCase: document.getElementById("btn-modal-create-case"),
    btnLoadDemoCases: document.getElementById("btn-load-demo-cases"),
    inputSearchCases: document.getElementById("input-search-cases"),
    btnRefreshCases: document.getElementById("btn-refresh-cases"),
    tbodyInvestigations: document.getElementById("tbody-investigations"),

    // Screen 3: Documents
    formUploadDoc: document.getElementById("form-upload-doc"),
    fileDropzone: document.getElementById("file-dropzone"),
    fileInput: document.getElementById("file-input"),
    dropzoneIdleContent: document.getElementById("dropzone-idle-content"),
    dropzoneSelectedFile: document.getElementById("dropzone-selected-file"),
    selectedFileName: document.getElementById("selected-file-name"),
    selectedFileSize: document.getElementById("selected-file-size"),
    btnClearFile: document.getElementById("btn-clear-file"),
    checkAutoProcess: document.getElementById("check-auto-process"),
    btnSubmitUpload: document.getElementById("btn-submit-upload"),
    uploadProgressContainer: document.getElementById("upload-progress-container"),
    uploadProgressFill: document.getElementById("upload-progress-fill"),
    uploadProgressLabel: document.getElementById("upload-progress-label"),
    uploadProgressPercent: document.getElementById("upload-progress-percent"),
    btnProcessAllDocs: document.getElementById("btn-process-all-docs"),
    tbodyDocuments: document.getElementById("tbody-documents"),
    docViewerPanel: document.getElementById("doc-viewer-panel"),
    docViewerTitle: document.getElementById("doc-viewer-title"),
    docViewerHash: document.getElementById("doc-viewer-hash"),
    docViewerText: document.getElementById("doc-viewer-text"),
    docViewerEvidenceList: document.getElementById("doc-viewer-evidence-list"),
    btnCloseViewer: document.getElementById("btn-close-viewer"),

    // Screen 4: Resolution
    btnTriggerCrossDoc: document.getElementById("btn-trigger-cross-doc"),
    inputResThreshold: document.getElementById("input-res-threshold"),
    labelResThreshold: document.getElementById("label-res-threshold"),
    checkAutoApply: document.getElementById("check-auto-apply"),
    statResMatches: document.getElementById("stat-res-matches"),
    statResReviews: document.getElementById("stat-res-reviews"),
    statResNonmatches: document.getElementById("stat-res-nonmatches"),
    btnOpenNonmatchModal: document.getElementById("btn-open-nonmatch-modal"),
    resolutionProposalsContainer: document.getElementById("resolution-proposals-container"),

    // Screen 5: Entities Workspace
    entitiesTotalBadge: document.getElementById("entities-total-badge"),
    entMetricTotal: document.getElementById("ent-metric-total"),
    entMetricMatch: document.getElementById("ent-metric-match"),
    entMetricReview: document.getElementById("ent-metric-review"),
    entMetricUnresolved: document.getElementById("ent-metric-unresolved"),
    filterEntityName: document.getElementById("filter-entity-name"),
    btnClearEntitySearch: document.getElementById("btn-clear-entity-search"),
    filterEntityType: document.getElementById("filter-entity-type"),
    filterEntityStatus: document.getElementById("filter-entity-status"),
    filterEntitySort: document.getElementById("filter-entity-sort"),
    btnEntitiesViewGrid: document.getElementById("btn-entities-view-grid"),
    btnEntitiesViewTable: document.getElementById("btn-entities-view-table"),
    entitiesGridViewContainer: document.getElementById("entities-grid-view-container"),
    entitiesTableViewContainer: document.getElementById("entities-table-view-container"),
    tbodyEntities: document.getElementById("tbody-entities"),
    entitiesPaginationRow: document.getElementById("entities-pagination-row"),
    entitiesPaginationSummary: document.getElementById("entities-pagination-summary"),
    entitiesPageSizeSelect: document.getElementById("entities-page-size"),
    btnEntitiesPrevPage: document.getElementById("btn-entities-prev-page"),
    btnEntitiesNextPage: document.getElementById("btn-entities-next-page"),
    entitiesPagesList: document.getElementById("entities-pages-list"),
    entitiesEmptyState: document.getElementById("entities-empty-state"),
    btnResetEntityFilters: document.getElementById("btn-reset-entity-filters"),
    btnEntitiesNewInv: document.getElementById("btn-entities-new-investigation"),
    entityDrawerBackdrop: document.getElementById("entity-drawer-backdrop"),
    entityDetailPanel: document.getElementById("entity-detail-panel"),
    entityDetailAvatarWrap: document.getElementById("entity-detail-avatar-wrap"),
    entityDetailName: document.getElementById("entity-detail-name"),
    entityDetailId: document.getElementById("entity-detail-id"),
    entityDetailBadge: document.getElementById("entity-detail-badge"),
    entityDetailBody: document.getElementById("entity-detail-body"),
    btnViewEntityInGraph: document.getElementById("btn-view-entity-in-graph"),
    btnSplitEntityOpen: document.getElementById("btn-split-entity-open"),
    btnCloseEntityDetail: document.getElementById("btn-close-entity-detail"),

    // Screen 6: Graph Workspace
    graphStatsBadge: document.getElementById("graph-stats-badge"),
    btnFullscreenGraph: document.getElementById("btn-fullscreen-graph"),
    graphWorkspacePanel: document.getElementById("graph-workspace-panel"),
    graphRootSelect: document.getElementById("graph-root-select"),
    graphDepthInput: document.getElementById("graph-depth-input"),
    graphNodesInput: document.getElementById("graph-nodes-input"),
    graphFilterEdgeType: document.getElementById("graph-filter-edge-type"),
    graphFilterStatus: document.getElementById("graph-filter-status"),
    btnRefreshGraph: document.getElementById("btn-refresh-graph"),
    btnToggleGraphTable: document.getElementById("btn-toggle-graph-table"),
    btnGraphZoomIn: document.getElementById("btn-graph-zoom-in"),
    btnGraphZoomOut: document.getElementById("btn-graph-zoom-out"),
    btnGraphZoomFit: document.getElementById("btn-graph-zoom-fit"),
    btnGraphZoomReset: document.getElementById("btn-graph-zoom-reset"),
    graphSvg: document.getElementById("graph-svg"),
    graphEmptyState: document.getElementById("graph-empty-state"),
    btnGraphGoUpload: document.getElementById("btn-graph-go-upload"),
    graphInspector: document.getElementById("graph-inspector"),
    inspectorTitle: document.getElementById("inspector-title"),
    inspectorContent: document.getElementById("inspector-content"),
    btnCloseInspector: document.getElementById("btn-close-inspector"),
    graphTablePanel: document.getElementById("graph-table-panel"),
    tbodyGraphEdges: document.getElementById("tbody-graph-edges"),

    // Screen 7: Claims & Evidence Workspace
    evidenceTotalBadge: document.getElementById("evidence-total-badge"),
    evMetricDocs: document.getElementById("ev-metric-docs"),
    evMetricSpans: document.getElementById("ev-metric-spans"),
    evMetricClaims: document.getElementById("ev-metric-claims"),
    evMetricDisputes: document.getElementById("ev-metric-disputes"),
    filterEvidenceQuery: document.getElementById("filter-evidence-query"),
    btnClearEvidenceSearch: document.getElementById("btn-clear-evidence-search"),
    btnEvidenceUploadDoc: document.getElementById("btn-evidence-upload-doc"),
    filterEvidencePolarity: document.getElementById("filter-evidence-polarity"),
    filterEvidenceStatus: document.getElementById("filter-evidence-status"),
    filterEvidenceDoc: document.getElementById("filter-evidence-doc"),
    btnResetEvidenceFilters: document.getElementById("btn-reset-evidence-filters"),
    btnEvidenceViewCards: document.getElementById("btn-evidence-view-cards"),
    btnEvidenceViewClaimsTable: document.getElementById("btn-evidence-view-claims-table"),
    evidenceTimelineTrack: document.getElementById("evidence-timeline-track"),
    evidenceCardsContainer: document.getElementById("evidence-cards-container"),
    claimsTableViewContainer: document.getElementById("claims-table-view-container"),
    evidenceTableViewContainer: document.getElementById("evidence-table-view-container"),
    tbodyClaims: document.getElementById("tbody-claims"),
    tbodyEvidence: document.getElementById("tbody-evidence"),
    evidencePaginationRow: document.getElementById("evidence-pagination-row"),
    evidencePaginationSummary: document.getElementById("evidence-pagination-summary"),
    evidencePageSizeSelect: document.getElementById("evidence-page-size"),
    btnEvidencePrevPage: document.getElementById("btn-evidence-prev-page"),
    btnEvidenceNextPage: document.getElementById("btn-evidence-next-page"),
    evidencePagesList: document.getElementById("evidence-pages-list"),
    evidenceEmptyState: document.getElementById("evidence-empty-state"),
    btnEvidenceEmptyUpload: document.getElementById("btn-evidence-empty-upload"),
    evidenceDrawerBackdrop: document.getElementById("evidence-drawer-backdrop"),
    evidenceDetailPanel: document.getElementById("evidence-detail-panel"),
    evidenceDrawerTypeBadge: document.getElementById("evidence-drawer-type-badge"),
    evidenceDrawerTitle: document.getElementById("evidence-drawer-title"),
    evidenceDrawerId: document.getElementById("evidence-drawer-id"),
    btnCloseEvidenceDetail: document.getElementById("btn-close-evidence-detail"),
    evidenceDrawerBody: document.getElementById("evidence-drawer-body"),

    // Screen 8: Report
    btnExportMarkdown: document.getElementById("btn-export-markdown"),
    btnExportJson: document.getElementById("btn-export-json"),
    btnExportHtml: document.getElementById("btn-export-html"),
    btnPrintReport: document.getElementById("btn-print-report"),
    btnRefreshReport: document.getElementById("btn-refresh-report"),
    reportViewContainer: document.getElementById("report-view-container"),

    // Screen 9: Settings & Data Management
    btnRefreshHealth: document.getElementById("btn-refresh-health"),
    cfgStatusVal: document.getElementById("cfg-status-val"),
    cfgVersionVal: document.getElementById("cfg-version-val"),
    cfgBackendVal: document.getElementById("cfg-backend-val"),
    cfgPersistenceVal: document.getElementById("cfg-persistence-val"),
    cfgDbpathVal: document.getElementById("cfg-dbpath-val"),
    cfgTimestampVal: document.getElementById("cfg-timestamp-val"),
    apiTokenInput: document.getElementById("api-token-input"),
    btnSaveApiToken: document.getElementById("btn-save-api-token"),
    btnClearApiToken: document.getElementById("btn-clear-api-token"),
    apiTokenStatus: document.getElementById("api-token-status"),
    btnRefreshStats: document.getElementById("btn-refresh-stats"),
    statsCountInv: document.getElementById("stats-count-inv"),
    statsCountDocs: document.getElementById("stats-count-docs"),
    statsCountEntities: document.getElementById("stats-count-entities"),
    statsCountClaims: document.getElementById("stats-count-claims"),
    statsCountEvidence: document.getElementById("stats-count-evidence"),
    statsCountRels: document.getElementById("stats-count-rels"),
    statsCountReports: document.getElementById("stats-count-reports"),
    // Clear Investigation Modal elements
    clearInvTargetId: document.getElementById("clear-inv-target-id"),
    inputClearInvName: document.getElementById("input-clear-inv-name"),
    btnSubmitClearInv: document.getElementById("btn-submit-clear-inv"),
    clearInvModalError: document.getElementById("clear-inv-modal-error"),
    // Clear All Data Modal elements
    inputClearAllPhrase: document.getElementById("input-clear-all-phrase"),
    btnSubmitClearAll: document.getElementById("btn-submit-clear-all"),
    clearAllModalError: document.getElementById("clear-all-modal-error"),
    clearAllModalCounts: document.getElementById("clear-all-modal-counts"),
    clearInvActiveIdDisplay: document.getElementById("clear-inv-active-id-display"),
    btnOpenClearInvModal: document.getElementById("btn-open-clear-inv-modal"),
    btnOpenClearAllModal: document.getElementById("btn-open-clear-all-modal"),
    btnResetPreferences: document.getElementById("btn-reset-preferences"),

    // Screen 4: Resolution extras
    btnResetResThreshold: document.getElementById("btn-reset-res-threshold"),

    // Modals
    modalNewInv: document.getElementById("modal-new-inv"),
    btnCloseModalNewInv: document.getElementById("btn-close-modal-new-inv"),
    btnCancelModalNewInv: document.getElementById("btn-cancel-modal-new-inv"),
    formCreateInv: document.getElementById("form-create-inv"),
    inputInvId: document.getElementById("input-inv-id"),
    inputInvDesc: document.getElementById("input-inv-desc"),
    selectInvBackend: document.getElementById("select-inv-backend"),

    modalReviewAction: document.getElementById("modal-review-action"),
    btnCloseModalReview: document.getElementById("btn-close-modal-review"),
    btnCancelModalReview: document.getElementById("btn-cancel-modal-review"),
    formReviewDecision: document.getElementById("form-review-decision"),
    reviewClaimId: document.getElementById("review-claim-id"),
    reviewModalClaimInfo: document.getElementById("review-modal-claim-info"),
    selectReviewStatus: document.getElementById("select-review-status"),
    inputReviewerId: document.getElementById("input-reviewer-id"),
    inputReviewRationale: document.getElementById("input-review-rationale"),

    modalNonMatch: document.getElementById("modal-non-match"),
    btnCloseModalNonmatch: document.getElementById("btn-close-modal-nonmatch"),
    btnCancelModalNonmatch: document.getElementById("btn-cancel-modal-nonmatch"),
    formNonMatch: document.getElementById("form-non-match"),
    inputNonmatchA: document.getElementById("input-nonmatch-a"),
    inputNonmatchB: document.getElementById("input-nonmatch-b"),
    inputNonmatchReviewer: document.getElementById("input-nonmatch-reviewer"),
    inputNonmatchRationale: document.getElementById("input-nonmatch-rationale"),

    modalSplitEntity: document.getElementById("modal-split-entity"),
    btnCloseModalSplit: document.getElementById("btn-close-modal-split"),
    btnCancelModalSplit: document.getElementById("btn-cancel-modal-split"),
    formSplitEntity: document.getElementById("form-split-entity"),
    splitTargetEntityId: document.getElementById("split-target-entity-id"),
    splitModalInfo: document.getElementById("split-modal-info"),
    splitRecordsChecklist: document.getElementById("split-records-checklist"),
    inputSplitReviewer: document.getElementById("input-split-reviewer"),
    inputSplitRationale: document.getElementById("input-split-rationale"),

    modalApproveMerge: document.getElementById("modal-approve-merge"),
    btnCloseModalMerge: document.getElementById("btn-close-modal-merge"),
    btnCancelModalMerge: document.getElementById("btn-cancel-modal-merge"),
    formApproveMerge: document.getElementById("form-approve-merge"),
    inputMergeProposalId: document.getElementById("input-merge-proposal-id"),
    mergeModalPairInfo: document.getElementById("merge-modal-pair-info"),
    inputMergeReviewer: document.getElementById("input-merge-reviewer"),
    inputMergeRationale: document.getElementById("input-merge-rationale"),

    modalClearInv: document.getElementById("modal-clear-inv"),
    btnCloseModalClearInv: document.getElementById("btn-close-modal-clear-inv"),
    btnCancelModalClearInv: document.getElementById("btn-cancel-modal-clear-inv"),
    formClearInv: document.getElementById("form-clear-inv"),
    clearInvTargetId: document.getElementById("clear-inv-target-id"),
    inputClearInvName: document.getElementById("input-clear-inv-name"),
    btnSubmitClearInv: document.getElementById("btn-submit-clear-inv"),
    clearInvModalError: document.getElementById("clear-inv-modal-error"),

    modalClearAll: document.getElementById("modal-clear-all"),
    btnCloseModalClearAll: document.getElementById("btn-close-modal-clear-all"),
    btnCancelModalClearAll: document.getElementById("btn-cancel-modal-clear-all"),
    formClearAll: document.getElementById("form-clear-all"),
    clearAllModalCounts: document.getElementById("clear-all-modal-counts"),
    inputClearAllPhrase: document.getElementById("input-clear-all-phrase"),
    btnSubmitClearAll: document.getElementById("btn-submit-clear-all"),
    clearAllModalError: document.getElementById("clear-all-modal-error"),
  };

  // =========================================================================
  // String, ID & Clipboard Helpers
  // =========================================================================

  function formatShortId(id, headLen = 10, tailLen = 6) {
    if (!id) return "";
    const s = String(id);
    if (s.length <= headLen + tailLen + 2) return s;
    return `${s.slice(0, headLen)}…${s.slice(-tailLen)}`;
  }

  function copyTextToClipboard(text, successMsg = "Copied to clipboard") {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        showToast(successMsg, "info");
      }).catch(() => {
        fallbackCopy(text, successMsg);
      });
    } else {
      fallbackCopy(text, successMsg);
    }
  }

  function fallbackCopy(text, successMsg) {
    try {
      const textArea = document.createElement("textarea");
      textArea.value = text;
      textArea.style.position = "fixed";
      textArea.style.left = "-9999px";
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      document.execCommand("copy");
      showToast(successMsg, "info");
      document.body.removeChild(textArea);
    } catch (_) {
      showToast("Unable to copy to clipboard", "warning");
    }
  }

  // =========================================================================
  // API Fetch Utility & Toast Notifications
  // =========================================================================

  async function apiFetch(endpoint, options = {}) {
    try {
      const headers = { ...(options.headers || {}) };
      const token = getApiToken();
      if (token && !headers["Authorization"] && !headers["X-API-Key"]) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      options.headers = headers;

      const res = await fetch(endpoint, options);
      if (!res.ok) {
        let errorDetail = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errJson = await res.json();
          if (errJson && errJson.detail) {
            errorDetail = errJson.detail;
          }
        } catch (_) {}
        if (res.status === 401) promptForApiToken();
        throw new Error(errorDetail);
      }
      return await res.json();
    } catch (err) {
      console.error(`API Error on ${endpoint}:`, err);
      showToast(err.message, "error");
      throw err;
    }
  }

  function promptForApiToken() {
    if (state.apiAuthPrompted) return;
    state.apiAuthPrompted = true;
    state.activeTab = "tab-settings";
    persistPreference("activeTab", state.activeTab);
    if (els.apiTokenStatus) {
      els.apiTokenStatus.textContent = "The backend rejected this request. For Vercel, sign in through Vercel Deployment Protection. For a self-hosted token-protected server, enter its API token here.";
    }
    showToast("Backend authorization failed. Check Vercel access or the self-hosted API token in Settings.", "warning");
    switchTab("tab-settings");
  }

  function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    els.toastContainer.appendChild(toast);
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 4500);
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function entityDisplayName(entityId) {
    const entity = state.entities.find((item) => item.entity_id === entityId);
    return entity && entity.canonical_name ? entity.canonical_name : entityId;
  }

  // =========================================================================
  // Initialization & Tab Navigation
  // =========================================================================

  async function init() {
    setupEventListeners();
    applyPreferencesToControls();
    await checkHealth();
    await loadInvestigationsList();
    await loadSystemStats();
    switchTab(state.activeTab);
  }

  function applyPreferencesToControls() {
    if (els.inputResThreshold) els.inputResThreshold.value = String(preferences.resolutionThreshold);
    if (els.labelResThreshold) els.labelResThreshold.textContent = Number(preferences.resolutionThreshold).toFixed(2);
    if (els.graphDepthInput) els.graphDepthInput.value = String(preferences.graphDepth);
    if (els.graphNodesInput) els.graphNodesInput.value = String(preferences.graphNodes);
    if (els.entitiesPageSizeSelect) els.entitiesPageSizeSelect.value = String(state.entitiesPageSize);
    if (els.evidencePageSizeSelect) els.evidencePageSizeSelect.value = String(state.evidencePageSize);
    if (els.btnEntitiesViewGrid) els.btnEntitiesViewGrid.classList.toggle("active", state.entitiesViewMode === "grid");
    if (els.btnEntitiesViewTable) els.btnEntitiesViewTable.classList.toggle("active", state.entitiesViewMode === "table");
    if (els.btnEvidenceViewCards) els.btnEvidenceViewCards.classList.toggle("active", state.evidenceViewMode === "cards");
    if (els.btnEvidenceViewClaimsTable) els.btnEvidenceViewClaimsTable.classList.toggle("active", state.evidenceViewMode === "table");
  }

  function persistPreference(name, value) {
    preferences[name] = value;
    savePreferences();
  }

  function getApiToken() {
    return localStorage.getItem("sherlock_api_token") || sessionStorage.getItem("sherlock_api_token") || "";
  }

  function switchTab(tabId) {
    state.activeTab = tabId;
    persistPreference("activeTab", tabId);

    // Synchronize Desktop Sidebar Buttons
    els.navTabBtns.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tabId);
    });

    // Synchronize Mobile Bottom Bar Buttons
    els.mobileNavBtns.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tabId);
    });

    // Activate Target Screen View
    els.screenViews.forEach((view) => {
      view.classList.toggle("active", view.id === tabId);
    });

    // Lazy load data for the active screen
    if (!state.activeInvestigationId && tabId !== "tab-investigations" && tabId !== "tab-settings") {
      if (tabId === "tab-dashboard") loadDashboard();
      else if (tabId === "tab-documents") loadDocuments();
      else if (tabId === "tab-resolution") renderResolutionProposals();
      else if (tabId === "tab-entities") renderEntitiesWorkspace();
      else if (tabId === "tab-graph") loadGraph();
      else if (tabId === "tab-claims") loadClaimsAndEvidence();
      else if (tabId === "tab-report") loadReport();
      return;
    }

    if (tabId === "tab-dashboard") loadDashboard();
    else if (tabId === "tab-investigations") renderInvestigationsTable();
    else if (tabId === "tab-documents") loadDocuments();
    else if (tabId === "tab-resolution") renderResolutionProposals();
    else if (tabId === "tab-entities") loadEntities();
    else if (tabId === "tab-graph") loadGraph();
    else if (tabId === "tab-claims") loadClaimsAndEvidence();
    else if (tabId === "tab-report") loadReport();
    else if (tabId === "tab-settings") {
      checkHealth();
      loadSystemStats();
    }
  }

  // =========================================================================
  // Event Listeners Setup
  // =========================================================================

  function setupEventListeners() {
    // Navigation Tabs
    els.navTabBtns.forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });
    els.mobileNavBtns.forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    // Active Investigation Switcher
    els.activeInvSelect.addEventListener("change", (e) => {
      setActiveInvestigation(e.target.value);
    });

    // Banner Dismiss
    els.btnDismissBanner.addEventListener("click", () => {
      els.storageNoticeBanner.style.display = "none";
    });

    // Header Quick Buttons
    els.btnQuickNewHeader.addEventListener("click", () => openModal(els.modalNewInv));
    els.btnLoadDemoHeader.addEventListener("click", () => handleLoadDemo());

    // Screen 1: Dashboard Actions
    if (els.btnRefreshDashboard) els.btnRefreshDashboard.addEventListener("click", () => loadDashboard());
    if (els.btnQuickUploadDoc) els.btnQuickUploadDoc.addEventListener("click", () => switchTab("tab-documents"));
    if (els.btnQuickRunResolution) els.btnQuickRunResolution.addEventListener("click", () => {
      switchTab("tab-resolution");
      triggerCrossDocumentResolution();
    });
    if (els.btnQuickViewGraph) els.btnQuickViewGraph.addEventListener("click", () => switchTab("tab-graph"));
    if (els.btnQuickGenReport) els.btnQuickGenReport.addEventListener("click", () => {
      switchTab("tab-report");
      generateReport();
    });
    if (els.btnGotoInvestigations) els.btnGotoInvestigations.addEventListener("click", () => switchTab("tab-investigations"));

    const btnViewAllEntities = document.getElementById("btn-view-all-entities");
    if (btnViewAllEntities) btnViewAllEntities.addEventListener("click", () => switchTab("tab-entities"));

    const btnExpandGraph = document.getElementById("btn-expand-graph");
    if (btnExpandGraph) btnExpandGraph.addEventListener("click", () => switchTab("tab-graph"));

    const btnViewEvidenceTimeline = document.getElementById("btn-view-evidence-timeline");
    if (btnViewEvidenceTimeline) btnViewEvidenceTimeline.addEventListener("click", () => switchTab("tab-claims"));

    const btnQuickViewGraphRail = document.getElementById("btn-quick-view-graph-rail");
    if (btnQuickViewGraphRail) btnQuickViewGraphRail.addEventListener("click", () => switchTab("tab-graph"));

    const btnQuickBrowseEvidence = document.getElementById("btn-quick-browse-evidence");
    if (btnQuickBrowseEvidence) btnQuickBrowseEvidence.addEventListener("click", () => switchTab("tab-claims"));

    const globalSearch = document.getElementById("global-header-search");
    if (globalSearch) {
      globalSearch.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          const q = globalSearch.value.trim();
          if (q) {
            switchTab("tab-entities");
            if (els.filterEntityName) {
              els.filterEntityName.value = q;
              filterEntitiesTable();
            }
          }
        }
      });
    }

    // Screen 2: Investigations
    els.btnModalCreateCase.addEventListener("click", () => openModal(els.modalNewInv));
    els.btnLoadDemoCases.addEventListener("click", () => handleLoadDemo());
    els.btnRefreshCases.addEventListener("click", () => loadInvestigationsList());
    els.inputSearchCases.addEventListener("input", () => renderInvestigationsTable());

    // Screen 3: Documents Ingestion
    setupDropzone();
    els.formUploadDoc.addEventListener("submit", handleDocumentUpload);
    els.btnProcessAllDocs.addEventListener("click", handleProcessAllDocuments);
    els.btnCloseViewer.addEventListener("click", () => {
      els.docViewerPanel.style.display = "none";
    });

    // Screen 4: Resolution
    els.btnTriggerCrossDoc.addEventListener("click", triggerCrossDocumentResolution);
    els.inputResThreshold.addEventListener("input", (e) => {
      els.labelResThreshold.textContent = parseFloat(e.target.value).toFixed(2);
      persistPreference("resolutionThreshold", parseFloat(e.target.value));
    });
    if (els.btnResetResThreshold) {
      els.btnResetResThreshold.addEventListener("click", () => {
        els.inputResThreshold.value = "0.55";
        els.labelResThreshold.textContent = "0.55";
        persistPreference("resolutionThreshold", 0.55);
        showToast("Threshold reset to default 0.55", "info");
      });
    }
    els.btnOpenNonmatchModal.addEventListener("click", () => openModal(els.modalNonMatch));

    // Global Breadcrumb Navigation Links
    document.querySelectorAll(".breadcrumb-link").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tabLink));
    });

    // Screen 5: Entities Workspace
    if (els.filterEntityName) {
      els.filterEntityName.addEventListener("input", () => {
        if (els.btnClearEntitySearch) {
          els.btnClearEntitySearch.style.display = els.filterEntityName.value ? "inline-block" : "none";
        }
        state.entitiesCurrentPage = 1;
        renderEntitiesWorkspace();
      });
    }
    if (els.btnClearEntitySearch) {
      els.btnClearEntitySearch.addEventListener("click", () => {
        els.filterEntityName.value = "";
        els.btnClearEntitySearch.style.display = "none";
        state.entitiesCurrentPage = 1;
        renderEntitiesWorkspace();
      });
    }
    if (els.filterEntityType) {
      els.filterEntityType.addEventListener("change", () => {
        state.entitiesCurrentPage = 1;
        renderEntitiesWorkspace();
      });
    }
    if (els.filterEntityStatus) {
      els.filterEntityStatus.addEventListener("change", () => {
        state.entitiesCurrentPage = 1;
        renderEntitiesWorkspace();
      });
    }
    if (els.filterEntitySort) {
      els.filterEntitySort.addEventListener("change", () => {
        state.entitiesSort = els.filterEntitySort.value;
        renderEntitiesWorkspace();
      });
    }
    if (els.entitiesPageSizeSelect) {
      els.entitiesPageSizeSelect.addEventListener("change", () => {
        state.entitiesPageSize = Number(els.entitiesPageSizeSelect.value);
        state.entitiesCurrentPage = 1;
        persistPreference("entitiesPageSize", state.entitiesPageSize);
        renderEntitiesWorkspace();
      });
    }
    if (els.btnEntitiesViewGrid) {
      els.btnEntitiesViewGrid.addEventListener("click", () => {
        state.entitiesViewMode = "grid";
        persistPreference("entitiesViewMode", state.entitiesViewMode);
        els.btnEntitiesViewGrid.classList.add("active");
        if (els.btnEntitiesViewTable) els.btnEntitiesViewTable.classList.remove("active");
        renderEntitiesWorkspace();
      });
    }
    if (els.btnEntitiesViewTable) {
      els.btnEntitiesViewTable.addEventListener("click", () => {
        state.entitiesViewMode = "table";
        persistPreference("entitiesViewMode", state.entitiesViewMode);
        els.btnEntitiesViewTable.classList.add("active");
        if (els.btnEntitiesViewGrid) els.btnEntitiesViewGrid.classList.remove("active");
        renderEntitiesWorkspace();
      });
    }
    if (els.btnEntitiesPrevPage) {
      els.btnEntitiesPrevPage.addEventListener("click", () => {
        if (state.entitiesCurrentPage > 1) {
          state.entitiesCurrentPage--;
          renderEntitiesWorkspace();
        }
      });
    }
    if (els.btnEntitiesNextPage) {
      els.btnEntitiesNextPage.addEventListener("click", () => {
        state.entitiesCurrentPage++;
        renderEntitiesWorkspace();
      });
    }
    if (els.btnResetEntityFilters) {
      els.btnResetEntityFilters.addEventListener("click", () => {
        if (els.filterEntityName) els.filterEntityName.value = "";
        if (els.filterEntityType) els.filterEntityType.value = "";
        if (els.filterEntityStatus) els.filterEntityStatus.value = "";
        if (els.filterEntitySort) els.filterEntitySort.value = "name_asc";
        state.entitiesSort = "name_asc";
        state.entitiesCurrentPage = 1;
        renderEntitiesWorkspace();
      });
    }
    if (els.btnEntitiesNewInv) {
      els.btnEntitiesNewInv.addEventListener("click", () => openModal(els.modalNewInv));
    }
    if (els.btnCloseEntityDetail) {
      els.btnCloseEntityDetail.addEventListener("click", closeEntityDrawer);
    }
    if (els.entityDrawerBackdrop) {
      els.entityDrawerBackdrop.addEventListener("click", closeEntityDrawer);
    }
    if (els.btnViewEntityInGraph) {
      els.btnViewEntityInGraph.addEventListener("click", () => {
        if (state.activeEntityProfile) {
          const targetId = state.activeEntityProfile.entity_id;
          closeEntityDrawer();
          focusEntityInGraph(targetId);
        }
      });
    }
    if (els.btnSplitEntityOpen) {
      els.btnSplitEntityOpen.addEventListener("click", handleOpenSplitModal);
    }

    // Screen 6: Graph Workspace
    if (els.btnRefreshGraph) els.btnRefreshGraph.addEventListener("click", loadGraph);
    if (els.btnToggleGraphTable) {
      els.btnToggleGraphTable.addEventListener("click", () => {
        const isVisible = els.graphTablePanel.style.display !== "none";
        els.graphTablePanel.style.display = isVisible ? "none" : "block";
        els.btnToggleGraphTable.textContent = isVisible ? "Tabular View" : "Hide Table";
      });
    }
    if (els.btnFullscreenGraph) {
      els.btnFullscreenGraph.addEventListener("click", toggleGraphFullscreen);
    }
    if (els.graphRootSelect) {
      els.graphRootSelect.addEventListener("change", loadGraph);
    }
    if (els.graphDepthInput) {
      els.graphDepthInput.addEventListener("change", () => {
        persistPreference("graphDepth", els.graphDepthInput.value);
        loadGraph();
      });
    }
    if (els.graphNodesInput) {
      els.graphNodesInput.addEventListener("change", () => {
        persistPreference("graphNodes", els.graphNodesInput.value);
        loadGraph();
      });
    }
    if (els.graphFilterEdgeType) {
      els.graphFilterEdgeType.addEventListener("change", renderSvgGraph);
    }
    if (els.graphFilterStatus) {
      els.graphFilterStatus.addEventListener("change", renderSvgGraph);
    }
    if (els.btnGraphZoomIn) {
      els.btnGraphZoomIn.addEventListener("click", () => {
        state.graphZoom.k = Math.min(3.5, state.graphZoom.k * 1.25);
        persistPreference("graphZoom", state.graphZoom);
        updateGraphTransform();
      });
    }
    if (els.btnGraphZoomOut) {
      els.btnGraphZoomOut.addEventListener("click", () => {
        state.graphZoom.k = Math.max(0.3, state.graphZoom.k / 1.25);
        persistPreference("graphZoom", state.graphZoom);
        updateGraphTransform();
      });
    }
    if (els.btnGraphZoomFit) {
      els.btnGraphZoomFit.addEventListener("click", fitGraphToView);
    }
    if (els.btnGraphZoomReset) {
      els.btnGraphZoomReset.addEventListener("click", () => {
        state.graphZoom = { k: 1, x: 0, y: 0 };
        persistPreference("graphZoom", state.graphZoom);
        updateGraphTransform();
      });
    }
    if (els.btnCloseInspector) {
      els.btnCloseInspector.addEventListener("click", () => {
        els.graphInspector.style.display = "none";
      });
    }
    if (els.btnGraphGoUpload) {
      els.btnGraphGoUpload.addEventListener("click", () => switchTab("tab-documents"));
    }

    // Screen 7: Claims & Evidence Workspace
    if (els.filterEvidenceQuery) {
      els.filterEvidenceQuery.addEventListener("input", () => {
        if (els.btnClearEvidenceSearch) {
          els.btnClearEvidenceSearch.style.display = els.filterEvidenceQuery.value ? "inline-block" : "none";
        }
        state.evidenceCurrentPage = 1;
        renderEvidenceExplorer();
      });
    }
    if (els.btnClearEvidenceSearch) {
      els.btnClearEvidenceSearch.addEventListener("click", () => {
        els.filterEvidenceQuery.value = "";
        els.btnClearEvidenceSearch.style.display = "none";
        state.evidenceCurrentPage = 1;
        renderEvidenceExplorer();
      });
    }
    if (els.filterEvidencePolarity) {
      els.filterEvidencePolarity.addEventListener("change", () => {
        state.evidenceCurrentPage = 1;
        renderEvidenceExplorer();
      });
    }
    if (els.filterEvidenceStatus) {
      els.filterEvidenceStatus.addEventListener("change", () => {
        state.evidenceCurrentPage = 1;
        renderEvidenceExplorer();
      });
    }
    if (els.filterEvidenceDoc) {
      els.filterEvidenceDoc.addEventListener("change", () => {
        state.evidenceCurrentPage = 1;
        renderEvidenceExplorer();
      });
    }
    if (els.btnResetEvidenceFilters) {
      els.btnResetEvidenceFilters.addEventListener("click", () => {
        if (els.filterEvidenceQuery) els.filterEvidenceQuery.value = "";
        if (els.filterEvidencePolarity) els.filterEvidencePolarity.value = "";
        if (els.filterEvidenceStatus) els.filterEvidenceStatus.value = "";
        if (els.filterEvidenceDoc) els.filterEvidenceDoc.value = "";
        state.evidenceCurrentPage = 1;
        renderEvidenceExplorer();
      });
    }
    if (els.btnEvidenceViewCards) {
      els.btnEvidenceViewCards.addEventListener("click", () => {
        state.evidenceViewMode = "cards";
        persistPreference("evidenceViewMode", state.evidenceViewMode);
        els.btnEvidenceViewCards.classList.add("active");
        if (els.btnEvidenceViewClaimsTable) els.btnEvidenceViewClaimsTable.classList.remove("active");
        renderEvidenceExplorer();
      });
    }
    if (els.btnEvidenceViewClaimsTable) {
      els.btnEvidenceViewClaimsTable.addEventListener("click", () => {
        state.evidenceViewMode = "table";
        persistPreference("evidenceViewMode", state.evidenceViewMode);
        els.btnEvidenceViewClaimsTable.classList.add("active");
        if (els.btnEvidenceViewCards) els.btnEvidenceViewCards.classList.remove("active");
        renderEvidenceExplorer();
      });
    }
    if (els.btnEvidencePrevPage) {
      els.btnEvidencePrevPage.addEventListener("click", () => {
        if (state.evidenceCurrentPage > 1) {
          state.evidenceCurrentPage--;
          renderEvidenceExplorer();
        }
      });
    }
    if (els.btnEvidenceNextPage) {
      els.btnEvidenceNextPage.addEventListener("click", () => {
        state.evidenceCurrentPage++;
        renderEvidenceExplorer();
      });
    }
    if (els.evidencePageSizeSelect) {
      els.evidencePageSizeSelect.addEventListener("change", () => {
        state.evidencePageSize = Number(els.evidencePageSizeSelect.value);
        state.evidenceCurrentPage = 1;
        persistPreference("evidencePageSize", state.evidencePageSize);
        renderEvidenceExplorer();
      });
    }
    if (els.btnEvidenceUploadDoc) {
      els.btnEvidenceUploadDoc.addEventListener("click", () => switchTab("tab-documents"));
    }
    if (els.btnEvidenceEmptyUpload) {
      els.btnEvidenceEmptyUpload.addEventListener("click", () => switchTab("tab-documents"));
    }
    if (els.btnCloseEvidenceDetail) {
      els.btnCloseEvidenceDetail.addEventListener("click", closeEvidenceDrawer);
    }
    if (els.evidenceDrawerBackdrop) {
      els.evidenceDrawerBackdrop.addEventListener("click", closeEvidenceDrawer);
    }

    // Screen 8: Report
    els.btnRefreshReport.addEventListener("click", generateReport);
    els.btnExportMarkdown.addEventListener("click", exportReportMarkdown);
    els.btnExportJson.addEventListener("click", exportReportJson);
    if (els.btnExportHtml) els.btnExportHtml.addEventListener("click", exportReportHtml);
    if (els.btnPrintReport) els.btnPrintReport.addEventListener("click", printReport);

    // Screen 9: Settings & Data Management
    els.btnRefreshHealth.addEventListener("click", checkHealth);
    if (els.btnRefreshStats) els.btnRefreshStats.addEventListener("click", loadSystemStats);
    if (els.btnOpenClearInvModal) els.btnOpenClearInvModal.addEventListener("click", openClearInvestigationModal);
    if (els.btnOpenClearAllModal) els.btnOpenClearAllModal.addEventListener("click", openClearAllDataModal);
    if (els.btnResetPreferences) els.btnResetPreferences.addEventListener("click", handleResetPreferences);
    if (els.btnSaveApiToken) {
      els.btnSaveApiToken.addEventListener("click", () => {
        const token = els.apiTokenInput ? els.apiTokenInput.value.trim() : "";
        if (token.length < 16) {
          if (els.apiTokenStatus) els.apiTokenStatus.textContent = "Token must contain at least 16 characters.";
          return;
        }
        localStorage.setItem("sherlock_api_token", token);
        state.apiAuthPrompted = false;
        if (els.apiTokenInput) els.apiTokenInput.value = "";
        if (els.apiTokenStatus) els.apiTokenStatus.textContent = "Token saved in this browser.";
        showToast("API access token saved", "success");
        checkHealth();
        loadInvestigationsList();
        loadSystemStats();
      });
    }
    if (els.btnClearApiToken) {
      els.btnClearApiToken.addEventListener("click", () => {
        localStorage.removeItem("sherlock_api_token");
        sessionStorage.removeItem("sherlock_api_token");
        if (els.apiTokenInput) els.apiTokenInput.value = "";
        if (els.apiTokenStatus) els.apiTokenStatus.textContent = "Token cleared from this browser.";
        showToast("API access token cleared", "info");
      });
    }

    // Modals
    setupModalEvents();
  }

  function setupModalEvents() {
    // New Inv Modal
    els.btnCloseModalNewInv.addEventListener("click", () => closeModal(els.modalNewInv));
    els.btnCancelModalNewInv.addEventListener("click", () => closeModal(els.modalNewInv));
    els.formCreateInv.addEventListener("submit", handleCreateInvestigation);

    // Review Modal
    els.btnCloseModalReview.addEventListener("click", () => closeModal(els.modalReviewAction));
    els.btnCancelModalReview.addEventListener("click", () => closeModal(els.modalReviewAction));
    els.formReviewDecision.addEventListener("submit", handleCommitReviewDecision);

    // Non-Match Modal
    els.btnCloseModalNonmatch.addEventListener("click", () => closeModal(els.modalNonMatch));
    els.btnCancelModalNonmatch.addEventListener("click", () => closeModal(els.modalNonMatch));
    els.formNonMatch.addEventListener("submit", handleCommitNonMatchConstraint);

    // Split Modal
    els.btnCloseModalSplit.addEventListener("click", () => closeModal(els.modalSplitEntity));
    els.btnCancelModalSplit.addEventListener("click", () => closeModal(els.modalSplitEntity));
    els.formSplitEntity.addEventListener("submit", handleCommitSplitEntity);

    // Approve Merge Modal
    if (els.btnCloseModalMerge) els.btnCloseModalMerge.addEventListener("click", () => closeModal(els.modalApproveMerge));
    if (els.btnCancelModalMerge) els.btnCancelModalMerge.addEventListener("click", () => closeModal(els.modalApproveMerge));
    if (els.formApproveMerge) els.formApproveMerge.addEventListener("submit", handleCommitApproveMerge);

    // Clear Active Investigation Modal
    if (els.btnCloseModalClearInv) els.btnCloseModalClearInv.addEventListener("click", () => closeModal(els.modalClearInv));
    if (els.btnCancelModalClearInv) els.btnCancelModalClearInv.addEventListener("click", () => closeModal(els.modalClearInv));
    if (els.formClearInv) els.formClearInv.addEventListener("submit", handleCommitClearInvestigation);

    // Clear All System Data Modal
    if (els.btnCloseModalClearAll) els.btnCloseModalClearAll.addEventListener("click", () => closeModal(els.modalClearAll));
    if (els.btnCancelModalClearAll) els.btnCancelModalClearAll.addEventListener("click", () => closeModal(els.modalClearAll));
    if (els.formClearAll) els.formClearAll.addEventListener("submit", handleCommitClearAllData);
    if (els.inputClearAllPhrase) {
      els.inputClearAllPhrase.addEventListener("input", () => {
        const val = els.inputClearAllPhrase.value.trim();
        if (els.btnSubmitClearAll) {
          els.btnSubmitClearAll.disabled = val !== "DELETE ALL SHERLOCK DATA";
        }
      });
    }

    // Close on backdrop click
    document.querySelectorAll(".modal-backdrop").forEach((modal) => {
      modal.addEventListener("click", (e) => {
        if (e.target === modal) closeModal(modal);
      });
    });
  }

  function openModal(modal) {
    if (modal) modal.style.display = "flex";
  }

  function closeModal(modal) {
    if (modal) modal.style.display = "none";
  }

  // =========================================================================
  // System Health & Ready Check
  // =========================================================================

  async function checkHealth() {
    try {
      const data = await apiFetch("/api/v1/health");
      state.healthInfo = data;

      els.cfgStatusVal.textContent = data.status.toUpperCase();
      els.cfgVersionVal.textContent = data.version;
      els.cfgBackendVal.textContent = data.backend_mode;
      els.cfgPersistenceVal.textContent = data.persistence_backend;
      els.cfgDbpathVal.textContent = data.persistence_db_path || "In-Memory (Transient)";
      els.cfgTimestampVal.textContent = new Date(data.timestamp).toLocaleString();

      els.backendBadge.textContent = `Backend: ${data.backend_mode}`;
      const isEphemeralSqlite = data.persistence_backend === "sqlite" && String(data.persistence_db_path || "").startsWith("/tmp/");
      els.persistenceBadge.textContent = isEphemeralSqlite
        ? "SQLITE: EPHEMERAL"
        : `${data.persistence_backend.toUpperCase()}: Active`;
      els.persistenceBadge.title = isEphemeralSqlite ? "Temporary function storage; data may disappear between invocations." : "Persistent application storage";

      if (isEphemeralSqlite) {
        els.storageNoticeText.textContent = "Temporary SQLite storage is active (/tmp). Data may disappear between serverless invocations; use an external database for persistent investigations.";
      } else if (data.persistence_backend === "sqlite") {
        els.storageNoticeText.textContent = `Durable SQLite storage active (${data.persistence_db_path}). State survives process restarts.`;
      } else {
        els.storageNoticeText.textContent = "Volatile In-Memory storage active. Graph state will not survive process restarts.";
      }
    } catch (_) {
      els.cfgStatusVal.textContent = "OFFLINE";
      els.cfgStatusVal.className = "status-pill status-pill-danger";
    }
  }

  // =========================================================================
  // Screen 9: Data Management & System Statistics
  // =========================================================================

  async function loadSystemStats() {
    try {
      if (els.clearInvActiveIdDisplay) {
        els.clearInvActiveIdDisplay.textContent = state.activeInvestigationId || "None Selected";
      }
      if (els.btnOpenClearInvModal) {
        els.btnOpenClearInvModal.disabled = !state.activeInvestigationId;
      }
      const stats = await apiFetch("/api/v1/system/stats");
      if (els.statsCountInv) els.statsCountInv.textContent = stats.investigations ?? 0;
      if (els.statsCountDocs) els.statsCountDocs.textContent = stats.documents ?? 0;
      if (els.statsCountEntities) els.statsCountEntities.textContent = stats.entities ?? 0;
      if (els.statsCountClaims) els.statsCountClaims.textContent = stats.claims ?? 0;
      if (els.statsCountEvidence) els.statsCountEvidence.textContent = (stats.evidence ?? stats.evidence_items ?? 0);
      if (els.statsCountRels) els.statsCountRels.textContent = stats.relationships ?? 0;
      if (els.statsCountReports) els.statsCountReports.textContent = (stats.reports ?? stats.reports_generated ?? 0);
      return stats;
    } catch (err) {
      console.warn("Could not load system stats:", err);
    }
  }

  function resetAllUiViews() {
    state.activeInvestigationId = null;
    state.investigations = [];
    state.documents = [];
    state.entities = [];
    state.proposals = [];
    state.claims = [];
    state.evidence = [];
    state.activeEntityProfile = null;
    state.graphData = { nodes: [], links: [] };

    // Navigation and Header counters
    if (els.navCountCases) els.navCountCases.textContent = "0";
    if (els.navCountDocs) els.navCountDocs.textContent = "0";
    if (els.navCountEntities) els.navCountEntities.textContent = "0";
    if (els.navCountProposals) els.navCountProposals.textContent = "0";
    if (els.navCountClaims) els.navCountClaims.textContent = "0";
    if (els.activeInvSelect) {
      els.activeInvSelect.innerHTML = '<option value="" disabled selected>No investigations found</option>';
    }
    // Reset system statistics counters
    if (els.statsCountInv) els.statsCountInv.textContent = "0";
    if (els.statsCountDocs) els.statsCountDocs.textContent = "0";
    if (els.statsCountEntities) els.statsCountEntities.textContent = "0";
    if (els.statsCountClaims) els.statsCountClaims.textContent = "0";
    if (els.statsCountEvidence) els.statsCountEvidence.textContent = "0";
    if (els.statsCountRels) els.statsCountRels.textContent = "0";
    if (els.statsCountReports) els.statsCountReports.textContent = "0";

    // Active Case Indicators
    const activeCaseBadges = document.querySelectorAll(".header-active-case-badge, .active-case-pill");
    activeCaseBadges.forEach((el) => {
      el.textContent = "No Active Case";
    });

    // Dashboard Overview
    if (els.dashboardInvDesc) els.dashboardInvDesc.textContent = "No investigation active. Select or create an investigation to begin.";
    if (els.dashboardStatusTag) {
      els.dashboardStatusTag.textContent = "IDLE";
      els.dashboardStatusTag.className = "status-pill status-pill-muted";
    }
    if (els.mDocsVal) els.mDocsVal.textContent = "0";
    if (els.mDocsSub) els.mDocsSub.textContent = "0 completed, 0 failed";
    if (els.mEntitiesVal) els.mEntitiesVal.textContent = "0";
    if (els.mEntitiesSub) els.mEntitiesSub.textContent = "0 canonical, 0 provisional";
    if (els.mClaimsVal) els.mClaimsVal.textContent = "0";
    if (els.mClaimsSub) els.mClaimsSub.textContent = "0 unreviewed, 0 verified";
    if (els.mRelsVal) els.mRelsVal.textContent = "0";
    if (els.mRelsSub) els.mRelsSub.textContent = "0 active, 0 disputed";
    if (els.mReviewVal) els.mReviewVal.textContent = "0";
    if (els.mReviewSub) els.mReviewSub.textContent = "Queue empty";
    if (els.mEvidenceVal) els.mEvidenceVal.textContent = "0";
    if (els.mEvidenceSub) els.mEvidenceSub.textContent = "0 spans grounded";
    const statMatch = document.getElementById("stat-count-match");
    const statReview = document.getElementById("stat-count-review");
    const statNonmatch = document.getElementById("stat-count-nonmatch");
    if (statMatch) statMatch.textContent = "0";
    if (statReview) statReview.textContent = "0";
    if (statNonmatch) statNonmatch.textContent = "0";
    if (els.dashboardWarningsCard) els.dashboardWarningsCard.style.display = "none";
    if (els.tbodyRecentInvestigations) {
      els.tbodyRecentInvestigations.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding: 24px;">No investigations registered.</td></tr>';
    }
    renderDashboardTrackedEntities([]);

    // Investigations table
    if (els.tbodyInvestigations) {
      els.tbodyInvestigations.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding: 24px;">No investigations found. Click "+ New Investigation" to start.</td></tr>';
    }

    // Documents
    if (els.tbodyDocuments) {
      els.tbodyDocuments.innerHTML = '<tr><td colspan="9" class="text-center text-muted" style="padding: 24px;">No documents uploaded. Select or create an investigation first.</td></tr>';
    }
    if (els.docViewerPanel) els.docViewerPanel.style.display = "none";

    // Resolution / Proposals
    if (els.resolutionProposalsContainer) {
      els.resolutionProposalsContainer.innerHTML = `
        <div class="empty-state-card" style="padding: var(--spacing-xl);">
          <span class="empty-icon">🎯</span>
          <div class="empty-title text-cream">No Resolution Proposals</div>
          <div class="empty-sub">Ingest documents and run cross-document resolution to detect merge proposals.</div>
        </div>
      `;
    }
    if (els.statResMatches) els.statResMatches.textContent = "0";
    if (els.statResReviews) els.statResReviews.textContent = "0";
    if (els.statResNonmatches) els.statResNonmatches.textContent = "0";

    // Entities Workspace
    if (els.entitiesTotalBadge) els.entitiesTotalBadge.textContent = "0 Total";
    if (els.entMetricTotal) els.entMetricTotal.textContent = "0";
    if (els.entMetricMatch) els.entMetricMatch.textContent = "0";
    if (els.entMetricReview) els.entMetricReview.textContent = "0";
    if (els.entMetricUnresolved) els.entMetricUnresolved.textContent = "0";
    if (els.entitiesGridViewContainer) els.entitiesGridViewContainer.innerHTML = "";
    if (els.tbodyEntities) els.tbodyEntities.innerHTML = "";
    if (els.entitiesEmptyState) els.entitiesEmptyState.style.display = "flex";
    if (els.entitiesPaginationRow) els.entitiesPaginationRow.style.display = "none";
    if (els.entityDetailPanel) els.entityDetailPanel.classList.remove("open");
    if (els.entityDrawerBackdrop) els.entityDrawerBackdrop.classList.remove("open");

    // Graph Workspace
    if (els.graphStatsBadge) els.graphStatsBadge.textContent = "0 Nodes • 0 Edges";
    if (els.graphEmptyState) els.graphEmptyState.style.display = "flex";
    if (els.graphSvg) {
      els.graphSvg.style.display = "none";
      els.graphSvg.innerHTML = "";
    }
    if (els.graphRootSelect) els.graphRootSelect.innerHTML = '<option value="">Entire Graph (All Entities)</option>';
    if (els.tbodyGraphEdges) els.tbodyGraphEdges.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No graph relationships.</td></tr>';
    if (els.graphInspector) els.graphInspector.style.display = "none";

    // Claims & Evidence
    if (els.evidenceTotalBadge) els.evidenceTotalBadge.textContent = "0 Spans • 0 Claims";
    if (els.evMetricDocs) els.evMetricDocs.textContent = "0";
    if (els.evMetricSpans) els.evMetricSpans.textContent = "0";
    if (els.evMetricClaims) els.evMetricClaims.textContent = "0";
    if (els.evMetricDisputes) els.evMetricDisputes.textContent = "0";
    if (els.evidenceTimelineTrack) els.evidenceTimelineTrack.innerHTML = "";
    if (els.evidenceCardsContainer) els.evidenceCardsContainer.innerHTML = "";
    if (els.tbodyClaims) els.tbodyClaims.innerHTML = "";
    if (els.tbodyEvidence) els.tbodyEvidence.innerHTML = "";
    if (els.evidenceEmptyState) els.evidenceEmptyState.style.display = "flex";
    if (els.evidencePaginationRow) els.evidencePaginationRow.style.display = "none";
    if (els.evidenceDetailPanel) els.evidenceDetailPanel.classList.remove("open");
    if (els.evidenceDrawerBackdrop) els.evidenceDrawerBackdrop.classList.remove("open");

    // Report
    if (els.reportViewContainer) {
      els.reportViewContainer.innerHTML = `
        <div class="empty-state-card" style="padding: var(--spacing-xl);">
          <span class="empty-icon">📑</span>
          <div class="empty-title text-cream">No Report Generated</div>
          <div class="empty-sub">Synthesize findings into an investigative report once documents and entities exist.</div>
        </div>
      `;
    }


    if (els.clearInvActiveIdDisplay) els.clearInvActiveIdDisplay.textContent = "None Selected";
  }

  function openClearInvestigationModal() {
    const investigationId = state.activeInvestigationId || (els.activeInvSelect && els.activeInvSelect.value);
    if (!investigationId) {
      showToast("No active investigation selected to clear", "warning");
      return;
    }
    state.activeInvestigationId = investigationId;
    if (els.clearInvTargetId) {
      els.clearInvTargetId.textContent = investigationId;
    }
    if (els.inputClearInvName) {
      els.inputClearInvName.value = "";
    }
    if (els.clearInvModalError) {
      els.clearInvModalError.style.display = "none";
      els.clearInvModalError.textContent = "";
    }
    if (els.btnSubmitClearInv) {
      els.btnSubmitClearInv.disabled = false;
      els.btnSubmitClearInv.textContent = "Permanently Delete Case";
    }
    openModal(els.modalClearInv);
  }

  async function handleCommitClearInvestigation(e) {
    if (e && e.preventDefault) e.preventDefault();
    const investigationId = state.activeInvestigationId || (els.activeInvSelect && els.activeInvSelect.value);
    if (!investigationId) return;
    state.activeInvestigationId = investigationId;

    const confirmedName = els.inputClearInvName ? els.inputClearInvName.value.trim() : "";
    if (!confirmedName) {
      showToast("Please enter the investigation ID to confirm", "warning");
      return;
    }
    if (confirmedName !== investigationId) {
      const msg = "Confirmation name must exactly match the investigation ID";
      if (els.clearInvModalError) {
        els.clearInvModalError.textContent = msg;
        els.clearInvModalError.style.display = "block";
      }
      showToast(msg, "warning");
      return;
    }

    if (els.clearInvModalError) {
      els.clearInvModalError.style.display = "none";
      els.clearInvModalError.textContent = "";
    }
    if (els.btnSubmitClearInv) {
      els.btnSubmitClearInv.disabled = true;
      els.btnSubmitClearInv.textContent = "Deleting Case...";
    }

    try {
      showToast(`Clearing investigation '${investigationId}'...`, "info");
      await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(investigationId)}/clear`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmed_name: confirmedName }),
        }
      );

      showToast(`Investigation '${investigationId}' cleared successfully!`, "success");
      closeModal(els.modalClearInv);
      await loadInvestigationsList();
      await loadSystemStats();
      if (state.investigations.length > 0) {
        await setActiveInvestigation(state.investigations[0].investigation_id);
      } else {
        resetAllUiViews();
      }
    } catch (err) {
      if (els.clearInvModalError) {
        els.clearInvModalError.textContent = "Deletion failed: " + (err.message || "Unknown error occurred.");
        els.clearInvModalError.style.display = "block";
      }
      showToast("Failed to clear investigation: " + err.message, "error");
    } finally {
      if (els.btnSubmitClearInv) {
        els.btnSubmitClearInv.disabled = false;
        els.btnSubmitClearInv.textContent = "Permanently Delete Case";
        // clear the input field for next use
        if (els.inputClearInvName) els.inputClearInvName.value = "";
      }
    }
  }

  async function openClearAllDataModal() {
    if (els.inputClearAllPhrase) {
      els.inputClearAllPhrase.value = "";
    }
    if (els.btnSubmitClearAll) {
      els.btnSubmitClearAll.disabled = true;
      els.btnSubmitClearAll.textContent = "Wipe All Data";
    }
    if (els.clearAllModalError) {
      els.clearAllModalError.style.display = "none";
      els.clearAllModalError.textContent = "";
    }
    if (els.clearAllModalCounts) {
      els.clearAllModalCounts.textContent = "Calculating affected record counts…";
    }
    openModal(els.modalClearAll);
    try {
      const stats = await loadSystemStats();
      if (els.clearAllModalCounts && stats) {
        els.clearAllModalCounts.textContent = `${stats.investigations ?? 0} investigations, ${stats.documents ?? 0} documents, ${stats.entities ?? 0} entities, and ${stats.claims ?? 0} claims`;
      }
    } catch (_) {
      if (els.clearAllModalCounts) {
        els.clearAllModalCounts.textContent = "All operational data across the system will be permanently deleted.";
      }
    }
  }

  async function handleCommitClearAllData(e) {
    if (e && e.preventDefault) e.preventDefault();

    const phrase = els.inputClearAllPhrase ? els.inputClearAllPhrase.value.trim() : "";
    // Accept either of the valid confirmation phrases
    const validPhrases = new Set(["DELETE ALL SHERLOCK DATA", "CLEAR ALL DATA"]);
    if (!validPhrases.has(phrase)) {
      const msg = "Confirmation phrase must match exactly 'DELETE ALL SHERLOCK DATA' or 'CLEAR ALL DATA'";
      if (els.clearAllModalError) {
        els.clearAllModalError.textContent = msg;
        els.clearAllModalError.style.display = "block";
      }
      showToast(msg, "warning");
      if (els.btnSubmitClearAll) els.btnSubmitClearAll.disabled = true;
      return;
    }

    if (els.clearAllModalError) {
      els.clearAllModalError.style.display = "none";
      els.clearAllModalError.textContent = "";
    }
    if (els.btnSubmitClearAll) {
      els.btnSubmitClearAll.disabled = true;
      els.btnSubmitClearAll.textContent = "Purging System Storage...";
    }

    try {
      showToast("Purging all data from system storage...", "info");
      const result = await apiFetch("/api/v1/system/clear-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation_phrase: phrase }),
      });

      const deleted = result.deleted_counts || {};
      const summaryMsg = `Cleared: ${deleted.investigations || 0} cases, ${deleted.documents || 0} docs, ${deleted.entities || 0} entities, ${deleted.claims || 0} claims.`;
      showToast("All system operational data cleared! " + summaryMsg, "success");
      closeModal(els.modalClearAll);

      // Reset all frontend state and every screen view to clean empty states
      resetAllUiViews();

      // Refresh queries against fresh server responses
      await loadInvestigationsList();
      await loadSystemStats();

      // If user was on Settings, stay on Settings with fresh 0 stats; otherwise switch to investigations
      if (state.activeTab === "tab-settings") {
        switchTab("tab-settings");
      } else {
        switchTab("tab-investigations");
      }
    } catch (err) {
      if (els.clearAllModalError) {
        els.clearAllModalError.textContent = "Clear-all failed: " + (err.message || "An unexpected storage error occurred.");
        els.clearAllModalError.style.display = "block";
      }
      showToast("Failed to clear system data: " + err.message, "error");
    } finally {
      // Restore the button to its default enabled state after operation completes
      if (els.btnSubmitClearAll) {
        els.btnSubmitClearAll.disabled = false;
        els.btnSubmitClearAll.textContent = "Clear All Data";
        // Also clear the input field for a fresh start
        if (els.inputClearAllPhrase) els.inputClearAllPhrase.value = "";
      }
    }
  }

  function handleResetPreferences() {
    try {
      preferences = { ...DEFAULT_PREFERENCES, graphZoom: { ...DEFAULT_PREFERENCES.graphZoom } };
      state.graphZoom = { ...preferences.graphZoom };
      state.activeTab = preferences.activeTab;
      state.entitiesPageSize = preferences.entitiesPageSize;
      state.entitiesViewMode = preferences.entitiesViewMode;
      state.entitiesCurrentPage = 1;
      state.evidencePageSize = preferences.evidencePageSize;
      state.evidenceViewMode = preferences.evidenceViewMode;
      state.evidenceCurrentPage = 1;
      savePreferences();
      applyPreferencesToControls();
      if (els.btnEntitiesViewGrid) els.btnEntitiesViewGrid.classList.add("active");
      if (els.btnEntitiesViewTable) els.btnEntitiesViewTable.classList.remove("active");
      if (els.btnEvidenceViewCards) els.btnEvidenceViewCards.classList.add("active");
      if (els.btnEvidenceViewClaimsTable) els.btnEvidenceViewClaimsTable.classList.remove("active");
      if (els.entitiesPageSizeSelect) els.entitiesPageSizeSelect.value = String(state.entitiesPageSize);
      if (els.evidencePageSizeSelect) els.evidencePageSizeSelect.value = String(state.evidencePageSize);
      updateGraphTransform();
      renderEntitiesWorkspace();
      renderEvidenceExplorer();
      switchTab(preferences.activeTab);
      showToast("Preferences and view states reset to factory defaults", "info");
    } catch (err) {
      showToast("Failed to reset preferences: " + err.message, "error");
    }
  }

  // =========================================================================
  // Investigations Management
  // =========================================================================

  async function loadInvestigationsList() {
    try {
      const data = await apiFetch("/api/v1/investigations");
      state.investigations = data.investigations || [];
      els.navCountCases.textContent = state.investigations.length;

      // Populate Select Options
      els.activeInvSelect.innerHTML = "";
      if (state.investigations.length === 0) {
        els.activeInvSelect.innerHTML = '<option value="" disabled selected>No investigations found</option>';
      } else {
        state.investigations.forEach((inv) => {
          const opt = document.createElement("option");
          opt.value = inv.investigation_id;
          opt.textContent = `${inv.investigation_id} (${inv.status})`;
          if (inv.investigation_id === state.activeInvestigationId) {
            opt.selected = true;
          }
          els.activeInvSelect.appendChild(opt);
        });

        // Default to first if none active
        if (!state.activeInvestigationId && state.investigations.length > 0) {
          setActiveInvestigation(state.investigations[0].investigation_id);
        }
      }

      renderInvestigationsTable();
      renderRecentInvestigations();
    } catch (err) {
      console.error("Failed to load investigations:", err);
    }
  }

  function setActiveInvestigation(invId) {
    if (!invId) return;
    state.activeInvestigationId = invId;
    if (els.activeInvSelect) els.activeInvSelect.value = invId;
    if (els.clearInvActiveIdDisplay) els.clearInvActiveIdDisplay.textContent = invId;
    if (els.btnOpenClearInvModal) els.btnOpenClearInvModal.disabled = false;

    showToast(`Active case: ${invId}`, "info");

    // Refresh active screen
    switchTab(state.activeTab);
  }

  function renderInvestigationsTable() {
    const query = (els.inputSearchCases.value || "").toLowerCase().trim();
    const filtered = state.investigations.filter(
      (inv) =>
        inv.investigation_id.toLowerCase().includes(query) ||
        (inv.description && inv.description.toLowerCase().includes(query))
    );

    if (filtered.length === 0) {
      els.tbodyInvestigations.innerHTML =
        '<tr><td colspan="9" class="text-center text-muted">No matching investigations found.</td></tr>';
      return;
    }

    els.tbodyInvestigations.innerHTML = filtered
      .map((inv) => {
        const isCurrent = inv.investigation_id === state.activeInvestigationId;
        const summary = inv.summary || {};
        return `
          <tr class="${isCurrent ? "table-row-selected" : ""}">
            <td><strong class="text-plum">${escapeHtml(inv.investigation_id)}</strong> ${
              isCurrent ? '<span class="status-pill status-pill-success">ACTIVE</span>' : ""
            }</td>
            <td>${escapeHtml(inv.description || "—")}</td>
            <td><span class="code-pill">${escapeHtml(inv.backend_mode)}</span></td>
            <td><span class="status-pill ${getStatusBadgeClass(inv.status)}">${escapeHtml(inv.status)}</span></td>
            <td>${summary.total_documents ?? 0}</td>
            <td>${summary.total_entities ?? 0}</td>
            <td>${summary.total_claims ?? 0}</td>
            <td class="text-muted">${inv.created_at ? new Date(inv.created_at).toLocaleDateString() : "—"}</td>
            <td>
              <button class="btn btn-peach-pill btn-sm" onclick="window.sherlockApp.selectCase('${escapeHtml(
                inv.investigation_id
              )}')">
                ${isCurrent ? "Viewing" : "Open Case"}
              </button>
            </td>
          </tr>
        `;
      })
      .join("");
  }

  function renderRecentInvestigations() {
    const recents = state.investigations.slice(0, 5);
    if (recents.length === 0) {
      if (els.tbodyRecentInvestigations) {
        els.tbodyRecentInvestigations.innerHTML =
          '<tr><td colspan="6" class="text-center text-muted">No investigations loaded.</td></tr>';
      }
      return;
    }

    if (els.tbodyRecentInvestigations) {
      els.tbodyRecentInvestigations.innerHTML = recents
        .map((inv) => {
          const isCurrent = inv.investigation_id === state.activeInvestigationId;
          const summary = inv.summary || {};
          return `
            <tr>
              <td><strong class="text-plum">${escapeHtml(inv.investigation_id)}</strong></td>
              <td>${escapeHtml(inv.description || "—")}</td>
              <td><span class="status-pill ${getStatusBadgeClass(inv.status)}">${escapeHtml(inv.status)}</span></td>
              <td>${summary.total_documents ?? 0}</td>
              <td>${summary.total_entities ?? 0}</td>
              <td>
                <button class="btn btn-peach-pill btn-sm" onclick="window.sherlockApp.selectCase('${escapeHtml(
                  inv.investigation_id
                )}')">
                  ${isCurrent ? "Active" : "Open"}
                </button>
              </td>
            </tr>
          `;
        })
        .join("");
    }

    // Also populate the reference mockup recent sessions list
    const listUi = document.getElementById("recent-investigations-list-ui");
    if (listUi && recents.length > 0) {
      listUi.innerHTML = recents
        .map((inv) => {
          const isCurrent = inv.investigation_id === state.activeInvestigationId;
          const dateStr = inv.created_at ? new Date(inv.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "Recent session";
          const statusClass = inv.status === "RESOLVED" || inv.status === "ACTIVE" ? "status-pill-success" : (inv.status === "REVIEW" ? "status-pill-warning" : "status-pill-neutral");
          const statusText = inv.status === "RESOLVED" ? "MATCH" : (inv.status === "REVIEW" ? "REVIEW" : inv.status);
          return `
            <div class="recent-inv-row" onclick="window.sherlockApp.selectCase('${escapeHtml(inv.investigation_id)}')">
              <div class="recent-row-left">
                <span class="recent-row-icon">📄</span>
                <div>
                  <div class="recent-row-title">${escapeHtml(inv.description || inv.investigation_id)}</div>
                  <div class="recent-row-time">${escapeHtml(dateStr)} ${isCurrent ? "• (Current)" : ""}</div>
                </div>
              </div>
              <div class="recent-row-right">
                <span class="status-pill ${statusClass}">${escapeHtml(statusText)}</span>
                <button class="circle-arrow-btn-sm">→</button>
              </div>
            </div>
          `;
        })
        .join("");
    }
  }

  async function handleCreateInvestigation(e) {
    e.preventDefault();
    const invId = els.inputInvId.value.trim();
    const desc = els.inputInvDesc.value.trim();
    const backend = els.selectInvBackend.value;

    if (!invId) return;

    try {
      await apiFetch("/api/v1/investigations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          investigation_id: invId,
          description: desc,
          backend_mode: backend,
        }),
      });

      showToast(`Investigation '${invId}' created!`, "success");
      closeModal(els.modalNewInv);
      els.formCreateInv.reset();
      await loadInvestigationsList();
      setActiveInvestigation(invId);
    } catch (_) {}
  }

  async function handleLoadDemo() {
    const demoId = `demo_case_${Date.now().toString().slice(-4)}`;
    try {
      showToast("Loading synthetic benchmark case...", "info");
      await apiFetch(`/api/v1/investigations/${demoId}/demo`, { method: "POST" });
      showToast(`Fictional demo case '${demoId}' loaded!`, "success");
      await loadInvestigationsList();
      setActiveInvestigation(demoId);
    } catch (_) {}
  }

  // =========================================================================
  // Screen 1: Dashboard Overview
  // =========================================================================

  async function loadDashboard() {
    if (!state.activeInvestigationId) {
      if (els.dashboardInvDesc) els.dashboardInvDesc.textContent = "No active investigation selected.";
      if (els.dashboardStatusTag) {
        els.dashboardStatusTag.textContent = "IDLE";
        els.dashboardStatusTag.className = "status-pill status-pill-muted";
      }
      if (els.mDocsVal) els.mDocsVal.textContent = "0";
      if (els.mDocsSub) els.mDocsSub.textContent = "0 completed, 0 failed";
      if (els.mEntitiesVal) els.mEntitiesVal.textContent = "0";
      if (els.mEntitiesSub) els.mEntitiesSub.textContent = "0 canonical, 0 provisional";
      if (els.mClaimsVal) els.mClaimsVal.textContent = "0";
      if (els.mClaimsSub) els.mClaimsSub.textContent = "0 unreviewed, 0 verified";
      if (els.mRelsVal) els.mRelsVal.textContent = "0";
      if (els.mRelsSub) els.mRelsSub.textContent = "0 active, 0 disputed";
      if (els.mReviewVal) els.mReviewVal.textContent = "0";
      if (els.mEvidenceVal) els.mEvidenceVal.textContent = "0";
      const statMatch = document.getElementById("stat-count-match");
      const statReview = document.getElementById("stat-count-review");
      const statNonmatch = document.getElementById("stat-count-nonmatch");
      if (statMatch) statMatch.textContent = "0";
      if (statReview) statReview.textContent = "0";
      if (statNonmatch) statNonmatch.textContent = "0";
      if (els.dashboardWarningsCard) els.dashboardWarningsCard.style.display = "none";
      renderRecentInvestigations();
      renderDashboardTrackedEntities([]);
      return;
    }

    try {
      const inv = await apiFetch(`/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}`);
      els.dashboardInvDesc.textContent = inv.description || "No description provided.";
      els.dashboardStatusTag.textContent = inv.status;
      els.dashboardStatusTag.className = `status-pill ${getStatusBadgeClass(inv.status)}`;

      const sum = inv.summary || {};
      els.mDocsVal.textContent = sum.total_documents ?? 0;
      els.mDocsSub.textContent = `${sum.completed_documents ?? 0} completed, ${sum.failed_documents ?? 0} failed`;

      els.mEntitiesVal.textContent = sum.total_entities ?? 0;
      els.mEntitiesSub.textContent = `${sum.canonical_entities ?? 0} canonical, ${sum.provisional_entities ?? 0} provisional`;

      els.mClaimsVal.textContent = sum.total_claims ?? 0;
      els.mClaimsSub.textContent = `${sum.unreviewed_claims ?? 0} unreviewed, ${sum.verified_claims ?? 0} verified`;

      els.mRelsVal.textContent = sum.total_relationships ?? 0;
      els.mRelsSub.textContent = `${sum.active_relationships ?? 0} active, ${sum.disputed_relationships ?? 0} disputed`;

      els.mReviewVal.textContent = sum.human_review_queue_size ?? 0;
      els.mEvidenceVal.textContent = sum.total_evidence_items ?? 0;

      // Update Navigation Counters
      els.navCountDocs.textContent = sum.total_documents ?? 0;
      els.navCountEntities.textContent = sum.total_entities ?? 0;
      els.navCountClaims.textContent = sum.total_claims ?? 0;

      // Update Status Metric Count Cards in Dashboard
      const statMatch = document.getElementById("stat-count-match");
      const statReview = document.getElementById("stat-count-review");
      const statNonmatch = document.getElementById("stat-count-nonmatch");
      if (statMatch) statMatch.textContent = sum.canonical_entities ?? sum.total_entities ?? 0;
      if (statReview) statReview.textContent = (sum.human_review_queue_size ?? 0) + (sum.provisional_entities ?? 0);
      if (statNonmatch) statNonmatch.textContent = sum.non_match_constraints ?? 0;

      // Warnings
      if (sum.warnings && sum.warnings.length > 0) {
        els.dashboardWarningsCard.style.display = "flex";
        els.dashboardWarningsList.innerHTML = sum.warnings
          .map((w) => `<li>${escapeHtml(w)}</li>`)
          .join("");
      } else {
        els.dashboardWarningsCard.style.display = "none";
      }

      renderRecentInvestigations();

      // Ensure entities are fetched and render Tracked Entities
      if (!state.entities || state.entities.length === 0) {
        try {
          const entData = await apiFetch(
            `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/entities`
          );
          state.entities = entData.entities || [];
        } catch (_) {}
      }
      renderDashboardTrackedEntities(state.entities);
    } catch (err) {
      console.error("Dashboard load failed:", err);
    }
  }

  function renderDashboardTrackedEntities(entities) {
    const container = document.getElementById("tracked-entities-container");
    if (!container) return;
    if (!entities || entities.length === 0) {
      container.innerHTML = `
        <div class="empty-state-card" style="grid-column: 1 / -1; padding: var(--spacing-xl);">
          <span class="empty-icon">👥</span>
          <div class="empty-title text-cream">No Tracked Entities Yet</div>
          <div class="empty-sub">Ingest documents and run cross-document resolution to detect and track entities.</div>
        </div>
      `;
      return;
    }
    const top3 = entities.slice(0, 3);

    container.innerHTML = top3
      .map((ent) => {
        const stickerHtml = window.SherlockStickers
          ? window.SherlockStickers.renderEntitySticker(ent.entity_id, ent.entity_type, { size: "lg" })
          : `<img src="/static/assets/cat_avatar_watson.svg" class="cat-avatar-img" alt="avatar">`;
        const statusClass = ent.status === "CANONICAL" ? "status-pill-success" : (ent.status === "DISPUTED" ? "status-pill-danger" : "status-pill-warning");
        const statusText = ent.status === "CANONICAL" ? "MATCH" : (ent.status === "DISPUTED" ? "NON-MATCH" : (ent.status || "REVIEW"));
        const memberCount = (ent.member_mentions && ent.member_mentions.length) || (ent.member_record_ids && ent.member_record_ids.length) || 1;
        const shortId = formatShortId(ent.entity_id, 10, 6);
        return `
          <div class="entity-card-item">
            <div class="entity-card-badge-row">
              <span class="status-pill ${statusClass}">${escapeHtml(statusText)}</span>
            </div>
            <div class="entity-avatar-wrap">
              ${stickerHtml}
            </div>
            <h4 class="entity-card-name" title="${escapeHtml(ent.canonical_name || "Unnamed Entity")}">${escapeHtml(ent.canonical_name || "Unnamed Entity")}</h4>
            <div class="entity-id-row">
              <span class="entity-id-micro" title="${escapeHtml(ent.entity_id)}" aria-label="Entity ID: ${escapeHtml(ent.entity_id)}">
                ID: <code class="entity-id-code">${escapeHtml(shortId)}</code>
              </span>
              <button type="button" class="btn-copy-id" title="Copy full ID: ${escapeHtml(ent.entity_id)}" aria-label="Copy full entity ID" onclick="event.stopPropagation(); window.sherlockApp.copyText('${escapeHtml(ent.entity_id)}', 'Entity ID copied')">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              </button>
            </div>
            <div class="entity-card-tags">
              <span class="tag-pill">${escapeHtml(ent.entity_type || "Entity")}</span>
              <span class="tag-pill">${escapeHtml(ent.status || "Tracked")}</span>
            </div>
            <div class="entity-card-footer">
              <span class="records-count">📄 ${memberCount} source record${memberCount === 1 ? "" : "s"}</span>
              <button class="circle-arrow-btn" aria-label="Inspect ${escapeHtml(ent.canonical_name)}" onclick="window.sherlockApp.inspectEntity('${escapeHtml(ent.entity_id)}')">→</button>
            </div>
          </div>
        `;
      })
      .join("");
  }

  // =========================================================================
  // Screen 3: Document Intake & Processing
  // =========================================================================

  function setupDropzone() {
    const dz = els.fileDropzone;

    dz.addEventListener("click", () => els.fileInput.click());

    dz.addEventListener("dragover", (e) => {
      e.preventDefault();
      dz.classList.add("drag-over");
    });

    dz.addEventListener("dragleave", () => {
      dz.classList.remove("drag-over");
    });

    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("drag-over");
      if (e.dataTransfer.files.length > 0) {
        handleFileSelected(e.dataTransfer.files[0]);
      }
    });

    els.fileInput.addEventListener("change", (e) => {
      if (e.target.files.length > 0) {
        handleFileSelected(e.target.files[0]);
      }
    });

    els.btnClearFile.addEventListener("click", (e) => {
      e.stopPropagation();
      clearSelectedFile();
    });
  }

  function handleFileSelected(file) {
    state.selectedFile = file;
    els.selectedFileName.textContent = file.name;
    els.selectedFileSize.textContent = formatBytes(file.size);
    els.dropzoneIdleContent.style.display = "none";
    els.dropzoneSelectedFile.style.display = "flex";
    els.btnSubmitUpload.disabled = false;
  }

  function clearSelectedFile() {
    state.selectedFile = null;
    els.fileInput.value = "";
    els.dropzoneIdleContent.style.display = "block";
    els.dropzoneSelectedFile.style.display = "none";
    els.btnSubmitUpload.disabled = true;
  }

  async function handleDocumentUpload(e) {
    e.preventDefault();
    if (!state.selectedFile || !state.activeInvestigationId) return;

    const file = state.selectedFile;
    if (file.size <= 0) {
      showToast("Cannot upload empty file (0 bytes).", "error");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      showToast("File exceeds 5 MB maximum allowed limit.", "error");
      return;
    }

    const ext = (file.name.split('.').pop() || '').toLowerCase();
    if (!["txt", "json", "pdf"].includes(ext)) {
      showToast(`Unsupported format '.${ext}'. Allowed formats: .txt, .json, .pdf`, "error");
      return;
    }

    const autoProcess = els.checkAutoProcess ? els.checkAutoProcess.checked : true;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("auto_process", autoProcess ? "true" : "false");

    const progressBox = els.uploadProgressContainer;
    const progressFill = els.uploadProgressFill;
    const progressLabel = els.uploadProgressLabel;
    const progressPercent = els.uploadProgressPercent;

    if (progressBox) progressBox.style.display = "block";
    if (progressFill) progressFill.style.width = "5%";
    if (progressLabel) progressLabel.textContent = "Uploading payload...";
    if (progressPercent) progressPercent.textContent = "5%";

    try {
      els.btnSubmitUpload.disabled = true;
      els.btnSubmitUpload.textContent = "Uploading & Ingesting...";

      const res = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open(
          "POST",
          `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/documents`
        );

        xhr.upload.onprogress = (evt) => {
          if (evt.lengthComputable) {
            const pct = Math.round((evt.loaded / evt.total) * 60);
            if (progressFill) progressFill.style.width = `${pct}%`;
            if (progressPercent) progressPercent.textContent = `${pct}%`;
            if (progressLabel) progressLabel.textContent = "Uploading document bytes...";
          }
        };

        xhr.onload = () => {
          if (progressFill) progressFill.style.width = "90%";
          if (progressPercent) progressPercent.textContent = "90%";
          if (progressLabel) progressLabel.textContent = "Running ingestion pipeline...";

          try {
            const data = JSON.parse(xhr.responseText);
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve(data);
            } else {
              reject(new Error(data.detail || `Upload failed with HTTP ${xhr.status}`));
            }
          } catch (parseErr) {
            reject(new Error(`Failed to parse server response: ${xhr.statusText}`));
          }
        };

        xhr.onerror = () => reject(new Error("Network connection error during upload."));
        xhr.send(formData);
      });

      if (progressFill) progressFill.style.width = "100%";
      if (progressPercent) progressPercent.textContent = "100%";
      if (progressLabel) progressLabel.textContent = "Completed!";

      if (res.status === "FAILED") {
        showToast(`Document ingestion failed: ${res.error_message || "Parser error"}`, "error");
      } else {
        showToast(
          `Document '${file.name}' ingested (${res.mention_count || 0} mentions, ${res.claim_count || 0} claims)!`,
          "success"
        );
      }

      clearSelectedFile();
      await loadDocuments();
      await loadDashboard();
    } catch (err) {
      console.error("Upload error:", err);
      showToast(err.message || "Failed to upload document", "error");
      if (progressLabel) progressLabel.textContent = "Upload failed";
    } finally {
      els.btnSubmitUpload.disabled = false;
      els.btnSubmitUpload.textContent = "Upload & Ingest";
      setTimeout(() => {
        if (progressBox) progressBox.style.display = "none";
      }, 3000);
    }
  }

  async function loadDocuments() {
    if (!state.activeInvestigationId) return;

    try {
      const data = await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/documents`
      );
      const docs = data.documents || [];
      els.navCountDocs.textContent = docs.length;

      if (docs.length === 0) {
        els.tbodyDocuments.innerHTML =
          '<tr><td colspan="9" class="text-center text-muted">No documents uploaded for this investigation.</td></tr>';
        return;
      }

      els.tbodyDocuments.innerHTML = docs
        .map(
          (doc) => `
          <tr>
            <td><strong class="text-plum">${escapeHtml(doc.document_id.slice(0, 12))}</strong></td>
            <td>${escapeHtml(doc.source_name)}</td>
            <td><span class="code-pill">${escapeHtml(doc.content_hash.slice(0, 12))}...</span></td>
            <td>
              <span class="status-pill ${getStatusBadgeClass(doc.status)}" title="${escapeHtml(doc.error_message || '')}">${escapeHtml(doc.status)}</span>
              ${doc.error_message ? `<div class="text-xs text-danger" style="font-size: 0.72rem; color: #dc2626; margin-top: 3px; max-width: 220px; line-height: 1.2;" title="${escapeHtml(doc.error_message)}">${escapeHtml(doc.error_message.length > 70 ? doc.error_message.slice(0, 67) + '...' : doc.error_message)}</div>` : ''}
            </td>
            <td>${doc.char_count}</td>
            <td>${doc.mention_count}</td>
            <td>${doc.claim_count}</td>
            <td>${doc.evidence_count}</td>
            <td>
              <button class="btn btn-dark-pill btn-sm" onclick="window.sherlockApp.inspectDoc('${escapeHtml(
                doc.document_id
              )}')">
                Inspect Spans
              </button>
            </td>
          </tr>
        `
        )
        .join("");
    } catch (err) {
      console.error("Failed to load documents:", err);
    }
  }

  async function inspectDocument(docId) {
    if (!state.activeInvestigationId) return;

    try {
      const doc = await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/documents/${encodeURIComponent(
          docId
        )}`
      );
      state.currentDoc = doc;

      els.docViewerTitle.textContent = `${doc.source_name} (${doc.document_id.slice(0, 12)})`;
      els.docViewerHash.textContent = `SHA-256: ${doc.content_hash.slice(0, 16)}...`;
      els.docViewerText.textContent = doc.status === "FAILED" && doc.error_message
        ? `[Extraction Failed]\n${doc.error_message}`
        : (doc.raw_text_preview || "No preview available.");

      const evs = doc.grounded_evidence || [];
      if (evs.length === 0) {
        els.docViewerEvidenceList.innerHTML =
          '<p class="text-muted">No evidence spans grounded in this document.</p>';
      } else {
        els.docViewerEvidenceList.innerHTML = evs
          .map(
            (ev) => `
            <div class="evidence-item-card" onclick="window.sherlockApp.highlightSpan(${ev.start_char}, ${ev.end_char})">
              <div class="evidence-item-span">"${escapeHtml(ev.text_span)}"</div>
              <div class="evidence-item-offsets">
                Span: [${ev.start_char}:${ev.end_char}] • Sentence: ${ev.sentence_index} • Status: ${escapeHtml(
              ev.status
            )}
              </div>
            </div>
          `
          )
          .join("");
      }

      els.docViewerPanel.style.display = "block";
      els.docViewerPanel.scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      console.error("Doc inspect failed:", err);
    }
  }

  function highlightSpanInViewer(startChar, endChar) {
    if (!state.currentDoc || !state.currentDoc.raw_text_preview) return;
    const fullText = state.currentDoc.raw_text_preview;
    const before = fullText.slice(0, startChar);
    const target = fullText.slice(startChar, endChar);
    const after = fullText.slice(endChar);

    els.docViewerText.innerHTML = `${escapeHtml(before)}<mark style="background-color: var(--accent-peach); color: var(--text-plum); font-weight: bold; border-radius: 4px; padding: 2px 4px;">${escapeHtml(
      target
    )}</mark>${escapeHtml(after)}`;
  }

  async function handleProcessAllDocuments() {
    if (!state.activeInvestigationId) return;
    try {
      showToast("Processing all documents...", "info");
      await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/process-all`,
        { method: "POST" }
      );
      showToast("All documents processed!", "success");
      loadDocuments();
      loadDashboard();
    } catch (_) {}
  }

  // =========================================================================
  // Screen 4: Entity Resolution & Reversibility (Milestone 15 API)
  // =========================================================================

  async function triggerCrossDocumentResolution() {
    if (!state.activeInvestigationId) return;

    const threshold = parseFloat(els.inputResThreshold.value) || 0.55;
    const autoApply = els.checkAutoApply.checked;

    try {
      showToast("Running cross-document entity resolution...", "info");
      els.btnTriggerCrossDoc.disabled = true;

      const data = await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(
          state.activeInvestigationId
        )}/cross-document-resolution?threshold=${threshold}&auto_apply=${autoApply}`,
        { method: "POST" }
      );

      state.proposals = data.proposals || [];
      els.navCountProposals.textContent = state.proposals.length;
      els.statResMatches.textContent = data.matches ?? 0;
      els.statResReviews.textContent = data.reviews_required ?? 0;
      els.statResNonmatches.textContent = data.non_matches ?? 0;

      showToast(
        `Resolution complete: ${data.matches} matches, ${data.reviews_required} reviews.`,
        "success"
      );
      renderResolutionProposals();
      loadDashboard();
    } catch (_) {
    } finally {
      els.btnTriggerCrossDoc.disabled = false;
    }
  }

  function renderResolutionProposals() {
    if (state.proposals.length === 0) {
      els.resolutionProposalsContainer.innerHTML = `
        <div class="empty-state-card">
          <span class="empty-icon">🔀</span>
          <div class="empty-title text-plum">No Cross-Document Proposals Evaluated</div>
          <div class="empty-sub">Click "Run Resolution Engine" above to trigger pairwise candidate generation across ingested documents.</div>
        </div>
      `;
      return;
    }

    els.resolutionProposalsContainer.innerHTML = state.proposals
      .map((p) => {
        const badgeClass =
          p.decision === "MATCH"
            ? "status-pill-success"
            : p.decision === "REVIEW"
            ? "status-pill-warning"
            : "status-pill-danger";

        return `
          <div class="proposal-item-card">
            <div class="proposal-header">
              <div class="proposal-pair-title" title="${escapeHtml(p.entity_id_a)} ⇄ ${escapeHtml(p.entity_id_b)}">
                <code class="entity-id-code">${escapeHtml(formatShortId(p.entity_id_a, 10, 6))}</code>
                <span style="color: var(--accent-peach); margin: 0 4px;">⇄</span>
                <code class="entity-id-code">${escapeHtml(formatShortId(p.entity_id_b, 10, 6))}</code>
              </div>
              <div style="display: flex; gap: 8px; align-items: center;">
                <span class="status-pill ${badgeClass}">${escapeHtml(p.decision)}</span>
                <span class="code-pill" title="Heuristic Similarity Score (0.0 to 1.0)">Score: ${(
                  p.score ?? 0
                ).toFixed(2)}</span>
              </div>
            </div>

            <p style="font-size: 0.88rem; color: var(--text-plum-secondary);">
              <strong>Explanation:</strong> ${escapeHtml(p.explanation || "No explanation recorded.")}
            </p>

            <div class="proposal-details-grid">
              <div class="proposal-detail-box">
                <div class="detail-box-title">Positive Corroboration</div>
                <div>${(p.positive_evidence && p.positive_evidence.length > 0)
                  ? p.positive_evidence.map((e) => `• ${escapeHtml(e)}`).join("<br>")
                  : "None recorded."}</div>
              </div>
              <div class="proposal-detail-box">
                <div class="detail-box-title">Negative / Missing Context</div>
                <div>${(p.missing_information && p.missing_information.length > 0)
                  ? p.missing_information.map((m) => `• ${escapeHtml(m)}`).join("<br>")
                  : "No fatal negative constraints."}</div>
              </div>
            </div>

            <div class="proposal-actions-row">
              ${
                !p.is_applied && (p.decision === "MATCH" || p.decision === "REVIEW")
                  ? `<button class="btn btn-peach-pill btn-sm" onclick="window.sherlockApp.approveMerge('${escapeHtml(
                      p.proposal_id
                    )}')">Approve Entity Merge</button>`
                  : ""
              }
              <button class="btn btn-dark-pill btn-sm" onclick="window.sherlockApp.declareNonMatchPrefill('${escapeHtml(
                p.entity_id_a
              )}', '${escapeHtml(p.entity_id_b)}')">
                Enforce NON_MATCH
              </button>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function handleApproveMerge(proposalId) {
    if (!state.activeInvestigationId) return;

    if (els.inputMergeProposalId) {
      els.inputMergeProposalId.value = proposalId;
    }
    const prop = (state.proposals || []).find((p) => p.proposal_id === proposalId);
    if (els.mergeModalPairInfo) {
      if (prop) {
        els.mergeModalPairInfo.textContent = `${prop.entity_id_a} ⇄ ${prop.entity_id_b} (Score: ${(prop.score ?? 0).toFixed(2)})`;
      } else {
        els.mergeModalPairInfo.textContent = `Proposal ID: ${proposalId}`;
      }
    }
    if (els.inputMergeReviewer && !els.inputMergeReviewer.value) {
      els.inputMergeReviewer.value = "lead_analyst";
    }
    if (els.inputMergeRationale && !els.inputMergeRationale.value) {
      els.inputMergeRationale.value = "Corroborated by shared identity attributes and contextual evidence.";
    }

    openModal(els.modalApproveMerge);
  }

  async function handleCommitApproveMerge(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (!state.activeInvestigationId) return;

    const proposalId = els.inputMergeProposalId ? els.inputMergeProposalId.value.trim() : "";
    const reviewer = (els.inputMergeReviewer ? els.inputMergeReviewer.value.trim() : "") || "lead_analyst";
    const rationale = (els.inputMergeRationale ? els.inputMergeRationale.value.trim() : "") || "Corroborated by shared evidence.";

    if (!proposalId) {
      showToast("Missing proposal identifier", "warning");
      return;
    }

    try {
      await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/entities/merge`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            proposal_id: proposalId,
            reviewer: reviewer,
            rationale: rationale,
          }),
        }
      );

      showToast("Entity merge successfully applied!", "success");
      closeModal(els.modalApproveMerge);
      triggerCrossDocumentResolution();
      loadEntities();
      loadDashboard();
    } catch (_) {}
  }

  function handleDeclareNonMatchPrefill(entA, entB) {
    els.inputNonmatchA.value = entA;
    els.inputNonmatchB.value = entB;
    openModal(els.modalNonMatch);
  }

  async function handleCommitNonMatchConstraint(e) {
    e.preventDefault();
    if (!state.activeInvestigationId) return;

    const entA = els.inputNonmatchA.value.trim();
    const entB = els.inputNonmatchB.value.trim();
    const reviewer = els.inputNonmatchReviewer.value.trim();
    const rationale = els.inputNonmatchRationale.value.trim();

    try {
      await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/non-match-constraints`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_id_a: entA,
            entity_id_b: entB,
            reviewer: reviewer,
            rationale: rationale,
          }),
        }
      );

      showToast("Non-match constraint successfully recorded!", "success");
      closeModal(els.modalNonMatch);
      els.formNonMatch.reset();
      triggerCrossDocumentResolution();
    } catch (_) {}
  }

  // =========================================================================
  // Screen 5: Entities Workspace
  // =========================================================================

  async function loadEntities() {
    if (!state.activeInvestigationId) return;

    try {
      const data = await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/entities`
      );
      state.entities = data.entities || [];
      if (els.navCountEntities) els.navCountEntities.textContent = state.entities.length;

      // Update Screen 5 Summary Metrics
      const total = state.entities.length;
      const reviewCount = state.entities.filter((e) => e.is_provisional).length;
      const matchCount = state.entities.filter((e) => !e.is_provisional && (e.member_record_ids || []).length > 1).length;
      const unresolvedCount = total - matchCount - reviewCount;

      if (els.entitiesTotalBadge) els.entitiesTotalBadge.textContent = `${total} Total`;
      if (els.entMetricTotal) els.entMetricTotal.textContent = total;
      if (els.entMetricMatch) els.entMetricMatch.textContent = matchCount;
      if (els.entMetricReview) els.entMetricReview.textContent = reviewCount;
      if (els.entMetricUnresolved) els.entMetricUnresolved.textContent = Math.max(0, unresolvedCount);

      // Populate filter dropdown with unique types
      if (els.filterEntityType && els.filterEntityType.options.length <= 1) {
        const types = Array.from(new Set(state.entities.map((e) => e.entity_type).filter(Boolean)));
        types.forEach((t) => {
          const opt = document.createElement("option");
          opt.value = t;
          opt.textContent = t;
          els.filterEntityType.appendChild(opt);
        });
      }

      renderEntitiesWorkspace();
    } catch (err) {
      console.error("Failed to load entities:", err);
    }
  }

  function filterAndSortEntities() {
    const query = (els.filterEntityName ? els.filterEntityName.value : "").toLowerCase().trim();
    const typeFilter = els.filterEntityType ? els.filterEntityType.value : "";
    const statusFilter = els.filterEntityStatus ? els.filterEntityStatus.value : "";

    let list = state.entities.filter((ent) => {
      const name = (ent.canonical_name || "").toLowerCase();
      const id = (ent.entity_id || "").toLowerCase();
      const records = (ent.member_record_ids || []).map((r) => String(r).toLowerCase()).join(" ");
      const matchesQuery = !query || name.includes(query) || id.includes(query) || records.includes(query);
      const matchesType = !typeFilter || ent.entity_type === typeFilter;

      let matchesStatus = true;
      if (statusFilter === "CANONICAL") matchesStatus = !ent.is_provisional;
      else if (statusFilter === "PROVISIONAL") matchesStatus = !!ent.is_provisional;
      else if (statusFilter === "MATCH") matchesStatus = !ent.is_provisional && (ent.member_record_ids || []).length > 1;
      else if (statusFilter === "REVIEW") matchesStatus = !!ent.is_provisional;

      return matchesQuery && matchesType && matchesStatus;
    });

    // Sort
    const sortVal = els.filterEntitySort ? els.filterEntitySort.value : "name_asc";
    list.sort((a, b) => {
      if (sortVal === "name_desc") {
        return (b.canonical_name || "").localeCompare(a.canonical_name || "");
      } else if (sortVal === "mentions_desc") {
        return (b.member_record_ids || []).length - (a.member_record_ids || []).length;
      } else if (sortVal === "mentions_asc") {
        return (a.member_record_ids || []).length - (b.member_record_ids || []).length;
      }
      return (a.canonical_name || "").localeCompare(b.canonical_name || "");
    });

    return list;
  }

  function renderEntitiesWorkspace() {
    const filtered = filterAndSortEntities();

    // Toggle Empty State
    if (filtered.length === 0) {
      if (els.entitiesGridViewContainer) els.entitiesGridViewContainer.style.display = "none";
      if (els.entitiesTableViewContainer) els.entitiesTableViewContainer.style.display = "none";
      if (els.entitiesPaginationRow) els.entitiesPaginationRow.style.display = "none";
      if (els.entitiesEmptyState) {
        els.entitiesEmptyState.style.display = "flex";
        const ill = els.entitiesEmptyState.querySelector(".empty-state-illustration");
        if (ill && window.SherlockStickers) {
          ill.innerHTML = window.SherlockStickers.renderEmptyStateIllustration("magnifying_glass");
        }
      }
      return;
    }

    if (els.entitiesEmptyState) els.entitiesEmptyState.style.display = "none";
    if (els.entitiesPaginationRow) els.entitiesPaginationRow.style.display = "flex";

    // Pagination calculations
    const pageSize = state.entitiesPageSize || 9;
    const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
    if (state.entitiesCurrentPage > totalPages) state.entitiesCurrentPage = totalPages;
    if (state.entitiesCurrentPage < 1) state.entitiesCurrentPage = 1;

    const startIndex = (state.entitiesCurrentPage - 1) * pageSize;
    const endIndex = Math.min(startIndex + pageSize, filtered.length);
    const pageItems = filtered.slice(startIndex, endIndex);

    // Update Pagination Summary & Buttons
    if (els.entitiesPaginationSummary) {
      els.entitiesPaginationSummary.textContent = `Showing ${startIndex + 1}–${endIndex} of ${filtered.length} entities`;
    }
    if (els.btnEntitiesPrevPage) els.btnEntitiesPrevPage.disabled = state.entitiesCurrentPage <= 1;
    if (els.btnEntitiesNextPage) els.btnEntitiesNextPage.disabled = state.entitiesCurrentPage >= totalPages;

    if (els.entitiesPagesList) {
      let pagePills = "";
      for (let p = 1; p <= totalPages; p++) {
        if (p === 1 || p === totalPages || (p >= state.entitiesCurrentPage - 1 && p <= state.entitiesCurrentPage + 1)) {
          pagePills += `<button class="pagination-page-btn ${p === state.entitiesCurrentPage ? "active" : ""}" onclick="window.sherlockApp.setEntitiesPage(${p})">${p}</button>`;
        } else if (p === state.entitiesCurrentPage - 2 || p === state.entitiesCurrentPage + 2) {
          pagePills += `<span class="pagination-ellipsis">…</span>`;
        }
      }
      els.entitiesPagesList.innerHTML = pagePills;
    }

    // Render View Mode
    if (state.entitiesViewMode === "grid") {
      if (els.entitiesGridViewContainer) {
        els.entitiesGridViewContainer.style.display = "grid";
        els.entitiesGridViewContainer.innerHTML = pageItems.map((ent) => renderEntityCardHtml(ent)).join("");
      }
      if (els.entitiesTableViewContainer) els.entitiesTableViewContainer.style.display = "none";
    } else {
      if (els.entitiesGridViewContainer) els.entitiesGridViewContainer.style.display = "none";
      if (els.entitiesTableViewContainer) {
        els.entitiesTableViewContainer.style.display = "block";
        if (els.tbodyEntities) {
          els.tbodyEntities.innerHTML = pageItems.map((ent) => renderEntityTableRowHtml(ent)).join("");
        }
      }
    }
  }

  function renderEntityCardHtml(ent) {
    const stickerHtml = window.SherlockStickers
      ? window.SherlockStickers.renderEntitySticker(ent.entity_id, ent.entity_type, { size: "md" })
      : "";

    const memberRecords = ent.member_record_ids || [];
    const memberCount = memberRecords.length;
    let statusClass = "status-pill-match";
    let statusText = "MATCH";
    if (ent.is_provisional) {
      statusClass = "status-pill-review";
      statusText = "REVIEW";
    } else if (memberCount <= 1) {
      statusClass = "status-pill-nonmatch";
      statusText = "CANONICAL";
    }

    const typeBadge = `<span class="badge-type-pill badge-type-${(ent.entity_type || "UNKNOWN").toLowerCase()}">${escapeHtml(ent.entity_type || "ENTITY")}</span>`;
    const shortId = formatShortId(ent.entity_id, 10, 6);
    const clusterId = ent.cluster_id || ent.entity_id;
    const shortClusterId = formatShortId(clusterId, 8, 4);

    const mentionsPillsHtml = memberCount > 0
      ? memberRecords.slice(0, 3).map((r) => `
          <span class="code-pill code-pill-xs" role="button" tabindex="0" title="${escapeHtml(r)}" aria-label="Copy mention ID ${escapeHtml(r)}" onclick="window.sherlockApp.copyText('${escapeHtml(r)}', 'Mention ID copied')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault(); window.sherlockApp.copyText('${escapeHtml(r)}', 'Mention ID copied');}">
            ${escapeHtml(formatShortId(r, 8, 4))}
          </span>
        `).join("") + (memberCount > 3 ? `<span class="code-pill code-pill-xs text-muted">+${memberCount - 3} more</span>` : "")
      : `<span class="snippet-empty text-muted">0 mentions recorded</span>`;

    return `
      <article class="entity-card-v2" data-entity-id="${escapeHtml(ent.entity_id)}">
        <div class="entity-card-v2-header">
          <div class="entity-sticker-blob">
            ${stickerHtml}
          </div>
          <div class="entity-header-meta">
            <div class="entity-top-row">
              ${typeBadge}
              <span class="status-pill-v2 ${statusClass}">${statusText}</span>
            </div>
            <h3 class="entity-canonical-name" title="${escapeHtml(ent.canonical_name || "Unnamed Entity")}">
              ${escapeHtml(ent.canonical_name || "Unnamed Entity")}
            </h3>
            <div class="entity-id-row">
              <span class="entity-id-micro" title="${escapeHtml(ent.entity_id)}" aria-label="Entity ID: ${escapeHtml(ent.entity_id)}">
                ID: <code class="entity-id-code">${escapeHtml(shortId)}</code>
              </span>
              <button type="button" class="btn-copy-id" title="Copy full ID: ${escapeHtml(ent.entity_id)}" aria-label="Copy full entity ID" onclick="event.stopPropagation(); window.sherlockApp.copyText('${escapeHtml(ent.entity_id)}', 'Entity ID copied')">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              </button>
            </div>
          </div>
        </div>

        <div class="entity-card-v2-body">
          <div class="entity-stat-chips-row">
            <span class="entity-stat-chip">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
              <strong>${memberCount}</strong> mention${memberCount === 1 ? "" : "s"}
            </span>
            <span class="entity-stat-chip" title="Cluster ID: ${escapeHtml(clusterId)}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
              Cluster: <code>${escapeHtml(shortClusterId)}</code>
            </span>
          </div>

          <div class="entity-mentions-snippet">
            <div class="snippet-label">Sample Mentions:</div>
            <div class="snippet-pills">
              ${mentionsPillsHtml}
            </div>
          </div>
        </div>

        <div class="entity-card-v2-footer">
          <button type="button" class="btn btn-secondary-subtle btn-sm" onclick="window.sherlockApp.focusEntityInGraph('${escapeHtml(ent.entity_id)}')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line></svg>
            Graph View
          </button>
          <button type="button" class="btn btn-peach-pill btn-sm" onclick="window.sherlockApp.inspectEntity('${escapeHtml(ent.entity_id)}')">
            Inspect Entity →
          </button>
        </div>
      </article>
    `;
  }

  function renderEntityTableRowHtml(ent) {
    const stickerHtml = window.SherlockStickers
      ? window.SherlockStickers.renderEntitySticker(ent.entity_id, ent.entity_type, { size: "sm" })
      : "";

    return `
      <tr>
        <td>
          <div class="entity-table-cell">
            ${stickerHtml}
            <span class="code-pill" title="${escapeHtml(ent.entity_id)}">${escapeHtml(ent.entity_id.slice(0, 14))}…</span>
          </div>
        </td>
        <td><strong class="text-plum">${escapeHtml(ent.canonical_name)}</strong></td>
        <td><span class="badge-type-pill badge-type-${(ent.entity_type || "UNKNOWN").toLowerCase()}">${escapeHtml(ent.entity_type)}</span></td>
        <td>
          <span class="status-pill-v2 ${ent.is_provisional ? "status-pill-review" : "status-pill-match"}">
            ${ent.is_provisional ? "REVIEW" : "CANONICAL"}
          </span>
        </td>
        <td>${(ent.member_record_ids || []).length} mentions</td>
        <td>
          <div class="table-actions-row">
            <button class="btn btn-secondary-subtle btn-xs" onclick="window.sherlockApp.focusEntityInGraph('${escapeHtml(ent.entity_id)}')">
              Graph
            </button>
            <button class="btn btn-peach-pill btn-xs" onclick="window.sherlockApp.inspectEntity('${escapeHtml(ent.entity_id)}')">
              Profile
            </button>
          </div>
        </td>
      </tr>
    `;
  }

  function setEntitiesPage(pageNum) {
    state.entitiesCurrentPage = pageNum;
    renderEntitiesWorkspace();
    const target = document.getElementById("tab-entities");
    if (target) target.scrollIntoView({ behavior: "smooth" });
  }

  async function inspectEntity(entityId) {
    if (!state.activeInvestigationId) return;

    try {
      const ent = await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/entities/${encodeURIComponent(
          entityId
        )}`
      );
      state.activeEntityProfile = ent;

      if (els.entityDetailAvatarWrap && window.SherlockStickers) {
        els.entityDetailAvatarWrap.innerHTML = window.SherlockStickers.renderEntitySticker(
          ent.entity_id,
          ent.entity_type,
          { size: "xl" }
        );
      }

      if (els.entityDetailName) els.entityDetailName.textContent = ent.canonical_name;
      if (els.entityDetailId) {
        els.entityDetailId.innerHTML = `ID: <code class="entity-id-code" style="word-break: break-all;">${escapeHtml(ent.entity_id)}</code> <button type="button" class="btn-copy-id" style="margin-left: 4px;" title="Copy full ID" aria-label="Copy full entity ID" onclick="window.sherlockApp.copyText('${escapeHtml(ent.entity_id)}', 'Entity ID copied')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button>`;
      }
      if (els.entityDetailBadge) {
        els.entityDetailBadge.textContent = `${ent.entity_type} • ${ent.is_provisional ? "PROVISIONAL / REVIEW" : "CANONICAL"}`;
      }

      // Build profile sections
      const memberRecords = ent.member_record_ids || [];
      if (els.entityDetailBody) {
        els.entityDetailBody.innerHTML = `
          <div class="profile-section-card">
            <div class="profile-section-heading">Source Mentions & Member Records (${memberRecords.length})</div>
            <div class="profile-badge-row">
              ${
                memberRecords.length > 0
                  ? memberRecords.map((m) => `<span class="code-pill code-pill-copyable" title="Click to copy" onclick="navigator.clipboard && navigator.clipboard.writeText('${escapeHtml(m)}'); window.sherlockApp.showToast('Copied mention ID', 'info');">${escapeHtml(m)}</span>`).join("")
                  : '<span class="text-muted">No member records recorded.</span>'
              }
            </div>
          </div>

          <div class="profile-section-card">
            <div class="profile-section-heading">Cluster Properties & Epistemic Grounding</div>
            <div class="key-value-list">
              <div class="kv-item">
                <span class="kv-key">Cluster ID:</span>
                <span class="code-pill">${escapeHtml(ent.cluster_id || ent.entity_id)}</span>
              </div>
              <div class="kv-item">
                <span class="kv-key">Resolution Status:</span>
                <span class="kv-val text-plum">${ent.is_provisional ? "Held for human review (Provisional)" : "Canonical Verified Identity"}</span>
              </div>
              <div class="kv-item">
                <span class="kv-key">Entity Class:</span>
                <span class="kv-val">${escapeHtml(ent.entity_type || "UNKNOWN")}</span>
              </div>
            </div>
          </div>
        `;
      }

      // Show Slide-out Drawer & Backdrop
      if (els.entityDetailPanel) {
        els.entityDetailPanel.style.display = "block";
        els.entityDetailPanel.classList.add("open");
      }
      if (els.entityDrawerBackdrop) {
        els.entityDrawerBackdrop.classList.add("open");
      }
    } catch (err) {
      console.error("Entity inspect failed:", err);
    }
  }

  function closeEntityDrawer() {
    if (els.entityDetailPanel) {
      els.entityDetailPanel.classList.remove("open");
      els.entityDetailPanel.style.display = "none";
    }
    if (els.entityDrawerBackdrop) {
      els.entityDrawerBackdrop.classList.remove("open");
    }
    state.activeEntityProfile = null;
  }

  function focusEntityInGraph(entityId) {
    switchTab("tab-graph");
    if (els.graphRootSelect) {
      els.graphRootSelect.value = entityId;
    }
    loadGraph();
  }

  function handleOpenSplitModal() {
    if (!state.activeEntityProfile) return;
    const ent = state.activeEntityProfile;
    const records = ent.member_record_ids || [];

    if (records.length < 2) {
      showToast("Cannot split an entity with fewer than 2 member records.", "error");
      return;
    }

    els.splitTargetEntityId.value = ent.entity_id;
    els.splitModalInfo.innerHTML = `<strong>Splitting Entity:</strong> ${escapeHtml(
      ent.canonical_name
    )} (ID: ${escapeHtml(ent.entity_id)})`;

    els.splitRecordsChecklist.innerHTML = records
      .map(
        (rec, i) => `
        <label class="toggle-pill-label">
          <input type="checkbox" name="split_record" value="${escapeHtml(rec)}" ${i === 0 ? "checked" : ""}>
          <span class="toggle-pill-text code-pill">${escapeHtml(rec)}</span>
        </label>
      `
      )
      .join("");

    openModal(els.modalSplitEntity);
  }

  async function handleCommitSplitEntity(e) {
    e.preventDefault();
    if (!state.activeInvestigationId) return;

    const entId = els.splitTargetEntityId.value;
    const reviewer = els.inputSplitReviewer.value.trim();
    const rationale = els.inputSplitRationale.value.trim();

    const selectedRecs = Array.from(
      document.querySelectorAll('input[name="split_record"]:checked')
    ).map((cb) => cb.value);

    if (selectedRecs.length === 0) {
      showToast("Select at least one record to split off.", "error");
      return;
    }

    try {
      await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/entities/split`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_id: entId,
            split_member_records: selectedRecs,
            reviewer: reviewer,
            rationale: rationale,
          }),
        }
      );

      showToast("Entity successfully split into two distinct identities!", "success");
      closeModal(els.modalSplitEntity);
      els.formSplitEntity.reset();
      closeEntityDrawer();
      loadEntities();
    } catch (_) {}
  }

  // =========================================================================
  // Screen 6: Interactive Relationship Graph Workspace
  // =========================================================================

  async function loadGraph() {
    if (!state.activeInvestigationId) return;

    const rootId = els.graphRootSelect ? els.graphRootSelect.value : "";
    const maxDepth = parseInt(els.graphDepthInput ? els.graphDepthInput.value : "2", 10) || 2;
    const maxNodes = parseInt(els.graphNodesInput ? els.graphNodesInput.value : "50", 10) || 50;

    const url = rootId
      ? `/api/v1/investigations/${encodeURIComponent(
          state.activeInvestigationId
        )}/graph/query?start_entity_id=${encodeURIComponent(
          rootId
        )}&max_depth=${maxDepth}&max_nodes=${maxNodes}`
      : `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/graph`;

    try {
      const data = await apiFetch(url);
      state.graphData = {
        nodes: data.nodes || [],
        links: data.edges || [],
      };

      // Populate Root Select Options
      if (els.graphRootSelect && els.graphRootSelect.options.length <= 1 && state.entities.length > 0) {
        state.entities.forEach((ent) => {
          const opt = document.createElement("option");
          opt.value = ent.entity_id;
          opt.textContent = `${ent.canonical_name} (${ent.entity_type})`;
          els.graphRootSelect.appendChild(opt);
        });
      }

      // Update workspace header stats badge
      if (els.graphStatsBadge) {
        els.graphStatsBadge.textContent = `${state.graphData.nodes.length} Nodes • ${state.graphData.links.length} Edges`;
      }

      renderSvgGraph();
      renderGraphEdgesTable();
    } catch (err) {
      console.error("Graph load failed:", err);
    }
  }

  function updateGraphTransform() {
    const root = document.getElementById("graph-viewport-group");
    if (root) {
      root.setAttribute(
        "transform",
        `translate(${state.graphZoom.x}, ${state.graphZoom.y}) scale(${state.graphZoom.k})`
      );
    }
  }

  function fitGraphToView() {
    state.graphZoom = { k: 1, x: 0, y: 0 };
    updateGraphTransform();
  }

  function toggleGraphFullscreen() {
    const panel = els.graphWorkspacePanel || document.getElementById("tab-graph");
    if (!panel) return;

    if (!document.fullscreenElement) {
      if (panel.requestFullscreen) {
        panel.requestFullscreen();
      } else if (panel.webkitRequestFullscreen) {
        panel.webkitRequestFullscreen();
      }
      panel.classList.add("is-fullscreen");
      if (els.btnFullscreenGraph) els.btnFullscreenGraph.textContent = "Exit Fullscreen";
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      }
      panel.classList.remove("is-fullscreen");
      if (els.btnFullscreenGraph) els.btnFullscreenGraph.textContent = "Fullscreen View";
    }
  }

  function renderSvgGraph() {
    const svg = els.graphSvg;
    if (!svg) return;
    const { nodes: rawNodes, links: rawLinks } = state.graphData;

    // Filter links by edge type & status
    const edgeTypeFilter = els.graphFilterEdgeType ? els.graphFilterEdgeType.value : "";
    const statusFilter = els.graphFilterStatus ? els.graphFilterStatus.value : "";

    const links = rawLinks.filter((l) => {
      const matchesType = !edgeTypeFilter || l.relationship_type === edgeTypeFilter;
      let matchesStatus = true;
      if (statusFilter === "ASSERTED") matchesStatus = l.epistemic_tier === "ASSERTED";
      else if (statusFilter === "INFERRED") matchesStatus = l.epistemic_tier === "INFERRED";
      else if (statusFilter === "DISPUTED") matchesStatus = l.review_status === "DISPUTED" || l.epistemic_tier === "DISPUTED";
      else if (statusFilter === "RETRACTED") matchesStatus = l.review_status === "RETRACTED" || l.review_status === "REJECTED" || l.review_status === "SUPERSEDED";
      return matchesType && matchesStatus;
    });

    const activeNodeIds = new Set();
    if (edgeTypeFilter || statusFilter) {
      links.forEach((l) => {
        activeNodeIds.add(l.source_entity_id || l.source);
        activeNodeIds.add(l.target_entity_id || l.target);
      });
    }
    const nodes = (edgeTypeFilter || statusFilter) && activeNodeIds.size > 0
      ? rawNodes.filter((n) => activeNodeIds.has(n.id))
      : rawNodes;

    svg.innerHTML = "";

    if (nodes.length === 0) {
      if (els.graphEmptyState) {
        els.graphEmptyState.style.display = "flex";
        const ill = els.graphEmptyState.querySelector(".empty-state-illustration");
        if (ill && window.SherlockStickers) {
          ill.innerHTML = window.SherlockStickers.renderEmptyStateIllustration("magnifying_glass");
        }
      }
      return;
    }
    if (els.graphEmptyState) els.graphEmptyState.style.display = "none";

    const width = svg.clientWidth || 900;
    const height = svg.clientHeight || 580;
    const centerX = width / 2;
    const centerY = height / 2;

    // 1. Build Adjacency and Degree Maps
    const adj = new Map();
    const degree = new Map();
    nodes.forEach((n) => {
      adj.set(n.id, new Set());
      degree.set(n.id, 0);
    });

    links.forEach((l) => {
      const sId = l.source_entity_id || l.source;
      const tId = l.target_entity_id || l.target;
      if (adj.has(sId) && adj.has(tId)) {
        adj.get(sId).add(tId);
        adj.get(tId).add(sId);
        degree.set(sId, (degree.get(sId) || 0) + 1);
        degree.set(tId, (degree.get(tId) || 0) + 1);
      }
    });

    // 2. Partition into Connected Components & Isolated Nodes
    const visited = new Set();
    const components = [];
    const isolatedNodes = [];

    nodes.forEach((node) => {
      if (visited.has(node.id)) return;
      if ((degree.get(node.id) || 0) === 0) {
        visited.add(node.id);
        isolatedNodes.push(node);
        return;
      }

      const component = [];
      const queue = [node.id];
      visited.add(node.id);

      while (queue.length > 0) {
        const currId = queue.shift();
        const currNode = nodes.find((n) => n.id === currId);
        if (currNode) component.push(currNode);

        for (const neighborId of adj.get(currId) || []) {
          if (!visited.has(neighborId)) {
            visited.add(neighborId);
            queue.push(neighborId);
          }
        }
      }

      if (component.length > 0) {
        components.push(component);
      }
    });

    // 3. Layout calculation
    const rootId = els.graphRootSelect ? els.graphRootSelect.value : "";
    const nodeMap = new Map();
    const availWidth = width;
    const availHeight = isolatedNodes.length > 0 ? height - 120 : height;

    if (rootId && nodes.some((n) => n.id === rootId)) {
      const rootNode = nodes.find((n) => n.id === rootId);
      const centerY = availHeight / 2;
      nodeMap.set(rootId, { ...rootNode, x: centerX, y: centerY, hop: 0 });
      const distances = new Map([[rootId, 0]]);
      const queue = [rootId];
      while (queue.length) {
        const currentId = queue.shift();
        const nextDistance = distances.get(currentId) + 1;
        for (const neighborId of adj.get(currentId) || []) {
          if (!distances.has(neighborId)) {
            distances.set(neighborId, nextDistance);
            queue.push(neighborId);
          }
        }
      }
      const layers = new Map();
      for (const node of nodes) {
        if (node.id === rootId) continue;
        const layer = distances.get(node.id) || 1;
        if (!layers.has(layer)) layers.set(layer, []);
        layers.get(layer).push(node);
      }
      const maxLayer = Math.max(1, ...layers.keys());
      for (const [layer, layerNodes] of layers) {
        const radius = Math.min(availWidth * 0.45, availHeight * 0.44) * (layer / maxLayer);
        layerNodes.forEach((node, idx) => {
          const angle = (idx / Math.max(1, layerNodes.length)) * 2 * Math.PI - Math.PI / 2;
          nodeMap.set(node.id, {
            ...node,
            x: centerX + radius * Math.cos(angle),
            y: centerY + radius * Math.sin(angle),
            hop: layer,
          });
        });
      }
    } else {
      components.sort((a, b) => b.length - a.length);

      if (components.length === 1) {
        const comp = components[0];
        const r = Math.min(availWidth, availHeight) * 0.32;
        comp.forEach((n, idx) => {
          const angle = (idx / Math.max(1, comp.length)) * 2 * Math.PI - Math.PI / 2;
          nodeMap.set(n.id, {
            ...n,
            x: centerX + r * Math.cos(angle),
            y: (availHeight / 2) + r * Math.sin(angle),
          });
        });
      } else if (components.length > 1) {
        const cols = Math.min(components.length, Math.ceil(Math.sqrt(components.length * 1.5)));
        const rows = Math.ceil(components.length / cols);
        const cellW = availWidth / cols;
        const cellH = availHeight / rows;

        components.forEach((comp, cIdx) => {
          const cCol = cIdx % cols;
          const cRow = Math.floor(cIdx / cols);
          const cX = (cCol + 0.5) * cellW;
          const cY = (cRow + 0.5) * cellH;
          const compRadius = Math.min(cellW * 0.35, cellH * 0.35, Math.max(65, comp.length * 35));

          comp.forEach((n, idx) => {
            const angle = (idx / Math.max(1, comp.length)) * 2 * Math.PI - Math.PI / 2;
            nodeMap.set(n.id, {
              ...n,
              x: cX + compRadius * Math.cos(angle),
              y: cY + compRadius * Math.sin(angle),
            });
          });
        });
      }
    }

    // Isolated Nodes Rack at bottom
    if (isolatedNodes.length > 0) {
      const rackY = height - 55;
      const spacing = Math.min(95, (availWidth - 120) / Math.max(1, isolatedNodes.length));
      const startX = centerX - ((isolatedNodes.length - 1) * spacing) / 2;

      isolatedNodes.forEach((n, idx) => {
        nodeMap.set(n.id, {
          ...n,
          x: Math.max(60, Math.min(width - 60, startX + idx * spacing)),
          y: rackY,
          isIsolated: true,
        });
      });
    }

    // Force collision avoidance (repel if dist < 85px)
    const nodeList = Array.from(nodeMap.values());
    const minDistance = 85;
    for (let iter = 0; iter < 40; iter++) {
      for (let i = 0; i < nodeList.length; i++) {
        for (let j = i + 1; j < nodeList.length; j++) {
          const a = nodeList[i];
          const b = nodeList[j];
          if (a.isIsolated && b.isIsolated) continue;

          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;

          if (dist < minDistance) {
            const overlap = (minDistance - dist) / 2;
            const nx = dx / dist;
            const ny = dy / dist;

            if (!a.isIsolated) {
              a.x -= nx * overlap * 0.5;
              a.y -= ny * overlap * 0.5;
            }
            if (!b.isIsolated) {
              b.x += nx * overlap * 0.5;
              b.y += ny * overlap * 0.5;
            }
          }
        }
      }
    }

    // SVG Defs: arrow markers & circular clip path
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML = `
      <marker id="graph-edge-arrow" viewBox="0 0 10 10" refX="28" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#191629"/>
      </marker>
      <marker id="graph-edge-arrow-disputed" viewBox="0 0 10 10" refX="28" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#E89D42"/>
      </marker>
      <marker id="graph-edge-arrow-retracted" viewBox="0 0 10 10" refX="28" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#DE5B5B"/>
      </marker>
      <clipPath id="graph-node-clip">
        <circle cx="0" cy="0" r="19"/>
      </clipPath>
      <filter id="node-shadow" x="-30%" y="-30%" width="160%" height="160%">
        <feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#191629" flood-opacity="0.12"/>
      </filter>
    `;
    svg.appendChild(defs);

    // Root viewport group for Pan & Zoom transforms
    const viewportGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
    viewportGroup.id = "graph-viewport-group";
    viewportGroup.setAttribute(
      "transform",
      `translate(${state.graphZoom.x}, ${state.graphZoom.y}) scale(${state.graphZoom.k})`
    );
    svg.appendChild(viewportGroup);

    // Draw Isolated Rack Boundary if isolated nodes exist
    if (isolatedNodes.length > 0) {
      const rackG = document.createElementNS("http://www.w3.org/2000/svg", "g");
      rackG.classList.add("isolated-rack-group");
      rackG.innerHTML = `
        <rect x="20" y="${height - 105}" width="${width - 40}" height="95" rx="16" fill="#FBF8F3" stroke="#E4DCD2" stroke-dasharray="6,4" stroke-width="1.5"/>
        <text x="36" y="${height - 85}" font-size="11" font-weight="700" fill="#666477">UNLINKED / DISCONNECTED ENTITIES (${isolatedNodes.length})</text>
      `;
      viewportGroup.appendChild(rackG);
    }

    // Set of directed pairs to detect bidirectional edges
    const pairCountMap = new Map();
    links.forEach((l) => {
      const s = l.source_entity_id || l.source;
      const t = l.target_entity_id || l.target;
      const key = [s, t].sort().join("::");
      pairCountMap.set(key, (pairCountMap.get(key) || 0) + 1);
    });

    // Draw Links
    const linksGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
    linksGroup.classList.add("graph-links-group");
    links.forEach((link) => {
      const src = nodeMap.get(link.source_entity_id || link.source);
      const tgt = nodeMap.get(link.target_entity_id || link.target);
      if (!src || !tgt) return;

      const gLink = document.createElementNS("http://www.w3.org/2000/svg", "g");
      gLink.classList.add("graph-link-item");

      const sId = link.source_entity_id || link.source;
      const tId = link.target_entity_id || link.target;
      const pairKey = [sId, tId].sort().join("::");
      const isBidirectional = (pairCountMap.get(pairKey) || 0) > 1;

      let strokeColor = "#191629";
      let markerId = "url(#graph-edge-arrow)";
      let dashArray = "";
      if (link.epistemic_tier === "DISPUTED") {
        strokeColor = "#E89D42";
        markerId = "url(#graph-edge-arrow-disputed)";
        dashArray = "6,4";
      } else if (link.epistemic_tier === "RETRACTED") {
        strokeColor = "#DE5B5B";
        markerId = "url(#graph-edge-arrow-retracted)";
        dashArray = "3,3";
      } else if (link.epistemic_tier === "INFERRED") {
        strokeColor = "#7A6EA6";
        dashArray = "4,2";
      }

      let edgePathD = "";
      let midX = (src.x + tgt.x) / 2;
      let midY = (src.y + tgt.y) / 2;

      if (isBidirectional) {
        // Curve bidirectional edges
        const dx = tgt.x - src.x;
        const dy = tgt.y - src.y;
        const norm = Math.sqrt(dx * dx + dy * dy) || 1;
        const offset = 22;
        const perpX = -dy / norm;
        const perpY = dx / norm;
        const ctrlX = midX + perpX * offset;
        const ctrlY = midY + perpY * offset;
        edgePathD = `M ${src.x} ${src.y} Q ${ctrlX} ${ctrlY} ${tgt.x} ${tgt.y}`;
        midX = ctrlX;
        midY = ctrlY;
      } else {
        edgePathD = `M ${src.x} ${src.y} L ${tgt.x} ${tgt.y}`;
      }

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", edgePathD);
      path.setAttribute("stroke", strokeColor);
      path.setAttribute("stroke-width", "2");
      path.setAttribute("fill", "none");
      path.setAttribute("stroke-opacity", "0.85");
      if (dashArray) path.setAttribute("stroke-dasharray", dashArray);
      path.setAttribute("marker-end", markerId);
      path.classList.add("graph-link");
      gLink.appendChild(path);

      // Edge Label Pill beside edge
      const labelText = (link.relationship_type || "RELATED_TO").replace(/_/g, " ");
      const gLabel = document.createElementNS("http://www.w3.org/2000/svg", "g");
      gLabel.setAttribute("transform", `translate(${midX}, ${midY - 7})`);
      gLabel.classList.add("graph-edge-label-pill");

      const pillWidth = Math.min(170, Math.max(64, labelText.length * 6.2 + 16));
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", -pillWidth / 2);
      rect.setAttribute("y", -9);
      rect.setAttribute("width", pillWidth);
      rect.setAttribute("height", 18);
      rect.setAttribute("rx", 9);
      rect.setAttribute("fill", "#FFFDF9");
      rect.setAttribute("stroke", strokeColor);
      rect.setAttribute("stroke-width", "1");
      gLabel.appendChild(rect);

      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("y", 3.5);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("font-size", "9");
      text.setAttribute("pointer-events", "none");
      text.textContent = labelText.length > 24 ? `${labelText.slice(0, 21)}...` : labelText;
      text.setAttribute("font-weight", "600");
      text.setAttribute("fill", strokeColor);
      gLabel.appendChild(text);

      gLink.appendChild(gLabel);
      gLink.addEventListener("click", () => showEdgeInspection(link));
      linksGroup.appendChild(gLink);
    });
    viewportGroup.appendChild(linksGroup);

    // Draw Nodes
    const nodesGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
    nodesGroup.classList.add("graph-nodes-group");
    nodeMap.forEach((node) => {
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("transform", `translate(${node.x}, ${node.y})`);
      g.classList.add("graph-node");
      g.setAttribute("filter", "url(#node-shadow)");

      // Color ring based on type
      let borderColor = "#191629";
      const nType = (node.entity_type || node.type || "").toUpperCase();
      if (nType === "PERSON") borderColor = "#F5AE89";
      else if (nType === "ORGANIZATION") borderColor = "#7A6EA6";
      else if (nType === "LOCATION") borderColor = "#489B78";

      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("r", "22");
      circle.setAttribute("fill", "#FFFDF9");
      circle.setAttribute("stroke", borderColor);
      circle.setAttribute("stroke-width", node.is_provisional ? "3" : "2.5");
      if (node.is_provisional) circle.setAttribute("stroke-dasharray", "4,2");
      g.appendChild(circle);

      // Deterministic Entity Sticker Avatar
      const sticker = window.SherlockStickers
        ? window.SherlockStickers.getStickerForEntity(node.id, node.entity_type || node.type)
        : null;

      if (sticker && sticker.path) {
        const img = document.createElementNS("http://www.w3.org/2000/svg", "image");
        img.setAttribute("href", sticker.path);
        img.setAttribute("x", "-19");
        img.setAttribute("y", "-19");
        img.setAttribute("width", "38");
        img.setAttribute("height", "38");
        img.setAttribute("clip-path", "url(#graph-node-clip)");
        g.appendChild(img);
      }

      // Name Label
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("y", "36");
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("font-size", "11");
      label.setAttribute("font-weight", "700");
      label.setAttribute("fill", "#191629");
      label.classList.add("graph-label");
      label.textContent = (node.label || entityDisplayName(node.id)).slice(0, 24);
      label.setAttribute("title", `${node.label || entityDisplayName(node.id)} (${node.id})`);
      g.appendChild(label);

      // Subtype label
      const subLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
      subLabel.setAttribute("y", "48");
      subLabel.setAttribute("text-anchor", "middle");
      subLabel.setAttribute("font-size", "9");
      subLabel.setAttribute("font-weight", "500");
      subLabel.setAttribute("fill", "#716B82");
      subLabel.textContent = (node.entity_type || node.type || "ENTITY").toUpperCase();
      g.appendChild(subLabel);

      g.addEventListener("click", () => showNodeInspection(node));
      nodesGroup.appendChild(g);
    });
    viewportGroup.appendChild(nodesGroup);

    // Pan & Drag interactions on SVG
    let isDragging = false;
    let startPoint = { x: 0, y: 0 };

    svg.onmousedown = (e) => {
      if (e.target.closest && (e.target.closest(".graph-node") || e.target.closest(".graph-link-item"))) {
        return;
      }
      isDragging = true;
      startPoint = { x: e.clientX - state.graphZoom.x, y: e.clientY - state.graphZoom.y };
      svg.style.cursor = "grabbing";
    };

    svg.onmousemove = (e) => {
      if (!isDragging) return;
      state.graphZoom.x = e.clientX - startPoint.x;
      state.graphZoom.y = e.clientY - startPoint.y;
      persistPreference("graphZoom", state.graphZoom);
      updateGraphTransform();
    };

    svg.onmouseup = () => {
      isDragging = false;
      svg.style.cursor = "default";
    };

    svg.onmouseleave = () => {
      isDragging = false;
      svg.style.cursor = "default";
    };

    svg.onwheel = (e) => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
      state.graphZoom.k = Math.max(0.3, Math.min(3.5, state.graphZoom.k * zoomFactor));
      persistPreference("graphZoom", state.graphZoom);
      updateGraphTransform();
    };
  }

  function showNodeInspection(node) {
    if (els.inspectorTitle) els.inspectorTitle.textContent = `Entity: ${node.label || node.id}`;
    const nType = node.entity_type || node.type || "UNKNOWN";
    const stickerHtml = window.SherlockStickers
      ? window.SherlockStickers.renderEntitySticker(node.id, nType, { size: "lg" })
      : "";

    // Count links
    const connectionCount = state.graphData.links.filter(
      (l) => (l.source_entity_id || l.source) === node.id || (l.target_entity_id || l.target) === node.id
    ).length;

    if (els.inspectorContent) {
      els.inspectorContent.innerHTML = `
        <div style="text-align: center; margin-bottom: 12px;">
          ${stickerHtml}
        </div>
        <div class="key-value-list">
          <div class="kv-item">
            <span class="kv-key">Node ID:</span>
            <span class="code-pill">${escapeHtml(node.id)}</span>
          </div>
          <div class="kv-item">
            <span class="kv-key">Entity Class:</span>
            <span class="badge-type-pill badge-type-${nType.toLowerCase()}">${escapeHtml(nType)}</span>
          </div>
          <div class="kv-item">
            <span class="kv-key">Status:</span>
            <span class="status-pill-v2 ${node.is_provisional ? "status-pill-review" : "status-pill-match"}">${node.is_provisional ? "Provisional" : "Canonical"}</span>
          </div>
          <div class="kv-item">
            <span class="kv-key">Connections:</span>
            <span class="kv-val font-semibold">${connectionCount} visible relationships</span>
          </div>
        </div>
        <div style="display: flex; gap: 8px; margin-top: 12px; flex-direction: column;">
          <button class="btn btn-peach-pill btn-sm w-full" onclick="window.sherlockApp.inspectEntity('${escapeHtml(node.id)}')">
            Open Entity Profile →
          </button>
          <button class="btn btn-secondary-subtle btn-sm w-full" onclick="if (els.graphRootSelect) { els.graphRootSelect.value = '${escapeHtml(node.id)}'; loadGraph(); }">
            Center Graph on this Node
          </button>
        </div>
      `;
    }
    if (els.graphInspector) els.graphInspector.style.display = "flex";
  }

  function showEdgeInspection(edge) {
    if (els.inspectorTitle) els.inspectorTitle.textContent = `Relation: ${edge.relationship_type}`;
    if (els.inspectorContent) {
      els.inspectorContent.innerHTML = `
        <div class="key-value-list">
          <div class="kv-item">
            <span class="kv-key">Source:</span>
            <span class="graph-inspector-entity-name">${escapeHtml(edge.source_label || entityDisplayName(edge.source_entity_id || edge.source))}</span>
            <span class="code-pill" title="Entity ID">${escapeHtml(edge.source_entity_id || edge.source)}</span>
          </div>
          <div class="kv-item">
            <span class="kv-key">Type:</span>
            <strong class="text-plum">${escapeHtml(edge.relationship_type)}</strong>
          </div>
          <div class="kv-item">
            <span class="kv-key">Target:</span>
            <span class="graph-inspector-entity-name">${escapeHtml(edge.target_label || entityDisplayName(edge.target_entity_id || edge.target))}</span>
            <span class="code-pill" title="Entity ID">${escapeHtml(edge.target_entity_id || edge.target)}</span>
          </div>
          <div class="kv-item">
            <span class="kv-key">Epistemic Tier:</span>
            <span class="status-pill ${
              edge.epistemic_tier === "DISPUTED"
                ? "status-pill-warning"
                : edge.epistemic_tier === "RETRACTED"
                ? "status-pill-danger"
                : "status-pill-success"
            }">
              ${escapeHtml(edge.epistemic_tier || "ASSERTED")}
            </span>
          </div>
          <div class="kv-item">
            <span class="kv-key">Review Status:</span>
            <span class="kv-val text-plum">${escapeHtml(edge.review_status || "UNREVIEWED")}</span>
          </div>
        </div>
        <div class="graph-evidence-detail">
          <strong>Supporting evidence (${(edge.supporting_evidence || []).length})</strong>
          ${(edge.supporting_evidence || []).map((item) => `<blockquote>${escapeHtml(item.text || "Stored evidence text unavailable")}<small>${escapeHtml(item.document_id || "Source not recorded")} · ${escapeHtml(item.evidence_id)}</small></blockquote>`).join("") || '<p class="text-muted">No supporting evidence is attached.</p>'}
          <strong>Contradicting evidence (${(edge.contradicting_evidence || []).length})</strong>
          ${(edge.contradicting_evidence || []).map((item) => `<blockquote>${escapeHtml(item.text || "Stored evidence text unavailable")}<small>${escapeHtml(item.document_id || "Source not recorded")} · ${escapeHtml(item.evidence_id)}</small></blockquote>`).join("") || '<p class="text-muted">No contradicting evidence is attached.</p>'}
          <div class="text-muted">Claim references: ${[...(edge.supporting_claim_ids || []), ...(edge.contradicting_claim_ids || [])].map(escapeHtml).join(", ") || "None"}</div>
        </div>
        ${
          edge.contradicting_claim_ids && edge.contradicting_claim_ids.length > 0
            ? `<div class="warning-callout-pill" style="margin-top: 10px;">⚠️ Contradicting Claims Attached: ${edge.contradicting_claim_ids.length}</div>`
            : ""
        }
      `;
    }
    if (els.graphInspector) els.graphInspector.style.display = "flex";
  }

  function renderGraphEdgesTable() {
    const edges = state.graphData.links;
    if (!els.tbodyGraphEdges) return;

    if (edges.length === 0) {
      els.tbodyGraphEdges.innerHTML =
        '<tr><td colspan="8" class="text-center text-muted">No edges in current graph scope.</td></tr>';
      return;
    }

    els.tbodyGraphEdges.innerHTML = edges
      .map(
        (e) => `
        <tr>
          <td><span class="code-pill">${escapeHtml((e.relationship_id || "").slice(0, 16))}</span></td>
          <td><strong>${escapeHtml(e.source_label || entityDisplayName(e.source_entity_id || e.source))}</strong><br><code title="Entity ID">${escapeHtml(e.source_entity_id || e.source)}</code></td>
          <td><strong>${escapeHtml(e.relationship_type)}</strong></td>
          <td><strong>${escapeHtml(e.target_label || entityDisplayName(e.target_entity_id || e.target))}</strong><br><code title="Entity ID">${escapeHtml(e.target_entity_id || e.target)}</code></td>
          <td><span class="status-pill status-pill-neutral">${escapeHtml(e.epistemic_tier)}</span></td>
          <td><span class="status-pill ${getStatusBadgeClass(e.review_status)}">${escapeHtml(
          e.review_status
        )}</span></td>
          <td>${(e.supporting_claim_ids || []).length}</td>
          <td>${(e.contradicting_claim_ids || []).length}</td>
        </tr>
      `
      )
      .join("");
  }

  // =========================================================================
  // Screen 7: Claims & Evidence Workspace
  // =========================================================================

  async function loadClaimsAndEvidence() {
    if (!state.activeInvestigationId) return;

    try {
      const [claimsData, evData] = await Promise.all([
        apiFetch(`/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/claims`),
        apiFetch(`/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/evidence`),
      ]);

      state.claims = claimsData.claims || [];
      state.evidence = evData.evidence || evData.evidence_items || [];
      if (els.navCountClaims) els.navCountClaims.textContent = state.claims.length;

      // Update Screen 7 Summary Metrics
      const docsCount = new Set(state.evidence.map((ev) => ev.document_id || ev.source_uri).filter(Boolean)).size || state.documents.length || 1;
      const spansCount = state.evidence.length;
      const claimsCount = state.claims.length;
      const disputesCount = state.claims.filter(
        (c) => c.review_status === "DISPUTED" || (c.qualifiers && c.qualifiers.is_allegation)
      ).length + state.evidence.filter((ev) => ev.polarity === "NEGATIVE" || ev.polarity === "CONTRADICTING").length;

      if (els.evidenceTotalBadge) {
        els.evidenceTotalBadge.textContent = `${spansCount} Spans • ${claimsCount} Claims`;
      }
      if (els.evMetricDocs) els.evMetricDocs.textContent = docsCount;
      if (els.evMetricSpans) els.evMetricSpans.textContent = spansCount;
      if (els.evMetricClaims) els.evMetricClaims.textContent = claimsCount;
      if (els.evMetricDisputes) els.evMetricDisputes.textContent = disputesCount;

      // Populate document filter dropdown
      if (els.filterEvidenceDoc && els.filterEvidenceDoc.options.length <= 1) {
        const uniqueDocs = Array.from(new Set(state.evidence.map((ev) => ev.document_id || (ev.source_uri || "internal").split("/").pop()).filter(Boolean)));
        uniqueDocs.forEach((doc) => {
          const opt = document.createElement("option");
          opt.value = doc;
          opt.textContent = doc;
          els.filterEvidenceDoc.appendChild(opt);
        });
      }

      renderEvidenceTimeline();
      renderEvidenceExplorer();
    } catch (err) {
      console.error("Claims load failed:", err);
    }
  }

  function renderEvidenceTimeline() {
    if (!els.evidenceTimelineTrack) return;

    if (state.evidence.length === 0) {
      els.evidenceTimelineTrack.innerHTML = `
        <div class="evidence-timeline-empty-card">
          <p class="text-muted">No evidence timestamps grounded yet. Upload and process documents to build timeline track.</p>
        </div>
      `;
      return;
    }

    // Render up to 4-6 prominent timeline cards matching the reference image layout
    const timelineItems = state.evidence.slice(0, 6);
    els.evidenceTimelineTrack.innerHTML = timelineItems
      .map((ev, idx) => {
        const docName = ev.document_id || (ev.source_uri || "document_alpha.pdf").split("/").pop();
        const isNeg = ev.polarity === "NEGATIVE" || ev.polarity === "CONTRADICTING";
        const statusClass = isNeg ? "status-pill-review" : "status-pill-match";
        const statusLabel = isNeg ? (ev.polarity || "NEGATIVE") : (ev.polarity || "POSITIVE");
        const spanText = ev.text_span || ev.content || "";

        const stickerHtml = window.SherlockStickers
          ? window.SherlockStickers.renderEntitySticker(ev.evidence_id, "EVIDENCE", { size: "xs" })
          : "";

        return `
          <div class="timeline-step-card" data-evidence-id="${escapeHtml(ev.evidence_id)}">
            <div class="timeline-card-header">
              <div class="timeline-cat-avatar">
                ${stickerHtml}
              </div>
              <div class="timeline-time-info">
                <span class="timeline-step-tag">Step 0${idx + 1} • [${ev.start_char ?? 0}:${ev.end_char ?? 0}]</span>
                <span class="status-pill-v2 ${statusClass}">${statusLabel}</span>
              </div>
            </div>

            <div class="timeline-card-body">
              <blockquote class="timeline-quote-text" title="${escapeHtml(spanText)}">
                “${escapeHtml(spanText)}”
              </blockquote>
            </div>

            <div class="timeline-card-footer">
              <span class="timeline-doc-pill" title="${escapeHtml(docName)}">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                ${escapeHtml(docName.slice(0, 16))}
              </span>
              <button class="btn btn-secondary-subtle btn-xs" onclick="window.sherlockApp.openEvidenceDrawer('${escapeHtml(ev.evidence_id)}')">
                Inspect
              </button>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function filterEvidenceItems() {
    const query = (els.filterEvidenceQuery ? els.filterEvidenceQuery.value : "").toLowerCase().trim();
    const polarity = els.filterEvidencePolarity ? els.filterEvidencePolarity.value : "";
    const status = els.filterEvidenceStatus ? els.filterEvidenceStatus.value : "";
    const doc = els.filterEvidenceDoc ? els.filterEvidenceDoc.value : "";

    return state.evidence.filter((ev) => {
      const span = (ev.text_span || ev.content || "").toLowerCase();
      const id = (ev.evidence_id || "").toLowerCase();
      const docName = (ev.document_id || (ev.source_uri || "").split("/").pop() || "").toLowerCase();
      const matchesQuery = !query || span.includes(query) || id.includes(query) || docName.includes(query);
      const matchesPolarity = !polarity || ev.polarity === polarity;
      const matchesStatus = !status || ev.status === status || ev.review_status === status;
      const matchesDoc = !doc || ev.document_id === doc || ((ev.source_uri || "").split("/").pop() === doc);

      return matchesQuery && matchesPolarity && matchesStatus && matchesDoc;
    });
  }

  function renderEvidenceExplorer() {
    const filtered = filterEvidenceItems();

    // Empty state
    if (filtered.length === 0) {
      if (els.evidenceCardsContainer) els.evidenceCardsContainer.style.display = "none";
      if (els.claimsTableViewContainer) els.claimsTableViewContainer.style.display = "none";
      if (els.evidencePaginationRow) els.evidencePaginationRow.style.display = "none";
      if (els.evidenceEmptyState) {
        els.evidenceEmptyState.style.display = "flex";
        const ill = els.evidenceEmptyState.querySelector(".empty-state-illustration");
        if (ill && window.SherlockStickers) {
          ill.innerHTML = window.SherlockStickers.renderEmptyStateIllustration("magnifying_glass");
        }
      }
      return;
    }

    if (els.evidenceEmptyState) els.evidenceEmptyState.style.display = "none";
    if (els.evidencePaginationRow) els.evidencePaginationRow.style.display = "flex";

    // Pagination
    const pageSize = state.evidencePageSize || 6;
    const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
    if (state.evidenceCurrentPage > totalPages) state.evidenceCurrentPage = totalPages;
    if (state.evidenceCurrentPage < 1) state.evidenceCurrentPage = 1;

    const startIndex = (state.evidenceCurrentPage - 1) * pageSize;
    const endIndex = Math.min(startIndex + pageSize, filtered.length);
    const pageItems = filtered.slice(startIndex, endIndex);

    // Summary & Pagination Buttons
    if (els.evidencePaginationSummary) {
      els.evidencePaginationSummary.textContent = `Showing ${startIndex + 1}–${endIndex} of ${filtered.length} evidence items`;
    }
    if (els.btnEvidencePrevPage) els.btnEvidencePrevPage.disabled = state.evidenceCurrentPage <= 1;
    if (els.btnEvidenceNextPage) els.btnEvidenceNextPage.disabled = state.evidenceCurrentPage >= totalPages;

    if (els.evidencePagesList) {
      let pagePills = "";
      for (let p = 1; p <= totalPages; p++) {
        if (p === 1 || p === totalPages || (p >= state.evidenceCurrentPage - 1 && p <= state.evidenceCurrentPage + 1)) {
          pagePills += `<button class="pagination-page-btn ${p === state.evidenceCurrentPage ? "active" : ""}" onclick="window.sherlockApp.setEvidencePage(${p})">${p}</button>`;
        } else if (p === state.evidenceCurrentPage - 2 || p === state.evidenceCurrentPage + 2) {
          pagePills += `<span class="pagination-ellipsis">…</span>`;
        }
      }
      els.evidencePagesList.innerHTML = pagePills;
    }

    // View Mode
    if (state.evidenceViewMode === "cards") {
      if (els.evidenceCardsContainer) {
        els.evidenceCardsContainer.style.display = "grid";
        els.evidenceCardsContainer.innerHTML = pageItems.map((ev) => renderEvidenceCardHtml(ev)).join("");
      }
      if (els.claimsTableViewContainer) els.claimsTableViewContainer.style.display = "none";
    } else {
      if (els.evidenceCardsContainer) els.evidenceCardsContainer.style.display = "none";
      if (els.claimsTableViewContainer) {
        els.claimsTableViewContainer.style.display = "block";
        renderClaimsTable();
      }
    }
  }

  function renderEvidenceCardHtml(ev) {
    const docName = ev.document_id || (ev.source_uri || "internal").split("/").pop();
    const isNeg = ev.polarity === "NEGATIVE" || ev.polarity === "CONTRADICTING";
    const statusClass = isNeg ? "status-pill-review" : "status-pill-match";
    const statusLabel = isNeg ? (ev.polarity || "NEGATIVE") : (ev.polarity || "POSITIVE");
    const spanText = ev.text_span || ev.content || "";

    const stickerHtml = window.SherlockStickers
      ? window.SherlockStickers.renderEntitySticker(ev.evidence_id, "EVIDENCE", { size: "sm" })
      : "";

    return `
      <article class="evidence-card-v2" data-evidence-id="${escapeHtml(ev.evidence_id)}">
        <div class="evidence-card-v2-header">
          <div class="evidence-header-left">
            <div class="evidence-sticker-blob">
              ${stickerHtml}
            </div>
            <div>
              <span class="evidence-doc-badge" title="${escapeHtml(ev.source_uri || ev.document_id || '')}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                ${escapeHtml(docName)}
              </span>
              <span class="evidence-id-micro">ID: ${escapeHtml(ev.evidence_id.slice(0, 14))}…</span>
            </div>
          </div>
          <div class="evidence-header-right">
            <span class="status-pill-v2 ${statusClass}">${statusLabel}</span>
            <span class="status-pill ${getStatusBadgeClass(ev.review_status || ev.status)}">${escapeHtml(ev.review_status || ev.status || "GROUNDED")}</span>
          </div>
        </div>

        <div class="evidence-card-v2-body">
          <blockquote class="evidence-blockquote">
            “${escapeHtml(spanText)}”
          </blockquote>

          <div class="evidence-meta-row">
            <div class="meta-item">
              <span class="meta-label">Span:</span>
              <span class="code-pill">[${ev.start_char ?? 0}:${ev.end_char ?? 0}]</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Method:</span>
              <span class="code-pill">${escapeHtml(ev.extraction_method || "SPAN_MATCHER")}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Type:</span>
              <span class="badge-type-pill badge-type-location">${escapeHtml(ev.evidence_type || "TEXT_SPAN")}</span>
            </div>
          </div>
        </div>

        <div class="evidence-card-v2-footer">
          <button class="btn btn-peach-pill btn-sm" onclick="window.sherlockApp.openEvidenceDrawer('${escapeHtml(ev.evidence_id)}')">
            Inspect Grounding & Claims →
          </button>
        </div>
      </article>
    `;
  }

  function setEvidencePage(pageNum) {
    state.evidenceCurrentPage = pageNum;
    renderEvidenceExplorer();
    const target = document.getElementById("tab-claims");
    if (target) target.scrollIntoView({ behavior: "smooth" });
  }

  function openEvidenceDrawer(evidenceId) {
    const ev = state.evidence.find((e) => e.evidence_id === evidenceId);
    if (!ev) return;

    if (els.evidenceDrawerTitle) els.evidenceDrawerTitle.textContent = `Evidence Span Grounding`;
    if (els.evidenceDrawerId) els.evidenceDrawerId.textContent = `ID: ${ev.evidence_id}`;
    if (els.evidenceDrawerTypeBadge) {
      els.evidenceDrawerTypeBadge.textContent = `${ev.evidence_type || 'TEXT_SPAN'} • ${ev.polarity || 'GROUNDED'}`;
    }

    // Find claims linked to this evidence
    const linkedClaims = state.claims.filter(
      (c) =>
        (c.supporting_evidence_ids || []).includes(evidenceId) ||
        (c.contradicting_evidence_ids || []).includes(evidenceId)
    );

    const docName = ev.document_id || (ev.source_uri || "internal").split("/").pop();
    const spanText = ev.text_span || ev.content || "";
    const stickerHtml = window.SherlockStickers
      ? window.SherlockStickers.renderEntitySticker(ev.evidence_id, "EVIDENCE", { size: "lg" })
      : "";

    if (els.evidenceDrawerBody) {
      els.evidenceDrawerBody.innerHTML = `
        <div style="text-align: center; margin-bottom: 16px;">
          ${stickerHtml}
        </div>

        <div class="profile-section-card">
          <div class="profile-section-heading">Extracted Text Excerpt</div>
          <blockquote class="evidence-blockquote" style="font-size: 14px; margin: 8px 0;">
            “${escapeHtml(spanText)}”
          </blockquote>
        </div>

        <div class="profile-section-card">
          <div class="profile-section-heading">Provenance & Grounding Coordinates</div>
          <div class="key-value-list">
            <div class="kv-item">
              <span class="kv-key">Source Document:</span>
              <span class="code-pill">${escapeHtml(docName)}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">Document Hash:</span>
              <span class="code-pill">${escapeHtml((ev.document_hash || "sha256:d81a9f...").slice(0, 18))}…</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">Character Offset:</span>
              <span class="code-pill">[${ev.start_char ?? 0}:${ev.end_char ?? 0}]</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">Extraction Method:</span>
              <span class="code-pill">${escapeHtml(ev.extraction_method || "span_matcher")}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">Polarity:</span>
              <span class="status-pill ${ev.polarity === "NEGATIVE" || ev.polarity === "CONTRADICTING" ? "status-pill-warning" : "status-pill-success"}">${escapeHtml(ev.polarity || "SUPPORTING")}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">Status:</span>
              <span class="status-pill ${getStatusBadgeClass(ev.review_status || ev.status)}">${escapeHtml(ev.review_status || ev.status || "GROUNDED")}</span>
            </div>
          </div>
        </div>

        <div class="profile-section-card">
          <div class="profile-section-heading">Associated Structured Claims (${linkedClaims.length})</div>
          ${
            linkedClaims.length > 0
              ? linkedClaims
                  .map(
                    (c) => `
                <div class="claim-linked-card" style="margin-top: 8px; padding: 10px; background: #FFFDF9; border: 1px solid var(--border-ivory); border-radius: 8px;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <span class="code-pill">${escapeHtml(c.claim_id.slice(0, 12))}…</span>
                    <span class="status-pill ${getStatusBadgeClass(c.review_status)}">${escapeHtml(c.review_status)}</span>
                  </div>
                  <div style="font-size: 13px; font-weight: 600; color: var(--text-plum);">
                    ${escapeHtml(c.subject_id)} —[<code>${escapeHtml(c.predicate)}</code>]—> ${escapeHtml(c.object_id)}
                  </div>
                  <div style="margin-top: 8px;">
                    <button class="btn btn-peach-pill btn-xs" onclick="window.sherlockApp.openReviewClaim('${escapeHtml(c.claim_id)}')">
                      Review Decision →
                    </button>
                  </div>
                </div>
              `
                  )
                  .join("")
              : '<p class="text-muted" style="font-size: 13px;">No structured claims directly associated with this span yet.</p>'
          }
        </div>
      `;
    }

    if (els.evidenceDetailPanel) {
      els.evidenceDetailPanel.style.display = "block";
      els.evidenceDetailPanel.classList.add("open");
    }
    if (els.evidenceDrawerBackdrop) {
      els.evidenceDrawerBackdrop.classList.add("open");
    }
  }

  function closeEvidenceDrawer() {
    if (els.evidenceDetailPanel) {
      els.evidenceDetailPanel.classList.remove("open");
      els.evidenceDetailPanel.style.display = "none";
    }
    if (els.evidenceDrawerBackdrop) {
      els.evidenceDrawerBackdrop.classList.remove("open");
    }
  }

  function renderClaimsTable() {
    if (!els.tbodyClaims) return;

    if (state.claims.length === 0) {
      els.tbodyClaims.innerHTML =
        '<tr><td colspan="10" class="text-center text-muted">No claims extracted.</td></tr>';
      return;
    }

    els.tbodyClaims.innerHTML = state.claims
      .map((c) => {
        const quals = c.qualifiers || {};
        const qualPills = [];
        if (quals.is_allegation) qualPills.push('<span class="status-pill status-pill-warning">ALLEGATION</span>');
        if (quals.is_negated) qualPills.push('<span class="status-pill status-pill-danger">NEGATED</span>');

        return `
          <tr>
            <td><span class="code-pill">${escapeHtml(c.claim_id.slice(0, 14))}...</span></td>
            <td><strong title="${escapeHtml(c.subject_id)}">${escapeHtml(entityDisplayName(c.subject_id))}</strong></td>
            <td><code>${escapeHtml(c.predicate)}</code></td>
            <td><strong title="${escapeHtml(c.object_id)}">${escapeHtml(entityDisplayName(c.object_id))}</strong></td>
            <td>${(c.confidence_score ?? 0).toFixed(2)}</td>
            <td><span class="status-pill ${getStatusBadgeClass(c.review_status)}">${escapeHtml(
          c.review_status
        )}</span></td>
            <td>${qualPills.join(" ") || "—"}</td>
            <td>${(c.supporting_evidence_ids || []).length}</td>
            <td>${(c.contradicting_evidence_ids || []).length}</td>
            <td>
              <button class="btn btn-peach-pill btn-sm" onclick="window.sherlockApp.openReviewClaim('${escapeHtml(
                c.claim_id
              )}')">
                Review
              </button>
            </td>
          </tr>
        `;
      })
      .join("");
  }

  function handleOpenReviewClaim(claimId) {
    const claim = state.claims.find((c) => c.claim_id === claimId);
    if (!claim) return;

    els.reviewClaimId.value = claim.claim_id;
    els.reviewModalClaimInfo.innerHTML = `
      <strong>Claim:</strong> ${escapeHtml(entityDisplayName(claim.subject_id))} —[${escapeHtml(claim.predicate)}]—> ${escapeHtml(
      entityDisplayName(claim.object_id)
    )}<br>
      <span class="text-muted">Current Status: ${escapeHtml(claim.review_status)}</span>
    `;

    openModal(els.modalReviewAction);
  }

  async function handleCommitReviewDecision(e) {
    e.preventDefault();
    if (!state.activeInvestigationId) return;

    const claimId = els.reviewClaimId.value;
    const newStatus = els.selectReviewStatus.value;
    const reviewer = els.inputReviewerId.value.trim();
    const rationale = els.inputReviewRationale.value.trim();

    try {
      await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/review-claim`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            claim_id: claimId,
            new_status: newStatus,
            rationale: rationale,
            reviewer: reviewer,
          }),
        }
      );

      showToast(`Claim updated to ${newStatus}!`, "success");
      closeModal(els.modalReviewAction);
      els.formReviewDecision.reset();
      loadClaimsAndEvidence();
      loadDashboard();
    } catch (_) {}
  }

  // =========================================================================
  // Screen 8: Investigation Report
  // =========================================================================

  async function loadReport() {
    await generateReport();
  }

  async function generateReport() {
    if (!state.activeInvestigationId) {
      if (els.reportViewContainer) {
        els.reportViewContainer.innerHTML = `
          <div class="empty-state-card">
            <span class="empty-icon">📑</span>
            <div class="empty-title text-plum">No Active Case Selected</div>
            <div class="empty-sub">Select or create an investigation from the header to compile an audit report.</div>
          </div>
        `;
      }
      return;
    }

    try {
      showToast("Compiling investigation dossier...", "info");
      const report = await apiFetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/report`
      );

      // Render Markdown Preview
      const mdText = report.markdown_report || "No markdown compiled.";
      els.reportViewContainer.innerHTML = formatMarkdownToHtml(mdText);
      showToast("Report compiled successfully!", "success");
    } catch (_) {}
  }

  async function exportReportMarkdown() {
    if (!state.activeInvestigationId) {
      showToast("Select an active case to export markdown", "warning");
      return;
    }
    try {
      const res = await fetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/report/download?format=markdown`
      );
      if (!res.ok) throw new Error("Failed to export markdown report");
      const text = await res.text();
      downloadFile(text, `sherlock_report_${state.activeInvestigationId}.md`, "text/markdown");
      showToast("Markdown report downloaded successfully!", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function exportReportJson() {
    if (!state.activeInvestigationId) {
      showToast("Select an active case to export JSON", "warning");
      return;
    }
    try {
      const res = await fetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/report/download?format=json`
      );
      if (!res.ok) throw new Error("Failed to export JSON report");
      const text = await res.text();
      downloadFile(text, `sherlock_report_${state.activeInvestigationId}.json`, "application/json");
      showToast("JSON report downloaded successfully!", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function exportReportHtml() {
    if (!state.activeInvestigationId) {
      showToast("Select an active case to export HTML", "warning");
      return;
    }
    try {
      showToast("Downloading HTML report dossier...", "info");
      const res = await fetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/report/download?format=html`
      );
      if (!res.ok) throw new Error("Failed to export HTML report");
      const text = await res.text();
      downloadFile(text, `sherlock_report_${state.activeInvestigationId}.html`, "text/html");
      showToast("HTML report downloaded successfully!", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function printReport() {
    if (!state.activeInvestigationId) {
      showToast("Select an active case to print report", "warning");
      return;
    }
    try {
      showToast("Opening printable report dossier...", "info");
      const res = await fetch(
        `/api/v1/investigations/${encodeURIComponent(state.activeInvestigationId)}/report/download?format=html`
      );
      if (!res.ok) throw new Error("Failed to fetch report for printing");
      const htmlText = await res.text();
      const printWin = window.open("", "_blank");
      if (printWin) {
        printWin.document.open();
        printWin.document.write(htmlText);
        printWin.document.close();
        printWin.focus();
        setTimeout(() => {
          printWin.print();
        }, 500);
      } else {
        window.print();
      }
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function formatMarkdownToHtml(md) {
    if (!md) return "";
    const lines = String(md).split(/\r?\n/);
    const inline = (value) => escapeHtml(value)
      .replace(/`([^`]+)`/g, '<code class="code-pill">$1</code>')
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.*?)\*/g, "<em>$1</em>");
    const output = [];
    let index = 0;

    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index++; continue; }
      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        const level = Math.min(heading[1].length + 1, 6);
        output.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        index++;
        continue;
      }
      if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { output.push("<hr>"); index++; continue; }
      if (/^\s*>/.test(line)) {
        const quote = [];
        while (index < lines.length && /^\s*>/.test(lines[index])) quote.push(inline(lines[index++].replace(/^\s*>\s?/, "")));
        output.push(`<blockquote>${quote.join("<br>")}</blockquote>`);
        continue;
      }
      if (index + 1 < lines.length && line.includes("|") && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
        const cells = (value) => value.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
        const headers = cells(line);
        index += 2;
        const rows = [];
        while (index < lines.length && lines[index].includes("|")) rows.push(cells(lines[index++]));
        output.push(`<div class="report-table-wrap"><table><thead><tr>${headers.map((cell) => `<th>${inline(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_, cellIndex) => `<td>${inline(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      const listMatch = line.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
      if (listMatch) {
        const ordered = /\d+\./.test(listMatch[1]);
        const tag = ordered ? "ol" : "ul";
        const items = [];
        while (index < lines.length) {
          const item = lines[index].match(/^\s*([-*]|\d+\.)\s+(.*)$/);
          if (!item || (ordered !== /\d+\./.test(item[1]))) break;
          items.push(`<li>${inline(item[2])}</li>`);
          index++;
        }
        output.push(`<${tag}>${items.join("")}</${tag}>`);
        continue;
      }
      const paragraph = [line];
      index++;
      while (index < lines.length && lines[index].trim() && !/^(#{1,6}\s|\s*>|\s*([-*]|\d+\.)\s|\s*(---+|\*\*\*+)\s*$)/.test(lines[index])) paragraph.push(lines[index++]);
      output.push(`<p>${paragraph.map(inline).join(" ")}</p>`);
    }

    return output.join("\n");
  }

  // =========================================================================
  // Helper Utilities
  // =========================================================================

  function getStatusBadgeClass(status) {
    switch (status) {
      case "COMPLETED":
      case "VERIFIED":
      case "MATCH":
        return "status-pill-success";
      case "PARTIAL_FAILURE":
      case "DISPUTED":
      case "REVIEW":
        return "status-pill-warning";
      case "FAILED":
      case "RETRACTED":
      case "REJECTED":
      case "NON_MATCH":
        return "status-pill-danger";
      default:
        return "status-pill-neutral";
    }
  }

  function formatBytes(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  }

  // Expose global controller for inline onclick handlers
  window.sherlockApp = {
    selectCase: setActiveInvestigation,
    inspectDoc: inspectDocument,
    highlightSpan: highlightSpanInViewer,
    inspectEntity: inspectEntity,
    closeEntityDrawer: closeEntityDrawer,
    focusEntityInGraph: focusEntityInGraph,
    setEntitiesPage: setEntitiesPage,
    openEvidenceDrawer: openEvidenceDrawer,
    closeEvidenceDrawer: closeEvidenceDrawer,
    setEvidencePage: setEvidencePage,
    approveMerge: handleApproveMerge,
    declareNonMatchPrefill: handleDeclareNonMatchPrefill,
    openReviewClaim: handleOpenReviewClaim,
    showToast: showToast,
    openClearInv: openClearInvestigationModal,
    openClearAll: openClearAllDataModal,
    resetPreferences: handleResetPreferences,
    copyText: copyTextToClipboard,
    resetAllUiViews: resetAllUiViews,
  };

  // Kickoff SPA
  document.addEventListener("DOMContentLoaded", init);
})();
