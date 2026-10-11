# Concurrency, retry, timeout и контроль выполнения пайплайнов

**Актуально для:** GitLab 17.x–19.x, GitLab Runner 17.x–19.x

## Определения

**concurrent** — глобальный лимит одновременно выполняемых jobs на менеджере GitLab Runner. Устанавливается в `config.toml` (`concurrent = N`). Отличается от `resource_group`: `concurrent` ограничивает общую нагрузку на Runner, а `resource_group` обеспечивает мьютекс на уровне GitLab для конкретного ресурса.

**retry** — политика повторного выполнения failed job с задержкой и ограничением по количеству попыток.

**timeout** — максимальное время выполнения job. По умолчанию 1 час для всех типов jobs. Может быть переопределён на уровне project, Runner или job.

**interruptible** — флаг, указывающий, что job может быть отменён при запуске нового пайплайна на той же ветке (`workflow:auto_cancel`).

**pipeline locking** — механизм блокировки пайплайна для предотвращения параллельных запусков. Реализуется через `resource_group` или внешние механизмы (Redis, etcd).

**resource_group_process_mode** — политика выбора следующей задачи из очереди `resource_group`. Доступные режимы: `unordered` (по умолчанию), `oldest_first`, `newest_first`, `newest_ready_first` (с GitLab 18.6).

## Предварительные требования

- GitLab CE/EE 13.12+ для `resource_group`; `resource_group_process_mode` доступен с GitLab 14.4+; `newest_ready_first` — с GitLab 18.6+
- Роль Developer (или выше) в проекте для настройки `resource_group`
- GitLab Runner зарегистрирован и доступен; `concurrent` в `config.toml` настроен исходя из доступных CPU/RAM
- Для внешних механизмов блокировки: доступный Redis или etcd из CI-среды
- Понимание `workflow:auto_cancel`, `interruptible` и lifecycle job'ов в GitLab CI

## Основные концепции

### Timeout hierarchy

```
job: timeout → Runner: maximum_timeout → GitLab Server: instance timeout
```

На каждом уровне timeout может быть переопределён. Job-level `timeout` имеет высший приоритет, затем `maximum_timeout` Runner'а, затем instance-wide setting. Настройте timeout на каждом уровне для предсказуемого поведения.

### Resource group process modes

С версии GitLab 14.4 для `resource_group` доступны режимы очереди (`process_mode`). По умолчанию используется `unordered`. Режим задаётся через API, а не в YAML:

```bash
curl --request PUT \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  --data "process_mode=oldest_first" \
  --url "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/resource_groups/production"
```

| Режим | Описание | When to use |
| :--- | :--- | :--- |
| **unordered** | Задача выполняется, когда освобождается ресурс. Порядок не гарантируется. | Порядок не важен, простая сериализация |
| **oldest_first** | Выбирается задача из самого старого pipeline'а (по ID). | Непрерывные деплои, когда важно сохранять порядок |
| **newest_first** | Выбирается задача из самого нового pipeline'а. | Когда нужно откатывать старые деплои |
| **newest_ready_first** | Выбирается самая готовая задача из новых pipeline'ов. С GitLab 18.6+ | Сложные deployment strategies с dependency |

### Retry стратегии

| Стратегия | Конфигурация | Поведение |
| :--- | :--- | :--- |
| **Фиксированная задержка** | `retry: { max: 2, when: [script_error, api_failure], delay: 30 }` | Повтор через 30 секунд |
| **Экспоненциальная задержка** | Через скрипт | `delay: $((2 ** $CI_JOB_STATUS * 30))` |
| **Селективный retry** | `retry: { max: 3, when: [stuck_or_timeout_failure] }` | Только для таймаутов |

### Сравнение механизмов контроля

| Механизм | Уровень | Тип контроля | Use case |
| :--- | :--- | :--- | :--- |
| **resource_group** | Job | Мьютекс на уровне GitLab | Сериализация деплоев, доступ к shared-ресурсам |
| **concurrent** (config.toml) | Runner | Глобальный лимит jobs на менеджере | Ограничение общей нагрузки на Runner'ы |
| **workflow:auto_cancel** | Pipeline | Отмена устаревших пайплайнов | Предотвращение накопления старых прогонов |
| **Semaphore / Redis lock** | External | Распределённый lock | Кросс-проектная синхронизация |

## Практические сценарии

### Сценарий 1: Resource group для сериализации деплоев

```yaml
stages:
  - test
  - deploy

test:
  stage: test
  script: npm test
  tags:
    - shared-runner

deploy:
  stage: deploy
  script: npm run deploy
  resource_group: "production-deploy"
  environment: production
```

**Примечание:** `resource_group` на уровне job гарантирует, что только один deploy job с ключом `production-deploy` выполняется одновременно. Остальные jobs в pipeline не блокируются. Для ограничения общей нагрузки на Runner используйте `concurrent` в `config.toml`.

### Сценарий 1a: Ограничение параллелизма через Runner config.toml

```toml
# /etc/gitlab-runner/config.toml
concurrent = 4
check_interval = 3
```

**Примечание:** `concurrent` ограничивает общее количество одновременно запущенных jobs на данном менеджере. Если все слоты заняты, новые jobs переходят в статус `pending`. Это не заменяет `resource_group`, а дополняет его на уровне инфраструктуры.

### Сценарий 2: Resource group с process_mode=oldest_first

```yaml
stages:
  - deploy

deploy:
  stage: deploy
  script: ./deploy.sh
  resource_group: "production"
  environment: production
```

```bash
# Настройка process_mode через API (GitLab 14.4+)
curl --request PUT \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  --data "process_mode=oldest_first" \
  --url "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/resource_groups/production"
```

**Валидация:** Проверьте текущий `process_mode` и статус очереди:

```bash
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/resource_groups/production" | jq '{key, process_mode}'
```

### Сценарий 3: Родительский и дочерний пайплайн с resource_group

```yaml
# .gitlab-ci.yml (родительский пайплайн)
stages:
  - test
  - deploy

test:
  stage: test
  script: npm test

deploy:
  stage: deploy
  trigger:
    include: deploy.gitlab-ci.yml
    strategy: depend
  resource_group: "production"
  environment: production
```

```yaml
# deploy.gitlab-ci.yml (дочерний пайплайн)
stages:
  - provision
  - deploy

provision:
  stage: provision
  script: echo "Provisioning..."

deploy:
  stage: deploy
  script: ./deploy.sh
  environment: production
```

**Важно:** При `oldest_first` или `newest_first` deadlock возникает, если родительский и дочерний пайплайн используют один `resource_group`. Определяйте `resource_group` только в родительской задаче `trigger`.

### Сценарий 4: Retry с экспоненциальной задержкой

```yaml
test_flaky:
  stage: test
  script:
    - npm test
  retry:
    max: 3
    when:
      - script_error
      - api_failure
    delay:
      - 30  # Первая попытка через 30с
      - 60  # Вторая попытка через 60с
      - 120 # Третья попытка через 120с
```

**Автоматическая экспоненциальная задержка:**
```yaml
test_flaky:
  stage: test
  script:
    - |
      # Экспоненциальная задержка: 2^n * 30 секунд
      DELAY=$((2 ** ($CI_JOB_STATUS - 1) * 30))
      echo "Retry in $DELAY seconds..."
      sleep $DELAY
      npm test
  retry:
    max: 3
    when:
      - stuck_or_timeout_failure
```

### Сценарий 5: Timeout для различных типов jobs

```yaml
variables:
  DEFAULT_TIMEOUT: "1h"
  DEPLOY_TIMEOUT: "30m"
  TEST_TIMEOUT: "15m"

# Быстрые unit-тесты
unit_test:
  stage: test
  script: npm run test:unit
  timeout: $TEST_TIMEOUT

# Медленные интеграционные тесты
integration_test:
  stage: test
  script: npm run test:integration
  timeout: 2h

# Деплой с увеличенным timeout
deploy:
  stage: deploy
  script: kubectl apply -f manifests/
  timeout: $DEPLOY_TIMEOUT
  environment: production
```

**Валидация:** Проверьте действующий timeout в UI: `Settings > CI/CD > General pipelines > Timeout`. Job-level `timeout` не может превышать `maximum_timeout` Runner'а.

### Сценарий 6: Interruptible jobs для предотвращения накопления

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "push"
  auto_cancel:
    on_new_commit: interruptible  # Отменять предыдущий pipeline при новом коммите
    on_job_failure: all           # Fail-fast: отменять всё при ошибке

fast_lint:
  stage: lint
  script: npm run lint
  interruptible: true  # Может быть отменён при новом коммите

slow_build:
  stage: build
  script: npm run build
  interruptible: false  # Нельзя отменить (например, дорогая сборка)
```

### Сценарий 7: Внешний semaphore для кросс-проектной синхронизации

```yaml
# Использование Redis для distributed lock
stages:
  - deploy

.deploy_with_lock:
  stage: deploy
  script:
    - |
      # Получение lock через Redis
      LOCK_KEY="deploy:production"
      LOCK_VALUE="$CI_PIPELINE_ID"
      LOCK_TTL=3600

      # Попытка acquire lock (SET NX)
      ACQUIRED=$(redis-cli -h redis.example.com SET "$LOCK_KEY" "$LOCK_VALUE" NX EX $LOCK_TTL)

      if [ "$ACQUIRED" != "OK" ]; then
        echo "Another deployment is in progress, waiting..."
        # Ожидание освобождения lock
        while [ "$(redis-cli -h redis.example.com GET "$LOCK_KEY")" != "" ]; do
          sleep 10
        done
        # Повторная попытка
        ACQUIRED=$(redis-cli -h redis.example.com SET "$LOCK_KEY" "$LOCK_VALUE" NX EX $LOCK_TTL)
        if [ "$ACQUIRED" != "OK" ]; then
          echo "Failed to acquire lock"
          exit 1
        fi
      fi

      # Выполнение деплоя
      kubectl rollout status deployment/myapp -n production --timeout=300s

      # Освобождение lock
      redis-cli -h redis.example.com DEL "$LOCK_KEY"
  environment: production
  only:
    - main
```

## Мониторинг и алерты

### Ключевые метрики

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Queue time** | Время ожидания resource_group lock | < 5 минут |
| **Retry rate** | Доля jobs, потребовавших retry | < 5% |
| **Timeout rate** | Доля jobs, завершившихся по timeout | < 1% |
| **Interruptible cancellation rate** | Доля interruptible jobs, отменённых при новом коммите | Мониторить тренд |

### Мониторинг resource_group через API

```bash
# Просмотр активных resource_group
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/resource_groups" | jq

# Проверка статуса конкретной resource_group
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/resource_groups/production-deploy" | jq
```

### Алерты

| Алерт | Условие | Действие |
| :--- | :--- | :--- |
| **Resource group queue time** | Job ждёт lock > 10 минут | Проверить, не завис ли предыдущий job |
| **Retry rate spike** | > 10% jobs требуют retry | Проверить стабильность инфраструктуры |
| **Timeout increase** > 5 минут | Проверить производительность деплоя | Оптимизировать деплой или увеличить timeout |
| **External lock failure** | Redis/etcd недоступен | Проверить connectivity, failover |

## Особые случаи и ограничения

### Утечка lock resource_group

Если job завершается некорректно (kill -9, OOM, потеря соединения с Runner'ом), lock может остаться занятым. GitLab не освобождает lock автоматически по TTL — он привязан к lifecycle job'а. Для принудительного освобождения используйте API или UI.

### Взаимодействие с parallel:matrix

`resource_group` и `parallel:matrix` конфликтуют: matrix создаёт N экземпляров задачи, каждый из которых пытается захватить один и тот же `resource_group`. Решение — сериализуйте matrix через `parallel: 1` или используйте отдельные `resource_group` на каждый экземпляр матрицы с динамическим ключом (`resource_group: "build-$CI_COMMIT_REF_SLUG"`).

### Артефакты при interruptible отмене

При отмене pipeline через `auto_cancel` артефакты interruptible jobs **не сохраняются**, даже при `when: always`. Для критичных артефактов используйте `interruptible: false`.

### Deadlock с oldest_first и дочерними пайплайнами

При `oldest_first` или `newest_first` deadlock возникает, если родительский и дочерний пайплайн используют один `resource_group`. Определяйте `resource_group` только в родительской задаче `trigger` и используйте `strategy: depend`.

### Resource group и manual jobs

Manual job, удерживающий `resource_group`, блокирует ресурс до перевода в `success` или `failed`. Если оператор не реагирует — используйте API для принудительного перевода или ручного освобождения lock.

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Job ждёт вечно | Lock не освобождался, job упал с ошибкой | Принудительно освободите lock через API/UI; увеличьте `timeout` job'а |
| Deadlock | Несколько job'ов ждут разные resource_group в цикле | Пересмотрите архитектуру, избегайте циклических зависимостей; используйте `strategy: depend` для downstream |
| Job отменён при новом коммите | `interruptible: true` + `auto_cancel: on_new_commit` | Установите `interruptible: false` для критичных jobs |
| Timeout слишком короткий | Деплой не успевает завершиться | Увеличьте `timeout` или оптимизируйте деплой |
| Concurrency превышен | Все слоты `concurrent` в `config.toml` заняты | Увеличьте `concurrent` или добавьте Runner'ы |
| Matrix не параллелится | `parallel:matrix` конфликтует с `resource_group` | Уберите `resource_group` с matrix-задач или используйте `parallel: 1` |
| Артефакты пропали после отмены | `interruptible: true` + `auto_cancel` | Установите `interruptible: false` для jobs с критичными артефактами |

## Best Practices

### Разработка (Dev)

1. **Устанавливайте timeout для каждого job:** По умолчанию 1 час может быть слишком много или слишком мало.
2. **Используйте `interruptible` для быстрых jobs:** Линт, форматирование — всегда interruptible.
3. **Не делайте interruptible дорогие jobs:** Сборки, деплои — `interruptible: false`.
4. **Используйте retry для нестабильных jobs:** Тесты с внешними зависимостями — retry с экспоненциальной задержкой.

### Эксплуатация (DevOps/SRE)

1. **Мониторьте очередь resource_group:** GitLab API позволяет получить список ожидающих jobs:
    ```bash
    curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
      "$CI_API_V4_URL/projects/$CI_PROJECT_ID/resource_groups" | jq
    ```
2. **Настройте алерты на долгие ожидания:** Если job ждёт lock > 10 минут — проверьте, не завис ли предыдущий job.
3. **Настройте process_mode:** Для production-деплоев используйте `oldest_first` через API. По умолчанию `unordered` не гарантирует порядок.
4. **Мониторьте Sidekiq queue:** Задания, ожидающие resource_group, находятся в Sidekiq queue. Мониторьте длину очереди.
5. **Настройте manual unlock:** При зависших jobs настройте процедуру принудительного освобождения lock через API/UI.

### Sysadmin

1. **Ограничьте количество resource_group на инстансе:** Каждый resource_group создаёт записи в базе. Лимит: 1000 на проект.
2. **Используйте отдельный Redis для external locks:** Не смешивайте кэш GitLab и external locks.
3. **Ротируйте секреты в external lock:** Не храните токены в Redis в открытом виде.
4. **Настройте принудительный unlock:** При зависших jobs используйте API или UI для ручного освобождения lock.

## Дополнительная информация

### См. также

- **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)** — типы исполнителей и их характеристики
- **[Мониторинг и метрики GitLab CI/CD](../Advanced/monitoring_and_metrics.md)** — метрики очередей и runners
- **[Downstream пайплайны: лучшие практики](../Advanced/Downstream_Pipelines/best_practices.md)** — мониторинг bridge jobs
- **[Матричные сборки и сериализация](../Advanced/workflow_rules/matrix_builds_and_serialization.md)** — resource_group, parallel:matrix
- **[API и Webhooks автоматизация](../Advanced/api_and_webhooks_automation.md)** — работа с GitLab API

### Внешние ресурсы

- [GitLab: resource_group](https://docs.gitlab.com/ee/ci/yaml/#resource_group)
- [GitLab: resource_group process modes](https://docs.gitlab.com/ee/ci/resource_groups/)
- [GitLab: retry](https://docs.gitlab.com/ee/ci/yaml/#retry)
- [GitLab: timeout](https://docs.gitlab.com/ee/ci/yaml/#timeout)
- [GitLab: interruptible](https://docs.gitlab.com/ee/ci/yaml/#interruptible)
