# Монорепозитории в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Определения

* **Monorepo (Монорепозиторий)** — подход к организации кода, при котором несколько проектов/сервисов хранятся в одном репозитории.
* **Polyrepo (Полирепозиторий)** — традиционный подход, при котором каждый проект/сервис имеет отдельный репозиторий.
* **Changed Files Detection (Детекция изменённых файлов)** — механизм GitLab CI для определения, какие файлы изменились в коммите, и запуска только соответствующих jobs.
* **Rules:changes** — директива GitLab CI для запуска job только при изменении определённых файлов.
* **DAG (Directed Acyclic Graph)** — направленный ациклический граф зависимостей между jobs в GitLab CI.
* **Child/Parent Pipeline** — механизм вызова одного пайплайна из другого для организации сложных monorepo сценариев.
* **Dynamic Child Pipeline** — дочерний пайплайн, генерируемый динамически на основе изменённых файлов.
* **Pipeline for Merged Results (PMR)** — пайплайн, запускаемый для результата слияния MR, включая изменения из target branch.
* **Test Impact Analysis (TIA)** — методика запуска только тех тестов, которые затрагивает изменение кода.

## Требования и ограничения

### Требования

| Компонент | Требование |
|:---|:---|
| Версия GitLab | 15.8+ для `include:rules`, 17.2+ для `rules:changes:compare_to` с переменными. CE/EE/PE поддерживаются одинаково. |
| GitLab Runner | Docker/Shell executor. Для Kubernetes-монорепо требуется Runner с достаточным `concurrent` лимитом. |
| Хранилище артефактов | Локальный или внешний объектный storage (S3-compatible, GCS, Azure Blob). Для monorepo с большими артефактами требуется пропускная способность > 1 Gbps. |
| Сеть | Задержка между Runner и GitLab Server < 100 ms для быстрого скачивания артефактов и кэша. |
| Диски | SSD для локального кэша Runner'ов. IOPS > 3000 для артефактов > 1 GB. |

### Ограничения

* **Размер MR:** `rules:changes` может быть неполным при MR > 1000 файлов. Разбивайте изменения на несколько MR.
* **Первый коммит в ветке:** `changes` возвращает пустой список, так как нет предыдущего коммита. Используйте fallback `when: always`.
* **Подмодули:** изменения в Git submodules не отражаются в `rules:changes`. Используйте `rules:if` с проверкой подмодулей.
* **Кэш:** общий кэш для всех сервисов инвалидируется при любом изменении. Используйте path-scoped cache keys.
* **Artifacts:** крупные артефакты (> 1 GB) замедляют downstream jobs. Используйте `dependencies` для выборочного скачивания.
* **Секреты:** в monorepo секреты одного сервиса могут быть доступны всем jobs. Используйте `rules` + `protected` variables + `CI_JOB_TOKEN` с ограниченным доступом.
* **Pipeline creation time:** большое количество `changes` паттернов замедляет создание pipeline. Мониторьте время создания через GitLab UI/API.

## Основные концепции

### Проблемы monorepo в CI/CD

| Проблема | Описание | Решение |
|:---|:---|:---|
| **Long feedback loop** | Полный прогон всех тестов занимает часы | Селективный запуск через `rules:changes` |
| **Resource waste** | Запуск ненужных jobs расходует ресурсы | Changed files detection + DAG |
| **Cache invalidation** | Изменение в общем коде инвалидирует кэш всех проектов | Path-scoped cache keys |
| **Pipeline complexity** | Один большой `.gitlab-ci.yml` становится неуправляемым | Child pipelines + components |
| **Cross-service changes** | Изменение затрагивает несколько сервисов | Dependency graph + matrix builds |

### Стратегии monorepo CI

| Стратегия | Описание | Применение |
|:---|:---|:---|
| **Path-based** | Запуск jobs по изменённым путям | Проекты с чёткими границами |
| **File-based** | Запуск jobs по изменённым файлам (glob patterns) | Проекты с overlapping boundaries |
| **DAG-based** | Запуск jobs на основе зависимостей между компонентами | Сложные monorepo с cross-dependencies |
| **Dynamic pipeline** | Генерация пайплайна на основе анализа изменений | Большие monorepo (100+ компонентов) |
| **Test Impact Analysis** | Запуск только затронутых тестов | Монолит с большой тестовой базой |

### GitLab CI features для monorepo

| Feature | Описание | Где используется |
|:---|:---|:---|
| **rules:changes** | Запуск job при изменении файлов | Path-based filtering |
| **needs** | DAG зависимости между jobs | DAG-based pipelines |
| **workflow:rules** | Глобальные правила запуска пайплайна | Conditional pipelines |
| **include:rules** | Условный include файлов | Dynamic configuration |
| **Child pipelines** | Вложенные пайплайны | Modular configuration |
| **Dynamic child pipelines** | Генерация пайплайна через script | Dynamic configuration |
| **Pipeline for Merged Results** | Тестирование результата слияния | MR validation |
| **CI_JOB_TOKEN** | Токен для межпроектного доступа | Cross-project triggers |
| **CI_PIPELINE_SOURCE** | Определение источника пайплайна | Conditional logic |

## Практические сценарии

### Сценарий 1: Path-based monorepo (простой)

Структура репозитория:
```
monorepo/
├── .gitlab-ci.yml
├── frontend/
│   ├── package.json
│   └── src/
├── backend/
│   ├── package.json
│   └── src/
└── shared/
    ├── types/
    └── utils/
```

```yaml
# .gitlab-ci.yml

stages:
  - lint
  - test
  - build
  - deploy

# Lint frontend только при изменении frontend/ файлов
lint_frontend:
  stage: lint
  image: node:20
  script:
    - cd frontend
    - npm ci
    - npm run lint
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - frontend/**/*
        - shared/**/*
  cache:
    key: ${CI_COMMIT_REF_SLUG}-frontend
    paths:
      - frontend/node_modules/

# Lint backend только при изменении backend/ файлов
lint_backend:
  stage: lint
  image: golang:1.22
  script:
    - cd backend
    - go mod download
    - go vet ./...
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - backend/**/*
        - shared/**/*
  cache:
    key: ${CI_COMMIT_REF_SLUG}-backend
    paths:
      - backend/go.sum

# Test frontend
test_frontend:
  stage: test
  image: node:20
  script:
    - cd frontend
    - npm ci
    - npm test
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - frontend/**/*
        - shared/**/*

# Test backend
test_backend:
  stage: test
  image: golang:1.22
  script:
    - cd backend
    - go test ./...
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - backend/**/*
        - shared/**/*

# Build frontend
build_frontend:
  stage: build
  image: node:20
  script:
    - cd frontend
    - npm ci
    - npm run build
  artifacts:
    paths:
      - frontend/dist/
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      changes:
        - frontend/**/*
        - shared/**/*

# Build backend
build_backend:
  stage: build
  image: golang:1.22
  script:
    - cd backend
    - go build -o bin/app
  artifacts:
    paths:
      - backend/bin/
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      changes:
        - backend/**/*
        - shared/**/*
```

### Сценарий 2: Dynamic child pipelines (сложный monorepo)

Структура репозитория:
```
monorepo/
├── .gitlab-ci.yml
├── services/
│   ├── api/
│   ├── worker/
│   └── web/
├── libraries/
│   ├── go-utils/
│   └── ts-utils/
└── ci/
    └── templates/
```

```yaml
# .gitlab-ci.yml (root)

stages:
  - detect
  - lint
  - test
  - build
  - deploy

# Определение изменённых сервисов
detect_changes:
  stage: detect
  image: alpine:latest
  script:
    - |
      # Получение списка изменённых директорий
      CHANGED_DIRS=$(git diff --name-only $CI_COMMIT_BEFORE_SHA $CI_COMMIT_SHA | \
        grep -E '^services/[^/]+/' | \
        cut -d'/' -f2 | \
        sort -u | \
        tr '\n' ' ')
      echo "CHANGED_SERVICES=$CHANGED_DIRS" >> build.env
  artifacts:
    reports:
      dotenv: build.env
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# Динамический запуск дочерних пайплайнов
generate_child_pipelines:
  stage: detect
  image: python:3.11
  script:
    - |
      import os
      import yaml

      changed_services = os.environ.get('CHANGED_SERVICES', '').split()
      if not changed_services:
        changed_services = ['api', 'worker', 'web']  # All services for main branch

      for service in changed_services:
        # Генерация дочернего пайплайна
        child_pipeline = {
          'stages': ['lint', 'test', 'build', 'deploy'],
          'include': [{'local': f'services/{service}/.gitlab-ci.yml'}],
          'variables': {
            'SERVICE': service
          }
        }

        # Запись в файл
        with open(f'{service}-pipeline.yml', 'w') as f:
          yaml.dump(child_pipeline, f, default_flow_style=False, sort_keys=False)

        # Триггер дочернего пайплайна через trigger job
        print(f"Generated {service}-pipeline.yml")
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  dependencies:
    - detect_changes
```

### Сценарий 3: DAG-based monorepo

```yaml
# .gitlab-ci.yml

stages:
  - lint
  - test
  - build
  - integration-test
  - deploy

# Lint shared библиотеки
lint_shared:
  stage: lint
  image: node:20
  script:
    - cd libraries/ts-utils
    - npm ci
    - npm run lint
  rules:
    - changes:
        - libraries/**/*
        - services/**/*

# Test shared библиотеки
test_shared:
  stage: test
  image: node:20
  script:
    - cd libraries/ts-utils
    - npm ci
    - npm test
  rules:
    - changes:
        - libraries/**/*

# Lint API сервис
lint_api:
  stage: lint
  image: golang:1.22
  script:
    - cd services/api
    - go vet ./...
  needs:
    - lint_shared
  rules:
    - changes:
        - services/api/**/*
        - libraries/**/*

# Lint Worker сервис
lint_worker:
  stage: lint
  image: golang:1.22
  script:
    - cd services/worker
    - go vet ./...
  needs:
    - lint_shared
  rules:
    - changes:
        - services/worker/**/*
        - libraries/**/*

# Test API
test_api:
  stage: test
  image: golang:1.22
  script:
    - cd services/api
    - go test ./...
  needs:
    - lint_api
  rules:
    - changes:
        - services/api/**/*
        - libraries/**/*

# Test Worker
test_worker:
  stage: test
  image: golang:1.22
  script:
    - cd services/worker
    - go test ./...
  needs:
    - lint_worker
  rules:
    - changes:
        - services/worker/**/*
        - libraries/**/*

# Integration test (зависит от обоих сервисов)
integration_test:
  stage: integration-test
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker compose -f services/docker-compose.yml up --build --abort-on-container-exit
  needs:
    - test_api
    - test_worker
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Сценарий 4: Test Impact Analysis

```yaml
# .gitlab-ci.yml

stages:
  - detect
  - test
  - build

# Определение затронутых тестов
detect_tests:
  stage: detect
  image: python:3.11
  script:
    - |
      import os
      import subprocess
      import json

      # Получение изменённых файлов
      result = subprocess.run(
        ['git', 'diff', '--name-only', os.environ['CI_COMMIT_BEFORE_SHA'], os.environ['CI_COMMIT_SHA']],
        capture_output=True, text=True
      )
      changed_files = result.stdout.strip().split('\n')

      # Определение затронутых модулей
      affected_modules = set()
      for f in changed_files:
        if f.startswith('services/api/'):
          affected_modules.add('api')
        elif f.startswith('services/worker/'):
          affected_modules.add('worker')
        elif f.startswith('libraries/'):
          affected_modules.add('shared')

      # Запуск только затронутых тестов
      for module in affected_modules:
        print(f"Running tests for {module}")

      # Сохранение результатов
      with open('test_plan.json', 'w') as f:
        json.dump({'modules': list(affected_modules)}, f)
  artifacts:
    reports:
      dotenv: test_plan.json
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# Запуск тестов только для затронутых модулей
run_tests:
  stage: test
  image: golang:1.22
  script:
    - |
      MODULES=${TEST_MODULES:-all}
      if [ "$MODULES" = "all" ]; then
        go test ./...
      else
        for module in $MODULES; do
          go test ./services/$module/...
        done
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Сценарий 5: Matrix builds для multi-service

```yaml
# .gitlab-ci.yml

stages:
  - lint
  - test
  - build

# Matrix lint для всех сервисов
lint_services:
  stage: lint
  image: node:20
  script:
    - cd services/$SERVICE
    - npm ci
    - npm run lint
  parallel:
    matrix:
      - SERVICE: ["api", "worker", "web", "mobile"]
  rules:
    - changes:
        - services/$SERVICE/**/*

# Matrix test для всех сервисов
test_services:
  stage: test
  image: node:20
  script:
    - cd services/$SERVICE
    - npm ci
    - npm test
  parallel:
    matrix:
      - SERVICE: ["api", "worker", "web", "mobile"]
  rules:
    - changes:
        - services/$SERVICE/**/*

# Build только изменённых сервисов
build_services:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker build -t $CI_REGISTRY/$CI_PROJECT_PATH/$SERVICE:$CI_COMMIT_SHA services/$SERVICE
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH/$SERVICE:$CI_COMMIT_SHA
  parallel:
    matrix:
      - SERVICE: ["api", "worker", "web", "mobile"]
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      changes:
        - services/$SERVICE/**/*
```

### Сценарий 7: `rules:changes:compare_to` (GitLab 17.2+)

```yaml
# .gitlab-ci.yml

stages:
  - test
  - build

# Сравнение изменений с целевой веткой MR
test_service:
  stage: test
  image: golang:1.22
  script:
    - cd services/$SERVICE
    - go test ./...
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        compare_to: $CI_MERGE_REQUEST_TARGET_BRANCH_NAME
        paths:
          - services/$SERVICE/**/*
          - shared/**/*
      when: always
    - when: never
```

`compare_to` решает проблему squash/merge, когда GitLab не может вычислить changed files корректно, так как head commit не существует в target branch.

### Сценарий 8: Безопасный деплой в monorepo с `resource_group`

```yaml
# .gitlab-ci.yml

stages:
  - deploy

deploy_api:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl apply -f services/api/manifests/
  resource_group: api-production
  environment:
    name: production
    url: https://api.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      changes:
        - services/api/**/*
  timeout: 30m
  retry:
    max: 2
    when:
      - runner_system_failure
      - stuck_or_timeout_failure

deploy_worker:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl apply -f services/worker/manifests/
  resource_group: worker-production
  environment:
    name: production
    url: https://worker.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      changes:
        - services/worker/**/*
  timeout: 30m
  retry:
    max: 2
    when:
      - runner_system_failure
      - stuck_or_timeout_failure
```

`resource_group` предотвращает одновременный деплой одного сервиса в production. `timeout` и `retry` защищают от зависших jobs и transient-ошибок Runner'ов.

## Валидация и диагностика

### CI Lint и симуляция пайплайна

```bash
# Встроенный линтер: Settings → CI/CD → Editor → Validate pipeline
# Или через API:
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/ci/lint" \
  -d "content=$(cat .gitlab-ci.yml)"
```

Проверьте:
1. **Simulate pipeline** — показывает, какие jobs запустятся для указанного ветки/тега/MR без реального выполнения.
2. **Empty Pipeline** — если симуляция возвращает пустой пайплайн, проверьте `workflow:rules` на наличие fallback-правила.
3. **`rules:changes` coverage** — убедитесь, что паттерны покрывают lock-файлы и необходимые директории.
4. **Matrix expansion** — для `parallel:matrix` проверьте, что переменные корректно раскрываются.

### Проверка changed files через git diff

```bash
# Сравнение текущего коммита с предыдущим
git diff --name-only HEAD~1 HEAD

# Для MR: сравнение с целевой веткой
git diff --name-only origin/main...HEAD

# Проверка, попадает ли файл под паттерн
git diff --name-only origin/main...HEAD | grep -E '^services/api/.*\.py$'
```

### API: получение списка changed files для pipeline

```bash
# Список коммитов в pipeline
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/commits" | \
  jq '.[].id'

# Сравнение двух коммитов через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/repository/compare?from=$FROM_REF&to=$TO_REF" | \
  jq '.diffs[].new_path'
```

### Проверка фильтрации jobs через API

```bash
# Получите список jobs пайплайна
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/jobs" | \
  jq '.[].name'
```

### Push rules: серверная валидация

```bash
# Включение push rules через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  -X PUT \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/push_rule" \
  -d "branch_name_regex=^(main|release/.*)$" \
  -d "commit_message_regex=(feat|fix|chore|docs):"
```

## Операции и команды

### Управление кэшем

```bash
# Очистка кэша через API (для конкретного проекта)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  -X POST \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache/clear"

# Очистка кэша Runner'а (локально)
gitlab-runner cache-clear --cache-dir /cache/gitlab-runner
```

### Управление артефактами

```bash
# Скачивание артефактов конкретного job через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$JOB_ID/artifacts" \
  -o artifacts.zip

# Список артефактов job'ов
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs" | \
  jq '.[] | select(.name | contains("build")) | {name, artifacts}'
```

### Проверка pipeline через CLI

```bash
# Список последних pipeline'ов
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines?per_page=5"

# Статус конкретного pipeline
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID"

# Retry failed jobs
curl --header "PRIVATE-TOKEN: $TOKEN" \
  -X POST \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/retry"
```

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| Все jobs запускаются всегда | Неправильный `rules:changes` | Проверьте glob patterns, убедитесь что пути корректны. Уберите `when: always` без условий. |
| Кэш инвалидируется часто | Общий ключ кэша для всех сервисов | Используйте path-scoped cache keys: `key: ${CI_COMMIT_REF_SLUG}-${SERVICE}`. |
| Долгий pipeline | Отсутствие DAG, последовательное выполнение | Используйте `needs` для параллелизма. Вынесите тяжёлые jobs в отдельные stages. |
| Child pipeline не запускается | Ошибка в YAML-файле | Проверьте валидность YAML, логи runner'а. Убедитесь, что дочерний файл существует в артефактах. |
| `include:rules` не работает | Устаревшая версия GitLab | Требуется GitLab 15.8+. Проверьте версию через `gitlab-rake gitlab:env:info`. |
| Pipeline for MR не запускается | Не настроен MR pipeline | Включите в Settings → CI/CD → General pipelines. Проверьте `workflow:rules`. |
| `changes` пуст для первого коммита | Нет предыдущего коммита | Добавьте fallback `when: always` для critical jobs. |
| Пустой пайплайн | `workflow:rules` блокирует все источники | Добавьте fallback-правило для `merge_request_event` и `push`. Проверьте через CI Lint. |
| Долгое создание pipeline (>30s) | Слишком много `changes` паттернов | Упростите правила. Используйте `workflow:rules` для грубой фильтрации. |
| `rules:changes` неполный для больших MR | > 1000 файлов | Разбивайте MR. Используйте `exists` для lock-файлов. |
| Подмодули игнорируются | `changes` не отслеживает submodules | Используйте `rules:if` с проверкой `git submodule status`. |
| Cross-service деплой конфликтует | Одновременный деплой нескольких сервисов | Используйте `resource_group` для сериализации деплоя. |
| Артефакты не скачиваются | Отсутствует `dependencies` или `needs` | Укажите `dependencies: [build_api]` для выборочного скачивания. |
| Matrix job не фильтруется | `changes` с переменной в паттерне | Используйте `rules:changes` с явным списком путей или `exists`. |
| Secrets доступны всем jobs | Нет ограничения по `rules` | Используйте `protected` branches + `rules:if: $CI_COMMIT_BRANCH == "main"` + `protected: true`. |
| Секреты утекают в логи | `script` печатает переменные | Используйте `echo "$VAR" >> secret.env` через `artifacts:reports:dotenv`, но не в stdout. Включите `CI_DEBUG_TRACE` только для отладки. |
| `compare_to` не работает | Устаревшая версия GitLab | Требуется GitLab 17.2+. Проверьте версию. |
| `resource_group` блокирует деплой | Другой job занял группу | Увеличьте таймаут деплоя или убедитесь, что предыдущий деплой завершился. |

## Безопасность monorepo CI

### Секреты и переменные

* **Path-scoped secrets:** не храните секреты всех сервисов в одном месте. Используйте `rules` для ограничения доступа к переменным.
* **Protected branches:** секреты production должны быть доступны только на `protected` ветках (`protected: true` в job).
* **Masked variables:** включайте `masking` для всех секретов. Избегайте секретов в артефактах и логах.
* **CI_JOB_TOKEN:** ограничьте `CI_JOB_TOKEN` через `CI_JOB_TOKEN_SCOPE` или используйте `PROJECT_ACCESS_TOKEN` с минимальными правами.
* **External secrets:** для production используйте Vault/DO/Sealed Secrets. Храните только references в CI variables.

### Доступ и ownership

* **CODEOWNERS:** настройте `CODEOWNERS` для каждого сервиса в monorepo. GitLab будет запрашивать approval только от ответственных.
* **Push rules:** ограничьте возможные ветки и формат commit messages через push rules.
* **Approval rules:** настройте approval rules на уровне групп для критичных директорий.
* **Protected tags:** защитите production-теги от-force push.

### Артефакты и кэш

* **Artifact access:** артефакты одного сервиса не должны быть доступны другому без явного `dependencies`.
* **Cache poisoning:** используйте `fallback_keys` для кэша и `policy: pull-push` для изоляции.
* **Retention:** настройте `expire_in` для артефактов (рекомендуется 7–30 дней для build, 1–7 дней для test).

## Мониторинг monorepo CI

### Ключевые метрики

| Метрика | Описание | Алерт |
|:---|:---|:---|
| `gitlab_ci_pipeline_duration_seconds` | Длительность пайплайна | > 30 min для monorepo |
| `gitlab_ci_job_duration_seconds` | Длительность job | > 15 min |
| `gitlab_ci_pipeline_creation_duration_seconds` | Время создания пайплайна | > 30s |
| `gitlab_ci_jobs_failed_total` | Количество упавших jobs | Тренд > N за час |
| `gitlab_ci_jobs_stuck_total` | Зависшие jobs | > 0 |
| `gitlab_runner_jobs` | Jobs на Runner'е | > concurrent limit |
| `gitlab_storage_artifacts_size_bytes` | Размер артефактов | > 1 GB на job |

### Prometheus-алерты

```yaml
groups:
  - name: gitlab_monorepo_ci
    rules:
      - alert: GitLabMonorepoPipelineSlow
        expr: histogram_quantile(0.95, rate(gitlab_ci_pipeline_duration_seconds_bucket[1h])) > 1800
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Monorepo pipeline p95 > 30m"
          description: "Длительность пайплайна {{ $value }}s. Проверьте rules:changes и DAG."

      - alert: GitLabMonorepoPipelineCreationSlow
        expr: histogram_quantile(0.95, rate(gitlab_ci_pipeline_creation_duration_seconds_bucket[1h])) > 30
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Pipeline creation > 30s"
          description: "Создание пайплайна {{ $value }}s. Проверьте количество rules:changes паттернов."

      - alert: GitLabMonorepoJobFailed
        expr: increase(gitlab_ci_jobs_failed_total[1h]) > 5
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "> 5 failed jobs за час"
          description: "{{ $value }} jobs упало. Проверьте логи."
```

### Аудит и логирование

* **Audit log:** включите audit logging для отслеживания изменений `.gitlab-ci.yml`.
* **Job logs:** храните логи jobs минимум 30 дней. Для compliance — 90 дней.
* **Metrics retention:** Prometheus метрики CI — минимум 15 дней для операций, 90 дней для trend analysis.

## Граничные случаи и ограничения

### Первый коммит в ветке

GitLab не имеет предыдущего коммита для сравнения → `changes` возвращает пустой список. Все jobs с `rules:changes` не запустятся.

```yaml
rules:
  - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    changes:
      - services/api/**/*
    when: always
  - when: always  # Fallback для первого коммита
```

### Merge/squash merge

При squash merge GitLab не может вычислить changed files до merge, так как head commit не существует в target branch. Используйте `rules:changes:compare_to` (GitLab 17.2+) для явного указания базы сравнения.

### Большие MR (>1000 файлов)

GitLab ограничивает объём diff для `changes`. Список может быть неполным, и задачи не запустятся, хотя изменились релевантные файлы.

**Решения:**
- Разбивайте MR на несколько.
- Используйте `exists` для проверки lock-файлов.
- Фильтруйте на уровне `workflow:rules`.

### Подмодули

Изменения в Git submodules не отражаются в `rules:changes`. GitLab сравнивает только файлы в репозитории проекта.

```yaml
rules:
  - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    changes:
      - services/api/**/*
    when: always
  - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    when: always  # Fallback для submodule изменений
```

### Восстановление после сбоя Runner'а

Для длинных monorepo jobs настройте `retry`:

```yaml
test_service:
  stage: test
  script: go test ./...
  retry:
    max: 2
    when:
      - runner_system_failure
      - stuck_or_timeout_failure
```

## Лучшие практики

### Структура monorepo

* **Clear boundaries:** чётко разделяйте сервисы/библиотеки по директориям.
* **Shared ownership:** назначьте ответственных за каждую директорию.
* **Minimal coupling:** минимизируйте cross-service зависимости.
* **Documentation:** документируйте структуру и ownership.
* **Lock-файлы:** храните lock-файлы (package-lock.json, go.sum, Cargo.lock) рядом с кодом, а не в корне. Это упрощает `rules:changes`.
* **CI конфигурация:** выносите `.gitlab-ci.yml` сервисов в их директории. Root-файл должен содержать только глобальную логику.

### CI/CD

* **Changed files first:** используйте `rules:changes` как первую линию фильтрации.
* **DAG over stages:** используйте `needs` для параллелизма вместо sequential stages.
* **Child pipelines:** выносите конфигурацию сервисов в отдельные файлы.
* **Dynamic pipelines:** используйте для автоматического определения изменённых сервисов.
* **Cache isolation:** используйте path-scoped cache keys для каждого сервиса.
* **Artifact retention:** настройте `expire_in` для артефактов.
* **Fallback для `changes`:** всегда добавляйте `when: always` fallback для critical jobs на случай первого коммита.
* **`compare_to` для MR:** используйте `rules:changes:compare_to` (GitLab 17.2+) для корректной работы при squash/merge.
* **Matrix builds:** используйте `parallel:matrix` для параллельного запуска одинаковых jobs для разных сервисов.
* **Resource groups:** используйте `resource_group` для сериализации деплоя в production.

### Кэширование

* **Path-scoped keys:** `key: ${CI_COMMIT_REF_SLUG}-${SERVICE}` предотвращает коллизии между сервисами.
* **Cache policy:** используйте `cache:policy: pull-push` для read-only кэша или `push` для инвалидации.
* **Fallback keys:** `fallback_keys: [${CI_COMMIT_REF_SLUG}-${SERVICE}-${CI_COMMIT_SHA}]` позволяет переиспользовать предыдущий кэш при инвалидации.
* **Cache hit ratio:** мониторьте `cache: hit ratio` через GitLab UI. Цель: > 50% для monorepo.

### Безопасность

* **Secrets isolation:** используйте `rules` + `protected` variables + `CI_JOB_TOKEN` с ограниченным доступом.
* **CODEOWNERS:** настройте CODEOWNERS для каждого сервиса. GitLab будет запрашивать approval только от ответственных.
* **Push rules:** ограничьте возможные ветки и формат commit messages через push rules.
* **Artifact access:** артефакты одного сервиса не должны быть доступны другому без явного `dependencies`.
* **Masking:** включайте `masking` для всех секретов. Избегайте секретов в артефактах и логах.

### Производительность

* **Parallel matrix builds:** используйте `parallel:matrix` для параллельного запуска.
* **Selective testing:** запускайте только затронутые тесты.
* **Incremental builds:** используйте кэш для ускорения сборок.
* **Resource limits:** ограничивайте ресурсы для каждого job через `tags` и Runner конфигурацию.
* **Timeout:** настройте `timeout` для всех jobs (рекомендуется 30–60 min для test, 15 min для lint).
* **Retry:** настройте `retry` для transient-ошибок Runner'ов (`runner_system_failure`, `stuck_or_timeout_failure`).

### Эксплуатация (SRE/Sysadmin)

* **Pipeline creation time:** мониторьте время создания пайплайна. Цель: < 30s. Если больше — упростите `rules:changes`.
* **MR size limit:** ограничьте максимальный размер MR (500–1000 файлов) для стабильности `changes`.
* **Runner concurrency:** для monorepo требуются Runner'ы с высоким `concurrent` лимитом. Мониторьте `gitlab_runner_jobs`.
* **Artifact storage:** для артефактов > 1 GB используйте external object storage (S3-compatible). Локальный диск заполнится быстро.
* **Group-level policies:** настройте group-level `workflow:rules` для общих ограничений (например, запрет деплоя из MR).
* **Audit logging:** включите audit logging для отслеживания изменений `.gitlab-ci.yml` и секретов.
* **DR Drill:** включите `resource_group` и протестируйте восстановление после сбоя деплоя.
* **NTP:** синхронизация времени на всех узлах (разница < 100 ms) для корректной работы `compare_to`.

## Дополнительная информация

### Связанные темы

*   **[CI/CD Catalog Components](../Reusable_Pipelines/ci_cd_catalog_components.md)** — современный стандарт переиспользования
*   **[Reusable Pipelines Overview](../Reusable_Pipelines/overview.md)** — переиспользуемые пайплайны
* **[CI/CD Components Catalog Limits](../Reusable_Pipelines/ci_cd_catalog_limits.md)** — лимиты и ограничения
* **[Changed Files and Workflow Rules](../Advanced/changed_files_and_workflow_rules.md)** — детекция изменённых файлов
* **[GitLab CI Basics](../Concepts/gitlab_ci_basics.md)** — база по стадиям и архитектуре

### Внешние ресурсы

* [GitLab CI Changed Rules](https://docs.gitlab.com/ee/ci/yaml/#ruleschanges)
* [GitLab Child Pipelines](https://docs.gitlab.com/ee/ci/parent_child_pipelines.html)
* [GitLab DAG](https://docs.gitlab.com/ee/ci/dag/)
* [GitLab Merge Request Pipelines](https://docs.gitlab.com/ee/ci/pipelines/merge_request_pipelines.html)
