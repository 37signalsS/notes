# Построение направленного ациклического графа (DAG) с использованием needs

**Актуально для:** GitLab CI/CD 11.8+ / 18.6+

Директива `needs` является ключевым инструментом оптимизации производительности в GitLab CI/CD, позволяющим отойти от традиционной линейной модели выполнения стадий в пользу графовой структуры (Directed Acyclic Graph, DAG). Это позволяет задачам игнорировать границы стадий и запускаться сразу по готовности зависимостей.

## Определения

**Направленный ациклический граф (Directed Acyclic Graph, DAG)** — это структура зависимостей между задачами, где ребра имеют направление (от родителя к потомку) и отсутствуют циклы (задача не может зависеть от самой себя или через цепочку вернуть к себе).

**needs** — директива для явного определения зависимостей задачи. Она определяет, какие работы должны успешно завершиться, прежде чем текущая работа сможет начаться.

### Типы зависимостей и ключи

- **Внутри пайплайна (`job`):** Базовая зависимость от задачи в том же пайплайне.
- **Опциональная (`optional: true`):** (GitLab 17.4+) Пайплайн не упадет, если зависимая задача не добавлена в граф (например, исключена через `rules`).
- **Кросс-проектная (`project`):** Получение артефактов из другого репозитория. В GitLab 17.0+ требует настройки **Inbound Allowlist** (Zero Trust) в целевом проекте (Settings -> CI/CD -> Job Token Permissions).
- **Пайплайн-зависимость (`pipeline`):** Зависимость от конкретного ID пайплайна, часто используется в связке с `trigger` (Downstream Pipelines).
- **Матричная зависимость (`parallel:matrix`):** Динамическая связь между инстансами параллельных матричных сборок. В GitLab 18.6+ поддерживаются выражения `$[[ matrix.VARIABLE ]]` для связей 1:1.

## Предварительные требования

### Версия GitLab и поддержка ключей

| Ключ / Возможность | Минимальная версия GitLab | Примечание |
| :--- | :--- | :--- |
| `needs` (базовый синтаксис) | 11.8+ | Базовая оркестрация задач |
| `needs: []` (немедленный запуск) | 11.8+ | Игнорирование стадий |
| `needs:project` | 11.8+ | Кросс-проектные артефакты |
| `needs:job` + `artifacts` | 12.2+ | Управление загрузкой артефактов |
| `needs:optional` | 17.4+ | Опциональные зависимости |
| `needs:parallel:matrix` | 16.3+ | Матричная адресация (1:1 связь) |
| `needs:parallel:matrix` с `$[[ matrix.VAR ]]` | 18.6+ | Выражения в матричных зависимостях |
| `rules:needs` | 16.0+ | Динамическое переопределение DAG |
| `auto_cancel:on_job_failure` | 13.12+ | Fail-Fast отмена веток графа |

### Необходимые знания

- Базовый синтаксис YAML и структура `.gitlab-ci.yml`
- Концепции стадий, задач и артефактов
- Предопределённые переменные GitLab (`CI_*`)
- Работа с Merge Request и ветками в Git
- Основы shell-скриптинга для написания команд

### Инструменты диагностики

- **CI Lint API/UI** — валидация конфигурации до запуска пайплайна
- **Pipeline Editor** — визуальный редактор с предпросмотром графа задач
- **`glab ci lint`** — CLI-утилита для локальной проверки конфигурации
- **CI_DEBUG_TRACE** — включение отладочного вывода для анализа переменных
- **Pipeline DAG visualization** — встроенный просмотр графа зависимостей в UI пайплайна

## Основные концепции

По умолчанию задачи в стадии выполняются параллельно, а стадии — последовательно. `needs` нарушает эту модель:

1.  **Обход стадий:** Задача запускается **сразу** после завершения указанных в `needs` задач. Не нужно ждать окончания всей стадии.
2.  **Автоматическое управление артефактами:** `needs` автоматически устанавливает `dependencies`, загружая артефакты **только** от указанных задач.
3.  **Ускорение обратной связи (Fail-Fast):** Критические задачи (например, быстрые тесты) могут начаться раньше, не дожидаясь долгих сборок, не связанных с ними.

### Принцип работы планировщика DAG

GitLab использует топологическую сортировку графа зависимостей для определения порядка выполнения задач. Планировщик работает в два этапа:

1. **Компиляция графа:** При создании пайплайна GitLab анализирует все директивы `needs`, `stage` и `rules`, строит граф зависимостей и проверяет отсутствие циклов. При обнаружении циклической зависимости пайплайн не создаётся.
2. **Выполнение по готовности:** Задача переходит в статус `pending` сразу после успешного завершения всех её прямых зависимостей, независимо от статуса других задач в той же или предыдущих стадиях. Это означает, что задача в стадии `test` может запуститься раньше, чем завершится задача в стадии `build`, если она зависит только от конкретной задачи сборки, а не от всей стадии.

Артефакты передаются автоматически: если задача указана в `needs`, GitLab загружает её артефакты на раннер перед выполнением скриптов. Для задач, которые зависят от статуса другой задачи, но не нуждаются в её артефактах, используйте `dependencies: []` — это предотвращает ненужную передачу данных и ускоряет запуск.

### Сравнение needs и dependencies

| Характеристика | `needs` | `dependencies` |
| :--- | :--- | :--- |
| **Основная цель** | Оркестрация (порядок запуска) | Передача данных (артефакты) |
| **Влияние на время** | Сокращает (запускает Job раньше) | Не влияет |
| **Соблюдение стадий** | Игнорирует (DAG) | Строго последовательно |
| **Выбор артефактов** | Только от задач в `needs` | Все из предыдущих стадий (по умолчанию) |

### Динамические зависимости (rules:needs)

С версии GitLab 16.0 массив `needs` можно изменять динамически с помощью правил. Это позволяет оптимизировать путь выполнения в зависимости от контекста.

```yaml
deploy:
  stage: deploy
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      needs: ["build:prod", "test:integration"]
    - if: $CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH
      needs: ["build:dev"] # Ускоренный путь для веток разработки
```

## Практические сценарии

### Сценарий 1: Ускорение пайплайна (DAG)

Независимые тесты не ждут долгих сборок всех компонентов.

```yaml
stages:
  - build
  - test

build:web:
  stage: build
  script: npm run build:web
  artifacts:
    paths: [dist/web/]

build:android:
  stage: build
  script: ./gradlew assembleDebug
  artifacts:
    paths: [app/build/outputs/apk/]

build:ios:
  stage: build
  script: xcodebuild -scheme MyApp
  artifacts:
    paths: [build/ios/]

# Запускается СРАЗУ после build:web (через ~2 мин), не ждёт android/ios (~10 мин)
test:web:
  stage: test
  needs: ["build:web"]
  script: npm run test:web

# Ждёт окончания всей стадии build (классическое поведение по умолчанию)
test:all:
  stage: test
  script: npm run test:all
```

**Оптимизация с `dependencies: []`:**
Если задача зависит от успеха другой задачи, но ей не нужны её артефакты, используйте `dependencies: []` вместе с `needs`. Это сэкономит время и трафик на скачивании данных.

### Сценарий 2: Опциональные зависимости (needs:optional)

Используется в динамических пайплайнах, где некоторые задачи могут не существовать.

```yaml
deploy:
  stage: deploy
  needs:
    - job: "security-scan"
      optional: true  # Пайплайн не упадет, если security-scan пропущен правилами rules
```

### Сценарий 3: Кросс-проектные зависимости (needs:project)

Позволяет построить цепочку поставок между репозиториями без использования API-скриптов.

```yaml
integration-test:
  stage: test
  needs:
    - project: "my-group/backend-api"
      job: "build-assets"
      ref: "main"
      artifacts: true
```
**Важно (Zero Trust):** Проект-источник обязан явно разрешить доступ вашему проекту через **Inbound Allowlist** в настройках CI/CD (**Token Access**).

### Сценарий 4: Динамические матричные зависимости (1:1)

В GitLab 18.6+ можно использовать матричные выражения для автоматической связи инстансов.

```yaml
build:
  stage: build
  parallel:
    matrix:
      - OS_TARGET: [ubuntu-22.04, debian-12, rockylinux-9]
  script: echo "Building for $OS_TARGET"

test:
  stage: test
  parallel:
    matrix:
      - OS_TARGET: [ubuntu-22.04, debian-12, rockylinux-9]
  needs:
    - job: build
      parallel:
        matrix:
          - OS_TARGET: ['$[[ matrix.OS_TARGET ]]'] # test:ubuntu-22.04 будет ждать только build:ubuntu-22.04
  script: echo "Testing for $OS_TARGET"
```

### Сценарий 5: Немедленный запуск (needs: [])

Пустой массив `needs: []` означает, что задача не зависит ни от чего и запускается **сразу** при старте пайплайна, независимо от стадий. Идеально для линтеров и уведомлений.

```yaml
lint:
  stage: test
  needs: []
  script: npm run lint
```

## Сложный DAG с несколькими зависимостями

Директива `needs` позволяет создавать сложные ветвящиеся структуры:

```yaml
lint:
  stage: test
  script: npm run lint

test:unit:
  stage: test
  script: npm run test:unit

test:integration:
  stage: test
  needs: ["lint", "test:unit"]
  script: npm run test:integration

deploy:
  stage: deploy
  needs: ["test:integration"]
  script: ./deploy.sh
```

**Граф выполнения:**
```
lint ──┬─→ test:integration ──→ deploy
        │
test:unit ──┘
```

### DevOps/SRE и on-premise сценарии

**Terraform: каскадное развертывание с DAG-зависимостями:**
```yaml
stages:
  - validate
  - plan
  - apply

variables:
  TF_ROOT: "terraform/"
  TF_STATE_NAME: "production"

.init: &terraform_init
  image: hashicorp/terraform:1.9
  before_script:
    - cd $TF_ROOT
    - terraform init -backend-config="backend.hcl"

terraform:validate:
  <<: *terraform_init
  stage: validate
  script:
    - terraform validate
    - terraform fmt -check -recursive
  rules:
    - changes:
        paths: ["terraform/**/*.tf"]
        compare_to: '${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main}'

terraform:plan:
  <<: *terraform_init
  stage: plan
  needs: ["terraform:validate"]
  script:
    - terraform plan -out=tfplan -var-file="production.tfvars"
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 1 day
  rules:
    - changes:
        paths: ["terraform/**/*.tf"]
        compare_to: '${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main}'

terraform:apply:
  <<: *terraform_init
  stage: apply
  needs: ["terraform:plan"]
  script:
    - terraform apply -auto-approve tfplan
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main" && $CI_PIPELINE_SOURCE == "web"'
      when: manual
    - when: never
```

**Ansible: каскадное развертывание с параллельной валидацией:**
```yaml
stages:
  - lint
  - test
  - deploy:staging
  - deploy:production

ansible:lint:
  stage: lint
  image: cytopia/ansible-lint
  needs: []
  script:
    - ansible-lint roles/
    - ansible-lint playbooks/
  rules:
    - changes:
        paths: ["ansible/**/*"]
        compare_to: 'main'

ansible:test:
  stage: test
  image: cytopia/ansible:2.14
  needs: ["ansible:lint"]
  script:
    - ansible-playbook --syntax-check playbooks/deploy.yml
    - molecule test

ansible:deploy:staging:
  stage: deploy:staging
  image: cytopia/ansible:2.14
  needs: ["ansible:test"]
  script:
    - ansible-playbook -i inventory/staging playbooks/deploy.yml
  environment:
    name: staging
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'
      when: manual
    - when: never

ansible:deploy:production:
  stage: deploy:production
  image: cytopia/ansible:2.14
  needs: ["ansible:deploy:staging"]
  script:
    - ansible-playbook -i inventory/production playbooks/deploy.yml
      --vault-password-file <(echo $VAULT_PASSWORD)
  environment:
    name: production
  variables:
    VAULT_PASSWORD: $ANSIBLE_VAULT_PASSWORD
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
    - when: never
```

**Salt/Puppet: валидация и применение конфигураций:**
```yaml
stages:
  - validate
  - apply

salt:validate:
  stage: validate
  image: saltstack/salt:latest
  needs: []
  script:
    - salt-call --local state.show_highstate --retcode-passthrough
  rules:
    - changes:
        paths: ["salt/**/*"]
        compare_to: 'main'

salt:apply:
  stage: apply
  image: saltstack/salt:latest
  needs: ["salt:validate"]
  script:
    - salt-call --local state.highstate
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
  allow_failure: false
```

**Проверка конфигурации сетевых устройств (NAPALM/Netmiko):**
```yaml
stages:
  - validate
  - diff
  - deploy

network:validate:
  stage: validate
  image: python:3.12
  needs: []
  before_script:
    - pip install napalm
  script:
    - python validate_configs.py configs/
  rules:
    - changes:
        paths: ["configs/**/*"]
        compare_to: 'main'

network:diff:
  stage: diff
  image: python:3.12
  needs: ["network:validate"]
  before_script:
    - pip install napalm
  script:
    - python generate_diff.py configs/ --output diff.txt
  artifacts:
    paths: ["diff.txt"]
    expire_in: 1 week

network:deploy:
  stage: deploy
  image: python:3.12
  needs: ["network:diff"]
  before_script:
    - pip install napalm
  script:
    - python deploy_configs.py configs/ --dry-run
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

**Мониторинг инфраструктуры (Consul/Prometheus):**
```yaml
stages:
  - validate
  - deploy

consul:validate:
  stage: validate
  image: hashicorp/consul:latest
  needs: []
  script:
    - consul validate configs/
  rules:
    - changes:
        paths: ["configs/consul/**/*"]
        compare_to: 'main'

prometheus:reload:
  stage: deploy
  image: curlimages/curl:latest
  needs: ["consul:validate"]
  script:
    - curl -X POST http://prometheus:9090/-/reload
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

## Валидация и отладка зависимостей

### Методы проверки конфигурации

**1. CI Lint (API/UI):**
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
Визуальный интерфейс для проверки графа зависимостей и валидации логики.

### Отладка DAG-зависимостей

**Проблема:** Задача запускается раньше или позже ожидаемого.

**Диагностика:**
1. Просмотрите граф пайплайна в UI (Pipelines > DAG visualization)
2. Добавьте отладочный вывод в начало `script`:
```yaml
debug_deps:
  stage: .pre
  script:
    - echo "Current job: $CI_JOB_NAME"
    - echo "Pipeline ID: $CI_PIPELINE_ID"
    - echo "Pipeline source: $CI_PIPELINE_SOURCE"
  needs: []
  rules:
    - when: always
```

3. Проверьте зависимости через API:
```bash
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/jobs"
# → Проверьте поле "needs" в ответе для каждой задачи
```

**Использование CI_DEBUG_TRACE:**
```yaml
debug_trace:
  script:
    - env | sort | grep CI_
  variables:
    CI_DEBUG_TRACE: "true"
  needs: []
  rules:
    - when: always
```

### Валидация логики зависимостей

**Тестирование всех веток логики:**
```bash
for BRANCH in main develop feature/test; do
  echo "Testing branch: $BRANCH"
  glab ci lint --dry-run --variable CI_COMMIT_BRANCH=$BRANCH
done
```

**Проверка кросс-проектных зависимостей:**
```bash
# Убедитесь, что Inbound Allowlist настроен
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$TARGET_PROJECT_ID/ci/variables" | \
  jq '.[] | select(.key == "CI_JOB_TOKEN_ACCESS_TOKEN")'
```

## Лучшие практики

### Структура DAG

1. **Минимизируйте глубину зависимостей:** Чем меньше уровней в графе, тем быстрее пайплайн. Используйте параллельные задачи вместо цепочек.
2. **Избегайте " fan-out / fan-in":** Не создавайте задачи, которые зависят от десятков других — это создает узкое место.
3. **Используйте `needs: []` для линтеров и валидаторов:** Они должны запускаться сразу, не ожидая сборки.
4. **Комбинируйте `needs` и `rules:needs`:** Динамические зависимости позволяют адаптировать граф под контекст (ветка, MR, тег).

### Артефакты и производительность

1. **`artifacts: false` в `needs`:** Если задача зависит от статуса другой, но не нуждается в артефактах — используйте `artifacts: false` для экономии времени на скачивание.
2. **`dependencies: []` + `needs`:** Если задача зависит от другой через `needs`, но артефакты не нужны — явно отключите их через `dependencies: []`.
3. **`expire_in` для артефактов:** Всегда указывайте срок хранения артефактов, чтобы не переполнять хранилище.
4. **`FF_USE_FASTZIP: "true"`:** Включает быстрый конкурентный zip для ускорения загрузки артефактов.

### Кросс-проектные зависимости

1. **Zero Trust (Inbound Allowlist):** Всегда настраивайте Job Token Permissions для кросс-проектных `needs:project`.
2. **Версионирование артефактов:** Используйте `ref: "main"` или конкретные теги для стабильных зависимостей.
3. **Минимизируйте кросс-проектные связи:** Чем меньше зависимостей между проектами, тем проще поддержка и отладка.

### Безопасность и compliance

1. **`allow_failure: false` для критических задач:** Деплой и миграции не должны падать молча.
2. **`interruptible: false` для транзакционных операций:** Не позволяйте `auto_cancel` прерывать критические процессы.
3. **Валидация перед apply:** Всегда используйте `plan`/`validate` перед `apply` в IaC-задачах.

### Производительность

1. **Кэшируйте зависимости:** Используйте `cache` для избежания повторной загрузки зависимостей.
2. **Параллелизуйте независимые задачи:** Задачи без зависимостей выполняются параллельно автоматически.
3. **Используйте `needs:parallel:matrix` для матричных сборок:** Это связывает инстансы 1:1 и уменьшает время ожидания.
4. **Мониторьте время выполнения:** Используйте встроенные метрики GitLab для выявления узких мест.

## Граничные случаи и ограничения

### Технические ограничения

- **Лимит зависимостей:** Максимальное количество задач в массиве `needs` — 50 (может быть изменено администратором инстанса).
- **Лимит имен:** Имена задач в `needs` ограничены 128 символами (GitLab 18.x+).
- **Стадийная последовательность:** Задача А может зависеть от задачи Б, только если Б находится в той же стадии или в стадии, определенной *раньше* в глобальном списке `stages`.
- **Вложенность:** `needs` нельзя использовать для прямой зависимости от задачи внутри дочернего пайплайна (Parent-Child). Используйте `bridge jobs` для передачи статуса.
- **Кросс-проектные артефакты:** `needs:project` требует настройки Inbound Allowlist и не работает с приватными проектами без явного разрешения.

### Особые сценарии

**Циклические зависимости:**
```yaml
# ОШИБКА: задачи зависят друг от друга по кругу
# job_a needs [job_b], job_b needs [job_a]
# GitLab выдаст: "circular dependency detected"
```
Решение: пересмотрите архитектуру графа, используйте промежуточные задачи или `trigger` для разрыва циклов.

**Конфликт `needs` и `stage`:**
```yaml
# Задача в stage: test зависит от задачи в stage: deploy
# Это невозможно, т.к. deploy идет ПОСЛЕ test в списке stages
# GitLab выдаст: "Job is not in any previous stage"
```
Решение: измените порядок `stages` или перераспределите задачи между стадиями.

**Пустой `needs: []` и `stage`:**
```yaml
# Задача с needs: [] запускается СРАЗУ, независимо от stage
# Это не ошибка — так работает DAG
lint:
  stage: test  # stage будет проигнорирован для порядка запуска
  needs: []
  script: npm run lint
```

**Конфликт `needs` и `dependencies`:**
```yaml
# Если указать и needs, и dependencies:
# needs управляет порядком запуска
# dependencies управляет загрузкой артефактов
# Они работают независимо друг от друга
deploy:
  needs: ["build"]
  dependencies: ["test"]  # Загрузит артефакты от test, но будет ждать build
```

**`needs:project` с несуществующим проектом:**
```yaml
# Если целевой проект не существует или нет доступа:
# GitLab выдаст ошибку на этапе компиляции пайплайна
# Убедитесь, что путь к проекту корректен и Inbound Allowlist настроен
```

### Несовместимость с другими директивами

- **`needs` и `stage`:** `needs` переопределяет порядок стадий. Задача может запуститься раньше, чем ожидается по `stage`.
- **`needs` и `resource_group`:** Если задача с `needs` использует `resource_group`, она может быть заблокирована до освобождения ресурса, даже если зависимости завершены.
- **`needs` и `trigger`:** Дочерние пайплайны (trigger) не могут быть зависимостями `needs` напрямую.
- **`needs` и `retry`:** Если зависимая задача упала и перезапущена, `needs` будет ждать её успешного завершения.

### Масштабирование

- **Монорепозитории:** Используйте `needs: []` для быстрого фидбека от линтеров и валидаторов, параллельно с тяжелыми сборками.
- **Микросервисы:** `needs:project` позволяет связать пайплайны разных сервисов без API-скриптов.
- **Большие матрицы (50+ задач):** Используйте `needs:parallel:matrix` для связывания 1:1, чтобы избежать "fan-out" и исчерпания квоты артефактов.

## Дополнительная информация

-   **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовые концепции, стадии, артефакты и переменные.
-   **[Продвинутые рабочие процессы](./gitlab_ci_advanced_workflow.md)** — архитектурные паттерны, Fan-in/Fan-out, Merge Queue, Security.
-   **[Матричные сборки и сериализация](./workflow_rules/matrix_builds_and_serialization.md)** — `parallel:matrix`, `resource_group`, оптимизация артефактов.
-   **[Обзор Runner и Executor](../gitlab_ci_runners_executors.md)** — изоляция и типы исполнителей.
-   **[Окружения и развертывания](../../Concepts/environments_and_deployments.md)** — deployment approvals и protected environments.
-   **[Кэширование и артефакты](../gitlab_ci_caching/caching_overview.md)** — стратегии кэширования.
-   **[Артефакты в GitLab CI](../gitlab_ci_caching/gitlab_ci_artifacts.md)** — artifacts, reports, retention.
-   **[Родительско-дочерние пайплайны](../Downstream_Pipelines/parent_child_pipelines.md)** — bridge jobs и downstream пайплайны.
-   **[Compliance и Audit](../compliance_and_audit.md)** — compliance pipelines и approval rules.
-   **[Container Registry](../container_registry.md)** — интеграция Registry с CI/CD пайплайнами.
-   **[Pipeline Schedules](../pipeline_schedules.md)** — cron-расписания и Scheduled Execution Policies.
