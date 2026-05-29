# Primeiros passos

Do clone até o primeiro `run`, em **6 passos**.

## Pré-requisitos

- **Python 3.12+**
- **PostgreSQL** acessível (serve de destino dos dados **e** do banco de monitoramento)
- Credenciais de uma instância **IXC Soft** (`base_url` + `token` no formato `usuario:token`)

## Passo a passo

```bash
# 1. clonar e entrar
git clone https://github.com/arktnld/tap-ixc && cd tap-ixc

# 2. instalar (cria o comando `tap-ixc`)
pip install -e .

# 3. ter um Postgres rodando (destino + monitoramento)

# 4. criar sua config a partir do exemplo e editar
cp config/clients.yml.example config/clients.yml
$EDITOR config/clients.yml          # base_url, token, postgres_dsn

# 5. apontar o banco de monitoramento e criar as tabelas
export ETL_MONITOR_DSN="postgresql://user:pass@localhost:5432/seu_db"
psql "$ETL_MONITOR_DSN" -f docs/schema.sql

# 6. validar e rodar
tap-ixc check minha-empresa         # valida API + monitoramento
tap-ixc run   minha-empresa         # sincroniza
```

!!! warning "O passo 4 é obrigatório"
    `config/clients.yml` **não** vem no repositório (apenas `config/clients.yml.example`).
    Se você esquecer, a CLI avisa com o comando exato:
    ```
    Config de clientes não encontrada: .../config/clients.yml
    Crie a partir do exemplo:
        cp config/clients.yml.example config/clients.yml
    ```

## Instalação como dependência

Para usar em outro projeto (sem clonar):

```bash
pip install git+https://github.com/arktnld/tap-ixc.git
```

Nesse caso você usa a [API Python](python-api.md) diretamente (passando `ApiConfig` e
`Destination` no código), sem precisar do `clients.yml`.

## Verificando a instalação

```bash
tap-ixc --help          # lista os comandos
tap-ixc list            # lista clientes do clients.yml
tap-ixc check <cliente> # valida credenciais + banco de monitoramento
```

`check` testa **as duas pontas** e aponta exatamente o que falta:

```text
  ✓ API de 'minha-empresa' ok.
  ✗ Monitoramento: tabelas ausentes. Rode:
      psql "$ETL_MONITOR_DSN" -f docs/schema.sql
```

## Próximo passo

Entendido o básico, veja [Configuração](configuration.md) para todos os campos do
`clients.yml`, ou a [API Python](python-api.md) para uso programático.
