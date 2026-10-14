"""Gemini-backed CrisisCore disaster-safety assistant."""
import logging
import re
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_MAX_TOKENS,
    LLM_TIMEOUT_SECONDS,
)

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types
    HAS_GEMINI = True
except ImportError:
    genai = None
    genai_errors = None
    genai_types = None
    HAS_GEMINI = False

logger = logging.getLogger(__name__)
SUPPORTED_FALLBACK_MODEL = "gemini-3.6-flash"
_API_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
_SECRET_PARAM_PATTERN = re.compile(
    r"(?i)(api[_-]?key|key|authorization)(\s*[=:]\s*)[^\s&,;]+"
)


def has_google_api_key_format(api_key: str = GEMINI_API_KEY) -> bool:
    """Google AI Studio / Gemini Developer API keys use the AIza prefix."""
    return bool(api_key and api_key.startswith("AIza") and not any(c.isspace() for c in api_key))

# System prompt — grounds the assistant in disaster-response domain
SYSTEM_PROMPT = """You are CrisisCore Assistant, a disaster-response AI for India.

You help users understand:
- Current disaster conditions and risk levels at their location
- Emergency preparedness steps for floods, earthquakes, heatwaves, droughts, and cyclones
- Nearby emergency resources (hospitals, shelters)
- How to interpret AI risk scores from the CrisisCore dashboard

Rules:
1. Ground every answer in the provided LIVE CONTEXT block when it is available.
2. Never invent phone numbers, shelter capacity, official orders, or event details not in context.
3. If data is unavailable, say so clearly instead of guessing.
4. Distinguish between observed events (USGS, Sentinel-1) and ML-derived risk assessments.
5. Keep answers concise, accurate, and actionable for emergency situations.
6. If asked about something unrelated to disaster safety, politely redirect.
7. Never claim to predict disasters with certainty; describe risk assessments as estimates.
"""

def _build_context_block(context: Optional[Dict[str, Any]]) -> str:
    """Convert live context dict into a readable text block for the LLM."""
    if not context:
        return "[No live context available]"

    lines = ["=== LIVE CONTEXT ==="]

    # Location
    loc = context.get("location", {})
    lines.append(f"Location: lat={loc.get('lat','?')}, lon={loc.get('lon','?')}")

    # Weather
    w = context.get("weather", {})
    if w.get("status") == "ok":
        lines.append(
            f"Weather at {w.get('location_name','?')}: "
            f"{w.get('temperature_c','?')}°C, feels like {w.get('feels_like_c','?')}°C, "
            f"humidity {w.get('humidity_pct','?')}%, wind {w.get('wind_speed_ms','?')} m/s, "
            f"condition: {w.get('condition','?')} — {w.get('description','')}"
        )
    else:
        lines.append("Weather: unavailable")

    # AI Risk
    risk_data = context.get("ai_risk_scores", {})
    overall = risk_data.get("overall", {})
    lines.append(
        f"Overall AI Risk: {overall.get('level','?')} (score {overall.get('score','?')}/100, "
        f"confidence {round((overall.get('confidence') or 0)*100)}%)"
    )
    for dtype, r in risk_data.get("risks", {}).items():
        if r.get("available"):
            lines.append(
                f"  {dtype.capitalize()} risk: {r.get('level','?')} ({r.get('score','?')}%) "
                f"— factors: {', '.join(r.get('factors', []))}"
            )

    # Flood satellite
    fi = context.get("flood_info", {})
    if fi.get("flood_detected"):
        lines.append(
            f"Flood: DETECTED by Sentinel-1 satellite — "
            f"{fi.get('flooded_area_km2','?')} km² (image date: {fi.get('satellite_image_date','?')})"
        )
    elif fi.get("satellite_ready"):
        lines.append("Flood: No new flood detected in this area per latest Sentinel-1 data.")
    else:
        lines.append("Flood satellite: Earth Engine not initialized — satellite data unavailable.")

    # Earthquakes
    eq = context.get("earthquake_event", {})
    closest = eq.get("closest_event")
    if closest and closest.get("magnitude", 0) > 0:
        lines.append(
            f"Nearest earthquake: M{closest.get('magnitude','?')} at "
            f"{round(eq.get('distance_km') or 999)} km, depth {closest.get('depth_km','?')} km, "
            f"at {closest.get('time_iso','?')}"
        )

    # Resources
    res = context.get("nearest_resources", {})
    h = res.get("closest_hospital")
    s = res.get("closest_shelter")
    if h:
        lines.append(f"Nearest hospital: {h.get('name','?')} ({h.get('distance_km','?')} km)")
    if s:
        lines.append(f"Nearest shelter: {s.get('name','?')} ({s.get('distance_km','?')} km)")

    # Alerts
    alerts = context.get("alerts", [])
    active_alerts = [a for a in alerts if a.get("severity") in ("high", "critical")]
    if active_alerts:
        lines.append(f"Active alerts ({len(active_alerts)}):")
        for a in active_alerts[:3]:
            lines.append(f"  [{a.get('severity','?').upper()}] {a.get('title','?')} — {a.get('message','')}")

    lines.append(f"Context generated at: {context.get('timestamp','?')}")
    lines.append("=== END CONTEXT ===")
    return "\n".join(lines)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _sanitize_provider_text(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    if GEMINI_API_KEY:
        text = text.replace(GEMINI_API_KEY, "[REDACTED]")
    text = _API_KEY_PATTERN.sub("[REDACTED]", text)
    text = _SECRET_PARAM_PATTERN.sub(r"\1\2[REDACTED]", text)
    return " ".join(text.split())[:400]


def _provider_diagnostics(exc: Exception) -> Dict[str, Any]:
    """Extract useful Google error details without retaining credentials or prompts."""
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if not isinstance(status_code, (int, str)):
        code_value = getattr(exc, "code", None)
        status_code = code_value if isinstance(code_value, (int, str)) else None

    body = getattr(exc, "response_json", None)
    if body is None:
        body = getattr(exc, "details", None)
    error_body = _field(body, "error", body)
    provider_code = (
        _field(error_body, "status")
        or _field(error_body, "reason")
        or _field(exc, "status")
        or _field(error_body, "code")
    )
    if not provider_code:
        details = _field(error_body, "details", []) or []
        for detail in details:
            provider_code = _field(detail, "reason") or _field(detail, "code")
            if provider_code:
                break

    raw_message = (
        _field(error_body, "message")
        or getattr(exc, "message", None)
        or str(exc)
    )
    return {
        "http_status": status_code,
        "provider_code": _sanitize_provider_text(provider_code)[:100] if provider_code else None,
        "message": _sanitize_provider_text(raw_message),
    }


def _classify_provider_error(exc: Exception, diagnostics: Dict[str, Any]) -> str:
    status_code = diagnostics["http_status"]
    provider_code = (diagnostics["provider_code"] or "").upper()
    message = diagnostics["message"].lower()

    if any(term in provider_code for term in ("API_KEY_INVALID", "INVALID_API_KEY")):
        return "invalid_api_key"
    if any(term in message for term in ("api key not valid", "invalid api key", "api_key_invalid")):
        return "invalid_api_key"
    if status_code == 429 or any(
        term in provider_code for term in ("RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED", "RATE_LIMIT")
    ) or any(term in message for term in ("quota", "rate limit", "resource exhausted")):
        return "rate_limited"
    if status_code == 404 or any(
        term in provider_code for term in ("NOT_FOUND", "MODEL_NOT_FOUND")
    ) or (
        "model" in message
        and any(term in message for term in ("not found", "not supported", "unsupported"))
    ):
        return "unsupported_model"
    if any(term in provider_code for term in ("PROMPT_BLOCKED", "PROHIBITED_CONTENT", "SAFETY")):
        return "prompt_blocked"
    if status_code == 400 and any(term in message for term in ("blocked", "safety filter", "prohibited content")):
        return "prompt_blocked"
    if status_code == 402 or any(
        term in provider_code for term in ("BILLING_DISABLED", "BILLING_NOT_ENABLED", "ACCESS_RESTRICTED")
    ) or (
        "billing" in provider_code.lower()
        or "billing" in message
        or "failed_precondition" in provider_code.lower()
        or "access_restricted" in provider_code.lower()
        or "permission_denied" in provider_code.lower()
        or status_code == 403
    ):
        return "access_restricted"
    if (
        status_code in (408, 504)
        or "deadline_exceeded" in provider_code.lower()
        or "deadline expired" in message
        or isinstance(exc, (TimeoutError,))
        or "timeout" in message
        or "timed out" in message
    ):
        return "timeout"
    if status_code == 503 or any(
        term in provider_code for term in ("UNAVAILABLE", "SERVICE_UNAVAILABLE")
    ) or "high demand" in message or "temporarily unavailable" in message:
        return "service_unavailable"
    if isinstance(exc, (ConnectionError, OSError)) or any(
        term in message for term in ("connection", "network", "unreachable")
    ):
        return "connection_error"
    if genai_errors and isinstance(exc, genai_errors.APIError):
        return "api_error"
    return "provider_error"


def _blocked_response_reason(response: Any) -> Optional[str]:
    feedback = getattr(response, "prompt_feedback", None)
    block_reason = _field(feedback, "block_reason")
    block_name = str(block_reason).rsplit(".", 1)[-1].upper() if block_reason else ""
    if block_name.startswith("BLOCKED_REASON_"):
        block_name = block_name.removeprefix("BLOCKED_REASON_")
    if block_name and block_name not in ("UNSPECIFIED", "0"):
        return str(block_reason)

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        finish_reason = _field(candidate, "finish_reason")
        finish_name = str(finish_reason).rsplit(".", 1)[-1].upper() if finish_reason else ""
        if finish_name.startswith("FINISH_REASON_"):
            finish_name = finish_name.removeprefix("FINISH_REASON_")
        if finish_name and any(
            flag in finish_name
            for flag in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII")
        ):
            return str(finish_reason)
    return None


def chat_with_assistant(
    messages: List[Dict[str, str]],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Send messages to the LLM with injected disaster context.
    Returns structured response dict.
    """
    if not GEMINI_API_KEY:
        return {
            "success": False,
            "reply": (
                "AI Assistant requires a Gemini API key. "
                "Set the GEMINI_API_KEY environment variable to enable live inference. "
                "The rest of the CrisisCore dashboard is fully functional without it."
            ),
            "model": None,
            "context_used": False,
            "error": "credentials_required",
        }

    if not has_google_api_key_format():
        logger.error(
            "Gemini credential format check failed: key is set but does not match Google API key format"
        )
        return {
            "success": False,
            "reply": (
                "The configured GEMINI_API_KEY does not look like a Google AI Studio API key. "
                "Create or copy a Gemini API key from Google AI Studio, then restart the backend. "
                "The key value is never logged."
            ),
            "model": None,
            "context_used": False,
            "error": "invalid_api_key_format",
        }

    if not HAS_GEMINI:
        return {
            "success": False,
            "reply": "Google Gen AI SDK is not installed. Run: pip install google-genai",
            "model": None,
            "context_used": False,
            "error": "package_missing",
        }

    context_block = _build_context_block(context)
    context_used = bool(context)

    system_instruction = SYSTEM_PROMPT
    if context:
        system_instruction += f"\n\n{context_block}"

    # Sanitize and limit history
    safe_messages = []
    for m in messages[-12:]:  # last 12 turns max
        role = m.get("role", "user")
        content = str(m.get("content", ""))[:4000]
        if role in ("user", "assistant") and content.strip():
            safe_messages.append(genai_types.Content(
                role="model" if role == "assistant" else "user",
                parts=[genai_types.Part(text=content)],
            ))

    client = None
    started = time.time()
    models_to_try = [GEMINI_MODEL]
    if GEMINI_MODEL != SUPPORTED_FALLBACK_MODEL:
        models_to_try.append(SUPPORTED_FALLBACK_MODEL)

    for model_index, model_name in enumerate(models_to_try):
        attempts_for_model = 2 if model_index == 0 else 1
        for attempt in range(attempts_for_model):
            try:
                if client is None:
                    client = genai.Client(
                        api_key=GEMINI_API_KEY,
                        http_options=genai_types.HttpOptions(timeout=LLM_TIMEOUT_SECONDS * 1000),
                    )

                response = client.models.generate_content(
                    model=model_name,
                    contents=safe_messages,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        max_output_tokens=LLM_MAX_TOKENS,
                        temperature=0.4,
                    ),
                )

                blocked_reason = _blocked_response_reason(response)
                if blocked_reason:
                    logger.warning(
                        "Gemini prompt blocked model=%s provider_code=%s",
                        model_name,
                        blocked_reason[:100],
                    )
                    return {
                        "success": False,
                        "reply": "Gemini blocked this prompt under its safety policies. Please rephrase the question.",
                        "model": None,
                        "context_used": context_used,
                        "error": "prompt_blocked",
                    }

                reply = (response.text or "").strip()
                if not reply:
                    raise RuntimeError("Gemini returned an empty response")
                usage = getattr(response, "usage_metadata", None)
                return {
                    "success": True,
                    "reply": reply,
                    "model": model_name,
                    "usage": {
                        "prompt_tokens": getattr(usage, "prompt_token_count", None),
                        "completion_tokens": getattr(usage, "candidates_token_count", None),
                    },
                    "context_used": context_used,
                    "elapsed_seconds": round(time.time() - started, 2),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            except Exception as exc:
                diagnostics = _provider_diagnostics(exc)
                error = _classify_provider_error(exc, diagnostics)
                logger.error(
                    "Gemini request failed model=%s attempt=%s exception=%s http_status=%s "
                    "provider_code=%s message=%s",
                    model_name,
                    attempt + 1,
                    type(exc).__name__,
                    diagnostics["http_status"],
                    diagnostics["provider_code"],
                    diagnostics["message"],
                )

                if error == "timeout" and attempt == 0:
                    logger.warning("Gemini deadline exceeded; retrying once model=%s", model_name)
                    time.sleep(0.4)
                    continue

                if error in ("rate_limited", "unsupported_model") and model_index == 0 and len(models_to_try) > 1:
                    logger.warning(
                        "Configured Gemini model cannot serve this request; switching to fallback model=%s reason=%s",
                        SUPPORTED_FALLBACK_MODEL,
                        error,
                    )
                    break

                if error in ("timeout", "service_unavailable") and model_index == 0 and len(models_to_try) > 1:
                    logger.warning(
                        "Configured Gemini model did not complete; trying supported fallback model=%s",
                        SUPPORTED_FALLBACK_MODEL,
                    )
                    break

                messages_by_error = {
                    "invalid_api_key": "Gemini API key is invalid. Check the GEMINI_API_KEY environment variable.",
                    "rate_limited": "Gemini quota or rate limit reached. Check Google AI Studio quota and try again later.",
                    "service_unavailable": "Google Gemini is temporarily experiencing high demand. Please retry shortly.",
                    "unsupported_model": "The configured Gemini model is unavailable to this API key. Check GEMINI_MODEL and model access.",
                    "access_restricted": "Gemini access is restricted. Check API billing, project access, and Google AI Studio availability.",
                    "prompt_blocked": "Gemini blocked this prompt under its safety policies. Please rephrase the question.",
                    "timeout": "Google Gemini timed out twice (DEADLINE_EXCEEDED). Please retry shortly; the provider did not complete this request.",
                    "connection_error": "The AI assistant could not connect to Google. Check backend network access and try again.",
                    "api_error": "Gemini returned an API error. Check backend logs for sanitized provider diagnostics.",
                    "provider_error": "Gemini returned an unexpected provider error. Check backend logs for sanitized diagnostics.",
                }
                reply = messages_by_error.get(
                    error,
                    "Gemini request failed. Check backend logs for sanitized diagnostics.",
                )
                if model_index > 0:
                    reply = f"Gemini fallback model {model_name} also failed: {reply}"
                return {
                    "success": False,
                    "reply": reply,
                    "model": None,
                    "context_used": context_used,
                    "error": error,
                }

    return {
        "success": False,
        "reply": "No configured Gemini model could serve this request.",
        "model": None,
        "context_used": context_used,
        "error": "unsupported_model",
    }
