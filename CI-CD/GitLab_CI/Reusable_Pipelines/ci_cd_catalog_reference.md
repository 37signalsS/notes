# GitLab CI: Каталог компонентов — справочная информация

## Определения

**Справочная информация** — систематизированный свод технических данных, параметров API, команд CLI и правил функционирования реестра CI/CD компонентов, предназначенный для глубокой интеграции и отладки.

**Валидация компонента** — процесс верификации синтаксиса YAML, структуры блока `spec:inputs`, корректности интерполяции переменных и соблюдения лимитов. Выполняется GitLab автоматически при публикации и доступен для ручного запуска через API/CLI.

**Публикация (Registration)** — процесс регистрации Git-тега репозитория в базе данных каталога. Это делает компонент доступным для поиска в UI и использования через `include:component` другими проектами.

**Инвентаризация компонентов** — процесс сбора и систематизации данных о всех доступных компонентах, их версиях, зависимостях и потреблении ресурсов для обеспечения видимости и контроля.

## Основные концепции

### Структура проекта компонента

Для корректной работы механизмов поиска и поддержки вложенности репозиторий должен соответствовать стандартной иерархии:

```text
├── templates/
│   ├── build.yml         # Основной файл компонента (содержит spec: и ---)
│   ├── deploy.yml        # Дополнительный компонент в том же репозитории
│   └── security/
│       └── scan.yml      # Вложенные пути поддерживаются (вызов: .../security/scan)
├── tests/                # Директория для интеграционных тестов (рекомендация)
├── README.md             # Документация (автоматически парсится каталогом для UI)
└── .gitlab-ci.yml        # Пайплайн для CI/CD самого компонента (тесты + релиз)
```

**Рекомендации по структуре для DevOps/SRE:**

| Директория | Назначение | Рекомендации |
| :--- | :--- | :--- |
| `templates/` | Основные файлы компонентов | Максимум 100 файлов (лимит каталога). Используйте подпапки для группировки. |
| `tests/` | Интеграционные тесты | Запускайте тесты с различными комбинациями `inputs`. Минимальное покрытие: happy path + edge cases. |
| `docs/` | Дополнительная документация | API-контракты, примеры использования, известные ограничения. |
| `scripts/` | Вспомогательные скрипты | Валидация, генерация документации, интеграция с мониторингом. |

### Форматы версий компонентов

При использовании директивы `include:component` версия указывается после символа `@`.

| Формат | Пример | Назначение | Уровень стабильности |
| :--- | :--- | :--- | :--- |
| **Commit SHA** | `@e3262fdb...` | Аудит и защита от подмены тега. | **Максимальный** |
| **SemVer (полный)** | `@1.2.0` | Фиксация конкретного стабильного релиза. | **Высокий** |
| **SemVer (частичный)** | `@1.2` или `@1` | Авто-получение patch/minor обновлений. | **Средний** |
| **~latest** | `@~latest` | Последний стабильный релиз (исключает RC). | **Низкий** |
| **Ветка** | `@main` | Только для отладки и разработки. | **Экспериментальный** |

> **Best Practice (Безопасность):** В критических Enterprise-пайплайнах рекомендуется использовать **Commit SHA**. Теги в Git не являются неизменяемыми объектами (их можно перевесить), тогда как хеш коммита гарантирует неизменность кода компонента и защищает от атак типа Supply Chain.

**Практические рекомендации по выбору версии:**

| Сценарий | Рекомендуемый формат | Обоснование |
| :--- | :--- | :--- |
| Production пайплайны | `@1.2.0` (полный SemVer) | Гарантия воспроизводимости, защита от непреднамеренных обновлений |
| Development/testing | `@main` или `@~latest` | Быстрая итерация, доступ к последним функциям |
| Audit/compliance | `@e3262fdb...` (SHA) | Неизменность кода, защита от атак типа Supply Chain |
| CI/CD компоненты | `@1.2` (частичный SemVer) | Автоматическое получение исправлений безопасности |

### Правила разрешения версий и приоритеты

При возникновении конфликтов имен или неоднозначности GitLab следует жесткой логике:

1.  **SHA vs Тег:** Если имя тега совпадает с коротким SHA, приоритет всегда отдаётся **SHA**.
2.  **Тег vs Ветка:** При совпадении имен приоритет отдаётся **тегу**.
3.  **Логика `~latest`:** Указатель выбирает самую свежую версию, помеченную как Release, игнорируя пре-релизы (например, `1.5.0-beta.1` будет проигнорирован в пользу `1.4.9`).
4.  **Разрешение масок:** Запрос `@1.2` будет автоматически перенаправлен на самый старший патч-релиз в этой ветке (например, `1.2.8`).

**Диагностические команды для проверки версий:**

```bash
# Просмотр всех доступных версий компонента
glab api "projects/${PROJECT_ID}/ci/components" | jq '.[].version'

# Проверка конкретной версии
glab api "projects/${PROJECT_ID}/ci/components/docker-build/versions/1.2.0"

# Проверка доступности ~latest
glab api "projects/${PROJECT_ID}/ci/components/docker-build/versions/latest"

# Список всех компонентов проекта
find templates/ -name "*.yml" -exec basename {} .yml \; | sort
```

### Управление публикацией и аналитика

- **Publication Allowlist (v18.7+):** Механизм контроля качества, позволяющий администраторам ограничивать список проектов, имеющих право публиковать компоненты в корпоративный каталог. Это предотвращает захламление реестра черновиками. Настройка: `Settings -> CI/CD -> Catalog -> Publication Allowlist`.
- **Components Analytics (v19.0+):** Панель аналитики, предоставляющая данные о популярности компонентов, частоте их использования и распределении версий в организации.
- **Аудит безопасности (Ultimate):** Позволяет выгружать список всех проектов, использующих конкретную уязвимую версию компонента, для проведения массовых обновлений.

**Практическое использование аналитики:**

```bash
# Получение статистики использования компонентов
glab api "projects/${PROJECT_ID}/ci/components" | jq '{
  total: length,
  by_version: group_by(.version) | map({version: .[0].version, count: length}),
  recently_used: sort_by(.last_used_at) | reverse | .[0:5]
}'

# Экспорт данных для Prometheus
glab api "projects/${PROJECT_ID}/ci/components" | \
  jq -r '.[] | "gitlab_component_usage{component=\"\(.name)\",version=\"\(.version)\"} 1"' | \
  curl --data-binary @- -X POST http://prometheus:9091/metrics/job/gitlab_catalog
```

### Динамический выбор входных данных (18.7)

Интерфейс «Run Pipeline» поддерживает каскадные (зависимые) списки `inputs`. Значения в одном выпадающем списке могут фильтроваться на основе выбора в предыдущем, что упрощает настройку сложных систем развертывания.

**Пример реализации каскадных входов:**

```yaml
# templates/deploy.yml
spec:
  inputs:
    environment:
      description: "Целевое окружение"
      options: ["staging", "production"]
      default: "staging"
    cluster:
      description: "Кластер"
      options:
        - value: "k8s-eu"
          label: "EU Cluster"
        - value: "k8s-us"
          label: "US Cluster"
      default: "k8s-eu"
---
deploy:
  stage: deploy
  script:
    - kubectl config use-context ${ cluster }
    - helm upgrade --install app ./charts --set env=${ environment }
```

### Интерполяция контекста компонента (v18.6+)

Компоненты могут динамически адаптироваться, используя собственные метаданные. Это избавляет от необходимости пробрасывать базовые параметры (например, версию) через `inputs`.

| Поле контекста | Описание | Пример значения |
| :--- | :--- | :--- |
| **`$[[ component.name ]]`** | Техническое имя текущего компонента. | `docker-build` |
| **`$[[ component.version ]]`** | Версия (тег или SHA), указанная при вызове. | `1.5.0` |
| **`$[[ component.sha ]]`** | Полный хеш коммита (Commit SHA) данной версии. | `e3262fdb...` |

**Пример применения:** Автоматический выбор версии Docker-образа инструментов, соответствующей версии самого компонента.
```yaml
# templates/build.yml
build-job:
  image: custom-registry/tools:$[[ component.version ]]
  script:
    - run-build.sh
```

**Практический пример с мониторингом:**

```yaml
# templates/deploy.yml
spec:
  inputs:
    environment:
      description: "Целевое окружение"
      options: ["staging", "production"]
---
deploy:
  stage: deploy
  script:
    - echo "Deploying component $[[ component.name ]] v$[[ component.version ]] to ${{ environment }}"
    - |
      # Логирование для мониторинга
      curl -X POST "${METRICS_ENDPOINT}" \
        -H "Content-Type: application/json" \
        -d "{
          \"component\": \"$[[ component.name ]]\",
          \"version\": \"$[[ component.version ]]\",
          \"environment\": \"${{ environment }}\",
          \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        }"
    - kubectl apply -f manifests/
```

---

## Практические сценарии

### Сценарий 1: Валидация через CLI и API

**Инструментарий `glab`:**
Основная команда для отладки — `glab ci lint --show-expanded`. Она имитирует работу сервера GitLab и показывает итоговый YAML со всеми вложенными файлами и интерполированными параметрами.

```bash
# Проверка текущего проекта
glab ci lint

# Просмотр итогового вида пайплайна (expand)
glab ci lint --show-expanded

# Валидация компонента в контексте другого (целевого) проекта
glab ci lint --project my-org/target-app --show-expanded > processed.yml
```

**Использование API (Автоматизация):**
Метод `POST /projects/:id/ci/lint` позволяет интегрировать проверку компонентов во внешние линтеры или Git-хуки.

```bash
curl --request POST --header "PRIVATE-TOKEN: <your_token>" \
  --header "Content-Type: application/json" \
  --data '{"content": "include:\n  - component: gitlab.com/org/comp@1.0.0", "include_merged_yaml": true}' \
  "https://gitlab.example.com/api/v4/projects/<id>/ci/lint"
```

**Автоматизированный аудит всех компонентов:**

```bash
#!/bin/bash
# audit_components.sh — проверка всех компонентов каталога

GITLAB_URL="${GITLAB_URL:-https://gitlab.example.com}"
TOKEN="${GITLAB_TOKEN}"
PROJECT_ID="${CATALOG_PROJECT_ID}"

echo "=== Аудит компонентов каталога ==="

# Получение списка компонентов
COMPONENTS=$(glab api "projects/${PROJECT_ID}/ci/components" | jq -r '.[].name')

for component in ${COMPONENTS}; do
  echo "Проверка ${component}..."
  
  # Валидация через API
  RESULT=$(curl -s --request POST \
    --header "PRIVATE-TOKEN: ${TOKEN}" \
    --header "Content-Type: application/json" \
    --data "{\"content\": \"include:\\n  - component: ${GITLAB_URL}/org/catalog@main\\n    inputs:\\n      component: ${component}\"}" \
    "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/ci/lint")
  
  STATUS=$(echo "${RESULT}" | jq -r '.valid')
  
  if [ "${STATUS}" = "true" ]; then
    echo "  OK: ${component}"
  else
    echo "  ОШИБКА: ${component}"
    echo "${RESULT}" | jq -r '.errors[]'
  fi
done

echo "=== Аудит завершен ==="
```

### Сценарий 2: Автоматизация публикации (CI/CD компонента)

Для автоматического появления версии в каталоге используется задание с ключевым словом `release:`.

```yaml
create-release:
  stage: deploy
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/ # Строгий SemVer (v1.2.3)
  script:
    - echo "Validating component and creating release for $CI_COMMIT_TAG"
  release:
    tag_name: $CI_COMMIT_TAG
    name: "Release $CI_COMMIT_TAG"
    description: "Component release version $CI_COMMIT_TAG. See CHANGELOG.md for details."
```

**Расширенный пример с валидацией и уведомлениями:**

```yaml
stages:
  - validate
  - test
  - release

validate_component:
  stage: validate
  image: alpine:3.19
  before_script:
    - apk add --no-cache bash jq
  script:
    - |
      echo "=== Валидация компонента ==="
      
      # Проверка наличия spec:inputs
      if ! grep -q "spec:" templates/*.yml; then
        echo "ОШИБКА: Отсутствует секция spec:"
        exit 1
      fi
      
      # Проверка количества входов (лимит 50)
      INPUT_COUNT=$(grep -c "inputs:" templates/*.yml || echo "0")
      if [ ${INPUT_COUNT} -gt 50 ]; then
        echo "ОШИБКА: Превышен лимит входов (${INPUT_COUNT}/50)"
        exit 1
      fi
      
      echo "=== Валидация пройдена ==="
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

test_component:
  stage: test
  image: python:3.12
  before_script:
    - pip install yamllint
  script:
    - |
      echo "=== Тестирование компонентов ==="
      for component in templates/*.yml; do
        echo "Проверка ${component}..."
        yamllint -d relaxed "${component}"
        if [ $? -ne 0 ]; then
          echo "ОШИБКА: Найдены проблемы в ${component}"
          exit 1
        fi
      done
      echo "=== Все компоненты прошли тестирование ==="
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

create_release:
  stage: release
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
  script:
    - echo "Creating release for $CI_COMMIT_TAG"
  release:
    tag_name: $CI_COMMIT_TAG
    name: "Release $CI_COMMIT_TAG"
    description: |
      Component release version $CI_COMMIT_TAG
      
      ## Changes
      - See CHANGELOG.md for details
      
      ## Usage
      ```yaml
      include:
        - component: $CI_SERVER_FQDN/org/catalog@$CI_COMMIT_TAG
      ```
```

### Сценарий 3: Поиск компонентов через API

Позволяет создавать внутренние дашборды или инструменты инвентаризации.

```bash
# Получение списка всех компонентов, доступных в проекте
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<id>/ci/components" | jq '.'

# Получение метаданных конкретной версии (включая входы/inputs)
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<id>/ci/components/<name>/versions/1.0.0"
```

**Создание инвентаризационного дашборда:**

```bash
#!/bin/bash
# inventory_dashboard.sh — генерация инвентаризации компонентов

GITLAB_URL="${GITLAB_URL:-https://gitlab.example.com}"
TOKEN="${GITLAB_TOKEN}"
OUTPUT_FILE="catalog_inventory_$(date +%Y%m%d_%H%M%S).json"

echo "=== Генерация инвентаризации каталога ==="

# Сбор данных о всех компонентах
glab api "projects/${CATALOG_PROJECT_ID}/ci/components" | \
  jq '{
    generated_at: now | todate,
    total_components: length,
    components: [.[] | {
      name: .name,
      version: .version,
      created_at: .created_at,
      last_used_at: .last_used_at,
      usage_count: .usage_count
    }]
  }' > "${OUTPUT_FILE}"

echo "Инвентаризация сохранена в ${OUTPUT_FILE}"

# Генерация отчета по использованию
echo "=== Топ-10 компонентов по использованию ==="
cat "${OUTPUT_FILE}" | jq -r '.components | sort_by(.usage_count) | reverse | .[0:10] | .[] | "\(.name)@\( .version): \(.usage_count) использований"'
```

### Сценарий 4: Мониторинг использования компонентов в продакшене

Для SRE-команд критически важно отслеживать использование компонентов и их влияние на производительность CI/CD.

**Настройка метрик для Prometheus:**

```yaml
# monitoring/gitlab-component-metrics.yml
groups:
  - name: gitlab_catalog
    rules:
      - record: gitlab_component_usage_total
        expr: sum(gitlab_pipeline_component_usage) by (component, version)
      
      - record: gitlab_component_duration_seconds
        expr: histogram_quantile(0.95, sum(rate(gitlab_pipeline_component_duration_seconds_bucket[5m])) by (le, component))
      
      - alert: GitLabComponentHighUsage
        expr: gitlab_component_usage_total > 1000
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "High component usage: {{ $labels.component }}"
          description: "Component {{ $labels.component }} version {{ $labels.version }} used {{ $value }} times"
```

**Скрипт сбора метрик:**

```bash
#!/bin/bash
# collect_metrics.sh — сбор метрик использования компонентов

PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
GITLAB_URL="${GITLAB_URL:-https://gitlab.example.com}"
TOKEN="${GITLAB_TOKEN}"

# Получение статистики из GitLab API
STATS=$(glab api "projects/${CATALOG_PROJECT_ID}/ci/components" | \
  jq -r '.[] | "gitlab_component_info{component=\"\(.name)\",version=\"\(.version)\"} \(.usage_count)"')

# Отправка в Prometheus Pushgateway
echo "${STATS}" | curl --data-binary @- -X POST "${PROMETHEUS_URL}/metrics/job/gitlab_catalog"

echo "Метрики отправлены в Prometheus"
```

### Сценарий 5: Диагностика проблем с компонентами

Когда компоненты не работают корректно, необходим систематический подход к диагностике.

**Диагностический скрипт:**

```bash
#!/bin/bash
# diagnose_component.sh — диагностика проблем с конкретным компонентом

COMPONENT="${1:?Укажите имя компонента}"
VERSION="${2:-main}"
GITLAB_URL="${GITLAB_URL:-https://gitlab.example.com}"
TOKEN="${GITLAB_TOKEN}"

echo "=== Диагностика компонента ${COMPONENT}@${VERSION} ==="

# 1. Проверка доступности компONENTA
echo "1. Проверка доступности..."
COMPONENT_INFO=$(curl -s --header "PRIVATE-TOKEN: ${TOKEN}" \
  "${GITLAB_URL}/api/v4/projects/${CATALOG_PROJECT_ID}/ci/components/${COMPONENT}/versions/${VERSION}")

if echo "${COMPONENT_INFO}" | jq -e '.error' > /dev/null 2>&1; then
  echo "   ОШИБКА: Компонент не найден"
  echo "${COMPONENT_INFO}" | jq -r '.message'
  exit 1
fi

echo "   OK: Компонент доступен"

# 2. Проверка версии
echo "2. Проверка версии..."
VERSION_INFO=$(echo "${COMPONENT_INFO}" | jq -r '.version')
echo "   Версия: ${VERSION_INFO}"

# 3. Проверка inputs
echo "3. Проверка inputs..."
INPUTS=$(echo "${COMPONENT_INFO}" | jq -r '.inputs // empty')
if [ -n "${INPUTS}" ]; then
  echo "   Inputs: $(echo "${INPUTS}" | jq -r 'keys | join(", ")')"
else
  echo "   Inputs: отсутствуют"
fi

# 4. Валидация через CI Lint
echo "4. Валидация через CI Lint..."
LINT_RESULT=$(curl -s --request POST \
  --header "PRIVATE-TOKEN: ${TOKEN}" \
  --header "Content-Type: application/json" \
  --data "{\"content\": \"include:\\n  - component: ${GITLAB_URL}/org/catalog@${VERSION}\"}" \
  "${GITLAB_URL}/api/v4/projects/${CATALOG_PROJECT_ID}/ci/lint")

if echo "${LINT_RESULT}" | jq -e '.valid' > /dev/null 2>&1; then
  echo "   OK: Валидация пройдена"
else
  echo "   ОШИБКА: Валидация не пройдена"
  echo "${LINT_RESULT}" | jq -r '.errors[]'
fi

# 5. Проверка лимитов
echo "5. Проверка лимитов..."
INCLUDE_COUNT=$(echo "${LINT_RESULT}" | jq -r '.merged_yaml' | grep -c "include:" || echo "0")
echo "   Include узлов: ${INCLUDE_COUNT}/150"

if [ ${INCLUDE_COUNT} -gt 120 ]; then
  echo "   ПРЕДУПРЕЖДЕНИЕ: Приближение к лимиту include"
fi

echo "=== Диагностика завершена ==="
```

### Сценарий 6: Безопасная миграция компонентов

При обновлении компонентов необходимо обеспечить безопасность и возможность отката.

**Стратегия Canary-миграции:**

```yaml
# .gitlab-ci.yml (миграция на новую версию компонента)
stages:
  - canary
  - production

canary_deploy:
  stage: canary
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
  script:
    - |
      echo "=== Canary-развертывание ==="
      
      # Развертывание на 10% трафика
      kubectl set image deployment/app \
        app=registry.example.com/app:$CI_COMMIT_SHA \
        --subresource=scale
      
      # Мониторинг метрик
      sleep 60
      
      # Проверка ошибок
      ERROR_RATE=$(curl -s "${METRICS_URL}/api/v1/query?query=rate(http_requests_total{status=~'5..'}[5m])" | jq '.data.result[0].value[1]' -r)
      
      if (( $(echo "${ERROR_RATE} > 0.01" | bc -l) )); then
        echo "ОШИБКА: Высокий уровень ошибок (${ERROR_RATE})"
        kubectl rollout undo deployment/app
        exit 1
      fi
      
      echo "OK: Canary-развертывание успешно"

production_deploy:
  stage: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
  script:
    - |
      echo "=== Production развертывание ==="
      kubectl set image deployment/app \
        app=registry.example.com/app:$CI_COMMIT_SHA
  when: manual
```

**Откат при проблемах:**

```bash
#!/bin/bash
# rollback_component.sh — быстрый откат компонента

COMPONENT="${1:?Укажите имя компонента}"
OLD_VERSION="${2:?Укажите старую версию}"
NEW_VERSION="${3:?Укажите новую версию}"

echo "=== Откат компонента ${COMPONENT} с ${NEW_VERSION} на ${OLD_VERSION} ==="

# Поиск всех проектов, использующих компонент
PROJECTS=$(grep -r "component:.*${COMPONENT}@${NEW_VERSION}" . --include="*.yml" -l)

for project in ${PROJECTS}; do
  echo "Обновление ${project}..."
  
  # Замена версии
  sed -i "s|${COMPONENT}@${NEW_VERSION}|${COMPONENT}@${OLD_VERSION}|g" "${project}"
  
  # Коммит изменений
  git add "${project}"
  git commit -m "rollback: ${COMPONENT} ${NEW_VERSION} -> ${OLD_VERSION}"
done

echo "Откат завершен. Необходимо запушить изменения."
```

### Сценарий 7: Тестирование компонентов в CI/CD

Для обеспечения качества компонентов необходимо автоматическое тестирование.

**Пример пайплайна тестирования:**

```yaml
# .gitlab-ci.yml (в проекте каталога)
stages:
  - lint
  - unit
  - integration
  - publish

lint_components:
  stage: lint
  image: alpine:3.19
  before_script:
    - apk add --no-cache yamllint
  script:
    - |
      echo "=== Линтинг компонентов ==="
      for component in templates/*.yml; do
        echo "Проверка ${component}..."
        yamllint -d relaxed "${component}"
      done
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == "main"'

unit_tests:
  stage: unit
  image: python:3.12
  before_script:
    - pip install pytest pyyaml
  script:
    - |
      echo "=== Юнит-тесты компонентов ==="
      pytest tests/unit/ -v
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == "main"'

integration_tests:
  stage: integration
  image: alpine:3.19
  before_script:
    - apk add --no-cache bash curl jq
  script:
    - |
      echo "=== Интеграционные тесты ==="
      
      # Тест каждого компонента с various inputs
      for component in templates/*.yml; do
        COMPONENT_NAME=$(basename "${component}" .yml)
        
        echo "Тестирование ${COMPONENT_NAME}..."
        
        # Создание тестового .gitlab-ci.yml
        cat > test-ci.yml << EOF
      include:
        - component: \$CI_SERVER_FQDN/org/catalog@main
          inputs:
            component: ${COMPONENT_NAME}
      EOF
      
        # Валидация
        glab ci lint --show-expanded > /dev/null 2>&1
        if [ $? -ne 0 ]; then
          echo "ОШИБКА: Тест не пройден для ${COMPONENT_NAME}"
          exit 1
        fi
      done
      
      echo "=== Все тесты пройдены ==="
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

publish_catalog:
  stage: publish
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
  script:
    - echo "Публикация каталога"
  release:
    tag_name: $CI_COMMIT_TAG
    name: "Catalog Release $CI_COMMIT_TAG"
    description: "Automated catalog release"
```

---

## DevOps/SRE-специфичные сценарии

### Влияние компонентов на SLA/SLO

Для SRE-команд компоненты CI/CD напрямую влияют на метрики надежности:

| Метрика | Влияние компонентов | Целевое значение |
| :--- | :--- | :--- |
| **Lead Time for Changes** | Время загрузки и валидации компонентов | < 2 минуты |
| **Deployment Frequency** | Доступность компонентов для автоматизации | > 10 деплоев в день |
| **Change Failure Rate** | Качество компонентов и их тестирование | < 5% |
| **Failed Deployment Recovery Time** | Скорость отката проблемных компонентов | < 15 минут |

**Формула расчета влияния на SLA:**

```
Component Impact = (Component Load Time / Total Pipeline Time) × 100%

Если Component Impact > 20%:
  - Риск инцидента: Высокий
  - Рекомендация: Оптимизация или кэширование компонентов

Если Component Impact > 10%:
  - Риск инцидента: Средний
  - Рекомендация: Мониторинг производительности

Если Component Impact < 10%:
  - Риск инцидента: Низкий
  - Рекомендация: Продолжить мониторинг
```

### Интеграция с системами мониторинга

Для полноценного мониторинга компонентов интегрируйте GitLab CI с существующими системами:

**Prometheus + Grafana:**

```yaml
# monitoring/gitlab-component-dashboard.json
{
  "dashboard": {
    "title": "GitLab CI Component Metrics",
    "panels": [
      {
        "title": "Component Usage",
        "type": "graph",
        "targets": [{
          "expr": "sum(gitlab_component_usage_total) by (component)",
          "legendFormat": "{{component}}"
        }]
      },
      {
        "title": "Component Load Time",
        "type": "graph",
        "targets": [{
          "expr": "histogram_quantile(0.95, sum(rate(gitlab_component_duration_seconds_bucket[5m])) by (le, component))",
          "legendFormat": "{{component}} p95"
        }]
      }
    ]
  }
}
```

**Alertmanager правила:**

```yaml
# prometheus/alerts/gitlab-component-alerts.yml
groups:
  - name: gitlab-components
    rules:
      - alert: GitLabComponentHighLoadTime
        expr: histogram_quantile(0.95, sum(rate(gitlab_component_duration_seconds_bucket[5m])) by (le, component)) > 30
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High component load time: {{ $labels.component }}"
          description: "Component {{ $labels.component }} takes {{ $value }}s to load"

      - alert: GitLabComponentNotFound
        expr: gitlab_component_usage_total == 0
        for: 24h
        labels:
          severity: info
        annotations:
          summary: "Unused component: {{ $labels.component }}"
          description: "Component {{ $labels.component }} not used for 24 hours"
```

### Стратегия реагирования на инциденты

При проблемах с компонентами необходим формализованный процесс реагирования:

**Уровень 1: Автоматическое реагирование**
```bash
#!/bin/bash
# incident_response.sh — автоматическое реагирование на инциденты

COMPONENT="${1:?Укажите имя компонента}"
ERROR_TYPE="${2:?Укажите тип ошибки}"

case ${ERROR_TYPE} in
  "load_failure")
    echo "=== Реагирование на сбой загрузки ==="
    
    # 1. Уведомление в Slack
    curl -X POST "${SLACK_WEBHOOK}" \
      -H 'Content-type: application/json' \
      -d "{\"text\":\"CRITICAL: Component ${COMPONENT} failed to load\"}"
    
    # 2. Автоматический откат (если возможно)
    if [ -f "rollback.sh" ]; then
      ./rollback.sh "${COMPONENT}"
    fi
    ;;
    
  "validation_error")
    echo "=== Реагирование на ошибку валидации ==="
    
    # 1. Логирование ошибки
    echo "$(date): Validation error for ${COMPONENT}" >> /var/log/component-errors.log
    
    # 2. Уведомление команды
    curl -X POST "${SLACK_WEBHOOK}" \
      -H 'Content-type: application/json' \
      -d "{\"text\":\"WARNING: Component ${COMPONENT} validation error\"}"
    ;;
    
  *)
    echo "Неизвестный тип ошибки: ${ERROR_TYPE}"
    exit 1
    ;;
esac
```

**Уровень 2: Ручное вмешательство**
1. Приоритизация компонентов по критичности
2. Анализ логов и метрик
3. Применение исправлений или откат

**Уровень 3: Стратегическое масштабирование**
1. Разработка плана улучшения компонентов
2. Внедрение дополнительного тестирования
3. Оптимизация производительности

### Чек-листы

#### Чек-лист публикации компонента

- [ ] Секция `spec:inputs` заполнена и синтаксически верна
- [ ] Добавлена валидация через `regex` или `options` для критических параметров
- [ ] Каждый `input` имеет поле `description`
- [ ] Компонент прошёл проверку через `glab ci lint --show-expanded`
- [ ] Проект помечен как «Catalog resource»
- [ ] Создан релиз с тегом SemVer (например, `v1.0.0`)
- [ ] README.md содержит документацию по использованию
- [ ] Добавлены тесты в директорию `tests/`
- [ ] Проверены все внутренние ссылки

#### Чек-лист мониторинга компонентов

- [ ] Настроен Prometheus/Grafana для метрик компонентов
- [ ] Настроены алерты при превышении порогов производительности
- [ ] Регулярный аудит использования компонентов
- [ ] Документированный процесс реагирования на инциденты
- [ ] Обучение команд использованию инструментов мониторинга

#### Чек-лист безопасности компонентов

- [ ] Используется Commit SHA для критических компонентов
- [ ] Настроен Publication Allowlist
- [ ] Регулярный аудит уязвимостей
- [ ] Проверка Supply Chain безопасности
- [ ] Логирование всех изменений версий

---

## Дополнительная информация

### Сводная таблица инструментов

| Инструмент | Команда / Эндпоинт | Назначение |
| :--- | :--- | :--- |
| **API** | `GET /projects/:id/ci/components` | Инвентаризация компонентов проекта. |
| **API** | `POST /projects/:id/ci/lint` | Глубокая валидация с раскрытием (expand). |
| **CLI** | `glab ci lint` | Быстрая проверка синтаксиса и интерполяции. |
| **Git** | `git tag -a v1.0.0` | Фиксация версии для публикации в каталоге. |
| **Monitoring** | Prometheus/Grafana | Мониторинг использования и производительности. |
| **Security** | GitLab Ultimate | Аудит безопасности и Supply Chain. |

### Диагностические команды

```bash
# Быстрая диагностика компонентов
echo "=== Диагностика компонентов ==="

# 1. Проверка доступности компонентов
glab api "projects/${PROJECT_ID}/ci/components" | jq '.[].name'

# 2. Проверка версий
glab api "projects/${PROJECT_ID}/ci/components" | jq '.[].version'

# 3. Валидация через glab
glab ci lint --show-expanded > /dev/null 2>&1
if [ $? -eq 0 ]; then
  echo "Статус: OK"
else
  echo "Статус: ОШИБКА"
fi

# 4. Проверка лимитов
COMPONENT_COUNT=$(find templates/ -name "*.yml" | wc -l)
echo "Компонентов: ${COMPONENT_COUNT}/100"

# 5. Проверка размера YAML
YAML_SIZE=$(du -sh . | cut -f1)
echo "Размер: ${YAML_SIZE}"
```

### История ключевых изменений

| Версия GitLab | Изменение / Статус |
| :--- | :--- |
| **16.10** | SemVer стал обязательным требованием для публикации в каталоге. |
| **17.0** | Статус General Availability (GA). Лимит размера YAML увеличен до 5 МБ. |
| **18.6** | Добавлена интерполяция контекста через `$[[ component.* ]]`. |
| **18.7** | Статус GA для контекстной интерполяции, Publication Allowlist и каскадные формы. |
| **19.0** | Запуск аналитики (Components Analytics) и фиксация неизменности входов. |

### Типичные ошибки и способы решения

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Spec must be a valid json schema` | Нарушение синтаксиса в блоке `spec:inputs`. | Проверьте отступы и наличие двоеточий. Инпуты должны быть списком объектов. |
| `Component content not found` | Неверный путь, отсутствие тега или нет прав. | Проверьте `Visibility` репозитория и правильность пути в `include:component`. |
| `Regex validation failed` | Инпут не соответствует регулярному выражению. | Сверьте передаваемое значение с полем `regex` в файле компонента. |
| `Input type mismatch` | Несоответствие типов (например, строка вместо числа). | Убедитесь, что типы в `inputs` и `spec` совпадают (string, number, boolean). |
| `Component load timeout` | Превышение времени загрузки компонента. | Проверьте сетевую доступность и размер компонента. Рассмотрите кэширование. |
| `Version conflict` | Конфликт версий при резолвинге. | Используйте полные SemVer версии вместо частичных. |

### Смотрите также

- **[GitLab CI: Каталог компонентов](./ci_cd_catalog_components.md)** — архитектура, типы и `spec:inputs`.
- **[Ограничения каталога компонентов](./ci_cd_catalog_limits.md)** — системные лимиты и запрещенные ключи.
- **[Продвинутые сценарии использования](./ci_cd_catalog_advanced_scenarios.md)** — цепочки компонентов и стратегии миграции.
