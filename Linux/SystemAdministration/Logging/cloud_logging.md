# Облачное логирование (Cloud Logging)

## Определения

**Cloud Logging** — централизованные сервисы сбора и анализа логов, предоставляемые облачными провайдерами (AWS, GCP, Azure). Они обеспечивают высокую доступность, автоматическое масштабирование и глубокую интеграцию с другими облачными сервисами (IAM, Monitoring, Lambda).

## AWS CloudWatch Logs

CloudWatch Logs — нативное решение AWS. Сбор данных осуществляется через **Unified CloudWatch Agent**.

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

Google Cloud Logging (ранее Stackdriver) использует **Ops Agent** на GCE и автоматическую интеграцию в GKE.

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

Azure Monitor Logs (Log Analytics) использует **Azure Monitor Agent (AMA)**, который заменяет устаревший MMA/OMS агент. Настройка выполняется через **Data Collection Rules (DCR)**.

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

## Сравнение облачных решений

| Параметр | **AWS CloudWatch** | **GCP Cloud Logging** | **Azure Monitor** |
| :--- | :--- | :--- | :--- |
| **Агент** | Unified CW Agent | Ops Agent (Fluent Bit based) | Azure Monitor Agent (AMA) |
| **Язык запросов** | CloudWatch Insights | Log Analytics Query Language | Kusto Query Language (KQL) |
| **Хранение** | Log Groups | Log Buckets | Log Analytics Workspaces |
| **Интеграция** | Lambda, SNS, S3 | Cloud Functions, Pub/Sub | Logic Apps, Automation |

## Рекомендации

1. **Используйте IAM роли:** Никогда не прописывайте Access Keys в конфигурации агентов. Используйте Instance Profiles (AWS), Service Accounts (GCP) или Managed Identities (Azure).
2. **Фильтрация на источнике:** Облачное логирование стоит дорого (оплата за GB). Настраивайте фильтры в агентах, чтобы не отправлять `debug` логи в облако.
3. **Ретенция (Retention):** Настраивайте разные сроки хранения для разных групп логов (например, 7 дней для `access` и 1 год для `auth`).

## Дополнительная информация

- [Обзор логирования в Linux](./logging_overview.md)
- [Интеграция Fluent Bit с Loki](./loki_overview.md)
