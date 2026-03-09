from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .db import Db


TRACK_STYLE = "style_product_decor"
TRACK_CONSTRUCTION = "construction_concern"
TRACK_MAINTENANCE = "home_maintenance_diy"
TRACK_IRRELEVANT = "irrelevant"
TRACK_LABELS = {TRACK_STYLE, TRACK_CONSTRUCTION, TRACK_MAINTENANCE, TRACK_IRRELEVANT}

SCHEMA_VERSION = "curation_v2"
DEFAULT_TRACK_GATE_MODEL = "provenance_weighted_track_gate_v1"

IRRELEVANT_HINTS = (
    "recipe",
    "recipes",
    "food",
    "meal",
    "vitamin",
    "supplement",
    "supplements",
    "granola",
    "salad",
    "pickle",
    "nail",
    "nails",
    "workout",
    "exercise",
    "fitness",
    "makeup",
    "cosmetic",
    "beauty",
    "haircare",
    "skincare",
    "pet",
    "dog",
    "cat",
    "cleaning",
    "mopping",
    "lifehack",
    "lifehacks",
    "moving furniture",
    "stripped screw",
    "household products",
    "problem-solving products",
    "lamp assembly",
    "woodworking",
    "joinery",
    "carpentry",
    "advertisement",
    "football",
    "off grid",
    "water pump",
    "stained grout",
    "diy project",
    "bug out bag",
    "emergency preparedness",
    "survival gear",
    "disaster kit",
    "prepper",
    "container gardening",
    "potting mix",
    "diy gardening",
)

IRRELEVANT_FITNESS_HINTS = (
    "workout",
    "exercise",
    "fitness",
    "gym",
    "pilates",
    "yoga",
    "kettlebell",
    "crossfit",
)

IRRELEVANT_PERSONAL_CARE_HINTS = (
    "makeup",
    "beauty",
    "haircare",
    "skincare",
    "cosmetic",
    "cosmetics",
    "eyeshadow",
    "eye makeup",
    "makeup tutorial",
    "eyebrow",
    "eyebrows",
    "salon",
    "nail",
    "nails",
)

MAINTENANCE_HINTS = (
    "home repair",
    "maintenance issue",
    "drywall repair",
    "wall repair",
    "patching",
    "drywall patch",
    "water damage",
    "water stains",
    "ceiling damage",
    "roof leak",
    "cracked concrete",
    "concrete repair",
    "rainwater collection",
    "rainwater harvesting",
    "rain barrel",
    "downspout",
    "downspouts",
    "gutter",
    "gutters",
    "gutter detail",
    "gutter system",
    "water conservation",
)

CONSTRUCTION_REFERENCE_HINTS = (
    "rainwater collection",
    "rainwater harvesting",
    "rainwater harvesting system",
    "rain barrel",
    "underground tank",
    "first flush chamber",
    "water filters",
    "leaf eater guards",
    "downspout leaf filter",
    "leaf filter",
    "drainage system",
    "garage floor",
    "epoxy coating",
    "garage floor coating",
    "anti-skid material",
    "epoxyshield",
)

STYLE_DIY_REFERENCE_HINTS = (
    "color drenching",
    "painting tips",
    "paint color",
    "door casing",
    "wall colors",
    "wall color",
    "interior paint",
    "painted doors",
)

STYLE_LANDSCAPE_REFERENCE_HINTS = (
    "landscaping",
    "landscape design",
    "garden design",
    "perennial",
    "verbena",
    "grow list",
)

CONSTRUCTION_HINTS = (
    "construction",
    "builder",
    "building",
    "house plan",
    "floor plan",
    "site plan",
    "blueprint",
    "foundation",
    "framing",
    "stud",
    "studs",
    "insulation",
    "spray foam",
    "hvac",
    "plumbing",
    "electrical",
    "wiring",
    "roof",
    "roofing",
    "drainage",
    "waterproof",
    "masonry",
    "slab",
    "lumber",
    "grading",
    "site prep",
    "permit",
    "building code",
    "structural",
    "septic",
    "well",
    "generator",
    "flashing",
    "vapor barrier",
    "zip system",
    "sheathing",
    "osb",
    "unfinished",
    "membrane",
    "duct",
    "truss",
    "rebar",
    "water heater",
    "tankless",
    "window system",
    "door detail",
    "inspection",
    "specification",
)

STYLE_HINTS = (
    "kitchen",
    "bathroom",
    "bedroom",
    "living room",
    "family room",
    "dining room",
    "entryway",
    "foyer",
    "mudroom",
    "laundry room",
    "pantry",
    "cabinet",
    "cabinetry",
    "backsplash",
    "vanity",
    "shower",
    "bathtub",
    "toilet",
    "sink",
    "faucet",
    "range",
    "refrigerator",
    "dishwasher",
    "sofa",
    "chair",
    "banquette",
    "nightstand",
    "headboard",
    "fireplace",
    "wallpaper",
    "lighting",
    "pendant",
    "sconce",
    "furniture",
    "decor",
    "styling",
    "interior",
    "exterior",
    "landscape",
    "garden",
    "patio",
    "porch",
    "cottage",
    "farmhouse",
    "traditional",
    "scandinavian",
    "white oak",
    "marble",
    "brass",
    "tile",
    "upholstery",
    "millwork",
    "trim",
    "powder room",
)

STYLE_REFERENCE_BOARD_HINTS = (
    "house-plans",
    "house-plans-with-attached-guest-house",
    "products-i-love",
    "favorite-places-spaces",
    "ikea-hacks",
)

STYLE_REFERENCE_PLAN_HINTS = (
    "floor plan",
    "floorplan",
    "house plan",
    "site layout",
    "property layout",
    "residential plan",
    "house layout",
    "residential layout",
    "residential design",
    "architectural drawing",
    "architectural model",
    "exterior rendering",
)

STYLE_REFERENCE_DETAIL_HINTS = (
    "built-in",
    "cabinetry",
    "shelving",
    "brick stain",
    "brick treatment",
    "brick wash",
    "whitewash",
    "color palette",
    "color swatches",
    "paint swatches",
    "color chart",
    "brick samples",
    "samples",
    "material",
    "architectural model",
    "herringbone pattern",
    "wood floor",
    "flooring installation",
    "entryway",
    "brick facade",
    "house exterior",
    "landscape design",
    "outdoor living",
)

STYLE_REFERENCE_BLOCKER_HINTS = (
    "permit",
    "building code",
    "inspection",
    "checklist",
    "must-have",
    "must-haves",
    "electrical",
    "hvac",
    "plumbing",
    "insulation",
    "waterproof",
    "foundation",
    "framing",
    "drainage",
    "french drain",
    "structural",
    "rebar",
    "flashing",
    "zip system",
    "water heater",
    "tankless",
    "repair",
    "water damage",
    "roof leak",
    "maintenance issue",
    "maintenance",
)

STYLE_COLOR_REFERENCE_HINTS = (
    "color palette",
    "color swatches",
    "paint swatches",
    "color chart",
    "paint color",
    "paint colors",
    "neutral colors",
    "greige",
)

MAGAZINE_CLIP_STYLE_HINTS = (
    "leslie's magazine clips",
    "leslies magazine clips",
)

IRRELEVANT_HARDWARE_REFERENCE_HINTS = (
    "hardware guide",
    "fasteners",
    "machine screws",
    "hex bolts",
    "carriage bolts",
    "eye bolts",
    "engineering",
)

IRRELEVANT_GARDENING_MISFIRE_HINTS = (
    "container gardening",
    "diy gardening",
    "potting mix",
    "planter",
)

TITLE_ORIGIN_WEIGHTS = {
    "title_audit": 0.95,
    "source_native": 0.8,
    "imported": 0.55,
    "ai_suggested": 0.45,
    "derived": 0.3,
}

TEXT_FIELD_BASE_WEIGHTS = {
    "board": 1.15,
    "title": 0.95,
    "description": 0.7,
    "notes": 0.8,
    "ai_summary": 0.45,
}

SOURCE_PRIORS = {
    "pinterest": (TRACK_STYLE, 0.22),
    "houzz": (TRACK_STYLE, 0.18),
}

VIDEO_CATEGORY_MAP = {
    "home_design": (TRACK_STYLE, 1.0),
    "product_review": (TRACK_STYLE, 0.45),
    "construction": (TRACK_CONSTRUCTION, 1.4),
    "diy": (TRACK_MAINTENANCE, 0.3),
    "irrelevant": (TRACK_IRRELEVANT, 1.4),
}

DEFAULT_AXIS_MODEL = "heuristic_multi_axis_v1"

ROOM_ALIASES = {
    "living": "living_room",
    "living room": "living_room",
    "family room": "living_room",
    "bath": "bathroom",
    "dining": "dining_room",
    "dining room": "dining_room",
    "entry": "entryway",
    "foyer": "entryway",
    "laundry": "laundry_room",
    "laundry room": "laundry_room",
    "mud": "mudroom",
    "mud room": "mudroom",
    "outdoor": "landscape",
    "garden": "landscape",
}

ROOM_HINTS: dict[str, tuple[str, ...]] = {
    "kitchen": ("kitchen", "backsplash", "cabinet", "pantry", "range hood"),
    "bathroom": ("bathroom", "vanity", "shower", "bathtub", "toilet", "powder room"),
    "bedroom": ("bedroom", "nightstand", "headboard", "bed"),
    "living_room": ("living room", "family room", "sofa", "fireplace", "daybed"),
    "dining_room": ("dining room", "dining", "breakfast nook", "banquette", "dining table"),
    "entryway": ("entryway", "foyer", "entry", "vestibule"),
    "mudroom": ("mudroom", "locker bench"),
    "laundry_room": ("laundry", "washer", "dryer"),
    "garage": ("garage",),
    "exterior": ("exterior", "facade", "curb appeal", "porch", "siding", "front elevation"),
    "landscape": ("landscape", "garden", "patio", "yard", "outdoor", "deck", "pool"),
}

SPACE_CONTEXT_HINTS: dict[str, tuple[str, ...]] = {
    "interior_room": (
        "kitchen",
        "bathroom",
        "bedroom",
        "living room",
        "dining room",
        "mudroom",
        "laundry room",
        "entryway",
        "interior",
    ),
    "outdoor_zone": ("outdoor", "patio", "garden", "yard", "porch", "deck", "pool", "landscape", "exterior"),
    "transition_space": ("entryway", "foyer", "hall", "hallway", "stair", "landing", "vestibule", "mudroom"),
    "whole_home": ("whole home", "house tour", "home tour", "entire home", "full house"),
    "non_spatial": ("product", "fixture", "appliance", "material", "finish", "close-up", "swatch", "document"),
}

SUBJECT_TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "full_space_scene": (
        "kitchen",
        "bathroom",
        "bedroom",
        "living room",
        "dining room",
        "entryway",
        "mudroom",
        "laundry room",
        "porch",
        "patio",
        "garden",
        "landscape",
        "room",
        "space",
    ),
    "vignette_styling": ("styled", "styling", "vignette", "shelf styling", "table setting", "corner"),
    "single_product": (
        "sink",
        "faucet",
        "toilet",
        "tub",
        "range",
        "refrigerator",
        "dishwasher",
        "pendant",
        "sconce",
        "chandelier",
        "hardware",
        "appliance",
        "fixture",
    ),
    "material_finish": ("tile", "paint", "fabric", "wallpaper", "flooring", "wood", "marble", "stone", "finish"),
    "architectural_detail": ("trim", "millwork", "molding", "fireplace surround", "arch", "ceiling beam", "built-in"),
    "plan_drawing": ("plan", "floor plan", "blueprint", "elevation", "section", "drawing"),
}

FUNCTION_HINTS: dict[str, tuple[str, ...]] = {
    "dining": ("dining", "breakfast nook", "banquette", "table setting", "table"),
    "cooking": ("kitchen", "range", "stove", "oven", "hood", "pantry", "prep"),
    "sleeping": ("bedroom", "bed", "headboard", "nightstand"),
    "bathing": ("bathroom", "vanity", "shower", "bathtub", "toilet", "powder room"),
    "storage": ("storage", "cabinet", "shelving", "closet", "pantry", "drawer"),
    "circulation": ("hallway", "entryway", "foyer", "stair", "landing", "corridor"),
    "utility": ("laundry", "mudroom", "washer", "dryer", "garage", "utility"),
    "entertaining": ("living room", "family room", "bar", "media room", "patio", "outdoor fireplace"),
}

PRODUCT_FOCUS_HINTS: dict[str, tuple[str, ...]] = {
    "range": ("range", "stove", "oven", "range cooker"),
    "refrigerator": ("refrigerator", "fridge"),
    "dishwasher": ("dishwasher",),
    "sink": ("sink", "farmhouse sink"),
    "toilet": ("toilet",),
    "tub": ("tub", "bathtub"),
    "faucet": ("faucet", "tap"),
    "lighting_fixture": ("lighting", "pendant", "sconce", "chandelier", "lantern"),
    "vanity": ("vanity",),
    "hardware": ("hardware", "cabinet pull", "knob", "drawer pull"),
}

CONCERN_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "inspection_quality_control": (
        "inspection",
        "inspector",
        "inspectors",
        "home inspection",
        "independent inspection",
        "rough-in inspection",
        "pre-drywall inspection",
        "final inspection",
        "walkthrough inspection",
        "builder walkthrough",
        "quality control",
    ),
    "site_exterior": (
        "grading",
        "drainage",
        "site prep",
        "erosion",
        "lot",
        "landscape drainage",
        "well",
        "septic",
        "rainwater collection",
        "rainwater harvesting",
        "rain barrel",
        "underground tank",
        "first flush chamber",
        "water conservation",
    ),
    "envelope": ("roof", "siding", "window", "door", "waterproof", "insulation", "flashing", "zip system", "sheathing", "membrane"),
    "structure": ("foundation", "framing", "structural", "beam", "load bearing", "slab", "truss", "rebar"),
    "mep": ("hvac", "plumb", "plumbing", "electrical", "wiring", "mechanical", "duct", "water heater", "tankless", "generator"),
    "plans_code_permits": ("permit", "code", "plan", "blueprint", "specification", "drawing", "zoning", "hoa"),
    "interiors_execution": (
        "tile layout",
        "cabinet install",
        "trim detail",
        "finish schedule",
        "millwork",
        "paint schedule",
        "hardware schedule",
        "garage floor",
        "epoxy coating",
        "garage floor coating",
        "anti-skid material",
        "floor coating",
    ),
}

PROJECT_PHASE_HINTS: dict[str, tuple[str, ...]] = {
    "concept": ("concept", "idea", "reference", "inspiration", "vision"),
    "design": ("design", "detail", "selection", "specification", "spec", "layout"),
    "permit_code": ("permit", "code", "inspection", "zoning", "hoa"),
    "procurement": ("quote", "vendor", "order", "lead time", "procurement", "price"),
    "build": ("build", "construction", "install", "framing", "rough-in", "waterproof", "site prep", "pour"),
    "commissioning_closeout": ("punch", "walkthrough", "closeout", "maintenance", "service"),
}

TRADE_SYSTEM_HINTS: dict[str, tuple[str, ...]] = {
    "structural": ("foundation", "framing", "beam", "load bearing", "truss", "rebar", "slab"),
    "envelope": ("roof", "roofing", "siding", "window", "door", "flashing", "waterproof", "zip system", "sheathing", "insulation", "membrane"),
    "mechanical": ("hvac", "heat pump", "furnace", "air handler", "duct"),
    "electrical": ("electrical", "wiring", "panel", "outlet", "generator"),
    "plumbing": ("plumbing", "plumb", "drain", "water heater", "tankless", "septic", "well"),
    "site": (
        "grading",
        "erosion",
        "site prep",
        "lot",
        "drainage",
        "landscape drainage",
        "rainwater collection",
        "rainwater harvesting",
        "rain barrel",
        "underground tank",
        "first flush chamber",
    ),
    "millwork_finish": (
        "cabinet",
        "trim",
        "tile",
        "paint",
        "millwork",
        "finish schedule",
        "flooring",
        "garage floor",
        "epoxy coating",
        "garage floor coating",
        "anti-skid material",
        "floor coating",
    ),
}

CONCERN_CLASS_HINTS: dict[str, tuple[str, ...]] = {
    "risk": ("risk", "problem", "issue", "failure", "leak", "moisture", "mold", "budget"),
    "decision": ("choose", "selection", "option", "decision", "worth it", "should we"),
    "requirement": ("must", "required", "need to", "code requires", "requirement"),
    "checklist": ("checklist", "must-have", "dont forget", "don't forget", "things to ask", "things to remember"),
    "reference_example": ("example", "reference", "how-to", "explained", "case study"),
}

PRODUCT_SYSTEM_HINTS: dict[str, tuple[str, ...]] = {
    "water_heater": ("water heater",),
    "tankless_water_heater": ("tankless water heater", "tankless"),
    "zip_system": ("zip system", "zipsheathing", "zip sheathing", "zip-r sheathing", "zip r sheathing"),
    "window_system": ("window system", "windows", "window detail", "window"),
    "door_system": ("door system", "door detail", "door frame", "door sill", "fire-rated door", "door"),
    "garage_door_system": ("garage door",),
    "siding_system": ("siding", "vinyl siding", "house siding"),
    "flashing_system": ("flashing", "flashing tape"),
    "sheathing_system": ("sheathing", "osb", "insulated sheathing"),
    "waterproofing_membrane": ("waterproofing membrane", "membrane", "waterproof"),
    "insulation_system": ("insulation", "rockwool", "spray foam"),
    "roofing_system": ("roof", "roofing", "roof system", "shingle", "metal roof"),
    "roof_vent_system": ("roof vent",),
    "duct_system": ("duct", "ductwork"),
}


@dataclass
class EvidenceContribution:
    track: str
    evidence_type: str
    evidence_ref: str
    weight: float
    confidence: float
    note: str


@dataclass
class AxisEvidence:
    axis_name: str
    axis_value: str
    evidence_type: str
    evidence_ref: str
    weight: float
    confidence: float
    note: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _csv_values(value: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in str(value or "").split(","):
        v = raw.strip()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _normalize_label(text: str) -> str:
    cleaned = _normalize_space(text).lower().strip(" ,.;:!#*()[]{}<>\"'")
    if len(cleaned) < 2:
        return ""
    return cleaned


def _labels_from_csv(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(value or "").split("|"):
        label = _normalize_label(raw)
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out


def _dedupe_labels(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        label = _normalize_label(raw)
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out


def _safe_json_object(text: Any) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _coerce_float(value: Any, default: float) -> float:
    try:
        out = float(value)
    except Exception:
        out = float(default)
    if out < 0.0:
        return 0.0
    if out > 1.0:
        return 1.0
    return out


def _contains_hint(text: str, hint: str) -> bool:
    haystack = text.lower()
    needle = hint.lower()
    if " " in needle:
        return needle in haystack
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


def _matching_hints(text: str, hints: tuple[str, ...]) -> list[str]:
    haystack = _normalize_space(text).lower()
    if not haystack:
        return []
    out: list[str] = []
    for hint in hints:
        if _contains_hint(haystack, hint):
            out.append(hint)
    return out


def _filter_irrelevant_matches(candidate: dict[str, Any], matches: list[str]) -> list[str]:
    filtered = _dedupe_labels(matches)
    if not filtered:
        return []
    context_text = _candidate_context_text(candidate)
    if context_text and _matching_hints(context_text, STYLE_COLOR_REFERENCE_HINTS):
        filtered = [match for match in filtered if match != "beauty"]
    return filtered


def _field_weight(candidate: dict[str, Any], field_name: str) -> float:
    base = TEXT_FIELD_BASE_WEIGHTS.get(field_name, 0.5)
    if field_name != "title":
        return base
    origin_type = str(candidate.get("title_origin_type") or "").strip().lower()
    origin_confidence = candidate.get("title_origin_confidence")
    try:
        conf = float(origin_confidence)
    except Exception:
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    provenance_weight = TITLE_ORIGIN_WEIGHTS.get(origin_type, 0.4)
    return base * max(0.25, provenance_weight) * max(0.35, conf)


def _add_contribution(
    scores: Counter[str],
    evidence: list[EvidenceContribution],
    *,
    track: str,
    evidence_type: str,
    evidence_ref: str,
    weight: float,
    confidence: float,
    note: str,
) -> None:
    weight = round(float(weight), 4)
    confidence = max(0.0, min(1.0, float(confidence)))
    if weight <= 0:
        return
    scores[track] += weight
    evidence.append(
        EvidenceContribution(
            track=track,
            evidence_type=evidence_type,
            evidence_ref=evidence_ref,
            weight=weight,
            confidence=round(confidence, 4),
            note=_normalize_space(note),
        )
    )


def _score_text_field(
    *,
    candidate: dict[str, Any],
    field_name: str,
    text: str,
    scores: Counter[str],
    evidence: list[EvidenceContribution],
) -> None:
    cleaned = _normalize_space(text)
    if not cleaned:
        return
    field_weight = _field_weight(candidate, field_name)
    style_matches = _matching_hints(cleaned, STYLE_HINTS)
    construction_matches = _matching_hints(cleaned, CONSTRUCTION_HINTS)
    maintenance_matches = _matching_hints(cleaned, MAINTENANCE_HINTS) if field_name != "ai_summary" else []
    irrelevant_matches = _filter_irrelevant_matches(candidate, _matching_hints(cleaned, IRRELEVANT_HINTS))
    if style_matches:
        conf = min(0.95, 0.55 + 0.08 * len(style_matches))
        _add_contribution(
            scores,
            evidence,
            track=TRACK_STYLE,
            evidence_type="field_text",
            evidence_ref=f"field:{field_name}",
            weight=field_weight * conf,
            confidence=conf,
            note=f"{field_name} matched style terms: {', '.join(style_matches[:6])}",
        )
    if construction_matches:
        conf = min(0.98, 0.58 + 0.08 * len(construction_matches))
        _add_contribution(
            scores,
            evidence,
            track=TRACK_CONSTRUCTION,
            evidence_type="field_text",
            evidence_ref=f"field:{field_name}",
            weight=field_weight * conf,
            confidence=conf,
            note=f"{field_name} matched construction terms: {', '.join(construction_matches[:6])}",
        )
    if maintenance_matches:
        conf = min(0.95, 0.58 + 0.08 * len(maintenance_matches))
        _add_contribution(
            scores,
            evidence,
            track=TRACK_MAINTENANCE,
            evidence_type="field_text",
            evidence_ref=f"field:{field_name}",
            weight=field_weight * conf,
            confidence=conf,
            note=f"{field_name} matched maintenance terms: {', '.join(maintenance_matches[:6])}",
        )
    if irrelevant_matches:
        conf = min(0.95, 0.6 + 0.08 * len(irrelevant_matches))
        weight_multiplier = 2.8 if field_name == "title" else 1.0
        _add_contribution(
            scores,
            evidence,
            track=TRACK_IRRELEVANT,
            evidence_type="field_text",
            evidence_ref=f"field:{field_name}",
            weight=field_weight * conf * weight_multiplier,
            confidence=conf,
            note=f"{field_name} matched irrelevant terms: {', '.join(irrelevant_matches[:6])}",
        )


def _score_labels(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    labels = candidate.get("labels") or []
    if not labels:
        return
    joined = " | ".join(str(x) for x in labels)
    style_matches = _matching_hints(joined, STYLE_HINTS)
    construction_matches = _matching_hints(joined, CONSTRUCTION_HINTS)
    irrelevant_matches = _filter_irrelevant_matches(candidate, _matching_hints(joined, IRRELEVANT_HINTS))
    if style_matches:
        conf = min(0.98, 0.62 + 0.07 * len(style_matches))
        _add_contribution(
            scores,
            evidence,
            track=TRACK_STYLE,
            evidence_type="asset_label",
            evidence_ref="asset_labels",
            weight=0.7 * conf,
            confidence=conf,
            note=f"labels matched style terms: {', '.join(style_matches[:8])}",
        )
    if construction_matches:
        conf = min(0.98, 0.64 + 0.07 * len(construction_matches))
        _add_contribution(
            scores,
            evidence,
            track=TRACK_CONSTRUCTION,
            evidence_type="asset_label",
            evidence_ref="asset_labels",
            weight=0.7 * conf,
            confidence=conf,
            note=f"labels matched construction terms: {', '.join(construction_matches[:8])}",
        )
    if irrelevant_matches:
        conf = min(0.95, 0.64 + 0.07 * len(irrelevant_matches))
        _add_contribution(
            scores,
            evidence,
            track=TRACK_IRRELEVANT,
            evidence_type="asset_label",
            evidence_ref="asset_labels",
            weight=0.65 * conf,
            confidence=conf,
            note=f"labels matched irrelevant terms: {', '.join(irrelevant_matches[:8])}",
        )


def _score_ai_payload(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    payload = candidate.get("ai_payload") or {}
    if not payload:
        return
    provider = str(candidate.get("ai_provider") or "").strip().lower()
    asset_ai_id = str(candidate.get("asset_ai_id") or "").strip() or provider or "asset_ai"
    evidence_ref = f"asset_ai:{asset_ai_id}"

    if provider == "gemini-video":
        category = _normalize_label(str(payload.get("category") or ""))
        mapped = VIDEO_CATEGORY_MAP.get(category)
        if mapped:
            track, base_weight = mapped
            _add_contribution(
                scores,
                evidence,
                track=track,
                evidence_type="asset_ai_json",
                evidence_ref=evidence_ref,
                weight=base_weight,
                confidence=_coerce_float(payload.get("confidence"), 0.75),
                note=f"video category={category}",
            )
        relevant = payload.get("relevant_to_home_design")
        if relevant is False:
            _add_contribution(
                scores,
                evidence,
                track=TRACK_IRRELEVANT,
                evidence_type="asset_ai_json",
                evidence_ref=evidence_ref,
                weight=0.9,
                confidence=_coerce_float(payload.get("confidence"), 0.75),
                note="video analysis marked not relevant to home design",
            )
        style_buckets = []
        for key in ("styles",):
            values = [_normalize_label(str(x)) for x in (payload.get(key) or []) if _normalize_label(str(x))]
            if values:
                style_buckets.extend(values)
        if style_buckets:
            _add_contribution(
                scores,
                evidence,
                track=TRACK_STYLE,
                evidence_type="asset_ai_json",
                evidence_ref=evidence_ref,
                weight=0.65,
                confidence=0.7,
                note=f"video analysis captured design facets: {', '.join(style_buckets[:6])}",
            )
        return

    image_type = _normalize_label(str(payload.get("image_type") or ""))
    if image_type in {"interior", "exterior", "product"}:
        _add_contribution(
            scores,
            evidence,
            track=TRACK_STYLE,
            evidence_type="asset_ai_json",
            evidence_ref=evidence_ref,
            weight=1.0 if image_type != "product" else 0.9,
            confidence=0.82,
            note=f"vision image_type={image_type}",
        )
    elif image_type == "plan":
        _add_contribution(
            scores,
            evidence,
            track=TRACK_CONSTRUCTION,
            evidence_type="asset_ai_json",
            evidence_ref=evidence_ref,
            weight=1.15,
            confidence=0.86,
            note="vision image_type=plan",
        )

    style_bucket_values: list[str] = []
    for key in ("rooms", "styles", "fixtures", "appliances"):
        for item in payload.get(key) or []:
            label = _normalize_label(str(item))
            if label:
                style_bucket_values.append(label)
    if style_bucket_values:
        _add_contribution(
            scores,
            evidence,
            track=TRACK_STYLE,
            evidence_type="asset_ai_json",
            evidence_ref=evidence_ref,
            weight=0.85,
            confidence=0.78,
            note=f"vision structured style evidence: {', '.join(style_bucket_values[:8])}",
        )

    construction_text = " ".join(
        _normalize_label(str(item))
        for key in ("text_in_image", "tags", "elements", "brands_products")
        for item in (payload.get(key) or [])
    )
    construction_matches = _matching_hints(construction_text, CONSTRUCTION_HINTS)
    if construction_matches:
        conf = min(0.95, 0.66 + 0.07 * len(construction_matches))
        _add_contribution(
            scores,
            evidence,
            track=TRACK_CONSTRUCTION,
            evidence_type="asset_ai_json",
            evidence_ref=evidence_ref,
            weight=0.65 * conf,
            confidence=conf,
            note=f"vision text/tags matched construction terms: {', '.join(construction_matches[:8])}",
        )
        if image_type in {"interior", "exterior"}:
            _add_contribution(
                scores,
                evidence,
                track=TRACK_CONSTRUCTION,
                evidence_type="asset_ai_json",
                evidence_ref=evidence_ref,
                weight=0.72,
                confidence=0.8,
                note=f"construction scene override for image_type={image_type}",
            )


def _score_source_prior(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    source = str(candidate.get("source") or "").strip().lower()
    mapped = SOURCE_PRIORS.get(source)
    if not mapped:
        return
    track, weight = mapped
    _add_contribution(
        scores,
        evidence,
        track=track,
        evidence_type="source_prior",
        evidence_ref=f"source:{source}",
        weight=weight,
        confidence=0.4,
        note=f"source prior for {source}",
    )


def _score_diy_irrelevant_override(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    category = _normalize_label(str(candidate.get("category") or ""))
    payload = candidate.get("ai_payload") or {}
    video_category = _normalize_label(str(payload.get("category") or ""))
    if category != "diy" and video_category != "diy":
        return

    generic_matches: list[str] = []
    for _, text in _candidate_text_fields(candidate):
        generic_matches.extend(_matching_hints(text, IRRELEVANT_HINTS))
    for label in candidate.get("labels") or []:
        generic_matches.extend(_matching_hints(label, IRRELEVANT_HINTS))
    for key in ("text_in_image", "tags", "elements", "brands_products", "materials"):
        for value in _payload_values(payload, key):
            generic_matches.extend(_matching_hints(value, IRRELEVANT_HINTS))

    unique_matches: list[str] = []
    seen: set[str] = set()
    for match in generic_matches:
        if match not in seen:
            seen.add(match)
            unique_matches.append(match)
    if not unique_matches:
        return

    weight = 0.52 + 0.1 * min(4, len(unique_matches))
    if any(
        match in {"cleaning", "mopping", "lifehack", "lifehacks", "moving furniture", "stripped screw", "household products", "water stain", "stained grout"}
        for match in unique_matches
    ):
        weight += 0.38
    _add_contribution(
        scores,
        evidence,
        track=TRACK_IRRELEVANT,
        evidence_type="diy_override",
        evidence_ref="diy_irrelevant_context",
        weight=weight,
        confidence=min(0.96, 0.7 + 0.04 * len(unique_matches)),
        note=f"diy context matched generic/non-home terms: {', '.join(unique_matches[:8])}",
    )


def _score_strong_irrelevant_visual_override(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    raw_context = " | ".join(
        _normalize_space(text)
        for field_name, text in _candidate_text_fields(candidate)
        if field_name != "ai_summary" and _normalize_space(text)
    )
    payload = candidate.get("ai_payload") or {}
    ai_parts = [str(candidate.get("ai_summary") or "").strip()]
    for key in ("summary", "actual_content"):
        ai_parts.append(str(payload.get(key) or "").strip())
    for key in ("text_in_image", "tags", "elements", "brands_products"):
        ai_parts.extend(_payload_values(payload, key))
    ai_context = " | ".join(part for part in ai_parts if part)
    if not raw_context or not ai_context:
        return

    raw_fitness = _matching_hints(raw_context, IRRELEVANT_FITNESS_HINTS)
    ai_fitness = _matching_hints(ai_context, IRRELEVANT_FITNESS_HINTS)
    raw_personal = _matching_hints(raw_context, IRRELEVANT_PERSONAL_CARE_HINTS)
    ai_personal = _matching_hints(ai_context, IRRELEVANT_PERSONAL_CARE_HINTS)

    matched: list[str] = []
    label = ""
    if raw_fitness and ai_fitness:
        matched.extend(_dedupe_labels(raw_fitness + ai_fitness))
        label = "exercise/personal fitness"
    if raw_personal and ai_personal:
        matched.extend(_dedupe_labels(raw_personal + ai_personal))
        label = "personal care/beauty" if not label else f"{label} + personal care/beauty"
    matched = _dedupe_labels(matched)
    if not matched:
        return

    _add_contribution(
        scores,
        evidence,
        track=TRACK_IRRELEVANT,
        evidence_type="strong_irrelevant_override",
        evidence_ref="raw_plus_visual_irrelevant",
        weight=min(2.6, 1.8 + 0.08 * len(matched)),
        confidence=min(0.98, 0.86 + 0.02 * len(matched)),
        note=f"raw + visual evidence agree on {label or 'non-home content'}: {', '.join(matched[:8])}",
    )


def _score_strong_irrelevant_intent_override(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    fields = {
        "board": _normalize_space(str(candidate.get("board") or "")),
        "title": _normalize_space(str(candidate.get("title") or "")),
        "description": _normalize_space(str(candidate.get("description") or "")),
        "notes": _normalize_space(str(candidate.get("notes") or "")),
    }
    if not any(fields.values()):
        return

    color_reference = bool(_matching_hints(_candidate_context_text(candidate), STYLE_COLOR_REFERENCE_HINTS))
    fitness_hits = [(name, _matching_hints(text, IRRELEVANT_FITNESS_HINTS)) for name, text in fields.items() if text]
    personal_hits = [(name, _matching_hints(text, IRRELEVANT_PERSONAL_CARE_HINTS)) for name, text in fields.items() if text]
    fitness_fields = [(name, matches) for name, matches in fitness_hits if matches]
    personal_fields = [(name, matches) for name, matches in personal_hits if matches]

    label = ""
    matched: list[str] = []
    field_names: list[str] = []
    if len(fitness_fields) >= 2:
        label = "exercise/personal fitness intent"
        field_names.extend(name for name, _ in fitness_fields)
        for _, matches in fitness_fields:
            matched.extend(matches)
    if len(personal_fields) >= 2:
        personal_matches = _dedupe_labels(match for _, matches in personal_fields for match in matches)
        if not (color_reference and set(personal_matches).issubset({"beauty"})):
            label = "personal care/beauty intent" if not label else f"{label} + personal care/beauty intent"
            field_names.extend(name for name, _ in personal_fields)
            matched.extend(personal_matches)

    matched = _dedupe_labels(matched)
    field_names = _dedupe_labels(field_names)
    if not matched or not field_names:
        return

    _add_contribution(
        scores,
        evidence,
        track=TRACK_IRRELEVANT,
        evidence_type="strong_irrelevant_override",
        evidence_ref="raw_intent_irrelevant",
        weight=min(2.25, 1.45 + 0.12 * len(field_names) + 0.06 * len(matched)),
        confidence=min(0.97, 0.84 + 0.03 * len(field_names)),
        note=f"raw intent strongly indicates {label or 'non-home content'} across {', '.join(field_names[:4])}: {', '.join(matched[:8])}",
    )


def _score_asset_category(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    category = _normalize_label(str(candidate.get("category") or ""))
    if not category:
        return
    if category == "other":
        _add_contribution(
            scores,
            evidence,
            track=TRACK_IRRELEVANT,
            evidence_type="asset_category",
            evidence_ref="assets.category",
            weight=0.55,
            confidence=0.65,
            note="assets.category=other",
        )
    elif category in {"construction", "diy"}:
        track = TRACK_MAINTENANCE if category == "diy" else TRACK_CONSTRUCTION
        weight = 0.28 if category == "diy" else 0.95
        _add_contribution(
            scores,
            evidence,
            track=track,
            evidence_type="asset_category",
            evidence_ref="assets.category",
            weight=weight,
            confidence=0.78,
            note=f"assets.category={category}",
        )
    elif category in {"home_design", "product_review"}:
        source = str(candidate.get("source") or "").strip().lower()
        weight = 0.08 if source == "facebook" else 0.22
        _add_contribution(
            scores,
            evidence,
            track=TRACK_STYLE,
            evidence_type="asset_category",
            evidence_ref="assets.category",
            weight=weight,
            confidence=0.65,
            note=f"assets.category={category}",
        )


def _candidate_context_text(candidate: dict[str, Any]) -> str:
    parts = [text for _, text in _candidate_text_fields(candidate)]
    parts.extend(str(label or "") for label in (candidate.get("labels") or []))
    payload = candidate.get("ai_payload") or {}
    for key in ("rooms", "styles", "fixtures", "appliances", "brands_products", "elements", "tags", "materials", "text_in_image"):
        parts.extend(_payload_values(payload, key))
    return " | ".join(_normalize_space(part) for part in parts if _normalize_space(part))


def _score_construction_reference_override(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    context_text = _candidate_context_text(candidate)
    if not context_text:
        return
    matches = _dedupe_labels(_matching_hints(context_text, CONSTRUCTION_REFERENCE_HINTS))
    if not matches:
        return

    weight = 1.45 + 0.12 * min(6, len(matches))
    if any(match in {"rainwater collection", "rainwater harvesting", "rainwater harvesting system", "rain barrel", "underground tank", "first flush chamber"} for match in matches):
        weight += 0.45
    if any(match in {"garage floor", "epoxy coating", "garage floor coating", "anti-skid material", "epoxyshield"} for match in matches):
        weight += 0.4
    _add_contribution(
        scores,
        evidence,
        track=TRACK_CONSTRUCTION,
        evidence_type="construction_reference_override",
        evidence_ref="construction_reference",
        weight=min(2.35, weight),
        confidence=min(0.96, 0.8 + 0.02 * len(matches)),
        note=f"construction reference override matched: {', '.join(matches[:8])}",
    )


def _score_style_reference_override(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    source = str(candidate.get("source") or "").strip().lower()
    if source not in {"pinterest", "houzz"}:
        return

    payload = candidate.get("ai_payload") or {}
    image_type = _normalize_label(str(payload.get("image_type") or ""))
    board = str(candidate.get("board") or "")
    context_text = _candidate_context_text(candidate)
    board_matches = _matching_hints(board, STYLE_REFERENCE_BOARD_HINTS)
    plan_matches = _matching_hints(context_text, STYLE_REFERENCE_PLAN_HINTS)
    detail_matches = _matching_hints(context_text, STYLE_REFERENCE_DETAIL_HINTS)
    blocker_matches = _matching_hints(context_text, STYLE_REFERENCE_BLOCKER_HINTS)
    style_matches = _matching_hints(context_text, STYLE_HINTS)
    if image_type == "product" and "architectural model" in detail_matches and set(blocker_matches).issubset({"framing"}):
        blocker_matches = []

    if (image_type == "plan" or plan_matches) and not blocker_matches:
        weight = 1.45
        if image_type == "plan":
            weight += 0.55
        if board_matches:
            weight += 0.25
        if any(_payload_values(payload, key) for key in ("rooms", "styles", "fixtures", "appliances")):
            weight += 0.2
        if any(
            match in {
                "property layout",
                "site layout",
                "residential plan",
                "house layout",
                "residential layout",
                "residential design",
                "architectural drawing",
                "exterior rendering",
            }
            for match in plan_matches
        ):
            weight += 0.15
        _add_contribution(
            scores,
            evidence,
            track=TRACK_STYLE,
            evidence_type="style_reference_override",
            evidence_ref="style_reference_plan",
            weight=min(2.55, weight),
            confidence=0.9,
            note=f"style reference plan override matched: {', '.join((plan_matches + board_matches)[:8]) or 'plan imagery'}",
        )
        return

    if blocker_matches or not detail_matches:
        return
    if image_type not in {"interior", "exterior", "product", "other", "document"}:
        return
    if image_type == "document" and not any(
        match in {"brick stain", "brick treatment", "brick wash", "whitewash", "color palette", "brick samples", "samples"}
        for match in detail_matches
    ):
        return
    if image_type == "other" and len(style_matches) + len(detail_matches) < 2 and not board_matches:
        return

    weight = 0.95
    if image_type in {"interior", "exterior", "product"}:
        weight += 0.35
    if board_matches:
        weight += 0.15
    if style_matches:
        weight += 0.1 * min(3, len(style_matches))
    _add_contribution(
        scores,
        evidence,
        track=TRACK_STYLE,
        evidence_type="style_reference_override",
        evidence_ref="style_reference_detail",
        weight=min(1.9, weight),
        confidence=0.84,
        note=f"style reference detail override matched: {', '.join((detail_matches + style_matches)[:8])}",
    )


def _score_magazine_clip_style_override(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    source = str(candidate.get("source") or "").strip().lower()
    if source != "scan":
        return

    raw_text = " | ".join(
        _normalize_space(str(candidate.get(key) or ""))
        for key in ("title", "description", "notes")
        if _normalize_space(str(candidate.get(key) or ""))
    )
    matches = _matching_hints(raw_text, MAGAZINE_CLIP_STYLE_HINTS)
    if not matches:
        return

    board_matches = _matching_hints(str(candidate.get("board") or ""), STYLE_HINTS)
    weight = 1.45
    if board_matches:
        weight += 0.25
    _add_contribution(
        scores,
        evidence,
        track=TRACK_STYLE,
        evidence_type="style_reference_override",
        evidence_ref="magazine_clip_scan",
        weight=min(2.0, weight),
        confidence=0.9,
        note=f"magazine clip style override matched: {', '.join((matches + board_matches)[:8])}",
    )


def _score_style_diy_reference_override(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    payload = candidate.get("ai_payload") or {}
    category = _normalize_label(str(candidate.get("category") or ""))
    video_category = _normalize_label(str(payload.get("category") or ""))
    video_subcategory = _normalize_label(str(payload.get("subcategory") or ""))
    if category != "diy" and video_category != "diy":
        return

    context_text = _candidate_context_text(candidate)
    if not context_text:
        return

    landscape_matches = _matching_hints(context_text, STYLE_LANDSCAPE_REFERENCE_HINTS)
    if video_subcategory == "landscaping":
        landscape_matches = _dedupe_labels(landscape_matches + ["landscaping"])
    if landscape_matches and not _matching_hints(context_text, IRRELEVANT_GARDENING_MISFIRE_HINTS):
        _add_contribution(
            scores,
            evidence,
            track=TRACK_STYLE,
            evidence_type="style_diy_override",
            evidence_ref="style_landscape_reference",
            weight=min(2.1, 1.45 + 0.1 * len(landscape_matches)),
            confidence=0.88,
            note=f"style landscape reference override matched: {', '.join(landscape_matches[:8])}",
        )
        return

    construction_blockers = _matching_hints(
        context_text,
        ("foundation", "framing", "inspection", "permit", "building code", "drainage system", "rainwater harvesting", "garage floor"),
    )
    if construction_blockers:
        return

    style_matches = _matching_hints(context_text, STYLE_DIY_REFERENCE_HINTS)
    if not style_matches:
        return
    _add_contribution(
        scores,
        evidence,
        track=TRACK_STYLE,
        evidence_type="style_diy_override",
        evidence_ref="style_paint_reference",
        weight=min(2.0, 1.38 + 0.08 * len(style_matches)),
        confidence=0.86,
        note=f"style diy reference override matched: {', '.join(style_matches[:8])}",
    )


def _score_irrelevant_misfire_override(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    context_text = _candidate_context_text(candidate)
    if not context_text:
        return

    survival_matches = _matching_hints(context_text, ("bug out bag", "emergency preparedness", "survival gear", "disaster kit", "prepper", "camping"))
    if survival_matches:
        _add_contribution(
            scores,
            evidence,
            track=TRACK_IRRELEVANT,
            evidence_type="irrelevant_override",
            evidence_ref="survival_misfire",
            weight=min(2.15, 1.45 + 0.12 * len(survival_matches)),
            confidence=0.92,
            note=f"survival/prepper misfire matched: {', '.join(survival_matches[:8])}",
        )
        return

    hardware_matches = _matching_hints(context_text, IRRELEVANT_HARDWARE_REFERENCE_HINTS)
    if len(hardware_matches) >= 2 and not _matching_hints(context_text, ("cabinet hardware", "drawer pull", "knob", "lighting fixture")):
        _add_contribution(
            scores,
            evidence,
            track=TRACK_IRRELEVANT,
            evidence_type="irrelevant_override",
            evidence_ref="hardware_reference_misfire",
            weight=min(1.95, 1.3 + 0.14 * len(hardware_matches)),
            confidence=0.88,
            note=f"generic hardware-reference misfire matched: {', '.join(hardware_matches[:8])}",
        )
        return

    garden_matches = _matching_hints(context_text, IRRELEVANT_GARDENING_MISFIRE_HINTS)
    if len(garden_matches) >= 2 and not _matching_hints(context_text, ("landscape design", "garden design", "outdoor living")):
        _add_contribution(
            scores,
            evidence,
            track=TRACK_IRRELEVANT,
            evidence_type="irrelevant_override",
            evidence_ref="gardening_misfire",
            weight=min(1.75, 1.15 + 0.12 * len(garden_matches)),
            confidence=0.84,
            note=f"generic gardening/household misfire matched: {', '.join(garden_matches[:8])}",
        )


def _score_maintenance_adjacent_override(candidate: dict[str, Any], scores: Counter[str], evidence: list[EvidenceContribution]) -> None:
    payload = candidate.get("ai_payload") or {}
    category = _normalize_label(str(candidate.get("category") or ""))
    video_category = _normalize_label(str(payload.get("category") or ""))
    raw_context_text = " | ".join(
        _normalize_space(text)
        for field_name, text in _candidate_text_fields(candidate)
        if field_name != "ai_summary" and _normalize_space(text)
    )
    if not raw_context_text:
        return

    maintenance_matches = _matching_hints(raw_context_text, MAINTENANCE_HINTS)
    if not maintenance_matches:
        return

    generic_irrelevant_matches = _matching_hints(
        raw_context_text,
        ("cleaning", "mopping", "lifehack", "lifehacks", "moving furniture", "stripped screw", "household products", "stained grout"),
    )
    if generic_irrelevant_matches:
        return

    blocker_matches = _matching_hints(
        raw_context_text,
        (
            "electrical",
            "new build",
            "inspection",
            "checklist",
            "permit",
            "building code",
            "foundation",
            "framing",
            "insulation",
            "waterproof",
            "zip system",
            "french drain",
            "drainage system",
            "rainwater collection",
            "rainwater harvesting",
            "rain barrel",
            "underground tank",
            "first flush chamber",
            "downspout leaf filter",
            "leaf filter",
            "retaining wall",
            "house plan",
            "floor plan",
            "must-have",
            "must-haves",
        ),
    )
    if blocker_matches:
        return

    unique_matches: list[str] = []
    seen: set[str] = set()
    for match in maintenance_matches:
        if match not in seen:
            seen.add(match)
            unique_matches.append(match)

    weight = 1.25 + 0.1 * min(5, len(unique_matches))
    if category == "diy" or video_category == "diy":
        weight += 0.12
    if any(
        match in {
            "home repair",
            "drywall repair",
            "wall repair",
            "patching",
            "drywall patch",
            "water damage",
            "water stains",
            "ceiling damage",
            "roof leak",
            "cracked concrete",
            "concrete repair",
        }
        for match in unique_matches
    ):
        weight += 0.35
    if any(
        match in {
            "rainwater collection",
            "rainwater harvesting",
            "rain barrel",
            "downspout",
            "downspouts",
            "gutter",
            "gutters",
            "gutter detail",
            "gutter system",
            "water conservation",
        }
        for match in unique_matches
    ):
        weight += 0.45
    _add_contribution(
        scores,
        evidence,
        track=TRACK_MAINTENANCE,
        evidence_type="maintenance_override",
        evidence_ref="maintenance_adjacent",
        weight=min(1.9, weight),
        confidence=min(0.94, 0.74 + 0.03 * len(unique_matches)),
        note=f"maintenance/repair/diy override matched: {', '.join(unique_matches[:8])}",
    )


def _finalize_track(scores: Counter[str], source: str) -> tuple[str, bool, float]:
    style = float(scores.get(TRACK_STYLE, 0.0))
    construction = float(scores.get(TRACK_CONSTRUCTION, 0.0))
    maintenance = float(scores.get(TRACK_MAINTENANCE, 0.0))
    irrelevant = float(scores.get(TRACK_IRRELEVANT, 0.0))
    top_positive = max(style, construction, maintenance)

    if irrelevant >= top_positive + 0.6 and irrelevant >= 0.9:
        top = irrelevant
        second = top_positive
        margin = top - second
        confidence = min(0.98, 0.5 + 0.12 * top + 0.08 * margin)
        return (TRACK_IRRELEVANT, False, confidence)
    if irrelevant >= top_positive + 0.3 and irrelevant >= 0.28:
        top = irrelevant
        second = top_positive
        margin = top - second
        confidence = min(0.82, 0.42 + 0.11 * top + 0.07 * margin)
        return (TRACK_IRRELEVANT, True, confidence)

    if style <= 0 and construction <= 0 and maintenance <= 0:
        if irrelevant >= 0.25:
            return (TRACK_IRRELEVANT, True, 0.45)
        if source in {"pinterest", "houzz"}:
            return (TRACK_STYLE, True, 0.42)
        return (TRACK_STYLE, True, 0.35)

    ordered_positive = sorted(
        (
            (TRACK_STYLE, style),
            (TRACK_CONSTRUCTION, construction),
            (TRACK_MAINTENANCE, maintenance),
        ),
        key=lambda item: (-item[1], item[0]),
    )
    track, top = ordered_positive[0]
    second = ordered_positive[1][1]

    margin = top - second
    ambiguous = top < 1.0 or margin < 0.55 or irrelevant >= top - 0.15
    confidence = min(0.98, 0.46 + 0.1 * top + 0.12 * max(0.0, margin))
    if ambiguous:
        confidence = min(confidence, 0.69)
    return (track, ambiguous, confidence)


def collect_track_gate_candidates(
    db: Db,
    *,
    triage_status: str = "pending,keeper",
    source: str = "",
    limit: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    sources = _csv_values(source)
    if sources:
        clauses.append("a.source in (%s)" % ",".join(["?"] * len(sources)))
        params.extend(sources)

    statuses = [s.lower() for s in _csv_values(triage_status)]
    if statuses:
        if "pending" in statuses:
            others = [s for s in statuses if s != "pending"]
            if others:
                clauses.append("(a.triage_status is null or a.triage_status in (%s))" % ",".join(["?"] * len(others)))
                params.extend(others)
            else:
                clauses.append("a.triage_status is null")
        else:
            clauses.append("a.triage_status in (%s)" % ",".join(["?"] * len(statuses)))
            params.extend(statuses)

    hidden_collection_id = db.query_value("select id from collections where lower(name)='hidden' limit 1")
    if hidden_collection_id:
        clauses.append("a.id not in (select asset_id from collection_items where collection_id = ?)")
        params.append(str(hidden_collection_id))

    where = "where " + " and ".join(clauses) if clauses else ""
    limit_sql = "limit ?" if limit and limit > 0 else ""
    if limit_sql:
        params.append(int(limit))

    rows = db.query(
        f"""
        select a.id, a.source, a.source_ref, a.source_url, a.title, a.description,
               a.board, a.notes, a.ai_summary, a.category, a.imported_at, a.triage_status,
               p.origin_type as title_origin_type,
               p.confidence as title_origin_confidence,
               p.origin_ref as title_origin_ref,
               (select group_concat(al.label, '|') from asset_labels al where al.asset_id = a.id) as labels_csv
        from assets a
        left join asset_field_provenance p
          on p.asset_id = a.id
         and p.field_name = 'title'
         and p.is_current = 1
        {where}
        order by a.imported_at desc
        {limit_sql}
        """,
        tuple(params),
    )

    candidates = []
    asset_ids: list[str] = []
    for row in rows:
        asset_id = str(row["id"])
        asset_ids.append(asset_id)
        candidates.append(
            {
                "asset_id": asset_id,
                "source": str(row["source"] or "").strip().lower(),
                "source_ref": str(row["source_ref"] or "").strip(),
                "source_url": str(row["source_url"] or "").strip(),
                "title": str(row["title"] or "").strip(),
                "description": str(row["description"] or "").strip(),
                "board": str(row["board"] or "").strip(),
                "notes": str(row["notes"] or "").strip(),
                "ai_summary": str(row["ai_summary"] or "").strip(),
                "category": str(row["category"] or "").strip().lower(),
                "imported_at": str(row["imported_at"] or "").strip(),
                "title_origin_type": str(row["title_origin_type"] or "").strip().lower(),
                "title_origin_confidence": row["title_origin_confidence"],
                "title_origin_ref": str(row["title_origin_ref"] or "").strip(),
                "labels": _labels_from_csv(row["labels_csv"]),
            }
        )

    if not asset_ids:
        return candidates

    placeholders = ",".join(["?"] * len(asset_ids))
    ai_rows = db.query(
        f"""
        select ai.id, ai.asset_id, ai.provider, ai.model, ai.summary, ai.json, ai.created_at
        from asset_ai ai
        join (
          select asset_id, max(created_at) as max_created_at
          from asset_ai
          where asset_id in ({placeholders})
          group by asset_id
        ) latest
          on latest.asset_id = ai.asset_id
         and latest.max_created_at = ai.created_at
        where ai.asset_id in ({placeholders})
        """,
        tuple(asset_ids + asset_ids),
    )
    ai_by_asset: dict[str, sqlite3.Row] = {}
    for row in ai_rows:
        ai_by_asset[str(row["asset_id"])] = row
    overrides_by_asset = _load_active_overrides(db, asset_ids)

    for candidate in candidates:
        ai_row = ai_by_asset.get(candidate["asset_id"])
        if not ai_row:
            candidate["asset_ai_id"] = ""
            candidate["ai_provider"] = ""
            candidate["ai_model"] = ""
            candidate["ai_payload"] = {}
            candidate["overrides"] = overrides_by_asset.get(candidate["asset_id"], [])
            continue
        candidate["asset_ai_id"] = str(ai_row["id"] or "")
        candidate["ai_provider"] = str(ai_row["provider"] or "").strip().lower()
        candidate["ai_model"] = str(ai_row["model"] or "").strip()
        candidate["ai_payload"] = _safe_json_object(ai_row["json"])
        candidate["overrides"] = overrides_by_asset.get(candidate["asset_id"], [])
    return candidates


def _score_candidate(candidate: dict[str, Any]) -> tuple[str, bool, float, Counter[str], list[EvidenceContribution]]:
    manual_track = _manual_track_override(candidate)
    if manual_track:
        track, note = manual_track
        return (
            track,
            False,
            0.995,
            Counter({track: 9.0}),
            [
                EvidenceContribution(
                    track=track,
                    evidence_type="manual_override",
                    evidence_ref="asset_overrides",
                    weight=9.0,
                    confidence=0.995,
                    note=note,
                )
            ],
        )

    scores: Counter[str] = Counter()
    evidence: list[EvidenceContribution] = []

    _score_source_prior(candidate, scores, evidence)
    _score_asset_category(candidate, scores, evidence)
    _score_text_field(candidate=candidate, field_name="board", text=candidate.get("board") or "", scores=scores, evidence=evidence)
    _score_text_field(candidate=candidate, field_name="title", text=candidate.get("title") or "", scores=scores, evidence=evidence)
    _score_text_field(
        candidate=candidate,
        field_name="description",
        text=candidate.get("description") or "",
        scores=scores,
        evidence=evidence,
    )
    _score_text_field(candidate=candidate, field_name="notes", text=candidate.get("notes") or "", scores=scores, evidence=evidence)
    _score_text_field(
        candidate=candidate,
        field_name="ai_summary",
        text=candidate.get("ai_summary") or "",
        scores=scores,
        evidence=evidence,
    )
    _score_labels(candidate, scores, evidence)
    _score_ai_payload(candidate, scores, evidence)
    _score_construction_reference_override(candidate, scores, evidence)
    _score_style_reference_override(candidate, scores, evidence)
    _score_magazine_clip_style_override(candidate, scores, evidence)
    _score_style_diy_reference_override(candidate, scores, evidence)
    _score_maintenance_adjacent_override(candidate, scores, evidence)
    _score_diy_irrelevant_override(candidate, scores, evidence)
    _score_strong_irrelevant_intent_override(candidate, scores, evidence)
    _score_strong_irrelevant_visual_override(candidate, scores, evidence)
    _score_irrelevant_misfire_override(candidate, scores, evidence)

    track, is_ambiguous, confidence = _finalize_track(scores, str(candidate.get("source") or ""))
    return (track, is_ambiguous, confidence, scores, evidence)


def run_track_gate_v2(
    db: Db,
    *,
    triage_status: str = "pending,keeper",
    source: str = "",
    limit: int = 0,
    notes: str = "",
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    created_at = _now_iso()
    config = {
        "triage_status": triage_status,
        "source": source,
        "limit": int(limit or 0),
        "track_labels": [TRACK_STYLE, TRACK_CONSTRUCTION, TRACK_MAINTENANCE, TRACK_IRRELEVANT],
    }
    db.exec(
        """
        insert into classification_runs
          (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            SCHEMA_VERSION,
            "track_gate",
            "heuristic",
            DEFAULT_TRACK_GATE_MODEL,
            "",
            json.dumps(config, ensure_ascii=True, sort_keys=True),
            created_at,
            notes or None,
        ),
    )

    candidates = collect_track_gate_candidates(db, triage_status=triage_status, source=source, limit=limit)
    assessment_rows: list[tuple[Any, ...]] = []
    evidence_rows: list[tuple[Any, ...]] = []
    counts: Counter[str] = Counter()
    ambiguous = 0
    top_examples: list[dict[str, Any]] = []

    for candidate in candidates:
        track, is_ambiguous, confidence, scores, evidence = _score_candidate(candidate)
        asset_id = str(candidate["asset_id"])
        decision_source = "manual_override" if any(item.evidence_type == "manual_override" for item in evidence) else "merged"
        assessment_rows.append(
            (
                str(uuid.uuid4()),
                run_id,
                asset_id,
                track,
                round(float(confidence), 4),
                1 if is_ambiguous else 0,
                decision_source,
                _reason_from_scores(track, scores, evidence),
                created_at,
            )
        )
        counts[track] += 1
        if is_ambiguous:
            ambiguous += 1
        for item in evidence:
            evidence_rows.append(
                (
                    str(uuid.uuid4()),
                    run_id,
                    asset_id,
                    item.track,
                    "track",
                    item.track,
                    item.evidence_type,
                    item.evidence_ref,
                    item.weight,
                    item.confidence,
                    item.note,
                    created_at,
                )
            )
        if len(top_examples) < 10:
            top_examples.append(
                {
                    "asset_id": asset_id,
                    "track": track,
                    "ambiguous": bool(is_ambiguous),
                    "title": str(candidate.get("title") or ""),
                }
            )

    if assessment_rows:
        db.executemany(
            """
            insert into asset_track_assessments
              (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            assessment_rows,
        )
    if evidence_rows:
        db.executemany(
            """
            insert into asset_axis_evidence
              (id, run_id, asset_id, track, axis_name, axis_value, evidence_type, evidence_ref,
               weight, confidence, note, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            evidence_rows,
        )

    return {
        "ok": True,
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "run_type": "track_gate",
        "model_provider": "heuristic",
        "model_name": DEFAULT_TRACK_GATE_MODEL,
        "candidate_count": len(candidates),
        "assessments_written": len(assessment_rows),
        "evidence_written": len(evidence_rows),
        "ambiguous_count": ambiguous,
        "counts": {
            TRACK_STYLE: int(counts.get(TRACK_STYLE, 0)),
            TRACK_CONSTRUCTION: int(counts.get(TRACK_CONSTRUCTION, 0)),
            TRACK_MAINTENANCE: int(counts.get(TRACK_MAINTENANCE, 0)),
            TRACK_IRRELEVANT: int(counts.get(TRACK_IRRELEVANT, 0)),
        },
        "examples": top_examples,
    }


def _reason_from_scores(track: str, scores: Counter[str], evidence: list[EvidenceContribution]) -> str:
    ordered_scores = sorted(scores.items(), key=lambda kv: (-float(kv[1]), kv[0]))
    score_bits = [f"{name}={float(value):.2f}" for name, value in ordered_scores if float(value) > 0]
    top_evidence = [
        item.note
        for item in sorted(evidence, key=lambda item: (-item.weight, item.evidence_type, item.note))[:3]
    ]
    parts = [f"winner={track}"]
    if score_bits:
        parts.append("scores: " + "; ".join(score_bits))
    if top_evidence:
        parts.append("top evidence: " + " | ".join(top_evidence))
    return _normalize_space(". ".join(parts))


def _candidate_text_fields(candidate: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("board", str(candidate.get("board") or "")),
        ("title", str(candidate.get("title") or "")),
        ("description", str(candidate.get("description") or "")),
        ("notes", str(candidate.get("notes") or "")),
        ("ai_summary", str(candidate.get("ai_summary") or "")),
    ]


def _load_active_overrides(db: Db, asset_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["?"] * len(asset_ids))
    now = _now_iso()
    rows = db.query(
        f"""
        select asset_id, axis_name, axis_value, operation, actor, note, created_at
        from asset_overrides
        where asset_id in ({placeholders})
          and (expires_at is null or expires_at > ?)
        order by created_at asc, id asc
        """,
        tuple(asset_ids + [now]),
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["asset_id"]), []).append(
            {
                "axis_name": str(row["axis_name"] or "").strip(),
                "axis_value": str(row["axis_value"] or "").strip(),
                "operation": str(row["operation"] or "").strip().lower(),
                "actor": str(row["actor"] or "").strip(),
                "note": str(row["note"] or "").strip(),
                "created_at": str(row["created_at"] or "").strip(),
            }
        )
    return out


def _load_latest_fetched_source_link_enrichment(db: Db, asset_ids: list[str]) -> dict[str, sqlite3.Row]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["?"] * len(asset_ids))
    rows = db.query(
        f"""
        select sle.*
        from asset_source_link_enrichment sle
        join (
          select asset_id, max(created_at) as max_created_at
          from asset_source_link_enrichment
          where asset_id in ({placeholders})
            and fetch_status = 'fetched'
          group by asset_id
        ) latest
          on latest.asset_id = sle.asset_id
         and latest.max_created_at = sle.created_at
        where sle.asset_id in ({placeholders})
          and sle.fetch_status = 'fetched'
        """,
        tuple(asset_ids + asset_ids),
    )
    return {str(row["asset_id"]): row for row in rows}


def _manual_track_override(candidate: dict[str, Any]) -> tuple[str, str] | None:
    selected: tuple[str, str] | None = None
    for row in candidate.get("overrides") or []:
        if str(row.get("axis_name") or "").strip() != "track":
            continue
        if str(row.get("operation") or "").strip().lower() != "set":
            continue
        track = str(row.get("axis_value") or "").strip()
        if track not in TRACK_LABELS:
            continue
        actor = str(row.get("actor") or "").strip() or "human"
        note = str(row.get("note") or "").strip() or f"manual track override by {actor}"
        selected = (track, note)
    return selected


def _add_axis_contribution(
    scores: Counter[str],
    evidence: list[AxisEvidence],
    *,
    axis_name: str,
    axis_value: str,
    evidence_type: str,
    evidence_ref: str,
    weight: float,
    confidence: float,
    note: str,
) -> None:
    axis_value = str(axis_value or "").strip()
    if not axis_value:
        return
    weight = round(float(weight), 4)
    confidence = max(0.0, min(1.0, float(confidence)))
    if weight <= 0:
        return
    scores[axis_value] += weight
    evidence.append(
        AxisEvidence(
            axis_name=axis_name,
            axis_value=axis_value,
            evidence_type=evidence_type,
            evidence_ref=evidence_ref,
            weight=weight,
            confidence=round(confidence, 4),
            note=_normalize_space(note),
        )
    )


def _matching_axis_values_for_label(label: str, hint_map: dict[str, tuple[str, ...]]) -> list[str]:
    cleaned = _normalize_label(label)
    if not cleaned:
        return []
    matches: list[str] = []
    for axis_value, hints in hint_map.items():
        if cleaned == _normalize_label(axis_value.replace("_", " ")):
            matches.append(axis_value)
            continue
        if any(_contains_hint(cleaned, hint) for hint in hints):
            matches.append(axis_value)
    return matches


def _score_axis_hint_map_from_text(
    *,
    candidate: dict[str, Any],
    axis_name: str,
    hint_map: dict[str, tuple[str, ...]],
    scores: Counter[str],
    evidence: list[AxisEvidence],
) -> None:
    for field_name, text in _candidate_text_fields(candidate):
        cleaned = _normalize_space(text)
        if not cleaned:
            continue
        field_weight = _field_weight(candidate, field_name)
        for axis_value, hints in hint_map.items():
            matches = _matching_hints(cleaned, hints)
            if not matches:
                continue
            conf = min(0.95, 0.54 + 0.06 * len(matches))
            weight_multiplier = 1.0
            if axis_name == "product_system_focus":
                if field_name == "title" and any(len(hint.replace("-", " ").split()) >= 2 for hint in matches):
                    weight_multiplier = 3.0
                elif any(len(hint.replace("-", " ").split()) >= 2 for hint in matches):
                    weight_multiplier = 1.8
            elif axis_name == "product_focus":
                if field_name == "title" and any(len(hint.replace("-", " ").split()) >= 2 for hint in matches):
                    weight_multiplier = 1.6
            _add_axis_contribution(
                scores,
                evidence,
                axis_name=axis_name,
                axis_value=axis_value,
                evidence_type="field_text",
                evidence_ref=f"field:{field_name}",
                weight=field_weight * conf * weight_multiplier,
                confidence=conf,
                note=f"{field_name} matched {axis_name} terms: {', '.join(matches[:6])}",
            )


def _score_axis_hint_map_from_labels(
    *,
    axis_name: str,
    hint_map: dict[str, tuple[str, ...]],
    labels: list[str],
    scores: Counter[str],
    evidence: list[AxisEvidence],
) -> None:
    for label in labels:
        matches = _matching_axis_values_for_label(label, hint_map)
        for axis_value in matches:
            _add_axis_contribution(
                scores,
                evidence,
                axis_name=axis_name,
                axis_value=axis_value,
                evidence_type="asset_label",
                evidence_ref="asset_labels",
                weight=0.7,
                confidence=0.82,
                note=f"label matched {axis_name}: {label}",
            )


def _score_axis_hint_map_from_source_link(
    *,
    candidate: dict[str, Any],
    axis_name: str,
    hint_map: dict[str, tuple[str, ...]],
    scores: Counter[str],
    evidence: list[AxisEvidence],
) -> None:
    field_weights = {
        "source_page_title": 1.0,
        "source_page_og_title": 0.92,
        "source_page_meta_description": 0.82,
        "source_page_og_description": 0.82,
        "source_page_text_excerpt": 0.95,
    }
    for field_name, text in _construction_source_link_fields(candidate):
        cleaned = _normalize_space(text)
        if not cleaned:
            continue
        field_weight = field_weights.get(field_name, 0.68)
        for axis_value, hints in hint_map.items():
            matches = _matching_hints(cleaned, hints)
            if not matches:
                continue
            conf = min(0.96, 0.58 + 0.05 * len(matches))
            _add_axis_contribution(
                scores,
                evidence,
                axis_name=axis_name,
                axis_value=axis_value,
                evidence_type="source_link_text",
                evidence_ref=f"field:{field_name}",
                weight=field_weight * conf,
                confidence=conf,
                note=f"{field_name} matched {axis_name} terms: {', '.join(matches[:6])}",
            )


def _normalize_room_value(value: str) -> str:
    raw = _normalize_label(value).replace("_", " ")
    if not raw:
        return ""
    raw = ROOM_ALIASES.get(raw, raw).replace(" ", "_")
    return raw if raw in ROOM_HINTS else ""


def _derive_function_from_room(room: str) -> str:
    return {
        "kitchen": "cooking",
        "bathroom": "bathing",
        "bedroom": "sleeping",
        "living_room": "entertaining",
        "dining_room": "dining",
        "entryway": "circulation",
        "mudroom": "utility",
        "laundry_room": "utility",
        "garage": "utility",
    }.get(room, "")


def _score_to_confidence(score: float, ambiguous: bool) -> float:
    conf = min(0.98, 0.38 + 0.18 * float(score))
    if ambiguous:
        conf = min(conf, 0.69)
    return round(conf, 4)


def _select_single_axis(
    scores: Counter[str],
    *,
    min_score: float = 0.55,
    ambiguity_margin: float = 0.22,
) -> list[tuple[str, float, int, bool, bool]]:
    ordered = [(k, float(v)) for k, v in scores.items() if float(v) > 0]
    ordered.sort(key=lambda kv: (-kv[1], kv[0]))
    if not ordered:
        return []
    top_value, top_score = ordered[0]
    if top_score < min_score:
        return []
    out = [(top_value, _score_to_confidence(top_score, False), 1, True, False)]
    if len(ordered) > 1:
        second_value, second_score = ordered[1]
        if second_score >= min_score and (top_score - second_score) < ambiguity_margin:
            out = [
                (top_value, _score_to_confidence(top_score, True), 1, True, True),
                (second_value, _score_to_confidence(second_score, True), 2, False, True),
            ]
    return out


def _select_multi_axis(
    scores: Counter[str],
    *,
    min_score: float = 0.6,
    max_values: int = 6,
    relative_threshold: float = 0.55,
) -> list[tuple[str, float, int, bool, bool]]:
    ordered = [(k, float(v)) for k, v in scores.items() if float(v) >= min_score]
    ordered.sort(key=lambda kv: (-kv[1], kv[0]))
    if not ordered:
        return []
    top_score = ordered[0][1]
    out: list[tuple[str, float, int, bool, bool]] = []
    for rank, (value, score) in enumerate(ordered[:max_values], start=1):
        if score < max(min_score, top_score * relative_threshold):
            continue
        ambiguous = rank > 1 and (top_score - score) < 0.2
        out.append((value, _score_to_confidence(score, ambiguous), rank, rank == 1, ambiguous))
    return out


def _payload_values(payload: dict[str, Any], key: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in payload.get(key) or []:
        label = _normalize_label(str(item))
        if not label or label in seen:
            continue
        seen.add(label)
        values.append(label)
    return values


def _construction_source_link_fields(candidate: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("source_page_title", str(candidate.get("source_page_title") or "")),
        ("source_page_og_title", str(candidate.get("source_page_og_title") or "")),
        ("source_page_meta_description", str(candidate.get("source_page_meta_description") or "")),
        ("source_page_og_description", str(candidate.get("source_page_og_description") or "")),
        ("source_page_text_excerpt", str(candidate.get("source_page_text_excerpt") or "")),
    ]


def _score_design_facets(candidate: dict[str, Any], scores: Counter[str], evidence: list[AxisEvidence]) -> None:
    payload = candidate.get("ai_payload") or {}
    asset_ai_id = str(candidate.get("asset_ai_id") or "").strip() or "asset_ai"
    for key, base_weight in (("styles", 0.85), ("materials", 0.8), ("colors", 0.68), ("elements", 0.58)):
        for label in _payload_values(payload, key):
            _add_axis_contribution(
                scores,
                evidence,
                axis_name="design_facets",
                axis_value=label,
                evidence_type="asset_ai_json",
                evidence_ref=f"asset_ai:{asset_ai_id}",
                weight=base_weight,
                confidence=0.78,
                note=f"vision {key} value: {label}",
            )


def _score_style_ai_payload(
    candidate: dict[str, Any],
    axis_scores: dict[str, Counter[str]],
    evidence: list[AxisEvidence],
) -> None:
    payload = candidate.get("ai_payload") or {}
    if not payload:
        return
    provider = str(candidate.get("ai_provider") or "").strip().lower()
    asset_ai_id = str(candidate.get("asset_ai_id") or "").strip() or provider or "asset_ai"
    evidence_ref = f"asset_ai:{asset_ai_id}"

    image_type = _normalize_label(str(payload.get("image_type") or ""))
    if image_type == "interior":
        _add_axis_contribution(axis_scores["space_context"], evidence, axis_name="space_context", axis_value="interior_room", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=1.0, confidence=0.85, note="vision image_type=interior")
        _add_axis_contribution(axis_scores["subject_type"], evidence, axis_name="subject_type", axis_value="full_space_scene", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.65, confidence=0.72, note="vision image_type suggests room scene")
    elif image_type == "exterior":
        _add_axis_contribution(axis_scores["space_context"], evidence, axis_name="space_context", axis_value="outdoor_zone", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=1.05, confidence=0.86, note="vision image_type=exterior")
        _add_axis_contribution(axis_scores["subject_type"], evidence, axis_name="subject_type", axis_value="full_space_scene", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.72, confidence=0.75, note="vision exterior suggests full scene")
    elif image_type == "product":
        _add_axis_contribution(axis_scores["space_context"], evidence, axis_name="space_context", axis_value="non_spatial", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.9, confidence=0.82, note="vision image_type=product")
        _add_axis_contribution(axis_scores["subject_type"], evidence, axis_name="subject_type", axis_value="single_product", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=1.0, confidence=0.88, note="vision image_type=product")
    elif image_type == "plan":
        _add_axis_contribution(axis_scores["space_context"], evidence, axis_name="space_context", axis_value="non_spatial", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=1.0, confidence=0.88, note="vision image_type=plan")
        _add_axis_contribution(axis_scores["subject_type"], evidence, axis_name="subject_type", axis_value="plan_drawing", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=1.15, confidence=0.92, note="vision image_type=plan")

    for room_label in _payload_values(payload, "rooms"):
        room_value = _normalize_room_value(room_label)
        if not room_value:
            continue
        _add_axis_contribution(axis_scores["room"], evidence, axis_name="room", axis_value=room_value, evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=1.0, confidence=0.84, note=f"vision room={room_label}")
        if room_value in {"entryway", "mudroom"}:
            _add_axis_contribution(axis_scores["space_context"], evidence, axis_name="space_context", axis_value="transition_space", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.95, confidence=0.8, note=f"vision room implies transition space: {room_value}")
        elif room_value in {"exterior", "landscape"}:
            _add_axis_contribution(axis_scores["space_context"], evidence, axis_name="space_context", axis_value="outdoor_zone", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.95, confidence=0.8, note=f"vision room implies outdoor zone: {room_value}")
        else:
            _add_axis_contribution(axis_scores["space_context"], evidence, axis_name="space_context", axis_value="interior_room", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.9, confidence=0.78, note=f"vision room implies interior room: {room_value}")
        derived_function = _derive_function_from_room(room_value)
        if derived_function:
            _add_axis_contribution(axis_scores["function"], evidence, axis_name="function", axis_value=derived_function, evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.78, confidence=0.76, note=f"vision room implies function: {room_value}")

    for bucket in ("fixtures", "appliances", "brands_products", "elements", "tags"):
        for label in _payload_values(payload, bucket):
            for axis_value in _matching_axis_values_for_label(label, PRODUCT_FOCUS_HINTS):
                _add_axis_contribution(axis_scores["product_focus"], evidence, axis_name="product_focus", axis_value=axis_value, evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.88, confidence=0.8, note=f"vision {bucket} implies product focus: {label}")

    if provider == "gemini-video":
        subcategory = _normalize_label(str(payload.get("subcategory") or ""))
        video_room = _normalize_room_value(subcategory)
        if video_room:
            _add_axis_contribution(axis_scores["room"], evidence, axis_name="room", axis_value=video_room, evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.75, confidence=0.74, note=f"video subcategory={subcategory}")
            if video_room in {"landscape", "exterior"}:
                _add_axis_contribution(axis_scores["space_context"], evidence, axis_name="space_context", axis_value="outdoor_zone", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.75, confidence=0.74, note=f"video subcategory implies outdoor zone: {subcategory}")
            else:
                _add_axis_contribution(axis_scores["space_context"], evidence, axis_name="space_context", axis_value="interior_room", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.7, confidence=0.7, note=f"video subcategory implies interior room: {subcategory}")
            derived_function = _derive_function_from_room(video_room)
            if derived_function:
                _add_axis_contribution(axis_scores["function"], evidence, axis_name="function", axis_value=derived_function, evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.65, confidence=0.7, note=f"video subcategory implies function: {subcategory}")

    _score_design_facets(candidate, axis_scores["design_facets"], evidence)


def _select_style_axis_memberships(candidate: dict[str, Any]) -> tuple[list[tuple[str, str, float, int, bool, bool]], list[AxisEvidence]]:
    axis_scores = {
        "space_context": Counter(),
        "subject_type": Counter(),
        "function": Counter(),
        "room": Counter(),
        "product_focus": Counter(),
        "design_facets": Counter(),
    }
    evidence: list[AxisEvidence] = []

    _score_axis_hint_map_from_text(candidate=candidate, axis_name="space_context", hint_map=SPACE_CONTEXT_HINTS, scores=axis_scores["space_context"], evidence=evidence)
    _score_axis_hint_map_from_text(candidate=candidate, axis_name="subject_type", hint_map=SUBJECT_TYPE_HINTS, scores=axis_scores["subject_type"], evidence=evidence)
    _score_axis_hint_map_from_text(candidate=candidate, axis_name="function", hint_map=FUNCTION_HINTS, scores=axis_scores["function"], evidence=evidence)
    _score_axis_hint_map_from_text(candidate=candidate, axis_name="room", hint_map=ROOM_HINTS, scores=axis_scores["room"], evidence=evidence)
    _score_axis_hint_map_from_text(candidate=candidate, axis_name="product_focus", hint_map=PRODUCT_FOCUS_HINTS, scores=axis_scores["product_focus"], evidence=evidence)

    labels = candidate.get("labels") or []
    _score_axis_hint_map_from_labels(axis_name="space_context", hint_map=SPACE_CONTEXT_HINTS, labels=labels, scores=axis_scores["space_context"], evidence=evidence)
    _score_axis_hint_map_from_labels(axis_name="subject_type", hint_map=SUBJECT_TYPE_HINTS, labels=labels, scores=axis_scores["subject_type"], evidence=evidence)
    _score_axis_hint_map_from_labels(axis_name="function", hint_map=FUNCTION_HINTS, labels=labels, scores=axis_scores["function"], evidence=evidence)
    _score_axis_hint_map_from_labels(axis_name="room", hint_map=ROOM_HINTS, labels=labels, scores=axis_scores["room"], evidence=evidence)
    _score_axis_hint_map_from_labels(axis_name="product_focus", hint_map=PRODUCT_FOCUS_HINTS, labels=labels, scores=axis_scores["product_focus"], evidence=evidence)

    _score_style_ai_payload(candidate, axis_scores, evidence)

    selected: list[tuple[str, str, float, int, bool, bool]] = []
    space_memberships = _select_single_axis(axis_scores["space_context"], min_score=0.6)
    subject_memberships = _select_single_axis(axis_scores["subject_type"], min_score=0.6)
    function_memberships = _select_single_axis(axis_scores["function"], min_score=0.55)
    product_focus_memberships = _select_multi_axis(axis_scores["product_focus"], min_score=0.72, max_values=4)
    design_facets_memberships = _select_multi_axis(axis_scores["design_facets"], min_score=0.75, max_values=6)

    has_plan_subject = any(value == "plan_drawing" for value, _, _, _, _ in subject_memberships)
    if has_plan_subject:
        non_spatial_score = max(0.9, float(axis_scores["space_context"].get("non_spatial", 0.0)))
        space_memberships = [("non_spatial", _score_to_confidence(non_spatial_score, False), 1, True, False)]

    primary_space = space_memberships[0][0] if space_memberships else ""
    primary_subject = subject_memberships[0][0] if subject_memberships else ""
    room_allowed = primary_space in {"interior_room", "transition_space"} and primary_subject in {"full_space_scene", "vignette_styling", ""}
    room_memberships: list[tuple[str, float, int, bool, bool]] = []
    if room_allowed:
        raw_room_memberships = _select_single_axis(axis_scores["room"], min_score=0.72)
        room_memberships = [m for m in raw_room_memberships if m[0] not in {"exterior", "landscape"}]

    for axis_name, memberships in (
        ("space_context", space_memberships),
        ("subject_type", subject_memberships),
        ("function", function_memberships),
        ("room", room_memberships),
        ("product_focus", product_focus_memberships),
        ("design_facets", design_facets_memberships),
    ):
        for value, confidence, rank, is_primary, is_ambiguous in memberships:
            selected.append((axis_name, value, confidence, rank, is_primary, is_ambiguous))
    return selected, evidence


PRODUCT_SYSTEM_TO_DOMAIN = {
    "zip_system": "envelope",
    "window_system": "envelope",
    "door_system": "envelope",
    "garage_door_system": "envelope",
    "siding_system": "envelope",
    "flashing_system": "envelope",
    "sheathing_system": "envelope",
    "waterproofing_membrane": "envelope",
    "insulation_system": "envelope",
    "roofing_system": "envelope",
    "roof_vent_system": "envelope",
    "duct_system": "mep",
    "water_heater": "mep",
    "tankless_water_heater": "mep",
}

PRODUCT_SYSTEM_TO_TRADE = {
    "zip_system": "envelope",
    "window_system": "envelope",
    "door_system": "envelope",
    "garage_door_system": "envelope",
    "siding_system": "envelope",
    "flashing_system": "envelope",
    "sheathing_system": "envelope",
    "waterproofing_membrane": "envelope",
    "insulation_system": "envelope",
    "roofing_system": "envelope",
    "roof_vent_system": "envelope",
    "duct_system": "mechanical",
    "water_heater": "plumbing",
    "tankless_water_heater": "plumbing",
}


def _score_construction_ai_payload(
    candidate: dict[str, Any],
    axis_scores: dict[str, Counter[str]],
    evidence: list[AxisEvidence],
) -> None:
    payload = candidate.get("ai_payload") or {}
    if not payload:
        return
    provider = str(candidate.get("ai_provider") or "").strip().lower()
    asset_ai_id = str(candidate.get("asset_ai_id") or "").strip() or provider or "asset_ai"
    evidence_ref = f"asset_ai:{asset_ai_id}"

    image_type = _normalize_label(str(payload.get("image_type") or ""))
    if image_type == "plan":
        _add_axis_contribution(axis_scores["concern_domain"], evidence, axis_name="concern_domain", axis_value="plans_code_permits", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=1.15, confidence=0.9, note="vision image_type=plan")
        _add_axis_contribution(axis_scores["project_phase"], evidence, axis_name="project_phase", axis_value="design", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.95, confidence=0.84, note="plan imagery implies design phase")
        _add_axis_contribution(axis_scores["concern_class"], evidence, axis_name="concern_class", axis_value="reference_example", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.7, confidence=0.74, note="plan imagery is usually reference/spec material")

    if provider == "gemini-video":
        category = _normalize_label(str(payload.get("category") or ""))
        subcategory = _normalize_label(str(payload.get("subcategory") or ""))
        if category in {"construction", "diy"}:
            _add_axis_contribution(axis_scores["project_phase"], evidence, axis_name="project_phase", axis_value="build", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.95, confidence=_coerce_float(payload.get("confidence"), 0.75), note=f"video category={category}")
            _add_axis_contribution(axis_scores["concern_class"], evidence, axis_name="concern_class", axis_value="reference_example", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.7, confidence=0.72, note=f"video category={category}")
        if subcategory == "exterior":
            _add_axis_contribution(axis_scores["concern_domain"], evidence, axis_name="concern_domain", axis_value="site_exterior", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.72, confidence=0.72, note="video subcategory=exterior")
            _add_axis_contribution(axis_scores["trade_system"], evidence, axis_name="trade_system", axis_value="site", evidence_type="asset_ai_json", evidence_ref=evidence_ref, weight=0.68, confidence=0.7, note="video exterior often maps to site/exterior")

    combined_labels = []
    for bucket in ("text_in_image", "tags", "brands_products", "elements", "materials"):
        combined_labels.extend(_payload_values(payload, bucket))
    joined = " | ".join(combined_labels)
    for axis_name, hint_map in (
        ("concern_domain", CONCERN_DOMAIN_HINTS),
        ("project_phase", PROJECT_PHASE_HINTS),
        ("trade_system", TRADE_SYSTEM_HINTS),
        ("concern_class", CONCERN_CLASS_HINTS),
        ("product_system_focus", PRODUCT_SYSTEM_HINTS),
    ):
        for axis_value, hints in hint_map.items():
            matches = _matching_hints(joined, hints)
            if not matches:
                continue
            conf = min(0.95, 0.62 + 0.06 * len(matches))
            base_weight = 1.05 if axis_name == "product_system_focus" else 0.82
            _add_axis_contribution(
                axis_scores[axis_name],
                evidence,
                axis_name=axis_name,
                axis_value=axis_value,
                evidence_type="asset_ai_json",
                evidence_ref=evidence_ref,
                weight=base_weight * conf,
                confidence=conf,
                note=f"vision tags matched {axis_name}: {', '.join(matches[:6])}",
            )


def _select_construction_axis_memberships(candidate: dict[str, Any]) -> tuple[list[tuple[str, str, float, int, bool, bool]], list[AxisEvidence]]:
    axis_scores = {
        "concern_domain": Counter(),
        "project_phase": Counter(),
        "trade_system": Counter(),
        "concern_class": Counter(),
        "product_system_focus": Counter(),
    }
    evidence: list[AxisEvidence] = []

    _score_axis_hint_map_from_text(candidate=candidate, axis_name="concern_domain", hint_map=CONCERN_DOMAIN_HINTS, scores=axis_scores["concern_domain"], evidence=evidence)
    _score_axis_hint_map_from_text(candidate=candidate, axis_name="project_phase", hint_map=PROJECT_PHASE_HINTS, scores=axis_scores["project_phase"], evidence=evidence)
    _score_axis_hint_map_from_text(candidate=candidate, axis_name="trade_system", hint_map=TRADE_SYSTEM_HINTS, scores=axis_scores["trade_system"], evidence=evidence)
    _score_axis_hint_map_from_text(candidate=candidate, axis_name="concern_class", hint_map=CONCERN_CLASS_HINTS, scores=axis_scores["concern_class"], evidence=evidence)
    _score_axis_hint_map_from_text(candidate=candidate, axis_name="product_system_focus", hint_map=PRODUCT_SYSTEM_HINTS, scores=axis_scores["product_system_focus"], evidence=evidence)
    _score_axis_hint_map_from_source_link(candidate=candidate, axis_name="concern_domain", hint_map=CONCERN_DOMAIN_HINTS, scores=axis_scores["concern_domain"], evidence=evidence)
    _score_axis_hint_map_from_source_link(candidate=candidate, axis_name="project_phase", hint_map=PROJECT_PHASE_HINTS, scores=axis_scores["project_phase"], evidence=evidence)
    _score_axis_hint_map_from_source_link(candidate=candidate, axis_name="trade_system", hint_map=TRADE_SYSTEM_HINTS, scores=axis_scores["trade_system"], evidence=evidence)
    _score_axis_hint_map_from_source_link(candidate=candidate, axis_name="concern_class", hint_map=CONCERN_CLASS_HINTS, scores=axis_scores["concern_class"], evidence=evidence)
    _score_axis_hint_map_from_source_link(candidate=candidate, axis_name="product_system_focus", hint_map=PRODUCT_SYSTEM_HINTS, scores=axis_scores["product_system_focus"], evidence=evidence)

    labels = candidate.get("labels") or []
    _score_axis_hint_map_from_labels(axis_name="concern_domain", hint_map=CONCERN_DOMAIN_HINTS, labels=labels, scores=axis_scores["concern_domain"], evidence=evidence)
    _score_axis_hint_map_from_labels(axis_name="project_phase", hint_map=PROJECT_PHASE_HINTS, labels=labels, scores=axis_scores["project_phase"], evidence=evidence)
    _score_axis_hint_map_from_labels(axis_name="trade_system", hint_map=TRADE_SYSTEM_HINTS, labels=labels, scores=axis_scores["trade_system"], evidence=evidence)
    _score_axis_hint_map_from_labels(axis_name="concern_class", hint_map=CONCERN_CLASS_HINTS, labels=labels, scores=axis_scores["concern_class"], evidence=evidence)
    _score_axis_hint_map_from_labels(axis_name="product_system_focus", hint_map=PRODUCT_SYSTEM_HINTS, labels=labels, scores=axis_scores["product_system_focus"], evidence=evidence)

    _score_construction_ai_payload(candidate, axis_scores, evidence)

    product_system_memberships = _select_multi_axis(
        axis_scores["product_system_focus"],
        min_score=0.68,
        max_values=4,
        relative_threshold=0.35,
    )
    for value, _, _, _, _ in product_system_memberships:
        domain = PRODUCT_SYSTEM_TO_DOMAIN.get(value)
        trade = PRODUCT_SYSTEM_TO_TRADE.get(value)
        if domain:
            _add_axis_contribution(axis_scores["concern_domain"], evidence, axis_name="concern_domain", axis_value=domain, evidence_type="derived_map", evidence_ref=f"product_system_focus:{value}", weight=0.62, confidence=0.72, note=f"derived concern domain from product/system focus: {value}")
        if trade:
            _add_axis_contribution(axis_scores["trade_system"], evidence, axis_name="trade_system", axis_value=trade, evidence_type="derived_map", evidence_ref=f"product_system_focus:{value}", weight=0.62, confidence=0.72, note=f"derived trade system from product/system focus: {value}")

    selected: list[tuple[str, str, float, int, bool, bool]] = []
    for axis_name, memberships in (
        ("concern_domain", _select_single_axis(axis_scores["concern_domain"], min_score=0.62)),
        ("project_phase", _select_single_axis(axis_scores["project_phase"], min_score=0.55)),
        ("trade_system", _select_single_axis(axis_scores["trade_system"], min_score=0.62)),
        ("concern_class", _select_single_axis(axis_scores["concern_class"], min_score=0.52)),
        ("product_system_focus", product_system_memberships),
    ):
        for value, confidence, rank, is_primary, is_ambiguous in memberships:
            selected.append((axis_name, value, confidence, rank, is_primary, is_ambiguous))
    return selected, evidence


def _apply_axis_overrides(
    candidate: dict[str, Any],
    memberships: list[tuple[str, str, float, int, bool, bool]],
    evidence: list[AxisEvidence],
) -> tuple[list[tuple[str, str, float, int, bool, bool]], list[AxisEvidence]]:
    override_rows = [row for row in (candidate.get("overrides") or []) if str(row.get("axis_name") or "").strip() != "track"]
    if not override_rows:
        return memberships, evidence

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in override_rows:
        axis_name = str(row.get("axis_name") or "").strip()
        if not axis_name:
            continue
        grouped.setdefault(axis_name, []).append(row)

    axis_memberships: dict[str, list[tuple[str, float, bool]]] = {}
    axis_order: list[str] = []
    for axis_name, axis_value, confidence, _rank, _is_primary, is_ambiguous in memberships:
        if axis_name not in axis_memberships:
            axis_memberships[axis_name] = []
            axis_order.append(axis_name)
        axis_memberships[axis_name].append((axis_value, confidence, is_ambiguous))

    out_evidence = list(evidence)
    for axis_name, rows in grouped.items():
        if axis_name not in axis_order:
            axis_order.append(axis_name)
        current = list(axis_memberships.get(axis_name, []))
        set_values = _dedupe_labels([str(row.get("axis_value") or "") for row in rows if str(row.get("operation") or "").strip().lower() == "set"])
        remove_values = set(_dedupe_labels([str(row.get("axis_value") or "") for row in rows if str(row.get("operation") or "").strip().lower() == "remove"]))
        add_values = _dedupe_labels([str(row.get("axis_value") or "") for row in rows if str(row.get("operation") or "").strip().lower() == "add"])

        if set_values:
            current = [(value, 0.995, False) for value in set_values]
        else:
            current = [item for item in current if _normalize_label(item[0]) not in remove_values]
            existing = {_normalize_label(item[0]) for item in current}
            for value in add_values:
                if value in existing:
                    continue
                current.append((value, 0.995, False))
                existing.add(value)
        axis_memberships[axis_name] = current

        latest_actor = str(rows[-1].get("actor") or "").strip() or "human"
        latest_note = str(rows[-1].get("note") or "").strip()
        override_values = set(set_values or add_values)
        if override_values:
            for value in override_values:
                out_evidence.append(
                    AxisEvidence(
                        axis_name=axis_name,
                        axis_value=value,
                        evidence_type="manual_override",
                        evidence_ref="asset_overrides",
                        weight=9.0,
                        confidence=0.995,
                        note=latest_note or f"manual {axis_name} override by {latest_actor}",
                    )
                )

    rebuilt: list[tuple[str, str, float, int, bool, bool]] = []
    for axis_name in axis_order:
        current = axis_memberships.get(axis_name, [])
        for index, (value, confidence, is_ambiguous) in enumerate(current, start=1):
            rebuilt.append((axis_name, value, confidence, index, index == 1, is_ambiguous))
    return rebuilt, out_evidence


def _resolve_track_run_id(db: Db, explicit_run_id: str) -> str:
    run_id = str(explicit_run_id or "").strip()
    if run_id:
        exists = db.query_value("select id from classification_runs where id=? limit 1", (run_id,))
        if not exists:
            raise ValueError(f"Track run not found: {run_id}")
        return run_id
    latest = db.query_value(
        """
        select id
        from classification_runs
        where run_type='track_gate'
          and schema_version=?
        order by created_at desc
        limit 1
        """,
        (SCHEMA_VERSION,),
    )
    if not latest:
        raise ValueError("No v2 track_gate run found. Run `curation track-gate-v2` first.")
    return str(latest)


def collect_axis_candidates(
    db: Db,
    *,
    track_run_id: str,
    limit: int = 0,
) -> list[dict[str, Any]]:
    limit_sql = "limit ?" if limit and limit > 0 else ""
    params: list[Any] = [track_run_id, TRACK_STYLE, TRACK_CONSTRUCTION, TRACK_MAINTENANCE]
    if limit_sql:
        params.append(int(limit))
    rows = db.query(
        f"""
        select ata.asset_id, ata.track, ata.confidence as track_confidence, ata.is_ambiguous as track_is_ambiguous,
               a.source, a.source_ref, a.source_url, a.title, a.description, a.board, a.notes,
               a.ai_summary, a.category, a.imported_at,
               p.origin_type as title_origin_type,
               p.confidence as title_origin_confidence,
               p.origin_ref as title_origin_ref,
               (select group_concat(al.label, '|') from asset_labels al where al.asset_id = a.id) as labels_csv
        from asset_track_assessments ata
        join assets a on a.id = ata.asset_id
        left join asset_field_provenance p
          on p.asset_id = a.id
         and p.field_name = 'title'
         and p.is_current = 1
        where ata.run_id = ?
          and ata.track in (?, ?, ?)
        order by a.imported_at desc
        {limit_sql}
        """,
        tuple(params),
    )
    candidates: list[dict[str, Any]] = []
    asset_ids: list[str] = []
    for row in rows:
        asset_id = str(row["asset_id"])
        asset_ids.append(asset_id)
        candidates.append(
            {
                "asset_id": asset_id,
                "track": str(row["track"] or "").strip(),
                "track_confidence": row["track_confidence"],
                "track_is_ambiguous": bool(int(row["track_is_ambiguous"] or 0)),
                "source": str(row["source"] or "").strip().lower(),
                "source_ref": str(row["source_ref"] or "").strip(),
                "source_url": str(row["source_url"] or "").strip(),
                "title": str(row["title"] or "").strip(),
                "description": str(row["description"] or "").strip(),
                "board": str(row["board"] or "").strip(),
                "notes": str(row["notes"] or "").strip(),
                "ai_summary": str(row["ai_summary"] or "").strip(),
                "category": str(row["category"] or "").strip().lower(),
                "imported_at": str(row["imported_at"] or "").strip(),
                "title_origin_type": str(row["title_origin_type"] or "").strip().lower(),
                "title_origin_confidence": row["title_origin_confidence"],
                "title_origin_ref": str(row["title_origin_ref"] or "").strip(),
                "labels": _labels_from_csv(row["labels_csv"]),
            }
        )

    if not asset_ids:
        return candidates

    placeholders = ",".join(["?"] * len(asset_ids))
    ai_rows = db.query(
        f"""
        select ai.id, ai.asset_id, ai.provider, ai.model, ai.summary, ai.json, ai.created_at
        from asset_ai ai
        join (
          select asset_id, max(created_at) as max_created_at
          from asset_ai
          where asset_id in ({placeholders})
          group by asset_id
        ) latest
          on latest.asset_id = ai.asset_id
         and latest.max_created_at = ai.created_at
        where ai.asset_id in ({placeholders})
        """,
        tuple(asset_ids + asset_ids),
    )
    ai_by_asset: dict[str, sqlite3.Row] = {}
    for row in ai_rows:
        ai_by_asset[str(row["asset_id"])] = row
    overrides_by_asset = _load_active_overrides(db, asset_ids)
    source_link_by_asset = _load_latest_fetched_source_link_enrichment(db, asset_ids)
    for candidate in candidates:
        ai_row = ai_by_asset.get(candidate["asset_id"])
        source_link_row = source_link_by_asset.get(candidate["asset_id"])
        candidate["source_page_title"] = str(source_link_row["page_title"] if source_link_row else "").strip()
        candidate["source_page_og_title"] = str(source_link_row["og_title"] if source_link_row else "").strip()
        candidate["source_page_meta_description"] = str(source_link_row["meta_description"] if source_link_row else "").strip()
        candidate["source_page_og_description"] = str(source_link_row["og_description"] if source_link_row else "").strip()
        candidate["source_page_text_excerpt"] = str(source_link_row["text_excerpt"] if source_link_row else "").strip()
        if not ai_row:
            candidate["asset_ai_id"] = ""
            candidate["ai_provider"] = ""
            candidate["ai_model"] = ""
            candidate["ai_payload"] = {}
            candidate["overrides"] = overrides_by_asset.get(candidate["asset_id"], [])
            continue
        candidate["asset_ai_id"] = str(ai_row["id"] or "")
        candidate["ai_provider"] = str(ai_row["provider"] or "").strip().lower()
        candidate["ai_model"] = str(ai_row["model"] or "").strip()
        candidate["ai_payload"] = _safe_json_object(ai_row["json"])
        candidate["overrides"] = overrides_by_asset.get(candidate["asset_id"], [])
    return candidates


def run_multi_axis_inference_v2(
    db: Db,
    *,
    track_run_id: str = "",
    limit: int = 0,
    notes: str = "",
) -> dict[str, Any]:
    resolved_track_run_id = _resolve_track_run_id(db, track_run_id)
    run_id = str(uuid.uuid4())
    created_at = _now_iso()
    config = {"track_run_id": resolved_track_run_id, "limit": int(limit or 0)}
    db.exec(
        """
        insert into classification_runs
          (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            SCHEMA_VERSION,
            "multi_axis_inference",
            "heuristic",
            DEFAULT_AXIS_MODEL,
            "",
            json.dumps(config, ensure_ascii=True, sort_keys=True),
            created_at,
            notes or None,
        ),
    )

    candidates = collect_axis_candidates(db, track_run_id=resolved_track_run_id, limit=limit)
    membership_rows: list[tuple[Any, ...]] = []
    evidence_rows: list[tuple[Any, ...]] = []
    axis_counts: Counter[str] = Counter()
    track_counts: Counter[str] = Counter()
    ambiguous_memberships = 0

    for candidate in candidates:
        track = str(candidate.get("track") or "").strip()
        if track == TRACK_STYLE:
            memberships, evidence = _select_style_axis_memberships(candidate)
        elif track in {TRACK_CONSTRUCTION, TRACK_MAINTENANCE}:
            memberships, evidence = _select_construction_axis_memberships(candidate)
        else:
            memberships, evidence = ([], [])
        memberships, evidence = _apply_axis_overrides(candidate, memberships, evidence)
        asset_id = str(candidate["asset_id"])
        track_counts[track] += 1
        for axis_name, axis_value, confidence, rank, is_primary, is_ambiguous in memberships:
            membership_rows.append(
                (
                    str(uuid.uuid4()),
                    run_id,
                    asset_id,
                    track,
                    axis_name,
                    axis_value,
                    confidence,
                    rank,
                    1 if is_primary else 0,
                    1 if is_ambiguous else 0,
                    created_at,
                )
            )
            axis_counts[axis_name] += 1
            if is_ambiguous:
                ambiguous_memberships += 1
        accepted_keys = {(axis_name, axis_value) for axis_name, axis_value, *_ in memberships}
        for item in evidence:
            if (item.axis_name, item.axis_value) not in accepted_keys:
                continue
            evidence_rows.append(
                (
                    str(uuid.uuid4()),
                    run_id,
                    asset_id,
                    track,
                    item.axis_name,
                    item.axis_value,
                    item.evidence_type,
                    item.evidence_ref,
                    item.weight,
                    item.confidence,
                    item.note,
                    created_at,
                )
            )

    if membership_rows:
        db.executemany(
            """
            insert into asset_axis_memberships
              (id, run_id, asset_id, track, axis_name, axis_value, confidence, rank, is_primary, is_ambiguous, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            membership_rows,
        )
    if evidence_rows:
        db.executemany(
            """
            insert into asset_axis_evidence
              (id, run_id, asset_id, track, axis_name, axis_value, evidence_type, evidence_ref,
               weight, confidence, note, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            evidence_rows,
        )

    return {
        "ok": True,
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "run_type": "multi_axis_inference",
        "model_provider": "heuristic",
        "model_name": DEFAULT_AXIS_MODEL,
        "track_run_id": resolved_track_run_id,
        "candidate_count": len(candidates),
        "memberships_written": len(membership_rows),
        "evidence_written": len(evidence_rows),
        "ambiguous_memberships": ambiguous_memberships,
        "track_counts": {k: int(v) for k, v in sorted(track_counts.items())},
        "axis_counts": {k: int(v) for k, v in sorted(axis_counts.items())},
    }
