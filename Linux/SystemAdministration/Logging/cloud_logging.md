# Облачное логирование (Cloud Logging)

## Определения

**Cloud Logging** — централизованные управляемые сервисы сбора, хранения и анализа логов, предоставляемые облачными провайдерами (AWS, GCP, Azure, Yandex Cloud). Они обеспечивают высокую доступность, автоматическое масштабирование и глубокую интеграцию с экосистемой облака (IAM, мониторинг, бессерверные вычисления).

**Ключевые преимущества:**
- **Zero-ops:** Нет необходимости управлять кластерами Elasticsearch или базами данных.
- **Безопасность:** Интеграция с нативными механизмами контроля доступа (RBAC/IAM).
- **Аналитика:** Встроенные языки запросов (KQL, CloudWatch Insights) для поиска и визуализации.

## AWS CloudWatch Logs

Нативное решение AWS. Основной агент сбора — **Unified CloudWatch Agent**, который объединяет сбор метрик и логов.

### Конфигурация агента (`amazon-cloudwatch-agent.json`)
```json
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/nginx/access.log",
            "log_group_name": "/ec2/nginx/access",
            "log_stream_name": "{instance_id}",
            "timestamp_format": "%d/%b/%Y:%H:%M:%S %z"
          }
        ]
      },
      "journald": {
        "collect_list": [
          {
            "log_group_name": "/ec2/system",
            "log_stream_name": "{instance_id}/journald"
          }
        ]
      }
    }
  }
}
```

### Пересылка из Fluent Bit (EKS/EC2)
Для Kubernetes рекомендуется использовать Fluent Bit с плагином `cloudwatch_logs`:
```ini
[OUTPUT]
    Name              cloudwatch_logs
    Match             kube.*
    region            eu-central-1
    log_group_name    /eks/cluster/application
    log_stream_prefix ${HOST_NAME}-
    auto_create_group true
```

## GCP Cloud Logging

Google Cloud Logging (ранее Stackdriver) использует **Ops Agent** на инстансах GCE и автоматический сбор логов в GKE.

### Конфигурация Ops Agent (`config.yaml`)
```yaml
logging:
  receivers:
    nginx_access:
      type: files
      include_paths:
        - /var/log/nginx/access.log
  processors:
    nginx_parser:
      type: parse_nginx_combined
  pipelines:
    nginx_pipeline:
      receivers: [nginx_access]
      processors: [nginx_parser]
```

## Azure Monitor Logs

Azure Monitor Logs (Log Analytics) использует **Azure Monitor Agent (AMA)** и управляется через **Data Collection Rules (DCR)**.

### Пример DCR (JSON фрагмент)
```json
{
  "dataSources": {
    "syslog": [
      {
        "streams": ["Microsoft-Syslog"],
        "facilityNames": ["auth", "authpriv", "daemon"],
        "logLevels": ["Warning", "Error", "Critical"],
        "name": "syslogSource"
      }
    ]
  },
  "destinations": {
    "logAnalytics": [
      {
        "workspaceResourceId": "/subscriptions/.../workspaces/my-logs",
        "name": "la-dest"
      }
    ]
  }
}
```

## Yandex Cloud Logging

Сервис сбора и анализа логов в Yandex Cloud. Поддерживает прием данных через Fluent Bit, Vector и API.

### Интеграция через Fluent Bit
```ini
[OUTPUT]
    Name            yc-logging
    Match           *
    group_id        <id_лог_группы>
    message_key     text
    authorization   iam-token
```

### Маршрутизация (Log Router)
Позволяет направлять потоки логов во внешние системы:
- **Cloud Functions:** Для автоматизации (например, отправка алертов в Telegram).
- **Data Streams (YDS):** Для передачи в ClickHouse или S3.

## Сравнение облачных решений

| Параметр | **AWS CloudWatch** | **GCP Cloud Logging** | **Azure Monitor** | **Yandex Cloud Logging** |
| :--- | :--- | :--- | :--- | :--- |
| **Агент** | Unified CW Agent | Ops Agent | AMA Agent | Fluent Bit / Vector |
| **Язык запросов** | Log Insights | Log Analytics (SQL) | KQL (Kusto) | Query Language |
| **Хранение** | Log Groups | Log Buckets | Log Analytics Workspace | Log Groups |
| **Интеграция** | Lambda, SNS, S3 | Pub/Sub, BQ, GCS | Logic Apps, Sentinel | Cloud Functions, YDS, S3 |

## Практические рекомендации и оптимизация

### 1. Безопасность и аутентификация
Никогда не используйте статические ключи доступа (`Access Keys`).
- **AWS:** Используйте IAM Roles для EC2 и IRSA (IAM Roles for Service Accounts) для EKS.
- **GCP:** Используйте Workload Identity.
- **Yandex Cloud:** Используйте сервисные аккаунты, привязанные к ВМ.

### 2. Оптимизация стоимости (Cost Optimization)
Облачное логирование тарифицируется по объему входящих данных.
- **Исключение (Exclusion):** Настраивайте фильтры на стороне агента, чтобы не отправлять логи уровня `DEBUG`.
- **Сэмплирование (Sampling):** Для `access` логов под высокой нагрузкой оправдано отправлять только 10% записей.
- **Архивация:** Перемещайте логи в дешевое хранилище (S3/GCS/Cold Storage) для долгосрочного хранения (Compliance).

### 3. Гибридные и мультиоблачные паттерны
Для унификации сбора логов в разных облаках используйте универсальные агенты:
- **Vector:** Написан на Rust, обладает минимальным overhead и мощными средствами трансформации (VRL).
- **Fluent Bit:** Легковесный и стандартный де-факто для Kubernetes.

## Дополнительная информация

### См. также
- [Обзор логирования в Linux](./logging_overview.md) — общая архитектура сбора данных.
- [Vector: современная альтернатива](../../../Vector/vector_overview.md) — использование в гибридных средах.
- [Yandex Monitoring: Концепции](../../../Yandex/Monitoring/monitoring_concepts.md) — интеграция логов и метрик.
