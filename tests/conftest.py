"""Shared pytest fixtures for fega-schmitt-mcp tests."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fega_schmitt_client import PriceAvailResultItem, Surcharge
from fega_schmitt_client.datanorm.store import DatanormArticle, DatanormSearchHit
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


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Credentials set, and all client caches (DATANORM, web cache, shop session) in tmp_path.

    Without this, tests would read the real ``~/.cache/fega-schmitt-client``.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("fega_schmitt_mcp.server._customer_number", "4711")
    monkeypatch.setattr("fega_schmitt_mcp.server._shop_password", "secret")
    monkeypatch.setattr("fega_schmitt_mcp.server._datanorm_db", None)


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
# DATANORM fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_datanorm_article():
    return DatanormArticle(
        material_number="0815",
        short_text_1="ACME Leitungsschutzschalter",
        short_text_2="B16 1polig",
        unit="STK",
        price_unit=1,
        list_price=Decimal("15.00"),
        net_price=Decimal("9.80"),
        ean="4012345678901",
        manufacturer_type="LS-B16",
        manufacturer_item_number="ABC-123",
        main_group="14",
        main_group_name="Installationsgeräte",
        sub_group="87",
        sub_group_name="Leitungsschutzschalter",
        delivery_date="2026-10-21",
    )


@pytest.fixture
def mock_datanorm_hit():
    return DatanormSearchHit(
        material_number="0815", description="ACME Leitungsschutzschalter B16 1polig", matched="ean"
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
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
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
