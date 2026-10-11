# Переменные и секреты GitLab CI/CD — глубинное погружение

**Актуально для:** GitLab 17.x–19.x

> **Примечание:** Данное руководство фокусируется на практическом применении переменных и секретов в пайплайнах. Полная теория управления секретами, OIDC и иерархия приоритетов описаны в **[Переменные и секреты GitLab CI/CD](../Concepts/gitlab_ci_variables_secrets.md)**.

## Определения

*   **CI/CD переменная** — пара `key=value`, используемая для параметризации пайплайна, передачи секретов и управления окружением.
*   **Защищенная переменная (`Protected`)** — доступна только в пайплайнах, запущенных для защищенных веток или тегов.
*   **Маскированная переменная (`Masked`)** — значение скрывается в логах (`[MASKED]`). С версии **18.3** применяется автоматически ко всем новым переменным. Требование: минимум 8 символов, отсутствие пробелов.
*   **Скрытая переменная (`Hidden`)** — значение полностью скрыто в интерфейсе и логах. После сохранения просмотр невозможен даже администраторам.
*   **Переменная типа `File`** — содержимое записывается во временный файл на Runner, переменная хранит путь к нему. Идеально для SSH-ключей и сертификатов.
*   **Сырая переменная (`Raw`)** — переменная, для которой отключено автоматическое расширение вложенных ссылок (`expansion`). Гарантирует, что спецсимволы (например, `$`) будут восприняты буквально.
*   **GitLab Secrets Manager** — нативное решение для управления секретами (GA с версии **19.2**), обеспечивающее безопасное хранение, версионирование и инъекцию секретов.
*   **OIDC (OpenID Connect)** — метод аутентификации пайплайна во внешних системах (Vault, Kubernetes, менеджеры секретов) через `ID Tokens`.
*   **`dotenv` переменные** — пары `key=value`, передаваемые между задачами через `artifacts:reports:dotenv`. Используются для динамических данных, вычисленных в предыдущих стадиях.
*   **`spec:inputs`** — типизированные параметры компонентов (Pipeline Inputs), доступные с версии **17.11**. В отличие от переменных, интерполируются на этапе компиляции YAML.

## Предварительные требования

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
|:---|:---|:---|
| `spec:inputs` (базовый) | 17.0+ | Типизация, значения по умолчанию |
| `spec:inputs` + `regex` | 17.10+ | Валидация регулярными выражениями |
| `spec:inputs` + `options` | 18.0+ | Выпадающий список в UI |
| `description` в Variables | 19.0+ | Описание переменных в UI |
| GitLab Secrets Manager | 19.2+ | Нативное управление секретами |
| `raw: true` для переменных | 17.3+ | Отключение расширения вложенных ссылок |
| Default masked | 18.3+ | Автоматическое маскирование новых переменных |
| `CI_JOB_TOKEN` Fine-grained | 18.3+ | Тонкая настройка прав токена |
| Inbound Allowlist | 17.0+ | Защита `CI_JOB_TOKEN` белым списком |
| `id_tokens` (OIDC) | 16.0+ | Федеративная аутентификация |

### Роли и ответственность

| Роль | Ответственность |
|:---|:---|
| **GitLab Maintainer** | Настройка CI/CD переменных, protected branches, runner'ы |
| **Security Engineer** | Аудит секретов, политики маскирования, ротация ключей |
| **DevOps/SRE** | Настройка OIDC, Vault, мониторинг доступа к секретам |
| **Sysadmin** | Управление Runner'ами, доступ к файловым переменным, бэкап |
| **Developer** | Использование `spec:inputs`, запрос новых переменных через MR |

### Инструменты диагностики

*   **CI Lint** — валидация конфигурации до запуска пайплайна
*   **Pipeline Editor** — визуальный редактор с предпросмотром графа задач
*   **`glab ci lint`** — CLI-утилита для локальной проверки конфигурации
*   **"View merged YAML"** — просмотр итоговой конфигурации после всех merge/include/inputs
*   **`CI_DEBUG_TRACE`** — включение отладочного вывода для анализа переменных
*   **Audit Logs** — логи изменений переменных в настройках проекта

## Архитектура и базовые концепции

### Жизненный цикл переменной

1.  **Этап компиляции (Pipeline Compilation):** GitLab собирает итоговый YAML из всех `include`, интерполирует `spec:inputs`, разрешает `!reference` и `extends`. На этом этапе переменные еще не существуют — работают только `inputs`.
2.  **Этап разрешения (Resolution):** Определяются значения CI/CD переменных из всех источников (UI settings, `.gitlab-ci.yml`, `rules:variables`) с учетом иерархии приоритетов. Полная иерархия описана в **[Переменные и секреты GitLab CI/CD](../Concepts/gitlab_ci_variables_secrets.md#иерархия-и-приоритет-переменных-precedence)**.
3.  **Этап выполнения (Job Execution):** Runner получает итоговый набор переменных в окружение задачи. `script`, `before_script`, `after_script` выполняются в изолированном shell.

> **Важно:** `spec:inputs` не являются CI/CD переменными и не участвуют в этой иерархии. Они интерполируются на этапе компиляции YAML до разрешения переменных.

### Environment Scope и изоляция

Для обеспечения безопасности (Security by Design) применяются следующие механизмы изоляции:

*   **Environment Scope** — секреты продакшена доступны только задачам с `environment: name: production`. Настраивается через `environment_scope` в UI переменной.
*   **Protected Scoping** — флаг `Protected` гарантирует, что переменная не будет доступна в пайплайнах, запущенных из незащищенных веток (защита от кражи секретов через Fork/Feature branches).
*   **Minimum Role Requirement (19.2+)** — настройка, позволяющая ограничить возможность использования переменных пайплайна только для ролей `Maintainer` и выше.

## Практические сценарии

### Сценарий 1: Типы переменных и их применение

```yaml
variables:
  # Глобальная переменная (доступна во всех задачах)
  DOCKER_REGISTRY: "registry.gitlab.example.com"
  # Сырая переменная — не расширяет $VAR внутри значения
  RAW_TOKEN: "pr-${CI_COMMIT_REF_SLUG}"
  RAW_TOKEN_ESCAPED:
    value: "pr-${CI_COMMIT_REF_SLUG}"
    raw: true

stages:
  - deploy

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  environment:
    name: production
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Валидация:**
```bash
# Проверка развертывания переменных
glab ci lint --dry-run --variable CI_COMMIT_BRANCH=main
# → merged YAML содержит DOCKER_REGISTRY и RAW_TOKEN_ESCAPED
```

### Сценарий 2: Защищенные и маскированные переменные

В UI GitLab (**Settings > CI/CD > Variables**) настройте:

| Переменная | Тип | Защищена? | Маскирована? | Где используется |
|:---|:---|:---|:---|:---|
| `SSH_PRIVATE_KEY` | **File** | Yes | Yes | Деплой по SSH |
| `KUBE_CONTEXT` | Variable | No | No | Kubernetes деплой |
| `VAULT_TOKEN` | Variable | Yes | Yes | Интеграция с Vault |
| `DB_PASSWORD` | Variable | Yes | Yes | Миграции БД |

**Проверка:**
```bash
# В логах задачи защищенные переменные из незащищенных веток не появятся
# Маскированные переменные отображаются как [MASKED]
echo "Token: $VAULT_TOKEN"
# → Token: [MASKED]
```

### Сценарий 3: Передача данных между задачами через dotenv

```yaml
stages:
  - build
  - deploy

build_image:
  stage: build
  image: docker:27.0
  services:
    - docker:27.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    - echo "IMAGE_TAG=$CI_COMMIT_SHORT_SHA" > build.env
  artifacts:
    reports:
      dotenv: build.env

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$IMAGE_TAG
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 4: `spec:inputs` для типизированных параметров

```yaml
# .gitlab-ci.yml
spec:
  inputs:
    deploy_env:
      type: string
      default: staging
      options: [staging, production]
    run_migrations:
      type: boolean
      default: false

stages:
  - deploy

deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace $[[ inputs.deploy_env ]] \
        --set image.tag=$CI_COMMIT_SHORT_SHA
    - if [ "$[[ inputs.run_migrations ]}" = "true" ]; then
        kubectl exec -n $[[ inputs.deploy_env ]] deploy/myapp -- \
          flask db upgrade;
      fi
  environment:
    name: $[[ inputs.deploy_env ]]
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 5: OIDC и временные секреты

```yaml
stages:
  - deploy

deploy_with_vault:
  stage: deploy
  image: alpine:3.21
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  script:
    - apk add --no-cache vault jq
    - export VAULT_TOKEN=$(vault write -field=token auth/jwt/login \
        role=gitlab-deploy-role jwt=$VAULT_ID_TOKEN)
    - vault kv get -format=json secret/projects/my-app/production/db > db.json
    - DB_PASS=$(echo $db.json | jq -r '.data.data.password')
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 6: Environment Scope и переменные окружения

В UI GitLab создайте переменную `DB_PASSWORD` с `environment_scope: production`. Она будет доступна только в задачах с `environment: name: production`.

```yaml
stages:
  - test
  - deploy

test:
  stage: test
  image: python:3.13-slim
  script:
    - pytest tests/
  environment:
    name: staging

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set db.password=$DB_PASSWORD
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 7: Air-gapped среда без внешних хранилищ

```yaml
stages:
  - deploy

variables:
  OFFLINE_MODE: "true"

deploy_offline:
  stage: deploy
  image: registry.internal.example.com/infra/deploy-tool:1.5.0
  script:
    - export DB_PASS=$(cat /run/secrets/db_password)
    - deploy.sh --password "$DB_PASS" --offline
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Валидация:**
```bash
# В air-gapped окружении проверьте доступность registry
curl -I https://registry.internal.example.com/v2/
# → HTTP/1.1 200 OK
```

### Сценарий 8: Emergency apply — временное отключение quality gate

```yaml
stages:
  - deploy

variables:
  DEPLOY_EMERGENCY: "false"

emergency_deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - if [ "$DEPLOY_EMERGENCY" = "true" ]; then
        echo "WARNING: Emergency mode enabled";
        helm upgrade --install myapp ./charts/app --namespace production --force;
      else
        helm upgrade --install myapp ./charts/app --namespace production;
      fi
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

**Валидация:**
```bash
# Проверьте, что emergency deploy требует manual approval
# и имеет повышенный уровень логирования
```

## Конфигурация

### Переменные окружения Runner

```yaml
# Пример конфигурации Runner через variables
variables:
  GIT_STRATEGY: fetch
  GIT_DEPTH: "1"
  RESTRICT_UI_VARIABLES: "true"
```

### Backend config для remote state

```yaml
variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_BACKEND_BUCKET: "terraform-state-${CI_PROJECT_ID}"
```

### Caching

```yaml
variables:
  PIP_CACHE_DIR: "${CI_PROJECT_DIR}/.cache/pip"
  npm_config_cache: "${CI_PROJECT_DIR}/.cache/npm"
```

### GitLab provider credentials

```yaml
variables:
  GITLAB_TOKEN: ${CI_JOB_TOKEN}
```

## Operations and Commands

### Управление переменными через GitLab REST API

**Получение списка переменных проекта:**
```bash
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables" | \
  jq '.[] | {key, value, protected, masked, environment_scope}'
```

**Создание переменной:**
```bash
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data '{
    "key": "DB_PASSWORD",
    "value": "secure_password",
    "protected": true,
    "masked": true,
    "environment_scope": "*"
  }' \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables"
```

**Обновление переменной:**
```bash
curl --request PUT \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data '{
    "value": "new_secure_password",
    "protected": true,
    "masked": true
  }' \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables/DB_PASSWORD"
```

**Удаление переменной:**
```bash
curl --request DELETE \
  --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables/DB_PASSWORD"
```

### Валидация конфигурации

**Проверка через CI Lint API:**
```bash
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"content": "'"$(cat .gitlab-ci.yml)"'"}' \
  "https://gitlab.example.com/api/v4/ci/lint"
```

**Просмотр merged YAML:**
```bash
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/merge_requests/$MR_IID/ci_config"
```

**CLI-валидация:**
```bash
# Локальная проверка
glab ci lint
glab ci lint --dry-run --variable CI_COMMIT_BRANCH=main

# Проверка всех веток
for BRANCH in main develop feature/test; do
  glab ci lint --dry-run --variable CI_COMMIT_BRANCH=$BRANCH
done
```

### Диагностика переменных в пайплайне

```yaml
debug_vars:
  stage: .pre
  script:
    # Вывод всех переменных (осторожно с секретами!)
    - env | sort
    
    # Просмотр конкретной переменной
    - echo "Current branch: $CI_COMMIT_BRANCH"
    - echo "Deploy target: $DEPLOY_ENV"
    
    # Проверка, задана ли переменная
    - |
      if [ -z "$DB_PASSWORD" ]; then
        echo "ERROR: DB_PASSWORD is not set"
        exit 1
      fi
  needs: []
  rules:
    - when: always
```

### Резервное копирование переменных

```bash
# Экспорт всех переменных проекта в JSON
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables" | \
  jq '.[] | {key, value, protected, masked, environment_scope}' > project_variables_backup.json

# Импорт переменных из бэкапа
jq -r '.[] | @base64' project_variables_backup.json | while read var; do
  _jq() {
    echo ${var} | base64 -d | jq -r ${1}
  }
  curl --request POST \
    --header "PRIVATE-TOKEN: $TOKEN" \
    --header "Content-Type: application/json" \
    --data "$(echo ${var} | base64 -d)" \
    "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables"
done
```

## Валидация и проверка

1. **CI Lint:** Проверьте синтаксис YAML и развертывание переменных в **CI/CD > Editor > Validate**
2. **Masked variables:** Запустите пайплайн и убедитесь, что переменная отображается как `[MASKED]` в логах
3. **Protected variables:** Попробуйте запустить пайплайн из незащищенной ветки — переменная не должна быть доступна
4. **File variables:** Убедитесь, что файл создан на Runner: `ls -la $SSH_PRIVATE_KEY`
5. **spec:inputs:** Проверьте интерфейс **Run pipeline** — должны отображаться выпадающие списки и флажки
6. **dotenv passing:** Проверьте, что переменные передаются только между задачами с `needs`
7. **Raw variables:** Проверьте, что переменная с `raw: true` не расширяет `$VAR` внутри значения

## Troubleshooting

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Variable not found** | Переменная определена в другом scope | Проверьте иерархию приоритетов. Убедитесь, что переменная доступна на уровне проекта/группы. |
| **Masked variable not working** | Значение содержит пробелы или менее 8 символов | Используйте минимум 8 символов без пробелов. С версии 18.3 маскирование автоматическое. |
| **Protected variable unavailable** | Пайплайн запущен из незащищенной ветки | Переместите ветку в Protected Branches или снимите флаг Protected с переменной. |
| **File variable empty** | Файл не был создан или очищен | Проверьте права на директорию Runner. Убедитесь, что `before_script` не удаляет файл. |
| **spec:inputs not showing** | Устаревшая версия GitLab | `spec:inputs` в корневом файле доступен с GitLab 17.11+. |
| **dotenv not passing** | Задача-потребитель не указана в `needs` | Dotenv переменные работают только между задачами, связанными через `needs`. |
| **Raw variable expanded** | Атрибут `raw: true` не установлен | Явно установите `raw: true` для переменных, содержащих `$`. |
| **Environment variable wrong value** | Неправильный `environment_scope` | Проверьте настройку scope в UI переменной. |
| **CI_JOB_TOKEN 403 Forbidden** | Целевой проект не добавлен в Inbound Allowlist | Перейдите в Settings -> CI/CD -> Token Access и добавьте проект-источник в список разрешенных. |
| **Masked variable with newlines** | Маскированная переменная содержит символы перевода строки | Используйте `File` тип переменной для многострочных данных. |
| **Variable expansion failed** | Циклическая ссылка переменных (`$A` ссылается на `$B`, `$B` на `$A`) | Проверьте вложенные ссылки. С версии 18.6+ expansion отключен по умолчанию. |
| **spec:inputs not found** | Неверный путь к компоненту или имя input | Проверьте `include:component` и `spec:inputs`. |
| **Hidden variable not visible** | Переменная скрыта даже для администраторов | После сохранения Hidden переменной просмотр невозможен. Удалите и создайте заново при необходимости. |

## Лучшие практики (Best Practices)

### Безопасность

**Для Security Engineer:**
*   Включите **Fine-grained Permissions** для `CI_JOB_TOKEN` (GitLab 18.3+) — ограничьте область действия токена конкретными правами (`read_registry`, `write_pages` и т.д.)
*   Настройте **Inbound Allowlist** для межпроектных вызовов через `CI_JOB_TOKEN` (GitLab 18.0+)
*   Используйте **GitLab Secrets Manager** (19.2+) для нативного хранения секретов с аудитом доступа
*   Включите автоматическое маскирование новых переменных (GitLab 18.3+)
*   Настройте `restrict_user_defined_variables` / `pipeline_variables_minimum_override_role` для ограничения Pipeline Variables по роли (18.0+)

**Для DevOps/SRE:**
*   Используйте `id_tokens` (OIDC) вместо статических токенов Vault/Kubernetes
*   Для production секретов используйте `Hidden` переменные (доступны только для чтения)
*   Ограничьте `environment_scope` для production переменных
*   Настройте **Secretless-подход**: временные токены через OIDC вместо долгоживущих секретов
*   Ротируйте секреты регулярно (каждые 90 дней)

**Для Sysadmin:**
*   Используйте `Protected` + `Masked` + тип `File` для критичных секретов
*   Храните SSH-ключи и сертификаты только в переменных типа `File`
*   Настройте separate Runner'ы для production задач с protected переменными
*   Включите аудит изменений переменных через Audit Logs

### Производительность

*   Используйте `spec:inputs` вместо свободных переменных для типизации и валидации
*   Для динамических данных между задачами используйте `dotenv` артефакты
*   Устанавливайте `expire_in` для артефактов с секретами
*   Используйте `raw: true` для переменных, содержащих regex или спецсимволы
*   Минимизируйте количество переменных в UI — используйте `description` и `options` для удобства

### Надёжность

*   Документируйте все переменные в `.gitlab-ci.yml` через `description`
*   Используйте `options` для переменных с ограниченным набором значений
*   Настраивайте Pipeline Execution Policies для принудительного использования секретов из Vault
*   Настройте **alerting** на изменения критичных переменных через Audit Event Hooks
*   Тестируйте изменения в staging перед применением в production

### Мониторинг и observability

*   **Audit Logs:** Включите логирование всех изменений переменных проекта/группы
*   **Event Hooks:** Настройте webhook на изменение критичных переменных для алертинга
*   **Pipeline Metrics:** Отслеживайте количество пайплайнов, упавших из-за отсутствия переменных
*   **Secret Access Logs:** Используйте GitLab Secrets Manager (19.2+) для аудит доступа к секретам на уровне деплоя

### Ротация и управление жизненным циклом

*   Настройте scheduled пайплайны для автоматической ротации секретов
*   Используйте `expires_at` в Secrets Manager для автоматического истечения
*   Ведите реестр всех production секретов с указанием владельца и срока действия
*   Настройте напоминания о ротации в ITSM/ServiceNow

### Ограничения и крайние случаи (Edge Cases)

#### Технические лимиты переменных

| Параметр | Лимит | Примечание |
|:---|:---|:---|
| Максимум переменных проекта | 500 | Включая group/instance |
| Максимальная длина значения | 10 КБ | Для masked: минимум 8 символов |
| Максимум `spec:inputs` | 50 | На компонент |
| Максимальная длина имени переменной | 255 символов | Регистронезависимое |

#### Несовместимость переменных

| Конфликт | Описание | Решение |
|:---|:---|:---|
| `masked` + значения с пробелами | GitLab не может маскировать строки с пробелами | Используйте `type: file` |
| `masked` + короткие значения (<8 символов) | Слишком короткие для надежного маскирования | Увеличьте длину или используйте `type: file` |
| `protected` + незащищенные ветки | Переменная недоступна в feature branches | Временно отключите `protected` для тестов |
| `raw: true` + `expansion` | `raw` отключает расширение вложенных ссылок | Используйте `raw` только при необходимости |
| `dotenv` + `needs` | Dotenv переменные видны только в зависимых задачах | Добавьте задачу в `needs` |
| `spec:inputs` + переменные | Inputs обрабатываются до переменных | Динамические имена переменных через inputs невозможны |

#### Масштаб репозитория

*   **Большие репозитории (>1GB):** Могут вызывать таймауты при `git clone`. Используйте `GIT_DEPTH: "1"` для shallow clone или настройте `GIT_STRATEGY: fetch`.
*   **Монорепозитории:** При множественных `include` из разных проектов учитывайте лимит 50 файлов на пайплайн. Используйте `rules:changes` для запуска только затронутых сервисов.

#### Параллелизм и ресурсы

*   **Конфликты ресурсов:** При параллельном выполнении задач убедитесь, что они не конфликтуют по портам, файлам или Docker-образам. Используйте `resource_group` для взаимного исключения.
*   **Ограничение параллелизма:** Глобальный параметр `concurrent` в `config.toml` ограничивает максимальное количество одновременных задач на Runner. При превышении задачи переходят в статус `pending`.

#### Специфичные ограничения

*   **Windows Runner:** Нет поддержки `services` (Docker Compose-style sidecar) и `docker-autoscaler`. Ограниченная совместимость с CI/CD-образами (Ubuntu-based).
*   **Shell Executor:** Отсутствует изоляция между задачами. Задачи могут конфликтовать по файлам, переменным среды и портам. Используйте только для простых системных задач.
*   **`gitlab-runner exec`:** Не поддерживает `services`, `include`, Protected/Masked переменные и кэш/артефакты. Используйте только для локальной отладки синтаксиса.

#### Версионная совместимость

| Функция | Минимальная версия | Примечание |
|:---|:---|:---|
| `spec:inputs` (базовый) | 17.0+ | Типизация, значения по умолчанию |
| `spec:inputs` + `regex` | 17.10+ | Валидация регулярными выражениями |
| `spec:inputs` + `options` | 18.0+ | Выпадающий список в UI |
| `description` в Variables | 19.0+ | Описание переменных в UI |
| GitLab Secrets Manager (GA) | 19.2+ | Нативное управление секретами |
| `raw: true` для переменных | 17.3+ | Отключение расширения вложенных ссылок |
| Default masked | 18.3+ | Автоматическое маскирование новых переменных |
| `CI_JOB_TOKEN` Fine-grained | 18.3+ | Тонкая настройка прав токена |
| Inbound Allowlist | 17.0+ | Защита `CI_JOB_TOKEN` белым списком |
| `id_tokens` (OIDC) | 16.0+ | Федеративная аутентификация |

## Очистка

```bash
# Удаление устаревших переменных проекта через API
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables/OLD_VAR"

# Пакетная очистка переменных через glab
glab api projects/$PROJECT_ID/variables | jq -r '.[].key' | \
  xargs -I {} glab api projects/$PROJECT_ID/variables/{} -X DELETE

# Экспорт переменных перед очисткой
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables" | \
  jq '.[] | {key, protected, masked, environment_scope}' > variables_audit.json
```

## Дополнительная информация

### Смотрите также

*   **[Переменные и секреты GitLab CI/CD](../Concepts/gitlab_ci_variables_secrets.md)** — полная теория, иерархия приоритетов, OIDC
*   **[Окружения и развертывания](../Concepts/environments_and_deployments.md)** — environment scope и deployment variables
*   **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — защита CI_JOB_TOKEN и Fine-grained Permissions
*   **[Pipeline Execution Policies](../Advanced/compliance_and_audit.md)** — принудительное управление секретами на уровне группы
*   **[API и Webhooks автоматизация](../Advanced/api_and_webhooks_automation.md)** — программное управление переменными
