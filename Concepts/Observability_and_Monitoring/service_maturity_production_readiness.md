# Зрелость сервиса и готовность к production (Service Maturity & Production Readiness)

**Актуально для:** Prometheus 3.13.x, Grafana Alerting 11.x, Grafana OnCall, Alertmanager, Loki 3.x, Jaeger 2.21.x, Tempo 3.0.x, Zabbix 7.0 LTS/7.4, Netdata 2.x, PostgreSQL 14–17, MySQL 8.0/8.4, Linux 5.4+ (PSI)

## Определения

- **Production Readiness (Готовность к production)** — оценка готовности сервиса к стабильной работе в production-среде без риска для пользователей и бизнеса.

- **Service Maturity (Зрелость сервиса)** — уровень развитости процессов, инструментов и культуры вокруг сервиса, определяющий его способность reliably обслуживать пользователей.

- **Readiness Gate (Ворота готовности)** — автоматизированная проверка, преграждающая деплой, если сервис не соответствует критериям production readiness.

- **Operational Excellence (Операционное превосходство)** — состояние, при котором команда может быстро и безопасно внедрять изменения, реагировать на инциденты и постоянно улучшать сервис.

- **SLO Readiness** — состояние сервиса, при котором установлены, отслеживаются и активно используются SLI/SLO для управления надежностью.

- **Chaos Readiness** — состояние сервиса, при котором регулярно проводятся хаос-эксперименты и инциденты используются для обучения.

- **Observability Maturity** — уровень развитости наблюдаемости: от базового мониторинга до полноценной observability-driven development.

---

## Архитектура и принципы

### Readiness Gate (Ворота готовности)

Readiness Gate — автоматизированный контроль перед деплоем в production. В простейшем виде это скрипт или набор Prometheus recording rules, блокирующих деплой при нарушении критериев.

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ CI Pipeline │────▶│ Readiness Gate│────▶│ Production  │
│             │     │ (Prometheus, │     │ Deploy      │
│             │     │  gate rules) │     │             │
└─────────────┘     └──────────────┘     └─────────────┘
```

**Критерии gate (пример):**
- SLO attainment за последние 24 часа > 99.9%
- Error budget burn rate < 2x за последний час
- Нет активных SEV1/SEV2 инцидентов
- Дашборд сервиса существует в Grafana
- Все SEV1/SEV2 алерты имеют `runbook_url`
- Дублирующий экземпляр доступен (for Level 2+)

### Критические зависимости

1. **NTP:** Все временные метки в логах, метриках и таймлайне инцидента должны быть синхронизированы. Разница > 1 секунды делает корреляцию невозможной. Проверка: `chronyc tracking` или `timedatectl show`.
2. **Scrape reliability:** Если Prometheus не собрал данные до алерта — MTTD растет. Используйте `scrape_timeout_seconds`, `evaluation_interval` и `scrape_interval` в конфигурации Prometheus. Проверка: `promtool check config prometheus.yml`.
3. **Label hygiene:** Лейблы `service`, `severity`, `team`, `region` должны присутствовать во всех алертах. Без них группировка и маршрутизация не работают.
4. **Runbook as Code:** Runbook хранится в Git рядом с кодом сервиса. Каждый алерт содержит `runbook_url`. Устаревший runbook хуже, чем его отсутствие.
5. **Backup verification:** Бэкап без проверки восстанова — не бэкап. Еженедельный restore test на отдельном хосте.

### Recording rules для Readiness Gate

```yaml
groups:
- name: readiness.gate
  interval: 30s
  rules:
  - record: readiness:slo:attainment_24h
    expr: avg_over_time(slo:success:ratio[24h]) * 100

  - record: readiness:error_budget:burn_rate_1h
    expr: (
      sum(rate(http_requests_total{status=~"5.."}[1h]))
      / sum(rate(http_requests_total[1h]))
    ) / (1 - 0.999) * 100

  - record: readiness:dashboard:exists
    expr: count(grafana_dashboard_exists{service="payment"}) > 0

  - record: readiness:runbook:coverage
    expr: count(alert_runbook_present{severity=~"page|warning"})
      / count(alert{severity=~"page|warning"}) * 100
```

### Роли в процессе Production Readiness Review

| Роль | Ответственность |
| :--- | :--- |
| **Владелец сервиса** | Заполнение self-assessment, ответы на вопросы SRE/Security |
| **SRE** | Проверка метрик, алертов, настройки на-call, runbooks |
| **Security** | Проверка RBAC, network policies, аудит, compliance |
| **DBA** | Проверка репликации, бэкапов, restore test, мониторинга БД |
| **Sysadmin** | Проверка железа, NTP, дисков, памяти, сети, лицензий |
| **Tech Lead** | Финальное Go/No-go решение |

---

## Базовые концепции

### Модель зрелости сервиса (Service Maturity Model)

Определяет 5 уровней зрелости от «не production-ready» до «operational excellence».

| Уровень | Название | Описание | Ключевые характеристики |
| :--- | :--- | :--- | :--- |
| **0** | **Prototype** | Прототип, разработка | Нет мониторинга, нет SLO, деплой вручную |
| **1** | **Basic Production** | Базовый production | Есть мониторинг, базовый SLO, ручные деплои |
| **2** | **Managed Production** | Управляемый production | SLO с алертами, CI/CD, базовый on-call |
| **3** | **Optimized Production** | Оптимизированный production | SLO-based decisions, автоматизация, постмортемы |
| **4** | **Operational Excellence** | Операционное превосходство | Полная automation, chaos engineering, continous improvement |

### Четыре измерения readiness

Production readiness оценивается по четырем измерениям:

```
┌──────────────────────────────────────────────────────────────┐
│  RELIABILITY        SECURITY        OBSERVABILITY   OPERATIONS │
│  (Надежность)       (Безопасность)  (Наблюдаемость) (Эксплуатация)│
└──────────────────────────────────────────────────────────────┘
```

---

### Измерение 1: Reliability (Надежность)

**Вопрос:** Можно ли доверить этому сервису критичные бизнес-процессы?

#### Критерии:

| Критерий | Уровень 1 | Уровень 2 | Уровень 3 | Уровень 4 |
| :--- | :--- | :--- | :--- | :--- |
| **SLO/SLI** | Есть базовый uptime SLA | Есть SLO для ключевых CUJ | SLO-based rollback, error budgets | Error budgets drive roadmap |
| **Redundancy** | Single instance | Multi-AZ deployment | Multi-region, active-active | Cross-cloud, geo-routing |
| **Testing** | Manual smoke tests | Automated unit + integration tests | Contract tests, canary | Chaos engineering, GameDays |
| **Graceful degradation** | Нет | Partial (circuit breaker) | Feature flags, bulkheads | Full graceful degradation |

#### Проверка Reliability:

```bash
# Проверка multi-AZ deployment
kubectl get pods -o wide -n production | awk '{print $7}' | sort | uniq -c
# → 3 us-east-1a
# → 3 us-east-1b
# → 3 us-east-1c  # ← multi-AZ confirmed

# Проверка PDB (Pod Disruption Budget)
kubectl get pdb -n production
# → NAME                        MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS
# → payment-service-pdb         2               N/A               1

# Проверка SLO алертов
curl -s 'http://prometheus:9090/api/v1/rules' | jq '.data.groups[] | select(.name | contains("slo")) | .rules[] | {alert: .alert, expr: .expr}'
```

---

### Измерение 2: Security (Безопасность)

**Вопрос:** Безопасен ли сервис для обработки данных и взаимодействия с пользователями?

#### Критерии:

| Критерий | Уровень 1 | Уровень 2 | Уровень 3 | Уровень 4 |
| :--- | :--- | :--- | :--- | :--- |
| **Secrets management** | ENV variables | SOPS / age / git-crypt | Automatic rotation | Short-lived tokens, Vault |
| **Network policy** | Нет | iptables/nftables default deny | Explicit allow rules | Envoy sidecar mTLS |
| **Image scanning** | Manual | CI/CD scan (Trivy/Grype) | Block critical CVEs | Runtime protection (Falco/Sysdig) |
| **RBAC** | root | Sudoers, unix groups | Least privilege, sudo with logging | RBAC в БД, audit logging |
| **Compliance** | Нет | Audit logging (journald) | GDPR/PCI relevant | Full audit trail, encryption at rest |

#### Проверка Security:

```bash
# Проверка наличия секретов в ENV
env | grep -iE 'password|secret|token|key' | wc -l
# → 0 (ожидается 0 для production)

# Проверка SOPS/age encrypted secrets
find /etc/secrets -name '*.age' -o -name '*.sops' | wc -l
# → 12 (ожидается >0)

# Проверка iptables default deny
sudo iptables -L INPUT -n | grep -i drop
# →Chain INPUT (policy DROP)

# Проверка Trivy в CI/CD
trivy image payment-service:latest --severity HIGH,CRITICAL
# → payment-service:latest (debian 12.4)
# → Total: 0 (HIGH: 0, CRITICAL: 0)

# Проверка audit logging
sudo ausearch -m avc -ts recent | wc -l
# → 0 (или количество ожидаемых denials)

# Проверка encryption at rest (LUKS)
sudo cryptsetup status cryptdisk | grep -c active
# → 1
```

---

### Измерение 3: Observability (Наблюдаемость)

**Вопрос:** Можно ли понять, что происходит внутри сервиса, когда что-то идет не так?

#### Критерии:

| Критерий | Уровень 1 | Уровень 2 | Уровень 3 | Уровень 4 |
| :--- | :--- | :--- | :--- | :--- |
| **Metrics** | Host-level (node_exporter) | Application metrics (RED) | SLO dashboards, burn rate | Alerting on SLO burn rate, recording rules |
| **Logs** | File logging | Structured JSON logs | Centralized (Loki/Promtail) | Correlation with traces, retention tiers |
| **Traces** | Нет | Distributed tracing (Jaeger/Tempo) | Sampling, 100% critical paths | Continuous profiling, flame graphs |
| **Dashboards** | Generic host dashboard | Service-specific dashboard | SLO dashboard, runbook-linked | Dynamic, auto-generated from templates |
| **Alerting** | Noisy alerts | Actionable alerts (SEV1/SEV2) | Runbook-linked, burn rate | Auto-remediation where possible |

#### Проверка Observability:

```bash
# Проверка presence всех golden signals
curl -s 'http://prometheus:9090/api/v1/query?query=rate(http_requests_total[5m])' | jq '.data.result | length'
# → 3 (services with RED metrics)

# Проверка presence дашборда
curl -s 'http://grafana:3000/api/search?query=payment-service' | jq '.[].title'
# → ["Payment Service - Overview", "Payment Service - SLO", "Payment Service - Dependencies"]

# Проверка runbook_url в алертах
curl -s 'http://prometheus:9090/api/v1/rules' | jq '.data.groups[].rules[] | select(.alert | contains("payment")) | .annotations.runbook_url'
# → "https://git.internal/runbooks/payment-service"

# Проверка Loki centralized logging
curl -s 'http://loki:3100/loki/api/v1/query?query={service="payment"}' | jq '.data.result | length'
# → 3 (streams found)
```

---

### Измерение 4: Operations (Эксплуатация)

**Вопрос:** Готов ли команда эксплуатировать сервис в production?

#### Критерии:

| Критерий | Уровень 1 | Уровень 2 | Уровень 3 | Уровень 4 |
| :--- | :--- | :--- | :--- | :--- |
| **On-call** | Нагрузка на тимлида | Rotating on-call, 1 engineer | Tiered escalation, secondary | Follow-the-sun, Grafana OnCall |
| **Runbooks** | Нет | Для SEV1/SEV2 | Для всех алертов | Автоматически проверяемые, auto-generated |
| **Deployment** | Manual, downtime | Blue-green | Canary, automated rollback | Progressive delivery, feature flags |
| **Incident response** | Ad-hoc | Defined severity taxonomy | War room, IC role | Blameless postmortem, action items |
| **Documentation** | README | Architecture diagram | Runbooks, playbooks | Living docs, auto-updated |
| **Capacity planning** | Ad-hoc | Quarterly review | Monthly forecast | Automated, trend-based prediction |

#### Проверка Operations:

```bash
# Проверка настройки on-call (Grafana OnCall)
curl -s 'http://grafana-oncall:8080/api/v1/escalation_policies' | jq '.[] | select(.name | contains("payment")) | .rules'
# → [{"delay": 300, "notify": "primary"}, {"delay": 900, "notify": "secondary"}]

# Проверка feature flags ( Unleash / Flagd )
curl -s 'http://unleash:4242/api/admin/features' | jq '.features[] | {name, enabled, strategies}'
# → {"name":"payment_v3","enabled":false,"strategies":[...]}

# Проверка journalctl для системных ошибок
journalctl -u payment-service --since "1 hour ago" -p err | wc -l
# → 0 (или количество ожидаемых ошибок)
```

---

## Чеклист Production Readiness

### Pre-production Checklist

#### Reliability

- [ ] SLO определены и согласованы с бизнесом
- [ ] Error budget рассчитан и отслеживается
- [ ] Настроены multi-window burn rate алерты
- [ ] Рedesigned for failure: circuit breakers, retries, timeouts, fallbacks
- [ ] Pod Disruption Budget / Disruption Budget настроен
- [ ] Multi-instance / Multi-AZ deployment
- [ ] Автоматический rollback при деградации SLO
- [ ] Бэкап настроен и restore test пройден за последние 30 дней
- [ ] База данных: репликация, `pg_stat_replication` / `SHOW SLAVE STATUS` в норме

#### Observability

- [ ] Дашборд с Golden Signals
- [ ] Дашборд SLO с burn rate
- [ ] Дашборд зависимостей (Dependency Map)
- [ ] Structured JSON логи с correlation ID
- [ ] Centralized logging (Loki/Promtail) настроен
- [ ] Distributed tracing настроен (Jaeger/Tempo)
- [ ] Runbook для каждого SEV1/SEV2 алерта
- [ ] Алерты привязаны к SL (Service Level), а не к utilization

#### Security

- [ ] Secrets в SOPS/age/git-crypt, не в ENV
- [ ] Network policies настроены (iptables/nftables default deny)
- [ ] Image scanning в CI/CD (Trivy/Grype)
- [ ] RBAC с least privilege
- [ ] Audit logging включен (journald, auditd)
- [ ] Encryption at rest для чувствительных данных (LUKS)

#### Operations

- [ ] On-call ротация настроена (Grafana OnCall / ntfy)
- [ ] War room channel создан (Mattermost/Matrix/Jitsi)
- [ ] Postmortem template готов
- [ ] Deployment pipeline с canary или blue-green
- [ ] Rollback procedure документирован
- [ ] Capacity plan на квартал вперед
- [ ] NTP синхронизация проверена на всех хостах (`chronyc tracking`)
- [ ] Sysadmin: проверены диски (`df -h`), память (`free -h`), сеть (`ip a`, `ss -tlnp`)
- [ ] DBA: `pg_isready` / `mysqladmin ping` в CI, репликация в норме

---

### Production Readiness Review (PRR)

**Процесс:** Оценка готовности сервиса перед выводом в production.

| Фаза | Длительность | Участники | Результат |
| :--- | :--- | :--- | :--- |
| **Self-assessment** | 1 день | Владелец сервиса | Заполненный чеклист |
| **Peer Review** | 2–3 дня | SRE, Security, DBA, Sysadmin, PM | Review comments, risk assessment |
| **Final Gate** | 1 час | IC (Incident Commander), Tech Lead | Go/No-go decision |
| **Trial Period** | 2 недели | SRE + команда | Мониторинг метрик, фиксация проблем |
| **Full Production** | Бессрочно | Все | Статус "production-ready" |

**Выходные документы:**
1. Production Readiness Assessment (PRA) — заполненный чеклист.
2. Risk Register — список рисков и mitigation plans.
3. Runbook — инструкция по типичным инцидентам.
4. SLO Document — согласованные SLI/SLO.
5. Backup & Restore Plan — процедуры бэкапа и restore test.

### Automation: Readiness Gate в CI/CD

Readiness Gate можно автоматизировать через Prometheus recording rules + Alertmanager + webhook в CI:

```yaml
# prometheus/rules/readiness_gate.yml
groups:
- name: readiness.gate
  interval: 30s
  rules:
  - alert: ReadinessSLOAttainmentLow
    expr: readiness:slo:attainment_24h < 99.9
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "SLO attainment below 99.9%"
      runbook_url: "https://git.internal/runbooks/readiness-gate"

  - alert: ReadinessErrorBudgetBurnHigh
    expr: readiness:error_budget:burn_rate_1h > 200
    for: 5m
    labels:
      severity: page
    annotations:
      summary: "Error budget burning >2x rate"
      runbook_url: "https://git.internal/runbooks/readiness-gate"
```

```bash
# CI check: query Prometheus before deploy
PROM_URL="http://prometheus:9090"
SLO_ATTAINMENT=$(curl -s "$PROM_URL/api/v1/query?query=readiness:slo:attainment_24h" | jq -r '.data.result[0].value[1]')
BURN_RATE=$(curl -s "$PROM_URL/api/v1/query?query=readiness:error_budget:burn_rate_1h" | jq -r '.data.result[0].value[1]')

if (( $(echo "$SLO_ATTAINMENT < 99.9" | bc -l) )); then
  echo "FAIL: SLO attainment $SLO_ATTAINMENT% < 99.9%"
  exit 1
fi

if (( $(echo "$BURN_RATE > 200" | bc -l) )); then
  echo "FAIL: Error budget burn rate ${BURN_RATE}% > 200%"
  exit 1
fi

echo "PASS: Readiness gate checks passed"
```

---

## Практические сценарии

### Сценарий 1: Оценка нового микросервиса

**Ситуация:** Команда Payments подготовила новый сервис `refund-service`. Требуется оценка готовности к production.

**Процесс оценки:**

```bash
# 1. Проверка SLO
cat slo-document.md | grep -E 'SLI|SLO|Target'
# → SLI: refund_success_rate
# → SLO: 99.95% за 30 дней
# → Target: 99.95% (aligned with business SLA)

# 2. Проверка алертов
curl -s 'http://prometheus:9090/api/v1/rules' | jq '.data.groups[] | select(.name | contains("refund")) | .rules[] | {alert, severity, has_runbook: (.annotations.runbook_url != null)}'
# → [
# →   {"alert": "RefundHighErrorRate", "severity": "page", "has_runbook": true},
# →   {"alert": "RefundLatencyP99", "severity": "warning", "has_runbook": true}
# → ]

# 3. Проверка дашборда
curl -s 'http://grafana:3000/api/search?query=refund-service' | jq '.[].title'
# → ["Refund Service - SLO Dashboard", "Refund Service - Dependencies"]

# 4. Проверка on-call
curl -s 'http://grafana-oncall:8080/api/v1/escalation_policies' | jq '.[] | select(.name | contains("payment")) | .rules'
# → [{"delay": 300, "notify": "primary"}, {"delay": 900, "notify": "secondary"}]

# 5. Проверка security
kubectl get networkpolicy -n production | grep refund
# → refund-service-allow    app=refund     2d
trivy image refund-service:latest --severity CRITICAL
# → refund-service:latest (debian 12.4)
# → Total: 0 (CRITICAL: 0)
```

**Результат:** Все критерии выполнены. Статус: **Go for production**.

### Сценарий 2: Повышение уровня зрелости

**Ситуация:** Сервис `notification-service` на уровне 1 (Basic Production). Цель — поднять до уровня 2 (Managed Production).

**План работ:**

| Неделя | Задача | Критерий успеха |
| :--- | :--- | :--- |
| 1 | Настроить SLO алерты с runbook_url | Все SEV1/SEV2 алерты имеют runbook |
| 2 | Внедрить CI/CD pipeline | Автоматические тесты + деплой |
| 3 | Настроить on-call ротацию | Grafana OnCall / ntfy настроены |
| 4 | Настроить дашборд SLO | Burn rate, error budget visualization |
| 5 | Написать runbooks | 100% покрытие SEV1/SEV2 |
| 6 | Провести first GameDay | Сценарий: отключение БД |

### Сценарий 3: Оценка сервиса на bare metal / VM

**Ситуация:** Сервис `legacy-billing` работает на裸-metal сервере без контейнеризации. Требуется оценка readiness.

**Команды проверки:**

```bash
# 1. NTP синхронизация
chronyc tracking | grep 'System time'
# → System time     : 0.000001 seconds slow of NTP time

# 2. Диски
df -h / /var /backups
# → /dev/sda1  50G   30G   20G  60% /
# → /dev/sdb1  500G  200G  300G  40% /backups

# 3. Память и swap
free -h
# →               total        used        free      shared  buff/cache   available
# → Mem:           32Gi       12Gi       16Gi       256Mi       4Gi       19Gi

# 4. Сеть
ip a show eth0 | grep 'inet '
# → inet 10.0.0.5/24 brd 10.0.0.255 scope global eth0
ss -tlnp | grep ':443'
# → LISTEN 0 128 *:443

# 5. База данных
pg_isready -h localhost -p 5432
# → /var/run/postgresql:5432 - accepting connections
mysqladmin ping -h localhost
# → mysqld is alive

# 6. Мониторинг
systemctl status node_exporter prometheus
# → ● prometheus.service - Prometheus Monitoring
# →    Active: active (running)

# 7. Дашборд
curl -s 'http://grafana:3000/api/search?query=billing' | jq '.[].title'
# → ["Billing Service - Overview"]

# 8. Алерты
curl -s 'http://prometheus:9090/api/v1/rules' | jq '.data.groups[] | select(.name | contains("billing")) | .rules[] | {alert, has_runbook: (.annotations.runbook_url != null)}'
# → [{"alert":"BillingHighErrorRate","has_runbook":true},...]
```

**Результат:** Служба готова к production на bare metal.

### Сценарий 4: Оценка readiness БД

**Ситуация:** PostgreSQL кластер `prod-pg` используется сервисом `payment`. Требуется проверка readiness БД.

```bash
# 1. Replication lag
psql -c "SELECT client_addr, state, sent_lsn, replay_lsn, replay_lag FROM pg_stat_replication;"
# → client_addr    | state    | sent_lsn    | replay_lsn  | replay_lag
# → 10.0.0.10      | streaming| 0/1A0000A0  | 0/1A0000A0  | 0

# 2. Connections
psql -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"
# → 42 (ожидается < max_connections * 0.8)

# 3. Бэкап
ls -la /backups/postgres/ | grep daily
# → -rw-r-----. 1 postgres postgres 2.1G Sep 30 03:00 daily.dump

# 4. Restore test
pg_restore --list /backups/postgres/daily.dump | head -5
# → ;    2629    1259    TABLE DATA public.users
# → ;    2630    1259    TABLE DATA public.payments

# 5. Мониторинг
curl -s 'http://prometheus:9090/api/v1/query?query=pg_up' | jq '.data.result'
# → [{"metric":{"job":"postgres","instance":"prod-pg:5432"},"value":[...]}]
curl -s 'http://prometheus:9090/api/v1/query?query=pg_stat_replication_lag_seconds' | jq '.data.result'
# → [] (lag = 0)
```

### Сценарий 5: Оценка readiness сетевого стека

**Ситуация:** Сервис `api-gateway` принимает трафик через nginx на bare metal.

```bash
# 1. Port listening
ss -tlnp | grep -E ':80 |:443 '
# → LISTEN 0 4096 *:80
# → LISTEN 0 4096 *:443

# 2. TLS сертификат
echo | openssl s_client -connect api.internal:443 -servername api.internal 2>/dev/null | openssl x509 -noout -dates
# → notBefore=Sep 30 00:00:00 2026 GMT
# → notAfter=Dec 29 00:00:00 2026 GMT

# 3. Firewall
sudo iptables -L INPUT -n | grep -i drop
# → Chain INPUT (policy DROP)

# 4. Rate limiting (nginx)
curl -s 'http://localhost:8080/nginx_status' | grep 'Reading:\|Writing:\'
# → Reading: 0 Writing: 1 Waiting: 42
```

---

## Устранение неполадок

### Readiness Gate блокирует деплой, но метрики в норме

**Причина:** Readiness Gate query к Prometheus возвращает stale данные. Проверьте `scrape_interval` и `evaluation_interval`.

```bash
# Проверка времени последнего scrape
curl -s 'http://prometheus:9090/api/v1/targets' | jq '.data.activeTargets[] | select(.job == "node_exporter") | {instance, lastScrape, health}'
# → {"instance":"prod-01:9100","lastScrape":"2026-09-30T11:40:00Z","health":"up"}
```

### SLO attainment низкий, но алертов нет

**Причина:** Burn rate алерты настроены только на SEV1, а SLO деградирует медленно.

```bash
# Проверка multi-window burn rate
curl -s 'http://prometheus:9090/api/v1/query?query=slo:burn_rate:1h' | jq '.data.result'
curl -s 'http://prometheus:9090/api/v1/query?query=slo:burn_rate:6h' | jq '.data.result'
```

### Runbook coverage < 100% для SEV1/SEV2

**Причина:** Новые алерты добавлены без `runbook_url`.

```bash
# Найти алерты без runbook
curl -s 'http://prometheus:9090/api/v1/rules' | jq '.data.groups[].rules[] | select(.severity == "page" or .severity == "warning") | select(.annotations.runbook_url == null) | .alert'
```

### On-call не отвечает на звонок

**Причина:** Неправильная конфигурация escalation policy или устаревший контакт.

```bash
# Проверка escalation policy (Grafana OnCall)
curl -s 'http://grafana-oncall:8080/api/v1/escalation_policies' | jq '.[] | select(.name | contains("payment")) | {name, rules}'

# Проверка статуса дежурного
curl -s 'http://grafana-oncall:8080/api/v1/users/current' | jq '{username, is_on_call, schedule_name}'
```

### Бэкап есть, но restore test падает

**Причина:** Бэкап устарел, поврежден, или не хватает зависимостей (WAL архивы, extensions).

```bash
# Проверка размера бэкапа
ls -lh /backups/postgres/daily.dump
# → -rw-r-----. 1 postgres postgres 2.1G Sep 30 03:00 daily.dump

# Dry-run restore
pg_restore --list /backups/postgres/daily.dump | head -10
# → ;    2629    1259    TABLE DATA public.users

# Проверка наличия WAL архива
ls /var/lib/postgresql/wal_archive/ | tail -5
# → 000000010000000000000001
```

### Дублирующий экземпляр недоступен

**Причина:** Secondary instance не прошла health check или отключена репликация.

```bash
# PostgreSQL
psql -c "SELECT client_addr, state, sent_lsn, replay_lsn FROM pg_stat_replication;"
# → client_addr    | state    | sent_lsn    | replay_lsn
# → 10.0.0.11      | streaming| 0/1A0000A0  | 0/1A0000A0

# Проверка DNS/endpoint
dig +short secondary-pg.internal
# → 10.0.0.11
```

## Лучшие практики

### Разработка

1. **Observability with the code:** Добавляйте метрики, логи и трейсы в код сервиса на этапе разработки, а не после деплоя.

2. **SLO-first design:** Определите SLO до написания кода. Они диктуют архитектурные решения (redundancy, caching, circuit breakers).

3. **Test in production-like environment:** Stage environment должен максимально приближен к production (same infra, same config, same load).

4. **Documentation as code:** Runbooks, architecture diagrams, playbooks хранятся в репозитории рядом с кодом.

### Эксплуатация

1. **Toil < 50%:** Автоматизируйте рутину. Если рутина >50% времени — приоритет автоматизации.

2. **Runbook freshness:** Обновляйте runbooks после каждого инцидента. Устаревший runbook хуже, чем его отсутствие.

3. **Capacity planning:** Планируйте capacity на квартал вперед. Используйте trend analysis, а не реактивный подход.

4. **Game Days:** Ежемесячные учения по сценариям отказов. Не тестируйте только систему — тестируйте людей и процессы.

5. **NTP first:** Перед любым деплоем убедитесь, что NTP синхронизация работает на всех хостах. Без этого корреляция логов и метрик невозможна.

6. **Backup verification:** Автоматизируйте restore test. Бэкап без проверки восстанова — не бэкап.

### Безопасность

1. **Defense in depth:** Не полагайтесь на один слой защиты. Сетевая изоляция + RBAC + audit logging + encryption at rest.

2. **Secrets rotation:** Ротация credentials каждые 90 дней. Никаких hardcoded secrets. Используйте SOPS/age для шифрования секретов в Git.

3. **Audit everything:** Все изменения в production логируются и доступны для аудита (journald, auditd).

4. **Network hardening:** iptables/nftables default deny, explicit allow только для необходимых портов. Регулярный аудит правил.

### Sysadmin / DBA

1. **Hardware health:** Проверяйте SMART (`smartctl -a`), температуру (`sensors`), fan speed перед каждым GameDay.

2. **Disk I/O:** Мониторьте `await`, `util` через `iostat`. Рост `await` > 20ms на SSD — сигнал к действию.

3. **Database readiness:** Перед production deploy убедитесь, что `pg_stat_replication` / `SHOW SLAVE STATUS` показывает 0 lag, connection pool настроен (pgbouncer), vacuum работает.

4. **Memory pressure:** На裸-metal отслеживайте `pspsi` (Pressure Stall Information) через `cat /proc/pressure/memory`. Рост `some` > 5% — признак нехватки RAM.

---

## Граничные случаи

### Legacy-системы

**Проблема:** Legacy-сервисы без метрик, на裸-metal, с ручным деплоем.

**Подход:**
1. Добавьте базовый мониторинг (node_exporter, blackbox_exporter).
2. Определите critical path и добавьте SLO пошагово.
3. Внедрите canary deployment через reverse proxy (nginx).
4. Постепенная миграция на современные практики.

### Multi-tenant

**Проблема:** Разные tenants имеют разные требования к reliability и compliance.

**Подход:**
1. Per-tenant SLO и алерты.
2. Tenant isolation через namespaces или systemd slices.
3. Resource quotas для каждого tenant.
4. Data residency compliance per tenant.

### Global services

**Проблема:** Сервис работает в нескольких регионах, с разной нагрузкой и законодательством.

**Подход:**
1. Per-region SLO с учетом локальных особенностей.
2. Geo-routing и failover между регионами (DNS-based или BGP).
3. Regional data residency compliance.
4. Multi-region chaos engineering.

### Отказ системы мониторинга

**Проблема:** Prometheus/Loki/Grafana недоступны во время инцидента.

**Подход:**
1. Meta-monitoring: отдельный Prometheus следит за основным кластером.
2. Локальное логирование journald + центральный syslog.
3. Alertmanager с резервным каналом (ntfy, Gotify) на случай недоступности Grafana.
4. Ежеквартальный failover test: отключаем primary Prometheus, проверяем работу secondary.

### Миграция с legacy на production-ready

**Проблема:** Сервис в production, но без SLO, мониторинга и runbooks.

**Подход:**
1. Небольшие изменения: добавьте метрики и алерты по одному измерению за неделю.
2. Чек-лист readiness review: пройдите по каждому пункту Pre-production Checklist.
3. DBA: начните с репликации и restore test — это критично.
4. Sysadmin: проверьте NTP, диски, память — это быстро и дает немедленный эффект.

---

## Метрики зрелости

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Deployment Frequency** | Как часто деплоится в production | >1 в день (уровень 3+) |
| **Lead Time for Changes** | Время от commit до production | < 1 день |
| **MTTR** | Среднее время восстановления | < 1 час |
| **Change Failure Rate** | % деплоев, вызвавших инцидент | <15% |
| **SLO Attainment** | % времени, когда SLO выполняется | >99.9% |
| **Runbook Coverage** | % алертов с runbook | 100% SEV1/SEV2 |
| **Postmortem Rate** | Постмортемы в месяц | >0 (каждый инцидент) |
| **Action Item Completion** | % action items в срок | >80% |
| **Toil %** | % времени на рутину | <50% |
| **NTP Drift** | Расхождение времени на хостах | < 1 секунда |
| **Backup Freshness** | Время с последнего успешного бэкапа | < 24 часа |
| **Restore Test Success** | % успешных restore test | 100% |
| **Disk Usage** | Использование диска | < 80% (с запасом для growth) |
| **Memory Pressure** | PSI memory some | < 5% |
| **DB Replication Lag** | Задержка репликации | < 1 секунда |

## Шаблон Runbook

Каждый runbook должен содержать следующие секции:

```markdown
# Runbook: <Название сервиса> — <Название алерта>

## Описание
Что означает этот алерт? Какие CUJ затрагивает?

## Диагностика
1. Проверьте дашборд: <ссылка на Grafana>
2. Проверьте SLO burn rate: <PromQL>
3. Проверьте recent deploys: <CI/CD ссылка>
4. Проверьте БД: `pg_isready`, `mysqladmin ping`

## Действия
### С immediate эффектом
- Step 1
- Step 2

### Если не помогает
- Эскалация: <команда/чат>
- Rollback: <процедура>

## Проверка
Как понять, что проблема решена?
- `curl` health endpoint
- SLO dashboard возвращается к норме
- Алерт исчезает из Alertmanager

## После инцидента
- Обновить этот runbook
- Создать postmortem
```

---

## См. также

- **[Концепции SRE: надежность, метрики и бюджет ошибок](../sre_concepts_main.md)** — SLO/SLI/SLA, error budgets.
- **[Управление инцидентами](./incident_management.md)** — жизненный цикл инцидента.
- **[Обзор Observability](./observability_definitions.md)** — три столпа observability.
- **[Методология мониторинга](./monitoring_methodologies.md)** — USE/RED/Golden Signals.
- **[Meta-Monitoring](./meta-monitoring.md)** — мониторинг самой системы мониторинга.
- **[Chaos Engineering Metrics](../../Chaos_Engineering/chaos_engineering_metrics.md)** — зрелость программы хаос-инжиниринга.
- **[High Availability — обзор](../High_Availability/ha_overview.md)** — архитектурные методы достижения высокого SLO.
- **[Disaster Recovery](../disaster_recovery.md)** — RPO/RTO, стратегии восстановления.
- **[Capacity Planning](../capacity-planning.md)** — планирование ресурсов для поддержания SLO.
- **[Deployment Strategies — сравнение](../CI-CD/Deployment_Strategies/comparison.md)** — выбор стратегии деплоя по blast radius, downtime, rollback speed.
- **[DORA Metrics](../CI-CD/Core_Concepts/dora_metrics.md)** — метрики производительности DevOps.
