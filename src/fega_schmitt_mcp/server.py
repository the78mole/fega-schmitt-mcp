"""
fega-schmitt MCP Server

Exposes FEGA & Schmitt Elektrogroßhandel data via the Model Context Protocol
(MCP). This server contains no protocol logic of its own (no SOAP, no XML, no
DATANORM parsing, no scraping) - all of that lives in the fega-schmitt-client
library. See docs/architecture.md for the split between the two repositories.

Sources, cheapest first (the client's ``ArticleLookup`` order):

1. DATANORM database (``fega datanorm import``): local, no request at all.
2. SOAP price/availability service: today's price, surcharges and stock.
3. Webshop: only after the user agreed to it (see ``_confirm_web``). Article
   pages already in the client's web cache are used without asking, since
   reading them sends no request to the shop.
"""

import os
from collections.abc import Callable
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any

import anyio.to_thread
from fega_schmitt_client import (
    FegaApiError,
    FegaAuthError,
    FegaSchmittClient,
    FegaTransportError,
    PriceAvailRequestItem,
    PriceAvailResultItem,
)
from fega_schmitt_client.datanorm.store import DEFAULT_SEARCH_LIMIT, DatanormArticle, DatanormStore
from fega_schmitt_client.lookup import ArticleInfo, ArticleLookup, ArticleNotFoundError, SearchHit
from fega_schmitt_client.web import (
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
from fega_schmitt_client.web.cache import WebArticleCache
from fega_schmitt_client.web.models import CableLength
from mcp.server.elicitation import render_elicitation_schema
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult
from mcp_types.version import is_version_at_least
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = MCPServer(
    "fega-schmitt",
    instructions=(
        "This server gives access to FEGA & Schmitt Elektrogroßhandel (a German electrical "
        "wholesaler) data. Use the sources in this order: (1) search_articles and get_article "
        "read the local DATANORM database (article master data, EAN, manufacturer numbers, list "
        "and net prices of the last delivery) and get_article adds today's price and availability "
        "from the SOAP service. (2) get_price_availability queries the SOAP service for up to 999 "
        "articles per call; per-article errors are reported per article in the result. (3) The "
        "webshop (shop.fega.de, scraped, best-effort) is only used with the user's consent: "
        "get_article(include_web=true), search_articles without DATANORM hits, and all web_* "
        "tools (cable lengths, categories, favorites, deals, carts, orders, own article number) "
        "ask the user before sending a request to the shop. If the client cannot show that "
        "question, the tool answers with web_confirmation_required=true; then ask the user "
        "yourself and repeat the call with allow_web=true only if they agreed. Never set "
        "allow_web=true without the user's explicit consent. Prefer DATANORM and SOAP; use the "
        "webshop only for what they cannot provide (images, technical attributes, accessories/"
        "variants, shop category, own article number, cutting fee, carts, orders)."
    ),
)

_customer_number: str | None = os.environ.get("FEGA_CUSTOMER_NUMBER")
_shop_password: str | None = os.environ.get("FEGA_SHOP_PASSWORD")
_endpoint: str | None = os.environ.get("FEGA_ENDPOINT")
_shop_base_url: str | None = os.environ.get("FEGA_SHOP_BASE_URL")
_datanorm_db: str | None = os.environ.get("FEGA_DATANORM_DB")
_timeout: float = float(os.environ.get("FEGA_TIMEOUT", "30"))


def _require_credentials() -> tuple[str, str]:
    if not _customer_number or not _shop_password:
        raise FegaAuthError("FEGA_CUSTOMER_NUMBER und FEGA_SHOP_PASSWORD müssen als Umgebungsvariablen gesetzt sein.")
    return _customer_number, _shop_password


def _has_credentials() -> bool:
    return bool(_customer_number and _shop_password)


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


def _build_lookup() -> ArticleLookup:
    """DATANORM, SOAP (if configured) and the web cache - but no webshop client.

    Without a ``web_factory`` the lookup never sends a request to the shop; it
    only returns shop pages that are already cached. Fetching from the shop is
    done separately, after ``_confirm_web``.
    """
    return ArticleLookup(
        datanorm=DatanormStore.open(Path(_datanorm_db) if _datanorm_db else None),
        soap=_build_client() if _has_credentials() else None,
        web_cache=WebArticleCache(),
    )


# ---------------------------------------------------------------------------
# Webshop consent
# ---------------------------------------------------------------------------


class WebConsent(BaseModel):
    """Form shown to the user before a webshop request."""

    allow: bool = Field(description="Webshop-Zugriff für diese Anfrage erlauben")


_ALLOW_WEB_DESCRIPTION = (
    "Nur auf true setzen, NACHDEM der User den Webshop-Zugriff ausdrücklich bestätigt hat. Wird nur "
    "ausgewertet, wenn der MCP-Client keine Rückfrage (Elicitation) anzeigen kann - sonst fragt der "
    "Server den User selbst. Default: false."
)

AllowWeb = Annotated[bool, Field(description=_ALLOW_WEB_DESCRIPTION)]


# Protocol revisions from 2026-07-28 on have no server-to-client requests during a
# tool call; the question travels in an InputRequiredResult and the client retries
# the call with the answer in input_responses under this key.
_INPUT_REQUIRED_VERSION = "2026-07-28"
_WEB_CONSENT_KEY = "web_consent"


async def _confirm_web(ctx: Context, purpose: str, allow_web: bool) -> str | InputRequiredResult | None:
    """Ask the user before a webshop request.

    Returns None if allowed, the reason if not, or an InputRequiredResult that the
    tool must return as is so the client asks the user and retries the call.

    The server asks the user itself via MCP elicitation whenever the client
    supports it; ``allow_web`` cannot skip that question. Only clients that
    cannot elicit fall back to ``allow_web``, which the model may set after
    asking the user in the chat.
    """
    message = f"Darf der FEGA & Schmitt-Webshop (shop.fega.de) abgefragt werden?\nZweck: {purpose}"
    capabilities = ctx.client_capabilities
    can_elicit = capabilities is not None and capabilities.elicitation is not None
    if ctx.protocol_version and is_version_at_least(ctx.protocol_version, _INPUT_REQUIRED_VERSION):
        answer = (ctx.input_responses or {}).get(_WEB_CONSENT_KEY)
        if isinstance(answer, ElicitResult):
            return None if _consented(answer.action, answer.content) else "Der User hat den Webshop-Zugriff abgelehnt."
        if can_elicit:
            params = ElicitRequestFormParams(message=message, requested_schema=render_elicitation_schema(WebConsent))
            return InputRequiredResult(input_requests={_WEB_CONSENT_KEY: ElicitRequest(params=params)})
    elif can_elicit:
        try:
            result = await ctx.elicit(message, WebConsent)
        except Exception:  # noqa: BLE001 - no back channel or a broken answer: fall back to allow_web
            pass
        else:
            data = result.data.model_dump() if result.action == "accept" else None
            return None if _consented(result.action, data) else "Der User hat den Webshop-Zugriff abgelehnt."
    if allow_web:
        return None
    return (
        "Webshop-Zugriff nicht freigegeben. Den User fragen, ob der Webshop abgefragt werden darf "
        f"({purpose}), und nur bei Zustimmung mit allow_web=true erneut aufrufen."
    )


def _consented(action: str, content: dict[str, Any] | None) -> bool:
    return action == "accept" and bool(content) and content.get("allow") is True


def _web_denied(reason: str) -> dict[str, Any]:
    return {"error": reason, "web_confirmation_required": True}


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


def _datanorm_article_to_dict(article: DatanormArticle) -> dict[str, Any]:
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in asdict(article).items()}


def _article_info_to_dict(info: ArticleInfo) -> dict[str, Any]:
    return {
        "material_number": info.material_number,
        "sources": info.sources,
        "description": info.description,
        "ean": info.ean,
        "manufacturer_item_number": info.manufacturer_item_number,
        "datanorm": _datanorm_article_to_dict(info.datanorm) if info.datanorm else None,
        "price_availability": _result_to_dict(info.price_availability) if info.price_availability else None,
        "web": info.web.to_dict() if info.web else None,
        "web_from_cache": info.web_from_cache,
        "warnings": info.warnings,
    }


def _search_hit_to_dict(hit: SearchHit) -> dict[str, Any]:
    return {
        "material_number": hit.material_number,
        "description": hit.description,
        "source": hit.source,
        "matched": hit.matched,
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


def _run_web(operation: Callable[[WebClient], dict[str, Any]]) -> dict[str, Any]:
    """Run `operation` against a fresh WebClient, translating exceptions into an error dict.

    Mirrors the SOAP tools' error-dict convention (no MCP-level exceptions), so all
    backends look the same to callers of this server. Blocking - call it in a worker
    thread from async tools.
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


async def _web_call(
    ctx: Context, purpose: str, allow_web: bool, operation: Callable[[WebClient], dict[str, Any]]
) -> dict[str, Any] | InputRequiredResult:
    """`_run_web`, but only after the user agreed to the webshop request."""
    if not _has_credentials():
        return await anyio.to_thread.run_sync(_run_web, operation)  # fails with the auth error, no question needed
    denied = await _confirm_web(ctx, purpose, allow_web)
    if isinstance(denied, InputRequiredResult):
        return denied
    if denied:
        return _web_denied(denied)
    return await anyio.to_thread.run_sync(_run_web, operation)


# ---------------------------------------------------------------------------
# MCP Tools - article lookup (DATANORM -> SOAP -> webshop with consent)
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_articles(
    query: Annotated[
        str, Field(description="Artikelnummer, EAN, Herstellernummer/Typ oder Suchwörter aus dem Kurztext.")
    ],
    ctx: Context,
    limit: Annotated[int, Field(ge=1, le=500, description="Maximale Trefferzahl.")] = DEFAULT_SEARCH_LIMIT,
    allow_web: AllowWeb = False,
) -> dict[str, Any] | InputRequiredResult:
    """Artikel suchen - zuerst in der lokalen DATANORM-Datenbank, im Webshop nur ohne Treffer
    und nur nach Rückfrage beim User.

    DATANORM findet Artikelnummer, EAN und Herstellernummern exakt (diese Treffer zuerst) sowie
    Artikel, deren Kurztexte alle Suchwörter enthalten. Jeder Treffer nennt seine Quelle
    (``source``: 'datanorm' oder 'web') und bei DATANORM das passende Feld (``matched``).
    Keine Preise/Verfügbarkeit - dafür get_article oder get_price_availability nutzen.
    """

    def _search_datanorm() -> tuple[str | None, list[SearchHit]]:
        with _build_lookup() as lookup:
            return lookup.datanorm_delivery_date, lookup.search(query, limit)

    delivery_date, hits = await anyio.to_thread.run_sync(_search_datanorm)
    result: dict[str, Any] = {"datanorm_delivery_date": delivery_date}
    if delivery_date is None:
        result["warnings"] = ["Keine DATANORM-Datenbank, erst `fega datanorm import` ausführen."]
    if hits or not _has_credentials():
        return {**result, "results": [_search_hit_to_dict(h) for h in hits]}

    denied = await _confirm_web(ctx, f"Suche nach {query!r} (kein Treffer in DATANORM)", allow_web)
    if isinstance(denied, InputRequiredResult):
        return denied
    if denied:
        return {**result, "results": [], **_web_denied(denied)}

    def _search_web(client: WebClient) -> dict[str, Any]:
        hits = [SearchHit(r.material_number, r.description, "web") for r in client.search(query)[:limit]]
        return {"results": [_search_hit_to_dict(h) for h in hits]}

    return {**result, **await anyio.to_thread.run_sync(_run_web, _search_web)}


@mcp.tool()
async def get_article(
    material_number: str,
    ctx: Context,
    include_web: Annotated[
        bool,
        Field(
            description=(
                "Zusätzlich Webshop-Daten (Bilder, technische Attribute, Zubehör/Varianten/Alternativen, "
                "Shop-Kategorie, eigene Artikelnummer, Schnittkosten) laden. Bereits gecachte Shop-Daten "
                "(max. 30 Tage alt) kommen immer mit; ein neuer Shop-Abruf erfordert die Zustimmung des Users."
            )
        ),
    ] = False,
    refresh_web: Annotated[
        bool, Field(description="Shop-Cache ignorieren und neu abrufen (nur mit include_web, mit Rückfrage).")
    ] = False,
    allow_web: AllowWeb = False,
) -> dict[str, Any] | InputRequiredResult:
    """Alles zu einem Artikel: DATANORM-Stammdaten und Preise der letzten Lieferung, heutiger
    Preis/Verfügbarkeit per SOAP sowie - aus dem Cache oder nach Rückfrage - Webshop-Daten.

    Jede Quelle steht in ihrem eigenen Feld (``datanorm``, ``price_availability``, ``web``);
    ``description``, ``ean`` und ``manufacturer_item_number`` sind zusammengeführt (DATANORM
    zuerst). DATANORM-Preise gelten je ``price_unit``. Fehlschläge einzelner Quellen stehen in
    ``warnings``, solange eine andere Quelle den Artikel kennt.
    """

    def _local() -> tuple[ArticleInfo | None, str | None]:
        # No web_factory: the shop is read from the cache only, never requested.
        with _build_lookup() as lookup:
            try:
                return lookup.get_article(material_number, refresh=refresh_web), None
            except ArticleNotFoundError as exc:
                return None, str(exc)

    info, not_found = await anyio.to_thread.run_sync(_local)
    need_web = include_web and (info is None or info.web is None or refresh_web)
    if need_web and not _has_credentials():
        need_web = False
        if info is not None:
            info.warnings.append("Webshop nicht abgefragt: kein Zugang konfiguriert.")
    if not need_web:
        if info is None:
            return {"error": not_found, "hint": "Mit include_web=true kann zusätzlich der Webshop gefragt werden."}
        return _article_info_to_dict(info)

    denied = await _confirm_web(ctx, f"Artikeldetails für {material_number}", allow_web)
    if isinstance(denied, InputRequiredResult):
        return denied
    if denied:
        if info is None:
            return {"error": not_found, **_web_denied(denied)}
        return {**_article_info_to_dict(info), **_web_denied(denied)}

    def _fetch(client: WebClient) -> dict[str, Any]:
        article = client.get_article(material_number)
        with WebArticleCache() as cache:
            cache.put(article)
        return {"article": article}

    fetched = await anyio.to_thread.run_sync(_run_web, _fetch)
    if info is None:
        if "error" in fetched:
            return {"error": f"{not_found} Webshop: {fetched['error']}"}
        info = ArticleInfo(material_number)
    if "error" in fetched:
        info.warnings.append(f"Webshop fehlgeschlagen: {fetched['error']}")
    else:
        info.web, info.web_from_cache = fetched["article"], False
    return _article_info_to_dict(info)


# ---------------------------------------------------------------------------
# MCP Tools - SOAP price/availability
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
# parsing is). Every call asks the user first, see _confirm_web.
# ---------------------------------------------------------------------------


@mcp.tool()
async def web_set_article_number(
    material_number: str, own_article_number: str, ctx: Context, allow_web: AllowWeb = False
) -> dict[str, Any] | InputRequiredResult:
    """Eigene (kundenspezifische) Artikelnummer für einen Artikel im Webshop setzen
    (nur nach Rückfrage beim User).

    Reine Beschriftung im Kundenkonto, keine Bestellung/Buchung. Gibt bei Erfolg
    ``{"status": "ok"}`` zurück; der Webshop bestätigt den neuen Wert nicht in der Antwort,
    daher ggf. mit get_article(include_web=true, refresh_web=true) gegenprüfen.
    """

    def _op(client: WebClient) -> dict[str, Any]:
        client.set_article_number(material_number, own_article_number)
        # The cached shop page still shows the old number.
        with WebArticleCache() as cache:
            cache.delete(material_number)
        return {"status": "ok"}

    return await _web_call(
        ctx, f"eigene Artikelnummer {own_article_number!r} für {material_number} setzen", allow_web, _op
    )


@mcp.tool()
async def web_get_cable_lengths(
    material_number: str, ctx: Context, allow_web: AllowWeb = False
) -> dict[str, Any] | InputRequiredResult:
    """Verfügbare Kabellängen (Trommeln/Reststücke) eines Kabelartikels über alle
    Lagerstandorte aus dem Webshop abfragen (nur nach Rückfrage beim User).

    Leere Liste bei Artikeln, die nicht von der Trommel verkauft werden, oder wenn aktuell
    überall Fehlbestand herrscht.
    """
    return await _web_call(
        ctx,
        f"Kabellängen für {material_number}",
        allow_web,
        lambda client: {"results": [_cable_length_to_dict(c) for c in client.get_cable_lengths(material_number)]},
    )


@mcp.tool()
async def web_list_articles_by_category(
    category_id: str, ctx: Context, allow_web: AllowWeb = False
) -> dict[str, Any] | InputRequiredResult:
    """Artikel einer FEGA & Schmitt-Warengruppe (UWG-Kategorie, z. B. 'UWG_14_87') aus dem
    Webshop auflisten (nur nach Rückfrage beim User).

    Vollständigkeit/Paginierung bei sehr großen Kategorien ist ungeklärt - dies liefert
    nur, was die erste Antwort enthält.
    """
    return await _web_call(
        ctx,
        f"Artikel der Kategorie {category_id}",
        allow_web,
        lambda client: {"results": [_search_result_to_dict(r) for r in client.list_articles_by_category(category_id)]},
    )


@mcp.tool()
async def web_get_favorites(ctx: Context, allow_web: AllowWeb = False) -> dict[str, Any] | InputRequiredResult:
    """Die im Webshop-Kundenkonto gespeicherte Favoritenliste abrufen (nur nach Rückfrage beim User)."""
    return await _web_call(
        ctx,
        "Favoritenliste",
        allow_web,
        lambda client: {"results": [_search_result_to_dict(r) for r in client.get_favorite_list()]},
    )


@mcp.tool()
async def web_get_deal_campaigns(ctx: Context, allow_web: AllowWeb = False) -> dict[str, Any] | InputRequiredResult:
    """Aktive "Aktionsangebote"-Kampagnen im Webshop auflisten, z. B. "Sonderabverkauf Licht"
    (nur nach Rückfrage beim User).

    Liefert nur Kampagnen (ID + Titel), keine Artikel - dafür web_get_deal_articles nutzen.
    """
    return await _web_call(
        ctx,
        "Aktionsangebote",
        allow_web,
        lambda client: {"results": [_deal_campaign_to_dict(c) for c in client.get_deal_campaigns()]},
    )


@mcp.tool()
async def web_get_deal_articles(
    campaign_id: str, ctx: Context, allow_web: AllowWeb = False
) -> dict[str, Any] | InputRequiredResult:
    """Artikel einer einzelnen Aktionsangebote-Kampagne abrufen (campaign_id aus
    web_get_deal_campaigns; nur nach Rückfrage beim User)."""
    return await _web_call(
        ctx,
        f"Artikel der Aktion {campaign_id}",
        allow_web,
        lambda client: {"results": [_search_result_to_dict(r) for r in client.get_deal_articles(campaign_id)]},
    )


@mcp.tool()
async def web_get_daily_deals(ctx: Context, allow_web: AllowWeb = False) -> dict[str, Any] | InputRequiredResult:
    """ "Tagesangebote" aus dem Webshop abrufen (nur nach Rückfrage beim User). Kann legitim
    leer sein, wenn FEGA & Schmitt aktuell keine Tagesangebote führt - das ist kein Fehler."""
    return await _web_call(
        ctx,
        "Tagesangebote",
        allow_web,
        lambda client: {"results": [_search_result_to_dict(r) for r in client.get_daily_deals()]},
    )


@mcp.tool()
async def web_get_second_choice_articles(
    ctx: Context,
    deal_id: Annotated[
        str | None,
        Field(description="Opaque Kampagnen-ID für '2. Wahl'/B-Ware. Weglassen für den bekannten Standardwert."),
    ] = None,
    allow_web: AllowWeb = False,
) -> dict[str, Any] | InputRequiredResult:
    """ "2. Wahl"/B-Ware-Artikel aus dem Webshop abrufen, z. B. Retouren/Restposten
    (nur nach Rückfrage beim User)."""

    def _op(client: WebClient) -> dict[str, Any]:
        results = client.get_second_choice_articles(deal_id) if deal_id else client.get_second_choice_articles()
        return {"results": [_search_result_to_dict(r) for r in results]}

    return await _web_call(ctx, "2.-Wahl-Artikel", allow_web, _op)


@mcp.tool()
async def web_get_cart(
    ctx: Context,
    cart_id: Annotated[
        str | None, Field(description="Warenkorb-ID. Weglassen für den aktuell aktiven Warenkorb.")
    ] = None,
    allow_web: AllowWeb = False,
) -> dict[str, Any] | InputRequiredResult:
    """Inhalt eines Warenkorbs im Webshop abrufen - Positionen mit Menge, keine Preise
    (nur nach Rückfrage beim User)."""

    def _op(client: WebClient) -> dict[str, Any]:
        cart = client.get_cart(cart_id) if cart_id else client.get_cart()
        return _cart_to_dict(cart)

    return await _web_call(ctx, f"Warenkorb {cart_id}" if cart_id else "aktiver Warenkorb", allow_web, _op)


@mcp.tool()
async def web_get_cart_list(ctx: Context, allow_web: AllowWeb = False) -> dict[str, Any] | InputRequiredResult:
    """Alle Warenkörbe des Kunden im Webshop auflisten, ID + Name, inklusive des aktuell
    aktiven (nur nach Rückfrage beim User)."""
    return await _web_call(
        ctx,
        "Liste der Warenkörbe",
        allow_web,
        lambda client: {"results": [_cart_summary_to_dict(c) for c in client.get_cart_list()]},
    )


@mcp.tool()
async def web_get_order_list(ctx: Context, allow_web: AllowWeb = False) -> dict[str, Any] | InputRequiredResult:
    """Bestellübersicht aus dem Webshop abrufen - Bestellnummer, Position, Datum, Status
    (nur nach Rückfrage beim User).

    Status wird best-effort extrahiert und ist nur für einen beobachteten Status-Typ
    zuverlässig, sonst ``null``.
    """
    return await _web_call(
        ctx,
        "Bestellübersicht",
        allow_web,
        lambda client: {"results": [_order_summary_to_dict(o) for o in client.get_order_list()]},
    )


@mcp.tool()
async def web_get_order(
    order_number: str, ctx: Context, allow_web: AllowWeb = False
) -> dict[str, Any] | InputRequiredResult:
    """Positionen einer einzelnen Bestellung aus dem Webshop abrufen - bestellte/gelieferte
    Menge je Artikel (nur nach Rückfrage beim User)."""
    return await _web_call(
        ctx, f"Bestellung {order_number}", allow_web, lambda client: _order_to_dict(client.get_order(order_number))
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the fega-schmitt MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
