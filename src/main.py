import os
import time
import subprocess

from typer import Typer, Exit, Argument, Option
from docker import DockerClient
from docker.errors import ImageNotFound
from pathlib import Path


import dotenv
dotenv.load_dotenv()


REGISTRY = os.environ.get("REGISTRY", 'lapig')
DOCKER_SOCKET = os.environ.get("DOCKER_SOCKET", 'unix:///var/run/docker.sock')


class ContextService:
    
    def __init__(self, app_name: str, app_type: str):
        self.client: DockerClient = DockerClient(base_url=DOCKER_SOCKET)

        self.registry: str = REGISTRY

        self.app_name: str = app_name
        self.app_type: str = app_type

        self.stack_name: str = f"{app_type}_{app_name}"

        self.path: Path = Path(f'/services/{self.app_name}')

        self.__compose_sufix: str = '.compose.yml'

    def __enter__(self):
        if not self.path.is_dir():
            raise Exception(f'A pasta {self.app_name} não existe')
        
        _compose_file = self.path / f'{self.app_type}{self.__compose_sufix}'
        
        if not _compose_file.is_file():
            raise Exception(f'O arquivo compose não esta definido para tipo {self.app_type} para o projeto {self.app_name}')
        
        self.compose_file = _compose_file

        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

        if exc_type is not None:
            print(f"Exceção capturada: {exc_type.__name__}", flush=True)
            print(f"Mensagem: {exc_val}", flush=True)

        return False
    

def get_services_status(ctx: ContextService) -> list:
    """
    Retorna uma lista de serviços da stack com seus respectivos status.

    A função busca todos os serviços vinculados à stack definida no contexto.
    Para cada serviço, verifica a quantidade de tarefas (tasks) em execução 
    em relação ao total de tarefas planejadas, retornando essas informações 
    de forma consolidada.

    Args:
        ctx (ContextService): Objeto de contexto contendo o cliente Docker (ctx.client) 
                              e o nome da stack (ctx.stack_name).

    Returns:
        list: Lista de dicionários, onde cada item representa um serviço e contém:
              - 'name' (str): Nome do serviço.
              - 'running' (bool): True se houver pelo menos uma task com status 'running'.
              - 'tasks' (str): Proporção de tasks ativas vs total (ex: "2/3" ou "1/1").
    """
    try:
        # 1. BUSCA DE SERVIÇOS:
        # Consulta a API do Docker para listar todos os serviços pertencentes 
        # à stack especificada, filtrando pela label padrão do Docker Swarm.
        services = ctx.client.services.list(filters={'label': f'com.docker.stack.namespace={ctx.stack_name}'})

        status_list = []

        # 2. ITERAÇÃO E MAPEAMENTO DE STATUS:
        # Varre cada serviço retornado pela API para inspecionar suas tarefas.
        for service in services:
            name = service.name
            
            # 3. BUSCA DAS TAREFAS (TASKS) DO SERVIÇO:
            # Lista todas as instâncias (containers) atreladas especificamente a este serviço.
            tasks = ctx.client.tasks.list(filters={'service': name})

            # 4. CONTAGEM DE TASKS:
            # Soma quantas tarefas estão com o estado exato de 'running' e o total.
            running = sum(1 for task in tasks if task.attrs['Status']['State'] == 'running')
            total = len(tasks)

            # 5. CONSOLIDAÇÃO DOS DADOS:
            # Adiciona o status formatado na lista de resultados.
            status_list.append({
                'name': name,
                'running': running > 0,
                'tasks': f"{running}/{total}"
            })

        # Retorna a lista completa com o status de todos os serviços.
        return status_list
    
    except Exception as e:
        # 6. TRATAMENTO DE ERRO:
        # Captura e exibe falhas na comunicação com a API do Docker, retornando uma lista vazia.
        print(f"Erro ao listar serviços: {e}", flush=True)
        return []


def apply_stack(ctx: ContextService, force: bool = False) -> bool:
    """
    Aplica ou atualiza uma stack do Docker Swarm.

    A função verifica se a stack já existe. Se existir, identifica as imagens 
    usadas pelos serviços, remove as imagens locais e faz o pull das versões mais 
    recentes. Opcionalmente, pode remover a stack inteira antes de recriá-la. 
    Por fim, executa o deploy usando o arquivo docker-compose.

    Args:
        ctx (ContextService): Objeto de contexto contendo o cliente Docker (ctx.client), 
                              o nome da stack (ctx.stack_name) e o caminho para o 
                              arquivo do compose (ctx.compose_file).
        force (bool, optional): Se True, remove a stack existente (docker stack rm) 
                                e aguarda 15 segundos antes de fazer o deploy 
                                novamente. Padrão é False.

    Returns:
        bool: True se a stack foi aplicada com sucesso, False em caso de falha.
    """
    try:
        # 1. BUSCA DE SERVIÇOS:
        # Consulta a API do Docker para listar todos os serviços que pertencem 
        # a esta stack específica, usando a label padrão do Docker Swarm.
        services = ctx.client.services.list(filters={'label': f'com.docker.stack.namespace={ctx.stack_name}'})

        if services:
            unique_images = set()

            # 2. MAPEAMENTO DE IMAGENS:
            # Varre os serviços encontrados para descobrir quais imagens eles usam.
            for service in services:
                imagem = service.attrs['Spec']['TaskTemplate']['ContainerSpec']['Image'].split('@')[0]
                unique_images.add(imagem)

            # 3. RENOVAÇÃO DAS IMAGENS LOCAIS:
            # Remove a versão local da imagem (para limpar o cache) e baixa 
            # (pull) a versão mais recente diretamente do registry.
            for image in unique_images:
                try:
                    ctx.client.images.remove(image, force=True)
                    print(f"Imagem removida: {image}", flush=True)
                except ImageNotFound:
                    print(f"Imagem não encontrada: {image}", flush=True)

                # Separa o nome da imagem e a tag para fazer o pull corretamente via API.
                if ':' in image:
                    imagem, tag = image.rsplit(':', 1)
                    print(f"Pulling: {imagem}:{tag}", flush=True)
                    ctx.client.images.pull(imagem, tag=tag)
                else:
                    print(f"Pulling: {image}", flush=True)
                    ctx.client.images.pull(image)

        # 4. REMOÇÃO FORÇADA (OPCIONAL):
        # Se force=True, destrói a stack atual completamente via CLI.
        # O sleep de 15 segundos garante que redes e volumes sejam desalocados 
        # pelo Swarm antes de tentarmos recriar a stack.
        if force:
            result_rm = subprocess.run(
                ["docker", "stack", "rm", ctx.stack_name],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result_rm.stdout:
                print(f"Stack removida: {result_rm.stdout}", flush=True)
            if result_rm.stderr:
                print(f"Aviso na remoção: {result_rm.stderr}", flush=True)

            time.sleep(15)

        print(f"Aplicando stack: {ctx.stack_name}", flush=True)

        # 5. DEPLOY DA STACK:
        # Executa o comando padrão do Swarm para aplicar o arquivo docker-compose.
        # Usa subprocess pois a API Python do Docker não possui um método simples 
        # e direto para 'stack deploy'.
        result = subprocess.run(
            ["docker", "stack", "deploy", "-c", str(ctx.compose_file), ctx.stack_name],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            print(f"✓ Stack '{ctx.stack_name}' aplicada com sucesso", flush=True)
            if result.stdout:
                print(f"Output: {result.stdout}", flush=True)
            return True

        print(f"Erro ao aplicar stack: {result.stderr}", flush=True)
        if result.stdout:
            print(f"Output: {result.stdout}", flush=True)
        return False

    except Exception as e:
        print(f"Erro: {e}", flush=True)
        return False


app = Typer()

@app.command()
def process(
    app_name: str = Argument(..., help="Nome da aplicação (ex: my-app)"),
    app_type: str = Argument(..., help="Tipo da aplicação"),
    force: bool = Option(False, "--force", "-f", help="Força remoção da stack antes do deploy"),
    verbose: bool = Option(False, "--verbose", "-v", help="Mostra logs no console durante a execução"),
    title: str = Option(None, "--title", help="Título customizado para o relatório"),
    commit: str = Option(None, "--commit", help="Hash do commit para gerar link do GitHub"),
    repo: str = Option(None, "--repo", help="URL do repositório GitHub (ex: owner/repo ou https://github.com/owner/repo)")
):
    """
    Faz deploy/atualização de uma aplicação Docker Stack.

    Processa o deploy de uma aplicação fazendo:
    - Atualização de imagens Docker
    - Remoção de imagens antigas
    - Deploy da stack usando docker-compose
    - Logging de todas as operações

    Exemplos:

    ```
    # Deploy com tag latest (padrão)
    python main.py process minha-app web

    # Deploy com tag específica
    python main.py process minha-app api --tag v1.2.3

    # Deploy usando forma curta
    python main.py process minha-app worker -t production
    ```
    """
    success = False

    try:
        ctx = ContextService(app_name=app_name, app_type=app_type)

        with ctx:
            success = apply_stack(ctx, force=force)
    except Exception as e:
        error_msg = str(e)
        print(error_msg, flush=True)

    if not success:
        raise Exit(code=1)
        