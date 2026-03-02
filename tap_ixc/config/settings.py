"""Config centralizada: Pydantic Settings + clients.yml."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiConfig(BaseModel):
    base_url: str
    token: str
    max_retries: int = 3
    backoff_factor: float = 0.5
    timeout_s: int = 60
    wait_jitter: float = 1.0           # jitter no backoff (anti-thundering-herd)
    session_renewal_every: int = 0     # recriar sessão a cada N páginas (0 = desligado)
    rate_limit_sleep: float = 0.0      # pausa entre páginas em segundos (0 = desligado)


class EndpointConfig(BaseModel):
    name: str           # nome da tabela destino (ex: clientes)
    api_endpoint: str   # nome do endpoint na API (ex: cliente)
    strategy: Literal["full", "delta"] = "full"
    pk_column: str = "id"
    page_size: int = 5000
    timeout_s: int = 60
    # Lista de campos a manter — None = SELECT * (todos os campos)
    fields: list[str] | None = None
    # SQL de transformação customizado — sobrescreve `fields` se definido
    transform_sql: str | None = None
    # caminho dotted para classe Pydantic de validação (opcional)
    schema_cls: str | None = None


class ClientConfig(BaseModel):
    client: str
    system: str
    schema_name: str
    postgres_dsn: str
    api: ApiConfig
    endpoints: list[EndpointConfig] = []
    webhook_url: str | None = None
    duckdb_path: str = "/tmp/etl-staging/{client}.duckdb"

    @model_validator(mode="after")
    def _resolve_env(self) -> "ClientConfig":
        """Expande ${VAR} em campos de string."""
        self.postgres_dsn = _expand(self.postgres_dsn)
        self.api.base_url = _expand(self.api.base_url)
        self.api.token = _expand(self.api.token)
        if self.webhook_url:
            self.webhook_url = _expand(self.webhook_url)
        return self

    def duckdb_resolved(self) -> str:
        return self.duckdb_path.format(client=self.client)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ETL_",
        env_file=".env",
        extra="ignore",
    )

    monitor_dsn: str = Field(
        default="postgresql://etl:etl@localhost:5432/etl_monitor",
    )
    monitor_schema: str = Field(default="etl")
    clients_yml: Path = Path(__file__).parent.parent.parent / "config" / "clients.yml"


_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _expand(value: str) -> str:
    """Expande ${VAR} usando variáveis de ambiente."""
    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        var = m.group(1)
        return os.environ.get(var, m.group(0))
    return _ENV_PATTERN.sub(_replace, value)


def load_clients(path: Path | None = None) -> dict[str, ClientConfig]:
    settings = Settings()
    yml_path = path or settings.clients_yml
    raw: dict = yaml.safe_load(yml_path.read_text())
    clients: dict[str, ClientConfig] = {}
    for name, data in raw.items():
        data["client"] = name
        clients[name] = ClientConfig.model_validate(data)
    return clients


def get_client(name: str, path: Path | None = None) -> ClientConfig:
    clients = load_clients(path)
    if name not in clients:
        raise KeyError(f"Cliente '{name}' não encontrado em clients.yml")
    return clients[name]
