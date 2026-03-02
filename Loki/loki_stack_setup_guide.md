# Настройка стека Loki в Kubernetes

## 1. Определения

Для ознакомления с определениями, архитектурой, языком запросов LogQL и другими базовыми концепциями обратитесь к основному источнику знаний: **[Обзор Grafana Loki](./loki_overview.md)**.

## 2. Практические сценарии

### Подготовка: Добавление Helm-репозитория

Добавьте официальный Helm-репозиторий Grafana, который содержит чарты для всех компонентов стека:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

> **Примечание:** На март 2026 актуальные версии чартов: `loki-5.x.x`, `promtail-6.x.x`, `grafana-8.x.x`. Проверяйте актуальные версии через `helm search repo grafana`.

### ⚠️ Важное замечание о Promtail

**Promtail находится в статусе deprecated (весна 2026).** Для новых развертываний рекомендуется использовать **Grafana Alloy**.

| Агент | Статус | Helm-чарт |
| :--- | :--- | :--- |
| **Grafana Alloy** | ✅ Рекомендовано | `grafana/alloy` |
| **Promtail** | ⚠️ Deprecated | `grafana/promtail` |

В данном руководстве показана настройка Promtail для совместимости с существующими развертываниями. Для настройки Alloy см. раздел [Альтернатива: Grafana Alloy](#альтернатива-grafana-alloy) и [Grafana Alloy](../Grafana/grafana_alloy_overview.md).

### Установка Loki

Loki будет использоваться для хранения и индексации логов.

#### Настройка Values для Loki

Сохраним стандартные `values` для дальнейшей кастомизации:

```bash
helm show values grafana/loki > loki_values.yaml
```

**Актуальные параметры для Loki 3.x (март 2026):**

| Параметр | Описание | Рекомендуемое значение |
| :--- | :--- | :--- |
| **`loki.storage.type`** | Тип хранилища | `s3`, `gcs`, `azure`, `filesystem` |
| **`loki.storage.bucketNames.chunks`** | Bucket для чанков | `loki-chunks` |
| **`loki.storage.bucketNames.ruler`** | Bucket для правил | `loki-ruler` |
| **`loki.storage.bucketNames.admin`** | Bucket для конфигураций | `loki-admin` |
| **`deploymentMode`** | Режим развертывания | `SimpleScalable` (рекомендуется) |
| **`loki.commonConfig.replication_factor`** | Фактор репликации | `3` (для HA) |
| **`read.replicas`** | Реплики для чтения | `2` |
| **`write.replicas`** | Реплики для записи | `2` |
| **`backend.replicas`** | Реплики бэкенда | `2` |

**Пример `loki_values.yaml` для production:**

```yaml
# loki_values.yaml
deploymentMode: SimpleScalable

loki:
  storage:
    type: s3
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
      admin: loki-admin
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

read:
  replicas: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1000m
      memory: 2Gi

write:
  replicas: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1000m
      memory: 2Gi

backend:
  replicas: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1000m
      memory: 2Gi

gateway:
  enabled: true
  replicas: 2

monitoring:
  dashboards:
    enabled: true
  rules:
    enabled: true
  serviceMonitor:
    enabled: true
```

> **Примечание:** Схема `v13` с хранилищем `tsdb` — актуальная схема для Loki 3.x. Для тестовых сред можно использовать `filesystem` вместо `s3`.

#### Установка Loki

Установим Loki с помощью Helm в `logging` namespace:

```bash
helm upgrade --install loki grafana/loki \
  --namespace logging \
  -f loki_values.yaml
```

Проверьте статус подов:

```bash
kubectl get pods -n logging -l app.kubernetes.io/name=loki
```

### Установка Promtail

> **⚠️ Важно:** Promtail deprecated. Для новых развертываний используйте [Grafana Alloy](#альтернатива-grafana-alloy).

Promtail — это агент для сбора логов, который будет работать как DaemonSet на каждой ноде кластера и отправлять логи в Loki.

#### Настройка Values для Promtail

Сохраним `values` для чарта `grafana/promtail`:

```bash
helm show values grafana/promtail > promtail_values.yaml
```

**Актуальные параметры для Promtail 6.x (март 2026):**

| Параметр | Описание | Рекомендуемое значение |
| :--- | :--- | :--- |
| **`config.lokiAddress`** | Адрес Loki | `http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push` |
| **`tolerations`** | Толерации для всех нод | `- operator: "Exists"` |
| **`serviceMonitor.enabled`** | ServiceMonitor для Prometheus | `true` |
| **`config.snippets.scrape_configs`** | Кастомизация scrape_configs | См. ниже |

**Пример `promtail_values.yaml`:**

```yaml
# promtail_values.yaml
config:
  lokiAddress: http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push
  
  snippets:
    scrape_configs:
      - job_name: kubernetes-pods
        kubernetes_sd_configs:
          - role: pod
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
            action: keep
            regex: true
          - source_labels: [__meta_kubernetes_pod_namespace]
            target_label: namespace
          - source_labels: [__meta_kubernetes_pod_name]
            target_label: pod
          - source_labels: [__meta_kubernetes_pod_container_name]
            target_label: container

# Толерации для запуска на всех нодах (включая master)
tolerations:
  - operator: "Exists"

# ServiceMonitor для мониторинга самого Promtail
serviceMonitor:
  enabled: true
  namespace: logging
  labels:
    release: prometheus
```

#### Установка Promtail

Установим Promtail, применив измененные `values`:

```bash
helm upgrade --install promtail grafana/promtail \
  --namespace logging \
  -f promtail_values.yaml
```

Проверьте поды:

```bash
kubectl get pods -n logging -l app.kubernetes.io/name=promtail -o wide
```

### Установка Grafana

Grafana будет использоваться для визуализации и анализа логов из Loki.

#### Настройка Values для Grafana

Сохраним `values` для чарта `grafana/grafana`:

```bash
helm show values grafana/grafana > grafana_values.yaml
```

**Актуальные параметры для Grafana 10.x/11.x (март 2026):**

| Параметр | Описание | Рекомендуемое значение |
| :--- | :--- | :--- |
| **`ingress.enabled`** | Включить Ingress | `true` (для доступа извне) |
| **`ingress.hosts`** | Хосты для Ingress | `["grafana.example.com"]` |
| **`adminPassword`** | Пароль admin | Используйте secrets! |
| **`datasources`** | Источники данных | Loki, Prometheus |
| **`persistence.enabled`** | Персистентность | `true` |
| **`serviceMonitor.enabled`** | ServiceMonitor | `true` |

**Пример `grafana_values.yaml`:**

```yaml
# grafana_values.yaml
ingress:
  enabled: true
  hosts:
    - grafana.example.com
  annotations:
    kubernetes.io/ingress.class: nginx
  tls:
    - secretName: grafana-tls
      hosts:
        - grafana.example.com

admin:
  existingSecret: grafana-admin-secret
  userKey: admin-user
  passwordKey: admin-password

datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Loki
        type: loki
        access: proxy
        orgId: 1
        url: http://loki-gateway.logging.svc.cluster.local:80
        isDefault: true
        version: 1
        editable: false
      - name: Prometheus
        type: prometheus
        access: proxy
        orgId: 1
        url: http://prometheus-server.monitoring.svc.cluster.local:80
        version: 1
        editable: false

persistence:
  enabled: true
  size: 10Gi
  storageClassName: standard

serviceMonitor:
  enabled: true
  namespace: logging
  labels:
    release: prometheus
```

> **Безопасность:** Не указывайте пароли в plain text. Используйте Kubernetes Secrets:
> ```bash
> kubectl create secret generic grafana-admin-secret \
>   --from-literal=admin-user="admin" \
>   --from-literal=admin-password="$(openssl rand -base64 20)" \
>   -n logging
> ```

#### Установка Grafana

Установим Grafana с настроенным Ingress и источником данных Loki:

```bash
helm upgrade --install grafana grafana/grafana \
  --namespace logging \
  -f grafana_values.yaml
```

#### Доступ к Grafana

После успешного запуска пода Grafana вы сможете получить доступ к веб-интерфейсу по адресу, указанному в `Ingress` (например, `https://grafana.example.com`). Войдите с логином `admin` и паролем из секрета.

### Работа с логами в Grafana

После установки стека можно приступать к анализу логов в Grafana.

#### Подключение Loki как источника данных (вручную)

Если вы не настроили `datasource` через `values.yaml` при установке Grafana, его можно добавить вручную:

1. Перейдите в **Connections** → **Data sources**.
2. Нажмите **Add data source** и выберите **Loki**.
3. В поле **URL** укажите адрес сервиса Loki:
   - Если Grafana и Loki в одном namespace: `http://loki:3100`
   - Если в разных namespaces: `http://loki-gateway.logging.svc.cluster.local:80`
4. Нажмите **Save & Test**.

#### Примеры LogQL запросов для Kubernetes

| Задача | LogQL запрос |
| :--- | :--- |
| **Все логи из namespace** | `{namespace="ingress-nginx"}` |
| **Логи конкретного пода** | `{pod="my-app-pod-12345"}` |
| **Поиск ошибок в Java-приложении** | `{app="my-java-app"} \|= "Exception"` |
| **Логи с уровнем ERROR** | `{app="my-app"} \|~ "(?i)error"` |
| **Парсинг JSON-логов** | `{app="my-app"} \| json` |
| **Фильтр по полю JSON** | `{app="my-app"} \| json \| status_code >= 500` |
| **Rate ошибок за 5 минут** | `sum(rate({app="my-app"} \|~ "error" [5m]))` |
| **Топ контейнеров по логам** | `topk(5, count_over_time({namespace="default"}[1h]))` |

> **Подробнее о LogQL:** [loki_overview.md](./loki_overview.md#язык-запросов-logql)

### Альтернатива: Grafana Alloy

Для новых развертываний рекомендуется использовать **Grafana Alloy** вместо Promtail.

#### Установка Alloy

```bash
helm show values grafana/alloy > alloy_values.yaml
```

**Пример `alloy_values.yaml`:**

```yaml
# alloy_values.yaml
alloy:
  configMap:
    create: true
    content: |
      // Сбор логов из подов Kubernetes
      discovery.kubernetes "pods" {
        role = "pod"
      }

      loki.source.kubernetes "pods" {
        targets    = discovery.kubernetes.pods.targets
        forward_to = [loki.write.default.receiver]
      }

      // Отправка в Loki
      loki.write "default" {
        endpoint {
          url = "http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push"
        }
      }

controller:
  type: daemonset  # DaemonSet для сбора логов со всех нод

tolerations:
  - operator: "Exists"
```

#### Установка Alloy

```bash
helm upgrade --install alloy grafana/alloy \
  --namespace logging \
  -f alloy_values.yaml
```

> **Преимущества Alloy:**
> - Универсальный агент (метрики + логи + трассировки)
> - Активная разработка и поддержка
> - Конвертеры конфигураций с Promtail/Grafana Agent
> - Язык конфигурации River (декларативный, похож на Terraform)
>
> **Подробнее:** [Grafana Alloy](../Grafana/grafana_alloy_overview.md)
