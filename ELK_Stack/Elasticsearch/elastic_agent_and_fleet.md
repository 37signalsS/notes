# Elastic Agent и Fleet: Централизованное управление сбором данных

> Руководство по Elastic Agent, Fleet Server и централизованному управлению политиками сбора данных. Рассматриваются архитектура, режимы развертывания, интеграции и миграция с Beats.
>
> Связанные темы: Filebeat — [Filebeat Overview](../filebeat_overview.md); Kibana администрирование — [Kibana Overview](../Kibana/kibana_overview.md); безопасность — [Security Advanced](./elasticsearch_security_advanced.md); [Beats Family](./beats_family.md); [ELK стек: Обзор](../elk_stack_overview.md).

## Определения

* **Elastic Agent** — единый агент сбора данных, заменяющий отдельные Beats. Управляется централизованно через Fleet или автономно через конфигурационный файл.
* **Fleet Server** — компонент, обеспечивающий связь между Kibana и Elastic Agent. Выступает как control plane для тысяч агентов.
* **Agent Policy** — набор интеграций и конфигураций, назначаемый группе агентов. Определяет, какие данные собираются и куда отправляются.
* **Integration** — предконфигурированный пакет для конкретного источника данных (nginx, mysql, kubernetes), включающий inputs, dashboards и pipelines.
* **Standalone Mode** — Elastic Agent работает без Fleet Server, управляется локальным конфигурационным файлом.
* **Fleet-managed Mode** — Elastic Agent подключается к Fleet Server, получает политики из Kibana.

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
                    │  (State &    │
                    │   Config)    │
                    └──────────────┘
```

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

Fleet Server — специальный режим Elastic Agent, который выступает как прокси между Kibana и агентами.

```bash
# Установка Fleet Server через elastic-agent install
sudo elastic-agent install \
  --url=https://fleet-server:8220 \
  --certificate-authorities=/path/to/ca.crt \
  --fleet-server-es=https://elasticsearch:9200 \
  --fleet-server-service-token=<token> \
  --fleet-server-policy=fleet-server-policy
```

**Требования:**
- Выделенный хост или pod (не совмещать с тяжелыми workloads)
- Доступ к Elasticsearch (запись состояния агентов)
- Доступ по порту 8220 от агентов (outbound от агентов к Fleet Server)
- TLS обязателен в production

### Fleet-managed Agent

```bash
sudo elastic-agent install \
  --url=https://fleet-server:8220 \
  --certificate-authorities=/path/to/ca.crt \
  --enrollment-token=<token>
```

### Standalone Agent

```yaml
# elastic-agent.yml
outputs:
  default:
    type: elasticsearch
    hosts: ["https://elasticsearch:9200"]
    username: "agent"
    password: "${ES_AGENT_PASSWORD}"

inputs:
  - type: system/metrics
    streams:
      - metricsets: ["cpu", "memory", "network"]
        dataset: system.cpu
        period: 10s
  - type: filestream
    id: nginx-logs
    paths:
      - /var/log/nginx/*.log
    parsers:
      - ndjson:
          target: ""
          add_error_key: true
```

```bash
# Запуск в standalone
sudo elastic-agent run -c elastic-agent.yml
```

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
│   └── (Elastic Security)
└── Output: production-es-cluster
```

### Создание политики через API

```bash
# Создание политики
POST kibana/api/fleet/agent_policies
{
  "name": "web-servers",
  "description": "Web servers monitoring",
  "namespace": "default",
  "monitoring_logs": true,
  "monitoring_metrics": true
}

# Добавление интеграции в политику
POST kibana/api/fleet/package_policies
{
  "policy_id": "web-servers-policy-id",
  "package": {
    "name": "nginx",
    "version": "1.20.0"
  },
  "name": "nginx-web",
  "namespace": "default",
  "inputs": {
    "nginx-logfile": {
      "enabled": true,
      "streams": {
        "nginx.access": {
          "enabled": true,
          "vars": {
            "paths": ["/var/log/nginx/access.log*"]
          }
        }
      }
    }
  }
}
```

## Режимы управления

### Fleet-managed (рекомендуется для production)

**Преимущества:**
- Централизованное управление через UI/API
- Массовое обновление конфигураций
- Мониторинг состояния всех агентов
- Автоматическое обновление агентов
- Управление через GitOps (через API)

**Недостатки:**
- Зависимость от доступности Fleet Server
- Дополнительная инфраструктура
- Outbound соединения от агентов (может быть ограничено)

### Standalone

**Преимущества:**
- Автономность — не требует Fleet Server
- Простота для edge-случаев и изолированных сред
- Полный контроль через конфиг-файл

**Недостатки:**
- Нет централизованного мониторинга
- Ручное управление конфигурацией
- Сложно при масштабировании >10 агентов

## Миграция с Beats на Elastic Agent

### Сравнение компонентов

| Beat | Elastic Agent Equivalent |
|------|-------------------------|
| Filebeat | Filestream input + processors |
| Metricbeat | Metricsets в inputs |
| Heartbeat | Synthetics input |
| Auditbeat | System Security integration |
| Packetbeat | Network Packet Capture integration |
| Functionbeat | Не поддерживается (serverless через другие решения) |

### Процесс миграции

1. **Установить Fleet Server** (если еще нет)
2. **Создать политику** в Fleet UI с нужными интеграциями
3. **Установить Elastic Agent** с enrollment token
4. **Проверить данные** — сравнить с Beat-потоком
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

# Elastic Agent (новый подход)
inputs:
  - type: filestream
    id: my-logs
    paths: ["/var/log/*.log"]
    # output определяется в Agent Policy
```

## Мониторинг агентов

### Fleet UI

В Kibana: **Management > Fleet > Agents**

- Статус агента: Healthy / Offline / Updating / Error
- Последний check-in
- Версия агента
- Назначенная политика

### API для мониторинга

```bash
# Список агентов
GET kibana/api/fleet/agents

# Детали конкретного агента
GET kibana/api/fleet/agents/<agent-id>

# Статус агентов в политике
GET kibana/api/fleet/agent_policies/<policy-id>/agents
```

### Алерты по состоянию агентов

```bash
PUT _watcher/agent/agents-health
{
  "trigger": { "schedule": { "interval": "5m" } },
  "condition": {
    "compare": {
      "ctx.payload.healthy_agents_ratio": { "lt": 0.95 }
    }
  }
}
```

## Best Practices

1. **Выделяйте отдельную политику** для каждой группы серверов (web, db, kube-nodes)
2. **Включайте monitoring_logs и monitoring_metrics** в политике — агенты сами отправляют метрики о себе
3. **Используйте namespace** для логического разделения (prod, staging, dev)
4. **Тестируйте обновления агентов** на canary-группе перед массовым rollout
5. **Мониторите Fleet Server** — это критический компонент для fleet-managed агентов
6. **Резервируйте Fleet Server** — для больших кластеров используйте несколько Fleet Server instances
7. **TLS обязателен** для всех соединений (Fleet Server ↔ Agent, Agent → Elasticsearch)

## Частые проблемы

### Agent не подключается к Fleet Server

- Проверить DNS-резолв Fleet Server hostname
- Проверить сертификат CA
- Проверить network policy / firewall (port 8220 inbound на Fleet Server)
- Логи: `elastic-agent status` или `/var/lib/elastic-agent/logs/elastic-agent-*`

### Агенты показывают "Offline"

- Fleet Server не получил check-in >5 минут
- Причины: сеть, агент перезагрузился, исчерпан диск (агент останавливается при >95% disk usage)

### Конфликт версий

- Версия агента должна быть совместима с версией Fleet Server и Kibana
- Fleet Server обновляется автоматически через Fleet UI

## См. также

* **[Filebeat: Обзор](../filebeat_overview.md)** — миграция с Filebeat на Elastic Agent.
* **[Beats Family](./beats_family.md)** — Metricbeat, Heartbeat, Auditbeat, Packetbeat.
* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — Fleet UI и управление агентами.
* **[Security Advanced](./elasticsearch_security_advanced.md)** — безопасность агентов и API Keys.
* **[Network и Firewall](../elasticsearch_network_requirements.md)** — порты и протоколы.
* **[ELK стек: Обзор](../elk_stack_overview.md)** — архитектура стека.
