# Наследование переменных в downstream-пайплайнах

**Актуально для:** GitLab 18.6+ / 19.x

**Наследование переменных** — это архитектурный механизм GitLab CI/CD, обеспечивающий проброс контекстных данных из родительского (upstream) пайплайна в дочерний (downstream). 

Технически процесс управляется компонентом **GitLab Rails**, который в момент создания дочернего пайплайна формирует его начальный набор переменных (Environment), объединяя данные из конфигурации YAML, настроек проекта и переданных триггером значений.

## Основные концепции

### Архитектура и иерархия приоритетов (GitLab 19.x)

Переменные, передаваемые через триггер, получают статус **Trigger/Pipeline Variables**. В иерархии GitLab они обладают одним из самых высоких приоритетов, что позволяет им переопределять значения, заданные в настройках дочернего проекта.

**Порядок вычисления (от высшего к низшему):**

1.  **Trigger Variables:** Переменные, переданные явно через `trigger:variables` или API-вызов.
2.  **Pipeline Inputs:** Типизированные значения из блока `spec:inputs` (интерполируются до создания пайплайна).
3.  **Forwarded Variables:** Переменные, автоматически проброшенные через `trigger:forward`.
4.  **Scheduled/Manual Variables:** Переменные, заданные при ручном запуске родительского пайплайна.
5.  **Project/Group Variables:** Переменные из интерфейса настроек дочернего проекта.
6.  **Dotenv Reports:** Значения, сгенерированные в upstream-задачах и переданные через `artifacts:reports:dotenv`.
7.  **Job Variables:** Переменные, определенные в блоке `variables` внутри дочернего YAML.
8.  **Predefined Variables:** Системные переменные GitLab (`CI_COMMIT_SHA`, `CI_PROJECT_ID` и др.).

> **Важно:** Предопределённые переменные (`CI_*`) **не могут быть переопределены** через `variables` или `trigger:variables`.

### Механизмы передачи (trigger:forward)

Директива `forward` определяет автоматический поток данных между пайплайнами. Это ключевой элемент безопасности в модели Zero Trust.

| Параметр | Описание | По умолчанию (Parent-Child) | По умолчанию (Multi-Project) |
| :--- | :--- | :---: | :---: |
| **`yaml_variables`** | Глобальные переменные из родительского `.gitlab-ci.yml`. | `true` | `false` |
| **`pipeline_variables`** | Переменные запуска (Web UI, API, Scheduled). | `true` | `false` |

**Обоснование различий:**
- **Parent-Child:** Выполняется в том же контексте безопасности. Максимальная прозрачность данных включена по умолчанию.
- **Multi-Project:** Может запускаться в проектах других команд. По умолчанию передача закрыта для предотвращения утечки внутренних настроек (например, имен секретных переменных) во внешние репозитории.

```yaml
# Пример безопасной настройки для межпроектного триггера
trigger-security-scan:
  trigger:
    project: 'security/scanners'
    forward:
      yaml_variables: true      # Передать настройки конфигурации
      pipeline_variables: false # Изолировать от токенов ручного запуска
```

### Изоляция и блокировка (inherit)

Для предотвращения конфликтов имен в сложных иерархиях используется ключевое слово `inherit`. Оно позволяет задаче-триггеру полностью игнорировать глобальные переменные своего файла.

```yaml
deploy-isolated:
  inherit:
    variables: false # Задача не видит глобальный блок variables
  variables:
    DEPLOY_ENV: "staging"
  trigger:
    include: 'ci/deploy.yml'
```

### Типы переменных и их ограничения

GitLab поддерживает несколько типов переменных, каждый со своими ограничениями:

| Тип | Описание | Ограничения |
| :--- | :--- | :--- |
| **Variable** | Обычная переменная окружения | Максимум **200 переменных** на проект (включая group/instance). |
| **File** | Переменная, автоматически записанная в временный файл | Доступна только в задачах, не в триггерах. |
| **Dotenv** | Значения из `artifacts:reports:dotenv` | Максимальный размер файла — **5 МБ**. Превышение приводит к silent failure. |
| **Input** | Типизированный параметр (`spec:inputs`) | Поддерживаемые типы: `string`, `number`, `boolean`, `array`. |

### Protected и Scoped переменные

**Protected Variables** — переменные, доступные только в задачах, выполняющихся в protected ветках или тегах. При передаче через триггер:
- Protected переменная **теряет** свой статус protected в дочернем проекте (если он не protected).
- Рекомендация: используйте отдельные имена с префиксом для protected переменных.

**Scoped Variables** — переменные, привязанные к конкретным условиям:
- **Environment scope:** Доступны только в задачах определенного окружения (например, `production`).
- **Branch scope:** Доступны только в определенных ветках.

```yaml
# Пример: переменная доступна только в production
deploy-prod:
  variables:
    DATABASE_URL: $PROD_DB_URL
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      variables:
        DATABASE_URL: $PROD_DB_URL
```

## Практические сценарии

### Сценарий 1: Современная передача через Inputs (GitLab 18.x+)

Использование `spec:inputs` является рекомендуемым стандартом. В отличие от переменных, входы (inputs) обеспечивают строгую типизацию и валидацию.

**1. Дочерний пайплайн (`child.yml`):**
```yaml
spec:
  inputs:
    replica_count:
      type: number
      default: 1
    environment:
      options: [staging, production]
      default: staging
---
deploy-job:
  script:
    - echo "Deploying to $[[ inputs.environment ]] with $[[ inputs.replica_count ]] replicas"
```

**2. Родительский пайплайн:**
```yaml
trigger-child:
  trigger:
    include:
      - local: 'child.yml'
        inputs:
          replica_count: 3
          environment: production
```

### Сценарий 2: Динамические данные через Dotenv

Паттерн для передачи значений, вычисленных во время выполнения (например, версия сборки или хеш артефакта).

```yaml
# Upstream
prepare-version:
  stage: build
  script:
    - APP_VERSION=$(cat VERSION)-${CI_COMMIT_SHORT_SHA}
    - echo "DYNAMIC_VERSION=${APP_VERSION}" > build.env
  artifacts:
    reports:
      dotenv: build.env

# Downstream
# Автоматически получит $DYNAMIC_VERSION в свое окружение
trigger-deploy:
  stage: deploy
  trigger: 'ops/deploy-repo'
```

**Ограничение:** Dotenv файл не может превышать **5 МБ**. При превышении переменные не загружаются без ошибки (silent failure).

### Сценарий 3: Multi-project изоляция с включением 특정ных переменных

Типичный паттерн для безопасного взаимодействия между проектами разных команд.

```yaml
# Проект: team-app (Родитель)
trigger-shared-scan:
  stage: security
  trigger:
    project: 'shared/security-scanner'
    strategy: mirror
    forward:
      yaml_variables: true   # Передать настройки конфигурации сканера
      pipeline_variables: false # Не передавать токены ручного запуска
    variables:
      SCAN_TARGET: $CI_PROJECT_PATH
      SCAN_REF: $CI_COMMIT_SHA
```

### Сценарий 4: OIDC (id_tokens) вместо секретов

Для безопасной передачи секретов в downstream-проект используйте `id_tokens` (OIDC) вместо `trigger:variables`. Это позволяет дочернему пайплайну получить временный токен для доступа к Vault или внешним сервисам.

```yaml
# Родительский пайплайн
trigger-vault-deploy:
  stage: deploy
  trigger:
    project: 'infra/vault-deploy'
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com

# Дочерний пайплайн (infra/vault-deploy)
deploy-with-vault:
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  script:
    - vault login -method jwt role=deploy-role token=$VAULT_ID_TOKEN
    - export DB_PASSWORD=$(vault kv get -field=password secret/app/db)
    - ./deploy.sh
```

### Сценарий 5: Nested override (parent-child-grandchild)

В иерархии из трёх уровней (родитель → ребенок → внук) переменные переопределяются на каждом уровне. Дочерний пайплайн наследует все `yaml_variables` родителя, но может переопределить их в своем `variables`.

```yaml
# Родитель (grandparent)
variables:
  DEPLOY_ENV: production
  IMAGE_TAG: v1.0

trigger-parent:
  trigger:
    include: 'parent.yml'
    strategy: mirror

# Ребёнок (parent.yml)
variables:
  DEPLOY_ENV: staging  # Переопределяет DEPLOY_ENV

trigger-child:
  trigger:
    include: 'child.yml'
    strategy: mirror

# Внук (child.yml)
script:
  - echo "Deploying to $DEPLOY_ENV" # Выведет: staging
```

### Сценарий 6: Параметризация pipeline через API

Программный запуск downstream-пайплайна с произвольными переменными через Pipeline Triggers API.

```bash
# Запуск downstream-пайплайна с переменными
curl --request POST \
  --form "token=<TRIGGER_TOKEN>" \
  --form "ref=main" \
  --form "variables[DEPLOY_ENV]=staging" \
  --form "variables[IMAGE_TAG]=$CI_COMMIT_SHORT_SHA" \
  "https://gitlab.example.com/api/v4/projects/<PROJECT_ID>/trigger/pipeline"
```

### Сценарий 7: Environment-specific переменные

Использование scope переменных для передачи различных значений в зависимости от окружения.

```yaml
# Дочерний пайплайн (ci/deploy.yml)
spec:
  inputs:
    environment:
      options: [staging, production]
---
deploy:
  script:
    - ./deploy.sh --env $[[ inputs.environment ]] --db-url $DB_URL

# Родительский пайплайн
trigger-staging:
  trigger:
    include:
      - local: 'ci/deploy.yml'
        inputs:
          environment: staging
  variables:
    DB_URL: $STAGING_DB_URL

trigger-production:
  trigger:
    include:
      - local: 'ci/deploy.yml'
        inputs:
          environment: production
  variables:
    DB_URL: $PROD_DB_URL
```

## Безопасность и риски

### Утечка маскированных секретов

При передаче переменных через `trigger:variables` в другой проект свойство **Masked** (скрытие в логах) может быть потеряно. 
**Рекомендация:** Не пробрасывайте секреты напрямую. Используйте **OIDC (ID Tokens)** в дочернем пайплайне для получения временных доступов в Vault или внешние сервисы напрямую.

### Настройка Inbound Allowlist (GitLab 17.0+)

Для безопасного взаимодействия между проектами необходимо явно разрешить доступ к `CI_JOB_TOKEN`.

**Пошаговая инструкция:**
1. Перейдите в **Settings → CI/CD → Job Token Permissions** целевого проекта.
2. В разделе **Allow access to the following projects** добавьте проект-инициатор.
3. Для групповых разрешений используйте **Group-level Token Access**.

> **Важно:** Начиная с GitLab 17.0, доступ через `CI_JOB_TOKEN` **запрещён по умолчанию**. Без добавления проекта в Allowlist любая попытка запуска триггера или скачивания артефактов завершится ошибкой `403 Forbidden`.

### Fine-grained Permissions (GitLab 18.3+)

Тонкая настройка прав доступа `CI_JOB_TOKEN` позволяет ограничить области действия токена:

| Право | Описание |
| :--- | :--- |
| `read_repository` | Чтение файлов проекта. |
| `write_repository` | Запись в Container Registry. |
| `read_api` | Доступ к API (артефакты, пайплайны). |
| `api` | Полный доступ к API. |

```yaml
# Пример: разрешить только чтение артефактов
trigger-artifact-fetch:
  trigger:
    project: 'other/build-project'
    strategy: mirror
  # CI_JOB_TOKEN будет иметь только read_api право
```

### Переполнение Dotenv

Максимальный размер `.env` файла составляет **5 МБ**. Превышение этого лимита приведет к тому, что переменные не будут загружены в дочерний пайплайн без явной ошибки (Silent Failure).

**Рекомендация:** Ограничивайте количество переменных в dotenv-файле. Используйте артефакты для передачи больших объемов данных.

## Диагностика и устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Переменная пуста в Downstream | Использование `forward: pipeline_variables: false` в Multi-project. | Проверьте настройки `forward` в задаче-триггере. |
| Значение переопределено неверно | Конфликт приоритетов (Trigger vs Project variables). | Используйте уникальные префиксы (например, `UPSTREAM_`) для передаваемых данных. |
| Ошибка `inputs` при запуске | Несоответствие типов данных (например, строка вместо числа). | Проверьте `spec:inputs` дочернего пайплайна через Pipeline Lint. |
| Секрет виден в логах | Секрет передан триггером, но не маскирован в дочернем проекте. | Настройте идентичные правила маскирования или используйте HashiCorp Vault. |
| `403 Forbidden` при триггере | Целевой проект не добавлен в Inbound Allowlist. | Добавьте проект в **Settings → CI/CD → Job Token Permissions**. |
| `Variables not passed` | Неверная настройка `trigger:forward` или изоляция multi-project. | Убедитесь, что `yaml_variables: true` и `pipeline_variables: true`. |
| Dotenv не загружается | Размер файла превышает 5 МБ (silent failure). | Ограничьте количество переменных или используйте артефакты для передачи данных. |

## Рекомендации по эксплуатации

1. **Используйте `spec:inputs`** вместо `trigger:variables` для безопасной передачи параметров. Это обеспечивает валидацию типов и защиту от инъекций.
2. **Настройте Inbound Allowlist** для каждого проекта, который использует `CI_JOB_TOKEN` для межпроектных взаимодействий.
3. **Не передавайте секреты через `trigger:variables`**. Используйте OIDC (`id_tokens`) или внешние менеджеры секретов (HashiCorp Vault).
4. **Ограничивайте `forward`** только необходимыми переменными. Отключайте `pipeline_variables: false` для multi-project триггеров.
5. **Используйте уникальные префиксы** для переменных (например, `UPSTREAM_`), чтобы избежать конфликтов имен в дочерних пайплайнах.
6. **Проверяйте Dotenv файлы** на превышение 5 МБ перед коммитом. Используйте сжатие или артефакты для больших данных.
7. **Настройте идентичные правила маскирования** секретов в родительском и дочернем проектах для предотвращения утечек в логах.
8. **Используйте Fine-grained Permissions** для тонкой настройки прав доступа `CI_JOB_TOKEN` (GitLab 18.3+).

## Edge Cases и известные проблемы

- **Потеря masked-статуса при forward в Multi-project** — даже если переменная помечена как Masked в родительском проекте, в дочернем она может быть записана в логи без маскирования. Решение: настройте идентичные правила маскирования в обоих проектах.
- **Dotenv silent failure** — если `.env` превышает 5 МБ, переменные не загружаются, но пайплайн не падает. Решение: проверяйте размер до коммита, используйте `artifacts:expire_in` и сжатие.
- **Protected переменные в non-protected downstream** — при триггере в проект без защищённых веток protected-переменная теряет статус и становится доступной во всех задачах. Решение: используйте отдельные префиксы или изолируйте проекты.
- **Scope переменные в nested triggers** — environment-scoped переменные не пробрасываются автоматически через `inherit: variables: false`. Решение: явно передавайте их через `trigger:variables` или `spec:inputs`.
- **Переопределение `CI_*` переменных** — попытка переопределить предопределённые переменные через `variables` или `trigger:variables` игнорируется без ошибки. Решение: используйте кастомные имена с префиксом.
- **Несовместимые версии GitLab** — `spec:inputs` работает с GitLab 17.0+, а `strategy: mirror` с 18.9+ для агрегации Security Reports. Решение: синхронизируйте версии или используйте минимальный общий набор фич.

### SRE: Инцидент-респонс

При расследовании проблем с наследованием переменных:

1. Получите список переменных downstream-пайплайна через API:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$DOWNSTREAM_ID/pipelines/$PIPELINE_ID/variables" | \
     jq '.[] | {key, value, masked, protected}'
   # → [{"key": "DEPLOY_ENV", "value": "staging", "masked": false, "protected": true}]
   ```

2. Проверьте, какие переменные были переданы через триггер:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PARENT_ID/pipelines/$PARENT_PIPELINE_ID/bridges" | \
     jq '.[] | {name, status, trigger_variables}'
   # → [{"name": "trigger-child", "status": "success", "trigger_variables": {"ENV": "prod"}}]
   ```

3. Для dotenv-артефактов проверьте содержимое:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$JOB_ID/artifacts/build.env"
   # → DYNAMIC_VERSION=1.0.0-abc123
   ```

4. Поиск утечек секретов в логах downstream-пайплайна:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$DOWNSTREAM_ID/jobs?scope=success&per_page=50" | \
     jq '.[] | {id, name, log_path}'
   # → {"id": 456, "name": "deploy", "log_path": "/projects/.../jobs/456/trace"}
   ```

5. При массовом падении downstream-пайплайнов проверьте:
   - Настройки `trigger:forward` в родительских проектах.
   - Статус `CI_JOB_TOKEN` и Fine-grained Permissions (GitLab 18.3+).
   - Версии GitLab в upstream и downstream.

6. Документируйте паттерн инцидента: какой проект-источник, какие переменные передавались, какой дочерний проект получил некорректные значения, время возникновения.

### Compliance и аудит

- **Аудит передачи секретов:** Регулярно проверяйте, что через `trigger:variables` не передаются секреты. Используйте `spec:inputs` только для несекретных типизированных параметров.
- **Аудит Inbound Allowlist:** Все cross-project триггеры должны быть явно разрешены. Регулярно ревьюьте список в `Settings > CI/CD > Token Access` и групповые разрешения.
- **Версионирование конфигураций:** Храните `.gitlab-ci.yml` с переменными в репозитории. Изменения должны проходить code review, так как они влияют на проброс данных между пайплайнами.
- **Сегрегация duties:** Разделите права на изменение переменных и триггеров (DevOps team) и права на запуск пайплайнов (CI/CD). Это предотвращает несанкционированную модификацию контекста.
- **Аудит логов:** Включите аудит доступа к переменным в GitLab (`Settings > CI/CD > Job Token Permissions > Audit log`). Это позволяет отслеживать изменения в Allowlist и передаче переменных.

### Очистка и откат

- **Откат изменений переменных:** Для возврата к предыдущим значениям используйте Git для отката `.gitlab-ci.yml` или перезапустите пайплайн с предыдущим коммитом. Это безопаснее, чем ручное редактирование переменных в UI.
- **Отключение forward на время расследования:** Используйте `forward: { yaml_variables: false, pipeline_variables: false }` для временной изоляции downstream-проекта от родительского контекста.
- **Очистка dotenv-артефактов:** Удалите устаревшие артефакты через интерфейс GitLab или API (`DELETE /projects/:id/jobs/:job_id/artifacts`), чтобы предотвратить использование сломанных переменных.
- **Удаление trigger токенов:** При компрометации перегенерируйте Pipeline Triggers Token в настройках проекта. Старый токен будет отклонён, что предотвратит несанкционированный запуск с поддельными переменными.
- **Валидация после отката:** После отката проверяйте, что downstream-пайплайн запускается с корректными значениями, и что родительский пайплайн не передаёт устаревшие переменные.

### Disaster Recovery

- **Fallback на статические переменные:** При сбое генерации dotenv или API используйте статические значения в `variables` блока. Это позволяет продолжить деплой даже при недоступности сервисов генерации.
- **Резервное копирование `.gitlab-ci.yml`:** Храните конфигурации пайплайнов с переменными в отдельном репозитории или артефакте. Это позволяет быстро восстановить пайплайн при потере ветки.
- **Восстановление CI_JOB_TOKEN доступа:** Если Allowlist сброшен, добавьте проект обратно в `Settings > CI/CD > Token Access` и перезапустите пайплайн. Проверьте, что токен имеет нужные scopes (`read_api`, `read_repository`).
- **Аварийный запуск через API:** Для критичных сервисов подготовьте curl-команду для запуска downstream-пайплайна с явным указанием переменных в обход Bridge Job.
- **Резервное копирование переменных проекта:** Экспортируйте переменные проекта через API перед критичными изменениями. Это позволяет быстро восстановить конфигурацию при ошибке.

### Self-managed инсталляции

- **Резервное копирование базы данных:** Регулярно выполняйте backup PostgreSQL. Переменные проектов и групп хранятся в таблицах `ci_variables` и `ci_group_variables`. При потере базы данные восстанавливаются из резервной копии.
- **Мониторинг Sidekiq:** Мониторьте очередь `create_downstream_pipeline` на задержки. При высокой нагрузке увеличьте количество воркеров Sidekiq, иначе создание downstream-пайплайнов будет тормозить.
- **Резервные Runner'ы:** Для критичных downstream-пайплайнов настройте Runner'ы с высокой доступностью. Недостаток Runner'ов приводит к зависанию Bridge Jobs и блокировке родительского пайплайна.
- **Версионирование GitLab:** Убедитесь, что все проекты в цепочке используют совместимые версии. `spec:inputs` требует GitLab 17.0+, а `strategy: mirror` для Security Reports — 18.9+.
- **Ограничения на размер dotenv:** В self-managed инсталляциях лимит в 5 МБ может быть изменён в конфигурации Rails. Проверьте `gitlab_rails['dotenv_max_size']` в `gitlab.rb`, но увеличение лимита не рекомендуется.

## См. также

- **[Определения Downstream-пайплайнов](./definitions.md)** — архитектура связей.
- **[Лучшие практики](./best_practices.md)** — безопасность и Zero Trust.
- **[Стратегии выполнения](./strategies.md)** — синхронизация жизненного цикла.
- **[Переменные и секреты](../../Concepts/gitlab_ci_variables_secrets.md)** — общий справочник по переменным.
