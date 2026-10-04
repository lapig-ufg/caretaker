# Caretaker

CLI que faz o deploy e a atualização de aplicações em **Docker Swarm** a partir de arquivos compose.

## O que faz

Dado um `app_name` e um `app_type`:

1. Procura o arquivo `/services/<app_name>/<app_type>.compose.yml`.
2. Se a stack já existe, remove as imagens locais usadas pelos serviços e baixa a versão mais recente (`pull`).
3. Com `--force`, remove a stack (`docker stack rm`) e espera 15 segundos.
4. Faz o deploy com `docker stack deploy`.

A stack é criada com o nome `<app_type>_<app_name>`.

## Requisitos

- Linux, rodando em um nó **manager** do Docker Swarm
- Docker CLI instalado e acesso ao socket do Docker
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Instalação

```bash
git clone <url-do-repositorio>
cd caretaker
uv sync
```

## Configuração

Opcional. Crie um arquivo `.env` na raiz do projeto:

| Variável        | Padrão                        | Descrição                  |
| --------------- | ----------------------------- | -------------------------- |
| `DOCKER_SOCKET` | `unix:///var/run/docker.sock` | Endereço do daemon Docker. |

## Estrutura dos serviços

Cada aplicação tem uma pasta em `/services` com um compose por tipo:

```
/services/
└── minha-app/
    ├── web.compose.yml
    └── worker.compose.yml
```

## Uso

```bash
uv run typer src/main.py run <app_name> <app_type> [--force]
```

| Argumento / opção | Descrição                                  |
| ----------------- | ------------------------------------------ |
| `app_name`        | Nome da pasta da aplicação em `/services`. |
| `app_type`        | Tipo da aplicação (prefixo do compose).    |
| `--force`, `-f`   | Remove a stack antes de fazer o deploy.    |

> As opções `--verbose`, `--title`, `--commit` e `--repo` são aceitas, mas ainda não têm efeito.

### Exemplos

```bash
# Atualiza a stack web_minha-app usando /services/minha-app/web.compose.yml
uv run typer src/main.py run minha-app web

# Recria a stack do zero
uv run typer src/main.py run minha-app worker --force
```

## Código de saída

| Código | Significado                                                           |
| ------ | --------------------------------------------------------------------- |
| `0`    | Deploy feito com sucesso.                                             |
| `1`    | Falha (pasta ou compose não encontrado, erro no Docker ou no deploy). |

Isso permite usar o comando diretamente em pipelines de CI/CD.
