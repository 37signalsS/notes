# Кэш и директивки пайплайна в GitLab CI

**Актуально для:** GitLab 19.x / GitLab Runner 19.x

## Требования и предварительные условия

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `workflow:rules` | 12.3+ | Глобальная фильтрация пайплайнов |
| `rules:changes` | 11.4+ | Фильтрация по изменениям файлов |
| `needs` (DAG) | 12.10+ | Параллельное выполнение без стадий |
| `dependencies` | 1.0+ | Управление артефактами |
| `interruptible` | 13.12+ | Разрешение отмены через `auto_cancel` |
| `auto_cancel:on_new_commit` | 16.0+ | Автоматическая отмена при новом пуш |
| `auto_cancel:on_job_failure` | 13.12+ | Fail-Fast отмена ветки графа |
| `resource_group` | 11.11+ | Сериализация доступа к ресурсам |
| `resource_group_process_mode` | 16.0+ | Режимы упорядочивания (`oldest_first`, `newest_first`) |

### Необходимые знания

- Базовый синтаксис `.gitlab-ci.yml` и жизненный цикл пайплайна
- Механизм кэширования GitLab Runner (`cache:key`, `policy`, `fallback_keys`) — см. **[Ключи и политики](./cache_keys.md#базовые-концепции)**
- Различие между кэшем и артефактами — см. **[Обзор кэширования](./caching_overview.md#сравнение-кэша-и-артефактов)**
- DAG-модель выполнения (`needs`, `dependencies`) — см. **[DAG с needs](../workflow_rules/dag_with_needs.md)**
- Принципы безопасного кэширования (cache poisoning, isolation) — см. **[Лучшие практики](./cache_best_practices.md#безопасность-security)**

### Целевая аудитория

Справочник предназначен для DevOps-инженеров, SRE и системных администраторов, работающих с on-premise и гибридной инфраструктурой. Примеры ориентированы на оптимизацию времени сборки, предотвращение потерь кэша при отмене пайплайнов и безопасную сериализацию записи в распределённых командах Shared Runners.

## Определения

**Cache-aware `rules`** — условие включения задачи в пайплайн, косвенно управляющие созданием кэша: если задача отфильтрована, её кэш не создаётся.

**Cache-aware `workflow:rules`** — глобальные правила, управляющие созданием всего пайплайна. Если пайплайн не создаётся, никакие кэши не создаются.

**Cache-aware `needs`** — DAG-зависимость, влияющая на параллельную загрузку кэша: задачи с `needs` запускаются раньше и могут начать загрузку кэша одновременно.

**Cache-aware `dependencies`** — директива, управляющая загрузкой артефактов. На кэш не влияет, но косвенно влияет на время начала загрузки кэша через порядок выполнения задачи.

**Cache-aware `interruptible`** — флаг задачи, разрешающий отмену через `auto_cancel`. При отмене задача не сохраняет кэш.

**Cache-aware `auto_cancel`** — механизм автоматической отмены устаревших пайплайнов. Режим `on_new_commit: interruptible` отменяет только задачи с `interruptible: true`, и их кэш не сохраняется.

**Cache-aware `resource_group`** — мьютекс на уровне GitLab, сериализующий доступ к общему ресурсу. Используется для предотвращения race condition при параллельной записи кэша.

## Основные концепции

### 1. Влияние `rules` и `workflow:rules` на кэш

Общие определения и синтаксис `rules` / `workflow:rules`: см. SSoT **[Правила запуска задач](../workflow_rules/job_rules.md)** и **[Конструктор рабочих процессов](../gitlab_ci_workflow_builder.md)**.

#### 1.1. Фильтрация задач

Если задача отфильтрована через `rules`, её кэш не создаётся и не загружается. Это значит, что:
- Задачи с `rules` могут иметь "холодный старт", если они редко запускаются.
- `fallback_keys` критичны для задач с селективными `rules`.

```yaml
test_app:
  stage: test
  rules:
    - changes:
        - apps/frontend/**/*
  cache:
    key:
      files: [apps/frontend/package-lock.json]
      prefix: frontend
    paths: [apps/frontend/.npm/]
    policy: pull-push
  script:
    - cd apps/frontend && npm test
```

**Проблема:** Если `apps/frontend/package-lock.json` не изменился, но задача не запускалась несколько дней, её кэш мог быть удалён через S3 lifecycle. Решение — используйте `fallback_keys` с базовым кэшем из `main`.

#### 1.2. Фильтрация пайплайнов

`workflow:rules` управляет созданием всего пайплайна. Если пайплайн не создаётся, никакие кэши не создаются.

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Проблема:** Scheduled пайплайны или pipeline для tags могут не иметь кэша, если они не покрыты `workflow:rules`. Решение — добавьте соответствующие условия.

#### 1.3. `rules:changes` и кэширование

`rules:changes` запускает задачу только при изменении определённых файлов. Если lock-файл не изменился, задача не запустится, и кэш не обновится.

```yaml
build_frontend:
  stage: build
  rules:
    - changes:
        - apps/frontend/**/*
        - package-lock.json
  cache:
    key:
      files: [apps/frontend/package-lock.json]
    paths: [apps/frontend/.npm/]
```

**Важно:** Если `package-lock.json` изменился, но `apps/frontend/**/*` нет, задача всё равно запустится и обновит кэш. Это корректное поведение.

### 2. Влияние `needs` и `dependencies` на кэш

Общие определения `needs` и `dependencies`: см. SSoT **[Артефакты в GitLab CI](./gitlab_ci_artifacts.md)** и **[DAG с needs](../workflow_rules/dag_with_needs.md)**.

#### 2.1. Параллельная загрузка кэша

`needs` позволяет задачам запускаться параллельно, как только готовы их зависимости. Это означает, что несколько задач могут начать загрузку кэша одновременно.

```yaml
build:
  stage: build
  cache:
    key: build-cache
    paths: [build/]
    policy: pull-push
  script:
    - make build

test_1:
  stage: test
  needs: [build]
  cache:
    key: test-cache
    paths: [.pytest-cache/]
    policy: pull
  script:
    - pytest tests/unit/

test_2:
  stage: test
  needs: [build]
  cache:
    key: test-cache
    paths: [.pytest-cache/]
    policy: pull
  script:
    - pytest tests/integration/
```

**Поведение:** `test_1` и `test_2` запускаются параллельно после завершения `build`. Обе задачи загружают `test-cache` параллельно. Если Runner поддерживает параллельный cache transfer (`FF_USE_PARALLEL_CACHE_TRANSFER`), загрузка ускоряется.

#### 2.2. `needs: [{job: build, artifacts: false}]` и кэш

`artifacts: false` в `needs` отключает загрузку артефактов, но НЕ влияет на кэш. Кэш загружается независимо от `needs`.

```yaml
deploy:
  stage: deploy
  needs:
    - job: build
      artifacts: false  # Артефакты не нужны
  cache:
    key: deploy-cache
    paths: [.deploy-tools/]
    policy: pull
  script:
    - ./deploy.sh
```

**Важно:** Кэш загружается всегда, если он указан в задаче, независимо от `needs` и `dependencies`.

#### 2.3. `dependencies` и кэш

`dependencies` управляет только артефактами. На кэш не влияет.

```yaml
lint:
  stage: lint
  needs: [build]
  dependencies: []  # Артефакты не нужны
  cache:
    key: lint-cache
    paths: [.eslint-cache/]
    policy: pull
  script:
    - npm run lint
```

**Кэш загружается**, хотя `dependencies: []` отключает артефакты.

### 3. Влияние `interruptible` и `auto_cancel` на кэш

Общие определения `interruptible` и `auto_cancel`: см. SSoT **[Конструктор рабочих процессов](../gitlab_ci_workflow_builder.md)** и **[Правила запуска задач](../workflow_rules/job_rules.md)**.

#### 3.1. Отмена задач и кэш

При отмене задачи через `auto_cancel` кэш **не сохраняется**, даже если `cache:when: always`.

```yaml
workflow:
  auto_cancel:
    on_new_commit: interruptible

test:
  stage: test
  interruptible: true
  cache:
    key: test-cache
    paths: [.pytest-cache/]
    policy: pull-push
  script:
    - pytest tests/
```

**Сценарий:**
1. Запущен пайплайн с `test` задачей.
2. `test` начал загрузку кэша и создание нового кэша.
3. Пришёл новый коммит, `auto_cancel` отменил `test`.
4. Кэш, который `test` должен был создать, **не сохранился**.

**Решение:** Для критичных кэшей используйте `interruptible: false`. Но это предотвращает отмену задачи, что может привести к простоям Runner'ов.

#### 3.2. `cache:when: always` и отмена

`cache:when: always` сохраняет кэш даже при падении задачи. Но при `auto_cancel` кэш всё равно не сохраняется.

```yaml
build:
  stage: build
  cache:
    key: build-cache
    paths: [build/]
    when: always  # Сохранять кэш даже при падении
  script:
    - make build || true
```

**Проблема:** Если задача упала, кэш может содержать неполные или повреждённые данные. Используйте `when: always` только для диагностики.

### 4. Влияние `resource_group` на кэш

Общее определение `resource_group` и режимы `resource_group_process_mode`: см. SSoT **[Матричные сборки и сериализация](../workflow_rules/matrix_builds_and_serialization.md)**.

`resource_group` сериализует доступ к общему ресурсу. При использовании `resource_group` с `policy: pull-push` только одна задача одновременно может записывать кэш.

```yaml
install_deps:
  stage: build
  cache:
    key: deps-$CI_COMMIT_REF_SLUG
    paths: [node_modules/]
    policy: pull-push
  resource_group: cache-write
  script:
    - npm ci

test_1:
  stage: test
  cache:
    key: deps-$CI_COMMIT_REF_SLUG
    paths: [node_modules/]
    policy: pull
  script:
    - npm test
```

**Поведение:**
- `install_deps` имеет `resource_group: cache-write`. Если параллельно запущены два пайплайна, второй будет ждать завершения первого.
- `test_1` имеет `policy: pull` и не имеет `resource_group`. Может выполняться параллельно с `install_deps`.

**Deadlock:** Если родительский и дочерний пайплайн используют одну `resource_group` с `oldest_first`, возникает взаимная блокировка. Решение — определите `resource_group` в родительской задаче `trigger`, а не в дочерней.

### 5. Практические сценарии

#### Сценарий 1: MR пайплайн с `workflow:rules` и кэшем

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

cache:
  key:
    files: [package-lock.json]
    prefix: npm
  paths: [.npm/]
  policy: pull-push

install:
  stage: .pre
  script:
    - npm ci --prefer-offline
  cache:
    policy: pull-push

test:
  stage: test
  script:
    - npm test
  cache:
    policy: pull

lint:
  stage: test
  script:
    - npm run lint
  cache:
    policy: pull
```

**Поведение:**
- Пайплайн создаётся только для MR и `main`.
- `install` создаёт кэш.
- `test` и `lint` только читают кэш.
- При новом коммите в MR `auto_cancel` отменяет предыдущий пайплайн. Если `interruptible: true`, `install` может не сохранить кэш.

#### Сценарий 2: DAG с параллельной загрузкой кэша

```yaml
build_a:
  stage: build
  cache:
    key: build-a
    paths: [build/a/]
    policy: pull-push
  script:
    - make build-a

build_b:
  stage: build
  cache:
    key: build-b
    paths: [build/b/]
    policy: pull-push
  script:
    - make build-b

test_a:
  stage: test
  needs: [build_a]
  cache:
    key: test-a
    paths: [.test-cache-a/]
    policy: pull
  script:
    - pytest tests/a/

test_b:
  stage: test
  needs: [build_b]
  cache:
    key: test-b
    paths: [.test-cache-b/]
    policy: pull
  script:
    - pytest tests/b/
```

**Поведение:**
- `build_a` и `build_b` выполняются параллельно.
- `test_a` и `test_b` также параллельны, каждая загружает свой кэш.
- Если `FF_USE_PARALLEL_CACHE_TRANSFER=true`, загрузка обоих кэшей ускоряется.

#### Сценарий 3: Сериализация записи кэша через `resource_group`

```yaml
stages:
  - build
  - test

install_deps:
  stage: build
  cache:
    key: deps-$CI_COMMIT_REF_SLUG
    paths: [node_modules/]
    policy: pull-push
  resource_group: cache-write
  resource_group_process_mode: oldest_first
  script:
    - npm ci

test:
  stage: test
  cache:
    key: deps-$CI_COMMIT_REF_SLUG
    paths: [node_modules/]
    policy: pull
  script:
    - npm test
```

**Поведение:**
- Если два MR одновременно запускают `install_deps`, второй ждёт завершения первого.
- `test` не имеет `resource_group` и выполняется сразу после `install_deps`.

## Валидация и диагностика

### Проверка фильтрации задач через `rules`

1. **CI Lint:** Вставьте конфигурацию в `CI/CD > Editor > Validate` и проверьте, что задачи, которые должны быть отфильтрованы, отсутствуют в списке.
2. **Pipeline graph:** После запуска пайплайна проверьте, что отфильтрованные задачи не отображаются.
3. **API:** Получите список задач пайплайна и проверьте их наличие:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/jobs" | \
     jq '.[].name'
   ```

### Проверка создания кэша

```bash
# В логах задачи ищите:
grep -E "(Checking cache|Downloading|Creating cache|Uploading|Archive is up to date)" job.log

# Примеры логов и их значение:
# "Checking cache for my-key-v123..." → Runner ищет кэш
# "Downloading https://s3.../cache.zip" → Cache miss, загрузка
# "Archive is up to date! Skipping upload" → FF_SKIP_NOOP_CACHE работает
# "Creating cache..." → Cache miss, создание нового кэша
# "Using parallel cache transfer with concurrency=4" → FF_USE_PARALLEL_CACHE_TRANSFER активен
```

### Проверка эффекта `auto_cancel` на кэш

1. Запустите пайплайн с задачей, которая создаёт кэш (`policy: pull-push`).
2. Сделайте новый коммит в ветку, пока пайплайн выполняется.
3. Проверьте, что предыдущий пайплайн перешёл в статус `canceled`.
4. Откройте логи отменённой задачи и убедитесь, что нет секции `Creating cache...` или `Uploading cache.zip`.
5. Если кэш должен был обновиться, но не обновился — это ожидаемое поведение для `interruptible: true`.

### Проверка `resource_group` и сериализации

1. Запустите два пайплайна одновременно, оба содержат задачу с одинаковой `resource_group`.
2. Вторая задача перейдёт в статус `pending` с сообщением `waiting for resource group`.
3. После завершения первой задачи вторая начнёт выполнение.
4. Проверьте, что кэш не повреждён (сравните хеш файлов в кэше до и после).

## Лучшие практики

### Безопасность

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| `interruptible: false` для писателей кэша | Задачи, создающие кэш (`pull-push`), не должны прерываться `auto_cancel`, иначе кэш не обновится | Высокий |
| `resource_group` для писателей кэша | При параллельных пайплайнах сериализуйте запись кэша, чтобы избежать race condition | Высокий |
| `policy: pull` для потребителей | Задачи, только читающие кэш, должны иметь `pull` — это предотвращает перезапись кэша при параллельном выполнении | Высокий |
| `fallback_keys` для селективных `rules` | Если задача запускается редко, используйте `fallback_keys` для избежания холодного старта | Средний |

**Важно:** Детальный разбор угроз cache poisoning и контрольных мер см. в **[Лучшие практики кэширования](./cache_best_practices.md#безопасность-security)**.

### Производительность

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| Уникальные ключи для параллельных задач | При `needs` с параллельной загрузкой используйте разные ключи для разных кэшей, чтобы избежать блокировки | Средний |
| `interruptible: true` для не критичных задач | Разрешите отмену задач, которые только читают кэш (`policy: pull`) — это освобождает Runner'ы | Средний |
| `cache:when: on_success` по умолчанию | Не используйте `when: always` для критичных кэшей — при падении задачи кэш может быть повреждён | Средний |
| `FF_USE_PARALLEL_CACHE_TRANSFER` для DAG | При параллельной загрузке нескольких кэшей включите параллельный transfer — это ускоряет загрузку в 3–5 раз | Средний |

### Организация пайплайна

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| Единая точка записи кэша | Только одна задача на pipeline должна иметь `pull-push` для данного ключа | Высокий |
| `workflow:rules` с fallback | Всегда добавляйте fallback-правило в `workflow:rules`, чтобы пайплайн создавался для scheduled/tag | Средний |
| Избегайте `dependencies` для управления кэшем | `dependencies` влияет только на артефакты, на кэш — нет. Используйте явный `cache:key` | Низкий |

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Кэш не создаётся, хотя задача запустилась | Отсутствует `cache:key` или `policy: push/pull-push` | Проверьте блок `cache:` в задаче. Для создания кэша нужна политика `pull-push` или `push` |
| Кэш не создаётся после `auto_cancel` | Задача была прервана, кэш не сохраняется | Используйте `interruptible: false` для задач, критичных для кэша |
| Задача не запускается, кэш не обновляется | `rules` или `workflow:rules` фильтруют задачу | Проверьте условия `rules`. Для `rules:changes` убедитесь, что lock-файл в списке изменений |
| Параллельные задачи перезаписывают кэш | Несколько задач с `policy: pull-push` и одним ключом | Добавьте `resource_group` для сериализации записи. Только одна задача должна иметь `pull-push` |
| Deadlock при parent-child пайпланах | Родитель и дочерний пайплайн используют одну `resource_group` с `oldest_first` | Определите `resource_group` в родительской задаче `trigger`, а не в дочерней |
| Кэш не загружается при `needs` | Ключ кэша указан неправильно или кэш отсутствует | Проверьте `cache:key`. `needs` не влияет на загрузку кэша, только на порядок запуска |
| `dependencies: []` отключает кэш | Ошибка в диагностике: `dependencies` влияет только на артефакты | Проверьте явно блок `cache:` в задаче. `dependencies` не трогает кэш |
| Холодный старт для задач с `rules:changes` | Задача редко запускается, кэш удалён через lifecycle | Используйте `fallback_keys` с базовым кэшем из `main` |
| `interruptible: true` не помогает | `interruptible` работает только на уровне планирования, уже запущенный job не прерывается | Убедитесь, что Runner поддерживает отмену через API. Для гарантии используйте `interruptible: false` |

## Граничные случаи и ограничения

### `rules:changes` и кэш

Если `rules:changes` не включает lock-файл, задача не запустится, и кэш не обновится, даже если изменился исходный код. Это корректное поведение: `changes` работает на уровне Git diff, а не на уровне содержимого кэша. Если вам нужно обновлять кэш при любых изменениях в директории, используйте `rules:changes` с lock-файлом или глобальное правило `if: $CI_PIPELINE_SOURCE == "push"`.

### `workflow:rules` и scheduled пайплайны

Scheduled пайплайны и пайплайны для tags имеют переменные `$CI_PIPELINE_SOURCE == "schedule"` и `$CI_PIPELINE_SOURCE == "tag"`. Если `workflow:rules` не покрывает эти источники, пайплайн не создаётся, и кэш не используется. Решение — добавьте явные условия:

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_PIPELINE_SOURCE == "tag"
```

### `interruptible` и уже запущенные задачи

`interruptible` работает только на уровне планирования GitLab. Если задача уже выполнена на Runner'е, новый коммит не прервёт её. Для гарантированной отмены убедитесь, что:
1. Runner поддерживает отмену через API (проверьте `concurrent` и `request_concurrency` в `config.toml`).
2. Задача не блокирует сигналы (например, `trap` в bash).
3. `timeout` задачи меньше, чем время между коммитами.

### `resource_group` и `interruptible: true`

Если задача с `resource_group` имеет `interruptible: true` и удерживает мьютекс, `auto_cancel` может прервать её. При этом мьютекс освобождается, и следующая задача начинается. Но если прерванная задача создавала кэш, он не сохраняется. Для критичных операций (деплой, миграции БД) всегда используйте `interruptible: false` в паре с `resource_group`.

### DAG и несколько кэшей с одним ключом

Если `needs` создаёт параллельные задачи, и они используют одинаковый ключ кэша с `policy: pull-push`, они будут конкурировать за запись. Используйте разные ключи или `resource_group` для сериализации. Для задач, только читающих кэш (`policy: pull`), конкуренции нет — они могут загружать один и тот же кэш параллельно.

## Дополнительная информация

### См. также

- **[Обзор кэширования](./caching_overview.md)** — архитектура и уровни хранения.
- **[Ключи и политики](./cache_keys.md)** — `cache:key`, `fallback_keys`, `policy`.
- **[Лучшие практики](./cache_best_practices.md)** — безопасность, мониторинг, SRE.
- **[Практические сценарии](./cache_scenarios.md)** — примеры для языков и инфраструктуры.
- **[Артефакты в GitLab CI](./gitlab_ci_artifacts.md)** — `needs`, `dependencies`, `dotenv`.
- **[Матричные сборки и сериализация](../workflow_rules/matrix_builds_and_serialization.md)** — `resource_group`, `parallel:matrix`.
- **[Правила запуска задач](../workflow_rules/job_rules.md)** — `rules`, `workflow:rules`.
- **[DAG с needs](../workflow_rules/dag_with_needs.md)** — направленный ациклический граф.
