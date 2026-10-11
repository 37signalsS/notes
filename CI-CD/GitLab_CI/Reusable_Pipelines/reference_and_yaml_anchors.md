# GitLab CI: Механизмы !reference и якоря YAML

**Актуально для:** GitLab CI 19.x

## Определения

**`!reference`** — специализированный технический тег GitLab CI, предназначенный для создания явных ссылок на фрагменты конфигурации других заданий или глобальных секций. Этот механизм позволяет извлекать и вставлять части настроек (`script`, `rules`, `variables`, `tags` и др.) с сохранением возможности глубокой валидации. Работает как внутри одного файла, так и между ресурсами, подключенными через `include`.

**Якорь YAML (YAML Anchor, `&`)** — стандартный механизм языка YAML для маркировки блока данных с целью его последующего многократного использования в рамках одного документа.

**Ссылка YAML (YAML Alias, `*`)** — механизм подстановки содержимого, ранее помеченного якорем.

**Скрытое задание (Hidden Job)** — задание, имя которого начинается с точки (например, `.base_script`). Такие задания игнорируются планировщиком GitLab и служат исключительно контейнерами (шаблонами) для хранения переиспользуемых фрагментов кода.

**Merge Key (`<<`)** — оператор YAML для слияния словарей (maps). Позволяет включить содержимое якоря в другой словарь, дополняя или перезаписывая ключи.

**Lazy Resolution (Ленивое разрешение)** — стратегия отложенной обработки тегов `!reference`, при которой ссылки разрешаются на финальном этапе компиляции пайплайна, а не при парсинге YAML.

## Основные концепции

### Сравнение механизмов переиспользования

Хотя оба инструмента служат для минимизации дублирования кода (принцип DRY), GitLab рекомендует использовать `!reference` в качестве основного стандарта из-за его интеграции в экосистему CI/CD.

| Критерий | `!reference` | Якоря YAML (`&`) / Ссылки (`*`) |
| :--- | :--- | :--- |
| **Уровень обработки** | Компилятор GitLab CI | Парсер YAML (самый ранний этап) |
| **Межфайловые ссылки** | **Да** (поддерживает `include`) | Нет (только внутри одного файла) |
| **Валидация Lint** | Полная поддержка структуры | Только синтаксис YAML |
| **Гибкость** | Доступ к индексам массивов | Только вставка блока целиком |
| **Резолюция** | Ленивое разрешение (Lazy) | Статическое разрешение |
| **Рекомендация** | Основной инструмент | Для локальных словарей (Merge Key) |
| **Вложенность** | До 10 уровней | Не ограничено (парсер YAML) |
| **Типы данных** | Скаляры, массивы, словари | Только блоки (массивы/словари) |

### Механика работы `!reference` и Lazy Resolution

В современных версиях GitLab (17.x+) механизмы `!reference` разрешаются на финальном этапе компиляции пайплайна. Это обеспечивает «ленивое разрешение»: вы можете ссылаться на задание, которое определено в файле, импортируемом в самом конце секции `include`.

**Порядок разрешения в GitLab CI:**
1. Парсинг YAML
2. Обработка `include`
3. Разрешение `inputs` (интерполяция)
4. Обработка `variables`
5. Разрешение `extends` (слияние структур)
6. **Разрешение `!reference`** (вставка фрагментов кода)

**Важное ограничение:** Теги `!reference` не поддерживают интерполяцию `inputs` (например, `$[[ inputs.name ]]`). Если вам нужно передать параметры в блок кода, используйте [CI/CD Components](./ci_cd_catalog_components.md).

### Синтаксис якорей и механизм слияния (Merge Key)

Якоря YAML работают на уровне парсера. Ссылка (`*`) технически не может быть использована в тексте выше, чем определен сам Якорь (`&`). Для объединения словарей используется оператор слияния `<<:`.

**Типы слияния:**

| Тип | Описание | Пример |
| :--- | :--- | :--- |
| **Shallow merge** | Поверхностное слияние (один уровень) | `<<: *anchor` |
| **Deep merge** | Глубокое слияние (вложенные ключи) | Требует явного указания вложенных ключей |
| **Replace** | Полная замена ключа | Ключ в дочернем блоке перезаписывает родительский |

**Важно:** Массивы (`script`, `rules`, `tags`) при слиянии **полностью заменяются**, а не дополняются. Для конкатенации массивов используйте `!reference`.

### Механизм `!reference` vs `extends` vs YAML Anchors

| Сценарий | Рекомендуемый механизм | Причина |
| :--- | :--- | :--- |
| Наследование всего задания | `extends` | Полная поддержка GitLab, ленивое разрешение |
| Вставка фрагмента скрипта | `!reference` | Точечная вставка без замены массива |
| Локальный словарь переменных | YAML Anchors (`<<:`) | Простое слияние в пределах файла |
| Межфайловые ссылки | `!reference` | Единственный механизм для межфайловых ссылок |
| Конкатенация массивов | `!reference` | `extends` заменяет массивы, не дополняет |

## Практические сценарии

### Предварительные условия

1. GitLab версии 14.3+ (для базового `!reference`) или 17.2+ (для доступа к индексам массивов).
2. Наличие прав на чтение репозиториев, если используются ссылки на внешние `include`.

### Сценарий 1: Атомарное переиспользование скриптов через !reference

Позволяет создавать библиотеки общих Bash-команд, которые можно вставлять в любую часть секции `script`, не перезаписывая её целиком (в отличие от `extends`).

```yaml
# templates/common.yml
.setup_registry:
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY

# .gitlab-ci.yml
build_image:
  stage: build
  script:
    - !reference [.setup_registry, script]
    - docker build -t $IMG_NAME .
```

**Диагностическая команда:**

```bash
# Просмотр результата вставки
glab ci config compile | grep -A 10 "build_image"
```

### Сценарий 2: Использование индексов массивов (v17.2+)

Уникальная возможность `!reference`, позволяющая извлекать конкретные элементы из списков тегов или образов.

```yaml
.runner_pool:
  tags: [docker, high-cpu, gpu-tesla-v100]

ml_training:
  tags:
    - !reference [.runner_pool, tags, 2] # Выберет только "gpu-tesla-v100"
  script:
    - python train.py
```

**Практический пример для DevOps/SRE:**

```yaml
# Шаблоны для различных окружений
.runner_eu:
  tags: [eu-runner, docker, high-memory]

.runner_us:
  tags: [us-runner, docker, high-memory]

# Использование конкретного тега
deploy_eu:
  tags:
    - !reference [.runner_eu, tags, 0] # "eu-runner"
  script:
    - ./deploy.sh --region=eu
```

### Сценарий 3: Централизованное управление правилами (rules)

Позволяет избежать дублирования длинных списков условий в сложных пайплайнах.

```yaml
.production_rules:
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      when: manual
    - if: '$CI_COMMIT_TAG'

deploy_app:
  stage: deploy
  rules:
    - !reference [.production_rules, rules]
  script:
    - ./deploy.sh
```

**Расширенный пример для multi-environment:**

```yaml
.staging_rules:
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'
      when: manual
    - if: '$CI_COMMIT_BRANCH == "staging"'
      when: on_success

.production_rules:
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
      when: on_success

deploy_staging:
  stage: deploy
  environment: staging
  rules:
    - !reference [.staging_rules, rules]
  script:
    - ./deploy.sh staging

deploy_production:
  stage: deploy
  environment: production
  rules:
    - !reference [.production_rules, rules]
  script:
    - ./deploy.sh production
```

### Сценарий 4: Слияние словарей через Merge Key (YAML Anchors)

Этот метод остается предпочтительным для управления конфигурациями переменных, где нужно дополнить базовый набор значений.

```yaml
.db_base_env: &db_vars
  variables:
    POSTGRES_DB: "app_db"
    POSTGRES_USER: "postgres"

test_db:
  variables:
    <<: *db_vars
    POSTGRES_PASSWORD: "password123" # Дополнение словаря
```

**DevOps/SRE пример с секретами:**

```yaml
.base_secrets: &base_secrets
  variables:
    DB_HOST: "db.internal.example.com"
    DB_PORT: "5432"
    LOG_LEVEL: "info"

staging_config:
  variables:
    <<: *base_secrets
    DB_NAME: "app_staging"
    DEBUG: "true"

production_config:
  variables:
    <<: *base_secrets
    DB_NAME: "app_production"
    DEBUG: "false"
```

### Сценарий 5: Совместное использование с extends

Паттерн «Гибрид»: `extends` задает архитектуру задания, а `!reference` впрыскивает специфичную логику.

```yaml
.base_job:
  interruptible: true
  retry: 2

.cleanup_script:
  - rm -rf /tmp/build-cache

job_with_cleanup:
  extends: .base_job
  script:
    - ./run.sh
  after_script:
    - !reference [.cleanup_script]
```

### Сценарий 6: Межфайловые ссылки с include

Комбинация `include` и `!reference` для создания модульной архитектуры.

```yaml
# .gitlab-ci.yml
include:
  - local: 'templates/common.yml'
  - local: 'templates/deploy.yml'

build_app:
  stage: build
  script:
    - !reference [.setup_registry, script]
    - !reference [.common_build_commands, script]
    - docker build -t $APP_IMAGE .

deploy_staging:
  stage: deploy
  script:
    - !reference [.deploy_script, script]
    - ./deploy.sh staging
  rules:
    - !reference [.deploy_rules, rules]
```

### Сценарий 7: Динамические переменные через Merge Key

Использование YAML Anchors для динамического управления переменными в разных окружениях.

```yaml
.base_env: &base_env
  variables:
    APP_ENV: "production"
    LOG_LEVEL: "info"
    METRICS_ENABLED: "true"

.monitoring_vars: &monitoring
  variables:
    PROMETHEUS_URL: "http://prometheus.internal:9090"
    GRAFANA_URL: "http://grafana.internal:3000"

staging:
  variables:
    <<: *base_env
    <<: *monitoring
    APP_ENV: "staging"
    DEBUG: "true"

production:
  variables:
    <<: *base_env
    <<: *monitoring
    APP_ENV: "production"
    DEBUG: "false"
```

---

## DevOps/SRE-специфичные сценарии

### Интеграция с мониторингом и алертингом

Для SRE-команд критично отслеживать использование компонентов и их влияние на инфраструктуру.

**Сбор метрик использования `!reference`:**

```yaml
# templates/metrics.yml
.metrics_script:
  script:
    - |
      METRICS=$(cat <<EOF
      gitlab_ci_reference_usage{
        component="$[[ component.name ]]",
        version="$[[ component.version ]]",
        job="$CI_JOB_NAME",
        project="$CI_PROJECT_PATH"
      } 1
      EOF
      )
      echo "${METRICS}" | curl --data-binary @- \
        -X POST "${PROMETHEUS_PUSHGATEWAY}/metrics/job/gitlab_ci"

# Использование в задании
build_with_metrics:
  stage: build
  script:
    - !reference [.metrics_script, script]
    - docker build -t $IMAGE .
```

**Интеграция с Alertmanager:**

```yaml
# templates/alerts.yml
.alert_on_failure:
  script:
    - |
      if [ "$CI_JOB_STATUS" == "failed" ]; then
        curl -X POST "${ALERTMANAGER_URL}/api/v1/alerts" \
          -H "Content-Type: application/json" \
          -d "[{
            \"labels\": {
              \"alertname\": \"CIFailure\",
              \"severity\": \"critical\",
              \"job\": \"${CI_JOB_NAME}\",
              \"project\": \"${CI_PROJECT_PATH}\"
            },
            \"annotations\": {
              \"summary\": \"CI pipeline failed for ${CI_PROJECT_NAME}\",
              \"description\": \"Job ${CI_JOB_NAME} failed in pipeline ${CI_PIPELINE_ID}\"
            }
          }]"
      fi

deploy_production:
  stage: deploy
  after_script:
    - !reference [.alert_on_failure, script]
  script:
    - ./deploy.sh production
```

### Инцидент-менеджмент и ответ на сбои

Стандартизированный процесс реагирования на инциденты, связанные с конфигурацией CI/CD.

**Автоматическое логирование инцидентов:**

```yaml
# templates/incident_response.yml
.log_incident:
  script:
    - |
      INCIDENT_ID=$(date +%s)-${CI_PIPELINE_ID}
      echo "=== Incident ${INCIDENT_ID} ==="
      echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
      echo "Project: ${CI_PROJECT_PATH}"
      echo "Pipeline: ${CI_PIPELINE_ID}"
      echo "Job: ${CI_JOB_NAME}"
      echo "Status: ${CI_JOB_STATUS}"
      echo "Commit: ${CI_COMMIT_SHA}"
      echo "=========================="
      
      # Логирование в файл
      echo "${INCIDENT_ID}: ${CI_JOB_STATUS} - ${CI_PROJECT_PATH}#${CI_PIPELINE_ID}" \
        >> /var/log/ci-incidents.log
      
      # Уведомление в Slack
      curl -X POST "${SLACK_WEBHOOK}" \
        -H 'Content-type: application/json' \
        -d "{\"text\":\"Incident ${INCIDENT_ID}: ${CI_JOB_STATUS} in ${CI_PROJECT_PATH}\"}"

failed_job:
  stage: .post
  when: on_failure
  script:
    - !reference [.log_incident, script]
  rules:
    - if: '$CI_JOB_STATUS == "failed"'
```

**Скрипт диагностики инцидента:**

```bash
#!/bin/bash
# diagnose_incident.sh — диагностика проблем с CI/CD

PIPELINE_ID="${1:?Укажите ID пайплайна}"
GITLAB_URL="${GITLAB_URL:-https://gitlab.example.com}"
TOKEN="${GITLAB_TOKEN}"

echo "=== Диагностика пайплайна ${PIPELINE_ID} ==="

# 1. Получение информации о пайплайне
echo "1. Информация о пайплайне..."
PIPELINE_INFO=$(curl -s --header "PRIVATE-TOKEN: ${TOKEN}" \
  "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/pipelines/${PIPELINE_ID}")

STATUS=$(echo "${PIPELINE_INFO}" | jq -r '.status')
echo "   Статус: ${STATUS}"

# 2. Поиск failed jobs
echo "2. Поиск failed jobs..."
FAILED_JOBS=$(curl -s --header "PRIVATE-TOKEN: ${TOKEN}" \
  "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/pipelines/${PIPELINE_ID}/jobs?scope=failed")

FAILED_COUNT=$(echo "${FAILED_JOBS}" | jq 'length')
echo "   Количество failed jobs: ${FAILED_COUNT}"

if [ ${FAILED_COUNT} -gt 0 ]; then
  echo "   Список failed jobs:"
  echo "${FAILED_JOBS}" | jq -r '.[] | "   - \(.name) (id: \(.id))"'
fi

# 3. Анализ логов failed job
if [ ${FAILED_JOBS} != "[]" ]; then
  FIRST_FAILED_JOB=$(echo "${FAILED_JOBS}" | jq -r '.[0].id')
  echo "3. Анализ логов job ${FIRST_FAILED_JOB}..."
  
  LOGS=$(curl -s --header "PRIVATE-TOKEN: ${TOKEN}" \
    "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/jobs/${FIRST_FAILED_JOB}/trace")
  
  echo "${LOGS}" | tail -20
fi

echo "=== Диагностика завершена ==="
```

### Тестирование конфигурации CI/CD

Автоматическое тестирование изменений в конфигурации перед деплоем.

**Пайплайн тестирования конфигурации:**

```yaml
# .gitlab-ci.yml (тестирование изменений)
stages:
  - validate
  - test
  - deploy

validate_yaml:
  stage: validate
  image: alpine:3.19
  before_script:
    - apk add --no-cache yamllint
  script:
    - |
      echo "=== Валидация YAML ==="
      yamllint -d relaxed .gitlab-ci.yml
      yamllint -d relaxed templates/*.yml
      
      # Проверка синтаксиса !reference
      for file in templates/*.yml; do
        echo "Проверка ${file}..."
        grep -n "!reference" "${file}" | while read -r line; do
          echo "  Найдена ссылка: ${line}"
        done
      done
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

test_references:
  stage: test
  image: alpine:3.19
  script:
    - |
      echo "=== Тестирование !reference ==="
      
      # Проверка доступности всех якорей
      for file in templates/*.yml; do
        ANCHORS=$(grep -oP '&\K[a-zA-Z0-9_-]+' "${file}" | sort -u)
        for anchor in ${ANCHORS}; do
          echo "Проверка якоря ${anchor} в ${file}..."
          
          # Проверка использования
          USAGE_COUNT=$(grep -c "\*${anchor}" "${file}" || echo "0")
          if [ ${USAGE_COUNT} -eq 0 ]; then
            echo "  ПРЕДУПРЕЖДЕНИЕ: Якорь ${anchor} не используется"
          fi
        done
      done
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

lint_expanded:
  stage: test
  image: alpine:3.19
  script:
    - |
      echo "=== Просмотр расширенного YAML ==="
glab ci config compile > expanded.yml
      
      # Проверка отсутствия ошибок
      if grep -q "error" expanded.yml; then
        echo "ОШИБКА: Найдены ошибки в expanded YAML"
        cat expanded.yml
        exit 1
      fi
      
      echo "OK: Expanded YAML валиден"
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

### Управление версиями конфигурации

Стратегии версионирования для конфигураций CI/CD.

**Семантическое версионирование (SemVer):**

```yaml
# templates/versioning.yml
.version_rules:
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
      when: on_success
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual

tag_release:
  stage: release
  rules:
    - !reference [.version_rules, rules]
  script:
    - |
      echo "=== Публикация версии ==="
      
      # Извлечение версии из тега
      VERSION=${CI_COMMIT_TAG#v}
      
      # Обновление версии в package.json (если есть)
      if [ -f "package.json" ]; then
        jq --arg ver "${VERSION}" '.version = $ver' package.json > tmp.json
        mv tmp.json package.json
        git add package.json
        git commit -m "chore: update version to ${VERSION}"
        git push
      fi
      
      # Публикация в каталоге компонентов
      curl --request POST \
        --header "PRIVATE-TOKEN: ${TOKEN}" \
        --data "version=${VERSION}" \
        "${GITLAB_URL}/api/v4/projects/${CATALOG_PROJECT_ID}/ci/components"
```

**Автоматическое версионирование:**

```bash
#!/bin/bash
# auto_version.sh — автоматическое определение версии

LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
echo "Последний тег: ${LAST_TAG}"

# Определение типа изменения
if git log ${LAST_TAG}..HEAD --oneline | grep -q "BREAKING CHANGE"; then
  TYPE="major"
elif git log ${LAST_TAG}..HEAD --oneline | grep -q "feat:"; then
  TYPE="minor"
else
  TYPE="patch"
fi

# Вычисление новой версии
IFS='.' read -r MAJOR MINOR PATCH <<< "${LAST_TAG#v}"
case ${TYPE} in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
esac

NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH}"
echo "Новая версия: ${NEW_VERSION}"

# Создание тега
git tag -a "${NEW_VERSION}" -m "Release ${NEW_VERSION}"
git push origin "${NEW_VERSION}"
```

---

## Безопасность

### Supply Chain Security для конфигураций

Защита целостности конфигураций CI/CD критична для предотвращения атак.

**Верификация целостности файлов:**

```yaml
# templates/security.yml
.verify_integrity:
  script:
    - |
      echo "=== Верификация целостности ==="
      
      # Проверка checksum критических файлов
      EXPECTED_CHECKSUMS="templates/checksums.sha256"
      
      if [ -f "${EXPECTED_CHECKSUMS}" ]; then
        sha256sum -c "${EXPECTED_CHECKSUMS}"
        if [ $? -ne 0 ]; then
          echo "ОШИБКА: Целостность файлов нарушена!"
          exit 1
        fi
      fi
      
      # Проверка подписи Git
      git verify-commit HEAD 2>/dev/null || \
        echo "ПРЕДУПРЕЖДЕНИЕ: Коммит не подписан"

security_scan:
  stage: test
  script:
    - !reference [.verify_integrity, script]
    - ./run-security-scan.sh
```

**Аудит доступа к конфигурациям:**

```yaml
# templates/audit.yml
.audit_access:
  script:
    - |
      AUDIT_LOG="/var/log/ci-config-audit.log"
      
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) | $(whoami) | ${CI_PROJECT_PATH} | ${CI_JOB_NAME} | ${CI_COMMIT_SHA}" \
        >> "${AUDIT_LOG}"
      
      # Отправка в SIEM
      curl -X POST "${SIEM_ENDPOINT}/api/v1/events" \
        -H "Content-Type: application/json" \
        -d "{
          \"event_type\": \"ci_config_access\",
          \"user\": \"$(whoami)\",
          \"project\": \"${CI_PROJECT_PATH}\",
          \"commit\": \"${CI_COMMIT_SHA}\",
          \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        }"

protected_deploy:
  stage: deploy
  script:
    - !reference [.audit_access, script]
    - ./deploy.sh
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

### OIDC аутентификация для конфигураций

Для безопасного доступа к внешним сервисам используйте `id_tokens`:

```yaml
# templates/oidc.yml
.secure_access:
  id_tokens:
    CI_ID_TOKEN:
      aud: "https://gitlab.example.com"
    VAULT_TOKEN:
      aud: "https://vault.internal:8200"
  script:
    - |
      echo "=== Безопасный доступ через OIDC ==="
      
      # Получение секретов из Vault
      SECRETS=$(curl -s \
        --header "X-Vault-Token: ${VAULT_TOKEN}" \
        "${VAULT_URL}/v1/secret/data/ci/${CI_PROJECT_PATH}")
      
      export DB_PASSWORD=$(echo "${SECRETS}" | jq -r '.data.data.db_password')
      export API_KEY=$(echo "${SECRETS}" | jq -r '.data.data.api_key')

deploy_secure:
  stage: deploy
  script:
    - !reference [.secure_access, script]
    - ./deploy.sh
```

---

## Диагностика и отладка

### Инструменты проверки

1.  **GitLab CLI (`glab`)**:
    ```bash
    # Просмотр финального YAML со всеми разрешенными ссылками
glab ci config compile
    ```
2.  **Pipeline Editor**: Вкладка «View merged YAML» в интерфейсе GitLab — лучший способ увидеть результат работы `!reference`.
3.  **Диагностический скрипт**:

```bash
#!/bin/bash
# diagnose_references.sh — диагностика проблем с !reference

echo "=== Диагностика !reference ==="

# 1. Проверка синтаксиса
echo "1. Проверка синтаксиса..."
if ! glab ci lint > /dev/null 2>&1; then
  echo "   ОШИБКА: Синтаксическая ошибка"
  glab ci lint
  exit 1
fi
echo "   OK: Синтаксис валиден"

# 2. Просмотр expanded YAML
echo "2. Просмотр expanded YAML..."
glab ci config compile > expanded.yml

# 3. Поиск не разрешенных ссылок
echo "3. Поиск не разрешенных ссылок..."
UNRESOLVED=$(grep -n "!reference" expanded.yml || echo "")
if [ -n "${UNRESOLVED}" ]; then
  echo "   ПРЕДУПРЕЖДЕНИЕ: Найдены неразрешенные ссылки:"
  echo "${UNRESOLVED}"
else
  echo "   OK: Все ссылки разрешены"
fi

# 4. Проверка глубины вложенности
echo "4. Проверка глубины вложенности..."
MAX_DEPTH=$(awk '/!reference/{depth=0; for(i=1;i<=length($0);i++) if(substr($0,i,1)=="[") depth++; if(depth>max) max=depth} END{print max}' expanded.yml)
echo "   Максимальная глубина: ${MAX_DEPTH}"
if [ ${MAX_DEPTH:-0} -gt 8 ]; then
  echo "   ПРЕДУПРЕЖДЕНИЕ: Приближение к лимиту вложенности (10)"
fi

# 5. Проверка межфайловых ссылок
echo "5. Проверка межфайловых ссылок..."
for ref in $(grep -oP '!\[.*?\]' expanded.yml | sort -u); do
  JOB_NAME=$(echo "${ref}" | grep -oP '\[\.\K[^,\]]+')
  if ! grep -q "\.${JOB_NAME}:" expanded.yml; then
    echo "   ОШИБКА: Задание .${JOB_NAME} не найдено"
  fi
done

echo "=== Диагностика завершена ==="
```

### Сводная таблица типичных ошибок

| Ошибка | Причина | Способ решения |
| :--- | :--- | :--- |
| `unknown anchor` | Ссылка на якорь в другом файле или выше определения. | Используйте `!reference` для межфайловых ссылок. Проверьте порядок строк для якорей. |
| `circular reference` | Кольцевая зависимость (А ссылается на Б, Б на А). | Разорвите цикл в иерархии ссылок. |
| `must be an array` | Неверный синтаксис аргументов `!reference`. | Убедитесь, что аргументы указаны в квадратных скобках: `[job, key]`. |
| `not found in ...` | Указанный ключ отсутствует в целевом задании. | Проверьте наличие ключа (например, `script`) в задании-источнике. |
| `nesting depth exceeded` | Превышена глубина вложенности (10 уровней). | Рефакторинг конфигурации, уменьшение вложенности. |
| `reference not resolved` | Ссылка не может быть разрешена (отсутствует задание). | Проверьте имя задания и убедитесь, что оно определено. |

## Особенности и ограничения

- **Лимит вложенности:** Глубина вложенных тегов `!reference` ограничена **10 уровнями**.
- **Типы данных:** `!reference` может возвращать как скаляры (строки), так и сложные объекты (массивы, словари).
- **Скрытие логики:** При использовании `!reference` в `before_script` или `after_script`, команды из ссылки будут отображаться в логах пайплайна как обычные шаги.
- **Производительность:** Использование большого количества `!reference` может увеличить время компиляции пайплайна. Рекомендуется не более 50 ссылок на файл.
- **Валидация:** `!reference` не валидирует содержимое на этапе парсинга — ошибки обнаруживаются только при компиляции.

---

## DevOps/SRE Best Practices

### Стандарты кодирования

1. **Именование скрытых заданий:** Используйте префикс `.` и осмысленные имена (`.setup_docker`, `.deploy_production`).
2. **Группировка:** Объединяйте связанные якоря в отдельные файлы (`.variables.yml`, `.rules.yml`, `.scripts.yml`).
3. **Документация:** Добавляйте комментарии к каждому якорю, объясняя его назначение.

### Мониторинг производительности

```yaml
# templates/performance.yml
.measure_time:
  script:
    - |
      START_TIME=$(date +%s)
      
      # Основная логика
      "$@"
      
      END_TIME=$(date +%s)
      DURATION=$((END_TIME - START_TIME))
      
      # Логирование метрик
      echo "job_duration_seconds{job=\"${CI_JOB_NAME}\"} ${DURATION}" \
        >> /tmp/metrics.prom
      
      # Отправка в Pushgateway
      curl --data-binary @/tmp/metrics.prom \
        "${PROMETHEUS_PUSHGATEWAY}/metrics/job/${CI_JOB_NAME}"
```

### Комбинация !reference с extends для сервисов и обработки ошибок

Массивы `services`, `script`, `retry`, `allow_failure` и `when` **полностью замещаются** при `extends`. Для частичного дополнения используйте `!reference`:

```yaml
# templates/base.yml
.base-test:
  services:
    - name: postgres:18
      alias: db
  retry:
    max: 2
    when: runner_system_failure
  script:
    - npm test

# Дочернее задание: добавляем сервис без потери родительского
integration-tests:
  extends: .base-test
  services:
    - !reference [.base-test, services]
    - name: redis:7-alpine
      alias: cache
  retry:
    max: !reference [.base-test, retry, max]
    when: !reference [.base-test, retry, when]
  script:
    - !reference [.base-test, script]
    - npm run test:integration
```

### Управление техническим долгом

| Проблема | Решение | Приоритет |
| :--- | :--- | :--- |
| Дублирование скриптов | Вынести в `!reference` | Высокий |
| YAML Anchors между файлами | Заменить на `!reference` | Высокий |
| Глубокая вложенность | Рефакторинг, разделение | Средний |
| Отсутствие тестов | Добавить интеграционные тесты | Средний |
| Нет документации | Добавить README и комментарии | Низкий |

### Чек-лист ревью конфигурации

- [ ] Все `!reference` корректно разрешаются (`glab ci config compile`)
- [ ] Нет циклических зависимостей
- [ ] Якоря YAML не используются между файлами
- [ ] Скрытые задания задокументированы
- [ ] Добавлены интеграционные тесты
- [ ] Проверена безопасность (нет секретов в YAML)
- [ ] Оптимизировано количество ссылок (< 50 на файл)

---

## Восстановление и очистка

### Откат изменений в конфигурации

При проблемах с `!reference` после деплоя конфигурации выполните откат на последний рабочий коммит:

```bash
# 1. Определение последнего рабочего коммита
LAST_GOOD=$(git log --oneline --grep="ci: !reference refactor" -n 1 --format="%H")

# 2. Откат .gitlab-ci.yml и шаблонов
git revert --no-commit ${LAST_GOOD} -- .gitlab-ci.yml templates/
git commit -m "revert: rollback !reference changes"
git push origin main

# 3. Верификация
glab ci config compile > expanded.yml
grep -q "!reference" expanded.yml && echo "WARNING: !reference still present" || echo "OK: !reference removed"
```

### Очистка неиспользуемых якорей

Регулярно удаляйте неиспользуемые якоря YAML, чтобы снизить технический долг:

```bash
#!/bin/bash
# cleanup_unused_anchors.sh

for file in templates/*.yml; do
  echo "Проверка ${file}..."
  
  # Извлечение всех якорей
  ANCHORS=$(grep -oP '&\K[a-zA-Z0-9_-]+' "${file}" | sort -u)
  
  for anchor in ${ANCHORS}; do
    # Проверка использования
    USAGE_COUNT=$(grep -c "\*${anchor}" "${file}" || echo "0")
    if [ ${USAGE_COUNT} -eq 0 ]; then
      echo "  Удаление неиспользуемого якоря: ${anchor}"
      # Удаление строки с якорем
      sed -i "/&${anchor}/d" "${file}"
    fi
  done
done
```

### Очистка кэша GitLab Runner

При изменении `!reference` убедитесь, что Runner использует актуальную конфигурацию:

```bash
# Перезапуск Runner для сброса кэша
gitlab-runner restart

# Очистка артефактов и кэша на Runner
gitlab-runner verify --delete
```

---

## Дополнительная информация

### Связанные разделы

- **[Обзор переиспользуемых пайплайнов](./overview.md)** — выбор архитектурного подхода.
- **[Механизм extends](./extends_keyword.md)** — наследование структур заданий.
- **[Механизм include](./include_keyword.md)** — подключение внешних YAML-ресурсов.
- **[Сервисные контейнеры](./services_and_service_containers.md)** — `services:`, DinD, health checks, aliases в reusable templates.
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — управление данными внутри пайплайна.
- **[CI/CD Components](./ci_cd_catalog_components.md)** — параметризованные компоненты (альтернатива `!reference` для передачи параметров).

### Внешние ресурсы

- [GitLab Docs: Optimization with !reference](https://docs.gitlab.com/ee/ci/yaml/yaml_optimization.html#reference-tags)
- [YAML 1.2 Alias Nodes Specification](https://yaml.org/spec/1.2.2/#71-alias-nodes)
