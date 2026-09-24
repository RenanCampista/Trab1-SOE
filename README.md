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
docker compose logs -f producer processor processor-2 alerts
```

Em Linux/macOS, use `cp .env.example .env`. Não sobrescreva um `.env` já configurado.
O Compose inicia Kafka em KRaft (sem ZooKeeper), com **2 brokers**, cria os quatro tópicos com
**3 partições e replication factor 2** e inicia os serviços. O processador possui duas instâncias
no mesmo consumer group, permitindo observar a distribuição das partições entre consumers.
Na primeira execução, o download e a inicialização podem levar alguns minutos.
Os alertas aparecem em JSON nos logs de `alerts` e no banco `/app/data/alerts.db`,
persistido no volume `alerts-data`.

**Interface visual:** abra [http://localhost:8501](http://localhost:8501).
O dashboard mostra mapa, aeronaves recentes, alertas filtráveis e a última coleta bem-sucedida.
Atualiza a cada cinco segundos sem fazer consultas adicionais à OpenSky. Marcadores laranja
indicam uma possível aproximação detectada nos últimos cinco minutos. O mapa-base usa CARTO e
requer internet; os detalhes também estão disponíveis na tabela de posições.

Os filtros de aeronave e tipo afetam a visualização, sem alterar a coleta. A lista exibe até
1.000 alertas por período. Posições com mais de `MAX_POSITION_AGE_SECONDS` saem do mapa:
com coleta anônima a cada 240 s e validade de 90 s, haverá intervalos sem marcadores recentes.
Use OAuth2 e coleta a cada 30 s para acompanhar movimentos com maior continuidade.

O serviço `visualization` consome os quatro tópicos com grupo independente e grava
`/app/data/dashboard.db` no volume `dashboard-data`. O `dashboard` lê esse banco.
Em projeto já existente, execute `docker compose up --build -d` para criar também o tópico
`aircraft.collections` e os novos serviços. Os bancos anteriores são preservados.

```powershell
docker compose stop
docker compose start
```

Para remover containers preservando os dados: `docker compose down`.
**`docker compose down -v` também apaga os volumes de Kafka e SQLite.**

### Kafka distribuído desta versão

A topologia didática desta versão foi ampliada para demonstrar conceitos da disciplina:

- **2 brokers** (`kafka` e `kafka-2`);
- **3 partições por tópico**;
- **replication factor 2**;
- producer com `acks=all` e idempotência;
- **2 instâncias do processador** no mesmo `group-id`;
- chave Kafka `region_id:icao24`, mantendo eventos da mesma aeronave na mesma partição.

O broker `kafka` também exerce o papel de controller KRaft. Isso permite demonstrar replicação
de dados entre dois brokers, mas **não fornece alta disponibilidade do plano de controle**: uma
topologia KRaft tolerante à falha de controller normalmente exige um quorum ímpar, por exemplo
três controllers. Para a apresentação, a configuração prioriza simplicidade e demonstração dos
conceitos de broker, partição, replicação, key e consumer group.

Para inspecionar a distribuição das partições:

```powershell
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:19092 --describe
```

Para observar os dois processadores no mesmo grupo:

```powershell
docker compose logs -f processor processor-2
```

> Ao migrar de uma versão antiga do projeto, os novos volumes `kafka-data-1` e `kafka-data-2`
> criam um cluster Kafka limpo. Os volumes SQLite (`alerts-data`, `dashboard-data` e
> `control-data`) continuam preservados.

## Escolher cidade/aeroporto

Na barra lateral do painel, escolha **Cidade / aeroporto** e clique em **Monitorar cidade**:

- Vitória / SBVT
- Guarulhos / SBGR
- Rio de Janeiro / SBGL (Galeão)

O mapa e as tabelas passam a mostrar a cidade selecionada. O produtor aplica a escolha no
**próximo ciclo**, sem reiniciar containers: até o intervalo configurado (240 s no padrão),
ou após a espera imposta pela API em caso de limite. Uma consulta já iniciada termina com a
região anterior. A troca não faz consultas extras nem contorna a cota da OpenSky.

A seleção é global para todos os usuários, persiste após reinícios e tem prioridade sobre
`REGION` no `.env`. Outras sessões acompanham a mudança na próxima atualização do painel.
O horário da última coleta OK indica quando a região foi consultada com sucesso; um produtor
desligado não começa a coletar apenas porque a seleção mudou.

O `.env` define o padrão inicial (antes da primeira seleção) e o raio:

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
docker compose up -d --force-recreate producer processor alerts visualization dashboard
```

Uma região é coletada por vez. A identificação de cada evento inclui região, centro e raio para
separar os históricos. Alertas de regiões anteriores permanecem no banco.
Com `REGION=custom`, a região personalizada também aparece no seletor; selecione-a para ativá-la.
O produtor e o dashboard compartilham `CONTROL_DATABASE_PATH` (local: `data/control.db`;
Docker: `/app/control/control.db`, volume `control-data`). Não é necessário alterar esse caminho
para escolher cidades. Em execução local, inicie ambos na raiz e com o mesmo `.env`.

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

## Colocar online para a apresentação

A aplicação continua usando a rede privada do Docker para Kafka; **não exponha as portas Kafka
na Internet**. Somente o dashboard precisa ficar acessível externamente. Em uma VM/VPS Linux:

1. Instale Docker e Docker Compose.
2. Copie/clonar o projeto para o servidor.
3. Crie `.env` a partir de `.env.example` e configure as credenciais OpenSky, se usadas.
4. Defina:

```dotenv
DASHBOARD_BIND_ADDRESS=0.0.0.0
```

5. Suba os containers:

```bash
docker compose up --build -d
```

6. No firewall da VM, libere **apenas TCP 8501** para a demonstração. O painel ficará em
`http://IP-DO-SERVIDOR:8501`. Para uso além de uma apresentação temporária, prefira colocar
Caddy/Nginx com HTTPS na frente do Streamlit em vez de expor a porta diretamente.

Os brokers permanecem publicados somente em `127.0.0.1` no host e são acessados pelos demais
containers pelos nomes `kafka:19092` e `kafka-2:19092`. Portanto, não é necessário alterar
`advertised.listeners` para colocar apenas o dashboard online.

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
docker compose up -d kafka kafka-2 kafka-init
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
`docker compose stop producer processor processor-2 alerts`.
Localmente, o banco fica em `data/alerts.db`. Ctrl+C encerra os serviços.

Para visualizar a execução local, abra mais dois terminais na raiz:

```powershell
uv run aeromonitor visualization
uv run streamlit run src/aeromonitor/dashboard.py --browser.gatherUsageStats=false
```

Ambos devem usar o mesmo `DATABASE_PATH` do `.env` (padrão: `data/alerts.db`). SQLite em modo WAL
permite leitura do painel enquanto os consumidores gravam. Pare também os serviços `visualization`
e `dashboard` no Docker antes de iniciar seus equivalentes locais.

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
- **Kafka indisponível:** consulte `docker compose logs kafka kafka-2 kafka-init`.
- **Evento inválido:** o consumidor falha sem confirmar o offset; corrija a origem antes de retomar.

## Estrutura

```text
src/aeromonitor/        API, configuração, contratos, Kafka, regras, SQLite e CLI
tests/                  testes offline
docs/ARCHITECTURE.md     arquitetura e limitações
compose.yaml            2 brokers Kafka, tópicos particionados/replicados e serviços
Dockerfile              imagem Python com uv
pyproject.toml          dependências, comando e Ruff
uv.lock                 versões resolvidas
```

Leia [a arquitetura](docs/ARCHITECTURE.md) para os contratos, garantias e limitações.
Fonte dos dados: [The OpenSky Network](https://opensky-network.org/).
