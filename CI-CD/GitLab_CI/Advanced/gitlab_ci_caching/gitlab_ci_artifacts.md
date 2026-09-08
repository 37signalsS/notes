# Артефакты в GitLab CI — глубокое погружение

## Определения

**Артефакт (Artifact)** — гарантированное хранилище файлов или директорий, которые сохраняются после выполнения задачи (job) и передаются между стадиями пайплайна. В отличие от кэша, артефакты передаются на сторону сервера GitLab (или во внешнее объектное хранилище) и обладают высокой степенью надежности. Артефакты предназначены для доставки результатов сборки, которые нельзя потерять.

**Отчет (Report)** — специализированный тип артефакта, который GitLab автоматически парсит и визуализирует в интерфейсе (Merge Request, вкладка Tests, секция Security). Современные пайплайны используют отчеты для генерации **SBOM (Software Bill of Materials)** и **аттестаций SLSA**, критически важных для безопасности цепочки поставок (Supply Chain Security).

**Зависимости (Dependencies)** — механизм явного указания задач, артефакты которых должны быть загружены в текущую задачу. Это фундаментальный инструмент оптимизации I/O, позволяющий избежать скачивания лишних гигабайт данных в эфемерную среду Runner'а.

**Аннотации (Annotations)** — (GitLab 16.11+) Механизм добавления структурированных метаданных (JSON) к артефактам для отображения кастомной информации и ссылок непосредственно в UI GitLab.

Подробное сравнение с механизмом кэширования: **[Обзор кэширования](./caching_overview.md)**.

## Предварительные требования (Prerequisites)

Для полноценной работы с артефактами в 2026 году необходимо:
- **GitLab Runner:** Версия 16.2+ (для поддержки Zstd и расширенных типов отчетов).
- **Сетевой доступ:** Runner должен иметь доступ к API GitLab (или S3 при использовании Direct Upload) по портам 80/443.
- **Хранилище:** Наличие настроенного Object Storage (S3/GCS/Azure) на стороне сервера GitLab для долгосрочного хранения.
- **Безопасность:** Для межпроектных артефактов проект-источник должен быть добавлен в **Inbound Allowlist** (Zero Trust модель, GitLab 17.0+).

## Основные концепции

### Эфемерность среды и архитектура передачи данных

GitLab Runner запускает каждую задачу в изолированной среде. Артефакты решают проблему передачи данных между задачами через централизованное хранилище:

1. **Архивация (Archive):** После выполнения скриптов Runner упаковывает указанные пути в `.zip` архив. 
   - **Оптимизация (Zstd):** В современных Runner'ах используется алгоритм **Zstd**, который в 3-5 раз быстрее распаковывает данные по сравнению с Zip.
   - **Конкурентность:** Переменная `FF_USE_FASTZIP: "true"` включает многопоточную упаковку, используя все доступные ядра CPU.
2. **Загрузка (Upload):** Архив передается на сервер GitLab.
   - **Direct Upload:** В современных инсталляциях Runner может загружать файлы напрямую в S3, минуя GitLab Rails, что снижает нагрузку на основной сервер и ускоряет процесс.
3. **Восстановление (Restore):** В задачах последующих стадий Runner скачивает архив и распаковывает его в рабочую директорию. По умолчанию загружаются артефакты **всех** предыдущих стадий.

### Пример: Передача бинарного файла между стадиями

```yaml
# Пример: Передача бинарного файла между стадиями
build_app:
  stage: build
  script:
    - go build -o app main.go
  artifacts:
    paths:
      - app
    expire_in: 1 hour

test_app:
  stage: test
  script:
    - ./app --version  # Файл 'app' доступен благодаря артефактам
```

По умолчанию артефакты задачи доступны **во всех задачах последующих стадий** того же пайплайна. Для передачи артефактов между разными пайплайнами (downstream pipelines) используются механизмы **[multi-project pipelines](../Downstream_Pipelines/multi_project_pipelines.md)** (требует настройки Zero Trust Allowlist в 17.0+).

### Ключевые параметры конфигурации

| Параметр | Описание и технические нюансы | Пример |
| :--- | :--- | :--- |
| `paths` | Список файлов и директорий для сохранения. Пути должны быть относительны корню проекта. | `paths: [bin/, dist/*.jar]` |
| `exclude` | Файлы, которые НЕ нужно включать в артефакты (поддерживает glob). | `exclude: ["**/*.log"]` |
| `expire_in` | Срок хранения (по умолчанию 30 дней). `never` отключает автоматическое удаление. | `expire_in: 1 week` |
| `name` | Имя архива для скачивания через UI. Поддерживает переменные. | `name: "$CI_JOB_NAME"` |
| `when` | Условие сохранения (`on_success`, `on_failure`, `always`). | `when: always` |
| `reports` | Специальные отчеты для визуализации (junit, cyclonedx, sast). | `reports: {junit: test.xml}` |
| `public` | Если `false`, артефакты доступны только участникам проекта (Project Members). | `public: false` |
| `untracked` | Включать все файлы, добавленные в рабочую директорию, но не отслеживаемые Git. | `untracked: true` |
| `annotations` | (GitLab 16.11+) Добавление кастомных метаданных в формате JSON для визуализации. | `annotations: [meta.json]` |

### Управление зависимостями и производительность

По умолчанию каждая задача скачивает артефакты **всех** задач предыдущих стадий. В больших проектах это может приводить к значительному замедлению из-за загрузки сотен мегабайт ненужных данных.

#### Взаимодействие `needs`, `dependencies` и артефактов

Директивы `needs` и `dependencies` управляют артефактами **независимо друг от друга**:

| Директива | Что управляет | Когда применяется |
| :--- | :--- | :--- |
| `needs` | Порядок запуска + загрузка артефактов от указанных задач | DAG-оркестрация |
| `dependencies` | Только загрузка артефактов (без влияния на порядок) | Явное указание источников |

**Критический нюанс:** Если используются обе директивы одновременно, они работают независимо. Задача может запускаться через `needs` (ожидая build), но загружать артефакты через `dependencies` от другой задачи (теста):

```yaml
deploy:
  stage: deploy
  needs: ["build"]          # Ждет завершения build для запуска
  dependencies: ["test"]    # Загружает артефакты от test, а не от build
  script: ./deploy.sh
```

#### Оптимизация через `dependencies`
- **`dependencies: []`** — отключает загрузку любых артефактов в задачу. Полезно для задач, которые не используют результаты сборки (линтеры, проверка формата).
- **`dependencies: [build_job]`** — загружает артефакты только из указанных задач. Позволяет выбрать конкретные источники данных.

#### Оптимизация через `needs`
- **`needs` (DAG)** — если используется `needs`, GitLab автоматически загружает артефакты только от задач, перечисленных в блоке `needs`. Если нужны артефакты от других задач (из предыдущих стадий, но не в `needs`), необходимо явно указать их в `dependencies`.
- **`needs: [{job: build, artifacts: false}]`** (GitLab 12.2+) — отключает загрузку артефактов от конкретной задачи в `needs`. Задача будет ожидать завершения указанной задачи, но не будет скачивать её артефакты. Это экономит время на скачивание, когда важен только статус выполнения (например, задача деплоя ожидает успешного тестирования, но не нуждается в результатах тестов).

```yaml
# Пример: деплой ожидает тесты, но не скачивает их результаты
deploy_production:
  stage: deploy
  needs:
    - job: build
      artifacts: true    # Нужны бинарные файлы сборки
    - job: integration_test
      artifacts: false   # Интересен только статус (success/failed)
  script: ./deploy.sh
```

#### Сжатие и флаги ускорения
Для ускорения работы с артефактами (особенно в GitLab 16.x/17.x+) рекомендуется использовать следующие переменные:

```yaml
variables:
  FF_USE_FASTZIP: "true"             # Включает быстрый конкурентный zip
  ARTIFACT_COMPRESSION_LEVEL: "fast"  # Уровни: fastest, fast, default, slow, slowest
```

### Кросс-проектные артефакты и Zero Trust (17.0+)

В современных версиях GitLab безопасность межпроектных взаимодействий строится на модели **Zero Trust**.

**Inbound Allowlist (Обязательно):**
Для того чтобы задача в Проекте А могла скачать артефакты из Проекта Б (через `needs:project`), Проект Б должен явно разрешить доступ Проекту А в своих настройках:
1. Перейдите в **Settings > CI/CD**.
2. Разверните секцию **Job Token Permissions**.
3. Добавьте целевой проект в **Inbound Allowlist**.

Без этой настройки любая попытка доступа к артефактам через `CI_JOB_TOKEN` будет отклонена с ошибкой 403.

### Отчеты через артефакты

Отчеты (`reports`) — это специализированный механизм интеграции данных в UI GitLab. В отличие от обычных `paths`, файлы отчетов парсятся сервером GitLab и визуализируются в Merge Request, секции Security и на вкладке Pipeline.

```yaml
test:
  stage: test
  script:
    - pytest --junitxml=test-results.xml --cov=app --cov-report=xml
    - trivy fs --format cyclonedx --output sbom.json .
  artifacts:
    reports:
      junit: test-results.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
      cyclonedx: sbom.json  # Генерация SBOM для SLSA-комплаенса
```

**Основные типы отчетов (2026):**
- `junit` — результаты тестирования. Отображаются в MR и на вкладке **Tests**.
- `coverage_report` — покрытие кода. Позволяет видеть процент в MR и аннотации в диффе.
- `cyclonedx` — (GitLab 15.0+) Ведомость ПО (SBOM) в формате CycloneDX. Необходима для инвентаризации зависимостей.
- `codequality` — анализ качества кода (Lint/SARIF).
- `dotenv` — динамические переменные окружения для последующих задач.
- `terraform` — планы и результаты выполнения Terraform в MR.
- `sast`, `dast`, `secret_detection` — отчеты безопасности для Security Dashboard.
- `requirements` — отчеты о соответствии требованиям (для Python/Ruby).
- `annotations` — (GitLab 16.11+) JSON-метаданные для кастомной визуализации в UI.

#### Dotenv-отчёт: передача динамических переменных

Механизм `dotenv` позволяет передавать вычисленные переменные из одной задачи в последующие. Это критично для сценариев, где версия или метаданные генерируются динамически.

```yaml
generate_version:
  stage: prepare
  script:
    - VERSION=$(date +%Y%m%d)-${CI_COMMIT_SHORT_SHA}
    - echo "VERSION=$VERSION" >> build.env
    - echo "BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> build.env
    - echo "DOCKER_IMAGE=${CI_REGISTRY_IMAGE}:${VERSION}" >> build.env
  artifacts:
    reports:
      dotenv: build.env

build_app:
  stage: build
  needs: [generate_version]
  script:
    - echo "Building version $VERSION"
    - docker build --build-arg VERSION=$VERSION -t ${DOCKER_IMAGE} .

deploy:
  stage: deploy
  needs: [build_app, generate_version]
  script:
    - echo "Deploying $VERSION (built on $BUILD_DATE)"
    - ./deploy.sh $DOCKER_IMAGE
```

**Ограничения dotenv (GitLab 17.1+):**

| Параметр | Значение по умолчанию | Настраивается в |
| :--- | :--- | :--- |
| Максимальный размер файла | 5 KB | Admin Area > CI/CD > CI/CD limits |
| Максимальное количество переменных | 20 | Admin Area > CI/CD > CI/CD limits |

**Важные нюансы:**
- Переменные из `dotenv` **недоступны** в блоке `rules` — они вычисляются после парсинга конфигурации.
- `dotenv` переменные **не работают** между инстансами матричных сборок (`parallel:matrix`). Для передачи данных между матричными задачами используйте API или файловые артефакты.
- Переменные доступны только в задачах, перечисленных в `needs` или следующих стадий (без `needs`).

### Срок хранения и лимиты

Срок хранения задается параметром `expire_in`. Формат: `<число> <единица>` (`1 hour`, `7 days`, `30 days`) или `never` (бессрочно).

| Значение | Когда использовать |
| :--- | :--- |
| `1 week` | Временные артефакты (промежуточные сборки, логи) |
| `30 days` | По умолчанию (баланс между доступностью и местом в хранилище) |
| `never` | Релизные артефакты, которые не должны удаляться автоматически |

#### Лимиты размеров артефактов

Размер артефактов ограничивается на нескольких уровнях. При конфликтных настройках применяется **наименьшее** значение.

| Уровень | Где настраивается | Параметр | Значение по умолчанию |
| :--- | :--- | :--- | :--- |
| **Instance** | Admin Area > CI/CD > CI/CD limits | Maximum artifacts size | 100 MB |
| **Group** | Group > Settings > CI/CD > Continuous Integration | Maximum artifacts size | Наследует instance |
| **Project** | Project > Settings > CI/CD > Continuous Integration | Maximum artifacts size | Наследует group |

**Отдельные лимиты для специфических типов отчетов:**

| Тип отчёта | Лимит | Примечание |
| :--- | :--- | :--- |
| `dotenv` | 5 KB / 20 переменных | Настраивается в Admin Area (GitLab 17.1+) |
| `cyclonedx` (SBOM) | Нет ограничения по умолчанию | Рекомендуется < 50 MB для производительности UI |
| `junit` | Нет ограничения | Но большие файлы замедляют отображение MR |
| `terraform` | Нет ограничения | Рекомендуется использовать `expire_in` для планов |

**Диагностика превышения лимита:**
При ошибке `413 Request Entity Too Large` или `Artifacts too large`:

```bash
# Проверка размера директории перед архивацией
du -sh dist/ build/ reports/

# Поиск крупных файлов
find . -type f -size +10M -exec ls -lh {} \;

# Просмотр лимитов через API (требует admin-доступ)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/application/settings" | \
  jq '.artifacts_size_limit, .ci_max_artifact_size'
```

**Решения при превышении лимита:**
1. Используйте `exclude` для исключения ненужных файлов (source maps, логи, временные данные).
2. Разбейте артефакты на несколько задач с `artifacts` в каждой.
3. Для крупных бинарников публикуйте их в Package Registry вместо CI artifacts.
4. Администратор может увеличить лимит в Admin Area, но это увеличивает потребление хранилища.

**Жизненный цикл и `keep_latest`:**
По умолчанию в GitLab включена настройка "Keep artifacts from most recent successful jobs" (сохранять артефакты последних успешных задач). Это означает, что артефакты последнего успешного пайплайна в ветке **не будут удалены**, даже если их срок `expire_in` истек. Это часто является причиной неожиданного роста потребления дискового пространства.

**Управление `keep_latest`:**
- Настройка доступна в **Admin Area > CI/CD > Continuous Integration > Continuous Integration and Deployment**.
- Параметр `Keep artifacts from most recent successful jobs` (по умолчанию: включено).
- Для project/group-level управления используйте **Settings > CI/CD > Artifacts** (GitLab Premium+).

## Практические сценарии

### Сценарий 1: Передача временных артефактов

`build` стадия создает артефакт, `test` стадия его использует:

```yaml
stages:
  - build
  - test

build:
  stage: build
  script:
    - ./gradlew clean build
    - mkdir -p dist && cp build/libs/app.jar dist/app-1.2.3-${CI_COMMIT_SHORT_SHA}.jar
    - sha256sum dist/* > dist/checksums.txt
  artifacts:
    paths:
      - dist/
    expire_in: 7 days

release:
  stage: release
  script: make release
  artifacts:
    paths: [release/*.tar.gz]
    expire_in: never
```

### Сценарий 2: Отчёты о тестах и покрытии

```yaml
test:
  stage: test
  script:
    - pytest --junitxml=test-results.xml --cov=app --cov-report=xml
  artifacts:
    paths:
      - test-results/
    reports:
      junit: test-results.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    expire_in: 1 week
```

### Сценарий 3: Комбинация кэша и артефактов

Кэш ускоряет установку зависимостей, артефакты передают результаты сборки — подробнее см. в документе: **[Практические сценарии кэширования](./cache_scenarios.md)**.

### Сценарий 4: Отладка — сохранение логов при падении задачи

Артефакты полезны не только для передачи файлов между задачами, но и для отладки. Если задача завершается с ошибкой, логи приложения могут помочь в диагностике, даже если они не попали в стандартный вывод (stdout).

```yaml
integration_test:
  stage: test
  script:
    - ./run_tests.sh --log-file=test-debug.log 2>&1
  artifacts:
    paths:
      - test-debug.log
    expire_in: 3 days
    when: always  # Сохранять артефакты независимо от результата задачи
```

Ключевой параметр `when: always` гарантирует, что артефакты будут сохранены даже при failed-задаче. Это позволяет скачать и проанализировать логи после сбоя через интерфейс GitLab (кнопка **Job Artifacts** на странице задачи).

### Сценарий 5: Динамические переменные через dotenv

Передача вычисленной версии между задачами без жесткой привязки к хардкоду:

```yaml
stages:
  - prepare
  - build
  - deploy

generate_version:
  stage: prepare
  script:
    - VERSION=$(date +%Y%m%d)-${CI_COMMIT_SHORT_SHA}
    - echo "VERSION=$VERSION" >> build.env
    - echo "BUILD_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> build.env
  artifacts:
    reports:
      dotenv: build.env

build_app:
  stage: build
  needs: [generate_version]
  script:
    - make build VERSION=$VERSION
    - docker build -t ${CI_REGISTRY_IMAGE}:$VERSION .
    - docker push ${CI_REGISTRY_IMAGE}:$VERSION

deploy_staging:
  stage: deploy
  needs: [build_app, generate_version]
  script:
    - helm upgrade --install myapp ./chart --set image.tag=$VERSION
  environment:
    name: staging

deploy_production:
  stage: deploy
  needs: [build_app, generate_version]
  script:
    - helm upgrade --install myapp ./chart --set image.tag=$VERSION
  environment:
    name: production
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 6: Terraform plan/apply с артефактами

Передача плана Terraform между задачами плана и применения. План сохраняется как артефакт и применяется только вручную:

```yaml
stages:
  - plan
  - apply

terraform:plan:
  stage: plan
  script:
    - cd terraform/environments/prod
    - terraform init -backend=true
    - terraform plan -out=tfplan -input=false
    - terraform show -json tfplan > tfplan.json
  artifacts:
    paths:
      - terraform/environments/prod/tfplan
      - terraform/environments/prod/tfplan.json
    reports:
      terraform: tfplan.json
    expire_in: 1 week
  rules:
    - changes:
        - terraform/**/*.tf

terraform:apply:
  stage: apply
  needs: ["terraform:plan"]
  script:
    - cd terraform/environments/prod
    - terraform init -backend=true
    - terraform apply -auto-approve tfplan
  dependencies:
    - terraform:plan
  when: manual
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Важно:** Параметр `reports: terraform` в `terraform:plan` позволяет отобразить план Terraform непосредственно в Merge Request, что упрощает ревью инфраструктурных изменений.

### Сценарий 7: Кросс-проектные артефакты через needs:project

Загрузка артефактов из другого проекта в рамках одного пайплайна. Требует настройки Zero Trust (Inbound Allowlist):

```yaml
integration_test:
  stage: test
  needs:
    - project: "my-group/backend-api"
      job: "build_binary"
      ref: "main"
      artifacts: true
    - project: "my-group/frontend-app"
      job: "build_assets"
      ref: "main"
      artifacts: true
  script:
    - ls backend-api/  # Бинарный файл из backend
    - ls frontend-app/ # Собранные статики из frontend
    - ./run-integration.sh
```

**Настройка Zero Trust (обязательно):**
1. В проекте-источнике: **Settings > CI/CD > Job Token Permissions**.
2. Добавьте проект-получатель в **Inbound Allowlist**.
3. Без этой настройки запрос будет отклонен с ошибкой 403.

### Сценарий 8: Исключение файлов через exclude

Контроль состава артефактов для уменьшения размера архива:

```yaml
build:
  stage: build
  script:
    - npm run build
    - npm run test -- --coverage
  artifacts:
    paths:
      - dist/
      - coverage/
      - "*.log"
    exclude:
      - dist/**/*.map
      - dist/**/*.test.js
      - coverage/tmp/
      - "*.log"  # Логи включены в paths, но exclude их убирает
    expire_in: 7 days
```

### Сценарий 9: Переопределение артефактов через extends

При использовании `extends` блок `artifacts` **перезаписывается** целиком (не сливается). Если дочерняя задача переопределяет только `paths`, остальные параметры (`expire_in`, `when`, `reports`) будут утеряны:

```yaml
.base_build:
  artifacts:
    paths: [dist/]
    expire_in: 7 days
    when: on_success

# ПРАВИЛЬНО: переопределяем весь блок artifacts
build_beta:
  extends: .base_build
  artifacts:
    paths: [dist-beta/]
    expire_in: 3 days
    when: always

# НЕПРАВИЛЬНО: потеряется expire_in и when
build_gamma:
  extends: .base_build
  artifacts:
    paths: [dist-gamma/]  # expire_in и when будут утеряны!
```

### Взаимодействие с `interruptible`

Артефакты **не сохраняются** при прерванной задаче (если `auto_cancel` отменил пайплайн). Для критических задач используйте `interruptible: false`:

```yaml
deploy_production:
  stage: deploy
  interruptible: false  # Защита от отмены auto_cancel
  script:
    - ./deploy.sh
  artifacts:
    paths:
      - deploy.log
    when: always
    expire_in: 30 days
```

Если артефакт критичен для прерываемой задачи, используйте `artifacts: when: always` — это гарантирует сохранение даже при падении, но не при отмене задачи через `auto_cancel`.

## Дополнительная информация

### Диагностика и устранение неполадок (Troubleshooting)

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Artifacts not found` | Неверный путь или `when` политика | Проверьте, что пути в `paths` относительны корню проекта. Используйте `when: always` для отладочных артефактов. |
| `413 Request Entity Too Large` | Размер архива превышает лимит сервера | Увеличьте лимит в Admin Area или используйте `exclude` для удаления мусора. Проверьте лимиты instance/group/project. |
| `403 Forbidden` в `needs:project` | Не настроен Zero Trust Allowlist | Добавьте проект-получатель в Job Token Authorized Projects (Settings > CI/CD > Job Token Permissions). |
| Медленный Upload/Download | Проблемы с CPU или сетью | Включите `FF_USE_FASTZIP: "true"` и `ARTIFACT_COMPRESSION_LEVEL: "fast"`. Проверьте Zstd-сжатие. |
| Артефакты не удаляются | Активна опция `keep_latest` | Отключите "Keep artifacts from most recent successful jobs" в настройках CI/CD. |
| Артефакты перезаписываются | Конкурентные задачи с одинаковым `name` | Используйте уникальные имена архивов (`name: "$CI_JOB_NAME-$CI_NODE_INDEX"`). |
| `dotenv` переменные не видны | Задача не в `needs` или в `rules` | Проверьте, что потребитель указан в `needs`. Переменные из `dotenv` недоступны в `rules`. |
| Артефакты потеряны при `extends` | Частичное переопределение блока `artifacts` | Переопределяйте весь блок `artifacts` целиком, не только отдельные ключи. |
| Артефакты не загружаются из кэша | Используется `cache` вместо `artifacts` | Различайте: `cache` — best-effort для зависимостей, `artifacts` — гарантированная передача результатов. |
| Ошибка `zstd: not found` | Старый Runner или ОС без zstd | Обновите Runner до 16.2+ или установите пакет `zstd` в базовый образ. |

### Управление хранилищем артефактов на self-managed инстансах

Для self-managed GitLab критически важно управлять потреблением хранилища артефактов:

**Рекомендации по настройке retention:**

```bash
# Просмотр текущих настроек через API (требует admin-доступ)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/application/settings" | \
  jq '.artifact_expired_before, .keep_latest_artifact, .artifacts_path'

# Настройка автоматической очистки через API
curl --request PUT --header "PRIVATE-TOKEN: $TOKEN" \
  --data "keep_latest_artifact=5" \
  "https://gitlab.example.com/api/v4/application/settings"
```

**Оптимизация Object Storage (S3/MinIO):**
- Настройте **Lifecycle Policies** для автоматического удаления старых объектов.
- Используйте **Storage Class** (S3 Standard → S3 Infrequent Access) для редко запрашиваемых артефактов.
- Включите **Server-Side Encryption** для артефактов, содержащих конфиденциальные данные.

**Мониторинг потребления:**

```bash
# Просмотр размера артефактов проекта через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID" | \
  jq '.statistics.build_artifacts_size'

# Топ-10 проектов по размеру артефактов (admin API)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects?order_by=build_artifacts_size&sort=desc&per_page=10" | \
  jq '.[] | {name: .name, size: .statistics.build_artifacts_size}'
```

### API взаимодействие с артефактами

GitLab предоставляет REST API для работы с артефактами, что позволяет автоматизировать скачивание, просмотр и управление:

```bash
# Скачивание артефактов задачи по ID
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --location \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$JOB_ID/artifacts" \
  --output artifacts.zip

# Скачивание артефактов по имени задачи и ветке
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --location \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/artifacts/main/download?job=build"

# Скачивание конкретного файла из артефактов
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/artifacts/main/raw/dist/index.html?job=build" \
  --output index.html

# Просмотр списка артефактов проекта
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$JOB_ID/artifacts" | \
  jq '.[] | {id, job_id, created_at, expire_at}'

# Удаление артефактов конкретной задачи
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$JOB_ID/artifacts"

# Скачивание артефактов из кросс-проектного пайплайна (CI_JOB_TOKEN)
curl --header "JOB-TOKEN: $CI_JOB_TOKEN" \
  --location \
  "https://gitlab.example.com/api/v4/projects/$SOURCE_PROJECT_ID/jobs/$SOURCE_JOB_ID/artifacts" \
  --output cross-project-artifacts.zip
```

**Примечание:** При использовании `curl` для скачивания с GitLab.com добавляйте флаг `--location` для обработки редиректов через CDN.

### Общие рекомендации SRE

1. **Устанавливайте `expire_in`** для временных артефактов (1-7 дней).
2. **Используйте `dependencies`** для явного ограничения загружаемых данных в задачу.
3. **Применяйте `reports`** для автоматизации аттестаций безопасности (SBOM).
4. **Для отладки** всегда используйте `when: on_failure` или `when: always`.
5. **Просмотр в UI:** После выполнения задачи используйте кнопку **Browse** на странице задачи для проверки состава архива.
6. **Измеряйте размер** артефактов перед загрузкой (`du -sh dist/`).
7. **Разделяйте артефакты** по типу: временные (для передачи между задачами) и релизные (для деплоя).
8. **Контролируйте `keep_latest`** — отключайте для проектов с активной разработкой и ограниченным хранилищем.
9. **Используйте Package Registry** для крупных бинарников вместо CI artifacts.
10. **Настройте мониторинг** потребления хранилища через API или Admin Area.
11. **НЕ используйте артефакты для зависимостей** (`node_modules`, `vendor`, `.m2`, `node_modules`). Это создаёт архивы размером в сотни мегабайт на каждый запуск, засоряет хранилище и замедляет пайплайн. Для зависимостей используйте `cache` с `cache:key:files`.

### См. также

- **[Обзор кэширования и артефактов](./caching_overview.md)**
- **[Лучшие практики кэширования](./cache_best_practices.md)**
- **[Управление артефактами](../../../CI-CD/artifact_management.md)**
- **[Downstream Pipelines — multi-project](../Downstream_Pipelines/multi_project_pipelines.md)**
- **[Безопасность цепочки поставок: SBOM](../../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**


