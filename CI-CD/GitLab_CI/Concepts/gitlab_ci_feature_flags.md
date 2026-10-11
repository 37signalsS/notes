# Feature Flags в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Определения

*   **Feature Flag (Флаг функциональности)** — механизм включения/выключения функциональности в production без деплоя нового кода. Позволяет делать progressive delivery, A/B тестирование и канареечные релизы.
*   **Feature Toggle** — синоним Feature Flag; термин Martin Fowler.
*   **OpenFeature** — открытый стандарт (CNCF) для управления флагами, предоставляющий единый API поверх разных бэкендов.
*   **Unleash** — популярный open-source feature flag management system.
*   **LaunchDarkly** — commercial feature flag management platform.
*   **Flagsmith** — open-source alternative с self-hosted опцией.
*   **Flag Hygiene** — процесс очистки устаревших флагов после полного выпуска функциональности.
*   **GitLab Feature Flags** — встроенный в GitLab (Ultimate) механизм управления флагами на базе Unleash-совместимого API.
*   **FF_ префикс (Runner feature flags)** — environment variables в GitLab Runner, управляющие поведением executor'ов (например, `FF_USE_FASTZIP`, `FF_NETWORK_PER_BUILD`).

> **Примечание:** Типология флагов (Release Flag, Ops Flag, Kill Switch, Experiment Flag) и стратегии управления описаны в **[Feature Toggles](../../CI-CD/Testing/feature_toggles/)**. Ниже — GitLab CI pipeline-интеграция и встроенные возможности GitLab.

## Базовые концепции

### Интеграция Feature Flags с GitLab CI/CD

Feature flags могут управляться на разных этапах пайплайна:

1.  **Валидация флагов**: Проверка naming conventions, документации, TTL.
2.  **Создание флагов**: Автоматическое создание флагов в feature flag management system.
3.  **Тестирование**: Валидация поведения флага в staging.
4.  **Промоушен**: Поэтапное включение флага (canary → production).
5.  **Очистка**: Автоматическое удаление флагов после полного выпуска.

### Архитектура управления флагами

```
[GitLab CI Pipeline]
    │
    ├─── Валидация naming conventions
    ├─── Создание/обновление флага (API)
    ├─── Тестирование в staging
    ├─── Промоушен в production
    └─── Очистка устаревших флагов
           │
           ▼
[Feature Flag Management System]
    │
    ├─── Unleash (self-hosted)
    ├─── LaunchDarkly (commercial)
    ├─── Flagsmith (open-source)
    └─── Встроенный (GitLab Feature Flags)
```

### Встроенные Feature Flags GitLab

GitLab имеет два слоя feature flags:

1.  **Прикладные флаги (Application Feature Flags)** — управляют функциональностью вашего приложения через Unleash-совместимый API. Доступны в GitLab Premium/Ultimate.
2.  **Инфраструктурные флаги (GitLab Feature Flags / FF_ flags)** — управляют поведением самого GitLab и Runner'ов. Включаются через Rails console или Admin Area.

**Примеры инфраструктурных флагов GitLab:**

| Флаг | Назначение | Версия |
|:---|:---|:---|
| `gitlab_ci_builds_queuing_metrics` | Метрики очереди CI/CD | 16.3+ |
| `gitlab_runner_autoscaling` | Автоскейлинг Runner'ов | 16.0+ |
| `feature_flag_management_permissions` | Ограничение прав на управление флагами | 19.4+ |
| `ci_stop_writing_to_pipeline_variables` | Оптимизация хранения pipeline variables | 17.0+ |

### GitLab Feature Flags API

GitLab предоставляет Unleash-совместимый API для управления флагами приложения:

*   **API endpoint:** `/api/v4/feature_flags`
*   **Максимум флагов на проект:**
    *   GitLab Self-Managed: 200
    *   GitLab.com Free: 50
    *   GitLab.com Premium: 150
    *   GitLab.com Ultimate: 200

**Поддерживаемые стратегии:**

*   **All users** — включено для всех пользователей
*   **Percent Rollout** — процент показов с консистентностью (User IDs / Session IDs / Random / Available ID)
*   **Percent of Users** — процент аутентифицированных пользователей
*   **User IDs** — список конкретных пользователей
*   **User List** — сохраненные списки пользователей

## Практические сценарии

### Предварительные требования

**Для работы с GitLab Feature Flags:**

*   GitLab 17.x+ (Premium/Ultimate для встроенных флагов)
*   GitLab Runner 17.x+ (для FF_ префиксов)
*   Unleash-совместимый SDK в приложении (Go, Ruby, Node.js, Python, Java)
*   `PRIVATE-TOKEN` с ролью Maintainer или выше

**Для внешних систем управления флагами (Unleash, LaunchDarkly):**

*   Развернутый FFaaS инстанс (self-hosted)
*   API токен с правами на создание/изменение флагов
*   Сетевая доступность из CI/CD Runner'ов до FFaaS

### Сценарий 1: Валидация naming conventions флагов

```yaml
stages:
  - validate
  - test
  - deploy

validate_flags:
  stage: validate
  image: alpine:latest
  script:
    # Проверка naming conventions: префикс, lowercase, snake_case
    - |
      FLAGS=$(git diff --name-only $CI_COMMIT_BEFORE_SHA $CI_COMMIT_SHA | grep -E 'flags/|feature_flags/')
      for FLAG in $FLAGS; do
        NAME=$(basename $FLAG .json)
        if ! echo "$NAME" | grep -qE '^(release|ops|experiment|kill_switch)_[a-z0-9_]+$'; then
          echo "ERROR: Invalid flag name: $NAME"
          echo "Expected format: <type>_<description> (e.g., release_new_checkout)"
          exit 1
        fi
      done
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - flags/**/*
        - feature_flags/**/*
```

### Сценарий 2: Создание feature flag через GitLab API

```yaml
stages:
  - validate
  - create_flag
  - test

create_feature_flag:
  stage: create_flag
  image: curlimages/curl:latest
  script:
    - |
      curl --request POST \
        --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
        --header "Content-Type: application/json" \
        --data '{
          "name": "new_checkout_flow",
          "description": "New checkout flow",
          "type": "release",
          "strategies": [
            {
              "name": "default",
              "parameters": {
                "rollout": "0"
              }
            }
          ]
        }' \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/feature_flags"
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - src/**/*

test_feature_flag:
  stage: test
  image: node:20
  script:
    - npm test -- --feature-flag=new_checkout_flow
```

### Сценарий 3: Промоушен флага через окружения

```yaml
stages:
  - deploy_staging
  - deploy_prod

enable_flag_staging:
  stage: deploy_staging
  image: curlimages/curl:latest
  script:
    - |
      curl --request PUT \
        --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
        --header "Content-Type: application/json" \
        --data '{"strategies": [{"name": "default", "parameters": {"rollout": "100"}}]}' \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/feature_flags/new_checkout_flow"
  environment:
    name: staging

enable_flag_prod_canary:
  stage: deploy_prod
  image: curlimages/curl:latest
  script:
    - |
      curl --request PUT \
        --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
        --header "Content-Type: application/json" \
        --data '{"strategies": [{"name": "gradualRolloutUserId", "parameters": {"percentage": "10"}}]}' \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/feature_flags/new_checkout_flow"
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 4: Автоматическая очистка устаревших флагов

```yaml
stages:
  - cleanup

cleanup_old_flags:
  stage: cleanup
  image: curlimages/curl:latest
  script:
    # Получить список флагов, созданных более 30 дней назад
    - |
      FLAGS=$(curl --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/feature_flags" | \
        jq -r '.[] | select(.created_at < (now - 2592000)) | .name')
      
      for FLAG in $FLAGS; do
        echo "Checking flag: $FLAG"
        # Проверить, что флаг не используется в коде
        if ! git grep -q "$FLAG"; then
          echo "Removing unused flag: $FLAG"
          curl --request DELETE \
            --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
            "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/feature_flags/$FLAG"
        fi
      done
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### Сценарий 5: Управление инфраструктурными feature flags GitLab

```yaml
stages:
  - validate
  - deploy

check_gitlab_feature_flags:
  stage: validate
  image: ruby:3.2
  script:
    - |
      # Подключение к GitLab Rails console для проверки флагов
      bundle exec rails runner "
      puts '=== CI Queue Metrics Flag ==='
      puts 'Enabled: ' + Feature.enabled?(:ci_observe_pipelines_finished).to_s
      puts 'Enabled: ' + Feature.enabled?(:gitlab_ci_builds_queuing_metrics).to_s
      "
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual

enable_queuing_metrics:
  stage: deploy
  image: ruby:3.2
  script:
    - |
      bundle exec rails runner "
      Feature.enable(:gitlab_ci_builds_queuing_metrics)
      puts 'Feature flag gitlab_ci_builds_queuing_metrics enabled'
      "
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
  environment:
    name: production
```

### Сценарий 6: Progressive delivery с GitLab Environments

```yaml
stages:
  - deploy_staging
  - deploy_prod_10
  - deploy_prod_50
  - deploy_prod_100

deploy_staging:
  stage: deploy_staging
  image: bitnami/kubectl:latest
  script:
    - kubectl set env deployment/my-app FEATURE_NEW_UI=true -n staging
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"

deploy_prod_10:
  stage: deploy_prod_10
  image: bitnami/kubectl:latest
  script:
    # Canary: 10% трафика
    - kubectl patch virtualservice my-app -n prod -p '{"spec":{"http":[{"route":[{"destination":{"host":"my-app","subset":"v1"},"weight":90},{"destination":{"host":"my-app","subset":"v2"},"weight":10}]}]}}'
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

deploy_prod_50:
  stage: deploy_prod_50
  image: bitnami/kubectl:latest
  script:
    - kubectl patch virtualservice my-app -n prod -p '{"spec":{"http":[{"route":[{"destination":{"host":"my-app","subset":"v1"},"weight":50},{"destination":{"host":"my-app","subset":"v2"},"weight":50}]}]}}'
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 7: Использование FF_ префиксов в GitLab Runner

```yaml
# .gitlab-ci.yml

stages:
  - build
  - test

build_job:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  variables:
    # Включение per-build сети (FF_NETWORK_PER_BUILD)
    FF_NETWORK_PER_BUILD: "true"
    # Отключение umask 0000 для docker executor
    FF_DISABLE_UMASK_FOR_DOCKER_EXECUTOR: "true"
  script:
    - docker build -t my-app:$CI_COMMIT_SHA .
    - docker push my-app:$CI_COMMIT_SHA
```

```toml
# /etc/gitlab-runner/config.toml
[[runners]]
  name = "docker-runner"
  url = "https://gitlab.example.com/"
  token = "TOKEN"
  executor = "docker"
  [runners.feature_flags]
    FF_USE_DIRECT_DOWNLOAD = true
    FF_NETWORK_PER_BUILD = true
```

## Валидация

### Проверка статуса feature flags

```bash
# Список всех флагов проекта через GitLab API
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/feature_flags" | jq .

# Проверка конкретного флага
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/feature_flags/my_feature" | jq .

# Включение флага
curl --request PUT \
  --header "PRIVATE-TOKEN: <token>" \
  --header "Content-Type: application/json" \
  --data '{"enabled": true}' \
  "https://gitlab.example.com/api/v4/projects/<project_id>/feature_flags/my_feature"

# Выключение флага
curl --request PUT \
  --header "PRIVATE-TOKEN: <token>" \
  --header "Content-Type: application/json" \
  --data '{"enabled": false}' \
  "https://gitlab.example.com/api/v4/projects/<project_id>/feature_flags/my_feature"
```

### Проверка инфраструктурных feature flags (self-managed)

```bash
# Список всех feature flags GitLab
gitlab-rake gitlab:feature_flags:list

# Проверка конкретного флага
gitlab-rake gitlab:feature_flags:list | grep builds_queuing

# Включение флага (требует Rails console)
gitlab-rails console
Feature.enable(:gitlab_ci_builds_queuing_metrics)
Feature.enabled?(:gitlab_ci_builds_queuing_metrics)
# → true
```

### Валидация стратегий флагов

```bash
# Проверка стратегий флага
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/feature_flags/my_feature" | \
  jq '.strategies'

# Ожидаемый результат: массив стратегий с параметрами
# [
#   {
#     "name": "default",
#     "parameters": {
#       "rollout": "100"
#     }
#   }
# ]
```

## Лучшие практики

### Безопасность

1.  **Kill Switch по умолчанию**: Каждый release flag должен иметь возможность быстрого отключения.
2.  **Аудит изменений**: Логируйте все изменения флагов через API.
3.  **Least Privilege**: Ограничьте права на изменение production флагов.
4.  **Feature flag management permissions**: Используйте `feature_flag_management_permissions` (GitLab 19.4+) для ограничения прав на управление флагами.

### Организация

1.  **Naming Conventions**: Префиксы `release_`, `ops_`, `experiment_`, `kill_switch_`.
2.  **TTL**: Устанавливайте срок жизни для release флагов.
3.  **Flag Hygiene**: Регулярно очищайте устаревшие флаги.
4.  **Документация**: Каждый флаг должен иметь описание и owner.
5.  **Стратегии**: Используйте User List для внутренних тестов, Percent Rollout для канареечных релизов.

### Производительность

1.  **Кэширование флагов**: Используйте SDK кэширование для снижения latency.
2.  **Graceful Degradation**: Приложение должно работать, если feature flag service недоступен.
3.  **Monitoring**: Отслеживайте usage каждого флага.
4.  **Unleash Proxy**: Для GitLab.com используйте Unleash Proxy для снижения количества запросов к API (deprecated, но единственный совместимый вариант).

### GitLab-specific

1.  **FF_ префиксы**: Используйте `FF_NETWORK_PER_BUILD` для изоляции сетей в docker executor.
2.  **Метрики очереди**: Включайте `gitlab_ci_builds_queuing_metrics` для мониторинга задержек CI/CD.
3.  **Rails console**: Для изменения инфраструктурных флагов используйте `Feature.enable(:flag_name)`.
4.  **Dogfooding**: Используйте feature flags для внутренних тестов новых функций GitLab.

## Особенности и ограничения (Edge Cases)

### Технические лимиты

| Параметр | Лимит | Примечание |
|:---|:---|:---|
| Максимум флагов на проект (Self-Managed) | 200 | Unleash self-hosted |
| Максимум флагов на проект (GitLab.com Free) | 50 | |
| Максимум флагов на проект (GitLab.com Premium) | 150 | |
| Максимум флагов на проект (GitLab.com Ultimate) | 200 | |
| Размер payload | 1 MB | LaunchDarkly |
| TTL | 90 дней | Рекомендуется для release flags |
| Evaluation latency | < 100 ms | Рекомендуемый порог |

### Несовместимость

| Конфликт | Описание | Решение |
|:---|:---|:---|
| Флаг без TTL | Устаревшие флаги накапливаются | Автоматическая очистка через пайплайн |
| Race condition при включении | Флаг включается во время деплоя | Используйте `wait_for_ready` |
| Отсутствие кэша | Высокая latency при каждом запросе | SDK кэширование + fallback |
| Unleash Proxy EOL (2026-11-26) | Замена (Unleash Edge) несовместима с GitLab | Ожидайте обновления GitLab или используйте self-hosted Unleash |
| FF_ флаги Runner'а | Устаревшие флаги удаляются в новых версиях | Проверяйте release notes Runner'а перед обновлением |

## Типичные ошибки и диагностика (Troubleshooting)

| Симптом | Причина | Диагностика | Решение |
|:---|:---|:---|:---|
| Флаг не переключается в UI | SDK кеширует значение | `tcpdump -i any port 8013` — проверить SSE/polling | Переключиться на SSE; проверить `maxAge` |
| Приложение падает при отказе FFaaS | Отсутствие fallback | Остановить платформу → проверить приложение | Каждый `get_boolean_value` требует `default` аргумент |
| Флаги живут месяцами | Нет TTL и cleanup процесса | `rg "is_enabled" src/` — найти старые флаги | Cleanup-PR в Definition of Done; алерт на возраст >14 дней |
| Прод отличается от staging | Дрифт сред | `diff` через API staging и production | Декларативное управление через Git; diff в CI/CD |
| Feature flag management permissions не работает | Флаг не включен | Проверить `feature_flag_management_permissions` в Admin Area | Включить флаг и настроить минимальную роль |
| Метрики очереди не экспортируются | Флаг `gitlab_ci_builds_queuing_metrics` выключен | `gitlab-rake gitlab:feature_flags:list \| grep queuing` | Включить через Rails console |
| Unleash Proxy возвращает 429 | Rate limit на GitLab.com | Увеличить `UNLEASH_FETCH_INTERVAL` или распределить клиенты по разным egress IP |
| Runner игнорирует FF_ флаг | Флаг deprecated или удален | Проверить release notes Runner'а | Обновить Runner или убрать использование флага |
| Флаг доступен всем пользователей | Отсутствие targeting rules | `curl $GITLAB_URL/api/v4/projects/<id>/feature_flags/<flag>` — проверить constraints | Настроить стратегию Percent Rollout или User List |

## Дополнительная информация

*   **[Развертывание и откат](../../Deployment_Strategies/deployment_health_checks_and_rollback.md)** — механизмы автоматизации откатов.
*   **[Canary deployment](../../Deployment_Strategies/canary_deployment.md)** — прогрессивная раскатка.
*   **[Shadow deployment](../../Deployment_Strategies/shadow_deployment.md)** — тёмный запуск.
*   **[Feature Toggles](../../CI-CD/Testing/feature_toggles/)** — типология флагов и стратегии управления.
*   **[GitLab Dogfooding](../../GitLab_CI/Advanced/gitlab_dogfooding.md)** — использование feature flags для внутренних тестов GitLab.
*   **[Мониторинг GitLab CI](../../GitLab_CI/Advanced/monitoring_and_metrics.md)** — метрики очереди, зависящие от feature flags.
*   **[Безопасность GitLab CI](../../GitLab_CI/Advanced/cicd_security_hardening.md)** — аудит feature flags на инстансе.
*   **[OpenFeature](https://openfeature.dev/)** — открытый стандарт для управления флагами.
*   **[Unleash](https://www.getunleash.io/)** — open-source feature flag management.
*   **[LaunchDarkly](https://launchdarkly.com/)** — commercial feature flag platform.
*   **[GitLab Feature Flags Docs](https://docs.gitlab.com/operations/feature_flags/)** — официальная документация.

> **Критичные изменения последних версий:**
>
> *   **19.4**: Введен `feature_flag_management_permissions` флаг для ограничения прав на управление флагами.
> *   **19.0**: Улучшена интеграция с Kubernetes через GitLab Agent (KAS) для динамического управления флагами.
> *   **18.0**: Поддержка OpenFeature SDK в официальных шаблонах.
> *   **17.0**: Встроенные feature flags в GitLab (Ultimate) для управления функциональностью UI.
