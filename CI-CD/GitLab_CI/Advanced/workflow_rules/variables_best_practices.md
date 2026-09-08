# Переменные и лучшие практики CI/CD

## Предварительные требования

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `spec:inputs` (базовый) | 17.0+ | Типизация, значения по умолчанию |
| `spec:inputs` + `regex` | 17.10+ | Валидация регулярными выражениями |
| `spec:inputs` + `options` | 18.0+ | Выпадающий список в UI |
| `description` в Variables | 19.0+ | Описание переменных в UI |
| GitLab Secrets Manager (GA) | 19.2+ | Нативное управление секретами |
| `raw: true` для переменных | 17.3+ | Отключение расширения вложенных ссылок |
| Default masked (18.3+) | 18.3+ | Автоматическое маскирование новых переменных |
| `CI_JOB_TOKEN` Fine-grained | 18.3+ | Тонкая настройка прав токена |
| Inbound Allowlist (18.0+) | 18.0+ | Защита `CI_JOB_TOKEN` белым списком |
| `id_tokens` (OIDC) | 16.0+ |联邦ная аутентификация |

### Необходимые знания

- Базовый синтаксис YAML и структура `.gitlab-ci.yml`
- Концепции стадий, задач, артефактов и кэша
- Предопределённые переменные GitLab (`CI_*`)
- Основы shell-скриптинга для написания команд
- Работа с Merge Request и ветками в Git
- Принципы Zero Trust и最小权限 (Least Privilege)

### Инструменты диагностики

- **CI Lint** — валидация конфигурации до запуска пайплайна
- **Pipeline Editor** — визуальный редактор с предпросмотром графа задач
- **`glab ci lint`** — CLI-утилита для локальной проверки конфигурации
- **"View merged YAML"** — просмотр итоговой конфигурации после всех merge/include/inputs
- **`CI_DEBUG_TRACE`** — включение отладочного вывода для анализа переменных
- **Audit Logs** — логи изменений переменных в настройках проекта

### Целевая аудитория

Данный справочник предназначен для DevOps-инженеров, SRE и системных администраторов, работающих с on-premise и гибридной инфраструктурой. Примеры ориентированы на Terraform, Ansible, Salt/Puppet и другие инструменты IaC и автоматизации инфраструктуры.

## Определения

- **Встроенные переменные (Predefined Variables):** Динамические значения, автоматически внедряемые GitLab в среду выполнения задачи. Содержат контекст коммита, ветки, пайплайна и метаданные раннера.
- **Входные параметры (spec:inputs):** Декларативный интерфейс конфигурации (введен в GitLab 17.0), поддерживающий строгую типизацию (`string`, `number`, `boolean`, `array`). В отличие от переменных, они интерполируются на этапе компиляции YAML, что предотвращает ошибки времени выполнения.
- **Маскированные переменные (Masked Variables):** Механизм фильтрации вывода логов. Значения, помеченные как маскированные, заменяются на `[masked]` в консоли Runner'а.
- **Environment Scoped Variables:** Переменные, область видимости которых ограничена конкретным окружением (`environment: name`), что позволяет безопасно разделять секреты разработки и продакшена.
- **OIDC/ID Tokens:** Временные JWT-токены для федерации идентичности (Workload Identity Federation), исключающие необходимость хранения долгоживущих секретов в переменных проекта.

## Базовые концепции

В 2026 году (GitLab 19.x / 20.x) архитектура управления данными в CI/CD базируется на принципе **явных контрактов**. Использование глобальных неявных переменных считается антипаттерном.

### Эволюция управления данными

1.  **Наследование и переопределение (Legacy):** Использование глобальных переменных на уровне проекта/группы. Главный недостаток — сложность отслеживания источника значения (Configuration Drift).
2.  **Композиция через шаблоны:** Использование `extends` и `!reference`. Позволяет переиспользовать блоки, но не обеспечивает валидацию входящих данных.
3.  **Изоляция и типизация (Modern):** Использование **CI/CD Components** и `spec:inputs`. Каждый модуль имеет четко определенный интерфейс, описание и типы данных.

### Стратегия отладки приоритетов

Если переменная имеет неожиданное значение, используйте следующий алгоритм диагностики:
1.  **CI Lint:** В интерфейсе GitLab проверьте "Merged YAML", чтобы увидеть итоговую конфигурацию после интерполяции `inputs`.
2.  **Job Environment:** Выполните команду `env` в начале секции `script`, чтобы увидеть фактический набор переменных в среде выполнения.
3.  **Audit Logs:** В настройках проекта проверьте логи изменений переменных, если есть подозрение на ручное вмешательство.

### Ограничение области видимости (Scoping)

Для обеспечения безопасности (Security by Design) применяйте следующие уровни изоляции:
- **Environment Scope:** Секреты продакшена доступны только задачам с `environment: name: production`.
- **Protected Scoping:** Флаг `Protected` гарантирует, что переменная не будет доступна в пайплайнах, запущенных из незащищенных веток (защита от кражи секретов через Fork/Feature branches).
- **Minimum Role Requirement (19.2+):** Настройка, позволяющая ограничить возможность использования переменных пайплайна только для ролей `Maintainer` и выше.

## Практические сценарии

### Сценарий 1: Оптимизация жизненного цикла через workflow

Использование `workflow:rules` совместно с `auto_cancel` позволяет экономить ресурсы и предотвращать конфликты деплоев.

```yaml
workflow:
  auto_cancel:
    on_new_commit: interruptible
    on_job_failure: all # Fail-fast: останавливает весь граф при ошибке
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - when: never # Запрет запуска в остальных случаях (например, пуш в ветку без MR)
```

**Рекомендация:** Для критических задач (деплой, миграция БД) всегда устанавливайте `interruptible: false`, чтобы `auto_cancel` не прервал транзакционный процесс.

### Сценарий 2: Продвинутая валидация входных данных (spec:inputs)

Использование регулярных выражений и списков выбора (options) для защиты пайплайна.

```yaml
spec:
  inputs:
    deploy_env:
      type: string
      default: staging
      options: [staging, production]
    version:
      type: string
      regex: '^v\d+\.\d+\.\d+$' # Валидация SemVer
    replicas:
      type: number
      default: 2
---
deploy_task:
  script:
    - echo "Deploying version $[[ inputs.version ]] to $[[ inputs.deploy_env ]]"
    - ./deploy.sh --replicas $[[ inputs.replicas ]]
```

### Сценарий 3: Интеграция с GitLab Secrets Manager (19.2+ GA)

Отказ от переменных окружения в пользу нативной инъекции секретов.

```yaml
deploy_prod:
  stage: deploy
  environment: production
  secrets:
    DB_PASSWORD:
      vault: production/database/password@secrets # Путь во внутреннем Secrets Manager
  script:
    - ./connect_db.sh --pass "$DB_PASSWORD"
```

**Преимущество:** Секреты из `Secrets Manager` не сохраняются в базе данных GitLab как обычные переменные и передаются раннеру в зашифрованном виде непосредственно перед выполнением.

### Сценарий 4: Передача динамических данных между задачами (dotenv)

Использование `artifacts:reports:dotenv` для передачи вычисленных значений в DAG-пайплайнах.

```yaml
build_image:
  stage: build
  script:
    - IMAGE_TAG=$(date +%s)
    - echo "BUILD_TAG=$IMAGE_TAG" >> build.env
  artifacts:
    reports:
      dotenv: build.env

deploy_app:
  stage: deploy
  needs: [build_image]
  script:
    - echo "Deploying image with tag $BUILD_TAG"
```

## Дополнительная информация

### Иерархия приоритетов переменных (GitLab 19.x / 20.x)

При конфликте имен GitLab выбирает значение согласно следующему приоритету (от высшего к низшему):

1.  **Trigger variables:** Переданные через API или Web UI при ручном запуске.
2.  **Dotenv variables:** Сгенерированные в предыдущих задачах через `artifacts:reports:dotenv`.
3.  **Scheduled variables:** Из настроек расписания.
4.  **Job variables:** Блок `variables` внутри конкретной задачи.
5.  **Workflow variables:** Блок `variables` внутри `workflow:rules`.
6.  **Pipeline Inputs:** Значения из `spec:inputs` (интерполированные через `[[ inputs.name ]]`).
7.  **Project variables:** Заданные в `Settings > CI/CD > Variables`.
8.  **Group variables:** Заданные на уровне группы.
9.  **Instance variables:** Заданные администратором инстанса.
10. **Predefined variables:** Встроенные переменные GitLab (`CI_*`).
11. **Default variables:** Блок `variables` внутри секции `default`.

### Лучшие практики (Do's and Don'ts)

| Действие | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Do** | Использовать `spec:inputs` | Гарантирует целостность контракта и типизацию. |
| **Do** | Применять OIDC (`id_tokens`) | Исключает использование статических токенов (Zero Trust). |
| **Do** | Использовать `type: file` | Для многострочных конфигов и ключей, чтобы избежать ошибок экранирования. |
| **Don't** | Хранить пароли в `variables` | Используйте `Secrets Manager` или внешние Vault для критических данных. |
| **Don't** | Использовать переменные для логики | Для условий запуска используйте `rules`, а не проверку `if [ "$VAR" == "val" ]` в bash. |

### Смотрите также

- **[Основы GitLab CI/CD](../../Concepts/gitlab_ci_basics.md)** — база по стадиям и архитектуре.
- **[Продвинутые рабочие процессы](../gitlab_ci_advanced_workflow.md)** — детализация `rules` и `needs`.
- **[Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md)** — детальный разбор безопасности и хранилищ.
- **[Справочник директив](./directives_definitions.md)** — полный перечень директив с описаниями.
- **[Правила запуска задач](./job_rules.md)** — логика условного включения задач.
- **[DAG и needs](./dag_with_needs.md)** — построение графа зависимостей.

## DevOps/SRE и on-premise сценарии

### Сценарий 5: Безопасная интеграция Terraform с Vault через OIDC

Использование `id_tokens` для беспарольного доступа к HashiCorp Vault в on-premise среде.

```yaml
.terraform_base:
  image: hashicorp/terraform:1.9
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.internal.example.com
      claims:
        role: ci-terraform
        project: $CI_PROJECT_PATH
  before_script:
    - export VAULT_TOKEN=$(vault write -field=token \
        auth/jwt/login role=terraform-ci jwt=$VAULT_ID_TOKEN)
    - terraform init -backend-config="backend.hcl"

terraform:plan:
  extends: .terraform_base
  stage: plan
  script:
    - terraform plan -out=tfplan
  artifacts:
    paths:
      - terraform/tfplan
    expire_in: 1 day

terraform:apply:
  extends: .terraform_base
  stage: apply
  script:
    - terraform apply -auto-approve tfplan
  environment:
    name: production
  resource_group: terraform_prod
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  interruptible: false
```

**Почему это важно:**
- `id_tokens` исключает долгоживущие токены Vault
- `resource_group` предотвращает параллельный `apply`
- `interruptible: false` защищает от прерывания критических транзакций

### Сценарий 6: Мульти-окружение с `type: file` для Ansible

Безопасная передача SSH-ключей и Vault-паролей через переменные типа `File`.

```yaml
.deploy_template:
  stage: deploy
  image: cytopia/ansible:2.14
  variables:
    ANSIBLE_VAULT_PASSWORD_FILE: $VAULT_PASSWORD_FILE
  before_script:
    - chmod 400 "$SSH_KEY_FILE"
    - eval "$(ssh-agent -s)" && ssh-add "$SSH_KEY_FILE"
  script:
    - ansible-playbook -i inventory/$DEPLOY_ENV site.yml
  after_script:
    - rm -f "$VAULT_PASSWORD_FILE"

deploy:staging:
  extends: .deploy_template
  variables:
    SSH_KEY_FILE:
      value: "$STAGING_SSH_KEY"
      options: ["$STAGING_SSH_KEY", "$STAGING_BASTION_KEY"]
      description: "SSH-ключ для деплоя в staging"
    DEPLOY_ENV: staging
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"
      when: manual

deploy:production:
  extends: .deploy_template
  variables:
    SSH_KEY_FILE: $PRODUCTION_SSH_KEY
    DEPLOY_ENV: production
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  allow_failure: false
```

**Ключевые моменты:**
- `type: file` — SSH-ключ записывается во временный файл, путь передается через переменную
- `ANSIBLE_VAULT_PASSWORD_FILE` — пароль Vault не попадает в логи
- `after_script` очищает временные файлы (даже при ошибке в `script`)

### Сценарий 7: Salt/Puppet с динамическими переменными

Передача результатов обнаружения (grains/facts) между задачами через `dotenv`.

```yaml
discover_hosts:
  stage: prepare
  image: python:3.12
  script:
    - python3 discover_infra.py --output hosts.json
    - |
      cat hosts.json | jq -r '.[] | "HOST=\(.ip) ROLE=\(.role)"' >> hosts.env
  artifacts:
    reports:
      dotenv: hosts.env
    paths:
      - hosts.json

apply_salt_highstate:
  stage: apply
  needs: ["discover_hosts"]
  image: python:3.12
  script:
    - pip install salt
    - salt-key -y --accept-all
    - salt '*' state.highstate pillar='{"role": "$ROLE"}'
  rules:
    - changes:
        paths: ["salt/"]
```

### Сценарий 8: GitLab CI для on-premise Kubernetes (K3s/K8s)

Безопасный деплой через `CI_JOB_TOKEN` с Fine-grained Permissions.

```yaml
variables:
  KUBECONFIG: $CI_PROJECT_DIR/.kube/config

deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  before_script:
    - echo "$KUBE_CA" | base64 -d > /tmp/ca.crt
    - kubectl config set-cluster k8s --server=$KUBE_URL --certificate-authority=/tmp/ca.crt
    - kubectl config set-credentials deployer --token=$CI_JOB_TOKEN
    - kubectl config set-context default --cluster=k8s --user=deployer --namespace=$KUBE_NAMESPACE
    - kubectl config use-context default
  script:
    - kubectl apply -f k8s/
    - kubectl rollout status deployment/app
  permissions:
    contents: read
    kubernetes: deploy
  environment:
    name: k8s-production
```

### Сценарий 9: Иерархия переменных для мульти-tenant on-premise

Использование group/project/CI-CD Variables для изоляции секретов разных команд.

```yaml
# Настройка в GitLab UI:
# Group "infrastructure": VAULT_ADDR=https://vault.infra.internal
# Group "infrastructure/production": VAULT_ROLE=prod-deploy
# Project "infrastructure/production/webapp": VAULT_ROLE=webapp-deploy

deploy_webapp:
  stage: deploy
  script:
    - vault read -field=token auth/approle/login role_id=$VAULT_ROLE_ID secret_id=$VAULT_SECRET_ID
    - ./deploy.sh
  variables:
    # Переопределяем роль на уровне задачи — приоритет выше, чем group variable
    VAULT_ROLE: webapp-deploy
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Порядок разрешения:**
1. `job:variables` (самый высокий)
2. Project Variables (Settings > CI/CD)
3. Group Variables (ближайшая подгруппа)
4. Instance Variables (Admin Area)

## Валидация и отладка переменных

### Методы проверки

**1. CI Lint API:**
```bash
# Проверка синтаксиса и валидация
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --data "content=$(cat .gitlab-ci.yml | base64)" \
  "https://gitlab.example.com/api/v4/ci/lint"
```

**2. Просмотр merged YAML:**
```bash
# Итоговая конфигурация после всех merge/include/inputs
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/merge_requests/$MR_IID/ci_config"
```

**3. CLI-валидация:**
```bash
# Локальная проверка
glab ci lint
glab ci lint --dry-run --variable CI_COMMIT_BRANCH=main

# Проверка всех веток
for BRANCH in main develop feature/test; do
  glab ci lint --dry-run --variable CI_COMMIT_BRANCH=$BRANCH
done
```

### Отладка переменных в пайплайне

**Вывод всех переменных (без секретов!):**
```yaml
debug_vars:
  stage: .pre
  script:
    - echo "=== GitLab CI Variables ==="
    - env | sort | grep -E "^(CI_|GITLAB_)" | head -50
    - echo "=== Custom Variables ==="
    - echo "DEPLOY_ENV=$DEPLOY_ENV"
    - echo "TF_ROOT=$TF_ROOT"
  needs: []
  rules:
    - when: always
```

**Проверка иерархии приоритетов через API:**
```bash
# Все переменные проекта с указанием уровня
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables" | \
  jq '.[] | {key, value, protected, masked, environment_scope}'
```

**Отладка переменных в `rules`:**
```yaml
# Проблема: правило if не работает
# Решение: добавьте отладочный вывод
debug_rules:
  stage: .pre
  script:
    - echo "CI_PIPELINE_SOURCE=$CI_PIPELINE_SOURCE"
    - echo "CI_COMMIT_BRANCH=$CI_COMMIT_BRANCH"
    - echo "CI_MERGE_REQUEST_ID=$CI_MERGE_REQUEST_ID"
    - echo "CI_COMMIT_TAG=$CI_COMMIT_TAG"
  rules:
    - when: always
```

### Валидация `spec:inputs`

```bash
# Проверка что все inputs корректно обрабатываются
# через CI Lint с имитацией значений
glab ci lint --dry-run \
  --variable CI_PIPELINE_SOURCE=merge_request_event \
  --variable CI_COMMIT_BRANCH=main
```

## Лучшие практики

### Безопасность переменных

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| **Never commit secrets** | Никогда не коммитьте секреты в репозиторий | Критический |
| **Masked + Protected** | Для критичных секретов включайте оба флага | Критический |
| **OIDC вместо статических ключей** | Используйте `id_tokens` для аутентификации | Высокий |
| **`type: file`** | Для многострочных конфигов и SSH-ключей | Высокий |
| **`raw: true`** | Для значений с `$` (пароли, конфиги) | Высокий |
| **Environment Scope** | Ограничивайте секреты конкретным окружением | Высокий |
| **Minimum Role (19.2+)** | Ограничьте доступ Maintainer+ для критичных переменных | Средний |
| **CI_JOB_TOKEN Allowlist** | Настройте белый список для доступа между проектами | Средний |

### Организация переменных

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| **Группировка по префиксам** | `TF_*`, `ANSIBLE_*`, `K8S_*` для визуальной сортировки | Высокий |
| **Использование `description`** | Описывайте переменные для ручного запуска | Средний |
| **`options` в `spec:inputs`** | Значения по умолчанию и списки выбора | Средний |
| **Иерархия group/project** | Секреты окружений на уровне группы | Высокий |
| **Документирование** | Храните описание переменных в README проекта | Средний |

### Производительность

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| **Minimize `dotenv` файлы** | Передавайте только необходимые значения | Средний |
| **Кэширование зависимостей** | Используйте `cache` вместо повторной загрузки | Средний |
| **`expire_in` для артефактов** | Не переполняйте хранилище | Низкий |
| **Параллелизация** | Независимые задачи выполняются параллельно | Средний |

### Операционная надежность

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| **`interruptible: false`** | Для критических задач (деплой, миграции) | Высокий |
| **`resource_group`** | Mutex для предотвращения Race Conditions | Высокий |
| **`allow_failure: false`** | Для задач, блокирующих релиз | Средний |
| **`when: manual`** | Для критичных деплоев в продакшен | Средний |
| **Очистка в `after_script`** | Временные файлы, токены, ключи | Средний |

## Граничные случаи и ограничения

### Технические лимиты переменных

| Параметр | Лимит | Примечание |
| :--- | :--- | :--- |
| Максимум переменных проекта | 500 | Включая group/instance |
| Максимальная длина значения | 10 КБ | Для masked: минимум 8 символов |
| Максимум `spec:inputs` | 50 | На компонент |
| Максимальная длина имени переменной | 255 символов | Регистронезависимое |

### Несовместимость переменных

| Конфликт | Описание | Решение |
| :--- | :--- | :--- |
| `masked` + значения с пробелами | GitLab не может маскировать строки с пробелами | Используйте `type: file` |
| `masked` + короткие значения (<8 символов) | Слишком короткие для надежного маскирования | Увеличьте длину или используйте `type: file` |
| `protected` + незащищенные ветки | Переменная недоступна в feature branches | Временно отключите `protected` для тестов |
| `raw: true` + `expansion` | `raw` отключает расширение вложенных ссылок | Используйте `raw` только при необходимости |
| `dotenv` + `needs` | Dotenv переменные видны только в зависимых задачах | Добавьте задачу в `needs` |
| `spec:inputs` + переменные | Inputs обрабатываются до переменных | Динамические имена переменных через inputs невозможны |

### Особые сценарии

**Конфликт переменных группы и проекта:**
```yaml
# Group variable: VAULT_ADDR=https://vault.group.internal
# Project variable: VAULT_ADDR=https://vault.project.internal
# Результат: используется project variable (приоритет выше)
```

**`dotenv` и матричные задачи:**
```yaml
# ПРОБЛЕМА: dotenv переменные НЕ работают между инстансами матрицы
# Решение: используйте artifacts или API
build:
  parallel:matrix:
    - TARGET: [amd64, arm64]
  script:
    - echo "BUILD_$TARGET=true" >> builds.env
  artifacts:
    reports:
      dotenv: builds.env

# Задача, зависящая от ОБЕИХ матричных задач:
deploy:
  needs: ["build: [amd64]", "build: [arm64]"]
  script:
    - echo "All builds done"
```

**Переменные с спецсимволами:**
```yaml
# ПРОБЛЕМА: пароль содержит $ — GitLab пытается расширить
# Решение 1: raw: true
variables:
  DB_PASS:
    value: "p@$$w0rd!#$"
    raw: true

# Решение 2: type: file
variables:
  DB_PASS:
    value: "p@$$w0rd!#$"
    type: file
script:
  - PGPASSWORD=$(cat "$DB_PASS") psql -h db-host
```

**Переменные в `after_script`:**
```yaml
# ВАЖНО: after_script выполняется в ОТДЕЛЬНОМ shell
# Изменения переменных в script НЕ видны в after_script
deploy:
  script:
    - export DEPLOY_STATUS="success"
  after_script:
    - echo $DEPLOY_STATUS  # будет пустым!
  # Решение: передавайте через файл или используйте артефакты
```

## Устранение неполадок

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Variable hidden` | Дубликат имени на другом уровне | Проверьте иерархию переменных |
| `CI_JOB_TOKEN` 403 Forbidden | Целевой проект не в Allowlist | Настройте Token Access в Settings |
| `Masked variable failed` | Значение < 8 символов или содержит пробелы | Увеличьте длину или используйте `type: file` |
| `Variable expansion failed` | Циклическая ссылка переменных | Проверьте вложенные ссылки |
| `spec:inputs not found` | Неверный путь к компоненту или имя input | Проверьте `include:component` и `spec:inputs` |

### Отладка приоритетов

```bash
# Шаг 1: Проверьте merged YAML
glab ci lint --show-expanded

# Шаг 2: Выведите переменные в пайплайне
env | sort | grep -E "^(CI_|GITLAB_|DEPLOY_)" | head -30

# Шаг 3: Проверьте API переменные проекта
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables" | \
  jq '.[] | {key, protected, masked, environment_scope}'

# Шаг 4: Сравните с переменными группы
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/groups/$GROUP_ID/variables" | \
  jq '.[] | {key, protected, masked, environment_scope}'
```

### Решение конфликтов переменных

```yaml
# Симптом: переменная имеет неожиданное значение
# Причина: конфликт приоритетов

# Алгоритм диагностики:
# 1. Найдите все источники переменной с именем VAR_NAME
# 2. Определите уровень каждого источника
# 3. Используйте 최имально узкий scope (job > global > project > group)
# 4. Переименуйте переменную, если конфликт не разрешим

# Пример: явное переопределение
deploy:
  variables:
    # Переопределяем group variable на уровне задачи
    VAULT_ROLE: webapp-deploy
  script:
    - echo "Using role: $VAULT_ROLE"
```

## Смотрите также

- **[Основы GitLab CI/CD](../../Concepts/gitlab_ci_basics.md)** — база по стадиям и архитектуре.
- **[Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md)** — SSoT по переменным, иерархии приоритетов и безопасности.
- **[Продвинутые рабочие процессы](../gitlab_ci_advanced_workflow.md)** — архитектура пайплайнов.
- **[Справочник директив](./directives_definitions.md)** — полный перечень директив с описаниями.
- **[Правила запуска задач](./job_rules.md)** — логика условного включения задач.
- **[DAG и needs](./dag_with_needs.md)** — построение графа зависимостей.
- **[Отладка и устранение неполадок](../debugging_and_troubleshooting.md)** — `glab` и `CI_DEBUG_TRACE`.
- **[Программная автоматизация: API и Webhooks](../api_and_webhooks_automation.md)** — управление переменными через API.
