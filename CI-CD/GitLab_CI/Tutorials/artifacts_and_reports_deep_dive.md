# Артефакты и отчеты в GitLab CI/CD — глубинное погружение

**Актуально для:** GitLab 18.x / 19.x

> **Примечание:** Полная теория артефактов, кеширования и reports описана в **[Артефакты и кеш](../Advanced/gitlab_ci_caching/gitlab_ci_artifacts.md)** и **[Обзор кэширования](../Advanced/gitlab_ci_caching/caching_overview.md)**. Это руководство фокусируется на production-grade управлении артефактами и отчетами.

## Определения

**Артефакт (Artifact)** — гарантированное хранилище файлов или директорий, сохраняемых после выполнения задачи и передаваемых между стадиями пайплайна или в downstream-проекты. В отличие от кэша, артефакты хранятся на стороне сервера GitLab (или во внутреннем объектном хранилище) и предназначены для данных, которые нельзя потерять.

**Отчет (Report)** — специализированный тип артефакта, который GitLab автоматически парсит и визуализирует в UI: Merge Request (вкладки Tests, Code Quality, Security), Pipeline view. Отчеты — основной механизм интеграции результатов анализа в рабочий процесс разработки.

**dotenv-отчет** — механизм передачи динамических переменных `key=value` между задачами через файл артефакта. Позволяет передавать вычисленные в ранних стадиях значения (версии, теги, метаданные) в задачи последующих стадий без жесткого кодирования.

**Зависимости (Dependencies)** — механизм явного указания задач, артефакты которых должны быть загружены в текущую задачу. Фундаментальный инструмент оптимизации I/O в больших пайплайнах.

Подробнее о терминах и сравнении артефактов с кэшем: **[Артефакты в GitLab CI — глубокое погружение](../Advanced/gitlab_ci_caching/gitlab_ci_artifacts.md)**.

## Основные концепции

### Архитектура передачи артефактов

GitLab Runner запускает каждую задачу в изолированной эфемерной среде. Артефакты решают проблему передачи результатов между задачами через централизованное хранилище:

1. **Архивация (Archive):** После выполнения скриптов Runner упаковывает указанные пути в архив. По умолчанию используется Zip; для ускорения в GitLab Runner 16.2+ применяется Zstd через `FF_USE_FASTZIP`.
2. **Загрузка (Upload):** Архив передается на сервер GitLab или во внутреннее объектное хранилище (S3-совместимое: MinIO, Ceph RGW).
3. **Восстановление (Restore):** В задачах последующих стадий Runner скачивает архив и распаковывает его в рабочую директорию.

По умолчанию загружаются артефакты **всех** предыдущих стадий. Для оптимизации используются директивы `needs` и `dependencies`.

### Ключевые параметры конфигурации

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `paths` | Файлы и директории для сохранения. Относительно корня проекта. | `paths: [dist/, build/libs/*.jar]` |
| `exclude` | Исключения (glob). | `exclude: ["**/*.map", "dist/**/*.test.js"]` |
| `expire_in` | Срок хранения. Формат: `1 hour`, `7 days`, `30 days`, `never`. | `expire_in: 1 week` |
| `name` | Имя архива для UI. Поддерживает переменные. | `name: "$CI_JOB_NAME-$CI_COMMIT_SHORT_SHA"` |
| `when` | Условие: `on_success`, `on_failure`, `always`. | `when: always` |
| `reports` | Отчеты для парсинга GitLab. | `reports: {junit: report.xml}` |
| `public` | `false` — только участники проекта. | `public: false` |
| `untracked` | Включать неотслеживаемые Git файлы. | `untracked: false` |

### Отчеты через артефакты

GitLab автоматически парсит файлы отчетов и визуализирует их в UI:

- `junit` — тесты (вкладка Tests в MR)
- `coverage_report` — покрытие кода (Cobertura)
- `cyclonedx` — SBOM (Software Bill of Materials)
- `codequality` — анализ кода (SARIF/Code Climate)
- `dotenv` — переменные окружения для последующих задач
- `terraform` — планы Terraform в MR
- `sast`, `dast`, `secret_detection` — Security Dashboard

### Взаимодействие `needs`, `dependencies` и артефактов

| Директива | Что управляет | Когда применяется |
| :--- | :--- | :--- |
| `needs` | Порядок запуска + загрузка артефактов | DAG-оркестрация |
| `dependencies` | Только загрузка артефактов | Явное указание источников |

Если используются обе директивы, они работают независимо. Для отключения загрузки артефактов от задачи в `needs` используйте `artifacts: false` (GitLab 12.2+).

## Предварительные требования

- **GitLab:** Версия 18.x+ (полная поддержка всех типов отчетов, Zero Trust Allowlist).
- **GitLab Runner:** Версия 19.x+ (Zstd, `FF_USE_FASTZIP`, конкурентная упаковка).
- **Сетевой доступ:** Runner → API GitLab (порты 80/443) и Object Storage.
- **Хранилище:** Настроенное Object Storage (MinIO, Ceph RGW) для долгосрочного хранения в self-hosted окружениях. Локальные диски GitLab также поддерживаются.
- **Безопасность:** Для межпроектных артефактов — настройка Inbound Allowlist (GitLab 17.0+).
- **Синхронизация времени (NTP):** Требуется для корректной работы подписей и логов.
- **Дисковое пространство Runner'а:** Минимум 2x от ожидаемого размера архива для распаковки.

## Практические сценарии

### Сценарий 1: Полный pipeline с артефактами и отчетами

```yaml
stages:
  - build
  - test
  - security
  - deploy

variables:
  IMAGE_TAG: $CI_COMMIT_SHORT_SHA

build:
  stage: build
  image: docker:29
  services:
    - docker:29-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$IMAGE_TAG .
    - docker push $CI_REGISTRY_IMAGE:$IMAGE_TAG
  artifacts:
    paths:
      - docker-image.tar
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

test:
  stage: test
  image: python:3.13-slim
  script:
    - pytest tests/ --junitxml=report.xml --cov=src --cov-report=xml:coverage.xml
  artifacts:
    paths:
      - report.xml
      - coverage.xml
    reports:
      junit: report.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    expire_in: 30 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

lint:
  stage: test
  image: node:22-slim
  script:
    - npm install
    - npm run lint -- --format json --output-file eslint-report.json
  artifacts:
    paths:
      - eslint-report.json
    reports:
      codequality: eslint-report.json
    expire_in: 30 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

security:
  stage: security
  image: aquasec/trivy:0.74.0
  script:
    - trivy image --format cyclonedx --output sbom.json $CI_REGISTRY_IMAGE:$IMAGE_TAG
  artifacts:
    paths:
      - sbom.json
    reports:
      cyclonedx: sbom.json
    expire_in: 90 days
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$IMAGE_TAG
  environment:
    name: production
    url: https://example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 2: Dotenv для передачи переменных между задачами

```yaml
stages:
  - build
  - deploy

build:
  stage: build
  image: docker:29
  services:
    - docker:29-dind
  script:
    - echo "IMAGE_TAG=$CI_COMMIT_SHORT_SHA" > build.env
    - echo "BUILD_DATE=$(date -Iseconds)" >> build.env
    - echo "BUILD_STATUS=success" >> build.env
  artifacts:
    reports:
      dotenv: build.env
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - echo "Deploying image $IMAGE_TAG built on $BUILD_DATE"
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$IMAGE_TAG \
        --set build.date=$BUILD_DATE \
        --set build.status=$BUILD_STATUS
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 3: Покрытие кода с отображением в MR

```yaml
stages:
  - test

test:
  stage: test
  image: python:3.13-slim
  script:
    - pip install pytest pytest-cov
    - pytest tests/ \
        --junitxml=report.xml \
        --cov=src \
        --cov-report=xml:coverage.xml \
        --cov-report=html:htmlcov
  artifacts:
    paths:
      - report.xml
      - coverage.xml
      - htmlcov/
    reports:
      junit: report.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    expire_in: 30 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Сценарий 4: Артефакты между стадиями с `needs`

```yaml
stages:
  - build
  - test
  - deploy

build:
  stage: build
  image: docker:29
  services:
    - docker:29-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  artifacts:
    paths:
      - image-manifest.json
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

test:
  stage: test
  image: aquasec/trivy:0.74.0
  needs: ["build"]
  script:
    - trivy image --format json --output report.json $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  artifacts:
    paths:
      - report.json
    reports:
      container_scanning: report.json
    expire_in: 30 days
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  needs: ["test"]
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 5: Очистка артефактов

```yaml
cleanup_artifacts:
  stage: deploy
  image: curlimages/curl:8.21.0
  script:
    - |
      # Получение списка артефактов старше 30 дней
      curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/jobs?scope=success&per_page=100" | \
        jq -r '.[] | select(.artifacts_expire_at < "'$(date -I)'") | .id' | \
        while read job_id; do
          echo "Deleting artifacts for job $job_id"
          curl --request DELETE --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
            "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/jobs/$job_id/artifacts"
        done
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      cron: "0 2 * * 0"  # Еженедельно в воскресенье в 02:00
  allow_failure: true
```

## Валидация и проверка

1. **Artifacts UI:** Проверьте **CI/CD > Jobs > <job-name> > Artifacts** — должны отображаться все файлы.
2. **Reports UI:** В Merge Request проверьте вкладки **Tests**, **Code Quality**, **Security** — должны отображаться отчеты.
3. **Coverage:** Проверьте **CI/CD > Pipelines > Coverage** — должен отображаться график покрытия.
4. **Expire:** Проверьте `artifacts_expire_at` в API — должен соответствовать `expire_in`.
5. **Dotenv:** В задаче-потребителе проверьте переменные — должны быть доступны.
6. **Dependencies:** В логах Runner'а проверьте строки `Downloading artifacts` — убедитесь, что загружаются только нужные артефакты.

## Troubleshooting

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Artifacts not found** | Задача-потребитель не указана в `needs` или `dependencies` | Добавьте `needs: ["build"]` или явно укажите `dependencies` |
| **Dotenv not working** | Задача-потребитель не в `needs` или файл > 5 KB | Dotenv работает только между задачами в `needs`; проверьте размер файла (лимит 5 KB) |
| **JUnit report not showing** | Неверный путь или формат | Проверьте путь к файлу и формат JUnit XML |
| **Coverage not calculated** | Отсутствует `coverage` в `.gitlab-ci.yml` | Добавьте `coverage: '/TOTAL\s+\d+/'` или аналогичный regex |
| **Artifacts too large** | Превышен лимит GitLab | Уменьшите размер артефактов или используйте External Artifacts / Package Registry |
| **Reports not showing in MR** | Отсутствуют artifacts reports | Проверьте, что задача создает reports artifacts в правильном формате |
| **Artifacts not deleted** | Активна опция `keep_latest` | Отключите "Keep artifacts from most recent successful jobs" в настройках CI/CD |
| **Artifacts перезаписаны** | Конкурентные задачи с одинаковым `name` | Используйте уникальные имена архивов (`name: "$CI_JOB_NAME-$CI_NODE_INDEX"`) |

## Лучшие практики (Best Practices)

**Безопасность:**
- Никогда не храните секреты в артефактах — используйте защищенные переменные.
- Устанавливайте `expire_in` для всех артефактов.
- Используйте `artifacts:when: always` только для логирования ошибок.
- Ограничьте размер артефактов (`artifacts:untracked: false`).
- Для артефактов с конфиденциальными данными используйте отдельные проекты с `public: false`.

**Производительность:**
- Используйте `dependencies: []` для задач, которые не используют результаты сборки (линтеры).
- Используйте `needs: [{job: build, artifacts: false}]` когда нужен только статус, а не артефакты.
- Сжимайте большие артефакты (gzip, zip).
- Используйте `FF_USE_FASTZIP: "true"` и `ARTIFACT_COMPRESSION_LEVEL: "fast"` для ускорения.
- Для файлов >1 GB используйте Package Registry или External Artifacts.

**Надёжность:**
- Всегда указывайте `expire_in` для артефактов.
- Используйте `artifacts:reports` для автоматического отображения в UI.
- Документируйте структуру артефактов в README.
- Используйте `needs` вместо `dependencies` для независимых задач.
- Настройте автоматическую очистку устаревших артефактов.
- Для критичных задач используйте `interruptible: false`, чтобы артефакты не потерялись при `auto_cancel`.

## Ограничения и граничные случаи

- **dotenv размер:** Максимальный размер файла — 5 KB, максимум 20 переменных (GitLab 17.1+). Настраивается в Admin Area > CI/CD > CI/CD limits.
- **dotenv и matrix:** Переменные из `dotenv` не работают между инстансами матричных сборок (`parallel:matrix`). Для передачи данных между матричными задачами используйте файловые артефакты или API.
- **dotenv и rules:** Переменные из `dotenv` недоступны в блоке `rules` — они вычисляются после парсинга конфигурации.
- **Matrix builds:** При `parallel:matrix` используйте уникальные имена артефактов (`name` с переменными матрицы), иначе артефакты перезапишутся.
- **Cross-project:** Для `needs:project` требуется настройка Inbound Allowlist (Zero Trust, GitLab 17.0+). Без этого возвращается `403 Forbidden`.
- **Large artifacts (>1 GB):** Таймауты обратного прокси — увеличьте `proxy_read_timeout` и `client_max_body_size`. Недостаточно памяти на Runner'е — увеличьте RAM или используйте `ARTIFACT_COMPRESSION_LEVEL: "fastest"`.
- **extends:** Блок `artifacts` при `extends` перезаписывается целиком. Если дочерняя задача переопределяет только `paths`, остальные параметры (`expire_in`, `when`, `reports`) будут утеряны.
- **interruptible:** Артефакты не сохраняются при прерванной задаче (`auto_cancel`). Используйте `interruptible: false` для критичных задач.

## Очистка

```bash
# Пакетное удаление артефактов старше 30 дней
glab api projects/$PROJECT_ID/jobs?per_page=100 | jq -r '.[] | select(.artifacts_expire_at < "'$(date -I)'") | .id' | \
  xargs -I {} glab api projects/$PROJECT_ID/jobs/{} -X DELETE

# Очистка кеша
glab api projects/$PROJECT_ID/cache | jq -r '.[].key' | \
  xargs -I {} glab api projects/$PROJECT_ID/cache/{} -X DELETE
```

## Дополнительная информация

### Смотрите также

- **[Артефакты и кеш — полное руководство](../Advanced/gitlab_ci_caching/gitlab_ci_artifacts.md)** — теория, все типы артефактов
- **[Обзор кэширования](../Advanced/gitlab_ci_caching/caching_overview.md)** — стратегии кеширования
- **[Программная автоматизация: API и Webhooks](../Advanced/api_and_webhooks_automation.md)** — управление артефактами через API
- **[Управление артефактами](../../artifact_management.md)** — общий обзор управления артефактами в CI/CD
