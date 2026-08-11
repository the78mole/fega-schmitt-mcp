"""
fega-schmitt MCP Server

Exposes the FEGA & Schmitt Elektrogroßhandel SOAP price/availability service
via the Model Context Protocol (MCP). This server contains no protocol logic
of its own (no SOAP, no XML, no returncode mapping) - all of that lives in
the fega-schmitt-client library. See docs/architecture.md for the split
between the two repositories.
"""

import os
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fega_schmitt_client import (
    FegaApiError,
    FegaAuthError,
    FegaSchmittClient,
    FegaTransportError,
    PriceAvailRequestItem,
    PriceAvailResultItem,
)
from fega_schmitt_client.web import (
    Article,
    ArticleSearchResult,
    Cart,
    CartSummary,
    DealCampaign,
    FegaLoginError,
    FegaScrapingError,
    Order,
    OrderSummary,
    WebClient,
)
from fega_schmitt_client.web.models import CableLength
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = MCPServer(
    "fega-schmitt",
    instructions=(
        "This server gives access to FEGA & Schmitt Elektrogroßhandel (a German electrical "
        "wholesaler) data via two backends. (1) get_price_availability queries the official "
        "SOAP price/availability service: provide article (material) numbers with quantity and "
        "an optional unit, up to 999 articles per call; per-article errors (unknown article "
        "number, invalid unit, ...) are reported per article in the result, not as a failure of "
        "the whole request. (2) The web_* tools scrape the customer-facing webshop frontend "
        "(shop.fega.de) - an undocumented interface, best-effort and more likely to break if "
        "FEGA & Schmitt changes their site. They cover search, article detail (EAN, "
        "manufacturer numbers, category, attributes, images, accessories/variants/alternatives/"
        "cross-sell), cable-length availability, category listing, favorites, deal campaigns, "
        "carts and orders. Both backends use the same FEGA & Schmitt customer number/shop "
        "password."
    ),
)

_customer_number: str | None = os.environ.get("FEGA_CUSTOMER_NUMBER")
_shop_password: str | None = os.environ.get("FEGA_SHOP_PASSWORD")
_endpoint: str | None = os.environ.get("FEGA_ENDPOINT")
_shop_base_url: str | None = os.environ.get("FEGA_SHOP_BASE_URL")
_timeout: float = float(os.environ.get("FEGA_TIMEOUT", "30"))


def _require_credentials() -> tuple[str, str]:
    if not _customer_number or not _shop_password:
        raise FegaAuthError("FEGA_CUSTOMER_NUMBER und FEGA_SHOP_PASSWORD müssen als Umgebungsvariablen gesetzt sein.")
    return _customer_number, _shop_password


def _build_client() -> FegaSchmittClient:
    """Construct a FegaSchmittClient from the configured environment variables."""
    customer_number, shop_password = _require_credentials()
    kwargs: dict[str, Any] = {
        "partner_purchaser": customer_number,
        "legitimation_id": shop_password,
        "timeout": _timeout,
    }
    if _endpoint:
        kwargs["endpoint"] = _endpoint
    return FegaSchmittClient(**kwargs)


def _build_web_client() -> WebClient:
    """Construct a WebClient from the configured environment variables."""
    customer_number, shop_password = _require_credentials()
    kwargs: dict[str, Any] = {
        "customer_number": customer_number,
        "shop_password": shop_password,
        "timeout": _timeout,
    }
    if _shop_base_url:
        kwargs["base_url"] = _shop_base_url
    return WebClient(**kwargs)


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


def _search_result_to_dict(result: ArticleSearchResult) -> dict[str, Any]:
    return {
        "material_number": result.material_number,
        "description": result.description,
        "thumbnail_url": result.thumbnail_url,
        "detail_url": result.detail_url,
    }


def _cable_length_to_dict(length: CableLength) -> dict[str, Any]:
    return {
        "location": length.location,
        "packaging": length.packaging,
        "is_cuttable": length.is_cuttable,
        "fixed_length_m": str(length.fixed_length_m) if length.fixed_length_m is not None else None,
        "count": length.count,
        "total_available_m": str(length.total_available_m),
    }


def _deal_campaign_to_dict(campaign: DealCampaign) -> dict[str, Any]:
    return {"campaign_id": campaign.campaign_id, "title": campaign.title}


def _cart_summary_to_dict(summary: CartSummary) -> dict[str, Any]:
    return {"cart_id": summary.cart_id, "name": summary.name}


def _cart_to_dict(cart: Cart) -> dict[str, Any]:
    return {
        "cart_id": cart.cart_id,
        "name": cart.name,
        "items": [
            {
                "position": item.position,
                "material_number": item.material_number,
                "description": item.description,
                "quantity": str(item.quantity),
                "position_id": item.position_id,
                "comment": item.comment,
            }
            for item in cart.items
        ],
    }


def _order_summary_to_dict(summary: OrderSummary) -> dict[str, Any]:
    return {
        "order_number": summary.order_number,
        "position": summary.position,
        "order_date": summary.order_date,
        "status": summary.status,
    }


def _order_to_dict(order: Order) -> dict[str, Any]:
    return {
        "order_number": order.order_number,
        "items": [
            {
                "position": item.position,
                "material_number": item.material_number,
                "description": item.description,
                "quantity_ordered": str(item.quantity_ordered) if item.quantity_ordered is not None else None,
                "quantity_delivered": str(item.quantity_delivered) if item.quantity_delivered is not None else None,
            }
            for item in order.items
        ],
    }


def _article_to_dict(article: Article) -> dict[str, Any]:
    return article.to_dict()


def _web_call(operation: Callable[[WebClient], dict[str, Any]]) -> dict[str, Any]:
    """Run `operation` against a fresh WebClient, translating exceptions into an error dict.

    Mirrors the SOAP tools' error-dict convention (no MCP-level exceptions), so both
    backends look the same to callers of this server.
    """
    try:
        client = _build_web_client()
    except FegaAuthError as exc:
        return {"error": f"Authentifizierungsfehler: {exc}"}

    try:
        with client:
            return operation(client)
    except FegaLoginError as exc:
        return {"error": f"Webshop-Login fehlgeschlagen: {exc}"}
    except FegaScrapingError as exc:
        return {"error": f"Antwort der Webshop-Seite konnte nicht verarbeitet werden: {exc}"}
    except FegaTransportError as exc:
        return {"error": f"Transportfehler: {exc}"}
    except FegaApiError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


_PARTNER_WAREHOUSE_DESCRIPTION = (
    "FEGA & Schmitt-Lagernummer (numerisch, max. 4 Ziffern, z. B. '22') - KEIN Ortsname. "
    "Nur relevant bei shipment_type='02' (Abholung), um ein anderes als das Standardlager "
    "anzufragen; bei Lieferung oder wenn das Standardlager genutzt werden soll, weglassen. "
    "VORBEHALT: In Live-Tests hat jeder getestete Wert von '1' bis '30' bei shipment_type='02' "
    "auf dasselbe (Heimat-)Lager des Kunden aufgelöst - nur das Weglassen des Parameters ergab "
    "ein anderes Lager. Es ist unklar, ob der Wert eine globale Lagernummer oder ein "
    "kundenbezogener Index ist; verlasst euch NICHT darauf, dass ein bestimmter Wert "
    "zuverlässig eine bestimmte Abholstelle auswählt, ohne das vorher zu verifizieren."
)


@mcp.tool()
def get_price_availability(
    items: list[PriceAvailItem],
    shipment_type: Annotated[str, Field(description="Versandart: '01'=Lieferung (Default), '02'=Abholung.")] = "01",
    partner_warehouse: Annotated[str | None, Field(description=_PARTNER_WAREHOUSE_DESCRIPTION)] = None,
) -> dict[str, Any]:
    """Preis und Verfügbarkeit für bis zu 999 FEGA & Schmitt-Artikel abfragen.

    Fehler auf einzelnen Positionen (unbekannte Artikelnummer, ungültige
    Mengeneinheit, Mengenüberlauf, ...) werden je Artikel im Ergebnis
    gemeldet (``status: "error"``), ohne die gesamte Anfrage abzubrechen.

    Args:
        items: Liste von Artikeln mit Artikelnummer, Menge und optionaler
            Mengeneinheit.
        shipment_type: Versandart für die gesamte Anfrage (nicht pro
            Artikel): '01'=Lieferung (Default) oder '02'=Abholung.
        partner_warehouse: Numerische FEGA & Schmitt-Lagernummer für die
            gesamte Anfrage (nicht pro Artikel), nur relevant bei
            shipment_type='02'. Siehe Feldbeschreibung für den Vorbehalt
            zur unklaren Semantik dieses Werts.

    Returns:
        Dict mit ``results`` (Liste der Ergebnisse je Artikel), oder
        ``{"error": ...}`` bei einem Auth-/Transportfehler oder einer
        ungültigen Anfrage (inkl. ungültigem partner_warehouse).
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
        results = client.get_price_availability(
            request_items, shipment_type=shipment_type, partner_warehouse=partner_warehouse
        )
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
# MCP Tools - Webshop (scraped frontend, best-effort - see fega-schmitt-client
# docs/extensions.md for what each of these is based on and how confident the
# parsing is)
# ---------------------------------------------------------------------------


@mcp.tool()
def web_search_articles(query: str) -> dict[str, Any]:
    """Artikel im Webshop suchen: Artikelnummer, EAN, Herstellerteilenummer oder Freitext -
    alles über dasselbe Suchfeld.

    Liefert nur Trefferkacheln (Artikelnummer, Beschreibung, Vorschaubild, Detail-URL),
    keine Preise/Verfügbarkeit - dafür get_price_availability nutzen.
    """
    return _web_call(lambda client: {"results": [_search_result_to_dict(r) for r in client.search(query)]})


@mcp.tool()
def web_get_article(material_number: str) -> dict[str, Any]:
    """Artikeldetails aus dem Webshop laden: EAN, Herstellernummer(n), Kategorie, eigene
    Artikelnummer, technische Attribute, Bilder, Schnittkosten (nur Kabelartikel) sowie
    Artikelnummern von Zubehör/Varianten/Alternativen/"Oft zusammengekauft mit".

    Zwei HTTP-Requests intern (erst Suche, dann Detailseite). ``documents`` ist aktuell immer
    leer (Endpunkt liefert bislang keine Daten). Bei Artikeln mit sehr vielen Varianten/
    Alternativen/Cross-Sell-Einträgen ist unklar, ob die Liste vollständig ist.
    """
    return _web_call(lambda client: _article_to_dict(client.get_article(material_number)))


@mcp.tool()
def web_set_article_number(material_number: str, own_article_number: str) -> dict[str, Any]:
    """Eigene (kundenspezifische) Artikelnummer für einen Artikel im Webshop setzen.

    Reine Beschriftung im Kundenkonto, keine Bestellung/Buchung. Gibt bei Erfolg
    ``{"status": "ok"}`` zurück; der Webshop bestätigt den neuen Wert nicht in der Antwort,
    daher ggf. mit web_get_article gegenprüfen.
    """

    def _op(client: WebClient) -> dict[str, Any]:
        client.set_article_number(material_number, own_article_number)
        return {"status": "ok"}

    return _web_call(_op)


@mcp.tool()
def web_get_cable_lengths(material_number: str) -> dict[str, Any]:
    """Verfügbare Kabellängen (Trommeln/Reststücke) eines Kabelartikels über alle
    Lagerstandorte abfragen.

    Leere Liste bei Artikeln, die nicht von der Trommel verkauft werden, oder wenn aktuell
    überall Fehlbestand herrscht.
    """
    return _web_call(
        lambda client: {"results": [_cable_length_to_dict(c) for c in client.get_cable_lengths(material_number)]}
    )


@mcp.tool()
def web_list_articles_by_category(category_id: str) -> dict[str, Any]:
    """Artikel einer FEGA & Schmitt-Warengruppe (UWG-Kategorie, z. B. 'UWG_14_87') auflisten.

    Vollständigkeit/Paginierung bei sehr großen Kategorien ist ungeklärt - dies liefert
    nur, was die erste Antwort enthält.
    """
    return _web_call(
        lambda client: {"results": [_search_result_to_dict(r) for r in client.list_articles_by_category(category_id)]}
    )


@mcp.tool()
def web_get_favorites() -> dict[str, Any]:
    """Die im Webshop-Kundenkonto gespeicherte Favoritenliste abrufen."""
    return _web_call(lambda client: {"results": [_search_result_to_dict(r) for r in client.get_favorite_list()]})


@mcp.tool()
def web_get_deal_campaigns() -> dict[str, Any]:
    """Aktive "Aktionsangebote"-Kampagnen auflisten (z. B. "Sonderabverkauf Licht").

    Liefert nur Kampagnen (ID + Titel), keine Artikel - dafür web_get_deal_articles nutzen.
    """
    return _web_call(lambda client: {"results": [_deal_campaign_to_dict(c) for c in client.get_deal_campaigns()]})


@mcp.tool()
def web_get_deal_articles(campaign_id: str) -> dict[str, Any]:
    """Artikel einer einzelnen Aktionsangebote-Kampagne abrufen (campaign_id aus
    web_get_deal_campaigns)."""
    return _web_call(
        lambda client: {"results": [_search_result_to_dict(r) for r in client.get_deal_articles(campaign_id)]}
    )


@mcp.tool()
def web_get_daily_deals() -> dict[str, Any]:
    """ "Tagesangebote" abrufen. Kann legitim leer sein, wenn FEGA & Schmitt aktuell keine
    Tagesangebote führt - das ist kein Fehler."""
    return _web_call(lambda client: {"results": [_search_result_to_dict(r) for r in client.get_daily_deals()]})


@mcp.tool()
def web_get_second_choice_articles(
    deal_id: Annotated[
        str | None,
        Field(description="Opaque Kampagnen-ID für '2. Wahl'/B-Ware. Weglassen für den bekannten Standardwert."),
    ] = None,
) -> dict[str, Any]:
    """ "2. Wahl"/B-Ware-Artikel abrufen (reduzierte Ware, z. B. Retouren/Restposten)."""

    def _op(client: WebClient) -> dict[str, Any]:
        results = client.get_second_choice_articles(deal_id) if deal_id else client.get_second_choice_articles()
        return {"results": [_search_result_to_dict(r) for r in results]}

    return _web_call(_op)


@mcp.tool()
def web_get_cart(
    cart_id: Annotated[
        str | None, Field(description="Warenkorb-ID. Weglassen für den aktuell aktiven Warenkorb.")
    ] = None,
) -> dict[str, Any]:
    """Inhalt eines Warenkorbs abrufen (Positionen mit Menge, keine Preise)."""

    def _op(client: WebClient) -> dict[str, Any]:
        cart = client.get_cart(cart_id) if cart_id else client.get_cart()
        return _cart_to_dict(cart)

    return _web_call(_op)


@mcp.tool()
def web_get_cart_list() -> dict[str, Any]:
    """Alle Warenkörbe des Kunden auflisten (ID + Name), inklusive des aktuell aktiven."""
    return _web_call(lambda client: {"results": [_cart_summary_to_dict(c) for c in client.get_cart_list()]})


@mcp.tool()
def web_get_order_list() -> dict[str, Any]:
    """Bestellübersicht abrufen (Bestellnummer, Position, Datum, Status).

    Status wird best-effort extrahiert und ist nur für einen beobachteten Status-Typ
    zuverlässig, sonst ``null``.
    """
    return _web_call(lambda client: {"results": [_order_summary_to_dict(o) for o in client.get_order_list()]})


@mcp.tool()
def web_get_order(order_number: str) -> dict[str, Any]:
    """Positionen einer einzelnen Bestellung abrufen (bestellte/gelieferte Menge je Artikel)."""
    return _web_call(lambda client: _order_to_dict(client.get_order(order_number)))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the fega-schmitt MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
