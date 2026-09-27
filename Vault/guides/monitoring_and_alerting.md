# Мониторинг и алертинг Vault

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
| `vault.raft.leader` | Является ли узел лидером (1/0) | Gauge | High |
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

Эндпоинт `/v1/sys/health` возвращает различные HTTP-коды:

| Код | Состояние | Описание |
| :--- | :--- | :--- |
| 200 | Unsealed, Active | Vault распечатан и готов к обслуживанию запросов |
| 200 (standbyok=true) | Unsealed, Standby | Vault распечатан, но является standby-узлом |
| 200 (sealedcode=200) | Sealed, initialized | Vault запечатан, но инициализирован (ожидает unseal) |
| 501 | Uninitialized | Vault не инициализирован |
| 503 | Sealed | Vault запечатан |
| 503 (standby) | Standby | Vault является standby-узлом |

## Практические сценарии

### Сценарий 1: Настройка Prometheus exporter

#### Включение метрик в Vault

```hcl
# server.hcl
metrics {
  prometheus_enabled = true
  prometheus_retention_time = "30s"
}
```

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
    scheme: https
    tlsConfig:
      caFile: /etc/prometheus/ca.crt
      certFile: /etc/prometheus/client.crt
      keyFile: /etc/prometheus/client.key
```

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
histogram_quantile(0.95, sum(rate(vault_raft_commit_time_bucket[5m])) by (le))

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
        expr: histogram_quantile(0.95, sum(rate(vault_raft_commit_time_bucket[5m])) by (le)) > 100
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
# Успешные запросы (HTTP 2xx/4xx, исключая 4xx auth errors)
sum(rate(vault_request_count{status=~"2..|4.."}[5m]))
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
    summary: "Высокий burn rate error budget"
    description: "Текущий burn rate {{ $value | humanizePercentage }} превышает допустимый 0.1%"
```

### Сценарий 5: Health Checks для Kubernetes

#### Liveness Probe

```yaml
livenessProbe:
  httpGet:
    path: /v1/sys/health
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
    path: /v1/sys/health?standbyok=true&sealedcode=200&uninitcode=200
    port: 8200
    scheme: HTTPS
  initialDelaySeconds: 30
  periodSeconds: 10
```

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
4. **Health Checks:** Используйте `/v1/sys/health` с правильными параметрами (`standbyok=true`, `sealedcode=200`).
5. **SLO:** Определите SLO для Vault и отслеживайте error budget.
6. **Vault Agent:** Включите метрики Agent для мониторинга автоматической аутентификации и рендеринга.
7. **Audit:** Включите audit device для расследования инцидентов.

## Ограничения и известные проблемы

- **Метрики Agent:** По умолчанию Agent не экспортирует метрики. Требуется блок `telemetry` в конфигурации.
- **TLS для метрик:** В production используйте TLS для endpoint `/v1/sys/metrics`. Не оставляйте `tls_disable = true`.
- **Retention:** По умолчанию метрики хранятся 30 секунд. Увеличьте retention для исторических данных.
- **High cardinality:** Метрика `vault_token_count_by_policy` может иметь высокую cardinality при большом количестве политик. Используйте с осторожностью.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и кластеризация.
*   **[Установка Vault](../guides/vault_installation.md)** — мониторинг в production.
*   **[Интеграция с Kubernetes](../guides/vault_kubernetes_integration.md)** — health checks и мониторинг.
*   [Официальная документация по мониторингу](https://developer.hashicorp.com/vault/docs/enterprise/monitoring)
