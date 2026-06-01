from __future__ import annotations

import json
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from src.retail.advisor import RetailStockAdvisor
from src.retail.repositories import JsonRetailRepository

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 16 * 1024


class RetailAdvisorHandler(BaseHTTPRequestHandler):
    advisor = RetailStockAdvisor()
    repository = JsonRetailRepository()

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if self.path == "/api/products":
            payload = [
                {
                    "product_id": product.product_id,
                    "name": product.name,
                    "category": product.category,
                }
                for product in self.repository.list_products()
            ]
            self._send_json({"products": payload})
            return
        if self.path == "/api/periods":
            payload = [
                {
                    "period_id": trend.period_id,
                    "label": trend.label,
                    "description": trend.description,
                }
                for trend in self.repository.list_seasonal_trends()
            ]
            self._send_json({"periods": payload})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        if self.path != "/api/ask":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            payload = self._read_json_body()
            question = str(payload.get("question", "")).strip()
            category = str(payload.get("category", "")).strip() or None
            period_id = str(payload.get("period_id", "")).strip() or None
            if not question:
                self._send_json({"error": "question is required"}, HTTPStatus.BAD_REQUEST)
                return

            result = self.advisor.answer(question=question, category=category, period_id=period_id)
            self._send_json(
                {
                    "answer": result.answer,
                    "restock_items": result.restock_items,
                    "promotion_items": result.promotion_items,
                    "seasonal_items": result.seasonal_items,
                    "metrics": result.metrics,
                    "trace": [asdict(item) for item in result.trace],
                }
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_file(self, path: Path, content_type: str) -> None:
        if path.parent != STATIC_DIR:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY_BYTES:
            raise ValueError("Request body too large")
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), RetailAdvisorHandler)
    print(f"Retail Stock Advisor is running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
