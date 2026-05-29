# Troubleshooting

Erros comuns, causa e correção. A CLI já tenta apontar a solução na própria
mensagem — abaixo está o detalhe.

## Configuração

### `Config de clientes não encontrada: .../config/clients.yml`

`config/clients.yml` não existe. Ele **não** vem no repositório (só o `.example`):

```bash
cp config/clients.yml.example config/clients.yml
$EDITOR config/clients.yml
```

### `Cliente 'x' não encontrado. Disponíveis: [...]`

O nome passado não está no `clients.yml`. Use um dos listados, ou rode
`tap-ixc list`.

### `variável de ambiente 'X' não definida (campo 'api.token')`

O `clients.yml` referencia `${X}` mas a variável não está exportada. Exporte-a:

```bash
export X="valor"
```

…ou troque por um valor literal no YAML. Veja [Configuração](configuration.md).

### `clients.yml com sintaxe YAML inválida`

Erro de indentação/sintaxe no YAML. A mensagem inclui a linha. Valide a
indentação (use espaços, não tabs).

## Banco de monitoramento

### `Falha ao conectar no Postgres de monitoramento (ETL_MONITOR_DSN)`

`ETL_MONITOR_DSN` aponta para um Postgres inacessível ou com credencial errada.
O default é `postgresql://etl:etl@localhost:5432/etl_monitor` — se você não criou
esse usuário/banco, aponte para um existente:

```bash
export ETL_MONITOR_DSN="postgresql://user:pass@host:5432/db"
```

### `Tabelas de monitoramento ausentes. Crie o schema...`

O banco conecta mas faltam as tabelas `etl.*`. Crie uma vez:

```bash
psql "$ETL_MONITOR_DSN" -f docs/schema.sql
```

!!! tip
    `tap-ixc check <cliente>` valida API **e** monitoramento de uma vez — rode antes
    do primeiro `run`.

## Execução

### `run` termina com `✗` em um stream, mas outros com `✓`

Comportamento esperado: streams são independentes. O `run` sai com código `!= 0`
se **qualquer** um falhar (para Airflow/cron detectarem), mas os que deram certo
foram carregados. O erro de cada um aparece na linha `erro:`.

### Incremental não traz nada (0 registros)

Se nada mudou desde o último cursor, 0 registros é o resultado correto — um no-op
de sucesso. Confira o cursor salvo:

```sql
SELECT metadata FROM etl.checkpoints WHERE client = 'x' AND pipeline = 'clientes';
```

### Registros apagados na origem continuam no destino

O incremental não captura deletes. Rode `strategy: full` periodicamente para
reconciliar. Veja [Incremental e validação](incremental-and-validation.md).

### Quero retomar uma carga que falhou no meio

```bash
tap-ixc run minha-empresa --from-checkpoint
```

Stages já concluídos são pulados; a carga retoma de onde parou.

## API IXC

### `HTTP 401` no `check`/`run`

Token inválido ou expirado. Confira o `token` (formato `usuario:token`) no
`clients.yml`.

### `API error: Recurso ... não está disponível`

O `api_endpoint` configurado não existe na sua instância IXC. Confira o nome do
endpoint na API.

### Lentidão / `429`

A lib respeita o `Retry-After` em `429` e tem backoff. Para cargas pesadas, ajuste
`rate_limit_sleep` e `page_size` no bloco `api`/endpoint. Veja
[Configuração](configuration.md).
