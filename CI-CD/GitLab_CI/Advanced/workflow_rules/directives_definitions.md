# Справочник директив GitLab CI/CD

**Актуально для:** GitLab CI/CD 17.x–19.x

## Определения

**Справочник директив** — это центральный технический документ (SSoT), описывающий синтаксис, назначение и архитектурные нюансы ключевых слов в конфигурации `.gitlab-ci.yml`. В отличие от вводных материалов, данный справочник ориентирован на глубокую техническую детализацию реализации и возможности версий GitLab 17.x–19.x (актуально на 2026 год).

## Предварительные требования

### Версия GitLab и поддержка директив

| Директива / Возможность | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `default` (блок) | 17.0+ | Рекомендуется вместо глобальных ключей |
| `workflow:name` | 15.8+ | Имя пайплайна в UI |
| `workflow:auto_cancel:on_job_failure` | 13.12+ | Fail-Fast отмена пайплайнов |
| `workflow:auto_cancel:on_new_commit` | 16.0+ | Автоматическая отмена при новом пуш |
| `workflow:rules:auto_cancel` | 19.x+ | Условная отмена для protected-веток |
| `include:component` | 15.3+ | CI/CD Catalog компоненты |
| `include:remote:integrity` | 17.9+ | Проверка целостности SHA256 |
| `include:remote:cache` | 18.9+ эксперимент, 19.0 GA | Кэширование удаленных файлов |
| `include:rules` | 17.0+ | Условное подключение файлов |
| `include:inputs` + `spec:inputs` | 16.1+ | Параметризация компонентов |
| `spec:include` | 18.9+ | Повторное использование inputs across configs |
| `spec:inputs:rules` | 18.7+ | Условные options/default для inputs |
| `extends` (базовый) | 11.3+ | Наследование от скрытых заданий |
| `extends` + `inputs` | 16.0+ | Параметризованные шаблоны |
| `!reference` | 13.9+ | Копирование фрагментов YAML |
| `inherit` | 12.9+ | Селективное наследование defaults/variables |
| `needs:project` | 11.8+ | Кросс-проектные зависимости |
| `needs:parallel:matrix` | 16.3+ | Матричная адресация (1:1 связь) |
| `needs:parallel:matrix` с `$[[ matrix.VAR ]]` | 18.6+ | Выражения в матричных зависимостях |
| `rules:needs` | 16.0+ | Динамическое переопределение DAG |
| `id_tokens` (OIDC) | 16.0+ | Генерация JWT-токенов |
| `secrets` (Secrets Manager) | 19.0+ public beta, 19.3+ GA | Динамическое извлечение секретов |
| `parallel:matrix` | 11.5+ | Матричные сборки |
| `resource_group` | 12.9+ | Mutex для задач |
| `resource_group:process_mode` | 14.3+ API, 18.x+ YAML | Приоритезация задач в очереди |
| `manual_confirmation` | 17.5+ | Диалог подтверждения для manual-задач |
| `identity` | 18.0+ | Федерация идентичности (OIDC) |
| `artifacts:reports:cyclonedx` | 12.7+ | SBOM-отчеты |
| `cache:policy` | 11.0+ | pull/push/pull-push политики |
| `run` (Functions) | 19.x эксперимент | Версионируемые функции в OCI |

### Необходимые знания

- Базовый синтаксис YAML и структура `.gitlab-ci.yml`
- Концепции стадий, задач, артефактов и кэша
- Предопределённые переменные GitLab (`CI_*`)
- Основы shell-скриптинга для написания команд
- Работа с Merge Request и ветками в Git

### Инструменты диагностики

- **CI Lint API/UI** — валидация конфигурации до запуска пайплайна
- **Pipeline Editor** — визуальный редактор с предпросмотром графа задач
- **`glab ci lint`** — CLI-утилита для локальной проверки конфигурации
- **CI_DEBUG_TRACE** — включение отладочного вывода для анализа переменных
- **"View merged YAML"** — просмотр итоговой конфигурации после всех merge/include

### Целевая аудитория

Данный справочник предназначен для DevOps-инженеров, SRE и системных администраторов, работающих с on-premise и гибридной инфраструктурой. Примеры ориентированы на Terraform, Ansible, Salt/Puppet, NAPALM/Netmiko и другие инструменты IaC и автоматизации инфраструктуры.

## Глобальные директивы (Global Keywords)

### `default`
Набор общих параметров, которые автоматически наследуются всеми задачами пайплайна, если не переопределены явно.
- **Теория:** Служит для обеспечения единообразия среды выполнения и предотвращения дублирования (DRY). Архитектурно блок `default` компилируется в каждое задание на этапе пре-процессинга YAML.
- **Включает:** `image`, `services`, `before_script`, `after_script`, `tags`, `cache`, `artifacts`, `interruptible`, `retry`, `timeout`, `id_tokens`, `hooks`.
- **Нюанс:** Начиная с версии 19.x, использование этих ключей на верхнем уровне (вне блока `default`) официально признано устаревшим и может вызывать предупреждения линтера.

**Практический пример:**
```yaml
default:
  image: ruby:3.3
  before_script:
    - bundle install
  tags:
    - docker
  retry:
    max: 2
    when: runner_system_failure
```

### `stages`
Определяет логическую последовательность и названия этапов выполнения пайплайна.
- **Поведение:** Задачи внутри одной стадии выполняются параллельно при наличии свободных Runner'ов. Переход к следующей стадии происходит только после успешного завершения всех задач текущей (если не используется DAG через `needs`).
- **Скрытые стадии:** `.pre` (всегда первая) и `.post` (всегда последняя).

### `workflow`
Директива для управления жизненным циклом всего пайплайна на уровне события.
- **`rules`**: Определяет условия создания пайплайна (например, запрет дублирования при Merge Request).
- **`name` (15.8+):** Назначение пользовательского имени пайплайну. Поддерживает строки и переменные (`$CI_COMMIT_BRANCH`). Имя отображается в UI и хранится в `ci_pipeline_metadata`.
- **`auto_cancel` (16.0+):** Оптимизация ресурсов путем отмены устаревших или неактуальных запусков.
  - `on_new_commit`: Автоматически отменяет текущий пайплайн при поступлении нового пуша в ту же ветку (требует `interruptible: true` в задачах). Режимы: `conservative` (по умолчанию), `interruptible`, `none`.
  - `on_job_failure`: `all` позволяет мгновенно остановить весь пайплайн при падении критической задачи, экономя время и квоты. `none` отключает автоматическую отмену.
- **`rules:auto_cancel` (19.x+):** Условная отмена — переопределение глобальных настроек `auto_cancel` для конкретных веток или условий.

### `include`
Механизм композиции пайплайна из внешних модулей и компонентов.
- **Типы:** `local` (в том же репозитории), `project` (из другого проекта), `remote` (по URL), `template` (встроенные шаблоны GitLab), `component` (GitLab CI/CD Catalog).
- **`inputs`:** Параметризация подключаемых файлов через контракт `spec:inputs`. Современный стандарт, заменяющий неявную передачу через глобальные переменные.
- **`rules` (17.0+):** Условное подключение файлов на основе `if`, `changes`, `exists`.
- **`integrity` (17.9+):** Проверка целостности SHA256 для `include:remote`. Пайплайн прерывается, если хеш не совпадает.
- **`cache` (18.9+ эксперимент, 19.0 GA):** Кэширование удаленных файлов для снижения количества HTTP-запросов. Поддерживает TTL (`true` = 1 час по умолчанию, или строковое значение длительности).
- **Порядок обработки:** `include` обрабатывается **первыми**. Затем результат объединяется с основной конфигурацией. При совпадении имен заданий локальная конфигурация всегда имеет приоритет.
- **Лимит вложенности:** Максимум 150 узлов в дереве зависимостей `include` (учитываются все типы).
- **Время разрешения:** Лимит 30 секунд на разрешение всех `include`.
- **Техническая SSoT:** **[include_keyword.md](../../Reusable_Pipelines/include_keyword.md)**.

**Краткая таблица типов:**

| Тип | Описание | Когда использовать |
| :--- | :--- | :--- |
| `local` | Файл в том же репозитории | Разделение конфигурации внутри проекта |
| `project` | Файл из другого проекта | Централизованные шаблоны для организации |
| `remote` | Файл по HTTP/HTTPS URL | Сторонние шаблоны, публичные библиотеки |
| `template` | Встроенные шаблоны GitLab | SAST, DAST, Auto DevOps |
| `component` | CI/CD компонент из каталога | Версионируемые модули с `spec:inputs` |

### `extends`
Наследование конфигурации от одного или нескольких "скрытых" заданий.
- **Скрытое задание:** Имя начинается с точки (`.base_job`). Игнорируется планировщиком и не запускается напрямую.
- **Алгоритм:** Обратное глубокое слияние (Reverse Deep Merge) — дочернее задание имеет приоритет над родительским.
- **Множественное наследование:** `extends: [.parent_a, .parent_b]`. Порядок слияния: справа налево, итог сливается с дочерним заданием.
- **Поведение по типам:** `variables` — глубокое слияние; `script`, `rules`, `tags`, `artifacts`, `cache` — перезапись.
- **Техническая SSoT:** **[extends_keyword.md](../../Reusable_Pipelines/extends_keyword.md)**.

### `spec:include` (18.9+)
Механизм повторного использования определений входных параметров (`spec:inputs`) across multiple pipeline configurations.
- **История:** Эксперимент в 18.6 (FF `ci_file_inputs`), GA в 18.9.
- **Поддерживаемые типы include:** `local`, `remote`, `project`. Не поддерживает `template`, `component`, `artifact`.
- **Порядок разрешения:** Внешние входы сливаются первыми, затем применяются inline-входы. Дублирование имен вызывает ошибку валидации.
- **Ограничение:** Внешний файл может содержать только ключ `inputs`.

### `spec:inputs:rules` (18.7+)
Условные `options` и `default` для входных параметров на основе значений других входов.
- **Синтаксис:** Массив правил с `if` (использует `$[[ inputs.input-id ]]`), `options`, `default`.
- **Поведение:** Правила проверяются последовательно. Первое совпадение определяет допустимые значения. Последнее правило без `if` является fallback.
- **Ограничение:** Нельзя использовать `rules` совместно с верхнеуровневыми `options` или `default` для того же входа.

## Директивы управления выполнением (Execution Control)

### `rules`
Основной инструмент логики включения задач в граф выполнения.
- **Ключи:** `if` (логические выражения), `changes` (мониторинг путей файлов), `exists` (наличие файлов в корне), `when` (статус запуска), `allow_failure` (мягкий отказ), `start_in` (отложенное начало), `variables` (переопределение переменных), `needs` (динамические зависимости, 16.0+).
- **Поведение:** Оцениваются последовательно. **Первое совпадение** определяет, будет ли задание включено в пайплайн и с какими параметрами. Если ни одно правило не совпало — задание пропускается.
- **Замена:** `rules` полностью заменяет устаревшие `only`/`except` (deprecated).
- **Техническая SSoT:** **[job_rules.md](./job_rules.md)**.

### `needs` (DAG)
Директива для создания Направленного Ациклического Графа (Directed Acyclic Graph).
- **Теория:** Позволяет задачам "перепрыгивать" границы стадий, запускаясь сразу по готовности зависимостей. Это радикально ускоряет пайплайны с длинными сборками и короткими тестами.
- **Типы зависимостей:** `job` (другая задача), `pipeline` (дочерний пайплайн), `project` (кросс-проектные артефакты), `optional` (опциональные, 17.4+), `parallel:matrix` (матричная адресация, 16.3+).
- **`artifacts: false`:** Отключение загрузки артефактов при необходимости только статуса зависимости.
- **Матричные выражения (18.6+):** Использование `$[[ matrix.VAR ]]` для связи конкретных инстансов параллельных задач.
- **Техническая SSoT:** **[dag_with_needs.md](./dag_with_needs.md)**.

### `parallel`
Масштабирование одной задачи на несколько параллельных инстансов.
- **`parallel: N`:** Простое дублирование задачи N раз (нумерация от 0 до N-1).
- **`parallel:matrix`:** Позволяет задать массив значений переменных, для каждой комбинации которых будет создана отдельная задача.
- **`exclude`:** Исключение комбинаций из матрицы (17.9+).
- **Лимиты:** Обычно до 200 задач на одну матрицу.
- **Техническая SSoT:** **[matrix_builds_and_serialization.md](./matrix_builds_and_serialization.md)**.

### `trigger`
Создание зависимых (Downstream) пайплайнов.
- **Сценарии:** Parent-Child (внутри одного репозитория для динамической генерации) или Multi-project (для сложных микросервисных архитектур).
- **`strategy: depend`:** Синхронизация статуса: родительская задача не завершится, пока дочерний пайплайн не перейдет в финальное состояние.
- **`include` внутри trigger:** Динамическая генерация YAML-конфигурации для дочернего пайплайна.

### `resource_group`
Механизм взаимного исключения (mutex) для задач.
- **Применение:** Предотвращение одновременного деплоя нескольких пайплайнов на одно и то же физическое окружение (защита от Race Conditions).
- **`process_mode` (14.3+ API, 18.x+ YAML):** Управление очередью задач в группе ресурсов.
  - `unordered` (по умолчанию): Без гарантий порядка.
  - `oldest_first`: Приоритет старых пайплайнов (безопасный деплой).
  - `newest_first`: Приоритет новых пайплайнов (отмена устаревших).
  - `newest_ready_first` (19.x+): Приоритет новых готовых к запуску пайплайнов.
- **Синтаксис YAML:** `resource_group: <name>` или `resource_group: { name: <name>, process_mode: <mode> }`.

### `!reference` (13.9+)
Тег для копирования фрагментов YAML из скрытых заданий или других секций конфигурации.
- **Теория:** Позволяет извлекать отдельные элементы (массивы команд, значения переменных) из шаблонов без полного наследования через `extends`. В отличие от `extends`, `!reference` копирует только указанный блок, а не задание целиком.
- **Синтаксис:** `!reference [.job_name, key.subkey]`
- **Порядок разрешения:** `!reference` разрешается **после** `include`, `inputs`, `variables` и `extends`. Это означает, что ссылка может обращаться к уже обработанным значениям.
- **Взаимодействие с `inputs`:** `!reference` разрешается после `inputs`, поэтому передать `inputs` внутрь `!reference` напрямую невозможно.
- **Техническая SSoT:** **[reference_and_yaml_anchors.md](../../Reusable_Pipelines/reference_and_yaml_anchors.md)**.

**Пример:**
```yaml
.deploy_base:
  script:
    - echo "Base deploy script"
    - ./deploy.sh

.deploy_notifications:
  script:
    - echo "Sending notification"
    - curl -X POST https://hooks.example.com/deploy

deploy:
  stage: deploy
  script: !reference [.deploy_base, script]
  after_script: !reference [.deploy_notifications, script]
```

## Управление данными (Data Management)

### `artifacts`
Передача результатов работы задачи между стадиями и кросс-проектно.
- **`paths`:** Список файлов/директорий для включения в артефакт.
- **`exclude`:** Исключение файлов из артефакта (16.4+).
- **`expire_in`:** Срок хранения артефактов (по умолчанию 30 дней).
- **`when`:** Условия создания — `on_success` (по умолчанию), `on_failure`, `always`, `manual`, `delayed`.
- **`reports`:** Специализированные парсеры для JUnit (тесты), Cobertura (покрытие), Cyclonedx/Sbom (безопасность), SAST/DAST/Secret Detection.
- **`dotenv`:** Экспорт переменных из одной задачи в последующие через файл (`artifacts:reports:dotenv`).
- **`artifacts: false` в `needs`:** Отключение загрузки артефактов при зависимости только по статусу.
- **`dependencies`:** Явное управление загрузкой артефактов (отдельно от `needs`).
- **Техническая SSoT:** **[gitlab_ci_artifacts.md](../gitlab_ci_caching/gitlab_ci_artifacts.md)**.

### `cache`
Временное хранилище для повторного использования между пайплайнами.
- **Политики:** `pull-push` (чтение и обновление), `pull` (только чтение — ускоряет задачи тестирования), `push` (только запись — для задач подготовки зависимостей).
- **`key`:** Идентификатор версии кэша. Поддерживает переменные, хеши файлов и комбинации.
- **`fallback_keys`:** Запасные ключи, если основной не найден (13.12+).
- **`paths`:** Список файлов/директорий для кэширования.
- **`when`:** Условия кэширования — `on_success` (по умолчанию), `on_failure`, `always`.
- **Различие с `artifacts`:** Кэш — для зависимостей (npm, pip); артефакты — для результатов сборки (dist/, binaries).

### `before_script` и `after_script`
Скрипты, выполняемые до и после основного `script`.
- **`before_script`:** Выполняется в том же shell-процессе, что и `script`. Имеет доступ к тем же переменным. Используется для подготовки среды (установка зависимостей, настройка окружения).
- **`after_script`:** Выполняется в **отдельном** shell-процессе. Не может изменять статус задачи (даже при ошибке, задача останется успешной). Не видит изменения переменных окружения, внесенные в `script`. Используется для очистки, отправки уведомлений, архивации логов.
- **Порядок выполнения:** `before_script` → `script` → `after_script` (если `script` завершился успешно или с `allow_failure: true`).

## Дополнительные директивы задач (Job-level Keywords)

### `inherit` (12.9+)
Селективное управление наследованием глобальных `default` и `variables`.
- **`default: false`:** Полный отказ от наследования блоков `default`.
- **`variables: false`:** Полный отказ от наследования глобальных переменных.
- **Массив:** Указание конкретных ключей/переменных для наследования. Всё остальное отбрасывается.
- **Применение:** Изоляция шаблонов (.base) от глобальных defaults в организации с общими пайплайнами.

### `manual_confirmation` (17.5+)
Директива для добавления кастомного диалога подтверждения перед запуском manual-задачи.
- **Назначение:** Предотвращение случайного деплоя или удаления данных в production.
- **Синтаксис:** Строка с текстом подтверждения. Отображается в UI при нажатии на задачу.
- **Ограничение:** Работает только в связке с `when: manual`.

### `identity` (18.0+)
Аутентификация с внешними сервисами через федерацию идентичности (Identity Federation).
- **Назначение:** Беспарольный доступ к SaaS/PaaS сервисам через OIDC-провайдеры.
- **Отличие от `id_tokens`:** `identity` использует внешний OIDC-провайдер; `id_tokens` генерирует JWT внутри GitLab.

### `run` (19.x эксперимент)
Экспериментальная директива для выполнения задач через версированные функции (GitLab Functions / CI/CD Steps).
- **Архитектура:** Вместо `script` задача объявляет `run` — список шагов, вызывающих OCI-функции.
- **Требования:** На Runner'е должен быть установлен `step-runner` бинарник.
- **Ограничения:** Нельзя использовать вместе с `script`, `before_script`, `after_script`. Два синтаксиса выражений: `${{ }}` (evaluation at execution) и `$[[ ]]` (evaluation at pipeline creation).
- **Статус:** Experiment, возможны breaking changes.

### `coverage`
Настройка сбора покрытия кода для задачи.
- **Значения:** Строка с выражением или `override: false` для отключения.
- **Применение:** Интеграция с Codecov, Coveralls или внутренними дашбордами.

### `release`
Генерация объекта Release в GitLab на основе выполнения задачи.
- **Назначение:** Автоматическое создание release notes, связывание артефактов с тегом.
- **Ограничение:** Доступно только для задач на защищенных ветках.

### `pages`
Загрузка артефактов для GitLab Pages.
- **Ограничения:** Только одна задача с `pages` на пайплайн. Требует `artifacts:paths: [public]`.

### `hooks` (в `default`)
Hook-скрипты, доступные в блоке `default` (19.x+).
- **Назначение:** Глобальные точки расширения для pre-job и post-job логики.

### `environment`
Именование окружения для деплоя и интеграция с GitLab Environments.
- **`name`:** Имя окружения (обязательно для deployments). Поддерживает переменные.
- **`url`:** URL развернутого приложения. Отображается в UI.
- **`on_stop`:** Задача для остановки/отката окружения.
- **`auto_stop_in`:** Автоматическое удаление окружения через указанный период (например, `7 days`).
- **`action`:** Действие для deployments — `start`, `stop`, `prepare`, `verify`.
- **Применение:** Канареечные деплои, review apps, автоматическая очистка environments.

### `timeout`
Пользовательский таймаут для задачи.
- **Значение:** Длительность в человекочитаемом формате (`10 minutes`, `1 hour`). Минимум — `1 minute`.
- **Приоритет:** Переопределяет глобальный таймаут проекта.
- **SRE-применение:** Ограничение времени выполнения для предотвращения зависаний на shared runners.

### `interruptible`
Разрешение отмены задачи при поступлении нового пайплайна.
- **`true` (по умолчанию):** Задача может быть отменена через `workflow:auto_cancel:on_new_commit`.
- **`false`:** Задача защищена от отмены. Критические деплои и миграции должны использовать `false`.
- **Взаимодействие с `workflow:auto_cancel`:** Режим `interruptible` отменяет только задачи с `interruptible: true`.

### `retry`
Повторный запуск задачи при ошибке.
- **`max`:** Максимальное количество попыток (обычно 1-2).
- **`when`:** Условия повтора — `always`, `unknown_failure`, `script_failure`, `runner_system_failure`, `stuck_or_timeout_failure`.
- **SRE-применение:** Повтор при сетевых сбоях (`runner_system_failure`), но не при логических ошибках (`script_failure`).

### `dependencies`
Явное управление загрузкой артефактов.
- **`dependencies: []`:** Отключение загрузки артефактов (используйте вместе с `needs`).
- **Список задач:** Загрузка артефактов только от указанных задач.
- **Отличие от `needs`:** `needs` определяет порядок запуска; `dependencies` определяет, какие артефакты скачиваются.

## Безопасность и интеграция (Security)

### `id_tokens` (16.x+)
Генерация JWT-токенов (OIDC) для аутентификации во внешних сервисах.
- **Применение:** Беспарольный доступ к хранилищам секретов, Kubernetes API, менеджерам конфигураций. Токен подписывается GitLab и проверяется внешним сервисом.
- **`aud`:** Audience — целевой сервис (обязательный параметр).
- **`claims`:** Дополнительные поля в JWT (опционально).
- **Рекомендация:** Выносите конфигурацию `id_tokens` в базовые шаблоны (`.auth_base`) для переиспользования через `extends`.
- **Техническая SSoT:** **[gitlab_ci_variables_secrets.md](../../Concepts/gitlab_ci_variables_secrets.md)**.

**Пример для HashiCorp Vault:**
```yaml
deploy:
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
      claims:
        role: ci-deploy
  script:
    - export VAULT_TOKEN=$(vault write -field=token auth/jwt/login role=ci-deploy jwt=$VAULT_ID_TOKEN)
    - vault kv get -mount=secret -field=password db/prod
```

### `secrets` (19.0+ public beta, 19.3+ GA)
Интеграция с **GitLab Secrets Manager**.
- **Теория:** Динамическое извлечение секретов непосредственно в память задачи. Секреты не сохраняются в переменных окружения Runner'а, что минимизирует риск утечки через логи.
- **Типы секретов:** `password`, `key`, `certificate`, `token`, `json_web_token` и др.
- **Версионирование:** Каждое обновление секрета создает новую версию. Пайплайны могут ссылаться на конкретную версию или `latest`.
- **Техническая SSoT:** **[gitlab_ci_variables_secrets.md](../../Concepts/gitlab_ci_variables_secrets.md)**.

**Пример:**
```yaml
deploy:
  secrets:
    DB_PASSWORD:
      vault:
        engine: { name: kv-v2, path: kv }
        path: secret/data/database
        field: password
  script:
    - psql "postgresql://user:$DB_PASSWORD@db.example.com/mydb"
```

### `variables`
Управление переменными окружения на разных уровнях.
- **Типы переменных:** Protected (только защищенные ветки), Masked (скрыты в логах), Hidden (полностью скрыты), File (путь к файлу), Raw (без расширения).
- **`expand` (19.x+):** Управление раскрытием переменных (`true`/`false`). По умолчанию `true` для переменных в YAML.
- **`description`:** Описание для ручного запуска пайплайна (отображается в UI).
- **`value`:** Предfilled значение для manual-запусков (вместе с `description`).
- **Приоритеты:** 14 уровней от Script-level (высший) до Predefined (низший).
- **Техническая SSoT:** **[gitlab_ci_variables_secrets.md](../../Concepts/gitlab_ci_variables_secrets.md)**.

### Иерархия приоритетов переменных (GitLab 19.x)
В случае конфликта имен значение выбирается согласно следующему приоритету (от высшего к низшему):
1. Script-level переменные (внутри `script`)
2. Trigger переменные (через API/Web UI)
3. Manual переменные (введены вручную при запуске)
4. Pipeline execution policy переменные
5. Scheduled переменные
6. Job-level переменные (`job:variables`)
7. Included переменные (из файлов `include`)
8. Global переменные (на верхнем уровне `.gitlab-ci.yml`)
9. Project переменные (Settings > CI/CD > Variables)
10. Group переменные (Settings > CI/CD > Variables)
11. Instance переменные (Admin Area)
12. Dotenv переменные (через `artifacts:reports:dotenv`)
13. Deployment переменные (специфичные для окружения)
14. Predefined переменные (`CI_COMMIT_SHA` и др.)

## DevOps/SRE и on-premise сценарии

### Полный пайплайн развертывания IaC с использованием всех директив

```yaml
# default — единообразная среда для всех задач
default:
  image: hashicorp/terraform:1.9
  before_script:
    - cd $TF_ROOT
    - terraform init -backend-config="backend.hcl"
  cache:
    key: terraform-${CI_COMMIT_REF_SLUG}
    paths:
      - $TF_ROOT/.terraform/

# stages — логическая последовательность
stages:
  - validate
  - plan
  - apply
  - notify

# variables — параметры пайплайна
variables:
  TF_ROOT: "terraform/"
  VAULT_ADDR: "https://vault.example.com"

# workflow — предотвращение дублирования пайплайнов
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Скрытое задание для переиспользования
.validate_base:
  stage: validate
  script:
    - terraform validate
    - terraform fmt -check -recursive
    - tflint --init && tflint
  rules:
    - changes:
        paths: ["terraform/**/*.tf"]
        compare_to: 'main'

.plan_base:
  stage: plan
  script:
    - terraform plan -out=tfplan -var-file="${DEPLOY_ENV}.tfvars"
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 1 day
    when: on_success

# Основные задачи
terraform:validate:
  extends: .validate_base
  needs: []

terraform:plan:staging:
  extends: .plan_base
  needs: ["terraform:validate"]
  variables:
    DEPLOY_ENV: staging

terraform:plan:production:
  extends: .plan_base
  needs: ["terraform:validate"]
  variables:
    DEPLOY_ENV: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

terraform:apply:staging:
  stage: apply
  needs: ["terraform:plan:staging"]
  script:
    - terraform apply -auto-approve tfplan
  environment:
    name: staging
  resource_group: staging_deploy
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"

terraform:apply:production:
  stage: apply
  needs: ["terraform:plan:production"]
  script:
    - terraform apply -auto-approve tfplan
  environment:
    name: production
  resource_group: production_deploy
  interruptible: false
  allow_failure: false
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

# Уведомление через after_script
notify:
  stage: notify
  image: curlimages/curl:latest
  needs: ["terraform:apply:production"]
  script: []
  after_script:
    - curl -X POST "$SLACK_WEBHOOK"
      -H "Content-Type: application/json"
      -d "{\"text\": \"Deploy $CI_COMMIT_SHORT_SHA to production completed\"}"
  rules:
    - when: on_success
```

### Использование `!reference` для модульных пайплайнов

```yaml
# Базовые скрипты
.ansible_lint:
  script:
    - ansible-lint roles/
    - ansible-lint playbooks/

.ansible_test:
  script:
    - ansible-playbook --syntax-check playbooks/deploy.yml
    - molecule test

.ansible_deploy:
  script:
    - ansible-playbook -i inventory/$DEPLOY_ENV playbooks/deploy.yml
      --vault-password-file <(echo $VAULT_PASSWORD)

# Задачи с compose-логикой через !reference
ansible:validate:
  stage: lint
  image: cytopia/ansible-lint
  needs: []
  script: !reference [.ansible_lint, script]

ansible:test:
  stage: test
  image: cytopia/ansible:2.14
  needs: ["ansible:validate"]
  script: !reference [.ansible_test, script]

ansible:deploy:staging:
  stage: deploy
  image: cytopia/ansible:2.14
  needs: ["ansible:test"]
  script: !reference [.ansible_deploy, script]
  variables:
    DEPLOY_ENV: staging
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"
      when: manual
```

### Композиция через `include` и `inputs`

```yaml
# Подключение шаблона с параметрами
include:
  - local: '.gitlab-ci/terraform.yml'
    inputs:
      environment: staging
      var_file: "staging.tfvars"

  - project: 'infra/ci-templates'
    ref: v3.2.0
    file: '/security/secret-scan.yml'

  - template: 'Jobs/Secret-Detection.gitlab-ci.yml'
```

### Мониторинг инфраструктуры с `id_tokens` и `resource_group`

```yaml
stages:
  - check
  - deploy

check:
  stage: check
  image: python:3.12
  needs: []
  script:
    - pip install prometheus-api-client
    - python check_alerts.py
  rules:
    - changes:
        paths: ["monitoring/**/*"]
        compare_to: 'main'

reload:
  stage: deploy
  image: curlimages/curl:latest
  needs: ["check"]
  script:
    - curl -X POST http://prometheus:9090/-/reload
  resource_group: monitoring_config
  id_tokens:
    PROM_ID_TOKEN:
      aud: http://consul:8500
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  allow_failure: false
```

## Валидация и отладка конфигурации

### Методы проверки

**1. CI Lint API:**
```bash
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --data "content=$(cat .gitlab-ci.yml | base64)" \
  "https://gitlab.example.com/api/v4/ci/lint"
# → {"valid": true} или {"valid": false, "errors": [...]}
```

**2. CLI-валидация (glab):**
```bash
glab ci lint
glab ci lint --dry-run --variable CI_COMMIT_BRANCH=main
```

**3. Pipeline Editor:**
Визуальный интерфейс для проверки графа зависимостей, валидации логики и просмотра "View merged YAML".

**4. Проверка всех веток логики:**
```bash
for BRANCH in main develop feature/test; do
  echo "Testing branch: $BRANCH"
  glab ci lint --dry-run --variable CI_COMMIT_BRANCH=$BRANCH
done
```

### Отладка переменных

**Отладочный вывод:**
```yaml
debug_vars:
  stage: .pre
  script:
    - echo "=== GitLab CI Variables ==="
    - env | sort | grep -E "^(CI_|GITLAB_)" | head -50
    - echo "=== Custom Variables ==="
    - echo "TF_ROOT=$TF_ROOT"
    - echo "DEPLOY_ENV=$DEPLOY_ENV"
  needs: []
  rules:
    - when: always
```

**Проверка иерархии приоритетов:**
```bash
# Вывод всех переменных с указанием источника
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/variables" | \
  jq '.[] | {key, value, protected, masked}'
```

### Валидация `include` и `extends`

**Просмотр итоговой конфигурации:**
```bash
# Через API — merged YAML
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/merge_requests/$MR_IID/ci_config"
# → Полный YAML после обработки include, extends, inputs, !reference
```

**Отладка `!reference`:**
```bash
# Если !reference не разрешается — проверьте порядок обработки:
# 1. include → 2. inputs → 3. variables → 4. extends → 5. !reference
# !reference не может обращаться к переменным, определенным в том же блоке
```

## Лучшие практики

### Структура конфигурации

1. **Иерархия шаблонов:** Базовые шаблоны (`.base`) → Специализированные (`.docker_base`, `.k8s_base`) → Реализации (`build`, `test`, `deploy`).
2. **Именование скрытых заданий:** Используйте префиксы для группировки (`.build:*`, `.test:*`, `.deploy:*`).
3. **Группировка по типу:** Директивы безопасности (`id_tokens`, `secrets`) выносите в отдельные файлы и подключайте через `include`.
4. **DRY через `extends`:** Используйте наследование вместо копирования блоков. Для отдельных фрагментов — `!reference`.

### Безопасность

1. **Zero Trust для `CI_JOB_TOKEN`:** Всегда настраивайте Inbound Allowlist (17.0+).
2. **Маскирование секретов:** Используйте `masked: true` и `protected: true` для продакшен-секретов.
3. **`interruptible: false` для критических задач:** Деплой и миграции не должны прерываться `auto_cancel`.
4. **Валидация перед apply:** Всегда используйте `plan`/`validate` перед `apply` в IaC-задачах.
5. **OIDC вместо статических ключей:** Используйте `id_tokens` для аутентификации вместо долгоживущих секретов.

### Производительность

1. **Кэширование зависимостей:** Используйте `cache` с `key` для избежания повторной загрузки.
2. **`cache: policy: pull` для тестов:** Тесты только читают зависимости — не обновляйте кэш.
3. **Минимизация артефактов:** Используйте `exclude` для исключения ненужных файлов.
4. **`expire_in` для всех артефактов:** Не переполняйте хранилище.
5. **Параллелизация:** Независимые задачи выполняются параллельно автоматически.

### Масштабирование

1. **Монорепозитории:** Разделяйте конфигурацию на логические модули через `include:local`.
2. **Микросервисы:** Используйте `include:project` с SemVer-тегами для централизованных шаблонов.
3. **CI/CD Catalog:** Публикуйте переиспользуемые компоненты с `spec:inputs` для типизированных интерфейсов.
4. **Кросс-проектные зависимости:** `needs:project` для связывания пайплайнов разных сервисов.

## Граничные случаи и ограничения

### Технические лимиты

| Параметр | Лимит | Версия |
| :--- | :--- | :--- |
| Узлов в дереве `include` | 150 | Все |
| Глубина наследования `extends` | 11 | Все |
| Максимум `spec:inputs` в компоненте | 50 | 16.10+ |
| Максимум `spec:inputs:options` | 50 | 19.0+ |
| Задач в `parallel:matrix` | 200 | Все |
| Задач в `needs` | 50 | Все |
| Длина имени задачи в `needs` | 128 символов | 18.x+ |
| Длина строки в `$[[ inputs.X ]]` | 1 KB | Все |
| Общий размер интерполяций в `$[[ ]]` | 1 MB | Все |
| Время разрешения `include` | 30 секунд | Все |

### Несовместимость директив

| Конфликт | Описание | Решение |
| :--- | :--- | :--- |
| `needs` + `stage` | `needs` переопределяет порядок стадий | Используйте `needs` для DAG, `stage` — только для визуальной группировки |
| `needs` + `dependencies` | Независимые механизмы | `needs` = порядок запуска; `dependencies` = загрузка артефактов |
| `needs` + `trigger` | Дочерние пайплайны не могут быть зависимостями | Используйте `trigger` с `strategy: depend` и API для связи |
| `extends` + `script` | Массив `script` перезаписывается, не сливается | Используйте `!reference` для конкатенации |
| `include` + переменные | `inputs` обрабатываются до `variables` | Динамические имена переменных через `inputs` невозможны |
| `rules` + `only/except` | Взаимоисключающие директивы | Используйте только `rules` (only/except deprecated) |

### Особые сценарии

**Циклические зависимости (`extends`):**
```yaml
# ОШИБКА: .parentA extends .parentB, .parentB extends .parentA
# GitLab выдаст: "circular dependency detected"
```
Решение: пересмотрите иерархию шаблонов, используйте плоскую структуру.

**`!reference` к несуществующему ключу:**
```yaml
# ОШИБКА: .hidden_job не существует или ключ wrong_key не найден
# GitLab выдаст: "couldn't find the job"
```
Решение: проверьте имя скрытого задания и путь к ключу.

**`include:remote` с невалидным URL:**
```yaml
# ОШИБКА: файл не найден или нет доступа
# GitLab выдаст: "error" на этапе компиляции
```
Решение: проверьте URL, доступность и `integrity` хеш (17.9+).

**`resource_group` с несуществующим проектом:**
```yaml
# ОШИБКА: целевой проект в include:project не существует
# GitLab выдаст ошибку до запуска任何 задач
```

**Пустой `default: before_script`:**
```yaml
# Не ошибка, но пустой массив может вызвать предупреждение
default:
  before_script: []  # Явно указывайте пустой массив
```

**`spec:include` с дублирующимися именами:**
```yaml
# ОШИБКА: внешний файл inputs.yml определяет env, inline тоже определяет env
# GitLab выдаст: "duplicate input definition"
```
Решение: используйте уникальные имена или переименуйте inline-входы.

**`resource_group:process_mode` в YAML (18.x+):**
```yaml
deploy:
  resource_group:
    name: production
    process_mode: oldest_first
```
Примечание: В версиях до 18.x `process_mode` можно было установить только через API.

**`run` без установленного step-runner:**
```yaml
# ОШИБКА: step-runner: not found (exit code 127)
# GitLab Runner не может выполнить функцию без бинарника
```
Решение: добавьте `step-runner` в Docker-образ задачи.

**`workflow:name` с пустой строкой:**
```yaml
# Если name: '' — пайплайн не получит имени в UI
workflow:
  name: ''
```
Примечание: Пустое имя может сломать интеграции, зависящие от названия пайплайна.

### Устранение неисправностей

#### Синтаксические ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Syntax error` | Невалидный YAML | Используйте CI Lint для валидации |
| `Unknown key` | Неизвестная директива или опечатка | Проверьте справочник директив |
| `Invalid input` | Неверный тип в `spec:inputs` | Убедитесь, что типы совпадают (string, number, boolean) |

#### Логические ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Задача не запускается** | `rules` не совпали или `only/except` исключили | Проверьте условия `rules` через Pipeline Editor |
| **Задача запускается не в том порядке** | `needs` переопределяет `stage` | Просмотрите DAG в UI пайплайна |
| **Артефакты не скачиваются** | Задача не в `needs` и не в `dependencies` | Добавьте задачу в `needs` или `dependencies` |
| **Переменные не раскрываются** | Включено `raw: true` или отключено expansion | Проверьте атрибуты переменных |

#### Проблемы с `include` и `extends`

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Too many includes` | Дерево > 150 узлов | Объедините мелкие файлы, используйте `!reference` |
| `Expanded YAML too large` | Итоговый конфиг > 5 МБ | Сократите комментарии, используйте `extends` вместо копирования |
| `Maximum levels of inheritance` | Глубина `extends` > 11 | Упростите иерархию шаблонов |
| `Component not found` | Неверный путь или нет тега | Проверьте `include:component` и версию |
| `Input 'X' must match regex` | Значение нарушает `spec:inputs:regex` | Проверьте регулярное выражение и входное значение |
| `Duplicate input definition` | Два `spec:inputs` с одинаковым именем | Уберите дублирование между `spec:include` и inline |
| `step-runner: not found` | Функция `run` без бинарника | Добавьте `step-runner` в образ задачи |
| `process_mode` игнорируется | Используется API-режим, а не YAML | Проверьте версию GitLab (18.x+ для YAML) |
| `manual_confirmation` не появляется | `when` не установлен в `manual` | Укажите `when: manual` для задачи |

## Смотрите также

- **[Основы GitLab CI/CD](../../Concepts/gitlab_ci_basics.md)** — архитектурные принципы и базовые примеры.
- **[Механизм include](../../Reusable_Pipelines/include_keyword.md)** — синтаксис и типы подключения.
- **[Механизм extends](../../Reusable_Pipelines/extends_keyword.md)** — правила слияния и наследование.
- **[!reference и YAML anchors](../../Reusable_Pipelines/reference_and_yaml_anchors.md)** — детализация ссылок.
- **[Переменные и секреты](../../Concepts/gitlab_ci_variables_secrets.md)** — иерархия переменных и безопасность.
- **[Обзор Runner и Executor](../gitlab_ci_runners_executors.md)** — изоляция, executor types, config.toml.
- **[Окружения и развертывания](../../Concepts/environments_and_deployments.md)** — protected environments и deployment approvals.
- **[Кэширование и артефакты](../gitlab_ci_caching/caching_overview.md)** — стратегии кэширования.
- **[Артефакты в GitLab CI](../gitlab_ci_caching/gitlab_ci_artifacts.md)** — артефакты, reports, retention.
- **[Родительско-дочерние пайплайны](../Downstream_Pipelines/parent_child_pipelines.md)** — trigger и parent-child паттерны.
- **[Compliance и Audit](../compliance_and_audit.md)** — compliance pipelines и политики.
- **[CI/CD Catalog компоненты](../../Reusable_Pipelines/ci_cd_catalog_components.md)** — публикация и использование компонентов.
- **[Container Registry](../container_registry.md)** — интеграция Registry с CI/CD.
- **[Pipeline Schedules](../pipeline_schedules.md)** — cron-расписания и Scheduled Execution Policies.
