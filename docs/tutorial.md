# 10 minutos com tap-ixc

Um passeio prático: do zero até dados sincronizados, incremental e agendado. Ao
final você terá rodado uma carga real e entendido o ciclo.

!!! info "Pré-requisitos"
    Python 3.12+, um PostgreSQL acessível e credenciais de uma instância IXC Soft
    (`base_url` + `token` no formato `usuario:token`).

## 1. Instalar

```bash
git clone https://github.com/arktnld/tap-ixc && cd tap-ixc
pip install -e .
```

Isso cria o comando `tap-ixc`. Confira:

```bash
tap-ixc --help
```

## 2. Configurar seu primeiro cliente

A configuração vive em `config/clients.yml`. Crie a partir do exemplo:

```bash
cp config/clients.yml.example config/clients.yml
```

Edite para o seu provedor — começamos com **um** endpoint (`clientes`):

```yaml
acme:
  system: ixc
  schema_name: public
  postgres_dsn: "postgresql://postgres:senha@localhost:5432/acme"
  duckdb_path: "/tmp/etl-staging/acme.duckdb"
  api:
    base_url: "https://acme.ixcsoft.com.br/webservice/v1"
    token: "10:seu_token_aqui"
  endpoints:
    - name: clientes
      api_endpoint: cliente
      strategy: full
```

## 3. Preparar o monitoramento

A lib registra cada run num schema PostgreSQL dedicado. Aponte e crie as tabelas:

```bash
export ETL_MONITOR_DSN="postgresql://postgres:senha@localhost:5432/acme"
psql "$ETL_MONITOR_DSN" -f docs/schema.sql
```

## 4. Validar antes de rodar

```bash
tap-ixc check acme
```

```text
  ✓ API de 'acme' ok.
  ✓ Monitoramento ok (schema 'etl').
```

Se algo faltar, a mensagem diz exatamente o quê (token, env var, schema...).

## 5. Primeira carga

```bash
tap-ixc run acme
```

```text
  ✓ clientes: 12435 registros
```

Veja os dados:

```sql
SELECT count(*) FROM public.clientes;     -- 12435
```

E o histórico do run:

```bash
tap-ixc status --client acme
```

## 6. Ligar o modo incremental

Carregar 12 mil clientes todo dia é desperdício. Mude para `delta` — só o que mudou:

```yaml
    - name: clientes
      api_endpoint: cliente
      strategy: delta        # incremental por ultima_atualizacao
      pk_column: id
```

O primeiro `delta` ainda exige um backfill — você já fez no passo 5 com `full`.
A partir de agora, cada run baixa só os registros alterados desde o último:

```bash
tap-ixc run acme
# → clientes: 37 registros   (só o que mudou hoje)
```

A lib guarda o cursor (`ultima_atualizacao`) no checkpoint e avança **só** após o
carregamento completo. Pular um dia não perde dados. Um dia sem mudanças é um
no-op de sucesso. (Detalhes em [Incremental](incremental-and-validation.md).)

## 7. Adicionar mais endpoints

Acrescente `contratos` e `titulos` ao `clients.yml`:

```yaml
    - name: contratos
      api_endpoint: cliente_contrato
      strategy: delta
      pk_column: id
    - name: titulos
      api_endpoint: fn_areceber
      strategy: delta
      pk_column: id
```

```bash
tap-ixc run acme                       # sincroniza os três
tap-ixc run acme --stream titulos      # ou só um
```

## 8. Agendar

Cada run é idempotente e o load é atômico — pode agendar sem medo. No cron:

```cron
0 8 * * * cd /opt/tap-ixc && ETL_MONITOR_DSN="$ETL_MONITOR_DSN" tap-ixc run acme >> /var/log/tap-ixc.log 2>&1
```

`tap-ixc run` sai com código `!= 0` se algum stream falhar — o agendador detecta.
Para Airflow, veja [Deploy](deployment.md).

## Pronto

Você instalou, configurou, validou, carregou, ligou o incremental e agendou.
Próximos caminhos:

- **Excluir campos sensíveis** (ex: `senha`) → [Configuração: `fields`](configuration.md#fields-projetarexcluir-colunas)
- **Validar linhas e isolar lixo** → [Incremental e validação](incremental-and-validation.md)
- **Como funciona por dentro** → [Arquitetura](concepts.md)
- **Adicionar um endpoint novo via código** → [Streams](streams.md)
