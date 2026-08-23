# Beats Family: Metricbeat, Heartbeat, Auditbeat, Packetbeat

> Обзор семейства Beats помимо Filebeat. Рассматриваются Metricbeat, Heartbeat, Auditbeat, Packetbeat и их использование в production.
>
> Связанные темы: Filebeat — [Filebeat Overview](../filebeat_overview.md); Elastic Agent — [Elastic Agent and Fleet](./elastic_agent_and_fleet.md); Stack Monitoring — [Stack Monitoring](./elasticsearch_stack_monitoring.md).

## Определения

* **Beats** — легковесные агенты сбора данных (shippers) для Elasticsearch. Каждый Beat специализируется на типе данных.
* **Metricbeat** — сбор метрик систем и сервисов (CPU, memory, disk, HTTP, databases).
* **Heartbeat** — мониторинг доступности сервисов (HTTP, TCP, ICMP).
* **Auditbeat** — сбор данных аудита (системные события, целостность файлов).
* **Packetbeat** — анализ сетевого трафика (HTTP, DNS, MySQL, etc.).
* **Module** — предконфигурированный набор inputs и dashboards для конкретного сервиса.
* **Metricset** — набор метрик внутри модуля.

## Обзор Beats

| Beat | Тип данных | Использование | Замена в Elastic Agent |
|------|-----------|---------------|----------------------|
| Filebeat | Логи | Сбор и парсинг логов | Filestream input |
| Metricbeat | Метрики | Системные и сервисные метрики | Metricsets |
| Heartbeat | Uptime | Мониторинг доступности | Synthetics |
| Auditbeat | Аудит | Системный аудит, FIM | System Security |
| Packetbeat | Сеть | Анализ сетевого трафика | NPC integration |
| Functionbeat | Serverless | Сбор из cloud functions | Не поддерживается |

## Metricbeat

### Установка

```bash
# Debian/Ubuntu
wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo apt-key add -
echo "deb https://artifacts.elastic.co/packages/8.x/apt stable main" | sudo tee /etc/apt/sources.list.d/elastic-8.x.list
sudo apt update && sudo apt install metricbeat

# Или через Docker
docker pull docker.elastic.co/beats/metricbeat:8.15.0
```

### Конфигурация

```yaml
# metricbeat.yml
metricbeat.config.modules:
  path: ${path.config}/modules.d/*.yml
  reload.enabled: false

output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  username: "metricbeat"
  password: "${ES_METRICBEAT_PASSWORD}"

setup.kibana:
  host: "https://kibana:5601"

setup.dashboards.enabled: true
```

### Модули

```bash
# Список доступных модулей
metricbeat modules list

# Включение модуля
metricbeat modules enable system
metricbeat modules enable nginx
metricbeat modules enable mysql
metricbeat modules enable docker
metricbeat modules enable kubernetes
```

### System Module

```yaml
# modules.d/system.yml
- module: system
  period: 10s
  metricsets:
    - cpu
    - load
    - memory
    - network
    - process
    - process_summary
    - diskio
    - filesystem
    - fsstat
  processors:
    - add_host_metadata: ~
    - add_cloud_metadata: ~
```

### Docker Module

```yaml
# modules.d/docker.yml
- module: docker
  metricsets:
    - container
    - cpu
    - diskio
    - healthcheck
    - info
    - memory
    - network
  hosts: ["unix:///var/run/docker.sock"]
  period: 10s
```

### Kubernetes Module

```yaml
# modules.d/kubernetes.yml
- module: kubernetes
  metricsets:
    - node
    - system
    - pod
    - container
    - volume
  period: 10s
  host: ${NODE_NAME}
  hosts: ["https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT}"]
```

### HTTP Module

```yaml
# modules.d/http.yml
- module: http
  metricsets:
    - json
  period: 10s
  hosts: ["http://localhost:8080"]
  namespace: "json_namespace"
  path: "/"
  body: ""
  method: "GET"
```

### Процессоры

```yaml
processors:
  - add_host_metadata:
      netinfo.enabled: true
  - add_cloud_metadata: ~
  - add_docker_metadata: ~
  - add_kubernetes_metadata:
      host: ${NODE_NAME}
      include_annotations: ["annotation1"]
  - drop_fields:
      fields: ["host.name", "agent.version"]
  - rename:
      fields:
        - from: "system.cpu.total.pct"
          to: "cpu.usage"
```

## Heartbeat

### Установка

```bash
sudo apt install heartbeat-elastic
```

### Конфигурация

```yaml
# heartbeat.yml
heartbeat.monitors:
  - type: http
    id: my-website
    name: My Website
    urls: ["https://my-website.com"]
    schedule: '@every 30s'
    timeout: 10s
    check.response:
      status: 200
      body:
        - positive: "Welcome"
    ssl:
      certificate_authorities: ["/path/to/ca.crt"]

  - type: tcp
    id: my-database
    name: PostgreSQL
    hosts: ["my-db-host"]
    ports: [5432]
    schedule: '@every 60s'

  - type: icmp
    id: my-server
    name: Server Ping
    hosts: ["10.0.0.1"]
    schedule: '@every 10s'

output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  username: "heartbeat"
  password: "${ES_HEARTBEAT_PASSWORD}"
```

### Типы мониторов

| Тип | Описание | Использование |
|-----|----------|---------------|
| `http` | HTTP/HTTPS запрос | Веб-сайты, API |
| `tcp` | TCP соединение | Базы данных, сервисы |
| `icmp` | ICMP ping | Доступность хостов |
| `browser` | Synthetics (real browser) | E2E тесты |

### HTTP Monitor с детальной проверкой

```yaml
heartbeat.monitors:
  - type: http
    id: api-health
    name: API Health Check
    urls: ["https://api.company.com/health"]
    schedule: '@every 30s'
    timeout: 10s
    check.request:
      method: GET
      headers:
        Authorization: "Bearer ${API_TOKEN}"
    check.response:
      status: 200
      json:
        - description: "Status is healthy"
          condition:
            equals:
              status: "healthy"
      headers:
        - description: "Content type is JSON"
          condition:
            equals:
              "content-type": "application/json"
```

## Auditbeat

### Установка

```bash
sudo apt install auditbeat
```

### Конфигурация

```yaml
# auditbeat.yml
auditbeat.modules:
  - module: file_integrity
    paths:
      - /bin
      - /usr/bin
      - /etc
    exclude_files:
      - '(?i)\.sw[nop]$'
      - '~$'
    scan_at_start: true
    scan_rate_per_sec: 50 MB
    max_file_size: 100 MB
    hash_types: [sha1]
    recursive: true

  - module: system
    datasets:
      - host
      - login
      - package
      - process
      - socket
      - user
    state.period: 12h
    user.detect_password_changes: true

output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  username: "auditbeat"
  password: "${ES_AUDITBEAT_PASSWORD}"
```

### File Integrity Monitoring (FIM)

```yaml
- module: file_integrity
  paths:
    - /etc/nginx
    - /etc/ssl
    - /opt/myapp
  scan_at_start: true
  hash_types: [sha256]
```

**Важно:** FIM может генерировать много данных при первом сканировании. Используйте `exclude_files` для временных файлов.

### System Module

| Dataset | Описание |
|---------|----------|
| `host` | Информация о хосте |
| `login` | Логины/логауты |
| `package` | Установленные пакеты |
| `process` | Процессы |
| `socket` | Сетевые соединения |
| `user` | Пользователи |

## Packetbeat

### Установка

```bash
sudo apt install packetbeat
```

### Конфигурация

```yaml
# packetbeat.yml
packetbeat.interfaces.device: any

packetbeat.flows:
  timeout: 30s
  period: 10s

packetbeat.protocols:
  - type: http
    ports: [80, 8080, 8000, 5000, 8002]
    send_headers: ["User-Agent", "Cookie"]
    send_all_headers: false
    include_body_for: ["text/html"]

  - type: dns
    ports: [53]

  - type: mysql
    ports: [3306]

  - type: postgresql
    ports: [5432]

  - type: redis
    ports: [6379]

  - type: tls
    ports: [443, 993, 995, 5223]

output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  username: "packetbeat"
  password: "${ES_PACKETBEAT_PASSWORD}"
```

### Поддерживаемые протоколы

| Протокол | Порт | Информация |
|----------|------|------------|
| HTTP | 80, 8080, etc. | Запросы/ответы, latency |
| DNS | 53 | Запросы DNS |
| MySQL | 3306 | Запросы, latency |
| PostgreSQL | 5432 | Запросы, latency |
| Redis | 6379 | Команды, latency |
| MongoDB | 27017 | Запросы |
| TLS | 443 | TLS handshake info |
| ICMP | - | Ping |

### Flows (NetFlow-like)

```yaml
packetbeat.flows:
  timeout: 30s
  period: 10s
```

Flows агрегирует сетевые соединения без deep packet inspection.

## Сравнение Metricbeat и Packetbeat

| Критерий | Metricbeat | Packetbeat |
|----------|------------|------------|
| Тип данных | Метрики (числа) | Транзакции (события) |
| Уровень | Приложение | Сеть |
| Overhead | Низкий | Средний (DPI) |
| Использование | Capacity planning | Troubleshooting |
| CPU | <1% | 5-15% |

## Docker и Kubernetes

### Metricbeat в Docker

```yaml
# docker-compose.yml
metricbeat:
  image: docker.elastic.co/beats/metricbeat:8.15.0
  user: root
  volumes:
    - ./metricbeat.yml:/usr/share/metricbeat/metricbeat.yml
    - /var/run/docker.sock:/var/run/docker.sock
    - /sys/fs/cgroup:/hostfs/sys/fs/cgroup
    - /proc:/hostfs/proc
    - /:/hostfs
  environment:
    - ELASTICSEARCH_HOSTS=https://elasticsearch:9200
```

### Metricbeat в Kubernetes (DaemonSet)

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: metricbeat
  namespace: kube-system
spec:
  template:
    spec:
      containers:
        - name: metricbeat
          image: docker.elastic.co/beats/metricbeat:8.15.0
          volumeMounts:
            - name: config
              mountPath: /usr/share/metricbeat/metricbeat.yml
              subPath: metricbeat.yml
            - name: dockersock
              mountPath: /var/run/docker.sock
      volumes:
        - name: config
          configMap:
            name: metricbeat-config
        - name: dockersock
          hostPath:
            path: /var/run/docker.sock
```

## Индексы для Beats

| Beat | Индекс | ILM |
|------|--------|-----|
| Filebeat | filebeat-* | filebeat |
| Metricbeat | metricbeat-* | metricbeat |
| Heartbeat | heartbeat-* | heartbeat |
| Auditbeat | auditbeat-* | auditbeat |
| Packetbeat | packetbeat-* | packetbeat |

## ILM Policies для Beats

```bash
PUT _ilm/policy/metricbeat
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_size": "50GB",
            "max_age": "30d"
          },
            "set_priority": { "priority": 100 }
        }
      },
      "warm": {
        "min_age": "30d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 }
        }
      },
      "cold": {
        "min_age": "90d",
        "actions": {
          "freeze": {}
        }
      },
      "delete": {
        "min_age": "365d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

## Best Practices

### Общие

1. **Используйте modules** — вместо ручной настройки, когда возможно
2. **Настройте ILM** — автоматическое управление retention
3. **Processors** — обогащайте данные на уровне агента
4. **Мониторинг** — следите за здоровьем Beats через Stack Monitoring
5. **Безопасность** — TLS, API keys вместо паролей

### Metricbeat

1. **System module** — включен по умолчанию, не отключайте
2. **Kubernetes module** — для K8s мониторинга
3. **Docker module** — для Docker контейнеров
4. **period: 10s** — хороший баланс между granularity и overhead

### Heartbeat

1. **Уникальный id** для каждого монитора
2. **check.response** — проверяйте не только status code
3. **ssl** — всегда указывайте CA для production
4. **schedule** — не слишком агрессивно (<30s для critical, <5m для остальных)

### Auditbeat

1. **FIM** — ограничивайте paths для избежания перегрузки
2. **hash_types** — sha256 для безопасности, sha1 для скорости
3. **exclude_files** — исключайте временные и изменяющиеся файлы

### Packetbeat

1. **DPI overhead** — учитывайте CPU usage при включении на всех хостах
2. **include_body_for** — ограничивайте для снижения объема данных
3. **Flows** — менее resource-intensive, чем DPI

## Troubleshooting

### Данные не появляются в Elasticsearch

1. Проверить output конфигурацию
2. Проверить credentials
3. Проверить network connectivity
4. Логи: `/var/log/metricbeat/metricbeat`

### High CPU usage

1. Увеличить `period`
2. Отключить неиспользуемые модули
3. Ограничить Packetbeat DPI
4. Проверить `max_file_size` для Auditbeat FIM

### ILM не применяется

1. Проверить index template
2. Проверить ILM policy exists
3. Проверить permissions для ILM

## См. также

* **[Filebeat: Обзор](../filebeat_overview.md)** — Filebeat для сбора логов.
* **[Elastic Agent и Fleet](./elastic_agent_and_fleet.md)** — замена Beats на Elastic Agent.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — мониторинг Beats.
* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — дашборды для Beats.
* **[Index Templates и Data Streams](./elasticsearch_index_templates.md)** — шаблоны для Beats индексов.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — ILM для Beats данных.
