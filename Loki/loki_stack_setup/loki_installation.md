# Установка Loki в Kubernetes

## Определения

**Loki Helm-чарт** — официальный пакет для автоматизированного развертывания Grafana Loki в Kubernetes. Начиная с версии 3.x, чарт поддерживает три основных режима: Single Binary (монолит), Simple Scalable (масштабируемый) и Distributed (микросервисный). Основной упор сделан на производительности запросов и поддержке нативного поиска по Bloom-фильтрам.

**Мультиарендность (Multi-tenancy)** — режим работы Loki, позволяющий изолировать данные разных команд (тенантов) в рамках одного кластера. Идентификация происходит по HTTP-заголовку `X-Scope-OrgID`.

**Важное замечание (март 2026):** Репозиторий `grafana https://grafana.github.io/helm-charts` переведен в режим обслуживания. Актуальный чарт Loki теперь находится в репозитории `grafana-community`.

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update
```

**Текущая версия (август 2026):** Loki 3.x (стабильная), Helm-чарт 6.60.x+

**Подробнее:** [Обзор Grafana Loki](../loki_overview.md)

## Основные концепции

### Режимы развертывания

| Режим | Компоненты | Назначение |
| :--- | :--- | :--- |
| **Single Binary** | Все компоненты в одном поде | Тестирование, разработка, малые нагрузки (< 10 ГБ/день) |
| **Simple Scalable** | Группировка: Read, Write и Backend | Рекомендуемый режим для Production средних и крупных масштабов |
| **Distributed** | Каждый микросервис (Ingester, Querier, Distributor, Querier-Frontend и др.) отдельно | Экстремальные нагрузки, требующие независимого масштабирования |

### Архитектура Simple Scalable (рекомендуемый режим)

В этом режиме компоненты группируются по типам нагрузки. Gateway (Nginx) выступает единой точкой входа, маршрутизируя трафик:
-   **Write таргет:** Distributor → Ingester (запись в хранилище).
-   **Read таргет:** Query Frontend → Querier (чтение из хранилища и кешей).
-   **Backend таргет:** Compactor, Ruler, Index Gateway (обслуживание индекса и правил).

```
┌─────────┐     ┌──────────┐     ┌─────────┐
│ Gateway │────→│  Write   │────→│ Storage │
│ (Nginx) │     │ (Ingester)│     │  (S3)   │
└────┬────┘     └──────────┘     └─────────┘
     │
     │     ┌──────────┐     ┌─────────┐
     └────→│   Read   │────→│  Cache  │
           │(Querier) │     │ (Redis) │
           └──────────┘     └─────────┘
           ┌──────────┐
           │ Backend  │
           │(Compactor)│
           └──────────┘
```

### Ключевые особенности Loki 3.x

1.  **Bloom Filters:** Позволяют ускорить поиск по неиндексированным данным (grep-подобный поиск) до 10-50 раз за счет отсечения чанков, не содержащих искомые токены.
2.  **Structured Metadata:** Поддержка прикрепления метаданных к строкам логов на стороне агента (например, Alloy), что позволяет фильтровать логи без создания "тяжелых" лейблов и раздувания индекса.
3.  **TSDB Index:** Основной формат индекса, обеспечивающий высокую плотность хранения, быструю загрузку и поддержку Bloom-фильтров.

## Практические сценарии

### Подготовка репозитория Helm

```bash
# Добавление актуального репозитория
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Получение стандартных значений для анализа
helm show values grafana-community/loki > loki_values.yaml
```

### Сценарий 1: Production — Simple Scalable с S3 и Bloom-фильтрами

Обеспечивает высокую доступность и производительность для средних и больших нагрузок.

**Файл `loki_values.yaml`:**

```yaml
deploymentMode: SimpleScalable

loki:
  auth_enabled: true # Включение мультиарендности

  storage:
    type: s3
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
      admin: loki-admin
    s3:
      endpoint: s3.amazonaws.com
      region: us-east-1
      secretAccessKey: ${S3_SECRET_KEY}
      accessKeyId: ${S3_ACCESS_KEY}

  commonConfig:
    replication_factor: 3

  schemaConfig:
    configs:
      - from: "2024-01-01"
        store: tsdb
        object_store: s3
        schema: v13
        index:
          prefix: index_
          period: 24h

  # Настройка Bloom-фильтров (ускорение поиска)
  bloom_build_config:
    enabled: true
  bloom_gateway:
    enabled: true

  limits_config:
    retention_period: 744h  # 31 день
    max_query_series: 5000
    allow_structured_metadata: true

# Мониторинг Loki (требуется установленный Prometheus Operator)
monitoring:
  dashboards:
    enabled: true
  serviceMonitor:
    enabled: true
  selfMonitoring:
    enabled: false # Рекомендуется использовать внешний Prometheus stack

# Масштабирование компонентов
write:
  replicas: 3
  resources:
    requests:
      cpu: 1
      memory: 2Gi
    limits:
      cpu: 2
      memory: 4Gi

read:
  replicas: 3
  resources:
    requests:
      cpu: 1
      memory: 4Gi
    limits:
      cpu: 4
      memory: 8Gi

backend:
  replicas: 2
  persistence:
    enabled: true
    size: 10Gi # Для локального кеша индекса

gateway:
  enabled: true
  replicas: 2
```

### Сценарий 2: Тестирование — Single Binary с локальным хранилищем

Минимальное потребление ресурсов для разработки.

```yaml
deploymentMode: SingleBinary

loki:
  auth_enabled: false # Отключено для упрощения тестов
  storage:
    type: filesystem
  commonConfig:
    replication_factor: 1
  schemaConfig:
    configs:
      - from: "2024-01-01"
        store: tsdb
        object_store: filesystem
        schema: v13

singleBinary:
  replicas: 1
  persistence:
    enabled: true
    size: 10Gi

gateway:
  enabled: true
```

### Сценарий 3: Настройка безопасности и доступа

Для работы с включенной мультиарендностью (`auth_enabled: true`), все запросы должны содержать заголовок `X-Scope-OrgID`.

1.  **На стороне агента (Alloy):**
    ```river
    loki.write "default" {
      endpoint {
        url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
        headers = {
          "X-Scope-OrgID" = "team-alpha",
        }
      }
    }
    ```
2.  **На стороне Grafana:**
    В настройках DataSource необходимо добавить пользовательский HTTP заголовок `X-Scope-OrgID: team-alpha`.

### Установка в кластер

```bash
# Рекомендуется использовать sops или helm-secrets для S3 ключей
helm upgrade --install loki grafana-community/loki \
  --namespace logging \
  --create-namespace \
  -f loki_values.yaml \
  --wait --atomic
```

### Проверка работоспособности

```bash
# Просмотр статуса всех компонентов
kubectl get pods -n logging -l app.kubernetes.io/name=loki

# Проверка логов записи (Distributor/Ingester)
kubectl logs -n logging -l app.kubernetes.io/component=write -f

# Проверка метрик (если включен ServiceMonitor)
kubectl get servicemonitor -n logging
```

### Сценарий 4: Локальная установка (Binary) на Linux

Минималистичный способ запуска Loki без использования контейнеров, подходящий для отладки или малых систем.

**1. Загрузка и подготовка бинарного файла:**

```bash
# Загрузка актуальной версии с GitHub Releases
curl -O -L "https://github.com/grafana/loki/releases/download/v3.1.1/loki-linux-amd64.zip"

# Распаковка
unzip loki-linux-amd64.zip
chmod +x loki-linux-amd64
```

**2. Конфигурация:**

Для быстрого старта можно скачать пример конфигурации:
```bash
wget https://raw.githubusercontent.com/grafana/loki/main/cmd/loki/loki-local-config.yaml
```

**Основные параметры в `loki-local-config.yaml`:**
*   **Порты:** `3100` (HTTP для API и метрик), `9096` (gRPC для взаимодействия компонентов).
*   **Хранилище:** По умолчанию используется локальная файловая система (`filesystem`). Чанки логов сохраняются в `/tmp/loki/chunks`.

**3. Запуск:**

```bash
./loki-linux-amd64 -config.file=loki-local-config.yaml
```

**4. Верификация:**

Если сервер запущен успешно, эндпоинт метрик должен вернуть данные:
```bash
curl http://localhost:3100/metrics
# → Ожидается вывод метрик в формате Prometheus
```

### Сценарий 5: Быстрый старт через Umbrella Chart (loki-stack)

Используется для быстрого развертывания полного стека (Loki + Prometheus + Grafana + Promtail) в демонстрационных или тестовых целях.

**1. Подготовка репозитория:**
```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

**2. Настройка `values.yaml`:**
В этом чарте Grafana по умолчанию отключена. Для активации создайте файл:
```yaml
# custom-stack-values.yaml
grafana:
  enabled: true
  image:
    tag: latest # Или конкретная версия, например 11.x
promtail:
  enabled: true
```

**3. Установка:**
```bash
helm install loki-stack grafana/loki-stack --values custom-stack-values.yaml
```

**4. Доступ к Grafana:**
По умолчанию используется `ClusterIP`. Для доступа используйте Port-forward:
```bash
kubectl port-forward deployment/loki-stack-grafana 3000:3000
```

**5. Получение пароля администратора:**
Логин по умолчанию: `admin`. Пароль генерируется автоматически и хранится в секрете:
```bash
kubectl get secret loki-stack-grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

**Преимущество:** Loki автоматически добавляется как источник данных (DataSource) в Grafana, ручная настройка URL не требуется.

### Диагностика типичных ошибок

| Ошибка | Возможная причина | Путь решения |
| :--- | :--- | :--- |
| **Pending Pods** | Недостаточно ресурсов или проблемы с PVC | Проверьте `kubectl describe pod`. Убедитесь, что StorageClass поддерживает динамическое выделение. |
| **401 Unauthorized** | Включен `auth_enabled`, но отсутствует заголовок | Добавьте `X-Scope-OrgID` в настройки агента и Grafana. |
| **Invalid Schema** | Версия схемы не соответствует версии Loki | Для Loki 3.x используйте `v13` и `store: tsdb`. |
| **High Ingestion Latency** | Недостаточно реплик `write` или медленный S3 | Увеличьте количество реплик `write`, проверьте лимиты CPU. |
| **Bloom filter missing** | Bloom-фильтры не успели построиться | Построение фильтров происходит с задержкой после записи данных (настраивается в `bloom_build_config`). |

### Полезные команды для эксплуатации

```bash
# Просмотр текущей конфигурации
helm get values loki -n logging

# Проверка состояния индекса через API (требуется port-forward к gateway)
curl -G -H "X-Scope-OrgID: fake" http://localhost:3100/loki/api/v1/status/buildinfo
```

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Loki](../loki_overview.md) | Архитектура, принципы работы и сравнение с ELK |
| [Установка Grafana](grafana_installation.md) | Настройка источника данных и дашбордов |
| [Примеры LogQL](logql_examples.md) | Практическое руководство по языку запросов |
| [Установка Alloy](alloy_installation.md) | Настройка современного агента сбора логов |
| [Loki на Minikube](../../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_lgtm_stack_deployment.md) | Практическое руководство по развертыванию полного стека |
| [Документация по Bloom-фильтрам](https://grafana.com/docs/loki/latest/operations/bloom-filters/) | Детальная настройка ускорения запросов |

