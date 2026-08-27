# Метрики DORA (DevOps Research and Assessment)

## Определения

- **DORA (DevOps Research and Assessment)** — исследовательская группа, основанная Николь Форсгрен (Nicole Forsgren) и позднее вошедшая в структуру Google Cloud. Группа на основе статистического анализа данных тысяч организаций (исследование «Accelerate» и ежегодный «State of DevOps Report») доказала, что эффективность поставки ПО коррелирует с бизнес-результатами (прибыльностью, долей рынка, удержанием клиентов). Метрики DORA являются индустриальным стандартом (de facto) для измерения баланса между скоростью поставки ПО и стабильностью системы. Важно понимать: DORA измеряет не «производительность разработчика», а **характеристики потока поставки всей инженерной системы** (команда + процессы + инструменты).

- **Deployment Frequency (Частота развертывания)** — частота успешных релизов кода в среду Production. Служит индикатором пропускной способности (throughput) и зрелости процессов автоматизации. Чем выше частота при малых размерах изменений, тем меньше риск каждого отдельного релиза.

- **Lead Time for Changes (Время выполнения изменений)** — время, проходящее от момента фиксации кода (commit) до его успешного запуска в Production. В DORA этот показатель измеряет эффективность CI/CD пайплайна, а не всего цикла разработки (Cycle Time). Cycle Time включает этапы до коммита (планирование, написание кода), тогда как Lead Time for Changes начинается строго с commit/timestamp.

- **Change Failure Rate (CFR, Процент сбоев при изменениях)** — доля изменений, которые привели к деградации сервиса в Production и потребовали немедленного исправления (rollback, hotfix, patch). Измеряется как отношение числа «плохих» деплоев к общему числу деплоев, а не к числу коммитов.

- **Time to Restore Service (Время восстановления обслуживания)** — время, необходимое для восстановления работоспособности сервиса после инцидента или сбоя, вызванного деплоем (или любым другим сбоем в Production). В DORA 2023/2024 это показатель относят к категории эксплуатационных исходов; он тесно связан с MTTR из практик SRE.

- **Reliability (Надежность)** — пятая метрика (добавлена в 2021 году), оценивающая способность команды выполнять свои обязательства перед пользователями (достижение целей SLO/SLA). Она не сводится к отсутствию инцидентов, а измеряет, насколько операционная деятельность (on-call, автоматизация, toil) позволяет удерживать согласованный уровень надежности при росте нагрузки.

### Что считается «развертыванием» (единицей измерения)

Перед сбором метрик команда обязана договориться о том, что именно считается deployment. От этого зависит корректность всех четырёх показателей:

- **Успешный деплой** — изменение, попавшее в Production и прошедшее все гейты (health check, smoke test). Неудачный деплой (упал, откатился) засчитывается в CFR, но не увеличивает Deployment Frequency.
- **Единица — не коммит и не запуск пайплайна.** Если один деплой включает 50 коммитов — это один деплой. Если один коммит раскатывается в 10 сервисов отдельными релизами — это 10 деплоев (или 1, если договорились считать «релиз продукта»).
- **Конфигурационные изменения.** Изменение флага, переменной окружения или правила в балансировщике, влияющее на поведение Production, по умолчанию тоже является деплоем. Игнорирование конфиг-изменений занижает CFR и искажает Lead Time.
- **Миграции БД, ручные правки на сервере (sysadmin), изменения в инфраструктуре** — если они меняют поведение Production, их следует учитывать явно, иначе метрики перестают отражать реальный риск.

> **Принцип:** метрика бесполезна, если определение деплоя не зафиксировано и не согласовано. Зафиксируйте определение в runbook до начала сбора.

## Основные концепции

Метрики DORA сгруппированы так, чтобы предотвратить «перекос» в сторону только скорости или только стабильности. Высокая скорость без стабильности ведёт к выгоранию и инцидентам; высокая стабильность без скорости — к потере рыночной релевантности.

| Категория | Метрики | Цель измерения |
| :--- | :--- | :--- |
| **Скорость (Velocity/Throughput)** | Deployment Frequency, Lead Time | Как быстро мы поставляем ценность? |
| **Стабильность (Stability/Quality)** | Change Failure Rate | Насколько надёжны наши изменения? |
| **Эксплуатация (Performance/Outcomes)** | Time to Restore, Reliability | Как быстро мы чиним и держим обещания? |

> **Важно:** Целевые показатели (benchmarks) не являются константой и обновляются в ежегодных отчетах **State of DevOps Report**. Ниже приведены актуальные данные для 2024 года. Границы между уровнями со временем смещаются, поэтому ориентируйтесь на динамику своей команды, а не на абсолютное попадание в Elite.

### Сводная таблица уровней зрелости (2024)

| Метрика | Elite | High | Medium | Low |
| :--- | :--- | :--- | :--- | :--- |
| **Deployment Frequency** | По запросу (несколько раз в день) | От 1/нед до 1/день | От 1/мес до 1/нед | Реже 1/мес |
| **Lead Time for Changes** | < 1 дня | От 1 дня до 1 недели | От 1 недели до 1 месяца | > 1 месяца |
| **Change Failure Rate** | 0–15% | 16–30% | 16–30% (разрыв с High сокращается) | > 45% |
| **Time to Restore Service** | < 1 часа | < 1 дня | < 1 дня | > 1 недели |
| **Reliability (SLO)** | ≥ 99.9% приемлемой работы, бюджет ошибок не исчерпан | 99.5–99.9% | 99–99.5% | < 99% или бюджет ошибок постоянно сгорает |

### Детальное описание и уровни зрелости

**1. Deployment Frequency (Частота развертывания)**
- **Фокус:** Миниатюризация пакетов работы и автоматизация CD.
- **Источники данных:** CI/CD (успешные job деплоя), GitOps-синхронизации, системный лог деплоев (sysadmin), системы релизов (Helm/Jenkins/GitLab).
- **Формула:** `DF = Количество успешных деплоев в Production / период (день/неделя/месяц)`.
- **Уровни:**
  - *Elite:* По запросу (несколько раз в день).
  - *High:* От одного раза в неделю до одного раза в день.
  - *Medium:* От одного раза в месяц до одного раза в неделю.
  - *Low:* Реже одного раза в месяц.

**2. Lead Time for Changes (Время выполнения изменений)**
- **Фокус:** Устранение узких мест в пайплайне (очереди на ревью, долгое тестирование).
- **Источники данных:** VCS (время коммита) + система деплоя (время успешного релиза); корреляция по commit SHA.
- **Формула:** `Lead Time = t(успешный деплой в Prod) − t(commit)`.
- **Декомпозиция этапов:**
  1. **Coding Time:** От первого коммита до создания PR/MR.
  2. **Review & Test:** Время прохождения пайплайнов и аппрувов.
  3. **Wait for Deploy:** Время нахождения в очереди на деплой.
- **Уровни:**
  - *Elite:* Менее 1 дня.
  - *High:* От 1 дня до 1 недели.
  - *Medium:* От 1 недели до 1 месяца.
  - *Low:* Более 1 месяца.

**3. Change Failure Rate (CFR)**
- **Фокус:** Качество автоматизированных тестов и безопасность процесса релиза (Canary, Blue-Green).
- **Источники данных:** записи деплоев со статусом + записи инцидентов/откатов.
- **Формула:** `CFR = (Число деплоев, потребовавших rollback/hotfix/patch) / (Общее число деплоев) × 100%`.
- **Уровни:**
  - *Elite:* 0–15%.
  - *High:* 16–30%.
  - *Medium:* 16–30% (разрыв между High и Medium сокращается).
  - *Low:* Более 45%.

**4. Time to Restore Service (Время восстановления)**
- **Фокус:** Наблюдаемость (Observability) и автоматизация откатов.
- **Источники данных:** система алертинга/инцидентов (время начала) + подтверждение восстановления (health check, алерт «resolved»).
- **Формула:** `TTRS = t(восстановление подтверждено) − t(начало инцидента/сбоя)`.
- **Связь с SRE:** Напрямую зависит от декомпозиции MTTR (TTD, TTN, TTDi, TTF). Подробнее см. в **[Концепции SRE](../../Concepts/sre_concepts_main.md#декомпозиция-mttr-для-оптимизации)**.
- **Уровни:**
  - *Elite:* Менее 1 часа.
  - *High:* Менее 1 дня.
  - *Medium:* Менее 1 дня.
  - *Low:* Более 1 недели.

**5. Reliability (Надежность)**
- **Фокус:** Способность удерживать согласованный уровень обслуживания (SLO) под реальной нагрузкой.
- **Источники данных:** SLI (технические индикаторы), SLO (цель), бюджет ошибок (error budget).
- **Связь с SRE:** Reliability — это операционное выражение SLO. Если бюджет ошибок исчерпан, новые фичи замораживаются в пользу стабилизации. Подробнее см. в **[Концепции SRE](../../Concepts/sre_concepts_main.md)**.
- **Признаки уровня:** Elite — SLO достигнут, бюджет ошибок не сгорает; Low — постоянные нарушения SLO, дежурства выгорают.

### DORA и фреймворк SPACE

В современной инженерии метрики DORA (сфокусированные на техническом потоке) дополняются фреймворком **SPACE** для учета человеческого фактора:
- **S**atisfaction (Удовлетворенность).
- **P**erformance (Производительность глазами бизнеса).
- **A**ctivity (Активность: количество коммитов, PR).
- **C**ommunication (Сотрудничество).
- **E**fficiency (Эффективность и когнитивная нагрузка).

### DORA и инженерные практики (SRE / DevOps)

Метрики не существуют сами по себе — они улучшаются через конкретные практики:

- **Trunk-Based Development** сокращает Lead Time и снижает CFR за счёт маленьких, частых интеграций. См. **[Рабочие процессы в Git](../../Git/git_workflows.md)**.
- **Health Checks и автоматический rollback** снижают TTRS и CFR. См. **[Health Checks и rollback](../Deployment_Strategies/deployment_health_checks_and_rollback.md)**.
- **Error Budget Policy (SRE)** превращает Reliability из абстракции в управляемый процесс принятия решений.
- **Observability** — фундамент, без которого TTRS и Reliability невозможно измерить честно. См. **[Наблюдаемость](../../Concepts/Observability_and_Monitoring/observability_definitions.md)** и **[Наблюдаемость пайплайнов](./pipeline_observability.md)**.
- **Chaos Engineering** выявляет слабые места до деплоя, снижая CFR и улучшая TTRS. См. **[Интеграция Chaos и DORA](../../Chaos_Engineering/chaos_engineering_metrics.md#интеграция-с-dora)**.

## Практические сценарии

Перед сбором любой метрики выполните подготовку:

**Предварительные требования (Prerequisites):**
- Доступ к VCS (Git) с историей коммитов и возможностью извлекать `commit timestamp` и SHA.
- Доступ к системе деплоя (CI/CD, GitOps, либо системный лог деплоев) с фиксацией успешных/неуспешных релизов и среды (Production/не-Production).
- Система учёта инцидентов (ticketing, Alertmanager, on-call) с временем открытия и закрытия.
- Согласованное определение «деплоя» и список Production-сред (см. раздел Определения).
- Для Dashboard — сервер метрик (Prometheus, либо простая БД/файл), Grafana опционально.

**Общая методология сбора (event model):**
1. Каждая система (VCS, CI, deploy, incident) порождает события с временной меткой и идентификатором (SHA, deploy_id, incident_id).
2. События нормализуются в единую модель: `deploy(sha, env, status, ts)`, `incident(id, ts_start, ts_resolve)`.
3. Метрики вычисляются агрегацией за период (день/неделя/месяц).
4. Результаты визуализируются и сравниваются с уровнями зрелости.

### Сценарий 1: GitLab CI — встроенные DORA-метрики

GitLab (в т.ч. self-hosted) рассчитывает DORA автоматически на основе окружений уровня `production` и событий деплоя. Подробности настройки окружений см. в **[Окружения и развертывания в GitLab CI](../GitLab_CI/Concepts/environments_and_deployments.md)**.

Включение и получение значений через REST API (требуется токен с правами `read_api`):

```bash
# Deployment Frequency за последний месяц (помесячно)
curl --silent --header "PRIVATE-TOKEN: <TOKEN>" \
  "https://gitlab.example.com/api/v4/projects/<PROJECT_ID>/dora/metrics?metric=deployment_frequency&interval=monthly"
# → {"2024-05-01":12,"2024-06-01":15}

# Lead Time for Changes
curl --silent --header "PRIVATE-TOKEN: <TOKEN>" \
  "https://gitlab.example.com/api/v4/projects/<PROJECT_ID>/dora/metrics?metric=lead_time_for_changes&interval=monthly"
# → {"2024-05-01":86400,"2024-06-01":43200}

# Change Failure Rate (доля в процентах)
curl --silent --header "PRIVATE-TOKEN: <TOKEN>" \
  "https://gitlab.example.com/api/v4/projects/<PROJECT_ID>/dora/metrics?metric=change_failure_rate&interval=monthly"
# → {"2024-05-01":8.3,"2024-06-01":6.7}

# Time to Restore Service (в секундах)
curl --silent --header "PRIVATE-TOKEN: <TOKEN>" \
  "https://gitlab.example.com/api/v4/projects/<PROJECT_ID>/dora/metrics?metric=time_to_restore_service&interval=monthly"
# → {"2024-05-01":1800,"2024-06-01":900}
```

**Валидация:** значения появляются только если в `.gitlab-ci.yml` используется блок `environment: production:` с реальными деплоями. Если метрики пусты — проверьте `deployment_tier` окружения. Dashboard доступен в разделе `Deployments → Metrics` проекта.

### Сценарий 2: Jenkins — сбор из пайплайна и логов

В Jenkins нет встроенного DORA-дашборда, поэтому события деплоя фиксируются явно. Ниже — паттерн записи события деплоя в файл из `Jenkinsfile` (Groovy), который затем парсится внешним скриптом:

```groovy
// Jenkinsfile (фрагмент)
pipeline {
  agent any
  stages {
    stage('Deploy to Prod') {
      steps {
        script {
          def sha = sh(script: 'git rev-parse HEAD', returnStdout: true).trim()
          try {
            // ... команды деплоя ...
            sh "echo \"$(date -u +%Y-%m-%dT%H:%M:%SZ) deploy sha=${sha} env=production status=success\" >> /var/lib/jenkins/deploys.log"
          } catch (e) {
            sh "echo \"$(date -u +%Y-%m-%dT%H:%M:%SZ) deploy sha=${sha} env=production status=failed\" >> /var/lib/jenkins/deploys.log"
            error("Deploy failed")
          }
        }
      }
    }
  }
}
```

Для готовых графиков используется плагин **DORA Metrics Plugin** (читает историю builds) либо экспорт событий в Prometheus через Pushgateway. Валидация: после прогона проверьте, что в `deploys.log` появилась строка со `status=success` и корректным `sha`.

### Сценарий 3: Sysadmin — сбор из системных логов деплоя (без CI-платформы)

В среде без централизованного CI деплои часто выполняются скриптами/ansible/вручную. Метрики всё равно измеримы, если вести лог деплоев и использовать Git как источник времени коммита.

Формат лога `/var/log/deploys.log`:

```text
2024-06-01T10:15:00Z deploy sha=abc1234 env=production status=success
2024-06-02T14:20:00Z deploy sha=def5678 env=production status=failed
2024-06-02T14:45:00Z deploy sha=def5678 env=production status=success
```

Скрипт на Python для расчёта Deployment Frequency и среднего Lead Time (Lead Time берётся из `git log` по SHA):

```python
#!/usr/bin/env python3
# compute_dora.py — минимальный сборщик DORA из лога деплоев + git
import subprocess, re, datetime, collections

DEPLOY_LOG = "/var/log/deploys.log"
PERIOD_DAYS = 30

def commit_time(sha):
    # Время коммита из локального репозитория
    out = subprocess.check_output(
        ["git", "log", "-1", "--format=%cI", sha]
    ).decode().strip()
    return datetime.datetime.fromisoformat(out.replace("Z", "+00:00"))

def deploy_time(ts):
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))

deploys = collections.defaultdict(list)   # sha -> [(ts, status)]
with open(DEPLOY_LOG) as f:
    for line in f:
        m = re.search(r"(\S+) deploy sha=(\w+) env=production status=(\w+)", line)
        if m:
            deploys[m.group(2)].append((m.group(1), m.group(3)))

# Deployment Frequency: уникальные успешные деплои за период
success = [d for s, lst in deploys.items()
           for (ts, st) in lst if st == "success"]
df = len(success)
print(f"Deployment Frequency (за {PERIOD_DAYS} дн.): {df} успешных деплоев")

# Lead Time: успешный деплой минус время коммита
lead_times = []
for sha, lst in deploys.items():
    succ = [ts for ts, st in lst if st == "success"]
    if not succ:
        continue
    dts = deploy_time(succ[0])
    cts = commit_time(sha)
    lead_times.append((dts - cts).total_seconds() / 3600.0)

if lead_times:
    avg = sum(lead_times) / len(lead_times)
    print(f"Средний Lead Time: {avg:.1f} ч ({avg/24:.1f} дн.)")

# Change Failure Rate: деплои с хотя бы одним failed / общее
total = len(deploys)
failed = sum(1 for s, lst in deploys.items() if any(st == "failed" for _, st in lst))
cfr = (failed / total) * 100 if total else 0
print(f"Change Failure Rate: {cfr:.1f}%")
```

**Валидация:** запустите `python3 compute_dora.py`; убедитесь, что `df` совпадает с числом строк `status=success` в логе, а Lead Time — положительное число (если отрицательное, значит деплой помечен раньше коммита — ошибка в логировании).

**Очистка:** лог деплоев ротируется по стандартным правилам (logrotate), парсер не меняет исходные данные. Для гарантии целостности лог пишется в append-only режиме.

### Сценарий 4: SRE — Time to Restore из управления инцидентами

TTRS измеряется по журналу инцидентов. Пример лога `/var/log/incidents.log`:

```text
2024-06-03T08:00:00Z incident id=INC-101 start
2024-06-03T08:42:00Z incident id=INC-101 resolved
```

Расчёт TTRS (в минутах) и фиксация для Reliability:

```bash
# TTRS для инцидента INC-101 (разница меток start/resolved)
START=$(date -d "$(grep 'INC-101 start' /var/log/incidents.log | awk '{print $1}')" +%s)
END=$(date -d "$(grep 'INC-101 resolved' /var/log/incidents.log | awk '{print $1}')" +%s)
echo "TTRS: $(( (END - START) / 60 )) мин"
# → TTRS: 42 мин
```

Связь с наблюдаемостью: TTRS напрямую зависит от TTD (время обнаружения). Если `START` берётся не из алерта, а из жалобы пользователя, TTRS будет завышен и маскирует реальную проблему мониторинга. Декомпозиция MTTR (TTD/TTN/TTDi/TTF) — в **[Концепциях SRE](../../Concepts/sre_concepts_main.md#декомпозиция-mttr-для-оптимизации)**.

**Reliability (SLO/Error Budget)** считается отдельно: например, SLO = «99.9% запросов успешны за 30 дней». Бюджет ошибок = 0.1% = ~43 минуты недоступности на месяц. Если суммарный TTRS по всем инцидентам превышает бюджет — уровень Reliability падает до Low независимо от скорости.

### Сценарий 5: Prometheus (self-hosted) — метрики из событий деплоя

Если используется GitOps (например, ArgoCD), метрики можно извлекать из экспортеров. Для любого деплоя (не только GitOps) удобен Pushgateway, куда скрипт деплоя отправляет событие:

```bash
# После успешного деплоя отправляем метку времени в Pushgateway
TS=$(date +%s)
echo "last_deploy_success_timestamp $TS" | curl --silent --data-binary @- \
  "http://prometheus-pushgateway:9091/metrics/job/deploy_prod/instance/webapp"
```

Запросы PromQL:

```promql
# 1. Deployment Frequency (Кол-во успешных синхронизаций за сутки)
sum(increase(argocd_app_sync_total{phase="Succeeded", dest_namespace="prod"}[24h]))

# 2. Change Failure Rate (Отношение ошибок к общему числу деплоев)
sum(rate(argocd_app_sync_total{phase="Failed"}[1h])) 
/ 
sum(rate(argocd_app_sync_total[1h]))

# 3. Time to Restore — время между алертом Degraded и возвратом в Healthy
#    (через запись длительности инцидента в метрику incident_duration_seconds)
sum(incident_duration_seconds{severity="critical"})
```

**Валидация:** в Grafana запрос (1) должен возвращать целое число ≥ 0; (2) — значение от 0 до 1 (доля); (3) — суммарное время в секундах. Если (2) > 0.45 — команда в зоне Low по CFR.

### Сценарий 6: Four Keys — модель данных для аналитики (SQL)

Подход Google Four Keys строит единую модель событий. Для Lead Time требуется корреляция данных из VCS (GitLab/GitHub) и системы деплоя. Полная схема:

```sql
-- Таблица деплоев (одна строка = один деплой в среду)
CREATE TABLE deployments (
    deploy_id    INTEGER PRIMARY KEY,
    commit_sha   TEXT NOT NULL,        -- SHA коммита, попавшего в прод
    deployed_at  TIMESTAMP NOT NULL,   -- время успешного деплоя
    environment  TEXT NOT NULL,        -- 'production' / 'staging'
    status       TEXT NOT NULL         -- 'success' / 'failed'
);

-- Таблица инцидентов (сбои, требующие починки)
CREATE TABLE incidents (
    incident_id  INTEGER PRIMARY KEY,
    deploy_id    INTEGER REFERENCES deployments(deploy_id), -- какой деплой вызвал
    opened_at    TIMESTAMP NOT NULL,   -- начало инцидента
    resolved_at  TIMESTAMP             -- NULL пока не восстановлено
);

-- 1. Deployment Frequency (успешные деплои в прод за месяц)
SELECT DATE_TRUNC('month', deployed_at) AS mon,
       COUNT(*) AS deploys
FROM deployments
WHERE environment = 'production' AND status = 'success'
GROUP BY mon;

-- 2. Lead Time for Changes (среднее, часы)
SELECT AVG(EXTRACT(EPOCH FROM (d.deployed_at - c.commit_timestamp)) / 3600) AS lead_hours
FROM deployments d
JOIN commits c ON d.commit_sha = c.sha
WHERE d.environment = 'production' AND d.status = 'success';

-- 3. Change Failure Rate (%)
SELECT 100.0 * SUM(CASE WHEN i.incident_id IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*) AS cfr_pct
FROM deployments d
LEFT JOIN incidents i ON i.deploy_id = d.deploy_id
WHERE d.environment = 'production' AND d.status = 'success';

-- 4. Time to Restore Service (среднее, минуты)
SELECT AVG(EXTRACT(EPOCH FROM (i.resolved_at - i.opened_at)) / 60) AS ttrs_min
FROM incidents i
WHERE i.resolved_at IS NOT NULL;
```

**Валидация:** запрос (2) должен возвращать положительное число; если `NULL` — нет связи `commit_sha` с таблицей `commits`. Запрос (4) требует, чтобы `resolved_at` был заполнен (иначе инцидент ещё открыт и TTRS бесконечен).

### Валидация и сверка результатов

После настройки сбора выполните сверку (sanity check):

1. **Треугольник согласованности:** `Deployment Frequency × (1 − CFR/100)` ≈ число «хороших» деплоев. Если не сходится — дублируете или теряете события.
2. **Логические границы:** Lead Time ≥ 0; CFR ∈ [0, 100]; TTRS ≥ 0. Отрицательные значения = ошибка временных меток.
3. **Выбросы:** единичный деплой с Lead Time в месяц часто означает, что в ветке копился код до коммита — проверьте практику ветвления.
4. **Сравнение источников:** если GitLab показывает DF=15, а ваш парсер логов — 9, значит часть деплоев не логируется (ручные правки sysadmin, конфиг-изменения).

### Типичные ошибки измерения (Troubleshooting)

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| DF аномально высокий | Считаются dev/staging деплои или пересборки пайплайна | Фильтруйте по `environment=production` и статусу success |
| Lead Time отрицательный | Деплой помечен раньше коммита / неверная таймзона | Используйте UTC (`date -u`), сверяйте SHA |
| CFR близок к 0% | Откаты не фиксируются как инциденты | Обязательная регистрация rollback/hotfix в `incidents` |
| TTRS завышен | `START` берётся из жалобы юзера, а не алерта | Берите время начала из системы алертинга (TTD) |
| Метрики «красивые, но бесполезные» | Squash/cherry-pick ломают SHA-корреляцию | Коррелируйте по deploy-SHA (реальный в проде), а не по PR |
| Расхождение источников | Ручные/sysadmin-изменения не учтены | Включите конфиг- и инфра-изменения в определение деплоя |

### Лучшие практики и очистка

- **Автоматизируйте сбор**, не собирайте вручную через Excel/Jira — это теряет точность и доверие.
- **Храните сырые события** (логи/таблицы) отдельно от агрегатов; агрегаты пересчитываются, сырьё — нет.
- **Фиксируйте определение деплоя** в runbook и пересматривайте раз в квартал.
- **Не наказывайте команду метриками** — DORA диагностический инструмент, а не KPI для штрафов (иначе возникает «Gaming the metrics»).
- **Очистка:** ротируйте логи деплоев (logrotate), партиционируйте таблицы по месяцам, удаляйте тестовые события не-Production по расписанию.

### Граничные случаи (Edge Cases)

- **Мобильные приложения:** релиз в стор занимает дни/недели — сравнивать с Web-деплоями некорректно; измеряйте частоту merge в релизную ветку как прокси.
- **Миграции БД:** долгие, рискованные; учитывайте отдельно, т.к. они растягивают Lead Time и повышают CFR.
- **Ручные изменения sysadmin** (правка конфига на сервере): если влияют на Production — это деплой; без учёта метрики лгут о стабильности.
- **Rollforward vs Rollback:** если баг исправлен новым деплоем (rollforward), а не откатом — это всё равно сбой (CFR растёт), но TTRS считается до момента восстановления.
- **Периоды низкой активности** (праздники): DF падает не из-за регресса процесса — сравнивайте однородные периоды.

## Белые пятна и вызовы (Антипаттерны)

### Типичные ошибки внедрения

1.  **Gaming the metrics (Манипуляция):** Искусственное дробление задач на микро-коммиты для завышения Deployment Frequency без реальной бизнес-ценности.
2.  **Игнорирование контекста:** Сравнение команд с разным стеком (например, мобильная разработка с недельными релизами в сторы vs Web с деплоем по кнопке).
3.  **Отсутствие Reliability:** Высокая скорость (Elite по Lead Time) при игнорировании SLO приводит к выгоранию команды и нестабильности системы.
4.  **Ручной ввод данных:** Попытка собирать DORA через Excel или Jira вручную ведет к низкой точности и потере доверия к метрикам.
5.  **Смешивание сред:** Учёт staging/ dev деплоев вместе с Production искажает все четыре метрики.
6.  **Conflation Lead Time и Cycle Time:** отчёт «Lead Time = 2 недели» при измерении от планирования до продакшена скрывает реальные узкие места CI/CD.
7.  **Игнорирование TTD в TTRS:** измерение восстановления от жалобы пользователя маскирует слабость мониторинга.

### Как улучшить показатели

- **Для Lead Time:** Внедрение Trunk-Based Development и сокращение времени жизни веток. См. **[Рабочие процессы в Git](../../Git/git_workflows.md)**.
- **Для CFR:** Автоматизация **[Health Checks](../Deployment_Strategies/deployment_health_checks_and_rollback.md)** и внедрение Chaos Engineering для проверки устойчивости. См. **[Интеграция Chaos и DORA](../../Chaos_Engineering/chaos_engineering_metrics.md#интеграция-с-dora)**.
- **Для Deployment Frequency:** миниатюризация задач, автоматизация пайплайна релиза, устранение ручных гейтов.
- **Для Time to Restore:** вложения в наблюдаемость и автоматизированные откаты; отработка инцидентов по SRE-практикам (postmortem, error budget).
- **Для Reliability:** внедрение SLO и бюджета ошибок как управляемого процесса.

## Дополнительная информация

- **Паттерны CI/CD:** [Практики улучшения метрик](../ci_cd_patterns.md).
- **Анти-паттерны CI/CD:** [Ошибки и узкие места](../ci_cd_antipatterns.md).
- **SRE и доступность:** [High Availability](../../Concepts/High_Availability/ha_overview.md) и [Концепции SRE](../../Concepts/sre_concepts_main.md).
- **Наблюдаемость:** [Observability](../../Concepts/Observability_and_Monitoring/observability_definitions.md) как фундамент для сбора метрик и **[Наблюдаемость пайплайнов](./pipeline_observability.md)** для диагностики их эффективности.
- **GitLab CI:** [Окружения и DORA-метрики](../GitLab_CI/Concepts/environments_and_deployments.md).
- **State of DevOps Report** — ежегодные отчеты Google Cloud / DORA.
