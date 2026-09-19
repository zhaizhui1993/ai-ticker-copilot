"""P0 验收测试：Settings 默认值与打码输出。"""

from config.settings import Settings, dump_masked


def test_settings_defaults() -> None:
    s = Settings()
    assert s.mock_mode is False
    assert s.db_port == 3306
    assert s.event_poll_interval_min == 20
    assert s.max_x_bloggers_per_run == 5
    assert s.llm_temperature == 0.3


def test_dump_masked_hides_secrets() -> None:
    masked = dump_masked()
    assert "llm_api_key" in masked
    assert "db_password" in masked
    # 未配置时为空串，配置后只保留前 4 字符 + ****
    for key in ("llm_api_key", "fred_api_key", "db_password"):
        value = masked[key]
        assert value == "" or value.endswith("****")
