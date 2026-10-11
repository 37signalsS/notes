# Стратегии выполнения downstream-пайплайнов

**Актуально для:** GitLab 18.6+ / 19.x

## Определения

**Downstream-стратегия (Strategy)** — высокоуровневый параметр в ключевом слове `trigger`, определяющий модель взаимодействия и синхронизации жизненных циклов родительского (upstream) и дочернего (downstream) пайплайнов.

**Fire and Forget** — режим асинхронного запуска downstream-пайплайна без ожидания его завершения. Bridge Job сразу переходит в `success` после постановки downstream в очередь.

Базовые термины (Bridge Job, upstream/downstream pipeline, multi-project pipeline) определены в [Определения Downstream-пайплайнов](./definitions.md).

## Архитектура и механизм синхронизации

Синхронизация через `trigger` работает на уровне состояний конечного автомата (State Machine) пайплайна:

1.  **Регистрация события:** При достижении стадии с `trigger`, GitLab создает Bridge Job и инициирует создание downstream-пайплайна.
2.  **Ожидание (Polling/Hooks):** Если указана стратегия (`mirror` или `depend`), Bridge Job переходит в статус `running` и подписывается на обновления статуса дочернего пайплайна.
3.  **Трансляция статуса:** При переходе дочернего пайплайна в финальное состояние, шина событий отправляет уведомление Bridge Job, которое завершается с соответствующим кодом.
4.  **Агрегация метаданных:** В стратегиях `mirror` и `depend` (при наличии разрешений `CI_JOB_TOKEN`) происходит автоматический сбор ссылок на артефакты и отчеты для отображения в интерфейсе родительского Merge Request.

## Основные стратегии

### Стратегия mirror (Рекомендуемая)

**Назначение:** Полное зеркалирование (High Fidelity) состояния дочернего процесса. Введена в **GitLab 18.6** как стандарт для Enterprise-инсталляций и сложных рабочих процессов.

**Технические нюансы:**
- **Точность статусов:** Bridge Job в точности повторяет финальное состояние дочернего пайплайна. Если downstream пропущен (`skipped`) или ожидает ручного подтверждения (`manual`), родительское задание примет ровно этот же статус. Это критично для корректной работы `rules:if` в последующих стадиях родителя.
- **Двусторонняя отмена (Auto-cancel):** Поддерживает распространение сигнала отмены. При отмене родительского пайплайна GitLab автоматически останавливает все downstream-процессы, запущенные через `mirror`, и наоборот.
- **Агрегация Security Reports (GitLab 18.9+):** Это единственная стратегия, гарантирующая корректное отображение результатов SAST, DAST, Dependency Scanning и SBOM из дочерних проектов непосредственно в виджете Merge Request родительского проекта.
- **Матричные Downstream:** Если используется `parallel:matrix`, Bridge Job с `mirror` будет ждать завершения **всех** инстансов матрицы. Общий статус будет `failed`, если хотя бы один инстанс упал.

```yaml
# Пример High Fidelity Mirroring
trigger_security_scan:
  stage: test
  trigger:
    include: 
      - project: 'security/templates'
        file: 'sast-scanner.yml'
    strategy: mirror
```

### Стратегия depend (Legacy)

**Назначение:** Упрощенное ожидание завершения. Считается устаревшей для новых проектов. Рекомендуется мигрировать на `mirror`.

**Технические особенности:**
- **Аппроксимация статусов:** Преобразует сложные состояния (`manual`, `skipped`, `canceled`) в упрощенные. Конкретное поведение зависит от версии GitLab:
  - `skipped` дочернего пайплайна → `success` на родителе (ложноположительный результат)
  - `manual` дочернего → `blocked` или `success` (зависит от конфигурации)
  - `canceled` дочернего → `failed` на родителе (невозможно отличить от реального падения)
- **Ограниченная отчетность:** Поддерживает агрегацию JUnit тестов, но результаты Security Reports (SAST, DAST, SBOM) не транслируются в Merge Request родителя.
- **Нет двусторонней отмены:** Auto-cancel не распространяется на downstream-процессы. При отмене родительского пайплайна дочерний процесс продолжает выполняться до завершения или таймаута.

**Взаимодействие с `allow_failure`:**
- Если дочерний пайплайн завершился с ошибкой, Bridge Job с `depend` примет статус `failed`.
- При `allow_failure: true` на Bridge Job родительский пайплайн продолжит выполнение, но статус MR будет `warnings`.
- **Важное отличие от `mirror`:** `depend` не различает `failed` и `canceled` — оба приводят к `failed` на родителе.

**Когда использовать (если миграция на `mirror` невозможна):**
- Legacy-проекты на GitLab < 18.6, где `mirror` недоступен.
- Некритичные фоновые задачи, где нетребовательная точность статусов.
- Сценарии, где важна только проверка успешного завершения (без учёта `manual`/`skipped`).

### Fire and Forget (Асинхронный запуск)

Используется по умолчанию, если параметр `strategy` не указан.

**Поведение:**
- Bridge Job переходит в статус `success` немедленно после успешной постановки downstream-пайплайна в очередь (API статус `created` или `pending`).
- **Преимущество:** Мгновенное освобождение лимитов Runner'а в upstream.
- **Недостаток:** Ошибки в downstream никак не влияют на выполнение upstream.

**Ограничения:**
- **Нет агрегации отчетов:** Security Reports и JUnit из дочернего пайплайна не отображаются в MR родителя.
- **Нет auto-cancel:** Отмена родительского пайплайна не останавливает дочерний процесс.
- **Нет видимости статуса:** В интерфейсе GitLab Bridge Job отображается как `passed`, даже если downstream упал.

**Подходит для:**
- Фоновых задач, не критичных для текущего релиза (обновление документации, отправка уведомлений, логирование метрик).
- Запуска инфраструктурных проверок, где результат проверяется отдельно.
- Сценариев, где downstream-проект имеет собственный цикл жизни и не должен блокировать upstream.

## Сравнение характеристик

| Характеристика | Без стратегии | `strategy: depend` | `strategy: mirror` |
| :--- | :---: | :---: | :---: |
| **Ожидание завершения** | Нет | Да | Да |
| **Синхронизация статуса** | Нет | Частично | **Полная** |
| **Агрегация отчётов** | Нет | Да | **Полная (18.9+)** |
| **Auto-cancel** | Нет | Ограниченно | **Да** |
| **Слот Runner'а** | **Освобождается** | Занят | **Занят** |
| **Двусторонняя отмена** | Нет | Нет | **Да** |
| **Обработка `manual`** | Н/Д | Приближённо | **Точно** |
| **Обработка `skipped`** | Н/Д | Как `success` | **Как `skipped`** |
| **Рекомендуемая версия** | Любая | Legacy | **>= 18.6** |
| **Валидация входных данных** | Нет | Нет | Да (через `spec:inputs` или `trigger:inputs`) |

## Выбор стратегии (Decision Tree)

```
Нужно ли дождаться завершения downstream?
├── НЕТ → Fire and Forget (без strategy)
│   └── Используйте для фоновых задач, уведомлений, некритичных проверок
└── ДА → Нужна ли точная трансляция статуса (manual, skipped)?
    ├── НЕТ → strategy: depend
    │   └── Только если достаточно проверить "успех/неуспех"
    └── ДА → strategy: mirror (рекомендуется)
        └── Обязательно для деплоев, security, compliance, MR-интеграций
```

**Альтернатива trigger: `needs:project`**

Для получения артефактов из другого проекта БЕЗ запуска downstream-пайплайна используйте `needs:project`. Это не замена `trigger`, а принципиально иной механизм:

| Критерий | `trigger` + `strategy` | `needs:project` |
| :--- | :--- | :--- |
| **Запуск пайплайна** | Да | Нет (только скачивание) |
| **Выполнение задач** | Да (в downstream) | Нет |
| **Артефакты** | Опосредованно (через downstream) | Прямое скачивание |
| **Зависимость от внешнего проекта** | Полная (жизненный цикл) | Только файлы |
| **Слот Runner'а** | Занят (при `mirror`/`depend`) | **Освобождается** |

```yaml
# Пример: скачивание артефактов без запуска downstream
test-with-build:
  stage: test
  needs:
    - project: 'group/build-project'
      job: 'build-binary'
      ref: main
      artifacts: true
  script:
    - ./bin/app --test
```

## Передача параметров в downstream

Начиная с GitLab 18.0, для передачи данных в дочерний пайплайн рекомендуется использовать **`trigger:inputs`** вместо неструктурированных переменных. Это обеспечивает строгую типизацию и валидацию до запуска downstream.

```yaml
trigger_child:
  stage: deploy
  trigger:
    project: 'group/infra-deploy'
    branch: main
    strategy: mirror
    inputs:
      service:
        type: string
      environment:
        type: string
        options: [staging, production]
      dry_run:
        type: boolean
        default: false
```

**Преимущества `inputs` перед `trigger:variables`:**
- Валидация типов и допустимых значений до создания пайплайна.
- Отсутствие неявной утечки переменных родительского окружения.
- Поддержка `boolean`, `array`, `number` на уровне схемы.

**`trigger:forward`** управляет пробросом контекста:
- `yaml_variables: true` — пробросить переменные, определенные в YAML родителя.
- `pipeline_variables: true` — пробросить переменные окружения CI (например, `CI_COMMIT_SHA`).
- По умолчанию оба параметра отключены для multi-project триггеров.

## Практические сценарии

### Сценарий 1: Агрегация результатов безопасности

Для compliance-проектов, где результаты сканирования в дочернем проекте должны блокировать Merge в основном проекте.

**Настройка:**
1. В дочернем проекте настроены артефакты `reports:sast`.
2. В родительском проекте задание-триггер использует `mirror`.

```yaml
compliance-security-gate:
  stage: test
  trigger:
    project: 'group/security-scanners'
    strategy: mirror
  allow_failure: false # Важно: блокирует upstream при провале сканирования
```

### Сценарий 2: Матричный триггер с агрегацией

Запуск тестов одновременно на разных версиях окружения с ожиданием всех результатов.

```yaml
multi-env-test:
  stage: test
  parallel:
    matrix:
      - ENV: [staging, production, sandbox]
  trigger:
    include: child-pipeline.yml
    strategy: mirror # Ждет все три инстанса
```

### Сценарий 3: Infrastructure-as-Code (Terraform) с approval gate

Деплой инфраструктуры через downstream-пайплайн с обязательным ручным подтверждением. `mirror` гарантирует, что родительский пайплайн не завершится успешно, пока деплой не будет подтвержден.

```yaml
# Родительский проект (app-repo)
trigger-terraform-plan:
  stage: build
  trigger:
    project: 'ops/terraform-modules'
    strategy: mirror
  variables:
    TF_ACTION: "plan"
    SERVICE: "auth-api"

trigger-terraform-apply:
  stage: deploy
  trigger:
    project: 'ops/terraform-modules'
    strategy: mirror
  variables:
    TF_ACTION: "apply"
    SERVICE: "auth-api"
  when: manual
  allow_failure: false
```

```yaml
# Дочерний проект (ops/terraform-modules)
spec:
  inputs:
    TF_ACTION:
      options: [plan, apply]
    SERVICE:
      type: string
---
terraform:
  stage: deploy
  script:
    - cd services/$[[ inputs.SERVICE ]]
    - terraform $[[ inputs.TF_ACTION ]] -auto-approve
```

**Почему `mirror`:** Если Terraform упадёт, родительский пайплайн тоже упадёт. Если `apply` требует `manual` подтверждения, родительский Bridge Job будет ждать в `running`.

### Сценарий 4: Multi-service цепочка зависимостей

Запуск тестов нескольких микросервисов параллельно с агрегацией результатов в родительском пайплайне.

```yaml
.test-service:
  stage: test
  trigger:
    strategy: mirror
  allow_failure: false

test-auth:
  extends: .test-service
  trigger:
    include: services/auth/ci.yml

test-payment:
  extends: .test-service
  trigger:
    include: services/payment/ci.yml

test-notification:
  extends: .test-service
  trigger:
    include: services/notification/ci.yml

# Все три запускаются параллельно, родитель ждет каждого
integration-test:
  stage: integration
  script:
    - ./run-integration-tests.sh
  needs: [test-auth, test-payment, test-notification]
```

**Важно:** Если хотя бы один сервис упадёт, `allow_failure: false` заблокирует `integration-test`.

### Сценарий 5: Деплой с approval gate и fallback-сценарием

Деплой в production через downstream-пайплайн с обязательным ручным подтверждением. `mirror` гарантирует, что родительский пайплайн не завершится успешно, пока деплой не будет подтвержден или не случится откат.

```yaml
# Родительский проект (app-repo)
trigger-deploy-plan:
  stage: build
  trigger:
    project: 'ops/deploy-templates'
    strategy: mirror
  variables:
    DEPLOY_TARGET: "auth-api"
    ENVIRONMENT: "production"

trigger-deploy-apply:
  stage: deploy
  trigger:
    project: 'ops/deploy-templates'
    strategy: mirror
  variables:
    DEPLOY_TARGET: "auth-api"
    ENVIRONMENT: "production"
    ACTION: "apply"
  when: manual
  allow_failure: false

trigger-deploy-rollback:
  stage: deploy
  trigger:
    project: 'ops/deploy-templates'
    strategy: mirror
  variables:
    DEPLOY_TARGET: "auth-api"
    ENVIRONMENT: "production"
    ACTION: "rollback"
  when: manual
  allow_failure: false
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

```yaml
# Дочерний проект (ops/deploy-templates)
spec:
  inputs:
    DEPLOY_TARGET:
      type: string
    ENVIRONMENT:
      type: string
      options: [staging, production]
    ACTION:
      type: string
      options: [plan, apply, rollback]
---
deploy:
  stage: deploy
  script:
    - ./scripts/${ACTION}.sh $[[ inputs.DEPLOY_TARGET ]] $[[ inputs.ENVIRONMENT ]]
```

**Почему `mirror`:** Если деплой упадет, родительский пайплайн тоже упадет. Если `apply` требует `manual` подтверждения, родительский Bridge Job будет ждать в `running`. При отмене родителя деплой в downstream также останавливается.

### Сценарий 6: CI для shared library с кросс-проектным тестированием

Автоматическая проверка совместимости общей библиотеки со всеми проектами-потребителями.

```yaml
# Проект: shared-lib (библиотека)
.test-consumer:
  stage: test
  trigger:
    strategy: mirror
  allow_failure: false

test-consumer-webapp:
  extends: .test-consumer
  trigger:
    project: 'apps/webapp'
    forward:
      yaml_variables: true
  variables:
    LIB_VERSION: $CI_COMMIT_SHA

test-consumer-api:
  extends: .test-consumer
  trigger:
    project: 'apps/api-service'
    forward:
      yaml_variables: true
  variables:
    LIB_VERSION: $CI_COMMIT_SHA

test-consumer-mobile:
  extends: .test-consumer
  trigger:
    project: 'mobile/ios-app'
    forward:
      yaml_variables: true
  variables:
    LIB_VERSION: $CI_COMMIT_SHA
```

**Паттерн:** Если хотя бы один потребитель сломался — merge request библиотеки не будет замержён.

## Технические ограничения и риски

### Проблема "Runner Deadlock"

При использовании `mirror` или `depend` Bridge Job находится в статусе `running` весь цикл жизни дочернего пайплайна. Хотя само задание не выполняет код, оно **учитывается в лимитах конкурентности (concurrency)** Runner'а.

*   **Риск:** Если `concurrency` вашего Runner'а равно 10, и вы запустили 10 upstream-заданий с `mirror`, все слоты будут заняты ожиданием. Дочерние задания не смогут запуститься, так как нет свободных слотов. Возникает бесконечное ожидание (Deadlock).
*   **Решение:** 
    1. Увеличьте `concurrency` в `config.toml` Runner'а.
    2. Используйте разные теги (`tags`) для upstream и downstream заданий.
    3. Используйте асинхронный запуск для некритичных задач.
    4. Мониторьте количество активных Bridge Jobs через API: `GET /api/v4/projects/:id/pipelines/:pipeline_id/bridges`.

### Лимиты вложенности

GitLab ограничивает глубину цепочки downstream-пайплайнов **2 уровнями** (Parent -> Child -> Grandchild). При попытке запустить 3-й уровень через `trigger` возникнет ошибка валидации.

**Обходные пути:**
- Используйте Pipeline Triggers API для программного запуска глубоких цепочек.
- Проектируйте плоскую архитектуру: один родитель → несколько детей (без вложенности детей друг в друга).

### `needs` + `trigger` конфликт

Задача с `trigger` не может одновременно иметь `needs`. Это ограничение GitLab: Bridge Job не может быть зависимостью для других задач.

**Решение:** Используйте `strategy: depend` или `mirror` для связи через статус, а `needs` — только для артефактов из других задач.

```yaml
# НЕПРАВИЛЬНО — вызовет ошибку валидации
deploy:
  needs: [build]
  trigger:
    project: 'ops/deploy'
    strategy: mirror

# ПРАВИЛЬНО — используйте stages для порядка
build:
  stage: build
  script: make build

deploy:
  stage: deploy
  trigger:
    project: 'ops/deploy'
    strategy: mirror
  needs: []  # Или без needs вовсе
```

### `parallel:matrix` + `mirror`

При использовании `parallel:matrix` совместно с `strategy: mirror` Bridge Job ждёт завершения **всех** инстансов матрицы. Общий статус будет `failed`, если хотя бы один инстанс упал.

**Рекомендации для больших матриц:**
- Матрица из 10+ элементов может заблокировать Bridge Job на продолжительное время.
- Используйте `rules` для динамического формирования матрицы на основе изменений.
- При > 5 инстансах рассмотрите разбиение на отдельные триггеры с `fire and forget`.

### `timeout` для Bridge Job и downstream

Таймаут должен покрывать:
1. Время выполнения всех стадий downstream-пайплайна.
2. Время ожидания в очереди Runner'а downstream.
3. Время ожидания `manual` действий (если используется `mirror`).

**Рекомендация:** Установите `timeout` Bridge Job на 20–30% больше суммарного времени downstream. Для сценариев с `manual` действиями используйте `timeout: 7 days` или больше.

Параллельно настраивайте `timeout` на уровне downstream-пайплайна и его задач, чтобы защититься от зависаний на стороне дочернего проекта.

### `interruptible` и auto-cancel

- **`mirror` + `interruptible: true`:** При отмене родительского пайплайна сигнал отмены передаётся в downstream, и дочерний процесс корректно останавливается.
- **`depend` + `interruptible: true`:** Родительский Bridge Job отменяется, но downstream **продолжает выполняться** (нет двусторонней отмены).
- **Fire and Forget:** Auto-cancel не работает — downstream полностью независим.
- **Явное исключение:** Если downstream-задача помечена `interruptible: false`, она не будет отменена даже при использовании `mirror`. Используйте это только для критичных операций, которые опаснее отмены, чем дублирования.

### Очереди и `resource_group`

При массовом запуске downstream-пайплайнов используйте `resource_group` в дочернем проекте, чтобы сериализовать доступ к ограниченным ресурсам (например, shared environment или базе данных для миграций). Это не влияет на Bridge Job напрямую, но предотвращает перегрузку downstream Runner'ов.

### Fan-out и Fan-in

- **Fan-out:** Один родительский пайплайн запускает несколько downstream-пайплайнов параллельно через несколько Bridge Jobs. При `strategy: mirror` родитель ждет завершения всех.
- **Fan-in:** Несколько upstream-пайплайнов триггерят один downstream-пайплайн. GitLab поддерживает это через Pipeline Subscriptions или API-триггеры, но не на уровне native `trigger` в одном YAML.

## Диагностика и устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Bridge Job "завис" в Running | Downstream ждет `manual` действия при `mirror`. | Нажмите кнопку в дочернем пайплайне или уберите `strategy: mirror`. |
| Bridge Job "завис" в Running | Downstream выполняется дольше `timeout` Bridge Job. | Увеличьте `timeout` Bridge Job (см. раздел "timeout для Bridge Job и downstream"). |
| Статус Always Success | Не добавлен `strategy: mirror` или `depend`. | Без стратегии Bridge Job всегда завершается `success` после запуска. |
| Отчеты не отображаются в MR | Не настроен Inbound Allowlist или версия < 18.9. | Добавьте проект в `Settings > CI/CD > Token Access` и обновите GitLab. |
| Runner Deadlock | Все слоты `concurrency` заняты Bridge Jobs. | Увеличьте `concurrency` или используйте `fire and forget` для некритичных задач. |
| `failed` вместо `canceled` при `depend` | `depend` не различает `failed` и `canceled`. | Мигрируйте на `mirror` для корректной трансляции статусов. |
| Downstream не отменяется при отмене родителя | `depend` не поддерживает двустороннюю отмену или downstream помечен `interruptible: false`. | Мигрируйте на `mirror` или уберите `interruptible: false`. |
| Статус `skipped` отображается как `success` | Используется `depend` вместо `mirror`. | `depend` аппроксимирует `skipped` → `success`. Используйте `mirror`. |
| Ошибка `trigger` + `needs` | Bridge Job не может иметь `needs`. | Уберите `needs` из задачи с `trigger` или перенесите зависимость на уровень stages. |
| Матрица из 10+ инстансов блокирует пайплайн | `mirror` ждет ВСЕ инстансы матрицы. | Разбейте матрицу на отдельные триггеры или используйте `fire and forget`. |
| `403 Forbidden` при триггере | Целевой проект не добавлен в Inbound Allowlist или `CI_JOB_TOKEN` не имеет прав. | Настройте `Settings > CI/CD > Token Access` и Fine-grained Permissions (18.3+). |
| `Downstream pipeline could not be created` | Ошибка синтаксиса в дочернем YAML, неверные права или путь к проекту. | Проверьте Pipeline Lint для дочернего файла и настройки Token Access. |
| `Downstream pipeline tree is too large` | Превышен лимит в 1000 пайплайнов в иерархии или 2 уровня вложенности. | Пересмотрите архитектуру, используйте API-вызовы или плоскую структуру. |
| Переменная пуста в downstream | Неверная настройка `trigger:forward` или изоляция multi-project. | Проверьте `forward: yaml_variables: true` и `pipeline_variables: true` или используйте `spec:inputs`. |
| Ошибка валидации `inputs` | Несоответствие типов данных (например, строка вместо числа). | Проверьте `spec:inputs` дочернего пайплайна через Pipeline Lint. |

## Мониторинг эффективности downstream-стратегий

### Ключевые метрики

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Bridge Job duration** | Время от запуска Bridge Job до получения финального статуса downstream. | Не критично (зависит от downstream) |
| **Runner slot utilization** | Доля слотов Runner'а, занятых Bridge Jobs. | < 30% |
| **Deadlock incidents** | Количество ситуаций, когда все слоты заняты Bridge Jobs. | 0 |
| **Strategy distribution** | Соотношение `mirror`/`depend`/fire-and-forget. | `mirror` > 60% для критичных задач |
| **Manual approval wait time** | Среднее время ожидания ручного подтверждения. | Мониторьте для SLA |

### Команды для диагностики

```bash
# Просмотр Bridge Jobs в пайплайне
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges" | \
  jq '.[] | {id, name, status, stage, downstream.pipeline_ref}'

# Подсчет активных Bridge Jobs (поиск потенциального deadlock)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges" | \
  jq '[.[] | select(.status == "running")] | length'

# Проверка статуса downstream-пайплайна
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$DOWNSTREAM_ID" | \
  jq '{id, status, finished_at}'
```

## Best Practices

1. **Стандартизируйте `mirror`** для всех критичных процессов (деплой, security, compliance). `depend` допустима только для legacy-проектов на GitLab < 18.6.
2. **Мониторьте concurrency** — настройте алерт при достижении > 80% использования слотов Runner'а. Детали — в [Лучшие практики](./best_practices.md).
3. **Используйте разные теги** для Bridge Jobs и рабочих задач для предотвращения deadlock.
4. **Устанавливайте `timeout`** явно для Bridge Job и downstream-задач — не полагайтесь на значение по умолчанию (1 час).
5. **Документируйте стратегии** — ведите реестр, какие проекты используют какую стратегию и почему.
6. **Тестируйте auto-cancel** — убедитесь, что `interruptible` настроен корректно для downstream-задач.
7. **Ревизия `depend`** — при наличии GitLab 18.6+ планируйте миграцию на `mirror`.
8. **Настройте `allow_failure`** явно — по умолчанию Bridge Job с `mirror` наследует `allow_failure: false` от родителя.
9. **Предпочитайте `trigger:inputs`** переменным для передачи параметров — это снижает риск инъекций и утечек контекста.
10. **Ограничивайте глубину цепочки** — проектируйте плоскую архитектуру (не более 2 уровней вложенности).

## Edge Cases и ограничения

- **Глубина триггеров:** Максимальная вложенность — **2 уровня** (Parent -> Child -> Grandchild). Третий уровень через `trigger` невозможен. Для глубоких иерархий используйте Pipeline Triggers API или перепроектируйте архитектуру.
- **Размер дерева:** Вся иерархия связанных триггерами пайплайнов не может превышать **1000** объектов. Превышение вызывает ошибку `Downstream pipeline tree is too large`.
- **Защита от циклов:** GitLab анализирует цепочку триггеров. Если обнаружена попытка запустить тот же проект с тем же `commit SHA`, триггер будет заблокирован для предотвращения рекурсивного DDoS инфраструктуры.
- **`needs` + `trigger` конфликт:** Задача с `trigger` не может одновременно иметь `needs`. Bridge Job не может быть зависимостью для других задач. Используйте `stages` для порядка или `strategy: depend`/`mirror` для связи через статус.
- **Прямой API-вызов:** Если нужна глубокая вложенность или асинхронный fan-out, используйте Pipeline Triggers API (`POST /projects/:id/trigger/pipeline`). Это обходит лимит в 2 уровня, но требует явной обработки аутентификации и Allowlist.

## См. также

- **[Определения Downstream-пайплайнов](./definitions.md)** — терминология и типы связей.
- **[Лучшие практики](./best_practices.md)** — архитектурные паттерны и безопасность.
- **[Межпроектные пайплайны](./multi_project_pipelines.md)** — особенности работы между разными репозиториями.
- **[Родительско-дочерние пайплайны](./parent_child_pipelines.md)** — декомпозиция внутри одного проекта.

## Миграция стратегий и конфигураций

### Миграция с `strategy: depend` на `strategy: mirror`

`depend` считается устаревшей стратегией. Миграция на `mirror` требует проверки совместимости downstream-пайплайнов.

**Пошаговая инструкция:**

1.  **Аудит:** Найдите все Bridge Jobs с `strategy: depend`:
    ```bash
    curl --header "PRIVATE-TOKEN: $TOKEN" \
      "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges" | \
      jq '.[] | select(.strategy == "depend") | {id, name, project}'
    ```

2.  **Canary-миграция:** Для каждого Bridge Job:
    - Создайте MR с изменением `depend` → `mirror`.
    - Запустите тестовый пайплайн на feature-ветке.
    - Проверьте, что downstream-пайплайн завершается корректно и статус транслируется в родителя.
    - Проверьте отображение Security Reports (SAST, DAST) в MR.

3.  **Валидация:** После мержа monitored downstream-пайплайн в production-среде в течение 1-2 недель.

4.  **Rollback:** Если `mirror` вызывает проблемы (например, downstream ждет `manual` действие), верните `depend` через emergency MR.

**Особенности миграции:**
- `mirror` требует GitLab 18.6+. Убедитесь, что все проекты в цепочке используют совместимую версию.
- `mirror` транслирует статус `skipped` как `skipped`, а `depend` — как `success`. Проверьте `allow_failure` на Bridge Job.
- `mirror` поддерживает двустороннюю отмену (auto-cancel). Проверьте, что downstream-задачи помечены `interruptible: true` если это безопасно.

### Миграция с `trigger:variables` на `spec:inputs`

Переход от неструктурированных переменных к типизированным входам повышает безопасность и предотвращает инъекции.

**Пошаговая инструкция:**

1.  **Добавьте `spec:inputs` в дочерний пайплайн:**
    ```yaml
    # Дочерний пайплайн (ops/deploy-repo)
    spec:
      inputs:
        environment:
          type: string
          options: [staging, production]
          default: staging
        replicas:
          type: number
          default: 2
    ---
    deploy:
      script:
        - echo "Deploy to $[[ inputs.environment ]] with $[[ inputs.replicas ]] replicas"
    ```

2.  **Обновите родительский пайплайн:**
    ```yaml
    # Родительский пайплайн (app-repo)
    trigger-deploy:
      stage: deploy
      trigger:
        project: 'ops/deploy-repo'
        inputs:
          environment: production
          replicas: 5
        strategy: mirror
    ```

3.  **Валидация:** Запустите `glab ci lint --dry-run` для проверки типов и обязательных полей.

4.  **Удалите `trigger:variables`:** После успешного тестирования удалите старые переменные из родительского пайплайна.

**Особенности миграции:**
- `spec:inputs` работает с GitLab 17.0+. Для старых версий используйте `variables` с `options`.
- `inputs` поддерживает типы `string`, `number`, `boolean`, `array`. Убедитесь, что типы совпадают с ожиданиями дочернего пайплайна.
- Обязательные параметры без `default` приведут к падению Bridge Job при отсутствии значения. Добавьте `default` или передавайте все обязательные `inputs`.

### Миграция с монолитного `.gitlab-ci.yml` на Parent-Child

Декомпозиция большого файла на родительский + дочерние пайплайны улучшает поддерживаемость и selective CI.

**Пошаговая инструкция:**

1.  **Инвентаризация:** Определите логические группы задач в монолитном файле (build, test, deploy для разных сервисов).

2.  **Создание дочерних файлов:**
    ```bash
    # Структура репозитория
    .gitlab-ci.yml              # Родительский (оркестратор)
    ci/
    ├── build.yml               # Дочерний: сборка
    ├── test.yml                # Дочерний: тесты
    └── deploy.yml              # Дочерний: деплой
    ```

3.  **Миграция с canary-подходом:**
    - Создайте дочерний файл для одной группы задач (например, `build.yml`).
    - Подключите его через `trigger:include` в родительском файле.
    - Запустите тестовый пайплайн и проверьте, что дочерний пайплайн выполняется корректно.
    - Постепенно перенесите остальные группы задач.

4.  **Валидация:** Проверяйте expanded YAML через `glab ci config compile` для гарантии, что все `include` и `extends` работают.

**Особенности миграции:**
- Дочерний пайплайн наследует тот же `ref` и `commit SHA`, что и родитель. Невозможно запустить child на другой ветке через `trigger:include`.
- Parent-child пайплайны ограничены 2 уровнями вложенности. Для глубоких иерархий используйте multi-project триггеры или API.
- Bridge Job не может иметь `needs`. Используйте `stages` для порядка выполнения.
