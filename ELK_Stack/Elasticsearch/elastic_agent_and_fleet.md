# Elastic Agent и Fleet: Централизованное управление сбором данных

**Актуально для:** Elastic Agent / Fleet 9.5.x (текущий минор 9.5.5, октябрь 2026) / 8.19 LTS (8.19.23)

> Руководство по Elastic Agent, Fleet Server и централизованному управлению политиками сбора данных. Рассматриваются архитектура, режимы развертывания, интеграции, мониторинг, обновление агентов и миграция с Beats.
>
> Связанные темы: Filebeat — [Filebeat Overview](../filebeat_overview.md); Kibana администрирование — [Kibana Overview](../Kibana/kibana_overview.md); безопасность — [Security Advanced](./elasticsearch_security_advanced.md); [Beats Family](./beats_family.md); [ELK стек: Обзор](../elk_stack_overview.md).

## Определения

* **Elastic Agent** — единый агент сбора данных, заменяющий отдельные Beats. Собирает логи, метрики и обеспечивает защиту конечных точек (Elastic Defend). Управляется централизованно через Fleet или автономно через конфигурационный файл. Внутри себя Elastic Agent выступает супервизором: при минимальной конфигурации он разворачивает экземпляры Filebeat (логи) и Metricbeat (метрики) и следит за их работоспособностью.
* **Fleet** — веб-интерфейс в Kibana для централизованного управления Elastic Agent. Обеспечивает дистрибуцию политик, обновлений и интеграций на тысячи хостов. Fleet имеет API-first дизайн: всё, что делается в UI, можно сделать через API.
* **Fleet Server** — механизм связи Elastic Agent с Fleet. Это Elastic Agent, зачисленный (enrolled) в специальную Fleet Server policy, который работает в особом режиме: мониторит служебные индексы Fleet в Elasticsearch, забирает новые политики и доставляет их всем агентам, зачисленным в политику. Может быть запущен из любого x64-артефакта Elastic Agent.
* **Agent Policy** — набор интеграций и настроек, назначаемый группе агентов. Определяет, какие данные собираются, куда отправляются и как обновляются агенты.
* **Integration** (интеграционный пакет) — предконфигурированный пакет для конкретного источника данных (nginx, mysql, system, kubernetes), включающий inputs, dashboards, ingest pipelines и alert rules.
* **Enrollment Token** — токен зачисления агента в Fleet, генерируется в Kibana при создании политики (Agents → Add agent). Один токен можно использовать для нескольких агентов.
* **Service Token** — токен, которым Fleet Server записывает данные в Elasticsearch. Генерируется в Kibana (Fleet → Settings / инструкции при добавлении Fleet Server).
* **Standalone Mode** — Elastic Agent работает без Fleet Server, управляется локальным конфигурационным файлом `elastic-agent.yml`.
* **Fleet-managed Mode** — Elastic Agent подключается к Fleet Server, получает конфигурацию из Agent Policy в Kibana.
* **Namespace** — логическое разделение политик и данных (prod, staging, dev). Мониторинг агентов всегда пишется в namespace `default` политики.

## Архитектура

### Компоненты Fleet

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Kibana    │────▶│ Fleet Server │◀────│  Agents     │
│  (UI/API)   │     │ (Control     │     │ (Data Plane)│
└─────────────┘     │  Plane)      │     └─────────────┘
                     └──────────────┘
                            │
                     ┌──────────────┐
                     │Elasticsearch │
                     │  (Fleet      │
                     │  indices)    │
                     └──────────────┘
```

### Как это работает

1. **Создание политики.** При создании Agent Policy в Fleet UI политика сохраняется в служебные индексы Fleet в Elasticsearch.
2. **Зачисление (enrollment).** Агент отправляет запрос Fleet Server с enrollment token для аутентификации и получает назначение в политику.
3. **Check-in.** После зачисления Elastic Agent регулярно инициирует check-in к Fleet Server по HTTP long-polling. Fleet Server доставляет агенту актуальную конфигурацию политики.
4. **Сбор данных.** Агент запускает inputs (Filebeat/Metricbeat-компоненты) и отправляет данные напрямую в configured output (Elasticsearch, Logstash или Kafka) — данные не проходят через Fleet Server.
5. **Отказоустойчивость.** При потере связи с Fleet Server агенты продолжают отправлять данные в кластер, но не получают обновлений политики и не могут быть переконфигурированы централизованно.

### Типовая инфраструктура

```
Kibana (UI) ←→ Fleet Server (standalone host)
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
    Agent(1)     Agent(2)    Agent(N)
    ├─ System    ├─ System    ├─ Nginx
    └─ Endpoint  └─ MySQL     └─ Kafka
```

## Установка и настройка

### Fleet Server

Fleet Server — специальный режим Elastic Agent, зачисленного в Fleet Server policy. Политика конфигурирует агент на запуск процесса Fleet Server.

**Порядок установки (self-managed):**

1. В Fleet (Agent policies) создайте политику для Fleet Server: включите «Collect system logs and metrics» (рекомендуется), добавьте интеграцию **Fleet Server** (Add integration → Fleet Server → Add Fleet Server).
2. Выберите режим **Production** — полностью защищённый режим, где TLS-сертификаты обеспечивают безопасную связь Fleet Server с Elasticsearch.
3. Укажите Fleet Server hosts (например, `https://192.0.2.1:8220`) и создайте service token для записи в Elasticsearch.
4. Установите Elastic Agent с флагами bootstrap:

```bash
# Установка Fleet Server через elastic-agent install
sudo elastic-agent install \
  --url=https://fleet-server:8220 \
  --certificate-authorities=/path/to/ca.crt \
  --fleet-server-es=https://elasticsearch:9200 \
  --fleet-server-service-token=<token> \
  --fleet-server-policy=fleet-server-policy
```

Параметры (верифицированы в Elastic Agent command reference):

| Флаг | Назначение |
|------|-----------|
| `--fleet-server-es <url>` | Запустить процесс Fleet Server и подключить его к указанному Elasticsearch |
| `--fleet-server-service-token <token>` | Service token для связи с Elasticsearch (взаимоисключающ с `--fleet-server-service-token-path`) |
| `--fleet-server-policy <id>` | Использовать конкретную политику для self-managed Fleet Server; по умолчанию — `fleet-server-policy` |
| `--fleet-server-cert` / `--fleet-server-cert-key` | Сертификат и ключ для HTTPS-эндпоинта Fleet Server |
| `--fleet-server-host` / `--fleet-server-port` | Хост/порт биндинга Fleet Server (переопределяют политику) |
| `--fleet-server-es-ca` / `--fleet-server-es-ca-trusted-fingerprint` | CA или fingerprint для проверки сертификата Elasticsearch |
| `--certificate-authorities` | CA для связи агентов с Fleet Server |

При bootstrap с `--fleet-server-es` Elastic Agent сам генерирует CA и сертификаты для запущенного Fleet Server. Команда `install` размещает файлы по стандартным путям, запускает сервис и выполняет `enroll`.

**Требования и рекомендации:**
- Выделенный хост или pod (не совмещать с тяжелыми workloads) — рекомендация, а не обязательное требование
- Доступ к Elasticsearch (запись состояния агентов и политик) с service token
- Порт **8220** (default для self-managed; 443/9243 для Elastic Cloud) — открыт для ingress и egress
- TLS в production (режим Production)
- Kibana нужен доступ в интернет для загрузки интеграционных пакетов из Elastic Package Registry

### Fleet-managed Agent

```bash
# Установка как сервиса и зачисление в Fleet
sudo elastic-agent install \
  --url=https://fleet-server:8220 \
  --certificate-authorities=/path/to/ca.crt \
  --enrollment-token=<token>
```

* На одном хосте можно установить только один Elastic Agent.
* Агент устанавливается как автостартующий сервис и перезапускается при перезагрузке хоста.
* `--tag` — comma-разделённый список тегов для фильтрации агентов; `--insecure` — для self-signed сертификатов (только non-production); `--base-path` — кастомный путь установки.
* Если статус зависает на «Enrolling» — проверьте, что процесс `elastic-agent` запущен.

### Standalone Agent

Минимальная конфигурация standalone-агента — это output (куда отправлять) и хотя бы один input (что собирать):

```yaml
# elastic-agent.yml
outputs:
  default:
    type: elasticsearch
    hosts: ["https://elasticsearch:9200"]
    api_key: "API_KEY_ID:API_KEY_SECRET"   # либо username/password

inputs:
  - type: system/metrics
    id: unique-system-metrics-id
    data_stream.namespace: default
    use_output: default
    streams:
      - metricsets:
          - cpu
        data_stream.dataset: system.cpu
      - metricsets:
          - memory
        data_stream.dataset: system.memory
      - metricsets:
          - network
        data_stream.dataset: system.network
```

```yaml
# Сбор логов (filestream)
inputs:
  - type: filestream
    id: your-input-id
    streams:
      - id: your-filestream-stream-id
        data_stream:
          dataset: generic
        paths:
          - /var/log/*.log
```

```bash
# Запуск в standalone (флаг -c задаёт конфиг; без него — {path.config}/elastic-agent.yml)
sudo elastic-agent run -c elastic-agent.yml
```

* Inputs можно выносить в отдельные файлы в `{path.config}/inputs.d/` — каждый файл начинается со строки `inputs:` и содержит только inputs; перезагружаются вместе с основной конфигурацией.
* `id` input должен быть уникален; без явного `id` он defaults на тип input — задавайте явно при нескольких inputs одного типа.
* `data_stream.namespace` defaults на `default`, `data_stream.dataset` — на `generic`; `data_stream.type` определяется типом данных (logs/metrics) автоматически.
* Для сбора данных, требующих ingest pipeline или dashboards, необходимо установить assets соответствующей интеграции (см. Install standalone Elastic Agents).

## Agent Policies

### Структура политики

```
Agent Policy "production-servers"
├── Integration: System
│   └── Inputs:
│       ├── System Metrics (CPU, Memory, Network)
│       ├── System Logs (/var/log/syslog)
│       └── System Security (auditd)
├── Integration: Nginx
│   └── Inputs:
│       ├── Nginx Access Logs
│       └── Nginx Error Logs
├── Integration: Endpoint Security
│   └── (Elastic Defend)
└── Output: production-es-cluster
```

### Создание политики через API

Fleet API требует аутентификации (API key или session) и заголовка `kbn-xsrf`. В Kibana Dev Tools Console запросы пишутся с префиксом `kbn:` (например, `GET kbn:/api/fleet/agent_policies`).

```bash
# Создание agent policy
# sys_monitoring=true добавляет system integration в политику
curl --request POST \
  --url 'https://kibana-host:5601/api/fleet/agent_policies?sys_monitoring=true' \
  --header 'Content-Type: application/json' \
  --header 'kbn-xsrf: true' \
  --header 'Authorization: ApiKey <base64key>' \
  --data '{
    "name": "web-servers",
    "description": "Web servers monitoring",
    "namespace": "default",
    "monitoring_enabled": ["logs", "metrics"]
  }'

# Ответ (поле id понадобится для добавления интеграций):
# {
#   "item": {
#     "id": "2b820230-4b54-11ed-b107-4bfe66d759e4",
#     "name": "web-servers",
#     "namespace": "default",
#     "monitoring_enabled": ["logs", "metrics"],
#     "status": "active",
#     "is_managed": false,
#     "revision": 1,
#     "schema_version": "1.0.0"
#   }
# }
```

```bash
# Добавление интеграции (package policy) в политику
curl --request POST \
  --url 'https://kibana-host:5601/api/fleet/package_policies' \
  --header 'Content-Type: application/json' \
  --header 'kbn-xsrf: true' \
  --header 'Authorization: ApiKey <base64key>' \
  --data '{
    "name": "nginx-web",
    "policy_id": "2b820230-4b54-11ed-b107-4bfe66d759e4",
    "package": {
      "name": "nginx",
      "version": "1.5.0"
    },
    "inputs": {
      "nginx-logfile": {
        "streams": {
          "nginx.access": {
            "vars": {
              "paths": ["/var/log/nginx/access.log*"],
              "tags": ["web"]
            }
          },
          "nginx.error": {
            "vars": {
              "tags": ["web"]
            }
          }
        }
      }
    }
  }'
```

Доступные операции: `GET/PUT/DELETE /api/fleet/package_policies/{id}`, `POST /api/fleet/package_policies/_bulk_get`, `POST /api/fleet/package_policies/upgrade` и `/upgrade/dryrun`. Список доступных inputs, streams и vars для интеграции — в Integrations → выберите интеграцию → API reference.

**Списочные эндпоинты** (`GET /api/fleet/agents`, `/api/fleet/agent_policies`, `/api/fleet/package_policies`, `/api/fleet/enrollment_api_keys`) принимают параметр `kuery` с KQL-строкой для фильтрации. Удаление политики: `POST /api/fleet/agent_policies/delete` с телом `{"agentPolicyId": "<id>"}`.

### Возможности политики

* **Custom fields** — поля, добавляемые ко всем данным агентов политики (для идентификации и downstream-манипуляций).
* **Agent monitoring** — сбор логов и метрик самого агента; включён по умолчанию в новых политиках.
* **Auto-upgrade agents** (GA с 9.1, требует уровня подписки) — постепенное автоматическое обновление бинарников агентов до целевой версии (см. раздел «Обновление агентов»).
* **Inactivity timeout** — автоматическое unenroll неактивных агентов и инвалидация их API keys; полезно для ephemeral-сред (Docker, Kubernetes).
* **HTTP monitoring endpoint** — включение эндпоинта `/liveness` для проверки здоровья агента по HTTP-кодам.
* **Смена output** — политика позволяет изменить output (например, при миграции кластера).
* Ограничение: один Fleet поддерживает максимум **1000 agent policies**; при большем числе деградирует производительность UI.

### Preconfiguration (GitOps / IaC)

Политики, пакеты и Fleet Server hosts можно предзадать в `kibana.yml` — политики создаются при старте Fleet:

```yaml
# kibana.yml
xpack.fleet.packages:
  - name: system
    version: latest
  - name: elastic_agent
    version: latest
xpack.fleet.agentPolicies:
  - name: "Agent policy 1"
    id: agent-policy-1
    namespace: default
    monitoring_enabled:
      - logs
      - metrics
    package_policies:
      - name: system-1
        id: default-system
        package:
          name: system
```

Fleet Server hosts предзадаются через `xpack.fleet.agents.fleet_server.hosts` (при этом настройка в UI становится недоступной — серым).

## Режимы управления

### Fleet-managed (рекомендуется для production)

**Преимущества:**
- Централизованное управление через UI/API (API-first дизайн)
- Массовое обновление конфигураций и интеграций
- Централизованный мониторинг состояния всех агентов
- Автоматическое обновление бинарников агентов (auto-upgrade, с уровнем подписки)
- Управление через GitOps (через API или preconfiguration в `kibana.yml`)

**Недостатки:**
- Зависимость от доступности Fleet Server для управления (данные при этом продолжают отправляться в кластер)
- Дополнительная инфраструктура (Fleet Server)
- Outbound-соединения от агентов к Fleet Server (порт 8220), что может ограничиваться firewall

### Standalone

**Преимущества:**
- Автономность — не требует Fleet Server
- Простота для edge-случаев и изолированных сред
- Полный контроль через конфигурационный файл

**Недостатки:**
- Нет централизованного мониторинга состояния агентов
- Ручное управление конфигурацией на каждом хосте
- Ручное обновление (`elastic-agent upgrade <version>`)

## Миграция с Beats на Elastic Agent

### Сравнение компонентов

| Beat | Elastic Agent Equivalent |
|------|-------------------------|
| Filebeat | Filestream input |
| Metricbeat | Metricsets в inputs (`system/metrics` и др.) |
| Heartbeat | Elastic Synthetics |
| Auditbeat | System Audit integration |
| Packetbeat | Network Packet Capture integration |
| Winlogbeat | Custom Windows Event Logs (`winlog`) / Windows integration |
| Functionbeat | Не поддерживается |

Таблица консистентна с [Beats Family](./beats_family.md).

### Процесс миграции

1. **Установить Fleet Server** (если еще нет)
2. **Создать политику** в Fleet UI с нужными интеграциями
3. **Установить Elastic Agent** с enrollment token
4. **Проверить данные** — сравнить с Beat-потоком (датасеты, поля, volume)
5. **Отключить Beat** после верификации

### Отличия в конфигурации

```yaml
# Filebeat (старый подход)
filebeat.inputs:
  - type: filestream
    id: my-logs
    paths: ["/var/log/*.log"]

output.elasticsearch:
  hosts: ["https://es:9200"]

# Elastic Agent standalone (новый подход)
inputs:
  - type: filestream
    id: my-logs
    streams:
      - data_stream:
          dataset: generic
        paths: ["/var/log/*.log"]
# output определяется в секции outputs (standalone)
# или в Agent Policy (fleet-managed)
```

## Мониторинг агентов

### Fleet UI

В Kibana: **Management → Fleet → Agents**. Вкладка отображает максимум 10 000 агентов (500 страниц по 20 строк) — при большем числе используйте фильтрацию и сортировку.

Статусы Elastic Agent (официальные определения):

| Статус | Значение |
|--------|----------|
| **Healthy** | Агент зачислен и делает check-in; нет обновлений политики или бинарника в процессе (бинарник может быть устаревшим) |
| **Unhealthy** | Агент имеет ошибки или работает в деградированном состоянии |
| **Orphaned** | Только для Elastic Defend: ошибка связи между сервисом Elastic Agent и endpoint-сервисом Defend; интеграция Defend при этом продолжает защищать хост |
| **Updating** | Агент обновляет политику, бинарник или зачисляется/выходит из Fleet |
| **Offline** | Агент не делает check-in с Fleet Server **не менее 5 минут**. Порог фиксирован и не настраивается; API keys offline-агентов остаются валидными |

Внутренние состояния компонентов агента: `STARTING`, `CONFIGURING`, `HEALTHY`, `DEGRADED`, `FAILED`, `STOPPING`, `UPGRADING`, `ROLLBACK`.

### Метрики и алерты

Мониторинг агентов выполняется вне stack monitoring. При включённом agent monitoring в политике данные пишутся в data streams:

* **`metrics-fleet_server.agent_status-default`** — число агентов в различных состояниях. Поля: `fleet.agents.total`, `fleet.agents.enrolled`, `fleet.agents.unenrolled`, `fleet.agents.healthy`, `fleet.agents.offline`, `fleet.agents.updating`, `fleet.agents.unhealthy`, `fleet.agents.inactive`.
* **`metrics-fleet_server.agent_versions-default`** — отдельный документ на каждую версию с числом зачисленных агентов. Поля: `fleet.agent.version`, `fleet.agent.count`.

В Kibana доступны **out-of-the-box alert rules** на основе статуса Fleet и Elastic Agent (включаются в правилах алертинга). Дашборд: **[Elastic Agent] Agent metrics** (Analytics → Dashboard).

### Мониторинг Fleet Server

Для self-managed Fleet Server мониторинг включён по умолчанию в новой политике:

1. Fleet → Agent policies → откройте Fleet Server policy → Settings.
2. Убедитесь, что выбраны «Collect agent logs» и «Collect agent metrics».
3. Задайте Default namespace (например, `fleetserver`) — разделяет данные мониторинга Fleet Server от остальных.
4. Analytics → Discover: запрос `data_stream.namespace: "fleetserver"`; там же видны CPU и память — по ним масштабируют Fleet Server.

## Обновление агентов

### Правила совместимости версий

* Агент можно обновить до **нового patch в пределах текущего minor**, но не до minor новее, чем Fleet Server, с которым он зачислен. Пример: Fleet Server 9.1.0 поддерживает обновление агентов до любой 9.1.x, но не до 9.2.0.
* **Перед обновлением агентов на новый minor сначала обновите агенты, играющие роль Fleet Server** (агенты с Fleet Server policy).
* Агент должен работать как сервис (Linux) и не внутри контейнера.
* Поддержка Fleet-managed апгрейда по способу установки: Linux tar.gz (как сервис) — да; Windows msi/zip — да; macOS tar.gz — да; **DEB и RPM — нет** (обновляйте пакеты вручную).

### Процедура и поведение

* Обновление инициируется в Management → Fleet → Agents: выбор агентов → Actions → upgrade. Интервалы повторных попыток: 1m, 5m, 10m, 15m, 30m, 1h; в этот период агент может показываться как «retrying».
* Застрявшие обновления перезапускаются для одного агента или массово (Actions → Restart upgrade agents) с выбором версии и maintenance window; «Immediately» принудительно обновляет сейчас (не используйте для больших партий).
* **Rollback** обновления агента на предыдущую версию — GA с 9.3.
* **Auto-upgrade agents** (GA с 9.1, требует уровня подписки): Agent policies → политика → Auto-upgrade agents → Manage → Add target version — постепенное обновление заданного процента агентов. Настройки интервала и повторов в `kibana.yml`:

```yaml
xpack.fleet.autoUpgrades.taskInterval: 15m
xpack.fleet.autoUpgrades.retryDelays: ['5m', '10m', '20m']
```

* **Интеграции** System, Elastic Agent и Fleet Server обновляются автоматически по умолчанию. Если новая версия интеграции содержит deprecations, Fleet приостанавливает авто-обновление и требует review и принятия изменений.
* Standalone-агенты обновляются вручную: `elastic-agent upgrade <version> [--source-uri <uri>]` (только для standalone; зачисленные в Fleet агенты обновляются через Fleet).

## Устранение неполадок

### Agent не подключается к Fleet Server

- Проверить DNS-резолв Fleet Server hostname
- Проверить сертификат CA (`--certificate-authorities`)
- Проверить network policy / firewall: порт 8220 открыт для ingress и egress
- Ошибка `x509: certificate signed by unknown authority` — Fleet Server использует self-signed сертификат; в non-production помочь может `--insecure`, в production — правильный CA
- Логи агента (внутренние rotating-логи всегда пишутся, независимо от конфигурации):
  - Linux tar.gz: `/opt/Elastic/Agent/data/elastic-agent-*/logs/elastic-agent-*.ndjson`
  - DEB/RPM: `/var/lib/elastic-agent/data/elastic-agent-*/logs/elastic-agent-*.ndjson`
  - Windows: `C:\Program Files\Elastic\Agent\data\elastic-agent-*\logs\elastic-agent-*.ndjson`
  - macOS: `/Library/Elastic/Agent/data/elastic-agent-*/logs/elastic-agent-*.ndjson`
  - Имена файлов содержат дату ротации: `elastic-agent-YYYYMMDD.ndjson`; events log — в `.../logs/events/elastic-agent-event-log*.ndjson`
- Внешний вывод логов настраивается (по умолчанию stderr; также syslog, eventlog, files): `agent.logging.files.rotateeverybytes` (default 10 МБ), `agent.logging.files.keepfiles`
- Диагностический бандл для поддержки: `elastic-agent diagnostics`; конфигурация компонентов: `elastic-agent inspect components [--show-config]`

### Агенты показывают «Offline»

- Fleet Server не получал check-in ≥ 5 минут (порог фиксирован)
- Причины: сеть, перезагрузка агента, остановка сервиса. API keys offline-агентов остаются валидными — после восстановления связи агент возобновляет check-in

### Конфликт версий

- Версия Elastic Agent должна совпадать с версией стека (major.minor); агент не может быть новее Fleet Server на minor
- Fleet Server обновляется через Fleet: при обновлении на новый minor сначала обновляются агенты с Fleet Server policy
- DEB/RPM-агенты не обновляются через Fleet — обновляйте пакеты вручную

### Данные не появляются в Elasticsearch

1. Проверить статус агента: `elastic-agent status` (команды: `status`, `restart`, `uninstall`, `privileged`/`unprivileged`, `otel`)
2. Проверить, что output в политике (fleet-managed) или `outputs` в `elastic-agent.yml` (standalone) указывает на рабочий кластер
3. Проверить данные мониторинга агента: `metrics-fleet_server.agent_status-default`
4. Сравнить с Beat-потоком при миграции (см. раздел «Миграция»)

## Лучшие практики

1. **Выделяйте отдельную политику** для каждой группы серверов (web, db, kube-nodes) — до 1000 политик на Fleet
2. **Проверяйте, что agent monitoring включён** в политике (включён по умолчанию) — агенты сами отправляют логи и метрики о себе
3. **Используйте namespace** для логического разделения (prod, staging, dev)
4. **Обновляйте агенты постепенно** — auto-upgrade с процентом агентов или canary-группа перед массовым rollout
5. **Мониторьте Fleet Server** — критический компонент для fleet-managed агентов; отдельный namespace (`fleetserver`) и дашборд [Elastic Agent] Agent metrics
6. **Резервируйте Fleet Server** — укажите несколько URL Fleet Server hosts в Fleet settings: агенты подключаются к ним в round-robin порядке до успешного соединения (автоматический failover); при добавлении/удалении хоста все политики обновляются автоматически
7. **TLS обязателен** для всех соединений (Fleet Server ↔ Agent, Agent → Elasticsearch) — режим Production при установке Fleet Server
8. **Используйте `inactivity_timeout`** для ephemeral-сред (Docker, K8s) — автоматический unenroll неактивных агентов и освобождение API keys
9. **Автоматизируйте через API или preconfiguration** (`xpack.fleet.agentPolicies` в `kibana.yml`) — Fleet API-first, всё из UI доступно через API

## См. также

* **[Filebeat: Обзор](../filebeat_overview.md)** — миграция с Filebeat на Elastic Agent.
* **[Beats Family](./beats_family.md)** — Metricbeat, Heartbeat, Auditbeat, Packetbeat, Winlogbeat.
* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — Fleet UI и управление агентами.
* **[Security Advanced](./elasticsearch_security_advanced.md)** — безопасность агентов и API Keys.
* **[Network и Firewall](../elasticsearch_network_requirements.md)** — порты и протоколы (8220 для Fleet Server).
* **[ELK стек: Обзор](../elk_stack_overview.md)** — архитектура стека.
