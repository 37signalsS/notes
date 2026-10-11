# GitLab CI/CD: справочник ключевых слов YAML

**Актуально для:** GitLab 17.x–19.x

## Определения

**Keyword (Ключевое слово)** — элемент конфигурации `.gitlab-ci.yml`, управляющий поведением пайплайна.

**Global Keyword** — ключевое слово, применимое на корневом уровне или уровне job.

**Job-level Keyword** — ключевое слово, применимое только внутри конкретной задачи.

**Default Block** — блок `default:` для определения глобальных параметров задач (GitLab 18.x+).

**Deprecated Keyword** — устаревшее ключевое слово, подлежащее замене.

**Expression** — динамическое выражение, разрешаемое во время выполнения или компиляции.

**Hidden Job** — задание, имя которого начинается с точки (например, `.base_job`). Такие задания игнорируются планировщиком GitLab и служат шаблонами для `extends` и `!reference`.

**DAG (Directed Acyclic Graph)** — модель выполнения пайплайна, где задачи запускаются по готовности зависимостей через `needs`, а не строго по стадиям.

**Resource Group** — серверный мьютекс (`resource_group`), сериализующий доступ задачи к внешнему ресурсу (реестр, БД, bare-metal сервер) для предотвращения race conditions.

**Matrix Build** — декларативный механизм `parallel:matrix`, генерирующий декартово произведение комбинаций переменных для параллельного тестирования/сборки.

**Workflow Rule** — правило на уровне пайплайна (`workflow:rules`), определяющее, должен ли пайплайн быть создан вообще.

**Bound Claims** — набор ограничений в роли внешнего провайдера (Vault, Consul), гарантирующий, что токен будет принят только от конкретного проекта или ветки GitLab.

## Основные концепции

### Иерархия ключевых слов

```
.gitlab-ci.yml
├── default:          # Глобальные настройки по умолчанию (18.x+)
│   ├── image
│   ├── services
│   ├── before_script
│   ├── after_script
│   └── cache
├── workflow:         # Управление пайплайном в целом
│   └── rules
├── stages:           # Определение стадий
├── variables:        # Глобальные переменные
├── include:          # Подключение внешних файлов
├── spec:             # Pipeline Inputs (17.11+)
│   └── inputs
└── <job_name>:       # Задача
    ├── stage
    ├── image
    ├── services
    ├── before_script
    ├── script
    ├── after_script
    ├── rules
    ├── only/except
    ├── when
    ├── allow_failure
    ├── timeout
    ├── retry
    ├── parallel
    ├── matrix
    ├── resource_group
    ├── interruptible
    ├── tags
    ├── cache
    ├── artifacts
    ├── dependencies
    ├── needs
    ├── trigger
    ├── environment
    ├── release
    └── ...
```

### Глобальные ключевые слова

| Ключевое слово | Уровень | Тип | Описание |
|:---|:---|:---|:---|
| `stages` | Global | List | Определяет порядок и названия стадий |
| `variables` | Global | Map | Глобальные переменные окружения |
| `default` | Global | Map | Блок настроек по умолчанию для всех задач (18.x+) |
| `include` | Global | List/Map | Подключение внешних YAML-файлов |
| `workflow` | Global | Map | Управление созданием пайплайна |
| `spec` | Global | Map | Pipeline Inputs (17.11+) |

### Ключевые слова задачи

| Ключевое слово | Тип | По умолчанию | Описание |
|:---|:---|:---|:---|
| `stage` | String | `test` | Стадия, к которой относится задача |
| `image` | String/Map | `default` | Docker-образ для выполнения |
| `services` | List | — | Дополнительные сервисные контейнеры |
| `before_script` | List/String | — | Команды, выполняемые перед `script` |
| `script` | List/String | — | Основные команды задачи |
| `after_script` | List/String | — | Команды, выполняемые после `script` |
| `rules` | List | — | Правила запуска задачи (современный синтаксис) |
| `only` | List/String | — | Устаревшее: условия для запуска |
| `except` | List/String | — | Устаревшее: условия для пропуска |
| `when` | String | `on_success` | Условие запуска (`manual`, `always`, `never`, `on_success`, `on_failure`) |
| `allow_failure` | Boolean | `false` | Разрешить падение задачи без блокировки пайплайна |
| `timeout` | String | `30m` | Таймаут выполнения задачи |
| `retry` | Integer/Map | `0` | Количество повторных запусков при падении |
| `parallel` | Integer | — | Количество параллельных экземпляров задачи |
| `matrix` | Map | — | Матрица параллельных задач (17.3+) |
| `resource_group` | String | — | Группа ресурсов для взаимного исключения |
| `interruptible` | Boolean | `true` | Разрешить автоматическую отмену при перезапуске |
| `tags` | List | — | Теги для выбора Runner'а |
| `cache` | Map/List | — | Кэширование файлов между запусками |
| `artifacts` | Map/List | — | Артефакты, сохраняемые после выполнения |
| `dependencies` | List | — | Задачи, артефакты которых нужно скачать |
| `needs` | List/Map | — | Задачи, от которых зависит текущая (DAG) |
| `trigger` | Map | — | Запуск downstream-пайплайна |
| `environment` | String/Map | — | Окружение для деплоя |
| `release` | Map | — | Создание GitLab Release |
| `coverage` | String | — | Регулярное выражение для извлечения % покрытия |
| `pages` | Map | — | Деплой статических файлов на GitLab Pages |
| `epoch` | Integer | `0` | Версия конфигурации задачи |
| `secrets` | Map | — | Секреты для задач (19.2+) |

### Специальные ключевые слова

| Ключевое слово | Уровень | Описание |
|:---|:---|:---|
| `!reference` | Job | Копирование фрагмента YAML из другой задачи |
| `extends` | Job | Наследование конфигурации от другой задачи или шаблона |
| `spec:inputs` | Global | Типизированные параметры для компонентов |
| `default:before_script` | Global | Глобальный `before_script` (18.x+) |
| `default:after_script` | Global | Глобальный `after_script` (18.x+) |
| `default:image` | Global | Глобальный образ (18.x+) |
| `default:services` | Global | Глобальные сервисы (18.x+) |
| `default:cache` | Global | Глобальный кэш (18.x+) |

### Обработка директив (порядок компиляции)

Для понимания поведения ключевых слов важен порядок их обработки GitLab CI:

1. **Парсинг YAML** — базовая проверка синтаксиса
2. **Обработка `include`** — сборка полного YAML-документа
3. **Интерполяция `inputs`** — подстановка параметров в компоненты
4. **Обработка `variables`** — разрешение статических переменных
5. **Применение `extends`** — слияние структур заданий (reverse deep merge)
6. **Разрешение `!reference`** — финальная вставка фрагментов кода
7. **Вычисление `rules`** — фильтрация задач
8. **Построение DAG через `needs`** — определение порядка выполнения

### Приоритет источников переменных (GitLab 19.x)

При конфликте имён переменных GitLab соблюдает строгую иерархию (от высшего к низшему):

1. Pipeline Execution Policies
2. Переменные ручного запуска (Web UI / API), триггеры, расписания
3. Переменные проекта (`project variables`)
4. Переменные группы (`group variables`)
5. Переменные инстанса (`instance variables`)
6. Переменные из `artifacts:reports:dotenv` предыдущих задач
7. Переменные задачи (`job:variables`)
8. Переменные правила (`rules:variables`)
9. Переменные `workflow:rules:variables`
10. Глобальные переменные пайплайна (`variables` на верхнем уровне)
11. Deployment variables
12. Предопределённые переменные GitLab (`CI_*`)

## Практические сценарии

### Сценарий 1: Использование блока `default` (GitLab 18.x+)

Глобальные настройки, наследуемые всеми задачами автоматически:

```yaml
default:
  image: node:20-slim
  services:
    - docker:24.0-dind
  before_script:
    - npm ci
  cache:
    key: ${CI_COMMIT_REF_SLUG}
    paths:
      - node_modules/
  timeout: 20m

lint:
  script:
    - npm run lint

test:
  script:
    - npm test
```

### Сценарий 2: Правила запуска задач (`rules`)

Современный синтаксис, заменивший `only`/`except`:

```yaml
job:
  rules:
    # Запускать для Merge Request'ов
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

    # Запускать для push в main
    - if: $CI_COMMIT_BRANCH == "main"

    # Запускать вручную для других веток
    - if: $CI_COMMIT_BRANCH
      when: manual
      allow_failure: true

    # Пропускать для тегов
    - if: $CI_COMMIT_TAG
      when: never
```

### Сценарий 3: Матричные сборки (`parallel:matrix`)

Генерация декартова произведения комбинаций переменных:

```yaml
test:
  stage: test
  image: python:3.12
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.10", "3.11", "3.12"]
        DB: ["postgres", "mysql"]
  script:
    - python -m pytest tests/
```

### Сценарий 4: Resource Group для deployments

Сериализация критических операций через мьютекс:

```yaml
deploy_production:
  stage: deploy
  resource_group: production_deployments
  resource_group_process_mode: oldest_first
  script:
    - ./deploy.sh production
  environment:
    name: production
  when: manual
```

### Сценарий 5: Использование `!reference`

Атомарное переиспользование фрагментов конфигурации:

```yaml
# Определение переиспользуемого блока
.setup_environment: &setup_environment
  before_script:
    - echo "Setting up environment"
    - source ./env.sh

# Использование ссылки
job1:
  <<: *setup_environment
  script:
    - make build

# Или через !reference (между файлами)
# В include-файле:
.hidden_job:
  script:
    - echo "Shared script"

# В основном .gitlab-ci.yml:
job:
  script:
    - !reference [.hidden_job, script]
```

### Сценарий 6: Наследование через `extends`

Многоуровневая иерархия шаблонов:

```yaml
# Уровень 1: Инфраструктурный стандарт (SRE)
.infra-base:
  tags: [docker-runner]
  interruptible: true
  retry:
    max: 2
    when: [runner_system_failure, stuck_or_timeout_failure]

# Уровень 2: Технологический стек (DevOps)
.python_base:
  extends: .infra-base
  image: python:3.11
  before_script:
    - pip install -r requirements.txt
  cache:
    key: "$CI_COMMIT_REF_SLUG"
    paths: [.pip/]
    policy: pull-push

# Уровень 3: Конкретная задача (Dev)
test_unit:
  extends: .python_base
  script:
    - pytest tests/unit
  artifacts:
    reports:
      junit: reports/junit.xml
    expire_in: 7 days
```

### Сценарий 7: DAG через `needs`

Параллельное выполнение независимых задач без стадий:

```yaml
build:
  stage: build
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .

test:
  stage: test
  needs: [build]
  script:
    - docker run $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA npm test

deploy:
  stage: deploy
  needs: [test]
  script:
    - ./deploy.sh
```

### Сценарий 8: Parent-child пайплайны через `trigger`

Декомпозиция монорепозитория на изолированные конфигурации:

```yaml
# parent-pipeline.yml
stages:
  - test
  - deploy

test_service_a:
  stage: test
  trigger:
    include: service-a/.gitlab-ci.yml
    strategy: depend

test_service_b:
  stage: test
  trigger:
    include: service-b/.gitlab-ci.yml
    strategy: depend

deploy:
  stage: deploy
  needs: [test_service_a, test_service_b]
  script:
    - ./deploy-all.sh
```

### Сценарий 9: Workflow rules для фильтрации пайплайнов

Глобальные правила, предотвращающие создание пайплайнов:

```yaml
workflow:
  rules:
    # Создавать только для MR и push в защищённые ветки
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"
    - if: $CI_COMMIT_BRANCH == "develop"

    # Не создавать для WIP-коммитов
    - if: $CI_COMMIT_TITLE =~ /^WIP:/
      when: never
```

## Валидация и проверка

### Инструменты валидации

| Инструмент | Назначение | Команда / Доступ |
|:---|:---|:---|
| **IDE плагины** | Синтаксис YAML + базовые схемы GitLab CI | RedHat YAML, GitLab Workflow |
| **yamllint** | Статическая проверка синтаксиса | `yamllint -d relaxed .gitlab-ci.yml` |
| **glab ci lint** | Локальная проверка + dry-run | `glab ci lint` / `glab ci lint --dry-run` |
| **CI Lint API** | Программная проверка с раскрытием include/extends | `POST /api/v4/projects/:id/ci/lint` |
| **Pipeline Editor** | Визуальный просмотр merged YAML | Web UI → CI/CD → Pipeline Editor |
| **CI_DEBUG_TRACE** | Отладочный вывод переменных | `CI_DEBUG_TRACE=true` в задаче |

### Проверка синтаксиса YAML

```bash
# Статическая проверка
yamllint -d relaxed .gitlab-ci.yml templates/*.yml

# Проверка через GitLab CLI
glab ci lint

# Просмотр раскрытого YAML
glab ci config compile
```

### Dry Run (глубокая валидация)

```bash
# Имитация создания пайплайна с проверкой правил
glab ci lint --dry-run --ref main

# Через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --data "content=$(cat .gitlab-ci.yml | base64)" \
  "https://gitlab.example.com/api/v4/ci/lint?include_merged_yaml=true" | jq .
```

### Проверка reference и extends

```bash
# Поиск неразрешённых ссылок в раскрытом YAML
glab ci config compile > expanded.yml
grep -n "!reference" expanded.yml && echo "WARNING: unresolved references" || echo "OK"

# Проверка глубины вложенности extends
awk '/extends/{depth=0; for(i=1;i<=length($0);i++) if(substr($0,i,1)=="[") depth++; if(depth>max) max=depth} END{print max}' expanded.yml
```

### Мониторинг выполнения пайплайна

```bash
# Просмотр статуса задач через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/jobs" | \
  jq '[.[] | {name, status, duration, runner_description}]'

# Проверка активных resource_group
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/resource_groups" | \
  jq '.[] | {key, process_mode, jobs: [.jobs[] | {id, name, status}]}'
```

## Устранение неполадок

### Сводная таблица типичных ошибок

| Ошибка | Возможная причина | Решение |
|:---|:---|:---|
| `YAML syntax error` | Неверный отступ или кавычки | `yamllint`, проверка вложенности |
| `unknown keyword` | Неподдерживаемое ключевое слово | Проверка версии GitLab, документация |
| `!reference not resolved` | Ссылка на несуществующий ключ | `glab ci config compile`, проверка имени |
| `circular reference` | Кольцевая зависимость extends | Разрыв цепочки наследования |
| `exceeded max levels` | Глубина extends > 11 уровней | Упрощение иерархии, целевой ≤3 уровня |
| `Job(s) disabled` | >200 задач в одной матрице | Разбивка на несколько матриц |
| `needs:job not found` | Имя задачи в needs не совпадает | Проверка `CI_JOB_NAME` с суффиксами матрицы |
| `Resource group timeout` | Очередь не освобождается | Проверка `resource_group_process_mode` |
| `Cache collision` | Матричные задачи перезаписывают кэш | Уникальный `cache:key` с переменной матрицы |
| `Variable not defined` | Переменная не объявлена в matrix | Добавление в `parallel:matrix` |
| `rules condition failed` | Ошибка в синтаксисе `if` | Проверка переменных на этапе компиляции |
| `Token audience mismatch` | `aud` в `id_tokens` не совпадает с провайдером | Синхронизация значений |
| `JWKS fetch failed` | Vault/Consul не видит GitLab | Проверка DNS, firewall, self-signed сертификаты |

### Диагностика правил запуска

```bash
# Отладка переменных в rules
echo "CI_COMMIT_BRANCH=$CI_COMMIT_BRANCH"
echo "CI_PIPELINE_SOURCE=$CI_PIPELINE_SOURCE"
echo "CI_COMMIT_TAG=$CI_COMMIT_TAG"

# Проверка сработавшего правила
glab ci lint --dry-run --variable CI_COMMIT_BRANCH=main
```

### Диагностика matrix и resource_group

```bash
# Просмотр сгенерированных матричных задач
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/jobs" | \
  jq '[.[] | select(.name | startswith("test:python"))] | {name, status}'

# Проверка очереди resource_group
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/resource_groups" | \
  jq '.[] | {key, process_mode, job_count: (.jobs | length)}'
```

## Лучшие практики

### Безопасность

1. **Никаких секретов в YAML:** Используйте `id_tokens` (OIDC), `secrets` (Vault / GitLab Secrets Manager) или внешние менеджеры секретов. Никогда не храните секреты в шаблонах.
2. **Ограничьте scope токенов:** Настройте `bound_claims` и минимальные политики для Vault/Consul.
3. **Least Privilege:** Назначайте минимум прав на уровне bound claims, политик и `resource_group`.
4. **Аудит:** Включите audit logging в Vault/Consul и логи всех аутентификаций через OIDC.
5. **Верификация целостности:** Проверяйте checksum критических файлов и подписи Git коммитов.
6. **Ротация ключей:** Регулярная ротация ключей JWKS (автоматически каждые 90 дней в GitLab).
7. **Защищённые ветки:** Используйте `ref_protected` и `environment_protected` для production деплоев.

### Эксплуатация (DevOps/SRE)

1. **Используйте `default:`-блок:** Для DRY и соответствия GitLab 19.x. Глобальные ключи на верхнем уровне устарели.
2. **Настройте `interruptible: true`** для MR-пайплайнов — экономьте ресурсы при активной разработке.
3. **Используйте `resource_group`** для критических операций (миграции БД, деплой на bare-metal) с `interruptible: false`.
4. **Мониторьте OIDC failures:** Алерты на 401/403 от внешних провайдеров.
5. **Кэшируйте зависимости:** `cache:key: $CI_JOB_NAME-$TARGET` для матричных задач, `policy: pull-push`.
6. **Версионируйте шаблоны:** SemVer для централизованных шаблонов, `ref: vX.Y.Z` в `include:project`.
7. **Тестируйте в staging:** Перед использованием в production протестируйте OIDC flow и новые шаблоны.
8. **Мониторьте метрики:** Доступность Vault/Consul API, latency, количество активных токенов.
9. **Настройте SLO:** Доступность критических сервисов (Vault/Consul/Runner'ы) — например, 99.9% uptime.

### Sysadmin

1. **Включите `workload_oidc_token` на уровне группы:** Централизованное управление OIDC.
2. **Настройте network policies:** Ограничьте доступ к Vault/Consul/JWKS только из CI/CD сетей.
3. **Настройте TLS:** Все endpoints (GitLab, Vault, Consul, внутренние сервисы) должны использовать валидные TLS-сертификаты.
4. **Резервное копирование:** Регулярное резервное копирование Vault (Raft snapshot) и Consul (snapshot).
5. **Аудит JWT usage:** Логи всех аутентификаций через OIDC.
6. **Резервное копирование GitLab:** `gitlab-backup create` + `gitlab-secrets.json` на безопасное хранилище.
7. **Настройте мониторинг Runner'ов:** Доступность, геораспределение, SLA.
8. **Резервное копирование конфигурации CI/CD:** Храните шаблоны в отдельном репозитории с защищённой веткой `main`.

### Разработка (Dev)

1. **Используйте `rules` вместо `only`/`except`:** `only`/`except` удалены в GitLab 19.x.
2. **Тестируйте в feature branches:** Используйте `ref_protected: "false"` для тестовых сред.
3. **Используйте `spec:inputs` для компонентов:** Типизированные параметры с валидацией.
4. **Кэшируйте зависимости:** Уникальные ключи для разных версий/окружений.
5. **Артефакты с `expire_in`:** Промежуточные результаты — 1 час, финальные — 7 дней.
6. **Тестируйте в feature branches:** Используйте `when: manual` для production деплоев.

## Ограничения и крайние случаи

### Время жизни и таймауты

- ID Token истекает через таймаут задачи или 5 минут при отсутствии таймаута
- Для long-running задач (>6 минут) настройте `timeout` в задаче
- Vault/Consul credentials должны запрашиваться внутри той же задачи, где используется токен

### Bound Claims и масштабирование

- При >100 проектов используйте `bound_claims_type="glob"` для масок
- Для мульти-Tenant GitLab настройте разные `bound_issuer` в разных ролях
- `ref_protected` доступен только для защищённых веток/тегов

### Self-hosted GitLab

- При использовании self-signed сертификатов добавьте CA в доверенное хранилище Vault/Consul
- JWKS endpoint: `https://gitlab.example.com/-/jwks`
- Если сетевой доступ невозможен, используйте статический `jwt_validation_pubkeys` (требует ручной ротации)

### Ограничения YAML-конфигурации

| Параметр | Лимит | Рекомендация |
|:---|:---|:---|
| Размер одного YAML-файла | 2 MB | Разделение на `include` |
| Общий размер конфигурации | 314.6 MB | Оптимизация артефактов |
| Максимум `include` | 150 | Группировка шаблонов |
| Максимум `rules` patterns | 1000 | Упрощение условий |
| Максимум стадий | 1000 | Группировка логики |
| Задач в пайплайне | 1000 (soft limit) | Декомпозиция на downstream |
| Задач в `parallel:matrix` | 200 | Разбивка на несколько матриц |
| Глубина `extends` | 11 уровней | Целевой ≤3 уровня |
| Глубина `!reference` | 10 уровней | Рефакторинг при приближении |
| `parallel: N` (шардов) | 100 | Шардирование тестов |
| Размер dotenv файла | 5 KB, 20 переменных | Передавайте только необходимое |

### Matrix expressions (18.6+)

Matrix expressions (`$[[ matrix.VAR ]]`) упрощают создание 1:1 зависимостей, но имеют строгие ограничения:
- **Compile-time only:** Идентификаторы разрешаются при создании пайплайна, а не во время выполнения задачи
- **String replacement only:** Нет сложной логики или трансформаций
- **Matrix identifiers only:** Нельзя ссылаться на обычные CI/CD переменные или `spec:inputs`
- **Только текущая матрица:** Выражение ссылается на идентификаторы из `parallel:matrix` текущей задачи

### Несовместимость и побочные эффекты

| Механизм | Ограничение | Решение |
|:---|:---|:---|
| `dotenv` + `parallel:matrix` | Dotenv переменные не работают между инстансами матрицы | Используйте общие артефакты или API |
| `parallel:matrix` + `parallel: N` | Числовой `parallel` и `matrix` взаимоисключающие | Добавьте измерение шардирования в матрицу |
| `resource_group` + parent-child `oldest_first` | Взаимная блокировка (deadlock) | Определяйте `resource_group` в родительской задаче `trigger` |
| `interruptible: true` + `resource_group` | Критическая операция может быть прервана `auto_cancel` | Устанавливайте `interruptible: false` |
| `matrix expressions` + обычные переменные | `$[[ ... ]]` не разрешает `$CI_*` или `$VARIABLE` | Используйте только идентификаторы матрицы |

### Особые сценарии

**Deadlock при parent-child пайплайнах:**
```yaml
# ПРОБЛЕМА: родительский deploy ждет child-pipeline,
# child-pipeline ждет resource_group, который занят родителем
# РЕШЕНИЕ: resource_group определяем в trigger-задаче родителя
test:
  stage: test
  trigger:
    include: child-pipeline.yml
    strategy: mirror
  resource_group: production_deploy  # Блокировка здесь
```

**Кэширование в матричных задачах:**
```yaml
# Проблема: все матричные задачи делят один кэш
# Решение: уникальный ключ для каждой комбинации
test:
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.10", "3.11", "3.12"]
  cache:
    key: py${PYTHON_VERSION}-deps  # Уникальный ключ
    paths:
      - .venv/
```

## Очистка и откат

### Откат изменений в конфигурации

При проблемах с `!reference` или `extends` после деплоя выполните откат:

```bash
# 1. Определение последнего рабочего коммита
LAST_GOOD=$(git log --oneline -n 5 --format="%H")

# 2. Откат .gitlab-ci.yml и шаблонов
git revert --no-commit ${LAST_GOOD} -- .gitlab-ci.yml templates/
git commit -m "revert: rollback CI configuration"
git push origin main

# 3. Верификация
glab ci config compile > expanded.yml
grep -q "!reference" expanded.yml && echo "WARNING: !reference still present" || echo "OK: !reference removed"
```

### Очистка неиспользуемых якорей

```bash
#!/bin/bash
# cleanup_unused_anchors.sh

for file in templates/*.yml; do
  echo "Проверка ${file}..."
  ANCHORS=$(grep -oP '&\K[a-zA-Z0-9_-]+' "${file}" | sort -u)
  for anchor in ${ANCHORS}; do
    USAGE_COUNT=$(grep -c "\*${anchor}" "${file}" || echo "0")
    if [ ${USAGE_COUNT} -eq 0 ]; then
      echo "  Удаление неиспользуемого якоря: ${anchor}"
      sed -i "/&${anchor}/d" "${file}"
    fi
  done
done
```

### Очистка кэша GitLab Runner

```bash
# Перезапуск Runner для сброса кэша
gitlab-runner restart

# Очистка артефактов и кэша на Runner
gitlab-runner verify --delete

# Очистка через API
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache"
```

### Удаление CI/CD переменных

```bash
# Удаление переменных через API
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables/VAULT_ADDR"
```

## Дополнительная информация

### Связанные файлы

- **[Механизм !reference и YAML Anchors](../Reusable_Pipelines/reference_and_yaml_anchors.md)** — детализация ссылок
- **[Ключевое слово include](../Reusable_Pipelines/include_keyword.md)** — подключение файлов
- **[Ключевое слово extends](../Reusable_Pipelines/extends_keyword.md)** — наследование конфигурации
- **[Workflow Rules](../Advanced/workflow_rules/job_rules.md)** — правила запуска
- **[Справочник директив GitLab CI/CD](../Advanced/workflow_rules/directives_definitions.md)** — полный справочник ключевых слов
- **[Матричные сборки и сериализация](../Advanced/workflow_rules/matrix_builds_and_serialization.md)** — `parallel:matrix`, `resource_group`
- **[DAG с использованием needs](../Advanced/workflow_rules/dag_with_needs.md)** — управление графом зависимостей
- **[Валидация и версионирование пайплайнов](../../Advanced/pipeline_validation_and_versioning.md)** — проверка YAML
- **[Переменные и секреты GitLab CI/CD](../Concepts/gitlab_ci_variables_secrets.md)** — управление переменными
- **[Кеширование и артефакты](../Advanced/gitlab_ci_caching/cache_pipeline_directives.md)** — стратегии кэширования
- **[Интеграция GitLab CI и HashiCorp Vault в Kubernetes](../Tutorials/vault_kubernetes_integration.md)** — детальное руководство по Vault + K8s + OIDC

### Устаревшие ключевые слова

| Устаревшее | Современная замена | С версии |
|:---|:---|:---|
| `only` | `rules` | GitLab 12.0+ |
| `except` | `rules` | GitLab 12.0+ |
| `before_script` (global) | `default:before_script` | GitLab 18.x+ |
| `image` (global) | `default:image` | GitLab 18.x+ |
| `cache` (global) | `default:cache` | GitLab 18.x+ |
| `CI_JOB_JWT` | `id_tokens` | GitLab 15.9+ (deprecated), 18.0 (removed) |

### Ограничения

- Максимальный размер одного YAML-файла: 2 MB
- Максимальный размер всей конфигурации: 314.6 MB (2 MB × 150 includes, GitLab 17.3+)
- Максимальное количество `include`: 150
- Максимальное количество `rules` patterns: 1000
- Максимальное количество стадий: 1000
- Максимальное количество задач в пайплайне: 1000 (soft limit)

### Внешние ресурсы

- [GitLab Docs: CI/CD YAML reference](https://docs.gitlab.com/ee/ci/yaml/index.html)
- [GitLab Docs: ID Token authentication](https://docs.gitlab.com/ee/ci/secrets/id_token_authentication.html)
- [HashiCorp Vault: JWT Auth Method](https://developer.hashicorp.com/vault/docs/auth/jwt)
- [HashiCorp Consul: JWT Auth Method](https://developer.hashicorp.com/consul/docs/security/acl/auth-methods)
