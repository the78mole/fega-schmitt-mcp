"""Unit tests for fega-schmitt MCP tool functions.

All tests patch ``_build_client``/``_build_web_client`` so no real HTTP
requests are made and no environment variables need to be set.
"""

from unittest.mock import ANY, MagicMock, patch

from fega_schmitt_client import FegaAuthError, FegaTransportError
from fega_schmitt_client.web import FegaLoginError, FegaScrapingError

from fega_schmitt_mcp.server import (
    PriceAvailItem,
    _result_to_dict,
    get_price_availability,
    web_get_article,
    web_get_cable_lengths,
    web_get_cart,
    web_get_cart_list,
    web_get_daily_deals,
    web_get_deal_articles,
    web_get_deal_campaigns,
    web_get_favorites,
    web_get_order,
    web_get_order_list,
    web_get_second_choice_articles,
    web_list_articles_by_category,
    web_search_articles,
    web_set_article_number,
)


def _mock_web_client(**attrs: object) -> MagicMock:
    """A MagicMock standing in for WebClient, usable as a context manager.

    ``__exit__`` must return a falsy value so exceptions raised inside
    ``with client: ...`` in ``_web_call`` propagate instead of being
    swallowed by the mock's (otherwise truthy) default return value.
    """
    client = MagicMock(**attrs)
    client.__exit__.return_value = False
    return client


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

    def test_default_shipment_type_and_partner_warehouse_passed_through(self, mock_result_ok):
        mock_client = MagicMock()
        mock_client.get_price_availability.return_value = [mock_result_ok]
        with patch("fega_schmitt_mcp.server._build_client", return_value=mock_client):
            get_price_availability([PriceAvailItem(material_number="0815")])

        mock_client.get_price_availability.assert_called_with([ANY], shipment_type="01", partner_warehouse=None)

    def test_shipment_type_and_partner_warehouse_passed_through(self, mock_result_ok):
        mock_client = MagicMock()
        mock_client.get_price_availability.return_value = [mock_result_ok]
        with patch("fega_schmitt_mcp.server._build_client", return_value=mock_client):
            get_price_availability(
                [PriceAvailItem(material_number="0815")],
                shipment_type="02",
                partner_warehouse="22",
            )

        mock_client.get_price_availability.assert_called_with([ANY], shipment_type="02", partner_warehouse="22")

    def test_invalid_partner_warehouse_returns_error_dict(self):
        mock_client = MagicMock()
        mock_client.get_price_availability.side_effect = ValueError(
            "partner_warehouse muss eine numerische Lagernummer mit maximal 4 Ziffern sein, erhalten: 'abcde'"
        )
        with patch("fega_schmitt_mcp.server._build_client", return_value=mock_client):
            result = get_price_availability(
                [PriceAvailItem(material_number="0815")],
                shipment_type="02",
                partner_warehouse="abcde",
            )
        assert "error" in result


# ---------------------------------------------------------------------------
# Web tools - shared error handling (checked once via web_search_articles,
# _web_call is exercised identically by every web_* tool)
# ---------------------------------------------------------------------------


class TestWebCallErrorHandling:
    def test_missing_credentials_returns_error(self):
        with patch("fega_schmitt_mcp.server._build_web_client", side_effect=FegaAuthError("nope")):
            result = web_search_articles("0815")
        assert "error" in result

    def test_login_error_returns_error_dict(self):
        client = _mock_web_client()
        client.search.side_effect = FegaLoginError("abgelehnt")
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_search_articles("0815")
        assert "error" in result

    def test_scraping_error_returns_error_dict(self):
        client = _mock_web_client()
        client.search.side_effect = FegaScrapingError("Markup geändert")
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_search_articles("0815")
        assert "error" in result

    def test_transport_error_returns_error_dict(self):
        client = _mock_web_client()
        client.search.side_effect = FegaTransportError("timeout")
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_search_articles("0815")
        assert "error" in result

    def test_client_is_closed_after_call(self):
        client = _mock_web_client()
        client.search.return_value = []
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            web_search_articles("0815")
        client.__exit__.assert_called_once()


# ---------------------------------------------------------------------------
# Web tools - individual tools
# ---------------------------------------------------------------------------


class TestWebSearchArticles:
    def test_returns_results(self, mock_search_result):
        client = _mock_web_client()
        client.search.return_value = [mock_search_result]
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_search_articles("0815")
        assert result["results"][0]["material_number"] == "0815"
        client.search.assert_called_with("0815")


class TestWebGetArticle:
    def test_returns_article_dict(self, mock_article):
        client = _mock_web_client()
        client.get_article.return_value = mock_article
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_article("0815")
        assert result["material_number"] == "0815"
        assert result["cutting_fee"] == "5.00"
        assert result["accessories"] == ["1000"]


class TestWebSetArticleNumber:
    def test_returns_ok_status(self):
        client = _mock_web_client()
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_set_article_number("0815", "MEIN-0815")
        assert result == {"status": "ok"}
        client.set_article_number.assert_called_with("0815", "MEIN-0815")


class TestWebGetCableLengths:
    def test_returns_results(self, mock_cable_length):
        client = _mock_web_client()
        client.get_cable_lengths.return_value = [mock_cable_length]
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_cable_lengths("0815")
        assert result["results"][0]["total_available_m"] == "1000"
        assert result["results"][0]["fixed_length_m"] == "500"


class TestWebListArticlesByCategory:
    def test_returns_results(self, mock_search_result):
        client = _mock_web_client()
        client.list_articles_by_category.return_value = [mock_search_result]
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_list_articles_by_category("UWG_14_87")
        assert result["results"][0]["material_number"] == "0815"
        client.list_articles_by_category.assert_called_with("UWG_14_87")


class TestWebGetFavorites:
    def test_returns_results(self, mock_search_result):
        client = _mock_web_client()
        client.get_favorite_list.return_value = [mock_search_result]
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_favorites()
        assert result["results"][0]["material_number"] == "0815"


class TestWebGetDealCampaigns:
    def test_returns_results(self, mock_deal_campaign):
        client = _mock_web_client()
        client.get_deal_campaigns.return_value = [mock_deal_campaign]
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_deal_campaigns()
        assert result["results"][0]["campaign_id"] == "42"


class TestWebGetDealArticles:
    def test_returns_results(self, mock_search_result):
        client = _mock_web_client()
        client.get_deal_articles.return_value = [mock_search_result]
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_deal_articles("42")
        assert result["results"][0]["material_number"] == "0815"
        client.get_deal_articles.assert_called_with("42")


class TestWebGetDailyDeals:
    def test_returns_empty_results(self):
        client = _mock_web_client()
        client.get_daily_deals.return_value = []
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_daily_deals()
        assert result["results"] == []


class TestWebGetSecondChoiceArticles:
    def test_default_deal_id_calls_without_argument(self, mock_search_result):
        client = _mock_web_client()
        client.get_second_choice_articles.return_value = [mock_search_result]
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_second_choice_articles()
        assert result["results"][0]["material_number"] == "0815"
        client.get_second_choice_articles.assert_called_with()

    def test_explicit_deal_id_passed_through(self, mock_search_result):
        client = _mock_web_client()
        client.get_second_choice_articles.return_value = [mock_search_result]
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            web_get_second_choice_articles(deal_id="9999")
        client.get_second_choice_articles.assert_called_with("9999")


class TestWebGetCart:
    def test_default_cart_id_calls_without_argument(self, mock_cart):
        client = _mock_web_client()
        client.get_cart.return_value = mock_cart
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_cart()
        assert result["cart_id"] == "1"
        assert result["items"][0]["quantity"] == "10"
        client.get_cart.assert_called_with()

    def test_explicit_cart_id_passed_through(self, mock_cart):
        client = _mock_web_client()
        client.get_cart.return_value = mock_cart
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            web_get_cart(cart_id="7")
        client.get_cart.assert_called_with("7")


class TestWebGetCartList:
    def test_returns_results(self, mock_cart_summary):
        client = _mock_web_client()
        client.get_cart_list.return_value = [mock_cart_summary]
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_cart_list()
        assert result["results"][0]["cart_id"] == "1"


class TestWebGetOrderList:
    def test_returns_results(self, mock_order_summary):
        client = _mock_web_client()
        client.get_order_list.return_value = [mock_order_summary]
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_order_list()
        assert result["results"][0]["order_number"] == "AB123"


class TestWebGetOrder:
    def test_returns_order_dict(self, mock_order):
        client = _mock_web_client()
        client.get_order.return_value = mock_order
        with patch("fega_schmitt_mcp.server._build_web_client", return_value=client):
            result = web_get_order("AB123")
        assert result["order_number"] == "AB123"
        assert result["items"][0]["quantity_ordered"] == "10"
        assert result["items"][0]["quantity_delivered"] == "8"
        client.get_order.assert_called_with("AB123")
