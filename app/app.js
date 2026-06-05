// ─── State ─────────────────────────────────────────────────────────────────────
const state = {
  // Navigation
  view: "browse",               // "browse" | "explorer" | "review"
  sidebarHidden: false,         // side panel collapsed state
  currentBoard: null,           // board filter (null = all)
  currentSource: null,          // source filter (null = all)
  currentContentKind: null,     // clip subtype filter (scan/photo/video)
  currentCollection: null,      // collection ID filter
  currentCollectionIds: [],     // recursive collection scope
  currentCollectionLabel: "",   // display label for collection scope
  currentCatalogFile: null,     // catalog dimension file (e.g. "room/bathroom.md")
  currentCatalogFiles: [],      // recursive catalog scope
  currentCatalogLabel: "",      // display label for catalog scope
  currentClassificationAxis: null,   // v2 browse axis filter (e.g. room, track)
  currentClassificationValue: null,  // optional v2 axis value (e.g. kitchen)
  currentClassificationLabel: "",    // display label for v2 classification scope
  classificationFacets: {},     // stackable browse filters: axis -> [values]
  classificationFacetLabels: {}, // display labels keyed as "axis:value"
  currentTreeNodeId: null,      // active sidebar tree node ID
  triageFilter: "",             // "" | "pending" | "keeper" | "hidden" | "needs-comment" | "flagged" | "irrelevant-discarded"
  showDiscarded: false,         // Browse discarded items alongside ordinary items.

  // Assets
  assets: [],
  hasMore: false,
  loadingAssets: false,
  pendingAssetsReload: false,
  offset: 0,
  q: "",
  semanticMode: false,
  assetsRequestSeq: 0,
  chatPrompt: "",                // last Ask-Dave prompt that produced results
  chatItemIds: null,             // array of IDs from a chat show_items action

  // Review mode
  reviewItems: [],
  reviewIndex: 0,
  reviewHistory: [],
  reviewDrafts: {},
  reviewSkipped: 0,
  reviewKept: 0,
  reviewMoved: 0,
  reviewHidden: 0,
  reviewSnapshotTotal: 0,
  reviewScopeTotal: 0,
  reviewSeedIds: null,

  // Collections + facets + catalog
  collections: [],
  hiddenCollections: [],
  collectionActors: [],
  collectionManagerSelectedId: null,
  collectionShareFilter: "all",
  facets: { sources: [], boards: [] },
  catalogTree: [],

  // Modal + annotations
  modalAsset: null,
  annotations: [],
  activeAnnotationId: null,
  dragging: null,
  noteTimers: {},
  modalScanPages: null,
  modalScanPageIndex: 0,
  modalScanStartPage: 1,         // absolute page number in master scan PDF for group index 0
  modalLoadSeq: 0,
  modalScopeAssetIds: [],
  modalScopeAssetIndex: -1,
  modalSourceCandidateSelectedId: "",
  modalSourceCandidateBusyAction: "",
  modalSourceCandidateMessage: "",
  modalAdvancedEditing: false,
  modalClassificationDirty: false,

  // Imports
  scanImportBusy: false,
  photoImportBusy: false,
  videoImportBusy: false,
  scanImportFile: null,
  photoImportFile: null,
  videoImportFile: null,

  // Canvas review mode
  canvasReview: false,          // true when canvas review overlay is active
  canvasCollectionBuild: false, // true while selecting cards for a collection
  canvasSelected: new Set(),    // set of selected asset IDs

  // Local owner session. Legacy collaborator fields remain only for old data.
  actor: null,                  // local owner identity
  hiddenTree: null,             // hidden items tree for sidebar (owners only)
  expandedTreeNodes: new Set(), // track which tree nodes are expanded by user
  allItemsTreeCollapsed: null,
  collaboratorTreeUnlocked: false, // legacy collaborator-mode flag; inactive in local owner mode
  collaboratorDefaultScopeApplied: false,
  sharedCollectionLandingId: "",
  lastCollaboratorBrowseUnlockAt: 0,
  openQuestions: [],             // legacy question dashboard; inactive in local owner mode
  questionPollTimer: null,
};

const DESKTOP_ASSETS_PAGE_SIZE = 240;
const TABLET_ASSETS_PAGE_SIZE = 120;
const PHONE_ASSETS_PAGE_SIZE = 80;
// Start pagination several screens early so its JSON request does not wait
// behind the burst of lazy thumbnail requests near the bottom of the grid.
const AUTO_LOAD_MORE_MARGIN_PX = 3600;
let _autoLoadMoreRaf = 0;
let _autoLoadMoreObservers = [];

function _detectAssetsPageSize() {
  const vw = Math.max(0, window.innerWidth || 0);
  const vh = Math.max(0, window.innerHeight || 0);
  const shortest = Math.min(vw || Infinity, vh || Infinity);
  const ua = navigator.userAgent || "";
  const isTouchMac = /Macintosh/i.test(ua) && Number(navigator.maxTouchPoints || 0) > 1;
  const isIpad = /iPad/i.test(ua) || isTouchMac;
  if (shortest <= 520) return PHONE_ASSETS_PAGE_SIZE;
  if (isIpad || shortest <= 980) return TABLET_ASSETS_PAGE_SIZE;
  return DESKTOP_ASSETS_PAGE_SIZE;
}

const ASSETS_PAGE_SIZE = _detectAssetsPageSize();
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const escapeHtml = Shared.escapeHtml;
const api = Shared.api;
const formatApiError = Shared.formatApiError;
const _bp = Shared.prefixPath;
const _B = Shared.basePath;
const SIDEBAR_VISIBILITY_KEY = "inspirations.ui.sidebar.hidden.v1";
const SIDEBAR_WIDTH_KEY = "inspirations.ui.sidebar.width.v1";
const VIEW_MODE_KEY = "inspirations.ui.view.mode.v1";
const CONTEXT_LINK_BANNER_DEFAULT = "This local link opened a referenced item.";
const CLASSIFICATION_TRACK_LABELS = {
  style_product_decor: "Style / Decor",
  construction_concern: "Construction",
  home_maintenance_diy: "Maintenance / DIY",
  irrelevant: "Irrelevant",
};
const REVIEW_FOCUS_LABELS = {
  landscaping: "Landscaping",
  inspection: "Inspection",
};
const MEDIA_RELIABILITY_LABELS = {
  trust_title_source: "Trust title / source",
  thumbnail_placeholder: "Thumbnail is placeholder",
  thumbnail_mismatch: "Thumbnail mismatches content",
};
const MOVABLE_CLASSIFICATION_TRACKS = [
  "style_product_decor",
  "construction_concern",
  "home_maintenance_diy",
];
const SIDEBAR_MIN_WIDTH = 220;
const SIDEBAR_MAX_WIDTH = 420;

const IMAGE_SUFFIX_RE = /\.(jpg|jpeg|png|webp|gif|bmp|svg)(\?.*)?$/i;
const VIDEO_SUFFIX_RE = /\.(mp4|mov|m4v|webm|avi|mkv|mpeg|mpg|wmv|3gp)(\?.*)?$/i;
const PDF_FILE_EXT_RE = /\.pdf$/i;
const IMAGE_FILE_EXT_RE = /\.(jpg|jpeg|png|webp|gif|bmp|heic|heif|tif|tiff)$/i;
const VIDEO_FILE_EXT_RE = /\.(mp4|mov|m4v|webm|avi|mkv|mpeg|mpg|wmv|3gp)$/i;
const TITLE_DYNAMIC_SEGMENT_RE = /^(?:home|index|main|blog|news|latest|feed|explore|discover|topics?|category|categories|tag|tags|shop|products?|wirecutter)$/i;
const TITLE_DYNAMIC_QUERY_KEY_RE = /^(?:page|p|offset|start|sort|view)$/i;
const TITLE_GENERIC_PREVIEW_RE = /(?:og[_-]?(?:image|default|general)|default(?:[_-]?image)?|site[_-]?icon|logo|placeholder)/i;
const INGEST_TAG_GROUPS = [
  {
    key: "source",
    label: "Source",
    tags: ["scan", "photo", "video"],
  },
  {
    key: "rooms",
    label: "Rooms",
    tags: [
      "bathroom", "kitchen", "bedroom", "living_room", "dining_room", "office",
      "laundry", "mudroom", "closet", "garage", "hallway", "foyer", "nursery",
      "basement", "attic", "pantry", "sunroom", "patio", "pool", "garden",
    ],
  },
  {
    key: "styles",
    label: "Styles",
    tags: [
      "modern", "contemporary", "traditional", "transitional", "farmhouse",
      "rustic", "coastal", "industrial", "mid_century", "scandinavian",
      "mediterranean", "craftsman", "colonial", "art_deco", "bohemian",
      "minimalist", "eclectic", "french_country", "spanish", "japanese",
    ],
  },
  {
    key: "materials",
    label: "Materials",
    tags: [
      "wood", "tile", "stone", "marble", "granite", "quartz", "concrete",
      "brick", "metal", "glass", "stainless_steel", "brass", "copper",
      "iron", "ceramic", "porcelain", "hardwood", "laminate", "vinyl",
      "leather", "fabric", "linen", "wallpaper", "stucco", "shiplap",
    ],
  },
  {
    key: "types",
    label: "Types",
    tags: ["interior", "exterior", "product", "plan", "document", "other"],
  },
  {
    key: "colors",
    label: "Colors",
    tags: [
      "white", "black", "gray", "brown", "beige", "blue", "green", "red",
      "yellow", "orange", "pink", "purple", "gold", "silver", "navy",
    ],
  },
  {
    key: "elements",
    label: "Elements",
    tags: ["cabinet", "countertop", "sink", "bathtub", "shower", "fireplace", "lighting", "window", "door", "shelving"],
  },
];

async function apiUpload(path, formData) {
  const res = await fetch(_bp(path), { method: "POST", body: formData });
  if (!res.ok) { const t = await res.text(); throw new Error(t || res.statusText); }
  return res.json();
}

// ─── Utilities ─────────────────────────────────────────────────────────────────

function semanticQueryFromInput(value) {
  const text = `${value || ""}`.trim();
  if (!text) return "";
  for (const p of ["sem:", "similar:"]) {
    if (text.toLowerCase().startsWith(p)) return text.slice(p.length).trim();
  }
  return "";
}

function _mediaVersionForAsset(asset) {
  const raw = String(asset?.sha256 || asset?.stored_video_path || asset?.stored_path || asset?.thumb_path || "").trim();
  if (!raw) return "";
  let hash = 0;
  for (let i = 0; i < raw.length; i += 1) hash = ((hash << 5) - hash + raw.charCodeAt(i)) | 0;
  return Math.abs(hash).toString(36);
}

function _mediaUrlForAsset(asset, kind) {
  const assetId = String(asset?.id || "").trim();
  if (!assetId) return "";
  const version = _mediaVersionForAsset(asset);
  return `${_B}/media/${encodeURIComponent(assetId)}?kind=${encodeURIComponent(kind)}${version ? `&v=${version}` : ""}`;
}

function previewForAsset(a) {
  if (a.thumb_path) return _mediaUrlForAsset(a, "thumb");
  if (a.stored_path && IMAGE_SUFFIX_RE.test(a.stored_path)) return _mediaUrlForAsset(a, "original");
  if (a.image_url && IMAGE_SUFFIX_RE.test(a.image_url)) return a.image_url;
  return "";
}

function isVideoAsset(asset) {
  const mediaStatus = String(asset?.media_status || "").trim().toLowerCase();
  const contentKind = String(asset?.content_kind || "").trim().toLowerCase();
  if (mediaStatus === "video") return true;
  if (contentKind === "video" || contentKind === "reel") return true;
  if (asset?.stored_path && VIDEO_SUFFIX_RE.test(String(asset.stored_path))) return true;
  if (asset?.image_url && VIDEO_SUFFIX_RE.test(String(asset.image_url))) return true;
  return false;
}

function videoUrlForAsset(asset) {
  if (!asset) return "";
  if (asset.stored_video_path) return _mediaUrlForAsset(asset, "video");
  if (asset.stored_path && VIDEO_SUFFIX_RE.test(asset.stored_path)) return _mediaUrlForAsset(asset, "original");
  if (asset.image_url && VIDEO_SUFFIX_RE.test(asset.image_url)) return asset.image_url;
  return "";
}

const FB_SAVED_LINK_TITLE_RE = /^\s*[^.]+ saved a link from (.+?)'s post\.?\s*$/i;

function _titleCaseWords(text) {
  return String(text || "")
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => (w.length <= 2 ? w.toUpperCase() : (w[0].toUpperCase() + w.slice(1).toLowerCase())))
    .join(" ");
}

function _fallbackTitleFromSourceRef(asset) {
  const sourceRef = String(asset?.source_ref || "").trim();
  if (!sourceRef) return "";
  const title = String(asset?.title || "").trim();
  const m = FB_SAVED_LINK_TITLE_RE.exec(title);
  const sourceName = m ? String(m[1] || "").trim() : "";
  try {
    const u = new URL(sourceRef);
    const host = (u.hostname || "").replace(/^www\./i, "");
    const parts = decodeURIComponent((u.pathname || "").replace(/\/+/g, "/"))
      .split("/")
      .filter(Boolean);
    let slug = parts.length ? parts[parts.length - 1] : "";
    slug = slug.replace(/\.[a-z0-9]{2,5}$/i, "");
    slug = slug
      .replace(/[-_+]+/g, " ")
      .replace(/[^a-z0-9 ]+/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (slug && !/^\d+$/.test(slug)) {
      const prettySlug = _titleCaseWords(slug);
      if (sourceName) return `${sourceName}: ${prettySlug}`;
      return prettySlug;
    }
    if (sourceName) return `${sourceName} link`;
    if (host) return _titleCaseWords(host.replace(/\./g, " "));
    return "";
  } catch (_) {
    return sourceName ? `${sourceName} link` : "";
  }
}

function displayTitle(a) {
  const info = a && typeof a === "object" ? (a.title_info || null) : null;
  const serverDisplay = String((info && info.display_title) || a?.display_title || "").trim();
  if (serverDisplay) return serverDisplay;
  const title = (a.title || "").trim();
  const ai = (a.ai_summary || "").trim();
  const alt = (a.seo_alt_text || "").trim().replace(/^This may contain:\s*/i, "");
  const isGenericSavedLink = FB_SAVED_LINK_TITLE_RE.test(title);
  const sourceRefTitle = isGenericSavedLink ? _fallbackTitleFromSourceRef(a) : "";
  // Junk titles: bare domains, parking pages, etc.
  const isJunk = title && /^(https?:\/\/|www\.)|\.(com|org|net|co)\b/i.test(title)
    && title.length < 40;
  const bestTitle = sourceRefTitle || ((!title || isJunk) ? (ai || alt || title) : title);
  return bestTitle
    || (a.board || "").trim()
    || (a.creator_name ? `via ${a.creator_name}` : "")
    || "(untitled)";
}

function classificationTrackLabel(value) {
  const key = String(value || "").trim();
  return CLASSIFICATION_TRACK_LABELS[key] || key || "";
}

function titleQualityForAsset(asset) {
  const serverQuality = asset?.title_quality || asset?.title_info?.quality || null;
  if (serverQuality && typeof serverQuality === "object") {
    const label = String(serverQuality.label || "").trim();
    if (label) {
      return {
        kind: String(serverQuality.kind || "").trim(),
        label,
        tooltip: String(serverQuality.tooltip || "").trim(),
      };
    }
  }
  const source = normalizeSourceKey(asset?.source);
  const title = String(asset?.title || "").trim();
  const sourceRef = String(asset?.source_ref || "").trim();
  const imageUrl = String(asset?.image_url || "").trim();
  const isGenericSavedLink = source === "facebook" && FB_SAVED_LINK_TITLE_RE.test(title);
  if (!isGenericSavedLink) {
    return { kind: "", label: "", tooltip: "" };
  }

  let host = "";
  let rootLikePath = false;
  let dynamicPath = false;
  let dynamicQuery = false;
  try {
    const u = new URL(sourceRef);
    host = (u.hostname || "").replace(/^www\./i, "");
    const parts = decodeURIComponent((u.pathname || "").replace(/\/+/g, "/"))
      .split("/")
      .filter(Boolean);
    rootLikePath = parts.length <= 1;
    const last = (parts[parts.length - 1] || "").trim();
    dynamicPath = rootLikePath || TITLE_DYNAMIC_SEGMENT_RE.test(last.toLowerCase());
    for (const key of u.searchParams.keys()) {
      if (TITLE_DYNAMIC_QUERY_KEY_RE.test(String(key || "").toLowerCase())) {
        dynamicQuery = true;
        break;
      }
    }
  } catch (_) {
    // Leave host/path signals empty when source_ref is not a URL.
  }
  const genericPreview = TITLE_GENERIC_PREVIEW_RE.test(imageUrl.toLowerCase());
  const dynamic = dynamicPath || dynamicQuery || genericPreview;
  if (dynamic) {
    const hostSuffix = host ? ` (${host})` : "";
    return {
      kind: "dynamic-link",
      label: "Dynamic Link",
      tooltip: `Title may drift over time because this source looks dynamic${hostSuffix}.`,
    };
  }

  return {
    kind: "title-check",
    label: "Title Check",
    tooltip: "Saved-link title was auto-generated. Verify before sharing.",
  };
}

function sourceHost(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function sourceDisplayName(source) {
  const key = normalizeSourceKey(source);
  if (key === "scan") return "Clips";
  if (!key) return "";
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function normalizeSourceKey(source) {
  const key = String(source || "").trim().toLowerCase();
  if (key === "clip" || key === "clips" || key === "magazine clip" || key === "magazine clips") {
    return "scan";
  }
  return key;
}

function normalizeOtherDimensionLabel(label) {
  const raw = String(label || "").trim();
  const key = raw.toLowerCase();
  if (key === "uncategorized") return "Other / ?";
  if (key === "(small groups)") return "Small Groups";
  return raw;
}

function describeSourceCatchall(child) {
  const file = String(child?.file || "").trim().toLowerCase();
  const label = String(child?.label || "").trim();
  if (file.endsWith("_unboarded-reel.md")) {
    return { label: "Unsorted Reels", note: "Cleanup bucket from source import; not a deliberate board." };
  }
  if (file.endsWith("_unboarded-post.md")) {
    return { label: "Unsorted Posts", note: "Cleanup bucket from source import; not a deliberate board." };
  }
  if (file.endsWith("_unboarded.md")) {
    return { label: "Unsorted Houzz Photos", note: "Cleanup bucket from source import; not a deliberate board." };
  }
  if (file.endsWith("_unboarded-scan.md")) {
    return { label: "Unsorted Scans", note: "Cleanup bucket from source import; scan grouping still needs refinement." };
  }
  if (file.endsWith("_unboarded-video.md")) {
    return { label: "Unsorted Videos", note: "Cleanup bucket from source import; not a deliberate board." };
  }
  if (file.endsWith("_small.md")) {
    return { label: "Small Groups", note: "Catch-all bucket for low-count source groups." };
  }
  if (label.startsWith("(") && label.endsWith(")")) {
    return { label: label.slice(1, -1), note: "Catch-all source bucket." };
  }
  return null;
}

function setContextLinkBanner(message, { error = false } = {}) {
  const banner = $("#contextLinkBanner");
  if (!banner) return;
  banner.textContent = String(message || CONTEXT_LINK_BANNER_DEFAULT);
  banner.hidden = false;
  banner.classList.toggle("context-link-banner-error", !!error);
}

function clearContextLinkBanner() {
  const banner = $("#contextLinkBanner");
  if (!banner) return;
  banner.hidden = true;
  banner.textContent = "";
  banner.classList.remove("context-link-banner-error");
}

function _directItemLinkPayloadFromUrl() {
  const params = new URLSearchParams(window.location.search || "");
  const collectionId = (params.get("collection_id") || "").trim();
  if (collectionId) return null;
  const itemId = (params.get("item_id") || "").trim();
  if (!itemId) return null;
  const openRaw = (params.get("open") || "").trim().toLowerCase();
  const shouldAutoOpen = openRaw === "1" || openRaw === "true" || openRaw === "yes";
  return { itemId, shouldAutoOpen };
}

function _collectionScopeIdFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search || "");
    return String(params.get("collection_id") || "").trim();
  } catch {
    return "";
  }
}

function _setModalMediaStatus(message = "", { error = false } = {}) {
  const statusEl = $("#modalMediaStatus");
  if (!statusEl) return;
  const text = String(message || "").trim();
  statusEl.textContent = text;
  statusEl.hidden = !text;
  if (text && error) statusEl.setAttribute("data-state", "error");
  else statusEl.removeAttribute("data-state");
}

function _loadModalImageAsset(asset, seq) {
  const img = $("#modalImage");
  if (!img) return;
  const assetId = String(asset?.id || "").trim();
  const thumbUrl = asset?.thumb_path ? _mediaUrlForAsset(asset, "thumb") : "";
  const originalUrl = asset?.stored_path
    ? _mediaUrlForAsset(asset, "original")
    : (asset?.thumb_path ? _mediaUrlForAsset(asset, "original") : String(asset?.image_url || "").trim());

  const showUnavailable = () => {
    if (!_isCurrentModalLoad(assetId, seq)) return;
    img.removeAttribute("src");
    img.style.display = "none";
    _setModalMediaStatus("Image unavailable for this item.", { error: true });
  };

  const loadOriginalDirect = () => {
    if (!originalUrl) {
      showUnavailable();
      return;
    }
    _setModalMediaStatus("Loading image…");
    img.onload = () => {
      if (!_isCurrentModalLoad(assetId, seq)) return;
      img.style.display = "block";
      _setModalMediaStatus("");
      img.onload = null;
      img.onerror = null;
    };
    img.onerror = () => {
      if (!_isCurrentModalLoad(assetId, seq)) return;
      showUnavailable();
    };
    img.style.display = "none";
    img.src = originalUrl;
  };

  img.onload = null;
  img.onerror = null;
  img.style.display = "none";

  if (thumbUrl) {
    _setModalMediaStatus("Loading preview…");
    img.onload = () => {
      if (!_isCurrentModalLoad(assetId, seq)) return;
      img.style.display = "block";
      _setModalMediaStatus("");
      img.onload = null;
      img.onerror = null;
      if (originalUrl && originalUrl !== thumbUrl) {
        const preloader = new Image();
        preloader.onload = () => {
          if (!_isCurrentModalLoad(assetId, seq)) return;
          img.src = originalUrl;
        };
        preloader.onerror = () => {};
        preloader.src = originalUrl;
      }
    };
    img.onerror = () => {
      if (!_isCurrentModalLoad(assetId, seq)) return;
      loadOriginalDirect();
    };
    img.src = thumbUrl;
    return;
  }

  loadOriginalDirect();
}

function _loadModalVideoAsset(asset, seq, videoUrl) {
  const img = $("#modalImage");
  const video = $("#modalVideo");
  if (!video || !videoUrl) {
    _loadModalImageAsset(asset, seq);
    return;
  }
  let fallbackTimer = 0;
  const showPosterFallback = () => {
    if (!_isCurrentModalLoad(asset.id, seq)) return;
    window.clearTimeout(fallbackTimer);
    video.onerror = null;
    video.onloadedmetadata = null;
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.hidden = true;
    _loadModalImageAsset(asset, seq);
  };

  _setModalMediaStatus("Loading video…");
  if (img) {
    img.removeAttribute("src");
    img.style.display = "none";
    img.onload = null;
    img.onerror = null;
  }
  video.onerror = showPosterFallback;
  video.onloadedmetadata = () => {
    if (!_isCurrentModalLoad(asset.id, seq)) return;
    window.clearTimeout(fallbackTimer);
    _setModalMediaStatus("");
  };
  video.src = videoUrl;
  const poster = asset.thumb_path ? _mediaUrlForAsset(asset, "thumb") : "";
  if (poster) video.poster = poster;
  else video.removeAttribute("poster");
  video.hidden = false;
  video.load();
  fallbackTimer = window.setTimeout(() => {
    if (video.readyState === HTMLMediaElement.HAVE_NOTHING) showPosterFallback();
  }, 2200);
}

async function restoreDirectItemLinkFromUrl() {
  const payload = _directItemLinkPayloadFromUrl();
  if (!payload) return;
  if (state.modalAsset && String(state.modalAsset.id || "") === String(payload.itemId || "")) return;
  let asset = state.assets.find((a) => String(a?.id || "") === String(payload.itemId || ""));
  if (!asset) asset = await fetchAssetForModal(payload.itemId);
  if (!asset) {
    setContextLinkBanner("This item is not available in this session.", { error: true });
    return;
  }
  clearContextLinkBanner();
  if (!payload.shouldAutoOpen) return;
  await openModal(asset);
}

function applyCollectionScopeFromUrl() {
  const collectionId = _collectionScopeIdFromUrl();
  if (!collectionId) return;
  if (!state.actor) {
    setContextLinkBanner("Local owner mode is still starting; try again in a moment.", { error: true });
    return;
  }
  const col = state.collections.find((c) => String(c.id || "") === collectionId);
  if (!col) {
    setContextLinkBanner("This collection is not available.", { error: true });
    return;
  }
  state.currentSource = null;
  state.currentBoard = null;
  state.currentContentKind = null;
  clearCatalogFilter();
  setCollectionFilterIds([collectionId], { label: col ? col.name : "", nodeId: null });
  if (isCollaboratorActor()) state.sharedCollectionLandingId = collectionId;
  if (Array.isArray(state.catalogTree) && state.catalogTree.length) renderCatalogTree();
  else updateSidebarModeVisibility();
  clearContextLinkBanner();
}

function sourceKeyFromNode(node) {
  const id = String(node?.id || "");
  if (id.startsWith("source:")) return normalizeSourceKey(id.slice("source:".length));
  return normalizeSourceKey(node?.source || node?.label || "");
}

async function fetchAssetForModal(assetId) {
  if (!assetId) return null;
  const includeHidden = isOwner() ? "?include_hidden=1" : "";
  try {
    const data = await api(`/api/assets/${encodeURIComponent(assetId)}${includeHidden}`);
    if (data && data.asset) return data.asset;
  } catch (_) {
    // Fall through to legacy prefix lookup for compatibility.
  }
  try {
    const data = await api(`/api/assets?ids=${encodeURIComponent(String(assetId).slice(0, 8))}&limit=1${isOwner() ? "&include_hidden=1" : ""}`);
    const assets = data.assets || [];
    const exact = assets.find((a) => a.id === assetId);
    return exact || assets[0] || null;
  } catch (_) {
    return null;
  }
}

function isPdfFile(file) {
  if (!file) return false;
  return PDF_FILE_EXT_RE.test(file.name || "") || (file.type || "").toLowerCase() === "application/pdf";
}

function isImageFile(file) {
  if (!file) return false;
  return (file.type || "").startsWith("image/") || IMAGE_FILE_EXT_RE.test(file.name || "");
}

function isVideoFile(file) {
  if (!file) return false;
  return (file.type || "").startsWith("video/") || VIDEO_FILE_EXT_RE.test(file.name || "");
}

function setSingleFileSelection(input, file, stateKey) {
  state[stateKey] = file || null;
  if (!input) return;
  if (!file) { input.value = ""; return; }
  try { const dt = new DataTransfer(); dt.items.add(file); input.files = dt.files; } catch {}
}

function wireSingleFileDropZone(options) {
  const { zone, input } = options;
  if (!zone || !input) return;
  const prevent = (e) => { e.preventDefault(); e.stopPropagation(); };
  const busy = () => typeof options.isBusy === "function" ? !!options.isBusy() : false;
  ["dragenter", "dragover"].forEach((evt) => zone.addEventListener(evt, (e) => { prevent(e); if (!busy()) zone.classList.add("dragActive"); }));
  ["dragleave", "dragend"].forEach((evt) => zone.addEventListener(evt, (e) => { prevent(e); zone.classList.remove("dragActive"); }));
  zone.addEventListener("drop", (e) => {
    prevent(e); zone.classList.remove("dragActive");
    if (busy()) return;
    const file = e.dataTransfer?.files?.[0] || null;
    if (!file) return;
    if (!options.accept(file)) { if (options.invalidMessage) Shared.showToast(options.invalidMessage, { type: "error" }); return; }
    setSingleFileSelection(input, file, options.stateKey);
    if (typeof options.onSelected === "function") options.onSelected(file);
  });
}

function parseTagInput(raw) {
  const out = [];
  const seen = new Set();
  for (const part of String(raw || "").split(/[,\n;]+/)) {
    const tag = part.trim();
    if (!tag) continue;
    const key = tag.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(tag);
  }
  return out;
}

function _ingestTagDisplayLabel(raw) {
  return String(raw || "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function renderIngestTagChips(inputId, chipsId) {
  const input = document.getElementById(inputId);
  const wrap = document.getElementById(chipsId);
  if (!input || !wrap) return;
  wrap.innerHTML = "";
  if (!INGEST_TAG_GROUPS.length) return;
  const selected = new Set(parseTagInput(input.value).map((t) => t.toLowerCase()));
  for (const group of INGEST_TAG_GROUPS) {
    const section = document.createElement("section");
    section.className = "ingestTagGroup";

    const heading = document.createElement("div");
    heading.className = "ingestTagGroupLabel";
    heading.textContent = group.label;
    section.appendChild(heading);

    const row = document.createElement("div");
    row.className = "ingestTagGroupChips";
    for (const value of group.tags) {
      const tag = String(value || "").trim();
      if (!tag) continue;
      const key = tag.toLowerCase();
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = selected.has(key) ? "ingestTagChip active" : "ingestTagChip";
      btn.textContent = _ingestTagDisplayLabel(tag);
      btn.addEventListener("click", () => {
        const tags = parseTagInput(input.value);
        const idx = tags.findIndex((t) => t.toLowerCase() === key);
        if (idx >= 0) tags.splice(idx, 1);
        else tags.push(tag);
        input.value = tags.join(", ");
        renderIngestTagChips(inputId, chipsId);
      });
      row.appendChild(btn);
    }
    section.appendChild(row);
    wrap.appendChild(section);
  }
}

function refreshIngestTagPickers() {
  renderIngestTagChips("scanImportTagsInput", "scanImportTagChips");
  renderIngestTagChips("photoImportTagsInput", "photoImportTagChips");
  renderIngestTagChips("videoImportTagsInput", "videoImportTagChips");
}

function _uniqNonEmpty(values) {
  const out = [];
  const seen = new Set();
  for (const raw of (values || [])) {
    const v = `${raw || ""}`.trim();
    if (!v || seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

function getCatalogFilterFiles() {
  return _uniqNonEmpty([...(state.currentCatalogFiles || []), state.currentCatalogFile || ""]);
}

function hasCatalogFilter() {
  return getCatalogFilterFiles().length > 0;
}

function clearCatalogFilter() {
  state.currentCatalogFile = null;
  state.currentCatalogFiles = [];
  state.currentCatalogLabel = "";
}

function setCatalogFilter(files, { label = "", nodeId = null } = {}) {
  const uniq = _uniqNonEmpty(files);
  if (!uniq.length) {
    clearCatalogFilter();
    state.currentTreeNodeId = null;
  } else {
    state.currentCatalogFile = uniq[0];
    state.currentCatalogFiles = uniq;
    state.currentCatalogLabel = label || "";
    state.currentTreeNodeId = nodeId;
  }
}

function getCollectionFilterIds() {
  return _uniqNonEmpty([...(state.currentCollectionIds || []), state.currentCollection || ""]);
}

function isExplorerViewActive() {
  const explorerView = $("#explorerView");
  return !!(explorerView && !explorerView.hidden);
}

function getReviewScopeInfo() {
  const collectionIds = getCollectionFilterIds();
  if (!collectionIds.length) {
    return {
      hasCollectionScope: false,
      collectionIds: [],
      label: "Entire library",
    };
  }
  if (collectionIds.length === 1) {
    const onlyId = collectionIds[0];
    const col = state.collections.find((c) => c.id === onlyId);
    return {
      hasCollectionScope: true,
      collectionIds,
      label: col?.name || state.currentCollectionLabel || onlyId.slice(0, 8),
    };
  }
  return {
    hasCollectionScope: true,
    collectionIds,
    label: state.currentCollectionLabel || `${collectionIds.length} collections`,
  };
}

function _currentTrackFilterValues() {
  const facetValues = getClassificationFacetValues("track");
  if (facetValues.length) return facetValues;
  if (String(state.currentClassificationAxis || "").trim() !== "track") return [];
  return String(state.currentClassificationValue || "")
    .split(",")
    .map((value) => String(value || "").trim())
    .filter(Boolean);
}

function shouldExcludeIrrelevantFromUsableScope() {
  if (state.showDiscarded || state.triageFilter) return false;
  return !_currentTrackFilterValues().includes("irrelevant");
}

function appendUsableTrackExclusionParam(params) {
  if (shouldExcludeIrrelevantFromUsableScope()) params.set("exclude_tracks", "irrelevant");
}

function isIrrelevantDiscardedReviewScope(value = state.triageFilter) {
  return value === "irrelevant-discarded";
}

function appendReviewScopeParams(params, { includeHiddenForOwner = true } = {}) {
  if (state.triageFilter === "needs-comment") {
    params.set("needs_annotation", "1");
    if (includeHiddenForOwner || isOwner()) params.set("include_hidden", "1");
  } else if (_isHiddenReviewQueue()) {
    _appendHiddenReviewQueueParams(params);
    if (includeHiddenForOwner || isOwner()) params.set("include_hidden", "1");
  } else if (state.triageFilter === "flagged") {
    params.set("flagged", "1");
    if (includeHiddenForOwner || isOwner()) params.set("include_hidden", "1");
  } else if (isIrrelevantDiscardedReviewScope()) {
    params.set("review_status", "irrelevant_discarded");
    if (includeHiddenForOwner || isOwner()) params.set("include_hidden", "1");
  } else if (state.triageFilter) {
    params.set("triage_status", state.triageFilter);
  }
}

function _reviewItemMatchesCurrentScope(item) {
  if (!item) return false;
  const trackValues = _currentTrackFilterValues();
  if (trackValues.length) {
    const effectiveTrack = _effectiveClassificationTrack(item.classification_review || {});
    if (!effectiveTrack || !trackValues.includes(effectiveTrack)) return false;
  }
  return true;
}

function _buildCurrentAssetQueryParams({ limit, offset = 0, ids = null } = {}) {
  const params = new URLSearchParams();
  if (limit != null) params.set("limit", String(limit));
  params.set("offset", String(offset));

  if (Array.isArray(ids) && ids.length) {
    params.set("ids", ids.join(","));
  } else {
    const semQ = semanticQueryFromInput(state.q);
    if (semQ) {
      params.set("q", `sem:${semQ}`);
    } else if (state.q) {
      params.set("q", state.q);
    }
    if (state.currentSource) params.set("source", state.currentSource);
    if (state.currentBoard) params.set("board", state.currentBoard);
    if (state.currentContentKind) params.set("content_kind", state.currentContentKind);
    appendClassificationFacetParams(params);
    const collectionIds = getCollectionFilterIds();
    if (collectionIds.length) params.set("collection_id", collectionIds.join(","));
  }

  appendReviewScopeParams(params);
  appendShowDiscardedParam(params);
  appendUsableTrackExclusionParam(params);
  return params;
}

function _buildCurrentCatalogQueryParams({ limit, offset = 0 } = {}) {
  const params = new URLSearchParams();
  const catalogFiles = getCatalogFilterFiles();
  for (const file of catalogFiles) params.append("file", file);
  if (limit != null) params.set("limit", String(limit));
  params.set("offset", String(offset));
  appendReviewScopeParams(params);
  appendShowDiscardedParam(params);
  appendUsableTrackExclusionParam(params);
  return params;
}

async function _fetchAssetsByIds(ids) {
  const orderedIds = _uniqNonEmpty(ids || []);
  if (!orderedIds.length) return [];
  const byId = new Map();
  const chunkSize = 80;
  for (let i = 0; i < orderedIds.length; i += chunkSize) {
    const chunk = orderedIds.slice(i, i + chunkSize);
    const params = _buildCurrentAssetQueryParams({ limit: chunk.length + 5, ids: chunk });
    const data = await api(`/api/assets?${params}`);
    for (const asset of (data.assets || [])) {
      if (asset && asset.id) byId.set(asset.id, asset);
    }
  }
  return orderedIds.map((id) => byId.get(id)).filter(Boolean);
}

async function _fetchAllAssetsForCurrentScope() {
  const catalogFiles = getCatalogFilterFiles();
  const semQ = semanticQueryFromInput(state.q);
  if (semQ) {
    return {
      items: [...state.assets],
      scopeTotal: Number.isFinite(Number(state.totalCount)) ? Number(state.totalCount) : state.assets.length,
    };
  }

  if (Array.isArray(state.reviewSeedIds) && state.reviewSeedIds.length) {
    const items = await _fetchAssetsByIds(state.reviewSeedIds);
    return { items, scopeTotal: items.length };
  }

  const pageSize = 500;
  const items = [];
  let offset = 0;
  let total = 0;
  while (true) {
    let data;
    if (catalogFiles.length) {
      const params = _buildCurrentCatalogQueryParams({ limit: pageSize, offset });
      data = await api(`/api/catalog/items?${params}`);
    } else {
      const params = _buildCurrentAssetQueryParams({ limit: pageSize, offset });
      data = await api(`/api/assets?${params}`);
    }
    const batch = data.assets || [];
    items.push(...batch);
    total = Number(data.total || items.length);
    if (!data.has_more || !batch.length) break;
    offset += batch.length;
  }
  return { items, scopeTotal: total || items.length };
}

function _reviewActorLabel() {
  return "Reviewer: Jim";
}

function _actorRoleLabel(role) {
  const clean = String(role || "").trim().toLowerCase();
  if (!clean) return "";
  return clean
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function _actorContextLabel() {
  const actor = state.actor || null;
  if (!actor) return "Viewing as visitor";
  const name = String(actor.name || "Unknown").trim() || "Unknown";
  const roleLabel = _actorRoleLabel(actor.role);
  if (!roleLabel) return `Viewing as ${name}`;
  const lowerName = name.toLowerCase();
  const lowerRole = roleLabel.toLowerCase();
  if (lowerName.endsWith(`(${lowerRole})`)) return `Viewing as ${name}`;
  return `Viewing as ${name} (${roleLabel})`;
}

function updateActorContextChips() {
  for (const id of ["actorContextChip", "modalActorChip"]) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.hidden = true;
    el.textContent = "";
  }
}

const ITEM_VIEW_OPTIONS = {
  usable: {
    triageFilter: "",
    showDiscarded: false,
    emptyLabel: "No usable items match the current scope.",
  },
  all: {
    triageFilter: "",
    showDiscarded: true,
    emptyLabel: "No items match the current scope.",
  },
  keeper: {
    triageFilter: "keeper",
    showDiscarded: false,
    emptyLabel: "No keepers match the current scope.",
  },
  flagged: {
    triageFilter: "flagged",
    showDiscarded: false,
    emptyLabel: "No flagged items match the current scope.",
  },
  hidden: {
    triageFilter: "hidden",
    showDiscarded: false,
    emptyLabel: "No discarded items match the current scope.",
  },
  "irrelevant-discarded": {
    triageFilter: "irrelevant-discarded",
    showDiscarded: false,
    emptyLabel: "No irrelevant or discarded items match the current scope.",
  },
};

function isReviewStatusFilterActive(status) {
  return state.triageFilter === status;
}

function updateReviewScopeChips() {
  const scope = getReviewScopeInfo();
  const chipText = `Scope: ${scope.label}`;
  const headerChip = $("#reviewScopeChip");
  if (headerChip) headerChip.textContent = chipText;
  const oneByOneActorChip = $("#reviewActorChip");
  if (oneByOneActorChip) oneByOneActorChip.textContent = _reviewActorLabel();
}

function confirmGlobalHideBulk(count) {
  const total = Math.max(0, Number(count || 0));
  const noun = total === 1 ? "item" : "items";
  return window.confirm(
    `Discard ${total} ${noun}?\n\n`
    + "Discarded items leave ordinary browsing across the library.\n"
    + "You can restore them later from Browse → Review Status → Irrelevant / Discarded."
  );
}

function appendShowDiscardedParam(params) {
  if (isOwner() && state.showDiscarded) params.set("include_hidden", "1");
}

function hasCollectionFilter() {
  return getCollectionFilterIds().length > 0;
}

function hasClassificationFilter() {
  return getClassificationFacetEntries().length > 0 || !!String(state.currentClassificationAxis || "").trim();
}

function _classificationFacetKey(axis, value = "") {
  return `${String(axis || "").trim()}:${String(value || "").trim()}`;
}

function getClassificationFacetValues(axis) {
  const cleanAxis = String(axis || "").trim();
  if (!cleanAxis) return [];
  const values = state.classificationFacets?.[cleanAxis];
  return Array.isArray(values)
    ? values.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
}

function getClassificationFacetEntries() {
  const facets = state.classificationFacets || {};
  const entries = [];
  for (const [axis, values] of Object.entries(facets)) {
    const cleanAxis = String(axis || "").trim();
    if (!cleanAxis) continue;
    if (Array.isArray(values) && values.length) {
      for (const value of values) {
        const cleanValue = String(value || "").trim();
        if (cleanValue) entries.push({ axis: cleanAxis, value: cleanValue });
      }
    } else {
      entries.push({ axis: cleanAxis, value: "" });
    }
  }
  return entries;
}

function classificationFacetIsActive(axis, value = "") {
  const cleanAxis = String(axis || "").trim();
  const cleanValue = String(value || "").trim();
  if (!cleanAxis) return false;
  const values = getClassificationFacetValues(cleanAxis);
  if (!cleanValue) return Object.prototype.hasOwnProperty.call(state.classificationFacets || {}, cleanAxis);
  return values.includes(cleanValue);
}

function classificationFacetLabel(axis, value = "") {
  const key = _classificationFacetKey(axis, value);
  const label = String(state.classificationFacetLabels?.[key] || "").trim();
  if (label) return label;
  return String(value || axis || "").replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function _syncLegacyClassificationStateFromFacets() {
  const entries = getClassificationFacetEntries();
  if (entries.length === 1) {
    const only = entries[0];
    state.currentClassificationAxis = only.axis;
    state.currentClassificationValue = only.value || null;
    state.currentClassificationLabel = classificationFacetLabel(only.axis, only.value);
    return;
  }
  state.currentClassificationAxis = null;
  state.currentClassificationValue = null;
  state.currentClassificationLabel = entries.length
    ? entries.map((entry) => classificationFacetLabel(entry.axis, entry.value)).join(", ")
    : "";
}

function appendClassificationFacetParams(params) {
  const entries = getClassificationFacetEntries();
  if (!entries.length && state.currentClassificationAxis) {
    params.set("classification_axis", state.currentClassificationAxis);
    if (state.currentClassificationValue) params.set("classification_value", state.currentClassificationValue);
    return;
  }
  for (const entry of entries) {
    params.append("facet", entry.value ? `${entry.axis}:${entry.value}` : entry.axis);
  }
}

function clearClassificationFilter() {
  state.classificationFacets = {};
  state.classificationFacetLabels = {};
  state.currentClassificationAxis = null;
  state.currentClassificationValue = null;
  state.currentClassificationLabel = "";
}

function setClassificationFilter(axis, value = "", { label = "", nodeId = null } = {}) {
  const cleanAxis = String(axis || "").trim();
  const cleanValue = String(value || "").trim();
  if (!cleanAxis) {
    clearClassificationFilter();
    state.currentTreeNodeId = null;
    return;
  }
  state.classificationFacets = { [cleanAxis]: cleanValue ? [cleanValue] : [] };
  state.classificationFacetLabels = {};
  if (label) state.classificationFacetLabels[_classificationFacetKey(cleanAxis, cleanValue)] = label;
  _syncLegacyClassificationStateFromFacets();
  state.currentTreeNodeId = nodeId;
}

function toggleClassificationFacet(axis, value, { label = "" } = {}) {
  const cleanAxis = String(axis || "").trim();
  const cleanValue = String(value || "").trim();
  if (!cleanAxis || !cleanValue) return;
  const facets = { ...(state.classificationFacets || {}) };
  const currentValues = Array.isArray(facets[cleanAxis]) ? [...facets[cleanAxis]] : [];
  const existingIdx = currentValues.indexOf(cleanValue);
  if (existingIdx >= 0) {
    currentValues.splice(existingIdx, 1);
  } else {
    currentValues.push(cleanValue);
  }
  if (currentValues.length) facets[cleanAxis] = currentValues;
  else delete facets[cleanAxis];
  state.classificationFacets = facets;
  state.classificationFacetLabels = { ...(state.classificationFacetLabels || {}) };
  const key = _classificationFacetKey(cleanAxis, cleanValue);
  if (existingIdx >= 0) delete state.classificationFacetLabels[key];
  else state.classificationFacetLabels[key] = label || cleanValue;
  _syncLegacyClassificationStateFromFacets();
  state.currentTreeNodeId = null;
}

function clearClassificationFacetAxis(axis) {
  const cleanAxis = String(axis || "").trim();
  if (!cleanAxis) return;
  const facets = { ...(state.classificationFacets || {}) };
  delete facets[cleanAxis];
  state.classificationFacets = facets;
  const labels = { ...(state.classificationFacetLabels || {}) };
  for (const key of Object.keys(labels)) {
    if (key.startsWith(`${cleanAxis}:`)) delete labels[key];
  }
  state.classificationFacetLabels = labels;
  _syncLegacyClassificationStateFromFacets();
}

function clearCollectionFilter() {
  state.currentCollection = null;
  state.currentCollectionIds = [];
  state.currentCollectionLabel = "";
  syncCollectionPdfExportButton();
}

function isAllItemsScopeActive() {
  return !state.currentSource && !state.currentBoard && !state.currentContentKind
    && !hasCollectionFilter() && !hasCatalogFilter() && !hasClassificationFilter();
}

function setCollectionFilterIds(ids, { label = "", nodeId = null } = {}) {
  const uniq = _uniqNonEmpty(ids);
  if (!uniq.length) {
    clearCollectionFilter();
    state.currentTreeNodeId = null;
  } else {
    state.currentCollection = uniq.length === 1 ? uniq[0] : null;
    state.currentCollectionIds = uniq;
    state.currentCollectionLabel = label || "";
    state.currentTreeNodeId = nodeId;
  }
  syncCollectionPdfExportButton();
}

function isCollaboratorActor() {
  return false;
}

function _activeSharedCollectionLandingId() {
  const landingId = String(state.sharedCollectionLandingId || "").trim();
  if (!landingId || !isCollaboratorActor()) return "";
  const selected = getCollectionFilterIds();
  return selected.length === 1 && selected[0] === landingId ? landingId : "";
}

function _isFocusedSharedCollectionSession() {
  return !!_activeSharedCollectionLandingId();
}

function shouldIgnorePostBrowseUnlockTreeClick() {
  if (!isCollaboratorActor()) return false;
  if (!state.lastCollaboratorBrowseUnlockAt) return false;
  const elapsed = Date.now() - state.lastCollaboratorBrowseUnlockAt;
  if (elapsed < 0 || elapsed > 500) return false;
  // Only guard while collaborator is still in collection scope.
  return hasCollectionFilter();
}

function _findCollectionsGroupNode() {
  const tree = Array.isArray(state.catalogTree) ? state.catalogTree : [];
  return tree.find((node) => node && node.type === "collections_group") || null;
}

function _setCollaboratorSharedCollectionsScope() {
  if (!isCollaboratorActor()) return false;
  state.sharedCollectionLandingId = "";
  const collectionsNode = _findCollectionsGroupNode();
  if (!collectionsNode) return false;
  const collectionIds = collectDescendantCollectionIds(collectionsNode);
  if (!collectionIds.length) return false;

  resetTriageFilter();
  state.currentSource = null;
  state.currentBoard = null;
  state.currentContentKind = null;
  clearCatalogFilter();
  setCollectionFilterIds(collectionIds, { label: "Shared Collections", nodeId: collectionsNode.id });
  state.currentTreeNodeId = collectionsNode.id;
  state.expandedTreeNodes.add("collections");
  return true;
}

function _applyCollaboratorCollectionsDefaultScope() {
  if (!isCollaboratorActor()) return;
  if (state.collaboratorDefaultScopeApplied) return;
  state.collaboratorDefaultScopeApplied = true;

  const hasExistingScope = !isAllItemsScopeActive()
    || !!state.triageFilter
    || !!(state.q && state.q.trim())
    || !!(state.chatItemIds && state.chatItemIds.length);
  if (hasExistingScope) return;

  if (!_setCollaboratorSharedCollectionsScope()) return;
  state.expandedTreeNodes.add("collections");
  renderCatalogTree();
}

function collectDescendantCatalogFiles(node) {
  const files = [];
  const stack = [node];
  while (stack.length) {
    const cur = stack.pop();
    if (!cur || typeof cur !== "object") continue;
    if (cur.file) files.push(cur.file);
    const children = Array.isArray(cur.children) ? cur.children : [];
    for (const child of children) stack.push(child);
  }
  return _uniqNonEmpty(files);
}

function collectDescendantCollectionIds(node) {
  const ids = [];
  const stack = [node];
  while (stack.length) {
    const cur = stack.pop();
    if (!cur || typeof cur !== "object") continue;
    if (cur.collection_id) ids.push(cur.collection_id);
    const children = Array.isArray(cur.children) ? cur.children : [];
    for (const child of children) stack.push(child);
  }
  return _uniqNonEmpty(ids);
}

function _setTreeNodeExpanded(nodeKey, toggleEl, childrenEl, open) {
  if (open) {
    childrenEl.classList.add("open");
    toggleEl.classList.add("expanded");
    state.expandedTreeNodes.add(nodeKey);
  } else {
    childrenEl.classList.remove("open");
    toggleEl.classList.remove("expanded");
    state.expandedTreeNodes.delete(nodeKey);
  }
}

function _toggleTreeNodeExpanded(nodeKey, toggleEl, childrenEl) {
  _setTreeNodeExpanded(nodeKey, toggleEl, childrenEl, !childrenEl.classList.contains("open"));
}

function _wireTreeArrowToggle(toggleEl, nodeKey, childrenEl) {
  const arrow = toggleEl.querySelector(".tree-arrow");
  if (!arrow) return;
  arrow.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    _toggleTreeNodeExpanded(nodeKey, toggleEl, childrenEl);
  });
}

function _scanPageFromRef(sourceRef) {
  const m = String(sourceRef || "").match(/#p(\d+)$/i);
  if (!m) return null;
  const page = parseInt(m[1], 10);
  return Number.isFinite(page) && page > 0 ? page : null;
}

function _scanPdfHrefForAsset(asset) {
  if (!asset || !asset.id) return "#";
  let page = 1;
  if (Array.isArray(state.modalScanPages) && state.modalScanPages.length) {
    const idx = state.modalScanPages.indexOf(asset.id);
    if (idx >= 0) page = idx + 1;
  }
  return `${_B}/api/scan/doc-pdf?asset_id=${encodeURIComponent(asset.id)}#page=${page}`;
}

function sourceLinkCheckInfo(asset) {
  const candidate = asset?.source_link_candidate || {};
  const status = String(candidate.fetch_status || "").trim();
  const httpStatus = Number(candidate.http_status || 0);
  const checkedAt = String(candidate.created_at || "").trim();
  const error = String(candidate.error || "").trim();
  if (!status) {
    return {
      tone: "unknown",
      label: "Source not checked",
      note: "Open the link before discarding; this may be fixable.",
      checkedAt,
    };
  }
  if (status === "fetched") {
    return {
      tone: "ok",
      label: httpStatus ? `Source reachable (${httpStatus})` : "Source reachable",
      note: "This link worked during the latest source check.",
      checkedAt,
    };
  }
  if (status === "http_error") {
    return {
      tone: "bad",
      label: httpStatus ? `HTTP ${httpStatus}` : "HTTP error",
      note: "The source responded with an error. It may still work in a logged-in browser.",
      checkedAt,
      error,
    };
  }
  if (["browser_error", "browser_timeout", "network_error", "error", "redirect_limit"].includes(status)) {
    return {
      tone: "unknown",
      label: status.replace(/_/g, " "),
      note: "The check failed, but that does not prove the source link is broken.",
      checkedAt,
      error,
    };
  }
  if (status === "platform_wrapper_skipped") {
    return {
      tone: "unknown",
      label: "Source check skipped",
      note: "Platform links often need an authenticated browser check.",
      checkedAt,
    };
  }
  if (status === "no_url" || status === "unsafe_url" || status === "browser_unsafe_url") {
    return {
      tone: "bad",
      label: status.replace(/_/g, " "),
      note: "There is no safe source URL to open from the app.",
      checkedAt,
      error,
    };
  }
  return {
    tone: "unknown",
    label: status.replace(/_/g, " "),
    note: "Open the source before deciding whether to discard.",
    checkedAt,
    error,
  };
}

function formatSourceCheckTooltip(info) {
  if (!info) return "";
  const parts = [info.note || ""];
  if (info.checkedAt) parts.push(`Last checked: ${info.checkedAt}`);
  if (info.error) parts.push(info.error);
  return parts.filter(Boolean).join("\n");
}

function isBrokenSourceDiscardAsset(asset) {
  return String(asset?.flagged_note || "").trim().toLowerCase() === "broken source link";
}

function renderModalSourceLinks(asset) {
  if (!asset) return;
  const ref = asset.source_ref || "";
  const isHttpRef = ref.startsWith("http://") || ref.startsWith("https://");
  const siteUrl = asset.source_url || "";
  const isHttpSite = siteUrl.startsWith("http://") || siteUrl.startsWith("https://");
  const brokenSourceDiscarded = isBrokenSourceDiscardAsset(asset);

  const sourceLink = $("#sourceLink");
  if (sourceLink) {
    if (asset.source === "scan" && ref) {
      sourceLink.href = _scanPdfHrefForAsset(asset);
      sourceLink.textContent = "Open PDF";
      sourceLink.hidden = false;
    } else if (isHttpRef) {
      sourceLink.href = ref;
      sourceLink.textContent = `Open ${asset.source || "original"}`;
      sourceLink.hidden = false;
    } else if (isHttpSite) {
      sourceLink.href = siteUrl;
      sourceLink.textContent = `Open ${asset.source || "original"}`;
      sourceLink.hidden = false;
    } else {
      sourceLink.hidden = true;
    }
  }

  // Source site link — only show when primary link used source_ref (not source_url)
  const sourceSiteRow = $("#sourceSiteRow");
  const sourceSiteLink = $("#sourceSiteLink");
  const showSiteLink = sourceSiteRow && sourceSiteLink && isHttpSite && isHttpRef;
  if (showSiteLink) {
    sourceSiteLink.href = siteUrl;
    sourceSiteLink.textContent = `Original site (${sourceHost(siteUrl) || siteUrl}) ↗`;
    sourceSiteRow.hidden = false;
  } else if (sourceSiteRow) {
    sourceSiteRow.hidden = true;
  }

  const checkInfo = sourceLinkCheckInfo(asset);
  const sourceCheckStatus = $("#modalSourceCheckStatus");
  if (sourceCheckStatus) {
    sourceCheckStatus.textContent = checkInfo.label;
    sourceCheckStatus.title = formatSourceCheckTooltip(checkInfo);
    sourceCheckStatus.dataset.tone = checkInfo.tone;
    sourceCheckStatus.hidden = asset.source === "scan" || !(isHttpRef || isHttpSite);
  }

  const brokenSourceBtn = $("#modalBrokenSourceBtn");
  if (brokenSourceBtn) {
    brokenSourceBtn.hidden = !(isOwner() && asset.source !== "scan" && (isHttpRef || isHttpSite) && !brokenSourceDiscarded);
    brokenSourceBtn.disabled = false;
    brokenSourceBtn.textContent = checkInfo.tone === "bad"
      ? "Broken link · discard item"
      : "Mark source unusable · discard";
    brokenSourceBtn.title = checkInfo.note || "";
    brokenSourceBtn.onclick = () => { void markModalBrokenSourceLink(asset); };
  }

  const restoreBrokenSourceBtn = $("#modalRestoreBrokenSourceBtn");
  if (restoreBrokenSourceBtn) {
    restoreBrokenSourceBtn.hidden = !(isOwner() && brokenSourceDiscarded && asset.source !== "scan" && (isHttpRef || isHttpSite));
    restoreBrokenSourceBtn.disabled = false;
    restoreBrokenSourceBtn.title = "Clear the broken-source flag and restore this item to ordinary browsing. The original source link is kept.";
    restoreBrokenSourceBtn.onclick = () => { void restoreModalBrokenSourceLink(asset); };
  }

  const sourceLinksWrap = $("#modalSourceLinks");
  if (sourceLinksWrap) {
    const primaryVisible = !!(sourceLink && !sourceLink.hidden);
    const secondaryVisible = !!(sourceSiteRow && !sourceSiteRow.hidden);
    const brokenActionVisible = !!(brokenSourceBtn && !brokenSourceBtn.hidden);
    const restoreActionVisible = !!(restoreBrokenSourceBtn && !restoreBrokenSourceBtn.hidden);
    sourceLinksWrap.hidden = !(primaryVisible || secondaryVisible || brokenActionVisible || restoreActionVisible);
  }

}

async function markModalBrokenSourceLink(asset) {
  if (!asset?.id || !isOwner()) return;
  const checkInfo = sourceLinkCheckInfo(asset);
  const caution = checkInfo.tone === "bad"
    ? "The latest source check found a source-link problem."
    : "The app has not confirmed this source is broken. If the link opens in Safari, this is probably fixable and should not be discarded as broken.";
  if (!window.confirm(`${caution}\n\nDiscard this item from ordinary browsing and mark its source link unusable?`)) return;
  const button = $("#modalBrokenSourceBtn");
  if (button) button.disabled = true;
  try {
    const data = await api(`/api/assets/${encodeURIComponent(asset.id)}/broken-source`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (data.asset) replaceAssetInState(data.asset);
    closeModal();
    await Promise.all([loadAssets(), loadCatalogTree()]);
    Shared.showToast("Broken source link flagged and discarded.", { type: "success", duration: 3000 });
  } catch (e) {
    Shared.showToast(`Unable to discard broken link: ${formatApiError(e)}`, { type: "error", duration: 3200 });
  } finally {
    if (button) button.disabled = false;
  }
}

async function restoreModalBrokenSourceLink(asset) {
  if (!asset?.id || !isOwner()) return;
  if (!window.confirm("Clear the broken-source discard mark and restore this item to ordinary browsing?\n\nThe original source link will be kept.")) return;
  const button = $("#modalRestoreBrokenSourceBtn");
  if (button) button.disabled = true;
  try {
    const data = await api(`/api/assets/${encodeURIComponent(asset.id)}/broken-source/restore`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (data.asset) {
      replaceAssetInState(data.asset);
      await openModal(data.asset, { hydrate: false });
    }
    await Promise.all([loadAssets(), loadCatalogTree(), loadCollections()]);
    Shared.showToast("Source restored; item is back in ordinary browsing.", { type: "success", duration: 3000 });
  } catch (e) {
    Shared.showToast(`Unable to restore source item: ${formatApiError(e)}`, { type: "error", duration: 3200 });
  } finally {
    if (button) button.disabled = false;
  }
}

function _readSidebarHiddenPref() {
  try {
    return localStorage.getItem(SIDEBAR_VISIBILITY_KEY) === "1";
  } catch {
    return false;
  }
}

function _writeSidebarHiddenPref(hidden) {
  try {
    localStorage.setItem(SIDEBAR_VISIBILITY_KEY, hidden ? "1" : "0");
  } catch {
    // no-op
  }
}

function _readViewModePref() {
  try {
    const raw = (localStorage.getItem(VIEW_MODE_KEY) || "").trim().toLowerCase();
    return raw === "explorer" ? "explorer" : "grid";
  } catch {
    return "grid";
  }
}

function _writeViewModePref(mode) {
  try {
    localStorage.setItem(VIEW_MODE_KEY, mode === "explorer" ? "explorer" : "grid");
  } catch {
    // no-op
  }
}

function _readViewModeFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search || "");
    const raw = (params.get("view") || "").trim().toLowerCase();
    if (raw === "explorer") return "explorer";
    if (raw === "grid") return "grid";
    return "";
  } catch {
    return "";
  }
}

function _writeViewModeToUrl(mode) {
  try {
    const url = new URL(window.location.href);
    if (mode === "explorer") {
      url.searchParams.set("view", "explorer");
    } else {
      url.searchParams.delete("view");
    }
    window.history.replaceState({}, "", url.toString());
  } catch {
    // no-op
  }
}

function applySidebarVisibility() {
  const layout = $(".layout");
  const sidebar = $("aside.sidebar");
  const collapseBtn = $("#sidebarCollapseHandle");
  const expandBtn = $("#sidebarExpandHandle");
  const resizeHandle = $("#sidebarResizeHandle");
  if (layout) layout.classList.toggle("sidebar-hidden", state.sidebarHidden);
  if (sidebar) sidebar.hidden = !!state.sidebarHidden;
  if (collapseBtn) collapseBtn.hidden = !!state.sidebarHidden;
  if (expandBtn) expandBtn.hidden = !state.sidebarHidden;
  if (resizeHandle) resizeHandle.hidden = !!state.sidebarHidden || !_canResizeSidebar();
}

function _resizeActiveExplorer() {
  if (state.view !== "explorer" || !_ExplorerImpl || typeof _ExplorerImpl.resize !== "function") return;
  try {
    _ExplorerImpl.resize();
  } catch {
    // no-op
  }
}

function _nudgeLayoutAfterSidebarChange() {
  const layout = $(".layout");
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    try {
      window.dispatchEvent(new Event("resize"));
    } catch {
      // no-op
    }
    _resizeActiveExplorer();
  };
  if (layout) {
    const onTransitionEnd = (event) => {
      if (event.target !== layout) return;
      layout.removeEventListener("transitionend", onTransitionEnd);
      finish();
    };
    layout.addEventListener("transitionend", onTransitionEnd);
    setTimeout(() => {
      layout.removeEventListener("transitionend", onTransitionEnd);
      finish();
    }, 260);
    return;
  }
  setTimeout(finish, 220);
}

function setSidebarHidden(hidden, { persist = true } = {}) {
  state.sidebarHidden = !!hidden;
  applySidebarVisibility();
  _nudgeLayoutAfterSidebarChange();
  if (persist) _writeSidebarHiddenPref(state.sidebarHidden);
}

function wireSidebarToggle() {
  const collapseBtn = $("#sidebarCollapseHandle");
  const expandBtn = $("#sidebarExpandHandle");
  setSidebarHidden(_readSidebarHiddenPref(), { persist: false });
  if (collapseBtn) {
    collapseBtn.addEventListener("click", () => {
      setSidebarHidden(true);
    });
  }
  if (expandBtn) {
    expandBtn.addEventListener("click", () => {
      setSidebarHidden(false);
    });
  }
}

function _canResizeSidebar() {
  return window.matchMedia("(min-width: 901px) and (hover: hover) and (pointer: fine)").matches;
}

function _readSidebarWidthPref() {
  try {
    const raw = window.localStorage.getItem(SIDEBAR_WIDTH_KEY);
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return null;
    return Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, parsed));
  } catch {
    return null;
  }
}

function _writeSidebarWidthPref(width) {
  try {
    if (Number.isFinite(width)) window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(Math.round(width)));
  } catch {
    // no-op
  }
}

function _applySidebarWidth(width, { persist = true } = {}) {
  const next = Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, Number(width) || SIDEBAR_MIN_WIDTH));
  document.documentElement.style.setProperty("--sidebar-width", `${next}px`);
  if (persist) _writeSidebarWidthPref(next);
}

function wireSidebarResize() {
  const handle = $("#sidebarResizeHandle");
  const layout = $(".layout");
  const applySavedWidth = () => {
    const saved = _readSidebarWidthPref();
    _applySidebarWidth(saved || 240, { persist: false });
    applySidebarVisibility();
  };
  applySavedWidth();
  window.addEventListener("resize", applySavedWidth);
  if (!handle || !layout) return;
  let dragging = false;
  const onPointerMove = (event) => {
    if (!dragging || !_canResizeSidebar()) return;
    const width = event.clientX - layout.getBoundingClientRect().left;
    _applySidebarWidth(width);
  };
  const stopDrag = () => {
    if (!dragging) return;
    dragging = false;
    layout.classList.remove("sidebar-resizing");
    document.body.style.cursor = "";
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", stopDrag);
    window.removeEventListener("pointercancel", stopDrag);
  };
  handle.addEventListener("pointerdown", (event) => {
    if (!_canResizeSidebar() || state.sidebarHidden) return;
    dragging = true;
    layout.classList.add("sidebar-resizing");
    document.body.style.cursor = "col-resize";
    handle.setPointerCapture?.(event.pointerId);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopDrag);
    window.addEventListener("pointercancel", stopDrag);
    event.preventDefault();
  });
}

// ─── Asset loading ─────────────────────────────────────────────────────────────

async function loadAssets(opts = {}) {
  if (state.loadingAssets) {
    if (!opts.append) state.pendingAssetsReload = true;
    return;
  }
  state.pendingAssetsReload = false;
  const append = opts.append || false;
  if (!append) { state.offset = 0; }

  state.loadingAssets = true;
  updateLoadMoreBtn();
  if (append) updateStats();
  const seq = ++state.assetsRequestSeq;

  if (!append) renderSkeletons();

  const params = new URLSearchParams();
  params.set("limit", ASSETS_PAGE_SIZE);
  params.set("offset", state.offset);

  const semQ = semanticQueryFromInput(state.q);
  if (semQ) {
    params.set("q", `sem:${semQ}`);
    state.semanticMode = true;
  } else {
    state.semanticMode = false;
    if (state.q) params.set("q", state.q);
  }

  if (state.currentSource) params.set("source", state.currentSource);
  if (state.currentBoard) params.set("board", state.currentBoard);
  if (state.currentContentKind) params.set("content_kind", state.currentContentKind);
  if (state.currentCollection) params.set("collection_id", state.currentCollection);
  appendClassificationFacetParams(params);

  appendReviewScopeParams(params);
  appendShowDiscardedParam(params);
  appendUsableTrackExclusionParam(params);

  try {
    let data;
    const catalogFiles = getCatalogFilterFiles();
    if (catalogFiles.length) {
      // Catalog browsing: load items from one or more catalog files
      const catParams = _buildCurrentCatalogQueryParams({ limit: ASSETS_PAGE_SIZE, offset: state.offset });
      data = await api(`/api/catalog/items?${catParams}`, { priority: "high" });
    } else if (semQ) {
      const res = await fetch(_bp(`/api/search/similar?${params}`), { priority: "high" });
      if (!res.ok) throw new Error(await res.text());
      data = await res.json();
    } else {
      const collectionIds = getCollectionFilterIds();
      if (collectionIds.length) params.set("collection_id", collectionIds.join(","));
      data = await api(`/api/assets?${params}`, { priority: "high" });
    }

    if (seq !== state.assetsRequestSeq) return; // stale

    const newAssets = data.assets || [];
    if (append) {
      state.assets = [...state.assets, ...newAssets];
    } else {
      state.assets = newAssets;
    }
    state.hasMore = !!(data.has_more);
    state.totalCount = data.total || null;
    state.offset += newAssets.length;

    renderGrid();
    updateStats();
    updateLoadMoreBtn();
    updateFilterIndicator();
    await syncExplorerFilter();
  } catch (e) {
    if (seq !== state.assetsRequestSeq) return;
    if (append) {
      Shared.showToast(`Unable to load more items: ${formatApiError(e)}`, { type: "error", duration: 4200 });
      return;
    }
    const grid = $("#grid");
    if (grid) grid.innerHTML = `<div class="empty-state">Unable to load items: ${escapeHtml(formatApiError(e))}</div>`;
  } finally {
    if (seq === state.assetsRequestSeq) {
      state.loadingAssets = false;
      updateLoadMoreBtn();
      updateStats();
      scheduleAutoLoadMore();
      // A scope change can arrive while an automatic append request is active.
      // Always honor the queued full reload once the in-flight request finishes.
      if (state.pendingAssetsReload) {
        state.pendingAssetsReload = false;
        loadAssets();
      }
    }
  }
}

function updateLoadMoreBtn() {
  const btn = $("#loadMore");
  if (!btn) return;
  btn.hidden = !state.hasMore || state.semanticMode;
  btn.disabled = state.loadingAssets;
  btn.textContent = state.loadingAssets ? "Loading…" : "Load More";
}

function _autoLoadScrollRemainingPx() {
  const scroller = $(".content");
  if (scroller && getComputedStyle(scroller).overflowY !== "visible") {
    return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
  }
  const root = document.scrollingElement || document.documentElement;
  return root.scrollHeight - window.scrollY - window.innerHeight;
}

function maybeAutoLoadMore() {
  _autoLoadMoreRaf = 0;
  const browseView = $("#browseView");
  if (!browseView || browseView.hidden) return;
  if (state.view !== "browse") return;
  if (!state.hasMore || state.loadingAssets || state.semanticMode) return;
  if (_autoLoadScrollRemainingPx() > AUTO_LOAD_MORE_MARGIN_PX) return;
  loadAssets({ append: true });
}

function scheduleAutoLoadMore() {
  if (_autoLoadMoreRaf) return;
  _autoLoadMoreRaf = window.requestAnimationFrame(maybeAutoLoadMore);
}

function setupAutoLoadMoreObservers() {
  if (!("IntersectionObserver" in window)) return;
  const sentinel = $(".load-more-wrap");
  if (!sentinel) return;
  for (const observer of _autoLoadMoreObservers) observer.disconnect();
  _autoLoadMoreObservers = [];

  const contentScroller = $(".content");
  const roots = contentScroller ? [contentScroller, null] : [null];
  for (const root of roots) {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) scheduleAutoLoadMore();
      },
      { root, rootMargin: `${AUTO_LOAD_MORE_MARGIN_PX}px 0px`, threshold: 0 },
    );
    observer.observe(sentinel);
    _autoLoadMoreObservers.push(observer);
  }
}

function syncTopFilterToolbar() {
  const cardToolbar = $("#topCardFilterToolbar");
  const explorerToolbar = $("#explorerToolbarMount");
  const input = $("#canvasTextFilter");
  const explorerActive = isExplorerViewActive();

  syncCollectionPdfExportButton();
  if (cardToolbar) cardToolbar.hidden = false;
  if (explorerToolbar) {
    explorerToolbar.hidden = !explorerActive || explorerToolbar.children.length === 0;
  }
  if (input && document.activeElement !== input) input.value = state.q || "";
}

function updateExplorerModeChip() {
  const chip = $("#explorerModeChip");
  syncTopFilterToolbar();
  if (!chip) return;
  if (!isExplorerViewActive()) {
    chip.hidden = true;
    chip.textContent = "";
    chip.className = "explorer-mode-chip";
    return;
  }

  const count = Number.isFinite(_explorerFilterCount)
    ? Math.max(0, Number(_explorerFilterCount || 0))
    : null;
  const countLabel = count === null ? "" : `${count} item${count === 1 ? "" : "s"}`;
  const isMobileMode = _isExplorerMobileConstrained();
  const is3D = _explorerMode === "3d";
  const mobileBudget = isMobileMode ? _explorerMobile3DBudget : null;
  const budgetTitle = mobileBudget?.nodeLimit
    ? ` This iPad's measured 3D budget is about ${mobileBudget.nodeLimit} items.`
    : "";
  chip.hidden = false;
  chip.className = `explorer-mode-chip ${is3D ? "mode-3d" : "mode-2d"}`;
  if (_explorerModeChipOverride) {
    chip.textContent = _explorerModeChipOverride;
    return;
  }
  if (is3D) {
    const isScoped3D = !!(_explorerInternalFilterIds || _explorerPayloadFilterKey || _hasActiveFilters());
    const rotateHint = isMobileMode ? " - drag to rotate" : "";
    chip.title = `Drag the map to rotate.${budgetTitle}`;
    chip.textContent = `${isScoped3D ? "3D subset" : "3D map"}${countLabel ? `: ${countLabel}` : ""}${rotateHint}${_explorerInternalFilterIds ? " - tap pill to clear" : ""}`;
  } else if (isMobileMode) {
    chip.title = mobileBudget?.nodeLimit
      ? `Large sets use 2D lite mode. Filter below about ${mobileBudget.nodeLimit} items to switch into 3D on this iPad.`
      : "Large sets use 2D lite mode on iPad until a filtered subset is small enough for 3D.";
    chip.textContent = `iPad lite: 2D map${countLabel ? ` (${countLabel})` : ""}`;
  } else {
    chip.title = "";
    chip.textContent = `2D map${countLabel ? `: ${countLabel}` : ""}`;
  }
}

function updateStats() {
  const statsEl = $("#stats");
  if (!statsEl) return;
  syncTopFilterToolbar();
  updateExplorerModeChip();
  if (isExplorerViewActive() && Number.isFinite(_explorerFilterCount)) {
    const count = Math.max(0, Number(_explorerFilterCount || 0));
    statsEl.textContent = `${count} item${count === 1 ? "" : "s"}`;
    return;
  }
  const shown = state.assets.length;
  const total = state.totalCount;
  const loadingMore = state.loadingAssets && shown > 0 ? " · loading more…" : "";
  if (state.hasMore && total) {
    statsEl.textContent = `${shown} loaded of ${total} items${loadingMore}`;
  } else if (state.hasMore) {
    statsEl.textContent = `${shown} items loaded - more available${loadingMore}`;
  } else {
    statsEl.textContent = `${shown} items`;
  }
}

// ─── Grid rendering ─────────────────────────────────────────────────────────────

function renderSkeletons() {
  const grid = $("#grid");
  if (!grid) return;
  grid.innerHTML = "";
  for (let i = 0; i < 12; i++) {
    const el = document.createElement("div");
    el.className = "skeleton-card";
    el.innerHTML = '<div class="skeleton-thumb"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div>';
    grid.appendChild(el);
  }
}

function renderGrid() {
  const grid = $("#grid");
  if (!grid) return;
  grid.innerHTML = "";
  // Maintain canvas selection classes across re-renders.
  const browseView = $("#browseView");
  if (browseView) {
    browseView.classList.toggle("canvas-review-active", state.canvasReview);
    browseView.classList.toggle("canvas-selection-active", state.canvasReview || state.canvasCollectionBuild);
  }
  syncTopFilterToolbar();

  if (!state.assets.length) {
    grid.innerHTML = '<div class="empty-state">No items match your current filters.</div>';
    return;
  }

  for (const a of state.assets) {
    grid.appendChild(buildCard(a));
  }
}

function buildCard(a) {
  const el = document.createElement("div");
  el.className = "card";
  el.dataset.id = a.id;

  const imgUrl = previewForAsset(a);
  const videoUrl = videoUrlForAsset(a);
  const showVideo = !!(videoUrl && isVideoAsset(a));
  const ts = a.triage_status || "";
  const needsComment = a.needs_annotation == 1;
  const flagged = a.flagged == 1;
  const tagged = a.tagged == 1;

  // Triage badges — owner-only. Flag state is shown by the quick flag control.
  let badgeHtml = "";
  if (isOwner()) {
    if (ts === "keeper" && needsComment) {
      badgeHtml = '<span class="triage-badge needs-comment" title="Keeper — needs comment"></span>';
    } else if (ts === "keeper") {
      badgeHtml = '<span class="triage-badge keeper" title="Keeper"></span>';
    } else if (ts === "hidden") {
      badgeHtml = '<span class="triage-badge hidden-status" title="Discarded / irrelevant"></span>';
    }
  }

  const isScan = a.source === "scan";
  const memberIds = (a.scan_group_member_ids || []);
  const isMultiScan = isScan && memberIds.length > 1;

  let scanNavHtml = "";
  if (isMultiScan) {
    scanNavHtml = `<div class="card-scan-nav">
      <button class="scan-nav-btn scan-prev" aria-label="Previous page" disabled>‹</button>
      <span class="scan-nav-indicator">1 / ${memberIds.length}</span>
      <button class="scan-nav-btn scan-next" aria-label="Next page">›</button>
    </div>`;
  }

  const sourceLabel = { pinterest: "Pin", facebook: "FB", scan: "Clip", photo: "Photo" }[a.source] || a.source || "";
  const titleQuality = titleQualityForAsset(a);
  const titleQualityHtml = titleQuality.label
    ? `<span class="title-quality-badge ${escapeHtml(titleQuality.kind)}" title="${escapeHtml(titleQuality.tooltip)}">${escapeHtml(titleQuality.label)}</span>`
    : "";
  const quickTagHtml = canUseTag()
    ? `<button class="card-quick-tag${tagged ? " tagged" : ""}" title="${tagged ? "Remove tag" : "Tag for diagnosis"}" type="button">🏷️</button>`
    : "";
  const isKeeper = ts === "keeper";
  const quickStarHtml = isOwner() && ts !== "hidden"
    ? `<button class="card-quick-star${isKeeper ? " starred" : ""}" title="${isKeeper ? "Remove keeper" : "Mark as keeper"}" type="button">★</button>`
    : "";
  const quickFlagLabel = flagged ? "Unflag follow-up" : "Flag for follow-up";
  const quickFlagHtml = canUseFlag()
    ? `<button class="card-quick-flag${flagged ? " flagged" : ""}" title="${escapeHtml(quickFlagLabel)}" aria-label="${escapeHtml(quickFlagLabel)}" type="button">${flagged ? "⚐" : "⚑"}</button>`
    : "";
  const quickRestoreHtml = isOwner() && ts === "hidden"
    ? '<button class="card-quick-restore" title="Restore to ordinary browsing" type="button">Restore</button>'
    : "";

  const isSelectionMode = state.canvasReview || state.canvasCollectionBuild;
  const selectedClass = isSelectionMode && state.canvasSelected.has(a.id) ? " canvas-selected" : "";
  const discardedClass = ts === "hidden" ? " discarded" : "";
  el.className = "card" + discardedClass + selectedClass;

  const mediaHtml = showVideo
    ? (imgUrl
      ? `<img src="${escapeHtml(imgUrl)}" loading="lazy" alt="" class="video-poster" />`
      : `<video src="${escapeHtml(videoUrl)}" preload="metadata" playsinline muted></video>`)
    : imgUrl
      ? `<img src="${escapeHtml(imgUrl)}" loading="lazy" alt="" />`
      : `<div class="card-placeholder">${escapeHtml(displayTitle(a))}</div>`;

  el.innerHTML = `
    <div class="card-image">
      <button class="card-checkbox" type="button" aria-label="${escapeHtml(isSelectionMode ? "Toggle selected item" : "Select for collection")}" title="${escapeHtml(isSelectionMode ? "Toggle selected item" : "Select for collection")}"></button>
      ${mediaHtml}
      ${badgeHtml}
      <span class="source-badge source-${escapeHtml(a.source || "")}">${escapeHtml(sourceLabel)}</span>
      ${quickStarHtml}
      ${quickTagHtml}
      ${quickFlagHtml}
      ${quickRestoreHtml}
      ${scanNavHtml}
    </div>
    <div class="card-footer">
      <div class="card-title-row">
        <span class="card-title">${escapeHtml(displayTitle(a))}</span>
        ${titleQualityHtml}
      </div>
      <span class="card-source">${escapeHtml([a.board, a.creator_name].filter(Boolean).join(" · "))}</span>
    </div>
  `;

  el.onclick = (e) => {
    if (e.target.closest(".scan-nav-btn")) return;
    if (state.canvasCollectionBuild) {
      toggleCanvasSelection(a.id, el);
      return;
    }
    openModal(a);
  };

  const checkbox = el.querySelector(".card-checkbox");
  if (checkbox) {
    checkbox.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!state.canvasReview && !state.canvasCollectionBuild) {
        enterCollectionBuild({ initialSelectionId: a.id });
        return;
      }
      toggleCanvasSelection(a.id, el);
    });
  }

  // Scan page nav wiring
  if (isMultiScan) {
    let pageIdx = 0;
    const prev = el.querySelector(".scan-prev");
    const next = el.querySelector(".scan-next");
    const indicator = el.querySelector(".scan-nav-indicator");
    const img = el.querySelector(".card-image img");

    const updateNav = () => {
      if (prev) prev.disabled = pageIdx === 0;
      if (next) next.disabled = pageIdx >= memberIds.length - 1;
      if (indicator) indicator.textContent = `${pageIdx + 1} / ${memberIds.length}`;
      if (img) img.src = `${_B}/media/${memberIds[pageIdx]}?kind=thumb`;
    };

    if (prev) prev.addEventListener("click", (e) => { e.stopPropagation(); pageIdx = Math.max(0, pageIdx - 1); updateNav(); });
    if (next) next.addEventListener("click", (e) => { e.stopPropagation(); pageIdx = Math.min(memberIds.length - 1, pageIdx + 1); updateNav(); });
  }

  // Quick-tag button wiring (Jim's anomaly tagging)
  const quickTagBtn = el.querySelector(".card-quick-tag");
  if (quickTagBtn) {
    quickTagBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!canUseTag()) {
        Shared.showToast("Tag workflow retired.", { type: "info" });
        return;
      }
      const newTagged = a.tagged ? 0 : 1;
      try {
        await api(`/api/assets/${encodeURIComponent(a.id)}/tag`, {
          method: "POST",
          body: JSON.stringify({ tagged: newTagged }),
        });
        a.tagged = newTagged;
        // Toggle tag badge on card
        const cardImg = el.querySelector(".card-image");
        const oldBadge = el.querySelector(".triage-badge.tagged");
        if (oldBadge) oldBadge.remove();
        if (newTagged && cardImg) {
          const badge = document.createElement("span");
          badge.className = "triage-badge tagged";
          badge.title = "Tagged for diagnosis";
          cardImg.prepend(badge);
        }
        // Update quick-tag button state
        quickTagBtn.classList.toggle("tagged", !!newTagged);
        quickTagBtn.title = newTagged ? "Remove tag" : "Tag for diagnosis";
        Shared.showToast(newTagged ? "Tagged for diagnosis" : "Tag removed", { type: "success", duration: 2000 });
      } catch (err) {
        Shared.showToast(`Tag failed: ${formatApiError(err)}`, { type: "error" });
      }
    });
  }

  // Quick-flag button wiring (owner follow-up marker)
  const quickFlagBtn = el.querySelector(".card-quick-flag");
  if (quickFlagBtn) {
    quickFlagBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!canUseFlag()) {
        Shared.showToast("Flagging is owner-only.", { type: "info" });
        return;
      }
      const newFlagged = a.flagged ? 0 : 1;
      try {
        await api(`/api/assets/${encodeURIComponent(a.id)}/flag`, {
          method: "POST",
          body: JSON.stringify({ flagged: newFlagged }),
        });
        a.flagged = newFlagged;
        quickFlagBtn.classList.toggle("flagged", !!newFlagged);
        const actionLabel = newFlagged ? "Unflag follow-up" : "Flag for follow-up";
        quickFlagBtn.title = actionLabel;
        quickFlagBtn.setAttribute("aria-label", actionLabel);
        quickFlagBtn.textContent = newFlagged ? "⚐" : "⚑";
        if (isReviewStatusFilterActive("flagged") && !newFlagged) {
          await loadAssets();
        } else {
          renderGrid();
        }
        Shared.showToast(newFlagged ? "Flagged for follow-up." : "Flag removed.", { type: "success", duration: 1800 });
      } catch (err) {
        Shared.showToast(`Flag failed: ${formatApiError(err)}`, { type: "error" });
      }
    });
  }

  const quickRestoreBtn = el.querySelector(".card-quick-restore");
  if (quickRestoreBtn) {
    quickRestoreBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        await api(`/api/assets/${encodeURIComponent(a.id)}/triage`, {
          method: "POST",
          body: JSON.stringify({ status: null, reason: "restored from discarded browse" }),
        });
        a.triage_status = null;
        if (isReviewStatusFilterActive("hidden")) {
          await loadAssets();
        } else {
          renderGrid();
        }
        await loadCatalogTree();
        Shared.showToast("Restored to ordinary browsing.", { type: "success", duration: 1800 });
      } catch (err) {
        Shared.showToast(`Restore failed: ${formatApiError(err)}`, { type: "error" });
      }
    });
  }

  // Quick-star button wiring (owner keep/unkeep)
  const quickStarBtn = el.querySelector(".card-quick-star");
  if (quickStarBtn) {
    quickStarBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const newStatus = a.triage_status === "keeper" ? null : "keeper";
      try {
        await api(`/api/assets/${encodeURIComponent(a.id)}/triage`, {
          method: "POST",
          body: JSON.stringify({ status: newStatus }),
        });
        a.triage_status = newStatus;
        // Toggle keeper badge on card
        const cardImg = el.querySelector(".card-image");
        const oldBadge = el.querySelector(".triage-badge.keeper");
        if (oldBadge) oldBadge.remove();
        if (newStatus === "keeper" && cardImg) {
          const badge = document.createElement("span");
          badge.className = "triage-badge keeper";
          badge.title = "Keeper";
          cardImg.prepend(badge);
        }
        // Update star button state
        quickStarBtn.classList.toggle("starred", newStatus === "keeper");
        quickStarBtn.title = newStatus === "keeper" ? "Remove keeper" : "Mark as keeper";
        if (isReviewStatusFilterActive("keeper") && newStatus !== "keeper") await loadAssets();
        Shared.showToast(newStatus === "keeper" ? "Marked as keeper ★" : "Keeper removed", { type: "success", duration: 2000 });
        // Refresh tree counts
        loadCatalogTree();
        if (isOwner()) loadHiddenTree();
      } catch (err) {
        Shared.showToast(`Keep failed: ${formatApiError(err)}`, { type: "error" });
      }
    });
  }

  return el;
}

// ─── Catalog tree + sidebar ──────────────────────────────────────────────────

async function loadFacets() {
  try {
    const params = new URLSearchParams();
    if (state.currentSource) params.set("source", state.currentSource);
    const qs = params.toString();
    const data = await api(`/api/facets${qs ? "?" + qs : ""}`);
    const facets = data.facets || data;
    state.facets = facets;
    refreshIngestTagPickers();
  } catch (e) {
    console.error("Failed to load facets:", e);
  }
}

async function loadCatalogTree() {
  try {
    const data = await api("/api/catalog/tree");
    state.catalogTree = data.tree || [];
    renderCatalogTree();
  } catch (e) {
    console.error("Failed to load catalog tree:", e);
    const wrap = $("#catalogTree");
    if (wrap) wrap.innerHTML = '<div class="muted sidebar-loading">Tree unavailable.</div>';
  }
}

async function refreshSidebarTrees() {
  const tasks = [loadCollections(), loadCatalogTree()];
  if (isOwner()) tasks.push(loadHiddenTree());
  await Promise.all(tasks);
}

function resetTriageFilter() {
  if (state.triageFilter) {
    state.triageFilter = "";
  }
}

function renderCatalogTree() {
  const wrap = $("#catalogTree");
  const collectionWrap = $("#collectionTree");
  const collectionSection = $("#collectionSidebarSection");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (collectionWrap) collectionWrap.innerHTML = "";

  const tree = state.catalogTree || [];
  if (!tree.length) {
    wrap.innerHTML = '<div class="muted sidebar-loading">No catalog yet.</div>';
    if (collectionSection) collectionSection.hidden = true;
    return;
  }

  const collectionsNodes = tree.filter((n) => n.type === "collections_group");
  if (collectionWrap && collectionSection) {
    if (collectionsNodes.length) {
      collectionSection.hidden = false;
      for (const node of collectionsNodes) {
        collectionWrap.appendChild(buildCollectionsGroupNode(node));
      }
    } else {
      collectionSection.hidden = true;
    }
  }

  const sourceNodes = tree.filter((n) => n.type === "source");
  const classificationNodes = tree.filter((n) => n.type === "classification");
  const otherNode = tree.find((n) => String(n?.id || "").trim().toLowerCase() === "dimension:other") || null;
  const nonHomeTrackValues = new Set(["home_maintenance_diy"]);
  const primaryClassificationNodes = [];
  const nonHomeNodes = [];

  for (const node of classificationNodes) {
    if (String(node.axis_name || "").trim() !== "track") {
      primaryClassificationNodes.push(node);
      continue;
    }
    const nonHomeChildren = (node.children || []).filter((child) => nonHomeTrackValues.has(String(child.axis_value || "").trim()));
    if (nonHomeChildren.length) {
      nonHomeNodes.push({
        ...node,
        id: "classification:non_home_tracks",
        label: "Non-home / DIY",
        count: nonHomeChildren.reduce((sum, child) => sum + Number(child.count || 0), 0),
        children: nonHomeChildren,
      });
    }
  }
  if (otherNode) {
    nonHomeNodes.push({
      ...otherNode,
      children: (otherNode.children || []).map((child) => ({
        ...child,
        label: normalizeOtherDimensionLabel(child.label),
      })),
    });
  }

  if (sourceNodes.length) {
    wrap.appendChild(buildBrowseGroupNode({
      id: "browse-group:sources",
      label: "Sources",
      nodes: sourceNodes,
      defaultExpanded: false,
      builder: (node) => buildSourceNode(node),
    }));
  }
  for (const node of primaryClassificationNodes) {
    wrap.appendChild(buildClassificationNode(node));
  }
  if (!isCollaboratorActor() && nonHomeNodes.length) {
    wrap.appendChild(buildBrowseGroupNode({
      id: "browse-group:non-home",
      label: "Other / Non-Home-Design",
      nodes: nonHomeNodes,
      defaultExpanded: false,
      builder: (node) => node.type === "dimension" ? buildDimensionNode(node) : buildClassificationNode(node),
    }));
  }
  wrap.appendChild(buildReviewStatusGroupNode());

  updateSidebarModeVisibility();
}

function buildReviewStatusGroupNode() {
  const nodes = [
    { id: "review-status:usable", label: "Usable items", view: "usable" },
    { id: "review-status:flagged", label: "Flagged", view: "flagged" },
    { id: "review-status:keeper", label: "Keepers", view: "keeper" },
    { id: "review-status:needs-comment", label: "Needs comment", triageFilter: "needs-comment" },
    { id: "review-status:irrelevant-discarded", label: "Irrelevant / Discarded", view: "irrelevant-discarded" },
    { id: "review-status:all", label: "All items, including discarded", view: "all" },
  ];
  return buildBrowseGroupNode({
    id: "browse-group:review-status",
    label: "Review Status",
    nodes,
    defaultExpanded: false,
    builder: (node) => buildReviewStatusLeaf(node),
  });
}

function buildReviewStatusLeaf(node) {
  const leaf = document.createElement("button");
  const active = state.triageFilter === (node.triageFilter || ITEM_VIEW_OPTIONS[node.view]?.triageFilter || "")
    && !!state.showDiscarded === !!(ITEM_VIEW_OPTIONS[node.view]?.showDiscarded || false);
  leaf.className = `tree-leaf${active ? " active" : ""}`;
  leaf.type = "button";
  leaf.innerHTML = `<span>${escapeHtml(node.label)}</span>`;
  leaf.title = node.label;
  leaf.onclick = () => {
    if (shouldIgnorePostBrowseUnlockTreeClick()) return;
    if (node.view) {
      setItemView(node.view);
      return;
    }
    state.triageFilter = node.triageFilter || "";
    state.showDiscarded = false;
    state.offset = 0;
    renderCatalogTree();
    updateFilterIndicator();
    loadAssets();
  };
  return leaf;
}

function _treeNodeContainsActiveSelection(node) {
  if (!node) return false;
  if (state.currentTreeNodeId && state.currentTreeNodeId === node.id) return true;
  if (node.type === "classification") {
    const axisName = String(node.axis_name || "").trim();
    if (classificationFacetIsActive(axisName)) return true;
  }
  if (node.type === "classification_item") {
    const axisName = String(node.axis_name || "").trim();
    const axisValue = String(node.axis_value || "").trim();
    if (classificationFacetIsActive(axisName, axisValue)) return true;
  }
  return Array.isArray(node.children) && node.children.some((child) => _treeNodeContainsActiveSelection(child));
}

function buildBrowseGroupNode({ id, label, nodes, builder, defaultExpanded = false }) {
  const el = document.createElement("div");
  el.className = "tree-node";
  const toggle = document.createElement("button");
  const hasActiveChild = (nodes || []).some((node) => _treeNodeContainsActiveSelection(node));
  const expanded = state.expandedTreeNodes.has(id) || hasActiveChild || defaultExpanded;
  if (expanded) state.expandedTreeNodes.add(id);
  toggle.className = `tree-toggle${expanded ? " expanded" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span class="tree-label">${escapeHtml(label)}</span>`;
  toggle.title = label;
  const children = document.createElement("div");
  children.className = "tree-children";
  _setTreeNodeExpanded(id, toggle, children, expanded);
  toggle.onclick = () => {
    const nextExpanded = !children.classList.contains("open");
    if (nextExpanded) state.expandedTreeNodes.add(id);
    else state.expandedTreeNodes.delete(id);
    _setTreeNodeExpanded(id, toggle, children, nextExpanded);
  };
  for (const node of nodes || []) {
    children.appendChild(builder(node));
  }
  el.appendChild(toggle);
  el.appendChild(children);
  return el;
}

function buildSourceNode(node) {
  const el = document.createElement("div");
  el.className = "tree-node";

  const nodeKey = node.id;
  const sourceKey = sourceKeyFromNode(node);
  const sourceLabel = sourceKey === "pinterest"
    ? "Pinterest Boards"
    : (sourceDisplayName(sourceKey) || node.label);
  const selectedCatalogFiles = getCatalogFilterFiles();
  const selectedCatalogSet = new Set(selectedCatalogFiles);
  const isActiveSource = state.currentTreeNodeId === node.id
    || (
      state.currentSource === sourceKey
      && !state.currentBoard
      && !state.currentContentKind
      && !hasCatalogFilter()
      && !hasCollectionFilter()
    );
  const toggle = document.createElement("button");
  toggle.className = `tree-toggle${isActiveSource ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span class="tree-label">${escapeHtml(sourceLabel)}</span><span class="tree-count">${node.count}</span>`;
  toggle.title = sourceLabel;

  const children = document.createElement("div");
  children.className = "tree-children";

  // Check if any child is active — auto-expand
  const hasActiveChild = (node.children || []).some(
    (c) => {
      if (c.type === "source_subtype") {
        const subtypeKind = String(c.content_kind || "").trim().toLowerCase();
        return (
          state.currentSource === sourceKey
          && !state.currentBoard
          && !hasCatalogFilter()
          && !hasCollectionFilter()
          && state.currentContentKind === subtypeKind
        );
      }
      const boardName = c.board_name || "";
      const isCatchAll = boardName.startsWith("(");
      if (isCatchAll) return !!c.file && selectedCatalogSet.has(c.file);
      return state.currentSource === sourceKey && state.currentBoard && state.currentBoard.toLowerCase() === boardName.toLowerCase();
    }
  );
  if (hasActiveChild || isActiveSource) state.expandedTreeNodes.add(nodeKey);
  _setTreeNodeExpanded(nodeKey, toggle, children, state.expandedTreeNodes.has(nodeKey));
  _wireTreeArrowToggle(toggle, nodeKey, children);

  // Header click filters to the full source scope (all descendant folders).
  toggle.onclick = () => {
    if (shouldIgnorePostBrowseUnlockTreeClick()) return;
    resetTriageFilter();
    state.currentSource = sourceKey;
    state.currentBoard = null;
    state.currentContentKind = null;
    clearCollectionFilter();
    clearCatalogFilter();
    state.currentTreeNodeId = node.id;
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };

  for (const child of (node.children || [])) {
    if (child.type === "source_subtype") {
      const subtypeLeaf = document.createElement("button");
      const subtypeKind = String(child.content_kind || "").trim().toLowerCase();
      const isSubtypeActive = (
        state.currentSource === sourceKey
        && state.currentContentKind === subtypeKind
        && !state.currentBoard
        && !hasCatalogFilter()
        && !hasCollectionFilter()
      );
      subtypeLeaf.className = `tree-leaf${isSubtypeActive ? " active" : ""}`;
      subtypeLeaf.innerHTML = `<span>${escapeHtml(child.label)}</span><span class="tree-count">${child.count}</span>`;
      subtypeLeaf.title = child.label;
      subtypeLeaf.onclick = () => {
        if (shouldIgnorePostBrowseUnlockTreeClick()) return;
      resetTriageFilter();
      state.currentSource = sourceKey;
      state.currentBoard = null;
      state.currentContentKind = subtypeKind || null;
      clearCollectionFilter();
      clearCatalogFilter();
      state.currentTreeNodeId = child.id || null;
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
      };
      const _src = sourceKey;
      const _kind = subtypeKind;
      addTreeHideToggle(subtypeLeaf, () => ({ source: _src, content_kind: _kind }));
      children.appendChild(subtypeLeaf);
      continue;
    }

    const leaf = document.createElement("button");
    const catchall = describeSourceCatchall(child);
    const boardName = catchall?.label || child.label;
    const boardDbName = child.board_name || "";  // original board name from DB
    const isCatchAll = boardDbName.startsWith("(");  // (small boards), (unsorted reels), etc.

    // For catch-all entries, use catalog file mode; for regular boards, filter by source+board
    const isActive = isCatchAll
      ? selectedCatalogFiles.length === 1 && selectedCatalogFiles[0] === child.file
      : (state.currentSource === sourceKey
        && state.currentBoard
        && state.currentBoard.toLowerCase() === boardDbName.toLowerCase());

    leaf.className = `tree-leaf${isActive ? " active" : ""}`;
    leaf.innerHTML = `<span>${escapeHtml(boardName)}</span><span class="tree-count">${child.count}</span>`;
    leaf.title = catchall?.note ? `${boardName} — ${catchall.note}` : boardName;
    leaf.title = boardName;
    leaf.onclick = () => {
      if (shouldIgnorePostBrowseUnlockTreeClick()) return;
      resetTriageFilter();
      if (isCatchAll) {
        // Use catalog file mode for catch-all entries
        state.currentSource = null;
        state.currentBoard = null;
        state.currentContentKind = null;
        clearCollectionFilter();
        clearClassificationFilter();
        setCatalogFilter([child.file], { label: child.label, nodeId: child.id });
      } else {
        // Direct source+board filter for named boards
        state.currentSource = sourceKey;
        state.currentBoard = boardDbName;
        state.currentContentKind = null;
        clearCollectionFilter();
        clearCatalogFilter();
        state.currentTreeNodeId = child.id;
      }
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
    };
    // Context menu for bulk triage (owner-only)
    if (!isCatchAll) {
      const _src = sourceKey;
      const _brd = boardDbName;
      addTreeHideToggle(leaf, () => ({ source: _src, board: _brd }));
    }
    children.appendChild(leaf);
  }

  // Context menu for the entire source (owner-only)
  addTreeHideToggle(toggle, () => ({ source: sourceKey }));

  el.appendChild(toggle);
  el.appendChild(children);
  return el;
}

function buildDimensionNode(node) {
  const el = document.createElement("div");
  el.className = "tree-node";

  const nodeKey = node.id;
  const selectedCatalogFiles = getCatalogFilterFiles();
  const selectedCatalogSet = new Set(selectedCatalogFiles);
  const isActiveHeader = state.currentTreeNodeId === node.id;
  const toggle = document.createElement("button");
  toggle.className = `tree-toggle${isActiveHeader ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span class="tree-label">${escapeHtml(node.label)}</span><span class="tree-count">${node.count}</span>`;
  toggle.title = node.label;
  toggle.title = node.label;

  const children = document.createElement("div");
  children.className = "tree-children";

  // Check if any child is active — auto-expand
  const hasActiveChild = (node.children || []).some(
    (c) => selectedCatalogSet.has(c.file)
  );
  if (hasActiveChild || isActiveHeader) state.expandedTreeNodes.add(nodeKey);
  _setTreeNodeExpanded(nodeKey, toggle, children, state.expandedTreeNodes.has(nodeKey));
  _wireTreeArrowToggle(toggle, nodeKey, children);

  // Header click filters to all descendant catalog files.
  toggle.onclick = () => {
    if (shouldIgnorePostBrowseUnlockTreeClick()) return;
    resetTriageFilter();
    state.currentSource = null;
    state.currentBoard = null;
    state.currentContentKind = null;
    clearCollectionFilter();
    clearClassificationFilter();
    setCatalogFilter(collectDescendantCatalogFiles(node), { label: node.label, nodeId: node.id });
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };

  for (const child of (node.children || [])) {
    const leaf = document.createElement("button");
    const isActive = selectedCatalogFiles.length === 1 && selectedCatalogFiles[0] === child.file;
    leaf.className = `tree-leaf${isActive ? " active" : ""}`;
    leaf.innerHTML = `<span>${escapeHtml(child.label)}</span><span class="tree-count">${child.count}</span>`;
    leaf.title = child.label;
    leaf.title = child.label;
    leaf.onclick = () => {
      if (shouldIgnorePostBrowseUnlockTreeClick()) return;
      resetTriageFilter();
      state.currentSource = null;
      state.currentBoard = null;
      state.currentContentKind = null;
      clearCollectionFilter();
      clearClassificationFilter();
      setCatalogFilter([child.file], { label: child.label, nodeId: child.id });
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
    };
    children.appendChild(leaf);
  }

  el.appendChild(toggle);
  el.appendChild(children);
  return el;
}

function buildClassificationNode(node) {
  const el = document.createElement("div");
  el.className = "tree-node";

  const nodeKey = node.id;
  const axisName = String(node.axis_name || "").trim();
  const hasActiveChild = (node.children || []).some(
    (child) => classificationFacetIsActive(
      String(child.axis_name || "").trim(),
      String(child.axis_value || "").trim(),
    )
  );
  const isActiveHeader = hasActiveChild || classificationFacetIsActive(axisName);
  const toggle = document.createElement("button");
  toggle.className = `tree-toggle${isActiveHeader ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span class="tree-label">${escapeHtml(node.label)}</span><span class="tree-count">${node.count}</span>`;

  const children = document.createElement("div");
  children.className = "tree-children";

  if (hasActiveChild || isActiveHeader) state.expandedTreeNodes.add(nodeKey);
  _setTreeNodeExpanded(nodeKey, toggle, children, state.expandedTreeNodes.has(nodeKey));
  _wireTreeArrowToggle(toggle, nodeKey, children);

  toggle.onclick = () => {
    if (shouldIgnorePostBrowseUnlockTreeClick()) return;
    _toggleTreeNodeExpanded(nodeKey, toggle, children);
  };

  if (hasActiveChild || classificationFacetIsActive(axisName)) {
    const clearBtn = document.createElement("button");
    clearBtn.className = "tree-leaf tree-facet-clear";
    clearBtn.type = "button";
    clearBtn.innerHTML = `<span>Clear ${escapeHtml(node.label)}</span>`;
    clearBtn.onclick = () => {
      clearClassificationFacetAxis(axisName);
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
    };
    children.appendChild(clearBtn);
  }

  for (const child of (node.children || [])) {
    const axisValue = String(child.axis_value || "").trim();
    const leaf = document.createElement("button");
    const isActive = classificationFacetIsActive(axisName, axisValue);
    leaf.className = `tree-leaf${isActive ? " active facet-active" : ""}`;
    leaf.type = "button";
    leaf.setAttribute("aria-pressed", isActive ? "true" : "false");
    leaf.innerHTML = `<span>${escapeHtml(child.label)}</span><span class="tree-count">${child.count}</span>`;
    leaf.onclick = () => {
      if (shouldIgnorePostBrowseUnlockTreeClick()) return;
      toggleClassificationFacet(axisName, axisValue, { label: child.label });
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
    };
    const _axis = axisName;
    const _value = axisValue;
    addTreeHideToggle(leaf, () => ({ classification_axis: _axis, classification_value: _value }));
    children.appendChild(leaf);
  }

  addTreeHideToggle(toggle, () => ({ classification_axis: axisName }));

  el.appendChild(toggle);
  el.appendChild(children);
  return el;
}

function buildCollectionLeaf(child, selectedCollectionIds) {
  const leaf = document.createElement("button");
  const isActive = selectedCollectionIds.length === 1 && selectedCollectionIds[0] === child.collection_id;
  const badge = child.provenance_badge
    ? `<span class="tree-collection-badge" title="${escapeHtml(child.provenance_label || "")}">${escapeHtml(child.provenance_badge)}</span>`
    : "";
  const sharedNames = Array.isArray(child.shared_actor_names) ? child.shared_actor_names.filter(Boolean) : [];
  const shareSummary = _sharedWithSummary(sharedNames);
  const shareBadge = String(child.intent || "").trim().toLowerCase() === "shared"
    ? `<span class="tree-collection-badge tree-collection-share-badge" title="${escapeHtml(shareSummary || "Shared collection")}">Shared</span>`
    : "";
  const hiddenBadge = Number(child.hidden || 0) === 1
    ? `<span class="tree-collection-badge" title="Hidden collection">Hidden</span>`
    : "";
  const titleBits = [String(child.label || "")];
  if (shareSummary) titleBits.push(shareSummary);
  if (child.provenance_label) titleBits.push(String(child.provenance_label));
  if (child.provenance_note) titleBits.push(String(child.provenance_note));
  leaf.className = `tree-leaf${isActive ? " active" : ""}`;
  leaf.title = titleBits.join(" — ");
  leaf.innerHTML = `<span class="tree-leaf-main"><span class="tree-leaf-text">${escapeHtml(child.label)}</span>${shareBadge}${badge}${hiddenBadge}</span><span class="tree-count">${child.count}</span>`;
  leaf.onclick = () => {
    resetTriageFilter();
    state.currentSource = null;
    state.currentBoard = null;
    state.currentContentKind = null;
    clearCatalogFilter();
    setCollectionFilterIds([child.collection_id], { label: child.label, nodeId: child.id });
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };
  const _colId = child.collection_id;
  addTreeHideToggle(leaf, () => ({ collection_id: _colId }));
  return leaf;
}

function buildCollectionBranchNode(node, selectedCollectionIds) {
  const el = document.createElement("div");
  el.className = "tree-node";
  const nodeKey = String(node.id || node.label || "collection-branch");
  const selectedCollectionSet = new Set(selectedCollectionIds);
  const visibleChildren = Array.isArray(node.children) ? node.children : [];
  const hasActiveChild = visibleChildren.some((child) => (
    (child.collection_id && selectedCollectionSet.has(child.collection_id))
    || _treeNodeContainsActiveSelection(child)
  ));
  if (hasActiveChild) state.expandedTreeNodes.add(nodeKey);

  const toggle = document.createElement("button");
  toggle.className = `tree-toggle${hasActiveChild ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span class="tree-label">${escapeHtml(node.label || "Collections")}</span><span class="tree-count">${Number(node.count || visibleChildren.length || 0)}</span>`;
  toggle.title = node.label || "Collections";

  const children = document.createElement("div");
  children.className = "tree-children";
  _setTreeNodeExpanded(nodeKey, toggle, children, state.expandedTreeNodes.has(nodeKey));
  _wireTreeArrowToggle(toggle, nodeKey, children);
  toggle.onclick = () => {
    resetTriageFilter();
    state.currentSource = null;
    state.currentBoard = null;
    state.currentContentKind = null;
    clearCatalogFilter();
    setCollectionFilterIds(collectDescendantCollectionIds(node), { label: node.label || "Collections", nodeId: node.id });
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };

  for (const child of visibleChildren) {
    if (Array.isArray(child.children)) children.appendChild(buildCollectionBranchNode(child, selectedCollectionIds));
    else children.appendChild(buildCollectionLeaf(child, selectedCollectionIds));
  }

  el.appendChild(toggle);
  el.appendChild(children);
  return el;
}

function buildCollectionsGroupNode(node) {
  const el = document.createElement("div");
  el.className = "tree-node";

  const nodeKey = "collections";
  const selectedCollectionIds = getCollectionFilterIds();
  const selectedCollectionSet = new Set(selectedCollectionIds);
  const focusedLandingId = _activeSharedCollectionLandingId();
  const visibleChildren = focusedLandingId
    ? (node.children || []).filter((child) => String(child.collection_id || "") === focusedLandingId)
    : (node.children || []);
  const isActiveHeader = state.currentTreeNodeId === node.id;
  const toggle = document.createElement("button");
  const groupLabel = focusedLandingId ? "Shared Collection" : "All Collections";
  const groupCount = focusedLandingId
    ? visibleChildren.reduce((sum, child) => sum + Number(child.count || 0), 0)
    : Number(node.count || 0);
  toggle.className = `tree-toggle${isActiveHeader ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span class="tree-label">${escapeHtml(groupLabel)}</span><span class="tree-count">${groupCount}</span>`;
  toggle.title = groupLabel;

  const children = document.createElement("div");
  children.className = "tree-children";

  const hasActiveChild = visibleChildren.some((c) => selectedCollectionSet.has(c.collection_id));
  const collaboratorDefaultExpanded = isCollaboratorActor();
  if (hasActiveChild || isActiveHeader || collaboratorDefaultExpanded) state.expandedTreeNodes.add(nodeKey);
  _setTreeNodeExpanded(nodeKey, toggle, children, state.expandedTreeNodes.has(nodeKey));
  _wireTreeArrowToggle(toggle, nodeKey, children);

  // Header click filters to all descendant collections.
  toggle.onclick = () => {
    resetTriageFilter();
    state.currentSource = null;
    state.currentBoard = null;
    state.currentContentKind = null;
    clearCatalogFilter();
    setCollectionFilterIds(
      focusedLandingId ? [focusedLandingId] : collectDescendantCollectionIds(node),
      { label: focusedLandingId ? (visibleChildren[0]?.label || "Shared Collection") : "All Collections", nodeId: node.id },
    );
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };

  for (const child of visibleChildren) {
    if (Array.isArray(child.children)) children.appendChild(buildCollectionBranchNode(child, selectedCollectionIds));
    else children.appendChild(buildCollectionLeaf(child, selectedCollectionIds));
  }

  el.appendChild(toggle);
  el.appendChild(children);
  return el;
}

// ─── Bulk triage from sidebar (owner-only) ───────────────────────────────────

// Track which tree node keys have been bulk-hidden (for undo)
// Key: serialized filter params string; Value: array of asset IDs that were hidden
const _bulkHiddenByNode = {};

function _nodeKey(filterParams) {
  return JSON.stringify(filterParams, Object.keys(filterParams).sort());
}

function addTreeHideToggle(el, getFilterParams) {
  if (!isOwner()) return;
  const btn = document.createElement("button");
  btn.className = "tree-hide-toggle";
  btn.title = "Discard all items in this folder";
  const key = _nodeKey(getFilterParams());
  const isHidden = !!_bulkHiddenByNode[key];
  btn.innerHTML = "✗";
  btn.classList.toggle("tree-hide-active", isHidden);

  btn.onclick = async (e) => {
    e.stopPropagation();
    e.preventDefault();
    const currentKey = _nodeKey(getFilterParams());
    if (_bulkHiddenByNode[currentKey]) {
      // UNDO: reset items back to pending
      await bulkTriageFromTree(null, getFilterParams(), currentKey);
    } else {
      // HIDE: hide all items
      await bulkTriageFromTree("hidden", getFilterParams(), currentKey);
    }
  };
  el.style.position = "relative";
  el.appendChild(btn);
}

async function bulkTriageFromTree(status, filterParams, nodeKey) {
  const isHiding = status === "hidden";
  const isUndoing = status === null && _bulkHiddenByNode[nodeKey];
  try {
    let ids;
    if (isUndoing) {
      // Use the saved IDs to undo
      ids = _bulkHiddenByNode[nodeKey];
    } else {
      // Fetch all matching IDs from the server
      const params = new URLSearchParams(filterParams);
      params.set("limit", "5000");
      params.set("offset", "0");
      params.set("include_hidden", "1");
      const data = await api(`/api/assets?${params}`);
      ids = (data.assets || []).map((a) => a.id);
    }
    if (!ids || !ids.length) {
      Shared.showToast("No items in this folder.", { type: "info" });
      return;
    }
    if (isHiding && !confirmGlobalHideBulk(ids.length)) {
      Shared.showToast("Discard canceled.", { type: "info" });
      return;
    }
    await api("/api/assets/triage/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, status }),
    });

    if (isHiding) {
      _bulkHiddenByNode[nodeKey] = ids;
      Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} discarded.`, { type: "success" });
    } else if (isUndoing) {
      delete _bulkHiddenByNode[nodeKey];
      Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} restored.`, { type: "success" });
    }

    // Refresh grid + tree (re-fetch tree for updated counts)
    await loadAssets();
    await loadCatalogTree();
    if (isOwner()) loadHiddenTree();
  } catch (e) {
    Shared.showToast(`Bulk triage failed: ${formatApiError(e)}`, { type: "error" });
  }
}

function setSourceFilter(source) {
  resetTriageFilter();
  state.currentSource = normalizeSourceKey(source) || null;
  state.currentBoard = null;
  state.currentContentKind = null;
  clearCollectionFilter();
  clearCatalogFilter();
  state.currentTreeNodeId = null;
  state.offset = 0;
  renderCatalogTree();
  loadAssets();
}

function setBoardFilter(board) {
  resetTriageFilter();
  state.currentBoard = board || null;
  state.currentContentKind = null;
  clearCollectionFilter();
  clearCatalogFilter();
  state.currentTreeNodeId = null;
  state.offset = 0;
  renderCatalogTree();
  loadAssets();
}

function showDynamicSidebar(heading, items) {
  const section = $("#dynamicSidebarSection");
  const headingEl = $("#dynamicSidebarHeading");
  const content = $("#dynamicSidebarContent");
  if (!section || !headingEl || !content) return;
  headingEl.textContent = heading;
  content.innerHTML = "";
  for (const item of items) {
    const btn = document.createElement("button");
    btn.className = "tree-leaf";
    btn.innerHTML = `<span>${escapeHtml(item.label)}</span>${item.count != null ? `<span class="tree-count">${item.count}</span>` : ""}`;
    if (item.onclick) btn.onclick = item.onclick;
    content.appendChild(btn);
  }
  section.hidden = false;
}

function hideDynamicSidebar() {
  const section = $("#dynamicSidebarSection");
  if (section) section.hidden = true;
}

// ─── Hidden tree (owner-only) ──────────────────────────────────────────────────

async function loadHiddenTree() {
  try {
    const data = await api("/api/hidden/tree");
    state.hiddenTree = data;
    renderHiddenTree();
  } catch {
    state.hiddenTree = null;
  }
}

function renderHiddenTree() {
  if (isReviewModeActive()) renderReviewSidebarSummary();
}

// ─── Legacy question dashboard (retired with live sharing) ─────────────────────

async function pollQuestions() {
  state.openQuestions = [];
  renderQuestionBadge();
}

function refreshQuestionsIfOwner() {
  state.openQuestions = [];
  renderQuestionBadge();
}

function renderQuestionBadge() {
  $("#questionBadge")?.remove();
  $("#questionPanel")?.remove();
}

function toggleQuestionPanel() {
  renderQuestionBadge();
}

// ─── Item visibility and legacy triage filters ─────────────────────────────────

function _hiddenReviewQueueActor(value = state.triageFilter) {
  if (value === "hidden-manual") return "manual";
  if (value === "hidden-ai") return "ai-reel-triage";
  return "";
}

function _isHiddenReviewQueue(value = state.triageFilter) {
  return value === "hidden" || value === "hidden-manual" || value === "hidden-ai";
}

function _appendHiddenReviewQueueParams(params) {
  params.set("triage_status", "hidden");
  const triageActor = _hiddenReviewQueueActor();
  if (triageActor) params.set("triage_actor", triageActor);
}

async function setItemView(view) {
  const config = ITEM_VIEW_OPTIONS[view];
  if (!config) return;
  state.triageFilter = config.triageFilter;
  state.showDiscarded = config.showDiscarded;
  state.offset = 0;
  updateReviewScopeChips();
  updateCanvasSelectionCount();
  updateCollectionBuildSelectionCount();
  renderCatalogTree();
  updateFilterIndicator();
  await loadAssets();
  if (!state.assets.length) {
    Shared.showToast(config.emptyLabel, { type: "info" });
  }
}

// ─── Collections ────────────────────────────────────────────────────────────────

function _isSystemHiddenCollectionName(name) {
  return String(name || "").trim().toLowerCase() === "hidden";
}

function _collectionIsHidden(collection) {
  if (!collection) return false;
  const raw = collection.hidden;
  if (raw === true) return true;
  const n = Number(raw);
  return Number.isFinite(n) && n === 1;
}

async function loadCollections() {
  try {
    const data = await api("/api/collections");
    const rows = Array.isArray(data.collections) ? data.collections : [];
    state.collections = rows
      .filter((c) => !_collectionIsHidden(c))
      .filter((c) => !_isSystemHiddenCollectionName(c.name));
    state.hiddenCollections = [];
  } catch (e) {
    console.error("Failed to load collections:", e);
  }
}

async function loadCollectionsForManager() {
  try {
    const data = await api("/api/collections?include_hidden=1");
    const rows = Array.isArray(data.collections) ? data.collections : [];
    const nonSystem = rows.filter((c) => !_isSystemHiddenCollectionName(c.name));
    state.collections = nonSystem.filter((c) => !_collectionIsHidden(c));
    state.hiddenCollections = nonSystem.filter((c) => _collectionIsHidden(c));
  } catch (e) {
    console.error("Failed to load collections:", e);
    state.collections = [];
    state.hiddenCollections = [];
  }
}

async function loadCollectionActors() {
  state.collectionActors = [];
}

function _allManagerCollections() {
  return [...(state.collections || []), ...(state.hiddenCollections || [])];
}

function _selectedCollectionForManager() {
  const selectedId = String(state.collectionManagerSelectedId || "");
  if (!selectedId) return null;
  return (state.collections || []).find((collection) => String(collection?.id || "") === selectedId) || null;
}

function _ensureCollectionManagerSelection() {
  const available = state.collections || [];
  if (!available.length) {
    state.collectionManagerSelectedId = null;
    return;
  }
  const selected = _selectedCollectionForManager();
  if (selected) return;
  state.collectionManagerSelectedId = String((state.collections[0] || {}).id || "");
}

function _currentCollectionDetailFormState() {
  return {
    name: String($("#collectionDetailName")?.value || "").trim(),
    description: String($("#collectionDetailDescription")?.value || "").trim(),
    intent: "working",
    shared_actor_ids: [],
  };
}

function _currentCollectionCreateFormState() {
  return {
    name: String($("#collectionCreateName")?.value || "").trim(),
    description: String($("#collectionCreateDescription")?.value || "").trim(),
  };
}

function _sameStringList(a, b) {
  const left = Array.isArray(a) ? a.map((v) => String(v || "").trim()).filter(Boolean) : [];
  const right = Array.isArray(b) ? b.map((v) => String(v || "").trim()).filter(Boolean) : [];
  if (left.length !== right.length) return false;
  for (let i = 0; i < left.length; i += 1) {
    if (left[i] !== right[i]) return false;
  }
  return true;
}

function _collectionIntentLabel(intent) {
  return "Local";
}

function _collectionActorNamesByIds(actorIds) {
  const wanted = new Set((Array.isArray(actorIds) ? actorIds : []).map((v) => String(v || "").trim()).filter(Boolean));
  if (!wanted.size) return [];
  return (state.collectionActors || [])
    .filter((actor) => wanted.has(String(actor?.id || "").trim()))
    .map((actor) => String(actor?.name || "").trim())
    .filter(Boolean);
}

function _sharedWithSummary(names) {
  return "";
}

function _buildSharedCollectionLink(collection, actor) {
  return "";
}

const collectionBulkSelection = {
  active: new Set(),
  hidden: new Set(),
};

function _filteredShareCollections() {
  const rows = (state.collections || []).slice();
  const byName = (left, right) => String(left?.name || "").localeCompare(String(right?.name || ""), undefined, { sensitivity: "base" });
  return rows.sort(byName);
}

function _pruneCollectionBulkSelection() {
  const activeIds = new Set((state.collections || []).map((c) => String(c.id || "")));
  const hiddenIds = new Set((state.hiddenCollections || []).map((c) => String(c.id || "")));
  for (const id of Array.from(collectionBulkSelection.active)) {
    if (!activeIds.has(id)) collectionBulkSelection.active.delete(id);
  }
  for (const id of Array.from(collectionBulkSelection.hidden)) {
    if (!hiddenIds.has(id)) collectionBulkSelection.hidden.delete(id);
  }
}

function _renderCollectionBulkList(kind) {
  const isHidden = kind === "hidden";
  const listEl = isHidden ? $("#collectionBulkHiddenList") : $("#collectionBulkActiveList");
  const countEl = isHidden ? $("#collectionBulkHiddenCount") : $("#collectionBulkActiveCount");
  const selected = isHidden ? collectionBulkSelection.hidden : collectionBulkSelection.active;
  const rows = isHidden ? (state.hiddenCollections || []) : (state.collections || []);
  if (countEl) {
    countEl.textContent = `${rows.length} collection${rows.length === 1 ? "" : "s"}`;
  }
  if (!listEl) return;
  if (!rows.length) {
    listEl.innerHTML = `<div class="muted">${isHidden ? "No archived collections." : "No active collections."}</div>`;
    return;
  }
  const renderRow = (c) => {
    const id = String(c.id || "");
    const checked = selected.has(id) ? "checked" : "";
    const name = escapeHtml(String(c.name || "Untitled collection"));
    const count = Number(c.count || 0);
    const provenanceBadge = escapeHtml(String(c.provenance_badge || ""));
    const provenanceLabel = escapeHtml(String(c.provenance_label || ""));
    const provenanceNote = escapeHtml(String(c.provenance_note || ""));
    const badgeHtml = provenanceBadge
      ? `<span class="collectionProvenanceBadge" title="${provenanceLabel}">${provenanceBadge}</span>`
      : "";
    const metaBits = [];
    if (provenanceLabel) metaBits.push(provenanceLabel);
    if (provenanceNote) metaBits.push(provenanceNote);
    const metaHtml = `<span class="collectionBulkMeta">${escapeHtml(metaBits.filter(Boolean).join(" · "))}</span>`;
    const rowClass = "collectionBulkRow";
    return (
      `<label class="${rowClass}" data-row-id="${escapeHtml(id)}">`
      + `<input type="checkbox" data-kind="${isHidden ? "hidden" : "active"}" data-id="${escapeHtml(id)}" ${checked} />`
      + `<span class="collectionBulkNameWrap"><span class="collectionBulkNameLine"><span class="collectionBulkName">${name}</span>${badgeHtml}</span>${metaHtml}</span>`
      + `<span class="collectionBulkCount">${count}</span>`
      + `</label>`
    );
  };
  if (isHidden) {
    const archiveGroups = [
      ["workflow_review", "Completed Reviews"],
      ["source_mirror", "Imported Board Mirrors"],
      ["legacy", "Legacy Folders"],
    ];
    listEl.innerHTML = archiveGroups.map(([groupKind, groupLabel]) => {
      const groupRows = rows.filter((c) => (
        groupKind === "legacy"
          ? !["workflow_review", "source_mirror"].includes(String(c.provenance_kind || ""))
          : String(c.provenance_kind || "") === groupKind
      ));
      if (!groupRows.length) return "";
      return (
        `<section class="collectionArchiveGroup">`
        + `<div class="collectionArchiveGroupHeader"><span>${escapeHtml(groupLabel)}</span><span>${groupRows.length}</span></div>`
        + groupRows.map(renderRow).join("")
        + `</section>`
      );
    }).join("");
  } else {
    listEl.innerHTML = rows.map(renderRow).join("");
  }
  listEl.querySelectorAll("input[type='checkbox'][data-id]").forEach((input) => {
    input.addEventListener("change", () => {
      const cid = String(input.getAttribute("data-id") || "");
      if (!cid) return;
      if (input.checked) selected.add(cid);
      else selected.delete(cid);
      refreshCollectionBulkActions();
    });
  });
}

function renderCollectionShareList() {
  const listEl = $("#collectionShareList");
  const countEl = $("#collectionShareCount");
  if (!listEl) return;
  const rows = _filteredShareCollections();
  if (countEl) {
    countEl.textContent = `${rows.length} collection${rows.length === 1 ? "" : "s"}`;
  }
  const selectedId = String(state.collectionManagerSelectedId || "");
  if (!rows.length) {
    listEl.innerHTML = `<div class="muted">No collections match this filter.</div>`;
    return;
  }
  listEl.innerHTML = rows.map((c) => {
    const id = String(c.id || "");
    const name = escapeHtml(String(c.name || "Untitled collection"));
    const count = Number(c.count || 0);
    const provenanceBadge = escapeHtml(String(c.provenance_badge || ""));
    const provenanceLabel = escapeHtml(String(c.provenance_label || ""));
    const provenanceNote = escapeHtml(String(c.provenance_note || ""));
    const badgeHtml = provenanceBadge
      ? `<span class="collectionProvenanceBadge" title="${provenanceLabel}">${provenanceBadge}</span>`
      : "";
    const primaryMeta = String(c.description || "").trim() || "Local collection";
    const metaBits = [];
    if (provenanceLabel) metaBits.push(provenanceLabel);
    if (provenanceNote) metaBits.push(provenanceNote);
    const rowClass = [
      "collectionBulkRow",
      "collectionShareRow",
      selectedId === id ? "is-selected" : "",
    ].filter(Boolean).join(" ");
    return (
      `<button type="button" class="${rowClass}" data-share-row-id="${escapeHtml(id)}" title="${name}">`
      + `<span class="collectionBulkNameWrap"><span class="collectionBulkNameLine"><span class="collectionBulkName">${name}</span>${badgeHtml}</span><span class="collectionSharePrimaryMeta">${escapeHtml(primaryMeta)}</span><span class="collectionBulkMeta">${escapeHtml(metaBits.filter(Boolean).join(" · "))}</span></span>`
      + `<span class="collectionShareAside"><span class="collectionBulkCount">${count}</span><span class="collectionShareCountLabel">items</span></span>`
      + `</button>`
    );
  }).join("");
  listEl.querySelectorAll("[data-share-row-id]").forEach((row) => {
    row.addEventListener("click", () => {
      const id = String(row.getAttribute("data-share-row-id") || "");
      if (!id) return;
      state.collectionManagerSelectedId = id;
      renderCollectionShareModal();
    });
  });
}

function _updateCollectionDetailDerivedUI(selected) {
  if (!selected) return;
  const payload = _currentCollectionDetailFormState();
  const selectedName = String(selected.name || "").trim();
  const selectedDescription = String(selected.description || "").trim();
  const effectiveName = payload.name || selectedName || "Untitled collection";
  const effectiveDescription = payload.description || selectedDescription;
  const effectiveIntent = "working";
  const shareDraftDirty =
    String(payload.name || "") !== selectedName
    || String(payload.description || "") !== selectedDescription;

  const summaryNameEl = $("#collectionDetailSummaryName");
  const summaryBadgeEl = $("#collectionDetailSummaryIntentBadge");
  const summaryMetaEl = $("#collectionDetailSummaryMeta");
  const summaryDescriptionEl = $("#collectionDetailSummaryDescription");
  if (summaryNameEl) summaryNameEl.textContent = effectiveName;
  if (summaryBadgeEl) {
    summaryBadgeEl.textContent = _collectionIntentLabel(effectiveIntent);
    summaryBadgeEl.setAttribute("data-intent", effectiveIntent);
  }
  if (summaryMetaEl) {
    const metaParts = [`${Number(selected.count || 0)} items`];
    if (selected.provenance_label) metaParts.push(String(selected.provenance_label));
    metaParts.push("Designer PDF ready");
    summaryMetaEl.textContent = metaParts.join(" · ");
  }
  if (summaryDescriptionEl) {
    summaryDescriptionEl.textContent = effectiveDescription;
    summaryDescriptionEl.hidden = !effectiveDescription;
  }

  const collaboratorsWrap = $("#collectionDetailCollaboratorsWrap");
  const collaboratorsHintEl = $("#collectionDetailCollaboratorsHint");
  const collaboratorsSummaryEl = $("#collectionDetailCollaboratorsSummary");
  if (collaboratorsWrap) collaboratorsWrap.hidden = true;
  if (collaboratorsHintEl) {
    collaboratorsHintEl.textContent = "";
  }
  if (collaboratorsSummaryEl) {
    collaboratorsSummaryEl.hidden = true;
    collaboratorsSummaryEl.textContent = "";
    collaboratorsSummaryEl.removeAttribute("data-state");
  }

  const linksHintEl = $("#collectionDetailLinksHint");
  const linksEl = $("#collectionDetailLinks");
  if (linksHintEl) linksHintEl.textContent = "";
  if (linksEl) linksEl.innerHTML = "";

  const saveStatusEl = $("#collectionDetailSaveStatus");
  const saveBtn = $("#collectionDetailSaveBtn");
  if (saveStatusEl) {
    if (shareDraftDirty) {
      saveStatusEl.textContent = "Unsaved changes";
      saveStatusEl.removeAttribute("data-state");
    } else {
      saveStatusEl.textContent = "Saved";
      saveStatusEl.removeAttribute("data-state");
    }
  }
  if (saveBtn) saveBtn.disabled = !shareDraftDirty;
}

function renderCollectionDetailEditor() {
  const emptyEl = $("#collectionShareDetailEmpty");
  const formEl = $("#collectionShareDetailForm");
  const statusEl = $("#collectionShareDetailStatus");
  const selected = _selectedCollectionForManager();
  if (!selected) {
    if (emptyEl) emptyEl.hidden = false;
    if (formEl) formEl.hidden = true;
    if (statusEl) statusEl.textContent = "Select a collection to edit.";
    return;
  }

  if (emptyEl) emptyEl.hidden = true;
  if (formEl) formEl.hidden = false;
  if (statusEl) {
    statusEl.textContent = `Local collection · ${selected.name || "Untitled collection"}`;
  }

  const currentForm = _currentCollectionDetailFormState();
  const nameEl = $("#collectionDetailName");
  const descEl = $("#collectionDetailDescription");
  const intentEl = $("#collectionDetailIntent");
  const currentEditingId = String(formEl?.getAttribute("data-collection-id") || "");
  const preserveDraft = currentEditingId === String(selected.id || "");
  if (nameEl) nameEl.value = preserveDraft && currentForm.name ? currentForm.name : String(selected.name || "");
  if (descEl) descEl.value = preserveDraft ? currentForm.description : String(selected.description || "");
  if (intentEl) intentEl.value = "working";
  if (formEl) formEl.setAttribute("data-collection-id", String(selected.id || ""));

  const collaboratorsWrap = $("#collectionDetailCollaboratorsWrap");
  const collaboratorsEl = $("#collectionDetailCollaborators");
  if (collaboratorsEl) collaboratorsEl.innerHTML = "";
  if (collaboratorsWrap) collaboratorsWrap.hidden = true;
  _updateCollectionDetailDerivedUI(selected);
}

function refreshCollectionBulkActions() {
  const hideBtn = $("#collectionBulkHideBtn");
  const restoreBtn = $("#collectionBulkRestoreBtn");
  const deleteBtn = $("#collectionBulkDeleteBtn");
  const selectedActive = collectionBulkSelection.active.size;
  const selectedHidden = collectionBulkSelection.hidden.size;
  if (hideBtn) hideBtn.disabled = selectedActive === 0;
  if (restoreBtn) restoreBtn.disabled = selectedHidden === 0;
  if (deleteBtn) deleteBtn.disabled = selectedHidden === 0;
}

function renderCollectionBulkModal() {
  _pruneCollectionBulkSelection();
  _renderCollectionBulkList("active");
  _renderCollectionBulkList("hidden");
  refreshCollectionBulkActions();
}

function renderCollectionShareFilterButtons() {
  const filters = $("#collectionShareFilters");
  if (filters) filters.hidden = true;
}

function renderCollectionShareModal() {
  _ensureCollectionManagerSelection();
  const visibleRows = _filteredShareCollections();
  const selectedId = String(state.collectionManagerSelectedId || "");
  if (visibleRows.length && !visibleRows.some((row) => String(row?.id || "") === selectedId)) {
    state.collectionManagerSelectedId = String(visibleRows[0]?.id || "");
  }
  if (!visibleRows.length) {
    state.collectionManagerSelectedId = null;
  }
  renderCollectionShareFilterButtons();
  renderCollectionShareList();
  renderCollectionDetailEditor();
  renderCollectionBulkModal();
}

async function _refreshCollectionViewsAfterBulkChange() {
  await Promise.all([loadCollections(), loadCatalogTree()]);
  if (isOwner()) await loadHiddenTree();
  await loadAssets();
}

async function bulkHideCollections() {
  const ids = Array.from(collectionBulkSelection.active);
  if (!ids.length) return;
  try {
    const payload = await api("/api/collections/bulk-hide", {
      method: "POST",
      body: JSON.stringify({ collection_ids: ids, hidden: true }),
    });
    const updated = Number(payload.updated || 0);
    Shared.showToast(`Archived ${updated} collection${updated === 1 ? "" : "s"}.`, { type: "success" });
    collectionBulkSelection.active.clear();
    await loadCollectionsForManager();
    renderCollectionBulkModal();
    await _refreshCollectionViewsAfterBulkChange();
  } catch (e) {
    Shared.showToast(`Archive failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function bulkRestoreCollections() {
  const ids = Array.from(collectionBulkSelection.hidden);
  if (!ids.length) return;
  try {
    const payload = await api("/api/collections/bulk-hide", {
      method: "POST",
      body: JSON.stringify({ collection_ids: ids, hidden: false }),
    });
    const updated = Number(payload.updated || 0);
    Shared.showToast(`Restored ${updated} collection${updated === 1 ? "" : "s"}.`, { type: "success" });
    collectionBulkSelection.hidden.clear();
    await loadCollectionsForManager();
    renderCollectionBulkModal();
    await _refreshCollectionViewsAfterBulkChange();
  } catch (e) {
    Shared.showToast(`Restore failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function bulkDeleteHiddenCollections() {
  const ids = Array.from(collectionBulkSelection.hidden);
  if (!ids.length) return;
  const ok = confirm(`Delete ${ids.length} archived collection${ids.length === 1 ? "" : "s"} permanently? The folders will be removed, but their items will remain in the library.`);
  if (!ok) return;
  try {
    const payload = await api("/api/collections/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ collection_ids: ids }),
    });
    const deleted = Number(payload.deleted || 0);
    const skipped = Number(payload.skipped || 0);
    if (skipped > 0) {
      Shared.showToast(`Deleted ${deleted}. Skipped ${skipped} (must already be archived).`, { type: "info" });
    } else {
      Shared.showToast(`Deleted ${deleted} archived collection${deleted === 1 ? "" : "s"}.`, { type: "success" });
    }
    collectionBulkSelection.hidden.clear();
    await loadCollectionsForManager();
    renderCollectionBulkModal();
    await _refreshCollectionViewsAfterBulkChange();
  } catch (e) {
    Shared.showToast(`Delete failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function openCollectionBulkModal() {
  if (!isOwner()) {
    Shared.showToast("Owner access required.", { type: "error" });
    return;
  }
  await loadCollectionsForManager();
  renderCollectionBulkModal();
  $("#collectionShareModal")?.classList.remove("hidden");
}

function closeCollectionBulkModal() {
  collectionBulkSelection.active.clear();
  collectionBulkSelection.hidden.clear();
  state.collectionManagerSelectedId = null;
  renderCollectionBulkModal();
  $("#collectionShareModal")?.classList.add("hidden");
}

async function openCollectionShareModal() {
  if (!isOwner()) {
    Shared.showToast("Owner access required.", { type: "error" });
    return;
  }
  await loadCollectionsForManager();
  renderCollectionShareModal();
  const createStatus = $("#collectionCreateStatus");
  if (createStatus) createStatus.textContent = "";
  $("#collectionShareModal")?.classList.remove("hidden");
}

function closeCollectionShareModal() {
  state.collectionManagerSelectedId = null;
  state.collectionShareFilter = "all";
  collectionBulkSelection.active.clear();
  collectionBulkSelection.hidden.clear();
  const createName = $("#collectionCreateName");
  const createDescription = $("#collectionCreateDescription");
  const createStatus = $("#collectionCreateStatus");
  if (createName) createName.value = "";
  if (createDescription) createDescription.value = "";
  if (createStatus) createStatus.textContent = "";
  renderCollectionShareModal();
  $("#collectionShareModal")?.classList.add("hidden");
}

async function createEmptyCollectionFromManager() {
  if (!isOwner()) {
    Shared.showToast("Owner access required.", { type: "error" });
    return;
  }
  const payload = _currentCollectionCreateFormState();
  const statusEl = $("#collectionCreateStatus");
  const createBtn = $("#collectionCreateBtn");
  if (!payload.name) {
    if (statusEl) statusEl.textContent = "Name required";
    $("#collectionCreateName")?.focus();
    return;
  }
  if (createBtn) createBtn.disabled = true;
  if (statusEl) statusEl.textContent = "Creating…";
  try {
    const data = await api("/api/collections", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const collection = data?.collection || {};
    state.collectionManagerSelectedId = String(collection.id || "");
    const nameEl = $("#collectionCreateName");
    const descEl = $("#collectionCreateDescription");
    if (nameEl) nameEl.value = "";
    if (descEl) descEl.value = "";
    await loadCollectionsForManager();
    await Promise.all([loadCollections(), loadCatalogTree()]);
    renderCollectionShareModal();
    renderCatalogTree();
    Shared.showToast(`Created collection "${payload.name}".`, { type: "success" });
  } catch (e) {
    if (statusEl) statusEl.textContent = "Create failed";
    Shared.showToast(`Create failed: ${formatApiError(e)}`, { type: "error" });
  } finally {
    if (createBtn) createBtn.disabled = false;
  }
}

async function saveCollectionDetails() {
  if (!isOwner()) {
    Shared.showToast("Owner access required.", { type: "error" });
    return;
  }
  const selected = _selectedCollectionForManager();
  if (!selected) {
    Shared.showToast("Select a collection first.", { type: "info" });
    return;
  }
  const payload = _currentCollectionDetailFormState();
  if (!payload.name) {
    Shared.showToast("Collection name is required.", { type: "error" });
    return;
  }
  try {
    const data = await api(`/api/collections/${encodeURIComponent(selected.id)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    const updated = data?.collection || {};
    state.collectionManagerSelectedId = String(updated.id || selected.id);
    await loadCollectionsForManager();
    await Promise.all([loadCollections(), loadCatalogTree()]);
    renderCollectionShareModal();
    renderCatalogTree();
    Shared.showToast(`Saved collection "${payload.name}".`, { type: "success" });
  } catch (e) {
    Shared.showToast(`Save failed: ${formatApiError(e)}`, { type: "error" });
  }
}

function _filenameFromDisposition(value, fallback) {
  const text = String(value || "");
  const star = text.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) {
    try { return decodeURIComponent(star[1]); } catch {}
  }
  const plain = text.match(/filename="?([^";]+)"?/i);
  return plain ? plain[1] : fallback;
}

function _collectionPdfFilename(collection) {
  const name = String(collection?.name || "collection").trim().toLowerCase();
  const slug = name.replace(/[^a-z0-9._-]+/g, "-").replace(/-+/g, "-").replace(/^[-._]+|[-._]+$/g, "") || "collection";
  return `${slug}.pdf`;
}

function syncCollectionPdfExportButton() {
  const btn = $("#exportCollectionPdf");
  if (!btn) return;
  const ids = getCollectionFilterIds();
  const collection = ids.length === 1
    ? (state.collections || []).find((c) => String(c.id || "") === ids[0]) || null
    : null;
  const collectionName = String(collection?.name || state.currentCollectionLabel || "selected collection").trim();
  const canExport = isOwner() && ids.length === 1;
  btn.hidden = !canExport;
  if (canExport) {
    btn.title = `Export "${collectionName}" as a standalone PDF. Active filters do not change the exported collection.`;
    btn.setAttribute("aria-label", `Export ${collectionName} collection as PDF`);
  } else {
    btn.removeAttribute("title");
    btn.removeAttribute("aria-label");
  }
}

async function exportCurrentCollectionPdf() {
  const ids = getCollectionFilterIds();
  if (ids.length !== 1) {
    Shared.showToast("Choose one collection in the sidebar before exporting a PDF.", { type: "info", duration: 4500 });
    return;
  }
  const collectionId = ids[0];
  const collection = (state.collections || []).find((c) => String(c.id || "") === collectionId) || null;
  const btn = $("#exportCollectionPdf");
  const originalText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Exporting…";
  }
  try {
    const res = await fetch(_bp(`/api/collections/${encodeURIComponent(collectionId)}/export/pdf`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatApiError(text || res.statusText));
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = _filenameFromDisposition(res.headers.get("Content-Disposition"), _collectionPdfFilename(collection));
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 2000);
    Shared.showToast("Collection PDF exported.", { type: "success", duration: 3000 });
  } catch (e) {
    Shared.showToast(`PDF export failed: ${formatApiError(e)}`, { type: "error", duration: 8000 });
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText || "Export Collection PDF";
    }
  }
}

function setCollectionFilter(collectionId) {
  if (collectionId) {
    state.currentSource = null;
    state.currentBoard = null;
    state.currentContentKind = null;
    clearCatalogFilter();
    const col = state.collections.find((c) => c.id === collectionId);
    setCollectionFilterIds([collectionId], { label: col ? col.name : "", nodeId: null });
  } else {
    clearCollectionFilter();
    state.currentTreeNodeId = null;
  }
  state.offset = 0;
  renderCatalogTree();
  loadAssets();
}

function closeCollectionBuildModal() {
  $("#collectionBuildModal")?.classList.add("hidden");
}

function renderCollectionBuildExistingOptions() {
  const select = $("#collectionBuildExistingSelect");
  if (!select) return;
  const rows = (state.collections || []).filter((collection) => !_collectionIsHidden(collection));
  select.innerHTML = rows.length
    ? rows.map((collection) => `<option value="${escapeHtml(collection.id)}">${escapeHtml(collection.name || "Untitled collection")} · ${Number(collection.count || 0)} items</option>`).join("")
    : '<option value="">No collections yet</option>';
  const activeIds = getCollectionFilterIds();
  if (activeIds.length === 1 && rows.some((collection) => collection.id === activeIds[0])) {
    select.value = activeIds[0];
  }
  const addBtn = $("#collectionBuildAdd");
  if (addBtn) addBtn.disabled = !rows.length;
}

function openCollectionBuildModal(mode) {
  const count = state.canvasSelected.size;
  if (!count) {
    Shared.showToast("Select at least one item first.", { type: "info" });
    return;
  }
  const showNew = mode === "new";
  const title = $("#collectionBuildModalTitle");
  const hint = $("#collectionBuildModalHint");
  const newSection = $("#collectionBuildNewSection");
  const existingSection = $("#collectionBuildExistingSection");
  if (title) title.textContent = showNew ? "Create a collection" : "Add to a collection";
  if (hint) hint.textContent = `${count} selected item${count === 1 ? "" : "s"}.`;
  if (newSection) newSection.hidden = !showNew;
  if (existingSection) existingSection.hidden = showNew;
  if (showNew) {
    const nameInput = $("#collectionBuildName");
    const descriptionInput = $("#collectionBuildDescription");
    if (nameInput) nameInput.value = "";
    if (descriptionInput) descriptionInput.value = "";
  } else {
    renderCollectionBuildExistingOptions();
  }
  $("#collectionBuildModal")?.classList.remove("hidden");
  if (showNew) $("#collectionBuildName")?.focus();
}

async function addSelectedToNewCollection() {
  const ids = Array.from(state.canvasSelected);
  const name = String($("#collectionBuildName")?.value || "").trim();
  const description = String($("#collectionBuildDescription")?.value || "").trim();
  if (!ids.length) return;
  if (!name) {
    Shared.showToast("Give the new collection a name.", { type: "info" });
    $("#collectionBuildName")?.focus();
    return;
  }
  const btn = $("#collectionBuildCreate");
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/collections", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    });
    const collection = data?.collection || {};
    await addAssetsToCollections(ids, [collection.id]);
    await refreshSidebarTrees();
    closeCollectionBuildModal();
    clearCanvasSelection();
    Shared.showToast(`Created "${name}" with ${ids.length} item${ids.length === 1 ? "" : "s"}.`, { type: "success" });
  } catch (e) {
    Shared.showToast(`Collection creation failed: ${formatApiError(e)}`, { type: "error" });
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function addSelectedToExistingCollection() {
  const ids = Array.from(state.canvasSelected);
  const collectionId = String($("#collectionBuildExistingSelect")?.value || "").trim();
  if (!ids.length || !collectionId) return;
  const collection = (state.collections || []).find((row) => row.id === collectionId) || null;
  const btn = $("#collectionBuildAdd");
  if (btn) btn.disabled = true;
  try {
    await addAssetsToCollections(ids, [collectionId]);
    await refreshSidebarTrees();
    closeCollectionBuildModal();
    clearCanvasSelection();
    Shared.showToast(`Added ${ids.length} item${ids.length === 1 ? "" : "s"} to "${collection?.name || "collection"}".`, { type: "success" });
  } catch (e) {
    Shared.showToast(`Add failed: ${formatApiError(e)}`, { type: "error" });
  } finally {
    if (btn) btn.disabled = false;
  }
}

const exportCollectionPdfBtn = $("#exportCollectionPdf");
if (exportCollectionPdfBtn) {
  exportCollectionPdfBtn.addEventListener("click", exportCurrentCollectionPdf);
}
const closeCollectionBuildModalBtn = $("#closeCollectionBuildModal");
if (closeCollectionBuildModalBtn) closeCollectionBuildModalBtn.addEventListener("click", closeCollectionBuildModal);
const collectionBuildCreateBtn = $("#collectionBuildCreate");
if (collectionBuildCreateBtn) collectionBuildCreateBtn.addEventListener("click", addSelectedToNewCollection);
const collectionBuildAddBtn = $("#collectionBuildAdd");
if (collectionBuildAddBtn) collectionBuildAddBtn.addEventListener("click", addSelectedToExistingCollection);
const collectionBuildModalEl = $("#collectionBuildModal");
if (collectionBuildModalEl) {
  collectionBuildModalEl.addEventListener("click", (event) => {
    if (event.target === collectionBuildModalEl) closeCollectionBuildModal();
  });
}
const manageCollectionsBtn = $("#manageCollections");
if (manageCollectionsBtn) {
  manageCollectionsBtn.addEventListener("click", async () => {
    await openCollectionShareModal();
  });
}
const closeCollectionShareBtn = $("#closeCollectionShare");
if (closeCollectionShareBtn) closeCollectionShareBtn.addEventListener("click", closeCollectionShareModal);
const cancelCollectionShareBtn = $("#cancelCollectionShare");
if (cancelCollectionShareBtn) cancelCollectionShareBtn.addEventListener("click", closeCollectionShareModal);
const collectionBulkHideBtn = $("#collectionBulkHideBtn");
if (collectionBulkHideBtn) collectionBulkHideBtn.addEventListener("click", bulkHideCollections);
const collectionBulkRestoreBtn = $("#collectionBulkRestoreBtn");
if (collectionBulkRestoreBtn) collectionBulkRestoreBtn.addEventListener("click", bulkRestoreCollections);
const collectionBulkDeleteBtn = $("#collectionBulkDeleteBtn");
if (collectionBulkDeleteBtn) collectionBulkDeleteBtn.addEventListener("click", bulkDeleteHiddenCollections);
const collectionDetailSaveBtn = $("#collectionDetailSaveBtn");
if (collectionDetailSaveBtn) collectionDetailSaveBtn.addEventListener("click", saveCollectionDetails);
const collectionCreateBtn = $("#collectionCreateBtn");
if (collectionCreateBtn) collectionCreateBtn.addEventListener("click", createEmptyCollectionFromManager);
const collectionDetailIntent = $("#collectionDetailIntent");
if (collectionDetailIntent) {
  collectionDetailIntent.addEventListener("change", () => _updateCollectionDetailDerivedUI(_selectedCollectionForManager()));
}
const collectionDetailName = $("#collectionDetailName");
if (collectionDetailName) {
  collectionDetailName.addEventListener("input", () => _updateCollectionDetailDerivedUI(_selectedCollectionForManager()));
}
const collectionDetailDescription = $("#collectionDetailDescription");
if (collectionDetailDescription) {
  collectionDetailDescription.addEventListener("input", () => _updateCollectionDetailDerivedUI(_selectedCollectionForManager()));
}
const collectionShareFilterAllBtn = $("#collectionShareFilterAll");
if (collectionShareFilterAllBtn) {
  collectionShareFilterAllBtn.addEventListener("click", () => {
    state.collectionShareFilter = "all";
    renderCollectionShareModal();
  });
}
const collectionShareFilterWorkingBtn = $("#collectionShareFilterWorking");
if (collectionShareFilterWorkingBtn) {
  collectionShareFilterWorkingBtn.addEventListener("click", () => {
    state.collectionShareFilter = "working";
    renderCollectionShareModal();
  });
}
const collectionShareFilterSharedBtn = $("#collectionShareFilterShared");
if (collectionShareFilterSharedBtn) {
  collectionShareFilterSharedBtn.addEventListener("click", () => {
    state.collectionShareFilter = "shared";
    renderCollectionShareModal();
  });
}
const collectionDetailCollaborators = $("#collectionDetailCollaborators");
if (collectionDetailCollaborators) {
  collectionDetailCollaborators.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (!target.matches("input[type='checkbox'][data-actor-id]")) return;
    _updateCollectionDetailDerivedUI(_selectedCollectionForManager());
  });
}
const collectionShareModalEl = $("#collectionShareModal");
if (collectionShareModalEl) {
  collectionShareModalEl.addEventListener("click", (e) => {
    if (e.target === collectionShareModalEl) closeCollectionShareModal();
  });
}
const collectionBulkModalEl = $("#collectionBulkModal");
if (collectionBulkModalEl) {
  collectionBulkModalEl.addEventListener("click", (e) => {
    if (e.target === collectionBulkModalEl) closeCollectionBulkModal();
  });
}

// ─── Detail modal ────────────────────────────────────────────────────────────────

function replaceAssetInState(updatedAsset) {
  const next = updatedAsset && typeof updatedAsset === "object" ? updatedAsset : null;
  if (!next || !next.id) return;
  state.assets = state.assets.map((asset) => (asset && asset.id === next.id ? next : asset));
  state.reviewItems = state.reviewItems.map((asset) => (asset && asset.id === next.id ? next : asset));
  if (state.modalAsset && state.modalAsset.id === next.id) state.modalAsset = next;
}

function assetMatchesActiveItemView(asset) {
  const status = String(asset?.triage_status || "").trim().toLowerCase();
  if (state.triageFilter === "flagged") return asset?.flagged == 1;
  if (state.triageFilter === "needs-comment") return asset?.needs_annotation == 1;
  if (_isHiddenReviewQueue()) return status === "hidden";
  if (isIrrelevantDiscardedReviewScope()) {
    const effectiveTrack = _effectiveClassificationTrack(asset?.classification_review || {});
    return status === "hidden" || effectiveTrack === "irrelevant";
  }
  if (state.triageFilter) return status === state.triageFilter;
  if (state.showDiscarded) return true;
  return status !== "hidden";
}

function setModalCurationBusy(busy) {
  for (const id of ["modalKeepBtn", "modalDiscardBtn", "modalFlagBtn"]) {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = !!busy;
  }
}

function renderModalTriageInfo(asset) {
  const triageSection = $("#modalTriageInfoSection");
  const triageSummary = $("#modalTriageInfoSummary");
  const triageMeta = $("#modalTriageInfoMeta");
  if (!triageSection || !triageSummary || !triageMeta) return;

  const triageInfo = asset?.triage_info || {};
  const status = String(asset?.triage_status || triageInfo.status || "").trim().toLowerCase();
  const actor = String(triageInfo.actor || "").trim();
  const reason = String(triageInfo.reason || "").trim();
  const createdAt = String(triageInfo.created_at || "").trim();
  const hidden = status === "hidden";
  const aiReelCleanup = actor === "ai-reel-triage";
  triageSection.hidden = !hidden;
  triageSummary.textContent = aiReelCleanup
    ? "Discarded by AI reel cleanup"
    : (actor ? `Discarded manually by ${actor}` : "Discarded from ordinary browsing");
  const metaParts = [];
  if (createdAt) metaParts.push(createdAt.slice(0, 10));
  if (reason) metaParts.push(reason);
  triageMeta.textContent = metaParts.join(" · ");
}

async function refreshAfterModalCuration(updatedAsset, { refreshTree = false } = {}) {
  if (assetMatchesActiveItemView(updatedAsset)) {
    renderGrid();
  } else {
    await loadAssets();
  }
  if (refreshTree) {
    await loadCatalogTree();
    if (isOwner()) await loadHiddenTree();
  }
}

async function setModalTriageStatus(status, { reason, toastText } = {}) {
  const asset = state.modalAsset;
  if (!asset?.id) return;
  if (!isOwner()) {
    Shared.showToast("Curation actions are owner-only.", { type: "info" });
    return;
  }

  setModalCurationBusy(true);
  try {
    await api(`/api/assets/${encodeURIComponent(asset.id)}/triage`, {
      method: "POST",
      body: JSON.stringify({ status, reason: reason || "detail modal curation" }),
    });
    const triageInfo = status === "hidden"
      ? {
          status: "hidden",
          actor: String(state.actor?.name || "Jim"),
          reason: reason || "detail modal curation",
          created_at: new Date().toISOString(),
        }
      : null;
    const updated = { ...asset, triage_status: status, triage_info: triageInfo };
    replaceAssetInState(updated);
    renderModalTriageInfo(updated);
    await refreshAfterModalCuration(updated, { refreshTree: true });
    if (state.modalAsset?.id === updated.id) renderModalCurationActions(state.modalAsset);
    Shared.showToast(toastText || "Curation status updated.", { type: "success", duration: 1800 });
  } catch (e) {
    Shared.showToast(`Curation update failed: ${formatApiError(e)}`, { type: "error" });
  } finally {
    if (state.modalAsset?.id === asset.id) setModalCurationBusy(false);
  }
}

async function toggleModalFlag() {
  const asset = state.modalAsset;
  if (!asset?.id) return;
  if (!canUseFlag()) {
    Shared.showToast("Flagging is owner-only.", { type: "info" });
    return;
  }

  const newFlagged = asset.flagged ? 0 : 1;
  setModalCurationBusy(true);
  try {
    await api(`/api/assets/${encodeURIComponent(asset.id)}/flag`, {
      method: "POST",
      body: JSON.stringify({ flagged: newFlagged }),
    });
    const updated = { ...asset, flagged: newFlagged };
    replaceAssetInState(updated);
    await refreshAfterModalCuration(updated);
    if (state.modalAsset?.id === updated.id) renderModalCurationActions(state.modalAsset);
    Shared.showToast(newFlagged ? "Flagged for follow-up." : "Flag removed.", {
      type: "success",
      duration: 1800,
    });
  } catch (e) {
    Shared.showToast(`Flag update failed: ${formatApiError(e)}`, { type: "error" });
  } finally {
    if (state.modalAsset?.id === asset.id) setModalCurationBusy(false);
  }
}

function renderModalCurationActions(asset) {
  const group = $("#modalCurationGroup");
  const keepBtn = $("#modalKeepBtn");
  const discardBtn = $("#modalDiscardBtn");
  const flagBtn = $("#modalFlagBtn");
  const owner = isOwner();
  if (group) group.hidden = !owner;
  if (!owner || !asset) return;

  const status = String(asset.triage_status || "").trim().toLowerCase();
  const keeper = status === "keeper";
  const discarded = status === "hidden";
  if (keepBtn) {
    keepBtn.disabled = false;
    keepBtn.classList.toggle("active", keeper);
    keepBtn.textContent = keeper ? "★ Keeper" : "★ Keep";
    keepBtn.title = keeper ? "Remove keeper status" : "Mark as keeper";
    keepBtn.onclick = () => {
      void setModalTriageStatus(keeper ? null : "keeper", {
        reason: keeper ? "keeper removed from detail modal" : "marked keeper from detail modal",
        toastText: keeper ? "Keeper removed." : "Marked as keeper.",
      });
    };
  }
  if (discardBtn) {
    discardBtn.disabled = false;
    discardBtn.classList.toggle("restore", discarded);
    discardBtn.textContent = discarded ? "↟ Restore" : "✗ Discard";
    discardBtn.title = discarded ? "Restore to ordinary browsing" : "Discard from ordinary browsing";
    discardBtn.onclick = () => {
      if (!discarded && !confirmGlobalHideBulk(1)) {
        Shared.showToast("Discard canceled.", { type: "info" });
        return;
      }
      void setModalTriageStatus(discarded ? null : "hidden", {
        reason: discarded ? "restored from detail modal" : "discarded from detail modal",
        toastText: discarded ? "Restored to ordinary browsing." : "Discarded from ordinary browsing.",
      });
    };
  }
  if (flagBtn) {
    flagBtn.disabled = false;
    flagBtn.classList.toggle("active", !!asset.flagged);
    flagBtn.textContent = asset.flagged ? "⚐ Unflag" : "⚑ Flag";
    flagBtn.title = asset.flagged ? "Remove follow-up flag" : "Flag for follow-up";
    flagBtn.onclick = () => { void toggleModalFlag(); };
  }
}

function setTitleRow(rowId, valueId, metaId, value, meta) {
  const row = $(rowId);
  const valueEl = $(valueId);
  const metaEl = $(metaId);
  const text = String(value || "").trim();
  const note = String(meta || "").trim();
  if (valueEl) valueEl.textContent = text;
  if (metaEl) {
    metaEl.textContent = note;
    metaEl.hidden = !note;
  }
  if (row) row.hidden = !text;
}

function renderModalTitlePanel(asset) {
  const panel = $("#modalTitlePanel");
  if (!panel) return;
  const advancedEditing = isModalAdvancedEditingEnabled();
  if (!advancedEditing) {
    panel.hidden = true;
    const editor = $("#modalTitleEditor");
    if (editor) editor.hidden = true;
    return;
  }
  const info = asset?.title_info || {};
  const workingTitle = String(info.working_title || asset?.title || "").trim();
  const workingMeta = String(info.working_origin_label || "").trim();
  const suggestedTitle = String(info.suggested_title || "").trim();
  const suggestedMeta = String(info.suggestion_label || "").trim();
  const originalTitle = String(info.best_original_title || "").trim();
  const originalMeta = String(info.best_original_origin_label || "").trim();

  setTitleRow("#modalSuggestedTitleRow", "#modalSuggestedTitleValue", "#modalSuggestedTitleMeta", suggestedTitle, suggestedMeta);
  setTitleRow("#modalOriginalTitleRow", "#modalOriginalTitleValue", "#modalOriginalTitleMeta", originalTitle, originalMeta);

  const workingValueEl = $("#modalWorkingTitleValue");
  const workingMetaEl = $("#modalWorkingTitleMeta");
  if (workingValueEl) workingValueEl.textContent = workingTitle || displayTitle(asset);
  if (workingMetaEl) {
    workingMetaEl.textContent = workingMeta;
    workingMetaEl.hidden = !workingMeta;
  }

  const editor = $("#modalTitleEditor");
  const workingInput = $("#modalWorkingTitleInput");
  const saveBtn = $("#modalTitleSaveBtn");
  const suggestedBtn = $("#modalTitleUseSuggestedBtn");
  const owner = advancedEditing;
  if (editor) editor.hidden = !owner;
  if (workingInput) workingInput.value = workingTitle;
  if (saveBtn) saveBtn.disabled = !owner;
  if (suggestedBtn) {
    suggestedBtn.disabled = !owner || !suggestedTitle;
    suggestedBtn.hidden = !suggestedTitle;
  }

  panel.hidden = !(workingTitle || suggestedTitle || originalTitle || owner);
}

async function hydrateModalAsset(asset) {
  const assetId = String(asset?.id || "").trim();
  if (!assetId) return asset;
  const qs = isOwner() ? "?include_hidden=1" : "";
  try {
    const data = await api(`/api/assets/${encodeURIComponent(assetId)}${qs}`);
    if (data?.asset && typeof data.asset === "object") {
      return { ...asset, ...data.asset };
    }
  } catch (_) {
    // Fall back to the asset already on hand when detail hydration fails.
  }
  return asset;
}

function _isCurrentModalLoad(assetId, seq) {
  return (
    seq === Number(state.modalLoadSeq || 0) &&
    !!state.modalAsset &&
    String(state.modalAsset.id || "") === String(assetId || "") &&
    !$("#modal")?.classList.contains("hidden")
  );
}

async function _fetchAssetForModal(assetId) {
  const qs = isOwner() ? "?include_hidden=1" : "";
  const data = await api(`/api/assets/${encodeURIComponent(assetId)}${qs}`);
  return data?.asset && typeof data.asset === "object" ? data.asset : null;
}

async function _resolveCurrentScopeAssetIds() {
  if (state.chatItemIds) return Array.isArray(state.chatItemIds) ? state.chatItemIds.slice() : [];

  const catalogFiles = getCatalogFilterFiles();
  if (catalogFiles.length) {
    const params = _buildCurrentCatalogQueryParams();
    const data = await api(`/api/catalog/asset-ids?${params}`);
    return Array.isArray(data?.ids) ? data.ids : [];
  }

  const params = new URLSearchParams();
  if (state.q && state.q.trim()) params.set("q", state.q.trim());
  if (state.currentSource) params.set("source", state.currentSource);
  if (state.currentBoard) params.set("board", state.currentBoard);
  if (state.currentContentKind) params.set("content_kind", state.currentContentKind);
  appendClassificationFacetParams(params);
  const collectionIds = getCollectionFilterIds();
  if (collectionIds.length) params.set("collection_id", collectionIds.join(","));
  appendReviewScopeParams(params, { includeHiddenForOwner: false });
  appendShowDiscardedParam(params);
  appendUsableTrackExclusionParam(params);
  const data = await api(`/api/asset-ids?${params}`);
  return Array.isArray(data?.ids) ? data.ids : [];
}

function renderModalNavigation() {
  const group = $("#modalNavGroup");
  const statusEl = $("#modalNavStatus");
  const prevBtn = $("#modalPrevBtn");
  const nextBtn = $("#modalNextBtn");
  const ids = Array.isArray(state.modalScopeAssetIds) ? state.modalScopeAssetIds : [];
  const index = Number(state.modalScopeAssetIndex || 0);
  const total = ids.length;
  const show = total > 1 && index >= 0;
  if (group) group.hidden = !show;
  if (!show) return;
  if (statusEl) statusEl.textContent = `${index + 1} of ${total}`;
  if (prevBtn) prevBtn.disabled = index <= 0;
  if (nextBtn) nextBtn.disabled = index >= total - 1;
}

async function _loadModalNavigation(assetId, seq) {
  try {
    const ids = await _resolveCurrentScopeAssetIds();
    if (!_isCurrentModalLoad(assetId, seq)) return;
    state.modalScopeAssetIds = ids;
    state.modalScopeAssetIndex = ids.indexOf(String(assetId || ""));
    renderModalNavigation();
  } catch {
    if (!_isCurrentModalLoad(assetId, seq)) return;
    state.modalScopeAssetIds = [];
    state.modalScopeAssetIndex = -1;
    renderModalNavigation();
  }
}

async function navigateModalBy(delta) {
  if (state.modalClassificationDirty) {
    Shared.showToast("Save or discard the pending review changes before leaving this item.", {
      type: "info",
      duration: 3200,
    });
    return;
  }
  const ids = Array.isArray(state.modalScopeAssetIds) ? state.modalScopeAssetIds : [];
  const currentIndex = Number(state.modalScopeAssetIndex || 0);
  if (!ids.length || currentIndex < 0) return;
  const nextIndex = Math.max(0, Math.min(ids.length - 1, currentIndex + delta));
  if (nextIndex === currentIndex) return;
  const nextId = String(ids[nextIndex] || "");
  if (!nextId) return;
  try {
    const asset = await _fetchAssetForModal(nextId);
    if (!asset) throw new Error("Asset not found");
    state.modalScopeAssetIndex = nextIndex;
    renderModalNavigation();
    await openModal(asset);
  } catch (e) {
    Shared.showToast(`Navigation failed: ${formatApiError(e)}`, { type: "error" });
  }
}

function _renderModalLabels(labels) {
  const labelsEl = $("#modalLabels");
  const labelsTitleEl = $("#modalLabelsTitle");
  const labelsSectionEl = $("#modalLabelsSection");
  if (!labelsEl) return;
  labelsEl.innerHTML = "";
  labelsEl.hidden = true;
  labelsEl.classList.remove("expanded");
  if (labelsTitleEl) labelsTitleEl.hidden = true;
  if (labelsSectionEl) labelsSectionEl.hidden = true;
  if (!Array.isArray(labels) || !labels.length) return;
  const INITIAL_SHOW = 30;
  const chips = labels.map((l) =>
    `<span class="label-chip" data-source="${escapeHtml(l.source || "")}" title="${escapeHtml(l.source || "")}">${escapeHtml(l.label)}</span>`
  );
  labelsEl.innerHTML = chips.slice(0, INITIAL_SHOW).join(" ");
  if (labels.length > INITIAL_SHOW) {
    const toggleBtn = document.createElement("button");
    toggleBtn.className = "labels-toggle";
    toggleBtn.textContent = `+${labels.length - INITIAL_SHOW} more`;
    toggleBtn.onclick = () => {
      labelsEl.innerHTML = chips.join(" ");
      labelsEl.classList.add("expanded");
    };
    labelsEl.appendChild(toggleBtn);
  }
  labelsEl.hidden = false;
  if (labelsTitleEl) labelsTitleEl.hidden = false;
  if (labelsSectionEl) labelsSectionEl.hidden = false;
}

async function _loadModalLabels(assetId, seq) {
  try {
    const resp = await fetch(_bp(`/api/assets/${encodeURIComponent(assetId)}/labels`));
    if (!resp.ok || !_isCurrentModalLoad(assetId, seq)) return;
    const data = await resp.json();
    if (!_isCurrentModalLoad(assetId, seq)) return;
    _renderModalLabels(data.labels || []);
  } catch {}
}

async function _loadModalAnnotations(assetId, seq) {
  try {
    const data = await api(`/api/annotations?asset_id=${encodeURIComponent(assetId)}`);
    if (!_isCurrentModalLoad(assetId, seq)) return;
    state.annotations = data.annotations || [];
  } catch {
    if (!_isCurrentModalLoad(assetId, seq)) return;
    state.annotations = [];
  }
  renderAnnotations();
  renderMarkers();
}

function _isBoilerplateClassificationReviewNote(note) {
  const text = String(note || "").trim().toLowerCase();
  if (!text) return false;
  if (text === "keep current track (modal review)") return true;
  return /^move to [a-z_]+ \(modal review\)$/.test(text);
}

function _effectiveClassificationTrack(review) {
  return String(review?.active_override_track || review?.current_track || "").trim();
}

function _preferredMoveTrack(track, fallback = "style_product_decor") {
  const normalized = String(track || "").trim();
  if (MOVABLE_CLASSIFICATION_TRACKS.includes(normalized)) return normalized;
  return fallback;
}

function _reviewFocusLabel(value) {
  const key = String(value || "").trim();
  return REVIEW_FOCUS_LABELS[key] || key || "";
}

function _mediaReliabilityLabel(value) {
  const key = String(value || "").trim();
  return MEDIA_RELIABILITY_LABELS[key] || key || "";
}

function _renderMediaReliabilityOverlay(elementId, value) {
  const el = $(elementId);
  if (!el) return;
  const label = _mediaReliabilityLabel(value);
  el.textContent = label;
  el.hidden = !label;
}

function renderModalSourceCandidatePanel(asset) {
  const panel = $("#modalSourceCandidatePanel");
  if (!panel) return;
  if (!isModalAdvancedEditingEnabled()) {
    panel.hidden = true;
    panel.open = false;
    return;
  }
  const candidate = asset?.source_link_candidate || {};
  const fetchStatus = String(candidate.fetch_status || "").trim();
  const pageTitle = String(candidate.page_title || "").trim();
  const heroImageUrl = String(candidate.hero_image_url || "").trim();
  const heroImageAlt = String(candidate.hero_image_alt || "").trim();
  const heroText = String(candidate.hero_text_excerpt || "").trim();
  const textExcerpt = String(candidate.text_excerpt || "").trim();
  const error = String(candidate.error || "").trim();
  const mediaCandidates = Array.isArray(candidate.media_candidates) ? candidate.media_candidates : [];
  const currentMedia = mediaCandidates.find((item) => item && item.current) || null;
  const currentRepresentationLabel = String(currentMedia?.representation_label || "").trim();
  const evidenceStatus = String(currentMedia?.evidence_status || "").trim();
  const replacementCandidates = mediaCandidates.filter((item) => item && !item.current);
  const selectableIds = new Set(
    replacementCandidates
      .filter((item) => item && item.selectable)
      .map((item) => String(item.id || "").trim())
      .filter(Boolean),
  );
  if (!selectableIds.has(state.modalSourceCandidateSelectedId)) {
    state.modalSourceCandidateSelectedId = "";
  }

  panel.hidden = false;
  const summaryEl = $("#modalSourceCandidateSummary");
  if (summaryEl) {
    summaryEl.textContent = currentRepresentationLabel
      ? `Current: ${currentRepresentationLabel}`
      : "Choose a replacement only if needed";
  }
  const statusEl = $("#modalSourceCandidateStatus");
  if (statusEl) {
    const parts = [];
    const busyAction = String(state.modalSourceCandidateBusyAction || "").trim();
    if (evidenceStatus.startsWith("refresh_required:")) {
      parts.push("Search evidence is waiting for Admin refresh.");
    }
    if (busyAction) {
      parts.push(busyAction === "promote"
        ? "Applying the selected media…"
        : "Checking the original post for source images…");
    } else if (state.modalSourceCandidateMessage) {
      parts.push(state.modalSourceCandidateMessage);
    } else if (fetchStatus === "fetched") {
      const sourceImageCount = mediaCandidates.filter((item) => item?.kind === "post_image").length;
      const commentImageCount = mediaCandidates.filter((item) => item?.kind === "post_image" && /comment image/i.test(String(item?.label || ""))).length;
      const savedMediaCount = mediaCandidates.filter((item) => item?.kind === "saved_media").length;
      parts.push(sourceImageCount
        ? (commentImageCount
          ? "Source media found, including comment images. Choose a replacement only if it is better."
          : "Source media found. Choose a post image or a generated text card.")
        : (savedMediaCount
          ? "No source images were found in the post. Previously used media remains available below."
          : "No source images were found in the post. The current media was not changed."));
    } else if (fetchStatus) {
      parts.push(fetchStatus);
    }
    if (error) parts.push(error);
    statusEl.textContent = parts.join(" · ");
    statusEl.hidden = !parts.length;
  }
  const galleryEl = $("#modalSourceCandidateGallery");
  if (galleryEl) {
    galleryEl.innerHTML = replacementCandidates.map((item) => {
      const candidateId = String(item?.id || "").trim();
      const kind = String(item?.kind || "").trim();
      const label = String(item?.label || "Source media").trim();
      const text = String(item?.text || "").trim();
      const rawPreviewUrl = String(item?.preview_url || "").trim();
      const previewUrl = rawPreviewUrl.startsWith("/") ? _bp(rawPreviewUrl) : rawPreviewUrl;
      const selectable = !!item?.selectable && !!candidateId;
      const selected = selectable && candidateId === state.modalSourceCandidateSelectedId;
      const cardTag = selectable ? "button" : "div";
      const attrs = selectable
        ? ` type="button" data-candidate-id="${escapeHtml(candidateId)}" aria-pressed="${selected ? "true" : "false"}"`
        : "";
      const preview = kind === "text_card"
        ? `<div class="modal-source-candidate-text-card">${escapeHtml(text)}</div>`
        : (previewUrl
          ? `<img src="${escapeHtml(previewUrl)}" alt="${escapeHtml(String(item?.alt || label))}" />`
          : "");
      const hint = kind === "text_card"
        ? "Built locally from the captured post text"
        : (kind === "saved_media"
          ? "Preserved from an earlier media choice"
        : (String(item?.source_page_url || "").trim()
          ? "Captured from the linked source page"
          : "Captured from the source post"));
      return `
        <${cardTag} class="modal-source-candidate-card${selected ? " is-selected" : ""}"${attrs}>
          <div class="modal-source-candidate-preview">${preview}</div>
          <div class="modal-source-candidate-label">${escapeHtml(label)}</div>
          <div class="modal-source-candidate-hint">${escapeHtml(hint)}</div>
        </${cardTag}>
      `;
    }).join("");
    galleryEl.querySelectorAll("button[data-candidate-id]").forEach((button) => {
      button.onclick = () => {
        state.modalSourceCandidateSelectedId = String(button.dataset.candidateId || "").trim();
        renderModalSourceCandidatePanel(asset);
      };
    });
  }
  const titleRow = $("#modalSourceCandidateTitleRow");
  const titleEl = $("#modalSourceCandidateTitle");
  if (titleRow) titleRow.hidden = !pageTitle;
  if (titleEl) titleEl.textContent = pageTitle;
  const heroTextRow = $("#modalSourceCandidateHeroTextRow");
  const heroTextEl = $("#modalSourceCandidateHeroText");
  if (heroTextRow) heroTextRow.hidden = !(heroImageUrl && heroText);
  if (heroTextEl) heroTextEl.textContent = heroText;
  const textRow = $("#modalSourceCandidateTextRow");
  const textEl = $("#modalSourceCandidateText");
  if (textRow) textRow.hidden = !textExcerpt;
  if (textEl) textEl.textContent = textExcerpt;
  const detailsEl = $("#modalSourceCandidateDetails");
  if (detailsEl) detailsEl.hidden = !(pageTitle || (heroImageUrl && heroText) || textExcerpt);

  const captureBtn = $("#modalSourceCandidateCaptureBtn");
  const promoteBtn = $("#modalSourceCandidatePromoteBtn");
  const busyAction = String(state.modalSourceCandidateBusyAction || "").trim();
  const busy = !!busyAction;
  if (captureBtn) {
    captureBtn.disabled = busy;
    captureBtn.classList.toggle("is-busy", busyAction === "capture");
    captureBtn.textContent = busyAction === "capture" ? "Finding source media…" : "Find source media";
    captureBtn.setAttribute("aria-busy", busyAction === "capture" ? "true" : "false");
  }
  if (promoteBtn) {
    promoteBtn.disabled = busy || !state.modalSourceCandidateSelectedId;
    promoteBtn.classList.toggle("is-busy", busyAction === "promote");
    promoteBtn.textContent = busyAction === "promote" ? "Using selected media…" : "Use selected media";
    promoteBtn.setAttribute("aria-busy", busyAction === "promote" ? "true" : "false");
  }
}

async function runModalSourceCandidateAction(action) {
  const asset = state.modalAsset;
  if (!asset || !asset.id) return;
  if (!isOwner()) {
    Shared.showToast("Source candidate tools are owner-only.", { type: "info" });
    return;
  }
  if (state.modalSourceCandidateBusyAction) return;
  const selectedCandidateId = String(state.modalSourceCandidateSelectedId || "").trim();
  if (action === "promote" && !selectedCandidateId) {
    Shared.showToast("Choose source media before using it.", { type: "info" });
    return;
  }
  const panel = $("#modalSourceCandidatePanel");
  if (panel) panel.open = true;
  state.modalSourceCandidateBusyAction = action;
  state.modalSourceCandidateMessage = "";
  renderModalSourceCandidatePanel(asset);
  if (action === "capture") {
    Shared.showToast("Checking the original post for source media…", { type: "info", duration: 2200 });
  }
  try {
    const requestAction = action === "promote" ? "promote_candidate" : action;
    const data = await api(`/api/assets/${encodeURIComponent(asset.id)}/source-link-candidate`, {
      method: "PUT",
      body: JSON.stringify({ action: requestAction, candidate_id: selectedCandidateId }),
    });
    const updated = data.asset || null;
    if (!updated) throw new Error("Updated asset missing from response");
    replaceAssetInState(updated);
    state.modalAsset = updated;
    state.modalSourceCandidateSelectedId = "";
    state.modalSourceCandidateBusyAction = "";
    renderModalSourceCandidatePanel(updated);
    if (action === "promote") {
      renderGrid();
      const promotedKind = String(data?.result?.kind || "").trim();
      Shared.showToast(
        promotedKind === "text_card"
          ? "Generated text card is now in use. Search evidence is waiting for Admin refresh."
          : (promotedKind === "saved_media"
            ? "Previously used image is now in use. Search evidence is waiting for Admin refresh."
            : "Selected source image is now in use. Search evidence is waiting for Admin refresh."),
        { type: "success", duration: 4200 },
      );
      await openModal(updated);
      const modalContent = document.querySelector("#modal .modalContent");
      if (modalContent) modalContent.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      const mediaCandidates = Array.isArray(updated?.source_link_candidate?.media_candidates)
        ? updated.source_link_candidate.media_candidates
        : [];
      const sourceImageCount = mediaCandidates.filter((item) => item?.kind === "post_image").length;
      const commentImageCount = mediaCandidates.filter((item) => item?.kind === "post_image" && /comment image/i.test(String(item?.label || ""))).length;
      const savedMediaCount = mediaCandidates.filter((item) => item?.kind === "saved_media").length;
      state.modalSourceCandidateMessage = sourceImageCount
        ? `${sourceImageCount} source image${sourceImageCount === 1 ? "" : "s"} found${commentImageCount ? `, including ${commentImageCount} from comments` : ""}. Choose a replacement only if it is better.`
        : (savedMediaCount
          ? "No source images were found in this post. Previously used media is still available below."
          : "No source images were found in this post. The current media was not changed.");
      renderModalSourceCandidatePanel(updated);
      Shared.showToast(state.modalSourceCandidateMessage, {
        type: sourceImageCount ? "success" : "info",
        duration: 4400,
      });
    }
  } catch (e) {
    state.modalSourceCandidateBusyAction = "";
    state.modalSourceCandidateMessage = action === "capture"
      ? `Source media check failed: ${formatApiError(e)}`
      : `Media change failed: ${formatApiError(e)}`;
    if (state.modalAsset?.id === asset.id) renderModalSourceCandidatePanel(state.modalAsset);
    Shared.showToast(state.modalSourceCandidateMessage, { type: "error", duration: 4200 });
  } finally {
    state.modalSourceCandidateBusyAction = "";
    if (state.modalAsset?.id === asset.id) renderModalSourceCandidatePanel(state.modalAsset);
  }
}

function _modalClassificationNeedsReview(review) {
  if (!review || typeof review !== "object") return false;
  if (Number(review.current_is_ambiguous || 0) > 0) return true;
  if (String(review.source_qc_verdict || "").trim() === "conflicting") return true;
  if (String(review.active_override_track || "").trim()) return true;
  return false;
}

function _modalClassificationStatusText(review) {
  const messages = [];
  if (Number(review?.current_is_ambiguous || 0) > 0) {
    messages.push("Classifier is unsure.");
  }
  if (String(review?.source_qc_verdict || "").trim() === "conflicting") {
    messages.push("Source link conflicts with the current track.");
  }
  if (String(review?.active_override_track || "").trim()) {
    messages.push("Human review is saved and will persist.");
  }
  return messages.join(" ");
}

function _setModalClassificationDirty(dirty) {
  state.modalClassificationDirty = !!dirty;
  const draftStatus = $("#modalClassificationDraftStatus");
  const discardBtn = $("#modalClassificationDiscardBtn");
  if (draftStatus) {
    const irrelevantToggle = $("#modalClassificationIrrelevantToggle");
    const savedIrrelevant = irrelevantToggle?.dataset.savedIrrelevant === "true";
    if (irrelevantToggle?.checked && !savedIrrelevant) {
      draftStatus.textContent = "This item will be marked irrelevant when saved. Switch it off to cancel, or save before moving to another item.";
    } else if (!irrelevantToggle?.checked && savedIrrelevant) {
      draftStatus.textContent = "This item will be restored to the selected track when saved. Choose the track, or discard this change.";
    } else {
      draftStatus.textContent = "Unsaved review changes. Save them or discard them before moving to another item.";
    }
    draftStatus.hidden = !state.modalClassificationDirty;
  }
  if (discardBtn) discardBtn.hidden = !state.modalClassificationDirty;
}

function _syncModalClassificationControls() {
  const irrelevantToggle = $("#modalClassificationIrrelevantToggle");
  const moveTo = $("#modalClassificationMoveTo");
  const keepBtn = $("#modalClassificationKeepBtn");
  const saveBtn = $("#modalClassificationSaveBtn");
  const savedIrrelevant = irrelevantToggle?.dataset.savedIrrelevant === "true";
  const pendingIrrelevant = !!irrelevantToggle?.checked;
  const isSavedIrrelevant = savedIrrelevant && pendingIrrelevant;
  if (moveTo) moveTo.disabled = pendingIrrelevant;
  if (keepBtn) {
    keepBtn.classList.toggle("is-saved-state", isSavedIrrelevant);
    keepBtn.disabled = isSavedIrrelevant ? true : (pendingIrrelevant ? false : keepBtn.dataset.savedDisabled === "true");
    keepBtn.textContent = isSavedIrrelevant
      ? "Saved as irrelevant"
      : pendingIrrelevant
      ? "Save as irrelevant"
      : (savedIrrelevant ? "Save restored track" : "Save, keep track");
  }
  if (saveBtn) {
    saveBtn.textContent = "Save and move";
    saveBtn.hidden = pendingIrrelevant || savedIrrelevant;
  }
}

function _refreshModalClassificationDirty() {
  const irrelevantToggle = $("#modalClassificationIrrelevantToggle");
  const controls = [
    $("#modalClassificationMoveTo"),
    $("#modalClassificationFocusSelect"),
    $("#modalClassificationMediaSelect"),
    $("#modalClassificationComment"),
  ];
  const changedValue = controls.some((control) => (
    control && String(control.value || "") !== String(control.dataset.savedValue || "")
  ));
  const changedIrrelevant = !!irrelevantToggle && (
    irrelevantToggle.checked !== (irrelevantToggle.dataset.savedIrrelevant === "true")
  );
  _setModalClassificationDirty(changedValue || changedIrrelevant);
}

function discardModalClassificationChanges() {
  if (!state.modalAsset) return;
  renderModalClassificationPanel(state.modalAsset);
  Shared.showToast("Pending review changes discarded.", { type: "info", duration: 1800 });
}

function renderModalClassificationPanel(asset) {
  const panel = $("#modalClassificationPanel");
  if (!panel) return;
  if (!isModalAdvancedEditingEnabled()) {
    panel.hidden = true;
    return;
  }
  const review = asset?.classification_review || {};
  const currentTrack = String(review.current_track || "").trim();
  const currentConfidence = Number(review.current_confidence || 0);
  const currentReason = String(review.current_reason || "").trim();
  const sourceVerdict = String(review.source_qc_verdict || "").trim();
  const sourceTrack = String(review.source_qc_inferred_track || "").trim();
  const sourceConfidence = Number(review.source_qc_confidence || 0);
  const sourceReason = String(review.source_qc_reason || "").trim();
  const overrideTrack = String(review.active_override_track || "").trim();
  const overrideActor = String(review.active_override_actor || "").trim();
  const overrideNote = String(review.active_override_note || "").trim();
  const overrideCreatedAt = String(review.active_override_created_at || "").trim();
  const overrideFocus = String(review.active_review_focus || "").trim();
  const overrideMedia = String(review.active_media_reliability || "").trim();
  const effectiveTrack = _effectiveClassificationTrack(review);
  const needsReview = _modalClassificationNeedsReview(review);
  const statusText = _modalClassificationStatusText(review);
  const cleanedOverrideNote = _isBoilerplateClassificationReviewNote(overrideNote) ? "" : overrideNote;

  panel.hidden = false;

  const statusEl = $("#modalClassificationStatus");
  if (statusEl) {
    statusEl.textContent = statusText || (needsReview ? "" : "Advanced review tools are available for this item.");
    statusEl.hidden = !(statusEl.textContent || "").trim();
  }

  const currentEl = $("#modalClassificationCurrent");
  if (currentEl) {
    const parts = [];
    if (currentTrack) parts.push(classificationTrackLabel(currentTrack));
    if (currentConfidence) parts.push(`${Math.round(currentConfidence * 100)}%`);
    currentEl.textContent = parts.join(" · ") || "No current track";
    currentEl.title = currentReason || "";
  }

  const sourceRow = $("#modalClassificationSourceRow");
  const sourceEl = $("#modalClassificationSource");
  const sourceReasonEl = $("#modalClassificationSourceReason");
  const hasSourceConflict = sourceVerdict === "conflicting" && !!sourceTrack;
  if (sourceRow) sourceRow.hidden = !hasSourceConflict;
  if (sourceEl) {
    const parts = [];
    if (sourceTrack) parts.push(classificationTrackLabel(sourceTrack));
    if (sourceConfidence) parts.push(`${Math.round(sourceConfidence * 100)}%`);
    sourceEl.textContent = hasSourceConflict ? parts.join(" · ") : "";
  }
  if (sourceReasonEl) {
    sourceReasonEl.textContent = sourceReason;
    sourceReasonEl.hidden = !(hasSourceConflict && sourceReason);
  }

  const overrideRow = $("#modalClassificationOverrideRow");
  const overrideEl = $("#modalClassificationOverride");
  const overrideMetaEl = $("#modalClassificationOverrideMeta");
  if (overrideRow) overrideRow.hidden = !overrideTrack;
  if (overrideEl) overrideEl.textContent = overrideTrack ? classificationTrackLabel(overrideTrack) : "";
  if (overrideMetaEl) {
    const parts = [];
    if (overrideActor) parts.push(`by ${overrideActor}`);
    if (overrideCreatedAt) parts.push(overrideCreatedAt.slice(0, 10));
    if (cleanedOverrideNote) parts.push(cleanedOverrideNote);
    overrideMetaEl.textContent = parts.join(" · ");
    overrideMetaEl.hidden = !parts.length;
  }

  const focusRow = $("#modalClassificationFocusRow");
  const focusEl = $("#modalClassificationFocus");
  if (focusRow) focusRow.hidden = !overrideFocus;
  if (focusEl) focusEl.textContent = overrideFocus ? _reviewFocusLabel(overrideFocus) : "";
  const mediaRow = $("#modalClassificationMediaRow");
  const mediaEl = $("#modalClassificationMedia");
  if (mediaRow) mediaRow.hidden = !overrideMedia;
  if (mediaEl) mediaEl.textContent = overrideMedia ? _mediaReliabilityLabel(overrideMedia) : "";

  const editor = $("#modalClassificationEditor");
  const moveTo = $("#modalClassificationMoveTo");
  const focusSelect = $("#modalClassificationFocusSelect");
  const mediaSelect = $("#modalClassificationMediaSelect");
  const comment = $("#modalClassificationComment");
  const keepBtn = $("#modalClassificationKeepBtn");
  const saveBtn = $("#modalClassificationSaveBtn");
  const discardBtn = $("#modalClassificationDiscardBtn");
  const irrelevantToggle = $("#modalClassificationIrrelevantToggle");
  if (editor) editor.hidden = false;
  const defaultTrack = overrideTrack || (hasSourceConflict ? sourceTrack : currentTrack);
  if (moveTo) moveTo.value = _preferredMoveTrack(defaultTrack);
  if (focusSelect) focusSelect.value = overrideFocus && REVIEW_FOCUS_LABELS[overrideFocus] ? overrideFocus : "";
  if (mediaSelect) mediaSelect.value = overrideMedia && MEDIA_RELIABILITY_LABELS[overrideMedia] ? overrideMedia : "";
  if (comment) comment.value = cleanedOverrideNote || "";
  for (const control of [moveTo, focusSelect, mediaSelect, comment]) {
    if (control) control.dataset.savedValue = String(control.value || "");
  }
  if (moveTo) moveTo.onchange = _refreshModalClassificationDirty;
  if (focusSelect) focusSelect.onchange = _refreshModalClassificationDirty;
  if (mediaSelect) mediaSelect.onchange = _refreshModalClassificationDirty;
  if (comment) comment.oninput = _refreshModalClassificationDirty;
  if (discardBtn) discardBtn.onclick = discardModalClassificationChanges;
  if (irrelevantToggle) {
    irrelevantToggle.checked = effectiveTrack === "irrelevant";
    irrelevantToggle.dataset.savedIrrelevant = effectiveTrack === "irrelevant" ? "true" : "false";
    irrelevantToggle.onchange = () => {
      _syncModalClassificationControls();
      _refreshModalClassificationDirty();
    };
  }
  if (keepBtn) {
    keepBtn.dataset.savedDisabled = !effectiveTrack ? "true" : "false";
    keepBtn.disabled = !effectiveTrack;
  }
  if (saveBtn) saveBtn.disabled = false;
  if (irrelevantToggle) irrelevantToggle.disabled = false;
  _syncModalClassificationControls();
  _setModalClassificationDirty(false);
}

async function saveModalClassificationReview(opts = {}) {
  const asset = state.modalAsset;
  if (!asset || !asset.id) return;
  if (!isOwner()) {
    Shared.showToast("Classification review is owner-only.", { type: "info" });
    return;
  }
  const review = asset.classification_review || {};
  const currentTrack = _effectiveClassificationTrack(review);
  const moveTo = $("#modalClassificationMoveTo");
  const focusSelect = $("#modalClassificationFocusSelect");
  const mediaSelect = $("#modalClassificationMediaSelect");
  const comment = $("#modalClassificationComment");
  const keepBtn = $("#modalClassificationKeepBtn");
  const saveBtn = $("#modalClassificationSaveBtn");
  const discardBtn = $("#modalClassificationDiscardBtn");
  const irrelevantToggle = $("#modalClassificationIrrelevantToggle");
  const track = String(
    irrelevantToggle?.checked
      ? "irrelevant"
      : (opts.keepCurrent && currentTrack !== "irrelevant" ? currentTrack : (opts.track || moveTo?.value || ""))
  ).trim();
  const reviewFocus = String(opts.reviewFocus ?? focusSelect?.value ?? "").trim();
  const mediaReliability = String(opts.mediaReliability ?? mediaSelect?.value ?? "").trim();
  const note = String(comment?.value || "").trim();
  if (!track) {
    Shared.showToast("Choose a track first.", { type: "info" });
    return;
  }
  if (keepBtn) keepBtn.disabled = true;
  if (saveBtn) saveBtn.disabled = true;
  if (discardBtn) discardBtn.disabled = true;
  if (irrelevantToggle) irrelevantToggle.disabled = true;
  if (moveTo) moveTo.disabled = true;
  if (focusSelect) focusSelect.disabled = true;
  if (mediaSelect) mediaSelect.disabled = true;
  if (comment) comment.disabled = true;
  try {
    const data = await api(`/api/assets/${encodeURIComponent(asset.id)}/classification-review`, {
      method: "PUT",
      body: JSON.stringify({ track, note, review_focus: reviewFocus, media_reliability: mediaReliability }),
    });
    const updated = data.asset || null;
    if (!updated) throw new Error("Updated asset missing from response");
    replaceAssetInState(updated);
    state.modalAsset = updated;
    renderModalClassificationPanel(updated);
    _renderMediaReliabilityOverlay(
      "#modalMediaOverlay",
      updated?.classification_review?.active_media_reliability || ""
    );
    Shared.showToast(
      track === "irrelevant"
        ? "Marked irrelevant."
        : (track === currentTrack ? "Kept current classification." : `Moved to ${classificationTrackLabel(track)}.`),
      { type: "success", duration: 2600 }
    );
    await Promise.all([loadCatalogTree(), loadAssets()]);
  } catch (e) {
    Shared.showToast(formatApiError(e), { type: "error", duration: 3200 });
  } finally {
    if (keepBtn) keepBtn.disabled = false;
    if (saveBtn) saveBtn.disabled = false;
    if (discardBtn) discardBtn.disabled = false;
    if (irrelevantToggle) irrelevantToggle.disabled = false;
    if (moveTo) moveTo.disabled = false;
    if (focusSelect) focusSelect.disabled = false;
    if (mediaSelect) mediaSelect.disabled = false;
    if (comment) comment.disabled = false;
    _syncModalClassificationControls();
  }
}

async function saveWorkingTitleFromModal(opts = {}) {
  const asset = state.modalAsset;
  if (!asset || !asset.id) return;
  if (!isOwner()) {
    Shared.showToast("Title editing is owner-only.", { type: "info" });
    return;
  }
  const saveBtn = $("#modalTitleSaveBtn");
  const suggestedBtn = $("#modalTitleUseSuggestedBtn");
  const input = $("#modalWorkingTitleInput");
  const useSuggested = !!opts.useSuggested;
  const title = useSuggested
    ? ""
    : String(input?.value || "").trim();
  if (!useSuggested && !title) {
    Shared.showToast("Enter a title first.", { type: "info" });
    return;
  }
  const payload = {
    expected_title: String(asset.title || "").trim(),
    use_suggested: useSuggested,
  };
  if (!useSuggested) payload.title = title;
  if (saveBtn) saveBtn.disabled = true;
  if (suggestedBtn) suggestedBtn.disabled = true;
  if (input) input.disabled = true;
  try {
    const data = await api(`/api/assets/${encodeURIComponent(asset.id)}/title`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    const updated = data.asset || null;
    if (!updated) throw new Error("Updated asset missing from response");
    replaceAssetInState(updated);
    renderGrid();
    await openModal(updated);
    Shared.showToast("Title saved.", { type: "success", duration: 1800 });
  } catch (e) {
    Shared.showToast(formatApiError(e), { type: "error", duration: 3200 });
  } finally {
    if (input) input.disabled = false;
    if (saveBtn) saveBtn.disabled = false;
    if (suggestedBtn) suggestedBtn.disabled = false;
  }
}

async function openModal(asset, options = {}) {
  const shouldHydrate = options.hydrate !== false;
  const advancedEditing = Object.prototype.hasOwnProperty.call(options, "advancedEditing")
    ? !!options.advancedEditing
    : isReviewModeActive();
  const modalSeq = (Number(state.modalLoadSeq || 0) + 1);
  state.modalLoadSeq = modalSeq;
  state.modalAdvancedEditing = isOwner() && advancedEditing;
  if (String(state.modalAsset?.id || "") !== String(asset?.id || "")) {
    state.modalSourceCandidateSelectedId = "";
    state.modalSourceCandidateBusyAction = "";
    state.modalSourceCandidateMessage = "";
  }
  state.modalAsset = asset;

  const title = displayTitle(asset);
  const metaParts = [];
  if (asset.board) metaParts.push(asset.board);
  metaParts.push(asset.source || "");
  if (asset.created_at) metaParts.push(asset.created_at.slice(0, 10));

  $("#modalTitle").textContent = title;
  const titleQualityEl = $("#modalTitleQuality");
  if (titleQualityEl) {
    const q = titleQualityForAsset(asset);
    if (q.label) {
      titleQualityEl.className = `title-quality-badge modal-title-quality ${q.kind}`;
      titleQualityEl.textContent = q.label;
      titleQualityEl.title = q.tooltip || q.label;
      titleQualityEl.hidden = false;
    } else {
      titleQualityEl.hidden = true;
      titleQualityEl.textContent = "";
      titleQualityEl.title = "";
      titleQualityEl.className = "title-quality-badge modal-title-quality";
    }
  }
  $("#modalMeta").textContent = metaParts.filter(Boolean).join(" · ");
  updateActorContextChips();
  const modalAssetIdRow = $("#modalAssetIdRow");
  const modalAssetIdText = $("#modalAssetIdText");
  const assetIdText = String(asset.id || "").trim();
  if (modalAssetIdText) modalAssetIdText.textContent = assetIdText;
  if (modalAssetIdRow) {
    modalAssetIdRow.hidden = !(isOwner() && assetIdText);
  }
  renderModalTitlePanel(asset);
  renderModalClassificationPanel(asset);
  renderModalSourceCandidatePanel(asset);
  renderModalCurationActions(asset);
  renderModalNavigation();
  _renderMediaReliabilityOverlay("#modalMediaOverlay", asset?.classification_review?.active_media_reliability || "");
  const titleSaveBtn = $("#modalTitleSaveBtn");
  if (titleSaveBtn) titleSaveBtn.onclick = () => saveWorkingTitleFromModal({ useSuggested: false });
  const titleSuggestedBtn = $("#modalTitleUseSuggestedBtn");
  if (titleSuggestedBtn) titleSuggestedBtn.onclick = () => saveWorkingTitleFromModal({ useSuggested: true });
  const classificationKeepBtn = $("#modalClassificationKeepBtn");
  if (classificationKeepBtn) {
    classificationKeepBtn.onclick = () => saveModalClassificationReview({
      keepCurrent: true,
    });
  }
  const classificationSaveBtn = $("#modalClassificationSaveBtn");
  if (classificationSaveBtn) classificationSaveBtn.onclick = () => saveModalClassificationReview();
  const sourceCandidateCaptureBtn = $("#modalSourceCandidateCaptureBtn");
  if (sourceCandidateCaptureBtn) sourceCandidateCaptureBtn.onclick = () => runModalSourceCandidateAction("capture");
  const sourceCandidatePromoteBtn = $("#modalSourceCandidatePromoteBtn");
  if (sourceCandidatePromoteBtn) sourceCandidatePromoteBtn.onclick = () => runModalSourceCandidateAction("promote");
  const modalPrevBtn = $("#modalPrevBtn");
  if (modalPrevBtn) modalPrevBtn.onclick = () => { void navigateModalBy(-1); };
  const modalNextBtn = $("#modalNextBtn");
  if (modalNextBtn) modalNextBtn.onclick = () => { void navigateModalBy(1); };

  const img = $("#modalImage");
  const video = $("#modalVideo");
  const modalVideoUrl = videoUrlForAsset(asset);
  if (modalVideoUrl) {
    _loadModalVideoAsset(asset, modalSeq, modalVideoUrl);
  } else {
    if (video) {
      video.pause();
      video.onerror = null;
      video.onloadedmetadata = null;
      video.removeAttribute("src");
      video.hidden = true;
    }
    _loadModalImageAsset(asset, modalSeq);
  }

  // Content kind badge
  const badgeWrap = $("#modalBadge");
  if (badgeWrap) {
    const kind = (asset.content_kind || "").trim();
    const kindLabels = { pin: "Pin", reel: "Reel", video: "Video", photo: "Photo", scan: "Clip", link: "Link", post: "Post" };
    if (kind) {
      badgeWrap.textContent = kindLabels[kind.toLowerCase()] || kind;
      badgeWrap.hidden = false;
    } else {
      badgeWrap.hidden = true;
    }
  }

  // Creator
  const creatorEl = $("#modalCreator");
  if (creatorEl) {
    const creator = (asset.creator_name || "").trim();
    creatorEl.textContent = creator ? `by ${creator}` : "";
    creatorEl.hidden = !creator;
  }

  // Description (post_text / closeup_desc / seo_alt_text)
  const descEl = $("#modalDescription");
  if (descEl) {
    const desc = (asset.post_text || "").trim()
      || (asset.closeup_desc || "").trim()
      || (asset.seo_alt_text || "").trim();
    descEl.textContent = desc;
    descEl.hidden = !desc;
  }

  // Hashtags
  const hashtagsEl = $("#modalHashtags");
  if (hashtagsEl) {
    const raw = (asset.hashtags || "").trim();
    if (raw) {
      const tags = raw.split(",").map(t => t.trim()).filter(Boolean);
      hashtagsEl.innerHTML = tags.map(t => `<span class="hashtag-chip">${escapeHtml(t)}</span>`).join(" ");
      hashtagsEl.hidden = false;
    } else {
      hashtagsEl.innerHTML = "";
      hashtagsEl.hidden = true;
    }
  }

  renderModalTriageInfo(asset);

  // Labels / tags
  const labelsEl = $("#modalLabels");
  if (labelsEl) {
    labelsEl.innerHTML = "";
    labelsEl.hidden = true;
    labelsEl.classList.remove("expanded");
  }
  const labelsSectionEl = $("#modalLabelsSection");
  if (labelsSectionEl) labelsSectionEl.hidden = true;
  const labelsTitleEl = $("#modalLabelsTitle");
  if (labelsTitleEl) labelsTitleEl.hidden = true;

  // Engagement stats
  const engagementEl = $("#modalEngagement");
  if (engagementEl) {
    let engHtml = "";
    try {
      const eng = asset.engagement_json ? JSON.parse(asset.engagement_json) : null;
      if (eng) {
        const parts = [];
        if (eng.repins != null) parts.push(`${eng.repins} repins`);
        if (eng.comments != null) parts.push(`${eng.comments} comments`);
        if (eng.likes != null) parts.push(`${eng.likes} likes`);
        if (eng.reactions != null) parts.push(`${eng.reactions} reactions`);
        if (eng.shares != null) parts.push(`${eng.shares} shares`);
        engHtml = parts.join(" · ");
      }
    } catch {}
    engagementEl.textContent = engHtml;
    engagementEl.hidden = !engHtml;
  }

  // Image dimensions
  const dimsEl = $("#modalDimensions");
  if (dimsEl) {
    const w = asset.image_width;
    const h = asset.image_height;
    if (w && h) {
      dimsEl.textContent = `${w} × ${h}`;
      dimsEl.hidden = false;
    } else {
      dimsEl.hidden = true;
    }
  }

  // Print button
  const printBtn = $("#printAssetBtn");
  if (printBtn) {
    printBtn.disabled = false;
    printBtn.title = "";
    printBtn.onclick = (e) => {
      if (e) { e.preventDefault(); e.stopPropagation(); }
      printModalAsset(asset);
    };
  }
  const annHintText = $("#annHintText");
  const annQuestionToggle = $("#annQuestionToggle");
  const annQuestionLabel = $("#annQuestionLabel");
  const annotationsTitle = $("#modalAnnotationsTitle");
  const stagePrompt = $("#modalStagePrompt");
  const notesSection = $("#modalNotesSection");
  const notesTitle = $("#modalNotesTitle");
  const collaboratorOnlyQuestions = false;
  if (annHintText) {
    annHintText.textContent = "Click on the image to add a note.";
  }
  if (annQuestionToggle) {
    annQuestionToggle.checked = false;
    annQuestionToggle.disabled = true;
  }
  if (annQuestionLabel) {
    annQuestionLabel.hidden = true;
  }
  if (annotationsTitle) {
    annotationsTitle.textContent = "Annotations";
    annotationsTitle.classList.remove("sectionTitle-questions");
    annotationsTitle.classList.add("sectionTitle-annotations");
  }
  if (notesTitle) {
    notesTitle.textContent = "Notes";
    notesTitle.classList.remove("sectionTitle-context");
  }
  if (stagePrompt) {
    stagePrompt.hidden = true;
    stagePrompt.innerHTML = "";
  }
  const annHintRow = annHintText ? annHintText.closest(".ann-hint-row") : null;
  if (annHintRow) {
    annHintRow.hidden = false;
  }

  // Notes
  const notesArea = $("#assetNotes");
  const notesHint = $("#assetNotesHint");
  if (notesArea) {
    const notesValue = String(asset.notes || "");
    const hasNotes = !!notesValue.trim();
    notesArea.value = notesValue;
    const editable = canEditAssetNotes();
    notesArea.placeholder = editable ? "General notes about this image…" : "Owner notes will appear here.";
    notesArea.readOnly = !editable;
    notesArea.disabled = false;
    notesArea.oninput = editable ? () => scheduleNotesUpdate(asset.id, notesArea.value) : null;
    notesArea.onblur = editable ? () => { void persistAssetNotesNow(asset.id, notesArea.value); } : null;
    notesArea.onfocus = () => { clearActiveAnnotationSelection(); };
    if (notesSection) notesSection.hidden = !editable && !hasNotes;
    if (notesSection) notesSection.classList.toggle("modal-side-section-readonly", !editable);
    if (notesHint) {
      notesHint.hidden = editable;
      notesHint.textContent = editable ? "" : "Notes are read-only in this view.";
    }
  }

  // Scan page nav
  const imageStage = $("#imageStage");
  const existingNav = imageStage && imageStage.querySelector(".modalScanNav");
  if (existingNav) existingNav.remove();

  if (asset.source === "scan" && (asset.scan_group_member_ids || []).length > 1) {
    const pages = asset.scan_group_member_ids;
    state.modalScanPages = pages;
    const currentIdx = Math.max(0, pages.indexOf(asset.id));
    state.modalScanPageIndex = currentIdx;
    const absolutePage = _scanPageFromRef(asset.source_ref || "") || 1;
    state.modalScanStartPage = Math.max(1, absolutePage - currentIdx);
    const navEl = document.createElement("div");
    navEl.className = "modalScanNav";
    navEl.innerHTML = `
      <button class="modalScanPrev" ${state.modalScanPageIndex === 0 ? "disabled" : ""}>‹</button>
      <span class="modalScanIndicator">Page ${state.modalScanPageIndex + 1} of ${pages.length}</span>
      <button class="modalScanNext" ${state.modalScanPageIndex === pages.length - 1 ? "disabled" : ""}>›</button>
    `;
    navEl.querySelector(".modalScanPrev").onclick = () => _navModalScan(-1);
    navEl.querySelector(".modalScanNext").onclick = () => _navModalScan(1);
    if (imageStage) imageStage.appendChild(navEl);
  } else {
    state.modalScanPages = null;
    state.modalScanPageIndex = 0;
    state.modalScanStartPage = _scanPageFromRef(asset.source_ref || "") || 1;
  }

  renderModalSourceLinks(state.modalAsset || asset);

  $("#modal").classList.remove("hidden");
  state.annotations = [];
  renderAnnotations();
  renderMarkers();
  void _loadModalNavigation(asset.id, modalSeq);
  void _loadModalLabels(asset.id, modalSeq);
  void _loadModalAnnotations(asset.id, modalSeq);
  if (shouldHydrate) {
    void (async () => {
      const hydrated = await hydrateModalAsset(asset);
      if (!_isCurrentModalLoad(asset.id, modalSeq)) return;
      const merged = hydrated && typeof hydrated === "object" ? { ...asset, ...hydrated } : asset;
      state.modalAsset = merged;
      await openModal(merged, { hydrate: false });
    })();
  }
}

async function removeAssetsFromCollections(assetIds, collectionIds) {
  const ids = _uniqNonEmpty(assetIds);
  const targetCollections = _uniqNonEmpty(collectionIds);
  const out = [];
  for (const collectionId of targetCollections) {
    const data = await api(`/api/collections/${encodeURIComponent(collectionId)}/items/remove`, {
      method: "POST",
      body: JSON.stringify({ asset_ids: ids }),
    });
    out.push({ collectionId, removed: Number(data?.removed || 0) });
  }
  return out;
}

async function addAssetsToCollections(assetIds, collectionIds) {
  const ids = _uniqNonEmpty(assetIds);
  const targetCollections = _uniqNonEmpty(collectionIds);
  for (const collectionId of targetCollections) {
    await api(`/api/collections/${encodeURIComponent(collectionId)}/items`, {
      method: "POST",
      body: JSON.stringify({ asset_ids: ids }),
    });
  }
}

function closeModal() {
  if (state.modalClassificationDirty && !window.confirm("Discard unsaved review changes?")) return;
  const currentAsset = state.modalAsset;
  const notesArea = $("#assetNotes");
  if (currentAsset && notesArea && canEditAssetNotes()) {
    void persistAssetNotesNow(currentAsset.id, notesArea.value);
  }
  const activeAnnId = state.activeAnnotationId;
  const floatingTextEl = $("#floatingText");
  if (activeAnnId && floatingTextEl) {
    void persistAnnotationNow(activeAnnId, { text: floatingTextEl.value });
  }
  clearActiveAnnotationSelection();
  $("#modal").classList.add("hidden");
  state.modalAsset = null;
  state.modalSourceCandidateSelectedId = "";
  state.modalSourceCandidateBusyAction = "";
  state.modalSourceCandidateMessage = "";
  state.modalAdvancedEditing = false;
  state.modalClassificationDirty = false;
  state.annotations = [];
  state.activeAnnotationId = null;
  state.modalScopeAssetIds = [];
  state.modalScopeAssetIndex = -1;
  const img = $("#modalImage");
  if (img) img.style.display = "block";
  const video = $("#modalVideo");
  if (video) {
    video.pause();
    video.onerror = null;
    video.onloadedmetadata = null;
    video.removeAttribute("src");
    video.hidden = true;
  }
  renderModalNavigation();
  if (state.view === "review") void renderReviewCard();
}

async function _navModalScan(delta) {
  if (!state.modalScanPages) return;
  const newIdx = Math.max(0, Math.min(state.modalScanPages.length - 1, state.modalScanPageIndex + delta));
  if (newIdx === state.modalScanPageIndex) return;
  state.modalScanPageIndex = newIdx;
  const siblingId = state.modalScanPages[newIdx];
  const curAsset = state.modalAsset;
  const absolutePage = Math.max(1, (state.modalScanStartPage || 1) + newIdx);
  const sourceBase = (curAsset.source_ref || "").replace(/#p\d+$/i, "");
  const siblingSourceRef = sourceBase ? `${sourceBase}#p${absolutePage}` : (curAsset.source_ref || "");
  state.modalAsset = { ...curAsset, id: siblingId, source_ref: siblingSourceRef };
  const modalImage = $("#modalImage");
  if (modalImage) modalImage.src = `${_B}/media/${siblingId}?kind=thumb`;
  const indicator = document.querySelector(".modalScanIndicator");
  if (indicator) indicator.textContent = `Page ${newIdx + 1} of ${state.modalScanPages.length}`;
  const prevBtn = document.querySelector(".modalScanPrev");
  const nextBtn = document.querySelector(".modalScanNext");
  if (prevBtn) prevBtn.disabled = newIdx === 0;
  if (nextBtn) nextBtn.disabled = newIdx === state.modalScanPages.length - 1;
  renderModalSourceLinks(state.modalAsset);
  await loadAnnotations(siblingId);
  renderAnnotations();
  renderMarkers();
}

// ─── Notes / annotations ────────────────────────────────────────────────────────

async function persistAssetNotesNow(assetId, value) {
  clearTimeout(state.noteTimers[assetId]);
  delete state.noteTimers[assetId];
  try {
    await api(`/api/assets/${encodeURIComponent(assetId)}`, {
      method: "PUT",
      body: JSON.stringify({ notes: value }),
    });
  } catch (_) {}
}

function scheduleNotesUpdate(assetId, value) {
  clearTimeout(state.noteTimers[assetId]);
  state.noteTimers[assetId] = setTimeout(() => { void persistAssetNotesNow(assetId, value); }, 800);
}

async function loadAnnotations(assetId) {
  try {
    const data = await api(`/api/annotations?asset_id=${encodeURIComponent(assetId)}`);
    state.annotations = data.annotations || [];
  } catch { state.annotations = []; }
}

function canManageAnnotation(ann) {
  if (!ann) return false;
  if (isOwner()) return true;
  const actorId = String(state.actor?.id || "").trim();
  const annActorId = String(ann.actor_id || "").trim();
  return !!actorId && !!annActorId && actorId === annActorId;
}

function canEditAssetNotes() {
  return isOwner();
}

function annotationActorClass(ann) {
  if (!ann || !ann.actor_name) return "";
  const actorId = String(state.actor?.id || "").trim();
  const annActorId = String(ann.actor_id || "").trim();
  if (isOwner() && actorId && annActorId && actorId === annActorId) {
    return "ann-actor-owner";
  }
  if (actorId && annActorId && actorId === annActorId) {
    return "ann-actor-self";
  }
  return "ann-actor-other";
}

function renderAnnotations() {
  const wrap = $("#annList");
  if (!wrap) return;
  wrap.innerHTML = "";
  let annotationNumber = 0;
  state.annotations.forEach((ann, idx) => {
    const isQuestion = false;
    const isResolved = false;
    const canManage = canManageAnnotation(ann);
    const displayNumber = ++annotationNumber;
    const el = document.createElement("div");
    el.className = `listItem annItem${state.activeAnnotationId === ann.id ? " active" : ""}${canManage ? "" : " ann-readonly"}`;

    const marker = `#${displayNumber}`;
    const actorCls = annotationActorClass(ann);
    const actorLabel = ann.actor_name ? `<span class="ann-actor ${actorCls}">${escapeHtml(ann.actor_name)}</span>` : "";
    const resolveBtn = "";
    const deleteBtn = canManage
      ? `<button class="iconBtn danger" data-del="${ann.id}" type="button">\u00d7</button>`
      : "";
    const readonlyHint = canManage
      ? ""
      : `<div class="ann-readonly-note">Read-only: only the author or owner can edit.</div>`;

    el.innerHTML = `
      <div class="annHeader">
        <strong>${marker}</strong>${actorLabel}${resolveBtn}
        ${deleteBtn}
      </div>
      <textarea data-ann="${ann.id}" ${canManage ? "" : "readonly"}>${escapeHtml(ann.text || "")}</textarea>
      ${readonlyHint}
    `;
    el.onclick = () => setActiveAnnotation(ann.id);
    const ta = el.querySelector("textarea");
    if (ta && canManage) {
      ta.addEventListener("input", async () => {
        ann.text = ta.value;
        syncFloatingText(ann.id, ta.value);
        scheduleAnnotationUpdate(ann.id, { text: ta.value });
      });
      ta.addEventListener("blur", () => {
        void persistAnnotationNow(ann.id, { text: ta.value });
      });
      ta.addEventListener("keydown", (event) => {
        _handleAnnotationEditorKeydown(event, ann.id);
      });
    }
    const delEl = el.querySelector("[data-del]");
    if (delEl) {
      delEl.onclick = async (e) => {
        e.stopPropagation();
        await deleteAnnotationWithUndo(ann);
      };
    }
    const resolveEl = el.querySelector("[data-resolve]");
    if (resolveEl) {
      resolveEl.onclick = async (e) => {
        e.stopPropagation();
        const newVal = ann.resolved ? 0 : 1;
        try {
          await api(`/api/annotations/${ann.id}`, { method: "PUT", body: JSON.stringify({ resolved: newVal }) });
          ann.resolved = newVal;
          renderAnnotations();
          renderMarkers();
          refreshQuestionsIfOwner();
        } catch (err) {
          Shared.showToast(`Failed to update: ${formatApiError(err)}`, { type: "error" });
        }
      };
    }
    wrap.appendChild(el);
  });
  if (!wrap.childElementCount) {
    const empty = document.createElement("div");
    empty.className = "ann-empty-state";
    empty.innerHTML = `
      <div class="ann-empty-title">No annotations yet</div>
      <div class="ann-empty-body">Click on the image to add a note.</div>
    `;
    wrap.appendChild(empty);
  }
}

function scheduleAnnotationUpdate(annId, patch) {
  clearTimeout(state.noteTimers[`ann_${annId}`]);
  state.noteTimers[`ann_${annId}`] = setTimeout(() => { void persistAnnotationNow(annId, patch); }, 600);
}

function focusActiveAnnotationEditor() {
  const annId = state.activeAnnotationId;
  if (!annId) return;
  const ann = state.annotations.find((a) => a.id === annId);
  if (!ann || !canManageAnnotation(ann)) return;
  requestAnimationFrame(() => {
    const floatingNote = $("#floatingNote");
    const ft = $("#floatingText");
    if (floatingNote && ft && !floatingNote.classList.contains("hidden")) {
      ft.focus({ preventScroll: true });
      const end = (ft.value || "").length;
      ft.setSelectionRange(end, end);
      return;
    }
    const listTa = document.querySelector(`textarea[data-ann="${annId}"]`);
    if (listTa && !listTa.readOnly) {
      listTa.focus({ preventScroll: true });
      const end = (listTa.value || "").length;
      listTa.setSelectionRange(end, end);
    }
  });
}

function setActiveAnnotation(annId, options = {}) {
  const focusEditor = !!options.focusEditor;
  state.activeAnnotationId = annId;
  renderAnnotations();
  renderMarkers();
  renderFloatingNote();
  if (focusEditor) focusActiveAnnotationEditor();
}

function clearActiveAnnotationSelection() {
  if (!state.activeAnnotationId) {
    renderFloatingNote();
    return;
  }
  state.activeAnnotationId = null;
  renderAnnotations();
  renderMarkers();
  renderFloatingNote();
}

function syncFloatingText(annId, value) {
  if (state.activeAnnotationId !== annId) return;
  const ft = $("#floatingText");
  if (ft && ft.value !== value) ft.value = value;
}

function _handleAnnotationEditorKeydown(event, annId) {
  if (event.key !== "Enter" || event.shiftKey) return;
  event.preventDefault();
  const target = event.target;
  if (!(target instanceof HTMLTextAreaElement)) return;
  void persistAnnotationNow(annId, { text: target.value });
  target.blur();
  if (state.activeAnnotationId === annId) clearActiveAnnotationSelection();
}

function renderFloatingNote() {
  const note = $("#floatingNote");
  const ft = $("#floatingText");
  if (!note || !ft) return;
  const ann = state.annotations.find((a) => a.id === state.activeAnnotationId);
  if (!ann) { note.classList.add("hidden"); return; }
  const pt = normalizedToStagePoint(ann.x, ann.y);
  note.style.left = `${pt.left + 16}px`;
  note.style.top = `${pt.top}px`;
  note.classList.remove("hidden");
  ft.value = ann.text || "";
}

async function persistAnnotationNow(annId, patch) {
  clearTimeout(state.noteTimers[`ann_${annId}`]);
  delete state.noteTimers[`ann_${annId}`];
  try {
    await api(`/api/annotations/${annId}`, { method: "PUT", body: JSON.stringify(patch) });
  } catch (e) {
    console.error("Annotation save failed:", e);
    Shared.showToast("Annotation save failed — will retry on next edit", { type: "error" });
  }
}

const floatingTextEl = $("#floatingText");
if (floatingTextEl) {
  floatingTextEl.addEventListener("input", () => {
    const annId = state.activeAnnotationId;
    if (!annId) return;
    const ann = state.annotations.find((a) => a.id === annId);
    if (!ann || !canManageAnnotation(ann)) return;
    ann.text = floatingTextEl.value;
    const listTextarea = document.querySelector(`textarea[data-ann="${annId}"]`);
    if (listTextarea && listTextarea.value !== floatingTextEl.value) {
      listTextarea.value = floatingTextEl.value;
    }
    scheduleAnnotationUpdate(annId, { text: floatingTextEl.value });
  });
  floatingTextEl.addEventListener("blur", () => {
    const annId = state.activeAnnotationId;
    if (!annId) return;
    void persistAnnotationNow(annId, { text: floatingTextEl.value });
  });
  floatingTextEl.addEventListener("keydown", (event) => {
    const annId = state.activeAnnotationId;
    if (!annId) return;
    _handleAnnotationEditorKeydown(event, annId);
  });
}

async function deleteAnnotationWithUndo(ann) {
  const { id, x, y, text } = ann;
  const assetId = state.modalAsset?.id;
  await api(`/api/annotations/${id}`, { method: "DELETE" });
  state.annotations = state.annotations.filter((a) => a.id !== id);
  if (state.activeAnnotationId === id) state.activeAnnotationId = null;
  renderAnnotations(); renderMarkers(); renderFloatingNote();
  Shared.showToast("Annotation deleted", {
    type: "info", actionLabel: "Undo",
    onAction: async () => {
      if (!assetId) return;
      const res = await api("/api/annotations", { method: "POST", body: JSON.stringify({ asset_id: assetId, x, y, text: text || "" }) });
      state.annotations.push(res.annotation);
      renderAnnotations(); renderMarkers(); renderFloatingNote();
    },
  });
}

function modalImageGeometry() {
  const stage = $("#imageStage");
  const img = $("#modalImage");
  const stageRect = stage.getBoundingClientRect();
  const { width: sw, height: sh } = stageRect;
  if (!img || img.style.display === "none" || !img.naturalWidth || !img.naturalHeight || sw <= 0 || sh <= 0) {
    return { stageRect, left: 0, top: 0, width: sw, height: sh };
  }
  const scale = Math.min(sw / img.naturalWidth, sh / img.naturalHeight);
  const width = img.naturalWidth * scale;
  const height = img.naturalHeight * scale;
  return { stageRect, left: (sw - width) / 2, top: (sh - height) / 2, width, height };
}

function stagePointToNormalized(clientX, clientY, clamp = false) {
  const geo = modalImageGeometry();
  if (geo.width <= 0 || geo.height <= 0) return null;
  let x = (clientX - geo.stageRect.left - geo.left) / geo.width;
  let y = (clientY - geo.stageRect.top - geo.top) / geo.height;
  if (clamp) { x = Math.max(0, Math.min(1, x)); y = Math.max(0, Math.min(1, y)); return { x, y, geo }; }
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return { x, y, geo };
}

function normalizedToStagePoint(x, y) {
  const geo = modalImageGeometry();
  return { left: geo.left + x * geo.width, top: geo.top + y * geo.height, geo };
}

const _markerColors = ["#6F5AA8","#c4787a","#7a9b8a","#b8860b","#5a8fc4"];
function markerColor(idx) { return _markerColors[idx % _markerColors.length]; }

function renderMarkers() {
  $$(".marker").forEach((m) => m.remove());
  const stage = $("#imageStage");
  if (!stage) return;
  let annotationNumber = 0;
  state.annotations.forEach((ann, idx) => {
    const isQuestion = false;
    const isResolved = false;
    const canManage = canManageAnnotation(ann);
    const displayNumber = ++annotationNumber;
    const m = document.createElement("div");
    m.className = `marker${isQuestion ? " marker-question" : ""}${isResolved ? " marker-resolved" : ""}`;
    const pt = normalizedToStagePoint(ann.x, ann.y);
    m.style.left = `${pt.left}px`;
    m.style.top = `${pt.top}px`;
    m.dataset.id = ann.id;
    m.style.background = markerColor(idx);
    const markerLabel = `${displayNumber}`;
    const markerActions = canManage
      ? `
      <div class="badgeIcons">
        <button class="ok" data-ok="${ann.id}" aria-label="Done" type="button">
          <svg viewBox="0 0 16 16" width="12" height="12"><path d="M3.2 8.4l2.3 2.3L12.8 3.6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <button class="del" data-del="${ann.id}" aria-label="Delete" type="button">
          <svg viewBox="0 0 16 16" width="12" height="12"><path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        </button>
      </div>
      `
      : "";
    m.innerHTML = `
      <span style="color:#F2F2F6">${markerLabel}</span>
      ${markerActions}
    `;
    if (canManage) {
      m.onpointerdown = (e) => {
        if (e.target.closest(".badgeIcons")) return;
        e.stopPropagation();
        m.setPointerCapture(e.pointerId);
        state.dragging = { id: ann.id, pointerId: e.pointerId, moved: false };
      };
    }
    m.onclick = (e) => { e.stopPropagation(); setActiveAnnotation(ann.id); };
    if (state.activeAnnotationId === ann.id) m.classList.add("active");
    const okBtn = m.querySelector("[data-ok]");
    if (okBtn) {
      okBtn.onclick = (e) => { e.stopPropagation(); state.activeAnnotationId = null; renderAnnotations(); renderMarkers(); renderFloatingNote(); };
    }
    const delBtn = m.querySelector("[data-del]");
    if (delBtn) {
      delBtn.onclick = async (e) => { e.stopPropagation(); await deleteAnnotationWithUndo(ann); };
    }
    stage.appendChild(m);
  });
}

// Image stage event listeners for annotation creation/drag
const imageStageEl = document.getElementById("imageStage");
if (imageStageEl) {
  imageStageEl.addEventListener("click", async (e) => {
    if (!state.modalAsset) return;
    if (!state.actor) {
      Shared.showToast("Sign in to add annotations.", { type: "warning", duration: 2200 });
      return;
    }
    const modalImage = $("#modalImage");
    // Only create annotations from direct clicks on the rendered image.
    // This avoids accidental note creation from unrelated modal controls.
    if (!modalImage || modalImage.style.display === "none" || e.target !== modalImage) return;
    if (e.target.closest(".marker") || e.target.closest(".floatingNote")) return;
    const point = stagePointToNormalized(e.clientX, e.clientY);
    if (!point) return;
    const res = await api("/api/annotations", {
      method: "POST",
      body: JSON.stringify({ asset_id: state.modalAsset.id, x: point.x, y: point.y, text: "", annotation_type: "note" }),
    });
    state.annotations.push(res.annotation);
    setActiveAnnotation(res.annotation.id, { focusEditor: true });
  });

  imageStageEl.addEventListener("pointermove", async (e) => {
    if (!state.dragging) return;
    const point = stagePointToNormalized(e.clientX, e.clientY, true);
    if (!point) return;
    const ann = state.annotations.find((a) => a.id === state.dragging.id);
    if (!ann) return;
    ann.x = point.x; ann.y = point.y;
    state.dragging.moved = true;
    renderMarkers(); renderFloatingNote();
  });

  imageStageEl.addEventListener("pointerup", async () => {
    if (!state.dragging) return;
    const ann = state.annotations.find((a) => a.id === state.dragging.id);
    if (ann) {
      await api(`/api/annotations/${ann.id}`, { method: "PUT", body: JSON.stringify({ x: ann.x, y: ann.y }) });
    }
    state.dragging = null;
  });
}

// Modal close wiring
const closeModalBtn = $("#closeModal");
if (closeModalBtn) closeModalBtn.onclick = closeModal;
const modalEl = $("#modal");
if (modalEl) modalEl.onclick = (e) => { if (e.target.id === "modal") closeModal(); };

// ─── Print ──────────────────────────────────────────────────────────────────────

function printModalAsset(asset) {
  const modalImage = $("#modalImage");
  const modalVideo = $("#modalVideo");
  const modalImageUrl = modalImage && modalImage.style.display !== "none"
    ? String(modalImage.currentSrc || modalImage.src || "").trim()
    : "";
  const modalPosterUrl = modalVideo && !modalVideo.hidden
    ? String(modalVideo.poster || "").trim()
    : "";
  const fallbackUrl = asset?.thumb_path
    ? `${_B}/media/${asset.id}?kind=thumb`
    : (asset?.id ? `${_B}/media/${asset.id}?kind=original` : (asset?.image_url || ""));
  const url = modalImageUrl || modalPosterUrl || fallbackUrl;
  if (!url) {
    Shared.showToast("Nothing to print for this item.", { type: "info" });
    return;
  }
  const win = window.open("", "_blank");
  if (!win) {
    Shared.showToast("Pop-up blocked. Allow pop-ups to print.", { type: "error" });
    return;
  }

  const safeUrl = escapeHtml(url);
  const safeTitle = escapeHtml(displayTitle(asset));
  const metaParts = [];
  if (asset?.board) metaParts.push(String(asset.board));
  if (asset?.source) metaParts.push(String(asset.source));
  if (asset?.creator_name) metaParts.push(`by ${String(asset.creator_name)}`);
  const contextParts = [];
  if (state.currentCollectionLabel) contextParts.push(`Collection: ${state.currentCollectionLabel}`);
  else if (hasClassificationFilter()) {
    const facetLabel = getClassificationFacetEntries()
      .map((entry) => classificationFacetLabel(entry.axis, entry.value))
      .filter(Boolean)
      .join(", ") || state.currentClassificationLabel;
    contextParts.push(`Refine: ${facetLabel}`);
  }
  else if (state.currentSource) contextParts.push(`Source: ${sourceDisplayName(state.currentSource)}`);
  const notesText = String(asset?.notes || "").trim();
  const sourceRef = String(asset?.source_ref || "").trim();
  const labelTexts = Array.from(document.querySelectorAll("#modalLabels .label-chip"))
    .map((el) => String(el.textContent || "").trim())
    .filter(Boolean);
  const visibleLabels = labelTexts.slice(0, 12);
  const extraLabelCount = Math.max(0, labelTexts.length - visibleLabels.length);
  const annotationItems = [];
  let annotationNumber = 0;
  const clampPrintPoint = (value) => {
    const num = Number(value);
    return Number.isFinite(num) ? Math.max(0, Math.min(1, num)) : 0;
  };
  for (const ann of (Array.isArray(state.annotations) ? state.annotations : [])) {
    annotationNumber += 1;
    const text = String(ann?.text || "").trim() || "No annotation text.";
    annotationItems.push({
      label: `#${annotationNumber}`,
      marker: String(annotationNumber),
      text,
      x: clampPrintPoint(ann?.x),
      y: clampPrintPoint(ann?.y),
      color: markerColor(annotationNumber - 1),
    });
  }
  const safeMeta = escapeHtml(metaParts.join(" · "));
  const safeContext = escapeHtml(contextParts.join(" · "));
  const safeId = escapeHtml(String(asset?.id || "").trim());
  const safeNotes = escapeHtml(notesText);
  const safeSourceRef = escapeHtml(sourceRef);
  const labelsMarkup = visibleLabels.length
    ? visibleLabels.map((label) => `<span class="label-chip">${escapeHtml(label)}</span>`).join("")
      + (extraLabelCount ? `<span class="label-chip label-chip-more">+${extraLabelCount} more</span>` : "")
    : "";
  const annotationMarkup = annotationItems.length
    ? annotationItems.map((item) => `<li><span class="ann-num">${escapeHtml(item.label)}</span><span>${escapeHtml(item.text)}</span></li>`).join("")
    : "";
  const markerMarkup = annotationItems.length
    ? annotationItems.map((item) => {
      const left = (item.x * 100).toFixed(3);
      const top = (item.y * 100).toFixed(3);
      const color = escapeHtml(item.color);
      return `<span class="print-marker" style="left:${left}%;top:${top}%;background:${color};">${escapeHtml(item.marker)}</span>`;
    }).join("")
    : "";
  const hasSupplementary = !!(safeNotes || labelsMarkup || annotationMarkup);
  const mediaMaxHeight = hasSupplementary ? "6.4in" : "7.25in";
  win.document.open();
  win.document.write(`<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>${safeTitle || "Print"}</title>
    <style>
      @page {
        size: letter portrait;
        margin: 0.35in;
      }
      html, body { margin: 0; padding: 0; background: #fff; }
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: #2c2825;
      }
      .toolbar { position: fixed; top: 8px; right: 8px; z-index: 2; }
      .toolbar button {
        border: 1px solid #bbb; background: #fff; color: #333;
        border-radius: 8px; padding: 6px 10px; cursor: pointer;
      }
      .sheet {
        display: grid;
        grid-template-rows: auto auto auto;
        gap: 0.12in;
        min-height: calc(100vh - 0.7in);
      }
      .header {
        display: grid;
        gap: 0.04in;
      }
      .title {
        font-size: 16px;
        line-height: 1.2;
        font-weight: 650;
      }
      .meta, .context, .asset-id, .source-ref {
        font-size: 10px;
        line-height: 1.3;
        color: #5f5852;
      }
      .asset-id {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      }
      .frame {
        border: 1px solid rgba(44, 40, 37, 0.16);
        border-radius: 12px;
        padding: 0.1in;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        min-height: 0;
      }
      .image-wrap {
        position: relative;
        display: inline-block;
        max-width: 100%;
        line-height: 0;
      }
      .frame img {
        display: block;
        max-width: 100%;
        max-height: ${mediaMaxHeight};
        object-fit: contain;
      }
      .print-marker {
        position: absolute;
        transform: translate(-50%, -50%);
        width: 22px;
        height: 22px;
        border-radius: 50%;
        border: 2px solid #fff;
        box-shadow: 0 1px 5px rgba(44, 40, 37, 0.36);
        color: #fff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        font-weight: 800;
        line-height: 1;
      }
      .detail-stack {
        display: grid;
        gap: 0.1in;
      }
      .notes,
      .labels,
      .annotations {
        border-top: 1px solid rgba(44, 40, 37, 0.12);
        padding-top: 0.08in;
        display: grid;
        gap: 0.05in;
      }
      .notes-label,
      .section-label {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #6b6158;
      }
      .notes-text {
        font-size: 11px;
        line-height: 1.35;
        color: #2c2825;
      }
      .labels-row {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .label-chip {
        display: inline-flex;
        align-items: center;
        padding: 3px 8px;
        border-radius: 999px;
        border: 1px solid rgba(44, 40, 37, 0.12);
        background: #f7f4ef;
        font-size: 10px;
        line-height: 1.2;
        color: #5f5852;
      }
      .label-chip-more {
        background: rgba(184, 134, 11, 0.08);
        border-color: rgba(184, 134, 11, 0.2);
        color: #8a6510;
      }
      .ann-list {
        margin: 0;
        padding: 0;
        list-style: none;
        display: grid;
        gap: 5px;
      }
      .ann-list li {
        display: grid;
        grid-template-columns: auto 1fr;
        gap: 8px;
        font-size: 11px;
        line-height: 1.35;
      }
      .ann-num {
        font-weight: 700;
        color: #6b6158;
        white-space: nowrap;
      }
      @media print {
        .toolbar { display: none; }
        html, body { width: auto; height: auto; }
        .sheet { min-height: auto; }
      }
    </style>
  </head>
  <body>
    <div class="toolbar"><button type="button" onclick="window.print()">Print</button></div>
    <div class="sheet">
      <div class="header">
        <div class="title">${safeTitle || "Untitled item"}</div>
        ${safeMeta ? `<div class="meta">${safeMeta}</div>` : ""}
        ${safeContext ? `<div class="context">${safeContext}</div>` : ""}
        ${safeId ? `<div class="asset-id">Item ID ${safeId}</div>` : ""}
        ${safeSourceRef ? `<div class="source-ref">${safeSourceRef}</div>` : ""}
      </div>
      <div class="frame">
        <div class="image-wrap">
          <img id="printImage" src="${safeUrl}" alt="Print item" />
          ${markerMarkup}
        </div>
      </div>
      ${(safeNotes || labelsMarkup || annotationMarkup) ? `<div class="detail-stack">
        ${safeNotes ? `<div class="notes"><div class="notes-label">Notes</div><div class="notes-text">${safeNotes}</div></div>` : ""}
        ${labelsMarkup ? `<div class="labels"><div class="section-label">Labels</div><div class="labels-row">${labelsMarkup}</div></div>` : ""}
        ${annotationMarkup ? `<div class="annotations"><div class="section-label">Annotations</div><ul class="ann-list">${annotationMarkup}</ul></div>` : ""}
      </div>` : ""}
    </div>
    <script>
      (function () {
        let printed = false;
        function tryPrint() {
          if (printed) return;
          printed = true;
          try {
            window.focus();
            window.print();
          } catch (_) {}
        }
        window.addEventListener("load", function () { setTimeout(tryPrint, 60); });
        const img = document.getElementById("printImage");
        if (img) img.addEventListener("load", function () { setTimeout(tryPrint, 30); });
        setTimeout(tryPrint, 500);
      })();
    </script>
  </body>
</html>`);
  win.document.close();
}

// ─── Review mode ────────────────────────────────────────────────────────────────

async function enterReview(options = {}) {
  const startAssetId = String(options.startAssetId || "").trim();
  const seedIds = Array.isArray(state.reviewSeedIds) ? _uniqNonEmpty(state.reviewSeedIds) : [];
  if (!state.assets.length && !seedIds.length) {
    Shared.showToast("No items to review.", { type: "info" });
    return;
  }
  let reviewData;
  try {
    reviewData = await _fetchAllAssetsForCurrentScope();
  } catch (e) {
    Shared.showToast(`Unable to load review scope: ${formatApiError(e)}`, { type: "error" });
    return;
  }
  const reviewItems = Array.isArray(reviewData?.items) ? reviewData.items : [];
  if (!reviewItems.length) {
    Shared.showToast("No items to review.", { type: "info" });
    return;
  }
  if (isExplorerViewActive()) {
    setViewMode("grid", { persist: false });
  }
  state.view = "review";
  state.reviewItems = reviewItems;
  const startIndex = startAssetId
    ? reviewItems.findIndex((item) => String(item?.id || "") === startAssetId)
    : -1;
  state.reviewIndex = startIndex >= 0 ? startIndex : 0;
  state.reviewHistory = [];
  state.reviewDrafts = {};
  state.reviewSkipped = 0;
  state.reviewKept = 0;
  state.reviewMoved = 0;
  state.reviewHidden = 0;
  state.reviewSnapshotTotal = reviewItems.length;
  state.reviewScopeTotal = Number(reviewData?.scopeTotal || reviewItems.length);

  const browseView = $("#browseView");
  const reviewView = $("#reviewView");
  const reviewComplete = $("#reviewComplete");
  const reviewCard = $("#reviewCard");
  const reviewActions = document.querySelector(".review-actions");
  if (browseView) browseView.hidden = true;
  if (reviewView) reviewView.hidden = false;
  if (reviewComplete) reviewComplete.hidden = true;
  if (reviewCard) reviewCard.hidden = false;
  if (reviewActions) reviewActions.style.display = "";

  // Update back button label based on whether we came from canvas review
  const backBtn = $("#reviewBack");
  if (backBtn) backBtn.textContent = state.canvasReview ? "← Back to grid" : "← Back to browsing";

  // Hide canvas action bar while in one-by-one (it'll come back when we return to grid)
  const actionBar = $("#canvasActionBar");
  if (actionBar) actionBar.hidden = true;

  updateSidebarModeVisibility();
  await renderReviewCard();
}

function exitReview() {
  state.view = "browse";
  const browseView = $("#browseView");
  const reviewView = $("#reviewView");
  if (browseView) browseView.hidden = false;
  if (reviewView) reviewView.hidden = true;

  if (state.canvasReview) {
    // Return to canvas review grid — re-show action bar, keep review state
    const actionBar = $("#canvasActionBar");
    if (actionBar) actionBar.hidden = false;
    loadAssets();
  } else {
    loadAssets();
  }
  updateSidebarModeVisibility();
}

async function hydrateReviewItem(index = state.reviewIndex) {
  const item = state.reviewItems[index];
  if (!item || !isOwner()) return item;
  if (item.classification_review) return item;
  const hydrated = await hydrateModalAsset(item);
  if (hydrated && hydrated.id === item.id) {
    state.reviewItems[index] = hydrated;
    replaceAssetInState(hydrated);
    return hydrated;
  }
  return item;
}

function renderReviewClassificationPanel(item) {
  const panel = $("#reviewClassificationPanel");
  if (!panel) return;
  if (!isOwner()) {
    panel.hidden = true;
    return;
  }
  const review = item?.classification_review || {};
  const currentTrack = String(review.current_track || "").trim();
  const currentConfidence = Number(review.current_confidence || 0);
  const currentReason = String(review.current_reason || "").trim();
  const sourceVerdict = String(review.source_qc_verdict || "").trim();
  const sourceTrack = String(review.source_qc_inferred_track || "").trim();
  const sourceConfidence = Number(review.source_qc_confidence || 0);
  const sourceReason = String(review.source_qc_reason || "").trim();
  const overrideTrack = String(review.active_override_track || "").trim();
  const overrideActor = String(review.active_override_actor || "").trim();
  const overrideNote = String(review.active_override_note || "").trim();
  const overrideCreatedAt = String(review.active_override_created_at || "").trim();
  const overrideFocus = String(review.active_review_focus || "").trim();
  const overrideMedia = String(review.active_media_reliability || "").trim();
  const effectiveTrack = _effectiveClassificationTrack(review);
  const statusText = _modalClassificationStatusText(review);
  const cleanedOverrideNote = _isBoilerplateClassificationReviewNote(overrideNote) ? "" : overrideNote;
  const draft = state.reviewDrafts && item?.id ? state.reviewDrafts[item.id] || null : null;

  panel.hidden = false;

  const statusEl = $("#reviewClassificationStatus");
  if (statusEl) {
    statusEl.textContent = statusText;
    statusEl.hidden = !statusText;
  }

  const currentEl = $("#reviewClassificationCurrent");
  if (currentEl) {
    const parts = [];
    if (currentTrack) parts.push(classificationTrackLabel(currentTrack));
    if (currentConfidence) parts.push(`${Math.round(currentConfidence * 100)}%`);
    currentEl.textContent = parts.join(" · ") || "No current track";
    currentEl.title = currentReason || "";
  }

  const hasSourceConflict = sourceVerdict === "conflicting" && !!sourceTrack;
  const sourceRow = $("#reviewClassificationSourceRow");
  const sourceEl = $("#reviewClassificationSource");
  const sourceReasonEl = $("#reviewClassificationSourceReason");
  if (sourceRow) sourceRow.hidden = !hasSourceConflict;
  if (sourceEl) {
    const parts = [];
    if (sourceTrack) parts.push(classificationTrackLabel(sourceTrack));
    if (sourceConfidence) parts.push(`${Math.round(sourceConfidence * 100)}%`);
    sourceEl.textContent = hasSourceConflict ? parts.join(" · ") : "";
  }
  if (sourceReasonEl) {
    sourceReasonEl.textContent = sourceReason;
    sourceReasonEl.hidden = !(hasSourceConflict && sourceReason);
  }

  const overrideRow = $("#reviewClassificationOverrideRow");
  const overrideEl = $("#reviewClassificationOverride");
  const overrideMetaEl = $("#reviewClassificationOverrideMeta");
  if (overrideRow) overrideRow.hidden = !overrideTrack;
  if (overrideEl) overrideEl.textContent = overrideTrack ? classificationTrackLabel(overrideTrack) : "";
  if (overrideMetaEl) {
    const parts = [];
    if (overrideActor) parts.push(`by ${overrideActor}`);
    if (overrideCreatedAt) parts.push(overrideCreatedAt.slice(0, 10));
    if (cleanedOverrideNote) parts.push(cleanedOverrideNote);
    overrideMetaEl.textContent = parts.join(" · ");
    overrideMetaEl.hidden = !parts.length;
  }

  const focusRow = $("#reviewClassificationFocusRow");
  const focusEl = $("#reviewClassificationFocus");
  if (focusRow) focusRow.hidden = !overrideFocus;
  if (focusEl) focusEl.textContent = overrideFocus ? _reviewFocusLabel(overrideFocus) : "";
  const mediaRow = $("#reviewClassificationMediaRow");
  const mediaEl = $("#reviewClassificationMedia");
  if (mediaRow) mediaRow.hidden = !overrideMedia;
  if (mediaEl) mediaEl.textContent = overrideMedia ? _mediaReliabilityLabel(overrideMedia) : "";

  const editor = $("#reviewClassificationEditor");
  const moveTo = $("#reviewClassificationMoveTo");
  const focusSelect = $("#reviewClassificationFocusSelect");
  const mediaSelect = $("#reviewClassificationMediaSelect");
  const comment = $("#reviewClassificationComment");
  const keepBtn = $("#reviewClassificationKeepBtn");
  const saveBtn = $("#reviewClassificationSaveBtn");
  const irrelevantBtn = $("#reviewClassificationIrrelevantBtn");
  if (editor) editor.hidden = false;
  const defaultTrack = (draft && draft.track) || overrideTrack || (hasSourceConflict ? sourceTrack : currentTrack);
  if (moveTo) moveTo.value = _preferredMoveTrack(defaultTrack);
  const defaultFocus = (draft && draft.focus) || overrideFocus;
  if (focusSelect) focusSelect.value = defaultFocus && REVIEW_FOCUS_LABELS[defaultFocus] ? defaultFocus : "";
  const defaultMedia = (draft && draft.mediaReliability) || overrideMedia;
  if (mediaSelect) mediaSelect.value = defaultMedia && MEDIA_RELIABILITY_LABELS[defaultMedia] ? defaultMedia : "";
  if (comment) comment.value = draft && Object.prototype.hasOwnProperty.call(draft, "note") ? draft.note : (cleanedOverrideNote || "");
  if (keepBtn) keepBtn.disabled = !effectiveTrack;
  if (saveBtn) saveBtn.disabled = false;
  if (irrelevantBtn) {
    const savedIrrelevant = effectiveTrack === "irrelevant";
    irrelevantBtn.classList.toggle("is-saved-state", savedIrrelevant);
    irrelevantBtn.textContent = savedIrrelevant ? "Saved as irrelevant" : "Mark irrelevant";
    irrelevantBtn.disabled = savedIrrelevant;
  }
}

function _persistCurrentReviewDraft() {
  if (!state.reviewDrafts || state.view !== "review") return;
  const item = state.reviewItems[state.reviewIndex];
  if (!item || !item.id) return;
  const moveTo = $("#reviewClassificationMoveTo");
  const focusSelect = $("#reviewClassificationFocusSelect");
  const mediaSelect = $("#reviewClassificationMediaSelect");
  const comment = $("#reviewClassificationComment");
  if (!moveTo && !focusSelect && !comment) return;
  state.reviewDrafts[item.id] = {
    track: _preferredMoveTrack(moveTo?.value || ""),
    focus: String(focusSelect?.value || "").trim(),
    mediaReliability: String(mediaSelect?.value || "").trim(),
    note: String(comment?.value || ""),
  };
}

async function renderReviewCard() {
  let item = await hydrateReviewItem(state.reviewIndex);
  while (item && !_reviewItemMatchesCurrentScope(item)) {
    state.reviewItems.splice(state.reviewIndex, 1);
    state.reviewSnapshotTotal = state.reviewItems.length;
    state.reviewScopeTotal = Math.min(
      Math.max(0, Number(state.reviewScopeTotal || 0)),
      state.reviewItems.length,
    );
    if (!state.reviewItems.length || state.reviewIndex >= state.reviewItems.length) {
      showReviewComplete();
      return;
    }
    item = await hydrateReviewItem(state.reviewIndex);
  }
  if (!item) return;

  const total = state.reviewSnapshotTotal || state.reviewItems.length;
  const scopeTotal = Number.isFinite(Number(state.reviewScopeTotal))
    ? Math.max(0, Number(state.reviewScopeTotal))
    : total;
  const counter = $("#reviewCounter");
  const progressBar = $("#reviewProgressBar");
  if (counter) {
    if (scopeTotal !== total) {
      counter.textContent = `${state.reviewIndex + 1} of ${total} snapshot · ${scopeTotal} in scope`;
    } else {
      counter.textContent = `${state.reviewIndex + 1} of ${total}`;
    }
  }
  if (progressBar) progressBar.style.width = `${((state.reviewIndex) / total) * 100}%`;

  const img = $("#reviewImg");
  if (img) {
    const url = item.thumb_path ? `${_B}/media/${item.id}?kind=original`
                : item.stored_path ? `${_B}/media/${item.id}?kind=original`
                : item.image_url || "";
    img.src = url;
    img.alt = displayTitle(item);
  }

  const titleEl = $("#reviewTitle");
  if (titleEl) {
    titleEl.textContent = displayTitle(item);
    titleEl.style.color = "";
  }

  const metaEl = $("#reviewMeta");
  if (metaEl) {
    const parts = [];
    if (item.board) parts.push(item.board);
    parts.push(item.source || "");
    metaEl.textContent = parts.filter(Boolean).join(" · ");
  }
  const assetIdEl = $("#reviewAssetId");
  if (assetIdEl) assetIdEl.textContent = item.id ? `ID ${item.id}` : "";

  const descEl = $("#reviewDesc");
  if (descEl) descEl.textContent = item.seo_alt_text || item.ai_summary || item.description || "";
  _renderMediaReliabilityOverlay("#reviewMediaOverlay", item?.classification_review?.active_media_reliability || "");

  const link = $("#reviewSourceLink");
  if (link) {
    const ref = item.source_ref || "";
    link.href = ref || "#";
    link.hidden = !ref;
    link.textContent = ref ? `View on ${item.source || "source"} ↗` : "";
  }
  const editDetailsBtn = $("#reviewEditDetailsBtn");
  if (editDetailsBtn) {
    editDetailsBtn.disabled = !isOwner();
    editDetailsBtn.onclick = () => openModal(item);
  }
  renderReviewClassificationPanel(item);

  // Update undo button
  const prevBtn = $("#reviewPrevBtn");
  if (prevBtn) prevBtn.disabled = state.reviewHistory.length === 0;
  const undoBtn = $("#reviewUndo");
  if (undoBtn) undoBtn.disabled = state.reviewHistory.length === 0;
  const scope = getReviewScopeInfo();
  const keepBtn = $("#reviewKeepBtn");
  if (keepBtn) keepBtn.disabled = !isOwner();
  const hideLocalBtn = $("#reviewHideLocalBtn");
  if (hideLocalBtn) hideLocalBtn.disabled = !(isOwner() && scope.hasCollectionScope);
  const hideGlobalBtn = $("#reviewHideGlobalBtn");
  if (hideGlobalBtn) {
    const restore = item.triage_status === "hidden";
    hideGlobalBtn.disabled = !isOwner();
    hideGlobalBtn.title = restore ? "Restore to ordinary browsing" : "Discard from the library";
    hideGlobalBtn.querySelector(".review-btn-icon").textContent = restore ? "↟" : "✗";
    hideGlobalBtn.querySelector(".review-btn-label").textContent = restore ? "Restore" : "Discard";
  }
  const flagBtn = $("#reviewFlagBtn");
  if (flagBtn) flagBtn.disabled = !canUseFlag();
  const clearBtn = $("#reviewClearBtn");
  if (clearBtn) clearBtn.disabled = !isOwner();
}

function _incrementReviewDecisionCounter(kind) {
  if (kind === "keep_current" || kind === "keep") state.reviewKept += 1;
  else if (kind === "move" || kind === "flag" || kind === "clear") state.reviewMoved += 1;
  else if (kind === "irrelevant" || kind === "hide_global" || kind === "hide_local") state.reviewHidden += 1;
  else if (kind === "skip") state.reviewSkipped += 1;
}

function _decrementReviewDecisionCounter(kind) {
  if (kind === "keep_current" || kind === "keep") state.reviewKept = Math.max(0, state.reviewKept - 1);
  else if (kind === "move" || kind === "flag" || kind === "clear") state.reviewMoved = Math.max(0, state.reviewMoved - 1);
  else if (kind === "irrelevant" || kind === "hide_global" || kind === "hide_local") state.reviewHidden = Math.max(0, state.reviewHidden - 1);
  else if (kind === "skip") state.reviewSkipped = Math.max(0, state.reviewSkipped - 1);
}

async function _advanceReviewAfterDecision() {
  const snapshotTotal = state.reviewSnapshotTotal || state.reviewItems.length;
  state.reviewIndex += 1;
  if (state.reviewIndex >= snapshotTotal) {
    showReviewComplete();
    return;
  }
  await renderReviewCard();
}

async function saveReviewClassificationReview(opts = {}) {
  const item = await hydrateReviewItem(state.reviewIndex);
  if (!item || !item.id) return;
  if (!isOwner()) {
    Shared.showToast("Track review is owner-only.", { type: "info" });
    return;
  }

  const review = item.classification_review || {};
  const currentTrack = _effectiveClassificationTrack(review);
  const previousOverrideTrack = String(review.active_override_track || "").trim();
  const previousOverrideNote = String(review.active_override_note || "").trim();
  const previousOverrideFocus = String(review.active_review_focus || "").trim();
  const previousOverrideMediaReliability = String(review.active_media_reliability || "").trim();
  const moveTo = $("#reviewClassificationMoveTo");
  const focusSelect = $("#reviewClassificationFocusSelect");
  const mediaSelect = $("#reviewClassificationMediaSelect");
  const comment = $("#reviewClassificationComment");
  const keepBtn = $("#reviewClassificationKeepBtn");
  const saveBtn = $("#reviewClassificationSaveBtn");
  const irrelevantBtn = $("#reviewClassificationIrrelevantBtn");
  const track = String(opts.track || moveTo?.value || "").trim();
  const reviewFocus = String(opts.reviewFocus ?? focusSelect?.value ?? "").trim();
  const mediaReliability = String(opts.mediaReliability ?? mediaSelect?.value ?? "").trim();
  const note = String(comment?.value || "").trim();
  if (!track) {
    Shared.showToast("Choose a track first.", { type: "info" });
    return;
  }

  if (keepBtn) keepBtn.disabled = true;
  if (saveBtn) saveBtn.disabled = true;
  if (irrelevantBtn) irrelevantBtn.disabled = true;
  if (moveTo) moveTo.disabled = true;
  if (focusSelect) focusSelect.disabled = true;
  if (mediaSelect) mediaSelect.disabled = true;
  if (comment) comment.disabled = true;

  try {
    const data = await api(`/api/assets/${encodeURIComponent(item.id)}/classification-review`, {
      method: "PUT",
      body: JSON.stringify({ track, note, review_focus: reviewFocus, media_reliability: mediaReliability }),
    });
    const updated = data.asset || null;
    if (!updated) throw new Error("Updated asset missing from response");
    replaceAssetInState(updated);
    state.reviewItems[state.reviewIndex] = updated;
    state.modalAsset = state.modalAsset?.id === updated.id ? updated : state.modalAsset;
    if (state.reviewDrafts && updated.id) delete state.reviewDrafts[updated.id];

    const kind = track === currentTrack ? "keep_current" : (track === "irrelevant" ? "irrelevant" : "move");
    state.reviewHistory.push({
      kind: "classification",
      decisionKind: kind,
      id: updated.id,
      index: state.reviewIndex,
      previousOverrideTrack,
      previousOverrideNote,
      previousOverrideFocus,
      previousOverrideMediaReliability,
      appliedTrack: track,
      appliedFocus: reviewFocus,
      appliedMediaReliability: mediaReliability,
      appliedNote: note,
    });
    _incrementReviewDecisionCounter(kind);
    await _advanceReviewAfterDecision();
  } catch (e) {
    Shared.showToast(`Failed to save: ${formatApiError(e)}`, { type: "error" });
  } finally {
    if (keepBtn) keepBtn.disabled = false;
    if (saveBtn) saveBtn.disabled = false;
    if (irrelevantBtn) irrelevantBtn.disabled = false;
    if (moveTo) moveTo.disabled = false;
    if (focusSelect) focusSelect.disabled = false;
    if (mediaSelect) mediaSelect.disabled = false;
    if (comment) comment.disabled = false;
  }
}

async function reviewAction(action) {
  if (action !== "skip") return;
  const item = state.reviewItems[state.reviewIndex];
  if (!item) return;
  state.reviewHistory.push({
    kind: "skip",
    id: item.id,
    index: state.reviewIndex,
    decisionKind: "skip",
  });
  _incrementReviewDecisionCounter("skip");
  await _advanceReviewAfterDecision();
}

function _replaceReviewItem(updated) {
  if (!updated || !updated.id) return;
  const idx = state.reviewItems.findIndex((item) => item && item.id === updated.id);
  if (idx >= 0) state.reviewItems[idx] = updated;
  replaceAssetInState(updated);
  if (state.modalAsset?.id === updated.id) state.modalAsset = updated;
}

async function _reviewSetTriage(item, status, decisionKind, toastText) {
  const previousStatus = Object.prototype.hasOwnProperty.call(item, "triage_status") ? item.triage_status : null;
  const previousNeedsAnnotation = Object.prototype.hasOwnProperty.call(item, "needs_annotation") ? item.needs_annotation : null;
  await api(`/api/assets/${encodeURIComponent(item.id)}/triage`, {
    method: "POST",
    body: JSON.stringify({ status, reason: `review ${decisionKind}` }),
  });
  const updated = { ...item, triage_status: status };
  _replaceReviewItem(updated);
  state.reviewHistory.push({
    kind: "triage",
    decisionKind,
    id: item.id,
    index: state.reviewIndex,
    previousStatus,
    previousNeedsAnnotation,
    appliedStatus: status,
  });
  _incrementReviewDecisionCounter(decisionKind);
  Shared.showToast(toastText, { type: "success", duration: 1800 });
  await _advanceReviewAfterDecision();
}

async function reviewPrimaryAction(action) {
  const item = state.reviewItems[state.reviewIndex];
  if (!item || !item.id) return;
  if (!isOwner()) {
    Shared.showToast("Review actions are owner-only.", { type: "info" });
    return;
  }

  try {
    if (action === "keep") {
      await _reviewSetTriage(item, "keeper", "keep", "Marked as keeper.");
      return;
    }
    if (action === "hide_global") {
      if (item.triage_status === "hidden") {
        await _reviewSetTriage(item, null, "restore", "Restored to ordinary browsing.");
        return;
      }
      if (!confirmGlobalHideBulk(1)) {
        Shared.showToast("Discard canceled.", { type: "info" });
        return;
      }
      await _reviewSetTriage(item, "hidden", "hide_global", "Discarded from ordinary browsing.");
      return;
    }
    if (action === "hide_local") {
      const scope = getReviewScopeInfo();
      if (!scope.hasCollectionScope) {
        Shared.showToast("No active collection scope. Use Discard for library-wide removal.", { type: "info" });
        return;
      }
      const results = await removeAssetsFromCollections([item.id], scope.collectionIds);
      const removed = results.reduce((sum, r) => sum + Number(r.removed || 0), 0);
      if (!removed) {
        Shared.showToast("This item is not in the active collection scope.", { type: "info" });
        return;
      }
      state.reviewHistory.push({
        kind: "collection_remove",
        decisionKind: "hide_local",
        id: item.id,
        index: state.reviewIndex,
        collectionIds: scope.collectionIds,
      });
      _incrementReviewDecisionCounter("hide_local");
      Shared.showToast("Removed from this collection.", { type: "success", duration: 1800 });
      await _advanceReviewAfterDecision();
      return;
    }
    if (action === "flag") {
      if (!canUseFlag()) {
        Shared.showToast("Flagging is owner-only.", { type: "info" });
        return;
      }
      const previousFlagged = item.flagged;
      await api(`/api/assets/${encodeURIComponent(item.id)}/flag`, {
        method: "POST",
        body: JSON.stringify({ flagged: 1 }),
      });
      const updated = { ...item, flagged: 1 };
      _replaceReviewItem(updated);
      state.reviewHistory.push({
        kind: "flag",
        decisionKind: "flag",
        id: item.id,
        index: state.reviewIndex,
        previousFlagged,
      });
      _incrementReviewDecisionCounter("flag");
      Shared.showToast("Flagged for follow-up.", { type: "success", duration: 1800 });
      await _advanceReviewAfterDecision();
      return;
    }
    if (action === "clear") {
      const previousStatus = Object.prototype.hasOwnProperty.call(item, "triage_status") ? item.triage_status : null;
      const previousNeedsAnnotation = Object.prototype.hasOwnProperty.call(item, "needs_annotation") ? item.needs_annotation : null;
      const previousFlagged = item.flagged;
      await api(`/api/assets/${encodeURIComponent(item.id)}/triage`, {
        method: "POST",
        body: JSON.stringify({ status: null, reason: "review clear" }),
      });
      if (previousFlagged) {
        await api(`/api/assets/${encodeURIComponent(item.id)}/flag`, {
          method: "POST",
          body: JSON.stringify({ flagged: 0 }),
        });
      }
      const updated = { ...item, triage_status: null, flagged: 0 };
      _replaceReviewItem(updated);
      state.reviewHistory.push({
        kind: "clear_status",
        decisionKind: "clear",
        id: item.id,
        index: state.reviewIndex,
        previousStatus,
        previousNeedsAnnotation,
        previousFlagged,
      });
      _incrementReviewDecisionCounter("clear");
      Shared.showToast("Status cleared.", { type: "success", duration: 1800 });
      await _advanceReviewAfterDecision();
    }
  } catch (e) {
    Shared.showToast(`Review action failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function undoReview() {
  const last = state.reviewHistory.pop();
  if (!last) return;

  _decrementReviewDecisionCounter(last.decisionKind || "");

  try {
    if (last.kind === "classification") {
      const payload = last.previousOverrideTrack
        ? {
            track: last.previousOverrideTrack,
            note: last.previousOverrideNote,
            review_focus: last.previousOverrideFocus || "",
            media_reliability: last.previousOverrideMediaReliability || "",
          }
        : { clear: true };
      const data = await api(`/api/assets/${encodeURIComponent(last.id)}/classification-review`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      const restored = data.asset || null;
      if (restored) {
        const idx = state.reviewItems.findIndex((item) => item && item.id === last.id);
        if (idx >= 0) state.reviewItems[idx] = restored;
        replaceAssetInState(restored);
        if (state.modalAsset?.id === restored.id) state.modalAsset = restored;
      }
      if (state.reviewDrafts && last.id) {
        state.reviewDrafts[last.id] = {
          track: String(last.appliedTrack || "").trim(),
          focus: String(last.appliedFocus || "").trim(),
          mediaReliability: String(last.appliedMediaReliability || "").trim(),
          note: String(last.appliedNote || ""),
        };
      }
    } else if (last.kind === "triage") {
      await api(`/api/assets/${encodeURIComponent(last.id)}/triage`, {
        method: "POST",
        body: JSON.stringify({
          status: last.previousStatus ?? null,
          needs_annotation: last.previousNeedsAnnotation,
          reason: "review undo",
        }),
      });
      const existing = state.reviewItems.find((item) => item && item.id === last.id) || { id: last.id };
      _replaceReviewItem({ ...existing, triage_status: last.previousStatus ?? null, needs_annotation: last.previousNeedsAnnotation });
    } else if (last.kind === "collection_remove") {
      await addAssetsToCollections([last.id], last.collectionIds || []);
    } else if (last.kind === "flag") {
      await api(`/api/assets/${encodeURIComponent(last.id)}/flag`, {
        method: "POST",
        body: JSON.stringify({ flagged: last.previousFlagged ? 1 : 0 }),
      });
      const existing = state.reviewItems.find((item) => item && item.id === last.id) || { id: last.id };
      _replaceReviewItem({ ...existing, flagged: last.previousFlagged ? 1 : 0 });
    } else if (last.kind === "clear_status") {
      await api(`/api/assets/${encodeURIComponent(last.id)}/triage`, {
        method: "POST",
        body: JSON.stringify({
          status: last.previousStatus ?? null,
          needs_annotation: last.previousNeedsAnnotation,
          reason: "review undo clear",
        }),
      });
      if (last.previousFlagged) {
        await api(`/api/assets/${encodeURIComponent(last.id)}/flag`, {
          method: "POST",
          body: JSON.stringify({ flagged: 1 }),
        });
      }
      const existing = state.reviewItems.find((item) => item && item.id === last.id) || { id: last.id };
      _replaceReviewItem({
        ...existing,
        triage_status: last.previousStatus ?? null,
        needs_annotation: last.previousNeedsAnnotation,
        flagged: last.previousFlagged ? 1 : 0,
      });
    }
  } catch (e) {
    Shared.showToast(`Undo failed: ${formatApiError(e)}`, { type: "error" });
    state.reviewHistory.push(last);
    _incrementReviewDecisionCounter(last.decisionKind || "");
    return;
  }

  state.reviewIndex = last.index;

  const reviewComplete = $("#reviewComplete");
  const reviewCard = $("#reviewCard");
  const reviewActions = document.querySelector(".review-actions");
  const reviewUndoBtn = $("#reviewUndo");
  if (reviewComplete) reviewComplete.hidden = true;
  if (reviewCard) reviewCard.hidden = false;
  if (reviewActions) reviewActions.style.display = "";
  if (reviewUndoBtn) reviewUndoBtn.hidden = false;

  await renderReviewCard();
}

function showReviewComplete() {
  const reviewCard = $("#reviewCard");
  const reviewActions = document.querySelector(".review-actions");
  const reviewUndoBtn = $("#reviewUndo");
  const reviewComplete = $("#reviewComplete");

  if (reviewCard) reviewCard.hidden = true;
  if (reviewActions) reviewActions.style.display = "none";
  if (reviewUndoBtn) reviewUndoBtn.hidden = true;
  if (reviewComplete) {
    reviewComplete.hidden = false;
    const desc = $("#reviewCompleteDesc");
    const total = state.reviewSnapshotTotal || state.reviewItems.length;
    if (desc) desc.textContent = `You reviewed ${total} item${total === 1 ? "" : "s"}.`;
    const statsEl = $("#reviewCompleteStats");
    if (statsEl) {
      statsEl.innerHTML = `
        <span class="review-stat keeper">${state.reviewKept} kept</span>
        <span class="review-stat moved">${state.reviewMoved} updated</span>
        <span class="review-stat hidden-s">${state.reviewHidden} discarded</span>
        <span class="review-stat skipped">${state.reviewSkipped} skipped</span>
      `;
    }
    const progressBar = $("#reviewProgressBar");
    if (progressBar) progressBar.style.width = "100%";
    const counter = $("#reviewCounter");
    if (counter) {
      const scopeTotal = Number.isFinite(Number(state.reviewScopeTotal))
        ? Math.max(0, Number(state.reviewScopeTotal))
        : total;
      counter.textContent = scopeTotal !== total ? `${total} of ${total} snapshot · ${scopeTotal} in scope` : `${total} of ${total}`;
    }
  }
}

// ─── Canvas Review Mode ──────────────────────────────────────────────────────

function enterCanvasReview() {
  if (!state.assets.length) {
    Shared.showToast("No items to review.", { type: "info" });
    return;
  }
  if (state.canvasCollectionBuild) exitCollectionBuild();
  let switchedFromExplorer = false;
  if (isExplorerViewActive()) {
    if (_ExplorerImpl && typeof _ExplorerImpl.getVisibleNodeIds === "function") {
      try {
        state.reviewSeedIds = _uniqNonEmpty(_ExplorerImpl.getVisibleNodeIds() || []);
      } catch (_) {
        state.reviewSeedIds = null;
      }
    } else {
      state.reviewSeedIds = null;
    }
    setViewMode("grid", { persist: false });
    switchedFromExplorer = true;
  } else {
    state.reviewSeedIds = null;
  }
  state.canvasReview = true;
  state.canvasSelected.clear();

  const browseView = $("#browseView");
  if (browseView) {
    browseView.classList.add("canvas-review-active");
    browseView.classList.add("canvas-selection-active");
  }

  const actionBar = $("#canvasActionBar");
  if (actionBar) actionBar.hidden = false;

  // Highlight grid button to indicate active review
  const gridBtn = $("#viewGrid");
  if (gridBtn) gridBtn.classList.add("reviewing");

  updateReviewScopeChips();
  updateCanvasSelectionCount();
  updateSidebarModeVisibility();
  Shared.showToast(
    switchedFromExplorer
      ? "Review actions are grid-only for safety. Switched to Grid review mode."
      : "Review mode — click a card for advanced details; use checkboxes for bulk actions or One-by-one for fast triage.",
    { type: "info" }
  );
}

function exitCanvasReview() {
  state.canvasReview = false;
  state.canvasSelected.clear();

  const browseView = $("#browseView");
  if (browseView) {
    browseView.classList.remove("canvas-review-active");
    if (!state.canvasCollectionBuild) browseView.classList.remove("canvas-selection-active");
  }

  const actionBar = $("#canvasActionBar");
  if (actionBar) actionBar.hidden = true;

  // Remove review highlight from grid button
  const gridBtn = $("#viewGrid");
  if (gridBtn) gridBtn.classList.remove("reviewing");

  $$(".card.canvas-selected").forEach((c) => c.classList.remove("canvas-selected"));
  updateSidebarModeVisibility();
}

function toggleCanvasSelection(id, cardEl) {
  if (state.canvasSelected.has(id)) {
    state.canvasSelected.delete(id);
    if (cardEl) cardEl.classList.remove("canvas-selected");
  } else {
    state.canvasSelected.add(id);
    if (cardEl) cardEl.classList.add("canvas-selected");
  }
  updateCanvasSelectionCount();
  updateCollectionBuildSelectionCount();
}

function selectAllCanvas() {
  state.assets.forEach((a) => state.canvasSelected.add(a.id));
  $$(".card").forEach((c) => {
    const id = c.dataset.id;
    if (id && state.canvasSelected.has(id)) c.classList.add("canvas-selected");
  });
  updateCanvasSelectionCount();
}

function clearCanvasSelection() {
  state.canvasSelected.clear();
  $$(".card.canvas-selected").forEach((c) => c.classList.remove("canvas-selected"));
  updateCanvasSelectionCount();
  updateCollectionBuildSelectionCount();
}

function updateCollectionBuildSelectionCount() {
  const count = state.canvasSelected.size;
  const countEl = $("#collectionBuildSelectionCount");
  if (countEl) countEl.textContent = `${count} selected`;
  const newBtn = $("#collectionBuildNew");
  if (newBtn) newBtn.disabled = count === 0;
  const existingBtn = $("#collectionBuildExisting");
  if (existingBtn) existingBtn.disabled = count === 0;
  const removeBtn = $("#collectionBuildRemove");
  if (removeBtn) {
    const scope = getReviewScopeInfo();
    const showRemove = scope.hasCollectionScope && scope.collectionIds.length === 1;
    removeBtn.hidden = !showRemove;
    removeBtn.disabled = !(showRemove && count > 0);
  }
}

function enterCollectionBuild(options = {}) {
  if (!state.assets.length) {
    Shared.showToast("No items are visible to add to a collection.", { type: "info" });
    return;
  }
  const initialSelectionId = String(options?.initialSelectionId || "").trim();
  if (state.canvasReview) exitCanvasReview();
  if (isExplorerViewActive()) setViewMode("grid", { persist: false });
  state.canvasCollectionBuild = true;
  state.canvasSelected.clear();
  if (initialSelectionId) state.canvasSelected.add(initialSelectionId);
  $("#browseView")?.classList.add("canvas-selection-active");
  const bar = $("#collectionBuildBar");
  if (bar) bar.hidden = false;
  $("#collectionBuildBtn")?.classList.add("active");
  updateCollectionBuildSelectionCount();
  renderGrid();
  Shared.showToast(
    initialSelectionId ? "Collection selection started. Choose more cards, then create or add to a collection." : "Select cards to add to a collection.",
    { type: "info", duration: initialSelectionId ? 3200 : 2200 }
  );
}

function exitCollectionBuild() {
  state.canvasCollectionBuild = false;
  state.canvasSelected.clear();
  $("#browseView")?.classList.remove("canvas-selection-active");
  const bar = $("#collectionBuildBar");
  if (bar) bar.hidden = true;
  $("#collectionBuildBtn")?.classList.remove("active");
  $$(".card.canvas-selected").forEach((card) => card.classList.remove("canvas-selected"));
  updateCollectionBuildSelectionCount();
}

async function removeSelectedFromActiveCollection() {
  const ids = Array.from(state.canvasSelected);
  const scope = getReviewScopeInfo();
  if (!ids.length || !scope.hasCollectionScope || scope.collectionIds.length !== 1) return;
  try {
    const results = await removeAssetsFromCollections(ids, scope.collectionIds);
    const removed = results.reduce((sum, result) => sum + Number(result.removed || 0), 0);
    clearCanvasSelection();
    await Promise.all([loadAssets(), loadCatalogTree(), loadCollections()]);
    Shared.showToast(`${removed} item${removed === 1 ? "" : "s"} removed from this collection.`, { type: "success" });
  } catch (e) {
    Shared.showToast(`Remove failed: ${formatApiError(e)}`, { type: "error" });
  }
}

function updateCanvasSelectionCount() {
  const count = state.canvasSelected.size;
  const el = $("#canvasSelectionCount");
  if (el) el.textContent = `${count} selected`;
  const hasSelection = count > 0;
  const scope = getReviewScopeInfo();
  const keepBtn = $("#canvasKeep");
  if (keepBtn) keepBtn.disabled = !hasSelection;
  const hideLocalBtn = $("#canvasHideLocal");
  if (hideLocalBtn) hideLocalBtn.disabled = !(hasSelection && scope.hasCollectionScope);
  const hideGlobalBtn = $("#canvasHideGlobal");
  if (hideGlobalBtn) {
    hideGlobalBtn.disabled = !hasSelection;
    const selectedAssets = Array.from(state.canvasSelected)
      .map((id) => state.assets.find((asset) => asset.id === id))
      .filter(Boolean);
    const shouldRestore = selectedAssets.length > 0 && selectedAssets.every((asset) => asset.triage_status === "hidden");
    hideGlobalBtn.textContent = shouldRestore ? "↟ Restore" : "✗ Discard";
    hideGlobalBtn.classList.toggle("canvas-action-restore", shouldRestore);
  }
  const flagBtn = $("#canvasFlag");
  if (flagBtn) {
    flagBtn.disabled = !(hasSelection && canUseFlag());
    const selectedAssets = Array.from(state.canvasSelected)
      .map((id) => state.assets.find((asset) => asset.id === id))
      .filter(Boolean);
    const shouldUnflag = selectedAssets.length > 0 && selectedAssets.every((asset) => asset.flagged == 1);
    flagBtn.textContent = shouldUnflag ? "⚐ Unflag" : "⚑ Flag";
  }
  const tagBtn = $("#canvasTag");
  if (tagBtn) tagBtn.disabled = !(hasSelection && canUseTag());
}

async function canvasBulkKeep() {
  const ids = Array.from(state.canvasSelected);
  if (!ids.length) return;
  try {
    await api("/api/assets/triage/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, status: "keeper" }),
    });
    ids.forEach((id) => {
      const a = state.assets.find((x) => x.id === id);
      if (a) a.triage_status = "keeper";
    });
    Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} marked as keepers.`, { type: "success" });
    clearCanvasSelection();
    renderGrid();
  } catch (e) {
    Shared.showToast(`Bulk keep failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function canvasBulkHideLocal() {
  const ids = Array.from(state.canvasSelected);
  if (!ids.length) return;
  const scope = getReviewScopeInfo();
  if (!scope.hasCollectionScope) {
    Shared.showToast("No active collection scope. Use Discard for library-wide removal.", { type: "info" });
    return;
  }
  try {
    const results = await removeAssetsFromCollections(ids, scope.collectionIds);
    const removed = results.reduce((sum, r) => sum + Number(r.removed || 0), 0);
    if (!removed) {
      Shared.showToast("Selected items were not in the active collection scope.", { type: "info" });
      return;
    }
    Shared.showToast(
      `Removed ${removed} item${removed === 1 ? "" : "s"} from active collection scope.`,
      { type: "success" }
    );
    clearCanvasSelection();
    await Promise.all([loadAssets(), loadCatalogTree()]);
  } catch (e) {
    Shared.showToast(`Collection hide failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function canvasBulkHideGlobal() {
  const ids = Array.from(state.canvasSelected);
  if (!ids.length) return;
  const selectedAssets = ids.map((id) => state.assets.find((asset) => asset.id === id)).filter(Boolean);
  const shouldRestore = selectedAssets.length > 0 && selectedAssets.every((asset) => asset.triage_status === "hidden");
  if (!shouldRestore && !confirmGlobalHideBulk(ids.length)) return;
  try {
    await api("/api/assets/triage/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, status: shouldRestore ? null : "hidden" }),
    });
    Shared.showToast(
      `${ids.length} item${ids.length === 1 ? "" : "s"} ${shouldRestore ? "restored" : "discarded"}.`,
      { type: "success" },
    );
    clearCanvasSelection();
    await Promise.all([loadAssets(), loadCatalogTree()]);
  } catch (e) {
    Shared.showToast(`${shouldRestore ? "Restore" : "Discard"} failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function canvasBulkToggleFlag() {
  if (!canUseFlag()) {
    Shared.showToast("Flagging is owner-only.", { type: "info" });
    return;
  }
  const ids = Array.from(state.canvasSelected);
  if (!ids.length) return;
  const selectedAssets = ids.map((id) => state.assets.find((asset) => asset.id === id)).filter(Boolean);
  const newFlagged = selectedAssets.length > 0 && selectedAssets.every((asset) => asset.flagged == 1) ? 0 : 1;
  try {
    await api("/api/assets/flag/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, flagged: newFlagged }),
    });
    ids.forEach((id) => {
      const a = state.assets.find((x) => x.id === id);
      if (a) a.flagged = newFlagged;
    });
    Shared.showToast(
      `${ids.length} item${ids.length === 1 ? "" : "s"} ${newFlagged ? "flagged for follow-up" : "unflagged"}.`,
      { type: "success" }
    );
    clearCanvasSelection();
    if (isReviewStatusFilterActive("flagged") && !newFlagged) {
      await loadAssets();
    } else {
      renderGrid();
    }
  } catch (e) {
    Shared.showToast(`Bulk flag failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function canvasBulkTag() {
  if (!canUseTag()) {
    Shared.showToast("Tag workflow retired.", { type: "info" });
    return;
  }
  const ids = Array.from(state.canvasSelected);
  if (!ids.length) return;
  try {
    await api("/api/assets/tag/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, tagged: 1 }),
    });
    ids.forEach((id) => {
      const a = state.assets.find((x) => x.id === id);
      if (a) a.tagged = 1;
    });
    Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} tagged for diagnosis.`, { type: "success" });
    clearCanvasSelection();
    renderGrid();
  } catch (e) {
    Shared.showToast(`Bulk tag failed: ${formatApiError(e)}`, { type: "error" });
  }
}

// Canvas review action bar wiring
const canvasKeepBtn = $("#canvasKeep");
if (canvasKeepBtn) canvasKeepBtn.addEventListener("click", canvasBulkKeep);
const canvasHideLocalBtn = $("#canvasHideLocal");
if (canvasHideLocalBtn) canvasHideLocalBtn.addEventListener("click", canvasBulkHideLocal);
const canvasHideGlobalBtn = $("#canvasHideGlobal");
if (canvasHideGlobalBtn) canvasHideGlobalBtn.addEventListener("click", canvasBulkHideGlobal);
const canvasFlagBtn = $("#canvasFlag");
if (canvasFlagBtn) canvasFlagBtn.addEventListener("click", canvasBulkToggleFlag);
const canvasTagBtn = $("#canvasTag");
if (canvasTagBtn) canvasTagBtn.addEventListener("click", canvasBulkTag);
const canvasClearBtn = $("#canvasClear");
if (canvasClearBtn) canvasClearBtn.addEventListener("click", clearCanvasSelection);
const canvasToOneByOneBtn = $("#canvasToOneByOne");
if (canvasToOneByOneBtn) canvasToOneByOneBtn.addEventListener("click", () => {
  clearCanvasSelection();
  enterReview();
});
const canvasExitReviewBtn = $("#canvasExitReview");
if (canvasExitReviewBtn) canvasExitReviewBtn.addEventListener("click", exitCanvasReview);

// Collection building is a separate creative selection mode.
const collectionBuildBtn = $("#collectionBuildBtn");
if (collectionBuildBtn) collectionBuildBtn.addEventListener("click", enterCollectionBuild);
const collectionBuildNewBtn = $("#collectionBuildNew");
if (collectionBuildNewBtn) collectionBuildNewBtn.addEventListener("click", () => openCollectionBuildModal("new"));
const collectionBuildExistingBtn = $("#collectionBuildExisting");
if (collectionBuildExistingBtn) collectionBuildExistingBtn.addEventListener("click", () => openCollectionBuildModal("existing"));
const collectionBuildRemoveBtn = $("#collectionBuildRemove");
if (collectionBuildRemoveBtn) collectionBuildRemoveBtn.addEventListener("click", removeSelectedFromActiveCollection);
const collectionBuildClearBtn = $("#collectionBuildClear");
if (collectionBuildClearBtn) collectionBuildClearBtn.addEventListener("click", clearCanvasSelection);
const collectionBuildDoneBtn = $("#collectionBuildDone");
if (collectionBuildDoneBtn) collectionBuildDoneBtn.addEventListener("click", exitCollectionBuild);

// Review button — canvas review is the default
const reviewBtn = $("#reviewBtn");
if (reviewBtn) reviewBtn.addEventListener("click", enterCanvasReview);

const reviewBackBtn = $("#reviewBack");
if (reviewBackBtn) reviewBackBtn.addEventListener("click", exitReview);

const reviewSkipBtn = $("#reviewSkipBtn");
if (reviewSkipBtn) reviewSkipBtn.addEventListener("click", () => reviewAction("skip"));

const reviewKeepBtn = $("#reviewKeepBtn");
if (reviewKeepBtn) reviewKeepBtn.addEventListener("click", () => reviewPrimaryAction("keep"));

const reviewHideLocalBtn = $("#reviewHideLocalBtn");
if (reviewHideLocalBtn) reviewHideLocalBtn.addEventListener("click", () => reviewPrimaryAction("hide_local"));

const reviewHideGlobalBtn = $("#reviewHideGlobalBtn");
if (reviewHideGlobalBtn) reviewHideGlobalBtn.addEventListener("click", () => reviewPrimaryAction("hide_global"));

const reviewFlagBtn = $("#reviewFlagBtn");
if (reviewFlagBtn) reviewFlagBtn.addEventListener("click", () => reviewPrimaryAction("flag"));

const reviewClearBtn = $("#reviewClearBtn");
if (reviewClearBtn) reviewClearBtn.addEventListener("click", () => reviewPrimaryAction("clear"));

const reviewClassificationKeepBtn = $("#reviewClassificationKeepBtn");
if (reviewClassificationKeepBtn) {
  reviewClassificationKeepBtn.addEventListener("click", () => saveReviewClassificationReview({
    track: _effectiveClassificationTrack(state.reviewItems[state.reviewIndex]?.classification_review || {}),
  }));
}

const reviewClassificationMoveTo = $("#reviewClassificationMoveTo");
if (reviewClassificationMoveTo) {
  reviewClassificationMoveTo.addEventListener("change", _persistCurrentReviewDraft);
}

const reviewClassificationFocusSelect = $("#reviewClassificationFocusSelect");
if (reviewClassificationFocusSelect) {
  reviewClassificationFocusSelect.addEventListener("change", _persistCurrentReviewDraft);
}

const reviewClassificationComment = $("#reviewClassificationComment");
if (reviewClassificationComment) {
  reviewClassificationComment.addEventListener("input", _persistCurrentReviewDraft);
}

const reviewClassificationSaveBtn = $("#reviewClassificationSaveBtn");
if (reviewClassificationSaveBtn) reviewClassificationSaveBtn.addEventListener("click", () => saveReviewClassificationReview());

const reviewClassificationIrrelevantBtn = $("#reviewClassificationIrrelevantBtn");
if (reviewClassificationIrrelevantBtn) {
  reviewClassificationIrrelevantBtn.addEventListener("click", () => saveReviewClassificationReview({ track: "irrelevant" }));
}

const reviewPrevBtn = $("#reviewPrevBtn");
if (reviewPrevBtn) reviewPrevBtn.addEventListener("click", undoReview);

const reviewUndoBtn = $("#reviewUndo");
if (reviewUndoBtn) reviewUndoBtn.addEventListener("click", undoReview);

const reviewExitBtn = $("#reviewExitBtn");
if (reviewExitBtn) reviewExitBtn.addEventListener("click", exitReview);

const reviewSkippedBtn = $("#reviewSkippedBtn");
if (reviewSkippedBtn) reviewSkippedBtn.addEventListener("click", async () => {
  // Restart with skipped items only.
  const skipped = state.reviewItems.filter((item) => {
    const histEntry = state.reviewHistory.find((h) => h.id === item.id);
    return histEntry && histEntry.decisionKind === "skip";
  });
  if (!skipped.length) { Shared.showToast("No skipped items.", { type: "info" }); return; }
  state.reviewItems = skipped;
  state.reviewIndex = 0;
  state.reviewHistory = [];
  state.reviewDrafts = {};
  state.reviewKept = 0;
  state.reviewMoved = 0;
  state.reviewHidden = 0;
  state.reviewSkipped = 0;
  state.reviewSnapshotTotal = skipped.length;
  state.reviewScopeTotal = skipped.length;
  const reviewComplete = $("#reviewComplete");
  const reviewCard = $("#reviewCard");
  const reviewActions = document.querySelector(".review-actions");
  const reviewUndoBtnEl = $("#reviewUndo");
  if (reviewComplete) reviewComplete.hidden = true;
  if (reviewCard) reviewCard.hidden = false;
  if (reviewActions) reviewActions.style.display = "";
  if (reviewUndoBtnEl) reviewUndoBtnEl.hidden = false;
  await renderReviewCard();
});

// ─── Keyboard shortcuts ──────────────────────────────────────────────────────────

window.addEventListener("keydown", (e) => {
  // Close modal with Escape
  if (e.key === "Escape") {
    if (!$("#modal").classList.contains("hidden")) { closeModal(); return; }
    if (!$("#collectionBuildModal").classList.contains("hidden")) { closeCollectionBuildModal(); return; }
    if (!$("#collectionShareModal").classList.contains("hidden")) { closeCollectionShareModal(); return; }
    if (!$("#collectionBulkModal").classList.contains("hidden")) { closeCollectionBulkModal(); return; }
    if (!$("#mediaImportModal").classList.contains("hidden") && !isAnyImportBusy()) { closeMediaImportModal(); return; }
    if (!$("#scanImportModal").classList.contains("hidden") && !state.scanImportBusy) { closeScanImportModal(); return; }
    if (!$("#photoImportModal").classList.contains("hidden") && !state.photoImportBusy) { closePhotoImportModal(); return; }
    if (!$("#videoImportModal").classList.contains("hidden") && !state.videoImportBusy) { closeVideoImportModal(); return; }
    if (state.canvasReview) { exitCanvasReview(); return; }
    if (state.canvasCollectionBuild) { exitCollectionBuild(); return; }
    if (state.view === "review") { exitReview(); return; }
    return;
  }

  // Canvas selection shortcuts
  if (state.canvasReview || state.canvasCollectionBuild) {
    const tag = (e.target && e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (!$("#modal").classList.contains("hidden")) return;
    if ((e.ctrlKey || e.metaKey) && e.key === "a") {
      e.preventDefault();
      selectAllCanvas();
    }
    return;
  }

  // One-by-one review mode shortcuts (only when review is active and no modal/input focused)
  if (state.view !== "review") return;
  const tag = (e.target && e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return;
  if (!$("#modal").classList.contains("hidden")) return;

  switch (e.key) {
    case "ArrowRight":
    case "k":
    case "K":
      e.preventDefault();
      saveReviewClassificationReview({
        track: _effectiveClassificationTrack(state.reviewItems[state.reviewIndex]?.classification_review || {}),
      });
      break;
    case "ArrowLeft":
    case "s":
    case "S":
      e.preventDefault();
      saveReviewClassificationReview({ track: "irrelevant" });
      break;
    case "Enter":
    case "m":
    case "M":
      e.preventDefault();
      saveReviewClassificationReview();
      break;
    case "ArrowDown":
    case " ":
      e.preventDefault();
      reviewAction("skip");
      break;
    case "z":
    case "Z":
      e.preventDefault();
      undoReview();
      break;
  }
});

// ─── Chat bar ────────────────────────────────────────────────────────────────────

function showChatSpinner(text) {
  const bar = $("#chatResponse");
  if (!bar) return;
  clearTimeout(addChatResponse._timer);
  bar.innerHTML = `<span class="chat-spinner"></span>${escapeHtml(text || "Thinking…")}`;
  bar.hidden = false;
}

function hideChatSpinner() {
  const bar = $("#chatResponse");
  if (!bar) return;
  clearTimeout(addChatResponse._timer);
  bar.hidden = true;
  bar.innerHTML = "";
}

function addChatResponse(text, duration) {
  const bar = $("#chatResponse");
  if (!bar) return;
  bar.innerHTML = "";
  bar.textContent = text;
  bar.hidden = false;
  clearTimeout(addChatResponse._timer);
  addChatResponse._timer = setTimeout(() => { if (bar) bar.hidden = true; }, duration || 6000);
}

// Extract meaningful keywords from a chat message for text-search fallback.
const _CHAT_STOP_WORDS = new Set([
  "show", "me", "find", "get", "display", "list", "search", "look", "give",
  "make", "create", "do", "see", "open", "go", "browse", "view", "let",
  "for", "some", "all", "the", "a", "an", "with", "in", "of", "and",
  "or", "that", "have", "has", "are", "is", "it", "to", "my", "its",
  "please", "can", "you", "could", "would", "want", "need", "like",
  "i", "items", "things", "images", "photos", "pictures", "inspirations",
  "inspiration", "ideas", "try", "just",
]);
function _chatKeywords(text) {
  return text.toLowerCase().split(/\s+/)
    .filter((w) => w.length > 1 && !_CHAT_STOP_WORDS.has(w))
    .join(" ");
}

function _parseRollbackDaysCommand(text) {
  const raw = String(text || "").trim().toLowerCase();
  if (!raw) return null;
  if (!/^\/?rollback\b/.test(raw)) return null;
  if (/\bday\s+before\s+yesterday\b/.test(raw)) return 2;
  if (/\byesterday\b/.test(raw)) return 1;
  const explicitDays = raw.match(/\b(\d+)\s*d(?:ays?)?\b/) || raw.match(/^\/?rollback\s+(\d+)\b/);
  if (explicitDays) {
    const days = Number(explicitDays[1]);
    if (Number.isFinite(days) && days >= 0) return days;
  }
  return 2;
}

async function _runOwnerTriageRollback(daysAgo) {
  if (!isOwner()) {
    addChatResponse("Rollback is owner-only.", 5000);
    return;
  }
  const days = Math.max(0, Math.min(3650, Number(daysAgo || 0)));
  showChatSpinner(`Rolling back triage changes from the last ${days} day${days === 1 ? "" : "s"}…`);
  try {
    const report = await api("/api/triage/rollback", {
      method: "POST",
      body: JSON.stringify({ days_ago: days }),
    });
    await Promise.all([loadAssets(), loadCatalogTree()]);
    if (isOwner()) await loadHiddenTree();
    hideChatSpinner();
    const updated = Number(report?.updated || 0);
    if (!updated) {
      addChatResponse(`No triage changes found in the last ${days} day${days === 1 ? "" : "s"}.`, 7000);
      return;
    }
    addChatResponse(
      `Rolled back ${updated} item${updated === 1 ? "" : "s"} to their pre-cutoff triage state.`,
      9000
    );
  } catch (e) {
    hideChatSpinner();
    addChatResponse(`Rollback failed: ${formatApiError(e)}`, 8000);
  }
}

async function processChat(text) {
  const trimmed = (text || "").trim();
  if (!trimmed) return;

  const rollbackDays = _parseRollbackDaysCommand(trimmed);
  if (rollbackDays != null) {
    await _runOwnerTriageRollback(rollbackDays);
    return;
  }

  showChatSpinner("Thinking\u2026");

  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message: trimmed }),
    });

    const action = data.action || "message";
    const params = data.params || {};
    let message = data.message || "";
    const routingMessage = data.routing_message || "";

    // Show routing acknowledgment while grid loads
    if (routingMessage && action !== "message") {
      showChatSpinner(routingMessage);
    }

    // Persist the prompt for any action that changes the visible results
    if (action !== "message") {
      state.chatPrompt = trimmed;
    }

    await executeChatAction(action, params);

    if (action === "search" && /dave is unavailable/i.test(message) && (state.assets || []).length === 0) {
      const reasonMatch = message.match(/dave is unavailable\s*\(([^)]+)\)/i);
      const reason = reasonMatch ? ` (${reasonMatch[1]})` : "";
      state.q = "";
      state.chatPrompt = "";
      state.chatItemIds = null;
      await loadAssets();
      message = `Dave is unavailable right now${reason}. Keyword fallback found no matches, so I left your current view unchanged.`;
    }

    hideChatSpinner();

    if (message) {
      addChatResponse(message, action === "message" ? 12000 : 6000);
    }
  } catch (e) {
    hideChatSpinner();
    const errMsg = formatApiError(e);
    const keywords = _chatKeywords(trimmed) || trimmed;
    state.chatPrompt = trimmed;
    state.q = keywords;
    try {
      await loadAssets();
      if ((state.assets || []).length === 0) {
        // If naive keyword fallback yields no results, revert to the user's
        // current tree/panel scope instead of stranding them on an empty grid.
        state.q = "";
        state.chatPrompt = "";
        state.chatItemIds = null;
        await loadAssets();
        addChatResponse(
          `Dave is unavailable right now (${errMsg}). Text fallback found no matches, so I left your current view unchanged.`,
          9000
        );
      } else {
        addChatResponse(`Dave is unavailable right now (${errMsg}). Filtering by "${keywords}" instead.`, 9000);
      }
    } catch (loadErr) {
      addChatResponse(
        `Dave failed (${errMsg}) and fallback search failed (${formatApiError(loadErr)}).`,
        9000
      );
    }
  }
}

async function executeChatAction(action, params) {
  switch (action) {
    case "show_items": {
      // Fetch specific items by ID prefix and display
      const ids = (params.ids || []).join(",");
      if (!ids) break;
      try {
        // Clear any stale filter state so the indicator reflects the chat result
        state.q = "";
        state.currentSource = null;
        state.currentBoard = null;
        state.currentContentKind = null;
        clearCollectionFilter();
        clearCatalogFilter();
        clearClassificationFilter();
        state.currentTreeNodeId = null;
        state.triageFilter = "";
        const data = await api(`/api/assets?ids=${encodeURIComponent(ids)}&include_hidden=1&limit=200`);
        state.assets = data.assets || [];
        state.hasMore = false;
        state.offset = state.assets.length;
        // Store curated IDs so the explorer can highlight just these
        state.chatItemIds = state.assets.map((a) => a.id);
        renderGrid();
        updateStats();
        updateLoadMoreBtn();
        updateFilterIndicator();
        syncExplorerFilter();
      } catch (e) {
        addChatResponse(`Failed to load items: ${formatApiError(e)}`, 8000);
      }
      break;
    }
    case "show_sidebar": {
      const type = params.type || "";
      if (type === "collections") {
        await loadCollections();
        const visible = state.collections.filter((c) => (c.name || "").toLowerCase() !== "hidden");
        showDynamicSidebar("Collections", visible.map((c) => ({
          label: c.name,
          count: c.count || 0,
          onclick: () => { setCollectionFilter(c.id); hideDynamicSidebar(); },
        })));
      } else if (type === "boards") {
        const sourceFilter = normalizeSourceKey(params.source || "");
        // Build board list from catalog tree
        const boards = [];
        for (const node of (state.catalogTree || [])) {
          if (node.type !== "source") continue;
          const sourceKey = sourceKeyFromNode(node);
          const sourceLabel = sourceDisplayName(sourceKey) || node.label;
          if (sourceFilter && sourceKey !== sourceFilter) continue;
          for (const child of (node.children || [])) {
            if (child.type !== "board") continue;
            boards.push({
              label: `${child.label} (${sourceLabel})`,
              count: child.count,
              onclick: () => {
                const boardDbName = child.board_name || "";
                const isCatchAll = boardDbName.startsWith("(");
                if (isCatchAll && child.file) {
                  state.currentSource = null;
                  state.currentBoard = null;
                  state.currentContentKind = null;
                  clearCollectionFilter();
                  setCatalogFilter([child.file], { label: child.label, nodeId: null });
                } else {
                  state.currentSource = sourceKey;
                  state.currentBoard = boardDbName || child.label;
                  state.currentContentKind = null;
                  clearCollectionFilter();
                  clearCatalogFilter();
                }
                state.currentTreeNodeId = null;
                state.offset = 0;
                renderCatalogTree();
                loadAssets();
                hideDynamicSidebar();
              },
            });
          }
        }
        showDynamicSidebar(sourceFilter ? `${sourceDisplayName(sourceFilter) || sourceFilter} Boards` : "All Boards", boards);
      } else if (type === "sources") {
        const sources = (state.catalogTree || [])
          .filter((n) => n.type === "source")
          .map((n) => ({
            label: sourceDisplayName(sourceKeyFromNode(n)) || n.label,
            count: n.count,
            onclick: () => {
              state.currentSource = sourceKeyFromNode(n);
              state.currentBoard = null;
              state.currentContentKind = null;
              clearCollectionFilter();
              clearCatalogFilter();
              state.currentTreeNodeId = null;
              state.offset = 0;
              renderCatalogTree();
              loadAssets();
              hideDynamicSidebar();
            },
          }));
        showDynamicSidebar("Sources", sources);
      }
      break;
    }
    case "filter": {
      state.chatItemIds = null;
      state.currentTreeNodeId = null;
      if (params.source !== undefined) {
        state.currentSource = normalizeSourceKey(params.source) || null;
        if (params.content_kind === undefined || params.source === "" || params.source == null) {
          state.currentContentKind = null;
        }
        if (params.source) {
          clearCatalogFilter();
          if (!params.board) clearCollectionFilter();
        }
      }
      if (params.board !== undefined) {
        state.currentBoard = params.board || null;
        state.currentContentKind = null;
        if (params.board) {
          clearCollectionFilter();
          clearCatalogFilter();
        }
      }
      if (params.content_kind !== undefined) {
        const kind = String(params.content_kind || "").trim().toLowerCase();
        state.currentContentKind = kind || null;
        if (kind) {
          clearCollectionFilter();
          clearCatalogFilter();
          if (!state.currentSource) state.currentSource = "scan";
          state.currentBoard = null;
        }
      }
      if (params.triage_status !== undefined) {
        state.triageFilter = params.triage_status || "";
      }
      if (params.q !== undefined) {
        state.q = params.q || "";
      }
      if (params.collection_id !== undefined) {
        if (params.collection_id) {
          state.currentSource = null;
          state.currentBoard = null;
          state.currentContentKind = null;
          clearCatalogFilter();
          const col = state.collections.find((c) => c.id === params.collection_id);
          setCollectionFilterIds([params.collection_id], { label: col ? col.name : "", nodeId: null });
        } else {
          clearCollectionFilter();
        }
      }
      renderCatalogTree();
      await loadAssets();
      break;
    }
    case "search": {
      state.chatItemIds = null;
      state.q = params.q || "";
      await loadAssets();
      break;
    }
    case "semantic_search": {
      state.chatItemIds = null;
      state.q = `sem:${params.q || ""}`;
      await loadAssets();
      break;
    }
    case "create_collection": {
      if (params.name) {
        try {
          await api("/api/collections", {
            method: "POST",
            body: JSON.stringify({ name: params.name }),
          });
          await loadCollections();
          await loadCatalogTree();
        } catch (e) {
          addChatResponse(`Couldn't create collection: ${formatApiError(e)}`, 8000);
        }
      }
      break;
    }
    case "show_collection": {
      const name = (params.name || "").toLowerCase();
      const col = state.collections.find(
        (c) => c.name.toLowerCase() === name || c.name.toLowerCase().includes(name)
      );
      if (col) {
        setCollectionFilter(col.id);
      } else if (params.collection_id) {
        setCollectionFilter(params.collection_id);
      }
      break;
    }
    case "enter_review": {
      enterCanvasReview();
      break;
    }
    case "clear_filters": {
      state.currentSource = null;
      state.currentBoard = null;
      state.currentContentKind = null;
      clearCollectionFilter();
      clearCatalogFilter();
      clearClassificationFilter();
      state.currentTreeNodeId = null;
      state.triageFilter = "";
      state.q = "";
      renderCatalogTree();
      await loadAssets();
      break;
    }
    case "bulk_triage": {
      const status = params.status || null;
      // In canvas review with selection, act on selected items; otherwise all visible
      const ids = (state.canvasReview && state.canvasSelected.size > 0)
        ? Array.from(state.canvasSelected)
        : state.assets.map((a) => a.id);
      if (!ids.length) {
        addChatResponse("No items visible to triage.", 6000);
        break;
      }
      try {
        const scope = getReviewScopeInfo();
        const shouldUseCollectionHide = status === "hidden" && scope.hasCollectionScope;
        if (shouldUseCollectionHide) {
          await removeAssetsFromCollections(ids, scope.collectionIds);
          await loadCatalogTree();
        } else {
          await api("/api/assets/triage/bulk", {
            method: "POST",
            body: JSON.stringify({ ids, status }),
          });
        }
        if (state.canvasReview) clearCanvasSelection();
        await loadAssets();
      } catch (e) {
        addChatResponse(`Bulk triage failed: ${formatApiError(e)}`, 8000);
      }
      break;
    }
    case "bulk_flag": {
      if (!canUseFlag()) {
        addChatResponse("Flagging is owner-only.", 6000);
        break;
      }
      const ids = (state.canvasReview && state.canvasSelected.size > 0)
        ? Array.from(state.canvasSelected)
        : state.assets.map((a) => a.id);
      if (!ids.length) {
        addChatResponse("No items to flag.", 6000);
        break;
      }
      try {
        await api("/api/assets/flag/bulk", {
          method: "POST",
          body: JSON.stringify({ ids, flagged: 1 }),
        });
        if (state.canvasReview) clearCanvasSelection();
        await loadAssets();
      } catch (e) {
        addChatResponse(`Bulk flag failed: ${formatApiError(e)}`, 8000);
      }
      break;
    }
    case "triage_by_query": {
      // Server already applied the triage — just refresh the grid
      await loadAssets();
      break;
    }
    case "message":
    default:
      break;
  }
}

const chatInput = $("#chatInput");
const chatSend = $("#chatSend");
if (chatSend) chatSend.addEventListener("click", () => {
  const val = chatInput?.value || "";
  if (val.trim()) { processChat(val.trim()); chatInput.value = ""; }
});
if (chatInput) chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    const val = chatInput.value || "";
    if (val.trim()) { processChat(val.trim()); chatInput.value = ""; }
  }
});

// ─── View toggle (Grid / Explorer) ───────────────────────────────────────────────

let explorerLoaded = false;
let explorerData = null;

const viewGridBtn = $("#viewGrid");
const viewExplorerBtn = $("#viewExplorer");
const explorerModeChip = $("#explorerModeChip");
const explorerBusyOverlay = $("#explorerBusyOverlay");
const explorerBusyText = $("#explorerBusyText");

// Explorer implementations: 3D primary, with 2D fallback when unavailable.
const _Explorer2D = window.AttractorExplorer || window.Explorer || null;
let _explorerMode = "3d";   // "2d" | "3d"
let _ExplorerImpl = null;
let _disable3DForSession = false;
let _explorer3DLoadPromise = null;
const EXPLORER_3D_MODULE_URL = `${_B}/app/attractor-explorer-3d.js?v=60`;
// Hard refresh in Safari can cold-load Three.js from CDN; allow enough
// headroom so we do not incorrectly drop into 2D fallback.
const EXPLORER_3D_READY_WAIT_MS = 12000;
const EXPLORER_3D_READY_POLL_MS = 50;
function _getExplorer3D() {
  const impl = window.AttractorExplorer3D || null;
  if (!impl || impl.__unavailable) return null;
  return impl;
}

async function _waitForExplorer3DReady(timeoutMs = EXPLORER_3D_READY_WAIT_MS) {
  if (_disable3DForSession) return;
  const start = performance.now();
  while ((performance.now() - start) < timeoutMs) {
    const marker = window.AttractorExplorer3D;
    if (marker) return;
    await new Promise((resolve) => setTimeout(resolve, EXPLORER_3D_READY_POLL_MS));
  }
}

async function _ensureExplorer3DLoaded() {
  if (_disable3DForSession) return null;
  const existing = _getExplorer3D();
  if (existing) return existing;

  if (!_explorer3DLoadPromise) {
    const marker = document.querySelector('script[data-explorer3d="1"]');
    if (marker) {
      _explorer3DLoadPromise = Promise.resolve();
    } else {
      _explorer3DLoadPromise = new Promise((resolve) => {
        const script = document.createElement("script");
        script.type = "module";
        script.src = EXPLORER_3D_MODULE_URL;
        script.dataset.explorer3d = "1";
        script.onload = () => resolve();
        script.onerror = (err) => {
          console.warn("[Explorer] 3D module load failed", err);
          resolve();
        };
        document.head.appendChild(script);
      });
    }
  }

  await _explorer3DLoadPromise;
  await _waitForExplorer3DReady();
  return _getExplorer3D();
}

function _filterKeyFromIds(ids) {
  if (!Array.isArray(ids) || ids.length === 0) return "";
  return ids.slice().sort().join("|");
}

function _filterExplorerDataByIds(data, ids) {
  if (!data || !Array.isArray(data.assets) || !Array.isArray(ids) || ids.length === 0) return data;
  const wanted = new Set(ids);
  return {
    ...data,
    assets: data.assets.filter((asset) => wanted.has(asset.id)),
    filtered_total: ids.length,
  };
}

function _resolveExplorerImpl(forceMode = null) {
  if (forceMode === "2d") return { impl: _Explorer2D, mode: "2d" };
  if (!_disable3DForSession && (forceMode === "3d" || !_isExplorerMobileConstrained())) {
    const e3d = _getExplorer3D();
    if (e3d) return { impl: e3d, mode: "3d" };
  }
  return { impl: _Explorer2D, mode: "2d" };
}
let _cachedExplorerAttractorData = null;
let _cachedExplorerAttractorDataIncludesHidden = false;
let _explorerFilterCount = null;
let _explorerPayloadIncludesHidden = false;
let _explorerScopeReloading = false;
let _explorerModeReloading = false;
let _busyCursorDepth = 0;
let _explorerBusyDepth = 0;
let _explorerBusyStartedAt = 0;
let _explorerBusyToken = 0;
const EXPLORER_MIN_BUSY_MS = 280;
const EXPLORER_MOBILE_3D_BUDGET_KEY = "inspirations.explorer.mobile3dBudget.v1";
const EXPLORER_MOBILE_3D_FALLBACK_BUDGET = 650;
let _explorerPayloadFilterKey = "";
let _explorerModeChipOverride = "";
let _explorerInternalFilterIds = null;
let _explorerMobile3DBudget = null;
let _explorerMobile3DBudgetPromise = null;

function _setGlobalBusyCursor(cursor) {
  if (document.body) document.body.style.cursor = cursor;
  if (document.documentElement) document.documentElement.style.cursor = cursor;
  const container = document.getElementById("explorerContainer");
  if (container) container.style.cursor = cursor;
}

function _pushBusyCursor() {
  _busyCursorDepth += 1;
  _setGlobalBusyCursor("wait");
}

function _popBusyCursor() {
  _busyCursorDepth = Math.max(0, _busyCursorDepth - 1);
  if (_busyCursorDepth === 0) _setGlobalBusyCursor("");
}

function _nextPaint() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve());
  });
}

function _setExplorerBusyOverlay(visible, text = "") {
  if (!explorerBusyOverlay) return;
  if (explorerBusyText && text) explorerBusyText.textContent = text;
  explorerBusyOverlay.hidden = !visible;
}

function _setExplorerModeChipOverride(text = "") {
  _explorerModeChipOverride = String(text || "");
  updateExplorerModeChip();
}

function _setExplorerFrozen(visible) {
  const explorerView = $("#explorerView");
  if (!explorerView) return;
  explorerView.classList.toggle("explorer-frozen", !!visible);
}

function _beginExplorerBusy(message) {
  _explorerBusyDepth += 1;
  if (_explorerBusyDepth === 1) {
    _explorerBusyStartedAt = performance.now();
    _explorerBusyToken += 1;
    _pushBusyCursor();
    _setExplorerFrozen(true);
    if (viewExplorerBtn) viewExplorerBtn.disabled = true;
  }
  _setExplorerBusyOverlay(true, message);
}

async function _endExplorerBusy() {
  _explorerBusyDepth = Math.max(0, _explorerBusyDepth - 1);
  if (_explorerBusyDepth !== 0) return;
  const token = _explorerBusyToken;
  const elapsed = Math.max(0, performance.now() - _explorerBusyStartedAt);
  const waitMs = Math.max(0, EXPLORER_MIN_BUSY_MS - elapsed);
  if (waitMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, waitMs));
  }
  if (_explorerBusyDepth !== 0 || token !== _explorerBusyToken) return;
  _setExplorerBusyOverlay(false);
  _setExplorerFrozen(false);
  if (viewExplorerBtn) viewExplorerBtn.disabled = false;
  _popBusyCursor();
}

function _isAttractorPayload(data) {
  return !!(
    data &&
    Array.isArray(data.assets) &&
    Array.isArray(data.dimensions) &&
    data.categories &&
    data.attractors
  );
}

function _isExplorerMobileConstrained() {
  return !!(
    window.matchMedia &&
    (
      window.matchMedia("(max-width: 900px)").matches ||
      window.matchMedia("(hover: none) and (pointer: coarse)").matches
    )
  );
}

function _explorerMobileBudgetCacheKey() {
  const dpr = Math.round((window.devicePixelRatio || 1) * 100) / 100;
  const width = Math.round(window.innerWidth || 0);
  const height = Math.round(window.innerHeight || 0);
  const cores = Number(navigator.hardwareConcurrency || 0);
  return `${width}x${height}@${dpr}/c${cores}`;
}

function _readExplorerMobile3DBudget() {
  try {
    const raw = window.sessionStorage?.getItem(EXPLORER_MOBILE_3D_BUDGET_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.cacheKey !== _explorerMobileBudgetCacheKey()) return null;
    const nodeLimit = Number(parsed.nodeLimit);
    if (!Number.isFinite(nodeLimit) || nodeLimit < 1) return null;
    return parsed;
  } catch (_) {
    return null;
  }
}

function _writeExplorerMobile3DBudget(budget) {
  try {
    window.sessionStorage?.setItem(EXPLORER_MOBILE_3D_BUDGET_KEY, JSON.stringify(budget));
  } catch (_) {
    // Session storage is optional; the benchmark can be rerun.
  }
}

function _makeExplorerMobile3DBudget(nodeLimit, details = {}) {
  const limit = Math.max(250, Math.min(2200, Math.round(Number(nodeLimit) || EXPLORER_MOBILE_3D_FALLBACK_BUDGET)));
  return {
    cacheKey: _explorerMobileBudgetCacheKey(),
    nodeLimit: limit,
    measuredAt: Date.now(),
    ...details,
  };
}

async function _measureExplorerMobile3DBudget() {
  const fallback = _makeExplorerMobile3DBudget(EXPLORER_MOBILE_3D_FALLBACK_BUDGET, {
    source: "fallback",
    reason: "WebGL benchmark unavailable",
  });
  const canvas = document.createElement("canvas");
  const dpr = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
  canvas.width = Math.round(256 * dpr);
  canvas.height = Math.round(256 * dpr);
  const gl = canvas.getContext("webgl", {
    alpha: false,
    antialias: false,
    depth: false,
    failIfMajorPerformanceCaveat: false,
    powerPreference: "high-performance",
    preserveDrawingBuffer: false,
    stencil: false,
  });
  if (!gl) return fallback;

  const compileShader = (type, source) => {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  };

  const vertexShader = compileShader(gl.VERTEX_SHADER, `
    attribute vec2 a_pos;
    void main() {
      gl_Position = vec4(a_pos, 0.0, 1.0);
      gl_PointSize = 2.0;
    }
  `);
  const fragmentShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    void main() {
      gl_FragColor = vec4(1.0, 0.85, 0.35, 0.85);
    }
  `);
  if (!vertexShader || !fragmentShader) return fallback;

  const program = gl.createProgram();
  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return fallback;
  gl.useProgram(program);

  const counts = [350, 600, 900, 1200, 1600, 2200, 3000, 4000];
  const maxCount = counts[counts.length - 1];
  const positions = new Float32Array(maxCount * 2);
  for (let i = 0; i < maxCount; i += 1) {
    // Deterministic scatter, enough to exercise draw cost without layout work.
    const a = i * 2.399963229728653;
    const r = Math.sqrt((i + 0.5) / maxCount) * 1.9;
    positions[i * 2] = Math.cos(a) * r * 0.5;
    positions[i * 2 + 1] = Math.sin(a) * r * 0.5;
  }

  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(program, "a_pos");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  gl.viewport(0, 0, canvas.width, canvas.height);

  let drawBudget = counts[0];
  let lastAvgMs = 0;
  const targetDrawMs = 4.5;
  for (const count of counts) {
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const start = performance.now();
    for (let pass = 0; pass < 4; pass += 1) {
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.POINTS, 0, count);
    }
    gl.finish();
    lastAvgMs = (performance.now() - start) / 4;
    if (lastAvgMs <= targetDrawMs) {
      drawBudget = count;
    } else {
      break;
    }
  }

  const maxTextureSize = Number(gl.getParameter(gl.MAX_TEXTURE_SIZE) || 0);
  const viewportPixels = (window.innerWidth || 0) * (window.innerHeight || 0) * dpr * dpr;
  const textureFactor = maxTextureSize && maxTextureSize < 4096 ? 0.72 : 1;
  const viewportFactor = viewportPixels > 2_800_000 ? 0.82 : 1;
  const mobileSafetyFactor = 0.55;
  const nodeLimit = drawBudget * mobileSafetyFactor * textureFactor * viewportFactor;
  return _makeExplorerMobile3DBudget(nodeLimit, {
    source: "webgl-draw",
    drawBudget,
    lastAvgMs: Math.round(lastAvgMs * 100) / 100,
    maxTextureSize,
  });
}

async function _getExplorerMobile3DBudget() {
  if (!_isExplorerMobileConstrained()) {
    return _makeExplorerMobile3DBudget(Number.POSITIVE_INFINITY, { source: "desktop" });
  }
  if (_explorerMobile3DBudget) return _explorerMobile3DBudget;
  const stored = _readExplorerMobile3DBudget();
  if (stored) {
    _explorerMobile3DBudget = stored;
    return stored;
  }
  if (!_explorerMobile3DBudgetPromise) {
    _explorerMobile3DBudgetPromise = _measureExplorerMobile3DBudget()
      .then((budget) => {
        _explorerMobile3DBudget = budget;
        _writeExplorerMobile3DBudget(budget);
        updateExplorerModeChip();
        return budget;
      })
      .finally(() => {
        _explorerMobile3DBudgetPromise = null;
      });
  }
  return _explorerMobile3DBudgetPromise;
}

function _canUseMobile3DForCount(count, budget) {
  const n = Number(count || 0);
  if (!Number.isFinite(n) || n <= 0) return false;
  const limit = Number(budget?.nodeLimit || EXPLORER_MOBILE_3D_FALLBACK_BUDGET);
  return n <= limit;
}

function _merge3DExplorerData(layoutData, attractorData) {
  const base = attractorData || {};
  const assets = Array.isArray(base.assets) ? base.assets : [];
  const layoutNodes = Array.isArray(layoutData?.nodes) ? layoutData.nodes : [];
  const layoutById = new Map(layoutNodes.map((node) => [node.id, node]));
  let matched = 0;
  let unmatched = 0;

  // Layout coordinates use a different scale than attractor-data fallback.
  // If a node is missing from layout (usually no embedding yet), place it
  // near the layout centroid with tiny deterministic jitter.
  const layoutCenter = (() => {
    if (!layoutNodes.length) return { x: 0, y: 0, z: 0 };
    let sx = 0;
    let sy = 0;
    let sz = 0;
    for (const n of layoutNodes) {
      sx += Number.isFinite(n.x) ? n.x : 0;
      sy += Number.isFinite(n.y) ? n.y : 0;
      sz += Number.isFinite(n.z) ? n.z : 0;
    }
    return { x: sx / layoutNodes.length, y: sy / layoutNodes.length, z: sz / layoutNodes.length };
  })();
  const jitterScale = (() => {
    if (!layoutNodes.length) return 0.8;
    let minX = Infinity, minY = Infinity, minZ = Infinity;
    let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
    for (const n of layoutNodes) {
      const x = Number.isFinite(n.x) ? n.x : 0;
      const y = Number.isFinite(n.y) ? n.y : 0;
      const z = Number.isFinite(n.z) ? n.z : 0;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (z < minZ) minZ = z;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
      if (z > maxZ) maxZ = z;
    }
    const span = Math.max(maxX - minX, maxY - minY, maxZ - minZ);
    return Math.max(0.5, Math.min(2.5, span * 0.03));
  })();
  const _idHash = (id) => {
    const raw = String(id || "");
    let h = 2166136261;
    for (let i = 0; i < raw.length; i++) {
      h ^= raw.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  };
  const _axisJitter = (seed, shift) => (((seed >> shift) & 1023) / 1023 - 0.5) * 2 * jitterScale;

  const mergedAssets = assets.map((asset) => {
    const layoutNode = layoutById.get(asset.id);
    if (!layoutNode) {
      unmatched += 1;
      const seed = _idHash(asset.id);
      return {
        ...asset,
        x: layoutCenter.x + _axisJitter(seed, 0),
        y: layoutCenter.y + _axisJitter(seed, 10),
        z: layoutCenter.z + _axisJitter(seed, 20),
      };
    }
    matched += 1;
    return {
      ...asset,
      x: Number.isFinite(layoutNode.x) ? layoutNode.x : asset.x,
      y: Number.isFinite(layoutNode.y) ? layoutNode.y : asset.y,
      z: Number.isFinite(layoutNode.z) ? layoutNode.z : asset.z,
      title: asset.title || layoutNode.title || "",
      t: asset.t || layoutNode.thumb_url || "",
    };
  });

  if (layoutNodes.length === 0) {
    console.warn("[Explorer] 3D layout returned no nodes; using PCA fallback positions");
  } else if (matched === 0) {
    console.warn("[Explorer] 3D layout IDs did not overlap; using PCA fallback positions");
  } else {
    console.log(`[Explorer] 3D layout merged ${matched}/${assets.length} nodes (${unmatched} fallback)`);
  }

  return {
    ...base,
    assets: mergedAssets,
    layout_clusters: Array.isArray(layoutData?.clusters) ? layoutData.clusters : [],
  };
}

function _shouldExplorerIncludeHiddenData() {
  return isOwner() && (state.showDiscarded || _isHiddenReviewQueue());
}

async function _loadExplorerPayload(mode, includeHidden, payloadFilterIds = null) {
  const hiddenQs = includeHidden ? "include_hidden=1" : "";
  const attractorUrl = `/api/explorer/attractor-data?dims=2${hiddenQs ? `&${hiddenQs}` : ""}`;
  const layoutUrl = `/api/explorer/layout${hiddenQs ? `?${hiddenQs}` : ""}`;

  if (mode === "3d") {
    // Keep 3D loads fast: reuse attractor metadata (vectors/chips) already
    // loaded for 2D, and only fetch layout coords for the current refresh.
    const layoutPromise = api(layoutUrl);
    let baseData =
      (_isAttractorPayload(explorerData) && _explorerPayloadIncludesHidden === includeHidden)
        ? explorerData
        : null;
    if (!_isAttractorPayload(baseData)) {
      baseData =
        (_isAttractorPayload(_cachedExplorerAttractorData)
          && _cachedExplorerAttractorDataIncludesHidden === includeHidden)
          ? _cachedExplorerAttractorData
          : null;
    }
    if (!_isAttractorPayload(baseData)) {
      baseData = await api(attractorUrl);
    }
    _cachedExplorerAttractorData = baseData;
    _cachedExplorerAttractorDataIncludesHidden = includeHidden;
    try {
      const layoutData = await layoutPromise;
      return _filterExplorerDataByIds(_merge3DExplorerData(layoutData, baseData), payloadFilterIds);
    } catch (e) {
      console.warn("[Explorer] 3D layout request failed; using PCA fallback positions", e);
      return _filterExplorerDataByIds(baseData, payloadFilterIds);
    }
  }
  const data = await api(attractorUrl);
  _cachedExplorerAttractorData = data;
  _cachedExplorerAttractorDataIncludesHidden = includeHidden;
  return _filterExplorerDataByIds(data, payloadFilterIds);
}

function _resetExplorerViewInstance(impl = _ExplorerImpl) {
  if (impl && explorerLoaded && typeof impl.destroy === "function") {
    impl.destroy();
  }
  const container = document.getElementById("explorerContainer");
  if (container) container.innerHTML = "";
  explorerLoaded = false;
  explorerData = null;
  _explorerPayloadIncludesHidden = false;
  _explorerPayloadFilterKey = "";
}

async function clearExplorerInternalFilter() {
  _explorerInternalFilterIds = null;
  _setExplorerModeChipOverride("Returning to iPad 2D lite full map...");
  await _ensureMobileExplorerModeForFilterIds(null);
  _setExplorerModeChipOverride("");
  updateStats();
}

function setViewMode(mode, options = {}) {
  const { persist = true } = options;
  if (mode === "explorer" && isReviewModeActive()) {
    Shared.showToast("Exit review mode before opening 3D Explorer.", { type: "info", duration: 3000 });
    return;
  }
  if (mode === "explorer" && state.canvasCollectionBuild) {
    exitCollectionBuild();
    Shared.showToast("Collection selection closed before opening 3D Explorer.", { type: "info", duration: 3000 });
  }
  const browseView = $("#browseView");
  const explorerView = $("#explorerView");
  const sidebarEl = $("aside.sidebar");
  const layoutEl = $(".layout");

  if (mode === "explorer") {
    state.view = "explorer";
    if (browseView) browseView.hidden = true;
    if (explorerView) explorerView.hidden = false;
    if (layoutEl) layoutEl.classList.add("explorer-active");
    if (viewGridBtn) viewGridBtn.classList.remove("active");
    if (viewExplorerBtn) viewExplorerBtn.classList.add("active");
    _writeViewModeToUrl("explorer");
    if (persist) _writeViewModePref("explorer");
    updateStats();
    loadExplorerView();
  } else {
    state.view = "browse";
    if (browseView) browseView.hidden = false;
    if (explorerView) explorerView.hidden = true;
    if (layoutEl) layoutEl.classList.remove("explorer-active");
    if (viewGridBtn) viewGridBtn.classList.add("active");
    if (viewExplorerBtn) viewExplorerBtn.classList.remove("active");
    _writeViewModeToUrl("grid");
    if (persist) _writeViewModePref("grid");
    updateStats();
    if (_ExplorerImpl && explorerLoaded) {
      _ExplorerImpl.pause();
    }
  }
}

async function loadExplorerView({ allow2DFallback = true, forceMode = null, payloadFilterIds = null } = {}) {
  // Load 3D code lazily when explorer is opened.
  // This avoids paying Three.js startup cost when the user stays in grid mode.
  if (forceMode === "3d" || !_isExplorerMobileConstrained()) {
    await _ensureExplorer3DLoaded();
  }

  const nextExplorer = _resolveExplorerImpl(forceMode);
  const nextImpl = nextExplorer.impl;
  const previousImpl = _ExplorerImpl;
  const implChanged = explorerLoaded && previousImpl && previousImpl !== nextImpl;
  if (implChanged) _resetExplorerViewInstance(previousImpl);
  _ExplorerImpl = nextImpl;
  _explorerMode = nextExplorer.mode;

  if (!_ExplorerImpl || typeof _ExplorerImpl.init !== "function") {
    Shared.showToast("Explorer not available", { type: "error", duration: 3000 });
    return;
  }

  if (!explorerLoaded) {
    _ExplorerImpl.init("explorerContainer");
    _ExplorerImpl.onClickNode(async (nodeId) => {
      // Try local cache first, then fetch from server
      let asset = state.assets.find((a) => a.id === nodeId);
      if (!asset) {
        asset = await fetchAssetForModal(nodeId);
      }
      if (asset) openModal(asset);
    });
    if (typeof _ExplorerImpl.onSelect === "function") {
      _ExplorerImpl.onSelect((nodeIds, meta = {}) => {
        _handleExplorerInternalSelection(nodeIds, meta);
      });
    }
    explorerLoaded = true;
  } else {
    if (typeof _ExplorerImpl.pause === "function") _ExplorerImpl.pause();
  }

  // Load data from appropriate endpoint
  const busyMessage = _explorerMode === "3d"
    ? "Building your 3D map…"
    : "Loading your map…";
  _beginExplorerBusy(busyMessage);
  try {
    await _nextPaint();
    const includeHidden = _shouldExplorerIncludeHiddenData();
    _setExplorerBusyOverlay(true, _explorerMode === "3d" ? "Fetching your 3D map…" : "Fetching your map…");
    Shared.showToast(`Loading ${_explorerMode.toUpperCase()} attractor map…`, { type: "info", duration: 2000 });
    const data = await _loadExplorerPayload(_explorerMode, includeHidden, payloadFilterIds);
    _setExplorerBusyOverlay(true, _explorerMode === "3d" ? "Arranging your 3D tiles…" : "Arranging your map…");
    await _nextPaint();
    explorerData = data;
    _explorerPayloadIncludesHidden = includeHidden;
    _explorerPayloadFilterKey = _filterKeyFromIds(payloadFilterIds);
    _explorerFilterCount = Array.isArray(data?.assets) ? data.assets.length : null;
    _ExplorerImpl.loadData(data, { deferSettle: _explorerMode === "3d" });
    if (typeof _ExplorerImpl.resume === "function") _ExplorerImpl.resume();
    syncExplorerFilter();   // apply any active grid filters as dim
    updateStats();
  } catch (e) {
    const canFallbackTo2D =
      allow2DFallback &&
      _explorerMode === "3d" &&
      !!_Explorer2D &&
      _Explorer2D !== _ExplorerImpl;
    if (canFallbackTo2D) {
      console.warn("[Explorer] 3D failed; switching to 2D lite fallback", e);
      _disable3DForSession = true;
      Shared.showToast("3D unavailable, switched to 2D lite mode.", { type: "warning", duration: 3000 });
      _resetExplorerViewInstance();
      await loadExplorerView({ allow2DFallback: false });
      return;
    }
    Shared.showToast(`Explorer: ${formatApiError(e)}`, { type: "error" });
  } finally {
    await _endExplorerBusy();
  }
}

if (viewGridBtn) viewGridBtn.addEventListener("click", () => setViewMode("grid", { persist: true }));
if (viewExplorerBtn) viewExplorerBtn.addEventListener("click", () => setViewMode("explorer", { persist: true }));
if (explorerModeChip) {
  explorerModeChip.addEventListener("click", () => {
    if (_explorerInternalFilterIds && _explorerInternalFilterIds.length) clearExplorerInternalFilter();
  });
}

let _explorerTextFilterTimer = 0;
window.addEventListener("inspirations:explorer-text-filter", (event) => {
  const term = String(event?.detail?.term || "").trim();
  window.clearTimeout(_explorerTextFilterTimer);
  _explorerTextFilterTimer = window.setTimeout(() => {
    if (state.q === term && !state.chatPrompt && !state.chatItemIds) return;
    state.q = term;
    state.chatPrompt = "";
    state.chatItemIds = null;
    updateFilterIndicator();
    loadAssets();
  }, 260);
});

// ─── Explorer ↔ filter sync ──────────────────────────────────────────────────────

let _explorerFilterSeq = 0;

function _hasActiveFilters() {
  return !!(
    state.triageFilter ||
    state.currentSource ||
    state.currentBoard ||
    hasClassificationFilter() ||
    hasCollectionFilter() ||
    hasCatalogFilter() ||
    state.chatItemIds ||
    (state.q && state.q.trim())
  );
}

async function _ensureMobileExplorerModeForFilterIds(ids) {
  if (!_isExplorerMobileConstrained() || _explorerModeReloading) return false;
  const count = Array.isArray(ids) ? ids.length : 0;
  const budget = await _getExplorerMobile3DBudget();
  const canUseFiltered3D = _canUseMobile3DForCount(count, budget);
  const nextMode = canUseFiltered3D ? "3d" : "2d";
  const nextKey = canUseFiltered3D ? _filterKeyFromIds(ids) : "";
  if (_explorerMode === nextMode && _explorerPayloadFilterKey === nextKey) return false;

  _explorerModeReloading = true;
  try {
    _setExplorerModeChipOverride(canUseFiltered3D
      ? `Switching to 3D subset: ${count} item${count === 1 ? "" : "s"}...`
      : (count > 0
        ? `Using 2D lite: ${count} items exceeds this iPad's 3D budget (${budget.nodeLimit})...`
        : "Returning to iPad 2D lite full map..."));
    await loadExplorerView({
      forceMode: nextMode,
      payloadFilterIds: canUseFiltered3D ? ids : null,
    });
  } finally {
    _setExplorerModeChipOverride("");
    _explorerModeReloading = false;
  }
  return true;
}

async function _handleExplorerInternalSelection(nodeIds, meta = {}) {
  if (!_isExplorerMobileConstrained() || _explorerModeReloading) return;
  if (!Array.isArray(nodeIds)) return;
  const categoryMode = String(meta.categoryMode || "");
  const hasInternalAttractor =
    categoryMode !== "group" &&
    Array.isArray(meta.activeAttractors) &&
    meta.activeAttractors.length > 0;
  _explorerInternalFilterIds = hasInternalAttractor ? nodeIds.slice() : null;
  const count = nodeIds.length;
  _explorerFilterCount = count;
  _setExplorerModeChipOverride("");
  updateStats();
  await _ensureMobileExplorerModeForFilterIds(nodeIds);
  _setExplorerModeChipOverride("");
  updateStats();
}

async function syncExplorerFilter() {
  if (!_ExplorerImpl || !explorerLoaded) return;
  const explorerActive = state.view === "explorer" && !$("#explorerView")?.hidden;
  if (explorerActive) {
    _beginExplorerBusy("Updating your map…");
    if (typeof _ExplorerImpl.pause === "function") _ExplorerImpl.pause();
    await _nextPaint();
  }

  try {

    // Sync header search text into explorer's local title search
    if (typeof _ExplorerImpl.setSearch === "function") {
      _ExplorerImpl.setSearch(state.q || "");
    }

    // Hidden data is loaded only for owner hidden view.
    const wantsHiddenPayload = _shouldExplorerIncludeHiddenData();
    if (_explorerPayloadIncludesHidden !== wantsHiddenPayload) {
      if (_explorerScopeReloading) return;
      _explorerScopeReloading = true;
      try {
        await loadExplorerView();
      } finally {
        _explorerScopeReloading = false;
      }
      return;
    }

    // No filters → show everything
    if (!_hasActiveFilters()) {
      if (_explorerInternalFilterIds && _explorerInternalFilterIds.length) {
        if (await _ensureMobileExplorerModeForFilterIds(_explorerInternalFilterIds)) return;
        _ExplorerImpl.setFilter(_explorerInternalFilterIds);
        _explorerFilterCount = _explorerInternalFilterIds.length;
        updateStats();
        return;
      }
      if (await _ensureMobileExplorerModeForFilterIds(null)) return;
      _ExplorerImpl.setFilter(null);
      _explorerFilterCount = Array.isArray(explorerData?.assets) ? explorerData.assets.length : null;
      updateStats();
      return;
    }

    // Chat-curated items: highlight only those IDs
    if (state.chatItemIds) {
      if (await _ensureMobileExplorerModeForFilterIds(state.chatItemIds)) return;
      _ExplorerImpl.setFilter(state.chatItemIds);
      _explorerFilterCount = state.chatItemIds.length;
      updateStats();
      return;
    }

    const catalogFiles = getCatalogFilterFiles();
    if (catalogFiles.length) {
      const catalogParams = new URLSearchParams();
      for (const file of catalogFiles) catalogParams.append("file", file);
      appendShowDiscardedParam(catalogParams);
      appendUsableTrackExclusionParam(catalogParams);
      const seq = ++_explorerFilterSeq;
      try {
        const data = await api(`/api/catalog/asset-ids?${catalogParams}`);
        if (seq !== _explorerFilterSeq) return; // stale
        if (await _ensureMobileExplorerModeForFilterIds(data.ids || [])) return;
        _ExplorerImpl.setFilter(data.ids || []);
        _explorerFilterCount = Array.isArray(data.ids) ? data.ids.length : 0;
        updateStats();
      } catch (e) {
        // Silently ignore — filter dim is a nice-to-have
      }
      return;
    }

    // Build the same filter params the grid uses
    const params = new URLSearchParams();
    if (state.q && state.q.trim()) params.set("q", state.q.trim());
    if (state.currentSource) params.set("source", state.currentSource);
    if (state.currentBoard) params.set("board", state.currentBoard);
    if (state.currentContentKind) params.set("content_kind", state.currentContentKind);
    appendClassificationFacetParams(params);
    const collectionIds = getCollectionFilterIds();
    if (collectionIds.length) params.set("collection_id", collectionIds.join(","));
    appendReviewScopeParams(params, { includeHiddenForOwner: _shouldExplorerIncludeHiddenData() });
    appendShowDiscardedParam(params);
    appendUsableTrackExclusionParam(params);

    const seq = ++_explorerFilterSeq;
    try {
      const data = await api(`/api/asset-ids?${params}`);
      if (seq !== _explorerFilterSeq) return; // stale
      if (await _ensureMobileExplorerModeForFilterIds(data.ids || [])) return;
      _ExplorerImpl.setFilter(data.ids || []);
      _explorerFilterCount = Array.isArray(data.ids) ? data.ids.length : 0;
      updateStats();
    } catch (e) {
      // Silently ignore — filter dim is a nice-to-have
    }
  } finally {
    if (explorerActive) {
      if (typeof _ExplorerImpl.resume === "function") _ExplorerImpl.resume();
      await _endExplorerBusy();
    }
  }
}

// ─── Filter indicator ────────────────────────────────────────────────────────────

function clearAllActiveFilters() {
  state.q = "";
  state.semanticMode = false;
  state.chatPrompt = "";
  state.chatItemIds = null;
  state.currentSource = null;
  state.currentBoard = null;
  state.currentContentKind = null;
  state.currentTreeNodeId = null;
  state.offset = 0;
  state.showDiscarded = false;
  resetTriageFilter();
  clearCatalogFilter();
  clearClassificationFilter();
  clearCollectionFilter();
  renderCatalogTree();
  updateFilterIndicator();
  loadAssets();
}

function updateFilterIndicator() {
  const bar = $("#filterSummary");
  const text = $("#filterSummaryText");
  const clearBtn = $("#clearFilterSummary");
  if (!bar || !text) return;

  const davePrompt = String(state.chatPrompt || "").trim();
  const parts = [];
  const catalogFiles = getCatalogFilterFiles();
  const collectionIds = getCollectionFilterIds();

  if (!davePrompt && state.semanticMode) {
    const semQ = semanticQueryFromInput(state.q);
    parts.push(`Semantic search: "${semQ}"`);
  } else if (!davePrompt && state.q && state.q.trim()) {
    parts.push(`"${state.q.trim()}"`);
  }
  if (state.currentSource && !catalogFiles.length && !collectionIds.length) {
    parts.push(`Source: ${sourceDisplayName(state.currentSource) || state.currentSource}`);
  }
  if (state.currentContentKind && !catalogFiles.length && !collectionIds.length) {
    const kindLabel = _ingestTagDisplayLabel(state.currentContentKind);
    parts.push(`Type: ${kindLabel}`);
  }
  if (state.currentBoard && !catalogFiles.length && !collectionIds.length) {
    parts.push(`Board: ${state.currentBoard}`);
  }
  if (catalogFiles.length) {
    let catalogLabel = state.currentCatalogLabel || "";
    if (!catalogLabel && catalogFiles.length === 1) {
      catalogLabel = catalogFiles[0].split("/").pop().replace(".md", "").replace(/_/g, " ");
    } else if (!catalogLabel) {
      catalogLabel = `${catalogFiles.length} folders`;
    }
    parts.push(`Catalog: ${catalogLabel}`);
  }
  if (hasClassificationFilter()) {
    const facetLabels = getClassificationFacetEntries()
      .map((entry) => classificationFacetLabel(entry.axis, entry.value))
      .filter(Boolean);
    const visible = facetLabels.slice(0, 4).join(", ");
    const extra = Math.max(0, facetLabels.length - 4);
    const fallback = String(
      state.currentClassificationLabel
      || state.currentClassificationValue
      || state.currentClassificationAxis
      || ""
    ).trim();
    parts.push(`Refine: ${visible || fallback}${extra ? ` +${extra}` : ""}`);
  }
  if (collectionIds.length) {
    if (collectionIds.length === 1) {
      const cid = collectionIds[0];
      const col = state.collections.find((c) => c.id === cid);
      parts.push(`Collection: ${col ? col.name : cid.slice(0, 8)}`);
    } else {
      parts.push(`Collections: ${state.currentCollectionLabel || `${collectionIds.length} folders`}`);
    }
  }
  if (state.triageFilter) {
    const labels = { pending: "Pending", keeper: "Keepers", hidden: "Discarded", "hidden-manual": "Discarded manually", "hidden-ai": "Discarded by AI cleanup", "needs-comment": "Needs comment", flagged: "Flagged", "irrelevant-discarded": "Irrelevant / Discarded" };
    parts.push(`Status: ${labels[state.triageFilter] || state.triageFilter}`);
  }
  if (state.showDiscarded) parts.push("Status: All items, including discarded");

  updateReviewScopeChips();
  if (!davePrompt && parts.length === 0) {
    bar.hidden = true;
    if (clearBtn) {
      clearBtn.hidden = true;
      clearBtn.disabled = true;
    }
    return;
  }
  if (davePrompt) {
    text.textContent = parts.length
      ? `Filtered by Dave: "${davePrompt}" • ${parts.join(" • ")}`
      : `Filtered by Dave: "${davePrompt}"`;
    if (clearBtn) {
      clearBtn.hidden = false;
      clearBtn.disabled = false;
    }
  } else {
    text.textContent = `Results filtered by: ${parts.join(" • ")}`;
    if (clearBtn) {
      clearBtn.hidden = false;
      clearBtn.disabled = false;
    }
  }
  bar.hidden = false;
}

const clearFilterBtn = $("#clearFilterSummary");
if (clearFilterBtn) clearFilterBtn.addEventListener("click", () => {
  clearAllActiveFilters();
});

// ─── Search (driven entirely via Ask Dave now) ──────────────────────────────────

const canvasTextFilter = $("#canvasTextFilter");
let _canvasTextFilterTimer = 0;
if (canvasTextFilter) {
  canvasTextFilter.addEventListener("input", (event) => {
    const term = String(event.target.value || "").trim();
    window.clearTimeout(_canvasTextFilterTimer);
    _canvasTextFilterTimer = window.setTimeout(() => {
      state.q = term;
      state.chatPrompt = "";
      state.chatItemIds = null;
      updateFilterIndicator();
      loadAssets();
    }, 260);
  });
}

// ─── Load More ───────────────────────────────────────────────────────────────────

const loadMoreBtn = $("#loadMore");
if (loadMoreBtn) loadMoreBtn.addEventListener("click", () => loadAssets({ append: true }));
const contentScroller = $(".content");
if (contentScroller) contentScroller.addEventListener("scroll", scheduleAutoLoadMore, { passive: true });
window.addEventListener("scroll", scheduleAutoLoadMore, { passive: true });
window.addEventListener("resize", scheduleAutoLoadMore);
setupAutoLoadMoreObservers();

// ─── Media import ───────────────────────────────────────────────────────────────

function isAnyImportBusy() {
  return !!(state.scanImportBusy || state.photoImportBusy || state.videoImportBusy);
}

function openMediaImportModal() { $("#mediaImportModal")?.classList.remove("hidden"); }
function closeMediaImportModal() { $("#mediaImportModal")?.classList.add("hidden"); }

function setAddMediaButtonState() {
  const btn = $("#addMedia");
  if (!btn) return;
  btn.disabled = isAnyImportBusy();
  btn.textContent = isAnyImportBusy() ? "Importing…" : "Add Media";
}

function openScanImportModal() { $("#scanImportModal")?.classList.remove("hidden"); }
function closeScanImportModal() { $("#scanImportModal")?.classList.add("hidden"); }
function openPhotoImportModal() { $("#photoImportModal")?.classList.remove("hidden"); }
function closePhotoImportModal() { $("#photoImportModal")?.classList.add("hidden"); }
function openVideoImportModal() { $("#videoImportModal")?.classList.remove("hidden"); }
function closeVideoImportModal() { $("#videoImportModal")?.classList.add("hidden"); }

function currentScanImportFile() {
  const input = $("#scanPdfInput");
  return state.scanImportFile || (input?.files?.[0]) || null;
}

function currentPhotoImportFile() {
  const input = $("#photoInput");
  return state.photoImportFile || (input?.files?.[0]) || null;
}

function currentVideoImportFile() {
  const input = $("#videoInput");
  return state.videoImportFile || (input?.files?.[0]) || null;
}

function setScanImportButtonState() {
  const runBtn = $("#runScanImport");
  if (runBtn) runBtn.disabled = isAnyImportBusy() || !currentScanImportFile();
}

function setPhotoImportButtonState() {
  const runBtn = $("#runPhotoImport");
  if (runBtn) runBtn.disabled = isAnyImportBusy() || !currentPhotoImportFile();
}

function setVideoImportButtonState() {
  const runBtn = $("#runVideoImport");
  if (runBtn) runBtn.disabled = isAnyImportBusy() || !currentVideoImportFile();
}

function refreshImportButtonStates() {
  setAddMediaButtonState();
  setScanImportButtonState();
  setPhotoImportButtonState();
  setVideoImportButtonState();
}

function resetScanImportModal() {
  const input = $("#scanPdfInput");
  setSingleFileSelection(input, null, "scanImportFile");
  const titleInput = $("#scanImportTitleInput");
  if (titleInput) titleInput.value = "";
  const tagsInput = $("#scanImportTagsInput");
  if (tagsInput) tagsInput.value = "";
  const parser = $("#scanUseFormParser");
  if (parser) parser.checked = false;
  const delimiters = $("#scanDetectDelimiters");
  if (delimiters) delimiters.checked = true;
  const dropZone = $("#scanDropZone");
  if (dropZone) dropZone.classList.remove("dragActive");
  renderIngestTagChips("scanImportTagsInput", "scanImportTagChips");
  setScanImportButtonState();
}

function resetPhotoImportModal() {
  const input = $("#photoInput");
  setSingleFileSelection(input, null, "photoImportFile");
  const titleInput = $("#photoImportTitleInput");
  if (titleInput) titleInput.value = "";
  const tagsInput = $("#photoImportTagsInput");
  if (tagsInput) tagsInput.value = "";
  const dropZone = $("#photoDropZone");
  if (dropZone) dropZone.classList.remove("dragActive");
  renderIngestTagChips("photoImportTagsInput", "photoImportTagChips");
  setPhotoImportButtonState();
}

function resetVideoImportModal() {
  const input = $("#videoInput");
  setSingleFileSelection(input, null, "videoImportFile");
  const titleInput = $("#videoImportTitleInput");
  if (titleInput) titleInput.value = "";
  const tagsInput = $("#videoImportTagsInput");
  if (tagsInput) tagsInput.value = "";
  const dropZone = $("#videoDropZone");
  if (dropZone) dropZone.classList.remove("dragActive");
  renderIngestTagChips("videoImportTagsInput", "videoImportTagChips");
  setVideoImportButtonState();
}

async function importScanPdf(file, opts = {}) {
  if (!file) return;
  if (!isPdfFile(file)) { Shared.showToast("Please choose a PDF file.", { type: "error" }); return; }
  const name = file.name || "";
  const useFormParser = !!opts.useFormParser;
  const detectDelimiters = opts.detectDelimiters !== false;
  const title = String(opts.title || "").trim();
  const tags = parseTagInput(opts.tags || "").join(", ");
  state.scanImportBusy = true;
  refreshImportButtonStates();
  const narrative = $("#canvasNarrative");
  if (narrative) narrative.textContent = `Importing "${name}"…`;
  try {
    const formData = new FormData();
    formData.append("file", file, name);
    formData.append("use_form_parser", useFormParser ? "1" : "0");
    formData.append("split_on_delimiters", detectDelimiters ? "1" : "0");
    if (title) formData.append("title", title);
    if (tags) formData.append("tags", tags);
    const payload = await apiUpload("/api/import/scans", formData);
    const report = payload.import || {};
    const created = Number(report.created_assets || 0);
    await loadFacets();
    await loadAssets();
    Shared.showToast(`Imported ${created} clip page${created === 1 ? "" : "s"} from "${name}".`, { type: "success" });
    Shared.showToast("New items may take a few seconds to appear in the tree.", { type: "info", duration: 4500 });
    closeScanImportModal();
  } catch (e) {
    Shared.showToast(`Clip import failed: ${formatApiError(e)}`, { type: "error", duration: 8000 });
  } finally {
    state.scanImportBusy = false;
    refreshImportButtonStates();
    setSingleFileSelection($("#scanPdfInput"), null, "scanImportFile");
    if (narrative) narrative.textContent = "";
  }
}

async function importPhoto(file, opts = {}) {
  if (!file) return;
  const name = file.name || "";
  const title = String(opts.title || "").trim();
  const tags = parseTagInput(opts.tags || "").join(", ");
  if (!isImageFile(file)) { Shared.showToast("Please choose an image file.", { type: "error" }); return; }
  state.photoImportBusy = true;
  refreshImportButtonStates();
  const narrative = $("#canvasNarrative");
  if (narrative) narrative.textContent = `Importing "${name}"…`;
  try {
    const formData = new FormData();
    formData.append("file", file, name);
    if (title) formData.append("title", title);
    if (tags) formData.append("tags", tags);
    const payload = await apiUpload("/api/import/photos", formData);
    const report = payload.import || {};
    const created = Number(report.created_assets || 0);
    await loadFacets();
    await loadAssets();
    Shared.showToast(`Imported ${created} photo${created === 1 ? "" : "s"} from "${name}".`, { type: "success" });
    Shared.showToast("New items may take a few seconds to appear in the tree.", { type: "info", duration: 4500 });
    closePhotoImportModal();
  } catch (e) {
    Shared.showToast(`Photo import failed: ${formatApiError(e)}`, { type: "error", duration: 8000 });
  } finally {
    state.photoImportBusy = false;
    refreshImportButtonStates();
    setSingleFileSelection($("#photoInput"), null, "photoImportFile");
    if (narrative) narrative.textContent = "";
  }
}

async function importVideo(file, opts = {}) {
  if (!file) return;
  const name = file.name || "";
  const title = String(opts.title || "").trim();
  const tags = parseTagInput(opts.tags || "").join(", ");
  if (!isVideoFile(file)) { Shared.showToast("Please choose a video file.", { type: "error" }); return; }
  state.videoImportBusy = true;
  refreshImportButtonStates();
  const narrative = $("#canvasNarrative");
  if (narrative) narrative.textContent = `Importing "${name}"…`;
  try {
    const formData = new FormData();
    formData.append("file", file, name);
    if (title) formData.append("title", title);
    if (tags) formData.append("tags", tags);
    const payload = await apiUpload("/api/import/videos", formData);
    const report = payload.import || {};
    const created = Number(report.created_assets || 0);
    await loadFacets();
    await loadAssets();
    Shared.showToast(`Imported ${created} video${created === 1 ? "" : "s"} from "${name}".`, { type: "success" });
    Shared.showToast("New items may take a few seconds to appear in the tree.", { type: "info", duration: 4500 });
    closeVideoImportModal();
  } catch (e) {
    Shared.showToast(`Video import failed: ${formatApiError(e)}`, { type: "error", duration: 8000 });
  } finally {
    state.videoImportBusy = false;
    refreshImportButtonStates();
    setSingleFileSelection($("#videoInput"), null, "videoImportFile");
    if (narrative) narrative.textContent = "";
  }
}

const addMediaBtn = $("#addMedia");
const closeMediaImportBtn = $("#closeMediaImport");
const openClipImportBtn = $("#openClipImport");
const openPhotoImportBtn = $("#openPhotoImport");
const openVideoImportBtn = $("#openVideoImport");

const scanPdfInput = $("#scanPdfInput");
const scanDropZone = $("#scanDropZone");
const runScanImportBtn = $("#runScanImport");
const cancelScanImportBtn = $("#cancelScanImport");
const closeScanImportBtn = $("#closeScanImport");

const photoInput = $("#photoInput");
const photoDropZone = $("#photoDropZone");
const runPhotoImportBtn = $("#runPhotoImport");
const cancelPhotoImportBtn = $("#cancelPhotoImport");
const closePhotoImportBtn = $("#closePhotoImport");

const videoInput = $("#videoInput");
const videoDropZone = $("#videoDropZone");
const runVideoImportBtn = $("#runVideoImport");
const cancelVideoImportBtn = $("#cancelVideoImport");
const closeVideoImportBtn = $("#closeVideoImport");

for (const [inputId, chipsId] of [
  ["scanImportTagsInput", "scanImportTagChips"],
  ["photoImportTagsInput", "photoImportTagChips"],
  ["videoImportTagsInput", "videoImportTagChips"],
]) {
  const input = document.getElementById(inputId);
  if (!input) continue;
  input.addEventListener("input", () => renderIngestTagChips(inputId, chipsId));
}

if (addMediaBtn) {
  addMediaBtn.onclick = () => {
    if (!isAnyImportBusy()) openMediaImportModal();
  };
}
if (closeMediaImportBtn) {
  closeMediaImportBtn.onclick = () => {
    if (!isAnyImportBusy()) closeMediaImportModal();
  };
}
if (openClipImportBtn) {
  openClipImportBtn.onclick = () => {
    if (isAnyImportBusy()) return;
    closeMediaImportModal();
    resetScanImportModal();
    openScanImportModal();
  };
}
if (openPhotoImportBtn) {
  openPhotoImportBtn.onclick = () => {
    if (isAnyImportBusy()) return;
    closeMediaImportModal();
    resetPhotoImportModal();
    openPhotoImportModal();
  };
}
if (openVideoImportBtn) {
  openVideoImportBtn.onclick = () => {
    if (isAnyImportBusy()) return;
    closeMediaImportModal();
    resetVideoImportModal();
    openVideoImportModal();
  };
}

if (scanPdfInput) {
  scanPdfInput.addEventListener("change", () => {
    const file = scanPdfInput.files?.[0] || null;
    if (file && !isPdfFile(file)) {
      Shared.showToast("Please choose a PDF file.", { type: "error" });
      setSingleFileSelection(scanPdfInput, null, "scanImportFile");
      setScanImportButtonState();
      return;
    }
    state.scanImportFile = file || null;
    setScanImportButtonState();
  });
}
if (scanDropZone) {
  wireSingleFileDropZone({
    zone: scanDropZone,
    input: scanPdfInput,
    stateKey: "scanImportFile",
    accept: isPdfFile,
    invalidMessage: "Please drop a PDF file.",
    isBusy: () => isAnyImportBusy(),
    onSelected: () => setScanImportButtonState(),
  });
}
if (runScanImportBtn) {
  runScanImportBtn.addEventListener("click", async () => {
    if (isAnyImportBusy()) return;
    const file = currentScanImportFile();
    const useFormParser = !!($("#scanUseFormParser")?.checked);
    const detectDelimiters = !!($("#scanDetectDelimiters")?.checked);
    const title = String($("#scanImportTitleInput")?.value || "").trim();
    const tags = String($("#scanImportTagsInput")?.value || "").trim();
    await importScanPdf(file, { useFormParser, detectDelimiters, title, tags });
  });
}
if (cancelScanImportBtn) cancelScanImportBtn.onclick = () => { if (!state.scanImportBusy) { closeScanImportModal(); resetScanImportModal(); } };
if (closeScanImportBtn) closeScanImportBtn.onclick = () => { if (!state.scanImportBusy) { closeScanImportModal(); resetScanImportModal(); } };

if (photoInput) {
  photoInput.addEventListener("change", () => {
    const file = photoInput.files?.[0] || null;
    if (file && !isImageFile(file)) {
      Shared.showToast("Please choose an image file.", { type: "error" });
      setSingleFileSelection(photoInput, null, "photoImportFile");
      setPhotoImportButtonState();
      return;
    }
    state.photoImportFile = file || null;
    setPhotoImportButtonState();
  });
}
if (photoDropZone) {
  wireSingleFileDropZone({
    zone: photoDropZone,
    input: photoInput,
    stateKey: "photoImportFile",
    accept: isImageFile,
    invalidMessage: "Please drop an image file.",
    isBusy: () => isAnyImportBusy(),
    onSelected: () => setPhotoImportButtonState(),
  });
}
if (runPhotoImportBtn) {
  runPhotoImportBtn.addEventListener("click", async () => {
    if (isAnyImportBusy()) return;
    const title = String($("#photoImportTitleInput")?.value || "").trim();
    const tags = String($("#photoImportTagsInput")?.value || "").trim();
    await importPhoto(currentPhotoImportFile(), { title, tags });
  });
}
if (cancelPhotoImportBtn) cancelPhotoImportBtn.onclick = () => { if (!state.photoImportBusy) { closePhotoImportModal(); resetPhotoImportModal(); } };
if (closePhotoImportBtn) closePhotoImportBtn.onclick = () => { if (!state.photoImportBusy) { closePhotoImportModal(); resetPhotoImportModal(); } };

if (videoInput) {
  videoInput.addEventListener("change", () => {
    const file = videoInput.files?.[0] || null;
    if (file && !isVideoFile(file)) {
      Shared.showToast("Please choose a video file.", { type: "error" });
      setSingleFileSelection(videoInput, null, "videoImportFile");
      setVideoImportButtonState();
      return;
    }
    state.videoImportFile = file || null;
    setVideoImportButtonState();
  });
}
if (videoDropZone) {
  wireSingleFileDropZone({
    zone: videoDropZone,
    input: videoInput,
    stateKey: "videoImportFile",
    accept: isVideoFile,
    invalidMessage: "Please drop a video file.",
    isBusy: () => isAnyImportBusy(),
    onSelected: () => setVideoImportButtonState(),
  });
}
if (runVideoImportBtn) {
  runVideoImportBtn.addEventListener("click", async () => {
    if (isAnyImportBusy()) return;
    const title = String($("#videoImportTitleInput")?.value || "").trim();
    const tags = String($("#videoImportTagsInput")?.value || "").trim();
    await importVideo(currentVideoImportFile(), { title, tags });
  });
}
if (cancelVideoImportBtn) cancelVideoImportBtn.onclick = () => { if (!state.videoImportBusy) { closeVideoImportModal(); resetVideoImportModal(); } };
if (closeVideoImportBtn) closeVideoImportBtn.onclick = () => { if (!state.videoImportBusy) { closeVideoImportModal(); resetVideoImportModal(); } };

refreshImportButtonStates();
refreshIngestTagPickers();

// ─── Init ─────────────────────────────────────────────────────────────────────────

wireSidebarToggle();
wireSidebarResize();

function isOwner() {
  return true;
}

function canUseFlag() {
  return isOwner();
}

function canUseTag() {
  // Tag workflow retired.
  return false;
}

function isReviewModeActive() {
  return state.view === "review" || !!state.canvasReview;
}

function isModalAdvancedEditingEnabled() {
  return isOwner() && !!state.modalAdvancedEditing;
}

function renderReviewSidebarSummary() {
  const section = $("#dynamicSidebarSection");
  const headingEl = $("#dynamicSidebarHeading");
  const content = $("#dynamicSidebarContent");
  if (!section || !headingEl || !content) return;
  const scope = getReviewScopeInfo();
  const modeLabel = state.view === "review" ? "One-by-one review" : "Grid review";
  headingEl.textContent = "Review";
  content.innerHTML = `
      <div class="review-sidebar-summary">
        <div class="review-sidebar-row"><span class="muted">Scope</span><strong>${escapeHtml(scope.label || "Entire library")}</strong></div>
        <div class="review-sidebar-row"><span class="muted">Mode</span><strong>${escapeHtml(modeLabel)}</strong></div>
      <div class="review-sidebar-note muted">Use Keepers, Flagged, or Discarded to revisit decisions in this scope. Card clicks open advanced details; use checkboxes for bulk actions or One-by-one for fast triage.</div>
    </div>
  `;
  section.hidden = false;
}

function renderSharedSessionSidebarSummary() {
  const section = $("#dynamicSidebarSection");
  const headingEl = $("#dynamicSidebarHeading");
  const content = $("#dynamicSidebarContent");
  if (!section || !headingEl || !content) return;
  const collectionId = _activeSharedCollectionLandingId();
  const collection = (state.collections || []).find((row) => String(row?.id || "") === collectionId) || null;
  const collectionName = String(collection?.name || state.currentCollectionLabel || "Shared collection");
  const collectionDescription = String(collection?.description || "").trim();
  const itemCount = Number(collection?.count || 0);
  const actorName = String(state.actor?.name || "Collaborator");
  headingEl.textContent = "Session";
  content.innerHTML = `
    <div class="shared-session-card">
      <div class="shared-session-kicker">Viewing as</div>
      <div class="shared-session-actor">${escapeHtml(actorName)}</div>
      <div class="shared-session-collection">${escapeHtml(collectionName)}</div>
      <div class="shared-session-meta">${itemCount} item${itemCount === 1 ? "" : "s"}</div>
      ${collectionDescription ? `<div class="shared-session-description">${escapeHtml(collectionDescription)}</div>` : ""}
      <div class="shared-session-note">Legacy shared-session mode is retired; use Export Collection PDF for designer handoff.</div>
      <button id="sharedSessionRevealBtn" class="collection-shared-focus-action" type="button">Show all collections</button>
    </div>
  `;
  const btn = $("#sharedSessionRevealBtn");
  if (btn) {
    btn.addEventListener("click", () => {
      state.sharedCollectionLandingId = "";
      renderCatalogTree();
      updateSidebarModeVisibility();
    });
  }
  section.hidden = false;
}

function updateSidebarModeVisibility() {
  const owner = isOwner();
  const inReview = owner && isReviewModeActive();
  const focusedShared = _isFocusedSharedCollectionSession();
  const layout = $(".layout");
  const sidebar = $(".sidebar");
  const treeSection = $("#catalogTree")?.closest(".sidebar-section");
  const collectionsSection = $("#collectionTree")?.closest(".sidebar-section");
  const collectionActionsSection = $("#manageCollections")?.closest(".sidebar-section");
  const collectionsHeading = $("#collectionSidebarSection .sidebar-heading");

  if (treeSection) treeSection.hidden = inReview || focusedShared;
  if (collectionsSection) collectionsSection.hidden = inReview;
  if (collectionActionsSection) collectionActionsSection.hidden = inReview;
  if (collectionsHeading) collectionsHeading.textContent = focusedShared ? "Shared Collection" : "Collections";
  if (layout) layout.classList.toggle("shared-session-active", focusedShared);
  if (sidebar) sidebar.classList.toggle("shared-session-sidebar", focusedShared);
  if (collectionsSection) collectionsSection.classList.toggle("shared-session-collections", focusedShared);

  if (inReview) {
    renderReviewSidebarSummary();
  } else if (focusedShared) {
    renderSharedSessionSidebarSummary();
  } else {
    hideDynamicSidebar();
  }
}

function applyRoleVisibility() {
  const owner = isOwner();
  const role = String(state.actor?.role || "").trim().toLowerCase();
  if (document.documentElement) {
    if (role) document.documentElement.dataset.actorRole = role;
    else delete document.documentElement.dataset.actorRole;
  }
  if (state.allItemsTreeCollapsed === null) {
    state.allItemsTreeCollapsed = !!(state.actor && !owner);
  }

  // Review button, import buttons, admin link — owner-only
  const reviewBtnEl = $("#reviewBtn");
  if (reviewBtnEl) reviewBtnEl.hidden = !owner;
  const collectionBuildBtnEl = $("#collectionBuildBtn");
  if (collectionBuildBtnEl) collectionBuildBtnEl.hidden = !owner;
  const addMediaEl = $("#addMedia");
  if (addMediaEl) addMediaEl.hidden = !owner;
  const adminEl = $(".adminLink");
  if (adminEl) adminEl.hidden = !owner;
  syncCollectionPdfExportButton();
  const manageCollectionsEl = $("#manageCollections");
  if (manageCollectionsEl) manageCollectionsEl.hidden = !owner;

  const printBtn = document.getElementById("printAssetBtn");
  if (printBtn) printBtn.hidden = false;
  const shareGroup = $("#modalShareGroup");
  if (shareGroup) shareGroup.hidden = false;

  // Owner curation actions remain available in item detail; advanced repair panels are Review-scoped.
  const modalCurationGroup = $("#modalCurationGroup");
  if (modalCurationGroup) modalCurationGroup.hidden = !owner;

  const canvasFlagBtnEl = $("#canvasFlag");
  if (canvasFlagBtnEl) canvasFlagBtnEl.hidden = !canUseFlag();
  const canvasTagBtnEl = $("#canvasTag");
  if (canvasTagBtnEl) canvasTagBtnEl.hidden = !canUseTag();
  for (const id of ["reviewKeepBtn", "reviewHideLocalBtn", "reviewHideGlobalBtn", "reviewClearBtn"]) {
    const btn = document.getElementById(id);
    if (btn) btn.hidden = !owner;
  }
  const reviewFlagBtnEl = $("#reviewFlagBtn");
  if (reviewFlagBtnEl) reviewFlagBtnEl.hidden = !canUseFlag();

  // Notes and image annotations are local corpus-management tools.
  updateActorContextChips();
  updateReviewScopeChips();
  updateSidebarModeVisibility();
}

(async () => {
  try {
    state.actor = { id: "local-owner", name: "Jim", role: "owner" };

    // Apply role-based visibility before rendering
    applyRoleVisibility();

    const collectionsPromise = loadCollections();
    const facetsPromise = loadFacets();
    const catalogTreePromise = loadCatalogTree();
    await collectionsPromise;
    applyCollectionScopeFromUrl();
    _applyCollaboratorCollectionsDefaultScope();
    await loadAssets();
    await Promise.all([facetsPromise, catalogTreePromise]);
    const viewFromUrl = _readViewModeFromUrl();
    let preferredView = viewFromUrl || _readViewModePref();
    if (!viewFromUrl && isCollaboratorActor()) {
      preferredView = "grid";
    }
    if (preferredView === "explorer") {
      setViewMode("explorer", { persist: false });
    }
    await restoreDirectItemLinkFromUrl();

    // Owner-only local corpus tools.
    if (isOwner()) {
      loadHiddenTree();
    }
  } catch (e) {
    const grid = $("#grid");
    if (grid) grid.innerHTML = `<div class="empty-state">Unable to load: ${escapeHtml(formatApiError(e))}</div>`;
  }
})();
