# Управление инцидентами и постмортемы (SRE)

## Определения

- **Инцидент (Incident)** — событие, нарушающее нормальную работу сервиса или пайплайна (падение деплоя, недоступность реестра, просадка SLO).
- **MTTA (Mean Time To Acknowledge)** — среднее время до принятия инцидента дежурным.
- **MTTR (Mean Time To Recover/Resolve)** — среднее время восстановления сервиса. В контексте DORA: **Failed Deployment Recovery Time** — время восстановления после сбоя, вызванного деплоем. Подробнее: **[Метрики DORA](./dora_metrics.md)**.
- **MTTD (Mean Time To Detect)** — среднее время до обнаружения инцидента системой мониторинга.
- **Severity (SEV)** — уровень тяжести: SEV1 (критично, простой продукта), SEV2 (частичная деградация), SEV3 (локальная проблема).
- **On-call** — дежурство инженера, готового отреагировать на алерт в нерабочее время.
- **IC (Incident Commander)** — ответственный за координацию во время инцидента; принимает решения о mitigation и escalation.
- **War Room** — координационный канал/созвон во время активного инцидента.
- **Blameless Postmortem** — разбор без поиска виноватых, фокус на системных причинах и action items.
- **RCA (Root Cause Analysis)** — анализ первопричин (метод «5 почему»).
- **Runbook** — пошаговая инструкция реакции на типовой инцидент.
- **Error Budget** — допустимый объём сбоев, связывающий надёжность и скорость выпуска (см. [DORA-метрики](./dora_metrics.md) и [SLO/SLI в глоссарии](./pipeline_glossary.md)).
- **Escalation** — передача инцидента на вышестоящий уровень ответственности при превышении времени реакции или порога SEV.
- **Action Item** — конкретная задача, выявленная в ходе постмортема, с ответственным и сроком.

## Основные концепции

### Жизненный цикл инцидента

1.  **Detect** — алерт (Prometheus/Alertmanager) или сообщение пользователя.
2.  **Triage** — оценка SEV, назначение ответственного (IC — Incident Commander).
3.  **Mitigate** — быстрое снятие симптома (откат деплоя, feature flag, рестарт).
4.  **Resolve** — полное устранение.
5.  **Postmortem** — письменный разбор с таймлайном и action items.

### Severity levels и escalation matrix

| Уровень | Влияние | Пример | Время реакции | Эскалация |
| :--- | :--- | :--- | :--- | :--- |
| **SEV1** | Полный простой продукта, потеря данных | API недоступен, ошибки у всех пользователей | 15 мин | IC → Team Lead → Engineering Manager |
| **SEV2** | Частичная деградация, работающей subset | 10% запросов /checkout возвращают 500 | 30 мин | IC → Senior SRE |
| **SEV3** | Локальная проблема, обходной путь есть | Один endpoint медленный, фоллбэк работает | 2 ч | On-call DevOps/SRE |
| **SEV4** | Косметическая проблема, низкий приоритет | Деплой прошел с warning, метрики в норме | Следующий рабочий день | On-call (рабочее время) |

Эскалация по времени:
1.  0–15 мин: On-call инженер пытается решить проблему.
2.  15–30 мин: Эскалация на старшего инженера/IC.
3.  30–60 мин: Эскалация на team lead/менеджера.
4.  60+ мин: Эскалация на руководство.

### Blameless Postmortem

Принципы: фокус на том, *почему система позволила* ошибке проявиться, а не кто виноват. Обязателен таймлайн (по метрикам и логам), список action items с ответственными и сроками, и связь с error budget. Доменные примеры разбора — в [Frontend incident response](../../CI-CD/Frontend_CI_CD/frontend_incident_response.md) и [Mobile incident response](../../CI-CD/mobile-ci-cd/incident-response-mobile.md).

### Роль CI/CD в инцидентах

Частая причина инцидентов — «плохой деплой». Поэтому критичны: автоматический откат, feature flags (выключение фичи без релиза), canary-прокатка с мониторингом SLO и возможность быстро остановить раскатку. См. [Стратегии развёртывания](./deployment_strategies.md).

Для CI/CD-специфичных сценариев (Runner down, registry outage, pipeline failure, secret leak) см. отдельный файл: **[Incident Response для CI/CD](../GitLab_CI/Advanced/incident_response_cicd.md)**.

### Связь с наблюдаемостью

Без метрик/логов/трасс инцидент не диагностировать. Алерты должны быть actionnable и привязаны к SLO, а не к «шуму» ресурсов. См. [Наблюдаемость пайплайнов](./pipeline_observability.md).

### Роли и зоны ответственности

| Аспект | DevOps | SRE | Sysadmin |
| :--- | :--- | :--- | :--- |
| **Детекция** | Настройка алертов в пайплайне, связь DORA-метрик с инцидентами | Проектирование SLO/SLI, burn rate алерты, настройка Alertmanager | Мониторинг железа/сети/дисков, uptime sensor, watchdog |
| **Triage** | Оценка влияния на пайплайн и деплой | Оценка SEV по SLO/Error Budget, назначение IC | Оценка инфраструктурного влияния (диск, сеть, питание) |
| **Mitigation** | Откат деплоя, feature flag, canary pause | Автономный откат по SLO, judge engine, circuit breaker | Graceful shutdown, drain нод, переключение VIP/HAProxy |
| **Investigation** | Логи пайплайна, артефакты, Git history | Трассировка, Golden Signals, burn rate анализ | journald, syslog, сетевые дампы, tcpdump |
| **Postmortem** | Action items по пайплайну, SBOM, provenance | RCA, 5 почему, безвиновный разбор, action items | Action items по инфраструктуре (железо, сеть, бэкапы) |
| **Prevention** | Quality Gates, SAST/SCA, иммутабельные артефакты | Chaos Engineering, SLO-бюджет, автономная доставка | Золотой образ, Packer, immutable infrastructure |

## Практические сценарии

### Сценарий 1: Шаблон постмортема

```markdown
# Postmortem: SEV2 — сбой деплоя api (YYYY-MM-DD)
**Длительность:** 42 мин | **MTTR:** 42m | **SEV:** 2
**Влияние:** 10% запросов к /checkout возвращали 500.
### Таймлайн
- 10:00 — деплой v1.7.3 через pipeline
- 10:08 — алерт ErrorRate > 1% (SLO нарушен)
- 10:15 — IC объявил инцидент, запущен откат
- 10:42 — восстановление
### Первопричина (5 why)
Переменная окружения не мигрирована → ... → нет проверки в smoke-стадии.
### Action Items
- [ ] Добавить smoke-проверку env в пайплайн (owner: @dev, due: +1w)
- [ ] Запретить деплой без прохождения canary 5 мин (owner: @sre)
```

### Сценарий 2: Быстрый откат деплоя

```bash
# Откат на предыдущий стабильный релиз (пример для оркестратора)
kubectl rollout undo deployment/api --to-revision=42
# → deployment.apps/api rolled back

# Или переключение feature flag без релиза
curl -X POST registry.internal/flags/api-newcart --data '{"enabled":false}'
# → flag updated
```

### Сценарий 3: Алерт, инициирующий инцидент

```yaml
# prometheus_alerts.yml — привязка к SLO, а не к шуму
- alert: CheckoutErrorBudgetBurn
  expr: job:error_rate{job="api"} > 0.01
  for: 5m
  labels: { severity: page }
  annotations: { summary: "SLO /checkout нарушен — возможен инцидент" }
```

### Сценарий 4: Runbook «Отказ реестра артефактов»

```bash
# 1. Проверка доступности registry
curl -sSL https://registry.example.com/v2/_catalog
# → {"repositories":[...]} или ошибка соединения

# 2. Проверка диска на registry-ноде
df -h /var/lib/registry
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sdb1       500G  450G   50G  90% /var/lib/registry

# 3. Очистка кеша и неиспользуемых образов
docker system prune -a -f
# → Total reclaimed space: 45.2GB

# 4. Переключение на fallback registry
export CI_REGISTRY=fallback-registry.internal
```

Для CI/CD-специфичных runbooks (Runner down, pipeline failure, secret leak, deployment failure) см. **[Incident Response для CI/CD](../GitLab_CI/Advanced/incident_response_cicd.md)**.

### Сценарий 5: Исследование инцидента через логи и метрики

```bash
# 1. Таймлайн: найти первое появление ошибки в логах
journalctl -u myapp --since "10:00" --until "10:30" | grep -E "ERROR|panic|fatal" | tail -20
# → 2026-09-27T10:08:12Z ERROR failed to connect to db: connection refused

# 2. Просмотр дашборда Golden Signals во время инцидента
curl -s 'http://localhost:9090/api/v1/query_range?query=rate(http_requests_total{status=~"5.."}[5m])&start=10:00&end=10:30&step=60'
# → metric data для анализа burn rate

# 3. Поиск изменений в Git в окне инцидента
git log --oneline --since "2026-09-27 09:30" --until "2026-09-27 10:30"
# → a1b2c3d feat: migrate env vars (10:02)

# 4. Проверка артефактов деплоя
kubectl rollout history deployment/api
# → REVISION  CHANGE-CAUSE
# → 42        deploy v1.7.3 (10:00)
# → 41        deploy v1.7.2 (2026-09-26)
```

## Операции и команды

### Исследование инцидента: логи и метрики

```bash
# Поиск инцидентов в логах systemd-юнита
journalctl -u myapp --since "1 hour ago" --priority=err
# → список ERROR-записей за последний час с таймстемпами

# Фильтр по шаблону (например, panic/fatal)
journalctl -u myapp --since "2026-09-27 10:00" | grep -E "panic|fatal|segfault"
# → 2026-09-27T10:08:12Z panic: runtime error: invalid memory address

# Статистика по уровням логов
journalctl -u myapp --since "today" | awk '{print $3}' | sort | uniq -c | sort -rn
# → 15234 INFO
# → 312 ERROR
# → 12 WARNING
```

```bash
# Анализ метрик Prometheus: burn rate для SLO
curl -s 'http://localhost:9090/api/v1/query?query=rate(http_requests_total{status=~"5.."}[1h]) / rate(http_requests_total[1h])'
# → {"status":"success","data":{"resultType":"vector","result":[]}}

# Error budget за 30 дней (пример для 99.9% SLO)
curl -s 'http://localhost:9090/api/v1/query?query=sum(rate(http_requests_total{status=~"5.."}[30d])) / sum(rate(http_requests_total[30d]))'
# → 0.0002 (0.02% ошибок, бюджет ещё не исчерпан)
```

### Проверка состояния сервиса во время инцидента

```bash
# Проверка статуса Deployment и ревизий
kubectl rollout status deployment/myapp --timeout=10s
kubectl rollout history deployment/myapp
# → REVISION  CHANGE-CAUSE
# → 42        deploy v1.7.3 (10:00)

# Статус подов
kubectl get pods -l app=myapp
# → NAME                    READY   STATUS    RESTARTS   AGE
# → myapp-7d9f8b6c-x2abc    1/1     Running   0          5m
# → myapp-7d9f8b6c-y3def    0/1     CrashLoopBackOff  3   5m

# Логи упавшего пода
kubectl logs myapp-7d9f8b6c-y3def --previous
# → panic: runtime error: invalid memory address
```

```bash
# Проверка ресурсов ноды (Sysadmin-диагностика)
ssh node01 "df -h /var/lib/kubelet && free -h && top -bn1 | head -20"
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1       500G  420G   80G  84% /
# →               total        used        free      shared  buff/cache   available
# → Mem:            32Gi       28Gi        1Gi       256Mi       3Gi        3Gi
```

### Traefik — просмотр роутов и состояния

```bash
# Проверка доступности Traefik API (если включен)
curl -s http://localhost:8080/health
# → {"status":"UP"}

# Просмотр роутов и backend'ов
curl -s http://localhost:8080/api/http/routers | jq .
# → список routers с service, entryPoints, status

# Проверка состояния сервисов
curl -s http://localhost:8080/api/http/services | jq .
# → {"myapp":{"loadBalancer":{"servers":[...]}}}
```

### Создание war room и коммуникация

```
# Шаблон уведомления о начале инцидента (Slack/Telegram)

🔴 INCIDENT STARTED
Title: [SERVICE] — краткое описание
Severity: SEV-X
Start Time: YYYY-MM-DD HH:MM UTC
Duration: X минут

Affected Systems:
- service-api (Deployment: api)
- Registry (fallback активен)

Impact:
- 10% запросов /checkout возвращают 500
- Доступность: 99.9% → 99.5% за окно наблюдения

On-call Engineer: @name
Incident Commander: @name
War Room: #incidents-sev2

Status: Investigating
Next Update: через 15 мин
```

### Восстановление и верификация

```bash
# Откат и проверка
kubectl rollout undo deployment/api
kubectl rollout status deployment/api --timeout=60s
# → deployment "api" successfully rolled out

# Проверка health-эндпоинта
curl -fsS http://api.internal/healthz
# → {"status":"ok","db":"connected"}

# Проверка SLO-метрик после восстановления
curl -s 'http://localhost:9090/api/v1/query?query=job:error_rate{job="api"}'
# → < 0.01 (SLO восстановлен)

# Закрытие инцидента
echo "Incident resolved at $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /var/log/incidents.log
```

## Типичные ошибки и решения

| Симптом | Причина | Решение | Роль |
| :--- | :--- | :--- | :--- |
| **MTTD растет** | Алерты на шум ресурсов, а не на SLO | Перенести алерты на SLO/Error Budget; добавить burn rate | SRE |
| **MTTA растет** | On-call ротация не настроена, эскалация не работает | Настроить PagerDuty/OpsGenie, включить повторные алерты | SRE / DevOps |
| **Нет контекста при тригере** | Алерт без runbook ссылки, нет таймлайна | Добавить в аннотации Alertmanager ссылку на runbook и дашборд | SRE / DevOps |
| **Поиск виноватых** | Культура blame, нет безвиновного постмортема | Ввести правило: первый постмортем без поиска виноватых, далее action items | SRE / Team Lead |
| **Action items без ответственных** | Нет владельца или сроков в постмортеме | Шаблон postmortem с полями owner + due date; трекинг в Jira/GitLab Issues | SRE / DevOps |
| **Инцидент повторяется** | Нет RCA или action items не выполнены | Провести RCA, добавить тест/алерт/runbook, назначить review date | SRE / DevOps |
| **War Room не создан** | Нет шаблона коммуникации | Подготовить шаблоны (начало/обновление/закрытие) и канал заранее | DevOps / SRE |
| **Откат занимает > 15 мин** | Нет runbook, откат через rebuild вместо rollback | Задокументировать команды отката, протестировать на DR-площадке | DevOps / Sysadmin |
| **Столпление алертов** | Alertmanager не группирует, repeat_interval слишком частый | Настроить `group_by`, `group_interval`, `repeat_interval` | SRE / DevOps |
| **Ошибка «тихого» инцидента** | Деградация не покрыта алертами (нет SLO на логику) | Добавить SLI на бизнес-операции (checkout rate, login success) | SRE |
| **Постмортем откладывается** | Нет владельца или deadline после инцидента | Внести в процедуру: postmortem запланирован на 48h, владелец — IC | SRE / DevOps |
| **Эскалация не срабатывает** | PagerDuty/OpsGenie не настроен, on-call недоступен | Настроить escalation policy: повтор через 15/30 мин, звонок через 60 мин | SRE |
| **Критичный алерт в рабочее время** | On-call ротация включает рабочее время для SEV3/SEV4 | Разделить on-call (рабочее/нерабочее) по severity | SRE / DevOps |
| **Откат не проверен** | Откат выполнен, но smoke-тест не пройден | Включить верификацию в runbook: healthcheck + SLO-метрики | DevOps / Sysadmin |
| **Артефакты RCA потеряны** | Логи container'а удалены после отката | Настроить центральный сбор логов (journald → Loki/ELK) | Sysadmin / SRE |
| **Config drift после ручного фикса** | Инженер зашел на сервер и исправил вручную | Ввести rule: все изменения через IaC; drift-детекция ежедневно | Sysadmin / DevOps |
| **Не определён Error Budget** | SLO не зафиксирован, алерты на абсолютные значения | Определить SLO и Error Budget до инцидента; записать в runbook | SRE |
| **Алерт срабатывает на maintenance** | Дежурный получает шум во время плановых работ | Настроить silencing/mute для maintenance-окон; календарь в Alertmanager | SRE / DevOps |

## Лучшие практики

### Подготовка и культура

1. **Безвиновный постмортем по умолчанию:** первый разбор без поиска виноватого, фокус на системных причинах. Повторяющиеся инциденты после фикса — сигнал, что postmortem не работает.
2. **Runbook на каждый типовой инцидент:** команды должны быть готовы к копированию, проверены на DR-площадке, содержат шаги верификации.
3. **On-call ротация:** четкое разделение по severity и времени; escalation policy с повторными алертами и звонками.
4. **Tabletop exercises:** регулярные учения по сценариям инцидентов в рабочее время; проверка коммуникации и runbook'ов.

### Алертинг и наблюдаемость

5. **Алерты на SLO/Error Budget, а не на ресурсы:** дежурный должен получать только actionnable алерты, связанные с пользовательским опытом.
6. **Fail-Closed:** при недоступности мониторинга или ошибке «судьи» раскатка/алерт останавливается, а не продолжается автоматически.
7. **Burn Rate Multi-Window:** использование нескольких окон (1ч, 6ч, 24ч) для детектирования как всплесков, так и медленных утечек Error Budget.
8. **Correlation ID / Trace ID в логах:** каждый запрос должен иметь уникальный идентификатор для построения таймлайна инцидента.

### Процессы и организация

9. **War Room заранее:** канал и шаблоны коммуникации подготовлены до инцидента; IC назначается автоматически по ротации.
10. **Postmortem в течение 48 часов:** пока контекст свеж; владелец назначается в момент закрытия инцидента.
11. **Action items с владельцем и сроком:** без этих двух полей постмортем не принимается. Трекинг в Jira/GitLab Issues.
12. **Ревью action items:** через 2 недели после постмортема проверяется, что задачи закрыты; если нет — эскалация.
13. **Ежедневный drift check:** `ansible-playbook --check --diff` для Bare Metal/VM, drift-детекция для конфигов breaker/timeout/pool.
14. **Capacity planning для отката:** для Blue/Green и Shadow — 2x ресурсов; для Rolling — N+1 узел для surge.

### Связь с другими дисциплинами

15. **DORA-метрики:** Time to Restore (MTTR) — KPI эффективности реагирования. Цель Elite: < 1 часа. См. **[Метрики DORA](./dora_metrics.md)**.
16. **Reliability Patterns:** Circuit Breaker, Bulkhead, Retry с Backoff — паттерны, предотвращающие инциденты или уменьшающие их радиус. См. **[Паттерны надёжности](./reliability_patterns.md)**.
17. **Deployment Strategies:** Canary с автооткатом, Blue/Green, Feature Flags — технические меры снижения риска релизов. См. **[Стратегии развертывания](./deployment_strategies.md)**.
18. **Pipeline Observability:** SLI/SLO пайплайнов, трейсы, Golden Signals — данные для постмортема по CI/CD-инцидентам. См. **[Наблюдаемость пайплайнов](./pipeline_observability.md)**.

## Дополнительная информация

- **[Метрики DORA](./dora_metrics.md)** — Failed Deployment Recovery Time, Change Failure Rate, связь MTTR с показателями эффективности.
- **[Паттерны надёжности](./reliability_patterns.md)** — Circuit Breaker, Bulkhead, Timeout, Graceful Degradation, Chaos Engineering.
- **[Стратегии развертывания](./deployment_strategies.md)** — Canary, Blue/Green, автоматический откат, feature flags.
- **[Наблюдаемость пайплайнов](./pipeline_observability.md)** — SLI/SLO, трейсы, Golden Signals для CI/CD.
- **[Incident Response для CI/CD](../GitLab_CI/Advanced/incident_response_cicd.md)** — severity levels, escalation matrix, runbooks для Runner/Registry/Pipeline, скрипты отката, шаблоны коммуникации, мониторинг пайплайнов.
- **[Frontend incident response](../../CI-CD/Frontend_CI_CD/frontend_incident_response.md)** — фронтенд-специфичные инциденты (broken deploy, stale SW, CDN).
- **[Mobile incident response](../../CI-CD/mobile-ci-cd/incident-response-mobile.md)** — мобильные инциденты, hotfix, App Store/Google Play откат.
