# Матричные сборки и сериализация задач

**Актуально для:** GitLab CI/CD 17.x–19.4

## Определения

**Матричная сборка (`parallel:matrix`)** — это декларативный механизм GitLab CI/CD, позволяющий запускать одну задачу несколько раз с различными комбинациями переменных. На этапе компиляции пайплайна GitLab генерирует декартово произведение указанных массивов данных, создавая изолированные инстансы задачи. Это основной инструмент реализации принципа DRY (Don't Repeat Yourself) для масштабного тестирования и сборки.

**Шардирование (`parallel: N`)** — способ разделения большого набора данных (например, тысяч тест-кейсов) между N идентичными исполнителями. В отличие от матрицы, `parallel` создает копии без изменения переменных окружения, предоставляя лишь индексы шардов (`$CI_NODE_INDEX`), которые приложение должно обработать самостоятельно.

**Группа ресурсов (`resource_group`)** — серверный механизм синхронизации (мьютекс), гарантирующий эксклюзивный доступ задачи к внешнему ресурсу. Он обеспечивает сериализацию выполнения, предотвращая конкуренцию за ресурсы (Race Conditions) при развертывании или обновлении баз данных.

## Предварительные требования

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `parallel: N` (шардирование) | 11.0+ | Базовый параллелизм |
| `parallel:matrix` | 11.5+ | Матричные сборки |
| `exclude` в матрице | 12.0+ | Исключение комбинаций |
| `needs:parallel:matrix` | 16.3+ | Матричная адресация (1:1 связь) |
| `$[[ matrix.VAR ]]` в `needs` | 18.6+ | Выражения в матричных зависимостях |
| `resource_group` | 12.7+ | Базовая сериализация |
| `resource_group_process_mode` | 14.3+ API, 14.4+ YAML | 4 режима обработки очереди |
| `newest_ready_first` | 18.6+ | Приоритизация готовых задач |

### Необходимые знания

- Базовый синтаксис YAML и структура `.gitlab-ci.yml`
- Концепции стадий (`stages`), задач (`jobs`) и зависимостей (`needs`)
- Предопределённые переменные (`$CI_NODE_INDEX`, `$CI_NODE_TOTAL`, `$CI_PIPELINE_IID`)
- Работа с артефактами и кэшированием
- Принцип DRY и переиспользование шаблонов через скрытые задачи (`.template`)

### Целевая аудитория

Данный справочник предназначен для DevOps-инженеров, SRE и системных администраторов, работающих с on-premise и гибридной инфраструктурой. Примеры ориентированы на кросс-платформенное тестирование, мульти-окружения деплоя и безопасную сериализацию критических операций (миграции БД, деплой на физические серверы).

## Основные концепции

### Параллелизм и матрицы (parallel:matrix)

Матрицы позволяют эффективно масштабировать нагрузку, создавая сотни задач из нескольких строк конфигурации. GitLab вычисляет комбинации и создает отдельные задачи (jobs) в рамках одной стадии.

**Технические особенности (Стандарты 2025–2026):**
- **Лимиты перестановок:** Максимальное количество задач (jobs), генерируемых одной матрицей, ограничено **200**. Для обхода лимита рекомендуется использовать динамическую генерацию пайплайнов или несколько блоков матриц.
- **Исключения (`exclude`):** Позволяют точечно удалять нежелательные или несовместимые комбинации из декартова произведения (например, тестирование драйвера Windows на образе Linux).
- **Интерполяция:** Переменные матрицы могут использовать значения из `spec:inputs` или глобальных переменных.
- **Именование:** GitLab автоматически дополняет имя задачи значениями переменных в формате `job_name: [var1, var2]`. Это критично для отладки и визуализации.
- **Матричное шардирование:** Поскольку GitLab не позволяет использовать числовой `parallel` и `matrix` одновременно, стандартом 2026 года стало добавление измерения `SHARD` (или аналогичного) в саму матрицу для разделения тестов внутри конкретной ветки конфигурации.

### Сериализация и очереди (resource_group)

Когда задача требует монопольного доступа (например, `terraform apply`, миграция БД или деплой на физическое устройство), используется `resource_group`.

**Режимы обработки очереди (`resource_group_process_mode`):**

| Режим | Поведение | Типовой сценарий |
| :--- | :--- | :--- |
| **`unordered`** | Запуск в порядке готовности раннеров. | Базовая блокировка без строгих требований к хронологии. |
| **`oldest_first`** | Строгое соблюдение порядка создания пайплайнов. | **Миграции БД**, последовательное накатывание патчей. |
| **`newest_first`** | Приоритет самой свежей задачи; старые в очереди пропускаются. | **CD в Web-приложениях**: важен только актуальный код, старые деплои неактуальны. |
| **`newest_ready_first`** | Выбирает самое свежее задание из тех, что уже готовы к запуску. | Оптимизация ресурсов при использовании сложных правил `rules`. |

**Приоритизация (GitLab 18.x+):** Введена возможность настройки приоритетов внутри группы ресурсов. Задания из Merge Request могут иметь приоритет над Scheduled-запусками, даже если последние были созданы раньше.

**Важно:** Для задач с `resource_group` рекомендуется устанавливать `interruptible: false`, чтобы критическая операция (например, обновление схемы БД) не была прервана механизмом `auto_cancel`.

**Ограничения матричных выражений (18.6+):**
- **Compile-time only:** Идентификаторы разрешаются при создании пайплайна, а не во время выполнения задачи.
- **String replacement only:** Нет сложной логики или трансформаций.
- **Matrix identifiers only:** Нельзя ссылаться на обычные CI/CD переменные или `spec:inputs`.

**Deadlock при parent-child пайплайнах:** Если родительский и дочерний пайплайн используют одну и ту же `resource_group` с режимом `oldest_first`, возникает взаимная блокировка: родитель ждет дочерний, дочерний ждет родителя. Решение — определить `resource_group` в родительской задаче `trigger`, а не в дочерней.

## Практические сценарии

### Параллелизация тестов с parallel: N (sharding)

`parallel: N` запускает N идентичных копий задач. Каждая копия получает переменные `$CI_NODE_INDEX` (1..N) и `$CI_NODE_TOTAL` (N) — можно делить тест-файлы по индексу.

```yaml
test:sharded:
  stage: test
  parallel: 4
  script:
    - pytest --shard=$CI_NODE_INDEX/$CI_NODE_TOTAL tests/
```
*Результат:* GitLab создаст 4 задачи: `test 1/4`, `test 2/4`, `test 3/4`, `test 4/4`.

### Параметризация деплоя с parallel: matrix

Запуск задач с разными комбинациями окружений и регионов.

```yaml
deploy:
  stage: deploy
  script:
    - helm upgrade --install app ./chart --namespace $ENV
  parallel:
    matrix:
      - ENV: [dev, stage, prod]
        REGION: [ru-1]
      - ENV: [prod]
        REGION: [ru-1, ru-2]
```
*Результат:* Создается 5 задач с именами вроде `deploy: [dev, ru-1]`.

### Тестирование на разных версиях (Python)

```yaml
test:python:
  stage: test
  image: python:${PYTHON_VERSION}
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.10", "3.11", "3.12"]
  script:
    - pip install -r requirements.txt
    - pytest -q
```

### Go-сервис: тесты на 3 версиях с изоляцией артефактов

Использование суффиксов в именах файлов предотвращает перезапись артефактов разными инстансами матрицы.

```yaml
stages:
  - test
  - coverage

variables:
  COVERAGE_FILE: "coverage-${GO_VERSION}.out"

test:go:
  stage: test
  image: golang:${GO_VERSION}
  parallel:
    matrix:
      - GO_VERSION: ["1.21", "1.22", "1.23"]
  script:
    - go test -race -coverprofile="$COVERAGE_FILE" ./...
  artifacts:
    paths:
      - "$COVERAGE_FILE"
    expire_in: 1 hour

merge-coverage:
  stage: coverage
  needs:
    - job: test:go
      parallel:
        matrix:
          - GO_VERSION: ["1.21", "1.22", "1.23"]
  script:
    - go tool cover -html=coverage-1.23.out -o coverage.html
```

### Комбинированная матрица (Node.js OS × Version × Suite)

```yaml
build:node:
  stage: build
  image: ${BUILD_IMAGE}
  parallel:
    matrix:
      - BUILD_IMAGE: ["node:18", "node:20", "node:22"]
        TEST_SUITE: ["unit"]
      - BUILD_IMAGE: ["node:20"]
        TEST_SUITE: ["integration", "e2e"]
  script:
    - npm run test:${TEST_SUITE}
```

### Сериализация развертываний с resource_group

**Защита промышленной среды и миграции БД:**

```yaml
database_migration:
  stage: deploy
  resource_group: db_migrate
  resource_group_process_mode: oldest_first # Строго хронологически
  script:
    - ./migrate.sh
  interruptible: false

deploy_prod:
  stage: deploy
  resource_group: production
  resource_group_process_mode: newest_first # Только последний код
  script:
    - ./scripts/deploy.sh production
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

### Использование исключений (exclude)

```yaml
test:compatibility:
  stage: test
  parallel:
    matrix:
      - OS: [linux, windows, macOS]
        ARCH: [amd64, arm64]
        exclude:
          - OS: macOS
            ARCH: amd64 # Apple Silicon only
          - OS: windows
            ARCH: arm64 # Не поддерживается текущим раннером
  script:
    - ./test_on_${OS}_${ARCH}.sh
```

### Динамические зависимости (needs:parallel:matrix)

Сопоставление 1:1 между матрицами для ускорения пайплайна (GitLab 16.3+).

```yaml
build:
  stage: build
  parallel:
    matrix:
      - PROVIDER: [vsphere, libvirt, proxmox]
  script: ./build.sh $PROVIDER

test:
  stage: test
  parallel:
    matrix:
      - PROVIDER: [vsphere, libvirt, proxmox]
  needs:
    - job: build
      parallel:
        matrix:
          - PROVIDER: [$PROVIDER] # Тест vSphere не ждет сборку libvirt
  script: ./test.sh $PROVIDER
```

## DevOps/SRE и on-premise сценарии

### Кросс-платформенное тестирование инфраструктурных инструментов

Тестирование Ansible-плейбуков на разных ОС и версиях Python в on-premise среде.

```yaml
test:ansible:
  stage: test
  image: ${TEST_IMAGE}
  parallel:
    matrix:
      - TEST_IMAGE: ["python:3.10", "python:3.11", "python:3.12"]
        TARGET_OS: [centos9, rocky9, ubuntu2204]
        exclude:
          - TEST_IMAGE: "python:3.12"
            TARGET_OS: centos9  # Python 3.12 не входит в репозиторий CentOS 9
  before_script:
    - pip install ansible-core==2.16
    - ansible --version
  script:
    - ansible-playbook --syntax-check -i inventory/${TARGET_OS} site.yml
    - ansible-lint playbooks/
  artifacts:
    paths:
      - lint-results.txt
    when: always
```

### Матричная сборка Terraform-модулей для мульти-окружений

Сборка и валидация Terraform-модулей для разных провайдеров (on-premise: vSphere, libvirt, Proxmox).

```yaml
stages:
  - validate
  - plan
  - apply

.terraform_validate:
  stage: validate
  image: hashicorp/terraform:1.9
  script:
    - cd modules/$MODULE_NAME
    - terraform init -backend=false
    - terraform validate
    - terraform fmt -check -recursive

validate:modules:
  extends: .terraform_validate
  parallel:
    matrix:
      - MODULE_NAME: [networking, compute, storage, monitoring]
        PROVIDER: [vsphere, libvirt]
  artifacts:
    paths:
      - validation-results/${MODULE_NAME}-${PROVIDER}.json
    expire_in: 1 hour

plan:environments:
  stage: plan
  extends: .terraform_validate
  needs: ["validate:modules"]
  parallel:
    matrix:
      - DEPLOY_ENV: [staging, production]
        PROVIDER: [vsphere]
  script:
    - cd environments/$DEPLOY_ENV
    - terraform init
    - terraform plan -out=tfplan -var="provider=${PROVIDER}"
    - terraform show -json tfplan > plan-${DEPLOY_ENV}.json
  artifacts:
    paths:
      - environments/$DEPLOY_ENV/tfplan
      - environments/$DEPLOY_ENV/plan-${DEPLOY_ENV}.json
```

### Параллельное тестирование Salt-состояний

Проверка Salt-состояний на разных версиях Salt и целевых ОС.

```yaml
test:salt:
  stage: test
  image: python:${PYTHON_VERSION}
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.10", "3.11"]
        SALT_VERSION: ["3006", "3007"]
        TARGET: [master, minion]
        exclude:
          - PYTHON_VERSION: "3.11"
            SALT_VERSION: "3006"  # Salt 3006 не поддерживает Python 3.11
  before_script:
    - pip install salt==${SALT_VERSION}
  script:
    - salt-call --local state.show_highstate --out=json > highstate-${TARGET}.json
    - salt-call --local state.apply test=True --out=yaml
  artifacts:
    paths:
      - highstate-${TARGET}.json
    expire_in: 1 day
```

### Деплой на физические серверы с resource_group

Безопасное последовательное развертывание на bare-metal серверы через IPMI/iLO.

```yaml
deploy:baremetal:
  stage: deploy
  resource_group: baremetal_deploy
  resource_group_process_mode: oldest_first
  variables:
    SERVERS: "web01,web02,web03"
    DEPLOY_TIMEOUT: "30m"
  script:
    - for SERVER in $(echo $SERVERS | tr ',' '\n'); do
        echo "Deploying to $SERVER...";
        ipmitool -I lanplus -H $SERVER.IPMI -U admin -P $IPMI_PASS power cycle;
        sleep 10;
        ./wait_for_server.sh $SERVER;
        ansible-playbook -i "$SERVER," -e "target_host=$SERVER" deploy.yml;
      done
  after_script:
    - ./cleanup_temp_files.sh
  interruptible: false
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Шардирование интеграционных тестов с агрегацией результатов

Разбиение большого набора интеграционных тестов на шарды с последующей агрегацией отчётов.

```yaml
test:integration:sharded:
  stage: test
  image: python:3.12
  parallel: 8
  script:
    - pytest --shard=$CI_NODE_INDEX/$CI_NODE_TOTAL
      --junitxml=results-${CI_NODE_INDEX}.xml
      tests/integration/
  artifacts:
    reports:
      junit: results-${CI_NODE_INDEX}.xml
    paths:
      - results-${CI_NODE_INDEX}.xml
    expire_in: 1 day

aggregate:results:
  stage: report
  image: python:3.12
  needs: ["test:integration:sharded"]
  script:
    - pip install junitparser
    - python3 aggregate_results.py results-*.xml
    - junitparser merge results-*.xml > combined-results.xml
  artifacts:
    reports:
      junit: combined-results.xml
```

### Матричный деплой Helm-чартов с Depends-On

Деплой зависимости между сервисами через `needs:parallel:matrix`.

```yaml
build:helm:
  stage: build
  parallel:
    matrix:
      - SERVICE: [api, worker, nginx]
  script:
    - helm package charts/$SERVICE --version $CI_PIPELINE_IID
  artifacts:
    paths:
      - $SERVICE-*.tgz

deploy:services:
  stage: deploy
  parallel:
    matrix:
      - SERVICE: [api, worker, nginx]
  needs:
    - job: build:helm
      parallel:
        matrix:
          - SERVICE: ["$SERVICE"]  # Каждый сервис ждет свою сборку
    - job: deploy:services
      parallel:
        matrix:
          - SERVICE: [api]  # worker и nginx ждут деплой api
        optional: true
  script:
    - helm upgrade --install $SERVICE charts/$SERVICE
      --namespace $KUBE_NAMESPACE
      --set image.tag=$CI_COMMIT_SHA
```

### Селективные зависимости через матричные выражения (18.6+)

Matrix expressions позволяют зависеть только от части комбинаций upstream-матрицы, не указывая все варианты вручную.

```yaml
prepare_env:
  stage: prepare
  parallel:
    matrix:
      - OS: [linux, windows, macos]
        PYTHON: ["3.10", "3.11", "3.12"]
  script:
    - echo "Preparing $OS with Python $PYTHON"

test_project:
  stage: test
  parallel:
    matrix:
      - OS: [linux, windows, macos]
  needs:
    - job: prepare_env
      parallel:
        matrix:
          - OS: ['$[[ matrix.OS ]]']
            PYTHON: ["3.11", "3.12"]  # Только актуальные версии
  script:
    - pytest -k "not slow"
```

**Важно:**
- Matrix expressions разрешаются только на этапе компиляции.
- Можно ссылаться только на идентификаторы матрицы, но не на обычные переменные или `spec:inputs`.

### Parent-child пайплайны с resource_group: avoiding deadlock

При использовании `trigger` с `strategy: mirror` родительская задача ждет завершения дочернего пайплайна. Если дочерний пайплайн использует ту же `resource_group`, что и родительский `deploy`, при `oldest_first` возникает deadlock.

```yaml
# parent-pipeline.yml
test:
  stage: test
  trigger:
    include: child-pipeline.yml
    strategy: mirror
  resource_group: production_deploy  # Блокировка определяется здесь

deploy:
  stage: deploy
  resource_group: production_deploy
  script: ./deploy.sh
```

**Правило:** Всегда определяйте `resource_group` в родительской задаче `trigger`, а не в дочернем пайплайне.

### Кросс-платформенное тестирование Ansible на on-prem хостах

Тестирование плейбуков наCentOS Stream 9, Rocky Linux 9 и Ubuntu 22.04 через Docker-раннеры, имитирующие целевые ОС.

```yaml
test:ansible:
  stage: test
  parallel:
    matrix:
      - TARGET_OS: [centos9, rocky9, ubuntu2204]
        PYTHON_VERSION: ["3.10", "3.11", "3.12"]
        exclude:
          - TARGET_OS: centos9
            PYTHON_VERSION: "3.12"  # CentOS 9 Stream не имеет Python 3.12 в репозиториях
  image: python:${PYTHON_VERSION}
  before_script:
    - pip install ansible-core==2.16
  script:
    - ansible-playbook --syntax-check -i inventory/${TARGET_OS} site.yml
    - ansible-lint playbooks/
  artifacts:
    paths:
      - lint-results/${TARGET_OS}-${PYTHON_VERSION}.txt
    expire_in: 1 day
```

### Валидация Terraform-модулей для on-prem провайдеров

Запуск `terraform validate` и `terraform plan` для модулей, targeted на vSphere, Proxmox VE и libvirt.

```yaml
stages:
  - validate
  - plan

validate:modules:
  stage: validate
  image: hashicorp/terraform:1.9
  parallel:
    matrix:
      - MODULE: [networking, compute, storage]
        PROVIDER: [vsphere, proxmox, libvirt]
  script:
    - cd modules/${MODULE}
    - terraform init -backend=false
    - terraform validate
    - terraform fmt -check -recursive
  artifacts:
    paths:
      - validation-${MODULE}-${PROVIDER}.json
    expire_in: 1 hour

plan:staging:
  stage: plan
  needs: ["validate:modules"]
  parallel:
    matrix:
      - ENV: [staging, production]
        PROVIDER: [vsphere]
  script:
    - cd environments/${ENV}
    - terraform init
    - terraform plan -out=tfplan -var="provider=${PROVIDER}"
  artifacts:
    paths:
      - environments/${ENV}/tfplan
      - environments/${ENV}/plan-${ENV}.json
```

### Сериализация миграций БД с resource_group

Защита промышленной базы от конкурирующих миграций в параллельных пайплайнах.

```yaml
database_migration:
  stage: deploy
  resource_group: db_migrate
  resource_group_process_mode: oldest_first
  script:
    - ./migrate.sh
  interruptible: false
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
      allow_failure: false
```

## Валидация и отладка матричных сборок

### Просмотр сгенерированных задач

Перед запуском пайплайна можно проверить, какие именно задачи будут созданы матрицей:

```bash
# Через CI Lint API — покажет все сгенерированные инстансы
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --data "content=$(cat .gitlab-ci.yml | base64)" \
  "https://gitlab.example.com/api/v4/ci/lint" | jq '.jobs | length'

# Количество задач = произведение длин всех массивов минус исключения
# Пример: 3 * 2 - 1 exclude = 5 задач
```

### Отладка переменных в матричных задачах

```yaml
debug:matrix:
  stage: .pre
  parallel:
    matrix:
      - TARGET: [web01, web02, web03]
        ENV: [staging, production]
  script:
    - echo "=== Матричная переменная ==="
    - echo "TARGET=$TARGET"
    - echo "ENV=$ENV"
    - echo "CI_NODE_INDEX=$CI_NODE_INDEX"
    - echo "CI_NODE_TOTAL=$CI_NODE_TOTAL"
    - echo "CI_JOB_NAME=$CI_JOB_NAME"
    - echo "CI_PIPELINE_IID=$CI_PIPELINE_IID"
  rules:
    - when: always
```

### Проверка `needs:parallel:matrix` перед запуском

```bash
# Валидация: убедитесь, что переменные в needs совпадают с переменными в матрице build
# Ошибка: PROVIDER в needs не объявлен в матрице build
# Правильно: PROVIDER объявлен в обеих матрицах

# Проверка через glab
glab ci lint --dry-run --variable CI_COMMIT_BRANCH=main
```

### Мониторинг выполнения матричных задач

```bash
# Просмотр статуса всех задач матрицы через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/jobs" | \
  jq '[.[] | select(.name | startswith("test:python"))] | 
    {name, status, duration, runner_description}'
```

## Лучшие практики

### Оптимизация матричных сборок

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| **Минимальные артефакты** | `expire_in: 1 hour` для промежуточных результатов | Высокий |
| **Уникальные ключи кэша** | `cache:key: $CI_JOB_NAME-$TARGET` для каждой комбинации | Высокий |
| **`needs:parallel:matrix`** | Связывание 1:1 вместо ожидания всей матрицы | Высокий |
| **Matrix expressions (18.6+)** | `$[[ matrix.VAR ]]` для селективных зависимостей без ручного перечисления | Высокий |
| **`exclude`** | Исключайте несовместимые комбинации заранее | Средний |
| **Динамические матрицы** | Генерация через API при >50 комбинациях | Средний |
| **Группировка по stages** | Не смешивайте критичные и некритичные задачи в одной стадии | Средний |

### Сериализация и безопасность

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| **`interruptible: false`** | Для критических операций с `resource_group` | Критический |
| **`resource_group_process_mode`** | `oldest_first` для миграций, `newest_first` для деплоев | Высокий |
| **Таймауты** | Устанавливайте `timeout` для задач с `resource_group` | Высокий |
| **Deadlock avoidance** | Определяйте `resource_group` в родительской `trigger`, а не в дочернем пайплайне | Критический |
| **Очистка в `after_script`** | Удаляйте временные файлы, токены, ключи | Средний |
| **Мониторинг очереди** | Отслеживайте длину очереди `resource_group` через API | Средний |

### Производительность

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| **Разбиение тестов** | `parallel: N` для шардинга >1000 тестов | Высокий |
| **Кэширование зависимостей** | `cache` для pip, npm, go mod в матричных задачах | Средний |
| **Минимальные образы** | Используйте альпайны и slim-образы для быстрого старта | Средний |
| **Агрегация результатов** | Собирайте отчёты в одной задаче после матрицы | Средний |

## Устранение неполадок

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Job(s) disabled` | Более 200 задач в одной матрице | Разбейте на несколько матриц или динамическую генерацию |
| `needs:job not found` | Имя задачи в `needs` не совпадает с реальным именем | Проверьте `CI_JOB_NAME` (формат `name: [var1, var2]`) |
| `Variable not defined` | Переменная матрицы не объявлена в блоке `matrix` | Добавьте переменную в `parallel:matrix` |
| `Artifact not found` | Задача в `needs` не создала артефакт | Проверьте `paths` в `artifacts` и имя файла |
| `Resource group timeout` | Очередь `resource_group` не освобождается | Проверьте `resource_group_process_mode` и таймауты |
| `Cache collision` | Разные матричные задачи перезаписывают кэш | Добавьте переменную матрицы в `cache:key` |
| `Matrix expression error` | `$[[ matrix.VAR ]]` используется вне `needs:parallel:matrix` или ссылается на несуществующий идентификатор | Проверьте синтаксис и убедитесь, что переменная объявлена в `parallel:matrix` |
| `Deadlock` | Родительский и дочерний пайплайн используют одну `resource_group` с `oldest_first` | Определите `resource_group` в родительской задаче `trigger` |

### Диагностика проблем с `resource_group`

```bash
# Проверка активных задач в группе ресурсов
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/resource_groups" | \
  jq '.[] | {key, process_mode, jobs: [.jobs[] | {id, name, status}]}'

# Просмотр истории выполнения
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/resource_groups/$RESOURCE_GROUP/jobs" | \
  jq '.[] | {id, name, status, created_at, started_at, finished_at}'
```

### Диагностика матричных зависимостей

```yaml
# Проблема: test: [web01] не ждет build: [web01]
# Причина: неправильное использование переменной в needs

# НЕПРАВИЛЬНО:
needs:
  - job: build
    parallel:
      matrix:
        - TARGET: [web01, web02, web03]  # Все инстансы ждут ВСЕ инстансы build

# ПРАВИЛЬНО:
needs:
  - job: build
    parallel:
      matrix:
        - TARGET: [$TARGET]  # Каждый инстанс ждет только свой
```

### Отладка `exclude`

```yaml
# Проблема: exclude не работает
# Причина: exclude должен точно совпадать с комбинацией в matrix

# ПРОВЕРКА: убедитесь, что ключи и значения идентичны
parallel:
  matrix:
    - OS: [linux, windows, macos]
      ARCH: [amd64, arm64]
      exclude:
        - OS: macos      # Точное совпадение с matrix
          ARCH: amd64
```

## Граничные случаи и ограничения

### Технические лимиты

| Параметр | Лимит | Рекомендация |
| :--- | :--- | :--- |
| Задач в `parallel:matrix` | 200 | Разбейте на несколько матриц или используйте динамическую генерацию |
| `parallel: N` (шардов) | 100 | Используйте `pytest --shard` или аналогичные механизмы |
| Глубина вложенности `needs` | 100 | Избегайте цепочек длиннее 10 задач |
| Артефактов на задачу | Квота проекта | `expire_in` для промежуточных результатов |
| Записей кэша на задачу | 4 | Используйте `cache:key` с переменными матрицы |
| Размер dotenv файла | 5 KB, 20 переменных | Передавайте только необходимые значения |

### Ограничения матричных выражений (18.6+)

Matrix expressions (`$[[ matrix.VAR ]]`) упрощают создание 1:1 зависимостей, но имеют строгие ограничения:
- **Compile-time only:** Идентификаторы разрешаются при создании пайплайна, а не во время выполнения задачи.
- **String replacement only:** Нет сложной логики или трансформаций.
- **Matrix identifiers only:** Нельзя ссылаться на обычные CI/CD переменные или `spec:inputs`.
- **Только текущая матрица:** Выражение ссылается на идентификаторы из `parallel:matrix` текущей задачи.

### Несовместимость и побочные эффекты

| Механизм | Ограничение | Решение |
| :--- | :--- | :--- |
| `dotenv` + `parallel:matrix` | Dotenv переменные не работают между инстансами матрицы | Используйте общие артефакты или API |
| `parallel:matrix` + `parallel: N` | Числовой `parallel` и `matrix` взаимоисключающие | Добавьте измерение шардирования в саму матрицу |
| `resource_group` + parent-child `oldest_first` | Взаимная блокировка (deadlock) | Определяйте `resource_group` в родительской задаче `trigger` |
| `interruptible: true` + `resource_group` | Критическая операция может быть прервана `auto_cancel` | Устанавливайте `interruptible: false` |
| `matrix expressions` + обычные переменные | `$[[ ... ]]` не разрешает `$CI_*` или `$VARIABLE` | Используйте только идентификаторы матрицы |

### Особые сценарии

**Матрица с `rules` и `resource_group`:**
```yaml
# ВАЖНО: rules вычисляются ДО матрицы
# Каждая комбинация матрицы проверяется отдельно
deploy:
  resource_group: production
  parallel:
    matrix:
      - SERVICE: [api, worker]
        ENV: [staging, production]
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
    - if: $CI_COMMIT_BRANCH == "develop"
      variables:
        ENV: staging  # Принудительно staging для develop
```

**Кэширование в матричных задачах:**
```yaml
# Проблема: все матричные задачи делят один кэш
# Решение: уникальный ключ для каждой комбинации
test:
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.10", "3.11", "3.12"]
  cache:
    key: py${PYTHON_VERSION}-deps  # Уникальный ключ
    paths:
      - .venv/
```

**Матрица и `needs` с опциональными зависимостями:**
```yaml
# Опциональные зависимости (17.4+): задача не ждет, если зависимость отсутствует
deploy:
  parallel:
    matrix:
      - TARGET: [web01, web02]
  needs:
    - job: migrate
      optional: true  # Если migrate не существует или пропущен
    - job: build
      parallel:
        matrix:
          - TARGET: ["$TARGET"]
```

**Parent-child deadlock с `resource_group`:**
```yaml
# ПРОБЛЕМА: родительский deploy ждет child-pipeline,
# child-pipeline ждет resource_group, который занят родителем
# РЕШЕНИЕ: resource_group определяем в trigger-задаче родителя
test:
  stage: test
  trigger:
    include: child-pipeline.yml
    strategy: mirror
  resource_group: production_deploy  # Блокировка здесь
```

**Matrix expressions: ограничения (18.6+):**
```yaml
# НЕВОЗМОЖНО: ссылаться на обычные переменные в $[[ ... ]]
needs:
  - job: build
    parallel:
      matrix:
        - OS: ['$[[ matrix.OS ]]']  # OK: идентификатор матрицы
        - ENV: ['$[[ $CI_ENV ]]']   # ОШИБКА: обычная переменная не разрешается
```

**Dotenv и `parallel:matrix`:**
```yaml
# ПРОБЛЕМА: dotenv переменные не передаются между инстансами матрицы
# РЕШЕНИЕ: используйте общие артефакты или API для передачи данных
```

## Смотрите также

- **[DAG с использованием needs](./dag_with_needs.md)** — управление графом зависимостей и матричные связи.
- **[Артефакты в GitLab CI](../gitlab_ci_caching/gitlab_ci_artifacts.md)** — артефакты, кэширование, dotenv.
- **[Правила запуска задач](./job_rules.md)** — логика условного включения задач.
- **[Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md)** — иерархия переменных и безопасность.
- **[Обзор Runner и Executor](../gitlab_ci_runners_executors.md)** — архитектура, типы Executor'ов и оптимизация config.toml.
- **[Кэширование и артефакты](../gitlab_ci_caching/caching_overview.md)** — стратегии кэширования для матричных задач.
- **[Родительско-дочерние пайплайны](../Downstream_Pipelines/parent_child_pipelines.md)** — декомпозиция монорепозиториев.
