"""全局配置单例（.env → Settings）。

约定（docs/10-module-contracts.md §10.6）：本模块是 .env 的唯一读取点，
其余模块一律经依赖注入获取 Settings 实例，禁止散落的 os.getenv。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 打印配置时需要打码的敏感项
_SECRET_KEYS = {"llm_api_key", "fred_api_key", "db_password", "x_api_key"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM（供应商无关，OpenAI 兼容协议；换供应商只改这三项）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""  # .env 必填：gpt-4o / qwen-max / glm-4.x / deepseek-chat 等
    llm_temperature: float = 0.3

    # FRED 宏观（https://fred.stlouisfed.org 免费注册）
    fred_api_key: str = ""

    # 运行模式：true = 全链路 mock 数据（无网无 key 验证系统）
    mock_mode: bool = False

    # MySQL 8（启动时健康检查失败会给出中文指引）
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "ticker_copilot"

    # 缓存目录（相对项目根）
    cache_dir: str = "data/cache"

    # X 数据源：api = twitterapi.io 第三方接口（推荐，无需登录态）；crawl = Playwright
    # 本地爬虫（免 API 费用，需导出 cookie）；off = 关闭 X 采集
    x_mode: str = "crawl"
    x_api_key: str = ""  # twitterapi.io 控制台获取；X_MODE=api 时必填
    x_api_base: str = "https://api.twitterapi.io"

    # X 爬虫（防风控：每博主每天最多 1 次在 crawl_state 表节流，两种模式共用）
    x_storage_state_path: str = "data/x_state/state.json"
    max_x_bloggers_per_run: int = 5
    x_post_hours_back: int = 48

    # 新闻源（逗号分隔 RSS；留空使用内置默认源）
    news_rss_feeds: str = ""

    # 调度（三类核心任务：事件轮询 / 收盘分析 / X 低频，另有自动沉淀，见 scheduler.py）
    scheduler_enabled: bool = True
    event_poll_interval_min: int = 20
    new_event_notify: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def dump_masked() -> dict:
    """返回打码后的配置快照（用于打印/日志，不泄露密钥）。"""
    return {
        k: (v[:4] + "****" if k in _SECRET_KEYS and v else v)
        for k, v in settings.model_dump().items()
    }


if __name__ == "__main__":
    # P0 验收：settings 可打印全部配置（敏感项打码）
    for key, value in dump_masked().items():
        print(f"{key} = {value!r}")
