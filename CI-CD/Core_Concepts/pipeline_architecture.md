# Архитектура пайплайнов (Pipeline Architecture)

**Актуально для:** self-hosted CI/CD (GitLab CI, GitHub Actions, Jenkins) 2024–2026

> Область применения: практики DevOps, SRE и SysAdmin при эксплуатации самостоятельно развёрнутых систем. Материалы, относящиеся к публичным облакам и технологиям искусственного интеллекта, не рассматриваются.

## Определения

- **Архитектура пайплайна** — организация этапов (stages), задач (jobs) и их зависимостей в конвейере поставки.
- **DAG (Directed Acyclic Graph)** — направленный ациклический граф зависимостей между задачами. Позволяет запускать независимые задачи параллельно, сокращая критический путь.
- **Fan-out / Fan-in** — паттерн, при котором одна задача порождает множество downstream-задач (fan-out), а множество задач агрегируются в одной (fan-in).
- **Matrix Build** — параллельный запуск одной задачи с разными наборами переменных (платформа, версия, окружение).
- **Reusable Pipeline / Component** — обособленный блок логики (шаблон, компонент), который может быть вызван из разных пайплайнов с параметрами.
- **Pipeline Orchestrator** — компонент, управляющий запуском, очередью и зависимостями задач (CI-сервер + API).
- **Bridge Job** — задача-агрегатор, собирающая результаты fan-out для последующей fan-in.
- **Symmetric DAG** — паттерн, при котором количество задач fan-out совпадает с количеством задач fan-in.

## Основные концепции

### Принципы архитектуры пайплайнов

1. **Separation of Concerns:** Каждая задача отвечает за одно действие (линт, тест, сборка, деплой).
2. **Explicit Dependencies:** Задачи явно указывают зависимости через `needs` / `dependencies`.
3. **Fail-Fast:** Критические проверки выполняются первыми; при провале пайплайн останавливается.
4. **Idempotency:** Повторный запуск пайплайна даёт тот же результат.
5. **Immutability:** Артефакты не меняются после сборки; продвижение по средам без пересборки.

### Почему архитектура пайплайнов важна для DevOps, SRE и SysAdmin

- **DevOps:** Архитектура определяет скорость доставки и частоту релизов (Deployment Frequency). Плоская DAG-модель сокращает время цикла, уменьшая handoff между стадиями и командами.
- **SRE:** Чётко спроектированный DAG снижает риск каскадных откатов и упрощает расчёт MTTR. Изолированные fan-out-задачи не блокируют критические деплои при падении побочных проверок.
- **SysAdmin:** Архитектура влияет на утилизацию раннеров, планирование дисков/инодов и тепловыделение флота. Глубокие вложенности downstream-пайплайнов создаютburst-нагрузку на API и sidekiq-очереди GitLab.
- **Multi-platform complexity:** В гетерогенной среде (GitLab CI + GitHub Actions + Jenkins) единые принципы архитектуры (DAG, immutable artifacts, fan-out/fan-in) позволяют переносить паттерны между платформами без потери семантики.

### Паттерны архитектуры

#### 1. Sequential (Последовательный)

```
Lint → Test → Build → Security → Deploy
```

Простой, но медленный. Подходит для небольших проектов или этапов с жёстким порядком (например, миграции БД).

#### 2. Parallel Stages (Параллельные стадии)

```
        Lint
         ↓
    ┌────┴────┐
    ↓         ↓
  Test      Security
    ↓         ↓
    └────┬────┘
         ↓
       Build
         ↓
       Deploy
```

Независимые стадии (Test, Security) запускаются параллельно.

#### 3. DAG с needs

```
Lint → Unit Tests → Build → Deploy
               ↘
             Integration Tests → E2E Tests
```

Задачи запускаются сразу после выполнения зависимостей, не дожидаясь всей стадии. Детали реализации — см. **[DAG с needs](../GitLab_CI/Advanced/workflow_rules/dag_with_needs.md)**.

#### 4. Fan-out / Fan-in

```
            Trigger
               ↓
    ┌──────────┼──────────┐
    ↓          ↓          ↓
  Test A    Test B    Test C
    ↓          ↓          ↓
    └──────────┼──────────┘
               ↓
          Aggregate
               ↓
            Deploy
```

Используется для тестирования на разных платформах/версиях. Для стратегий downstream-пайплайнов см. **[Downstream Pipelines](../GitLab_CI/Advanced/Downstream_Pipelines/strategies.md)**.

#### 5. Matrix Build

```
matrix:
  platform: [linux/amd64, linux/arm64]
  version: [3.11, 3.12, 3.13]
```

Порождает 6 задач (3 платформы × 2 версии).

#### 6. Multi-Project / Downstream

```
Project A → Trigger → Project B → Trigger → Project C
```

Кросс-проектные пайплайны для микросервисной архитектуры.

### Сравнение downstream-механизмов

| Возможность | GitLab CI | GitHub Actions | Jenkins |
|:---|:---|:---|:---|
| **Native downstream** | `trigger:project` | `workflow_call` | `build job` + `build` trigger |
| **Cross-project** | Да | Да | Да |
| **Глубина вложенности** | 2 уровня | 4 уровня | Ограничена памятью/кучей |
| **Artifacts между проектами** | `needs:project` | `needs` + `actions/cache` | Copy Artifact plugin / `stash/unstash` |

## Предпосылки

- **Инфраструктура:** Self-hosted CI/CD-сервер (GitLab CE/EE, GitHub Enterprise Server, Jenkins) с выделенными раннерами.
- **Сеть:** Доступность API CI-сервера, registry и хранилищ артефктов внутри ЦОДа без зависимостей от внешних облачных провайдеров.
- **Раннеры:** Достаточный пул исполнителей с поддержкой требуемых executors (Docker, Kubernetes, shell, Windows).
- **Безопасность:** RBAC настроен; секреты хранятся в менеджере секретов (Vault), OIDC доверие установлено.
- **Мониторинг:** Метрики пайплайнов экспортируются в Prometheus; алерты настроены на деградацию очередей и рост MTTR.
- **Документация:** Runbook'ы и escalation matrix утверждены для каждой платформы.

## Практические сценарии

### Сценарий 1: DAG с fan-out/fan-in (GitLab CI)

#### Предпосылки
- Тестирование на 3 платформах (Ubuntu, Alpine, Windows).
- Агрегация результатов перед деплоем.

#### .gitlab-ci.yml
```yaml
stages:
  - test
  - aggregate
  - deploy

test:ubuntu:
  stage: test
  image: ubuntu:22.04
  script: [./run-tests.sh]
  artifacts:
    reports: [junit: report.xml]

test:alpine:
  stage: test
  image: alpine:3.19
  script: [./run-tests.sh]
  artifacts:
    reports: [junit: report.xml]

test:windows:
  stage: test
  image: mcr.microsoft.com/windows/servercore:ltsc2022
  script: [./run-tests.ps1]
  artifacts:
    reports: [junit: report.xml]

aggregate:
  stage: aggregate
  needs: [test:ubuntu, test:alpine, test:windows]
  script:
    - junit-merge report-*.xml > merged-report.xml
  artifacts:
    reports: [junit: merged-report.xml]

deploy:
  stage: deploy
  needs: [aggregate]
  script: [./deploy.sh]
```

#### Валидация
- 3 задачи запускаются параллельно.
- `aggregate` запускается после завершения всех трёх.
- При провале любой из тестов `deploy` не запускается.

### Сценарий 2: Matrix build с параметрами (GitLab CI)

#### Предпосылки
- Сборка и тестирование на нескольких версиях Python и ОС.

#### .gitlab-ci.yml
```yaml
stages:
  - test

.test_template:
  stage: test
  image: python:${PYTHON_VERSION}-${OS}
  variables:
    PYTHON_VERSION: "3.11"
    OS: "slim"
  script:
    - pip install -r requirements.txt
    - pytest tests/

test:python:3.11:alpine:
  extends: .test_template
  variables:
    PYTHON_VERSION: "3.11"
    OS: "alpine"

test:python:3.12:alpine:
  extends: .test_template
  variables:
    PYTHON_VERSION: "3.12"
    OS: "alpine"

test:python:3.13:alpine:
  extends: .test_template
  variables:
    PYTHON_VERSION: "3.13"
    OS: "alpine"
```

#### Валидация
- 3 задачи запускаются параллельно.
- Каждая задача имеет изолированное окружение.

### Сценарий 3: Cross-project downstream (GitLab CI)

#### Предпосылки
- Микросервисная архитектура: service-a → service-b → service-c.

#### .gitlab-ci.yml (service-a)
```yaml
stages:
  - build
  - trigger

build:
  stage: build
  script: [docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .]

trigger:service-b:
  stage: trigger
  trigger:
    project: group/service-b
    branch: main
    strategy: depend
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

#### .gitlab-ci.yml (service-b)
```yaml
stages:
  - build
  - trigger

build:
  stage: build
  script: [docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .]

trigger:service-c:
  stage: trigger
  trigger:
    project: group/service-c
    branch: main
    strategy: depend
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

#### Валидация
- При изменении в service-a запускается пайплайн service-b.
- При изменении в service-b запускается пайплайн service-c.
- `strategy: depend` гарантирует, что upstream пайплайн ждёт завершения downstream.

### Сценарий 4: Matrix build (GitHub Actions)

#### Предпосылки
- Параллельное тестирование на нескольких ОС и версиях Node.js в GitHub Actions.
- Self-hosted runners зарегистрированы в репозитории.

#### .github/workflows/matrix.yml
```yaml
name: Matrix Build
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-22.04, ubuntu-24.04, windows-2022]
        node: [18, 20, 22]
        exclude:
          - os: windows-2022
            node: 18
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node }}
      - run: npm ci
      - run: npm test
```

#### Валидация
- GitHub Actions создаёт 8 задач (3 ОС × 3 версии Node − 1 исключение).
- Задачи выполняются параллельно на доступных раннерах.
- При провале любой задачи пайплайн помечается как failed.

### Сценарий 5: Reusable pipeline component (GitLab CI)

#### Структура
```
templates/
├── build.yml
├── test.yml
└── deploy.yml
```

#### templates/build.yml
```yaml
spec:
  inputs:
    image:
      type: string
      default: "docker:24"
    registry:
      type: string
      default: "docker.io"

stages:
  - build

build:
  stage: build
  image: $[[ inputs.image ]]
  script:
    - docker build -t $[[ inputs.registry ]]/$CI_PROJECT_NAME:$CI_COMMIT_SHA .
```

#### .gitlab-ci.yml
```yaml
include:
  - component: group/templates/build@1.0.0
    inputs:
      image: "docker:24"
      registry: "registry.internal"
```

#### Валидация
- Компонент версионирован по тегу (`@1.0.0`).
- Изменения в компоненте не ломают старые пайплайны.
- Параметры `inputs` валидируются до запуска пайплайна.

### Сценарий 6: Оптимизация fan-out

#### Предпосылки
- Массовый запуск downstream-пайплайнов (>20).
- Риск превышения rate limit API.

#### .gitlab-ci.yml
```yaml
stages:
  - fan-out
  - deploy

fan-out:
  stage: fan-out
  image: python:3.13
  script:
    - |
      for project in service-a service-b service-c service-d service-e; do
        curl -X POST "https://gitlab.internal/api/v4/projects/group/$project/trigger/pipeline" \
          -H "PRIVATE-TOKEN: $TRIGGER_TOKEN" \
          -d "ref=main" &
        sleep 1  # Throttling
      done
      wait
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

deploy:
  stage: deploy
  needs: [fan-out]
  script: [./deploy.sh]
```

#### Валидация
- Throttling предотвращает массовый 429.
- Пауза 1 секунда между запросами.
- `wait` гарантирует завершение всех downstream перед deploy.

### Сценарий 7: Автомасштабирование флота для монорепозиториев

#### Предпосылки
- Монорепозиторий с 50+ сервисами.
- Переменная нагрузка на раннеры.

#### ScaledObject (KEDA)
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: gitlab-runner-scaler
spec:
  scaleTargetRef:
    name: gitlab-runner-deployment
  minReplicaCount: 5
  maxReplicaCount: 100
  triggers:
    - type: gitlab
      metadata:
        url: https://gitlab.internal
        tokenFromEnv: GITLAB_READ_TOKEN
        registrationTokenFromEnv: RUNNER_TOKEN
```

#### Валидация
- При росте очереди раннеры масштабируются автоматически.
- При простое раннеры удаляются.
- Минимум 5 раннеров всегда доступен.

## Ограничения и крайние случаи

- **Глубина вложенности:** GitLab CI ограничивает 2 уровня `trigger`. Для большей глубины используйте API-оркестратор.
- **Cyclic dependencies:** A → B → A через триггеры вызывает deadlock. Избегайте циклов.
- **Rate limiting:** Массовый fan-out (>20 downstream) вызывает 429. Используйте throttling.
- **Artifact size:** Большие артефакты (>100MB) между downstream-пайплайнами вызывают таймауты. Используйте registry.
- **Cache poisoning:** Общий кэш между проектами — поверхность атаки. Изолируйте кэш.
- **Cold start:** Эфемерные раннеры добавляют латентность. Используйте warm pools для latency-чувствительных пайплайнов.
- **Platform lock-in:** Глубокие platform-specific директивы (`parallel:matrix` в GitLab, `strategy.matrix` в GitHub Actions) усложняют перенос пайплайнов. Выносите общую логику в переиспользуемые компоненты.
- **Bridge Job concurrency:** При `strategy: mirror` Bridge Job занимает слот Runner'а на всё время downstream. При большом количестве одновременных mirror-триггеров возможен deadlock. Увеличьте `concurrency` в `config.toml` или используйте `fire and forget` для некритичных задач.
- **Matrix explosion:** Матрица из 50+ комбинаций создает burst-нагрузку на API и хранилище артефактов. Используйте `rules` для динамического формирования матрицы только для изменённых компонентов.

## Типичные ошибки и решения

| Симптом | Причина | Решение | Роль |
|:---|:---|:---|:---|
| Fan-in зависает в `pending` | Один из fan-out задач не создал артефакт (падение без `mirror`) | Используйте `strategy: mirror` + `allow_failure: false` для критичных downstream | DevOps |
| `429 Too Many Requests` при fan-out | Burst-запросы к Pipeline Triggers API без throttling | Добавьте задержку между запросами, используйте circuit breaker | DevOps |
| DAG содержит циклы | Две или более задачи ссылаются друг на друга через `needs` | Уберите лишнюю `needs`, разбейте на отдельные стадии | DevOps |
| `needs` + `trigger` конфликт | Bridge Job не может иметь `needs` одновременно | Используйте `stages` для порядка, а `trigger:strategy` для синхронизации | DevOps |
| Bridge Job занимает слот Runner'а | `strategy: mirror` или `depend` удерживает concurrency-слот | Увеличьте `concurrency`, разделите теги upstream/downstream | Sysadmin |
| Downstream не отменяется при отмене родителя | Используется `depend` вместо `mirror` или `interruptible: false` | Мигрируйте на `mirror`, проверьте `interruptible` | DevOps |
| Matrix build создаёт >50 задач | Неограниченная комбинация платформ/версий | Ограничьте `matrix` через `exclude`, используйте `rules` | DevOps |
| Артефакт >100MB между downstream | Таймаут передачи артефактов через API | Используйте registry вместо артефактов, или registry cache | Sysadmin |
| `trigger:inputs` валидация падает | Неверный тип данных в `spec:inputs` дочернего пайплайна | Проверьте типы `string`/`number`/`boolean` в схеме | DevOps |
| Symmetric DAG нарушен | Количество fan-out задач не совпадает с fan-in ожиданиями | Визуализируйте DAG, убедитесь что fan-in ожидает ровно N задач | DevOps |

## Лучшие практики

### Архитектура и проектирование

1. **DAG вместо последовательных стадий:** Параллелизм сокращает время выполнения на 30–70%.
2. **Ограничивайте fan-out:** Не запускайте >20 downstream-пайплайнов одновременно без throttling.
3. **Версионируйте компоненты:** Используйте теги SemVer или commit SHA в `ref` для reusable pipelines.
4. **Изолируйте кэш:** Разделяйте кэш по проекту/группе, используйте scoped S3-бакеты.
5. **Мониторьте DAG:** Визуализируйте граф зависимостей для поиска узких мест.
6. **Тестируйте архитектуру:** Регулярно проверяйте, что fan-in ожидает правильное количество задач.
7. **Symmetric DAG:** Количество задач fan-in должно совпадать с количеством задач fan-out.
8. **Multi-platform runbooks:** Для каждой платформы (GitLab, GitHub, Jenkins) должен быть свой runbook с platform-specific командами.
9. **Cleanup по умолчанию:** Планируйте `stop_review` и `auto_stop_in` для эфемерных окружений; настраивайте retention артефактов и registry GC.
10. **Bridge Job observability:** Мониторьте количество активных Bridge Jobs через API; алерт при >80% occupancy concurrency-слотов.
11. **Platform-agnostic patterns:** Выносите общую архитектурную логику в константы/шаблоны, чтобы паттерны переносились между GitLab, GitHub и Jenkins.
12. **Audit trail:** Все изменения в архитектуре пайплайнов фиксируются в Git history с описанием rationale (ADR).

## Дополнительная информация

### См. также

- **[Типичный поток пайплайна](./pipeline_workflow.md)** — каноническая структура конвейера.
- **[Глоссарий пайплайнов](./pipeline_glossary.md)** — термины и определения.
- **[Управление парком раннеров](../runner-fleet-management.md)** — масштабирование флота.
- **[Монорепозитории и инкрементальные сборки](../Build_Systems/monorepo_build_systems.md)** — сборка монорепозиториев.
- **[Downstream Pipelines](../GitLab_CI/Advanced/Downstream_Pipelines/strategies.md)** — стратегии кросс-проектных пайплайнов.
- **[DAG с needs](../GitLab_CI/Advanced/workflow_rules/dag_with_needs.md)** — глубинное погружение в графы зависимостей GitLab CI.
- **[Продвинутые рабочие процессы GitLab CI/CD](../GitLab_CI/Advanced/gitlab_ci_advanced_workflow.md)** — Fan-in/Fan-out, Merge Queue, Security.
- **[Метрики DORA](./dora_metrics.md)** — влияние архитектуры на Deployment Frequency и Lead Time.
