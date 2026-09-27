# Log Pipeline: Fluentd/Vector/Loki интеграция с Wazuh

## Определения

**Log Pipeline** — цепочка компонентов для сбора, обогащения, маршрутизации и хранения логов: Source → Collector → Processing → Storage → Visualization. Wazuh может быть как источником, так и получателем данных в пайплайне.

**Fluentd** — универсальный log collector (CNCF), поддерживающий 500+ плагинов для входов/выходов. Используется как DaemonSet в Kubernetes для сбора логов подов.

**Vector** — высокопроизводительный log/trace/metric агент (Rust), заменяющий Fluentd/Fluent Bit. Поддерживает трансформации (VRL) и множество выходов.

**Loki** — log aggregation system (Grafana Labs), хранящий только индексы (labels) без полнотекстового поиска. Комплементарен с Prometheus.

**OpenSearch** — целевое хранилище для Wazuh (替代 Elasticsearch). Wazuh 5.0 использует OpenSearch 3.x нативно.

## Основные концепции

### Архитектура лог-пайплайна с Wazuh

```
┌─────────────────────────────────────────────────────────────┐
│                    Sources                                   │
│  Linux (/var/log/*) │ Windows (EventLog) │ Containers │ API│
└────────┬────────────┴───────────────────┴─────────────┴────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│              Collection Layer                               │
│  Fluentd (DaemonSet) │ Vector Agent │ Filebeat │ Wazuh Agent│
└────────┬──────────────┴──────────────┴──────────┴──────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│              Processing Layer                               │
│  Wazuh Manager (Engine) │ Fluentd Parser │ Vector Transform │
│  Декодеры, правила, корреляция                              │
└────────┬──────────────┬──────────────┬─────────────────────┘
         │              │              │
         ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ OpenSearch   │ │ Loki         │ │ S3/MinIO     │
│ (Wazuh Index)│ │ (long-term)  │ │ (archive)    │
└──────┬───────┘ └──────┬───────┘ └──────────────┘
       │                │
       ▼                ▼
┌────────────────────────────────────┐
│  Visualization                      │
│  Wazuh Dashboard │ Grafana          │
└────────────────────────────────────┘
```

## Практические сценарии

### 1. Fluentd → Wazuh: сбор с Kubernetes

```yaml
# fluentd-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluentd-config
  namespace: logging
data:
  fluent.conf: |
    # Сбор логов подов
    <source>
      @type tail
      @id in_tail_container_logs
      path /var/log/containers/*.log
      pos_file /var/log/fluentd-containers.log.pos
      tag kubernetes.*
      exclude_path ["/var/log/containers/fluentd*"]
      read_from_head true
      <parse>
        @type multi_format
        <pattern>
          format json
          time_key time
          time_format %Y-%m-%dT%H:%M:%S.%NZ
          keep_time_key true
        </pattern>
        <pattern>
          format regexp
          expression /^(?<time>.+) (?<stream>stdout|stderr) [^ ]* (?<log>.*)$/
          time_format %Y-%m-%dT%H:%M:%S.%N%z
        </pattern>
      </parse>
    </source>

    # Обогащение Kubernetes-метаданными
    <filter kubernetes.**>
      @type kubernetes_metadata
      @id filter_kube_metadata
      kubernetes_url "https://#{ENV['KUBERNETES_SERVICE_HOST']}:#{ENV['KUBERNETES_SERVICE_PORT']}"
      verify_ssl true
      ca_file /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
      bearer_token_file /var/run/secrets/kubernetes.io/serviceaccount/token
      skip_labels false
      skip_container_metadata false
      skip_namespace_metadata true
      skip_master_url true
    </filter>

    # Отправка в Wazuh Manager
    <match kubernetes.**>
      @type wazuh
      @id out_wazuh
      wazuh_manager "wazuh-manager.wazuh.svc.cluster.local"
      wazuh_manager_port 1514
      protocol tcp
      log_level info
      <buffer>
        @type file
        path /var/log/fluentd-wazuh-buffer
        flush_mode interval
        flush_interval 5s
        retry_type exponential_backoff
        retry_max_interval 30s
        chunk_limit_size 2M
        queue_limit_length 32
        overflow_action block
      </buffer>
    </match>
```

### 2. Vector → Wazuh: сбор с Linux-серверов

```toml
# /etc/vector/vector.toml

# Sources
[sources.system_logs]
  type = "file"
  include = ["/var/log/syslog", "/var/log/auth.log", "/var/log/kern.log"]
  read_from = "beginning"

[sources.journald]
  type = "journald"
  journal_directory = "/var/log/journal"

[sources.docker_logs]
  type = "docker_logs"

# Transforms
[transforms.parse_syslog]
  type = "remap"
  inputs = ["system_logs"]
  source = '''
  parsed = parse_syslog!(.message)
  .severity = parsed.severity
  .facility = parsed.facility
  .message = parsed.message
  .hostname = parsed.hostname
  '''

[transforms.filter_critical]
  type = "filter"
  inputs = ["parse_syslog"]
  condition = '.severity == "crit" || .severity == "emerg" || .severity == "err"'

# Sinks
[sinks.wazuh]
  type = "socket"
  inputs = ["parse_syslog", "docker_logs"]
  address = "wazuh-manager:1514"
  protocol = "tcp"
  encoding.codec = "json"

[sinks.wazuh_critical]
  type = "socket"
  inputs = ["filter_critical"]
  address = "wazuh-manager:1514"
  protocol = "tcp"
  encoding.codec = "json"

[sinks.loki]
  type = "loki"
  inputs = ["system_logs", "docker_logs"]
  endpoint = "http://loki:3100"
  labels.job = "vector"
  labels.hostname = "{{ hostname }}"
  encoding.codec = "json"
```

### 3. Wazuh → Loki: экспорт алертов

```yaml
# Docker Compose: Vector как sidecar для Wazuh
version: '3.8'
services:
  wazuh-manager:
    image: wazuh/wazuh-manager:5.0
    volumes:
      - manager_logs:/var/ossec/logs
    networks:
      - wazuh-net

  vector:
    image: timberio/vector:latest-alpine
    volumes:
      - ./vector.toml:/etc/vector/vector.toml
      - manager_logs:/var/log/wazuh:ro
    depends_on:
      - wazuh-manager
    networks:
      - wazuh-net
```

```toml
# vector.toml: Wazuh alerts → Loki
[sources.wazuh_alerts]
  type = "file"
  include = ["/var/log/wazuh/alerts/alerts.log"]
  read_from = "end"

[transforms.parse_alerts]
  type = "remap"
  inputs = ["wazuh_alerts"]
  source = '''
  parsed = parse_json!(.message)
  .rule_id = parsed.rule.id
  .rule_level = parsed.rule.level
  .agent_name = parsed.agent.name
  .description = parsed.rule.description
  .timestamp = parsed.timestamp
  '''

[sinks.loki_alerts]
  type = "loki"
  inputs = ["parse_alerts"]
  endpoint = "http://loki:3100"
  labels.job = "wazuh-alerts"
  labels.level = "{{ rule_level }}"
  labels.agent = "{{ agent_name }}"
  encoding.codec = "json"
```

### 4. Fluent Bit → Wazuh: lightweight collector

```ini
# /etc/fluent-bit/fluent-bit.conf

[SERVICE]
    Flush         5
    Daemon        Off
    Log_Level     info
    Parsers_File  parsers.conf

[INPUT]
    Name          tail
    Path          /var/log/*.log
    Parser        syslog
    Tag           host.*
    Refresh_Interval 10

[OUTPUT]
    Name          wazuh
    Match         host.*
    Host          wazuh-manager
    Port          1514
    Proto         tcp
    Log_Level     info
```

### 5. Обработка и маршрутизация

```yaml
# Лог-пайплайн: разные источники → разные индексы
# Vector config
[sources.nginx]
  type = "file"
  include = ["/var/log/nginx/access.log"]
  tags = ["nginx", "web"]

[sources.mysql]
  type = "file"
  include = ["/var/log/mysql/slow.log", "/var/log/mysql/error.log"]
  tags = ["mysql", "database"]

[transforms.route_by_tag]
  type = "route"
  inputs = ["nginx", "mysql"]
  routes.nginx.type = "remap"
  routes.nginx.source = '.source = "nginx"'
  routes.mysql.type = "remap"
  routes.mysql.source = '.source = "mysql"'

[sinks.wazuh_nginx]
  type = "socket"
  inputs = ["route.nginx"]
  address = "wazuh-manager:1514"
  protocol = "tcp"
  encoding.codec = "json"

[sinks.wazuh_mysql]
  type = "socket"
  inputs = ["route.mysql"]
  address = "wazuh-manager:1514"
  protocol = "tcp"
  encoding.codec = "json"
```

### 6. Wazuh → S3/MinIO архив

```yaml
# Fluentd: архивация старых логов Wazuh
<match wazuh.**>
  @type s3
  @id out_s3_archive
  s3_bucket "wazuh-archive"
  s3_region "us-east-1"
  path "logs/%Y/%m/%d/"
  buffer_path /var/log/fluentd-s3-buffer
  <buffer time>
    @type file
    path /var/log/fluentd-s3-buffer
    timekey 1d
    timekey_wait 1h
  </buffer>
  <format>
    @type json
  </format>
</match>
```

## Дополнительная информация

### Выбор коллектора

| Критерий | Fluentd | Vector | Fluent Bit |
|:---|:---|:---|:---|
| **Язык** | Ruby | Rust | C |
| **Производительность** | Средняя | Высокая | Высокая |
| **Память** | 50–200 MB | 10–50 MB | 5–15 MB |
| **Плагины** | 500+ | 30+ (нативные) | 70+ |
| **Трансформации** | Basic | VRL (мощный) | Basic |
| **K8s** | DaemonSet | DaemonSet | DaemonSet |
| **Рекомендация** | Legacy | **Рекомендуется** | Lightweight |

### Best Practices

1. **Buffering**: всегда настройте буферизацию (file-based, не memory-only).
2. **Retry**: exponential backoff с максимальным количеством попыток.
3. **Filtering**: фильтруйте шум на этапе коллекции (не в Wazuh).
4. **Labels**: используйте labels для маршрутизации в Loki.
5. **Monitoring**: мониторьте сам пайплайн (Vector has internal metrics).

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Логи не доходят** | Нет сети до Manager | Проверьте `nc -zv wazuh-manager 1514` |
| **Дубли логов** | Два коллектора на один файл | Один источник = один коллектор |
| **Performance** | Слишком много regex | Используйте JSON-парсинг вместо regex |
| **Buffer overflow** | Маленький buffer | Увеличьте `chunk_limit_size` |

### См. также
- [Log Collection](./wazuh-log-collection.md) — нативная лог-коллекция Wazuh.
- [Custom Decoders](./custom-decoders.md) — парсинг логов.
- [Kubernetes](./wazuh-kubernetes.md) — DaemonSet для агентов.
