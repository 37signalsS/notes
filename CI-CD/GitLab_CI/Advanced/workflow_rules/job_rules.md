# Правила запуска задач (rules)

**Актуально для:** GitLab 17.x–19.x

## Определения

**`rules`** — современный и рекомендуемый способ декларативного управления жизненным циклом задач в GitLab CI/CD. Директива позволяет гибко определять условия включения задачи в пайплайн, изменять её параметры (переменные, зависимости, статус ошибки) и режим запуска на основе контекста выполнения.

В версиях **GitLab 17.x–19.x** `rules` полностью заменили устаревшие `only`/`except`, предоставляя мощный синтаксис для монорепозиториев, кросс-проектных проверок и динамических пайплайнов. Правила проверяются по порядку (first match), первое совпадение определяет поведение задачи.

**Поддерживаемые ключи и их технические детали:**
- **`if`**: Логические выражения на основе переменных. Поддерживают сравнение (`==`, `!=`), регулярные выражения (`=~`, `!~`) и логические операторы (`&&`, `||`). Оценка происходит в момент создания пайплайна.
- **`changes`**: Запуск при изменении конкретных файлов.
  - `paths`: Массив путей (glob-паттерны).
  - `compare_to`: Базовая ветка или коммит для сравнения. С версии GitLab 17.2 поддерживает использование CI/CD переменных (например, `compare_to: '$TARGET_BRANCH'`), что критически важно для монорепозиториев и MR-пайплайнов.
- **`exists`**: Запуск при наличии файлов в репозитории. Раскрытие переменных в путях работает корректно, включая слэши (улучшено в GitLab 17.3+).
  - `paths`: Массив путей к файлам.
  - `project` (GitLab 17.0+): Позволяет проверять существование файла в *другом* проекте.
  - `ref` (GitLab 17.0+): Позволяет проверять существование файла на конкретной ветке или теге.
- **`when`**: Режим запуска задачи при совпадении правила (`on_success`, `manual`, `never`, `always`, `on_failure`, `delayed`).
- **`start_in`**: Время задержки (например, `3 hours`, `10 minutes`) используется *только* в связке с `when: delayed`.
- **`allow_failure`**: Управление критичностью ошибки. Может принимать булево значение (`true`/`false`) или блок `exit_codes` (массив кодов, например `[137, 255]`) для игнорирования специфических кодов завершения скрипта.
- **`variables`**: Переопределение переменных окружения специально для конкретного сработавшего правила. Имеет приоритет над глобальными переменными, но ниже ручного запуска (см. иерархию 19.x).
- **`needs`**: Динамическое переопределение зависимостей (DAG). Позволяет подменять массив родительских задач (артефактов) в зависимости от сработавшего условия (GitLab 16.0+).

## Предварительные требования

### Версия GitLab и поддержка ключей

| Ключ / Возможность | Минимальная версия GitLab | Примечание |
| :--- | :--- | :--- |
| `rules` (базовый синтаксис) | 11.0+ | Полная замена `only`/`except` |
| `rules:changes:compare_to` (литералы) | 12.3+ | Сравнение с фиксированной веткой |
| `rules:changes:compare_to` (переменные) | 17.2+ | Критично для динамических MR-пайплайнов |
| `rules:exists:project` / `rules:exists:ref` | 17.0+ | Кросс-проектные проверки |
| `rules:needs` | 16.0+ | Динамическое переопределение DAG |
| `rules:allow_failure:exit_codes` | 12.8+ | Игнорирование специфических кодов завершения |
| `rules:variables` | 13.9+ | Переопределение переменных в правилах |
| `when: delayed` + `start_in` | 13.7+ | Отложенный запуск |

### Необходимые знания

- Базовый синтаксис YAML и структура `.gitlab-ci.yml`
- Концепции стадий, задач и артефактов
- Предопределённые переменные GitLab (`CI_*`)
- Работа с Merge Request и ветками в Git
- Основы shell-скриптинга для написания команд

### Инструменты диагностики

- **CI Lint API/UI** — валидация конфигурации до запуска пайплайна
- **Pipeline Editor** — визуальный редактор с предпросмотром графа задач
- **`glab ci lint`** — CLI-утилита для локальной проверки конфигурации
- **CI_DEBUG_TRACE** — включение отладочного вывода для анализа переменных

## Основные концепции

По умолчанию задачи запускаются согласно разделу `stages`. Директива `rules` переопределяет это поведение:

- Задача включается в пайплайн только при совпадении условия.
- Если ни одно правило не совпало — задача исключается.
- `when: never` в начале списка позволяет явно блокировать запуск в нежелательных условиях (например, для WIP-коммитов).
- Чтобы задача запускалась "всегда, если не сработали другие правила", последним элементом списка обычно ставят `- when: on_success`.

### Ограничение: видимость переменных

Правила `rules` вычисляются в момент создания пайплайна (Pipeline Creation Time). Это означает:
1. Переменные из других задач (через `artifacts:reports:dotenv`) **недоступны** в блоке `rules`.
2. Переменные, созданные в блоке `script`, не влияют на выполнение правил.
3. Доступны только предопределённые переменные GitLab (`CI_*`), переменные проекта, группы, глобальные переменные пайплайна и переменные, переданные при триггере.

```yaml
# ОШИБКА: переменная из другой job недоступна в rules
next_job:
  rules:
    - if: '$UPSTREAM_VERSION == "1.0"' # $UPSTREAM_VERSION не будет видна здесь, если она из dotenv
```

**Приоритет переменных (GitLab 19.x):**
При использовании `rules:variables` GitLab соблюдает строгую иерархию. В контексте файла `.gitlab-ci.yml` переменные правила занимают приоритет над переменными задачи, но ниже внешних источников (от высшего к низшему):

1. Переменные политик выполнения пайплайна (Pipeline execution policy).
2. Переменные пайплайна: ручной запуск (Web UI / API), триггеры, расписания, upstream-пайплайны.
3. Переменные проекта (`project variables`).
4. Переменные группы (`group variables`).
5. Переменные инстанса (`instance variables`).
6. Переменные из `artifacts:reports:dotenv` предыдущих задач.
7. Переменные задачи (`job:variables`).
8. **Переменные правила (`rules:variables`)** — внутри matching-правила.
9. Переменные `workflow:rules:variables`.
10. Глобальные переменные пайплайна (`variables` на верхнем уровне).
11. Deployment variables.
12. Предопределённые переменные GitLab (`CI_*`).

## Практические сценарии

### Базовое управление событиями

**Запуск только для Merge Request:**
```yaml
test_job:
  stage: test
  script:
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

**Запуск для MR в определённую ветку:**
```yaml
test_mr_to_main:
  script:
    - npm run test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"'
```

### Монорепозитории и отслеживание изменений

**Запуск при изменении файлов (базовый):**
```yaml
# Запуск только при изменении frontend-кода
test_frontend:
  script:
    - npm run test
  rules:
    - changes:
        - "frontend/**/*"
        - "package.json"
        - "pnpm-lock.yaml"
```

**Точное отслеживание с compare_to:**
В монорепозиториях важно сравнивать изменения не только с текущим коммитом, но и с базовой веткой (особенно для новых веток).
```yaml
test_component:
  rules:
    - changes:
        paths:
          - "component/**/*"
        compare_to: 'refs/heads/main' # сравнение с main
```

**Динамическое сравнение ветки (GitLab 17.2+):**
```yaml
test_frontend:
  script: npm run test
  rules:
    - changes:
        paths: ["frontend/**/*"]
        # Сравнение с целевой веткой MR или с main для обычных пушей
        compare_to: '${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main}'
```

### Продвинутая логика и зависимости

**Динамические зависимости (rules:needs):**
Разный набор зависимых задач для разных веток.
```yaml
deploy:
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      needs: ["build_prod", "test_all"]
    - if: '$CI_COMMIT_BRANCH != "main"'
      needs: ["build_dev"] # более быстрый путь для разработчиков
```

**Условная обработка ошибок (exit_codes):**
Продолжать выполнение, если задача упала с определённым кодом (например, OOM).
```yaml
optional_scan:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "push"'
      allow_failure:
        exit_codes:
          - 137 # Код OOM
```

**Комбинированное правило для деплоя:**
```yaml
deploy_job:
  stage: deploy
  script:
    - ./deploy.sh
  rules:
    # Автоматический деплой для main
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: on_success
    # Ручной деплой для staging
    - if: '$CI_COMMIT_BRANCH == "staging"'
      when: manual
    # Запрет для остальных веток
    - when: never
```

### Интеграция и Compliance

**Проверка файлов во внешнем репозитории (GitLab 17.0+):**
Полезно для централизованных шаблонов безопасности.
```yaml
compliance_check:
  script: echo "Checking compliance..."
  rules:
    - exists:
        paths: ["security-policy.yaml"]
        project: "org/security-standards"
        ref: "main"
      when: always
    - when: never
```

**Компоненты и входные параметры (spec:inputs, GitLab 17.x):**
```yaml
spec:
  inputs:
    environment:
      default: "staging"
---
deploy:
  rules:
    - if: '$[[ inputs.environment ]] == "production"'
      when: manual
    - when: on_success
  script:
    - ./deploy.sh $[[ inputs.environment ]]
```

### Динамические окружения

**Автоматическая очистка Review Apps:**
```yaml
stop_review:
  stage: deploy
  script: echo "Stopping env..."
  when: manual
  rules:
    - if: '$CI_MERGE_REQUEST_ID'
      allow_failure: true
    - when: never
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
```

### DevOps/SRE и on-premise сценарии

**Terraform: дифференциальный план для изменений инфраструктуры:**
```yaml
terraform:plan:
  stage: plan
  image: hashicorp/terraform:1.9
  script:
    - terraform init -backend-config="backend.hcl"
    - terraform plan -out=tfplan -var-file="production.tfvars"
  artifacts:
    paths: ["tfplan"]
    expire_in: 1 day
  rules:
    - changes:
        paths: ["terraform/**/*.tf"]
        compare_to: '${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main}'
      when: always

terraform:apply:
  stage: deploy
  image: hashicorp/terraform:1.9
  script:
    - terraform apply -auto-approve tfplan
  dependencies: ["terraform:plan"]
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main" && $CI_PIPELINE_SOURCE == "web"'
      when: manual
    - when: never
```

**Ansible: каскадное развертывание с последовательными окружениями:**
```yaml
ansible:lint:
  stage: lint
  image: cytopia/ansible-lint
  script:
    - ansible-lint roles/
    - ansible-lint playbooks/
  rules:
    - changes:
        paths: ["ansible/**/*"]
        compare_to: 'refs/heads/main'

ansible:deploy:staging:
  stage: deploy
  image: cytopia/ansible:2.14
  script:
    - ansible-playbook -i inventory/staging playbooks/deploy.yml
  environment:
    name: staging
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'
      when: manual
    - when: never

ansible:deploy:production:
  stage: deploy
  image: cytopia/ansible:2.14
  script:
    - ansible-playbook -i inventory/production playbooks/deploy.yml
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
    - when: never
  needs: ["ansible:deploy:staging"]
```

**Конфигурация серверов (Salt/Puppet) с валидацией:**
```yaml
salt:validate:
  stage: validate
  image: saltstack/salt:latest
  script:
    - salt-call --local state.show_highstate --retcode-passthrough
  rules:
    - changes:
        paths: ["salt/**/*"]
        compare_to: 'refs/heads/main'

salt:apply:
  stage: apply
  image: saltstack/salt:latest
  script:
    - salt-call --local state.highstate
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
  needs: ["salt:validate"]
```

**Проверка конфигурации сетевых устройств (NAPALM/Netmiko):**
```yaml
network:validate:
  stage: validate
  image: python:3.12
  before_script:
    - pip install napalm
  script:
    - python validate_configs.py configs/
  rules:
    - changes:
        paths: ["configs/**/*"]
        compare_to: 'refs/heads/main'

network:deploy:
  stage: deploy
  image: python:3.12
  before_script:
    - pip install napalm
  script:
    - python deploy_configs.py configs/ --dry-run
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
  needs: ["network:validate"]
```

## Валидация и отладка правил

### Методы проверки конфигурации

**1. CI Lint (API/UI):**
Проверка конфигурации на этапе создания пайплайна. Обнаруживает синтаксические ошибки и невалидные ключи.
```bash
# Через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --data "content=$(cat .gitlab-ci.yml | base64)" \
  "https://gitlab.example.com/api/v4/ci/lint"

# Результат: {"valid": true} или {"valid": false, "errors": [...]}
```

**2. CLI-валидация (glab):**
Локальная проверка без отправки в GitLab.
```bash
# Базовая проверка
glab ci lint

# С имитацией переменных окружения
glab ci lint --dry-run --variable CI_PIPELINE_SOURCE=merge_request_event
glab ci lint --dry-run --variable CI_COMMIT_BRANCH=main
glab ci lint --dry-run --variable CI_COMMIT_BRANCH=feature/new-api
```

**3. Pipeline Editor:**
Визуальный интерфейс GitLab для проверки конфигурации с предпросмотром графа задач и симуляцией выполнения.

### Отладка переменных в правилах

**Проблема:** Правило `if` не работает как ожидалось.

**Диагностика:**
1. Добавьте отладочный вывод переменных в начало секции `script`:
```yaml
debug_vars:
  stage: .pre
  script:
    - echo "CI_PIPELINE_SOURCE=$CI_PIPELINE_SOURCE"
    - echo "CI_COMMIT_BRANCH=$CI_COMMIT_BRANCH"
    - echo "CI_MERGE_REQUEST_ID=$CI_MERGE_REQUEST_ID"
    - echo "CI_MERGE_REQUEST_TARGET_BRANCH_NAME=$CI_MERGE_REQUEST_TARGET_BRANCH_NAME"
  rules:
    - when: always
```

2. Проверьте значение переменных через API:
```bash
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/variables"
```

3. Используйте `CI_DEBUG_TRACE` для полного вывода окружения:
```yaml
debug_trace:
  script:
    - env | sort | grep CI_
  variables:
    CI_DEBUG_TRACE: "true"
  rules:
    - when: always
```

### Валидация логики правил

**Тестирование всех веток логики:**
```bash
# Имитация различных сценариев
for BRANCH in main develop feature/test; do
  echo "Testing branch: $BRANCH"
  glab ci lint --dry-run --variable CI_COMMIT_BRANCH=$BRANCH
done

# Имитация_MR событий
for TARGET in main staging; do
  echo "Testing MR to: $TARGET"
  glab ci lint --dry-run \
    --variable CI_PIPELINE_SOURCE=merge_request_event \
    --variable CI_MERGE_REQUEST_TARGET_BRANCH_NAME=$TARGET
done
```

## Миграция с only/except на rules

### Причины миграции

- `only`/`except` объявлены устаревшими в GitLab 12.0+
- `rules` поддерживают сложную логику, `changes`, `exists`, `variables`
- `rules` позволяют изменять атрибуты задачи (`when`, `allow_failure`, `variables`, `needs`)
- `rules` совместимы с `workflow` для контроля над пайплайнами

### Таблица соответствия

| only/except | rules эквивалент | Примечание |
| :--- | :--- | :--- |
| `only: [branches]` | `if: '$CI_COMMIT_BRANCH == "name"'` | Точное имя ветки |
| `except: [branches]` | `if: '$CI_COMMIT_BRANCH != "name"'` + fallback | Инверсия логики |
| `only: [merge_requests]` | `if: '$CI_PIPELINE_SOURCE == "merge_request_event"'` | Источник триггера |
| `only: [tags]` | `if: '$CI_COMMIT_TAG'` | Наличие тега |
| `only: [schedules]` | `if: '$CI_PIPELINE_SOURCE == "schedule"'` | Расписание |
| `only: [web]` | `if: '$CI_PIPELINE_SOURCE == "web"'` | Ручной запуск |
| `only: [api]` | `if: '$CI_PIPELINE_SOURCE == "api"'` | API-вызов |
| `only: [pushes]` | `if: '$CI_PIPELINE_SOURCE == "push"'` | Пуш коммита |

### Практический пример миграции

**До (only/except):**
```yaml
deploy:production:
  script: ./deploy.sh
  only:
    - main
  except:
    - /^feature\/.*$/
  when: manual
```

**После (rules):**
```yaml
deploy:production:
  script: ./deploy.sh
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
    - when: never
```

**Ключевое отличие:** `rules` требует явного указания `when: never` для исключения сценариев, в то время как `except` делает это неявно.

## Дополнительная информация

### Ключевые условия (Детально)

| Условие | Описание и технические нюансы | Пример |
| :--- | :--- | :--- |
| `if` | Оценка логических выражений. Поддерживает regex (`=~` / `/.../`). | `if: '$CI_COMMIT_BRANCH =~ /^feature\/.*/'` |
| `changes` | Триггер на изменение путей. Требует `compare_to` для точности в обычных пушах. | `changes: - "src/**/*"` |
| `compare_to` | Уточнение базы для `changes`. Поддерживает переменные с 17.2. | `compare_to: 'refs/heads/main'` |
| `exists` | Триггер на наличие файлов. С 17.0 поддерживает кросс-проектные проверки. | `exists: - "Dockerfile"` |

### Режимы запуска (when) и их поведение

| Режим | Описание | Примечание |
| :--- | :--- | :--- |
| `on_success` | Выполняется при успехе предыдущих стадий. | Значение по умолчанию. |
| `on_failure` | Запускается только если стадия упала. | Для алертинга или cleanup. |
| `always` | Выполняется независимо от статуса. | Для финальной очистки ресурсов. |
| `manual` | Требует ручного запуска в UI. | Блокирует стадии без `allow_failure: true`. |
| `delayed` | Откладывает запуск на время `start_in`. | Максимум 1 неделя. |
| `never` | Задача полностью исключается. | Блокирующее правило в начале списка. |

### Типовые ошибки и устранение неполадок

#### Синтаксические ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Syntax error in "rules"` | Невалидный YAML или неверный ключ | Используйте CI Lint для валидации |
| `Unexpected keyword "only"` | Конфликт `only`/`except` с `rules` | Удалите `only`/`except`, используйте только `rules` |
| `Invalid regex pattern` | Неверный синтаксис регулярного выражения | Проверьте regex на regex101.com, используйте `/pattern/` |

#### Логические ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Regex без слэшей** | В `if` регулярные выражения ОБЯЗАТЕЛЬНО обрамляются `/.../` | `if: '$CI_COMMIT_BRANCH =~ /^feature\/.*/'` |
| **Задача не появляется** | Ни одно правило не совпало | Добавьте `- when: on_success` в конец списка |
| **Задача запускается дважды** | Два правила совпали с `when: on_success` | Используйте `when: never` для исключения |
| **Неверная переменная** | Переменная из dotenv недоступна в `rules` | Проверьте иерархию приоритетов переменных |
| **Конфликт переменных** | Разные приоритеты переменных | Используйте `rules:variables` для переопределения |

#### Проблемы с переменными

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Переменная не раскрывается** | Использование `${VAR}` вместо `$VAR` в `if` | В `if` используйте `$VAR` без фигурных скобок |
| **Regex не работает** | Отсутствие кавычек вокруг выражения | Оберните `if` в одинарные кавычки: `if: '$VAR =~ /pattern/'` |
| **Переменная пуста** | Переменная не определена в данном контексте | Проверьте scope: project, group, instance, predefined |

#### Проблемы с compare_to и changes

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **changes не срабатывает** | Отсутствует `compare_to` для обычных пушей | Добавьте `compare_to: 'refs/heads/main'` или используйте `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` |
| **Сравнение с собой** | `compare_to` указывает на текущую ветку | Убедитесь, что `compare_to` указывает на БАЗОВУЮ ветку, а не на текущую |
| **Неверный ref** | `compare_to` принимает только полные refs | Используйте `refs/heads/main`, а не `main` |

#### Проблемы с workflow:rules

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Дублирование пайплайнов** | Отсутствует исключение для MR+Push | Добавьте правило с `when: never` для комбинации |
| **Пустой пайплайн** | Все задачи отфильтрованы через `rules` | Проверьте `workflow:rules` на наличие fallback-правила |
| **Пайплайн не создается** | `workflow:rules` не включает источник | Добавьте `if: '$CI_PIPELINE_SOURCE == "push"'` |

### Устранение неисправностей (Troubleshooting)

**1. Задача не запускается:**
- Проверьте, что `workflow:rules` не исключает пайплайн
- Используйте CI Lint для валидации конфигурации
- Добавьте отладочный вывод переменных
- Проверьте, что переменные в `if` используют синтаксис `$VAR`, а не `${VAR}`

**2. Задача запускается, когда не должна:**
- Проверьте порядок правил: первое совпадение определяет поведение
- Убедитесь, что нет дублирующихся правил с `when: on_success`
- Добавьте `- when: never` в конец списка как catch-all

**3. Переменные в rules не работают:**
- Переменные из `artifacts:reports:dotenv` недоступны в `rules` (вычисляются в Pipeline Creation Time)
- Проверьте иерархию приоритетов переменных
- Используйте `rules:variables` для переопределения в конкретном правиле

**4. changes не отслеживает изменения:**
- Для обычных пушей (не MR) необходим `compare_to`
- `compare_to` поддерживает переменные только с GitLab 17.2+
- Убедитесь, что пути в `paths` используют glob-паттерны (`**/*`)

**5. compare_to не работает с переменными:**
- Версия GitLab должна быть 17.2 или выше
- Переменная должна быть определена до вычисления `rules`
- Используйте логическое ИЛИ для fallback: `${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main}`

## Лучшие практики

### Структура правил

1. **Порядок правил важен:** Первое совпадение определяет поведение. Ставьте наиболее специфичные правила в начало.
2. **Явное исключение:** Всегда завершайте список правил явным `- when: never`, если не все сценарии должны запускать задачу.
3. **Fallback-правило:** Если задача должна запускаться "всегда, если не сработали другие правила", последним элементом ставьте `- when: on_success`.

### Переменные и условия

1. **Не используйте переменные из script в rules:** Переменные из `artifacts:reports:dotenv` недоступны в `rules` (вычисляются в Pipeline Creation Time).
2. **Избегайте глобальных переменных для логики:** Используйте `rules:variables` для переопределения в конкретных условиях.
3. **Кавычки для if:** Всегда оборачивайте `if` в одинарные кавычки, если используете операторы сравнения или регулярные выражения.

### Монорепозитории

1. **Используйте compare_to:** Для отслеживания изменений в монорепозиториях всегда указывайте `compare_to` для `changes`.
2. **Комбинируйте if и changes:** Используйте логическое И для комбинирования условий ветки и изменений файлов.
3. **Динамическое сравнение:** С GitLab 17.2+ используйте `${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main}` для автоматического выбора целевой ветки.

### Безопасность и compliance

1. **Принудительные задачи:** Используйте `workflow:rules` для блокировки пайплайнов в нежелательных условиях.
2. **Ручной запуск для production:** Всегда используйте `when: manual` для задач деплоя в production.
3. **Разрешение ошибок:** Используйте `allow_failure: exit_codes` для игнорирования специфических кодов завершения (например, OOM).

### Производительность

1. **Минимизируйте количество правил:** Каждое правило проверяется последовательно. Чем меньше правил, тем быстрее создание пайплайна.
2. **Избегайте сложных regex:** Сложные регулярные выражения замедляют вычисление правил.
3. **Кэшируйте результаты:** Используйте `cache` для избежания повторной загрузки зависимостей.

## Граничные случаи и ограничения

### Технические ограничения

- **Лимит правил:** Нет формального лимита на количество правил, но слишком много правил замедляет создание пайплайна.
- **Длина условия `if`:** Ограничение на длину строки YAML (обычно 2048 символов для ключа).
- **Regex в `if`:** Поддерживаются только POSIX-совместимые регулярные выражения.
- **`changes` без `compare_to`:** В обычных пушах (не MR) `changes` сравнивает только с предыдущим коммитом, что может давать ложные срабатывания.
- **`exists` в разных ветках:** `exists` проверяет файл в текущем коммите, а не в целевой ветке.

### Особые сценарии

**WIP-коммиты (Work In Progress):**
```yaml
# Запрет запуска для WIP-коммитов
rules:
  - if: '$CI_COMMIT_TITLE =~ /^WIP:/'
    when: never
  - when: on_success
```

**Исключение определенных файлов:**
```yaml
# Запуск только при изменении определенных файлов
rules:
  - changes:
      paths: ["src/**/*"]
      compare_to: 'refs/heads/main'
    when: on_success
  - when: never
```

**Комбинирование условий ветки и изменений:**
```yaml
# Запуск только в main И при изменении определенных файлов
rules:
  - if: '$CI_COMMIT_BRANCH == "main"'
    changes:
      paths: ["deploy/**/*"]
      compare_to: 'refs/heads/main'
    when: manual
  - when: never
```

**Приоритет переменных в rules:**
```yaml
# Переопределение переменных в конкретном правиле
rules:
  - if: '$CI_COMMIT_BRANCH == "main"'
    variables:
      ENVIRONMENT: "production"
      REPLICAS: "3"
  - if: '$CI_COMMIT_BRANCH == "develop"'
    variables:
      ENVIRONMENT: "staging"
      REPLICAS: "1"
```

### Производительность

**Влияние на время создания пайплайна:**
- Каждое правило проверяется последовательно
- Сложные regex и множественные `changes` замедляют вычисление
- Рекомендуется минимизировать количество правил

**Оптимизация:**
- Используйте простые условия `if` вместо сложных regex
- Комбинируйте условия в одном правиле с `&&`
- Избегайте дублирующих правил с одинаковым результатом

**Масштабирование:**
- Для монорепозиториев с большим количеством сервисов используйте `workflow:rules` для фильтрации на уровне пайплайна
- Используйте `include` для переиспользования правил между проектами

### Несовместимость с другими директивами

- **`rules` и `only`/`except`:** Нельзя использовать одновременно. Выберите один механизм.
- **`rules` и `stage`:** `rules` переопределяет поведение стадий. Задача может запуститься в другой стадии, чем ожидается.
- **`rules` и `when` на верхнем уровне:** `rules` переопределяет глобальный `when`.

### Кросс-проектные ограничения

- **`exists` с `project`:** Требует разрешения доступа через Inbound Allowlist (GitLab 17.0+).
- **`changes` с `compare_to`:** `compare_to` не работает с кросс-проектными сравнениями.
- **`needs` с кросс-проектными зависимостями:** Требует настройки Job Token Permissions.

## См. также

- **[Основы GitLab CI/CD](../../Concepts/gitlab_ci_basics.md)** — базовые принципы и синтаксис.
- **[Продвинутые рабочие процессы](../gitlab_ci_advanced_workflow.md)** — описание `workflow`, `auto_cancel` и оптимизация.
- **[Справочник директив](./directives_definitions.md)** — детализация смежных ключевых слов.
- **[Обзор Runner и Executor](../gitlab_ci_runners_executors.md)** — типы executor'ов и конфигурация.
- **[Окружения и развертывания](../../Concepts/environments_and_deployments.md)** — protected environments, approvals, rollback.
- **[Кэширование и артефакты](../gitlab_ci_caching/caching_overview.md)** — стратегии кэширования.
- **[Артефакты в GitLab CI](../gitlab_ci_caching/gitlab_ci_artifacts.md)** — artifacts, reports, retention policies.
- **[Родительско-дочерние пайплайны](../Downstream_Pipelines/parent_child_pipelines.md)** — trigger и parent-child паттерны.
- **[Compliance и Audit](../compliance_and_audit.md)** — compliance frameworks и approval rules.
- **[CI/CD Catalog компоненты](../../Reusable_Pipelines/ci_cd_catalog_components.md)** — публикация и использование компонентов.
- **[Container Registry](../container_registry.md)** — интеграция Registry с CI/CD.
- **[Pipeline Schedules](../pipeline_schedules.md)** — cron-расписания и Scheduled Execution Policies.
