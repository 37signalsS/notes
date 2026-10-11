# Локальное тестирование GitLab CI конфигураций: gitlab-ci-local

**Актуально для:** GitLab 19.x, gitlab-ci-local 4.75.x (firecow/gitlab-ci-local)

## Определения

**gitlab-ci-local** — CLI-инструмент для локального выполнения и валидации `.gitlab-ci.yml` файлов без отправки их в GitLab. Разрабатывается в репозитории `firecow/gitlab-ci-local`. Позволяет разработчикам проверять пайплайны на правильность конфигурации, переменных и `rules` до коммита.

**Local CI runner** — исполнение задач GitLab CI в локальной среде (Docker, Shell) с использованием `gitlab-ci-local`.

**Mock variables** — подстановка тестовых значений переменных для имитации контекста CI/CD (ветка, событие MR, protected ветки).

**Staged rollout** — постепенное внедрение изменений в пайплайнах: canary-тестирование конфигурации на подмножестве проектов/веток перед полным rollout.

## Основные концепции

### Архитектура gitlab-ci-local

Инструмент работает в трех фазах:

1.  **Парсинг:** Читает `.gitlab-ci.yml`, раскрывает все `include`, `extends`, `!reference` и `spec:inputs`.
2.  **Валидация:** Проверяет синтаксис YAML, типы `inputs`, существование образов (опционально через `docker pull`).
3.  **Execution (опционально):** Запускает задачи в локальных Docker-контейнерах или Shell-окружении.

### Сравнение с glab ci lint и gitlab-runner exec

| Характеристика | gitlab-ci-local | glab ci lint | gitlab-runner exec |
| :--- | :--- | :--- | :--- |
| **Локальное выполнение** | Да (Docker/Shell) | Нет (только валидация через API) | Да (Docker/Shell) |
| **Валидация синтаксиса** | Да | Да | Нет (ожидает рабочий .gitlab-ci.yml) |
| **Валидация `rules`** | Частично (без контекста GitLab) | Да (`--dry-run` с контекстом) | Нет |
| **Валидация `spec:inputs`** | Да | Да (`--variable`) | Нет |
| **Выполнение скриптов** | Да (локально) | Нет | Да (локально, ближе к GitLab Runner) |
| **Зависимость от GitLab** | Нет (полностью офлайн) | Да (нужен доступ к API) | Нет |
| **Имитация `needs`** | Да (локальный DAG) | Нет | Частично (зависимости не запускаются автоматически) |
| **Конфигурация Runner'а** | Нет (использует Docker/Shell напрямую) | Нет | Да (читает config.toml) |
| **Скорость** | Быстро (офлайн) | Зависит от сети и API | Средне (ближе к реальному Runner'у) |
| **Артефакты/кэш** | Локальные | Нет | Локальные (Docker volumes) |

**Рекомендация:** Используйте `gitlab-ci-local` для быстрой локальной проверки конфигурации и `glab ci lint --dry-run` для проверки в контексте конкретного проекта/ветки. `gitlab-runner exec` полезен для отладки поведения, идентичного production Runner'у, особенно при работе с сервисными контейнерами и кэшем.

### Ключевые возможности

- **Локальное выполнение задач:** Запуск `.gitlab-ci.yml` задач в Docker-контейнерах с теми же образами, что и в GitLab.
- **Валидация конфигурации:** Проверка синтаксиса, типов `inputs`, наличия образов.
- **Имитация переменных:** Подстановка любых переменных через флаг `-v` или `.gitlab-ci.local.yml`.
- **Фильтрация задач:** Запуск только определенных задач через `--job`.
- **Интеграция с pre-commit:** Автоматическая валидация перед коммитом.

## Практические сценарии

### Сценарий 1: Установка и базовая валидация

**Установка (macOS/Linux):**
```bash
# macOS (Homebrew stable 4.75.1)
brew install gitlab-ci-local

# Linux (npm, cross-platform)
npm install -g gitlab-ci-local

# Linux (Nix)
nix profile install nixpkgs#gitlab-ci-local

# Или через go install (требует Go 1.21+)
go install github.com/firecow/gitlab-ci-local@latest

# Linux (Debian/Ubuntu, официальный скрипт)
curl -sSfL https://raw.githubusercontent.com/firecow/gitlab-ci-local/main/install.sh | sh

# Arch Linux (AUR)
paru -S gitlab-ci-local
```

**Базовая валидация `.gitlab-ci.yml`:**
```bash
# В корне репозитория
gitlab-ci-local

# Ожидаемый вывод:
# ✔ build (build) 5.2s
# ✔ test (test) 3.1s
# ✔ deploy (deploy) 2.8s
```

**Валидация без выполнения (dry-run):**
```bash
gitlab-ci-local --list
# → Выводит список задач без запуска
```

### Сценарий 2: Имитация контекста CI/CD

**Подстановка переменных:**
```bash
# Имитация MR-события
gitlab-ci-local -v CI_PIPELINE_SOURCE=merge_request_event \
                -v CI_COMMIT_BRANCH=feature-branch \
                -v CI_MERGE_REQUEST_TARGET_BRANCH_NAME=main \
                --job test

# Имитация protected branch
gitlab-ci-local -v CI_COMMIT_REF_PROTECTED=true \
                -v CI_COMMIT_BRANCH=main \
                --job deploy
```

### Файл `.gitlab-ci.local.yml`

`gitlab-ci-local` автоматически подхватывает файл `.gitlab-ci.local.yml` из корня репозитория для переопределения переменных и конфигурации. Файл не требуется коммитить в репозиторий.

```yaml
# .gitlab-ci.local.yml
variables:
  CI_PROJECT_ID: "12345"
  CI_API_V4_URL: "https://gitlab.example.com/api/v4"
  CI_COMMIT_BRANCH: "main"
  CI_PIPELINE_SOURCE: "push"
  CI_REGISTRY: "registry.example.com"
  CI_REGISTRY_USER: "ci-bot"
  CI_JOB_TOKEN: "test-token"
  ENVIRONMENT: "local"
```

**Приоритет переменных:**
1. CLI-флаг `-v KEY=VALUE` (наивысший приоритет)
2. Переменные из `.gitlab-ci.local.yml`
3. Переменные из `.gitlab-ci.yml`
4. Встроенные переменные GitLab CI (по умолчанию мокируются)

**Безопасность:** Добавьте `.gitlab-ci.local.yml` в `.gitignore`, если файл содержит тестовые секреты. Не храните реальные credentials в этом файле.

### Конфигурация Docker Executor

При использовании Docker executor `gitlab-ci-local` создает сеть bridge для каждого запуска. Настройки по умолчанию:

| Параметр | Значение по умолчанию | Примечание |
| :--- | :--- | :--- |
| **Сеть** | `gitlab-ci-local-<hash>` | Автосоздаваемая bridge-сеть |
| **Volume для артефактов** | `./.gitlab-ci-local/artifacts` | Локальное хранение артефактов |
| **Volume для кэша** | `./.gitlab-ci-local/cache` | Локальное хранение кэша |
| **Pull policy** | `if-not-present` | Используйте `--pull` для принудительного обновления |
| **Порт exposure** | Не разрешен по умолчанию | Используйте `--publish` для проброса портов |

### Shell executor

Для выполнения задач без Docker используйте `--shell`:

```bash
# Выполнение в текущем окружении (bash/zsh)
gitlab-ci-local --shell

# Или явно указать shell
gitlab-ci-local --shell /bin/bash
```

**Особенности Shell executor:**
- Задачи выполняются напрямую в файловой системе проекта
- Нет изоляции контейнеров — изменения в файловой системе сохраняются между запусками
- Артефакты и кэш работают через локальные директории
- Подходит для быстрой проверки скриптов, не требующих специфичного окружения

**Рекомендация:** Используйте Docker executor для тестирования образов и зависимостей. Shell executor — для быстрой проверки shell-скриптов и логики `rules`.

### Полезные флаги CLI

| Флаг | Назначение | Пример |
| :--- | :--- | :--- |
| `--pull` | Принудительно обновить образы | `gitlab-ci-local --pull` |
| `--shell` | Использовать Shell executor | `gitlab-ci-local --shell` |
| `--no-cache` | Пропустить загрузку кэша | `gitlab-ci-local --no-cache` |
| `--fetch-includes` | Обновить remote includes | `gitlab-ci-local --fetch-includes` |
| `--publish <port>` | Пробросить порт сервиса | `gitlab-ci-local --publish 5432` |
| `--no-interactive` | Отключить интерактивный режим | `gitlab-ci-local --no-interactive` |
| `--global-variables` | Вывести развернутую конфигурацию | `gitlab-ci-local --global-variables` |
| `--volume <src:dst>` | Смонтировать дополнительный volume | `gitlab-ci-local --volume ./data:/app/data` |

### Сценарий 3: Валидация `spec:inputs` и `trigger:inputs`

```bash
# Передача входных параметров
gitlab-ci-local -v INPUT_ENVIRONMENT=production \
                -v INPUT_REPLICAS=5 \
                --job deploy

# Или через .gitlab-ci.local.yml
echo 'inputs:
  environment: "staging"
  replicas: 3' >> .gitlab-ci.local.yml
```

**Ожидаемый вывод при ошибке типа:**
```
✗ deploy
  error: inputs.replicas must be a number, got string
```

### Сценарий 4: Локальный DAG и `needs`

```bash
# Запуск конкретной задачи с её зависимостями
gitlab-ci-local --job integration-test

# Вывод:
# ✔ build (build) 5.2s
# ✔ test (test) 3.1s
# ✔ integration-test (test) 2.8s
```

`gitlab-ci-local` автоматически определяет зависимости через `needs` и запускает их в правильном порядке.

### Сценарий 5: Интеграция с pre-commit hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: gitlab-ci-lint
        name: GitLab CI Local Validation
        entry: gitlab-ci-local --list
        language: system
        files: '\.gitlab-ci\.yml$'
        pass_filenames: false
```

```bash
# Установка pre-commit
pip install pre-commit
pre-commit install

# Теперь при каждом коммите gitlab-ci-local проверяет конфигурацию
git commit -m "feat: update pipeline"
# → gitlab-ci-local --list
# → ✔ All jobs valid
```

### Сценарий 6: Отладка `rules` и workflow

```bash
# Список задач, которые будут запущены для текущего контекста
gitlab-ci-local --list

# Ожидаемый вывод:
# ✔ build (build)
# ✔ test (test)
# ✗ deploy (deploy) — filtered by rules

# Проверка конкретной задачи
gitlab-ci-local --job deploy --dry-run
```

### Сценарий 7: Тестирование динамической генерации

Если пайплайн использует динамическую генерацию через артефакты:

```bash
# 1. Сгенерируйте конфигурацию локально
python3 scripts/generate_pipeline.py > generated-ci.yml

# 2. Валидируйте сгенерированный файл
gitlab-ci-local --file generated-ci.yml --list

# 3. Запустите downstream-пайплайн локально
gitlab-ci-local --file generated-ci.yml --job deploy
```

### Сценарий 8: Сравнение расширенной конфигурации

```bash
# Просмотр развернутой конфигурации (аналог glab ci config compile)
gitlab-ci-local --global-variables

# Ожидаемый вывод: полный YAML после обработки всех include, extends, !reference
```

### Сценарий 9: Тестирование артефактов и кэша

```bash
# Запуск с сохранением артефактов и кэша
gitlab-ci-local --job build

# Артефакты сохраняются в ./.gitlab-ci-local/artifacts/
# Кэш сохраняется в ./.gitlab-ci-local/cache/

# Очистка кэша при проблемах
rm -rf ./.gitlab-ci-local/cache/*

# Запуск без кэша
gitlab-ci-local --no-cache --job build
```

### Сценарий 10: Валидация с remote includes

```bash
# Обновить remote includes перед валидацией
gitlab-ci-local --fetch-includes

# Имитация include из внешнего проекта
gitlab-ci-local -v CI_PROJECT_ID="12345" \
                -v CI_API_V4_URL="https://gitlab.example.com/api/v4" \
                --job test
```

### Сценарий 11: Проброс портов для сервисных контейнеров

```bash
# Пробросить порт PostgreSQL для локального подключения
gitlab-ci-local --publish 5432:5432 --job integration-test

# Теперь PostgreSQL доступен на localhost:5432
# Используется для отладки данных после выполнения тестов
```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Image not found` | Образ недоступен локально | Используйте `--pull` для принудительной загрузки образа или проверьте имя образа. |
| `Variable not defined` | Переменная не задана в `.gitlab-ci.local.yml` | Добавьте переменную в `.gitlab-ci.local.yml` или передайте через `-v`. |
| `Job not found` | Задача отфильтрована `rules` | Проверьте контекст переменных; используйте `--list` для просмотра доступных задач. |
| `Input validation failed` | Несоответствие типа `spec:inputs` | Проверьте типы входных параметров в дочернем пайплайне. |
| `Permission denied` | Локальный runner не может выполнить скрипт | Проверьте права на файлы скриптов в репозитории. |
| `Docker not available` | Docker не запущен или нет прав | Запустите Docker или используйте `--shell` для выполнения в Shell. |
| `Cache not found` | Кэш не создан локально | Используйте `--no-cache` для пропуска кэширования. |
| `Include not found` | Remote include недоступен | Используйте `--fetch-includes` или проверьте URL/токен доступа. |
| `Port already in use` | Порт сервиса занят локально | Остановите локальный процесс на порту или используйте `--publish` с другим хост-портом. |
| `Artifact not found` | Артефакт не сохранен локально | Проверьте `artifacts:paths` в задаче; убедитесь, что путь существует. |
| `Service not responding` | Сервисный контейнер не готов | Увеличьте `health_check` retries или проверьте логи через `--publish`. |
| `Out of memory` | Недостаточно RAM для Docker | Увеличьте память Docker Desktop или используйте `--shell` executor. |
| `Network timeout` | Проблемы с сетью при pull образов | Проверьте интернет-соединение или используйте локальный registry mirror. |

## Безопасность

При использовании `gitlab-ci-local` учитывайте следующие риски:

1. **Секреты в `.gitlab-ci.local.yml`:** Файл может содержать тестовые значения, похожие на production-секреты. Убедитесь, что файл добавлен в `.gitignore` и не коммитится в репозиторий.
2. **Выполнение недоверенных скриптов:** `gitlab-ci-local` выполняет скрипты из `.gitlab-ci.yml` локально. Убедитесь, что конфигурация из доверенного источника.
3. **Образы из публичных registries:** При использовании `--pull` инструмент загружает образы из Docker Hub или других публичных источников. Проверяйте образы на уязвимости перед использованием.
4. **Volume mounts:** При использовании `--volume` убедитесь, что монтируемые директории не содержат чувствительных данных, которые могут быть случайно изменены задачами.
5. **Сетевая изоляция:** Локально запущенные сервисные контейнеры не наследуют сетевые политики production-окружения. Тестируйте сетевые правила отдельно.

## Best Practices

### Разработка (Dev)

1. **Валидируйте перед коммитом:** Добавьте `gitlab-ci-local` в pre-commit hook для проверки `.gitlab-ci.yml` перед каждым коммитом.
2. **Используйте `.gitlab-ci.local.yml`:** Храните тестовые переменные в этом файле (добавьте в `.gitignore`, если содержит секреты).
3. **Тестируйте `rules`:** Имитируйте различные контексты (MR, push, schedule, protected branch) через `-v`.
4. **Версионируйте gitlab-ci-local:** Укажите версию инструмента в `pre-commit` конфигурации для стабильности.
5. **Изолируйте локальное окружение:** Используйте отдельный Docker network или `--shell` executor для тестов, чтобы не влиять на рабочую среду.

### Эксплуатация (DevOps/SRE)

1. **Unit-тесты для пайплайнов:** Добавьте задачу в `.pre` стадию, которая запускает `gitlab-ci-local --list` для валидации конфигурации.
2. **Staged rollout:** Используйте canary-подход для изменения пайплайнов — сначала на одном проекте, затем на группе.
3. **Dry-run перед изменением:** Запускайте `gitlab-ci-local --dry-run` перед изменением критичных пайплайнов (production deploy).
4. **Интеграция с CI Lint:** Комбинируйте `gitlab-ci-local` (офлайн-валидация) с `glab ci lint --dry-run` (онлайн-валидация в контексте проекта).
5. **Batch-валидация шаблонов:** При обновлении общих шаблонов запустите `gitlab-ci-local --fetch-includes` на всех проектах-потребителях для проверки совместимости.
6. **Мониторинг уязвимостей образов:** Интегрируйте `trivy` или ` grype` в pre-commit для проверки образов, используемых в пайплайнах, на известные уязвимости.

### Sysadmin

1. **Docker ресурсы:** Убедитесь, что Docker имеет достаточно ресурсов (CPU, RAM, disk) для запуска задач `gitlab-ci-local`. Рекомендуется минимум 4 CPU и 8 GB RAM для параллельного выполнения нескольких задач.
2. **Сетевая изоляция:** Если runner работает в изолированной сети, настройте доступ к registry для загрузки образов. Используйте registry mirror для ускорения загрузки.
3. **Хранение `.gitlab-ci.local.yml`:** Добавьте файл в `.gitignore` или храните в защищенном месте, так как он может содержать тестовые секреты.
4. **Очистка артефактов и кэша:** Настройте cron для очистки `./.gitlab-ci-local/artifacts` и `./.gitlab-ci-local/cache` на разработческих машинах.
5. **Резервное копирование конфигураций:** Храните проверенные `.gitlab-ci.local.yml` в защищенном месте (например, в шифрованном хранилище) для быстрого восстановления окружения.

## Edge Cases и ограничения

- **Нет доступа к GitLab API:** `gitlab-ci-local` работает офлайн, но не может проверить права доступа, существование проектов или Inbound Allowlist. Используйте `glab ci lint --dry-run` для этих проверок.
- **Ограниченная имитация `needs:project`:** `gitlab-ci-local` не может скачать артефакты из других проектов. Для тестирования cross-project артефактов используйте реальный GitLab инстанс.
- **Отличие окружения:** Локальный runner (Docker/Shell) может вести себя иначе, чем GitLab Runner в Kubernetes. Тестируйте на staging перед production.
- **Секреты:** Не храните реальные секреты в `.gitlab-ci.local.yml`. Используйте тестовые значения или моки.
- **Кэширование:** `gitlab-ci-local` использует локальный кэш Docker, который может отличаться от кэша GitLab Runner. Очищайте кэш при проблемах.
- **Remote includes:** При использовании `include:project` или `include:remote` убедитесь, что токены доступа (`CI_JOB_TOKEN`, `PROJECT_ACCESS_TOKEN`) настроены в `.gitlab-ci.local.yml`. Без токенов `--fetch-includes` не сможет загрузить внешние ресурсы.
- **Динамические конфигурации:** Пайплайны, генерируемые скриптами во время выполнения, требуют предварительной генерации конфигурации перед валидацией (см. Сценарий 7).
- **Сервисные контейнеры:** `gitlab-ci-local` поддерживает сервисные контейнеры, но не все опции Docker (например, `--publish` пробрасывает порт только на хост-машину, а не между контейнерами). Для тестирования сетевого взаимодействия сервисов используйте Docker Compose отдельно.
- **Размеры образов:** Большие образы (>2 GB) могут значительно замедлить локальное выполнение. Используйте `--pull` только при необходимости и тестируйте с lightweight-альтернативами.
- **Windows поддержка:** На Windows требуется Git Bash с bash версии 4.x+. PowerShell не поддерживается напрямую. Используйте WSL2 для полноценной поддержки.

## Дополнительная информация

### Связанные документы

- **[Валидация и версионирование пайплайнов](../Advanced/pipeline_validation_and_versioning.md)** — CI Lint API, dry-run, batch-валидация.
- **[Отладка и устранение неполадок](../Advanced/debugging_and_troubleshooting.md)** — методы отладки пайплайнов, `gitlab-runner exec`.
- **[API и Webhooks](../Advanced/api_and_webhooks_automation.md)** — REST API, GraphQL, автоматизация.
- **[Сервисные контейнеры](../Reusable_Pipelines/services_and_service_containers.md)** — работа с сервисами в reusable templates.

### Альтернативные инструменты

| Инструмент | Описание | Когда использовать |
| :--- | :--- | :--- |
| **gitlab-ci-local** | Локальное выполнение и валидация | Быстрая проверка конфигурации, отладка `rules`, тестирование артефактов |
| **glab ci lint** | Валидация через GitLab API | Проверка в контексте проекта, dry-run с `rules`, проверка прав доступа |
| **gitlab-runner exec** | Локальное выполнение через Runner | Отладка поведения, идентичного production (сервисы, кэш, volumes) |
| **gitlab-ci-linter** | Онлайн-валидация (SaaS) | Быстрая проверка без установки инструментов |
| **checkov** | Статический анализ IaC (включая GitLab CI) | Compliance, security scanning, pre-commit |
| **trivy/grype** | Сканирование уязвимостей образов | Проверка образов, используемых в пайплайнах |
| **gitlab-ci-validate** | Простая валидация синтаксиса | CI-задача для базовой проверки |

### Интеграция с CI/CD pipeline

Добавьте задачу валидации в `.pre` стадию вашего пайплайна:

```yaml
stages:
  - .pre
  - build
  - test

validate-ci-config:
  stage: .pre
  image: alpine:3.24.2
  before_script:
    - apk add --no-cache curl jq
  script:
    - |
      # Базовая валидация синтаксиса
      if ! python3 -c "import yaml; yaml.safe_load(open('.gitlab-ci.yml'))"; then
        echo "ERROR: Invalid YAML syntax"
        exit 1
      fi
      
      # Валидация через CI Lint API
      RESPONSE=$(curl -s --request POST \
        --header "JOB-TOKEN: $CI_JOB_TOKEN" \
        --header "Content-Type: application/json" \
        --data "{\"content\": \"$(cat .gitlab-ci.yml | sed 's/\"/\\\"/g')\"}" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/ci/lint")
      
      if [ "$(echo "$RESPONSE" | jq -r '.valid')" != "true" ]; then
        echo "ERROR: CI Lint failed"
        echo "$RESPONSE" | jq '.errors'
        exit 1
      fi
      
      echo "✓ CI configuration valid"
  rules:
    - changes:
        - .gitlab-ci.yml
        - "**/*.ci.yml"
```

### Внешние ресурсы

- [gitlab-ci-local GitHub (firecow)](https://github.com/firecow/gitlab-ci-local) — основной репозиторий, документация, issue tracker.
- [gitlab-ci-local npm](https://www.npmjs.com/package/gitlab-ci-local) — пакет для установки через npm.
- [GitLab Docs: CI/CD](https://docs.gitlab.com/ee/ci/) — официальная документация GitLab CI/CD.
