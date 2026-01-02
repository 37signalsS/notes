# Проектирование комплексного CI/CD пайплайна: Практический пример

**Исходные данные:**
*   Существует приложение, написанное на Python.
*   Приложение еще не контейнеризировано.
*   Бюджет ограничен, поэтому мы будем использовать преимущественно бесплатные инструменты.

**Цель:**
Построить "идеальный" CI/CD пайплайн, который автоматизирует сборку, тестирование и развертывание приложения, следуя лучшим практикам.

## 2. Дизайн и планирование

### 2.1. Основные этапы
1.  **Контейнеризация:** Упаковать Python-приложение в Docker-контейнер.
2.  **Оркестрация:** Разворачивать приложение в кластер Kubernetes.
3.  **Тестирование:** Интегрировать в пайплайн максимальное количество видов тестов.
4.  **Release-цикл:** Определить и внедрить стратегию ветвления и релизов.
5.  **Инструменты:** Использовать GitLab CI, максимально задействовав его бесплатный функционал.

### 2.2. Стратегия ветвления и релизов (Git Flow)

*   **`feature-` ветки:** Вся разработка (новые функции, исправления) ведется в отдельных ветках. Жизненный цикл этих веток может быть как коротким, так и длинным.
*   **`develop` ветка:** Основная ветка для разработки. Feature-ветки сливаются в `develop` через Merge Request'ы (с обязательным код-ревью).
*   **`master` ветка:** Стабильная ветка, из которой формируются релизы. Ветка `develop` периодически сливается в `master`.

### 2.3. Стратегия окружений

*   **Production:** На это окружение разворачиваются только релизы, созданные из тегов в ветке `master`.
*   **Staging:** На это окружение разворачивается содержимое ветки `master`. Оно служит для финального, расширенного тестирования перед релизом.
*   **Development (Dev):** На это окружение разворачивается содержимое ветки `develop`.

> **Примечание:** Динамические окружения (Review Apps) для каждой feature-ветки являются возможным улучшением в будущем, но на данном этапе не реализуются для упрощения.

### 2.4. Стратегия тестирования и "Ворота качества" (Quality Gates)

#### **Критерии для слияния `feature` -> `develop`:**
*   Код-ревью пройдено.
*   Отсутствуют синтаксические ошибки (линтинг).
*   Docker-образ успешно собирается.
*   Проходят все **Unit-тесты**.
*   Проходят базовые тесты безопасности (**SAST**).

#### **Критерии для слияния `develop` -> `master`:**
*   Все предыдущие критерии выполнены.
*   Успешно проходят все **интеграционные тесты**.
*   Приложение успешно развернуто в `dev` окружение.
*   План развертывания (dry-run) в `staging` окружение выполняется без ошибок.

#### **Критерии для создания релиза (Production):**
*   Приложение успешно развернуто в `staging` окружение.
*   Все тесты на `staging` окружении проходят.
*   План развертывания (dry-run) в `production` окружение выполняется без ошибок.
*   Получено **ручное подтверждение** на развертывание (практика **Continuous Delivery**).

### 2.5. Выбор инструментов

*   **CI/CD:** **GitLab CI** — как основа всего процесса.
*   **Тестирование:** **Pytest** — для написания и запуска unit- и интеграционных тестов.
*   **Сборка образов:** **Kaniko** — для безопасной сборки Docker-образов без использования привилегированного режима Docker-in-Docker.
*   **Безопасность (SAST):** Встроенные шаблоны GitLab CI.
*   **E2E / Smoke тесты:** **cURL** — для простых health-check'ов, так как приложение не имеет сложного UI.
*   **Развертывание:** **Helm** — как стандарт де-факто для упаковки и управления приложениями в Kubernetes.
*   **Уведомления:** **Slack** — для оповещений о статусе выполнения пайплайнов.

---

## 3. Часть 1: Анализ проекта и создание скелета пайплайна

На этом шаге мы проанализируем структуру предоставленного нам Python-приложения и создадим базовую структуру (`скелет`) нашего `.gitlab-ci.yml` файла, который будет служить основой для дальнейшей автоматизации.

### 3.1. Обзор кодовой базы

Приложение представляет собой простой веб-сервис на базе **Flask**.

-   **`application/`**: Директория с исходным кодом.
    -   `__init__.py`: Основной файл Flask-приложения. Определяет два эндпоинта:
        -   `/`: Отдает точное время, полученное с NTP-сервера.
        -   `/version`: Отдает версию приложения из переменной окружения.
    -   `helpers.py`: Вспомогательная логика.
-   **`tests/`**: Директория с тестами на базе `pytest`.
    -   `unit/`: Модульные тесты для проверки отдельных компонентов.
    -   `integration/`: Интеграционные тесты для проверки совместной работы компонентов.
-   **`requirements.txt`**: Основные зависимости для работы приложения.
-   **`requirements-dev.txt`**: Дополнительные зависимости для разработки и тестирования.

### 3.2. Создание скелета `.gitlab-ci.yml`

Основываясь на нашем плане, мы создаем первоначальную версию `.gitlab-ci.yml` с определенными стадиями и пустыми задачами (placeholders). Это позволяет нам сразу заложить правильную структуру и логику работы пайплайна.

```yaml
# 1. Глобальные правила запуска всего пайплайна
workflow:
  rules:
    # Запускать для Merge Request'ов в develop или main
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && ($CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop" || $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main")'
    # Запускать при прямых пушах в develop или main
    - if: '$CI_COMMIT_BRANCH == "main" || $CI_COMMIT_BRANCH == "develop"'
    # Запускать при создании тега
    - if: '$CI_COMMIT_TAG'
    # Запускать при ручном старте из UI
    - if: '$CI_PIPELINE_SOURCE == "web"'

# 2. Определение последовательности стадий
stages:
  - linting
  - building
  - testing
  - deployment
  - validate_deployment
  - release

# 3. Шаблон для линтинга с использованием YAML-якоря
.lint_template: &lint_rules
  stage: linting
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

pylint:
  <<: *lint_rules # Наследование правил
  script:
    - echo "Running pylint..."

black:
  <<: *lint_rules # Наследование правил
  script:
    - echo "Running black..."

# 4. Стадия сборки
build-docker:
  stage: building
  script:
    - echo "Building docker image..." # Placeholder

# 5. Шаблоны правил для тестирования
.test_rules_template:
  develop: &develop_rules
    rules:
      - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop"'
      - if: '$CI_COMMIT_BRANCH == "develop"'
  main: &main_rules
    rules:
      - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"'
      - if: '$CI_COMMIT_BRANCH == "main"'

# 6. Задачи тестирования
unit-tests:
  stage: testing
  <<: *develop_rules # Запускать для develop и MR в него
  script:
    - echo "Running unit tests..." # Placeholder

integration-tests:
  stage: testing
  <<: *main_rules # Запускать для main и MR в него
  script:
    - echo "Running integration tests..." # Placeholder

security-tests-develop:
  stage: testing
  <<: *develop_rules
  script:
    - echo "Running security tests for develop..." # Placeholder

security-tests-main:
  stage: testing
  <<: *main_rules
  script:
    - echo "Running security tests for main..." # Placeholder

# 7. Задачи развертывания
deploy-dev:
  stage: deployment
  script:
    - echo "Deploying to dev..." # Placeholder
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

deploy-staging:
  stage: deployment
  script:
    - echo "Deploying to staging..." # Placeholder
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy-production:
  stage: deployment
  script:
    - echo "Deploying to production..." # Placeholder
  rules:
    - if: '$CI_COMMIT_TAG'
      when: manual # Только вручную по кнопке

# 8. Задачи валидации развертывания
validate-dev-smoke:
  stage: validate_deployment
  script:
    - echo "Running smoke tests on dev..." # Placeholder
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

validate-staging-e2e:
  stage: validate_deployment
  script:
    - echo "Running E2E tests on staging..." # Placeholder
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

# 9. Стадия релиза
create-release:
  stage: release
  script:
    - echo "Creating release tag..." # Placeholder
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual # Только вручную
```

#### Ключевые моменты структуры:

-   **`workflow:rules`**: Глобально контролирует, будет ли пайплайн запускаться в принципе. Это первая линия фильтрации.
-   **`stages`**: Четко определяют порядок выполнения задач.
-   **`rules` (внутри `job`)**: Контролируют запуск конкретной задачи в уже запущенном пайплайне.
-   **YAML Anchors/Aliases (`&` и `*`)**: Якоря, такие как `&lint_rules`, `&develop_rules`, позволяют нам определять набор правил один раз и переиспользовать его в нескольких задачах, что значительно сокращает дублирование кода.
-   **Placeholders (`echo "..."`)**: На данном этапе реальные команды заменены на "заглушки". Это позволяет проверить общую логику и последовательность пайплайна, убедиться, что он успешно проходит, прежде чем наполнять его реальной функциональностью.

---

## 4. Часть 2: Реализация стадий сборки и тестирования

В этой части мы заменим "заглушки" из нашего скелета `.gitlab-ci.yml` на реальные реализации для стадий `linting`, `building` и `testing`.

### 4.1. Оптимизация и кеширование зависимостей

Прежде чем запускать тесты или линтеры, необходимо установить зависимости. Чтобы не делать это на каждой задаче с нуля, мы оптимизируем процесс.

-   **`default:image`**: Устанавливаем `python:3.9` как образ по умолчанию для всех задач.
-   **`default:before_script`**: Определяем стандартный блок команд, который будет выполняться перед каждой задачей. Он создает виртуальное окружение `venv` и устанавливает в него зависимости из `requirements-dev.txt`.
-   **`default:cache`**: Включаем кеширование для директории `.venv`, чтобы зависимости сохранялись между запусками пайплайна, значительно ускоряя их выполнение.

### 4.2. Реализация стадии `building` (Сборка Docker-образа)

Задача `build-docker` теперь будет собирать реальный Docker-образ с помощью **Kaniko**.

#### Динамические теги для образов
Мы используем секцию `workflow:rules` не только для контроля запуска, но и для определения **переменных**, в данном случае — тега Docker-образа (`DOCKER_IMAGE_TAG`). Это позволяет создавать уникальные и предсказуемые теги для разных событий:
-   Для MR в `develop`: `dev-pr-<ID>`
-   Для коммитов в `main`: `main-<ID_пайплайна>`
-   Для Git-тегов (`v*`): `v1.2.3` (чистый тег)

#### `Dockerfile` и `.dockerignore`
-   **`Dockerfile`**: Используется **многостадийная сборка (multi-stage build)**.
    1.  На первой стадии в полном образе Python устанавливаются все зависимости.
    2.  На второй стадии берется минималистичный "distroless" образ от Google, в который копируются только код приложения и готовые зависимости из первой стадии. В итоге получается очень маленький и безопасный образ без лишних компонентов (shell, пакетный менеджер и т.д.).
-   **`.dockerignore`**: Добавлен, чтобы исключить из контекста сборки ненужные файлы (`.venv`, `.idea` и т.д.), что ускоряет процесс.

#### Код задачи `build-docker`
```yaml
build-docker:
  stage: building
  image:
    name: gcr.io/kaniko-project/executor:v1.9.0-debug
    entrypoint: [""]
  script:
    # Создаем конфигурационный файл для Kaniko, чтобы он мог аутентифицироваться в GitLab Registry
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    # Запускаем сборку
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      # В качестве destination используем переменные GitLab и нашу кастомную DOCKER_IMAGE_TAG
      --destination $CI_REGISTRY_IMAGE:$DOCKER_IMAGE_TAG
```

### 4.3. Реализация стадии `testing`

#### Юнит- и интеграционные тесты
Задачи `unit-tests` и `integration-tests` теперь запускают `pytest`, указывая на соответствующие директории с тестами. Они наследуют `before_script` и `cache` для быстрой установки зависимостей.

```yaml
unit-tests:
  stage: testing
  <<: *develop_rules
  script:
    - pytest tests/unit

integration-tests:
  stage: testing
  <<: *main_rules
  script:
    - pytest tests/integration
```

#### Тесты безопасности
Мы используем встроенные шаблоны GitLab для автоматического сканирования безопасности.

-   **`include`**: В `.gitlab-ci.yml` добавляются три шаблона:
    -   `Security/SAST.gitlab-ci.yml`: Статический анализ кода на уязвимости.
    -   `Security/Secret-Detection.gitlab-ci.yml`: Поиск секретов (паролей, ключей), случайно попавших в репозиторий.
    -   `Security/Container-Scanning.yml`: Сканирование готового Docker-образа на известные уязвимости в его компонентах.

-   **Кастомизация**: Мы переопределяем задачи из шаблонов, чтобы настроить правила их запуска с помощью наших якорей `&develop_rules` и `&main_rules`.
    -   `sast` и `secret-detection` запускаются для веток `develop` и `main`.
    -   `container-scanning`, как более длительный тест, запускается только для ветки `main`.

```yaml
# ... (в начале файла)
include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
  - template: Security/Container-Scanning.yml

# ... (в секции stages)

# Переопределяем задачи из шаблонов для кастомизации правил
sast:
  <<: *develop_rules

secret_detection:
  <<: *develop_rules

container_scanning:
  stage: testing
  <<: *main_rules
```
> Примечание: `sast` и `secret_detection` автоматически подхватывают стадию `test`. Для `container_scanning` может потребоваться явно указать стадию.

После этих изменений наш пайплайн не только проверяет качество кода и запускает тесты, но и выполняет комплексную проверку безопасности, автоматически блокируя изменения, которые несут в себе риски.

---

## 5. Часть 3: Реализация стадий развертывания (Deployment)

Теперь, когда у нас есть протестированный и упакованный в Docker-образ артефакт, мы можем реализовать логику его развертывания в наши Kubernetes-окружения (`dev`, `staging`, `production`).

### 5.1. Подготовка: Helm-чарт и доступ к кластеру

-   **Helm-чарт**: Для деплоя используется базовый Helm-чарт, созданный командой `helm create`. Ключевые изменения в нем:
    -   В `values.yaml` и шаблоне `deployment.yaml` добавлена поддержка `imagePullSecrets` для доступа к приватному GitLab Container Registry.
    -   Версия приложения передается в контейнер через переменную окружения `VERSION`, которая берется из `{{ .Values.image.tag }}`.
-   **Доступ к Kubernetes**: Для взаимодействия с кластером (в данном примере используется Amazon EKS) в CI/CD переменных проекта (`Settings > CI/CD > Variables`) необходимо настроить учетные данные облачного провайдера (например, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` и др.).
-   **Доступ к Registry**: В кластере Kubernetes необходимо вручную создать секрет типа `docker-registry`, содержащий `Deploy Token` с правом `read_registry`. Этот секрет затем указывается в Helm-чарте в `imagePullSecrets`.

### 5.2. Реализация задач `deployment` в `.gitlab-ci.yml`

Чтобы избежать дублирования кода, создается общий шаблон `.deploy_template`, от которого наследуются все задачи развертывания.

#### Шаблон `.deploy_template`
Этот шаблон содержит общую логику для всех окружений:
-   **`image`**: Используется кастомный Docker-образ, содержащий все необходимые утилиты: `kubectl`, `helm`, `aws-cli`.
-   **`before_script`**: Устанавливает плагин `helm-diff` и настраивает `kubectl` для доступа к кластеру в AWS.
-   **`script`**: Главная логика, которая в зависимости от наличия переменных `HELM_DIFF` или `HELM_APPLY` выполняет либо `helm diff` (показывает изменения, не применяя их), либо `helm upgrade --install` (применяет изменения).

```yaml
.deploy_template:
  stage: deployment
  image: darthvad1r/kube-helm-aws:1.0.0 # Образ с нужными инструментами
  before_script:
    - helm plugin install https://github.com/databus23/helm-diff
    - aws eks --region us-east-1 update-kubeconfig --name slurm-eks-cluster
    - kubectl version
  script:
    - |
      if [[ -n "$HELM_DIFF" ]]; then
        helm diff upgrade --allow-unreleased <имя-релиза> ./helm
      elif [[ -n "$HELM_APPLY" ]]; then
        helm upgrade --install <имя-релиза> ./helm --set image.tag=$DOCKER_IMAGE_TAG
      else
        echo "Skipping deployment step..."
      fi
```

#### Задачи развертывания
Задачи для каждого окружения (`deploy-dev`, `deploy-staging`, `deploy-production`) наследуют этот шаблон и добавляют свою специфику.

-   **`environment`**: Для каждой задачи определяется окружение, что позволяет отслеживать деплои в интерфейсе GitLab. Указывается `name` и `url` окружения.
-   **`rules`**: Правила определяют, когда запускать деплой (`HELM_APPLY`) и когда — только проверку изменений (`HELM_DIFF`). Например, для MR в `develop` будет запущен `helm diff`, а для прямого коммита в `develop` — `helm upgrade`.
-   **Авторизация для Production**: Задача `deploy-production` содержит дополнительный `before_script`, который проверяет, входит ли пользователь, запустивший задачу (`$GITLAB_USER_LOGIN`), в список авторизованных (`$AUTHORIZED_USERS`). Это простой, но эффективный способ ограничить права на выкатку в прод.

```yaml
deploy-staging:
  extends: .deploy_template
  variables:
    # Динамический URL для доступа к приложению в staging
    ENDPOINT: http://<...>.us-east-1.elb.amazonaws.com
  environment:
    name: staging
    url: $ENDPOINT
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"'
      variables:
        HELM_DIFF: "true" # Для MR в main запускаем только diff
    - if: '$CI_COMMIT_BRANCH == "main"'
      variables:
        HELM_APPLY: "true" # Для коммитов в main - применяем

deploy-production:
  extends: .deploy_template
  # ...
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      when: manual # Для тегов - ручной запуск
      variables:
        HELM_APPLY: "true"
  before_script:
    # Скрипт проверки авторизации
    - |
      if ! echo "$AUTHORIZED_USERS" | grep -q "$GITLAB_USER_LOGIN"; then
        echo "User $GITLAB_USER_LOGIN is not authorized to deploy to production."
        exit 1
      fi
    # ... (далее стандартный before_script из шаблона)
```


### 5.3. Результат в интерфейсе GitLab

После выполнения пайплайна во вкладке **Deployments > Environments** можно увидеть список всех окружений, историю развертываний для каждого из них, а также перейти по ссылке к работающему приложению. Проверка эндпоинта `/version` подтверждает, что в окружении развернута корректная версия образа, соответствующая тегу, сгенерированному в пайплайне.

---

## 6. Часть 4: Валидация, релизы и полный цикл

Это заключительная часть, в которой мы реализуем финальные стадии пайплайна — `validate_deployment` и `release`, а также демонстрируем полный рабочий процесс от feature-ветки до релиза в production.

### 6.1. Реализация стадии `validate_deployment`

После развертывания приложения в окружение, необходимо убедиться, что оно работает корректно.

-   **Smoke-тесты (`validate-dev-smoke`)**: Это простая проверка "на дым". Мы используем `curl`, чтобы отправить запрос на `ENDPOINT` нашего приложения и убедиться, что оно отвечает кодом `200 OK`.
-   **E2E-тесты (`validate-staging-e2e`)**: Это более осмысленная проверка. Мы также используем `curl` для запроса к эндпоинту `/version` и с помощью `grep` проверяем, что в ответе содержится правильный тег docker-образа, который был развернут на этой стадии. Это подтверждает, что выкатка прошла успешно и в окружении работает именно то, что мы ожидали.

```yaml
validate-staging-e2e:
  stage: validate_deployment
  image: curlimages/curl:7.75.0
  script:
    - |
      CONTENT=$(curl $ENDPOINT/version)
      if ! echo "$CONTENT" | grep -q "$DOCKER_IMAGE_TAG"; then
        echo "Version check failed!"
        exit 1
      else
        echo "Version check passed. Found version $DOCKER_IMAGE_TAG."
      fi
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### 6.2. Реализация стадии `release`

Эта стадия отвечает за создание официальных релизов.

-   **Задача `create-release`**: Запускается вручную из ветки `main`.
-   **Инструмент**: Используется сторонний инструмент для семантического версионирования (например, `semantic-release` или его аналоги). Он анализирует коммиты с момента последнего тега, автоматически определяет новую версию (patch, minor, major), генерирует `CHANGELOG` и создает новый Git-тег и GitLab Release.
-   **Авторизация**: Для работы этому инструменту требуется **GitLab Access Token** с правами `api`, который хранится в CI/CD-переменных.

```yaml
create-release:
  stage: release
  image: node:16-alpine # Пример, если используется JS-based релизер
  script:
    - npm install -g semantic-release @semantic-release/gitlab
    - semantic-release
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

### 6.3. Интеграция с Slack

Для получения уведомлений о статусе пайплайнов, можно настроить интеграцию со Slack:
1.  В настройках проекта GitLab перейдите в **Settings > Integrations**.
2.  Выберите **Slack notifications**.
3.  Активируйте интеграцию и вставьте **Incoming Webhook URL**, полученный из Slack.
4.  Выберите, по каким событиям отправлять уведомления (например, `failed pipeline`).
Для более кастомизированных уведомлений потребуется написать собственный скрипт, который будет отправлять сообщения через API Slack.

### 6.4. Демонстрация полного цикла

1.  **Feature-ветка -> `develop`**:
    -   Разработчик создает `feature/my-new-feature` и пушит код.
    -   Создается **Merge Request** в ветку `develop`.
    -   Запускается пайплайн для MR: `linting` -> `build-docker` -> `unit-tests` -> `sast` -> `secret-detection` -> `helm diff` (dry-run для dev).
    -   После успешного прохождения всех проверок и код-ревью MR сливается в `develop`.

2.  **Коммит в `develop`**:
    -   Слияние запускает новый пайплайн уже на самой ветке `develop`.
    -   Выполняются те же шаги, но вместо `helm diff` происходит реальное развертывание (`helm upgrade`) в **dev-окружение**.
    -   После деплоя запускается `validate-dev-smoke`, чтобы убедиться, что окружение работает.

3.  **`develop` -> `main` (подготовка к релизу)**:
    -   Создается **Merge Request** из `develop` в `main`.
    -   Запускается пайплайн для MR: `linting` -> `build-docker` -> `integration-tests` -> `container-scanning` -> `helm diff` (dry-run для staging).
    -   После слияния в `main` запускается пайплайн, который разворачивает приложение в **staging-окружение** и прогоняет на нем `validate-staging-e2e` тесты.

4.  **Релиз в Production**:
    -   Когда команда готова к релизу, менеджер вручную запускает задачу `create-release` из ветки `main`.
    -   Инструмент релиза создает новый тег (например, `v1.2.3`) и GitLab Release с описанием изменений.
    -   Создание тега автоматически запускает пайплайн для этого тега, в котором становится доступна ручная задача `deploy-production`.
    -   Авторизованный пользователь нажимает кнопку "Play", и приложение разворачивается в **production-окружение**.
