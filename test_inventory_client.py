import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from inventory_client import InventoryWebhookError, send_inventory_request


SAMPLE_PAYLOAD = {
    "external_request_id": "website-order-10001",
    "warehouse_code": "MAIN",
    "requested_by": "website",
    "notes": "Check stock before confirming customer order",
    "items": [
        {"sku": "LAP-DELL-001", "requested_quantity": 2},
        {"sku": "LAP-HP-001", "requested_quantity": 6},
    ],
}


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class InventoryClientTests(unittest.TestCase):
    @patch("inventory_client.urlopen")
    def test_posts_payload_and_returns_inventory_result(self, urlopen):
        result = {"status": "shortage", "stock_reserved": False, "items": []}
        urlopen.return_value = FakeResponse(json.dumps(result).encode("utf-8"))

        actual = send_inventory_request(SAMPLE_PAYLOAD, "https://n8n.example/webhook/test")

        self.assertEqual(actual, result)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            SAMPLE_PAYLOAD,
        )

    def test_requires_webhook_url(self):
        with self.assertRaisesRegex(InventoryWebhookError, "not configured"):
            send_inventory_request(SAMPLE_PAYLOAD, None)

    def test_rejects_invalid_webhook_url(self):
        with self.assertRaisesRegex(InventoryWebhookError, "absolute HTTP or HTTPS URL"):
            send_inventory_request(SAMPLE_PAYLOAD, "not-a-url")

    def test_rejects_non_positive_or_non_integer_quantities(self):
        payload = {**SAMPLE_PAYLOAD, "items": [{"sku": "LAP-DELL-001", "requested_quantity": True}]}
        with self.assertRaisesRegex(InventoryWebhookError, "positive integer"):
            send_inventory_request(payload, "https://n8n.example/webhook/test")

    @patch("inventory_client.urlopen")
    def test_reports_http_error_body(self, urlopen):
        urlopen.side_effect = HTTPError(
            "https://n8n.example/webhook/test",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"message":"invalid webhook auth"}'),
        )

        with self.assertRaisesRegex(InventoryWebhookError, "HTTP 401.*invalid webhook auth"):
            send_inventory_request(SAMPLE_PAYLOAD, "https://n8n.example/webhook/test")

    @patch("inventory_client.urlopen")
    def test_reports_connection_error(self, urlopen):
        urlopen.side_effect = URLError("connection refused")

        with self.assertRaisesRegex(InventoryWebhookError, "Could not reach"):
            send_inventory_request(SAMPLE_PAYLOAD, "https://n8n.example/webhook/test")

    @patch("inventory_client.urlopen")
    def test_reports_invalid_json_response(self, urlopen):
        urlopen.return_value = FakeResponse(b"not-json")

        with self.assertRaisesRegex(InventoryWebhookError, "invalid JSON"):
            send_inventory_request(SAMPLE_PAYLOAD, "https://n8n.example/webhook/test")


if __name__ == "__main__":
    unittest.main()
