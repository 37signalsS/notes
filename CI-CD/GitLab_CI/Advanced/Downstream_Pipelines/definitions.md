# Определения Downstream-пайплайнов

**Актуально для:** GitLab 18.6+ / 19.x

## Определения

**Downstream pipeline** — это пайплайн GitLab CI/CD, инициированный другим пайплайном. Он выполняется как независимая сущность со своим собственным графом задач, переменными и окружением, но сохраняет логическую и визуальную связь с вызвавшим его процессом.

**Upstream pipeline** — родительский пайплайн, содержащий задание-триггер, которое инициирует запуск одного или нескольких дочерних процессов.

**Bridge Job (Задание-мост)** — ключевой архитектурный элемент в Upstream-пайплайне. Это специальный тип задачи, который не выполняется на Runner'е напрямую, а служит прокси-объектом в GitLab Rails. Его задача — отправить запрос на создание дочернего пайплайна и (опционально) отслеживать его состояние.

**Техническая реализация Bridge Job:**
- **Роль в архитектуре:** Bridge Job — это объект внутри GitLab Rails (Puma/Sidekiq), а не процесс на Runner'е. Он не потребляет слоты `concurrency` Runner'а для выполнения кода, но **учитывается в лимитах конкурентности** при использовании стратегий `mirror`/`depend` (Bridge Job находится в статусе `running` всё время жизни downstream).
- **Статусы Bridge Job:** `created` → `pending` → `running` (при `mirror`/`depend`) или `success` (при fire-and-forget) → `failed`/`success`/`canceled`.
- **Взаимодействие с шиной событий:** Bridge Job подписывается на события downstream-пайплайна через внутренний API GitLab. При завершении дочернего процесса Rails обновляет статус Bridge Job на основании выбранной стратегии (`mirror`, `depend` или без стратегии).

## Основные концепции

### Жизненный цикл Downstream-пайплайна

1.  **Триггер:** Upstream-пайплайн достигает стадии, содержащей Bridge Job с директивой `trigger`.
2.  **Валидация:** GitLab проверяет:
    - **Права доступа:** Используется `CI_JOB_TOKEN` (по умолчанию) или права запустившего пайплайн пользователя. Для межпроектных триггеров обязательна настройка **Inbound Allowlist** в целевом проекте (17.0+).
    - **Лимиты вложенности:** Не более **2 уровней** через `trigger` (Parent → Child → Grandchild).
    - **Корректность параметров:** Если используются `spec:inputs` — проверка типов и обязательных полей до создания пайплайна. Если `trigger:variables` — только наличие значений.
    - **Синтаксис YAML:** Парсинг дочернего файла (локального, из артефакта или проекта).
3.  **Создание:** Если валидация пройдена, создается новый объект пайплайна. Поведение Bridge Job зависит от стратегии:
    - **Без стратегии (fire-and-forget):** Bridge Job немедленно получает статус `success`.
    - **`strategy: mirror`:** Bridge Job переходит в `running` и ждет завершения downstream (GitLab 18.6+).
    - **`strategy: depend`:** Аналогично `mirror`, но с аппроксимацией статусов (legacy).
4.  **Выполнение:** Дочерний пайплайн проходит стандартные стадии сборки и тестирования на Runner'ах.
5.  **Синхронизация:** При завершении дочернего процесса статус передается обратно в Bridge Job:
    - `mirror` — полная трансляция (включая `manual`, `skipped`, `canceled`).
    - `depend` — упрощенная аппроксимация (`skipped` → `success`, `canceled` → `failed`).
    - Без стратегии — downstream независим, Bridge Job уже завершен.

### Классификация связей

| Тип пайплайна | Контекст выполнения | Основная цель |
| :--- | :--- | :--- |
| **[Parent-child pipeline](./parent_child_pipelines.md)** | Тот же проект, тот же `ref`. | Декомпозиция больших файлов, оптимизация монорепозиториев. |
| **[Multi-project pipeline](./multi_project_pipelines.md)** | Другой проект/репозиторий. | Связывание микросервисов, разделение прав доступа (Compliance). |

### Механизмы передачи данных (Modern vs Legacy)

В современных версиях GitLab (17.0+ GA) рекомендуется использовать типизированные входы.

1.  **Pipeline Inputs (`spec:inputs`):**
    - **Типизация:** Поддержка `string`, `number`, `boolean`, `array`.
    - **Валидация:** Данные проверяются *до* создания пайплайна. Ошибка в типах приведет к немедленному падению Bridge Job с понятным описанием.
    - **Безопасность:** Предотвращение YAML-инъекций.
    - **Синтаксис в дочернем пайплайне:**
      ```yaml
      spec:
        inputs:
          environment:
            type: string
            options: [staging, production]
            default: staging
          replicas:
            type: number
            default: 2
          enable_monitoring:
            type: boolean
            default: true
      ---
      deploy-job:
        script:
          - echo "Deploy to $[[ inputs.environment ]], replicas=$[[ inputs.replicas ]]"
      ```
    - **Вызов из родителя:**
      ```yaml
      trigger-child:
        trigger:
          include:
            - local: 'ci/deploy.yml'
              inputs:
                environment: production
                replicas: 5
                enable_monitoring: false
      ```

2.  **CI/CD Variables (`trigger:variables`):**
    - **Гибкость:** Позволяет передавать любые строковые значения.
    - **Недостаток:** Отсутствие валидации типов и риск переопределения важных системных переменных.
    - **Пример:**
      ```yaml
      trigger-deploy:
        trigger:
          project: 'ops/deploy-repo'
          variables:
            APP_VERSION: $CI_COMMIT_TAG
            DEPLOY_ENV: production
      ```

3.  **Управление наследованием (`trigger:forward`):**
    Директива позволяет точно определить, какие контекстные данные пробрасывать вниз по иерархии:
    - `yaml_variables`: Переменные, определенные в файле `.gitlab-ci.yml`.
    - `pipeline_variables`: Переменные, переданные при запуске через API или интерфейс.

    **Значения по умолчанию:**
    - **Parent-Child:** `yaml_variables: true`, `pipeline_variables: true` (полная прозрачность).
    - **Multi-Project:** `yaml_variables: false`, `pipeline_variables: false` (изоляция по умолчанию).

### Альтернативы trigger: `needs:project` и Pipeline Subscriptions

1.  **`needs:project`** — скачивание артефактов из другого проекта **без запуска** downstream-пайплайна:
    ```yaml
    test-with-artifacts:
      stage: test
      needs:
        - project: 'group/build-project'
          job: 'build-binary'
          ref: main
          artifacts: true
      script:
        - ./bin/app --test
    ```
    - **Отличие от `trigger`:** Не создает новый пайплайн, не выполняет задачи в downstream, не занимает слоты Runner'а на время ожидания.
    - **Применение:** Когда нужен только артефакт (бинарник, документация), а не полный цикл CI.

2.  **Pipeline Subscriptions** — инвертированный триггер, downstream запускается автоматически при обновлении upstream:
    - **Настройка:** `Settings > CI/CD > Pipeline subscriptions` в downstream-проекте.
    - **Ограничение:** Работает только для **веток по умолчанию** (default branches).
    - **Применение:** Автоматическая пересборка Docker-образа при обновлении базового образа в другом репозитории.

## Практические сценарии

### Сценарий 1: Монорепозиторий с Parent-Child пайплайнами

Разделение логики сборки фронтенда и бэкенда для ускорения CI и упрощения поддержки.

```yaml
# Корневой .gitlab-ci.yml
trigger-backend:
  stage: test
  trigger:
    include: backend/.gitlab-ci.yml
  rules:
    - changes:
        - backend/**/*

trigger-frontend:
  stage: test
  trigger:
    include: frontend/.gitlab-ci.yml
  rules:
    - changes:
        - frontend/**/*
```

### Сценарий 2: Compliance-деплой в защищенный проект

Использование мультипроектного пайплайна для выполнения деплоя в проект, к которому у разработчиков основного репозитория нет прямого доступа.

```yaml
# Основной проект (app-repo)
deploy-to-prod:
  stage: deploy
  trigger:
    project: 'ops/infrastructure-deploy'
    branch: main
    strategy: mirror
  variables:
    APP_VERSION: $CI_COMMIT_TAG
```

### Сценарий 3: Типизированный триггер с `spec:inputs`

Безопасная передача параметров с валидацией типов в дочернем пайплайне.

```yaml
# Дочерний проект (ops/deploy-repo)
# Файл: .gitlab-ci.yml
spec:
  inputs:
    environment:
      type: string
      options: [staging, production]
    replicas:
      type: number
      default: 2
    enable_audit_log:
      type: boolean
      default: true
---
deploy:
  script:
    - echo "Deploy to $[[ inputs.environment ]]"
    - ./deploy.sh --replicas=$[[ inputs.replicas ]]
    - if $[[ inputs.enable_audit_log ]]; then enable-audit; fi
```

```yaml
# Родительский проект (app-repo)
trigger-deploy:
  stage: deploy
  trigger:
    project: 'ops/deploy-repo'
    inputs:
      environment: production
      replicas: 5
      enable_audit_log: true
    strategy: mirror
```

### Сценарий 4: Кросс-проектные артефакты через `needs:project`

Получение бинарника из другого проекта без запуска downstream-пайплайна.

```yaml
# Проект: performance-tests
load-testing:
  stage: test
  needs:
    - project: 'apps/main-api'
      job: 'build-binary'
      ref: main
      artifacts: true
  script:
    - ./bin/app --benchmark
```

### Сценарий 5: Pipeline Subscriptions для базовых образов

Автоматическая пересборка приложения при обновлении базового Docker-образа.

```yaml
# Проект: base-images (upstream) — при пуше в main пересобирает образ
# Проект: my-app (downstream) — подписан на base-images
# Настройка: Settings > CI/CD > Pipeline subscriptions > base-images

# В my-app .gitlab-ci.yml:
rebuild-app:
  stage: build
  script:
    - docker build -t my-app:$CI_COMMIT_SHA .
  rules:
    - if: $CI_PIPELINE_SOURCE == "pipeline"
```

## Технические лимиты и ограничения

- **Глубина вложенности:** Лимит составляет **2 уровня** (Parent → Child → Grandchild) при использовании `trigger`. Для более глубоких иерархий необходимо использовать API-вызовы.
- **Размер дерева:** Вся иерархия связанных триггерами пайплайнов не может превышать **1000** объектов.
- **Циклические зависимости:** GitLab блокирует попытки триггера проекта самим собой в рамках одной цепочки для предотвращения бесконечных циклов.
- **CI_JOB_TOKEN:** В версиях 17.0+ требуется обязательная настройка **Inbound Allowlist** в целевом проекте для авторизации входящих триггеров. С 18.3+ доступны **Fine-grained Permissions** для тонкой настройки областей доступа токена.
- **Размер конфигурации:** Максимальный размер дочернего YAML-файла (включая все вложенные `include`) составляет **5 МБ**.
- **Timeout Bridge Job:** По умолчанию Bridge Job имеет таймаут **1 час**. Для downstream с `manual` действиями или длительными задачами необходимо явно увеличивать `timeout`.
- **`needs` + `trigger`:** Задача с `trigger` не может иметь `needs` — это ограничение GitLab (Bridge Job не может быть зависимостью для других задач).
- **Pipeline Subscriptions:** Работают только для **веток по умолчанию** (main/master). Триггер на произвольную ветку через подписки невозможен.

## Edge Cases и известные проблемы

- **Bridge Job завис в `pending`/`running` без downstream (GitLab 18.x):** На самоуправляемых инсталляциях GitLab 18.10+ возможен интермитентный баг, при котором Bridge Job остается в состоянии `pending` или `running`, а `downstream_pipeline` через API равен `null`. Родительский пайплайн не прогрессирует. Причина — сбой в контроллере `Ci::CreateDownstreamPipelineWorker`. Рабоaround: ручная постановка `Ci::CreateDownstreamPipelineWorker.perform_async(<bridge_id>)` через Rails console. Мониторьте паттерн `downstream_pipeline: null` через API `/bridges`.
- **`downstream pipeline can not be created, the resulting pipeline would have been empty`:** Дочерний пайплайн не создал ни одной задачи из-за неверной конфигурации `rules` в дочернем файле. Для merge request пайплайнов дочерний файл должен иметь `workflow:rules` или `rules` для запуска задач.
- **`Ref is ambiguous`:** Нельзя запустить multi-project пайплайн по тегу, если существует ветка с тем же именем. Используйте полный ref (например, `refs/tags/v1.0.0`) или переименуйте ветку.
- **Переменная с `$` не интерпретируется:** При передаче переменной через `trigger:variables` символ `$` не экранируется через `$$` в downstream. Downstream продолжает воспринимать `$` как начало ссылки на переменную. Используйте заранее подготовленные значения без `$` или передавайте через `spec:inputs`.
- **`needs:pipeline` требует строковый pipeline ID:** При использовании динамических дочерних пайплайнов ID пайплайна может парситься как integer. Ошибка: `needs:need pipeline should be a string`. Решение: заключите ID в кавычки: `pipeline: "$UPSTREAM_PIPELINE_ID"`.
- **JWT-формат `CI_JOB_TOKEN` (GitLab 19.0+):** Начиная с GitLab 19.0, `CI_JOB_TOKEN` использует JWT по умолчанию. Legacy-формат можно включить только до релиза 20.0 через настройку группы. Убедитесь, что downstream-проекты и внешние сервисы (Vault, реестры) поддерживают JWT-валидацию.

## Диагностика и устранение неполадок

| Ошибка | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Downstream pipeline could not be created` | Ошибка синтаксиса в дочернем YAML или неверные права доступа. | Проверьте Pipeline Lint для дочернего файла и настройки `CI_JOB_TOKEN`. |
| `Downstream pipeline tree is too large` | Превышен лимит в 1000 пайплайнов в иерархии. | Пересмотрите архитектуру, используйте асинхронные API-вызовы. |
| `Spec must be a valid json schema` | Ошибка в блоке `spec:inputs` дочернего пайплайна. | Убедитесь в корректности типов и обязательных полей в `inputs`. |
| `Job failed (system failure)` | Проблемы на стороне внутренней шины событий GitLab. | Перезапустите пайплайн, проверьте статус GitLab (Status Page). |
| `403 Forbidden` при межпроектном триггере | Целевой проект не добавлен в Inbound Allowlist. | Добавьте проект-источник в `Settings > CI/CD > Token Access`. |
| Bridge Job `success` при падении downstream | Не указана стратегия (`mirror`/`depend`). | Добавьте `strategy: mirror` для синхронизации статусов. |
| `Variables not passed` в downstream | Неверная настройка `trigger:forward` или изоляция multi-project. | Проверьте `forward: yaml_variables: true` и `pipeline_variables: true`. |
| `Artifact not found` при `needs:project` | Артефакт не создан или проект не в Inbound Allowlist. | Проверьте статус задачи генерации и настройки Token Access. |
| `inputs` ошибка при запуске | Несоответствие типов (строка вместо числа). | Проверьте `spec:inputs` дочернего пайплайна через Pipeline Lint. |
| `circular reference detected` | Кольцевая зависимость триггеров (A → B → A). | Разорвите цикл, используйте DAG с `needs` вместо вложенных триггеров. |
| Bridge Job завис в `pending`/`running`, `downstream_pipeline: null` | Баг GitLab 18.10+ (intermittent). `CreateDownstreamPipelineWorker` не выполнился. | Перезапустите пайплайн. Если повторяется — выполните в Rails console: `Ci::CreateDownstreamPipelineWorker.perform_async(<bridge_id>)`. Откройте issue в self-managed инсталляции. |
| `Ref is ambiguous` при триггере по тегу | Ветка с тем же именем, что и тег. | Используйте полный ref `refs/tags/v1.0.0` или переименуйте ветку. |
| `needs:need pipeline should be a string` | Pipeline ID в `needs:pipeline` парсится как integer. | Заключите ID в кавычки: `pipeline: "$UPSTREAM_PIPELINE_ID"`. |
| `downstream pipeline can not be created, the resulting pipeline would have been empty` | Дочерний пайплайн не имеет запускаемых задач из-за `rules`. | Добавьте `workflow:rules` или `rules` в дочерний файл. Для MR-пайплайнов убедитесь, что дочерние задачи имеют условия запуска. |

## Best Practices

### Согласованность терминологии

Для исключения неоднозначности в runbooks, архитектурных диаграммах и коммуникации команды используйте единые обозначения:

- **Upstream / Downstream** — в операционном контексте (инциденты, мониторинг, запуски).
- **Родительский / Дочерний** — в контексте кода и конфигурации `.gitlab-ci.yml`.
- **Bridge Job** — полная форма; сокращение допустимо только во внутренних заметках, но не в официальной документации.
- **Trigger Job** — задание-инициатор; используйте префикс `trigger-` в именах для фильтрации в интерфейсе GitLab.

### Документирование топологии пайплайнов

Включите в системную документацию и runbooks SRE-команды:

- Граф зависимостей downstream-пайплайнов (кто кого триггерит, стратегии, критические пути).
- Карта `CI_JOB_TOKEN` разрешений (какие проекты имеют доступ к каким через Inbound Allowlist).
- Реестр стратегий: для каждого критичного триггера указано, используется ли `mirror`, `depend` или fire-and-forget, и почему.

### Именование заданий-мостов

При именовании Bridge Jobs следуйте паттерну `trigger-<target>-<action>`, например:

```yaml
trigger-auth-deploy:
  trigger:
    project: 'ops/deploy'
    strategy: mirror
```

Это упрощает:
- Фильтрацию в интерфейсе Pipelines и Jobs.
- Поиск через API.
- Аудит конфигурации при ревью MR.

### SRE: Мониторинг и алертинг

Включите в observability stack:

- **Метрика:** Количество активных Bridge Jobs в статусе `running` (через API `/bridges`).
- **Алерт:** Если `running` Bridge Jobs > 50% от `concurrency` Runner'а — потенциальный deadlock.
- **Алерт:** Bridge Job завершился `failed` без явной ошибки в downstream — проверьте Inbound Allowlist и `CI_JOB_TOKEN`.
- **Метрика:** Доля Bridge Jobs, упавших по таймауту. Целевое значение: < 5%.
- **Алерт:** `downstream_pipeline: null` для Bridge Job в статусе `running` дольше 5 минут — возможный баг контроллера (см. Edge Cases).

### SRE: Инцидент-респонс

При расследовании инцидента, связанного с CI/CD:

1. Определите, является ли проблема в upstream или downstream пайплайне, через `GET /projects/:id/pipelines/:pipeline_id/bridges`.
   ```bash
   # Ожидаемый вывод: список Bridge Jobs с полями id, name, status, downstream_pipeline
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges" | \
     jq '.[] | {id, name, status, downstream_pipeline}'
   # → {"id": 123, "name": "trigger-auth-deploy", "status": "running", "downstream_pipeline": 456}
   # → {"id": 124, "name": "trigger-api-test", "status": "pending", "downstream_pipeline": null}
   ```
2. При необходимости перезапустите downstream-пайплайн через API, не трогая upstream-конфигурацию:
   ```bash
   curl --request POST \
     --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/play"
   # → 201 Created, {"id": 789, "status": "pending", ...}
   ```
3. При массовом падении Bridge Jobs проверьте:
   - Состояние Inbound Allowlist в downstream-проектах.
   - Доступность Runner'ов downstream (возможно, проблема не в триггере, а в инфраструктуре дочернего проекта).
   - Лимиты API GitLab (rate limiting при массовых триггерах).
4. Если Bridge Job завис в `pending`/`running` с `downstream_pipeline: null` на GitLab 18.10+:
   - Проверьте наличие бага в self-managed инсталляции.
   - В Rails console выполните: `Ci::CreateDownstreamPipelineWorker.perform_async(<bridge_id>)`
   - Откройте issue с указанием версии GitLab и шагов воспроизведения.
5. Документируйте паттерн инцидента в runbook: какой проект, какая стратегия, какой был триггер, время жизни Bridge Job, диагностические команды.

### Чеклист ревью конфигурации

При ревью MR, затрагивающего `.gitlab-ci.yml` с downstream-триггерами, проверьте:

- [ ] Указана ли стратегия (`mirror` для критичных процессов, `depend` только с обоснованием).
- [ ] Настроен ли `timeout` для Bridge Job с запасом 20–30%.
- [ ] Используются ли `spec:inputs` вместо `trigger:variables` для передачи параметров.
- [ ] Добавлен ли downstream-проект в Inbound Allowlist (для multi-project).
- [ ] Указан ли `environment` в Bridge Job для видимости деплоя в MR.

### Валидация конфигурации

Перед коммитом проверяйте downstream-конфигурацию через Pipeline Lint и API:

```bash
# Валидация дочернего YAML через Pipeline Lint (GitLab 18.6+)
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"content": "'"$(cat ci/deploy.yml | sed 's/"/\\"/g')"'"}' \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/ci/lint"
# → {"status": "valid", "errors": [], "warnings": []}

# Проверка Bridge Jobs активного пайплайна
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges" | \
  jq '.[] | select(.status == "running") | {id, name, downstream_pipeline}'
# → {"id": 123, "name": "trigger-auth-deploy", "downstream_pipeline": 456}

# Проверка статуса downstream-пайплайна
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$DOWNSTREAM_ID" | \
  jq '{id, status, ref, finished_at}'
# → {"id": 456, "status": "success", "ref": "main", "finished_at": "2026-09-28T10:00:00Z"}
```

## См. также

- **[Стратегии выполнения](./strategies.md)** — детально о `mirror` и `depend`.
- **[Лучшие практики](./best_practices.md)** — архитектурные паттерны и безопасность.
- **[Наследование переменных](./variable_inheritance.md)** — глубокое погружение в `forward` и область видимости.
- **[Динамическая генерация](./dynamic_generation.md)** — создание пайплайнов «на лету».
