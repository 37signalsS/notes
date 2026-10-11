# GitLab CI: Каталог компонентов — продвинутые сценарии

**Актуально для:** GitLab CI 19.x

## Определения

**Продвинутый сценарий** — комплексный архитектурный паттерн использования CI/CD Components, выходящий за рамки базового импорта. Включает в себя миграцию крупномасштабных систем, управление монорепозиториями, многоуровневое каскадное подключение (chaining), стратегии безопасного развертывания новых версий и глубокую интеграцию с корпоративными политиками безопасности.

**Инкапсуляция логики** — принцип проектирования, при котором внутренние детали реализации (Bash-команды, Docker-образы) скрыты за декларативным интерфейсом `spec:inputs`, что снижает когнитивную нагрузку на разработчиков.

**Canary-развертывание** — стратегия постепенного внедрения изменений, при которой новая версия компонента сначала применяется к малому подмножеству проектов (1-10%), а затем масштабируется при отсутствии ошибок.

**Инцидент CI/CD** — событие, при котором компонент каталога вызывает сбой пайплайна, замедление или нарушение безопасности, требующее немедленного реагирования.

**SLA Impact** — показатель влияния времени загрузки компонента на общее время выполнения пайплайна. Рассчитывается как `(Load Time / Total Pipeline Time) × 100%`.

**RFC (Request for Comments)** — формальный процесс согласования архитектурных изменений в команде, включающий описание проблемы, предложенного решения, влияния и timeline.

## Основные концепции

### Фазы интерполяции и область видимости

Для проектирования сложных систем необходимо учитывать жизненный цикл разрешения YAML-конфигурации:
1.  **Разрешение `include`**: GitLab собирает все файлы (компоненты, шаблоны, локальные файлы).
2.  **Интерполяция `inputs`**: Значения подставляются во все блоки кода. 
    *   *Важно:* Теги `!reference` разрешаются **после** инпутов, поэтому передать `inputs` внутрь ссылки `!reference` напрямую невозможно.
3.  **Обработка `variables`**: Инициализируются переменные. Значения из `inputs` уже доступны для использования внутри блока `variables`.
4.  **Разрешение `extends` и `!reference`**: Выполняется финальное слияние структур и вставка фрагментов кода.

### Безопасность и цепочка поставок (Supply Chain Security)

Компоненты каталога обеспечивают уровень защиты Enterprise-класса:
-   **Изоляция контекста**: Интерполяция `$[[ inputs.* ]]` выполняется в изолированной области видимости, исключая конфликты имен между независимыми модулями.
-   **Контроль версий**: Поддержка Commit SHA (`@abc123de...`) гарантирует неизменность кода компонента и защищает от атак типа «отравление тега».
-   **Интеграция с OIDC**: Использование `id_tokens` внутри компонентов позволяет реализовать Zero Trust аутентификацию без долгоживущих секретов.

### Архитектурные паттерны каталога

При масштабировании каталога компонентов используются следующие паттерны:

| Паттерн | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Монолитный каталог** | Все компоненты в одном репозитории | < 30 компонентов, одна команда |
| **Мульти-каталог** | Разделение по доменам (infra, app, security) | > 30 компонентов, несколько команд |
| **Федеративный каталог** | Каждая команда owns свой каталог | > 100 компонентов, decentralized governance |
| **Виртуальный каталог** | Агрегация через include:project | Миграция, переходный период |

---

## Практические сценарии

### Сценарий 1: Миграция с include:project на компоненты

**До (Legacy):** Пайплайны зависят от веток (например, `main`), что делает их нестабильными.
```yaml
include:
  - project: 'group/ci-templates'
    file: '/docker-build.yml'
    ref: main
```

**После (Modern):** Использование компонентов с SemVer и типизированными входами.
```yaml
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/docker-build@1.5.0'
    inputs:
      image: docker:29.8
      push_registry: true
```

**Алгоритм миграции:**
1.  **Спецификация**: Создайте блок `spec:inputs` в исходном шаблоне.
2.  **Рефакторинг**: Замените обращения к переменным `$VAR` на интерполяцию `$[[ inputs.var ]]`.
3.  **Релиз**: Создайте тег SemVer (v1.0.0) и GitLab Release.
4.  **Проверка**: Используйте `glab ci config compile` для подтверждения корректности.

**Полный алгоритм миграции для крупных организаций:**

```bash
#!/bin/bash
# migrate_to_components.sh — пошаговая миграция include:project → components

set -euo pipefail

PROJECTS_FILE="${1:?Укажите файл со списком проектов}"
COMPONENT_PATH="${2:?Укажите путь к компоненту (org/catalog@version)}"
MIGRATION_LOG="/tmp/migration_$(date +%Y%m%d_%H%M%S).log"

echo "=== Миграция на CI/CD Components ===" | tee "${MIGRATION_LOG}"

while IFS= read -r PROJECT_ID; do
  echo "Обработка проекта ${PROJECT_ID}..." | tee -a "${MIGRATION_LOG}"
  
  # 1. Получение текущего .gitlab-ci.yml
  CURRENT_YAML=$(curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    "https://gitlab.example.com/api/v4/projects/${PROJECT_ID}/repository/files/.gitlab-ci.yml/raw?ref=main")
  
  if [ -z "${CURRENT_YAML}" ]; then
    echo "  ПРОПУСК: Файл .gitlab-ci.yml не найден" | tee -a "${MIGRATION_LOG}"
    continue
  fi
  
  # 2. Проверка наличия include:project
  if ! echo "${CURRENT_YAML}" | grep -q "include:project"; then
    echo "  ПРОПУСК: Уже использует компоненты или не имеет include:project" | tee -a "${MIGRATION_LOG}"
    continue
  fi
  
  # 3. Бэкап текущего файла
  echo "${CURRENT_YAML}" > "/tmp/backup_${PROJECT_ID}_$(date +%s).yml"
  
  # 4. Замена include:project на component
  UPDATED_YAML=$(echo "${CURRENT_YAML}" | sed \
    -e "s|project: 'group/ci-templates'|component: '${COMPONENT_PATH}'|g" \
    -e "s|ref: main||g")
  
  # 5. Коммит изменений
  BRANCH_NAME="ci/migrate-to-components-$(date +%s)"
  
  # Создание ветки
  curl -s --request POST \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    --data "branch=main&new_branch=${BRANCH_NAME}" \
    "https://gitlab.example.com/api/v4/projects/${PROJECT_ID}/repository/branches" > /dev/null
  
  # Коммит
  ENCODED_CONTENT=$(echo "${UPDATED_YAML}" | base64)
  curl -s --request POST \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    --data "branch=${BRANCH_NAME}&commit_message=ci: migrate to components&content=${ENCODED_CONTENT}" \
    "https://gitlab.example.com/api/v4/projects/${PROJECT_ID}/repository/files/.gitlab-ci.yml" > /dev/null
  
  # 6. Создание Merge Request
  MR_INFO=$(curl -s --request POST \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    --data "source_branch=${BRANCH_NAME}&target_branch=main&title=ci: migrate to CI/CD Components" \
    "https://gitlab.example.com/api/v4/projects/${PROJECT_ID}/merge_requests")
  
  MR_URL=$(echo "${MR_INFO}" | jq -r '.web_url')
  echo "  MR создан: ${MR_URL}" | tee -a "${MIGRATION_LOG}"
  
done < "${PROJECTS_FILE}"

echo "=== Миграция завершена. Лог: ${MIGRATION_LOG} ===" | tee -a "${MIGRATION_LOG}"
```

### Сценарий 2: Компонент для монорепозитория (Selective CI)

Эффективное управление сборкой через селективный запуск заданий на основе путей.

```yaml
# templates/module-builder.yml
spec:
  inputs:
    module_path:
      type: string
    build_command:
      default: "make build"
---
build-module:
  stage: build
  script:
    - cd $[[ inputs.module_path ]]
    - $[[ inputs.build_command ]]
  rules:
    - changes:
        - $[[ inputs.module_path ]]/**/*
```

### Сценарий 3: Глубокая валидация через options и regex

Использование `options` создает выпадающие списки в UI GitLab, а `regex` защищает от некорректных строк.

```yaml
spec:
  inputs:
    deploy_env:
      type: string
      options: [dev, staging, prod]
    replicas:
      type: number
      regex: '^[1-5]$' # Ограничение от 1 до 5 инстансов
---
deploy_job:
  script:
    - echo "Deploying $[[ inputs.replicas ]] nodes to $[[ inputs.deploy_env ]]"
```

### Сценарий 4: Цепочка компонентов (Component Chaining)

Создание «золотых пайплайнов» организации путем каскадного подключения модулей.

```yaml
# templates/standard-pipeline.yml
spec:
  inputs:
    app_name: { type: string }
---
include:
  - component: '$CI_SERVER_FQDN/org/linter@2.0.0'
  - component: '$CI_SERVER_FQDN/org/docker-builder@3.1.0'
    inputs: { image_name: $[[ inputs.app_name ]] }
```
> *Внимание:* Каждый вложенный компонент учитывается в лимите 150 `include`.

### Сценарий 5: Постепенное внедрение (Rollout) через условия

Безопасное тестирование новых версий критических инструментов на части проектов.

```yaml
include:
  # 90% проектов на стабильной версии
  - component: '$CI_SERVER_FQDN/org/security-scan@1.5.0'
    rules:
      - if: '$CI_PROJECT_ID % 10 != 0'
  # 10% проектов тестируют RC
  - component: '$CI_SERVER_FQDN/org/security-scan@2.0.0-rc1'
    rules:
      - if: '$CI_PROJECT_ID % 10 == 0'
```

### Сценарий 6: Вложенные компоненты (Nested Components)

Явная передача параметров по иерархии вложенности.

```yaml
# templates/parent.yml
spec:
  inputs: { stage_name: { default: test } }
---
include:
  - component: $CI_SERVER_FQDN/my-org/child@1.0.0
    inputs: { target_stage: $[[ inputs.stage_name ]] }
```

### Сценарий 7: Глобальные входы пайплайна (v17.11+)

Создание динамических форм запуска в корневом `.gitlab-ci.yml` проекта.

```yaml
# .gitlab-ci.yml
spec:
  inputs:
    target_cluster:
      options: [self-hosted-eu, self-hosted-us]
      default: self-hosted-eu
---
include:
  - component: $CI_SERVER_FQDN/org/deploy@1.0.0
    inputs: { cluster: $[[ inputs.target_cluster ]] }
```

### Сценарий 8: Контекстная адаптация (v18.6+)

Компонент автоматически определяет версию инструментов на основе собственной версии.

```yaml
# templates/scanner.yml
run-scan:
  image: custom-registry/scanner:$[[ component.version ]]
  script:
    - scanner-cli --path .
```

### Сценарий 9: Тестирование компонентов (Testing Strategy)

Полная стратегия тестирования компонентов каталога включает 4 уровня.

**Уровень 1: Синтаксическая проверка**

```yaml
# templates/testing.yml
.test_lint:
  stage: test
  image: alpine:3.19
  before_script:
    - apk add --no-cache yamllint
  script:
    - |
      echo "=== Синтаксическая проверка ==="
      yamllint -d relaxed templates/*.yml
      
      # Проверка наличия spec:inputs
      for file in templates/*.yml; do
        if ! grep -q "spec:" "${file}"; then
          echo "ПРЕДУПРЕЖДЕНИЕ: ${file} не имеет секции spec"
        fi
      done
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

**Уровень 2: Валидация через glab ci lint**

```yaml
.validate_component:
  stage: test
  image: gitlab/glab:latest
  script:
    - |
      echo "=== Валидация через glab ==="
      
      for component in templates/*.yml; do
        echo "Проверка ${component}..."
        
        if glab ci lint "${component}" > /dev/null 2>&1; then
          echo "  OK: ${component}"
        else
          echo "  ОШИБКА: ${component}"
          glab ci lint "${component}"
          exit 1
        fi
      done
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

**Уровень 3: Интеграционные тесты (реальные пайплайны)**

```yaml
.integration_test:
  stage: integration
  image: gitlab/glab:latest
  variables:
    GITLAB_TOKEN: $TEST_GITLAB_TOKEN
  script:
    - |
      echo "=== Интеграционные тесты ==="
      
      # Создание тестового проекта
      TEST_PROJECT_ID=$(curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        --data "name=component-test-$(date +%s)" \
        "${GITLAB_URL}/api/v4/projects" | jq -r '.id')
      
      echo "Тестовый проект: ${TEST_PROJECT_ID}"
      
      # Тест 1: Базовый вызов компонента
      cat > test-basic.yml <<EOF
      include:
        - component: ${CI_SERVER_FQDN}/${CATALOG_PROJECT_PATH}@${CI_COMMIT_TAG}
          inputs:
            image: alpine:3.19
      
      test-basic:
        script:
          - echo "OK"
      EOF
      
      curl -s --request POST \
        --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        --data "branch=main&commit_message=test: basic component usage&content=$(base64 < test-basic.yml)" \
        "${GITLAB_URL}/api/v4/projects/${TEST_PROJECT_ID}/repository/files/.gitlab-ci.yml"
      
      # Запуск пайплайна
      PIPELINE_ID=$(curl -s --request POST \
        --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        "${GITLAB_URL}/api/v4/projects/${TEST_PROJECT_ID}/pipeline?ref=main" | jq -r '.id')
      
      echo "Pipeline ID: ${PIPELINE_ID}"
      
      # Ожидание завершения (макс 5 минут)
      for i in $(seq 1 60); do
        STATUS=$(curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
          "${GITLAB_URL}/api/v4/projects/${TEST_PROJECT_ID}/pipelines/${PIPELINE_ID}" | jq -r '.status')
        
        if [ "${STATUS}" == "success" ]; then
          echo "  OK: Интеграционный тест пройден"
          break
        elif [ "${STATUS}" == "failed" ]; then
          echo "  ОШИБКА: Интеграционный тест провален"
          curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            "${GITLAB_URL}/api/v4/projects/${TEST_PROJECT_ID}/pipelines/${PIPELINE_ID}/jobs" | \
            jq -r '.[].failure_reason'
          exit 1
        fi
        
        sleep 5
      done
      
      # Очистка
      curl -s --request DELETE \
        --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        "${GITLAB_URL}/api/v4/projects/${TEST_PROJECT_ID}"
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      when: manual
```

**Уровень 4: Негативные тесты (проверка отклонения некорректных входов)**

```yaml
.negative_test:
  stage: negative
  image: gitlab/glab:latest
  script:
    - |
      echo "=== Негативные тесты ==="
      
      # Тест: Неверный тип данных
      cat > test-invalid-type.yml <<EOF
      include:
        - component: ${CI_SERVER_FQDN}/${CATALOG_PROJECT_PATH}@${CI_COMMIT_TAG}
          inputs:
            replicas: not-a-number
      
      test-invalid:
        script:
          - echo "Should not reach here"
      EOF
      
      # Валидация должна показать ошибку
      if glab ci lint test-invalid-type.yml 2>&1 | grep -q "input validation error"; then
        echo "  OK: Неверный тип данных корректно отклонен"
      else
        echo "  ОШИБКА: Неверный тип данных не был отклонен"
        exit 1
      fi
      
      # Тест: Отсутствующий обязательный input
      cat > test-missing-required.yml <<EOF
      include:
        - component: ${CI_SERVER_FQDN}/${CATALOG_PROJECT_PATH}@${CI_COMMIT_TAG}
          inputs: {}
      
      test-missing:
        script:
          - echo "Should not reach here"
      EOF
      
      if glab ci lint test-missing-required.yml 2>&1 | grep -q "missing required input"; then
        echo "  OK: Отсутствующий обязательный input корректно отклонен"
      else
        echo "  ОШИБКА: Отсутствующий обязательный input не был отклонен"
        exit 1
      fi
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      when: manual
```

**Структура каталога для тестирования:**

```
component-catalog/
├── templates/
│   ├── docker-build.yml
│   ├── security-scan.yml
│   └── deploy.yml
├── tests/
│   ├── unit/
│   │   ├── test_docker_build.sh
│   │   └── test_security_scan.sh
│   ├── integration/
│   │   ├── test_basic_usage.yml
│   │   └── test_advanced_usage.yml
│   └── negative/
│       ├── test_invalid_type.yml
│       └── test_missing_required.yml
├── scripts/
│   ├── validate_all.sh
│   └── run_integration_tests.sh
└── README.md
```

### Сценарий 10: Инцидент-менеджмент и автоматический откат

Стандартизированный процесс реагирования на сбои компонентов каталога.

**Уровень 1: Автоматическое реагирование (Auto-respond)**

```yaml
# templates/incident_response.yml
.auto_respond:
  script:
    - |
      INCIDENT_ID=$(date +%s)-${CI_PIPELINE_ID}
      ALERT_PAYLOAD=$(cat <<EOF
      {
        "labels": {
          "alertname": "ComponentFailure",
          "severity": "critical",
          "component": "$[[ component.name ]]",
          "version": "$[[ component.version ]]",
          "project": "${CI_PROJECT_PATH}"
        },
        "annotations": {
          "summary": "Component $[[ component.name ]] failed in ${CI_PROJECT_PATH}",
          "description": "Pipeline ${CI_PIPELINE_ID} failed at job ${CI_JOB_NAME}",
          "runbook": "https://wiki.internal/runbooks/component-failure"
        }
      }
      EOF
      )
      
      # Отправка в Alertmanager
      curl -s -X POST \
        --header "Content-Type: application/json" \
        --data "${ALERT_PAYLOAD}" \
        "${ALERTMANAGER_URL}/api/v1/alerts"
      
      # Автоматический откат при критических ошибках
      if echo "${CI_JOB_NAME}" | grep -q "deploy_production"; then
        echo "=== Критическая ошибка в продакшене ==="
        echo "Запуск автоматического отката..."
        
        # Поиск предыдущей успешной версии
        PREV_VERSION=$(git tag --sort=-v:refname | grep -v "rc\|alpha\|beta" | head -2)
        
        if [ -n "${PREV_VERSION}" ]; then
          echo "Откат на версию ${PREV_VERSION}..."
          
          # Обновление компонента в .gitlab-ci.yml
          sed -i "s|@${CI_COMMIT_TAG}|@${PREV_VERSION}|g" .gitlab-ci.yml
          
          git config user.name "Auto-Rollback Bot"
          git config user.email "bot@example.com"
          git add .gitlab-ci.yml
          git commit -m "rollback: revert to ${PREV_VERSION} due to component failure"
          git push origin main
        fi
      fi

failed_component_job:
  stage: .post
  when: on_failure
  script:
    - !reference [.auto_respond, script]
  rules:
    - if: '$CI_JOB_STATUS == "failed"'
```

**Уровень 2: Ручное вмешательство (Manual Intervention)**

```bash
#!/bin/bash
# manual_intervention.sh — процедура ручного вмешательства

COMPONENT_NAME="${1:?Укажите имя компонента}"
INCIDENT_ID="${2:?Укажите ID инцидента}"

echo "=== Ручное вмешательство: ${COMPONENT_NAME} ==="
echo "Incident ID: ${INCIDENT_ID}"

# 1. Сбор информации
echo "1. Сбор информации..."
AFFECTED_PROJECTS=$(curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  "${GITLAB_URL}/api/v4/projects?search=${COMPONENT_NAME}" | jq -r '.[].path_with_namespace')

echo "Затронутые проекты:"
echo "${AFFECTED_PROJECTS}"

# 2. Анализ логов
echo "2. Анализ логов..."
for PROJECT in ${AFFECTED_PROJECTS}; do
  echo "  Анализ ${PROJECT}..."
  
  FAILED_JOBS=$(curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    "${GITLAB_URL}/api/v4/projects/$(echo ${PROJECT} | tr '/' '%2F')/pipelines?status=failed&per_page=5" | \
    jq -r '.[].id')
  
  for JOB_ID in ${FAILED_JOBS}; do
    echo "    Job ${JOB_ID}:"
    curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
      "${GITLAB_URL}/api/v4/projects/$(echo ${PROJECT} | tr '/' '%2F')/jobs/${JOB_ID}/trace" | \
      tail -20
  done
done

# 3. Определение причины
echo "3. Определение причины..."
echo "Возможные причины:"
echo "  a) Баг в компоненте → Исправление и релиз патча"
echo "  b) Несовместимость с окружением → Обновление зависимостей"
echo "  c) Проблема с инфраструктурой → Эскалация в SRE"
echo "  d) Ошибка пользователя → Документация и обучение"

# 4. Выбор действия
echo "4. Выбор действия:"
echo "  1) Исправить компонент (патч)"
echo "  2) Откатить на предыдущую версию"
echo "  3) Эскалация в SRE"
read -p "Выберите действие (1-3): " ACTION

case ${ACTION} in
  1)
    echo "Создание ветки для исправления..."
    git checkout -b "hotfix/${COMPONENT_NAME}-${INCIDENT_ID}"
    ;;
  2)
    echo "Откат компонента..."
    PREV_VERSION=$(git tag --sort=-v:refname | grep -v "rc\|alpha\|beta" | head -2)
    sed -i "s|@${CURRENT_VERSION}|@${PREV_VERSION}|g" .gitlab-ci.yml
    git commit -m "rollback: ${COMPONENT_NAME} to ${PREV_VERSION}"
    git push
    ;;
  3)
    echo "Эскалация в SRE..."
    curl -s -X POST \
      --header "Content-Type: application/json" \
      --data "{\"incident_id\": \"${INCIDENT_ID}\", \"component\": \"${COMPONENT_NAME}\", \"severity\": \"critical\"}" \
      "${SRE_ONCALL_WEBHOOK}"
    ;;
esac

echo "=== Действие выполнено ==="
```

**Уровень 3: Масштабирование (Strategic Scaling)**

```yaml
# templates/strategic_scaling.yml
.scale_response:
  script:
    - |
      echo "=== Стратегическое масштабирование ==="
      
      # Анализ влияния на SLA
      PIPELINE_DURATION=$(curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/pipelines/${CI_PIPELINE_ID}" | \
        jq -r '.duration')
      
      SLA_IMPACT=$(echo "scale=2; ${PIPELINE_DURATION} / 3600 * 100" | bc)
      
      echo "Влияние на SLA: ${SLA_IMPACT}%"
      
      if (( $(echo "${SLA_IMPACT} > 5" | bc -l) )); then
        echo "КРИТИЧНО: SLA impact > 5%"
        
        # Уведомление руководства
        curl -s -X POST \
          --header "Content-Type: application/json" \
          --data "{
            \"channel\": \"#incident-response\",
            \"text\": \"CRITICAL: SLA impact ${SLA_IMPACT}% from component failure\"
          }" \
          "${SLACK_WEBHOOK}"
        
        # Масштабирование инфраструктуры (зависит от окружения: docker-compose, systemd, CI/CD)
        echo "Масштабирование пулов..."
      fi
```

### Сценарий 11: Canary-стратегия с мониторингом

Расширенная canary-стратегия с автоматической проверкой ошибок через Prometheus.

```yaml
# templates/canary_with_monitoring.yml
spec:
  inputs:
    component_name:
      type: string
    new_version:
      type: string
    old_version:
      type: string
    error_threshold:
      type: number
      default: 1
---
canary_deploy:
  stage: canary
  script:
    - |
      echo "=== Canary Deploy: $[[ inputs.component_name ]] ==="
      
      # Шаг 1: Развертывание на 5% проектов
      CANARY_PROJECTS=$(curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        "${GITLAB_URL}/api/v4/projects?per_page=100" | \
        jq -r '.[].id' | shuf | head -n 5)
      
      echo "Canary проекты: ${CANARY_PROJECTS}"
      
      for PROJECT_ID in ${CANARY_PROJECTS}; do
        # Обновление версии компонента
        curl -s --request PUT \
          --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
          --data "content=$(echo "include:\n  - component: ${CI_SERVER_FQDN}/${CATALOG_PATH}@$[[ inputs.new_version ]]" | base64)" \
          "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/repository/files/.gitlab-ci.yml?ref=main"
      done
      
      # Шаг 2: Мониторинг ошибок (5 минут)
      echo "Мониторинг ошибок..."
      START_TIME=$(date +%s)
      END_TIME=$((START_TIME + 300))
      
      while [ $(date +%s) -lt ${END_TIME} ]; do
        # Запрос к Prometheus
        ERROR_RATE=$(curl -s "${PROMETHEUS_URL}/api/v1/query?query=\
          rate(pipeline_failed_total{component=\"$[[ inputs.component_name ]]\"}[5m]) * 100" | \
          jq -r '.data.result[0].value[1] // "0"')
        
        echo "  Текущий error rate: ${ERROR_RATE}%"
        
        if (( $(echo "${ERROR_RATE} > $[[ inputs.error_threshold ]]" | bc -l) )); then
          echo "  ОШИБКА: Error rate превышает порог"
          
          # Автоматический откат
          for PROJECT_ID in ${CANARY_PROJECTS}; do
            curl -s --request PUT \
              --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
              --data "content=$(echo "include:\n  - component: ${CI_SERVER_FQDN}/${CATALOG_PATH}@$[[ inputs.old_version ]]" | base64)" \
              "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/repository/files/.gitlab-ci.yml?ref=main"
          done
          
          echo "Canary откачен из-за превышения порога ошибок"
          exit 1
        fi
        
        sleep 30
      done
      
      echo "Canary успешен. Безопасно для полного развертывания."
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
      when: manual

production_deploy:
  stage: production
  needs: [canary_deploy]
  script:
    - |
      echo "=== Production Deploy ==="
      
      # Полное развертывание на все проекты
      ALL_PROJECTS=$(curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        "${GITLAB_URL}/api/v4/projects?per_page=100" | jq -r '.[].id')
      
      for PROJECT_ID in ${ALL_PROJECTS}; do
        curl -s --request PUT \
          --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
          --data "content=$(echo "include:\n  - component: ${CI_SERVER_FQDN}/${CATALOG_PATH}@$[[ inputs.new_version ]]" | base64)" \
          "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/repository/files/.gitlab-ci.yml?ref=main"
      done
      
      echo "Production deploy завершен"
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
      when: manual
```

### Сценарий 12: Оптимизация производительности каталога

МерTheta для снижения влияния компонентов на время пайплайна.

**Мониторинг SLA Impact:**

```yaml
# templates/sla_monitoring.yml
.sla_check:
  script:
    - |
      echo "=== Проверка SLA Impact ==="
      
      # Получение метрик
      TOTAL_PIPELINE_TIME=$(curl -s "${PROMETHEUS_URL}/api/v1/query?query=\
        sum(pipeline_duration_seconds{project=\"${CI_PROJECT_PATH}\"})" | \
        jq -r '.data.result[0].value[1] // "0"')
      
      COMPONENT_LOAD_TIME=$(curl -s "${PROMETHEUS_URL}/api/v1/query?query=\
        sum(component_load_duration_seconds{component=\"$[[ component.name ]]\"})" | \
        jq -r '.data.result[0].value[1] // "0"')
      
      # Расчет SLA Impact
      SLA_IMPACT=$(echo "scale=2; ${COMPONENT_LOAD_TIME} / ${TOTAL_PIPELINE_TIME} * 100" | bc)
      
      echo "SLA Impact: ${SLA_IMPACT}%"
      
      # Оценка риска
      if (( $(echo "${SLA_IMPACT} > 20" | bc -l) )); then
        echo "ВЫСОКИЙ РИСК: SLA Impact > 20%"
        echo "Рекомендации:"
        echo "  1) Кэширование зависимостей"
        echo "  2) Параллельная загрузка компонентов"
        echo "  3) Локальное зеркало компонентов"
        exit 1
      elif (( $(echo "${SLA_IMPACT} > 10" | bc -l) )); then
        echo "СРЕДНИЙ РИСК: SLA Impact > 10%"
        echo "Рекомендации:"
        echo "  1) Мониторинг производительности"
        echo "  2) Оптимизация зависимостей"
      else
        echo "НИЗКИЙ РИСК: SLA Impact < 10%"
      fi
```

**Оптимизация через кэширование:**

```yaml
# templates/optimized_components.yml
.optimized_build:
  stage: build
  cache:
    key:
      files:
        - package-lock.json
        - requirements.txt
    paths:
      - node_modules/
      - .venv/
      - .cache/
    policy: pull-push
  script:
    - |
      # Проверка кэша
      if [ -d "node_modules" ]; then
        echo "Кэш найден, пропуск установки..."
      else
        echo "Кэш не найден, установка зависимостей..."
        npm ci
      fi
      
      # Сборка
      npm run build
```

**Оптимизация через параллелизм:**

```yaml
# templates/parallel_components.yml
parallel_build:
  stage: build
  parallel:
    matrix:
      - MODULE: [auth, api, web, worker]
        NODE_VERSION: [18, 20]
  script:
    - cd modules/$MODULE
    - nvm use $NODE_VERSION
    - npm ci
    - npm run build
```

### Сценарий 13: Мониторинг и наблюдаемость

Интеграция компонентов с Prometheus и Grafana для полной наблюдаемости.

```yaml
# templates/monitoring.yml
.metrics_export:
  script:
    - |
      echo "=== Экспорт метрик ==="
      
      # Метрика использования компонента
      cat <<EOF | curl --data-binary @- -X POST "${PROMETHEUS_PUSHGATEWAY}/metrics"
      # HELP gitlab_component_usage_total Total component usage
      # TYPE gitlab_component_usage_total counter
      gitlab_component_usage_total{
        component="$[[ component.name ]]",
        version="$[[ component.version ]]",
        project="${CI_PROJECT_PATH}",
        pipeline="${CI_PIPELINE_ID}"
      } 1
      
      # HELP gitlab_component_duration_seconds Component load duration
      # TYPE gitlab_component_duration_seconds histogram
      gitlab_component_duration_seconds_bucket{
        component="$[[ component.name ]]",
        le="0.1"
      } $(date +%s)
      gitlab_component_duration_seconds_bucket{
        component="$[[ component.name ]]",
        le="0.5"
      } $(date +%s)
      gitlab_component_duration_seconds_bucket{
        component="$[[ component.name ]]",
        le="1"
      } $(date +%s)
      gitlab_component_duration_seconds_bucket{
        component="$[[ component.name ]]",
        le="+Inf"
      } $(date +%s)
      EOF
      
      echo "Метрики экспортированы"
```

**Grafana Dashboard JSON:**

```json
{
  "dashboard": {
    "title": "GitLab CI Component Metrics",
    "panels": [
      {
        "title": "Component Usage",
        "type": "graph",
        "targets": [
          {
            "expr": "sum by (component)(gitlab_component_usage_total)",
            "legendFormat": "{{ component }}"
          }
        ]
      },
      {
        "title": "Component Load Time (p95)",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum by (le, component)(gitlab_component_duration_seconds_bucket))",
            "legendFormat": "{{ component }}"
          }
        ]
      }
    ]
  }
}
```

### Сценарий 14: Координация команд и процессов

Стандартизированный процесс изменения конфигурации CI/CD в команде.

**RFC Template:**

```markdown
# RFC-001: Миграция на CI/CD Components

## Проблема
Текущие шаблоны используют include:project, что приводит к:
- Нестабильности из-за зависимостей от веток
- Отсутствию типизации входов
- Сложности отслеживания версий

## Решение
Миграция на CI/CD Components с SemVer версионированием.

## Влияние
- 50+ проектов будут затронуты
- Требуется обучение команд
- Ожидаемое улучшение: стабильность +20%

## Timeline
- Неделя 1: Создание компонентов
- Неделя 2: Пилотное тестирование (5 проектов)
- Неделя 3: Миграция 50% проектов
- Неделя 4: Полная миграция

## Rollback Plan
1. Создать ветку rollback-components-to-extends
2. Revert всех изменений в .gitlab-ci.yml
3. Проверить шаблоны
4. Canary deploy (10% → 50% → 100%)
```

**Роли и ответственность:**

| Роль | Ответственность | Уровень доступа |
| :--- | :--- | :--- |
| **Platform Engineer** | Разработка и поддержка компонентов | Catalog Owner |
| **SRE** | Мониторинг и инцидент-менеджмент | Maintainer |
| **Tech Lead** | Архитектурные решения, RFC | Maintainer |
| **Developer** | Использование компонентов | Reporter |

**Процесс согласования:**

```yaml
# templates/approval_workflow.yml
.approval_required:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      changes:
        - "templates/*.yml"
  script:
    - |
      echo "=== Требуется согласование ==="
      
      # Уведомление Platform Engineer
      curl -s -X POST \
        --header "Content-Type: application/json" \
        --data "{
          \"channel\": \"#platform-engineering\",
          \"text\": \"MR ${CI_MERGE_REQUEST_IID} требует ревью изменений в компонентах\"
        }" \
        "${SLACK_WEBHOOK}"
      
      # Ожидание одобрения (макс 24 часа)
      APPROVAL_STATUS=$(curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/merge_requests/${CI_MERGE_REQUEST_IID}/approvals" | \
        jq -r '.approved')
      
      if [ "${APPROVAL_STATUS}" != "true" ]; then
        echo "ОШИБКА: MR не одобрен"
        exit 1
      fi
```

---

## Валидация и устранение неисправностей

### Диагностика типичных ошибок

| Проблема | Причина | Способ решения |
| :--- | :--- | :--- |
| **Error 404** | Неверный путь или проект не «Catalog resource». | Проверьте настройки Visibility и путь к файлу в `templates/`. |
| **Input validation error** | Ошибка типа (string вместо number). | Оборачивайте числа в кавычки в YAML, если в `spec` указан тип `string`. |
| **Exceeded max includes** | Слишком глубокая вложенность (лимит 150). | Используйте `!reference` для переиспользования кода внутри одного файла. |
| **Interpolation failed** | Ошибка синтаксиса `$[[ ]]`. | Проверьте закрывающие скобки и отсутствие циклов в инпутах. |
| **Component load timeout** | Медленная загрузка компонента (>30с). | Оптимизируйте зависимости, используйте кэширование. |
| **Version conflict** | Несовместимые версии в цепочке. | Используйте SemVer ranges, проверьте совместимость. |
| **OIDC token expired** | Истекший токен аутентификации. | Обновите токен, проверьте настройки OIDC. |
| **Pipeline too slow** | SLA Impact > 20%. | Оптимизируйте загрузку, параллелизм, кэширование. |

### Инструменты отладки

```bash
# Полный набор инструментов отладки

# 1. Просмотр expanded YAML
glab ci config compile

# 2. Проверка конкретного компонента
glab ci lint component.yml

# 3. Анализ метрик
curl "${PROMETHEUS_URL}/api/v1/query?query=gitlab_component_usage_total"

# 4. Поиск затронутых проектов
curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  "${GITLAB_URL}/api/v4/projects?search=component-name" | jq '.[].path_with_namespace'

# 5. Анализ времени выполнения
curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/pipelines?per_page=10" | \
  jq '.[] | {id: .id, duration: .duration, status: .status}'

# 6. Проверка версий компонентов
grep -r "component:" .gitlab-ci.yml | sed 's/.*@//' | sort -u

# 7. Анализ ошибок
curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/pipelines?status=failed&per_page=5" | \
  jq '.[].id' | while read PIPELINE_ID; do
    echo "=== Pipeline ${PIPELINE_ID} ==="
    curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
      "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/pipelines/${PIPELINE_ID}/jobs?scope=failed" | \
      jq '.[].failure_reason'
  done
```

### Диагностический скрипт

```bash
#!/bin/bash
# diagnose_catalog.sh — полная диагностика каталога компонентов

echo "=== Диагностика каталога компонентов ==="

CATALOG_PATH="${1:?Укажите путь к каталогу}"
GITLAB_URL="${GITLAB_URL:-https://gitlab.example.com}"
TOKEN="${GITLAB_TOKEN}"

# 1. Проверка структуры каталога
echo "1. Проверка структуры каталога..."
REQUIRED_DIRS=("templates" "tests" "docs")
for dir in "${REQUIRED_DIRS[@]}"; do
  if [ ! -d "${CATALOG_PATH}/${dir}" ]; then
    echo "  ОШИБКА: Отсутствует директория ${dir}"
  else
    echo "  OK: ${dir} существует"
  fi
done

# 2. Проверка компонентов
echo "2. Проверка компонентов..."
COMPONENT_COUNT=0
VALID_COUNT=0
INVALID_COUNT=0

for component in "${CATALOG_PATH}/templates/"*.yml; do
  if [ ! -f "${component}" ]; then
    continue
  fi
  
  COMPONENT_COUNT=$((COMPONENT_COUNT + 1))
  
  if glab ci lint "${component}" > /dev/null 2>&1; then
    VALID_COUNT=$((VALID_COUNT + 1))
    echo "  OK: $(basename ${component})"
  else
    INVALID_COUNT=$((INVALID_COUNT + 1))
    echo "  ОШИБКА: $(basename ${component})"
    glab ci lint "${component}"
  fi
done

echo "  Всего: ${COMPONENT_COUNT}, Валидных: ${VALID_COUNT}, Невалидных: ${INVALID_COUNT}"

# 3. Проверка версий
echo "3. Проверка версий..."
TAGS=$(cd "${CATALOG_PATH}" && git tag --sort=-v:refname | head -5)
echo "  Последние теги: ${TAGS}"

# 4. Проверка лимитов
echo "4. Проверка лимитов..."
INCLUDE_COUNT=$(grep -r "include:" "${CATALOG_PATH}/templates/" | wc -l)
echo "  Количество include: ${INCLUDE_COUNT}"
if [ ${INCLUDE_COUNT} -gt 100 ]; then
  echo "  ПРЕДУПРЕЖДЕНИЕ: Приближение к лимиту (150)"
fi

# 5. Проверка безопасности
echo "5. Проверка безопасности..."
SECRETS_FOUND=$(grep -r "password\|secret\|token" "${CATALOG_PATH}/templates/" | grep -v "description" | wc -l)
if [ ${SECRETS_FOUND} -gt 0 ]; then
  echo "  ОШИБКА: Найдены потенциальные секреты в шаблонах"
  grep -r "password\|secret\|token" "${CATALOG_PATH}/templates/" | grep -v "description"
else
  echo "  OK: Секреты не найдены"
fi

# 6. Проверка документации
echo "6. Проверка документации..."
if [ -f "${CATALOG_PATH}/README.md" ]; then
  echo "  OK: README.md существует"
  
  # Проверка наличия описаний для inputs
  for component in "${CATALOG_PATH}/templates/"*.yml; do
    if [ ! -f "${component}" ]; then
      continue
    fi
    
    INPUTS_COUNT=$(grep -c "type:" "${component}" || echo "0")
    DESCRIPTIONS_COUNT=$(grep -c "description:" "${component}" || echo "0")
    
    if [ ${INPUTS_COUNT} -gt ${DESCRIPTIONS_COUNT} ]; then
      echo "  ПРЕДУПРЕЖДЕНИЕ: $(basename ${component}) имеет inputs без описаний"
    fi
  done
else
  echo "  ОШИБКА: README.md отсутствует"
fi

echo "=== Диагностика завершена ==="
```

---

## Лучшие практики

1.  **Атомарность**: Один компонент — одна логическая задача.
2.  **Версионирование (Security)**: В продакшене используйте **Commit SHA** вместо тегов для защиты Supply Chain.
3.  **Документирование**: Каждый `input` должен иметь `description`. Поле `README.md` обязательно.
4.  **Тестирование**: Создавайте папку `tests/` в репозитории компонента и запускайте проверку перед каждым релизом.
5.  **Canary-развертывание**: Внедряйте изменения постепенно (5% → 20% → 100%) с мониторингом ошибок.
6.  **Мониторинг**: Экспортируйте метрики использования компонентов в Prometheus.
7.  **Инцидент-менеджмент**: Имейте стандартный процесс реагирования на сбои компонентов.
8.  **Координация команд**: Используйте RFC для согласования архитектурных изменений.
9.  **Оптимизация**: Мониторьте SLA Impact и оптимизируйте загрузку компонентов.
10. **Безопасность**: Проверяйте секреты, используйте OIDC, верифицируйте целостность.

---

## Безопасность

### Защита цепочки поставок (Supply Chain Security)

Продвинутые сценарии требуют усиленного контроля над цепочкой поставок компонентов:

- **Верификация Commit SHA**: Вместо тегов SemVer для критичных компонентов используйте полные SHA-хеши (`@abc123de...`). Это исключает атаки типа «отравление тега» (tag poisoning), когда злоумышленник перезаписывает легковесный тег.
- **Изоляция контекста**: Интерполяция `$[[ inputs.* ]]` выполняется в изолированной области видимости, исключая конфликты имен между независимыми модулями.
- **OIDC и короткоживущие токены**: Для доступа к внешним ресурсам (реестрам образов, API) используйте `id_tokens` вместо долгоживущих секретов. Пример конфигурации:

```yaml
# templates/secure_deploy.yml
deploy_job:
  image: alpine:3.19
  id_tokens:
    GITLAB_TOKEN:
      aud: https://gitlab.example.com
  script:
    - echo "Deploying with OIDC token"
```

- **Запрет глобальных ключей в компонентах**: Компоненты не должны содержать `workflow:`, `default:`, `stages:` на верхнем уровне — это гарантирует их функциональную изоляцию.

### Управление секретами

- **Никогда не передавайте секреты через `inputs`**: Параметры `spec:inputs` видны в раскрытом YAML и логах. Для секретов используйте `variables:` с защищенными переменными проекта/группы.
- **Сканирование на утечки**: Интегрируйте `gitleaks` или `truffleHog` в пайплайн каталога для автоматического поиска секретов в шаблонах.

### Контроль доступа

- **Роль Catalog Owner**: Только пользователи с ролью `Owner` в проекте-каталоге могут публиковать новые версии компонентов.
- **Change Advisory Board (CAB) lightweight**: Для каждого нового компонента требуется минимум 2 approve от команды инфраструктуры.
- **Аудит изменений**: Все изменения в каталоге проходят через Merge Request с обязательным ревью и CI-валидацией.

---

## Диагностика и отладка

### Типичные ошибки продвинутых сценариев

| Проблема | Причина | Способ решения |
| :--- | :--- | :--- |
| **Error 404** | Неверный путь или проект не «Catalog resource». | Проверьте настройки Visibility и путь к файлу в `templates/`. |
| **Input validation error** | Ошибка типа (string вместо number). | Оборачивайте числа в кавычки в YAML, если в `spec` указан тип `string`. |
| **Exceeded max includes** | Слишком глубокая вложенность (лимит 150). | Используйте `!reference` для переиспользования кода внутри одного файла. |
| **Interpolation failed** | Ошибка синтаксиса `$[[ ]]`. | Проверьте закрывающие скобки и отсутствие циклов в инпутах. |
| **Component load timeout** | Медленная загрузка компонента (>30с). | Оптимизируйте зависимости, используйте кэширование. |
| **Version conflict** | Несовместимые версии в цепочке. | Используйте SemVer ranges, проверьте совместимость. |
| **OIDC token expired** | Истекший токен аутентификации. | Обновите токен, проверьте настройки OIDC. |
| **Pipeline too slow** | SLA Impact > 20%. | Оптимизируйте загрузку, параллелизм, кэширование. |

### Инструменты отладки

```bash
# Полный набор инструментов отладки

# 1. Просмотр expanded YAML
glab ci config compile

# 2. Проверка конкретного компонента
glab ci lint templates/docker-build.yml

# 3. Анализ метрик
curl "${PROMETHEUS_URL}/api/v1/query?query=gitlab_component_usage_total"

# 4. Поиск затронутых проектов
curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  "${GITLAB_URL}/api/v4/projects?search=component-name" | jq '.[].path_with_namespace'

# 5. Анализ времени выполнения
curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/pipelines?per_page=10" | \
  jq '.[] | {id: .id, duration: .duration, status: .status}'

# 6. Проверка версий компонентов
grep -r "component:" .gitlab-ci.yml | sed 's/.*@//' | sort -u

# 7. Анализ ошибок
curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/pipelines?status=failed&per_page=5" | \
  jq '.[].id' | while read PIPELINE_ID; do
    echo "=== Pipeline ${PIPELINE_ID} ==="
    curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
      "${GITLAB_URL}/api/v4/projects/${CI_PROJECT_ID}/pipelines/${PIPELINE_ID}/jobs?scope=failed" | \
      jq '.[].failure_reason'
  done
```

### Диагностический скрипт

```bash
#!/bin/bash
# diagnose_catalog.sh — полная диагностика каталога компонентов

echo "=== Диагностика каталога компонентов ==="

CATALOG_PATH="${1:?Укажите путь к каталогу}"
GITLAB_URL="${GITLAB_URL:-https://gitlab.example.com}"
TOKEN="${GITLAB_TOKEN}"

# 1. Проверка структуры каталога
echo "1. Проверка структуры каталога..."
REQUIRED_DIRS=("templates" "tests" "docs")
for dir in "${REQUIRED_DIRS[@]}"; do
  if [ ! -d "${CATALOG_PATH}/${dir}" ]; then
    echo "  ОШИБКА: Отсутствует директория ${dir}"
  else
    echo "  OK: ${dir} существует"
  fi
done

# 2. Проверка компонентов
echo "2. Проверка компонентов..."
COMPONENT_COUNT=0
VALID_COUNT=0
INVALID_COUNT=0

for component in "${CATALOG_PATH}/templates/"*.yml; do
  if [ ! -f "${component}" ]; then
    continue
  fi
  
  COMPONENT_COUNT=$((COMPONENT_COUNT + 1))
  
  if glab ci lint "${component}" > /dev/null 2>&1; then
    VALID_COUNT=$((VALID_COUNT + 1))
    echo "  OK: $(basename ${component})"
  else
    INVALID_COUNT=$((INVALID_COUNT + 1))
    echo "  ОШИБКА: $(basename ${component})"
    glab ci lint "${component}"
  fi
done

echo "  Всего: ${COMPONENT_COUNT}, Валидных: ${VALID_COUNT}, Невалидных: ${INVALID_COUNT}"

# 3. Проверка версий
echo "3. Проверка версий..."
TAGS=$(cd "${CATALOG_PATH}" && git tag --sort=-v:refname | head -5)
echo "  Последние теги: ${TAGS}"

# 4. Проверка лимитов
echo "4. Проверка лимитов..."
INCLUDE_COUNT=$(grep -r "include:" "${CATALOG_PATH}/templates/" | wc -l)
echo "  Количество include: ${INCLUDE_COUNT}"
if [ ${INCLUDE_COUNT} -gt 100 ]; then
  echo "  ПРЕДУПРЕЖДЕНИЕ: Приближение к лимиту (150)"
fi

# 5. Проверка безопасности
echo "5. Проверка безопасности..."
SECRETS_FOUND=$(grep -r "password\|secret\|token" "${CATALOG_PATH}/templates/" | grep -v "description" | wc -l)
if [ ${SECRETS_FOUND} -gt 0 ]; then
  echo "  ОШИБКА: Найдены потенциальные секреты в шаблонах"
  grep -r "password\|secret\|token" "${CATALOG_PATH}/templates/" | grep -v "description"
else
  echo "  OK: Секреты не найдены"
fi

# 6. Проверка документации
echo "6. Проверка документации..."
if [ -f "${CATALOG_PATH}/README.md" ]; then
  echo "  OK: README.md существует"
  
  # Проверка наличия описаний для inputs
  for component in "${CATALOG_PATH}/templates/"*.yml; do
    if [ ! -f "${component}" ]; then
      continue
    fi
    
    INPUTS_COUNT=$(grep -c "type:" "${component}" || echo "0")
    DESCRIPTIONS_COUNT=$(grep -c "description:" "${component}" || echo "0")
    
    if [ ${INPUTS_COUNT} -gt ${DESCRIPTIONS_COUNT} ]; then
      echo "  ПРЕДУПРЕЖДЕНИЕ: $(basename ${component}) имеет inputs без описаний"
    fi
  done
else
  echo "  ОШИБКА: README.md отсутствует"
fi

echo "=== Диагностика завершена ==="
```

---

## Восстановление и очистка

### Откат миграции на компоненты

При проблемах после миграции с `include:project` на компоненты выполните откат:

```bash
# 1. Определение последнего рабочего коммита
LAST_GOOD=$(git log --oneline --grep="ci: migrate to components" -n 1 --format="%H")

# 2. Откат .gitlab-ci.yml
git revert --no-commit ${LAST_GOOD} -- .gitlab-ci.yml
git commit -m "revert: rollback component migration"
git push origin main

# 3. Верификация
glab ci config compile > expanded.yml
grep -q "component:" expanded.yml && echo "WARNING: components still present" || echo "OK: reverted to includes"
```

### Очистка неиспользуемых компонентов

Регулярно удаляйте неиспользуемые компоненты из каталога:

```bash
#!/bin/bash
# cleanup_unused_components.sh

CATALOG_PATH="${1:?Укажите путь к каталогу}"

echo "=== Очистка каталога компонентов ==="

# 1. Получение списка всех компонентов
COMPONENTS=$(find "${CATALOG_PATH}/templates/" -name "*.yml" | xargs -I {} basename {} .yml)

for component in ${COMPONENTS}; do
  echo "Проверка компонента: ${component}"
  
  # 2. Поиск проектов, использующих компонент
  USAGE=$(curl -s --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    "${GITLAB_URL}/api/v4/projects?search=${component}" | jq -r '.[].path_with_namespace')
  
  if [ -z "${USAGE}" ]; then
    echo "  Удаление неиспользуемого компонента: ${component}"
    rm "${CATALOG_PATH}/templates/${component}.yml"
  else
    echo "  Используется в: ${USAGE}"
  fi
done

echo "=== Очистка завершена ==="
```

### Очистка кэша Runner

При изменении компонентов убедитесь, что Runner использует актуальную конфигурацию:

```bash
# Перезапуск Runner для сброса кэша
gitlab-runner restart

# Очистка артефактов и кэша на Runner
gitlab-runner verify --delete
```

### Очистка тегов и артефактов

```bash
# Удаление устаревших тегов компонентов
git tag --list 'v*' | sort -V | head -n -5 | xargs -I {} git tag -d {}

# Очистка старых релизов
gitlab release list --per-page=100 | grep -v "latest" | awk '{print $1}' | tail -n +6 | \
  xargs -I {} gitlab release delete {}
```

---

## Особые случаи и ограничения

### Ограничения компонентов

| Ограничение | Значение | Версия GitLab | Архитектурный контекст |
| :--- | :--- | :--- | :--- |
| **Максимум компонентов на проект** | **100** | 18.5+ | Лимит на количество YAML-файлов в `templates/` проекта-ресурса. |
| **Лимит вложенности include** | **150** | Все | Суммарное количество узлов в дереве зависимостей `include`. |
| **Глубина цепочки компонентов** | **10** | Все | Лимит на последовательное подключение: `A -> B -> ... -> J`. |
| **Максимальное количество заданий** | **1000** | Все | Общий лимит `jobs` в одном пайплайне после раскрытия всех циклов. |
| **Размер одного YAML-файла** | **2 МБ** | 17.3+ (`max_yaml_size_bytes`) | Память, выделяемая на парсинг одного файла; настраивается администратором. |
| **Суммарный раскрытый YAML** | **314,6 МБ** | 17.3+ (`ci_max_total_yaml_size_bytes`) | 2 МБ × 150 включений; объём памяти под полную скомпилированную конфигурацию. |
| **Максимум входов (spec:inputs)** | **50** | 17.0+ | Лимит уникальных параметров в секции спецификации одного файла. |
| **Глубина наследования extends** | **11 уровней** | Все | Внутренняя константа `MAX_NESTING_LEVELS = 10`; рекомендуется ≤ 3–4. |

### Производительность

| Лимит | Влияние на производительность | Порог критичности |
| :--- | :--- | :--- |
| **150 include** | Каждый include увеличивает время компиляции пайплайна на 0.5–2 секунды. При 150 узлах задержка может достигать 5 минут. | > 100 узлов (67% от лимита) |
| **100 компонентов** | Большое количество компонентов замедляет обнаружение в каталоге и увеличивает время валидации. | > 70 компонентов (70% от лимита) |
| **1000 заданий** | Генерация более 500 заданий квадратично увеличивает время построения графа зависимостей. | > 500 заданий (50% от лимита) |

### Edge Cases

- **Циклические зависимости**: Компоненты не могут циклически зависеть друг от друга через `include`. GitLab обнаружит это на этапе компиляции и вернет ошибку.
- **Секреты в inputs**: Значения `inputs` видны в раскрытом YAML. Никогда не передавайте секреты через `spec:inputs`.
- **Глобальные ключи в компонентах**: Блоки `workflow:`, `default:`, `stages:` на верхнем уровне компонента игнорируются или вызывают ошибку. Перенесите их в корневой `.gitlab-ci.yml`.
- **Кэширование компонентов**: GitLab кэширует раскрытые компоненты на уровне инстанса. При обновлении компонента в каталоге существующие пайплайны могут использовать устаревшую версию до истечения TTL кэша.
- **Одновременное обновление**: При обновлении компонента, используемого сотнями проектов, все они увидят новую версию одновременно. Используйте canary-стратегию для постепенного внедрения.

---

## Справочная информация

### Чек-лист перед публикацией
- [ ] Секция `spec:inputs` заполнена и синтаксически верна.
- [ ] Добавлена валидация через `regex` или `options`.
- [ ] Компонент прошел проверку через `glab ci config compile`.
- [ ] Проект помечен как «Catalog resource».
- [ ] Создан релиз с тегом SemVer.
- [ ] Добавлены интеграционные тесты в папку `tests/`.
- [ ] Проведен canary-тест на 5% проектов.
- [ ] Экспортируются метрики в Prometheus.
- [ ] Есть процесс отката при сбоях.
- [ ] RFC согласован с командой.

### Чек-лист инцидент-менеджмента
- [ ] Определен уровень инцидента (1/2/3).
- [ ] Собрана информация о затронутых проектах.
- [ ] Проанализированы логи ошибок.
- [ ] Определена причина (баг/несовместимость/инфраструктура/пользователь).
- [ ] Выбрано действие (исправление/откат/эскалация).
- [ ] Уведомлены заинтересованные стороны.
- [ ] Задокументирован инцидент.

### Чек-лист мониторинга
- [ ] Настроен Prometheus Pushgateway.
- [ ] Экспортируются метрики использования.
- [ ] Экспортируются метрики времени загрузки.
- [ ] Настроены алерты в Alertmanager.
- [ ] Создан Grafana Dashboard.
- [ ] Мониторится SLA Impact.

### Внешние ресурсы
- [GitLab Docs: CI/CD Components advanced patterns](https://docs.gitlab.com/ee/ci/components/index.html)
- [GitLab Docs: Pipeline execution policies](https://docs.gitlab.com/ee/user/application_security/policies/pipeline_execution_policies.html)

### Связанные документы
- **[GitLab CI: Каталог компонентов](./ci_cd_catalog_components.md)** — база и синтаксис.
- **[Ограничения каталога компонентов](./ci_cd_catalog_limits.md)** — системные лимиты.
- **[Справочная информация по каталогу](./ci_cd_catalog_reference.md)** — API и CLI.
- **[Переиспользование: обзор](./overview.md)** — сравнение всех механизмов.
- **[Пример эволюции архитектуры](./evolution_example.md)** — полный пример миграции.
- **[Справочник: !reference и якоря YAML](./reference_and_yaml_anchors.md)** — альтернатива component chaining.
