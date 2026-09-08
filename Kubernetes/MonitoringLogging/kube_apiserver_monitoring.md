# Мониторинг kube-apiserver

## Определения

**Мониторинг `kube-apiserver`** — процесс наблюдения за производительностью и стабильностью центрального узла управления кластером. API-сервер является единственным компонентом, взаимодействующим с `etcd`, и "точкой входа" для всех запросов.

**SLI (Service Level Indicator)** — количественный показатель уровня обслуживания (например, задержка или частота ошибок).
**SLO (Service Level Objective)** — целевое значение для SLI (например, 99% запросов должны выполняться быстрее 100 мс).

Подробно о концепциях надежности: **[Концепции SRE: SLA, SLO, SLI](../../Concepts/sre_concepts_main.md)**.
Архитектура плоскости управления: **[Control Plane Architecture](../Concepts/control_plane_architecture.md)**.

## Основные концепции

### Золотые сигналы мониторинга
Для API-сервера критически важны следующие группы метрик:

1. **Задержка (Latency)**: Разделяется на общее время ответа и "чистое" время обработки (без учета очередей и вебхуков).
2. **Ошибки (Errors)**: Доля ответов с кодами `5xx` (серверные) и `429` (превышение лимитов).
3. **Насыщение (Saturation)**: Состояние очередей API Priority and Fairness (APF) и количество активных соединений.

### API Priority and Fairness (APF)
Современный механизм (стабилен с v1.29), заменяющий простые лимиты `max-inflight`. Он позволяет приоритизировать запросы от критических компонентов (например, `kube-scheduler`) над пользовательскими запросами.

## Практические сценарии

### Мониторинг задержки (Latency)
Для точной диагностики рекомендуется использовать два типа SLI:
- **Общая задержка**: `apiserver_request_duration_seconds_bucket` — то, что видит пользователь.
- **Внутренняя задержка (SLI метрика)**: `apiserver_request_sli_duration_seconds_bucket` — чистое время обработки сервером (без учета задержек внешних вебхуков).

**Пример PromQL для p99 общей задержки:**
```promql
histogram_quantile(0.99, sum(rate(apiserver_request_duration_seconds_bucket{verb!~"WATCH|CONNECT"}[5m])) by (le))
# → {le="0.1"} 0.045
```
**SLO**: p99 < 1s (для большинства запросов), p99 < 30s (для тяжелых LIST запросов).

### Мониторинг насыщения и очередей (APF)
Самый критический индикатор — отброшенные запросы из-за перегрузки.

**Метрика отброшенных запросов:**
```promql
sum(rate(apiserver_flowcontrol_rejected_requests_total[5m])) by (priority_level, flow_schema)
```
**Правило для алерта**: Любое значение > 0 указывает на то, что кластер начал отбрасывать запросы.

### Влияние etcd
Производительность API напрямую зависит от скорости записи в `etcd`.

**Критическая метрика etcd fsync:**
```promql
histogram_quantile(0.99, sum(rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) by (le))
```
**SLO**: p99 < 10мс. Значения выше указывают на медленные диски, что приведет к деградации всего Control Plane.
Подробнее: **[Мониторинг etcd](../../etcd/etcd_monitoring.md)**.

### Мониторинг доступности (Availability)
SLI доступности — доля успешных запросов (`code` `2xx`/`3xx`). Алертить стоит по доле `5xx` и `429`, а не по абсолютной нагрузке.

**Пример PromQL — доля ошибок:**
```promql
sum(rate(apiserver_request_total{code=~"5.."}[5m])) by (group, version, resource)
/
sum(rate(apiserver_request_total[5m])) by (group, version, resource)
# → {group="apps",version="v1",resource="deployments"} 0.0002
```
**SLO**: доля успешных запросов ≥ 99.9% (общий кластер), ≥ 99% для чтения/записи по конкретным ресурсам.

### Ресурсы и загрузка процесса
API-сервер — это Go-процесс. Собственное потребление CPU/RAM контейнера агрегируется через kubelet/cAdvisor, а метрики самого процесса (`process_*`) он публикует на собственном эндпоинте `/metrics`.

```promql
# Загрузка CPU процесса
rate(process_cpu_seconds_total[5m]) > 0.8
# Память процесса (RSS)
process_resident_memory_bytes
# Текущие выполняемые запросы (очередь APF) в реальном времени
apiserver_flowcontrol_current_executing_requests
```
**Интерпретация**:
- Частые перезапуски pod'а вместе с растущей RSS → утечка/давление памяти (митигация: увеличить `--per-connection-burst` и лимиты).
- `apiserver_current_inflight_requests` (легаси-счетчик до APF) полезен для диагностики старых кластеров.
- Приближение `apiserver_flowcontrol_current_executing_requests` к верхнему порогу означает насыщение очередей.

### Аутентификация и авторизация
Задержки на этапах authn/authz напрямую влияют на время ответа. Отделяйте их от времени самой обработки.

```promql
# P99 времени аутентификации
histogram_quantile(0.99, sum(rate(apiserver_authentication_duration_seconds_bucket[5m])) by (le))
# P99 времени авторизации
histogram_quantile(0.99, sum(rate(apiserver_authorization_duration_seconds_bucket[5m])) by (le))
```
**Интерпретация**: рост `authentication_duration` обычно связан с webhook-провайдерами (OIDC, TokenReview) или медленной проверкой сертификатов; рост `authorization_duration` — с объёмом RBAC-правил и частыми обновлениями `ClusterRoleBinding`.

### Watch Cache и Informer'ы
Watch-механизм — основа реактивной архитектуры Kubernetes. Все контроллеры, kubelet и внешние клиенты подписываются на изменения через API-сервер. `kube-apiserver` не отдаёт каждый watch-запрос напрямую в etcd — вместо этого он ведёт собственный кэш (**Watch Cache**), удовлетворяя большинство `list/watch`-запросов из кэша и снижая нагрузку на etcd.

**Ключевые метрики watch cache:**
```promql
# Количество событий в watch cache (ошибки — индикатор переполнения)
sum(rate(apiserver_watch_cache_events_received_total[5m])) by (type)
# Количество пропущенных событий (watch cache переполнен — критическая ситуация)
sum(rate(apiserver_watch_cache_events_missed_total[5m]))
# Текущий размер watch cache по типам ресурсов
apiserver_watch_cache_capacity
```
**Интерпретация:**
- Рост `events_missed_total` означает, что watch cache не успевает обрабатывать события. Причины: высокая нагрузка на API-сервер, медленные клиенты, недостаточный размер кэша.
- Метрика `apiserver_watch_cache_capacity` показывает текущий лимит кэша. Для крупных кластеров может потребоваться увеличение через `--watch-cache-sizes` (флаг API-сервера).

**Метрики informer'ов (клиентская сторона):**
```promql
# Задержка обработки событий informer'ом (время между получением и обработкой)
histogram_quantile(0.99, sum(rate(workqueue_queue_duration_seconds_bucket{controller=~".*"}[5m])) by (le, controller))
# Количество повторных попыток (requeue) из-за ошибок обработки
sum(rate(workqueue_retries_total{controller=~".*"}[5m])) by (controller)
```
**Примечание**: Метрики `workqueue_*` предоставляются контроллерами и scheduler'ом, а не API-сервером, но критичны для диагностики проблем с watch-пайплайном.

### Audit-логирование (метрики)
Kubernetes Audit Log — журнал всех API-запросов к `kube-apiserver` (кто, когда и к какому ресурсу обращался). Включается через `--audit-log-path` и `--audit-policy-file`. Метрики аудита позволяют отслеживать объём и целостность аудит-записей.

**Ключевые метрики:**
```promql
# Количество аудит-записей по уровням детализации
sum(rate(apiserver_audit_event_total[5m])) by (stage, level)
# Количество усеченных записей (превышены лимиты --audit-log-truncate-*)
sum(rate(apiserver_audit_truncated_total[5m]))
# Количество ошибок записи аудита
sum(rate(apiserver_audit_error_total[5m])) by (stage)
```
**Интерпретация:**
- Рост `apiserver_audit_truncated_total` указывает на превышение лимитов `--audit-log-truncate-request-body` / `--audit-log-truncate-response-body` или на медленную запись на диск.
- `apiserver_audit_error_total > 0` означает потерю аудит-записей (диск заполнен, webhook недоступен, проблемы с I/O).
- Анализ по `stage` (`RequestReceived`, `ResponseComplete`) позволяет выявить, на каком этапе возникают проблемы.

**SLO для аудита:** Доля потерянных аудит-записей = 0%. Любые ошибки аудита требуют немедленного расследования (особенно в средах с требованиями PCI DSS, SOC 2).

Подробнее: **[Аудит-логирование Kubernetes](../../Kubernetes/Security/audit.md)**.

### Пропускная способность API (Throughput)
Мониторинг количества запросов в секунду по типам и ресурсам позволяет выявить аномалии и "агрессивных" клиентов.

```promql
# Общий throughput API-сервера
sum(rate(apiserver_request_total[5m]))
# Throughput по verb (для выявления аномалий в LIST/WATCH)
sum(rate(apiserver_request_total{verb=~"LIST|WATCH"}[5m])) by (resource)
# Throughput по user (поиск "шумных" клиентов)
sum(rate(apiserver_request_total[5m])) by (user)
```
**Интерпретация:**
- Резкий рост `LIST`-запросов по конкретному ресурсу может указывать на неоптимизированный контроллер или operator.
- `WATCH`-запросы не должны быть активными постоянно — стабильный поток событий Watch обрабатывается из кэша API-сервера.

### Завершенные запросы с ошибками (Terminated Requests)
Метрика `apiserver_request_terminated_total` отслеживает запросы, которые были завершены до обработки (отклонены admission-контроллерами, authentication/authorization, или APF).

```promql
# Запросы, завершенные по причинам (component — этап, reason — причина)
sum(rate(apiserver_request_terminated_total{reason!~""}[5m])) by (component, reason)
```
**Интерпретация:**
- `component="apiserver", reason="rejected"` — запросы отклонены admission-контроллером (включая вебхуки).
- `component="apiserver", reason="timeout"` — клиент не дождался ответа (таймаут соединения).
- `component="apiserver", reason="panic"` — внутренняя ошибка API-сервера (критично, требует расследования).

## Диагностика и дашборды

### Анализ вебхуков
Если общая задержка растет, а внутренняя (SLI) остается в норме — проблема во внешних компонентах.
- **Метрика**: `apiserver_admission_webhook_admission_duration_seconds_bucket`.
- **Действие**: Выявите медленный `ValidatingWebhookConfiguration` или `MutatingWebhookConfiguration`.

### Интенсивность запросов
Анализ по `user` и `verb` помогает выявить "агрессивных" клиентов (например, некорректно написанный оператор).
- **Метрика**: `apiserver_request_total`.

### Типичные проблемы и их диагностика

| Проблема | Симптомы | Ключевые метрики | Решение |
|:---|:---|:---|:---|
| **Высокая задержка API** | p99 > 1s, рост `429` | `apiserver_request_duration_seconds_bucket`, `apiserver_flowcontrol_rejected_requests_total` | Проверить etcd (`etcd_disk_wal_fsync_duration_seconds`), увеличить лимиты APF |
| **Перегрузка API-сервера** | Массовые `429`, рост очередей APF | `apiserver_flowcontrol_current_inqueue_requests`, `apiserver_flowcontrol_rejected_requests_total` | Оптимизировать LIST-запросы (пагинация), настроить PriorityLevelConfiguration |
| **Watch cache переполнен** | Пропущенные события, ошибки контроллеров | `apiserver_watch_cache_events_missed_total` | Увеличить `--watch-cache-sizes`, оптимизировать подписки |
| **Медленный etcd** | Общая деградация, таймауты | `etcd_disk_wal_fsync_duration_seconds` p99 > 10ms | Замена диска на NVMe, оптимизация IOPS |
| **Audit log потеря** | Записи не появляются или обрезаны | `apiserver_audit_error_total`, `apiserver_audit_truncated_total` | Проверить диск, увеличить лимиты truncation, перейти на webhook backend |
| **Медленные admission-вебхуки** | Задержки до обработки запроса | `apiserver_admission_webhook_admission_duration_seconds_bucket` | Оптимизировать webhook или перейти на ValidatingAdmissionPolicy (CEL) |

### Рекомендуемые Grafana-дашборды

Для полного мониторинга API-сервера рекомендуется использовать следующие дашборды:

1. **Kubernetes API Server** (ID: 15760) — основные метрики: throughput, latency, errors, APF.
2. **Kubernetes API Server Audit** (ID: 16177) — аудит-логирование: количество записей, ошибки, truncation.
3. **etcd** (ID: 13394) — производительность etcd: fsync, backend commit, leaderboard.
4. **Kubernetes Cluster (Overview)** (ID: 7249) — общая картина здоровья кластера.

> **Примечание**: Дашборды доступны на [grafana.com/grafana/dashboards](https://grafana.com/grafana/dashboards). Импорт выполняется через Grafana UI или provisioning (JSON-файлы).

## Конфигурация сбора метрик

### ServiceMonitor для kube-apiserver (kube-prometheus-stack)

В стандартной конфигурации `kube-prometheus-stack` scrape-джоб для `kube-apiserver` уже преднастроен через встроенные **ServiceMonitor** и **EndpointSlice**. Однако в некоторых окружениях (особенно при ручной настройке или использовании внешнего etcd) может потребоваться создать собственный ServiceMonitor.

**Пример кастомного ServiceMonitor для API-сервера:**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kube-apiserver
  namespace: monitoring
  labels:
    k8s-app: kube-apiserver
spec:
  endpoints:
    - port: https-metrics
      scheme: https
      tlsConfig:
        caFile: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        serverName: kubernetes
      bearerTokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token
      interval: 30s
      scrapeTimeout: 25s
  namespaceSelector:
    matchNames:
      - default  # kube-apiserver Service находится в namespace "default"
  selector:
    matchLabels:
      component: kube-apiserver
```

**Важно:**
- По умолчанию `kube-apiserver` доступен через Service `kubernetes` в namespace `default` (порты `https-metrics`).
- TLS-конфигурация зависит от способа развертывания кластера (kubeadm, RKE2, и т.д.).
- В kube-prometheus-stack scrape-джоб для API-сервера уже встроен — создавайте кастомный ServiceMonitor только при необходимости переопределения (например, для добавления дополнительных метрик или изменения интервала).

Подробнее: **[Мониторинг master-нод](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/master_nodes_monitoring.md)**.

### Recording Rules для Prometheus

Recording Rules позволяют предварительно вычислять часто используемые или ресурсоёмкие запросы, повышая производительность дашбордов и алертов.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: kube-apiserver-recording-rules
  namespace: monitoring
spec:
  groups:
    - name: kube-apiserver.recording-rules
      interval: 30s
      rules:
        # P99 latency по verb и resource (для дашбордов)
        - record: apiserver_request_duration_seconds:p99:5m
          expr: histogram_quantile(0.99, sum(rate(apiserver_request_duration_seconds_bucket{verb!~"WATCH|CONNECT"}[5m])) by (le, verb, resource))

        # Доля ошибок 5xx по resource
        - record: apiserver_request_error_ratio:rate5m
          expr: sum(rate(apiserver_request_total{code=~"5.."}[5m])) by (resource) / sum(rate(apiserver_request_total[5m])) by (resource)

        # Throughput по verb (запросы/сек)
        - record: apiserver_request_throughput:rate5m
          expr: sum(rate(apiserver_request_total[5m])) by (verb)

        # Доля rejected запросов APF
        - record: apiserver_flowcontrol_rejected_ratio:rate5m
          expr: sum(rate(apiserver_flowcontrol_rejected_requests_total[5m])) by (priority_level, flow_schema)
```

### Alerting Rules для Prometheus

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: kube-apiserver-alerts
  namespace: monitoring
spec:
  groups:
    - name: kube-apiserver.alerting-rules
      rules:
        # Критично: Доля ошибок API-сервера > 5%
        - alert: KubeAPIServerHighErrorRate
          expr: |
            sum(rate(apiserver_request_total{code=~"5.."}[5m])) by (cluster)
            /
            sum(rate(apiserver_request_total[5m])) by (cluster) > 0.05
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Высокая доля ошибок API-сервера (>5%)"
            description: "API-сервер в кластере {{ $labels.cluster }} возвращает >5% ошибок 5xx в течение 5 минут"

        # Предупреждение: P99 latency > 1s
        - alert: KubeAPIServerHighLatency
          expr: |
            histogram_quantile(0.99, sum(rate(apiserver_request_duration_seconds_bucket{verb!~"WATCH|CONNECT"}[5m])) by (le)) > 1
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Высокая задержка API-сервера (p99 > 1s)"
            description: "P99 задержки API-сервера превышает 1 секунду в течение 10 минут"

        # Критично: APF отбрасывает запросы
        - alert: KubeAPIServerFlowControlRejected
          expr: sum(rate(apiserver_flowcontrol_rejected_requests_total[5m])) by (priority_level) > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "API-сервер отбрасывает запросы из-за APF"
            description: "API-сервер отбрасывает запросы приоритетного уровня {{ $labels.priority_level }}"

        # Предупреждение: Audit errors
        - alert: KubeAPIServerAuditErrors
          expr: sum(rate(apiserver_audit_error_total[5m])) > 0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Ошибки записи аудит-логов"
            description: "API-сервер фиксирует ошибки записи аудит-событий. Возможна потеря аудит-данных."

        # Критично: etcd fsync > 10ms
        - alert: EtcdHighFsyncLatency
          expr: histogram_quantile(0.99, sum(rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) by (le)) > 0.01
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Высокая задержка fsync в etcd"
            description: "P99 задержки fsync в etcd превышает 10мс. Критично для стабильности кластера."
```

## Дополнительная информация

### Смежные теми
- **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — RED и Four Golden Signals.
- **[Метрики: детали](../../Concepts/Observability_and_Monitoring/metrics_deep_dive.md)** — типы данных в Prometheus.
- **[Observability Definitions](../../Concepts/Observability_and_Monitoring/observability_definitions.md)** — гистограммы и квантили.
- **[Конфигурация экспортеров](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/exporters_config.md)** — настройка scrape-джобов в kube-prometheus-stack.
- **[Аудит-логирование](../../Kubernetes/Security/audit.md)** — политика и конфигурация аудита API-запросов.
