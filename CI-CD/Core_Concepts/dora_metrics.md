# Метрики DORA (DevOps Research and Assessment)

## Определения

- **DORA (DevOps Research and Assessment)** — исследовательская группа, основанная Николь Форсгрен (Nicole Forsgren). На основе статистического анализа данных тысяч организаций (исследование «Accelerate» и ежегодный «State of DevOps Report») DORA доказала, что эффективность поставки ПО коррелирует с бизнес-результатами (прибыльностью, долей рынка, удержанием клиентов). Метрики DORA являются индустриальным стандартом (de facto) для измерения баланса между скоростью поставки ПО и стабильностью системы. Важно понимать: DORA измеряет не «производительность разработчика», а **характеристики потока поставки всей инженерной системы** (команда + процессы + инструменты + операционная деятельность).

- **Deployment Frequency (Частота развертывания)** — количество успешных релизов кода в среду Production за единицу времени. Служит индикатором пропускной способности (throughput) и зрелости процессов автоматизации. Чем выше частота при малых размерах изменений, тем меньше риск каждого отдельного релиза.

- **Lead Time for Changes (Время выполнения изменений)** — время, проходящее от момента фиксации кода (commit) до его успешного запуска в Production. В DORA этот показатель измеряет эффективность CI/CD пайплайна, а не всего цикла разработки (Cycle Time). Cycle Time включает этапы до коммита (планирование, написание кода), тогда как Lead Time for Changes начинается строго с commit/timestamp.

- **Change Failure Rate (CFR, Процент сбоев при изменениях)** — доля изменений, которые привели к деградации сервиса в Production и потребовали немедленного исправления (rollback, hotfix, patch, rollforward). Измеряется как отношение числа «плохих» деплоев к общему числу деплоев, а не к числу коммитов.

- **Failed Deployment Recovery Time (Время восстановления после неудачного деплоя)** — formerly Mean Time To Recovery (MTTR) в контексте DORA. Время, необходимое для восстановления работоспособности сервиса после сбоя, вызванного изменением в Production (ошибка в коде, конфигурации или миграции). В отличие от общего MTTR, этот показатель учитывает только сбои, инициированные деплоем, а не внешние факторы (отказ оборудования, сетевые инциденты, катастрофы).

- **Deployment Rework Rate (Коэффициент переделок)** — пятая метрика, добавленная в 2024 году. Доля деплоев, которые являются незапланированной работой по исправлению багов, требующих возврата к предыдущему состоянию или создания патча. Показатель напрямую коррелирует с объемом технического долга, генерируемого процессом поставки.

- **Reliability (Надежность)** — операционная метрика, выходящая за рамки пяти метрик доставки ПО. Оценивает способность команды удерживать согласованный уровень обслуживания (SLO/SLA) под реальной нагрузкой. В контексте DORA Reliability выступает как компенсатор: высокая скорость при низкой Reliability ведёт к выгоранию дежурств и нестабильности системы.

### Что считается «развертыванием» (единицей измерения)

Перед сбором метрик команда обязана договорить о том, что именно считается deployment. От этого зависит корректность всех пяти показателей:

- **Успешный деплой** — изменение, попавшее в Production и прошедшее все гейты (health check, smoke test). Неудачный деплой (упал, откатился) засчитывается в CFR и Deployment Rework Rate, но не увеличивает Deployment Frequency.
- **Единица — не коммит и не запуск пайплайна.** Если один деплой включает 50 коммитов — это один деплой. Если один коммит раскатывается в 10 сервисов отдельными релизами — это 10 деплоев (или 1, если договорились считать «релиз продукта»).
- **Конфигурационные изменения.** Изменение флага, переменной окружения или правила в балансировщике, влияющее на поведение Production, по умолчанию тоже является деплоем. Игнорирование конфиг-изменений занижает CFR и искажает Lead Time.
- **Миграции БД, ручные правки на сервере (sysadmin), изменения в инфраструктуре** — если они меняют поведение Production, их следует учитывать явно, иначе метрики перестают отражать реальный риск.
- **Автоматические обновления (Renovate, Image Updater).** Робот-коммиты увеличивают Deployment Frequency; их либо исключают из подсчета, либо считают отдельной серией, чтобы не искажать метрики команды.

> **Принцип:** метрика бесполезна, если определение деплоя не зафиксировано и не согласовано. Зафиксируйте определение в runbook до начала сбора.

## Основные концепции

Метрики DORA сгруппированы так, чтобы предотвратить «перекос» в сторону только скорости или только стабильности. Высокая скорость без стабильности ведёт к выгоранию и инцидентам; высокая стабильность без скорости — к потере рыночной релевантности.

| Категория | Метрики | Цель измерения |
| :--- | :--- | :--- |
| **Пропускная способность (Throughput)** | Deployment Frequency, Lead Time for Changes | Как быстро мы поставляем ценность? |
| **Нестабильность (Instability)** | Change Failure Rate, Deployment Rework Rate | Насколько надёжны наши изменения? |
| **Восстановление (Recovery)** | Failed Deployment Recovery Time | Как быстро мы чиним и держим обещания? |
| **Эксплуатационная надежность (Operational Reliability)** | Reliability (SLO/SLA) | Как мы удерживаем уровень обслуживания при росте нагрузки? |

> **Важно:** Целевые показатели (benchmarks) не являются константой и обновляются в ежегодных отчетах **State of DevOps Report**. Ниже приведены актуальные данные для 2025–2026 годов. Границы между уровнями со временем смещаются, поэтому ориентируйтесь на динамику своей команды, а не на абсолютное попадание в Elite.

### Сводная таблица уровней зрелости (2025–2026)

| Метрика | Elite (Top 15%) | High (Top 15–30%) | Medium | Low |
| :--- | :--- | :--- | :--- | :--- |
| **Deployment Frequency** | По запросу (несколько раз в день) | От 1/нед до 1/день | От 1/мес до 1/нед | Реже 1/мес |
| **Lead Time for Changes** | < 1 дня | От 1 дня до 1 недели | От 1 недели до 1 месяца | > 1 месяца |
| **Change Failure Rate** | < 4% | 4–8% | 8–16% | > 16% |
| **Failed Deployment Recovery Time** | < 1 часа | < 1 дня | < 1 дня | > 1 недели |
| **Deployment Rework Rate** | < 4% | 4–8% | 8–16% | > 16% |

### Детальное описание и уровни зрелости

**1. Deployment Frequency (Частота развертывания)**
- **Фокус:** Миниатюризация пакетов работы и автоматизация CD.
- **Источники данных:** CI/CD (успешные job деплоя), GitOps-синхронизации, системный лог деплоев (sysadmin), системы релизов (Helm/Jenkins/GitLab), плагины окружений.
- **Формула:** `DF = Количество успешных деплоев в Production / период (день/неделя/месяц)`.
- **Декомпозиция:**
  1. **Batch Size:** Объем кода в одном деплое. Маленькие батчи снижают риск и ускоряют откат.
  2. **Automation Coverage:** Доля деплоев, проходящих без ручных гейтов.
  3. **Queue Time:** Время ожидания в очереди на деплой — скрытый компонент Lead Time.
- **Уровни:**
  - *Elite:* По запросу (несколько раз в день).
  - *High:* От одного раза в неделю до одного раза в день.
  - *Medium:* От одного раза в месяц до одного раза в неделю.
  - *Low:* Реже одного раза в месяц.

**2. Lead Time for Changes (Время выполнения изменений)**
- **Фокус:** Устранение узких мест в пайплайне (очереди на ревью, долгое тестирование, ручные гейты).
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
- **Фокус:** Качество автоматизированных тестов и безопасность процесса релиза (Canary, Blue-Green, Feature Flags).
- **Источники данных:** записи деплоев со статусом + записи инцидентов/откатов.
- **Формула:** `CFR = (Число деплоев, потребовавших rollback/hotfix/patch/rollforward) / (Общее число деплоев) × 100%`.
- **Уровни:**
  - *Elite:* < 4%.
  - *High:* 4–8%.
  - *Medium:* 8–16%.
  - *Low:* > 16%.

**4. Failed Deployment Recovery Time (Время восстановления после неудачного деплоя)**
- **Фокус:** Наблюдаемость (Observability) и автоматизация откатов. В отличие от общего MTTR, учитывает только сбои, вызванные изменением в Production.
- **Источники данных:** система алертинга/инцидентов (время начала) + подтверждение восстановления (health check, алерт «resolved»).
- **Формула:** `FDRT = t(восстановление подтверждено) − t(начало инцидента, вызванного деплоем)`.
- **Связь с SRE:** Напрямую зависит от декомпозиции MTTR (TTD, TTN, TTDi, TTF). Подробнее см. в **[Концепции SRE](../../Concepts/sre_concepts_main.md#декомпозиция-mttr-для-оптимизации)**.
- **Уровни:**
  - *Elite:* Менее 1 часа.
  - *High:* Менее 1 дня.
  - *Medium:* Менее 1 дня.
  - *Low:* Более 1 недели.

**5. Deployment Rework Rate (Коэффициент переделок)**
- **Фокус:** Объем технического долга, генерируемого процессом поставки. Высокий Rework Rate означает, что команда тратит ресурсы на исправление предыдущих деплоев вместо новой функциональности.
- **Источники данных:** записи деплоев + система инцидентов; требуется корреляционное окно (обычно 1–7 дней после деплоя).
- **Формула:** `Rework Rate = (Число деплоев, ставших причиной последующих незапланированных исправлений) / (Общее число деплоев) × 100%`.
- **Связь с DevOps:** Прямо указывает на качество гейт-тестов и наблюдаемости. Низкий Rework Rate означает, что изменения проходят первый раз правильно.
- **Уровни:**
  - *Elite:* < 4%.
  - *High:* 4–8%.
  - *Medium:* 8–16%.
  - *Low:* > 16%.

**6. Reliability (Надежность) — операционная метрика**
- **Фокус:** Способность удерживать согласованный уровень обслуживания (SLO) под реальной нагрузкой, независимо от скорости доставки.
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

### DORA и инженерные практики (SRE / DevOps / Sysadmin)

Метрики не существуют сами по себе — они улучшаются через конкретные практики:

- **Trunk-Based Development** сокращает Lead Time и снижает CFR за счёт маленьких, частых интеграций. См. **[Рабочие процессы в Git](../../Git/git_workflows.md)**.
- **Health Checks и автоматический rollback** снижают FDRT и CFR. См. **[Health Checks и rollback](../Deployment_Strategies/deployment_health_checks_and_rollback.md)**.
- **Error Budget Policy (SRE)** превращает Reliability из абстракции в управляемый процесс принятия решений. Бюджет ошибок связывает скорость деплоя с допустимым риском.
- **Observability** — фундамент, без которого FDRT, CFR и Rework Rate невозможно измерить честно. См. **[Наблюдаемость](../../Concepts/Observability_and_Monitoring/observability_definitions.md)** и **[Наблюдаемость пайплайнов](./pipeline_observability.md)**.
- **Chaos Engineering** выявляет слабые места до деплоя, снижая CFR и улучшая FDRT. См. **[Интеграция Chaos и DORA](../../Chaos_Engineering/chaos_engineering_metrics.md#интеграция-с-dora)**.
- **Configuration Management (Sysadmin)** — Ansible, Puppet, Chef, Salt позволяют версионировать инфраструктурные изменения и вести их учет как деплои, что даёт честные метрики для на-premise сред.
- **Change Management (ITIL/Sysadmin)** — formal Change Advisory Board (CAB) часто замедляет Deployment Frequency. Современный подход — заменить CAB на peer review + automated canary + fast rollback, чтобы не жертвовать скоростью ради контроля.

### Почему скорость и стабильность — не компромисс

Исследования DORA неоднократно подтверждали: команды с высокой пропускной способностью имеют и более низкий CFR, и более быстрый FDRT. Секрет не в «быстрых и careless» релизах, а в инверсии риска:
1. Маленькие батчи → каждый деплой имеет малый радиус поражения.
2. Автоматические откаты → при сбое восстановление занимает минуты, а не часы.
3. Наблюдаемость → проблема обнаруживается до того, как её заметят пользователи.
4. Quality Gates → брак отсеивается на этапе пайплайна, а не в Production.

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
# → {"2025-05-01":18,"2025-06-01":22}

# Lead Time for Changes
curl --silent --header "PRIVATE-TOKEN: <TOKEN>" \
  "https://gitlab.example.com/api/v4/projects/<PROJECT_ID>/dora/metrics?metric=lead_time_for_changes&interval=monthly"
# → {"2025-05-01":43200,"2025-06-01":28800}

# Change Failure Rate (доля в процентах)
curl --silent --header "PRIVATE-TOKEN: <TOKEN>" \
  "https://gitlab.example.com/api/v4/projects/<PROJECT_ID>/dora/metrics?metric=change_failure_rate&interval=monthly"
# → {"2025-05-01":5.2,"2025-06-01":3.8}

# Failed Deployment Recovery Time (в секундах)
curl --silent --header "PRIVATE-TOKEN: <TOKEN>" \
  "https://gitlab.example.com/api/v4/projects/<PROJECT_ID>/dora/metrics?metric=time_to_restore_service&interval=monthly"
# → {"2025-05-01":900,"2025-06-01":600}
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

В среде без централизованного CI деплои часто выполняются скриптами, Ansible Playbooks или вручную. Метрики всё равно измеримы, если вести лог деплоев и использовать Git как источник времени коммита.

Формат лога `/var/log/deploys.log`:

```text
2025-06-01T10:15:00Z deploy sha=abc1234 env=production status=success
2025-06-02T14:20:00Z deploy sha=def5678 env=production status=failed
2025-06-02T14:45:00Z deploy sha=def5678 env=production status=success
```

Скрипт на Python для расчёта Deployment Frequency, среднего Lead Time и Change Failure Rate (Lead Time берётся из `git log` по SHA):

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

**Sysadmin-контекст:** Для сред без Git-истории (голые серверы, mainframe) время коммита заменяется на время вручения задачи в изменения (change ticket timestamp). Миграции БД и ручные правки конфигов фиксируются в том же логе с типом `change_type=manual_config` — это позволяет отдельно анализировать риск ручных вмешательств.

### Сценарий 4: SRE — Failed Deployment Recovery Time из управления инцидентами

FDRT измеряется по журналу инцидентов. Пример лога `/var/log/incidents.log`:

```text
2025-06-03T08:00:00Z incident id=INC-101 start cause=deployment
2025-06-03T08:42:00Z incident id=INC-101 resolved
```

Расчёт FDRT (в минутах) и фиксация для Reliability:

```bash
# FDRT для инцидента INC-101 (разница меток start/resolved)
START=$(date -d "$(grep 'INC-101 start' /var/log/incidents.log | awk '{print $1}')" +%s)
END=$(date -d "$(grep 'INC-101 resolved' /var/log/incidents.log | awk '{print $1}')" +%s)
echo "FDRT: $(( (END - START) / 60 )) мин"
# → FDRT: 42 мин
```

Связь с наблюдаемостью: FDRT напрямую зависит от TTD (время обнаружения). Если `START` берётся не из алерта, а из жалобы пользователя, FDRT будет завышен и маскирует реальную проблему мониторинга. Декомпозиция MTTR (TTD/TTN/TTDi/TTF) — в **[Концепциях SRE](../../Concepts/sre_concepts_main.md#декомпозиция-mttr-для-оптимизации)**.

**Reliability (SLO/Error Budget)** считается отдельно: например, SLO = «99.9% запросов успешны за 30 дней». Бюджет ошибок = 0.1% = ~43 минуты недоступности на месяц. Если суммарный FDRT по всем инцидентам превышает бюджет — уровень Reliability падает до Low независимо от скорости.

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

# 3. Failed Deployment Recovery Time — время между алертом Degraded и возвратом в Healthy
#    (через запись длительности инцидента в метрику incident_duration_seconds)
sum(incident_duration_seconds{severity="critical"})
```

**Валидация:** в Grafana запрос (1) должен возвращать целое число ≥ 0; (2) — значение от 0 до 1 (доля); (3) — суммарное время в секундах. Если (2) > 0.16 — команда в зоне Low по CFR.

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

-- 4. Failed Deployment Recovery Time (среднее, минуты)
SELECT AVG(EXTRACT(EPOCH FROM (i.resolved_at - i.opened_at)) / 60) AS fdrt_min
FROM incidents i
WHERE i.resolved_at IS NOT NULL;

-- 5. Deployment Rework Rate (%)
SELECT 100.0 * COUNT(DISTINCT r.deploy_id) / COUNT(*) AS rework_pct
FROM deployments d
LEFT JOIN rework_incidents r ON r.deploy_id = d.deploy_id
WHERE d.environment = 'production' AND d.status = 'success';
```

**Валидация:** запрос (2) должен возвращать положительное число; если `NULL` — нет связи `commit_sha` с таблицей `commits`. Запрос (4) требует, чтобы `resolved_at` был заполнен (иначе инцидент ещё открыт и FDRT бесконечен). Запрос (5) требует отдельной таблицы `rework_incidents` или флага в `incidents`, отмечающего, что инцидент вызван предыдущим деплоем.

## Операции и команды

Быстрый справочник команд и запросов для извлечения DORA-метрик из распространённых инструментов.

### Git — получение времени коммита

```bash
# Время коммита в ISO 8601 (UTC)
git log -1 --format=%cI <sha>
# → 2025-05-15T14:30:00+00:00

# Разница между двумя коммитами в секундах
git log --format=%ct <sha_new> <sha_old> | awk '{print $1 - $2}'
# → 86400
```

### GitLab CI — REST API DORA

```bash
# Получение всех четырёх метрик за квартал
for metric in deployment_frequency lead_time_for_changes change_failure_rate time_to_restore_service; do
  curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
    "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/dora/metrics?metric=${metric}&interval=quarterly"
  echo
done
```

### Jenkins — парсинг лога деплоев

```bash
# Подсчет успешных деплоев за последнюю неделю
awk -v cutoff=$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ) \
  '$1 >= cutoff && $5 == "success"' /var/lib/jenkins/deploys.log | wc -l
# → 12
```

### Prometheus — типовые PromQL-запросы

```promql
# Средний Lead Time по времени завершения пайплайна (если экспортируется)
avg(gitlab_ci_pipeline_duration_seconds{job="build", environment="production"})

# Процент упавших пайплайнов за час
sum(rate(gitlab_ci_pipeline_total{status="failed"}[1h]))
/
sum(rate(gitlab_ci_pipeline_total[1h]))
```

### Sysadmin — аудит ручных изменений

```bash
# Поиск всех ручных правок в /etc за последний месяц
grep -E '^2025-0[5-6]-[0-9]{2}T' /var/log/deploys.log | grep change_type=manual_config | wc -l
# → 3
```

## Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| DF аномально высокий | Считаются dev/staging деплои или пересборки пайплайна | Фильтруйте по `environment=production` и статусу success |
| Lead Time отрицательный | Деплой помечен раньше коммита / неверная таймзона | Используйте UTC (`date -u`), сверяйте SHA |
| CFR близок к 0% | Откаты не фиксируются как инциденты | Обязательная регистрация rollback/hotfix в `incidents` |
| FDRT завышен | `START` берётся из жалобы юзера, а не алерта | Берите время начала из системы алертинга (TTD) |
| Метрики «красивые, но бесполезные» | Squash/cherry-pick ломают SHA-корреляцию | Коррелируйте по deploy-SHA (реальный в проде), а не по PR |
| Расхождение источников | Ручные/sysadmin-изменения не учтены | Включите конфиг- и инфра-изменения в определение деплоя |
| Rework Rate растёт, CFR стабилен | Баги утекают в прод, но не вызывают немедленного сбоя; накапливаются и потом массово фиксируются | Ужесточите acceptance test и canary-аналитику |

## Лучшие практики и очистка

- **Автоматизируйте сбор**, не собирайте вручную через Excel/Jira — это теряет точность и доверие.
- **Храните сырые события** (логи/таблицы) отдельно от агрегатов; агрегаты пересчитываются, сырьё — нет.
- **Фиксируйте определение деплоя** в runbook и пересматривайте раз в квартал.
- **Не наказывайте команду метриками** — DORA диагностический инструмент, а не KPI для штрафов (иначе возникает «Gaming the metrics»).
- **Очистка:** ротируйте логи деплоев (logrotate), партиционируйте таблицы по месяцам, удаляйте тестовые события не-Production по расписанию.
- **Для CFR:** Автоматизация **[Health Checks](../Deployment_Strategies/deployment_health_checks_and_rollback.md)** и внедрение Chaos Engineering для проверки устойчивости. См. **[Интеграция Chaos и DORA](../../Chaos_Engineering/chaos_engineering_metrics.md#интеграция-с-dora)**.
- **Для FDRT:** вложения в наблюдаемость и автоматизированные откаты; отработка инцидентов по SRE-практикам (postmortem, error budget).
- **Для Deployment Rework Rate:** внедрение pre-deploy quality gates (static analysis, integration tests, contract tests) и canary-аналитики.
- **Для Reliability:** внедрение SLO и бюджета ошибок как управляемого процесса.

## Граничные случаи (Edge Cases)

- **Мобильные приложения:** релиз в стор занимает дни/недели — сравнивать с Web-деплоями некорректно; измеряйте частоту merge в релизную ветку как прокси.
- **Миграции БД:** долгие, рискованные; учитывайте отдельно, т.к. они растягивают Lead Time и повышают CFR и Rework Rate.
- **Ручные изменения sysadmin** (правка конфига на сервере): если влияют на Production — это деплой; без учёта метрики лгут о стабильности.
- **Rollforward vs Rollback:** если баг исправлен новым деплоем (rollforward), а не откатом — это всё равно сбой (CFR растёт), но FDRT считается до момента восстановления.
- **Периоды низкой активности** (праздники): DF падает не из-за регресса процесса — сравнивайте однородные периоды.
- **Legacy / Mainframe:** для систем без CI/CD измеряйте Lead Time от approval change ticket до деплоя; это не идеально, но даёт направление для улучшения.
- **Bot-коммиты:** автоматические обновления (Renovate, Dependabot) учитывайте отдельно, чтобы не завышать Deployment Frequency команды.

## Белые пятна и вызовы (Антипаттерны)

### Типичные ошибки внедрения

1.  **Gaming the metrics (Манипуляция):** Искусственное дробление задач на микро-коммиты для завышения Deployment Frequency без реальной бизнес-ценности.
2.  **Игнорирование контекста:** Сравнение команд с разным стеком (например, мобильная разработка с недельными релизами в сторы vs Web с деплоем по кнопке).
3.  **Отсутствие Reliability:** Высокая скорость (Elite по Lead Time) при игнорировании SLO приводит к выгоранию команды и нестабильности системы.
4.  **Ручной ввод данных:** Попытка собирать DORA через Excel или Jira вручную ведет к низкой точности и потере доверия к метрикам.
5.  **Смешивание сред:** Учёт staging/ dev деплоев вместе с Production искажает все пять метрик.
6.  **Conflation Lead Time и Cycle Time:** отчёт «Lead Time = 2 недели» при измерении от планирования до продакшена скрывает реальные узкие места CI/CD.
7.  **Игнорирование TTD в FDRT:** измерение восстановления от жалобы пользователя маскирует слабость мониторинга.
8.  **Игнорирование Rework Rate:** команда может иметь низкий CFR, но высокий Rework Rate — это сигнал о «тихих» багах, которые не вызывают инцидентов, но тормозят развитие продукта.

### Как улучшить показатели

- **Для Lead Time:** Внедрение Trunk-Based Development и сокращение времени жизни веток. См. **[Рабочие процессы в Git](../../Git/git_workflows.md)**.
- **Для CFR:** Автоматизация **[Health Checks](../Deployment_Strategies/deployment_health_checks_and_rollback.md)** и внедрение Chaos Engineering для проверки устойчивости. См. **[Интеграция Chaos и DORA](../../Chaos_Engineering/chaos_engineering_metrics.md#интеграция-с-dora)**.
- **Для Deployment Frequency:** миниатюризация задач, автоматизация пайплайна релиза, устранение ручных гейтов.
- **Для FDRT:** вложения в наблюдаемость и автоматизированные откаты; отработка инцидентов по SRE-практикам (postmortem, error budget).
- **Для Deployment Rework Rate:** внедрение pre-deploy quality gates (static analysis, integration tests, contract tests) и canary-аналитики.
- **Для Reliability:** внедрение SLO и бюджета ошибок как управляемого процесса.

## Дополнительная информация

- **Паттерны CI/CD:** [Практики улучшения метрик](../ci_cd_patterns.md).
- **Анти-паттерны CI/CD:** [Ошибки и узкие места](../ci_cd_antipatterns.md).
- **SRE и доступность:** [High Availability](../../Concepts/High_Availability/ha_overview.md) и [Концепции SRE](../../Concepts/sre_concepts_main.md).
- **Наблюдаемость:** [Observability](../../Concepts/Observability_and_Monitoring/observability_definitions.md) как фундамент для сбора метрик и **[Наблюдаемость пайплайнов](./pipeline_observability.md)** для диагностики их эффективности.
- **GitLab CI:** [Окружения и DORA-метрики](../GitLab_CI/Concepts/environments_and_deployments.md).
- **State of DevOps Report** — ежегодные отчеты DORA.
- **DORA Quick Check** — инструмент для быстрой самооценки команды.
- **Four Keys** — референсная архитектура для сбора метрик.
