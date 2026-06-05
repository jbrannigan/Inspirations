"""Build multi-hot feature vectors from structured metadata.

No external API calls — everything derived from existing DB data
(AI JSON, labels, board names, titles, SEO alt text).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from .db import Db

# ─── Canonical dimensions ────────────────────────────────────────────────────

ROOMS = [
    "bathroom", "kitchen", "bedroom", "living_room", "dining_room", "office",
    "laundry", "mudroom", "closet", "garage", "hallway", "foyer", "nursery",
    "basement", "attic", "pantry", "sunroom", "patio", "pool", "garden",
]

STYLES = [
    "modern", "contemporary", "traditional", "transitional", "farmhouse",
    "rustic", "coastal", "industrial", "mid_century", "scandinavian",
    "mediterranean", "craftsman", "colonial", "art_deco", "bohemian",
    "minimalist", "eclectic", "french_country", "spanish", "japanese",
]

MATERIALS = [
    "wood", "tile", "stone", "marble", "granite", "quartz", "concrete",
    "brick", "metal", "glass", "stainless_steel", "brass", "copper",
    "iron", "ceramic", "porcelain", "hardwood", "laminate", "vinyl",
    "leather", "fabric", "linen", "wallpaper", "stucco", "shiplap",
]

COLORS = [
    "white", "black", "gray", "brown", "beige", "blue", "green", "red",
    "yellow", "orange", "pink", "purple", "gold", "silver", "navy",
]

IMAGE_TYPES = ["interior", "exterior", "product", "plan", "document", "other"]

SOURCES = ["pinterest", "facebook", "houzz", "scan"]

ELEMENTS = [
    "cabinet", "countertop", "sink", "bathtub", "shower", "fireplace",
    "lighting", "window", "door", "shelving",
]

ALL_DIMS: list[str] = ROOMS + STYLES + MATERIALS + COLORS + IMAGE_TYPES + SOURCES + ELEMENTS
DIM_INDEX: dict[str, int] = {d: i for i, d in enumerate(ALL_DIMS)}
NUM_DIMS = len(ALL_DIMS)

# Category boundaries (for the frontend attractor chip groups)
CATEGORIES = {
    "rooms":      {"label": "Rooms",     "start": 0,  "count": len(ROOMS)},
    "styles":     {"label": "Styles",    "start": len(ROOMS), "count": len(STYLES)},
    "materials":  {"label": "Materials", "start": len(ROOMS) + len(STYLES), "count": len(MATERIALS)},
    "colors":     {"label": "Colors",    "start": len(ROOMS) + len(STYLES) + len(MATERIALS), "count": len(COLORS)},
    "image_type": {"label": "Type",      "start": len(ROOMS) + len(STYLES) + len(MATERIALS) + len(COLORS), "count": len(IMAGE_TYPES)},
    "source":     {"label": "Source",    "start": len(ROOMS) + len(STYLES) + len(MATERIALS) + len(COLORS) + len(IMAGE_TYPES), "count": len(SOURCES)},
    "elements":   {"label": "Elements",  "start": len(ROOMS) + len(STYLES) + len(MATERIALS) + len(COLORS) + len(IMAGE_TYPES) + len(SOURCES), "count": len(ELEMENTS)},
}

# Explorer v2 emphasizes the new corpus characterization first, while keeping
# a few legacy visual facets as secondary attractors for open-ended browsing.
EXPLORER_AXIS_SPECS: tuple[tuple[str, str], ...] = (
    ("track", "Track"),
    ("space_context", "Space Context"),
    ("subject_type", "Subject Type"),
    ("room", "Rooms"),
    ("product_focus", "Style Product Focus"),
    ("concern_domain", "Construction Concerns"),
    ("product_system_focus", "Construction Systems"),
)

EXPLORER_LEGACY_SPECS: tuple[tuple[str, str, list[str], float], ...] = (
    ("style_family", "Style", STYLES, 0.75),
    ("materials", "Materials", MATERIALS, 0.80),
    ("colors", "Colors", COLORS, 0.70),
)

_CLASSIFICATION_VALUE_LABELS = {
    "style_product_decor": "Style / Decor",
    "construction_concern": "Construction",
    "home_maintenance_diy": "Maintenance / DIY",
    "plans_code_permits": "Plans / Code / Permits",
    "site_exterior": "Site / Exterior",
    "non_spatial": "Non-Spatial",
    "full_space_scene": "Full Space Scene",
    "single_product": "Single Product",
    "material_finish": "Material / Finish",
    "architectural_detail": "Architectural Detail",
    "plan_drawing": "Plan / Drawing",
    "vignette_styling": "Vignette / Styling",
    "lighting_fixture": "Lighting",
    "laundry_room": "Laundry",
    "entryway": "Entry",
    "mep": "MEP",
    "zip_system": "ZIP System",
    "mid_century": "Mid-Century",
    "art_deco": "Art Deco",
    "french_country": "French Country",
    "spanish": "Spanish / Mission",
}

_CLASSIFICATION_VALUE_ORDER = {
    "track": ["style_product_decor", "construction_concern", "home_maintenance_diy", "irrelevant"],
    "space_context": ["interior_room", "outdoor_zone", "transition_space", "non_spatial"],
    "subject_type": [
        "full_space_scene",
        "vignette_styling",
        "single_product",
        "material_finish",
        "architectural_detail",
        "plan_drawing",
    ],
    "concern_domain": ["envelope", "mep", "plans_code_permits", "site_exterior", "structure"],
}

# ─── Alias maps ──────────────────────────────────────────────────────────────

_ROOM_ALIASES: dict[str, str] = {}
_ROOM_RAW = {
    "bathroom": ["bath", "master bath", "guest bath", "powder room", "half bath",
                 "ensuite", "master bathroom", "guest bathroom", "primary bath",
                 "primary bathroom", "bathrooms", "bath remodel"],
    "kitchen": ["kitchenette", "kitchen remodel", "kitchen design", "kitchens",
                "commercial kitchen", "outdoor kitchen"],
    "bedroom": ["master bedroom", "guest bedroom", "master suite", "primary bedroom",
                "bedrooms", "guest room", "kids room", "kids bedroom", "child's room",
                "children's room"],
    "living_room": ["living room", "family room", "great room", "den", "sitting room",
                    "living area", "front room", "tv room", "media room", "rec room",
                    "common area", "lounge"],
    "dining_room": ["dining room", "breakfast nook", "dining area", "eat-in kitchen",
                    "formal dining", "dining"],
    "office": ["home office", "study", "workspace", "work area"],
    "laundry": ["laundry room", "utility room", "utility"],
    "mudroom": ["mud room"],
    "closet": ["walk-in closet", "closets", "wardrobe", "dressing room"],
    "garage": ["carport", "workshop", "2-car garage"],
    "hallway": ["corridor", "hall", "landing"],
    "foyer": ["entry", "entryway", "vestibule", "entrance"],
    "nursery": ["baby room"],
    "basement": ["lower level"],
    "attic": ["loft", "attic space"],
    "pantry": ["butler's pantry", "walk-in pantry", "beverage area"],
    "sunroom": ["conservatory", "sun room"],
    "patio": ["deck", "porch", "terrace", "outdoor living", "outdoor", "outdoor space",
              "covered patio", "covered porch", "screened porch", "covered rear porch",
              "veranda", "balcony", "loggia", "pergola", "portico"],
    "pool": ["pool house", "pool area", "swimming pool"],
    "garden": ["yard", "backyard", "front yard", "landscaping", "landscape",
               "outdoor garden", "garden design", "courtyard"],
}

_STYLE_ALIASES: dict[str, str] = {}
_STYLE_RAW = {
    "modern": ["modernist", "ultra-modern"],
    "contemporary": [],
    "traditional": ["classic", "timeless"],
    "transitional": [],
    "farmhouse": ["modern farmhouse"],
    "rustic": ["cabin", "lodge", "log cabin"],
    "coastal": ["coastal calm", "beach", "nautical", "seaside"],
    "industrial": ["loft", "warehouse"],
    "mid_century": ["mid-century", "mid century modern", "mcm", "retro"],
    "scandinavian": ["scandi", "nordic"],
    "mediterranean": ["tuscan", "italian"],
    "craftsman": ["arts and crafts", "bungalow"],
    "colonial": ["french colonial", "georgian"],
    "art_deco": ["art nouveau", "deco"],
    "bohemian": ["boho", "eclectic bohemian"],
    "minimalist": ["minimal", "clean"],
    "eclectic": [],
    "french_country": ["country french", "french provincial", "provencal"],
    "spanish": ["spanish colonial", "hacienda", "mission"],
    "japanese": ["zen", "wabi-sabi", "asian", "japandi"],
}

_MATERIAL_ALIASES: dict[str, str] = {}
_MATERIAL_RAW = {
    "wood": ["hardwood", "softwood", "timber", "plywood", "oak", "walnut",
             "maple", "cherry", "pine", "cedar", "teak", "mahogany",
             "reclaimed wood", "bamboo", "butcher block"],
    "tile": ["ceramic tile", "cement tile", "cement tiles", "subway tile",
             "mosaic tile", "floor tile", "wall tile", "terracotta", "terra cotta",
             "encaustic"],
    "stone": ["limestone", "travertine", "sandstone", "slate", "flagstone",
              "bluestone", "fieldstone", "cobblestone", "natural stone"],
    "marble": ["carrara marble", "calacatta marble", "marble tile",
               "cultured marble"],
    "granite": ["granite countertop"],
    "quartz": ["quartzite", "engineered quartz", "silestone", "caesarstone"],
    "concrete": ["cement", "polished concrete", "concrete countertop"],
    "brick": ["brick veneer", "exposed brick", "whitewashed brick"],
    "metal": ["aluminum", "zinc", "pewter", "tin", "wrought iron",
              "black metal", "aged metal", "brushed nickel", "chrome",
              "oil-rubbed bronze", "antique brass", "polished nickel"],
    "glass": ["tempered glass", "frosted glass", "stained glass", "mirror",
              "glass tile"],
    "stainless_steel": ["stainless", "ss"],
    "brass": ["brass accents", "polished brass", "antique brass", "unlacquered brass"],
    "copper": ["aged copper", "copper patina"],
    "iron": ["cast iron", "wrought iron", "forged iron"],
    "ceramic": ["ceramics", "pottery", "porcelain tile"],
    "porcelain": ["porcelain tile", "china"],
    "hardwood": ["hardwood floor", "wood floor", "engineered hardwood"],
    "laminate": ["laminate flooring", "laminate countertop"],
    "vinyl": ["vinyl plank", "vinyl flooring", "lvp", "lvt"],
    "leather": ["faux leather", "vegan leather"],
    "fabric": ["textile", "upholstery", "linen", "cotton", "chenille",
               "velvet", "silk", "wool"],
    "linen": [],
    "wallpaper": ["wall covering", "grasscloth", "peel and stick"],
    "stucco": ["plaster", "venetian plaster", "lime wash", "limewash"],
    "shiplap": ["tongue and groove", "board and batten", "wainscoting",
                "beadboard", "paneling"],
}

_COLOR_ALIASES: dict[str, str] = {}
_COLOR_RAW = {
    "white": ["off-white", "cream", "ivory", "snow", "alabaster"],
    "black": ["charcoal", "ebony", "jet"],
    "gray": ["grey", "slate", "pewter", "ash", "silver gray", "dove"],
    "brown": ["chocolate", "espresso", "walnut", "mocha", "coffee", "tan", "taupe"],
    "beige": ["cream", "khaki", "sand", "oatmeal", "ecru", "latte", "nude",
              "champagne"],
    "blue": ["cobalt", "cerulean", "sky blue", "powder blue", "teal",
             "turquoise", "aqua", "robin egg"],
    "green": ["sage", "olive", "emerald", "mint", "forest green", "hunter green",
              "seafoam", "eucalyptus"],
    "red": ["crimson", "burgundy", "scarlet", "ruby", "wine", "cranberry",
            "terra cotta red", "rust"],
    "yellow": ["mustard", "lemon", "sunflower", "buttercup"],
    "orange": ["rust", "terracotta", "amber", "peach", "coral", "tangerine"],
    "pink": ["blush", "rose", "mauve", "fuchsia", "salmon", "dusty pink",
             "dusty rose", "millennial pink"],
    "purple": ["lavender", "plum", "violet", "lilac", "amethyst", "eggplant",
               "aubergine"],
    "gold": ["golden", "brass", "antique gold", "aged gold", "honey"],
    "silver": ["platinum", "nickel", "chrome", "metallic"],
    "navy": ["dark blue", "midnight blue", "indigo", "ink"],
}

_ELEMENT_ALIASES: dict[str, str] = {}
_ELEMENT_RAW = {
    "cabinet": ["cabinetry", "cabinets", "kitchen cabinet", "bathroom vanity",
                "vanity", "cupboard"],
    "countertop": ["counter", "counters", "worktop", "work surface"],
    "sink": ["basin", "farmhouse sink", "vessel sink", "undermount sink"],
    "bathtub": ["tub", "soaking tub", "clawfoot tub", "freestanding tub",
                "bath tub", "jetted tub"],
    "shower": ["shower head", "walk-in shower", "shower enclosure", "rain shower",
               "shower tile"],
    "fireplace": ["mantel", "hearth", "fire pit", "wood stove", "mantle"],
    "lighting": ["chandelier", "pendant", "sconce", "lamp", "light fixture",
                 "recessed lighting", "track lighting", "under cabinet lighting"],
    "window": ["window treatment", "curtain", "drape", "blind", "shade",
               "shutter", "skylight", "dormer"],
    "door": ["entry door", "front door", "barn door", "french door",
             "sliding door", "pocket door", "dutch door", "garage door"],
    "shelving": ["shelf", "shelves", "bookshelf", "bookcase", "floating shelf",
                 "built-in", "open shelving", "display shelf"],
}

# Board name → dimension mappings (for assets without AI analysis)
_BOARD_MAP: dict[str, list[tuple[str, float]]] = {
    # Direct room matches
    "bathroom": [("bathroom", 0.9)],
    "kitchen": [("kitchen", 0.9)],
    "bedroom": [("bedroom", 0.9)],
    "garden": [("garden", 0.8), ("patio", 0.4)],
    "door": [("door", 0.8)],
    "flooring": [("hardwood", 0.4), ("tile", 0.4)],
    "lighting": [("lighting", 0.8)],
    "furniture": [("shelving", 0.3)],
    "garage": [("garage", 0.9)],
    "paint": [("wallpaper", 0.3)],
    "brick": [("brick", 0.9)],
    "building": [("concrete", 0.3)],
    "house-plans": [("plan", 0.8)],
    "exercise": [],  # not home-design related
    "workout": [],
    "food": [],
    "for-the-home": [("interior", 0.5)],
    "products-i-love": [("product", 0.5)],
    "favorite-places-spaces": [("interior", 0.3)],
    "misc": [],
}


def _build_alias_map(canonical_list: list[str], raw_map: dict[str, list[str]]) -> dict[str, str]:
    """Invert a {canonical: [aliases]} map to {alias: canonical}."""
    out: dict[str, str] = {}
    for canon in canonical_list:
        out[canon] = canon
        for alias in raw_map.get(canon, []):
            out[alias.lower()] = canon
    return out


# Build all alias maps at import time
_ROOM_ALIASES = _build_alias_map(ROOMS, _ROOM_RAW)
_STYLE_ALIASES = _build_alias_map(STYLES, _STYLE_RAW)
_MATERIAL_ALIASES = _build_alias_map(MATERIALS, _MATERIAL_RAW)
_COLOR_ALIASES = _build_alias_map(COLORS, _COLOR_RAW)
_ELEMENT_ALIASES = _build_alias_map(ELEMENTS, _ELEMENT_RAW)

# Pre-compile word boundary patterns for canonical terms (for title matching)
_TITLE_PATTERNS: list[tuple[re.Pattern, str]] = []
for dim in ALL_DIMS:
    nice = dim.replace("_", " ")
    _TITLE_PATTERNS.append((re.compile(r"\b" + re.escape(nice) + r"\b", re.I), dim))


# ─── Vector building ─────────────────────────────────────────────────────────

def _normalize(raw: str, alias_map: dict[str, str]) -> str | None:
    """Map a raw value to its canonical dimension name."""
    cleaned = raw.strip().lower()
    if not cleaned:
        return None
    # Remove trailing numbers / suffixes like "bath 2", "bedroom #3"
    cleaned_base = re.sub(r"\s*[#]?\d+$", "", cleaned).strip()
    # 1. Exact match
    if cleaned in alias_map:
        return alias_map[cleaned]
    if cleaned_base in alias_map:
        return alias_map[cleaned_base]
    # 2. Check if raw contains a canonical name as substring
    for alias, canon in alias_map.items():
        if len(alias) >= 4 and alias in cleaned:
            return canon
    return None


def _set_dim(vec: list[float], dim_name: str, weight: float) -> None:
    """Set a dimension in the vector, capping at 1.0."""
    idx = DIM_INDEX.get(dim_name)
    if idx is not None:
        vec[idx] = min(1.0, vec[idx] + weight)


def _apply_ai_json(vec: list[float], ai_json: dict, weight: float = 1.0) -> None:
    """Extract features from a Gemini image/video analysis JSON."""
    # Rooms
    for raw in ai_json.get("rooms", []):
        canon = _normalize(raw, _ROOM_ALIASES)
        if canon:
            _set_dim(vec, canon, weight)

    # Styles
    for raw in ai_json.get("styles", []):
        canon = _normalize(raw, _STYLE_ALIASES)
        if canon:
            _set_dim(vec, canon, weight)

    # Materials
    for raw in ai_json.get("materials", []):
        canon = _normalize(raw, _MATERIAL_ALIASES)
        if canon:
            _set_dim(vec, canon, weight)

    # Colors
    for raw in ai_json.get("colors", []):
        canon = _normalize(raw, _COLOR_ALIASES)
        if canon:
            _set_dim(vec, canon, weight)

    # Elements
    for raw in ai_json.get("elements", []):
        canon = _normalize(raw, _ELEMENT_ALIASES)
        if canon:
            _set_dim(vec, canon, weight)

    # Image type
    img_type = ai_json.get("image_type", "").lower().strip()
    if img_type in DIM_INDEX:
        _set_dim(vec, img_type, weight)


def _apply_video_json(vec: list[float], vj: dict, weight: float = 0.9) -> None:
    """Extract features from video analysis JSON."""
    cat = (vj.get("category", "") or "").lower()
    if cat == "home_design":
        _set_dim(vec, "interior", weight * 0.5)
    elif cat == "construction":
        _set_dim(vec, "exterior", weight * 0.3)

    board = (vj.get("suggested_board", "") or "").lower()
    if board:
        # Try as room
        canon = _normalize(board, _ROOM_ALIASES)
        if canon:
            _set_dim(vec, canon, weight * 0.7)
        # Try as style
        canon = _normalize(board, _STYLE_ALIASES)
        if canon:
            _set_dim(vec, canon, weight * 0.7)
        # Try as material
        canon = _normalize(board, _MATERIAL_ALIASES)
        if canon:
            _set_dim(vec, canon, weight * 0.7)


def _apply_labels(vec: list[float], labels: list[str], weight: float = 0.8) -> None:
    """Map AI-generated labels to canonical dimensions."""
    for raw in labels:
        for alias_map in [_ROOM_ALIASES, _STYLE_ALIASES, _MATERIAL_ALIASES,
                          _COLOR_ALIASES, _ELEMENT_ALIASES]:
            canon = _normalize(raw, alias_map)
            if canon:
                _set_dim(vec, canon, weight)
                break


def _apply_board(vec: list[float], board: str, weight: float = 0.6) -> None:
    """Map board name to dimensions."""
    board_lower = board.strip().lower()
    if not board_lower:
        return

    # Check explicit board map first
    if board_lower in _BOARD_MAP:
        for dim_name, w in _BOARD_MAP[board_lower]:
            _set_dim(vec, dim_name, w)
        return

    # Try matching board as room/style/material/element
    for alias_map in [_ROOM_ALIASES, _STYLE_ALIASES, _MATERIAL_ALIASES, _ELEMENT_ALIASES]:
        canon = _normalize(board_lower, alias_map)
        if canon:
            _set_dim(vec, canon, weight)


def _apply_text(vec: list[float], text: str, weight: float = 0.3) -> None:
    """Extract dimension signals from title/description text (lowest confidence)."""
    if not text or len(text) < 3:
        return
    text_lower = text.lower()
    for pattern, dim_name in _TITLE_PATTERNS:
        if pattern.search(text_lower):
            _set_dim(vec, dim_name, weight)


def build_legacy_facet_memberships(
    db: Db,
    asset_ids: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, dict[str, set[str]]]:
    """Return Explorer legacy facet memberships keyed by asset ID.

    These are the Style/Material/Color signals used by the attractor map before
    PCA/IDF weighting. Keeping this extraction shared prevents the sidebar from
    drifting away from the Explorer categories.
    """
    selected_ids = {
        str(asset_id or "").strip()
        for asset_id in (asset_ids or [])
        if str(asset_id or "").strip()
    }
    params: list[str] = []
    where_sql = ""
    if selected_ids:
        placeholders = ",".join(["?"] * len(selected_ids))
        where_sql = f" where a.id in ({placeholders})"
        params.extend(sorted(selected_ids))

    assets = db.query(
        "select a.id, a.board, a.title, a.seo_alt_text, a.source_ref "
        f"from assets a{where_sql} order by a.id",
        tuple(params),
    )
    if not assets:
        return {}

    asset_id_set = {str(row["id"] or "").strip() for row in assets}

    if selected_ids:
        ai_rows = db.query(
            f"select asset_id, provider, json from asset_ai where asset_id in ({placeholders})",
            tuple(params),
        )
    else:
        ai_rows = db.query("select asset_id, provider, json from asset_ai")
    ai_by_asset: dict[str, list[tuple[str, dict]]] = {}
    for row in ai_rows:
        asset_id = str(row["asset_id"] or "").strip()
        if asset_id not in asset_id_set:
            continue
        try:
            parsed = json.loads(row["json"]) if isinstance(row["json"], str) else row["json"]
        except Exception:
            continue
        if isinstance(parsed, dict):
            ai_by_asset.setdefault(asset_id, []).append((str(row["provider"] or ""), parsed))

    if selected_ids:
        label_rows = db.query(
            f"select asset_id, label from asset_labels where asset_id in ({placeholders})",
            tuple(params),
        )
    else:
        label_rows = db.query("select asset_id, label from asset_labels")
    labels_by_asset: dict[str, list[str]] = {}
    for row in label_rows:
        asset_id = str(row["asset_id"] or "").strip()
        if asset_id not in asset_id_set:
            continue
        labels_by_asset.setdefault(asset_id, []).append(str(row["label"] or ""))

    memberships: dict[str, dict[str, set[str]]] = {}
    for asset in assets:
        aid = str(asset["id"] or "").strip()
        if not aid:
            continue
        legacy_vec = [0.0] * NUM_DIMS

        for provider, ai_json in ai_by_asset.get(aid, []):
            if provider == "gemini":
                _apply_ai_json(legacy_vec, ai_json, weight=1.0)
            elif provider == "gemini-video":
                _apply_video_json(legacy_vec, ai_json, weight=0.9)

        asset_labels = labels_by_asset.get(aid, [])
        if asset_labels:
            _apply_labels(legacy_vec, asset_labels, weight=0.8)

        board = asset["board"] or ""
        if board:
            _apply_board(legacy_vec, board, weight=0.6)

        title = asset["title"] or ""
        seo = asset["seo_alt_text"] or ""
        source_ref = asset["source_ref"] or ""
        title_fallback = _fallback_title_from_source_ref(title, source_ref)
        text = f"{title_fallback or title} {seo}".strip()
        if text and not ai_by_asset.get(aid):
            _apply_text(legacy_vec, text, weight=0.3)

        for category_key, _label, dim_names, _weight in EXPLORER_LEGACY_SPECS:
            for dim_name in dim_names:
                legacy_idx = DIM_INDEX.get(dim_name)
                if legacy_idx is not None and legacy_vec[legacy_idx] > 0:
                    memberships.setdefault(aid, {}).setdefault(category_key, set()).add(dim_name)

    return memberships


def _apply_high_df_idf(
    vectors: list[list[float]],
    dim_labels: list[str] | tuple[str, ...] | None = None,
    threshold_ratio: float = 0.5,
) -> dict[str, float]:
    """Downweight dimensions that appear in most items using log(N / df)."""
    if not vectors:
        return {}
    n = len(vectors)
    d = len(vectors[0]) if vectors[0] else 0
    if n <= 1 or d == 0:
        return {}
    labels = list(dim_labels or ALL_DIMS)
    if len(labels) < d:
        labels = labels + [f"dim_{i}" for i in range(len(labels), d)]

    dim_counts = [0] * d
    for vec in vectors:
        for i, v in enumerate(vec):
            if v > 0:
                dim_counts[i] += 1

    applied: dict[str, float] = {}
    for i, df in enumerate(dim_counts):
        if df <= 0:
            continue
        if (df / n) <= threshold_ratio:
            continue
        scale = math.log(n / df)
        if scale < 0:
            scale = 0.0
        if scale >= 1.0:
            continue
        for vec in vectors:
            if vec[i] > 0:
                vec[i] *= scale
        applied[labels[i]] = scale
    return applied


# ─── PCA projection ─────────────────────────────────────────────────────────

def _pca_2d(vectors: list[list[float]]) -> list[tuple[float, float]]:
    """Project feature vectors to 2D using PCA. Pure-Python fallback if sklearn unavailable."""
    n = len(vectors)
    if n == 0:
        return []
    d = len(vectors[0])

    # Try sklearn first
    try:
        from sklearn.decomposition import PCA
        import numpy as np
        arr = np.array(vectors, dtype=np.float32)
        pca = PCA(n_components=min(2, n, d), random_state=42)
        coords = pca.fit_transform(arr)
        if coords.shape[1] == 1:
            coords = np.column_stack([coords, np.zeros(n)])
        return [(float(coords[i, 0]), float(coords[i, 1])) for i in range(n)]
    except ImportError:
        pass

    # Pure-Python fallback: use first two dimensions with most variance
    if d < 2:
        return [(vectors[i][0] if d > 0 else 0.0, 0.0) for i in range(n)]

    # Compute mean
    mean = [0.0] * d
    for v in vectors:
        for j in range(d):
            mean[j] += v[j]
    for j in range(d):
        mean[j] /= n

    # Compute variance per dimension
    var = [0.0] * d
    for v in vectors:
        for j in range(d):
            diff = v[j] - mean[j]
            var[j] += diff * diff
    for j in range(d):
        var[j] /= n

    # Pick top-2 variance dimensions
    ranked = sorted(range(d), key=lambda j: var[j], reverse=True)
    d0, d1 = ranked[0], ranked[1]

    coords = []
    for v in vectors:
        coords.append((v[d0] - mean[d0], v[d1] - mean[d1]))
    return coords


def _normalize_coords(coords: list[tuple[float, float]], spread: float = 300.0) -> list[tuple[float, float]]:
    """Scale coordinates to ±spread range."""
    if not coords:
        return coords
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    max_range = max(max(xs) - min(xs), max(ys) - min(ys), 0.001)
    scale = spread / max_range
    cx = (max(xs) + min(xs)) / 2
    cy = (max(ys) + min(ys)) / 2
    return [((x - cx) * scale, (y - cy) * scale) for x, y in coords]


def _pca_3d(vectors: list[list[float]]) -> list[tuple[float, float, float]]:
    """Project feature vectors to 3D using PCA. Pure-Python fallback if sklearn unavailable."""
    n = len(vectors)
    if n == 0:
        return []
    d = len(vectors[0])

    try:
        from sklearn.decomposition import PCA
        import numpy as np
        arr = np.array(vectors, dtype=np.float32)
        pca = PCA(n_components=min(3, n, d), random_state=42)
        coords = pca.fit_transform(arr)
        # Pad to 3 columns if fewer components
        if coords.shape[1] < 3:
            pad = np.zeros((n, 3 - coords.shape[1]))
            coords = np.hstack([coords, pad])
        return [(float(coords[i, 0]), float(coords[i, 1]), float(coords[i, 2])) for i in range(n)]
    except ImportError:
        pass

    # Pure-Python fallback: top-3 variance dimensions
    if d < 3:
        return [(vectors[i][0] if d > 0 else 0.0,
                 vectors[i][1] if d > 1 else 0.0,
                 0.0) for i in range(n)]

    mean = [sum(v[j] for v in vectors) / n for j in range(d)]
    var = [sum((v[j] - mean[j]) ** 2 for v in vectors) / n for j in range(d)]
    ranked = sorted(range(d), key=lambda j: var[j], reverse=True)
    d0, d1, d2 = ranked[0], ranked[1], ranked[2]
    return [(v[d0] - mean[d0], v[d1] - mean[d1], v[d2] - mean[d2]) for v in vectors]


def _normalize_coords_3d(
    coords: list[tuple[float, float, float]], spread: float = 300.0
) -> list[tuple[float, float, float]]:
    """Scale 3D coordinates to ±spread range."""
    if not coords:
        return coords
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    zs = [c[2] for c in coords]
    max_range = max(
        max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 0.001
    )
    scale = spread / max_range
    cx = (max(xs) + min(xs)) / 2
    cy = (max(ys) + min(ys)) / 2
    cz = (max(zs) + min(zs)) / 2
    return [((x - cx) * scale, (y - cy) * scale, (z - cz) * scale) for x, y, z in coords]


_FB_SAVED_LINK_TITLE_RE = re.compile(r"^\s*[^.]+ saved a link from (.+?)'s post\.?\s*$", re.IGNORECASE)


def _title_case_words(text: str) -> str:
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    out: list[str] = []
    for w in words:
        if len(w) <= 2:
            out.append(w.upper())
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def _fallback_title_from_source_ref(title: str, source_ref: str) -> str:
    t = (title or "").strip()
    m = _FB_SAVED_LINK_TITLE_RE.match(t)
    if not m:
        return ""
    source_name = (m.group(1) or "").strip()
    ref = (source_ref or "").strip()
    if not ref:
        return f"{source_name} link" if source_name else ""
    try:
        parsed = urlparse(ref)
        host = (parsed.hostname or "").replace("www.", "")
        path = unquote(parsed.path or "")
        parts = [p for p in path.split("/") if p]
        slug = parts[-1] if parts else ""
        slug = re.sub(r"\.[a-z0-9]{2,5}$", "", slug, flags=re.IGNORECASE)
        slug = re.sub(r"[-_+]+", " ", slug)
        slug = re.sub(r"[^a-z0-9 ]+", " ", slug, flags=re.IGNORECASE)
        slug = re.sub(r"\s+", " ", slug).strip()
        if slug and not slug.isdigit():
            pretty = _title_case_words(slug)
            if source_name:
                return f"{source_name}: {pretty}"
            return pretty
        if source_name:
            return f"{source_name} link"
        if host:
            return _title_case_words(host.replace(".", " "))
    except Exception:
        if source_name:
            return f"{source_name} link"
    return ""


def _latest_classification_run_id(db: Db, run_type: str) -> str:
    return str(
        db.query_value(
            "select id from classification_runs where run_type=? order by created_at desc limit 1",
            (str(run_type or "").strip(),),
        )
        or ""
    ).strip()


def _classification_value_label(axis_name: str, axis_value: str) -> str:
    axis = str(axis_name or "").strip().lower()
    value = str(axis_value or "").strip().lower()
    if not value:
        return ""
    if value in _CLASSIFICATION_VALUE_LABELS:
        return _CLASSIFICATION_VALUE_LABELS[value]
    if axis == "product_system_focus" and value.endswith("_system"):
        return value.replace("_", " ").title()
    return value.replace("_", " ").title()


def _ordered_classification_values(axis_name: str, values: set[str]) -> list[str]:
    order = _CLASSIFICATION_VALUE_ORDER.get(axis_name, [])
    rank = {value: idx for idx, value in enumerate(order)}
    return sorted(
        {str(value or "").strip() for value in values if str(value or "").strip()},
        key=lambda value: (rank.get(value, len(rank)), _classification_value_label(axis_name, value)),
    )


def _legacy_dim_label(dim_name: str) -> str:
    value = str(dim_name or "").strip().lower()
    if not value:
        return ""
    if value in _CLASSIFICATION_VALUE_LABELS:
        return _CLASSIFICATION_VALUE_LABELS[value]
    return value.replace("_", " ").title()


def _confidence_weight(raw_value: object, *, default: float = 0.9) -> float:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = default
    if value <= 0:
        value = default
    return max(0.25, min(1.0, value))


def _load_classification_memberships(
    db: Db,
    asset_ids: list[str],
) -> tuple[str, str, dict[str, list[tuple[str, float]]], dict[str, dict[str, list[tuple[str, float]]]], dict[str, set[str]]]:
    asset_id_set = {str(asset_id or "").strip() for asset_id in asset_ids if str(asset_id or "").strip()}
    track_run_id = _latest_classification_run_id(db, "track_gate")
    axis_run_id = _latest_classification_run_id(db, "multi_axis_inference")
    track_by_asset: dict[str, list[tuple[str, float]]] = {}
    axis_by_asset: dict[str, dict[str, list[tuple[str, float]]]] = {}
    axis_values_by_axis: dict[str, set[str]] = {axis_name: set() for axis_name, _ in EXPLORER_AXIS_SPECS}
    axis_names = {axis_name for axis_name, _ in EXPLORER_AXIS_SPECS if axis_name != "track"}

    if track_run_id:
        for row in db.query(
            "select asset_id, track, confidence from asset_track_assessments where run_id=?",
            (track_run_id,),
        ):
            asset_id = str(row["asset_id"] or "").strip()
            track = str(row["track"] or "").strip()
            if not asset_id or asset_id not in asset_id_set or not track:
                continue
            confidence = _confidence_weight(row["confidence"], default=0.95)
            track_by_asset.setdefault(asset_id, []).append((track, confidence))
            axis_values_by_axis["track"].add(track)

    if axis_run_id:
        for row in db.query(
            "select asset_id, axis_name, axis_value, confidence from asset_axis_memberships where run_id=?",
            (axis_run_id,),
        ):
            asset_id = str(row["asset_id"] or "").strip()
            axis_name = str(row["axis_name"] or "").strip()
            axis_value = str(row["axis_value"] or "").strip()
            if (
                not asset_id
                or asset_id not in asset_id_set
                or axis_name not in axis_names
                or not axis_value
            ):
                continue
            confidence = _confidence_weight(row["confidence"], default=0.85)
            axis_values_by_axis.setdefault(axis_name, set()).add(axis_value)
            axis_by_asset.setdefault(asset_id, {}).setdefault(axis_name, []).append((axis_value, confidence))

    return track_run_id, axis_run_id, track_by_asset, axis_by_asset, axis_values_by_axis


def _build_explorer_dimensions(
    axis_values_by_axis: dict[str, set[str]],
) -> tuple[list[str], dict[str, dict[str, int | str]], dict[int, str], dict[tuple[str, str], int], dict[tuple[str, str], int]]:
    dimensions: list[str] = []
    categories: dict[str, dict[str, int | str]] = {}
    dim_labels: dict[int, str] = {}
    classification_lookup: dict[tuple[str, str], int] = {}
    legacy_lookup: dict[tuple[str, str], int] = {}

    def _add_category(category_key: str, label: str, items: list[tuple[str, str]]) -> None:
        if not items:
            return
        start = len(dimensions)
        categories[category_key] = {"label": label, "start": start, "count": len(items)}
        for dim_name, dim_label in items:
            idx = len(dimensions)
            dimensions.append(dim_name)
            dim_labels[idx] = dim_label

    for axis_name, label in EXPLORER_AXIS_SPECS:
        values = _ordered_classification_values(axis_name, axis_values_by_axis.get(axis_name, set()))
        items = [(f"{axis_name}:{value}", _classification_value_label(axis_name, value)) for value in values]
        start = len(dimensions)
        _add_category(axis_name, label, items)
        for offset, value in enumerate(values):
            classification_lookup[(axis_name, value)] = start + offset

    for category_key, label, dim_names, _weight in EXPLORER_LEGACY_SPECS:
        start = len(dimensions)
        items = [(f"{category_key}:{dim_name}", _legacy_dim_label(dim_name)) for dim_name in dim_names]
        _add_category(category_key, label, items)
        for offset, dim_name in enumerate(dim_names):
            legacy_lookup[(category_key, dim_name)] = start + offset

    return dimensions, categories, dim_labels, classification_lookup, legacy_lookup


# ─── Main entry point ────────────────────────────────────────────────────────

def build_feature_vectors(
    db: Db,
    data_dir: Path | None = None,
    dims: int = 2,
    include_hidden: bool = False,
) -> dict:
    """Build feature vectors for all assets. Returns payload for the frontend."""
    # 1. Load asset rows, excluding hidden unless explicitly requested.
    params: list = []
    where_sql = ""
    if not include_hidden:
        hidden_col_id = db.query_value(
            "select id from collections where lower(name)='hidden' limit 1"
        )
        hide_clauses = ["(a.triage_status is null or a.triage_status != 'hidden')"]
        if hidden_col_id:
            hide_clauses.append(
                "a.id not in (select asset_id from collection_items where collection_id = ?)"
            )
            params.append(hidden_col_id)
        where_sql = " where " + " and ".join(hide_clauses)
    assets = db.query(
        "select a.id, a.source, a.board, a.title, a.seo_alt_text, a.thumb_path, a.ai_summary, a.source_ref "
        f"from assets a{where_sql} order by a.id",
        tuple(params),
    )
    if not assets:
        return {"dimensions": [], "categories": {}, "assets": [], "attractors": {}}

    asset_ids = [a["id"] for a in assets]
    (
        track_run_id,
        axis_run_id,
        track_by_asset,
        axis_by_asset,
        axis_values_by_axis,
    ) = _load_classification_memberships(db, asset_ids)
    explorer_dims, explorer_categories, explorer_dim_labels, classification_lookup, legacy_lookup = (
        _build_explorer_dimensions(axis_values_by_axis)
    )
    if not explorer_dims:
        return {"dimensions": [], "categories": {}, "assets": [], "attractors": {}}

    # 2. Load AI JSON
    ai_rows = db.query("select asset_id, provider, json from asset_ai")
    ai_by_asset: dict[str, list[tuple[str, dict]]] = {}
    for row in ai_rows:
        try:
            parsed = json.loads(row["json"]) if isinstance(row["json"], str) else row["json"]
        except Exception:
            continue
        ai_by_asset.setdefault(row["asset_id"], []).append((row["provider"], parsed))

    # 3. Load labels
    label_rows = db.query("select asset_id, label from asset_labels")
    labels_by_asset: dict[str, list[str]] = {}
    for row in label_rows:
        labels_by_asset.setdefault(row["asset_id"], []).append(row["label"])

    # 4. Build vectors
    vectors: list[list[float]] = []
    node_list: list[dict] = []
    node_meta: list[dict] = []

    for asset in assets:
        aid = asset["id"]
        vec = [0.0] * len(explorer_dims)
        legacy_vec = [0.0] * NUM_DIMS

        for track, confidence in track_by_asset.get(aid, []):
            idx = classification_lookup.get(("track", track))
            if idx is not None:
                vec[idx] = max(vec[idx], confidence)
        for axis_name, memberships in axis_by_asset.get(aid, {}).items():
            for axis_value, confidence in memberships:
                idx = classification_lookup.get((axis_name, axis_value))
                if idx is not None:
                    vec[idx] = max(vec[idx], confidence)

        # Source is still exposed as a separate explorer chip group, but not as a
        # semantic dimension. That keeps the layout driven by corpus meaning
        # instead of clustering by import source.
        src = (asset["source"] or "").lower()

        # AI analysis and text-derived legacy facets
        for provider, ai_json in ai_by_asset.get(aid, []):
            if provider == "gemini":
                _apply_ai_json(legacy_vec, ai_json, weight=1.0)
            elif provider == "gemini-video":
                _apply_video_json(legacy_vec, ai_json, weight=0.9)

        # Labels
        asset_labels = labels_by_asset.get(aid, [])
        if asset_labels:
            _apply_labels(legacy_vec, asset_labels, weight=0.8)

        # Board name
        board = asset["board"] or ""
        if board:
            _apply_board(legacy_vec, board, weight=0.6)

        # Title / SEO alt text (lowest priority)
        title = asset["title"] or ""
        seo = asset["seo_alt_text"] or ""
        source_ref = asset["source_ref"] or ""
        title_fallback = _fallback_title_from_source_ref(title, source_ref)
        text_title = title_fallback or title
        text = f"{text_title} {seo}".strip()
        if text and not ai_by_asset.get(aid):
            # Only use text extraction for assets without AI analysis
            _apply_text(legacy_vec, text, weight=0.3)

        for category_key, _label, dim_names, weight in EXPLORER_LEGACY_SPECS:
            for dim_name in dim_names:
                legacy_idx = DIM_INDEX.get(dim_name)
                explorer_idx = legacy_lookup.get((category_key, dim_name))
                if legacy_idx is None or explorer_idx is None:
                    continue
                legacy_weight = legacy_vec[legacy_idx]
                if legacy_weight > 0:
                    vec[explorer_idx] = max(vec[explorer_idx], legacy_weight * weight)

        vectors.append(vec)

        thumb = f"/media/{aid}?kind=thumb" if asset["thumb_path"] else ""
        display_title = title_fallback or title or asset["ai_summary"] or board or ""
        if len(display_title) > 80:
            display_title = display_title[:77] + "..."

        node_meta.append({
            "id": aid,
            "t": thumb,
            "title": display_title,
            "src": src,
        })

    # 5. IDF downweighting for high-frequency dimensions
    _apply_high_df_idf(vectors, dim_labels=explorer_dims, threshold_ratio=0.5)

    # Build sparse vectors for transport (only non-zero entries)
    for i, meta in enumerate(node_meta):
        sparse: dict[str, float] = {}
        for dim_idx, value in enumerate(vectors[i]):
            if value > 0:
                sparse[str(dim_idx)] = round(value, 2)
        node_list.append({
            "id": meta["id"],
            "v": sparse,
            "t": meta["t"],
            "title": meta["title"],
            "src": meta["src"],
        })

    # 6. PCA for initial positions (2D or 3D)
    if dims == 3:
        coords_3d = _pca_3d(vectors)
        coords_3d = _normalize_coords_3d(coords_3d, spread=350.0)
        for i, node in enumerate(node_list):
            node["x"] = round(coords_3d[i][0], 1)
            node["y"] = round(coords_3d[i][1], 1)
            node["z"] = round(coords_3d[i][2], 1)
    else:
        coords = _pca_2d(vectors)
        coords = _normalize_coords(coords, spread=350.0)
        for i, node in enumerate(node_list):
            node["x"] = round(coords[i][0], 1)
            node["y"] = round(coords[i][1], 1)

    # 7. Compute attractor options (dims with enough items to be useful)
    dim_counts = [0] * len(explorer_dims)
    for vec in vectors:
        for i, v in enumerate(vec):
            if v > 0:
                dim_counts[i] += 1

    attractors: dict[str, list[dict]] = {}
    for cat_key, cat_info in explorer_categories.items():
        start = cat_info["start"]
        count = cat_info["count"]
        options = []
        for offset in range(count):
            idx = start + offset
            dim_name = explorer_dims[idx]
            cnt = dim_counts[idx]
            if cnt >= 3:  # Only show dimensions with at least 3 items
                nice_name = explorer_dim_labels.get(idx, dim_name.replace("_", " ").title())
                options.append({"dim": idx, "name": nice_name, "count": cnt})
        options.sort(key=lambda x: x["count"], reverse=True)
        if options:
            attractors[cat_key] = options

    # 8. Cache result
    if data_dir:
        data_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256(
            (
                f"{','.join(sorted(asset_ids))}:dims={dims}:include_hidden={int(include_hidden)}:"
                f"track_run={track_run_id}:axis_run={axis_run_id}:idf=v2"
            ).encode()
        ).hexdigest()[:16]
        cache_file = data_dir / f"attractors_{cache_key}.json"
        payload = {
            "dimensions": explorer_dims,
            "categories": {
                k: {"label": v["label"], "start": v["start"], "count": v["count"]}
                for k, v in explorer_categories.items()
            },
            "assets": node_list,
            "attractors": attractors,
        }
        try:
            cache_file.write_text(json.dumps(payload))
        except Exception:
            pass
        return payload

    return {
        "dimensions": explorer_dims,
        "categories": {
            k: {"label": v["label"], "start": v["start"], "count": v["count"]}
            for k, v in explorer_categories.items()
        },
        "assets": node_list,
        "attractors": attractors,
    }
