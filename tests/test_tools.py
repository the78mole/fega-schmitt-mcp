"""Unit tests for fega-schmitt MCP tool functions.

All tests patch ``_build_client`` so no real HTTP requests are made and no
environment variables need to be set.
"""

from unittest.mock import MagicMock, patch

from fega_schmitt_client import FegaAuthError, FegaTransportError

from fega_schmitt_mcp.server import PriceAvailItem, _result_to_dict, get_price_availability

# ---------------------------------------------------------------------------
# _result_to_dict
# ---------------------------------------------------------------------------


class TestResultToDict:
    def test_ok_result_is_mapped(self, mock_result_ok):
        result = _result_to_dict(mock_result_ok)
        assert result["material_number"] == "0815"
        assert result["status"] == "ok"
        assert result["availability_status"] == "V"
        assert result["net_amount"] == "13.20"
        assert result["surcharges"] == [{"code": "CU", "text": "Kupferzuschlag", "amount": "0.70"}]

    def test_error_result_has_none_amounts(self, mock_result_error):
        result = _result_to_dict(mock_result_error)
        assert result["status"] == "error"
        assert result["net_amount"] is None
        assert result["surcharges"] == []


# ---------------------------------------------------------------------------
# get_price_availability
# ---------------------------------------------------------------------------


class TestGetPriceAvailability:
    def test_empty_items_returns_error(self):
        result = get_price_availability([])
        assert "error" in result

    def test_invalid_quantity_returns_error(self):
        items = [PriceAvailItem(material_number="0815", quantity="not-a-number")]
        result = get_price_availability(items)
        assert "error" in result

    def test_successful_call_returns_results(self, mock_result_ok):
        mock_client = MagicMock()
        mock_client.get_price_availability.return_value = [mock_result_ok]
        with patch("fega_schmitt_mcp.server._build_client", return_value=mock_client):
            result = get_price_availability([PriceAvailItem(material_number="0815", quantity="200", unit="MTR")])

        assert "results" in result
        assert result["results"][0]["material_number"] == "0815"

    def test_mixed_ok_and_error_items(self, mock_result_ok, mock_result_error):
        mock_client = MagicMock()
        mock_client.get_price_availability.return_value = [mock_result_ok, mock_result_error]
        with patch("fega_schmitt_mcp.server._build_client", return_value=mock_client):
            result = get_price_availability(
                [
                    PriceAvailItem(material_number="0815", quantity="200", unit="MTR"),
                    PriceAvailItem(material_number="unknown"),
                ]
            )

        assert len(result["results"]) == 2
        assert result["results"][0]["status"] == "ok"
        assert result["results"][1]["status"] == "error"

    def test_missing_credentials_returns_error(self):
        with patch("fega_schmitt_mcp.server._build_client", side_effect=FegaAuthError("nope")):
            result = get_price_availability([PriceAvailItem(material_number="0815")])
        assert "error" in result

    def test_transport_error_returns_error_dict(self):
        mock_client = MagicMock()
        mock_client.get_price_availability.side_effect = FegaTransportError("timeout")
        with patch("fega_schmitt_mcp.server._build_client", return_value=mock_client):
            result = get_price_availability([PriceAvailItem(material_number="0815")])
        assert "error" in result

    def test_value_error_returns_error_dict(self):
        mock_client = MagicMock()
        mock_client.get_price_availability.side_effect = ValueError("maximal 999 Artikel erlaubt")
        with patch("fega_schmitt_mcp.server._build_client", return_value=mock_client):
            result = get_price_availability([PriceAvailItem(material_number="0815")])
        assert "error" in result
