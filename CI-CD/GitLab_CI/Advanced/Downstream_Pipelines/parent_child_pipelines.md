# Родительско-дочерние пайплайны (Parent-Child Pipelines)

**Актуально для:** GitLab 18.6+ / 19.x

## Определения

**Родительско-дочерний пайплайн (Parent-Child Pipeline)** — это тип downstream-пайплайна, который запускается в рамках того же проекта и репозитория, что и основной (родительский) процесс. 

Технической основой реализации является **Bridge Job** (задание-мост) — специальный объект в GitLab Rails, который не потребляет ресурсы Runner'а напрямую для выполнения кода, а служит прокси-уровнем для управления жизненным циклом дочернего пайплайна через внутреннюю шину событий GitLab.

## Основные концепции

### Архитектура и жизненный цикл

1.  **Триггер (Trigger):** Родительское задание достигает стадии с директивой `trigger`. GitLab Rails создает Bridge Job.
2.  **Валидация:** GitLab парсит дочерний YAML (локальный файл или артефакт). Если в файле есть синтаксические ошибки или нарушены лимиты, Bridge Job падает.
3.  **Изоляция графа:** Дочерний пайплайн получает собственный граф задач и стадий. Это позволяет использовать одинаковые имена стадий (например, `test`) в родителе и ребенке без конфликтов.
4.  **Синхронизация (High Fidelity):** При использовании `strategy: mirror` (GitLab 18.6+) Bridge Job остается в статусе `running` до полного завершения дочернего процесса, в точности транслируя его финальный статус (включая `skipped` или `manual`).

### Технические характеристики и лимиты

-   **Контекст:** Дочерний пайплайн всегда использует тот же `ref` (ветку/тег) и `commit SHA`, что и родитель.
-   **Глубина вложенности:** Ограничена **2 уровнями** (Родитель -> Ребенок -> Внук). Попытка запустить 3-й уровень приведет к ошибке валидации.
-   **Лимит иерархии:** Одна цепочка может содержать до **1000** downstream-пайплайнов суммарно (критично для больших матричных триггеров).
-   **Переменные:** По умолчанию наследуются все `yaml_variables` и `pipeline_variables` родителя (настраивается через `trigger:forward`).

### Современная параметризация (trigger:inputs)

С версии GitLab 18.9+ рекомендуется использовать директиву **`trigger:inputs`** вместо переменных.
-   **Валидация типов:** Поддержка `string`, `number`, `boolean`, `array`.
-   **Compile-time check:** Ошибки в параметрах обнаруживаются в момент создания пайплайна, а не во время выполнения скриптов.

### Несовместимость `needs` и `trigger`

Bridge Job не может быть зависимостью для других задач. Если задача использует `trigger`, она **не может** иметь `needs`:
```yaml
# ОШИБКА: такая конфигурация не работает
build-app:
  stage: build
  script: echo "build"
  trigger:
    include: 'ci/build.yml'
  needs:
    - lint  # ОШИБКА: Bridge Jobs не поддерживают needs
```

**Решение:** Используйте `stages` для порядка выполнения или `strategy: depend/mirror` для связи через статус.

### Debug Bridge Jobs через API

Мониторинг состояния Bridge Jobs выполняется через GitLab API:

```bash
# Получить список Bridge Jobs родительского пайплайна
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges" | \
  jq '.[] | {id, name, status, downstream_pipeline: .downstream_pipeline.id}'
```

**Использование в CI/CD для обнаружения deadlock:**
```yaml
check-bridges:
  stage: .post
  script:
    - |
      ACTIVE=$(curl -s --header "PRIVATE-TOKEN: $TOKEN" \
        "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$CI_PIPELINE_ID/bridges" | \
        jq '[.[] | select(.status == "running")] | length')
      echo "Active Bridge Jobs: $ACTIVE"
      if [ "$ACTIVE" -gt 3 ]; then
        echo "WARNING: Potential deadlock risk - too many active bridges"
      fi
  when: always
```

## Практические сценарии

### Сценарий 1: Селективный CI для монорепозитория

Паттерн «Selective CI» позволяет запускать тесты только для измененных модулей, экономя тысячи минут Runner-времени.

```yaml
# .gitlab-ci.yml (Корневой)
auth-service-tests:
  stage: test
  trigger:
    include: services/auth/.gitlab-ci.yml
    strategy: mirror
  rules:
    - changes:
        - services/auth/**/*

billing-service-tests:
  stage: test
  trigger:
    include: services/billing/.gitlab-ci.yml
    strategy: mirror
  rules:
    - changes:
        - services/billing/**/*
```

### Сценарий 2: Типизированный триггер деплоя

Использование `inputs` для безопасной передачи параметров окружения.

**1. Конфигурация дочернего пайплайна (`ci/deploy.yml`):**
```yaml
spec:
  inputs:
    environment:
      options: [staging, production]
    replicas:
      type: number
      default: 2
---
deploy-job:
  script:
    - echo "Deploying to $[[ inputs.environment ]] with $[[ inputs.replicas ]] nodes"
```

**2. Вызов из родительского пайплайна:**
```yaml
deploy-to-prod:
  trigger:
    include: ci/deploy.yml
    inputs:
      environment: production
      replicas: 5
    strategy: mirror
```

### Сценарий 3: Security scan как дочерний пайплайн

Изоляция security-сканирования в отдельном child pipeline для параллельного выполнения и изоляции контекста.

```yaml
# .gitlab-ci.yml (Родитель)
security-sast:
  stage: test
  trigger:
    include: security/sast.yml
    strategy: mirror

security-dast:
  stage: test
  trigger:
    include: security/dast.yml
    strategy: mirror
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

# security/sast.yml (Дочерний)
sast-scan:
  image: security scanners/sast:latest
  script:
    - run-sast-scanner --project $CI_PROJECT_PATH --ref $CI_COMMIT_SHA
  artifacts:
    reports:
      sast: gl-sast-report.json
```

### Сценарий 4: Multi-level override (parent-child-grandchild)

В иерархии из трёх уровней переменные переопределяются на каждом уровне. Дочерний пайплайн наследует все `yaml_variables` родителя, но может переопределить их.

```yaml
# Родитель (grandparent)
variables:
  DEPLOY_ENV: production
  IMAGE_TAG: v1.0

trigger-parent:
  trigger:
    include: parent.yml
    strategy: mirror

# Ребёнок (parent.yml)
variables:
  DEPLOY_ENV: staging  # Переопределяет DEPLOY_ENV

trigger-child:
  trigger:
    include: child.yml
    strategy: mirror

# Внук (child.yml)
script:
  - echo "Deploying to $DEPLOY_ENV" # Выведет: staging
```

### Сценарий 5: Manual approval workflow

Когда в дочернем пайплайне есть задачи `when: manual`, родительское задание будет висеть в статусе `running` (при `mirror`), пока пользователь не нажмет кнопку в дочернем интерфейсе.

```yaml
# Родитель
trigger-production-deploy:
  stage: deploy
  trigger:
    include: ci/deploy.yml
    strategy: mirror

# Дочерний (ci/deploy.yml)
deploy-prod:
  script:
    - ./deploy.sh
  when: manual
  allow_failure: false
```

### Сценарий 6: Matrix parent-child с агрегацией отчетов

Использование `parallel:matrix` совместно с `strategy: mirror` для запуска нескольких инстансов дочернего пайплайна и агрегации результатов.

```yaml
# Родитель
test-matrix:
  stage: test
  trigger:
    include: ci/test.yml
    strategy: mirror
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.9", "3.10", "3.11"]

# Дочерний (ci/test.yml)
test-job:
  image: python:$PYTHON_VERSION
  script:
    - pytest --junitxml=report.xml
  artifacts:
    reports:
      junit: report.xml
```

**Важно:** При использовании `parallel:matrix` совместно с `strategy: mirror` Bridge Job ждет завершения **всех** инстансов матрицы. Общий статус будет `failed`, если хотя бы один инстанс упал.

### Сценарий 7: Rules с changes + trigger

Паттерн для запуска дочернего пайплайна только при изменении определенных файлов, с динамическим выбором конфигурации.

```yaml
# .gitlab-ci.yml
test-backend:
  stage: test
  trigger:
    include: backend/.gitlab-ci.yml
    strategy: mirror
  rules:
    - changes:
        - backend/**/*
        - shared/**/*

test-frontend:
  stage: test
  trigger:
    include: frontend/.gitlab-ci.yml
    strategy: mirror
  rules:
    - changes:
        - frontend/**/*
```

## Управление ресурсами и риски

### Проблема Deadlock (Взаимная блокировка)

При использовании синхронных стратегий (`mirror`, `depend`) Bridge Job занимает слот конкурентности (concurrency) вашего Runner'а всё время ожидания.

*   **Риск:** Если лимит Runner'а равен 5, и вы запустили 5 родительских заданий с `mirror`, дочерние задания не смогут запуститься из-за нехватки слотов. Возникает бесконечное ожидание.
*   **Решение:** Увеличьте `concurrency` в `config.toml` Runner'а или используйте разные теги (`tags`) для Bridge Jobs и рабочих задач.

### Ресурсная изоляция Bridge Jobs

Для предотвращения deadlock рекомендуется выделять отдельные Runner'ы (или теги) для Bridge Jobs и рабочих задач:

```yaml
# В config.toml Runner'а, выделенного для Bridge Jobs
concurrent = 10
[[runners]]
  name = "Bridge Runner"
  tags = ["bridge", "parent-child"]
  # Не требует Docker/Kubernetes executor - Bridge Jobs не выполняют код
```

```yaml
# В .gitlab-ci.yml
trigger-child:
  trigger:
    include: 'ci/child.yml'
    strategy: mirror
  tags:
    - bridge  # Использует Bridge Runner
```

### Отмена и прерывание

-   **Auto-cancel:** При отмене родительского пайплайна GitLab автоматически останавливает дочерние процессы (если они не помечены как `interruptible: false`).
-   **Manual Bridge:** Если в дочернем пайплайне есть задачи `when: manual`, родительское задание будет висеть в статусе `running` (при `mirror`), пока пользователь не нажмет кнопку в дочернем интерфейсе.

### Валидация конфигурации перед коммитом

Используйте `glab ci lint` для проверки синтаксиса и валидации конфигурации parent-child пайплайнов:

```bash
# Быстрая проверка синтаксиса
glab ci lint

# Раскрытый YAML (со всеми include/extends/inputs)
glab ci lint --show-expanded

# Dry run - глубокая валидация (GitLab 16.11+)
glab ci lint --dry-run --variable CI_PIPELINE_SOURCE=merge_request_event
```

**Рекомендация:** Запускайте `glab ci lint --show-expanded` перед каждым коммитом в CI/CD конфигурацию, особенно при изменении `trigger:include`.

## Диагностика и устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Downstream pipeline could not be created` | Ошибка синтаксиса в дочернем YAML-файле. | Проверьте дочерний файл через CI Lint (Web UI или `glab`). |
| `Status stuck in Running` | Дочерний пайплайн ждет Runner или ручное действие. | Проверьте состояние дочернего пайплайна в Pipeline Graph. |
| `Recursion limit exceeded` | Попытка запустить 3-й уровень вложенности. | Используйте Pipeline Triggers API для глубоких иерархий. |
| `Variables not passed` | Неверная настройка `trigger:forward`. | Убедитесь, что `yaml_variables` установлены в `true`. |
| Bridge Job "завис" в Running | Downstream ждет `manual` действия при `mirror`. | Нажмите кнопку в дочернем пайплайне или уберите `strategy: mirror`. |
| Статус Always Success | Не добавлен `strategy: mirror` или `depend`. | Без стратегии Bridge Job всегда завершается `success` после запуска. |
| `needs` + `trigger` конфликт | Bridge Job не может быть зависимостью. | Используйте `stages` для порядка или `strategy: depend` для связи через статус. |
| Deadlock при большом количестве триггеров | Все слоты Runner'а заняты Bridge Jobs. | Увеличьте `concurrency` или выделите отдельные Runner'ы для Bridge Jobs. |

## Рекомендации по эксплуатации

1. **Используйте `strategy: mirror`** для критических процессов (деплой, security-сканирование) — это гарантирует, что статус родителя отражает результат дочернего пайплайна.
2. **Не используйте `needs` с `trigger`** — Bridge Jobs не поддерживают зависимостей. Используйте `stages` или `strategy: depend/mirror`.
3. **Выделяйте отдельные Runner'ы** для Bridge Jobs для предотвращения deadlock.
4. **Валидируйте конфигурацию** через `glab ci lint --show-expanded` перед каждым коммитом.
5. **Настройте `interruptible: false`** для критических дочерних пайплайнов, чтобы предотвратить их отмену при auto-cancel родителя.
6. **Мониторьте Bridge Jobs** через API (`GET /api/v4/projects/:id/pipelines/:pipeline_id/bridges`) для раннего обнаружения deadlock.
7. **Используйте `rules:changes`** для selective CI — запускайте дочерние пайплайны только при изменении соответствующих файлов.
8. **Ограничивайте глубину** до 2 уровней — для более сложных иерархий используйте Pipeline Triggers API.

## Edge Cases и известные проблемы

- **Циклический include:** Если дочерний YAML включает родительский файл (или файл, который включает родителя), GitLab обнаруживает рекурсию только на этапе компиляции и падает с ошибкой `Recursion limit exceeded`. Решение: используйте плоские структуры или явно разделяйте конфигурации.
- **Лимит глубины 2 уровня:** Попытка запустить внука (child → grandchild) через `trigger` внутри дочернего пайплайна завершается ошибкой валидации. Для глубоких иерархий используйте Pipeline Triggers API или разделите на независимые цепочки.
- **Одинаковый `ref`:** Дочерний пайплайн всегда использует тот же `ref` (ветка/тег), что и родитель. Невозможно запустить child на другой ветке через `trigger:include`. Решение: используйте multi-project триггеры или динамическую генерацию для изменения `ref`.
- **Artifact include vs локальный файл:** При `include: artifact` дочерний пайплайн зависит от успешного завершения задачи-генератора. Если артефакт отсутствует или поврежден, Bridge Job падает с `Artifact not found`. Решение: проверяйте `artifacts:paths` в задаче-генераторе и добавляйте валидацию.
- **`parallel:matrix` + `mirror` deadlock:** При большом количестве инстансов матрицы Bridge Job занимает слоты `concurrency` Runner'а на время ожидания всех инстансов. При `concurrency < matrix_size` возникает deadlock. Решение: увеличивайте `concurrency` или разбивайте матрицу на несколько триггеров.
- **`manual` задачи в child при `mirror`:** Если дочерний пайплайн содержит `when: manual`, родительский Bridge Job зависает в `running` до ручного подтверждения. Это может привести к зависанию родительского пайплайна. Решение: используйте `strategy: depend` для асинхронного режима или настройте `interruptible: false`.

### SRE: Инцидент-респонс

При расследовании проблем с parent-child пайплайнами в рамках одного проекта:

1. Получите список Bridge Jobs родительского пайплайна:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges" | \
     jq '.[] | {id, name, status, downstream_pipeline: .downstream_pipeline.id, duration}'
   # → [{"id": 101, "name": "trigger-child", "status": "failed", "downstream_pipeline": {"id": 456}, "duration": 12.5}]
   ```

2. Проверьте состояние дочернего пайплайна:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$DOWNSTREAM_PIPELINE_ID" | \
     jq '{id, status, duration, web_url}'
   # → {"id": 456, "status": "failed", "duration": 8.2, "web_url": "https://gitlab.example.com/.../pipelines/456"}
   ```

3. Для artifact-based include проверьте наличие артефакта:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$GENERATOR_JOB_ID/artifacts/child.yml"
   # → содержимое сгенерированного YAML или ошибка 404
   ```

4. Поиск зависших Bridge Jobs:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges" | \
     jq '[.[] | select(.status == "running" and (.downstream_pipeline.status == "manual" or .downstream_pipeline.status == "pending"))] | length'
   # → 2 (количество зависших Bridge Jobs)
   ```

5. Проверка рекурсии include: если пайплайн падает с `Recursion limit exceeded`, проверьте все `include:` в дочерних YAML-файлах на циклические ссылки.

6. Документируйте паттерн инцидента: какой родительский пайплайн, какие дочерние файлы подключались, какой Bridge Job завис, время возникновения.

### Compliance и аудит

- **Аудит триггеров в рамках проекта:** Регулярно проверяйте все задания с директивой `trigger` в `.gitlab-ci.yml`. Изменения в конфигурации триггеров должны проходить code review, так как они влияют на запуск дочерних пайплайнов.
- **Защита артефактов:** Если дочерний YAML генерируется как артефакт, используйте `artifacts:protected: true` для предотвращения доступа к конфигурации из неподтвержденных веток.
- **Сегрегация duties:** Разделите права на изменение конфигурации parent-child пайплайнов (DevOps team) и права на запуск пайплайнов (CI/CD). Это предотвращает несанкционированную модификацию структуры пайплайнов.
- **Аудит Bridge Jobs:** Включите аудит создания downstream-пайплайнов в GitLab (`Settings > CI/CD > Pipeline triggers > Audit log`). Это позволяет отслеживать, кто и когда запускал дочерние процессы.
- **Версионирование конфигураций:** Храните все дочерние YAML-файлы в репозитории. Изменения должны проходить code review, особенно для критичных деплоев.

### Очистка и откат

- **Отмена родительского пайплайна:** При отмене родительского пайплайна GitLab автоматически останавливает все дочерние процессы, если они не помечены как `interruptible: false`. Для принудительной остановки используйте API:
  ```bash
  curl --request POST --header "PRIVATE-TOKEN: $TOKEN" \
    "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/cancel"
  ```
- **Очистка зависших Bridge Jobs:** Если Bridge Job завис в `running` из-за `manual` задачи в child, отмените дочерний пайплайн через API или завершите `manual` задачу. После этого Bridge Job перейдет в финальный статус.
- **Откат конфигурации:** Для возврата к предыдущей конфигурации дочернего пайплайна используйте Git для отката изменений в YAML-файле. Это безопаснее, чем ручное редактирование.
- **Удаление trigger конфигурации:** Для временного отключения дочернего пайплайна используйте комментарий или `rules: []` в задании-триггере. Это сохраняет историю изменений.
- **Очистка артефактов:** Удалите устаревшие артефакты с сгенерированными YAML-файлами через интерфейс GitLab или API, чтобы предотвратить использование сломанных конфигураций.

### Disaster Recovery

- **Fallback на локальный YAML:** При сбое artifact-based include используйте локальный файл в репозитории как резервный. Это позволяет продолжить выполнение даже при проблемах с генерацией артефактов.
- **Резервное копирование конфигураций:** Храните все дочерние YAML-файлы в отдельном репозитории или используйте Git tags для быстрого восстановления предыдущих версий.
- **Аварийный запуск child pipeline:** Для критичных сервисов подготовьте curl-команду для запуска дочернего пайплайна через API в обход Bridge Job:
  ```bash
  curl --request POST --header "PRIVATE-TOKEN: $TOKEN" \
    --form "ref=main" \
    "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline"
  ```
- **Восстановление после сбоя Runner'а:** Если Bridge Job завис из-за недоступности Runner'а, перезапустите дочерний пайплайн вручную через Web UI или API.
- **Резервное копирование переменных:** Экспортируйте переменные проекта через API перед критичными изменениями конфигурации.

### Self-managed инсталляции

- **Резервное копирование базы данных:** Регулярно выполняйте backup PostgreSQL. Состояние Bridge Jobs и downstream-пайплайнов хранится в таблицах `ci_builds` (тип `bridge`) и `ci_pipelines`. При потере базы данные восстанавливаются из резервной копии.
- **Мониторинг Sidekiq:** Мониторьте очередь `create_downstream_pipeline` на задержки. При высокой нагрузке увеличьте количество воркеров Sidekiq, иначе создание downstream-пайплайнов будет тормозить.
- **Настройка `concurrency` в `config.toml`:** Для предотвращения deadlock увеличьте `concurrent` в конфигурации Runner'а. Для Bridge Jobs рекомендуется выделять отдельные Runner'ы с повышенным `concurrency`:
  ```toml
  concurrent = 20
  [[runners]]
    name = "Bridge Runner"
    tags = ["bridge", "parent-child"]
    limit = 10
  ```
- **Резервные Runner'ы:** Настройте Runner'ы с высокой доступностью для Bridge Jobs. Недостаток Runner'ов приводит к зависанию Bridge Jobs и блокировке родительского пайплайна.
- **Версионирование GitLab:** Убедитесь, что используете GitLab 18.6+ для `strategy: mirror` и 18.9+ для `trigger:inputs` с валидацией типов. Self-managed инсталляции требуют планового обновления для поддержки новых фич.

## См. также

- **[Определения Downstream-пайплайнов](./definitions.md)** — архитектурная база.
- **[Лучшие практики](./best_practices.md)** — безопасность и оптимизация.
- **[Динамическая генерация](./dynamic_generation.md)** — создание пайплайнов на основе артефактов.
- **[Межпроектные пайплайны](./multi_project_pipelines.md)** — взаимодействие между разными репозиториями.
