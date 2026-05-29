# Política de Segurança

## Reportar uma vulnerabilidade

Não abra issue pública para vulnerabilidades. Use os
[Security Advisories](https://github.com/arktnld/tap-ixc/security/advisories/new)
do GitHub para reportar de forma privada.

## Credenciais

- `config/clients.yml` **não** é versionado (está no `.gitignore`) — só o `.example`.
- `token`, `postgres_dsn` e `base_url` aceitam `${VAR}` (variável de ambiente);
  prefira essa forma para secrets de produção, evitando texto puro em disco.
- Identificadores vindos de config (tabela/schema/pk) são validados antes de irem
  para SQL, mitigando injeção.

Nunca commite tokens, DSNs ou URLs com credenciais.
