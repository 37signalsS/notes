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

## Диагностика и дашборды

### Анализ вебхуков
Если общая задержка растет, а внутренняя (SLI) остается в норме — проблема во внешних компонентах.
- **Метрика**: `apiserver_admission_webhook_admission_duration_seconds_bucket`.
- **Действие**: Выявите медленный `ValidatingWebhookConfiguration` или `MutatingWebhookConfiguration`.

### Интенсивность запросов
Анализ по `user` и `verb` помогает выявить "агрессивных" клиентов (например, некорректно написанный оператор).
- **Метрика**: `apiserver_request_total`.

## Дополнительная информация

### Смежные темы
- **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — RED и Four Golden Signals.
- **[Метрики: детали](../../Concepts/Observability_and_Monitoring/metrics_deep_dive.md)** — типы данных в Prometheus.
- **[Observability Definitions](../../Concepts/Observability_and_Monitoring/observability_definitions.md)** — гистограммы и квантили.
