# Kubespray: Сбор логов в Kubernetes

## Определения

**Централизованный сбор логов (Centralized Logging)** — процесс агрегации логов со всех узлов и подов кластера в единое хранилище для анализа, мониторинга и аудита. В Kubernetes логи являются эфемерными (хранятся на узле до перезапуска пода), поэтому требуют внешнего сбора.

**Loki** — горизонтально масштабируемая система агрегации логов от Grafana Labs, которая индексирует только метаданные (метки), а не полный текст логов. Это позволяет значительно снизить затраты на хранение по сравнению с полнотекстовыми поисковыми системами (ELK).

**Alloy** — современный агент сбора телеметрии от Grafana Labs, заменяющий Promtail и другие специализированные агенты. Поддерживает сбор метрик, логов и трассировок в едином агенте.

**Fluent Bit** — легковесный агент сбора и пересылки логов, оптимизированный для контейнерных сред. Используется как альтернатива Alloy.

**LogQL** — язык запросов Loki для фильтрации и анализа логов, аналогичный PromQL для Prometheus.

**Structured Logging** — подход к форматированию логов в машиночитаемом формате (JSON), упрощающий парсинг и фильтрацию.

---

## Основные концепции

### Архитектура сбора логов в Kubespray

Kubespray не включает компоненты сбора логов в состав базовой установки. Рекомендуется устанавливать их отдельно через Helm после развертывания кластера.

```text
┌─────────────────────────────────────────────────────────────┐
│                      Kubernetes кластер                      │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Pod A     │  │   Pod B     │  │   Pod C     │         │
│  │  (stdout)   │  │  (stdout)   │  │  (stdout)   │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         ▼                ▼                ▼                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Alloy / Fluent Bit (DaemonSet)          │   │
│  │         Собирает логи со всех узлов                  │   │
│  └──────────────────────────┬──────────────────────────┘   │
│                             │                              │
│                             ▼                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    Loki (Backend)                    │   │
│  │         Хранение и индексация логов                  │   │
│  └──────────────────────────┬──────────────────────────┘   │
│                             │                              │
│                             ▼                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                   Grafana (UI)                       │   │
│  │         Визуализация и алертинг                      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Место хранения логов в Kubernetes

| Источник | Путь на узле | Описание |
| :--- | :--- | :--- |
| **System logs** | `/var/log/syslog`, `/var/log/kern.log` | Логи ОС и ядра |
| **Kubelet** | `/var/log/kubelet.log` | Логи kubelet |
| **Container logs** | `/var/log/containers/*.log` | Симлинки на логи контейнеров |
| **etcd** | `/var/log/etcd.log` | Логи etcd (если выделены) |
| **Audit logs** | `/var/log/kubernetes/audit/audit.log` | Логи аудита API |

### Логирование в Kubespray

Kubespray не предоставляет встроенных переменных для настройки сбора логов. Существует два подхода:

1. **Установка через Helm (рекомендуется):** После развертывания кластера устанавливаются Loki + Alloy через Helm-чарты. Этот подход не зависит от версий Kubespray и позволяет использовать актуальные версии компонентов.

2. **Настройка через Ansible-роли (продвинутый):** Создание кастомных Ansible-ролей, которые добавляют DaemonSet для сбора логов. Требует модификации Kubespray или использования внешних ролей.

### Сравнение агентов сбора логов

| Агент | Размер | CPU/RAM | Поддержка Loki | Поддержка Prometheus | Рекомендация |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Alloy** | ~50 МБ | Низкий | Да | Да | Рекомендуется для новых систем |
| **Fluent Bit** | ~10 МБ | Очень низкий | Да (плагин) | Да | Для ресурсно-ограниченных сред |
| **Promtail** | ~30 МБ | Средний | Да | Нет | Устарел, не рекомендуется |

---

## Практические сценарии

### 1. Установка Loki через Helm

Loki является бэкендом для хранения и индексации логов.

**Установка:**

```bash
# Добавление репозитория
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Создание неймспейса
kubectl create namespace logging

# Установка Loki (单实例 для dev/test)
helm install loki grafana-community/loki \
  --namespace logging \
  --set persistence.enabled=true \
  --set persistence.size=10Gi \
  --set auth.enabled=false
```

**Конфигурация для production (множественные реплики):**

```yaml
# loki-values.yaml
loki:
  auth_enabled: false
  commonConfig:
    replication_factor: 3
  storage:
    type: filesystem
  schemaConfig:
    configs:
    - from: "2024-01-01"
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: loki_index_
        period: 24h

singleBinary:
  replicas: 3

read:
  replicas: 2
  persistence:
    size: 10Gi

write:
  replicas: 3
  persistence:
    size: 20Gi

gateway:
  enabled: true

monitoring:
  dashboards:
    enabled: true
  serviceMonitor:
    enabled: true
```

**Установка с production-конфигурацией:**

```bash
helm install loki grafana-community/loki \
  --namespace logging \
  -f loki-values.yaml
```

**Валидация:**

```bash
# Проверка подов
kubectl get pods -n logging
# → NAME                                     READY   STATUS    RESTARTS   AGE
# → loki-0                                   1/1     Running   0          5m
# → loki-1                                   1/1     Running   0          5m
# → loki-2                                   1/1     Running   0          5m
# → loki-gateway-xxxxxxxxx-xxxxx             1/1     Running   0          5m

# Проверка доступности
kubectl port-forward -n logging svc/loki 3100:3100
curl http://localhost:3100/ready
# → ready

# Проверка метрик
curl http://localhost:3100/metrics | head -5
```

### 2. Установка Alloy (агент сбора логов)

Alloy заменяет Promtail и другие агенты, обеспечивая единый пайплайн для метрик и логов.

**Установка:**

```bash
# Добавление репозитория
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Установка Alloy
helm install alloy grafana/alloy \
  --namespace logging \
  --set alloy.configFromString="
    loki.source.kubernetes \"all\" {
      forward_to = [loki.write.default.receiver]
    }
    loki.write \"default\" {
      endpoint {
        url = \"http://loki.logging.svc.cluster.local:3100/loki/api/v1/push\"
      }
    }
  "
```

**Конфигурация с фильтрацией (prod-values.yaml):**

```yaml
alloy:
  configFromString: |
    // Сбор логов со всех подов
    loki.source.kubernetes "all" {
      forward_to = [loki.process.add_metadata.receiver]
    }

    // Добавление метаданных
    loki.process "add_metadata" {
      stage.labels {
        values = {
          "namespace" = "",
          "pod" = "",
          "container" = "",
        }
      }
      forward_to = [loki.write.default.receiver]
    }

    // Отправка в Loki
    loki.write "default" {
      endpoint {
        url = "http://loki.logging.svc.cluster.local:3100/loki/api/v1/push"
      }
    }

  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi

  persistence:
    enabled: true
    size: 5Gi
```

**Валидация:**

```bash
# Проверка пода Alloy
kubectl get pods -n logging -l app.kubernetes.io/name=alloy
# → NAME                     READY   STATUS    RESTARTS   AGE
# → alloy-xxxxxxxxx-xxxxx    1/1     Running   0          3m

# Проверка логов Alloy
kubectl logs -n logging -l app.kubernetes.io/name=alloy --tail=20
# → ts=2026-01-01T00:00:00Z level=info msg="Writing logs to Loki" endpoint=http://loki.logging.svc.cluster.local:3100/loki/api/v1/push
```

### 3. Интеграция с Grafana

Для визуализации логов необходимо добавить Loki как источник данных в Grafana.

**Добавление Loki через API:**

```bash
# Получение токена Grafana
GRAFANA_TOKEN=$(kubectl get secret -n monitoring monitoring-grafana -o jsonpath="{.data.admin-password}" | base64 --decode)

# Добавление Loki как источника данных
curl -X POST http://localhost:3000/api/datasources \
  -u admin:$GRAFANA_TOKEN \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Loki",
    "type": "loki",
    "url": "http://loki.logging.svc.cluster.local:3100",
    "access": "proxy",
    "isDefault": false
  }'
```

**Добавление через UI:**

1. Откройте Grafana: `kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80`
2. Перейдите в Configuration → Data Sources → Add data source.
3. Выберите Loki.
4. Укажите URL: `http://loki.logging.svc.cluster.local:3100`.
5. Нажмите Save & Test.

### 4. Примеры запросов LogQL

**Базовые запросы:**

```logql
# Все логи из неймспейса production
{namespace="production"}

# Логи с ошибками из неймспейса kube-system
{namespace="kube-system"} |= "error"

# Логи конкретного пода
{pod="nginx-5d89bdf494-x2jkl"}

# Логи с определенным уровнем
{namespace="production"} | json | level="error"

# Логи, содержащие "timeout" за последние 5 минут
{namespace="production"} |= "timeout" [5m]
```

**Продвинутые запросы:**

```logql
# Агрегация: количество ошибок по подам
sum by (pod) (count_over_time({namespace="production"} |= "error" [1h]))

# Топ-10 подов по количеству логов
topk(10, sum by (pod) (count_over_time({namespace="production"} [1h])))

# Фильтрация по JSON-полю
{namespace="production"} | json | level="error" | line_format "{{.timestamp}} {{.message}}"

# Регулярные выражения
{namespace="production"} | regexp `error=(?P<err_code>\d+)`
```

**Создание дашборда в Grafana:**

1. Создайте новый дашборд: + → Dashboard → Add new panel.
2. Выберите источник данных: Loki.
3. Введите запрос: `{namespace="production"} |= "error"`.
4. Настройте визуализацию: Time series, Table, или Logs.
5. Сохраните панель.

### 5. Настройка алертинга на логи

Loki поддерживает алертинг через Recording rules и Alerting rules.

**Пример alerting rule:**

```yaml
# loki-alerting-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: loki-alerts
  namespace: logging
spec:
  groups:
  - name: loki-alerts
    rules:
    - alert: HighErrorRate
      expr: |
        sum by (namespace) (count_over_time({namespace="production"} |= "error" [5m])) > 100
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Высокий уровень ошибок в неймспейсе {{ $labels.namespace }}"
        description: "Обнаружено {{ $value }} ошибок за 5 минут"
```

**Применение правил:**

```bash
kubectl apply -f loki-alerting-rules.yaml
```

### 6. Оптимизация хранилища логов

Для управления объемом хранимых логов настраиваются retention policies.

**Настройка retention через Values:**

```yaml
# loki-retention-values.yaml
loki:
  storageConfig:
    filesystem:
      directory: /loki/chunks
  limits_config:
    retention_period: 168h  # 7 дней
    max_query_length: 721h  # 30 дней

  compactor:
    compaction_interval: 10m
    retention_enabled: true
    retention_delete_delay: 2h
    retention_delete_worker_count: 150
```

**Применение:**

```bash
helm upgrade loki grafana-community/loki \
  --namespace logging \
  -f loki-retention-values.yaml
```

**Ручная очистка:**

```bash
# Очистка старых чанков
kubectl exec -n logging loki-0 -- loki-cli store delete --before="2026-01-01T00:00:00Z"
```

---

## Дополнительная информация

### Частые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Alloy не отправляет логи в Loki | Нет связности с Loki | Проверьте DNS: `nslookup loki.logging.svc.cluster.local` из пода Alloy |
| Loki не хранит логи | PVC не привязан | `kubectl get pvc -n logging` |
| Задержки в логах | Большой batch_wait | Уменьшите `batch_wait` в конфигурации Alloy |
| Высокое потребление RAM | Много логов без фильтрации | Добавьте фильтрацию в конфигурацию Alloy |
| Ошибки 429 (Too Many Requests) | Loki перегружен | Увеличьте количество реплик Loki или оптимизируйте запросы |

### Производительность

- **Индексирование:** Loki индексирует только метки, а не содержимое логов. Это снижает затраты на хранение, но требует правильного выбора меток.
- **Хранение:** Используйте SSD для etcd и Loki, если логи критичны для бизнеса.
- **Ретеншн:** Настройте автоматическую очистку старых логов через `retention_period`.

### Безопасность

- **Доступ к Loki:** Ограничьте доступ через NetworkPolicy или RBAC.
- **Чувствительные данные:** Не логируйте пароли, токены и другие секреты.
- **Шифрование:** Используйте TLS для соединений между компонентами.

### См. также

- [Обзор Kubespray](./overview.md) — базовые принципы.
- [Примеры конфигураций](./examples.md) — настройка мониторинга (Prometheus/Grafana).
- [Loki Overview](../../Loki/loki_overview.md) — архитектура и возможности Loki.
- [Grafana Alloy](../../Grafana/grafana_alloy_overview.md) — описание агента сбора.
- [LogQL Examples](../../Loki/loki_stack_setup/logql_examples.md) — примеры запросов.

### Внешние ресурсы

- [Loki Documentation](https://grafana.com/docs/loki/latest/) — официальная документация.
- [Alloy Documentation](https://grafana.com/docs/alloy/latest/) — документация Alloy.
- [LogQL Reference](https://grafana.com/docs/loki/latest/query/) — справочник по LogQL.