# AeroMonitor — OpenSky, Kafka e Python

Trabalho de Sistemas Orientados a Eventos. Monitora aeronaves em uma região configurável,
com foco inicial na Grande Vitória. Python coleta posições da OpenSky, publica no Kafka,
detecta três situações simples e uma derivada, e registra alertas em SQLite e no terminal.

## Requisitos

- Docker.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) para desenvolvimento local.
- Python 3.12: o uv pode instalar com `uv python install 3.12`.
- Internet para baixar dependências/imagens e consultar a API.

## Executar tudo no Docker

Na raiz do projeto, em PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
docker compose logs -f producer processor alerts
```

Em Linux/macOS, use `cp .env.example .env`. Não sobrescreva um `.env` já configurado.
O Compose inicia Kafka em KRaft (sem ZooKeeper), cria os tópicos e inicia os três serviços.
Na primeira execução, o download e a inicialização podem levar alguns minutos.
Os alertas aparecem em JSON nos logs de `alerts` e no banco `/app/data/alerts.db`,
persistido no volume `alerts-data`. Não há dashboard nesta versão.

```powershell
docker compose stop
docker compose start
```

Para remover containers preservando os dados: `docker compose down`.
**`docker compose down -v` também apaga os volumes de Kafka e SQLite.**

## Escolher cidade/aeroporto

Edite `.env`:

```dotenv
REGION=vitoria
RADIUS_KM=50
```

| REGION | Centro de referência |
| --- | --- |
| `vitoria` | Aeroporto de Vitória — SBVT |
| `guarulhos` | Aeroporto de Guarulhos — SBGR |
| `galeao` | Aeroporto do Galeão — SBGL |
| `custom` | Coordenadas fornecidas por você |

Exemplo de região personalizada:

```dotenv
REGION=custom
CUSTOM_NAME=Vila Velha
CUSTOM_LATITUDE=-20.3297
CUSTOM_LONGITUDE=-40.2925
RADIUS_KM=40
```

O círculo não representa um limite municipal oficial. Para inferir aproximação aeroportuária,
use o aeroporto como centro. As coordenadas dos presets são aproximadas.
Depois de mudar `.env`, recrie os serviços; `restart` sozinho não atualiza o ambiente:

```powershell
docker compose up -d --force-recreate producer processor alerts
```

Uma região é coletada por vez. A identificação de cada evento inclui região, centro e raio para
separar os históricos. Alertas de regiões anteriores permanecem no banco.

## OpenSky: acesso e frequência

O padrão usa acesso anônimo a cada **240 segundos**: cerca de 360 consultas/dia, com margem
nos 400 créditos/dia documentados para uma área pequena. Outros clientes no mesmo IP podem
compartilhar essa cota; áreas maiores custam mais créditos.

Para coleta mais frequente, crie uma conta e um API Client na OpenSky e preencha `.env`:

```dotenv
OPENSKY_CLIENT_ID=seu-client-id
OPENSKY_CLIENT_SECRET=seu-client-secret
POLL_INTERVAL_SECONDS=30
```

O cliente usa OAuth2 e renova o token. A conta padrão tem 4.000 créditos/dia; uma área pequena
a cada 30 s consome aproximadamente 2.880 créditos/dia, antes de testes e retries.
Não use login/senha do site como credenciais do cliente. Nunca publique o `.env`: ele é ignorado
pelo Git e excluído da imagem Docker. Consulte os limites na
[documentação oficial](https://openskynetwork.github.io/opensky-api/rest.html).

O produtor respeita a espera de HTTP 429 e aplica espera crescente em falhas transitórias.
Posições fora do círculo, inválidas ou com mais de 90 segundos são filtradas. A ausência de
uma aeronave não significa pouso ou saída da região.

## Desenvolvimento com uv

```powershell
uv sync --locked
uv run aeromonitor config
uv run aeromonitor probe
```

`config` mostra região e bounding box sem credenciais. `probe` faz **uma consulta real** sem Kafka.
Uma lista vazia pode indicar pouco movimento ou falta de cobertura.

Para usar Python local e apenas Kafka no Docker:

```powershell
docker compose up -d kafka kafka-init
```

Em três terminais separados, na raiz do projeto:

```powershell
uv run aeromonitor producer
uv run aeromonitor processor
uv run aeromonitor alerts
```

Use `KAFKA_BOOTSTRAP_SERVERS=localhost:9092` no `.env` para execução local.
No Compose, o endereço interno é configurado automaticamente. Não execute os mesmos serviços
simultaneamente no host e em containers. Para parar os serviços já ativos no Compose:
`docker compose stop producer processor alerts`.
Localmente, o banco fica em `data/alerts.db`. Ctrl+C encerra os serviços.

## Regras implementadas

| Tipo | Condição padrão | Tópico de saída |
| --- | --- | --- |
| `proximity` | Em voo e até 15 km do centro | `aircraft.alerts` |
| `low_altitude` | Em voo e altitude barométrica abaixo de 1.000 m | `aircraft.alerts` |
| `vertical_movement` | Em voo e módulo da taxa vertical ≥ 8 m/s | `aircraft.alerts` |
| `possible_approach` | Três posições consecutivas se aproximando e descendo; última até 15 km | `aircraft.derived` |

A aproximação exige redução de pelo menos 0,2 km e 20 m a cada passo, sem lacunas maiores que
300 s e com todas as posições em voo. Há cooldown de 600 s por regra/aeronave/região.
Um alerta persistente pode reaparecer depois desse intervalo. Os parâmetros estão em `.env.example`.

Altitude barométrica **não é altura sobre o terreno**. Os limites são demonstrativos e precisam
ser adaptados, especialmente em aeroportos elevados. Aproximação é uma inferência, não confirmação
de destino/pouso. A OpenSky não fornece horários comerciais, atrasos ou cancelamentos.

## Qualidade e testes

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
docker compose config --quiet
```

Para formatar: `uv run ruff format .`. A CI executa esses checks de código e sintaxe do Compose.
Os testes são offline: normalização, regras temporais, isolamento por região, OAuth2, rate limit
e deduplicação SQLite. Não precisam de conta nem gastam créditos da API.

## Diagnóstico

- **Docker não conecta:** inicie o Docker Desktop e aguarde o engine Linux ficar pronto.
- **Sem alertas:** confira posições válidas nos logs do produtor e os limites das regras.
- **401/403:** revise acesso e credenciais do API Client.
- **429:** aguarde a liberação e aumente o intervalo de coleta.
- **Kafka indisponível:** consulte `docker compose logs kafka kafka-init`.
- **Evento inválido:** o consumidor falha sem confirmar o offset; corrija a origem antes de retomar.

## Estrutura

```text
src/aeromonitor/        API, configuração, contratos, Kafka, regras, SQLite e CLI
tests/                  testes offline
docs/ARCHITECTURE.md     arquitetura e limitações
compose.yaml            Kafka, criação de tópicos e três serviços
Dockerfile              imagem Python com uv
pyproject.toml          dependências, comando e Ruff
uv.lock                 versões resolvidas
```

Leia [a arquitetura](docs/ARCHITECTURE.md) para os contratos, garantias e limitações.
Fonte dos dados: [The OpenSky Network](https://opensky-network.org/).
