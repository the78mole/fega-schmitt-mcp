"""Shared pytest fixtures for fega-schmitt-mcp tests."""

from decimal import Decimal

import pytest
from fega_schmitt_client import PriceAvailResultItem, Surcharge


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
