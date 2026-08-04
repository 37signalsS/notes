# PostgreSQL в Kubernetes (CloudNativePG)

## Определения

**CloudNativePG (CNPG)** — современный Kubernetes-оператор с открытым исходным кодом для автоматизации полного жизненного цикла кластеров PostgreSQL. Проект входит в CNCF Sandbox и ориентирован на "облачно-нативный" (Cloud Native) подход, используя внутренние механизмы Kubernetes вместо внешних инструментов управления кворумом (например, Patroni).

**Оператор (Operator)** — паттерн в Kubernetes, объединяющий Custom Resources и контроллеры для автоматизации задач администратора БД: развертывание, масштабирование, бэкапы и восстановление. Подробнее — [Kubernetes-операторы](../../../Kubernetes/Concepts/kubernetes_operators.md).

**WAL (Write-Ahead Log) Archiving** — процесс непрерывного копирования журналов транзакций в объектное хранилище (S3/GCS). Это необходимо для восстановления на любой момент времени (PITR).

## Основные концепции

### Архитектура и отказоустойчивость

CNPG не использует Patroni, полагаясь на нативные примитивы Kubernetes.

- **Управление кворумом:** Оператор сам отслеживает состояние подов и выполняет failover, обновляя `Primary` эндпоинт.
- **Синхронная репликация:** Для систем с требованием "Zero Data Loss" можно настроить синхронную передачу данных. Это гарантирует, что транзакция считается завершенной только после подтверждения записи хотя бы одной репликой.
- **Topology Spread Constraints:** распределение подов по разным зонам доступности (Availability Zones) для защиты от региональных сбоев.

### Безопасность и TLS

По умолчанию CNPG генерирует собственные самоподписанные сертификаты для внутреннего взаимодействия и клиентских подключений.
- **Cert-manager:** Оператор нативно интегрируется с `cert-manager` для автоматического получения и обновления доверенных сертификатов (например, через Let's Encrypt).
- **Non-privileged:** Контейнеры запускаются от пользователя с UID 1000, что соответствует стандартам безопасности Restricted Pod Security Standards.

### Хранение данных и снапшоты

CNPG поддерживает **Volume Snapshots**, что позволяет мгновенно клонировать кластеры или восстанавливаться после сбоев без долгого чтения из S3.
- **Persistent Volume Claims (PVC):** Каждому инстансу выделяется свой PVC. Рекомендуется использовать хранилища с низкой задержкой (NVMe SSD).

## Практические сценарии

### Шаг 1: Установка оператора

```bash
# Добавление репозитория
helm repo add cloudnative-pg https://cloudnative-pg.github.io/charts

# Установка
helm upgrade --install cnpg cloudnative-pg/cloudnative-pg \
  --namespace cnpg-system --create-namespace

# Установка плагина kubectl-cnpg
kubectl krew install cnpg
```

### Шаг 2: Развертывание Production-кластера (Best Practices 2026)

Пример манифеста с включенным мониторингом, бэкапами и синхронной репликацией.

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-main
spec:
  instances: 3
  
  # Синхронная репликация для защиты от потери данных
  minSyncReplicas: 1
  maxSyncReplicas: 1

  # Мониторинг (пробрасывает метрики в Prometheus)
  monitoring:
    enablePodMonitor: true

  # Ресурсы (Guaranteed QoS)
  resources:
    requests:
      cpu: "2"
      memory: "4Gi"
    limits:
      cpu: "2"
      memory: "4Gi"

  # Хранилище
  storage:
    size: 100Gi
    storageClass: local-path # Или облачный SSD

  # Резервное копирование и WAL
  backup:
    barmanObjectStore:
      destinationPath: "s3://backups/pg-main"
      endpointURL: "https://s3.example.com"
      s3Credentials:
        accessKeyId: { name: s3-creds, key: ID }
        secretAccessKey: { name: s3-creds, key: SECRET }
      wal:
        compression: bzip2
    retentionPolicy: "30d"

  # Настройка TLS через cert-manager
  certificates:
    serverAltNames:
      - pg-main.example.com
    issuerRef:
      name: letsencrypt-prod
      kind: ClusterIssuer
```

### Шаг 3: Мониторинг и Observability

CNPG предоставляет встроенный экспортер метрик (совместимый с `postgres_exporter`).
1.  **PodMonitor:** Если `monitoring.enablePodMonitor: true`, оператор создаст ресурс для автоматического обнаружения подов Prometheus Operator-ом.
2.  **Dashboard:** Рекомендуется импортировать стандартный дашборд CNPG в Grafana (ID: 15129).

### Шаг 4: Операционные задачи

**Переключение Primary (Switchover):**
Безопасная передача роли мастера другому узлу для проведения тех. работ.
```bash
kubectl cnpg promote pg-main pg-main-2
# Или через автоматический выбор:
kubectl cnpg switchover pg-main
```

**Восстановление на момент времени (PITR):**
Создание нового кластера из бэкапа.
```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-restored
spec:
  bootstrap:
    recovery:
      source: pg-main
      recoveryTarget:
        targetTime: "2026-08-03 12:00:00"
```

## Дополнительная информация

### Выбор между CNPG и Zalando Operator

| Критерий | CloudNativePG | Zalando Operator |
| :--- | :--- | :--- |
| **Основа HA** | Native K8s API | Patroni + etcd/K8s API |
| **Бэкапы** | Barman (встроенный) | WAL-G (Sidecar) |
| **Сложность** | Низкая (Cloud Native) | Средняя (Legacy-friendly) |
| **Снапшоты** | Нативная поддержка | Через VolumeSnapshot в Spilo |

### Связанные документы
- **[Наблюдаемость PostgreSQL](./observability.md)** — глубокая интеграция с Grafana.
- **[Сетевая связность](./kubernetes_connectivity.md)** — работа с сервисами и Ingress.
- **[Zalando Postgres Operator](./zalando_postgres_operator.md)** — альтернативный подход.
- **[Backup and Recovery](../Concepts/backup_and_recovery.md)** — теория WAL и архивации.
