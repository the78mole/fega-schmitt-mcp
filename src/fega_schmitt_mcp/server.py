"""
fega-schmitt MCP Server

Exposes the FEGA & Schmitt Elektrogroßhandel SOAP price/availability service
via the Model Context Protocol (MCP). This server contains no protocol logic
of its own (no SOAP, no XML, no returncode mapping) - all of that lives in
the fega-schmitt-client library. See docs/architecture.md for the split
between the two repositories.
"""

import os
from decimal import Decimal, InvalidOperation
from typing import Any

from fega_schmitt_client import (
    FegaApiError,
    FegaAuthError,
    FegaSchmittClient,
    FegaTransportError,
    PriceAvailRequestItem,
    PriceAvailResultItem,
)
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "fega-schmitt",
    instructions=(
        "This server queries prices and availability for articles at FEGA & Schmitt "
        "Elektrogroßhandel (a German electrical wholesaler) via their SOAP price/availability "
        "service. Provide FEGA & Schmitt article (material) numbers together with a quantity "
        "and an optional unit. Up to 999 articles can be queried in a single call. Errors on "
        "individual articles (unknown article number, invalid unit, ...) are reported per "
        "article in the result, not as a failure of the whole request."
    ),
)

_customer_number: str | None = os.environ.get("FEGA_CUSTOMER_NUMBER")
_shop_password: str | None = os.environ.get("FEGA_SHOP_PASSWORD")
_endpoint: str | None = os.environ.get("FEGA_ENDPOINT")
_timeout: float = float(os.environ.get("FEGA_TIMEOUT", "30"))


def _build_client() -> FegaSchmittClient:
    """Construct a FegaSchmittClient from the configured environment variables."""
    if not _customer_number or not _shop_password:
        raise FegaAuthError("FEGA_CUSTOMER_NUMBER und FEGA_SHOP_PASSWORD müssen als Umgebungsvariablen gesetzt sein.")
    kwargs: dict[str, Any] = {
        "partner_purchaser": _customer_number,
        "legitimation_id": _shop_password,
        "timeout": _timeout,
    }
    if _endpoint:
        kwargs["endpoint"] = _endpoint
    return FegaSchmittClient(**kwargs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class PriceAvailItem(BaseModel):
    """A single article line to query price and availability for."""

    material_number: str = Field(description="FEGA & Schmitt-Artikelnummer (Materialnummer), z. B. '0815'.")
    quantity: str = Field(default="1", description="Menge als Zahl, z. B. '200' oder '1'. Default: '1'.")
    unit: str | None = Field(default=None, description="Mengeneinheit, z. B. 'MTR'. Optional.")


def _result_to_dict(result: PriceAvailResultItem) -> dict[str, Any]:
    """Serialize a PriceAvailResultItem dataclass to a plain dict for MCP responses."""
    return {
        "line_item_number": result.line_item_number,
        "material_number": result.material_number,
        "status": result.status,
        "return_code": result.return_code,
        "return_code_text": result.return_code_text,
        "availability_status": result.availability_status,
        "warehouse_number": result.warehouse_number,
        "warehouse_name": result.warehouse_name,
        "price_amount": str(result.price_amount) if result.price_amount is not None else None,
        "net_amount": str(result.net_amount) if result.net_amount is not None else None,
        "list_amount": str(result.list_amount) if result.list_amount is not None else None,
        "surcharges": [{"code": s.code, "text": s.text, "amount": str(s.amount)} for s in result.surcharges],
    }


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_price_availability(items: list[PriceAvailItem]) -> dict[str, Any]:
    """Preis und Verfügbarkeit für bis zu 999 FEGA & Schmitt-Artikel abfragen.

    Fehler auf einzelnen Positionen (unbekannte Artikelnummer, ungültige
    Mengeneinheit, Mengenüberlauf, ...) werden je Artikel im Ergebnis
    gemeldet (``status: "error"``), ohne die gesamte Anfrage abzubrechen.

    Args:
        items: Liste von Artikeln mit Artikelnummer, Menge und optionaler
            Mengeneinheit.

    Returns:
        Dict mit ``results`` (Liste der Ergebnisse je Artikel), oder
        ``{"error": ...}`` bei einem Auth-/Transportfehler oder einer
        ungültigen Anfrage.
    """
    if not items:
        return {"error": "items darf nicht leer sein."}

    try:
        request_items = [
            PriceAvailRequestItem(
                material_number=item.material_number,
                quantity=Decimal(item.quantity),
                unit=item.unit,
            )
            for item in items
        ]
    except InvalidOperation as exc:
        return {"error": f"Ungültige Menge: {exc}"}

    try:
        client = _build_client()
        results = client.get_price_availability(request_items)
    except FegaAuthError as exc:
        return {"error": f"Authentifizierungsfehler: {exc}"}
    except FegaTransportError as exc:
        return {"error": f"Transportfehler: {exc}"}
    except FegaApiError as exc:
        return {"error": str(exc)}
    except ValueError as exc:
        return {"error": str(exc)}

    return {"results": [_result_to_dict(r) for r in results]}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the fega-schmitt MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
