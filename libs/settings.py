import base64
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openaiApiKey: SecretStr | None = Field(None, validation_alias="OPENAI_API_KEY")
    cheapModel: str = Field("gpt-4o-mini", validation_alias="CHEAP_MODEL")
    strongModel: str = Field("gpt-4o", validation_alias="STRONG_MODEL")
    openaiRequestsPerMinute: int = Field(60, validation_alias="OPENAI_REQUESTS_PER_MINUTE")
    # Any OpenAI-compatible server for chat, such as Ollama at http://localhost:11434/v1. Empty means OpenAI.
    # Embeddings stay on OpenAI: the paper library's vectors have OpenAI's dimensions.
    llmBaseUrl: str = Field("", validation_alias="LLM_BASE_URL")
    llmTimeoutSeconds: int = Field(60, validation_alias="LLM_TIMEOUT_SECONDS")
    # How long the orchestrator waits for the Fact-Checker, which makes its own model calls.
    a2aTimeoutSeconds: int = Field(180, validation_alias="A2A_TIMEOUT_SECONDS")
    researcherMode: Literal["workflow", "agent"] = Field("workflow", validation_alias="RESEARCHER_MODE")

    redisHost: str = Field("localhost", validation_alias="REDIS_HOST")
    redisPort: int = Field(6379, validation_alias="REDIS_PORT")
    redisPassword: SecretStr = Field(validation_alias="REDIS_PASSWORD")

    postgresHost: str = Field("localhost", validation_alias="POSTGRES_HOST")
    postgresPort: int = Field(5432, validation_alias="POSTGRES_PORT")
    postgresUser: str = Field("researchdesk", validation_alias="POSTGRES_USER")
    postgresPassword: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")
    postgresDb: str = Field("researchdesk", validation_alias="POSTGRES_DB")

    agentSigningSeed: SecretStr = Field(validation_alias="AGENT_SIGNING_SEED")
    agentPublicKey: str = Field(validation_alias="AGENT_PUBLIC_KEY")
    searchHmacKey: SecretStr = Field(validation_alias="SEARCH_HMAC_KEY")
    notesHmacKey: SecretStr = Field(validation_alias="NOTES_HMAC_KEY")
    evilHmacKey: SecretStr = Field(validation_alias="EVIL_HMAC_KEY")
    libraryHmacKey: SecretStr = Field(validation_alias="LIBRARY_HMAC_KEY")

    factCheckerSigningSeed: SecretStr = Field(validation_alias="FACTCHECKER_SIGNING_SEED")
    factCheckerPublicKey: str = Field(validation_alias="FACTCHECKER_PUBLIC_KEY")
    userApiKey: SecretStr = Field(validation_alias="USER_API_KEY")
    approverApiKey: SecretStr = Field(validation_alias="APPROVER_API_KEY")
    sessionSecret: SecretStr = Field(validation_alias="SESSION_SECRET")
    cookieSecure: bool = Field(False, validation_alias="COOKIE_SECURE")

    gatewayUrl: str = Field("http://localhost:8100/mcp", validation_alias="GATEWAY_URL")
    searchUrl: str = Field("http://localhost:8101/mcp", validation_alias="SEARCH_URL")
    notesUrl: str = Field("http://localhost:8102/mcp", validation_alias="NOTES_URL")
    libraryUrl: str = Field("http://localhost:8103/mcp", validation_alias="LIBRARY_URL")
    factCheckerUrl: str = Field("http://localhost:8110", validation_alias="FACTCHECKER_URL")
    apiUrl: str = Field("http://localhost:8010", validation_alias="API_URL")

    otlpEndpoint: str = Field("http://localhost:4318", validation_alias="OTLP_ENDPOINT")
    jaegerUrl: str = Field("http://localhost:16686", validation_alias="JAEGER_URL")
    kibanaUrl: str = Field("http://localhost:5601", validation_alias="KIBANA_URL")
    elasticsearchUrl: str = Field("http://localhost:9200", validation_alias="ELASTICSEARCH_URL")
    logRetentionDays: int = Field(30, validation_alias="LOG_RETENTION_DAYS")
    langfuseProjectUrl: str = Field("", validation_alias="LANGFUSE_PROJECT_URL")
    # The Obsidian vault finished reports are written to; open this folder in Obsidian.
    knowledgeDir: str = Field("knowledge", validation_alias="KNOWLEDGE_DIR")

    def trustedIssuers(self) -> dict[str, bytes]:
        return {
            "orchestrator": self.decodeKey(self.agentPublicKey),
            "factChecker": self.decodeKey(self.factCheckerPublicKey),
        }

    def makeRedis(self, db: int = 0) -> Redis:
        return Redis(
            host=self.redisHost,
            port=self.redisPort,
            password=self.redisPassword.get_secret_value(),
            db=db,
            decode_responses=True,
        )

    @property
    def postgresUrl(self) -> str:
        password = self.postgresPassword.get_secret_value()
        return f"postgresql://{self.postgresUser}:{password}@{self.postgresHost}:{self.postgresPort}/{self.postgresDb}"

    @staticmethod
    def decodeKey(value: str) -> bytes:
        return base64.urlsafe_b64decode(value)
