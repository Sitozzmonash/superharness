from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from super_harness import ZhipuVisionProvider, ZhipuWebSearchProvider

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(
    not os.environ.get("ZHIPU_SEARCH_API_KEY"), reason="ZHIPU_SEARCH_API_KEY is not configured"
)
@pytest.mark.asyncio
async def test_real_zhipu_search_returns_fresh_sourced_result() -> None:
    response = await ZhipuWebSearchProvider().search("北京今天的日期", top_n=3)
    assert response.results
    assert any(item.url.startswith("http") for item in response.results)


@pytest.mark.skipif(
    not os.environ.get("ZHIPU_VISION_API_KEY"), reason="ZHIPU_VISION_API_KEY is not configured"
)
@pytest.mark.asyncio
async def test_real_zhipu_vision_local_and_url(tmp_path: Path) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )
    provider = ZhipuVisionProvider()
    local = await provider.analyze(image, "Describe the image briefly")
    remote = await provider.analyze("https://httpbin.org/image/png", "Describe the image briefly")
    assert local.text.strip()
    assert remote.text.strip()
