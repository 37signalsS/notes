# Валидация и версионирование пайплайнов GitLab CI/CD

**Актуально для:** GitLab 19.x / GitLab Runner 19.x

## Определения

**Валидация пайплайнов** — комплексный процесс проверки синтаксиса (YAML Lint), логической целостности (DAG, зависимости) и контекстуальной корректности конфигурации. Выполняется на нескольких уровнях: от локальной проверки в IDE до серверной валидации через API.

**CI Lint API (Dry Run)** — метод глубокой валидации (GitLab 16.11+), имитирующий создание пайплайна. Проверяет не только синтаксис, но и права доступа, наличие образов, существование артефактов и корректность `rules` в контексте конкретной ветки или события. Отличается от базовой проверки синтаксиса тем, что раскрывает все `include`, `extends`, `!reference` и интерполирует `inputs`.

**Валидация входных параметров (Inputs Validation)** — процесс проверки типов и значений, передаваемых в компонент через `spec:inputs`. Ошибка возникает при несоответствии типа (string/number/boolean) или при отсутствии обязательного параметра. Проверяется через `glab ci lint --dry-run` с подстановкой тестовых значений.

**Batch-валидация** — автоматизированная проверка конфигурации на нескольких ветках или в нескольких проектах одновременно. Используется для выявления регрессий при обновлении общих шаблонов и для проверки совместимости с различными контекстами (ветки, MR-события, теги).

**MR-based валидация** — валидация конфигурации пайплайна в контексте Merge Request, включая проверку `rules` для MR-событий, валидацию target-ветки и проверку доступа через `CI_JOB_TOKEN`. Основной инструмент для предотвращения слияния сломанных конфигураций.

**Версионирование шаблонов (Infrastructure as Code)** — практика применения фиксированных меток (теги SemVer, commit SHA) к подключаемым YAML-ресурсам для предотвращения каскадных сбоев при обновлении инструментов.

**Pipeline Execution Policies** — корпоративный механизм (GitLab 19.x) для принудительного внедрения задач безопасности и комплаенса, которые невозможно пропустить или переопределить на уровне проекта.

**Validation Gates** — промежуточные проверки внутри пайплайна, блокирующие дальнейшее выполнение (например, деплой) при обнаружении логических ошибок в сгенерированных конфигурациях.

## Предварительные требования

- **GitLab 19.x** — требуется для доступа к полному функционалу CI Lint API с поддержкой `dry_run: true` (доступен с 16.11+), Pipeline Execution Policies и компонентов CI/CD Catalog.
- **GitLab Runner 19.x** — исполнитель пайплайнов, на котором запускаются задачи валидации.
- **GitLab CLI (`glab`) 2.x+** — инструмент для локальной валидации, компиляции конфигурации и dry-run без коммита.
- **curl и jq** — для прямого вызова CI Lint API из скриптов и автоматизации.
- **yamllint** — для статической проверки синтаксиса YAML на этапе pre-commit.
- **Права доступа** — PAT или `CI_JOB_TOKEN` с областью `api` для вызова CI Lint API из пайплайна.
- **Доступ к GitLab API** — URL сервера (`CI_API_V4_URL`) и токен должны быть доступны в окружении валидации.

## Основные концепции

### Иерархия валидации

Проверка конфигурации должна выполняться на нескольких уровнях. Чем раньше обнаружена ошибка, тем дешевле её исправление.

| Уровень | Инструмент | Что проверяется | Когда выполнять |
| :--- | :--- | :--- | :--- |
| **1. IDE** | Плагины RedHat YAML, GitLab Workflow | Синтаксис YAML, базовая схема GitLab CI | При написании |
| **2. Pre-commit** | `yamllint`, `glab ci lint` | Синтаксис + синтаксическая валидация CI | Перед коммитом |
| **3. CI Pipeline** | `glab ci lint --dry-run` | Логика `rules`, `needs`, интерполяция переменных | В пайплайне (`.pre` стадия) |
| **4. Server** | CI Lint API (`POST /ci/lint`) | Полная валидация с правами доступа, образами, артефактами | При создании MR |
| **5. MR Gate** | CI Lint в MR pipeline | Валидация в контексте target-ветки и MR-события | До слияния |
| **6. Runtime** | Дочерние пайплайны | Валидация динамически генерируемых конфигураций | Перед запуском bridge |

**Принцип:** Не пропускайте уровни. Pre-commit не заменяет CI Lint API (нет проверки прав), а CI Lint API не заменяет runtime-валидацию дочерних пайплайнов.

### Стратегии версионирования и их риски

| Стратегия | Пример (`ref`) | Стабильность | Гибкость | Рекомендация 2026 |
| :--- | :--- | :--- | :--- | :--- |
| **Commit SHA** | `abcdef12` | Максимальная | Нулевая | Для критической инфраструктуры (Bank/Fintech) |
| **SemVer (Full)** | `v1.2.3` | Высокая | Низкая | Стандарт для CI/CD Catalog компонентов |
| **SemVer (Minor)** | `v1.2` | Средняя | Средняя | Получение патчей безопасности автоматически |
| **Static Branch** | `main` / `stable` | Низкая | Высокая | **Запрещено** для Production (риск каскадного падения) |

**Миграция между стратегиями:**

При переходе с `static branch` на SemVer необходимо:
1. Зафиксировать текущее состояние тегом (`v1.0.0`)
2. Обновить все `include:project: ref:` в потребителях
3. Настроить CI Lint в MR для проверки совместимости
4. Использовать Canary-обновление (см. Сценарий 2)

## Практические сценарии

### Сценарий 1: Продвинутая валидация через Lint API (Dry Run)

Использование `dry_run: true` позволяет проверить логику `rules` и `needs` до запуска тяжелых задач.

```yaml
validate_pipeline_logic:
  stage: .pre
  image: alpine:3.24.2
  script:
    - apk add --no-cache curl jq
    - |
      # Кодируем содержимое текущего файла в JSON
      content=$(cat .gitlab-ci.yml)
      data=$(jq --null-input --arg yaml "$content" '{content: $yaml, dry_run: true, project_id: $CI_PROJECT_ID}')
      
      response=$(curl --fail -sS \
            --header "PRIVATE-TOKEN: ${CI_API_V4_TOKEN}" \
            --header "Content-Type: application/json" \
            --data "$data" \
            "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/ci/lint")
      
      if [[ $(echo "$response" | jq '.valid') != "true" ]]; then
        echo "Pipeline logic error in branch ${CI_COMMIT_REF_NAME}:"
        echo "$response" | jq -r '.errors[]'
        exit 1
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Ожидаемый результат при успехе:**
```json
{"valid": true, "errors": [], "warnings": []}
```

**Ожидаемый результат при ошибке:**
```json
{
  "valid": false,
  "errors": [
    "job `deploy`: `rules` syntax error: `if` clause is empty",
    "job `test`: dependency `build` does not exist"
  ]
}
```

**Важно:** Параметр `dry_run: true` доступен с GitLab 16.11+. Без него API выполняет только синтаксическую проверку без проверки логики `rules`.

### Сценарий 2: Canary Rollout для CI-шаблонов

Метод плавного обновления общих пайплайнов компании, чтобы не сломать все проекты одновременно.

```yaml
include:
  - project: 'ops/ci-library'
    file: '/templates/base.yml'
    # Используем переменную для управления версией
    ref: $CI_TEMPLATE_VERSION

variables:
  # По умолчанию используем стабильную версию
  CI_TEMPLATE_VERSION: "v2.5.0"

# В экспериментальных ветках или для отдельных групп включаем Canary
workflow:
  rules:
    - if: '$CI_PROJECT_NAMESPACE =~ /^canary-testers\//'
      variables:
        CI_TEMPLATE_VERSION: "v2.6.0-rc1"
    - when: always
```

### Сценарий 3: Локальная отладка через `glab` (v19.x)

Инструмент `glab` позволяет диагностировать проблемы наследования и интерполяции `inputs` без коммита.

```bash
# 1. Проверка синтаксиса с имитацией переменных MR
glab ci lint --dry-run --variable CI_PIPELINE_SOURCE=merge_request_event
      # 2. Получение финального YAML со всеми разрешенными !reference и extends

      glab ci config compile > processed-config.yml

# 3. Валидация конкретного файла (например, сгенерированного скриптом)
glab ci lint path/to/generated-ci.yml
```

**Интеграция с pre-commit:**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: gitlab-ci-lint
        name: GitLab CI Lint
        entry: glab ci lint
        language: system
        files: '\.gitlab-ci\.yml$'
        pass_filenames: false
```

**Ожидаемый результат `glab ci lint`:**
```
✓ CI Lint passed
```

**Ожидаемый результат `glab ci config compile`:**
```yaml
# Полный YAML после обработки всех include, extends, !reference, inputs
stages:
  - build
  - test
# ... (все развернутые задания)
```

### Сценарий 4: Принудительное исполнение политик (Scheduled Policies)

Настройка политик безопасности на уровне группы для регулярного аудита.

1.  Создайте проект `security-policies` в вашей группе.
2.  В проекте настройте `policy.yml`:
    ```yaml
    scan_execution_policy:
      - name: Weekly Security Audit
        enabled: true
        rules:
          - type: schedule
            cadence: "0 0 * * 0" # Каждое воскресенье
        actions:
          - scan: secret_detection
          - scan: container_scanning
    ```

### Сценарий 5: Pre-commit hooks для валидации CI

Интеграция локальной валидации в Git-хуки для автоматической проверки перед каждым коммитом.

**Установка зависимостей:**

```bash
# macOS
brew install yamllint glab

# Linux (Debian/Ubuntu)
pip install yamllint
# glab — см. https://gitlab.com/gitlab-org/cli/-/releases
```

**Конфигурация yamllint (`.yamllint`):**

```yaml
extends: default

rules:
  line-length:
    max: 200
    allow-non-breakable-words: true
    allow-non-breakable-inline-mappings: true
  truthy:
    allowed-values: ['true', 'false', 'on']
  comments:
    min-spaces-from-content: 1
  document-start: disable
```

**Pre-commit hook (`.git/hooks/pre-commit`):**

```bash
#!/bin/bash
set -euo pipefail

# Проверяем только изменённые YAML-файлы
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.(yml|yaml)$' || true)

if [ -z "$STAGED_FILES" ]; then
  exit 0
fi

echo "=== Валидация YAML ==="
for file in $STAGED_FILES; do
  echo "Проверка: $file"
  yamllint -d relaxed "$file" || exit 1
done

# Если изменён .gitlab-ci.yml — запускаем glab ci lint
CI_FILES=$(echo "$STAGED_FILES" | grep '\.gitlab-ci\.yml$' || true)
if [ -n "$CI_FILES" ]; then
  echo "=== Валидация GitLab CI ==="
  glab ci lint || exit 1
fi

echo "✓ Все проверки пройдены"
```

**Ожидаемый результат:**
```
=== Валидация YAML ===
Проверка: .gitlab-ci.yml
=== Валидация GitLab CI ===
✓ CI Lint passed
✓ Все проверки пройдены
```

### Сценарий 6: Batch-валидация всех веток

Проверка конфигурации на нескольких ветках для выявления регрессий при обновлении общих шаблонов.

```bash
#!/bin/bash
set -euo pipefail

BRANCHES=("main" "develop" "staging" "release/v2.0")
VARIABLES=("CI_COMMIT_BRANCH" "CI_PIPELINE_SOURCE")

echo "=== Batch-валидация пайплайна ==="
FAILED=0

for BRANCH in "${BRANCHES[@]}"; do
  echo "--- Ветка: $BRANCH ---"
  
  # Базовая валидация
  if ! glab ci lint --dry-run --variable "CI_COMMIT_BRANCH=$BRANCH" 2>/dev/null; then
    echo "ОШИБКА: Валидация не пройдена для ветки $BRANCH"
    FAILED=$((FAILED + 1))
    continue
  fi
  
  # MR-валидация (имитация merge request)
  if ! glab ci lint --dry-run \
    --variable "CI_PIPELINE_SOURCE=merge_request_event" \
    --variable "CI_MERGE_REQUEST_TARGET_BRANCH_NAME=$BRANCH" 2>/dev/null; then
    echo "ОШИБКА: MR-валидация не пройдена для target=$BRANCH"
    FAILED=$((FAILED + 1))
  fi
done

if [ $FAILED -gt 0 ]; then
  echo "=== ПРОВАЛЕНО: $FAILED ошибок ==="
  exit 1
fi

echo "=== Все ветки прошли валидацию ==="
```

**Использование в CI-пайплайне:**

```yaml
batch_validate:
  stage: .pre
  image: registry.gitlab.com/gitlab-org/cli:latest
  script:
    - ./scripts/batch_validate.sh
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 7: MR-based валидация с quality gates

Настройка的质量门 (quality gates) в Merge Request для блокирования слияния сломанных конфигураций.

```yaml
validate_mr_config:
  stage: .pre
  image: registry.gitlab.com/gitlab-org/cli:latest
  script:
    - |
      echo "=== MR Quality Gate: CI Config Validation ==="
      
      # 1. Базовая валидация
      if ! glab ci lint; then
        echo "ОШИБКА: CI Lint не пройден"
        exit 1
      fi
      
      # 2. Dry Run с контекстом MR
      if ! glab ci lint --dry-run \
        --variable CI_PIPELINE_SOURCE=merge_request_event \
        --variable CI_MERGE_REQUEST_TARGET_BRANCH_NAME=$CI_MERGE_REQUEST_TARGET_BRANCH_NAME; then
        echo "ОШИБКА: Dry Run не пройден для target=$CI_MERGE_REQUEST_TARGET_BRANCH_NAME"
        exit 1
      fi
      # 3. Проверка expand (все include/extends развернуты)

      glab ci config compile > /tmp/expanded.yml
      YAML_SIZE=$(wc -c < /tmp/expanded.yml)
      if [ "$YAML_SIZE" -gt 5242880 ]; then
        echo "ОШИБКА: Expanded YAML превышает 5 МБ ($YAML_SIZE bytes)"
        exit 1
      fi
      
      echo "✓ Quality Gate пройден"
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Настройка Protected Branch:**

В `Settings > Repository > Protected branches` настройте защиту ветки `main`:
- **Allowed to merge:** Maintainers
- **Allowed to push:** No one (только через MR)
- **Require approval from code owners:** Включить

Это гарантирует, что каждый MR пройдёт quality gate перед слиянием.

## Устранение неполадок (Troubleshooting)

### Типичные ошибки

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **`Circular dependency detected`** | Задачи A и B зависят друг от друга (напрямую или через цепочку) | Используйте `stages` для разделения; проверьте DAG в Pipeline Editor |
| **`Included file not found`** | Ошибка в путях `include:local` или нет прав у `CI_JOB_TOKEN` для `include:project` | Проверьте Visibility проекта и настройки Token Access |
| **`Input validation failed`** | Параметр не соответствует типу в `spec:inputs` | Проверьте `merged YAML` в Pipeline Editor; убедитесь что типы совпадают |
| **`Empty pipeline error`** | Все задачи отфильтрованы через `rules` | Добавьте placeholder-задачу или исправьте `workflow:rules` |
| **`Dry run not supported`** | GitLab < 16.11 или не передан `dry_run: true` | Обновите GitLab или добавьте `dry_run: true` в тело запроса |
| **`Too many includes`** | Дерево импортов > 150 узлов | Объедините мелкие файлы; используйте `!reference` вместо `include:local` |
| **`Maximum levels of inheritance`** | Глубина `extends` > 11 | Упростите иерархию шаблонов (рекомендуется 3-4 уровня) |
| **`Expanded YAML too large`** | Итоговый конфиг > 5 МБ | Сократите комментарии; используйте `extends` вместо копирования блоков |
| **`Component not found`** | Неверный путь или нет тега в `include:component` | Проверьте имя компонента и версию; используйте SemVer-тег |
| **`glab: not found`** | `glab` не установлен в образе | Используйте `registry.gitlab.com/gitlab-org/cli:latest` или установите в `before_script` |

### Инструменты диагностики

- **Pipeline Editor (Merged YAML):** Главный инструмент для понимания того, что "видит" сервер. Доступен через `CI/CD > Editor`.
- **Variables Trace:** Используйте `export` в тестовой задаче для проверки итогового значения версий шаблонов.
- **CI Lint API:** Прямой вызов API для проверки конфигурации вне контекста пайплайна.
- **glab ci config compile:** Просмотр полного YAML после обработки всех include, extends, !reference.

```bash
# Просмотр всех переменных с указанием источника
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/pipelines/${CI_PIPELINE_ID}/variables" | \
  jq '.[] | {key, value, protected, masked}'

# Проверка merged YAML через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/merge_requests/${MR_IID}/ci_config"
```

### Диагностический скрипт

Полная проверка всех компонентов валидации:

```bash
#!/bin/bash
set -euo pipefail

echo "=== Diagnostics: Pipeline Validation ==="

echo "--- 1. Проверка yamllint ---"
if command -v yamllint &>/dev/null; then
  yamllint -d relaxed .gitlab-ci.yml && echo "  OK" || echo "  ОШИБКА"
else
  echo "  yamllint не установлен"
fi

echo "--- 2. Проверка glab ci lint ---"
if command -v glab &>/dev/null; then
  glab ci lint && echo "  OK" || echo "  ОШИБКА"
else
  echo "  glab не установлен"
fi

echo "--- 3. Проверка glab ci config compile ---"
if command -v glab &>/dev/null; then
  glab ci config compile > /tmp/expanded.yml 2>/dev/null
  YAML_SIZE=$(wc -c < /tmp/expanded.yml)
  echo "  Размер expanded YAML: ${YAML_SIZE} bytes"
  if [ "$YAML_SIZE" -gt 5242880 ]; then
    echo "  ОШИБКА: Превышен лимит 5 МБ"
  else
    echo "  OK"
  fi
fi

echo "--- 4. Проверка лимитов ---"
if command -v glab &>/dev/null; then
  INCLUDE_COUNT=$(grep -c "include:" .gitlab-ci.yml 2>/dev/null || echo "0")
  echo "  Количество include: $INCLUDE_COUNT (лимит: 150)"
fi

echo "--- 5. Проверка версии GitLab ---"
if [ -n "${CI_SERVER_VERSION:-}" ]; then
  echo "  GitLab версия: $CI_SERVER_VERSION"
else
  echo "  Не в CI окружении"
fi

echo "=== Диагностика завершена ==="
```

## Edge cases и ограничения

| Ограничение | Описание | Решение |
| :--- | :--- | :--- |
| **CI Lint без `dry_run`** | Без `dry_run: true` API проверяет только синтаксис, не логику `rules` | Всегда передавайте `dry_run: true` для проверки логики |
| **CI Lint API и `include:remote`** | API не может скачать удалённые файлы без доступа к сети GitLab Runner | Убедитесь, что Runner имеет доступ к GitLab URL |
| **glab и `inputs`** | `glab ci lint --dry-run` не интерполирует `inputs` без явной передачи | Передавайте `--variable` для всех обязательных inputs |
| **Batch-валидация и protected variables** | Protected переменные недоступны в `--dry-run` | Используйте `CI_JOB_TOKEN` или PAT вместо protected переменных |
| **Expanded YAML и комментарии** | Комментарии сохраняются в expanded YAML, увеличивая размер | Удаляйте комментарии из шаблонов или используйте `extends` |
| **MR-валидация и target branch** | `rules: if` проверяется относительно target-ветки, не source | Имитируйте `CI_MERGE_REQUEST_TARGET_BRANCH_NAME` при batch-валидации |
| **Pre-commit и `include:project`** | Pre-commit не может проверить `include:project` без доступа к GitLab | Используйте CI Lint API в pre-commit hook вместо локального glab |
| **Runtime-валидация bridge jobs** | Дочерние пайплайны не валидируются родительским CI Lint | Добавьте CI Lint в `.pre` стадию дочернего пайплайна |
| **`yamllint` и GitLab CI YAML** | Стандартные правила yamllint могут ругаться на GitLab CI specific syntax | Используйте `-d relaxed` или настройте `.yamllint` |

## Лучшие практики

### SRE-ориентированные практики

- **Метрики валидации:** Отслеживайте долю успешных валидаций (`validation_success_rate`). Алерт при падении ниже 95% за 24 часа — это указывает на регрессию в шаблонах или сбой CI Lint API.
- **Детект дрейфа конфигурации:** Храните `expanded.yml` артефактом в `.pre` стадии и сравнивайте с baseline. Расхождения >5% должны запускать review.
- **Изоляция валидации Production:** Запускайте валидацию Production-пайплайнов в отдельной группе с повышенными правами. Это предотвращает утечку секретов и каскадные сбои.
- **Fallback при недоступности CI Lint:** Если API недоступен (5xx/timeout), разрешайте merge только после ручного approval. Настройте `EXTERNAL_VALIDATION_SERVICE_TIMEOUT` на адекватное значение (по умолчанию 5 секунд).
- **Аудит изменений:** Включите audit log для `.gitlab-ci.yml` и шаблонов. Каждое изменение должно иметь traceable author и MR IID.

### SysAdmin-ориентированные практики

- **Резервное копирование конфигурации:** Архивируйте `.gitlab-ci.yml` и все `include`-файлы в отдельный репозиторий с триггером на каждый push. Это обеспечивает точку отката при деградации шаблонов.
- **Управление токенами:** Ротируйте PAT, используемые для CI Lint API, каждые 90 дней. Храните их в Vault или GitLab CI/CD Variables с флагом `protected`.
- **Логирование валидации:** Включайте логи CI Lint API (`gitlab_workhorse` и `gitlab-rails`) с уровнем `info` для аудита. Храните логи минимум 90 дней.
- **Ограничение ресурсов валидации:** Ограничьте время выполнения задачи валидации (например, `timeout: 10m`), чтобы зависший CI Lint не блокировал очередь Runner'ов.
- **Верификация после обновления GitLab:** После каждого minor-обновления GitLab запускайте batch-валидацию всех критических пайплайнов. Недостаточная валидация после обновления — частая причина каскадных сбоев.

### Проверка корректности валидации

- **Success rate:** `successful_validations / total_validations`. Цель: > 95%.
- **Expanded YAML growth:** Сравнивайте размер `expanded.yml` между коммитами. Рост >20% без соразмерного увеличения функциональности — признак неконтролируемого роста конфигурации.
- **Время валидации:** Измеряйте latency CI Lint API. Цель: < 3 секунды для типовых конфигураций. Рост latency указывает на перегрузку shared runners или слишком большое дерево `include`.

## Дополнительная информация

### См. также

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — база и глоссарий.
- **[Директивы и определения](./workflow_rules/directives_definitions.md)** — синтаксис директив, лимиты, edge cases.
- **[Отладка и устранение неполадок](./debugging_and_troubleshooting.md)** — методы отладки пайплайнов.
