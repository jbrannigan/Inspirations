// ─── State ─────────────────────────────────────────────────────────────────────
const state = {
  // Navigation
  view: "browse",               // "browse" | "review"
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
  currentTreeNodeId: null,      // active sidebar tree node ID
  triageFilter: "",             // "" | "pending" | "keeper" | "hidden" | "needs-comment"

  // Assets
  assets: [],
  hasMore: false,
  loadingAssets: false,
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

  // Imports
  scanImportBusy: false,
  photoImportBusy: false,
  videoImportBusy: false,
  scanImportFile: null,
  photoImportFile: null,
  videoImportFile: null,

  // Canvas review mode
  canvasReview: false,          // true when canvas review overlay is active
  canvasSelected: new Set(),    // set of selected asset IDs

  // Actor / collaboration
  actor: null,                  // { id, name, role, token } or null
  hiddenTree: null,             // hidden items tree for sidebar (owners only)
  expandedTreeNodes: new Set(), // track which tree nodes are expanded by user
  allItemsTreeCollapsed: null,  // collaborator default: collapse browse tree under "All Items"
  collaboratorTreeUnlocked: false, // collaborator default: hide broader tree until explicit browse
  collaboratorDefaultScopeApplied: false, // avoid re-applying collaborator default collection scope
  lastCollaboratorBrowseUnlockAt: 0, // guards accidental follow-up taps right after browse unlock
  openQuestions: [],             // open question annotations (owners only)
  questionPollTimer: null,
};

const DESKTOP_ASSETS_PAGE_SIZE = 240;
const TABLET_ASSETS_PAGE_SIZE = 120;
const PHONE_ASSETS_PAGE_SIZE = 80;

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
const SIDEBAR_VISIBILITY_KEY = "inspirations.ui.sidebar.hidden.v1";
const SIDEBAR_WIDTH_KEY = "inspirations.ui.sidebar.width.v1";
const VIEW_MODE_KEY = "inspirations.ui.view.mode.v1";
const CONTEXT_LINK_BANNER_DEFAULT = "Use this shared context link to review the referenced item.";
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
  const actorToken = typeof Shared.getActorToken === "function" ? Shared.getActorToken() : "";
  const headers = actorToken ? { "X-Actor-Token": actorToken } : {};
  const res = await fetch(path, { method: "POST", body: formData, headers });
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

function previewForAsset(a) {
  if (a.thumb_path) return `/media/${a.id}?kind=thumb`;
  if (a.stored_path && IMAGE_SUFFIX_RE.test(a.stored_path)) return `/media/${a.id}?kind=original`;
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
  if (!asset || !isVideoAsset(asset)) return "";
  if (asset.stored_path) return `/media/${asset.id}?kind=original`;
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

function _contextLinkPayloadFromUrl() {
  const params = new URLSearchParams(window.location.search || "");
  const collectionId = (params.get("collection_id") || "").trim();
  const itemId = (params.get("item_id") || "").trim();
  if (!collectionId || !itemId) return null;
  const openRaw = (params.get("open") || "").trim().toLowerCase();
  const shouldAutoOpen = openRaw === "1" || openRaw === "true" || openRaw === "yes";
  return { collectionId, itemId, shouldAutoOpen };
}

function _contextLinkMessageForReason(reason) {
  const key = String(reason || "").trim();
  if (key === "item_not_in_collection") return "This item is no longer in this collection.";
  if (key === "collection_not_found") return "This shared collection no longer exists.";
  if (key === "item_hidden_for_role") return "This shared item is hidden for your role.";
  if (key === "item_missing") return "This shared item is no longer available.";
  return "This shared context could not be resolved.";
}

function _contextCollectionIdForModal() {
  const ids = getCollectionFilterIds();
  if (ids.length === 1) return ids[0];
  return "";
}

function _buildContextLink(collectionId, itemId) {
  const url = new URL(window.location.href);
  url.search = "";
  url.hash = "";
  url.searchParams.set("collection_id", collectionId);
  url.searchParams.set("item_id", itemId);
  url.searchParams.set("open", "1");
  return url.toString();
}

async function _copyText(value) {
  const text = String(value || "");
  if (!text) return;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
  } catch (_) {
    // fallback below
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.left = "-1000px";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); } finally { ta.remove(); }
}

function _setShareButtonsDisabled(disabled, title = "") {
  for (const id of ["modalShareLinkBtn", "modalShareEmailBtn", "modalShareMessageBtn"]) {
    const btn = document.getElementById(id);
    if (!btn) continue;
    btn.disabled = !!disabled;
    btn.title = title ? String(title) : "";
  }
}

function wireModalShareActions(asset) {
  const copyBtn = $("#modalShareLinkBtn");
  const emailBtn = $("#modalShareEmailBtn");
  const messageBtn = $("#modalShareMessageBtn");
  if (!copyBtn && !emailBtn && !messageBtn) return;

  if (!state.actor) {
    _setShareButtonsDisabled(true, "Sign in to share context links.");
    return;
  }

  const collectionId = _contextCollectionIdForModal();
  const itemId = String(asset?.id || "").trim();
  if (!collectionId || !itemId) {
    _setShareButtonsDisabled(true, "Select one collection before sharing context.");
    return;
  }

  _setShareButtonsDisabled(false);
  const link = _buildContextLink(collectionId, itemId);
  const title = displayTitle(asset);
  const summary = title ? `Please review: ${title}` : "Please review this item";

  if (copyBtn) {
    copyBtn.onclick = async (e) => {
      if (e) { e.preventDefault(); e.stopPropagation(); }
      await _copyText(link);
      Shared.showToast("Context link copied", { type: "success", duration: 1800 });
    };
  }
  if (emailBtn) {
    emailBtn.onclick = (e) => {
      if (e) { e.preventDefault(); e.stopPropagation(); }
      const subject = encodeURIComponent(title ? `Review item: ${title}` : "Review this item");
      const body = encodeURIComponent(`${summary}\n\n${link}`);
      window.location.href = `mailto:?subject=${subject}&body=${body}`;
    };
  }
  if (messageBtn) {
    messageBtn.onclick = async (e) => {
      if (e) { e.preventDefault(); e.stopPropagation(); }
      if (navigator.share) {
        try {
          await navigator.share({ title: title || "Shared item", text: summary, url: link });
          return;
        } catch (err) {
          if (err && err.name === "AbortError") return;
        }
      }
      const smsSep = /iphone|ipad|ipod/i.test(navigator.userAgent || "") ? "&" : "?";
      const smsBody = encodeURIComponent(`${summary}\n${link}`);
      window.location.href = `sms:${smsSep}body=${smsBody}`;
    };
  }
}

async function restoreContextLinkFromUrl() {
  const payload = _contextLinkPayloadFromUrl();
  if (!payload) return;
  if (!state.actor) {
    setContextLinkBanner("Please sign in to open this shared context link.", { error: true });
    return;
  }
  let report = null;
  try {
    report = await api(
      `/api/context/resolve?collection_id=${encodeURIComponent(payload.collectionId)}&item_id=${encodeURIComponent(payload.itemId)}`
    );
  } catch (e) {
    setContextLinkBanner(`Unable to resolve shared context: ${formatApiError(e)}`, { error: true });
    return;
  }

  const collectionName = String(
    report?.collection_name
    || (state.collections.find((c) => c.id === payload.collectionId)?.name || "")
  );
  if (String(report?.reason || "") !== "collection_not_found") {
    state.currentSource = null;
    state.currentBoard = null;
    state.currentContentKind = null;
    clearCatalogFilter();
    setCollectionFilterIds([payload.collectionId], { label: collectionName, nodeId: null });
    state.offset = 0;
    renderCatalogTree();
    await loadAssets();
  }

  if (!report || !report.found) {
    setContextLinkBanner(_contextLinkMessageForReason(report?.reason), { error: true });
    return;
  }

  clearContextLinkBanner();
  if (!payload.shouldAutoOpen) return;
  let asset = state.assets.find((a) => a.id === payload.itemId);
  if (!asset) asset = await fetchAssetForModal(payload.itemId);
  if (!asset) {
    setContextLinkBanner("Shared item could not be opened in this session.", { error: true });
    return;
  }
  await openModal(asset);
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
  if (String(state.currentClassificationAxis || "").trim() !== "track") return [];
  return String(state.currentClassificationValue || "")
    .split(",")
    .map((value) => String(value || "").trim())
    .filter(Boolean);
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
    if (state.currentClassificationAxis) params.set("classification_axis", state.currentClassificationAxis);
    if (state.currentClassificationValue) params.set("classification_value", state.currentClassificationValue);
    const collectionIds = getCollectionFilterIds();
    if (collectionIds.length) params.set("collection_id", collectionIds.join(","));
  }

  if (state.triageFilter === "needs-comment") {
    params.set("needs_annotation", "1");
    params.set("include_hidden", "1");
  } else if (state.triageFilter === "hidden") {
    params.set("triage_status", "hidden");
    params.set("include_hidden", "1");
  } else if (state.triageFilter === "flagged") {
    params.set("flagged", "1");
    params.set("include_hidden", "1");
  } else if (state.triageFilter) {
    params.set("triage_status", state.triageFilter);
  }
  return params;
}

function _buildCurrentCatalogQueryParams({ limit, offset = 0 } = {}) {
  const params = new URLSearchParams();
  const catalogFiles = getCatalogFilterFiles();
  for (const file of catalogFiles) params.append("file", file);
  if (limit != null) params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (state.triageFilter === "hidden" || state.triageFilter === "needs-comment" || state.triageFilter === "flagged") {
    params.set("include_hidden", "1");
  }
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
  const actor = state.actor || null;
  if (!actor) return "Reviewer: Not signed in";
  const name = String(actor.name || "Unknown").trim() || "Unknown";
  const role = String(actor.role || "").trim().toLowerCase();
  return role ? `Reviewer: ${name} (${role})` : `Reviewer: ${name}`;
}

function updateReviewScopeChips() {
  const scope = getReviewScopeInfo();
  const chipText = `Scope: ${scope.label}`;
  const headerChip = $("#reviewScopeChip");
  if (headerChip) headerChip.textContent = chipText;
  const oneByOneActorChip = $("#reviewActorChip");
  if (oneByOneActorChip) oneByOneActorChip.textContent = _reviewActorLabel();
  const canvasActorChip = $("#reviewActorChipCanvas");
  if (canvasActorChip) canvasActorChip.textContent = _reviewActorLabel();
}

function confirmGlobalHideBulk(count) {
  const total = Math.max(0, Number(count || 0));
  const noun = total === 1 ? "item" : "items";
  return window.confirm(
    `Hide ${total} ${noun} globally?\n\n`
    + "This applies to the entire library, not just the active collection.\n"
    + "You can restore items later from Hidden."
  );
}

function hasCollectionFilter() {
  return getCollectionFilterIds().length > 0;
}

function hasClassificationFilter() {
  return !!String(state.currentClassificationAxis || "").trim();
}

function clearClassificationFilter() {
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
  state.currentClassificationAxis = cleanAxis;
  state.currentClassificationValue = cleanValue || null;
  state.currentClassificationLabel = label || cleanValue || cleanAxis;
  state.currentTreeNodeId = nodeId;
}

function clearCollectionFilter() {
  state.currentCollection = null;
  state.currentCollectionIds = [];
  state.currentCollectionLabel = "";
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
}

function isCollaboratorActor() {
  return !!(state.actor && state.actor.role !== "owner");
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
  return `/api/scan/doc-pdf?asset_id=${encodeURIComponent(asset.id)}#page=${page}`;
}

function renderModalSourceLinks(asset) {
  if (!asset) return;
  const ref = asset.source_ref || "";
  const isHttpRef = ref.startsWith("http://") || ref.startsWith("https://");
  const siteUrl = asset.source_url || "";
  const isHttpSite = siteUrl.startsWith("http://") || siteUrl.startsWith("https://");

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

  const sourceLinksWrap = $("#modalSourceLinks");
  if (sourceLinksWrap) {
    const primaryVisible = !!(sourceLink && !sourceLink.hidden);
    const secondaryVisible = !!(sourceSiteRow && !sourceSiteRow.hidden);
    sourceLinksWrap.hidden = !(primaryVisible || secondaryVisible);
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

function setSidebarHidden(hidden, { persist = true } = {}) {
  state.sidebarHidden = !!hidden;
  applySidebarVisibility();
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
  if (state.loadingAssets) return;
  const append = opts.append || false;
  if (!append) { state.offset = 0; }

  state.loadingAssets = true;
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
  if (state.currentClassificationAxis) params.set("classification_axis", state.currentClassificationAxis);
  if (state.currentClassificationValue) params.set("classification_value", state.currentClassificationValue);

  if (state.triageFilter === "needs-comment") {
    params.set("needs_annotation", "1");
    params.set("include_hidden", "1");
  } else if (state.triageFilter === "hidden") {
    params.set("triage_status", "hidden");
    params.set("include_hidden", "1");
  } else if (state.triageFilter === "flagged") {
    params.set("flagged", "1");
    params.set("include_hidden", "1");
  } else if (state.triageFilter) {
    params.set("triage_status", state.triageFilter);
  }

  // Always include hidden items when "all" is selected to show full picture
  // but don't show triage=hidden by default unless explicitly requested
  // (server default: exclude hidden)

  try {
    let data;
    const catalogFiles = getCatalogFilterFiles();
    if (catalogFiles.length) {
      // Catalog browsing: load items from one or more catalog files
      const catParams = new URLSearchParams();
      for (const file of catalogFiles) catParams.append("file", file);
      catParams.set("limit", ASSETS_PAGE_SIZE);
      catParams.set("offset", state.offset);
      data = await api(`/api/catalog/items?${catParams}`);
    } else if (semQ) {
      const res = await fetch(`/api/search/similar?${params}`);
      if (!res.ok) throw new Error(await res.text());
      data = await res.json();
    } else {
      const collectionIds = getCollectionFilterIds();
      if (collectionIds.length) params.set("collection_id", collectionIds.join(","));
      data = await api(`/api/assets?${params}`);
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
    syncExplorerFilter();
  } catch (e) {
    if (seq !== state.assetsRequestSeq) return;
    const grid = $("#grid");
    if (grid) grid.innerHTML = `<div class="empty-state">Unable to load items: ${escapeHtml(formatApiError(e))}</div>`;
  } finally {
    if (seq === state.assetsRequestSeq) state.loadingAssets = false;
  }
}

function updateLoadMoreBtn() {
  const btn = $("#loadMore");
  if (!btn) return;
  btn.hidden = !state.hasMore || state.semanticMode;
  btn.disabled = state.loadingAssets;
  btn.textContent = state.loadingAssets ? "Loading…" : "Load More";
}

function updateStats() {
  const statsEl = $("#stats");
  if (!statsEl) return;
  if (isExplorerViewActive() && Number.isFinite(_explorerFilterCount)) {
    const count = Math.max(0, Number(_explorerFilterCount || 0));
    statsEl.textContent = `${count} item${count === 1 ? "" : "s"}`;
    return;
  }
  const shown = state.assets.length;
  const total = state.totalCount;
  if (state.hasMore && total) {
    statsEl.textContent = `${shown} of ${total} items`;
  } else if (state.hasMore) {
    statsEl.textContent = `${shown} items shown — more available`;
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
  // Maintain canvas review class across re-renders
  const browseView = $("#browseView");
  if (browseView) browseView.classList.toggle("canvas-review-active", state.canvasReview);

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

  // Triage/flag badges — owner-only
  let badgeHtml = "";
  if (isOwner()) {
    if (flagged) {
      badgeHtml = '<span class="triage-badge flagged" title="Flagged for review"></span>';
    } else if (ts === "keeper" && needsComment) {
      badgeHtml = '<span class="triage-badge needs-comment" title="Keeper — needs comment"></span>';
    } else if (ts === "keeper") {
      badgeHtml = '<span class="triage-badge keeper" title="Keeper"></span>';
    } else if (ts === "hidden") {
      badgeHtml = '<span class="triage-badge hidden-status" title="Hidden"></span>';
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
  const quickStarHtml = isOwner()
    ? `<button class="card-quick-star${isKeeper ? " starred" : ""}" title="${isKeeper ? "Remove keeper" : "Mark as keeper"}" type="button">★</button>`
    : "";

  const selectedClass = state.canvasReview && state.canvasSelected.has(a.id) ? " canvas-selected" : "";
  el.className = "card" + selectedClass;

  const mediaHtml = showVideo
    ? (imgUrl
      ? `<img src="${escapeHtml(imgUrl)}" loading="lazy" alt="" class="video-poster" />`
      : `<video src="${escapeHtml(videoUrl)}" preload="metadata" playsinline muted></video>`)
    : imgUrl
      ? `<img src="${escapeHtml(imgUrl)}" loading="lazy" alt="" />`
      : `<div class="card-placeholder">${escapeHtml(displayTitle(a))}</div>`;

  el.innerHTML = `
    <div class="card-image">
      <div class="card-checkbox"></div>
      ${mediaHtml}
      ${badgeHtml}
      <span class="source-badge source-${escapeHtml(a.source || "")}">${escapeHtml(sourceLabel)}</span>
      ${quickStarHtml}
      ${quickTagHtml}
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
    if (state.canvasReview) {
      toggleCanvasSelection(a.id, el);
      return;
    }
    openModal(a);
  };

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
      if (img) img.src = `/media/${memberIds[pageIdx]}?kind=thumb`;
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
    // Update status chip UI to reflect "All"
    $$("[data-triage]").forEach((c) => {
      c.classList.toggle("active", c.dataset.triage === "");
    });
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

  const allItemsActive = isAllItemsScopeActive();
  const collapseRest = allItemsActive && !!state.allItemsTreeCollapsed;

  // "All items" node (root order differs for collaborator view)
  const allBtn = document.createElement("button");
  allBtn.className = `tree-toggle tree-toggle-root${allItemsActive ? " active" : ""}${!collapseRest ? " expanded" : ""}`;
  allBtn.innerHTML = `<span class="tree-arrow">&#9654;</span><span class="tree-label">All Items</span>`;
  allBtn.title = "All Items";
  allBtn.onclick = () => {
    if (shouldIgnorePostBrowseUnlockTreeClick()) return;
    const wasAllItemsActive = isAllItemsScopeActive();
    if (wasAllItemsActive) {
      state.allItemsTreeCollapsed = !state.allItemsTreeCollapsed;
      renderCatalogTree();
      return;
    }
    resetTriageFilter();
    state.currentSource = null;
    state.currentBoard = null;
    state.currentContentKind = null;
    clearCollectionFilter();
    clearCatalogFilter();
    clearClassificationFilter();
    state.currentTreeNodeId = null;
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };
  const appendAllItemsRoot = () => wrap.appendChild(allBtn);
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

  appendAllItemsRoot();

  if (!collapseRest) {
    const sourceNodes = tree.filter((n) => n.type === "source");
    const classificationNodes = tree.filter((n) => n.type === "classification");
    const otherNode = tree.find((n) => String(n?.id || "").trim().toLowerCase() === "dimension:other") || null;
    const nonHomeTrackValues = new Set(["home_maintenance_diy"]);
    const discardTrackValues = new Set(["irrelevant"]);
    const primaryClassificationNodes = [];
    const nonHomeNodes = [];
    const discardNodes = [];

    for (const node of classificationNodes) {
      if (String(node.axis_name || "").trim() !== "track") {
        primaryClassificationNodes.push(node);
        continue;
      }
      const children = Array.isArray(node.children) ? node.children : [];
      const visibleChildren = children.filter((child) => {
        const value = String(child.axis_value || "").trim();
        return !nonHomeTrackValues.has(value) && !discardTrackValues.has(value);
      });
      const nonHomeChildren = children.filter((child) => nonHomeTrackValues.has(String(child.axis_value || "").trim()));
      const discardChildren = children.filter((child) => discardTrackValues.has(String(child.axis_value || "").trim()));
      if (visibleChildren.length) {
        primaryClassificationNodes.unshift({
          ...node,
          count: visibleChildren.reduce((sum, child) => sum + Number(child.count || 0), 0),
          children: visibleChildren,
        });
      }
      if (nonHomeChildren.length) {
        nonHomeNodes.push({
          ...node,
          id: "classification:non_home_tracks",
          label: "Track",
          count: nonHomeChildren.reduce((sum, child) => sum + Number(child.count || 0), 0),
          children: nonHomeChildren,
        });
      }
      if (discardChildren.length) {
        discardNodes.push({
          ...node,
          id: "classification:discard_tracks",
          label: "Track",
          count: discardChildren.reduce((sum, child) => sum + Number(child.count || 0), 0),
          children: discardChildren,
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

    const allItemsBranch = document.createElement("div");
    allItemsBranch.className = "all-items-branch";
    const groups = [
      {
        id: "browse-group:classification",
        label: "Classification",
        nodes: primaryClassificationNodes,
        defaultExpanded: true,
        builder: (node) => buildClassificationNode(node),
      },
      {
        id: "browse-group:sources",
        label: "Sources",
        nodes: sourceNodes,
        defaultExpanded: false,
        builder: (node) => buildSourceNode(node),
      },
    ];
    if (!isCollaboratorActor()) {
      groups.splice(1, 0,
        {
          id: "browse-group:non-home",
          label: "Other / Non-Home-Design",
          nodes: nonHomeNodes,
          defaultExpanded: false,
          builder: (node) => node.type === "dimension" ? buildDimensionNode(node) : buildClassificationNode(node),
        },
        {
          id: "browse-group:discards",
          label: "Irrelevant / Discarded",
          nodes: discardNodes,
          defaultExpanded: false,
          builder: (node) => buildClassificationNode(node),
        },
      );
    }
    for (const group of groups) {
      if (!group.nodes.length) continue;
      allItemsBranch.appendChild(buildBrowseGroupNode(group));
    }
    if (allItemsBranch.childElementCount) {
      wrap.appendChild(allItemsBranch);
    }
  }

  updateSidebarModeVisibility();
}

function _treeNodeContainsActiveSelection(node) {
  if (!node) return false;
  if (state.currentTreeNodeId && state.currentTreeNodeId === node.id) return true;
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
    clearClassificationFilter();
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
      clearClassificationFilter();
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
        clearClassificationFilter();
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
  const isActiveHeader = state.currentTreeNodeId === node.id
    || (state.currentClassificationAxis === axisName && !state.currentClassificationValue);
  const toggle = document.createElement("button");
  toggle.className = `tree-toggle${isActiveHeader ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span class="tree-label">${escapeHtml(node.label)}</span><span class="tree-count">${node.count}</span>`;

  const children = document.createElement("div");
  children.className = "tree-children";

  const hasActiveChild = (node.children || []).some(
    (child) => (
      state.currentClassificationAxis === String(child.axis_name || "").trim()
      && state.currentClassificationValue === String(child.axis_value || "").trim()
    )
  );
  if (hasActiveChild || isActiveHeader) state.expandedTreeNodes.add(nodeKey);
  _setTreeNodeExpanded(nodeKey, toggle, children, state.expandedTreeNodes.has(nodeKey));
  _wireTreeArrowToggle(toggle, nodeKey, children);

  toggle.onclick = () => {
    if (shouldIgnorePostBrowseUnlockTreeClick()) return;
    resetTriageFilter();
    state.currentSource = null;
    state.currentBoard = null;
    state.currentContentKind = null;
    clearCollectionFilter();
    clearCatalogFilter();
    setClassificationFilter(axisName, "", { label: node.label, nodeId: node.id });
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };

  for (const child of (node.children || [])) {
    const axisValue = String(child.axis_value || "").trim();
    const leaf = document.createElement("button");
    const isActive = (
      state.currentClassificationAxis === axisName
      && state.currentClassificationValue === axisValue
    );
    leaf.className = `tree-leaf${isActive ? " active" : ""}`;
    leaf.innerHTML = `<span>${escapeHtml(child.label)}</span><span class="tree-count">${child.count}</span>`;
    leaf.onclick = () => {
      if (shouldIgnorePostBrowseUnlockTreeClick()) return;
      resetTriageFilter();
      state.currentSource = null;
      state.currentBoard = null;
      state.currentContentKind = null;
      clearCollectionFilter();
      clearCatalogFilter();
      setClassificationFilter(axisName, axisValue, { label: child.label, nodeId: child.id });
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

function buildCollectionsGroupNode(node) {
  const el = document.createElement("div");
  el.className = "tree-node";

  const nodeKey = "collections";
  const selectedCollectionIds = getCollectionFilterIds();
  const selectedCollectionSet = new Set(selectedCollectionIds);
  const isActiveHeader = state.currentTreeNodeId === node.id;
  const toggle = document.createElement("button");
  toggle.className = `tree-toggle${isActiveHeader ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span class="tree-label">Collections</span><span class="tree-count">${node.count}</span>`;
  toggle.title = "Collections";

  const children = document.createElement("div");
  children.className = "tree-children";

  const hasActiveChild = (node.children || []).some((c) => selectedCollectionSet.has(c.collection_id));
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
    clearClassificationFilter();
    setCollectionFilterIds(collectDescendantCollectionIds(node), { label: "All Collections", nodeId: node.id });
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };

  for (const child of (node.children || [])) {
    const leaf = document.createElement("button");
    const isActive = selectedCollectionIds.length === 1 && selectedCollectionIds[0] === child.collection_id;
    const badge = child.provenance_badge
      ? `<span class="tree-collection-badge" title="${escapeHtml(child.provenance_label || "")}">${escapeHtml(child.provenance_badge)}</span>`
      : "";
    const titleBits = [String(child.label || "")];
    if (child.provenance_label) titleBits.push(String(child.provenance_label));
    if (child.provenance_note) titleBits.push(String(child.provenance_note));
    leaf.className = `tree-leaf${isActive ? " active" : ""}`;
    leaf.title = titleBits.join(" — ");
    leaf.innerHTML = `<span class="tree-leaf-main"><span class="tree-leaf-text">${escapeHtml(child.label)}</span>${badge}</span><span class="tree-count">${child.count}</span>`;
    leaf.onclick = () => {
      resetTriageFilter();
      state.currentSource = null;
      state.currentBoard = null;
      state.currentContentKind = null;
      clearCatalogFilter();
      clearClassificationFilter();
      setCollectionFilterIds([child.collection_id], { label: child.label, nodeId: child.id });
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
    };
    // Context menu for bulk triage on collections (owner-only)
    const _colId = child.collection_id;
    addTreeHideToggle(leaf, () => ({ collection_id: _colId }));
    children.appendChild(leaf);
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
  btn.title = "Hide all items in this folder";
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
      Shared.showToast("Global hide canceled.", { type: "info" });
      return;
    }
    await api("/api/assets/triage/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, status }),
    });

    if (isHiding) {
      _bulkHiddenByNode[nodeKey] = ids;
      Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} hidden.`, { type: "success" });
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
  clearClassificationFilter();
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
  clearClassificationFilter();
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

// ─── Question badge + polling (owner-only) ──────────────────────────────────────

async function pollQuestions() {
  try {
    const data = await api("/api/questions/dashboard");
    state.openQuestions = data.questions || [];
    renderQuestionBadge();
  } catch {
    // silent
  }
}

function refreshQuestionsIfOwner() {
  if (!isOwner()) return;
  void pollQuestions();
}

function renderQuestionBadge() {
  let badge = $("#questionBadge");
  if (!badge) {
    // Create badge element in header if it doesn't exist
    const header = $(".top-bar") || $("header");
    if (!header) return;
    badge = document.createElement("button");
    badge.id = "questionBadge";
    badge.className = "question-badge";
    badge.title = "Open questions from collaborators";
    badge.onclick = toggleQuestionPanel;
    header.appendChild(badge);
  }
  const count = state.openQuestions.length;
  badge.hidden = count === 0;
  badge.innerHTML = `<span class="question-badge-icon">?</span><span class="question-badge-count">${count}</span>`;
}

function toggleQuestionPanel() {
  let panel = $("#questionPanel");
  if (panel) {
    panel.remove();
    return;
  }
  panel = document.createElement("div");
  panel.id = "questionPanel";
  panel.className = "question-panel";

  const header = document.createElement("div");
  header.className = "question-panel-header";
  header.innerHTML = `<strong>Open Questions (${state.openQuestions.length})</strong>`;
  const closeBtn = document.createElement("button");
  closeBtn.textContent = "\u00d7";
  closeBtn.className = "question-panel-close";
  closeBtn.onclick = () => panel.remove();
  header.appendChild(closeBtn);
  panel.appendChild(header);

  if (!state.openQuestions.length) {
    panel.innerHTML += '<div class="question-panel-empty">No open questions!</div>';
  } else {
    for (const q of state.openQuestions) {
      const item = document.createElement("div");
      item.className = "question-panel-item";
      item.innerHTML = `
        <div class="question-panel-item-meta">${escapeHtml(q.actor_name || "Anonymous")} &middot; ${escapeHtml(q.asset_title || "Untitled")}</div>
        <div class="question-panel-item-text">${escapeHtml(q.text || "(no text)")}</div>
      `;
      item.onclick = () => {
        panel.remove();
        // Navigate to the asset
        const asset = state.assets.find((a) => a.id === q.asset_id);
        if (asset) { openModal(asset); }
        else { Shared.showToast("Loading item...", { type: "info", duration: 2000 }); }
      };
      panel.appendChild(item);
    }
  }

  const badge = $("#questionBadge");
  if (badge) badge.parentElement.appendChild(panel);
  else document.body.appendChild(panel);
}

// ─── Triage status filter ───────────────────────────────────────────────────────

function wireStatusChips() {
  const chips = $$("[data-triage]");
  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      chips.forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      state.triageFilter = chip.dataset.triage;
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
    });
  });
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

const collectionBulkSelection = {
  active: new Set(),
  hidden: new Set(),
};

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
    listEl.innerHTML = `<div class="muted">${isHidden ? "No hidden collections." : "No active collections."}</div>`;
    return;
  }
  listEl.innerHTML = rows.map((c) => {
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
    const metaHtml = provenanceBadge || provenanceNote
      ? `<span class="collectionBulkMeta">${provenanceLabel}${provenanceNote ? ` · ${provenanceNote}` : ""}</span>`
      : "";
    return (
      `<label class="collectionBulkRow">`
      + `<input type="checkbox" data-kind="${isHidden ? "hidden" : "active"}" data-id="${escapeHtml(id)}" ${checked} />`
      + `<span class="collectionBulkNameWrap"><span class="collectionBulkNameLine"><span class="collectionBulkName">${name}</span>${badgeHtml}</span>${metaHtml}</span>`
      + `<span class="collectionBulkCount">${count}</span>`
      + `</label>`
    );
  }).join("");
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
    Shared.showToast(`Hidden ${updated} collection${updated === 1 ? "" : "s"}.`, { type: "success" });
    collectionBulkSelection.active.clear();
    await loadCollectionsForManager();
    renderCollectionBulkModal();
    await _refreshCollectionViewsAfterBulkChange();
  } catch (e) {
    Shared.showToast(`Hide failed: ${formatApiError(e)}`, { type: "error" });
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
  const ok = confirm(`Delete ${ids.length} hidden collection${ids.length === 1 ? "" : "s"} permanently? This cannot be undone.`);
  if (!ok) return;
  try {
    const payload = await api("/api/collections/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ collection_ids: ids }),
    });
    const deleted = Number(payload.deleted || 0);
    const skipped = Number(payload.skipped || 0);
    if (skipped > 0) {
      Shared.showToast(`Deleted ${deleted}. Skipped ${skipped} (must already be hidden).`, { type: "info" });
    } else {
      Shared.showToast(`Deleted ${deleted} hidden collection${deleted === 1 ? "" : "s"}.`, { type: "success" });
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
  $("#collectionBulkModal")?.classList.remove("hidden");
}

function closeCollectionBulkModal() {
  collectionBulkSelection.active.clear();
  collectionBulkSelection.hidden.clear();
  renderCollectionBulkModal();
  $("#collectionBulkModal")?.classList.add("hidden");
}

function setCollectionFilter(collectionId) {
  if (collectionId) {
    state.currentSource = null;
    state.currentBoard = null;
    state.currentContentKind = null;
    clearCatalogFilter();
    clearClassificationFilter();
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

$("#newCollection").addEventListener("click", async () => {
  const name = prompt("Collection name:");
  if (!name || !name.trim()) return;
  try {
    await api("/api/collections", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
    await loadCollections();
    await loadCatalogTree();
    Shared.showToast(`Created collection "${name.trim()}"`, { type: "success" });
  } catch (e) {
    Shared.showToast(`Failed: ${formatApiError(e)}`, { type: "error" });
  }
});

const manageCollectionsBtn = $("#manageCollections");
if (manageCollectionsBtn) {
  manageCollectionsBtn.addEventListener("click", async () => {
    await openCollectionBulkModal();
  });
}
const closeCollectionBulkBtn = $("#closeCollectionBulk");
if (closeCollectionBulkBtn) closeCollectionBulkBtn.addEventListener("click", closeCollectionBulkModal);
const cancelCollectionBulkBtn = $("#cancelCollectionBulk");
if (cancelCollectionBulkBtn) cancelCollectionBulkBtn.addEventListener("click", closeCollectionBulkModal);
const collectionBulkHideBtn = $("#collectionBulkHideBtn");
if (collectionBulkHideBtn) collectionBulkHideBtn.addEventListener("click", bulkHideCollections);
const collectionBulkRestoreBtn = $("#collectionBulkRestoreBtn");
if (collectionBulkRestoreBtn) collectionBulkRestoreBtn.addEventListener("click", bulkRestoreCollections);
const collectionBulkDeleteBtn = $("#collectionBulkDeleteBtn");
if (collectionBulkDeleteBtn) collectionBulkDeleteBtn.addEventListener("click", bulkDeleteHiddenCollections);
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
  if (state.modalAsset && state.modalAsset.id === next.id) state.modalAsset = next;
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
  const owner = isOwner();
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

function _renderModalLabels(labels) {
  const labelsEl = $("#modalLabels");
  const labelsTitleEl = $("#modalLabelsTitle");
  if (!labelsEl) return;
  labelsEl.innerHTML = "";
  labelsEl.hidden = true;
  labelsEl.classList.remove("expanded");
  if (labelsTitleEl) labelsTitleEl.hidden = true;
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
}

async function _loadModalLabels(assetId, seq) {
  try {
    const resp = await fetch(`/api/assets/${encodeURIComponent(assetId)}/labels`);
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
  if (!isOwner()) {
    panel.hidden = true;
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

  panel.hidden = false;
  const statusEl = $("#modalSourceCandidateStatus");
  if (statusEl) {
    const parts = [];
    if (fetchStatus) parts.push(fetchStatus);
    if (error) parts.push(error);
    statusEl.textContent = parts.join(" · ");
    statusEl.hidden = !parts.length;
  }
  const imageWrap = $("#modalSourceCandidateImageWrap");
  const imageEl = $("#modalSourceCandidateImage");
  if (imageWrap) imageWrap.hidden = !heroImageUrl;
  if (imageEl) {
    imageEl.src = heroImageUrl || "";
    imageEl.alt = heroImageAlt || pageTitle || "Source candidate";
  }
  const titleRow = $("#modalSourceCandidateTitleRow");
  const titleEl = $("#modalSourceCandidateTitle");
  if (titleRow) titleRow.hidden = !pageTitle;
  if (titleEl) titleEl.textContent = pageTitle;
  const heroTextRow = $("#modalSourceCandidateHeroTextRow");
  const heroTextEl = $("#modalSourceCandidateHeroText");
  if (heroTextRow) heroTextRow.hidden = !heroText;
  if (heroTextEl) heroTextEl.textContent = heroText;
  const textRow = $("#modalSourceCandidateTextRow");
  const textEl = $("#modalSourceCandidateText");
  if (textRow) textRow.hidden = !textExcerpt;
  if (textEl) textEl.textContent = textExcerpt;

  const captureBtn = $("#modalSourceCandidateCaptureBtn");
  const promoteBtn = $("#modalSourceCandidatePromoteBtn");
  if (captureBtn) captureBtn.disabled = false;
  if (promoteBtn) promoteBtn.disabled = !heroImageUrl;
}

async function runModalSourceCandidateAction(action) {
  const asset = state.modalAsset;
  if (!asset || !asset.id) return;
  if (!isOwner()) {
    Shared.showToast("Source candidate tools are owner-only.", { type: "info" });
    return;
  }
  const captureBtn = $("#modalSourceCandidateCaptureBtn");
  const promoteBtn = $("#modalSourceCandidatePromoteBtn");
  if (captureBtn) captureBtn.disabled = true;
  if (promoteBtn) promoteBtn.disabled = true;
  try {
    const data = await api(`/api/assets/${encodeURIComponent(asset.id)}/source-link-candidate`, {
      method: "PUT",
      body: JSON.stringify({ action }),
    });
    const updated = data.asset || null;
    if (!updated) throw new Error("Updated asset missing from response");
    replaceAssetInState(updated);
    state.modalAsset = updated;
    renderModalSourceCandidatePanel(updated);
    if (action === "promote") {
      renderGrid();
      await openModal(updated);
      Shared.showToast("Candidate image promoted.", { type: "success", duration: 1800 });
    } else {
      Shared.showToast("Source candidate captured.", { type: "success", duration: 1800 });
    }
  } catch (e) {
    Shared.showToast(formatApiError(e), { type: "error", duration: 3200 });
  } finally {
    if (captureBtn) captureBtn.disabled = false;
    if (promoteBtn) promoteBtn.disabled = false;
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

function renderModalClassificationPanel(asset) {
  const panel = $("#modalClassificationPanel");
  if (!panel) return;
  if (!isOwner()) {
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

  panel.hidden = !needsReview;
  if (!needsReview) return;

  const statusEl = $("#modalClassificationStatus");
  if (statusEl) {
    statusEl.textContent = statusText;
    statusEl.hidden = !statusText;
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
  const irrelevantBtn = $("#modalClassificationIrrelevantBtn");
  if (editor) editor.hidden = false;
  const defaultTrack = overrideTrack || (hasSourceConflict ? sourceTrack : currentTrack);
  if (moveTo) moveTo.value = _preferredMoveTrack(defaultTrack);
  if (focusSelect) focusSelect.value = overrideFocus && REVIEW_FOCUS_LABELS[overrideFocus] ? overrideFocus : "";
  if (mediaSelect) mediaSelect.value = overrideMedia && MEDIA_RELIABILITY_LABELS[overrideMedia] ? overrideMedia : "";
  if (comment) comment.value = cleanedOverrideNote || "";
  if (keepBtn) keepBtn.disabled = !effectiveTrack;
  if (saveBtn) saveBtn.disabled = false;
  if (irrelevantBtn) irrelevantBtn.disabled = false;
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
  const irrelevantBtn = $("#modalClassificationIrrelevantBtn");
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
    const data = await api(`/api/assets/${encodeURIComponent(asset.id)}/classification-review`, {
      method: "PUT",
      body: JSON.stringify({ track, note, review_focus: reviewFocus, media_reliability: mediaReliability }),
    });
    const updated = data.asset || null;
    if (!updated) throw new Error("Updated asset missing from response");
    replaceAssetInState(updated);
    state.modalAsset = updated;
    await Promise.all([loadCatalogTree(), loadAssets()]);
    renderModalClassificationPanel(updated);
    Shared.showToast(
      track === currentTrack ? "Kept current classification." : `Moved to ${classificationTrackLabel(track)}.`,
      { type: "success", duration: 1800 }
    );
  } catch (e) {
    Shared.showToast(formatApiError(e), { type: "error", duration: 3200 });
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
  const modalSeq = (Number(state.modalLoadSeq || 0) + 1);
  state.modalLoadSeq = modalSeq;
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
  const copyAssetIdBtn = $("#copyAssetIdBtn");
  if (copyAssetIdBtn) {
    copyAssetIdBtn.onclick = async () => {
      const idText = String(asset.id || "").trim();
      if (!idText) return;
      try {
        await navigator.clipboard.writeText(idText);
      } catch (_) {
        const ta = document.createElement("textarea");
        ta.value = idText;
        ta.style.position = "fixed";
        ta.style.left = "-1000px";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); } catch {}
        ta.remove();
      }
      Shared.showToast("Item ID copied", { type: "success", duration: 1500 });
    };
  }
  renderModalTitlePanel(asset);
  renderModalClassificationPanel(asset);
  renderModalSourceCandidatePanel(asset);
  _renderMediaReliabilityOverlay("#modalMediaOverlay", asset?.classification_review?.active_media_reliability || "");
  const titleSaveBtn = $("#modalTitleSaveBtn");
  if (titleSaveBtn) titleSaveBtn.onclick = () => saveWorkingTitleFromModal({ useSuggested: false });
  const titleSuggestedBtn = $("#modalTitleUseSuggestedBtn");
  if (titleSuggestedBtn) titleSuggestedBtn.onclick = () => saveWorkingTitleFromModal({ useSuggested: true });
  const classificationKeepBtn = $("#modalClassificationKeepBtn");
  if (classificationKeepBtn) {
    classificationKeepBtn.onclick = () => saveModalClassificationReview({
      track: _effectiveClassificationTrack(state.modalAsset?.classification_review || {}),
    });
  }
  const classificationSaveBtn = $("#modalClassificationSaveBtn");
  if (classificationSaveBtn) classificationSaveBtn.onclick = () => saveModalClassificationReview();
  const classificationIrrelevantBtn = $("#modalClassificationIrrelevantBtn");
  if (classificationIrrelevantBtn) {
    classificationIrrelevantBtn.onclick = () => saveModalClassificationReview({ track: "irrelevant" });
  }
  const sourceCandidateCaptureBtn = $("#modalSourceCandidateCaptureBtn");
  if (sourceCandidateCaptureBtn) sourceCandidateCaptureBtn.onclick = () => runModalSourceCandidateAction("capture");
  const sourceCandidatePromoteBtn = $("#modalSourceCandidatePromoteBtn");
  if (sourceCandidatePromoteBtn) sourceCandidatePromoteBtn.onclick = () => runModalSourceCandidateAction("promote");

  const img = $("#modalImage");
  const video = $("#modalVideo");
  const modalVideoUrl = videoUrlForAsset(asset);
  if (modalVideoUrl) {
    if (img) {
      img.removeAttribute("src");
      img.style.display = "none";
    }
    if (video) {
      video.src = modalVideoUrl;
      const poster = asset.thumb_path ? `/media/${asset.id}?kind=thumb` : "";
      if (poster) video.poster = poster;
      else video.removeAttribute("poster");
      video.hidden = false;
    }
  } else {
    const url = asset.thumb_path ? `/media/${asset.id}?kind=original`
      : asset.stored_path ? `/media/${asset.id}?kind=original`
        : asset.image_url || "";
    if (img) {
      img.src = url;
      img.style.display = url ? "block" : "none";
    }
    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.hidden = true;
    }
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

  // Labels / tags
  const labelsEl = $("#modalLabels");
  if (labelsEl) {
    labelsEl.innerHTML = "";
    labelsEl.hidden = true;
    labelsEl.classList.remove("expanded");
  }
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
  if (printBtn) printBtn.onclick = () => printModalAsset(asset);
  wireModalShareActions(asset);

  const annHintText = $("#annHintText");
  const annQuestionToggle = $("#annQuestionToggle");
  const annQuestionLabel = $("#annQuestionLabel");
  const annotationsTitle = $("#modalAnnotationsTitle");
  const stagePrompt = $("#modalStagePrompt");
  const collaboratorOnlyQuestions = !!(state.actor && state.actor.role !== "owner");
  if (annHintText) {
    annHintText.textContent = collaboratorOnlyQuestions
      ? "Click on the image to ask a question."
      : "Click on the image to add a note.";
  }
  if (annQuestionToggle) {
    annQuestionToggle.checked = collaboratorOnlyQuestions ? true : !!annQuestionToggle.checked;
    annQuestionToggle.disabled = collaboratorOnlyQuestions;
  }
  if (annQuestionLabel) {
    annQuestionLabel.hidden = collaboratorOnlyQuestions;
  }
  if (annotationsTitle) {
    annotationsTitle.textContent = collaboratorOnlyQuestions ? "Questions" : "Annotations";
    annotationsTitle.classList.toggle("sectionTitle-questions", collaboratorOnlyQuestions);
    annotationsTitle.classList.toggle("sectionTitle-annotations", !collaboratorOnlyQuestions);
  }
  if (stagePrompt) {
    if (collaboratorOnlyQuestions) {
      stagePrompt.innerHTML = `
        <div class="modal-stage-prompt-title">Questions</div>
        <div class="modal-stage-prompt-text">Click on the image to ask a question.</div>
      `;
      stagePrompt.hidden = false;
    } else {
      stagePrompt.hidden = true;
      stagePrompt.innerHTML = "";
    }
  }
  const annHintRow = annHintText ? annHintText.closest(".ann-hint-row") : null;
  if (annHintRow) {
    annHintRow.hidden = collaboratorOnlyQuestions;
  }

  // Notes
  const notesArea = $("#assetNotes");
  const notesHint = $("#assetNotesHint");
  if (notesArea) {
    notesArea.value = asset.notes || "";
    const editable = canEditAssetNotes();
    notesArea.readOnly = !editable;
    notesArea.disabled = false;
    notesArea.oninput = editable ? () => scheduleNotesUpdate(asset.id, notesArea.value) : null;
    notesArea.onblur = editable ? () => { void persistAssetNotesNow(asset.id, notesArea.value); } : null;
    notesArea.onfocus = () => { clearActiveAnnotationSelection(); };
    if (notesHint) {
      notesHint.hidden = editable;
      notesHint.textContent = editable
        ? ""
        : "General notes are owner-only. Use annotations or questions to leave feedback.";
    }
  }

  // Flag button
  const flagBtn = $("#modalFlagBtn");
  if (flagBtn) {
    flagBtn.classList.toggle("active", !!asset.flagged);
    flagBtn.textContent = asset.flagged ? "🚩 Flagged" : "🚩 Flag";
    flagBtn.onclick = async () => {
      if (!canUseFlag()) {
        Shared.showToast("Flagging is owner-only.", { type: "info" });
        return;
      }
      const newFlagged = asset.flagged ? 0 : 1;
      try {
        await api(`/api/assets/${encodeURIComponent(asset.id)}/flag`, {
          method: "POST",
          body: JSON.stringify({ flagged: newFlagged }),
        });
        asset.flagged = newFlagged;
        flagBtn.classList.toggle("active", !!newFlagged);
        flagBtn.textContent = newFlagged ? "🚩 Flagged" : "🚩 Flag";
        // Update card badge
        const card = $(`[data-id="${asset.id}"]`);
        if (card) {
          const oldBadge = card.querySelector(".triage-badge.flagged");
          if (oldBadge) oldBadge.remove();
          if (newFlagged) {
            const badge = document.createElement("span");
            badge.className = "triage-badge flagged";
            badge.title = "Flagged for review";
            card.querySelector(".card-image").prepend(badge);
          }
        }
        Shared.showToast(newFlagged ? "Flagged for review" : "Flag removed", { type: "success" });
      } catch (e) {
        Shared.showToast(`Failed: ${formatApiError(e)}`, { type: "error" });
      }
    };
  }

  // Tag button (diagnosis marker)
  const tagBtn = $("#modalTagBtn");
  if (tagBtn) {
    tagBtn.classList.toggle("active", !!asset.tagged);
    tagBtn.textContent = asset.tagged ? "🏷️ Tagged" : "🏷️ Tag";
    tagBtn.onclick = async () => {
      if (!canUseTag()) {
        Shared.showToast("Tag workflow retired.", { type: "info" });
        return;
      }
      const newTagged = asset.tagged ? 0 : 1;
      try {
        await api(`/api/assets/${encodeURIComponent(asset.id)}/tag`, {
          method: "POST",
          body: JSON.stringify({ tagged: newTagged }),
        });
        asset.tagged = newTagged;
        tagBtn.classList.toggle("active", !!newTagged);
        tagBtn.textContent = newTagged ? "🏷️ Tagged" : "🏷️ Tag";

        const card = $(`[data-id="${asset.id}"]`);
        if (card) {
          const cardImg = card.querySelector(".card-image");
          const oldBadge = card.querySelector(".triage-badge.tagged");
          if (oldBadge) oldBadge.remove();
          if (newTagged && cardImg) {
            const badge = document.createElement("span");
            badge.className = "triage-badge tagged";
            badge.title = "Tagged for diagnosis";
            cardImg.prepend(badge);
          }
          const quickTagBtn = card.querySelector(".card-quick-tag");
          if (quickTagBtn) {
            quickTagBtn.classList.toggle("tagged", !!newTagged);
            quickTagBtn.title = newTagged ? "Remove tag" : "Tag for diagnosis";
          }
        }

        Shared.showToast(newTagged ? "Tagged for diagnosis" : "Tag removed", { type: "success", duration: 2000 });
      } catch (e) {
        Shared.showToast(`Tag failed: ${formatApiError(e)}`, { type: "error" });
      }
    };
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
  state.annotations = [];
  state.activeAnnotationId = null;
  const img = $("#modalImage");
  if (img) img.style.display = "block";
  const video = $("#modalVideo");
  if (video) {
    video.pause();
    video.removeAttribute("src");
    video.hidden = true;
  }
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
  if (modalImage) modalImage.src = `/media/${siblingId}?kind=thumb`;
  const indicator = document.querySelector(".modalScanIndicator");
  if (indicator) indicator.textContent = `Page ${newIdx + 1} of ${state.modalScanPages.length}`;
  const prevBtn = document.querySelector(".modalScanPrev");
  const nextBtn = document.querySelector(".modalScanNext");
  if (prevBtn) prevBtn.disabled = newIdx === 0;
  if (nextBtn) nextBtn.disabled = newIdx === state.modalScanPages.length - 1;
  renderModalSourceLinks(state.modalAsset);
  wireModalShareActions(state.modalAsset);
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
  if (state.actor && state.actor.role === "owner") return true;
  const actorId = String(state.actor?.id || "").trim();
  const annActorId = String(ann.actor_id || "").trim();
  return !!actorId && !!annActorId && actorId === annActorId;
}

function canEditAssetNotes() {
  return !!(state.actor && state.actor.role === "owner");
}

function annotationActorClass(ann) {
  if (!ann || !ann.actor_name) return "";
  const actorId = String(state.actor?.id || "").trim();
  const annActorId = String(ann.actor_id || "").trim();
  if (state.actor?.role === "owner" && actorId && annActorId && actorId === annActorId) {
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
  state.annotations.forEach((ann, idx) => {
    const isQuestion = ann.annotation_type === "question";
    const isResolved = isQuestion && ann.resolved;
    const canManage = canManageAnnotation(ann);
    const el = document.createElement("div");
    el.className = `listItem annItem${state.activeAnnotationId === ann.id ? " active" : ""}${isQuestion ? " ann-question" : ""}${isResolved ? " ann-resolved" : ""}${canManage ? "" : " ann-readonly"}`;

    const marker = isQuestion ? "?" : `#${idx + 1}`;
    const actorCls = annotationActorClass(ann);
    const actorLabel = ann.actor_name ? `<span class="ann-actor ${actorCls}">${escapeHtml(ann.actor_name)}</span>` : "";
    const resolveBtn = isQuestion && state.actor && state.actor.role === "owner"
      ? `<button class="iconBtn ann-resolve" data-resolve="${ann.id}" title="${isResolved ? "Unresolve" : "Resolve"}" type="button">${isResolved ? "&#9745;" : "&#9744;"}</button>`
      : "";
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
  state.annotations.forEach((ann, idx) => {
    const isQuestion = ann.annotation_type === "question";
    const isResolved = isQuestion && ann.resolved;
    const canManage = canManageAnnotation(ann);
    const m = document.createElement("div");
    m.className = `marker${isQuestion ? " marker-question" : ""}${isResolved ? " marker-resolved" : ""}`;
    const pt = normalizedToStagePoint(ann.x, ann.y);
    m.style.left = `${pt.left}px`;
    m.style.top = `${pt.top}px`;
    m.dataset.id = ann.id;
    m.style.background = isQuestion ? "#e67e22" : markerColor(idx);
    const markerLabel = isQuestion ? "?" : `${idx + 1}`;
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
    // Check if "question mode" toggle is active
    const qToggle = $("#annQuestionToggle");
    const annotation_type = qToggle && qToggle.checked ? "question" : "note";
    const res = await api("/api/annotations", {
      method: "POST",
      body: JSON.stringify({ asset_id: state.modalAsset.id, x: point.x, y: point.y, text: "", annotation_type }),
    });
    state.annotations.push(res.annotation);
    setActiveAnnotation(res.annotation.id, { focusEditor: true });
    if (annotation_type === "question") refreshQuestionsIfOwner();
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
  const url = asset?.id ? `/media/${asset.id}?kind=original` : (asset?.image_url || "");
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
  win.document.open();
  win.document.write(`<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>${safeTitle || "Print"}</title>
    <style>
      html, body { margin: 0; padding: 0; background: #fff; }
      body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
      .toolbar { position: fixed; top: 8px; right: 8px; z-index: 2; }
      .toolbar button {
        border: 1px solid #bbb; background: #fff; color: #333;
        border-radius: 8px; padding: 6px 10px; cursor: pointer;
      }
      .frame {
        min-height: 100vh; display: flex; align-items: center; justify-content: center;
      }
      .frame img {
        display: block; max-width: 100%; max-height: 100vh; object-fit: contain;
      }
      @media print {
        .toolbar { display: none; }
      }
    </style>
  </head>
  <body>
    <div class="toolbar"><button type="button" onclick="window.print()">Print</button></div>
    <div class="frame">
      <img id="printImage" src="${safeUrl}" alt="Print item" />
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

async function enterReview() {
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
  state.reviewIndex = 0;
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
  if (irrelevantBtn) irrelevantBtn.disabled = false;
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
    const url = item.thumb_path ? `/media/${item.id}?kind=original`
                : item.stored_path ? `/media/${item.id}?kind=original`
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
  renderReviewClassificationPanel(item);

  // Update undo button
  const prevBtn = $("#reviewPrevBtn");
  if (prevBtn) prevBtn.disabled = state.reviewHistory.length === 0;
  const undoBtn = $("#reviewUndo");
  if (undoBtn) undoBtn.disabled = state.reviewHistory.length === 0;
}

function _incrementReviewDecisionCounter(kind) {
  if (kind === "keep_current") state.reviewKept += 1;
  else if (kind === "move") state.reviewMoved += 1;
  else if (kind === "irrelevant") state.reviewHidden += 1;
  else if (kind === "skip") state.reviewSkipped += 1;
}

function _decrementReviewDecisionCounter(kind) {
  if (kind === "keep_current") state.reviewKept = Math.max(0, state.reviewKept - 1);
  else if (kind === "move") state.reviewMoved = Math.max(0, state.reviewMoved - 1);
  else if (kind === "irrelevant") state.reviewHidden = Math.max(0, state.reviewHidden - 1);
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
        <span class="review-stat keeper">${state.reviewKept} kept current</span>
        <span class="review-stat moved">${state.reviewMoved} moved</span>
        <span class="review-stat hidden-s">${state.reviewHidden} irrelevant</span>
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
  if (browseView) browseView.classList.add("canvas-review-active");

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
      : "Review mode — click cards to select, then act on selection.",
    { type: "info" }
  );
}

function exitCanvasReview() {
  state.canvasReview = false;
  state.canvasSelected.clear();

  const browseView = $("#browseView");
  if (browseView) browseView.classList.remove("canvas-review-active");

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
  if (hideGlobalBtn) hideGlobalBtn.disabled = !hasSelection;
  const flagBtn = $("#canvasFlag");
  if (flagBtn) flagBtn.disabled = !(hasSelection && canUseFlag());
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
    Shared.showToast("No active collection scope. Use Hide globally for library-wide hide.", { type: "info" });
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
  if (!confirmGlobalHideBulk(ids.length)) return;
  try {
    await api("/api/assets/triage/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, status: "hidden" }),
    });
    Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} hidden.`, { type: "success" });
    clearCanvasSelection();
    await loadAssets();
  } catch (e) {
    Shared.showToast(`Bulk hide failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function canvasBulkFlag() {
  if (!canUseFlag()) {
    Shared.showToast("Flagging is owner-only.", { type: "info" });
    return;
  }
  const ids = Array.from(state.canvasSelected);
  if (!ids.length) return;
  try {
    await api("/api/assets/flag/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, flagged: 1 }),
    });
    ids.forEach((id) => {
      const a = state.assets.find((x) => x.id === id);
      if (a) a.flagged = 1;
    });
    Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} flagged for review.`, { type: "success" });
    clearCanvasSelection();
    renderGrid();
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
if (canvasFlagBtn) canvasFlagBtn.addEventListener("click", canvasBulkFlag);
const canvasTagBtn = $("#canvasTag");
if (canvasTagBtn) canvasTagBtn.addEventListener("click", canvasBulkTag);
const canvasClearBtn = $("#canvasClear");
if (canvasClearBtn) canvasClearBtn.addEventListener("click", clearCanvasSelection);
const canvasToOneByOneBtn = $("#canvasToOneByOne");
if (canvasToOneByOneBtn) canvasToOneByOneBtn.addEventListener("click", () => {
  exitCanvasReview();
  enterReview();
});
const canvasExitReviewBtn = $("#canvasExitReview");
if (canvasExitReviewBtn) canvasExitReviewBtn.addEventListener("click", exitCanvasReview);

// Review button — canvas review is the default
const reviewBtn = $("#reviewBtn");
if (reviewBtn) reviewBtn.addEventListener("click", enterCanvasReview);

const reviewBackBtn = $("#reviewBack");
if (reviewBackBtn) reviewBackBtn.addEventListener("click", exitReview);

const reviewSkipBtn = $("#reviewSkipBtn");
if (reviewSkipBtn) reviewSkipBtn.addEventListener("click", () => reviewAction("skip"));

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
    if (!$("#collectionBulkModal").classList.contains("hidden")) { closeCollectionBulkModal(); return; }
    if (!$("#mediaImportModal").classList.contains("hidden") && !isAnyImportBusy()) { closeMediaImportModal(); return; }
    if (!$("#scanImportModal").classList.contains("hidden") && !state.scanImportBusy) { closeScanImportModal(); return; }
    if (!$("#photoImportModal").classList.contains("hidden") && !state.photoImportBusy) { closePhotoImportModal(); return; }
    if (!$("#videoImportModal").classList.contains("hidden") && !state.videoImportBusy) { closeVideoImportModal(); return; }
    if (state.canvasReview) { exitCanvasReview(); return; }
    if (state.view === "review") { exitReview(); return; }
    return;
  }

  // Canvas review shortcuts
  if (state.canvasReview) {
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
        $$("[data-triage]").forEach((c) => {
          c.classList.toggle("active", c.dataset.triage === (params.triage_status || ""));
        });
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
      $$("[data-triage]").forEach((c) => {
        c.classList.toggle("active", c.dataset.triage === "");
      });
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
const explorerBusyOverlay = $("#explorerBusyOverlay");
const explorerBusyText = $("#explorerBusyText");

// Explorer implementations: 3D primary, with 2D fallback when unavailable.
const _Explorer2D = window.AttractorExplorer || window.Explorer || null;
let _explorerMode = "3d";   // "2d" | "3d"
let _ExplorerImpl = null;
let _disable3DForSession = false;
let _explorer3DLoadPromise = null;
const EXPLORER_3D_MODULE_URL = "/app/attractor-explorer-3d.js?v=39";
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

function _resolveExplorerImpl() {
  if (!_disable3DForSession) {
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
let _busyCursorDepth = 0;
let _explorerBusyDepth = 0;
let _explorerBusyStartedAt = 0;
let _explorerBusyToken = 0;
const EXPLORER_MIN_BUSY_MS = 280;

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
  return isOwner() && state.triageFilter === "hidden";
}

async function _loadExplorerPayload(mode, includeHidden) {
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
      return _merge3DExplorerData(layoutData, baseData);
    } catch (e) {
      console.warn("[Explorer] 3D layout request failed; using PCA fallback positions", e);
      return baseData;
    }
  }
  const data = await api(attractorUrl);
  _cachedExplorerAttractorData = data;
  _cachedExplorerAttractorDataIncludesHidden = includeHidden;
  return data;
}

function _resetExplorerViewInstance() {
  if (_ExplorerImpl && explorerLoaded && typeof _ExplorerImpl.destroy === "function") {
    _ExplorerImpl.destroy();
  }
  const container = document.getElementById("explorerContainer");
  if (container) container.innerHTML = "";
  explorerLoaded = false;
  explorerData = null;
  _explorerPayloadIncludesHidden = false;
}

function setViewMode(mode, options = {}) {
  const { persist = true } = options;
  if (mode === "explorer" && isReviewModeActive()) {
    Shared.showToast("Exit review mode before opening 3D Explorer.", { type: "info", duration: 3000 });
    return;
  }
  const browseView = $("#browseView");
  const explorerView = $("#explorerView");
  const sidebarEl = $("aside.sidebar");
  const layoutEl = $(".layout");

  if (mode === "explorer") {
    if (browseView) browseView.hidden = true;
    if (explorerView) explorerView.hidden = false;
    if (layoutEl) layoutEl.classList.add("explorer-active");
    if (viewGridBtn) viewGridBtn.classList.remove("active");
    if (viewExplorerBtn) viewExplorerBtn.classList.add("active");
    _writeViewModeToUrl("explorer");
    if (persist) _writeViewModePref("explorer");
    loadExplorerView();
  } else {
    if (browseView) browseView.hidden = false;
    if (explorerView) explorerView.hidden = true;
    if (layoutEl) layoutEl.classList.remove("explorer-active");
    if (viewGridBtn) viewGridBtn.classList.add("active");
    if (viewExplorerBtn) viewExplorerBtn.classList.remove("active");
    _writeViewModeToUrl("grid");
    if (persist) _writeViewModePref("grid");
    if (_ExplorerImpl && explorerLoaded) {
      _ExplorerImpl.pause();
    }
  }
}

async function loadExplorerView({ allow2DFallback = true } = {}) {
  // Load 3D code lazily when explorer is opened.
  // This avoids paying Three.js startup cost when the user stays in grid mode.
  await _ensureExplorer3DLoaded();

  const nextExplorer = _resolveExplorerImpl();
  const nextImpl = nextExplorer.impl;
  const implChanged = explorerLoaded && _ExplorerImpl && _ExplorerImpl !== nextImpl;
  _ExplorerImpl = nextImpl;
  _explorerMode = nextExplorer.mode;

  if (implChanged) _resetExplorerViewInstance();
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
    const data = await _loadExplorerPayload(_explorerMode, includeHidden);
    _setExplorerBusyOverlay(true, _explorerMode === "3d" ? "Arranging your 3D tiles…" : "Arranging your map…");
    await _nextPaint();
    explorerData = data;
    _explorerPayloadIncludesHidden = includeHidden;
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
      console.warn("[Explorer] 3D failed; switching to 2D fallback", e);
      _disable3DForSession = true;
      Shared.showToast("3D unavailable, switched to 2D fallback.", { type: "warning", duration: 3000 });
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
      _ExplorerImpl.setFilter(null);
      _explorerFilterCount = Array.isArray(explorerData?.assets) ? explorerData.assets.length : null;
      updateStats();
      return;
    }

    // Chat-curated items: highlight only those IDs
    if (state.chatItemIds) {
      _ExplorerImpl.setFilter(state.chatItemIds);
      _explorerFilterCount = state.chatItemIds.length;
      updateStats();
      return;
    }

    const catalogFiles = getCatalogFilterFiles();
    if (catalogFiles.length) {
      const catalogParams = new URLSearchParams();
      for (const file of catalogFiles) catalogParams.append("file", file);
      const seq = ++_explorerFilterSeq;
      try {
        const data = await api(`/api/catalog/asset-ids?${catalogParams}`);
        if (seq !== _explorerFilterSeq) return; // stale
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
    if (state.currentClassificationAxis) params.set("classification_axis", state.currentClassificationAxis);
    if (state.currentClassificationValue) params.set("classification_value", state.currentClassificationValue);
    const collectionIds = getCollectionFilterIds();
    if (collectionIds.length) params.set("collection_id", collectionIds.join(","));
    if (state.triageFilter === "needs-comment") {
      params.set("needs_annotation", "1");
      if (isOwner()) params.set("include_hidden", "1");
    } else if (state.triageFilter === "hidden") {
      params.set("triage_status", "hidden");
      if (_shouldExplorerIncludeHiddenData()) params.set("include_hidden", "1");
    } else if (state.triageFilter === "flagged") {
      params.set("flagged", "1");
      if (isOwner()) params.set("include_hidden", "1");
    } else if (state.triageFilter) {
      params.set("triage_status", state.triageFilter);
    }

    const seq = ++_explorerFilterSeq;
    try {
      const data = await api(`/api/asset-ids?${params}`);
      if (seq !== _explorerFilterSeq) return; // stale
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
    const axisLabel = String(state.currentClassificationAxis || "").trim().replace(/_/g, " ");
    const scopeLabel = String(state.currentClassificationLabel || state.currentClassificationValue || axisLabel).trim();
    parts.push(`Browse: ${scopeLabel}`);
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
    const labels = { pending: "Pending", keeper: "Keepers", hidden: "Hidden", "needs-comment": "Needs comment", flagged: "Flagged" };
    parts.push(`Status: ${labels[state.triageFilter] || state.triageFilter}`);
  }

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
      clearBtn.hidden = true;
      clearBtn.disabled = true;
    }
  }
  bar.hidden = false;
}

const clearFilterBtn = $("#clearFilterSummary");
if (clearFilterBtn) clearFilterBtn.addEventListener("click", () => {
  if (!state.chatPrompt) return;
  state.q = "";
  state.chatPrompt = "";
  state.chatItemIds = null;
  updateFilterIndicator();
  loadAssets();
});

// ─── Search (driven entirely via Ask Dave now) ──────────────────────────────────

// ─── Load More ───────────────────────────────────────────────────────────────────

const loadMoreBtn = $("#loadMore");
if (loadMoreBtn) loadMoreBtn.addEventListener("click", () => loadAssets({ append: true }));

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

wireStatusChips();
wireSidebarToggle();
wireSidebarResize();

function isOwner() {
  return state.actor && state.actor.role === "owner";
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

function renderReviewSidebarSummary() {
  const section = $("#dynamicSidebarSection");
  const headingEl = $("#dynamicSidebarHeading");
  const content = $("#dynamicSidebarContent");
  if (!section || !headingEl || !content) return;
  const scope = getReviewScopeInfo();
  const modeLabel = state.view === "review" ? "One-by-one review" : "Grid review";
  const hiddenMarkup = _buildReviewHiddenMarkup();
  headingEl.textContent = "Review";
  content.innerHTML = `
    <div class="review-sidebar-summary">
      <div class="review-sidebar-row"><span class="muted">Scope</span><strong>${escapeHtml(scope.label || "Entire library")}</strong></div>
      <div class="review-sidebar-row"><span class="muted">Mode</span><strong>${escapeHtml(modeLabel)}</strong></div>
      ${hiddenMarkup}
      <div class="review-sidebar-note muted">Status filters apply to the current review scope. Normal browse folders are hidden while review is active.</div>
    </div>
  `;
  section.hidden = false;
}

function _buildReviewHiddenMarkup() {
  if (!isOwner() || !state.hiddenTree || !Number(state.hiddenTree.total || 0)) return "";
  const sources = Array.isArray(state.hiddenTree.sources) ? state.hiddenTree.sources : [];
  const rows = [
    `<div class="review-hidden-row"><span class="review-hidden-label">All hidden</span><span class="tree-count">${Number(state.hiddenTree.total || 0)}</span></div>`,
  ];
  for (const src of sources) {
    const sourceName = escapeHtml(sourceDisplayName(src.source) || String(src.source || ""));
    rows.push(
      `<div class="review-hidden-row review-hidden-source"><span class="review-hidden-label">${sourceName}</span><span class="tree-count">${Number(src.total || 0)}</span></div>`
    );
    for (const board of (src.boards || [])) {
      rows.push(
        `<div class="review-hidden-row review-hidden-board"><span class="review-hidden-label">${sourceName} / ${escapeHtml(String(board.board || ""))}</span><span class="tree-count">${Number(board.count || 0)}</span></div>`
      );
    }
  }
  return `
    <div class="review-hidden-section">
      <div class="review-sidebar-subtitle">Hidden</div>
      <div class="review-hidden-list">
        ${rows.join("")}
      </div>
    </div>
  `;
}

function updateSidebarModeVisibility() {
  const owner = isOwner();
  const inReview = owner && isReviewModeActive();
  const statusSection = $("#statusChips")?.closest(".sidebar-section");
  const treeSection = $("#catalogTree")?.closest(".sidebar-section");
  const collectionsSection = $("#collectionTree")?.closest(".sidebar-section");
  const collectionActionsSection = $("#newCollection")?.closest(".sidebar-section");

  if (statusSection) statusSection.hidden = !inReview;
  if (treeSection) treeSection.hidden = inReview;
  if (collectionsSection) collectionsSection.hidden = inReview;
  if (collectionActionsSection) collectionActionsSection.hidden = inReview;

  if (inReview) {
    renderReviewSidebarSummary();
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
  const addMediaEl = $("#addMedia");
  if (addMediaEl) addMediaEl.hidden = !owner;
  const adminEl = $(".adminLink");
  if (adminEl) adminEl.hidden = !owner;
  const manageCollectionsEl = $("#manageCollections");
  if (manageCollectionsEl) manageCollectionsEl.hidden = !owner;

  // Share context actions — available to authenticated actors only
  for (const id of ["modalShareLinkBtn", "modalShareEmailBtn", "modalShareMessageBtn"]) {
    const btn = document.getElementById(id);
    if (btn) btn.hidden = !state.actor;
  }
  const shareGroup = $("#modalShareGroup");
  if (shareGroup) shareGroup.hidden = !state.actor;

  // Modal flag/tag buttons — scoped by named owner permissions
  const flagBtnEl = $("#modalFlagBtn");
  if (flagBtnEl) flagBtnEl.hidden = !canUseFlag();
  const tagBtnEl = $("#modalTagBtn");
  if (tagBtnEl) tagBtnEl.hidden = !canUseTag();

  const canvasFlagBtnEl = $("#canvasFlag");
  if (canvasFlagBtnEl) canvasFlagBtnEl.hidden = !canUseFlag();
  const canvasTagBtnEl = $("#canvasTag");
  if (canvasTagBtnEl) canvasTagBtnEl.hidden = !canUseTag();

  // Annotation question toggle — available to all (collaborators ask questions)
  // Notes textarea — available to all

  // New collection button — owner-only
  const newCollBtn = $("#newCollection");
  if (newCollBtn) newCollBtn.hidden = !owner;
  updateReviewScopeChips();
  updateSidebarModeVisibility();
}

async function checkFlaggedCount() {
  if (!isOwner()) return;
  try {
    const data = await api("/api/assets?flagged=1&limit=1");
    const chip = $("#flaggedChip");
    if (chip) chip.hidden = !(data.assets && data.assets.length > 0);
  } catch { /* ignore */ }
}

(async () => {
  try {
    // Resolve current actor identity (magic link)
    try {
      const meData = await api("/api/me");
      state.actor = meData.actor || null;
    } catch { state.actor = null; }

    // Apply role-based visibility before rendering
    applyRoleVisibility();

    const collectionsPromise = loadCollections();
    const facetsPromise = loadFacets();
    const catalogTreePromise = loadCatalogTree();
    await collectionsPromise;
    _applyCollaboratorCollectionsDefaultScope();
    await loadAssets();
    await Promise.all([facetsPromise, catalogTreePromise]);
    const viewFromUrl = _readViewModeFromUrl();
    const hasContextLink = !!_contextLinkPayloadFromUrl();
    let preferredView = viewFromUrl || _readViewModePref();
    // Shared context links and collaborator entry should default to Grid unless
    // the URL explicitly requests a specific view.
    if (!viewFromUrl && (hasContextLink || isCollaboratorActor())) {
      preferredView = "grid";
    }
    if (preferredView === "explorer") {
      setViewMode("explorer", { persist: false });
    }
    await restoreContextLinkFromUrl();

    // Owner-only features: hidden tree + question polling + flagged check
    if (isOwner()) {
      loadHiddenTree();
      pollQuestions();
      state.questionPollTimer = setInterval(pollQuestions, 15000);
      checkFlaggedCount();
      window.addEventListener("focus", refreshQuestionsIfOwner);
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") refreshQuestionsIfOwner();
      });
    }
  } catch (e) {
    const grid = $("#grid");
    if (grid) grid.innerHTML = `<div class="empty-state">Unable to load: ${escapeHtml(formatApiError(e))}</div>`;
  }
})();
