"""MCP-protocol-level tests for the fega-schmitt MCP server.

These tests call ``mcp.list_tools()`` and ``mcp.call_tool()`` directly on the
MCPServer instance, which exercises the full MCP dispatch path (argument
validation, tool lookup, serialisation) without needing a real HTTP transport.
"""

from unittest.mock import MagicMock, patch

import pytest

from fega_schmitt_mcp.server import mcp

EXPECTED_TOOLS = {
    "search_articles",
    "get_article",
    "get_price_availability",
    "web_set_article_number",
    "web_get_cable_lengths",
    "web_list_articles_by_category",
    "web_get_favorites",
    "web_get_deal_campaigns",
    "web_get_deal_articles",
    "web_get_daily_deals",
    "web_get_second_choice_articles",
    "web_get_cart",
    "web_get_cart_list",
    "web_get_order_list",
    "web_get_order",
}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_all_expected_tools_are_registered():
    tools = await mcp.list_tools()
    registered = {t.name for t in tools}
    assert EXPECTED_TOOLS == registered, f"Missing: {EXPECTED_TOOLS - registered}, Extra: {registered - EXPECTED_TOOLS}"


@pytest.mark.anyio
async def test_each_tool_has_description():
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.description, f"Tool '{tool.name}' has no description"


@pytest.mark.anyio
async def test_get_price_availability_has_items_parameter():
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "get_price_availability")
    params = tool.input_schema.get("properties", {})
    assert "items" in params


# ---------------------------------------------------------------------------
# Tool call – get_price_availability
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_call_get_price_availability_returns_results(mock_result_ok):
    mock_client = MagicMock()
    mock_client.get_price_availability.return_value = [mock_result_ok]
    with patch("fega_schmitt_mcp.server._build_client", return_value=mock_client):
        result = await mcp.call_tool(
            "get_price_availability",
            {"items": [{"material_number": "0815", "quantity": "200", "unit": "MTR"}]},
        )

    data = _parse_result(result)
    assert data["results"][0]["material_number"] == "0815"
    assert data["results"][0]["status"] == "ok"


@pytest.mark.anyio
async def test_call_get_price_availability_empty_items_returns_error():
    result = await mcp.call_tool("get_price_availability", {"items": []})
    data = _parse_result(result)
    assert "error" in data


# ---------------------------------------------------------------------------
# Tool schemas - webshop consent
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_web_tools_take_allow_web_defaulting_to_false():
    tools = await mcp.list_tools()
    web_tools = [t for t in tools if t.name.startswith("web_") or t.name in ("search_articles", "get_article")]
    for tool in web_tools:
        allow_web = tool.input_schema["properties"].get("allow_web")
        assert allow_web is not None, f"Tool '{tool.name}' has no allow_web parameter"
        assert allow_web["default"] is False
        assert "ctx" not in tool.input_schema["properties"]


@pytest.mark.anyio
async def test_soap_tool_has_no_allow_web():
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "get_price_availability")
    assert "allow_web" not in tool.input_schema["properties"]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse_result(result):
    """Extract the raw Python value returned by mcp.call_tool().

    MCPServer returns a ``CallToolResult`` whose ``structured_content``
    holds the un-serialised Python dict/list.
    """
    return result.structured_content
