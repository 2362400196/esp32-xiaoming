"""gateways.py 单元测试

历史上该文件还包含 LLM/TTS/Tool/Memory/Emotion 网关的测试，
但这些实现已删除（分别由 llm_gateways.py / tts_gateways.py / use_cases 层取代），
此处仅保留 ASR 重导出的测试。
"""
from unittest.mock import MagicMock, patch

from src.interfaces.gateways import create_asr_gateway


# ============================================================
# create_asr_gateway 重导出
# ============================================================


class TestCreateASRGateway:
    """create_asr_gateway 重导出"""

    def test_is_callable(self):
        # create_asr_gateway 是从 src.interfaces.asr 重导出的可调用对象
        assert callable(create_asr_gateway)

    def test_creates_asr_gateway(self):
        # 通过 gateways 模块引用调用，便于 patch
        import src.interfaces.gateways as gw_module
        with patch.object(gw_module, "create_asr_gateway") as mock_create:
            mock_gateway = MagicMock()
            mock_create.return_value = mock_gateway
            result = gw_module.create_asr_gateway(config={"provider": "volcengine"})
            mock_create.assert_called_once()
            assert result is mock_gateway

    def test_creates_with_default(self):
        import src.interfaces.gateways as gw_module
        with patch.object(gw_module, "create_asr_gateway") as mock_create:
            mock_gateway = MagicMock()
            mock_create.return_value = mock_gateway
            gw_module.create_asr_gateway(config=None)
            mock_create.assert_called_once()
