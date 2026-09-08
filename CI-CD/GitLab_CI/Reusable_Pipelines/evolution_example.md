# GitLab CI: Эволюция переиспользуемого пайплайна

## Определения

**Эволюция переиспользуемых пайплайнов** — это системный процесс последовательного совершенствования архитектуры CI/CD конфигураций. Целью процесса является минимизация дублирования кода (принцип DRY), повышение безопасности цепочки поставок (Software Supply Chain Security), обеспечение масштабируемости и снижение стоимости владения (TCO) инфраструктурой.

**Модель зрелости CI/CD (Maturity Model)** — иерархическая структура этапов развития пайплайнов, где каждый следующий уровень повышает уровень абстракции, усиливает изоляцию компонентов и переходит от императивного описания шагов к декларативным интерфейсам.

**Миграция пайплайнов** — контролируемый процесс перехода с одного уровня зрелости на другой, включающий анализ зависимостей, тестирование конфигураций и поэтапное обновление проектов. В контексте DevOps/SRE миграция рассматривается как изменение, требующее формализованного управления рисками и механизмов отката.

## Основные концепции

### Этапы развития и уровни зрелости

| Уровень | Метод | Ключевая характеристика | Критическая проблема |
| :--- | :--- | :--- | :--- |
| **1** | [Копирование (Boilerplate)](./evolution/evolution_boilerplate.md) | Прямое дублирование YAML-кода между проектами. | Невозможность массовых исправлений (O(N) обновлений). |
| **2** | [Централизация (Include)](./evolution/evolution_include.md) | Подключение общих файлов через `include:project`. | «Жесткие» шаблоны: сложно адаптировать под уникальные нужды. |
| **3** | [Наследование (Extends)](./evolution/evolution_extends.md) | Использование `extends` для кастомизации скрытых заданий. | Неявные интерфейсы: риск коллизий глобальных переменных. |
| **4** | [Абстракция деталей](./evolution/evolution_kaniko.md) | Инкапсуляция инструментов (например, Kaniko) внутри логики шаблона. | «Черный ящик»: сложность отладки для команд разработки. |
| **5** | [CI/CD Components (Catalog)](./evolution/evolution_components.md) | Типизированные входы (`inputs`), SemVer, UI-каталог. | Требует проектирования интерфейсов и тестирования самих компонентов. |
| **6** | **GitLab Steps** | Изолированные контейнерные шаги (atomic actions) вместо Bash. | Статус разработки (Active Development) в GitLab 17.x/18.x. |

### Техническое сравнение подходов

Для принятия решения о переходе на новый уровень необходимо учитывать различия в управлении конфигурацией:

| Характеристика | Этап 2 (Include) | Этап 3 (Extends) | Этап 5 (Catalog) | Этап 6 (Steps) |
| :--- | :--- | :--- | :--- | :--- |
| **Версионирование** | Ветки / Теги / SHA | Ветки / Теги / SHA | **SemVer релизы** | **SemVer релизы** |
| **Интерфейс** | Глобальные переменные | Переменные задания | **Декларативные inputs** | **Inputs / Outputs** |
| **Изоляция** | Отсутствует | Частичная (Variables) | **Полная (Scope)** | **Контейнерная (Run)** |
| **Валидация** | Синтаксическая | Синтаксическая | **Типизация данных** | **Строгие схемы** |
| **Стоимость владения** | Высокая (O(N) обновлений) | Средняя | **Низкая (O(1) обновление)** | **Низкая** |

### Экономика перехода (TCO Analysis)

Переход между уровнями зрелости снижает стоимость владения за счет уменьшения количества точек обновления:

| Сценарий | Этап 1 (Boilerplate) | Этап 2 (Include) | Этап 5 (Catalog) |
| :--- | :--- | :--- | :--- |
| Исправление уязвимости в Docker-образе | N репозиториев × правка | 1 шаблон + N пушей | 1 релиз компонента |
| Время на внедрение изменения | N × время_разработчика | 1 × время + N × время_ревью | 1 × время_разработки |
| Риск ошибки при обновлении | Высокий (ручные правки) | Средний (зависимость от шаблона) | Низкий (автоматическая валидация) |

## Практические сценарии

### Сценарий 1: Технические триггеры для миграции (Migration Triggers)

Переход между этапами должен быть обоснован техническими болями или требованиями бизнеса:

| Ситуация | Рекомендуемый переход | Ожидаемый результат |
| :--- | :--- | :--- |
| Ошибки в Bash-скриптах из-за опечаток в переменных | **3 → 5 (Catalog)** | Ошибки отлавливаются на этапе CI Lint благодаря проверке типов данных. |
| Потребность в смене Docker на Buildah без правки 1000 репозиториев | **3 → 4 (Abstraction)** | Логика меняется только в центральном шаблоне, проекты обновляются прозрачно. |
| Огромные `.gitlab-ci.yml` (более 1000 строк) | **1 → 2 (Include)** | Файл декомпозируется на логические модули (сборка, тесты, безопасность). |
| Конфликты имен переменных между шаблонами разных команд | **4 → 5 (Catalog)** | Каждый компонент работает в изолированном пространстве имен `$[[ inputs.name ]]`. |
| Невозможность встроить безопасность в CI без правки всех проектов | **2 → 5 (Catalog)** | Pipeline Execution Policies подключают компоненты на уровне группы. |
| Дублирование Bash-скриптов в 50+ проектах при обновлении версий инструментов | **1 → 2 (Include)** | Версии инструментов управления в одном файле шаблона. |

### Сценарий 2: Архитектура уровня Enterprise (Platform Engineering)

Для крупных организаций (100+ проектов) рекомендуется использовать гибридную модель «Platform CI»:

1.  **Центральный репозиторий компонентов:** Единый проект `org/ci-catalog` с использованием Stage 5.
2.  **Политика версионирования:** Категорический запрет на использование веток (`main`, `dev`) в директивах `include`. Использование только фиксированных тегов (SemVer) или Commit SHA.
3.  **Governance (Управление):** Принудительное внедрение проверок безопасности через **Pipeline Execution Policies** (v17.x+). Эти политики подключают компоненты Stage 5 на уровне группы, их невозможно пропустить или переопределить в проекте.
4.  **Self-Service:** Использование UI-каталога для обнаружения доступных инструментов командами разработки.

**Конкретный пример архитектуры:**

```
org/ci-catalog/
├── templates/
│   ├── build/
│   │   ├── docker-build.yml        (spec:inputs, SemVer)
│   │   ├── kaniko-build.yml        (spec:inputs, SemVer)
│   │   └── buildah-build.yml       (spec:inputs, SemVer)
│   ├── test/
│   │   ├── unit-test.yml           (spec:inputs, SemVer)
│   │   └── integration-test.yml    (spec:inputs, SemVer)
│   └── security/
│       ├── sast-scan.yml           (spec:inputs, SemVer)
│       ├── dast-scan.yml           (spec:inputs, SemVer)
│       └── license-check.yml       (spec:inputs, SemVer)
├── tests/
│   ├── docker-build/
│   │   ├── test-default-inputs.yml
│   │   └── test-custom-registry.yml
│   └── unit-test/
│       ├── test-go-project.yml
│       └── test-python-project.yml
└── README.md
```

### Сценарий 3: Чек-лист готовности к миграции на компоненты (Stage 5)

Перед публикацией шаблона в каталог необходимо обеспечить:
1.  **Контракт:** Все входные параметры описаны в `spec:inputs` с указанием типов и значений по умолчанию.
2.  **Документация:** Файл `README.md` содержит примеры подключения и описание каждого входного параметра.
3.  **Тестирование:** В репозитории компонента создана папка `tests/`, где пайплайн запускает сам компонент с различными комбинациями входов.
4.  **Безопасность:** Использование `id_tokens` (OIDC) для взаимодействия с внешними системами вместо передачи долгоживущих секретов.

### Сценарий 4: Поэтапная миграция крупного проекта

**Контекст:** Mono-репозиторий с 50+ модулями, `.gitlab-ci.yml` более 2000 строк, 15 команд разработки.

**Фаза 1: Анализ и декомпозиция (1–2 недели)**

1. Экспорт и анализ текущего конфига:
```bash
# Анализ структуры текущего .gitlab-ci.yml
glab ci lint --show-expanded > current-state.yml
wc -l current-state.yml  # → 2400 строк

# Поиск дублированных блоков
grep -n "script:" current-state.yml | wc -l  # → 87 вхождений
```

2. Выделение логических модулей:
```bash
# Пример декомпозиции на модули
mkdir -p ci-templates/{build,test,security,deploy}
# Каждый модуль — отдельный YAML-файл в центральном репозитории
```

**Фаза 2: Создание шаблонов Stage 2 (2–3 недели)**

```yaml
# ci-templates/build/docker-build.yml
.build_base:
  image: docker:${DOCKER_VERSION}
  services:
    - docker:${DOCKER_VERSION}-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"

build:
  extends: .build_base
  script:
    - docker build -t ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA} .
    - docker push ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}
```

**Фаза 3: Миграция проектов (1–2 недели на группу)**

```yaml
# Проект: microservice-a/.gitlab-ci.yml (после миграции)
include:
  - project: 'org/ci-templates'
    file: '/build/docker-build.yml'
    ref: v2.1.0  # ← SemVer тег, НЕ ветка

stages:
  - build
  - test
  - deploy

test:
  stage: test
  script:
    - go test ./...
```

**Фаза 4: Валидация после миграции**

```bash
# Проверка каждого проекта перед пушем
glab ci lint --show-expanded --project org/microservice-a

# Проверка всех проектов группы автоматически
for repo in $(glab repo list --group org --output json | jq -r '.[].path'); do
  echo "Checking $repo..."
  glab ci lint --project "org/$repo" --show-expanded > /dev/null
done
```

**Фаза 5: Отключение старых конфигов**

После полной миграции удалите старые версии `.gitlab-ci.yml` из проектов или переведите их в архив через Git Tags.

### Сценарий 5: Миграция с include:project на компоненты (Stage 2 → Stage 5)

**До (Legacy):** Пайплайны зависят от веток, что делает их нестабильными.
```yaml
# microservice/.gitlab-ci.yml (Legacy)
include:
  - project: 'group/ci-templates'
    file: '/docker-build.yml'
    ref: main  # ← НЕСТАБИЛЬНО: изменение в main ломает все проекты
```

**После (Modern):** Использование компонентов с SemVer и типизированными входами.
```yaml
# microservice/.gitlab-ci.yml (Modern)
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/docker-build@1.5.0'
    inputs:
      image: docker:27.0
      push_registry: true
```

**Алгоритм миграции:**
1.  **Спецификация**: Создайте блок `spec:inputs` в исходном шаблоне.
2.  **Рефакторинг**: Замените обращения к переменным `$VAR` на интерполяцию `$[[ inputs.var ]]`.
3.  **Релиз**: Создайте тег SemVer (v1.0.0) и GitLab Release.
4.  **Проверка**: Используйте `glab ci lint --show-expanded` для подтверждения корректности.
5.  **Rollout**: Обновляйте проекты по группам (10–20% в неделю), мониторя成功率.

### Сценарий 6: Миграция при конфликтах переменных (Stage 3 → Stage 5)

**Проблема:** Два шаблона используют переменную `BUILD_ARGS`, но с разным значением по умолчанию. При одновременном подключении возникает конфликт.

**До (Stage 3 — конфликт):**
```yaml
# team-a/.gitlab-ci.yml
include:
  - project: 'org/templates-a'
    file: '/build.yml'
  - project: 'org/templates-b'
    file: '/build.yml'

# templates-a/build.yml
variables:
  BUILD_ARGS: "--platform=linux/amd64"  # ← КОНФЛИКТ

# templates-b/build.yml
variables:
  BUILD_ARGS: "--platform=linux/arm64"  # ← КОНФЛИКТ
```

**После (Stage 5 — изоляция):**
```yaml
# team-a/.gitlab-ci.yml
include:
  - component: '$CI_SERVER_FQDN/org/build@2.0.0'
    inputs:
      platform: "linux/amd64"
  - component: '$CI_SERVER_FQDN/org/build@2.0.0'
    inputs:
      platform: "linux/arm64"
```

Каждый компонент работает в изолированном пространстве имен, конфликты исключены.

## Устранение неполадок при миграции

### Диагностические инструменты

| Инструмент | Назначение | Команда |
| :--- | :--- | :--- |
| **Pipeline Editor** | Визуальный просмотр раскрытого YAML с подсветкой ошибок. | Web UI → CI/CD → Pipeline Editor → «View merged YAML» |
| **GitLab CLI (`glab`)** | Локальная проверка синтаксиса и раскрытие `include`/`extends`/`inputs`. | `glab ci lint --show-expanded` |
| **CI Lint API** | Программная проверка через HTTP (для использования в CI-пайплайнах). | `POST /api/v4/projects/:id/ci/lint` |
| **Dry Run (v16.11+)** | Глубокая валидация, имитирующая создание пайплайна. | `glab ci lint --dry-run --variable CI_PIPELINE_SOURCE=merge_request_event` |

### Типичные ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Breaking Changes** | Обновление шаблона сломало сборки в проектах. | Внедрите SemVer. Никогда не меняйте логику в текущем мажорном теге. |
| **Потеря гибкости** | Шаблон стал слишком абстрактным и не подходит для спецзадач. | Используйте `inputs` с типом `options` или разрешите передачу `EXTRA_ARGS`. |
| **Циклические зависимости** | Шаблон А включает шаблон Б, который включает А. | Проверьте итоговый YAML через `glab ci lint --show-expanded`. |
| **Error 404 при подключении** | Неверный путь или проект не помечен как «Catalog resource». | Проверьте настройки Visibility и путь к файлу в `templates/`. |
| **Input validation error** | Ошибка типа (string вместо number). | Оборачивайте числа в кавычки в YAML, если в `spec` указан тип `string`. |
| **Exceeded max includes** | Слишком глубокая вложенность (лимит 150). | Используйте `!reference` для переиспользования кода внутри одного файла. |
| **Interpolation failed** | Ошибка синтаксиса `$[[ ]]`. | Проверьте закрывающие скобки и отсутствие циклов в инпутах. |

## DevOps/SRE-специфичные сценарии

### Мониторинг здоровья CI/CD при миграции

**Ключевые метрики для отслеживания:**

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Pipeline Success Rate** | Доля успешных пайплайнов после миграции | > 95% (в течение 1 недели) |
| **Mean Time to Recovery (MTTR)** | Среднее время восстановления после сбоя пайплайна | < 30 минут |
| **Pipeline Duration (P95)** | 95-й перцентиль длительности пайплайна | Не более +10% от базового |
| **Deployment Frequency** | Частота деплоев после миграции | Не менее до-миграционного уровня |
| **Change Failure Rate** | Доля сбоев, вызванных изменениями конфигурации | < 5% |

**Пример мониторинга через GitLab API:**

```bash
# Получение метрик пайплайнов за последние 7 дней
glab api "projects/${CI_PROJECT_ID}/pipelines?updated_after=$(date -d '7 days ago' +%Y-%m-%d)" \
  | jq '[.[] | {status: .status, duration: .duration}]'
# → Пример вывода: [{"status":"success","duration":142},{"status":"failed","duration":89}]

# Анализ причин сбоев
glab api "projects/${CI_PROJECT_ID}/pipelines?status=failed&per_page=10" \
  | jq '.[].failure_reason'
```

**Настройка алертинга:**

```yaml
# monitoring/ci-health-alert.yml
pipeline_success_rate:
  stage: monitoring
  script:
    - |
      SUCCESS_RATE=$(glab api "projects/${CI_PROJECT_ID}/pipelines" \
        | jq '[.[] | select(.status=="success")] | length / length * 100')
      if (( $(echo "$SUCCESS_RATE < 95" | bc -l) )); then
        echo "ALERT: Pipeline success rate dropped to ${SUCCESS_RATE}%"
        exit 1
      fi
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
```

### Стратегии отката (Rollback Strategies)

**Уровень 1: Откат версии компонента (Простейший)**

```yaml
# Было (сломанная версия)
include:
  - component: '$CI_SERVER_FQDN/org/build@2.1.0'

# Стало (откат на стабильную версию)
include:
  - component: '$CI_SERVER_FQDN/org/build@2.0.0'
```

**Уровень 2: Откат через Git revert**

```bash
# 1. Найти коммит с миграцией
git log --oneline --all | grep "ci: migrate to components"
# → a1b2c3d ci: migrate to components

# 2. Откат изменений
git revert a1b2c3d

# 3. Пуш и проверка
git push origin main
glab ci lint --show-expanded  # Проверка после отката
```

**Уровень 3: Аварийный откат через API**

```bash
# Откат последнего успешного пайплайна
glab api "projects/${CI_PROJECT_ID}/pipelines" \
  | jq '.[] | select(.status=="success") | .id' \
  | head -1 \
  | xargs -I {} glab api "projects/${CI_PROJECT_ID}/pipelines/{}/retry" -X POST
```

**Уровень 4: Откат整个人体ника (Полный откат архитектуры)**

Для полного отката Stage 5 → Stage 3:

1. Создайте ветку `rollback-components-to-extends`.
2. Верните все `.gitlab-ci.yml` в проектах к версии с `include:project`.
3. Убедитесь, что шаблоны Stage 3 (extends) доступны и работоспособны.
4. Проверьте каждый проект через `glab ci lint --show-expanded`.
5. Разверните изменения по группам (Canary-подход: 10% → 50% → 100%).

### Координация миграции в команде

**Раскоммуникация и согласование:**

1. **Создание RFC (Request for Comments):**
```markdown
# RFC-001: Миграция CI/CD шаблонов на компоненты

## Статус: Proposed
## Автор: Platform Team
## Сроки: 2024-Q2

### Проблема
Текущие шаблоны Stage 3 не обеспечивают изоляцию имен переменных.

### Решение
Миграция на CI/CD Components (Stage 5) с SemVer.

### Влияние
- 50+ проектов требуют обновления `.gitlab-ci.yml`
- Ожидаемое снижение инцидентов: 30%

### План миграции
1. Неделя 1-2: Создание компонентов
2. Неделя 3-4: Миграция pilot-группы (5 проектов)
3. Неделя 5-8: Миграция остальных проектов
4. Неделя 9-10: Мониторинг и финализация
```

2. **Канал связи:**
```bash
# Уведомление команды о начале миграции
curl -X POST "${SLACK_WEBHOOK}" \
  -H 'Content-type: application/json' \
  -d '{"text":"CI/CD Migration: Stage 3 → Stage 5 starts today. Check RFC-001."}'
```

3. **Роли и ответственность:**

| Роль | Ответственность |
| :--- | :--- |
| **Platform Engineer** | Проектирование и публикация компонентов |
| **SRE** | Мониторинг здоровья CI/CD, алертинг |
| **Tech Lead** | Координация миграции команды, ревью RFC |
| **Developer** | Обновление `.gitlab-ci.yml` в своих проектах |

### Интеграция с мониторингом инфраструктуры

**Экспорт метрик через Prometheus:**

```yaml
# monitoring/ci-metrics-export.yml
export-ci-metrics:
  stage: monitoring
  image: prom/prometheus:latest
  script:
    - |
      cat > /tmp/ci-metrics.txt <<EOF
      # HELP gitlab_pipeline_success_rate Success rate of CI pipelines
      # TYPE gitlab_pipeline_success_rate gauge
      gitlab_pipeline_success_rate{project="${CI_PROJECT_NAME}"} $(success_rate)
      # HELP gitlab_pipeline_duration_seconds Duration of CI pipelines
      # TYPE gitlab_pipeline_duration_seconds histogram
      gitlab_pipeline_duration_seconds{project="${CI_PROJECT_NAME}"} $(duration)
      EOF
    - curl -X POST http://prometheus:9091/metrics/job/ci_monitoring -T /tmp/ci-metrics.txt
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
```

**Интеграция с Alertmanager:**

```yaml
# prometheus/alerts/ci-alerts.yml
groups:
  - name: ci-cd-alerts
    rules:
      - alert: CIPipelineSuccessRateLow
        expr: gitlab_pipeline_success_rate < 0.95
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Pipeline success rate dropped below 95%"
          description: "Project: {{ $labels.project }}, Rate: {{ $value }}"

      - alert: CIPipelineDurationHigh
        expr: gitlab_pipeline_duration_seconds > 1800
        for: 30m
        labels:
          severity: info
        annotations:
          summary: "Pipeline duration exceeds 30 minutes"
          description: "Project: {{ $labels.project }}, Duration: {{ $value }}s"
```

### Безопасность при миграции (Supply Chain Security)

**Проверка целостности компонентов:**

```bash
# Проверка хеша Компонента перед подключением
COMPONENT_SHA=$(glab api "projects/${COMPONENT_PROJECT_ID}/repository/commits/main" | jq -r '.id')
echo "Expected SHA: ${COMPONENT_SHA}"

# Использование SHA вместо тега в продакшене
# development: @v1.2.0 (удобство)
# production: @a1b2c3d... (безопасность)
```

**Настройка Pipeline Execution Policies:**

```yaml
# group/ci-policies/security-scan.yml
pipeline_execution_policy:
  name: "Security Scan Policy"
  description: "Принудительное сканирование безопасности для всех проектов"
  pipeline_config_strategy: include_and_merge
  include:
    - project: 'org/ci-catalog'
      file: '/templates/security/sast-scan.yml'
      ref: v2.0.0
```

## Чек-листы

### Чек-лист подготовки к миграции

- [ ] Анализ текущего состояния: `glab ci lint --show-expanded > current-state.yml`
- [ ] Определение целевого уровня зрелости (Stage 3, 4 или 5)
- [ ] Проверка зависимостей между шаблонами
- [ ] Создание RFC и согласование с командами
- [ ] Определение pilot-группы проектов для тестирования
- [ ] Настройка мониторинга и алертинга
- [ ] Подготовка плана отката

### Чек-лист публикации компонента

- [ ] Секция `spec:inputs` заполнена и синтаксически верна
- [ ] Добавлена валидация через `regex` или `options`
- [ ] Компонент прошел проверку через `glab ci lint --show-expanded`
- [ ] Проект помечен как «Catalog resource»
- [ ] Создан релиз с тегом SemVer
- [ ] Файл `README.md` содержит документацию и примеры
- [ ] Создана папка `tests/` с проверочными пайплайнами

### Чек-лист пост-миграции

- [ ] Все проекты группы обновлены
- [ ] Pipeline Success Rate > 95% в течение 1 недели
- [ ] MTTR не увеличился
- [ ] Pipeline Duration (P95) не вырос более чем на 10%
- [ ] Удалены или архивированы старые шаблоны Stage 1–3
- [ ] Обновлена документация для команд разработки
- [ ] Проведен пост-мортем миграции

## Связанные документы

- **[Обзор механизмов переиспользования](./overview.md)** — сравнение инструментов (extends vs include vs components).
- **[Продвинутые сценарии каталога](./ci_cd_catalog_advanced_scenarios.md)** — миграция, chaining, rollout через условия.
- **[Механизм наследования (extends)](./extends_keyword.md)** — детальный справочник правил слияния YAML.
- **[Справочник CI/CD Catalog](./ci_cd_catalog_components.md)** — архитектура компонентов и работа с `spec:inputs`.
- **[Валидация и версионирование](../Advanced/pipeline_validation_and_versioning.md)** — CI Lint API, Dry Run, Pipeline Execution Policies.
- **[Официальная документация: CI/CD Components](https://docs.gitlab.com/ee/ci/components/)** — текущий стандарт.
- **[Официальная документация: GitLab Steps](https://docs.gitlab.com/ee/ci/steps/)** — будущее архитектуры (Stage 6).
