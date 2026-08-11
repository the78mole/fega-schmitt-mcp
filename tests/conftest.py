"""Shared pytest fixtures for fega-schmitt-mcp tests."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fega_schmitt_client import PriceAvailResultItem, Surcharge
from fega_schmitt_client.web import (
    Article,
    ArticleImage,
    ArticleSearchResult,
    Cart,
    CartItem,
    CartSummary,
    DealCampaign,
    Order,
    OrderItem,
    OrderSummary,
)
from fega_schmitt_client.web.models import CableLength


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_result_ok():
    """A single successful PriceAvailResultItem."""
    return PriceAvailResultItem(
        line_item_number=1,
        material_number="0815",
        status="ok",
        return_code="I720",
        return_code_text="OK",
        availability_status="V",
        warehouse_number="10",
        warehouse_name="Zentrallager",
        price_amount=Decimal("12.50"),
        net_amount=Decimal("13.20"),
        list_amount=Decimal("15.00"),
        surcharges=[Surcharge(code="CU", text="Kupferzuschlag", amount=Decimal("0.70"))],
    )


@pytest.fixture
def mock_result_error():
    """A single failed PriceAvailResultItem (unknown article)."""
    return PriceAvailResultItem(
        line_item_number=2,
        material_number="unknown",
        status="error",
        return_code="E999",
        return_code_text="Bitte pruefen Sie Ihre Anmeldedaten",
        availability_status=None,
        warehouse_number=None,
        warehouse_name=None,
        price_amount=None,
        net_amount=None,
        list_amount=None,
        surcharges=[],
    )


# ---------------------------------------------------------------------------
# Webshop fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_search_result():
    return ArticleSearchResult(
        material_number="0815",
        description="Testartikel",
        thumbnail_url="https://shop.fega.de/img/0815.jpg",
        detail_url="https://shop.fega.de/abtest/scripts/shop.php?cmd=Artikel/0815-testartikel",
    )


@pytest.fixture
def mock_article():
    return Article(
        material_number="0815",
        fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
        ean="4012345678901",
        manufacturer_item_number="ABC-123",
        manufacturer_item_number_alt=None,
        supplier_name="ACME",
        supplier_number="4711",
        category_id="UWG_14_87",
        category_name="Leitungsschutzschalter",
        own_article_number="MEIN-0815",
        cutting_fee=Decimal("5.00"),
        attributes={"Farbe": "grau"},
        images=[ArticleImage(material_number="0815", url="https://shop.fega.de/img/0815-1.jpg", is_primary=True)],
        accessories=["1000"],
        variants=["1001", "1002"],
        alternatives=["1003"],
        cross_sell=["1004"],
        documents=[],
    )


@pytest.fixture
def mock_cable_length():
    return CableLength(
        location="Zentrallager",
        packaging="Trommel",
        is_cuttable=True,
        fixed_length_m=Decimal("500"),
        count=2,
        total_available_m=Decimal("1000"),
    )


@pytest.fixture
def mock_deal_campaign():
    return DealCampaign(campaign_id="42", title="Sonderabverkauf Licht")


@pytest.fixture
def mock_cart_summary():
    return CartSummary(cart_id="1", name="Hauptwarenkorb")


@pytest.fixture
def mock_cart():
    return Cart(
        cart_id="1",
        name="Hauptwarenkorb",
        items=[
            CartItem(
                position=1,
                material_number="0815",
                description="Testartikel",
                quantity=Decimal("10"),
                position_id="pos-1",
                comment="",
            )
        ],
    )


@pytest.fixture
def mock_order_summary():
    return OrderSummary(order_number="AB123", position="1", order_date="2026-08-01", status="offen")


@pytest.fixture
def mock_order():
    return Order(
        order_number="AB123",
        items=[
            OrderItem(
                position=1,
                material_number="0815",
                description="Testartikel",
                quantity_ordered=Decimal("10"),
                quantity_delivered=Decimal("8"),
            )
        ],
    )
