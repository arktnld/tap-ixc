# CLI

Instalar a lib cria o comando `tap-ixc`. Todos os comandos leem `config/clients.yml`
e o banco de monitoramento (`ETL_MONITOR_DSN`).

```bash
tap-ixc --help
```

## `check` — valida credenciais e monitoramento

```bash
tap-ixc check minha-empresa
```

Testa **as duas pontas** antes de você rodar de verdade:

```text
  ✓ API de 'minha-empresa' ok.
  ✓ Monitoramento ok (schema 'etl').
```

Sai com código **`1`** se a API **ou** o monitoramento falharem, apontando o que fazer
(ex: rodar `docs/schema.sql` se faltar tabela).

## `discover` — lista streams e modos de sync

```bash
tap-ixc discover minha-empresa
```

```text
Streams disponíveis para 'minha-empresa':

  clientes             [incremental] → todos os campos
  contratos            [incremental] → todos os campos
  titulos              [incremental] → todos os campos
```

## `run` — sincroniza

```bash
tap-ixc run minha-empresa                       # todos os endpoints do YAML
tap-ixc run minha-empresa --stream clientes      # só um
tap-ixc run minha-empresa --stream clientes --stream titulos
tap-ixc run minha-empresa --from-checkpoint      # retoma do último checkpoint
```

| Flag | Descrição |
|---|---|
| `--stream <nome>` | Sincroniza só o(s) stream(s) indicado(s). Repetível. |
| `--from-checkpoint` | Pula stages já concluídos (retoma uma carga interrompida). |

Saída por stream:

```text
  ✓ clientes: 12435 registros
  ✗ titulos: 0 registros
      erro: connection failed: ...
```

!!! important "Exit code para Airflow/cron"
    `run` sai com código **`!= 0`** se **qualquer** stream falhar — mesmo que outros
    tenham sucesso. Assim Airflow/cron detectam a falha e re-tentam. Veja
    [Deploy](deployment.md).

## `list` — clientes configurados

```bash
tap-ixc list
```

```text
  minha-empresa        [ixc] → clientes, contratos, titulos
```

Funciona mesmo que credenciais de outros clientes não estejam setadas.

## `status` — últimos runs

```bash
tap-ixc status                       # últimos 20 (todos os clientes)
tap-ixc status --client minha-empresa
```

```text
CLIENT          STREAM       STATUS    STAGE    STARTED                    DUR   RECORDS
----------------------------------------------------------------------------------------
minha-empresa   clientes     SUCCESS   VERIFY   2026-05-29 10:46:16-03    14.6s  12435
```

## Mensagens de erro

Todos os comandos mostram erros **limpos** (sem traceback) e acionáveis:

| Situação | Mensagem |
|---|---|
| `clients.yml` ausente | `Crie a partir do exemplo: cp config/clients.yml.example config/clients.yml` |
| cliente não existe | `Cliente 'x' não encontrado. Disponíveis: [...]` |
| `${VAR}` não definida | `variável de ambiente 'X' não definida (campo 'api.token')` |
| YAML malformado | `clients.yml com sintaxe YAML inválida` |
| monitor fora | `Falha ao conectar no Postgres de monitoramento (ETL_MONITOR_DSN)` |
| tabelas do monitor ausentes | `Crie o schema: psql "$ETL_MONITOR_DSN" -f docs/schema.sql` |
