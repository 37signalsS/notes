# Установка Grafana Alloy в Kubernetes

## Определения

**Grafana Alloy** — универсальный агент для сбора и обработки телеметрии (метрики, логи, трассировки, профили). Использует декларативный язык конфигурации River, который позволяет строить сложные конвейеры обработки данных (DAG). Alloy является официальным преемником Promtail и Grafana Agent, обеспечивая нативную поддержку OpenTelemetry и бесшовную интеграцию со стеком Grafana (Loki, Mimir, Tempo, Phlare).

**Статус агентов (2026):**
- **Promtail:** В статусе Deprecated (с весны 2026). Поддержка ограничена критическими багфиксами.
- **Grafana Agent:** В статусе End-of-Life. Рекомендуется немедленная миграция на Alloy.
- **Grafana Alloy:** Стандарт индустрии для сбора телеметрии в гибридных и on-premise средах.

**Подробнее:** [Обзор Grafana Alloy](../../Grafana/grafana_alloy_overview.md)

## Основные концепции

### Архитектура развертывания в Kubernetes

| Режим | Тип контроллера | Назначение |
| :--- | :--- | :--- |
| **DaemonSet** | DaemonSet | Сбор системных логов (`/var/log/pods`), метрик нод (`node-exporter`) и eBPF данных. Один экземпляр на ноду. |
| **Deployment** | Deployment | Сбор метрик сервисов (Pull), прием OTLP трафика, работа в качестве OpenTelemetry Collector. Масштабируется через HPA. |
| **StatefulSet** | StatefulSet | Кластерный режим с сохранением состояния (WAL, кеши) и высокой доступностью. Используется при включенной кластеризации (gossip). |

### Выбор режима развертывания

| Критерий | DaemonSet | Deployment | StatefulSet |
| :--- | :--- | :--- | :--- |
| **Сбор логов подов** | Да | Нет | Нет |
| **Сбор метрик нод** | Да | Нет | Нет |
| **Прием OTLP от приложений** | Нет | Да | Да |
| **Сохранение состояния (WAL)** | Локальный PVC | Нет | PersistentVolumeClaim |
| **Кластеризация (gossip)** | Да (с overlaps) | Нет | Да (рекомендуется) |
| **Масштабирование** | Автоматически по нодам | HPA | Ручное/Operator |
| **Производительность** | Средняя | Высокая | Высокая (HA) |

### Язык конфигурации River

River базируется на блоках, аргументах и атрибутах. Основная ценность — динамическое обновление конфигурации без перезагрузки процесса (`hot reload`). Блок изменяется без остановки всего агента; неиспользуемые выходы игнорируются.

**Типовые стадии обработки (DAG):**
1. **Discovery:** Автоматическое обнаружение целей (Kubernetes API, статические списки).
2. **Scrape / Source:** Извлечение данных из целей.
3. **Transform / Relabel:** Изменение структуры, фильтрация, обогащение метаданными.
4. **Export / Write:** Отправка данных в один или несколько бэкендов.

**Подробнее о River, WAL, кластеризации и безопасности:** [Обзор Grafana Alloy](../../Grafana/grafana_alloy_overview.md)

### Structured Metadata в Loki 3.x

Alloy поддерживает передачу структурированных метаданных вместе с логами через параметр `allow_structured_metadata = true` в блоке `loki.write`. Это позволяет фильтровать логи по полям без создания тяжелых лейблов и раздувания индекса.

```river
loki.write "loki_backend" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
    allow_structured_metadata = true
  }
}
```

## Подготовка репозитория Helm

```bash
# Добавление официального репозитория Grafana
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Получение актуальных значений чарта
helm show values grafana/alloy > alloy_values.yaml
```

## Практические сценарии

### Сценарий 1: Сбор логов Kubernetes с поддержкой Loki 3.x

Использование структурированных метаданных для уменьшения кардинальности индекса.

**Конфигурация River:**

```river
// Обнаружение всех подов в кластере
discovery.kubernetes "all_pods" {
  role = "pod"
}

// Сбор логов
loki.source.kubernetes "container_logs" {
  targets    = discovery.kubernetes.all_pods.targets
  forward_to = [loki.process.add_metadata.receiver]
}

// Обработка и добавление структурированных метаданных (Loki 3.0+)
loki.process "add_metadata" {
  forward_to = [loki.write.loki_backend.receiver]

  stage.relabel {
    rule {
      source_labels = ["__meta_kubernetes_namespace"]
      target_label  = "namespace"
    }
    rule {
      source_labels = ["__meta_kubernetes_pod_name"]
      target_label  = "pod"
    }
    rule {
      source_labels = ["__meta_kubernetes_pod_labels_app"]
      target_label  = "app"
    }
  }
}

// Отправка данных
loki.write "loki_backend" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
    allow_structured_metadata = true
  }
}
```

**Валидация:**
```bash
# Проверка синтаксиса River
alloy fmt config.alloy
alloy lint config.alloy

# Проверка в Debug UI
kubectl port-forward svc/alloy 12345:12345
# → http://localhost:12345/graph — все компоненты должны быть в состоянии "Healthy"

# Проверка доставки логов в Loki
kubectl logs -l app.kubernetes.io/name=alloy -n logging --tail=20 | grep -i "loki.write"
```

### Сценарий 2: Авто-инструментирование через eBPF (Application Observability)

**Требования:** ядро Linux 5.8+ с BTF, привилегированный режим (CAP_SYS_ADMIN), доступ к `/proc` и `/sys`.

```river
// Сбор сетевых метрик без модификации кода
otelcol.receiver.ebpf "network_telemetry" {
  network_interface = "eth0"
  output {
    traces  = [otelcol.exporter.otlp.tempo.input]
    metrics = [otelcol.exporter.prometheus.mimir.input]
  }
}

// Отправка трейсов в Tempo
otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo-distributor.tracing.svc.cluster.local:4317"
    tls { insecure = true }
  }
}
```

**Валидация:**
```bash
# Проверка eBPF в Debug UI
curl -s http://localhost:12345/metrics | grep alloy_ebpf

# Проверка ядра
uname -r  # → 5.8+ с BTF
```

### Сценарий 3: Мультиарендность (Multi-tenancy)

Разделение потоков данных для разных команд через заголовки.

```river
loki.write "team_a" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
    headers = {
      "X-Scope-OrgID" = "team-alpha",
    }
  }
}

loki.write "team_b" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
    headers = {
      "X-Scope-OrgID" = "team-beta",
    }
  }
}
```

### Сценарий 4: Helm-установка DaemonSet (Production)

Установка Alloy как DaemonSet для сбора логов и метрик с всех нод кластера.

**Values (values-production.yaml):**

```yaml
# Режим развертывания
deployment:
  mode: DaemonSet

# Ресурсы и лимиты
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

# Хранилище для WAL
storage:
  path: /var/lib/alloy
  volumeClaimTemplate:
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "fast-ssd"
      resources:
        requests:
          storage: 10Gi

# Конфигурация River
configMap:
  content: |
    logging {
      level = "info"
      format = "logfmt"
    }

    discovery.kubernetes "pods" {
      role = "pod"
    }

    loki.source.kubernetes "pods" {
      targets    = discovery.kubernetes.pods.targets
      forward_to = [loki.write.default.receiver]
    }

    loki.write "default" {
      endpoint {
        url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
        allow_structured_metadata = true
      }
    }

# ServiceMonitor для Prometheus Operator
alloy:
  metrics:
    enabled: true
  serviceMonitor:
    enabled: true
    interval: 30s

# RBAC
controller:
  rbac:
    create: true
  serviceAccount:
    create: true
    name: "alloy-collector"

# Pod Disruption Budget
podDisruptionBudget:
  enabled: true
  minAvailable: 1
```

**Установка:**

```bash
helm upgrade --install alloy grafana/alloy \
  --namespace logging \
  --create-namespace \
  -f values-production.yaml
```

**Валидация:**
```bash
# Проверка статуса подов
kubectl get pods -n logging -l app.kubernetes.io/name=alloy

# Проверка DaemonSet
kubectl get daemonset -n logging alloy

# Проверка логов
kubectl logs -l app.kubernetes.io/name=alloy -n logging --tail=20

# Проверка Debug UI
kubectl port-forward svc/alloy 12345:12345 -n logging
curl -s http://localhost:12345/live
# → Healthy
```

### Сценарий 5: Production Deployment (OTLP/Metrics Collector)

Установка Alloy как Deployment для приема OTLP-трафика и сбора метрик сервисов.

```yaml
deployment:
  mode: Deployment
  replicas: 3

resources:
  requests:
    cpu: 200m
    memory: 256Mi
  limits:
    cpu: "1"
    memory: 1Gi

# Anti-affinity для распределения подов по разным нодам
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app.kubernetes.io/name: alloy
        topologyKey: kubernetes.io/hostname

# HPA для масштабирования
autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70

# PDB
podDisruptionBudget:
  enabled: true
  minAvailable: 2
```

### Сценарий 6: StatefulSet с кластеризацией (HA)

Для high availability с распределением нагрузки между узлами Alloy.

```yaml
deployment:
  mode: StatefulSet
  replicas: 3

# Headless Service для StatefulSet
service:
  headless:
    enabled: true
    clusterIP: None

# Кластеризация
alloy:
  clustering:
    enabled: true
    name: "alloy-prod"
    joinAddresses: ["alloy-0.alloy-headless.logging.svc.cluster.local:9094",
                    "alloy-1.alloy-headless.logging.svc.cluster.local:9094",
                    "alloy-2.alloy-headless.logging.svc.cluster.local:9094"]
    gossipInterval: "2s"

# Персистентное хранилище для WAL
storage:
  path: /var/lib/alloy
  volumeClaimTemplate:
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "fast-ssd"
      resources:
        requests:
          storage: 20Gi
```

### Сценарий 7: Сеть и безопасность (NetworkPolicy)

Изоляция сетевого трафика Alloy согласно принципу наименьших привилегий.

```yaml
# NetworkPolicy для Alloy
networkPolicy:
  enabled: true
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - protocol: TCP
          port: 12345
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 4318
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: logging
      ports:
        - protocol: TCP
          port: 3100
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - protocol: TCP
          port: 9090
        - protocol: TCP
          port: 4317
    - to: []
      ports:
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
```

### Сценарий 8: Миграция с Promtail на Alloy

Пошаговый план миграции без потери логов.

1. **Установка Alloy параллельно с Promtail:**
   ```bash
   helm install alloy grafana/alloy \
     --namespace logging \
     --set deployment.mode=DaemonSet \
     --set config.mapContent='...'
   ```

2. **Валидация сбора:** убедиться, что логи поступают в Loki от обоих агентов.

3. **Конвертация конфигурации:**
   ```bash
   alloy convert --source-format=promtail --output=config.alloy promtail-config.yaml
   alloy lint config.alloy
   ```

4. **Удаление Promtail:**
   ```bash
   helm uninstall promtail -n logging
   ```

**Важно:** Проверьте, что `external_labels` и `__meta_*` лейблы совпадают, чтобы избежать разрыва исторических данных в Loki (создания новых потоков).

### Сценарий 9: Мониторинг Alloy

Сбор метрик самого Alloy через ServiceMonitor.

```yaml
# values.yaml
alloy:
  metrics:
    enabled: true
  serviceMonitor:
    enabled: true
    namespace: monitoring
    interval: 30s
    scrapeTimeout: 10s
    labels:
      release: kube-prometheus-stack
```

**Ключевые метрики:**

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `alloy_component_healthy` | Состояние компонентов River | 0 (не healthy) |
| `alloy_build_info` | Версия и информация о сборке | — |
| `alloy_cluster_peers` | Число узлов в кластере | 1 при единственном узле |
| `alloy_process_resident_memory_bytes` | Потребление памяти процессом | > 80% лимита |
| `alloy_wal_segment` | Сегменты WAL | Рост без ограничений |
| `up{job="alloy"}` | Доступность агента | 0 (недоступен) |

### Сценарий 10: Резервное копирование и восстановление

**Бэкап конфигурации:**

```bash
# Получение текущих значений Helm
helm get values alloy -n logging > alloy-backup-$(date +%Y%m%d).yaml

# Экспорт конфигурации River
kubectl get configmap -n logging alloy-config -o yaml > alloy-config-backup.yaml
```

**Бэкап WAL (при использовании кластеризации):**

WAL размещается на PersistentVolume. Бэкап PV через инструменты CSI или snapshot:

```bash
# Создание snapshot PVC
kubectl snapshot volume alloy-alloy-0 -n logging
```

**Восстановление:**

```bash
# Восстановление из Helm-бэкапа
helm upgrade --install alloy grafana/alloy \
  --namespace logging \
  -f alloy-backup-20260914.yaml

# Проверка
kubectl get pods -n logging -l app.kubernetes.io/name=alloy
```

### Сценарий 11: Обновление и откат

**Обновление:**

```bash
# Обновление чарта
helm repo update
helm upgrade alloy grafana/alloy \
  --namespace logging \
  -f values-production.yaml \
  --atomic --timeout 5m
```

**Откат:**

```bash
# Просмотр истории релизов
helm history alloy -n logging

# Откат на предыдущую ревизию
helm rollback alloy 1 -n logging

# Валидация после отката
kubectl get pods -n logging -l app.kubernetes.io/name=alloy
kubectl logs -l app.kubernetes.io/name=alloy -n logging --tail=20
```

## Безопасность и права доступа (RBAC)

Для работы Discovery Alloy требуются права на чтение ресурсов Kubernetes API.

**Минимальные права (least-privilege):**

```yaml
# values.yaml
controller:
  rbac:
    create: true
    rules:
      - apiGroups: [""]
        resources: ["pods", "nodes", "namespaces"]
        verbs: ["get", "list", "watch"]
      - apiGroups: [""]
        resources: ["pods/log"]
        verbs: ["get", "list"]
```

По умолчанию Alloy запрашивает доступ к `pods`, `nodes`, `services`, `endpoints`, `configmaps`. Для eBPF необходимо дополнительно включить `privileged: true` в `securityContext`.

**Секреты:**
- Не храните пароли и токены в открытом виде в `config.alloy`.
- Используйте `sys.env("LOKI_PASSWORD")` для интерполяции переменных окружения.
- Монтируйте секреты через Kubernetes Secret Volume.
- Для шифрования литералов используйте `alloy secrets encrypt`.

## Мониторинг и эксплуатация

### Интеграция с Prometheus Operator

```yaml
# values.yaml
alloy:
  metrics:
    enabled: true
  serviceMonitor:
    enabled: true
    interval: 30s
    scrapeTimeout: 10s
    labels:
      release: kube-prometheus-stack
```

### Проверка работоспособности

1. **UI отладки:** `kubectl port-forward svc/alloy 12345:12345 -n logging`.
   - `Graph`: Визуализация DAG и связей компонентов.
   - `Status`: Здоровье каждого отдельного блока River.
   - `/live`: Проверка живости агента.
   - `/metrics`: Метрики в формате Prometheus.
2. **Проверка логов:** `kubectl logs -l app.kubernetes.io/name=alloy -n logging -f`.

### Диагностика

| Ошибка | Возможная причина | Путь решения |
| :--- | :--- | :--- |
| **Component unhealthy** | Ошибка в аргументах блока (неверный URL, отсутствует `forward_to`) | Проверьте UI (вкладка Status) — там будет детальное описание ошибки. |
| **OOMKilled** | Слишком много целей в discovery или большой объем логов в памяти | Увеличьте `memory.limits` или используйте `clustering` для распределения нагрузки. |
| **Permission denied (eBPF)** | Недостаточно прав у контейнера | Убедитесь, что установлены `privileged: true` и нужные `capabilities`. |
| **WAL растёт / диск заполняется** | Бэкенд недоступен длительное время | Разместите WAL на отдельном PVC; проверьте сеть до бэкенда. |
| **429 / rate limit** | Превышение лимита приёма Loki/Mimir | Настройте батчинг (`batch`/`queue`), согласуйте лимиты с админом бэкенда. |
| **Clustering split-brain** | Нестабильный gossip, неверные `join_addresses` | Используйте стабильные адреса `:9094`, проверьте `gossip_interval`. |

## Базовое масштабирование

### Горизонтальное масштабирование (HPA)

```yaml
autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
```

### Вертикальное масштабирование

```bash
# Изменение ресурсов через Helm
helm upgrade alloy grafana/alloy \
  --namespace logging \
  --set resources.limits.memory=1Gi \
  --set resources.limits.cpu=1
```

### Проверка балансировки

```bash
# Список подов
kubectl get pods -n logging -l app.kubernetes.io/name=alloy

# Проверка распределения по нодам
kubectl get pods -n logging -l app.kubernetes.io/name=alloy -o wide

# Проверка метрик кластеризации
kubectl port-forward svc/alloy 12345:12345 -n logging
curl -s http://localhost:12345/metrics | grep alloy_cluster_peers
```

## Ограничения и особые случаи

- **Семантика at-least-once:** при сбоях возможны дубликаты метрик/логов/трасс. На стороне Loki это решается идемпотентностью Push API.
- **Динамическая перезагрузка** пересоздаёт изменившиеся компоненты; in-memory состояние (локальные счётчики агрегаторов) сбрасывается.
- **eBPF** доступен только на Linux с BTF; на macOS/Windows не поддерживается.
- **Кластеризация** требует стабильной сети и явных `join_addresses`; авто-discovery peers ограничен.
- **WAL растёт неограниченно** при долгой недоступности бэкенда. Размещайте WAL на отдельном PVC с достаточным размером.
- **Порядок загрузки компонентов** определяется графом, а не позицией в файле.

## Полезные команды

```bash
# Проверка синтаксиса River
alloy fmt config.alloy
alloy lint config.alloy

# Dry-run без запуска
alloy run --dry-run /etc/alloy/config.alloy

# Статус DaemonSet
kubectl rollout status daemonset/alloy -n logging

# Просмотр логов
kubectl logs -l app.kubernetes.io/name=alloy -n logging --tail=100

# Debug UI
kubectl port-forward svc/alloy 12345:12345 -n logging

# Проверка метрик
curl -s http://localhost:12345/metrics | grep alloy_

# Проверка живости
curl -s http://localhost:12345/live
# → Healthy

# История Helm-релизов
helm history alloy -n logging
```

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Grafana Alloy](../../Grafana/grafana_alloy_overview.md) | Архитектура, River, WAL, кластеризация, безопасность |
| [Установка Loki](loki_installation.md) | Настройка бэкенда для приема логов от Alloy |
| [Примеры LogQL](logql_examples.md) | Язык запросов для анализа логов, собранных Alloy |
| [Миграция с Promtail](https://grafana.com/docs/alloy/latest/tasks/migrate/from-promtail/) | Пошаговое руководство по переходу на River |
| [Alloy на Minikube](../../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_lgtm_stack_deployment.md) | Полный цикл развертывания в тестовой среде |
