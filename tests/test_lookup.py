"""Tests for search_articles and get_article: DATANORM and SOAP first, the webshop
only with consent, cached shop pages without asking.

The client library's ArticleLookup and web cache run for real (the cache in
tmp_path, see conftest.py); only the DATANORM store, the SOAP client and the
webshop client are fakes.
"""

from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from unittest.mock import MagicMock, patch

import anyio
import pytest
from fega_schmitt_client import FegaTransportError
from fega_schmitt_client.web.cache import WebArticleCache

from fega_schmitt_mcp.server import get_article, search_articles


class NoElicitationContext:
    """Stands in for the MCP Context of a client without elicitation support."""

    client_capabilities = None
    protocol_version = None
    input_responses = None


def _run(tool, *args, **kwargs):
    return anyio.run(partial(tool, *args, ctx=NoElicitationContext(), **kwargs))


def _mock_web_client(**attrs: object) -> MagicMock:
    client = MagicMock(**attrs)
    client.__exit__.return_value = False
    return client


@pytest.fixture
def fresh_article(mock_article):
    """mock_article as fetched just now, so the 30-day web cache accepts it."""
    return replace(mock_article, fetched_at=datetime.now(timezone.utc))


@pytest.fixture
def datanorm(mock_datanorm_article, mock_datanorm_hit):
    store = MagicMock(delivery_date="2026-10-21")
    store.get_article.side_effect = lambda number: mock_datanorm_article if number == "0815" else None
    store.search.side_effect = lambda query, limit: [mock_datanorm_hit] if query == "4012345678901" else []
    with patch("fega_schmitt_mcp.server.DatanormStore.open", return_value=store):
        yield store


@pytest.fixture
def soap(mock_result_ok):
    client = MagicMock()
    client.get_price_availability.return_value = [mock_result_ok]
    with patch("fega_schmitt_mcp.server._build_client", return_value=client):
        yield client


@pytest.fixture
def web(fresh_article, mock_search_result):
    client = _mock_web_client()
    client.get_article.return_value = fresh_article
    client.search.return_value = [mock_search_result]
    with patch("fega_schmitt_mcp.server._build_web_client", return_value=client) as build:
        yield build


# ---------------------------------------------------------------------------
# search_articles
# ---------------------------------------------------------------------------


class TestSearchArticles:
    def test_datanorm_hit_does_not_touch_the_webshop(self, datanorm, web):
        result = _run(search_articles, "4012345678901")
        assert result["datanorm_delivery_date"] == "2026-10-21"
        assert result["results"] == [
            {
                "material_number": "0815",
                "description": "ACME Leitungsschutzschalter B16 1polig",
                "source": "datanorm",
                "matched": "ean",
            }
        ]
        web.assert_not_called()

    def test_no_hit_without_consent_asks(self, datanorm, web):
        result = _run(search_articles, "gibt es nicht")
        assert result["results"] == []
        assert result["web_confirmation_required"] is True
        web.assert_not_called()

    def test_no_hit_with_consent_searches_the_webshop(self, datanorm, web):
        result = _run(search_articles, "gibt es nicht", allow_web=True)
        assert result["results"][0]["source"] == "web"
        assert result["results"][0]["material_number"] == "0815"

    def test_web_results_respect_limit(self, datanorm, web, mock_search_result):
        web.return_value.search.return_value = [mock_search_result] * 5
        result = _run(search_articles, "gibt es nicht", limit=2, allow_web=True)
        assert len(result["results"]) == 2

    def test_no_hit_without_credentials_does_not_ask(self, datanorm, web, monkeypatch):
        monkeypatch.setattr("fega_schmitt_mcp.server._shop_password", None)
        result = _run(search_articles, "gibt es nicht")
        assert result["results"] == []
        assert "web_confirmation_required" not in result

    def test_without_database_warns(self, web):
        result = _run(search_articles, "0815")
        assert result["datanorm_delivery_date"] is None
        assert "datanorm import" in result["warnings"][0]
        assert result["web_confirmation_required"] is True


# ---------------------------------------------------------------------------
# get_article
# ---------------------------------------------------------------------------


class TestGetArticle:
    def test_datanorm_and_soap_without_webshop(self, datanorm, soap, web):
        result = _run(get_article, "0815")
        assert result["sources"] == ["datanorm", "soap"]
        assert result["description"] == "ACME Leitungsschutzschalter B16 1polig"
        assert result["datanorm"]["net_price"] == "9.80"
        assert result["datanorm"]["delivery_date"] == "2026-10-21"
        assert result["price_availability"]["net_amount"] == "13.20"
        assert result["web"] is None
        web.assert_not_called()

    def test_include_web_without_consent_returns_local_data(self, datanorm, soap, web):
        result = _run(get_article, "0815", include_web=True)
        assert result["sources"] == ["datanorm", "soap"]
        assert result["web_confirmation_required"] is True
        web.assert_not_called()

    def test_include_web_with_consent_fetches_and_caches(self, datanorm, soap, web):
        result = _run(get_article, "0815", include_web=True, allow_web=True)
        assert result["sources"] == ["datanorm", "soap", "web"]
        assert result["web"]["category"] == {"id": "UWG_14_87", "name": "Leitungsschutzschalter"}
        assert result["web_from_cache"] is False
        with WebArticleCache() as cache:
            assert cache.get("0815") is not None

    def test_cached_web_data_comes_without_asking(self, datanorm, soap, web, fresh_article):
        with WebArticleCache() as cache:
            cache.put(fresh_article)
        result = _run(get_article, "0815")
        assert result["sources"] == ["datanorm", "soap", "web"]
        assert result["web_from_cache"] is True
        web.assert_not_called()

    def test_stale_cache_entry_is_not_used(self, datanorm, soap, web, mock_article):
        with WebArticleCache() as cache:
            cache.put(mock_article)  # fetched 2026-08-12, older than 30 days
        result = _run(get_article, "0815")
        assert result["web"] is None
        web.assert_not_called()

    def test_refresh_web_asks_despite_cache(self, datanorm, soap, web, fresh_article):
        with WebArticleCache() as cache:
            cache.put(fresh_article)
        result = _run(get_article, "0815", include_web=True, refresh_web=True)
        assert result["web_confirmation_required"] is True
        assert result["web"] is None
        web.assert_not_called()

    def test_webshop_failure_becomes_warning(self, datanorm, soap, web):
        web.return_value.get_article.side_effect = FegaTransportError("timeout")
        result = _run(get_article, "0815", include_web=True, allow_web=True)
        assert result["sources"] == ["datanorm", "soap"]
        assert any("Webshop fehlgeschlagen" in w for w in result["warnings"])

    def test_soap_failure_becomes_warning(self, datanorm, soap, web):
        soap.get_price_availability.side_effect = FegaTransportError("timeout")
        result = _run(get_article, "0815")
        assert result["sources"] == ["datanorm"]
        assert any("SOAP" in w for w in result["warnings"])

    def test_unknown_article_hints_at_webshop(self, datanorm, web, mock_result_error):
        with patch("fega_schmitt_mcp.server._build_client") as build:
            build.return_value.get_price_availability.return_value = [mock_result_error]
            result = _run(get_article, "9999")
        assert "nicht gefunden" in result["error"]
        assert "include_web" in result["hint"]
        web.assert_not_called()

    def test_article_only_in_webshop(self, datanorm, web, mock_result_error):
        with patch("fega_schmitt_mcp.server._build_client") as build:
            build.return_value.get_price_availability.return_value = [mock_result_error]
            result = _run(get_article, "9999", include_web=True, allow_web=True)
        assert result["sources"] == ["web"]

    def test_without_credentials_uses_datanorm_only(self, datanorm, web, monkeypatch):
        monkeypatch.setattr("fega_schmitt_mcp.server._customer_number", None)
        result = _run(get_article, "0815", include_web=True)
        assert result["sources"] == ["datanorm"]
        assert "web_confirmation_required" not in result
        assert any("kein Zugang" in w for w in result["warnings"])
        web.assert_not_called()
