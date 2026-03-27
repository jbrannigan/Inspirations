from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


AMBIGUOUS_LOW_SIGNAL_URL = "ambiguous_low_signal_url"
AMBIGUOUS_MEDIA_MISMATCH = "ambiguous_media_mismatch"
AMBIGUOUS_MEDIA_LINK_MISMATCH = "ambiguous_media_link_mismatch"
AMBIGUOUS_MEDIA_WEAK_THUMBNAIL = "ambiguous_media_weak_thumbnail"
AMBIGUOUS_TRUE_CONTESTED = "ambiguous_true_contested"

LOW_SIGNAL_EVIDENCE_HINTS = {
    "assets.category=home_design",
    "source prior for pinterest",
    "assets.category=other",
    "assets.category=diy",
    "assets.category=product_review",
    "video category=product_review",
    "video category=diy",
}

LANDSCAPE_HINTS = (
    "landscape",
    "landscaping",
    "garden",
    "botanical",
    "botanicals",
    "perennial",
    "verbena",
    "outdoor maintenance",
    "driveway",
    "yard",
)

HOME_DECOR_HINTS = (
    "paint colors",
    "paint color",
    "greige",
    "home decor",
    "decor",
    "interior design",
    "interiors",
    "styling",
)

CONSTRUCTION_HINTS = (
    "builder",
    "builders",
    "building",
    "construction",
    "inspector",
    "inspection",
    "checklist",
    "qualifying",
    "generator",
    "window",
    "roof",
    "electrical",
    "foundation",
    "framing",
    "garage",
    "attic",
    "gutter",
    "rainwater",
    "home improvement",
)

IRRELEVANT_HINTS = (
    "barry manilow",
    "protest",
    "celebrity",
    "concert",
    "music",
    "workout",
    "exercise",
    "fitness",
    "kettlebells",
    "makeup",
    "beauty",
    "eyeshadow",
    "cosmetics",
    "skincare",
    "nail",
    "nails",
)

NON_HOME_MEDIA_HINTS = (
    "statement",
    "text-based",
    "overlay",
    "portrait",
    "portraits",
    "suited man",
    "protest scenes",
    "facial hair",
    "clothing",
    "polo shirt",
    "logo",
    "beard",
)

PLACEHOLDER_THUMBNAIL_HINTS = (
    "fedora and glasses",
    "fedora",
    "glasses icon",
    "anonymous",
    "avatar",
    "placeholder",
    "purple background",
    "silhouette",
    "profile icon",
)

HOME_VISUAL_HINTS = (
    "kitchen",
    "bathroom",
    "bedroom",
    "living room",
    "mudroom",
    "paint",
    "decor",
    "garden",
    "landscape",
    "driveway",
    "builder",
    "construction",
    "inspection",
    "roof",
    "window",
    "gutter",
    "cabinetry",
    "hooks",
)


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _contains_hint(text: str, hint: str) -> bool:
    haystack = _normalize(text)
    needle = _normalize(hint)
    if not needle:
        return False
    if " " in needle:
        return needle in haystack
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(_contains_hint(text, hint) for hint in hints)


def _parse_top_evidence(reason: str) -> list[str]:
    text = str(reason or "")
    marker = "top evidence:"
    if marker not in text:
        return []
    tail = text.split(marker, 1)[1].strip()
    return [part.strip() for part in tail.split(" | ") if part.strip()]


def _is_url_backed(asset: dict[str, Any]) -> bool:
    for key in ("source_url", "source_ref"):
        value = str(asset.get(key) or "").strip()
        if value.startswith("http://") or value.startswith("https://"):
            return True
    return False


def _source_domain(asset: dict[str, Any]) -> str:
    explicit = _normalize(asset.get("source_domain", ""))
    if explicit:
        return explicit
    for key in ("source_url", "source_ref"):
        value = str(asset.get(key) or "").strip()
        if not value:
            continue
        try:
            host = (urlparse(value).hostname or "").strip().lower()
        except Exception:
            host = ""
        if host:
            return host
    return ""


def _source_link_context(asset: dict[str, Any], source_link: dict[str, Any]) -> str:
    parts = [
        asset.get("source_domain", ""),
        asset.get("source_ref", ""),
        asset.get("source_url", ""),
        source_link.get("final_domain", ""),
        source_link.get("final_url", ""),
        source_link.get("canonical_url", ""),
        source_link.get("page_title", ""),
        source_link.get("og_title", ""),
        source_link.get("meta_description", ""),
        source_link.get("og_description", ""),
        source_link.get("text_excerpt", ""),
    ]
    return " | ".join(str(part or "") for part in parts if str(part or "").strip())


def _combined_context(asset: dict[str, Any], ai: dict[str, Any], source_link: dict[str, Any] | None = None) -> str:
    parts = [
        asset.get("title", ""),
        asset.get("board", ""),
        asset.get("description", ""),
        asset.get("notes", ""),
        _source_domain(asset),
        asset.get("source_ref", ""),
        asset.get("source_url", ""),
        ai.get("summary", ""),
    ]
    payload = ai.get("payload") or {}
    for key in ("summary", "actual_content"):
        parts.append(payload.get(key, ""))
    for key in ("text_in_image", "tags", "elements", "brands_products"):
        for item in payload.get(key) or []:
            parts.append(item)
    if source_link:
        parts.append(_source_link_context(asset, source_link))
    return " | ".join(str(part or "") for part in parts if str(part or "").strip())


def _is_low_signal_url(asset: dict[str, Any], track: dict[str, Any], ai: dict[str, Any], source_link: dict[str, Any] | None = None) -> bool:
    if not _is_url_backed(asset):
        return False
    evidence = _parse_top_evidence(track.get("track_reason", ""))
    source_status = _normalize((source_link or {}).get("fetch_status", ""))
    if not ai and evidence and all(part in LOW_SIGNAL_EVIDENCE_HINTS for part in evidence):
        return True
    if evidence and all(part in LOW_SIGNAL_EVIDENCE_HINTS for part in evidence):
        payload = ai.get("payload") or {}
        if not payload and source_status not in {"fetched", "http_error"}:
            return True
        image_type = _normalize(payload.get("image_type", ""))
        if image_type in {"", "other", "document"} and source_status not in {"fetched", "http_error"}:
            return True
    return False


def _is_media_mismatch(asset: dict[str, Any], track: dict[str, Any], ai: dict[str, Any], source_link: dict[str, Any] | None = None) -> bool:
    if not _is_url_backed(asset):
        return False
    payload = ai.get("payload") or {}
    if not payload and not source_link:
        return False
    image_type = _normalize(payload.get("image_type", ""))
    combined = _combined_context(asset, ai, source_link)
    source_context = _source_link_context(asset, source_link or {})
    ai_text = " | ".join(
        [
            ai.get("summary", ""),
            payload.get("summary", ""),
            payload.get("actual_content", ""),
            " | ".join(str(item) for item in payload.get("text_in_image") or []),
            " | ".join(str(item) for item in payload.get("tags") or []),
            " | ".join(str(item) for item in payload.get("elements") or []),
        ]
    )
    has_non_home_media = _contains_any(ai_text, NON_HOME_MEDIA_HINTS) or _contains_any(ai_text, IRRELEVANT_HINTS)
    has_home_visual = _contains_any(ai_text, HOME_VISUAL_HINTS)
    has_placeholder_thumbnail = _contains_any(ai_text, PLACEHOLDER_THUMBNAIL_HINTS)
    source_home = _contains_any(source_context, HOME_DECOR_HINTS + LANDSCAPE_HINTS + CONSTRUCTION_HINTS)
    source_non_home = _contains_any(source_context, IRRELEVANT_HINTS + NON_HOME_MEDIA_HINTS)
    reason = str(track.get("track_reason") or "")
    low_signal_reason = reason.endswith("top evidence: assets.category=home_design") or reason.endswith("top evidence: assets.category=other")
    if has_placeholder_thumbnail:
        return True
    if source_context and has_home_visual and source_non_home and not source_home:
        return True
    if source_context and source_home and (image_type in {"other", "document", ""} or not has_home_visual):
        return True
    if image_type == "document" and _contains_any(ai_text, IRRELEVANT_HINTS + NON_HOME_MEDIA_HINTS):
        return True
    if image_type in {"other", "document"} and has_non_home_media and not has_home_visual:
        return True
    if low_signal_reason and has_non_home_media and not _contains_any(combined, HOME_DECOR_HINTS + LANDSCAPE_HINTS + CONSTRUCTION_HINTS):
        return True
    return False


def classify_media_mismatch_subtype(
    asset: dict[str, Any], track: dict[str, Any], ai: dict[str, Any], source_link: dict[str, Any] | None = None
) -> tuple[str, str]:
    payload = ai.get("payload") or {}
    image_type = _normalize(payload.get("image_type", ""))
    context = _combined_context(asset, ai, source_link)
    source_context = _source_link_context(asset, source_link or {})
    ai_text = " | ".join(
        [
            ai.get("summary", ""),
            payload.get("summary", ""),
            payload.get("actual_content", ""),
            " | ".join(str(item) for item in payload.get("text_in_image") or []),
            " | ".join(str(item) for item in payload.get("tags") or []),
            " | ".join(str(item) for item in payload.get("elements") or []),
        ]
    )
    context_home = _contains_any(context, HOME_DECOR_HINTS + LANDSCAPE_HINTS + CONSTRUCTION_HINTS)
    context_irrelevant = _contains_any(context, IRRELEVANT_HINTS)
    source_home = _contains_any(source_context, HOME_DECOR_HINTS + LANDSCAPE_HINTS + CONSTRUCTION_HINTS)
    source_irrelevant = _contains_any(source_context, IRRELEVANT_HINTS + NON_HOME_MEDIA_HINTS)
    visual_home = _contains_any(ai_text, HOME_VISUAL_HINTS)
    visual_non_home = _contains_any(ai_text, NON_HOME_MEDIA_HINTS) or _contains_any(ai_text, IRRELEVANT_HINTS)
    placeholder_thumbnail = _contains_any(ai_text, PLACEHOLDER_THUMBNAIL_HINTS)

    if placeholder_thumbnail:
        return (
            AMBIGUOUS_MEDIA_WEAK_THUMBNAIL,
            "Thumbnail looks like an anonymous placeholder/avatar rather than content evidence.",
        )
    if _contains_any(ai_text, IRRELEVANT_HINTS):
        return (
            AMBIGUOUS_MEDIA_LINK_MISMATCH,
            "Thumbnail/image appears unrelated to the saved home-design link.",
        )
    if source_context and source_irrelevant and not source_home and visual_home:
        return (
            AMBIGUOUS_MEDIA_LINK_MISMATCH,
            "Source page looks unrelated, while the thumbnail/image looks home-related.",
        )
    if source_context and source_home and (image_type in {"other", "document", ""} or visual_non_home):
        return (
            AMBIGUOUS_MEDIA_WEAK_THUMBNAIL,
            "Source page looks home-related, but the thumbnail/image is generic or misleading.",
        )

    if visual_home and (context_irrelevant or not context_home):
        return (
            AMBIGUOUS_MEDIA_LINK_MISMATCH,
            "Thumbnail/image evidence looks home-related, but the saved link context looks unrelated or weak.",
        )
    if (image_type in {"other", "document"} or visual_non_home) and context_home and not visual_home:
        return (
            AMBIGUOUS_MEDIA_WEAK_THUMBNAIL,
            "Source link and title look home-related, but the thumbnail/image is generic or not informative.",
        )
    if visual_non_home and not context_home:
        return (
            AMBIGUOUS_MEDIA_LINK_MISMATCH,
            "Visual evidence looks unrelated to the saved home-design link.",
        )
    return (
        AMBIGUOUS_MEDIA_MISMATCH,
        "Visual evidence looks unrelated, generic, or mismatched to the saved home-design URL.",
    )


def suggest_track_for_low_signal_url(
    asset: dict[str, Any], ai: dict[str, Any], source_link: dict[str, Any] | None = None
) -> tuple[str, str]:
    context = _combined_context(asset, ai, source_link)
    if _contains_any(context, CONSTRUCTION_HINTS):
        return ("construction_concern", "URL/title/domain suggest builder, inspector, system, or construction context.")
    if _contains_any(context, LANDSCAPE_HINTS):
        return ("style_product_decor", "URL/title/domain suggest landscaping or outdoor style reference.")
    if _contains_any(context, HOME_DECOR_HINTS):
        return ("style_product_decor", "URL/title/domain suggest home decor or finish/style reference.")
    if _contains_any(context, IRRELEVANT_HINTS):
        return ("irrelevant", "URL/title/domain suggest unrelated media rather than home-design content.")
    return ("", "")


def classify_ambiguous_review_bucket(
    asset: dict[str, Any], track: dict[str, Any], ai: dict[str, Any], source_link: dict[str, Any] | None = None
) -> tuple[str, str, str]:
    if _is_media_mismatch(asset, track, ai, source_link):
        subtype, reason = classify_media_mismatch_subtype(asset, track, ai, source_link)
        return (subtype, "", reason)
    if _is_low_signal_url(asset, track, ai, source_link):
        suggested_track, suggested_reason = suggest_track_for_low_signal_url(asset, ai, source_link)
        return (AMBIGUOUS_LOW_SIGNAL_URL, suggested_track, suggested_reason)
    return (
        AMBIGUOUS_TRUE_CONTESTED,
        "",
        "Mixed home-design signals remain after image, text, and source evidence are considered.",
    )
