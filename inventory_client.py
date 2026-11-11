import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class InventoryWebhookError(RuntimeError):
    """Raised when an inventory request cannot be sent or decoded."""


def _validate_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise InventoryWebhookError("The inventory request must be a JSON object.")

    for field in ("external_request_id", "warehouse_code"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise InventoryWebhookError(f"{field} must be a non-empty string.")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise InventoryWebhookError("items must be a non-empty array.")

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise InventoryWebhookError(f"items[{index}] must be an object.")
        sku = item.get("sku")
        quantity = item.get("requested_quantity")
        if not isinstance(sku, str) or not sku.strip():
            raise InventoryWebhookError(f"items[{index}].sku must be a non-empty string.")
        if type(quantity) is not int or quantity <= 0:
            raise InventoryWebhookError(
                f"items[{index}].requested_quantity must be a positive integer."
            )


def send_inventory_request(
    payload: Any, webhook_url: str | None, timeout: float = 15
) -> dict[str, Any]:
    _validate_payload(payload)
    if not webhook_url or not webhook_url.strip():
        raise InventoryWebhookError(
            "N8N_INVENTORY_WEBHOOK_URL is not configured."
        )
    webhook_url = webhook_url.strip()
    try:
        parsed_url = urlsplit(webhook_url)
    except ValueError as exc:
        raise InventoryWebhookError(
            "N8N_INVENTORY_WEBHOOK_URL must be an absolute HTTP or HTTPS URL."
        ) from exc
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise InventoryWebhookError(
            "N8N_INVENTORY_WEBHOOK_URL must be an absolute HTTP or HTTPS URL."
        )

    request = Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        message = detail or str(exc.reason)
        raise InventoryWebhookError(
            f"n8n returned HTTP {exc.code}: {message}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise InventoryWebhookError(f"Could not reach the n8n webhook: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise InventoryWebhookError(
            "The n8n webhook response is not valid UTF-8."
        ) from exc

    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise InventoryWebhookError(
            "The n8n webhook returned invalid JSON."
        ) from exc
    if not isinstance(result, dict):
        raise InventoryWebhookError(
            "The n8n webhook response must be a JSON object."
        )
    return result
