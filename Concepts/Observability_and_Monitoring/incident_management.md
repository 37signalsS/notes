# Управление инцидентами (Incident Management)

**Актуально для:** Prometheus 3.13.x, Grafana Alerting 11.x, Grafana OnCall, Alertmanager, Loki 3.x, Linux 5.4+ (PSI), PostgreSQL 14–17, MySQL 8.0/8.4, Zabbix 7.0 LTS/7.4, Netdata 2.x

## Определения

- **Инцидент (Incident)** — неожиданное событие, вызывающее деградацию или полную потерю работоспособности сервиса, требующее немедленного реагирования для минимизации влияния на пользователей и бизнес.

- **Severity (Серьезность)** — классификация инцидента по влиянию на пользователей и бизнес. Определяет скорость реакции, состав команды и каналы коммуникации.

- **Incident Commander (IC)** — ответственный за координацию реагирования на инцидент: принимает решения, распределяет задачи, коммуницирует с заинтересованными сторонами.

- **Triage (Сортировка)** — процесс первичной оценки инцидента: определение severity, назначение ответственных, выбор стратегии реагирования.

- **War Room (Комната боевых действий)** — временный канал коммуникации (Mattermost, Jitsi, ntfy) для всех участников реагирования.

- **MTTD (Mean Time To Detect)** — среднее время от возникновения сбоя до его обнаружения системой мониторинга.

- **MTTI (Mean Time To Identify)** — среднее время от обнаружения до правильной идентификации проблемы.

- **MTTR (Mean Time To Recovery)** — среднее время от возникновения сбоя до полного восстановления сервиса.

- **MTTV (Mean Time To Verify)** — среднее время на проверку, что инцидент действительно решен.

- **Runbook** — пошаговая инструкция реагирования на типичный инцидент.

- **Postmortem (Постмортем)** — документированный анализ инцидента, фокусирующийся на системных причинах и action items.

- **Action Item** — конкретное исправление процесса или системы, выявленное в результате постмортема, с назначенным ответственным и дедлайном.

- **Near-Miss (Почти-инцидент)** — событие, которое могло привести к инциденту, но было обнаружено и предотвращено до влияния на пользователей.

---

## Архитектура и принципы

### Пайплайн реагирования на инцидент

```
Alert → Alertmanager → Grafana OnCall / ntfy → War Room → Runbook → Resolution → Postmortem
```

- **Alert:** Срабатывание правила на SLO burn rate, Golden Signals или hardware anomaly.
- **Alertmanager:** Группировка, подавление, маршрутизация по severity.
- **On-Call:** График дежурств, эскалация по времени, подтверждение (ack).
- **War Room:** Единый канал коммуникации (Mattermost/Matrix/Jitsi).
- **Runbook:** Пошаговая инструкция, привязанная к алерту через `runbook_url`.
- **Postmortem:** Безвиновный анализ, action items, обновление runbook.

### Критические зависимости

1. **NTP:** Все временные метки в логах, метриках и таймлайне инцидента должны быть синхронизированы. Разница > 1 секунды делает корреляцию невозможной.
2. **Scrape reliability:** Если Prometheus не добрал данные до алерта — MTTD растет. Используйте `scrape_timeout_seconds` и `evaluation_interval` в Alertmanager.
3. **Label hygiene:** Лейблы `service`, `severity`, `team`, `region` должны присутствовать во всех алертах. Без них группировка и маршрутизация не работают.
4. **Runbook as Code:** Runbook хранится в Git рядом с кодом сервиса. Каждый алерт содержит `runbook_url`. Устаревший runbook хуже, чем его отсутствие.

### Recording rules для метрик инцидентов

```yaml
groups:
- name: incident.sli
  interval: 30s
  rules:
  - record: incident:errors:rate5m
    expr: sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100

  - record: incident:latency:p99_5m
    expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))

  - record: incident:replication:lag_seconds
    expr: max(pg_stat_replication_lag_seconds) by (instance)
```

---

## Базовые концепции

### Жизненный цикл инцидента

Каждый инцидент проходит через пять обязательных фаз:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Detection  │ -> │  Response   │ -> │ Mitigation  │ -> │ Resolution  │ -> │  Learning   │
│   (MTTD)    │    │   (MTTI)    │    │   (MTTF)    │    │   (MTTV)    │    │ (Postmortem)│
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

#### Phase 1: Detection (Обнаружение)

**Цель:** Обнаружить инцидент как можно раньше, до того как он затронет значительное число пользователей.

- **Активный мониторинг:** Алерты на Golden Signals, SLO burn rate, error budget.
- **Пассивный мониторинг:** Synthetic monitoring, RUM (Real User Monitoring).
- **Коллективные сигналы:** Отчеты пользователей в support, социальных сетях, status page.
- **Автономные системы:** Self-healing (auto-restart, circuit breaker) могут скрыть инцидент от дежурного, но не от метрик.

**Ключевые метрики:**
- MTTD — целевое значение зависит от критичности сервиса:
  - SEV1: < 1 минута
  - SEV2: < 5 минут
  - SEV3: < 15 минут

#### Phase 2: Response (Реагирование)

**Цель:** Быстро оценить масштаб проблемы и собрать правильную команду.

- **Активация War Room:** Создание временного канала коммуникации.
- **Назначение Incident Commander:** Ответственный за координацию.
- **Triage:** Определение severity, привлечение экспертов.
- **Первичная диагностика:** Сбор логов, метрик, таймлайна событий.

**Алгоритм первичного triage (0–5 минут):**
1. Проверить дашборды сервиса в Grafana.
2. Проверить логи последних 5–10 минут.
3. Определить: локальная проблема или каскадный сбой?
4. Назначить severity и severity-коммуникацию.

#### Phase 3: Mitigation (Снижение ущерба)

**Цель:** Остановить распространение проблемы и минимизировать влияние на пользователей.

**Стратегии mitigation по приоритету:**
1. **Rollback:** Откат на предыдущую стабильную версию (самый быстрый способ).
2. **Kill Switch:** Отключение проблемной фичи через feature flag.
3. **Rate Limiting:** Ограничение запросов для защиты перегруженных компонентов.
4. **Traffic Shift:** Перенаправление трафика на здоровые инстансы или регионы.
5. **Graceful Degradation:** Отключение не критичных функций для сохранения основного функционала.
6. **Circuit Breaker:** Разрыв цепочки вызовов к проблемному сервису.

**Важно:** Mitigation ≠ Resolution. Цель фазы — остановить кровотечение, а не вылечить болезнь.

#### Phase 4: Resolution (Разрешение)

**Цель:** Полностью устранить корневую причину и восстановить нормальную работу системы.

- **Root Cause Analysis (RCA):** Определение первопричины с использованием 5 Whys или Fishbone diagram.
- **Верификация:** Проверка, что:
  - Метрики вернулись в норму (SLO восстановлен).
  - Очереди опустели.
  - Нет ложных успешных ответов.
- **Наблюдение:** Период усиленного мониторинга (1–2 часа) после восстановления.

#### Phase 5: Learning (Обучение)

**Цель:** Превратить инцидент в улучшения системы и процессов.

- **Безвиновный постмортем:** Фокус на системных причинах, а не на людях. Подробнее: **[Безвиновный постмортем](../sre_concepts_main.md#безвиновный-постмортем-blameless-postmortem)**.
- **Action Items:** Конкретные, измеримые, назначаемые, реалистичные, привязанные ко времени (SMART).
- **Trend Analysis:** Анализ паттернов инцидентов за квартал.
- **Обновление документации:** Runbooks, architecture diagrams, playbooks.

---

### Классификация серьезности (Severity Taxonomy)

Таксономия серьезности определена в **[Концепции SRE](../sre_concepts_main.md#классификация-инцидентов-incident-severity-taxonomy)**. Краткое напоминание:

| Severity | Описание | Время реакции | Время эскалации | Коммуникация |
| :--- | :--- | :--- | :--- | :--- |
| **SEV1 (Critical)** | Полная потеря сервиса для всех пользователей или критического CUJ. Потеря данных. Нарушение SLA. | 5 минут | 15 минут | Status page, Mattermost/Rocket.Chat #incidents, email leadership |
| **SEV2 (Major)** | Деградация сервиса для >10% пользователей. Частичная потеря функциональности. Бюджет ошибок исчерпывается. | 15 минут | 30 минут | Status page, Mattermost/Rocket.Chat #incidents |
| **SEV3 (Minor)** | Проблема затрагивает <10% пользователей. Есть workaround. Бюджет ошибок в пределах нормы. | 1 час | 4 часа | Mattermost/Rocket.Chat #incidents, тикет |
| **SEV4 (Low)** | Cosmetic баги, единичные жалобы. Не влияет на SLO. | 1 рабочий день | По плану | Тикет в backlog |

Подробнее про эскалации и on-call: **[Управление дежурствами](../sre_concepts_main.md#управление-дежурствами-on-call-management)**.

---

### Коммуникация при инциденте

#### Внутренняя коммуникация

**War Room (основной канал):**
- Mattermost/Rocket.Chat #incidents или отдельный War Room в Jitsi/Mattermost.
- Все сообщения должны содержать: `[SEV1][Service][Short description]`.
- Регулярные обновления каждые 15–30 минут.

**Ежечасный отчет для руководства (только SEV1/SEV2):**
- Текущий статус: `Investigating / Identified / Monitoring / Resolved`.
- Влияние: количество пользователей, географическое распространение.
- Действия: что уже сделано, что планируется.
- ETA: предполагаемое время восстановления.

#### Внешняя коммуникация

**Status Page:**
- Обновление в течение 5 минут после определения SEV1/SEV2.
- Тон: factual, без оправданий.
- Частота обновлений: каждые 30 минут или при изменении статуса.

**Customer Support:**
- Ежечасный briefing для support-команды.
- Prepared responses для часто задаваемых вопросов.

---

### Роли в реагировании

| Роль | Ответственность | Кого назначать |
| :--- | :--- | :--- |
| **Incident Commander (IC)** | Координация, коммуникация, принятие решений | Senior SRE / Tech Lead |
| **Technical Lead** | Глубокий technical analysis, написание кода для фикса | Developer / Senior Engineer |
| **Communications Lead** | Внешние и внутренние коммуникации | Product Manager / Tech Writer |
| **Subject Matter Expert (SME)** | Консультация по конкретному компоненту | Владелец сервиса |
| **Scribe** | Документирование таймлайна и решений | Junior Engineer / Intern |

**Важно:** IC не должен быть deeply technical. Его задача — координация, а не debugging. Technical Lead отвечает за technical aspects.

### Роли и зоны ответственности (DevOps / SRE / Sysadmin)

| Аспект | DevOps | SRE | Sysadmin |
| :--- | :--- | :--- | :--- |
| **Детекция** | Настройка алертов в пайплайне, связь DORA-метрик с инцидентами | Проектирование SLO/SLI, burn rate алерты, настройка Alertmanager | Мониторинг железа/сети/дисков, uptime sensor, watchdog |
| **Triage** | Оценка влияния на пайплайн и деплой | Оценка SEV по SLO/Error Budget, назначение IC | Оценка инфраструктурного влияния (диск, сеть, питание) |
| **Mitigation** | Откат деплоя, feature flag, canary pause | Автономный откат по SLO, judge engine, circuit breaker | Graceful shutdown, drain нод, переключение VIP/HAProxy |
| **Investigation** | Логи пайплайна, артефакты, Git history | Трассировка, Golden Signals, burn rate анализ | journald, syslog, сетевые дампы, tcpdump |
| **Postmortem** | Action items по пайплайну, SBOM, provenance | RCA, 5 почему, безвиновный разбор, action items | Action items по инфраструктуре (железо, сеть, бэкапы) |
| **Prevention** | Quality Gates, SAST/SCA, иммутабельные артефакты | Chaos Engineering, SLO-бюджет, автономная доставка | Золотой образ, Packer, immutable infrastructure |

---

## Практические сценарии

### Сценарий 1: Каскадный сбой в Kubernetes-кластере

**Ситуация:** Падение 80% подов в namespace `production` после обновления ConfigMap.

**Действия:**

```bash
# 1. Проверка статуса подов
kubectl get pods -n production -o wide | grep -E 'CrashLoop|Pending|ImagePullBackOff'
# → NAME                     READY   STATUS             RESTARTS   AGE
# → payment-service-7d9f4    0/1     CrashLoopBackOff   12         3m

# 2. Проверка событий namespace
kubectl get events -n production --sort-by='.lastTimestamp' | tail -20
# → Warning  FailedMount  2m  kubelet  MountVolume.SetUp failed for volume "config" ...

# 3. Проверка ConfigMap, вызвавшей сбой
kubectl describe configmap payment-config -n production
# → Data:
# →   config.yaml: |
# →     database:
# →       host: invalid-host  # ← ошибка: невалидный хост

# 4. Быстрое восстановление: откат ConfigMap
kubectl rollout undo deployment/payment-service -n production
# → deployment.apps/payment-service rolled back

# 5. Проверка восстановления
kubectl rollout status deployment/payment-service -n production --timeout=120s
# → deployment "payment-service" successfully rolled out
```

**Post-incident:** Добавить валидацию ConfigMap в CI/CD pipeline. Внедрить Canary для ConfigMap.

### Сценарий 2: Утечка памяти в production

**Ситуация:** Потребление RAM контейнером растет линейно, через 2 часа OOMKill.

**Действия:**

```bash
# 1. Быстрая mitigation: перезапуск подов с увеличенным лимитом памяти
kubectl patch deployment payment-service -n production -p '{"spec":{"template":{"spec":{"containers":[{"name":"payment-service","resources":{"limits":{"memory":"2Gi"}}}]}}}}'
# → deployment.apps/payment-service patched

# 2. Диагностика: сбор метрик heap-памяти
kubectl exec -it deployment/payment-service -n production -- curl -s localhost:8080/metrics | grep jvm_memory_used_bytes
# → jvm_memory_used_bytes{area="heap",id="PS Survivor Space",} 1.23456789e+08
# → jvm_memory_used_bytes{area="heap",id="PS Old Gen",} 1.456789012e+09

# 3. Сбор Flight Recording для анализа утечки
jcmd 1 JFR.start name=incident settings=profile path-to-gc-roots=true duration=60s filename=/tmp/incident.jfr
# → 12345: JFR.start (recording: 60 seconds)

# 4. После stabilization — откат на предыдущую версию
kubectl rollout undo deployment/payment-service -n production
```

**Post-incident:** Настроить alerts на скорость роста heap. Добавить алерт на количество GC pauses.

### Сценарий 3: Третьесторонний API поломал интеграцию

**Ситуация:** Payment provider изменил API v2 → v3 без уведомления. 30% платежей failing.

**Действия:**

```bash
# 1. Быстрая mitigation: включение fallback
kubectl set env deployment/payment-service PAYMENT_PROVIDER_FALLBACK=true -n production
# → deployment.apps/payment-service env updated

# 2. Проверка fallback
kubectl logs -l app=payment-service -n production | grep -i fallback
# → INFO  PaymentService - Using fallback provider for 15 transactions

# 3. Верификация метрик
curl -s 'http://prometheus:9090/api/v1/query?query=rate(payment_transactions_total{status="success"}[5m])' | jq '.data.result[0].value[1]'
# → 245.6  # ← метрики восстановлены

# 4. Долгое решение: миграция на API v3
# Отдельный epic на миграцию, feature flag для постепенного rollout
```

### Сценарий 4: Диск заполнен на bare metal/VM

**Ситуация:** `/var` заполнен на 100%, PostgreSQL перестает писать WAL, сервис отдает 500.

**Действия:**

```bash
# 1. Быстрая mitigation: освобождение места
du -sh /var/log/* | sort -rh | head -10
# → 12G /var/log/postgresql
# → 8G  /var/log/nginx

# Очистка старых логов (с подтверждением)
journalctl --vacuum-time=3d
# → Deleted 1.2G of archived journals.

# 2. Диагностика: какой процесс заполняет диск
df -h
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1       50G   50G  512M 100% /

# 3. Верификация восстановления
pg_isready -h localhost
# → localhost:5432 - accepting connections

curl -s http://localhost:8080/health
# → {"status":"ok"}
```

**Post-incident:** Настроить алерт на `disk_usage_percent > 85%` с runbook. Добавить logrotate или Promtail с rate-limit для сбора логов.

### Сценарий 5: Replication lag в PostgreSQL на self-hosted

**Ситуация:** Реплика отстает на 300 секунд, читающие запросы возвращают stale data.

**Действия:**

```bash
# 1. Быстрая mitigation: переключение читающих запросов на primary
# Если используется PgBouncer или ProxySQL:
echo "SELECT pg_promote();" | psql -h primary-db -U postgres
# → pg_promote
# → 1

# 2. Диагностика lag на реплике
psql -h replica-db -U postgres -c "SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;"
# → 00:05:00.123456

# 3. Проверка сетевых задержек между primary и replica
ping -c 10 replica-db.internal
# → rtt min/avg/max/mdev = 0.3/0.4/0.8/0.1 ms

# 4. Проверка WAL sender процессов на primary
psql -h primary-db -U postgres -c "SELECT pid, state, sent_lsn, replay_lsn, replay_lag FROM pg_stat_replication;"
# →  1 | streaming | 0/1A000000 | 0/1A000000 | 00:00:00
```

**Post-incident:** Добавить алерт `pg_stat_replication_lag_seconds > 30`. Проверить, что `wal_receiver_status_interval` и `wal_keep_size` настроены корректно.

## Устранение неполадок

### Нет ответа от дежурного (MTTA > целевого)

**Причины:**
- Не настроена эскалация по времени в Alertmanager или Grafana OnCall.
- Устаревший график дежурств (никто не обновил настройки после увольнения/отпуска).
- Дежурный отключил уведомления или находится вне зоны покрытия.

**Диагностика:**
```bash
# Проверить активные маршруты Alertmanager
curl -s http://alertmanager:9093/api/v2/alerts | jq '.[] | {alertname, labels, receiver}'

# Проверить конфигурацию эскалации Grafana OnCall
curl -s -H "Authorization: Bearer $GRAFANA_ONCALL_TOKEN" \
  https://oncall.grafana.internal/api/v1/schedules | jq '.results[] | {name, reminders}'
```

**Решение:** Настроить multi-channel escalation (SMS → call → Mattermost → email). Проверить график еженедельно.

### Alert storm при каскадном отказе

**Причины:**
- Алерты не группируются по severity или service.
- Отсутствуют inhibit rules для зависимых алертов.
- `repeat_interval` слишком мал.

**Диагностика:**
```bash
# Проверить количество алертов в Alertmanager
curl -s http://alertmanager:9093/api/v2/alerts | jq 'length'
# → 1247  # ← слишком много
```

**Решение:** Добавить `group_by: [alertname, service, severity]`, `group_wait: 30s`, `repeat_interval: 4h`. Использовать `inhibit_rules` для подавления вторичных алертов.

### Отсутствует runbook или runbook устарел

**Причины:**
- Runbook не обновлялся после изменений в архитектуре.
- `runbook_url` отсутствует в аннотациях алертов.
- Runbook хранится в heads-knowledge, а не в Git.

**Решение:** Для каждого SEV1/SEV2 алерта добавить `runbook_url`. Установить SLA: runbook обновляется после каждого инцидента, к нему есть доступ без VPN.

### War Room превращается в хаос

**Причины:**
- Нет IC или IC слишком technical.
- Несколько человек одновременно вносят изменения.
- Нет scribe — решения не фиксируются.

**Решение:** Четко объявить IC в первых 2 минутах. Только IC утверждает изменения. Scribe документирует каждое решение с временем. Закрыть War Room через 30 минут после Resolution.

### Повторяющиеся инциденты (Repeat Incident Rate > 10%)

**Причины:**
- Action items не закрываются.
- Нет трекинга в Gitea/GitLab Issues.
- Постмортемы пишутся, но не читаются.

**Решение:** Каждый action item — тикет с дедлайном. Отчет по закрытию action items на еженедельном standup. Если инцидент повторился — systemic audit процессов, а не людей.

### Действия во время maintenance window

**Проблема:** Инцидент начинается во время планового maintenance window.

**Решение:**
- Предупредить on-call заранее через календарь и Mattermost/Rocket.Chat.
- Назначить Incident Commander заранее (не дежурный, который выполняет maintenance).
- Использовать отдельный `maintenance` лейбл в Alertmanager для подавления нерелевантных алертов.

---

## Лучшие практики

### Подготовка к инцидентам

1. **Инцидент-менеджмент — это процесс, а не героизм:** Заранее определите роли, escalation paths, каналы коммуникации. Не полагайтесь на импровизацию во время кризиса.

2. **Runbooks для каждого SEV1/SEV2:** Без runbook алерт не сокращает MTTR, а лишь переносит нагрузку на дежурного. Шаблон: симптомы, диагностика, алгоритм действий, контакты. Подробнее: **[Runbook Engineering](../sre_concepts_main.md#runbook-engineering)**.

3. **Регулярные Game Days:** Ежемесячные учения по сценариям инцидентов. Цель — тренировка реакции, а не тестирование системы.

4. **Postmortem без вины:** Каждый инцидент → постмортем → action items → трекинг. Без этого инциденты будут повторяться. Подробнее: **[Безвиновный постмортем](../sre_concepts_main.md#безвиновный-постмортем-blameless-postmortem)**.

5. **Документируйте все:** Таймлайн, решения, контекст. Память ненадежна, а новый инженер должен понять, что произошло, за 30 минут.

### Во время инцидента

1. **IC не debug:** Incident Commander координирует, не пишет код. Это позволяет сохранять overview и принимать решения.

2. **Маленькие шаги:** Каждое изменение должно быть минимальным и проверяемым. Не делайте три правки одновременно.

3. **Коммуницируйте чаще, чем кажется нужным:** Лучше лишнее сообщение, чем тишина, которую interpreting как «все под контролем».

4. **Записывайте все решения:**scribe документирует каждое принятое решение с временем и reasoning.

5. **Не ищите виновных:** Фокус на «как процесс позволил ошибке случиться?», а не «кто виноват?».

### После инцидента

1. **Postmortem в первые 24–48 часов:** Пока детали свежи в памяти.

2. **Action Items должны быть SMART:**
   - Specific (конкретные)
   - Measurable (измеримые)
   - Achievable (достижимые)
   - Relevant (релевантные)
   - Time-bound (с дедлайном)

3. **Priority на systemic fixes:** Если инцидент повторился — проблема не в человеке, а в процессах.

4. **Share learnings:** Постмортем должен быть доступен всей организации. Повторяющиеся инциденты — это organizational learning failure.

### Шаблон Runbook

Каждый SEV1/SEV2 алерт должен иметь привязанный runbook. Минимальный набор секций:

```markdown
# Runbook: <Название алерта>

## Симптомы
- Что видит пользователь?
- Какие метрики/логи подтверждают проблему?

## Диагностика (0–5 минут)
1. Проверить дашборд: <ссылка>
2. Проверить логи: `journalctl -u <service> --since "5 minutes ago"`
3. Проверить метрики: `curl -s 'http://prometheus:9090/api/v1/query?query=<expr>'`

## Действия по mitigation
1. <Конкретное действие> → ожидаемый результат
2. <Конкретное действие> → ожидаемый результат

## Верификация
- Метрика X вернулась в норму
- Очередь Y опустела

## Эскалация
- Если не помогло за N минут → escalate to <роль/команда>

## Контакты
- Incident Commander: <Slack/Matrix ID>
- Service Owner: <Slack/Matrix ID>
- Runbook URL: <Git URL>
```

**Правило:** Runbook обновляется после каждого инцидента, в котором он использовался.

### Граничные случаи

- **Maintenance window во время инцидента:** Предупредить IC заранее. Назначить отдельного IC для maintenance, чтобы дежурный мог сосредоточиться на инциденте.
- **Юридические/ compliance требования:** В некоторых отраслях (финансы, медицина) инцидент требует фиксации в regulator-отчете. Укажите это в runbook заранее.
- **Мульти-site сценарии:** При отказе одного дата-центра escalation идет в другой регион. Убедитесь, что IC имеет доступ к War Room другого региона.
- **Отказ системы мониторинга:** Если Prometheus/Alertmanager недоступны, fallback — watchdog на хосте, синтетические проверки извне, сообщения пользователей.
- **Shallow накопительный эффект:** Небольшие degradation могут накапливаться днями. Алерт на trend (например, `predict_linear`) важнее алерта на абсолютный порог.

---

## Дополнительная информация

### Инструменты управления инцидентами

| Категория | Инструменты | Назначение |
| :--- | :--- | :--- |
| **Alerting & On-Call** | Grafana OnCall, Alertmanager, ntfy, Gotify | Эскалация, ротации, коммуникация |
| **War Room** | Mattermost, Rocket.Chat, Matrix/Element | Синхронная коммуникация |
| **Incident Tracking** | Gitea Issues, GitLab Issues, Zabbix | Трекинг инцидентов, SLA |
| **Status Page** | Cachet, самописный status page на Nginx + JSON | Внешняя коммуникация |
| **Postmortem** | Markdown в Git, Docusaurus, MkDocs | Документирование |
| **Runbook** | MkDocs, Docusaurus, internal Wiki | Инструкции |
| **Metrics & Logs** | Prometheus, Grafana, Loki, Tempo, Zabbix, Netdata | Диагностика |

### Метрики эффективности управления инцидентами

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **MTTD** | Среднее время до обнаружения | < 1 минута для SEV1 |
| **MTTI** | Среднее время до идентификации | < 5 минут для SEV1 |
| **MTTR** | Среднее время до восстановления | < 30 минут для SEV1 |
| **Postmortem Rate** | Количество постмортемов в месяц | >0 (каждый инцидент) |
| **Action Item Completion** | % action items, закрытых в срок | >80% |
| **Repeat Incident Rate** | % повторяющихся инцидентов | <10% |
| **Escalation Rate** | % инцидентов, достигших Tier 2/3 | <20% |

### См. также

- **[Концепции SRE: надежность, метрики и бюджет ошибок](../sre_concepts_main.md)** — SLO/SLI/SLA, error budgets, burn rate, severity taxonomy, on-call management, runbook engineering, blameless postmortem.
- **[Postmortem в CI/CD](../CI-CD/Core_Concepts/incident_response_sre.md)** — incident response в контексте CI/CD.
- **[Alerting Best Practices](./monitoring_alerting_recommendations.md)** — multi-window Burn Rate, runbook_url, severity hierarchy.
- **[Meta-Monitoring](./meta-monitoring.md)** — мониторинг самой системы мониторинга.
- **[Chaos Engineering Metrics](../../Chaos_Engineering/chaos_engineering_metrics.md)** — валидация надежности через инъекции сбоев.
- **[DORA Metrics](../CI-CD/Core_Concepts/dora_metrics.md)** — надежность как 5-я метрика DORA.
- **[Monitoring Methodologies](./monitoring_methodologies.md)** — RED, USE, Golden Signals.
