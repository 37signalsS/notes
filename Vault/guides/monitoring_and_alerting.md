# Мониторинг и алертинг Vault

**Актуально для:** Vault 2.x

> Метрики Vault работают через стейнджер `telemetry` в `vault.hcl` (блок `metrics` не существует). Prometheus скрейпит `/v1/sys/metrics?format=prometheus`; endpoint требует токена с `capabilities = ["read"]` на `path "/sys/metrics"`.

## Определения

**SLO (Service Level Objective)** — целевой уровень надёжности сервиса, выраженный в процентах доступности или допустимом количестве ошибок. Для Vault типичный SLO — 99.9% доступности (8.7 часов простоя в год).

**SLI (Service Level Indicator)** — количественный показатель надёжности, например, доля успешных запросов к Vault или время ответа.

**Error Budget (Бюджет ошибок)** — допустимое количество ошибок в рамках SLO. Например, при SLO 99.9% error budget составляет 0.1% (≈ 43 минуты простоя в месяц).

**Prometheus** — система мониторинга с открытым исходным кодом, используемая для сбора метрик Vault.

**Grafana** — платформа визуализации метрик, используемая для дашбордов Vault.

**Alertmanager** — компонент Prometheus, управляющий алертами (маршрутизация, группировка, ингибирование).

**Health Check** — проверка работоспособности Vault через эндпоинт `/v1/sys/health`. Возвращает различные HTTP-коды в зависимости от состояния кластера.

**Audit Device** — компонент Vault, записывающий все запросы и ответы в лог (файл, syslog, socket).

## Основные концепции

### Ключевые метрики Vault

| Метрика | Описание | Тип | Важность |
| :--- | :--- | :--- | :--- |
| `vault.core.unsealed` | Состояние распечатанности (1=unsealed) | Gauge | Critical |
| `vault.core.active` | Активный узел (лидер для HA); 1 = active, 0 = standby | Gauge | High |
| `vault.raft.commitTime` | Время коммита записи в Raft (ms) | Histogram | High |
| `vault.raft.apply` | Время применения записи (ms) | Histogram | High |
| `vault.cache.hit` / `vault.cache.miss` | Попадания/промахи кэша | Counter | Medium |
| `vault.token.count.by_policy` | Количество токенов по политикам | Gauge | Medium |
| `vault.runtime.lease.count` | Количество активных аренд | Gauge | Medium |
| `vault.request.count` | Общее число запросов | Counter | Medium |
| `vault.seal.in_progress` | Процесс распечатывания | Gauge | Critical |
| `vault.agent.auth.token.renewal.success` | Успешное продление токена | Counter | High |
| `vault.agent.auth.token.renewal.failure` | Неудача продления токена | Counter | High |
| `vault.agent.template.render.success` | Успешный рендеринг шаблона | Counter | Medium |
| `vault.agent.template.render.failure` | Ошибка рендеринга | Counter | Medium |

### Уровни здоровья Vault

Эндпоинт `/v1/sys/health` возвращает HTTP-коды в зависимости от состояния узла. По умолчанию:

| Код | Состояние | Описание |
| :--- | :--- | :--- |
| 200 | Initialized, unsealed, active | Raft: лидер; обслуживает запросы |
| 429 | Unsealed, standby | Follower (Replica) |
| 472 | DR secondary (active or standby) | Вторичный узел DR-репликации |
| 473 | Performance standby | Performance standby |
| 474 | Standby/perf-standby, cannot reach active | HA-кластер недоступен с этим узлом |
| 501 | Not initialized | Кластер не инициализирован |
| 503 | Sealed | Запечатан (требует unseal) |
| 530 | Removed | Удалён из HA-кластера |

Поведение перекрывается query-параметрами (`activecode`, `standbycode`, `drsecondarycode`, `performancestandbycode`, `haunhealthycode`, `removedcode`, `sealedcode`, `uninitcode`). Чаще всего используются:

| Параметр | По умолчанию | Применение |
| :--- | :--- | :--- |
| `standbyok=true` | `false` | standby возвращает `200` вместо `429` |
| `perfstandbyok=true` | `false` | perf-standby возвращает `200` вместо `473` |
| `sealedcode=204` | `503` | запечатанный узел возвращает `204` (не перезапускать) |
| `uninitcode=204` | `501` | неинициализированный узел возвращает `204` (не перезапускать) |
| `drsecondarycode=200` | `472` | DR-вторичный узел возвращает `200` |

## Практические сценарии

### Сценарий 1: Настройка Prometheus exporter

#### Включение метрик в Vault

```hcl
# server.hcl
telemetry {
  prometheus_retention_time = "24h"
  disable_hostname          = true
}
```

Метрики включаются **не** отдельным флагом: установка ненулевого `prometheus_retention_time` (по умолчанию — `24h`) активирует Prometheus-endpoint. Значение `0` отключает Prometheus-телеметрию. Метрики агрегрируются каждые 10 секунд и сохраняются в памяти в течение `prometheus_retention_time`.

### Требования к доступу

`/v1/sys/metrics` защищён и требует токен с `capabilities = ["read"]` на `path "sys/metrics"`. Prometheus может аутентифицироваться двумя способами:

-   **mTLS** (клиентский сертификат) — как в `ServiceMonitor` ниже;
-   **bearer-токен** (`bearer_token` / `bearer_token_file` в `prometheus.yml`).

```hcl
# policy: prometheus-metrics
path "sys/metrics" {
  capabilities = ["read"]
}
path "sys/metrics/" {
  capabilities = ["read", "list"]
}
```

> **Примечание:** без `prometheus_retention_time` Vault возвращает пустой ответ; без токена/сертификата — `403 Forbidden`.

#### Настройка ServiceMonitor (Prometheus Operator)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: vault
  namespace: vault
  labels:
    app: vault
spec:
  selector:
    matchLabels:
      app: vault
   endpoints:
   - port: http
     interval: 15s
     path: /v1/sys/metrics
     params:
       format:
         - prometheus
     scheme: https
     tlsConfig:
       caFile: /etc/prometheus/ca.crt
       certFile: /etc/prometheus/client.crt
       keyFile: /etc/prometheus/client.key
```

> Параметр `format=prometheus` обязателен: без него `/v1/sys/metrics` возвращает JSON. При `scheme: https` и `tlsConfig` используется аутентификация клиентским сертификатом (mTLS); иначе — `bearerTokenFile` токена с политикой `prometheus-metrics`.

### Сценарий 2: Дашборд Grafana

#### Панель 1: Состояние кластера

```promql
# Количество распечатанных узлов
sum(vault_core_unsealed)

# Лидер кластера
vault_core_leader
```

#### Панель 2: Производительность Raft

```promql
# Время коммита (p95)
histogram_quantile(0.95, sum(rate(vault_raft_commitTime_bucket[5m])) by (le))

# Время применения (p95)
histogram_quantile(0.95, sum(rate(vault_raft_apply_bucket[5m])) by (le))
```

#### Панель 3: Запросы и кэш

```promql
# Количество запросов в секунду
sum(rate(vault_request_count[5m]))

# Эффективность кэша
sum(rate(vault_cache_hit[5m])) / (sum(rate(vault_cache_hit[5m])) + sum(rate(vault_cache_miss[5m])))
```

#### Панель 4: Токены и lease

```promql
# Количество токенов по политикам
vault_token_count_by_policy

# Количество активных lease
vault_runtime_lease_count
```

#### Панель 5: Vault Agent

```promql
# Успешное продление токена
sum(rate(vault_agent_auth_token_renewal_success[5m]))

# Ошибки продления токена
sum(rate(vault_agent_auth_token_renewal_failure[5m]))

# Успешный рендеринг шаблонов
sum(rate(vault_agent_template_render_success[5m]))

# Ошибки рендеринга
sum(rate(vault_agent_template_render_failure[5m]))
```

### Сценарий 3: Правила алертинга

```yaml
# alerts.yaml
groups:
  - name: vault_alerts
    rules:
      # Vault запечатан
      - alert: VaultSealed
        expr: vault_core_unsealed == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Vault запечатан на {{ $labels.instance }}"
          description: "Vault находится в запечатанном состоянии более 1 минуты"

      # Высокое время коммита Raft
      - alert: VaultHighRaftCommitTime
        expr: histogram_quantile(0.95, sum(rate(vault_raft_commitTime_bucket[5m])) by (le)) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое время коммита Raft на {{ $labels.instance }}"
          description: "p95 время коммита {{ $value }}ms превышает порог 100ms"

      # Ошибки продления токена агентом
      - alert: VaultAgentTokenRenewalFailure
        expr: sum(rate(vault_agent_auth_token_renewal_failure[5m])) > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Ошибки продления токена Vault Agent"
          description: "{{ $value }} ошибок продления токена в секунду"

      # Рост количества токенов
      - alert: VaultTokenCountGrowth
        expr: deriv(vault_token_count_by_policy[5m]) > 10
        for: 5m
        labels:
          severity: info
        annotations:
          summary: "Всплеск создания токенов"
          description: "Рост {{ $value }} токенов/сек"

      # Низкая эффективность кэша
      - alert: VaultLowCacheHitRatio
        expr: |
          sum(rate(vault_cache_hit[5m])) / 
          (sum(rate(vault_cache_hit[5m])) + sum(rate(vault_cache_miss[5m]))) < 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Низкий hit ratio кэша на {{ $labels.instance }}"
          description: "Hit ratio {{ $value | humanizePercentage }} ниже 50%"
```

### Сценарий 4: SLO для Vault

#### Определение SLI

```promql
# Доля успешных запросов (HTTP 2xx) — SLI для SLO
sum(rate(vault_request_count{status=~"2.."}[5m]))
/
sum(rate(vault_request_count[5m]))
```

#### Цель SLO

```yaml
# SLO: 99.9% успешных запросов за 30 дней
# Error budget: 0.1% ≈ 43 минуты простоя в месяц
```

#### Алерт на истощение error budget

```yaml
- alert: VaultErrorBudgetBurnRate
  expr: |
    (
      sum(rate(vault_request_count{status=~"5.."}[5m])) 
      / 
      sum(rate(vault_request_count[5m]))
    ) > 0.001
  for: 5m
  labels:
    severity: critical
  annotations:
       summary: "Доля ошибок превышает порог SLO (0.1%)"
       description: "Текущая доля ошибок {{ $value | humanizePercentage }} превышает допустимые 0.1% (бюджет ошибок для SLO 99.9%)"
```

### Сценарий 5: Health Checks для Kubernetes

#### Liveness Probe

```yaml
livenessProbe:
  httpGet:
    path: /v1/sys/health?standbyok=true&perfstandbyok=true&drsecondarycode=200&sealedcode=204&uninitcode=204
    port: 8200
    scheme: HTTPS
    initialDelaySeconds: 60
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 3
```

#### Readiness Probe

```yaml
readinessProbe:
  httpGet:
    path: /v1/sys/health?standbyok=true&perfstandbyok=true&drsecondarycode=200
    port: 8200
    scheme: HTTPS
    initialDelaySeconds: 30
    periodSeconds: 10
```

Оба пути — из рекомендаций HashiCorp (Validated Designs). Для *liveness* запечатанный и неинициализированный узелы возвращают `204` (а не `503`/`501`), чтобы kubelet не перезапускал под — unseal требует внешнего вмешения. Для *readiness* `sealed`/`uninit` остаются не-`2xx`, поэтому sealed/uninitialized поды не попадают в балансировщик. Параметр `drsecondarycode=200` делает DR-вторичные узлы готовыми.

### Сценарий 6: Vault Agent метрики

```hcl
# agent-config.hcl
telemetry {
  prometheus_retention_time = "5m"
  disable_hostname          = true
  unauthenticated_metrics_access = false
}

listener "tcp" {
  address     = "127.0.0.1:9102"
  tls_disable = true
}
```

#### Ключевые метрики Agent

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `vault.agent.auth.token.renewal.success` | Успешное продление токена | Отсутствие в течение `2 × token_ttl` |
| `vault.agent.auth.token.renewal.failure` | Неудача продления | >0 за 5 минут |
| `vault.agent.template.render.success` | Успешный рендеринг | Отсутствие — секрет не обновляется |
| `vault.agent.template.render.failure` | Ошибка рендеринга | >0 — проблема с синтаксисом или доступом |
| `vault.agent.cache.hit` / `vault.agent.cache.miss` | Попадания/промахи кэша | Рост miss — кэш маловат |

## Лучшие практики

1. **Метрики с самого начала:** Включите Prometheus exporter на этапе установки Vault.
2. **Дашборд:** Создайте дашборд Grafana с основными панелями: состояние кластера, Raft, токены, lease.
3. **Алерты:** Настройте алерты на критичные метрики: `vault_core_unsealed`, `vault_raft_commitTime`, ошибки продления токенов.
4. **Health Checks:** Используйте `/v1/sys/health` с параметрами — `standbyok=true&perfstandbyok=true&drsecondarycode=200` для readiness и `+sealedcode=204&uninitcode=204` для liveness.
5. **SLO:** Определите SLO для Vault и отслеживайте error budget.
6. **Vault Agent:** Включите метрики Agent для мониторинга автоматической аутентификации и рендеринга.
7. **Audit:** Включите audit device для расследования инцидентов.

## Ограничения и известные проблемы

- **Метрики Agent:** По умолчанию Agent не экспортирует метрики. Требуется блок `telemetry` в конфигурации.
- **TLS для метрик:** В production используйте TLS для endpoint `/v1/sys/metrics`. Не оставляйте `tls_disable = true`.
- **Retention:** По умолчанию Prometheus-ретенция — `24h` (значение `0` отключает Prometheus-телеметрию). In-memory агрегирование — каждые 10 секунд, in-memory retention — 1 минута.
- **High cardinality:** Метрика `vault_token_count_by_policy` может иметь высокую cardinality при большом количестве политик. Используйте с осторожностью.

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `/v1/sys/metrics?format=prometheus` возвращает `403` | Нет токена или политика не даёт `read` на `sys/metrics` | Создайте политику `prometheus-metrics` с `path "sys/metrics" { capabilities = ["read", "list"] }` и токен с ней; либо используйте mTLS |
| `/v1/sys/metrics?format=prometheus` пустой / тело пустое | `prometheus_retention_time` не задан (0) — Prometheus-телеметрия отключена | Установите `prometheus_retention_time` в stanza `telemetry` (например `"24h"`) и перезапустите Vault |
| `vault_core_unsealed == 0` | Узел запечатан | `vault operator unseal` (требуется кворум ключей) |
| Метрики лидера/Raft отсутствуют на standby | Метрики — узлоспецифичны; leader-only метрики публикуются только активным узлом | Скрейпите с активного узла, либо включите `unauthenticated_metrics_access` |
| `humanizePercentage` отображает `0.1%` вместо `0.001` | Prometheus `humanizePercentage` умножает на 100 | В аннотации указывайте порог в % (`0.1%`), а не коэффициент |

Диагностические команды:

```bash
# Сырой вывод метрик (Prometheus-формат)
curl -s --header "X-Vault-Token: <token>" \
  "http://127.0.0.1:8200/v1/sys/metrics?format=prometheus" | head -30

# Дамп telemetry в stderr процесса (префиксы [C]/[G]/[S])
kill -s USR1 $(pgrep vault)

# Стрим метрик на stdout
vault monitor -m metrics
```


## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и кластеризация.
*   **[Установка Vault](../guides/vault_installation.md)** — мониторинг в production.
*   **[Интеграция с Kubernetes](../guides/vault_kubernetes_integration.md)** — health checks и мониторинг.
*   **[API справочник](./vault_api_reference.md)** — `/sys/metrics`, `/sys/health`.
*   **[Аудит и анализ логов](./audit_log_analysis.md)** — аудит-логи как сигнал для алертинга.
*   [Telemetry — конфигурация](https://developer.hashicorp.com/vault/docs/configuration/telemetry)
*   [Метрики: ключевые для health checks](https://developer.hashicorp.com/vault/docs/internals/telemetry/key-metrics)
*   [Справочник метрик (полный)](https://developer.hashicorp.com/vault/docs/internals/telemetry/metrics/all)
