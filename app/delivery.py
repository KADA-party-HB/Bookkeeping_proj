import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app


class DeliveryServiceError(RuntimeError):
    def __init__(self, code: str, *, message: str | None = None):
        super().__init__(message or code)
        self.code = code


class DeliveryAddressValidationError(DeliveryServiceError):
    pass


@dataclass(frozen=True)
class GeocodedAddress:
    formatted_address: str
    latitude: Decimal
    longitude: Decimal
    confidence: Decimal
    result_type: str


def _parse_decimal(value, *, field_name: str):
    if value in (None, ""):
        raise DeliveryServiceError("map_api_invalid_response", message=f"Missing {field_name}.")

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise DeliveryServiceError(
            "map_api_invalid_response",
            message=f"Invalid {field_name}.",
        ) from exc


def _request_json(base_url: str, params: dict[str, str]):
    url = f"{base_url}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": current_app.config["MAP_API_USER_AGENT"],
        },
    )

    try:
        with urlopen(request, timeout=current_app.config["MAP_API_TIMEOUT_SECONDS"]) as response:
            payload = json.load(response)
            current_app.logger.debug(
                "delivery_map_api_success url=%s params=%s",
                base_url,
                {
                    key: ("[redacted]" if key.lower() == "apikey" else value)
                    for key, value in params.items()
                },
            )
            return payload
    except HTTPError as exc:
        response_body = ""
        try:
            response_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            response_body = "<unavailable>"

        current_app.logger.warning(
            "delivery_map_api_http_error url=%s status=%s params=%s response=%s",
            base_url,
            exc.code,
            {
                key: ("[redacted]" if key.lower() == "apikey" else value)
                for key, value in params.items()
            },
            response_body[:1000],
        )
        raise DeliveryServiceError(
            "map_api_http_error",
            message=f"Map API returned HTTP {exc.code}.",
        ) from exc
    except URLError as exc:
        current_app.logger.warning(
            "delivery_map_api_connection_error url=%s reason=%s",
            base_url,
            str(exc.reason),
        )
        raise DeliveryServiceError(
            "map_api_connection_error",
            message="Could not reach the map API.",
        ) from exc
    except json.JSONDecodeError as exc:
        current_app.logger.warning(
            "delivery_map_api_invalid_json url=%s",
            base_url,
        )
        raise DeliveryServiceError(
            "map_api_invalid_response",
            message="Map API returned invalid JSON.",
        ) from exc


def _ensure_map_configured():
    api_key = (current_app.config.get("MAP_API_KEY") or "").strip()
    if not api_key:
        raise DeliveryServiceError(
            "map_api_not_configured",
            message="MAP_API_KEY is not configured.",
        )

    origin_address = (current_app.config.get("DELIVERY_ORIGIN_ADDRESS") or "").strip()
    if not origin_address:
        raise DeliveryServiceError(
            "delivery_origin_not_configured",
            message="DELIVERY_ORIGIN_ADDRESS is not configured.",
        )

    return api_key, origin_address


def _geocode_address(address: str, *, allow_street_level: bool = True):
    api_key, _ = _ensure_map_configured()
    address_text = (address or "").strip()
    if not address_text:
        raise DeliveryAddressValidationError("missing_address", message="Address is required.")

    params = {
        "text": address_text,
        "format": "json",
        "limit": "1",
        "apiKey": api_key,
    }

    country_code = (current_app.config.get("DELIVERY_GEOCODE_COUNTRYCODE") or "").strip().lower()
    if country_code:
        params["filter"] = f"countrycode:{country_code}"

    response = _request_json(current_app.config["MAP_API_GEOCODE_URL"], params)
    results = response.get("results") or []
    if not results:
        current_app.logger.info(
            "delivery_geocode_no_results address=%r country_code=%r",
            address_text,
            country_code,
        )
        raise DeliveryAddressValidationError(
            "address_not_found",
            message="We could not find that address.",
        )

    best = results[0]
    rank = best.get("rank") or {}
    confidence = _parse_decimal(rank.get("confidence", 0), field_name="geocoding confidence")
    result_type = (best.get("result_type") or "unknown").strip().lower()
    current_app.logger.info(
        "delivery_geocode_candidate input=%r formatted=%r result_type=%r confidence=%s match_type=%r country_code=%r allow_street_level=%s",
        address_text,
        (best.get("formatted") or "").strip(),
        result_type,
        str(confidence),
        rank.get("match_type"),
        country_code,
        allow_street_level,
    )

    allowed_result_types = {"building", "amenity"}
    if allow_street_level:
        allowed_result_types.add("street")

    if result_type not in allowed_result_types:
        current_app.logger.info(
            "delivery_geocode_rejected_result_type input=%r formatted=%r result_type=%r allowed=%s",
            address_text,
            (best.get("formatted") or "").strip(),
            result_type,
            sorted(allowed_result_types),
        )
        raise DeliveryAddressValidationError(
            "address_too_broad",
            message="Enter a more exact street address.",
        )

    min_confidence = current_app.config["DELIVERY_ADDRESS_MIN_CONFIDENCE"]
    if confidence < min_confidence:
        current_app.logger.info(
            "delivery_geocode_rejected_confidence input=%r formatted=%r result_type=%r confidence=%s min_confidence=%s",
            address_text,
            (best.get("formatted") or "").strip(),
            result_type,
            str(confidence),
            str(min_confidence),
        )
        raise DeliveryAddressValidationError(
            "address_low_confidence",
            message="We could not verify that address closely enough.",
        )

    formatted_address = (best.get("formatted") or address_text).strip()
    latitude = _parse_decimal(best.get("lat"), field_name="latitude")
    longitude = _parse_decimal(best.get("lon"), field_name="longitude")

    return GeocodedAddress(
        formatted_address=formatted_address,
        latitude=latitude,
        longitude=longitude,
        confidence=confidence,
        result_type=result_type,
    )


def _get_origin_address():
    _, origin_address = _ensure_map_configured()
    return _geocode_address(origin_address, allow_street_level=True)


def resolve_delivery_quote(address: str):
    api_key, _ = _ensure_map_configured()
    destination = _geocode_address(address, allow_street_level=True)
    origin = _get_origin_address()

    route_response = _request_json(
        current_app.config["MAP_API_ROUTE_URL"],
        {
            "waypoints": (
                f"{origin.latitude},{origin.longitude}"
                f"|{destination.latitude},{destination.longitude}"
            ),
            "format": "json",
            "mode": current_app.config["DELIVERY_ROUTE_MODE"],
            "apiKey": api_key,
        },
    )

    routes = route_response.get("results") or []
    if not routes:
        current_app.logger.info(
            "delivery_route_no_results origin=%r destination=%r",
            origin.formatted_address,
            destination.formatted_address,
        )
        raise DeliveryServiceError(
            "route_not_found",
            message="Could not calculate a delivery route.",
        )

    route = routes[0]
    distance_meters = _parse_decimal(route.get("distance"), field_name="route distance")
    distance_km = (distance_meters / Decimal("1000")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    current_app.logger.info(
        "delivery_route_calculated origin=%r destination=%r distance_km=%s destination_confidence=%s destination_result_type=%r",
        origin.formatted_address,
        destination.formatted_address,
        str(distance_km),
        str(destination.confidence),
        destination.result_type,
    )

    return {
        "formatted_address": destination.formatted_address,
        "distance_km": distance_km,
        "confidence": destination.confidence,
        "result_type": destination.result_type,
    }
