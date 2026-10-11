# GitLab CI: Каталог компонентов

**Актуально для:** GitLab CI 19.x

## Определения

**Каталог компонентов (CI/CD Catalog)** — это системное решение GitLab для централизованного управления переиспользуемыми конфигурациями CI/CD. Он позволяет создавать версионируемые, типизированные и изолированные блоки логики, превращая фрагментарное копирование YAML-кода в потребление программных модулей с четко определенным интерфейсом.

**Компонент CI/CD** — автономный блок конфигурации (YAML-файл в директории `templates/`), обладающий собственной спецификацией входных данных и набором заданий. Компоненты могут быть опубликованы в каталоге для использования во всей организации.

**`spec:inputs`** — декларативное описание «публичного интерфейса» компонента. Оно определяет ожидаемые параметры, их типы данных (`string`, `number`, `boolean`, `array`), значения по умолчанию и правила строгой валидации.

**Интерполяция** — механизм динамической подстановки переданных значений параметров в конфигурацию через синтаксис `$[[ inputs.<name> ]]`. 
> **Важно:** Интерполяция происходит на этапе компиляции пайплайна **до** разрешения ключевых слов `variables` и `extends`. Это гарантирует, что значения входов будут доступны во всех частях конфигурации, включая условия `rules`.

**Supply Chain Security** — практики защиты цепочки поставок программного обеспечения, включающие верификацию целостности кода, управление зависимостями и контроль доступа к компонентам. В контексте каталога GitLab это Commit SHA верификация, Publication Allowlist и аудит безопасности.

**OIDC (OpenID Connect)** — протокол аутентификации, позволяющий компонентам получать временные токены для доступа к внешним сервисам (реестрами, хранилищам) без передачи статических секретов. Реализуется через `id_tokens` в заданиях.

## Основные концепции

### Сравнение компонентов и механизма `include`

Компоненты являются качественной эволюцией традиционного подхода `include:project`, предлагая расширенный контроль и безопасность.

| Критерий | `include:project` | CI/CD Catalog (Components) |
| :--- | :--- | :--- |
| **Версионирование** | Теги, ветки, SHA | **SemVer** (обязательно для публикации) |
| **Типизация** | Нет (только строки) | **Да** (`spec:inputs` с проверкой типов) |
| **Валидация** | Только синтаксис YAML | **Глубокая** (проверка контракта входов до запуска) |
| **Документация** | Ручная (README.md) | **Автоматическая** (генерация из спецификации в UI) |
| **Изоляция** | Средняя | **Высокая** (изолированные области видимости `$[[ ]]`) |
| **Безопасность** | Базовая | **Расширенная** (Commit SHA, Publication Allowlist, OIDC) |

### Архитектура и структура проекта

Для корректной работы механизмов поиска и публикации репозиторий должен следовать строгому стандарту иерархии:

```text
component-repo/
├── templates/
│   ├── build.yml          # Основной файл (вызов: .../component-repo/build)
│   ├── deploy.yml         # Дополнительный компонент (вызов: .../deploy)
│   └── security/
│       └── scan.yml       # Вложенный компонент (вызов: .../security/scan)
├── README.md              # Документация, отображаемая в интерфейсе каталога
├── tests/                 # Интеграционные тесты работоспособности (рекомендация)
└── .gitlab-ci.yml         # Пайплайн для тестирования и релиза самого компонента
```

**Рекомендации по структуре для DevOps/SRE:**

| Директория | Назначение | Рекомендации |
| :--- | :--- | :--- |
| `templates/` | Основные файлы компонентов | Максимум 100 файлов (лимит каталога). Используйте подпапки для группировки по функциональности. |
| `tests/` | Интеграционные тесты | Запускайте тесты с различными комбинациями `inputs`. Минимальное покрытие: happy path + edge cases + negative tests. |
| `docs/` | Дополнительная документация | API-контракты, примеры использования, известные ограничения, миграционные гайды. |
| `scripts/` | Вспомогательные скрипты | Валидация, генерация документации, интеграция с мониторингом, автоматизация публикации. |

### Синтаксис и возможности `spec:inputs`

Директива `spec:inputs` обеспечивает строгую типизацию и предотвращает передачу некорректных данных в инфраструктуру.

```yaml
spec:
  inputs:
    stage:
      default: test
      type: string
      description: "Стадия пайплайна, на которой запускается задание"
    environment:
      type: string
      default: dev
      options: [dev, staging, prod] # Ограничение выбора (UI dropdown)
    parallel_limit:
      type: number
      default: 1
    enable_feature:
      type: boolean
      default: false
    allowed_regions:
      type: array
      default: ["us-east-1", "eu-central-1"] # Поддержка массивов (v17.5+)
    version_tag:
      type: string
      regex: '^v\d+\.\d+\.\d+$' # Валидация через регулярные выражения
---
# Конец секции спецификации, далее следует реализация YAML
```

**Технические нюансы:**
- **Тип `array`**: Позволяет передавать списки значений для итерации в `parallel:matrix` или использования в `tags`.
- **`options`**: Превращает текстовое поле в выпадающий список при ручном запуске пайплайна в UI.
- **Обязательность**: Параметры без `default` являются обязательными; GitLab заблокирует создание пайплайна, если они не переданы.
- **Вложенная интерполяция**: Входы могут ссылаться на другие входы внутри блока `spec` (v17.7+).
- **Лимиты**: Максимум 50 входов на файл (17.0+), максимальный размер YAML 2 МБ (`max_yaml_size_bytes`, 17.3+).

### Жизненный цикл интерполяции (Resolution Order)

Понимание порядка обработки критично для отладки:
1.  **Разрешение `include`**: Собираются все файлы компонентов.
2.  **Интерполяция `inputs`**: Значения подставляются во все блоки YAML (включая `script`, `rules`, `variables`).
3.  **Обработка `variables`**: Разрешаются переменные (здесь уже можно использовать значения из `inputs`).
4.  **Разрешение `extends`**: Наследование выполняется над уже интерполированным YAML.

**Диагностические команды для проверки порядка разрешения:**

```bash
# Просмотр результата интерполяции
glab ci config compile

# Экспорт в файл для анализа
glab ci config compile > resolved.yml

# Проверка конкретного компонента
glab ci config compile | grep -A 10 "component-name"
```

### Интерполяция контекста компонента (v18.6+)

Компоненты имеют доступ к собственным метаданным без необходимости их явной передачи через `inputs`:

| Переменная | Описание | Пример значения |
| :--- | :--- | :--- |
| **`$[[ component.name ]]`** | Техническое имя текущего компонента. | `docker-build` |
| **`$[[ component.version ]]`** | Версия (тег или SHA), указанная при вызове. | `1.5.2` |
| **`$[[ component.sha ]]`** | Полный Commit SHA версии компонента. | `e3262fdb...` |

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
    - echo "Deploying component $[[ component.name ]] v$[[ component.version ]] to $[[ inputs.environment ]]"
    - |
      # Логирование для мониторинга
      curl -X POST "${METRICS_ENDPOINT}" \
        -H "Content-Type: application/json" \
        -d "{
          \"component\": \"$[[ component.name ]]\",
          \"version\": \"$[[ component.version ]]\",
          \"environment\": \"$[[ inputs.environment ]]\",
          \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        }"
    - kubectl apply -f manifests/
```

### Root-level `spec:inputs` (v17.11+)

Для создания глобальных форм ввода, доступных на уровне пайплайна (а не отдельного компонента), используется корневой уровень `spec:inputs`. Это позволяет создавать единые точки входа для всех компонентов пайплайна.

```yaml
# .gitlab-ci.yml (корневой уровень)
spec:
  inputs:
    environment:
      description: "Целевое окружение"
      options: ["staging", "production"]
      default: "staging"
    deploy_strategy:
      description: "Стратегия деплоя"
      options: ["rolling", "blue-green", "canary"]
      default: "rolling"
    deploy_version:
      description: "Версия компонента deploy"
      default: "v1.0.0"
---
# Далее конфигурация пайплайна
include:
  - component: $CI_SERVER_FQDN/org/deploy@$[[ inputs.deploy_version ]]
    inputs:
      environment: $[[ inputs.environment ]]
```

### Каскадные (зависимые) входы (v18.7+)

Интерфейс «Run Pipeline» поддерживает каскадные списки `inputs`. Значения в одном выпадающем списке могут фильтроваться на основе выбора в предыдущем, что упрощает настройку сложных систем развертывания.

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
    - kubectl config use-context $[[ inputs.cluster ]]
    - helm upgrade --install app ./charts --set env=$[[ inputs.environment ]]
```

---

## Практические сценарии

### Сценарий 1: Подключение компонента из официального каталога

Использование стандартных инструментов безопасности с фиксацией версии.

```yaml
include:
  - component: '$CI_SERVER_FQDN/group/security/secret-detection@1.0.0'
    inputs:
      stage: security
      scan_path: './src'
```

### Сценарий 2: Создание собственного Docker-компонента

Использование `id_tokens` (OIDC) для беспарольной аутентификации в реестре.

**Файл `templates/build.yml`:**
```yaml
spec:
  inputs:
    stage:
      default: build
    dockerfile:
      default: Dockerfile
---
build_image:
  stage: $[[ inputs.stage ]]
  image: docker:29.8
  services:
    - docker:29.8-dind
  id_tokens:
    SIGSTORE_ID_TOKEN:
      aud: sigstore
  script:
    - docker build -f $[[ inputs.dockerfile ]] -t $CI_REGISTRY_IMAGE:$[[ component.version ]] .
```

### Сценарий 3: Компонент для полного жизненного цикла (Multi-job)

Объединение связанных задач в один подключаемый блок с использованием `needs`.

```yaml
# templates/nodejs-pipeline.yml
spec:
  inputs:
    node_version:
      default: "22"
---
install:
  stage: .pre
  image: node:$[[ inputs.node_version ]]
  script:
    - npm ci

test:
  stage: test
  image: node:$[[ inputs.node_version ]]
  script:
    - npm test
  needs: [install]
```

### Сценарий 4: Управление стратегией обновлений (SemVer)

Выбор баланса между стабильностью и получением исправлений.

```yaml
include:
  # 1. Фиксация на патч-версии (рекомендуется для Production)
  - component: '$CI_SERVER_FQDN/org/tool@1.2.5'

  # 2. Мажорная версия (авто-обновление минорных версий и патчей)
  - component: '$CI_SERVER_FQDN/org/tool@1'

  # 3. Указатель на последний релиз (игнорирует пре-релизы)
  - component: '$CI_SERVER_FQDN/org/tool@~latest'
```

### Сценарий 5: Валидация входных данных через regex

Защита пайплайна от некорректных значений (например, лимитов ресурсов).

```yaml
spec:
  inputs:
    replicas:
      type: number
      regex: '^[1-5]$' # Ограничение от 1 до 5 экземпляров
---
deploy:
  script:
    - echo "Scaling to $[[ inputs.replicas ]] nodes"
```

### Сценарий 6: Вложенные компоненты (Nested Components)

Компоненты могут выступать оркестраторами других компонентов. **Важно:** автоматического проброса инпутов нет, всё передается явно.

```yaml
spec:
  inputs:
    image_tag:
      default: latest
---
include:
  - component: $[[ component.name ]]/security-scanners@$[[ component.version ]]
    inputs:
      severity_level: high

build_job:
  image: custom-builder:$[[ inputs.image_tag ]]
  script:
    - build.sh
```

### Сценарий 7: Тестирование компонентов в CI/CD

Для обеспечения качества компонентов необходимо автоматическое тестирование.

**Пайплайн тестирования в проекте каталога:**

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
        glab ci config compile > /dev/null 2>&1
        if [ $? -ne 0 ]; then
          echo "ОШИБКА: Тест не пройден для ${COMPONENT_NAME}"
          exit 1
        fi
      done
      
      echo "=== Все тесты пройдены ==="
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

---

## Безопасность компонентов

### Supply Chain Security

Защита цепочки поставок критична для компонентов, используемых во всей организации.

**Commit SHA верификация:**
```yaml
# Безопасное подключение (Защита от подмены тега)
include:
  - component: '$CI_SERVER_FQDN/org/security-scanner@a1b2c3d4e5f6'
    inputs:
      severity: high

# Небезопасное подключение (Теги можно перезаписать)
include:
  - component: '$CI_SERVER_FQDN/org/security-scanner@main'
```

**Publication Allowlist (v18.7+):**
Контроль доступа к публикации компонентов в корпоративный каталог.

```bash
# Настройка через API
curl --request PUT \
  --header "PRIVATE-TOKEN: <token>" \
  --data "ci_catalog_publication_allowlist=project_id_1,project_id_2" \
  "https://gitlab.example.com/api/v4/groups/:group_id/ci/catalog_publication_allowlist"
```

**Protected Tags:**
Защита тегов от непреднамеренной перезаписи.

```bash
# Настройка Protected Tags через API
curl --request POST \
  --header "PRIVATE-TOKEN: <token>" \
  --data "name=v*" \
  --data "create_access_level=40" \
  "https://gitlab.example.com/api/v4/projects/:id/protected_tags"
```

### OIDC аутентификация (id_tokens)

Для беспарольного доступа к внешним сервисам используйте `id_tokens`:

```yaml
# templates/build.yml
build_image:
  stage: build
  image: docker:29.8
  id_tokens:
    SIGSTORE_ID_TOKEN:
      aud: sigstore
    REGISTRY_TOKEN:
      aud: registry.example.com
  script:
    # Автоматическая аутентификация через OIDC
    - docker login registry.example.com -u oauth2token -p $REGISTRY_TOKEN
    - docker build -t registry.example.com/app:$CI_COMMIT_SHA .
    - docker push registry.example.com/app:$CI_COMMIT_SHA
```

### Pipeline Execution Policies (v17.x+)

Принудительное подключение компонентов на уровне группы/подгруппы:

```yaml
# Настройка Pipeline Execution Policy
# (через UI: Group -> Settings -> CI/CD -> Pipeline Execution Policies)
policy:
  name: "Security Scanner"
  description: "Обязательный сканер безопасности для всех проектов"
  pipeline_execution_policy:
    - project: "org/security-components"
      file: "templates/security-scan.yml"
      ref: "main"
      inputs:
        severity_level: "high"
      strategy: "replace"  # Или "merge" для дополнения
```

---

## Валидация и отладка

Для обеспечения качества компонентов используйте:
1.  **Pipeline Editor**: Вкладка «View merged YAML» — единственный способ увидеть результат интерполяции инпутов и контекста.
2.  **GitLab CLI (`glab`)**:
    ```bash
    # Валидация локальной конфигурации с раскрытием всех вложенностей
    glab ci config compile
    ```
3.  **UI Catalog**: Проверка отображения спецификации и README в реестре компонентов организации.

**Диагностический скрипт для отладки:**

```bash
#!/bin/bash
# diagnose_component.sh — диагностика проблем с компонентом

COMPONENT="${1:?Укажите имя компонента}"
VERSION="${2:-main}"
GITLAB_URL="${GITLAB_URL:-https://gitlab.example.com}"
TOKEN="${GITLAB_TOKEN}"

echo "=== Диагностика компонента ${COMPONENT}@${VERSION} ==="

# 1. Проверка доступности компонента
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

---

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Unknown input: 'X'` | Параметр используется в YAML, но не описан в `spec:inputs`. | Добавьте параметр в секцию `spec`. |
| `Input 'X' must match regex` | Значение нарушает правила валидации. | Проверьте входные данные на соответствие регулярному выражению. |
| `Component not found` | Неверный путь, отсутствие тега или проект не помечен как ресурс каталога. | Проверьте настройки «Catalog resource» в проекте и правильность пути. |
| `Duplicate job name` | Компонент определяет имя задания, которое уже есть в проекте. | Используйте `inputs` для префикса имени задания или уникальные имена. |
| `Component load timeout` | Превышение времени загрузки компонента. | Проверьте сетевую доступность и размер компонента. Рассмотрите кэширование. |
| `Version conflict` | Конфликт версий при резолвинге. | Используйте полные SemVer версии вместо частичных. |

---

## Особые случаи и ограничения

### Пустой `spec:` против `spec:inputs:`

GitLab возвращает `Build component error: Spec must be a valid json schema`, если блок `spec:inputs:` объявлен, но не содержит ни одного входа. Для компонента без входов используйте пустой `spec:`:

```yaml
# Правильно — компонент без входов
spec:
---
cleanup:
  stage: cleanup
  script:
    - rm -rf /tmp/*
```

### Вложенные компоненты и явная передача входов

При использовании `include:component` внутри `templates/` другого компонента входы не наследуются автоматически. Каждый вложенный компонент должен получить свои `inputs` явно.

### Коллизии имен заданий

Если несколько компонентов в одном пайплайне определяют задание с одинаковым именем (например, `test`), GitLab завершит пайплайн с `Duplicate job name`. Используйте вход `job_name_prefix` и интерполяцию `$[[ inputs.job_name_prefix ]]_test` для уникальности.

### Размер и глубина

- Один файл компонента: максимум 2 МБ (`max_yaml_size_bytes`, 17.3+).
- Максимум 50 входов (`spec:inputs`) на один файл (17.0+).
- Максимум 20 входов верхнего уровня у пайплайна, включая `spec:inputs` корневых компонентов.
- Максимум 150 узлов `include` в раскрытом пайплайне; итоговый размер 314,6 МБ (`ci_max_total_yaml_size_bytes`, 17.3+).

### Сетевые сбои при загрузке компонентов

GitLab кэширует компоненты на уровне инстанса. При недоступности проекта-каталога пайплайн потребителя завершится ошибкой. Для минимизации рисков используйте внутренний URL проекта-каталога на Self-Managed инстансах.

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

### Безопасная миграция компонентов

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

---

## Best Practices

### Проектирование интерфейсов компонентов

- **Single Responsibility.** Один компонент решает одну задачу. Разделите `build`, `test`, `deploy` на отдельные компоненты.
- **Явный контракт.** Все входы должны иметь `description`. Используйте `options` вместо свободного текста там, где возможен фиксированный набор значений.
- **Минимизация `default:`.** `default:` удобны, но скрывают зависимость. Документируйте, почему значение выбрано именно так.
- **Без side effects.** Компонент не должен полагаться на глобальные переменные (`variables:`, `default:`) или изменять состояние за пределами своих заданий.

### Управление версиями

- **SemVer для всех публичных компонентов.** Major-версия = breaking change контракта (`spec:inputs`).
- **Фиксируйте production на SHA.** Теги (`v1.0.0`) удобны, но уязвимы для перезаписи. Для production пайплайнов используйте полный SHA.
- **Release notes.** Каждый релиз должен содержать: что изменилось, как мигрировать, известные ограничения.

### Тестирование

- **Contract testing.** Тестируйте, что компонент падает с понятной ошибкой при невалидном `input`.
- **Integration-тесты.** Запускайте компонент в реальном пайплайне через `glab ci config compile`.
- **Negative tests.** Убедитесь, что невалидный `regex` или `options` отклоняются на этапе CI Lint, а не во время выполнения задания.

### Governance

Для организационных политик (владелец каталога, CAB, deprecation policy, audit trail, canary-раскатка) см.:
- **[Справочная информация по компонентам](./ci_cd_catalog_reference.md)** — раздел Best Practices.

---

## Чек-листы

### Чек-лист публикации компонента

- [ ] Секция `spec:inputs` заполнена и синтаксически верна
- [ ] Добавлена валидация через `regex` или `options` для критических параметров
- [ ] Каждый `input` имеет поле `description`
- [ ] Компонент прошёл проверку через `glab ci config compile`
- [ ] Проект помечен как «Catalog resource»
- [ ] Создан релиз с тегом SemVer (например, `v1.0.0`)
- [ ] README.md содержит документацию по использованию
- [ ] Добавлены тесты в директорию `tests/`
- [ ] Проверены все внутренние ссылки

### Чек-лист безопасности компонента

- [ ] Используется Commit SHA для критических компонентов
- [ ] Настроен Publication Allowlist
- [ ] Настроены Protected Tags
- [ ] Регулярный аудит уязвимостей
- [ ] Проверка Supply Chain безопасности
- [ ] Логирование всех изменений версий

---

## Дополнительная информация

- **Версионирование**: Для публикации обязателен SemVer. Проект должен иметь статус «Catalog resource» в настройках General -> Visibility.
- **Будущее (GitLab Steps)**: Начиная с GitLab 19.0, вводится механизм **GitLab Steps**. Это Stage 6 эволюции, позволяющий переиспользовать конкретные шаги внутри задания с полной контейнерной изоляцией, минимизируя использование Bash-скриптов.

### Полезные ссылки

- **[Ограничения каталога](./ci_cd_catalog_limits.md)** — лимиты вложенности и запрещённые ключи.
- **[Справочная информация](./ci_cd_catalog_reference.md)** — API, команды CLI и детальная история изменений.
- **[Продвинутые сценарии](./ci_cd_catalog_advanced_scenarios.md)** — миграция и сложные цепочки.
- **[Механизм include](./include_keyword.md)** — база для всех типов подключений.
- **[Модель зрелости CI/CD](./evolution_example.md)** — сравнение подходов и сценарии миграции.
