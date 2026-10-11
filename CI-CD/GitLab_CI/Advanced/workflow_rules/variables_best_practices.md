# Переменные и лучшие практики CI/CD

**Актуально для:** GitLab CI/CD 17.x–19.x

## Определения

- **CI/CD переменная** — пара `key=value`, используемая для параметризации пайплайна, передачи секретов и управления окружением. Полные определения и иерархию приоритетов см. в **[Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md)**.
- **Защищенная переменная (`Protected`)** — доступна только в пайплайнах защищенных веток/тегов.
- **Маскированная переменная (`Masked`)** — значение скрывается в логах (`[MASKED]`). С 18.3 применяется автоматически к новым переменным.
- **Скрытая переменная (`Hidden`)** — значение полностью скрыто в UI и логах, даже для администраторов.
- **Переменная типа `File`** — содержимое записывается во временный файл на Runner, переменная хранит путь.
- **Сырая переменная (`Raw`)** — отключено автоматическое расширение вложенных ссылок.
- **GitLab Secrets Manager** — нативное хранилище секретов (public beta 19.0, GA 19.3).
- **`dotenv` переменные** — пары `key=value`, передаваемые между задачами через `artifacts:reports:dotenv`.
- **`spec:inputs`** — типизированные параметры компонентов, интерполируемые на этапе компиляции YAML (не являются CI/CD переменными).
- **Pipeline Variables** — переменные, передаваемые при ручном запуске пайплайна через UI/API. С 18.0+ доступность регулируется через `restrict_user_defined_variables` / `pipeline_variables_minimum_override_role`.
- **`CI_JOB_TOKEN`** — кратковременный токен задачи, используемый для межпроектных взаимодействий. С 17.0+ требует настройки Inbound Allowlist.

## Предварительные требования

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `spec:inputs` (базовый) | 17.0+ | Типизация, значения по умолчанию |
| `spec:inputs` + `regex` | 17.10+ | Валидация регулярными выражениями |
| `spec:inputs` + `options` | 18.0+ | Выпадающий список в UI |
| `description` в Variables | 19.0+ | Описание переменных в UI |
| GitLab Secrets Manager | 19.0+ public beta, 19.3+ GA | Нативное управление секретами |
| `raw: true` для переменных | 17.3+ | Отключение расширения вложенных ссылок |
| Default masked (18.3+) | 18.3+ | Автоматическое маскирование новых переменных |
| `CI_JOB_TOKEN` Fine-grained | 18.3+ | Тонкая настройка прав токена |
| Inbound Allowlist | 17.0+ | Защита `CI_JOB_TOKEN` белым списком |
| `restrict_user_defined_variables` | 18.0+ | Ограничение Pipeline Variables по роли |
| `id_tokens` (OIDC) | 16.0+ | Федеративная аутентификация |

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

Данный справочник предназначен для DevOps-инженеров, SRE и системных администраторов, работающих с on-premise инфраструктурой. Примеры ориентированы на Ansible, Salt/Puppet и другие инструменты автоматизации инфраструктуры.

- **Minimum Role Requirement (18.0+):** Настройка `restrict_user_defined_variables` / `pipeline_variables_minimum_override_role`, позволяющая ограничить возможность использования Pipeline Variables только для ролей `Maintainer` и выше. На GitLab.com для новых групп по умолчанию стоит `no_one_allowed`.

## Базовые концепции

В архитектуре GitLab 19.x управление переменными строится на принципе **явных контрактов** и многоуровневой изоляции. Использование глобальных неявных переменных считается антипаттерном.

### Архитектура потока переменных

Понимание жизненного цикла переменной необходимо для диагностики и hardening:

1.  **Этап компиляции (Pipeline Compilation):** GitLab собирает итоговый YAML из всех `include`, интерполирует `spec:inputs`, разрешает `!reference` и `extends`. На этом этапе переменные еще не существуют — работают только `inputs`.
2.  **Этап разрешения (Resolution):** Определяются значения CI/CD переменных из всех источников (UI settings, `.gitlab-ci.yml`, `rules:variables`) с учетом иерархии приоритетов. Полная иерархия описана в **[Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md#иерархия-и-приоритет-переменных-precedence)**.
3.  **Этап выполнения (Job Execution):** Runner получает итоговый набор переменных в окружение задачи. `script`, `before_script`, `after_script` выполняются в изолированном shell.

> **Важно:** `spec:inputs` не являются CI/CD переменными и не участвуют в иерархии приоритетов. Они интерполируются на этапе компиляции, до разрешения переменных.

### Эволюция управления данными

1.  **Наследование и переопределение (Legacy):** Глобальные переменные на уровне проекта/группы. Главный недостаток — сложность отслеживания источника значения (Configuration Drift).
2.  **Композиция через шаблоны:** `extends` и `!reference`. Позволяет переиспользовать блоки, но не обеспечивает валидацию входящих данных.
3.  **Изоляция и типизация (Modern):** **CI/CD Components** и `spec:inputs`. Каждый модуль имеет четко определенный интерфейс, описание и типы данных.

### Поведение расширения переменных (Expansion)

С версии **18.6** автоматическое расширение вложенных ссылок (`$VAR1` внутри значения `$VAR2`) **отключено по умолчанию**. Это изменение затрагивает только CI/CD Variables, определенные в UI Settings; переменные в YAML по-прежнему расширяются по умолчанию.

- **`expand: true`** (явное): Разрешает расширение. Доступно только для переменных, определенных в YAML.
- **`expand: false`** (явное): Отключает расширение. Рекомендуется для значений, содержащих `$` или другие спецсимволы, которые не должны интерпретироваться как ссылки.
- **`raw: true`** (17.3+): Полностью отключает любую обработку значения парсером GitLab. Гарантирует буквальное восприятие спецсимволов. Несовместим с маскированием (`masked`).

> **Предупреждение:** Маскированные переменные не могут содержать не-алфавитно-цифровые символы кроме `@`, `_`, `-`, `:`, `+`. Если значение требует спецсимволов, используйте `type: file` вместо маскирования.

### Ограничение Pipeline Variables (18.0+)

Настройка `restrict_user_defined_variables` (устаревшее имя) / `pipeline_variables_minimum_override_role` (актуальное) регулирует, кто может передавать переменные при ручном запуске пайплайна:

| Значение | Эффект |
| :--- | :--- |
| `no_one_allowed` | Полный запрет Pipeline Variables. Рекомендуется для продакшна. |
| `owner` | Только владельцы проекта. |
| `maintainer` | Maintainer и выше. |
| `developer` | Developer и выше. |

**Групповой default:** Настройка `pipeline_variables_default_role` на уровне группы задает значение по умолчанию для новых проектов. На GitLab.com для новых групп по умолчанию стоит `no_one_allowed`.

**Миграция:** GitLab предоставляет фоновую миграцию для отключения Pipeline Variables в проектах, которые их никогда не использовали (`Settings > CI/CD > Variables > Disable pipeline variables in projects that don't use them`).

### Защита артефактов от утечки секретов

Маскирование защищает только логи. Ничто не мешает задаче записать секрет в файл и выложить его как артефакт:

```yaml
# Уязвимый паттерн
job:
  script:
    - echo "$SECRET" > secret.txt
  artifacts:
    paths:
      - secret.txt
```

На 2026 год GitLab ведет работу над защитой артефактов (work item #594729), но нативного блокирования еще нет. **Обязательные контрмеры:**

- Никогда не записывайте секреты в файлы без необходимости.
- Используйте `artifacts:paths` с явным списком, исключая файлы с секретами.
- Включите **Pipeline Secret Detection** для сканирования артефактов.
- Для shared runners настройте сетевую сегментацию, чтобы задачи не могли exfil трафик.

### Изоляция Runner'ов

Runner является доверенной средой выполнения. Скомпрометированный Runner может украсть все переменные, доступные задаче:

- **Executor isolation:** Prefer `docker`/`kubernetes` over `shell`. Executor `shell` выполняет задачи в пользовательском пространстве Runner'а — компрометация одного проекта ведет к компрометации всех.
- **Ephemeral runners:** Используйте `MaxBuilds = 1` в Docker Machine или autoscaling, чтобы Runner уничтожался после задачи.
- **Dedicated runners:** Критические проекты (продакшен, инфраструктура) должны иметь выделенные runners, не обслуживающие feature branches.
- **Privileged mode:** Избегайте `privileged` контейнеров на shared runners. Для инфраструктурных задач используйте isolated ephemeral VMs.

### Стратегия отладки приоритетов

Если переменная имеет неожиданное значение, используйте алгоритм диагностики:
1.  **CI Lint / Merged YAML:** Проверьте итоговую конфигурацию после интерполяции `inputs` и `include`.
2.  **Job Environment:** `env | sort` в начале `script` — фактический набор переменных в среде выполнения.
3.  **Audit Logs:** Логи изменений переменных в `Settings > CI/CD > Audit Events`.
4.  **API:** `GET /projects/:id/variables` с указанием `environment_scope` для проверки scoped переменных.

### Ограничение области видимости (Scoping)

Для обеспечения Security by Design применяйте следующие уровни изоляции:
- **Environment Scope:** Секреты продакшена доступны только задачам с `environment: name: production`.
- **Protected Scoping:** Флаг `Protected` гарантирует, что переменная не будет доступна в пайплайнах из незащищенных веток.
- **Minimum Role Requirement (18.0+):** Ограничение Pipeline Variables по роли.
- **Group/Project isolation:** Групповые переменные наследуются проектами. Ближайшая подгруппа имеет приоритет над дальнейшими.
- **Instance-level variables:** Доступны ко всем проектам инстанса. Используйте только для общеинстансных конфигураций (например, общий Vault адрес).

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

### Сценарий 3: Интеграция с GitLab Secrets Manager (19.0+ public beta, 19.3+ GA)

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

Полную иерархию приоритетов переменных, типы переменных и механизмы безопасности см. в **[Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md#иерархия-и-приоритет-переменных-precedence)**.

## DevOps/SRE и on-premise сценарии

### Сценарий 5: Мульти-окружение с `type: file` для Ansible

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

### Сценарий 6: Salt/Puppet с динамическими переменными

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

### Сценарий 7: GitLab CI для on-premise Kubernetes (K3s/K8s)

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

### Сценарий 8: Иерархия переменных для мульти-tenant on-premise

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

**Порядок разрешения:** Полная иерархия приоритетов переменных описана в **[Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md#иерархия-и-приоритет-переменных-precedence)**. Ниже — ключевые правила для мульти-tenant сценариев:

- Group variables: ближайшая подгруппа к проекту имеет приоритет над дальнейшими.
- Project variables override group variables с тем же именем.
- Job-level variables override все вышеперечисленные.
- `spec:inputs` не участвуют в этой иерархии — они интерполируются на этапе компиляции.

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

### Безопасность

1.  **Never commit secrets:** Никогда не коммитьте секреты в репозиторий. Используйте Variables в UI Settings или GitLab Secrets Manager.
2.  **Masked + Protected + Environment Scope:** Для продукционных секретов применяйте все три флага одновременно. Masked скрывает значение в логах, Protected ограничивает доступ защищенными ветками, Environment Scope ограничивает окружением.
3.  **Prefer `type: file` для многострочных секретов:** SSH-ключи, сертификаты и JSON-ключи сервисов лучше передавать через `type: file`, а не как строковые переменные. Это исключает проблемы с маскированием и спецсимволами.
4.  **Минимизируйте `CI_DEBUG_TRACE`:** Отладочный вывод содержит все переменные в открытом виде. Используйте его только в изолированных заданиях на доверенных runners, никогда на shared runners.
5.  **OIDC вместо долгоживущих ключей:** Для интеграции с внешними системами (Vault, Kubernetes, облачные провайдеры) используйте `id_tokens` и кратковременные JWT вместо статических токенов в переменных.
6.  **Secrets Manager для новых проектов:** Начиная с GitLab 19.3, Secrets Manager является GA. Для новых проектов предпочитайте его CI/CD Variables — секреты не хранятся в базе GitLab и не участвуют в иерархии переменных.
7.  **Runner isolation:** Shared runners должны иметь минимальные права. Для критических проектов используйте dedicated runners с executor `docker`/`kubernetes` и без `privileged` режима.
8.  **Audit all variables:** Периодически экспортируйте переменные проекта/группы через API и проверяйте, нет ли лишних или устаревших записей.

### Организация

9.  **Нейминг:** Используйте префиксы для группировки: `VAULT_*`, `KUBE_*`, `DEPLOY_*`. Избегайте общих имен типа `TOKEN` или `KEY`.
10. **Group-level defaults:** Общие конфигурации (Vault адрес, окружение, регион) выносите на уровень группы. Специфичные для проекта — на проект. Секреты — только на проект.
11. **Documentation:** Каждая переменная, определенная в YAML, должна иметь комментарий. Для UI-переменных используйте поле `description`.
12. **`spec:inputs` вместо Pipeline Variables:** Для параметризации пайплайна используйте `spec:inputs` в компонентах. Они обеспечивают типизацию, валидацию и явный контракт. Pipeline Variables отключайте через `restrict_user_defined_variables`.
13. **`dotenv` только для DAG:** Используйте `artifacts:reports:dotenv` только для передачи данных между зависимыми задачами в DAG. Не используйте для передачи секретов — артефакты могут быть скачаны.
14. **`after_script` не наследует изменения:** Изменения переменных в `script` не видны в `after_script` (отдельный shell). Для передачи данных используйте файлы или артефакты.

### Производительность и надежность

15. **Кэширование переменных:** GitLab кэширует разрешенные переменные на уровне пайплайна. При массовом изменении переменных в UI учитывайте кэширование — изменения могут появиться с задержкой.
16. **Artifact retention:** Ограничивайте срок хранения артефактов с `dotenv` файлами. Чем дольше хранятся артефакты, тем выше риск утечки динамических секретов.
17. **Matrix и dotenv:** Dotenv переменные **не работают** между инстансами матрицы (`parallel:matrix`). Для передачи данных используйте общие артефакты или API.

Полный перечень рекомендаций по безопасности, организации и производительности см. в **[Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md#лучшие-практики)**.

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
| `Variable is empty or missing` | Переменная не определена или опечатка в имени | Проверьте регистр, пробелы и приоритеты. Используйте `env \| sort` в задаче. |
| `Masked variable showing in logs` | Значение нарушает требования маскирования (пробелы, <8 символов, спецсимволы) | Используйте `type: file` или `raw: true`. Для сложных значений Base64-encode. |
| `Protected variable not available` | Запуск из незащищенной ветки/тега | Проверьте `protected` флаг и тип ветки. MR из fork не имеет доступа к protected variables. |
| `Insufficient permissions to set pipeline variables` | Роль пользователя ниже `pipeline_variables_minimum_override_role` | Измените роль в `Settings > CI/CD > Variables` или запросите доступ у Maintainer. |
| `CI_JOB_TOKEN 403 Forbidden` | Целевой проект не в Inbound Allowlist | Добавьте проект-источник в `Settings > CI/CD > Token Access`. |
| `dotenv не передается` | Задача не в `needs` или артефакт не найден | Добавьте задачу в `needs`. Проверьте путь к файлу в `artifacts:reports:dotenv`. |
| `Variable expansion loop` | Циклическая ссылка (`A=$B`, `B=$A`) | Используйте `raw: true` или пересмотрите логику переменных. |
| `spec:inputs not found` | Неверный путь к компоненту или имя input | Проверьте `include:component` и `spec:inputs`. |
| `Artifact contains masked value` | Задача записала секрет в файл и выложила как артефакт | Включите Pipeline Secret Detection. Пересмотрите задачу — секреты не должны попадать в артефакты. |
| `CI_DEBUG_TRACE leaks secrets` | Включен отладочный режим на shared runner | Отключите `CI_DEBUG_TRACE`. Проверьте Audit Logs на предмет доступа к логам. |

### Диагностика переменных в пайплайне

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

Полный перечень рекомендаций по диагностике см. в **[Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md#диагностика-и-устранение-неполадок)**.

## Граничные случаи и ограничения

### Технические лимиты переменных

| Параметр | Лимит | Примечание |
| :--- | :--- | :--- |
| Максимум переменных проекта | 500 | Включая group/instance |
| Максимальная длина значения | 10 000 символов | Для masked: минимум 8 символов, без пробелов |
| Максимум `spec:inputs` | 50 | На компонент |
| Максимальная длина имени переменной | 255 символов | Только буквы, цифры и `_` |
| Максимум `options` в `spec:inputs` | 50 значений | На один input |
| Максимальная длина `$[[ ... ]]` interpolation | 1 КБ на выражение | 1 МБ итоговый размер после разрешения |
| Время разрешения `include` | 30 секунд | Для remote includes |
| Длина `description` переменной | 255 символов | Отображается в UI при ручном запуске |

### Несовместимость переменных

| Конфликт | Описание | Решение |
| :--- | :--- | :--- |
| `masked` + значения с пробелами | GitLab не может маскировать строки с пробелами | Используйте `type: file` |
| `masked` + короткие значения (<8 символов) | Слишком короткие для надежного маскирования | Увеличьте длину или используйте `type: file` |
| `masked` + нестандартные символы | Только `@`, `_`, `-`, `:`, `+` разрешены | Base64-encode значение или используйте `type: file` |
| `protected` + незащищенные ветки | Переменная недоступна в feature branches | Временно отключите `protected` для тестов |
| `raw: true` + `masked` | Несовместимы: `raw` отключает обработку, `masked` требует её | Используйте только один из флагов |
| `raw: true` + `expansion` | `raw` отключает расширение вложенных ссылок | Используйте `raw` только при необходимости |
| `dotenv` + `needs` | Dotenv переменные видны только в зависимых задачах | Добавьте задачу в `needs` |
| `dotenv` + `parallel:matrix` | Не работают между инстансами матрицы | Используйте общие артефакты или API |
| `spec:inputs` + переменные | Inputs обрабатываются до переменных | Динамические имена переменных через inputs невозможны |
| `CI_DEBUG_TRACE` + shared runners | Отладочный вывод виден всем с доступом к логам | Никогда не включайте на shared runners |

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

**Запрет Pipeline Variables (18.0+):**
```yaml
# Если настроено no_one_allowed, ручной запуск с переменными невозможен
# Ошибка: "Insufficient permissions to set pipeline variables"
# Решение: используйте `spec:inputs` в компонентах или запросите доступ
```

**Секреты в артефактах:**
```yaml
# ПРОБЛЕМА: секрет, записанный в файл, попадает в артефакт
# Решение 1: не записывайте секреты в артефакты
# Решение 2: включите Pipeline Secret Detection
# Решение 3: используйте GitLab Secrets Manager (секреты не попадают в артефакты)
```

## Смотрите также

- **[Основы GitLab CI/CD](../../Concepts/gitlab_ci_basics.md)** — база по стадиям и архитектуре.
- **[Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md)** — справочник по переменным, иерархии приоритетов и безопасности.
- **[Продвинутые рабочие процессы](../gitlab_ci_advanced_workflow.md)** — архитектура пайплайнов.
- **[Справочник директив](./directives_definitions.md)** — полный перечень директив с описаниями.
- **[Правила запуска задач](./job_rules.md)** — логика условного включения задач.
- **[DAG и needs](./dag_with_needs.md)** — построение графа зависимостей.
- **[Отладка и устранение неполадок](../debugging_and_troubleshooting.md)** — `glab` и `CI_DEBUG_TRACE`.
- **[Программная автоматизация: API и Webhooks](../api_and_webhooks_automation.md)** — управление переменными через API.
- **[Обзор Runner и Executor](../gitlab_ci_runners_executors.md)** — изоляция Runner'ов и executor types.
- **[Окружения и развертывания](../../Concepts/environments_and_deployments.md)** — protected environments и deployment tokens.
- **[Кэширование и артефакты](../gitlab_ci_caching/caching_overview.md)** — стратегии кэширования.
- **[Артефакты в GitLab CI](../gitlab_ci_caching/gitlab_ci_artifacts.md)** — управление артефактами и reports.
