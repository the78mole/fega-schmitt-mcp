"""The webshop consent flow over a real (in-process) MCP client connection.

Runs once per protocol generation: with the 2025 handshake the server asks via
a standalone elicitation request mid-call; from 2026-07-28 on it returns an
InputRequiredResult and the client retries with the answer. Either way the
user's answer decides, and ``allow_web`` only counts for clients that cannot
elicit.
"""

from unittest.mock import MagicMock, patch

import pytest
from mcp import types
from mcp.client import Client

from fega_schmitt_mcp.server import mcp

PROTOCOL_MODES = ["legacy", "auto"]  # auto negotiates the newest revision in-process


async def _accept(context, params):
    return types.ElicitResult(action="accept", content={"allow": True})


async def _accept_unchecked(context, params):
    return types.ElicitResult(action="accept", content={"allow": False})


async def _decline(context, params):
    return types.ElicitResult(action="decline")


async def _cancel(context, params):
    return types.ElicitResult(action="cancel")


async def _call_favorites(mode: str, elicitation_callback, arguments: dict | None = None):
    client = MagicMock()
    client.__exit__.return_value = False
    client.get_favorite_list.return_value = []
    kwargs = {"mode": mode}
    if elicitation_callback is not None:
        kwargs["elicitation_callback"] = elicitation_callback
    with patch("fega_schmitt_mcp.server._build_web_client", return_value=client) as build:
        async with Client(mcp, **kwargs) as session:
            result = await session.call_tool("web_get_favorites", arguments or {})
    return result.structured_content, build.call_count


@pytest.mark.anyio
@pytest.mark.parametrize("mode", PROTOCOL_MODES)
async def test_user_agrees(mode):
    asked = []

    async def callback(context, params):
        asked.append(params.message)
        return await _accept(context, params)

    result, built = await _call_favorites(mode, callback)
    assert result == {"results": []}
    assert built == 1
    assert len(asked) == 1
    assert "Favoritenliste" in asked[0]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", PROTOCOL_MODES)
@pytest.mark.parametrize("callback", [_decline, _cancel, _accept_unchecked])
async def test_user_refuses(mode, callback):
    result, built = await _call_favorites(mode, callback)
    assert result["web_confirmation_required"] is True
    assert "abgelehnt" in result["error"]
    assert built == 0


@pytest.mark.anyio
@pytest.mark.parametrize("mode", PROTOCOL_MODES)
async def test_allow_web_cannot_override_a_refusal(mode):
    result, built = await _call_favorites(mode, _decline, {"allow_web": True})
    assert "abgelehnt" in result["error"]
    assert built == 0


@pytest.mark.anyio
@pytest.mark.parametrize("mode", PROTOCOL_MODES)
async def test_client_without_elicitation_needs_allow_web(mode):
    result, built = await _call_favorites(mode, None)
    assert result["web_confirmation_required"] is True
    assert "allow_web=true" in result["error"]
    assert built == 0


@pytest.mark.anyio
@pytest.mark.parametrize("mode", PROTOCOL_MODES)
async def test_client_without_elicitation_with_allow_web(mode):
    result, built = await _call_favorites(mode, None, {"allow_web": True})
    assert result == {"results": []}
    assert built == 1
