import os

import pytest

from deepseek_api import DeepSeekSettings
from deepseek_client import DeepSeekClient
from model_client import ModelMessage


@pytest.mark.skipif(
    os.getenv("RUN_DEEPSEEK_ONLINE") != "1",
    reason="设置 RUN_DEEPSEEK_ONLINE=1 后才调用真实 DeepSeek API",
)
def test_deepseek_online_smoke() -> None:
    client = DeepSeekClient(
        settings=DeepSeekSettings.from_env(),
        timeout_seconds=60,
    )

    reply = client.chat(
        [ModelMessage(role="user", content="只回答 OK")]
    )

    assert reply.text.strip()
    assert reply.usage.total_tokens > 0
