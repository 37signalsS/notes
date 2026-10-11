# Комплексный CI/CD пайплайн для Python-проекта

**Актуально для:** GitLab 19.x, Python 3.11+, Kubernetes 1.27+

## Определения

**Комплексный CI/CD Pipeline** — полностью автоматизированный процесс жизненного цикла ПО, включающий проверку качества кода, многоуровневое тестирование, сборку артефактов и автоматизированное развертывание в различные среды.

**`uv`** — сверхбыстрый менеджер пакетов и установщик Python, написанный на Rust. К 2026 году является индустриальным стандартом для CI/CD благодаря экстремальной скорости установки (до 10-100 раз быстрее `pip`) и встроенной поддержке виртуальных окружений.

**`ruff`** — высокопроизводительный линтер и форматер кода для Python, заменяющий собой целый стек инструментов (Flake8, isort, Black). Позволяет значительно ускорить стадию валидации.

**`id_tokens` (OIDC)** — современный механизм аутентификации (стандарт 2026 года), позволяющий GitLab Runner безопасно взаимодействовать с внешними сервисами (Vault, внешние системы, Kubernetes) без использования долгоживущих секретов на основе доверия между провайдером личности (GitLab) и потребителем.

**GitLab Agent for Kubernetes (KAS)** — основной инструмент для безопасной интеграции GitLab с кластером. Обеспечивает двусторонний канал связи (**CI/CD Tunnel**), исключающий необходимость экспонирования API кластера наружу или хранения `KUBECONFIG` в переменных.

**SBOM (Software Bill of Materials)** — формализованный перечень всех библиотек и зависимостей, необходимый для аудита безопасности и соответствия стандартам цепочки поставок (**SLSA**).

## Основные концепции

### Архитектура и принцип Fail Fast

Современный пайплайн строится по принципу **Fail Fast**: наиболее быстрые и критичные проверки выполняются первыми. Это экономит ресурсы раннеров и время разработчиков.

1. **Стратегия ветвления (GitLab Flow):**
    - **`feature/*`**: Проходят стадию `validate` (линтеры, типы) и `unit-tests`.
    - **`develop`**: Проходит полный цикл проверок и деплоится в **Development**.
    - **`main`**: Финальные интеграционные тесты и деплой в **Staging**.
    - **Git-теги (`v*.*.*`)**: Инициируют релизный цикл с деплоем в **Production**.

2. **Zero Trust в CI/CD:**
    - Отказ от статических паролей и токенов в пользу кратковременных OIDC-токенов (`id_tokens`).
    - Использование GitLab Agent (KAS) с RBAC-ограничениями на уровне конкретных namespaces.
    - Сканирование образов и зависимостей на каждом этапе сборки.

3. **Оптимизация Python-сред:**
    - **Контейнеризация:** Использование Multi-stage Docker-сборок для минимизации размера и поверхности атаки.
    - **Управление зависимостями:** Использование `uv.lock` для гарантии детерминированности сборок.
    - **Кэширование:** Разделение кэша для загрузки пакетов (`uv cache`) и результатов тестирования.

## Практические сценарии

### Предварительные требования

**Инфраструктура:**
- **GitLab:** Версия 19.x (для KAS и `id_tokens`).
- **Kubernetes:** Кластер 1.27+ с доступом через kubectl или GitLab Agent (KAS).
- **Docker/Kaniko:** Раннер с Docker Executor или Kubernetes Executor (Kaniko работает без привилегий).
- **Python:** Версии 3.11+ (для `uv` и современных возможностей типа `type` hints).

**Инструменты (автоматически устанавливаются в CI через Docker-образы):**
- `uv` — менеджер пакетов (образ `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`).
- `ruff` — линтер и форматер (устанавливается через `uvx`).
- `Kaniko` — безопасная сборка Docker без привилегий (образ `gcr.io/kaniko-project/executor`).

**Переменные CI/CD (Settings > CI/CD > Variables):**
| Переменная | Тип | Назначение |
| :--- | :--- | :--- |
| `KUBE_CONTEXT` | Variable | Имя контекста Kubernetes в GitLab (формат: `group/project/k8s-agent:agent-name`). |
| `CI_REGISTRY_PASSWORD` | **File** (опционально) | Пароль для приватного Registry (если не используется автоматическая авторизация). |
| `SONAR_TOKEN` | **File** (опционально) | Токен для SonarQube (если включён SAST-анализ). |

**Базовые знания:**
- Основы Python: модули, пакеты, `pyproject.toml`, `uv`/`pip`.
- Основы Docker: Dockerfile, multi-stage builds, `.dockerignore`.
- Основы Kubernetes: Deployment, Service, HPA, Namespace.
- Основы GitLab CI/CD: stages, rules, variables, artifacts, templates.

### Реализация пайплайна в `.gitlab-ci.yml`

#### Шаг 1: Глобальные настройки и правила

Используем `workflow:rules` для фильтрации запусков и типизации тегов образов.

```yaml
variables:
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.uv-cache"
  DOCKER_IMAGE_TAG: $CI_COMMIT_SHORT_SHA
  KUBE_CONTEXT: "my-group/infra:prod-agent"

workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      variables:
        DOCKER_IMAGE_TAG: "mr-$CI_MERGE_REQUEST_IID"
    - if: '$CI_COMMIT_BRANCH == "develop"'
      variables:
        DOCKER_IMAGE_TAG: "dev-$CI_COMMIT_SHORT_SHA"
    - if: '$CI_COMMIT_BRANCH == "main"'
      variables:
        DOCKER_IMAGE_TAG: "staging-$CI_COMMIT_SHORT_SHA"
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      variables:
        DOCKER_IMAGE_TAG: $CI_COMMIT_TAG

stages:
  - validate
  - build
  - test
  - deploy
  - release

include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
  - template: Security/Container-Scanning.yml
  - template: Security/Dependency-Scanning.gitlab-ci.yml

default:
  image: ghcr.io/astral-sh/uv:python3.13-bookworm-slim
  cache:
    key:
      files:
        - uv.lock
    paths:
      - .uv-cache
```

#### Шаг 2: Валидация и Сборка (Ruff + Kaniko)

```yaml
linting:
  stage: validate
  script:
    - uvx ruff check .
    - uvx ruff format --check .
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

build_and_sbom:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.28.3
    entrypoint: [""]
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination $CI_REGISTRY_IMAGE:$DOCKER_IMAGE_TAG
    # Генерация SBOM с использованием Syft
    - pip install anchore-syft
    - syft $CI_REGISTRY_IMAGE:$DOCKER_IMAGE_TAG -o cyclonedx-json=sbom.json
  artifacts:
    reports:
      cyclonedx: sbom.json
  ```

**Валидация сборки:**
```bash
# Проверка, что образ собран и имеет правильный тег
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/repositories" \
  | jq '.[] | select(.name == "app") | .tags[] | select(.name == "staging-$CI_COMMIT_SHORT_SHA")'
# → {"name": "staging-abc1234", "manifest_path": "/manifest.json"}

# Проверка размера образа
skopeo inspect docker://$CI_REGISTRY_IMAGE:$DOCKER_IMAGE_TAG --format '{{.Size}}'
# → 24567890 (примерно 24 МБ)

# Проверка SBOM
cat sbom.json | jq '.components | length'
# → 42 (количество зависимостей)
```

#### Шаг 3: Тестирование с использованием uv

```yaml
.pytest_base:
  stage: test
  script:
    - uv sync --frozen
    - uv run pytest tests/unit --junitxml=report.xml
  artifacts:
    reports:
      junit: report.xml

unit_tests:
  extends: .pytest_base
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.11", "3.12", "3.13"]

integration_tests:
  extends: .pytest_base
  script:
    - uv run pytest tests/integration
  rules:
    - if: $CI_COMMIT_BRANCH == "main" || $CI_COMMIT_BRANCH == "develop"
  ```

**Валидация тестов:**
```bash
# Проверка JUnit-отчёта в артефактах
# В UI GitLab: Pipeline → job `unit_tests` → Tests: отображаются результаты pytest
# Или через API:
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$JOB_ID/trace" \
  | grep -E "passed|failed|error"
# → 42 passed, 0 failed

# Проверка coverage (если настроен pytest-cov)
uv run pytest tests/unit --cov=app --cov-report=term-missing
# → Name                    Stmts   Miss  Cover
# → app/__init__.py            12      0   100%
```

#### Шаг 4: Деплой через GitLab Agent (KAS) и Helm

```yaml
.helm_deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  id_tokens:
    K8S_TOKEN:
      aud: https://kubernetes.default.svc.cluster.local
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - >
      helm upgrade --install $RELEASE_NAME ./charts/app
        --namespace $NAMESPACE
        --set image.tag=$DOCKER_IMAGE_TAG
        --wait --atomic

deploy_dev:
  extends: .helm_deploy
  variables:
    RELEASE_NAME: "python-app-dev"
    NAMESPACE: "dev"
  environment:
    name: development
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

deploy_prod:
  extends: .helm_deploy
  variables:
    RELEASE_NAME: "python-app-prod"
    NAMESPACE: "production"
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      when: manual
  ```

**Валидация деплоя:**
```bash
# Проверка статуса Deployment
kubectl rollout status deployment/python-app -n app-dev --timeout=120s
# → deployment "python-app" successfully rolled out

# Проверка, что поды запущены и готовы
kubectl get pods -n app-dev -l app=python-app
# → NAME                    READY   STATUS    RESTARTS   AGE
# → python-app-xxx          1/1     Running   0          30s

# Проверка health endpoint
kubectl port-forward deployment/python-app -n app-dev 8080:8080 &
curl http://localhost:8080/health
# → {"status":"ok"}

# Проверка Helm-релиза
helm list -n app-dev
# → NAME            NAMESPACE       REVISION    UPDATED                                 STATUS      CHART
# → python-app-dev  app-dev         1           2026-09-28 15:30:00.000000 +0300 MSK    deployed    app-1.0.0
```

## Технические нюансы и Тюнинг

### Оптимизация кэширования
Для Python-проектов при использовании `uv` критично кэшировать директорию `.uv-cache`. В отличие от `pip`, `uv` использует глобальный кэш для всех виртуальных окружений, что позволяет избежать повторной загрузки и компиляции пакетов (wheel) даже при смене версии Python в матрице тестов.

### Безопасность через ID Tokens
Использование `id_tokens` в сочетании с GitLab Agent (KAS) позволяет реализовать модель **Workload Identity Federation (WIF)**. Раннер получает временный JWT, который Kubernetes (или Vault) проверяет через OIDC. Это полностью устраняет риск компрометации статических токенов доступа.

### Тюнинг Docker-образа
Для Python в 2026 году рекомендуется использовать многостадийную сборку (multi-stage):
1.  **Stage 1 (Builder):** Установка `uv`, компиляция зависимостей, экспорт виртуального окружения.
2.  **Stage 2 (Runtime):** Использование максимально легкого базового образа (например, `distroless` или `python-slim`). Копирование только готового окружения.
3.  **Non-root:** Обязательный запуск приложения от пользователя с ограниченными правами (UID > 1000).

### Архитектура Runner для Python-пайплайнов

Для Python-приложений выбор executor'а определяется требованиями к изоляции, скорости и доступности ресурсов:

| Executor | Изоляция | Скорость | Рекомендация для Python |
| :--- | :--- | :--- | :--- |
| **`kubernetes`** | Высокая (Pod) | Средняя | Стандарт для production: каждый job в отдельном Pod, автоматическая очистка. |
| **`docker`** | Средняя (контейнер) | Высокая | Подходит для сред с постоянным раннером; требует DinD или Kaniko для сборки образов. |
| **`shell`** | Отсутствует | Максимальная | Только для локальных разработческих задач и сборок, требующих direct HW access. |

**SRE: Конфигурация Kubernetes Executor для Python:**
```yaml
# config.toml фрагмент
[[runners]]
  name = "python-build-runner"
  executor = "kubernetes"
  [runners.kubernetes]
    image = "ghcr.io/astral-sh/uv:python3.13-bookworm-slim"
    cpu_limit = "1"
    memory_limit = "2Gi"
    cpu_request = "250m"
    memory_request = "512Mi"
    service_account = "gitlab-runner"
    namespace = "gitlab-runners"
    poll_interval = 5
    cache_dir = "/cache"
```

**Важно:** Для jobs с `uv sync` и установкой зависимостей выделяйте минимум 1 ГБ RAM — `uv` может потреблять значительную память при компиляции wheels для C-расширений (numpy, pandas).

### Мониторинг и алертинг пайплайнов

**Метрики здоровья пайплайнов (Prometheus + GitLab Exporter):**
- `gitlab_ci_pipeline_duration_seconds` — время выполнения пайплайна по стадиям.
- `gitlab_ci_job_failed_total` — количество упавших задач по проектам.
- `gitlab_runner_jobs_duration_seconds` — время выполнения задач на конкретном раннере.

**Ключевые алерты:**
- `PipelineFailed` — пайплайн упал в `main` или защищённой ветке.
- `JobStuck` — задача висит в `pending` дольше `timeout` из-за нехватки раннеров.
- `UVOOM` — job с `uv sync` упал по OOM (требует увеличения лимитов).
- `VulnerabilityFound` — `pip-audit` или `ruff` обнаружил CVE высокого/критического уровня.
- `CacheMiss` — кэш `uv` не восстановился (возможна проблема с Distributed Cache).

### Compliance и Supply Chain

**SBOM и артефакты:**
- Сохраняйте `sbom.json` (CycloneDX) как артефакт каждого `build_and_sbom` job — это требуется для SOC2/PCI-DSS аудита.
- Настройте retention policy для артефактов: `90 дней` для SBOM, `30 дней` для бинарных файлов.
- Используйте `rules:changes` для запуска `ruff` и `pip-audit` только при изменении `pyproject.toml` или `uv.lock`.

**Аудит сборки:**
- Включите audit log в GitLab для отслеживания, кто запускал деплой в production.
- Храните Docker-образы в приватном Registry с включённым vulnerability scanning.
- Используйте image tags на основе `$CI_COMMIT_SHORT_SHA`, а не `latest` — обеспечивает traceability.

### Инцидент-респонс для пайплайнов

При падении production-деплоя или критической уязвимости:

1.  **Остановка пайплайнов:** Переключите защищённую ветку в `Settings > Repository > Protected branches` и снимите флаг `Allowed to merge` на время расследования.
2.  **Откат образа:** Удалите проблемный тег через GitLab Registry API и выполните `kubectl rollout undo` в production namespace.
3.  **Аудит:** Проверьте, какой коммит и кто инициировал пайплайн: `git log --oneline $CI_COMMIT_SHA`. Проверьте audit log GitLab на предмет несанкционированных запусков.
4.  **Ротация секретов:** Если подозрение на утечку — отзовите `VAULT_TOKEN` и перегенерируйте секреты. Проверьте `vault token lookup` для compromised токенов.
5.  **Постмортем:** Зафиксируйте время инцидента, этап падения (`validate`/`test`/`deploy`), root cause и действия по исправлению. Обновите runbook.

### Жизненный цикл раннера (Runner Lifecycle)

- Ротируйте `glrt-` токены раннеров каждые 90 дней. Устаревшие registration tokens отключены в GitLab 17.0+ и удалены в 20.0.
- Настройте `concurrent` и `limit` в `config.toml` для предотвращения перегрузки раннеров.
- Используйте `check_interval = 3` для быстрого подхвата задач, но не меньше 2 секунд чтобы не создавать лишнюю нагрузку на GitLab API.
- При обновлении раннера используйте rolling update: остановите приём новых задач, дождитесь завершения текущих, обновите бинарник, проверьте `gitlab-runner verify`, запустите.

### Сеть и изоляция

- Настройте NetworkPolicy для namespace `gitlab-runners`, разрешающую только egress к GitLab API, Container Registry и Vault.
- Используйте отдельный ServiceAccount для runner'ов с минимальными привилегиями. Не используйте `default` SA.
- Для Kubernetes Executor включите `pod_annotations` для отслеживания владельца job в Kubernetes.

## Валидация и проверка

Для подтверждения успешной работы пайплайна выполните следующие действия:
1.  **Проверка визуализации тестов:** Убедитесь, что во вкладке **Tests** пайплайна отображаются результаты `pytest` (благодаря JUnit артефактам).
2.  **Аудит SBOM:** Скачайте артефакт `sbom.json` и проверьте его через `trivy sbom sbom.json` на наличие известных уязвимостей.
3.  **Логи KAS:** Проверьте вывод команды деплоя: там должен быть статус `atomic success`, подтверждающий корректный выкат в Kubernetes.

## Устранение неисправностей (Troubleshooting)

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`uv sync` fails** | Несоответствие `uv.lock` и `pyproject.toml` | Обновите lock-файл локально: `uv lock` и закомитьте его. Проверьте: `uv lock --check`. |
| **`KAS Context not found`** | Ошибка в имени проекта или агента | Проверьте формат: `group/project:agent-name`. Убедитесь, что агент разрешен для текущего проекта в `config.yaml`. |
| **`Permission denied` в Kaniko** | Неверные данные в `config.json` | Проверьте переменные `$CI_REGISTRY_USER` и пароль. Попробуйте использовать `id_tokens` для Registry. |
| **Тесты падают по таймауту** | Недостаточно ресурсов у раннера | Оптимизируйте тесты или увеличьте лимиты в конфигурации GitLab Runner (`concurrent`, `limit`). |
| **`ModuleNotFoundError` в тестах** | Пакет не установлен в виртуальном окружении | Убедитесь, что `pyproject.toml` содержит все зависимости. Запустите `uv sync` локально. |
| **`ruff` не находит файлы** | Неверная директория запуска | Убедитесь, что `working_directory` соответствует корню проекта. Проверьте наличие `pyproject.toml` в текущей директории. |
| **Helm deploy падает с `timeout`** | Под не переходит в Ready | Проверьте `kubectl describe pod -n <ns>`. Увеличьте `--timeout` или добавьте `readinessProbe` в Deployment. |
| **`id_tokens` не работает** | OIDC не настроен в Vault/Kubernetes | Убедитесь, что `KUBE_CONTEXT` указывает на правильный агент. Проверьте OIDC-проверку: `kubectl auth can-i create pods --as=system:serviceaccount:ns:sa`. |
| **Docker-образ больше 1GB** | Нет multi-stage или не установлены dev-зависимости | Используйте `uv sync --no-dev` в runtime-стадии. Убедитесь, что `__pycache__` и `.git` исключены через `.dockerignore`. |
| **SBOM пустой или некорректный** | Syft не может прочитать бинарник Python | Используйте `syft dir:.` вместо `syft bin/app`. Для Python SBOM анализируйте `pyproject.toml` и `uv.lock`. |
| **`pip-audit` не находит уязвимости** | Устаревшая база данных | Обновите: `uv run pip-audit --strict --desc --fix`. Проверьте версию `pip-audit` — требуются свежие данные. |
| **Кэш не восстанавливается** | Неверный `key` или изменение файлов манифеста | Используйте `cache:key:files` с привязкой к `uv.lock`. Не используйте `key: $CI_COMMIT_REF_SLUG` без `files`.
| **`uv sync` падает по OOM** | Недостаточно RAM при установке C-зависимостей | Увеличьте `memory_limit` раннера до 2-4 ГБ. Используйте `uv sync --no-dev` для сокращения зависимостей. |
| **`ruff` падает с segfault** | Устаревшая версия или конфликт плагинов | Обновите `ruff` до последней версии. Проверьте `ruff --version`. Убедитесь, что нет конфликтов с `flake8`/`pylint` в той же среде. |
| **`pytest` паникает в CI** | Отсутствуют переменные окружения или секреты | Используйте `--env` в конфигурации runner'а или `variables:` в job. Проверьте `pytest -v` с локальными переменными. |
| **SBOM не генерируется** | Syft не может прочитать pyproject.toml | Убедитесь, что `syft` установлен через `pip install anchore-syft`. Проверьте путь к проекту: `syft dir:.` вместо `syft bin/app`. |
| **`git clone` зависает** | Large repo или нехватка диска на runner'е | Используйте `GIT_STRATEGY: fetch` и `GIT_DEPTH: 1` для поверхностного клонирования. Увеличьте диск runner'а до 50 ГБ. |
| **`pip-audit` слишком медленный** | Большой граф зависимостей | Запускайте `pip-audit` только при изменении `pyproject.toml` через `rules:changes`. Используйте `--ignore-vuln` для известных принятых рисков. |
| **Image pull backoff в K8s** | Неверный tag или нет доступа к Registry | Проверьте `image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}`. Убедитесь, что `imagePullSecret` настроен. |
| **`interruptible: true` не отменяет job** | Job уже запущен на runner'е | `interruptible` работает только на уровне планирования. Убедитесь, что runner'ы поддерживают отмену через API. |
| **`uv lock` mismatch в CI** | Кастомный `UV_INDEX_URL` меняет разрешение | Используйте один и тот же индекс в CI и локально. Проверьте: `uv lock --check`. |
| **`pytest` xdist: отчёты пустые** | Воркеры пишут в отдельные файлы | Используйте `--json-report` с `pytest-json-report` или `--junitxml=report-${CI_NODE_INDEX}.xml`. |
| **`distroless` образ не запускается** | Отсутствует SHELL или_entrypoint_ошибка | Проверьте: `docker run --rm --entrypoint "" <image> ls /app`. Убедитесь, что бинарник скомпилирован корректно. |
| **`PYTHONDONTWRITEBYTECODE` не работает** | Переменная установлена после импорта | Установите `ENV PYTHONDONTWRITEBYTECODE=1` в Dockerfile до COPY приложения. |
| **`tini` не обрабатывает сигналы** | Не установлен как PID 1 | Используйте `--init` в `docker run` или добавьте `tini` в Dockerfile: `ENTRYPOINT ["/sbin/tini", "--"]`. |
| **`uv` cache повреждён** | Неполная запись при OOM kill | Очистите кэш: `uv cache clean`. В CI используйте `cache:key:files` с привязкой к `uv.lock`. |
| **Helm upgrade падает с `already exists`** | Релиз уже развёрнут в другом namespace | Проверьте: `helm list --all-namespaces | grep python-app`. Убедитесь, что `--namespace` указан корректно. |
| **NetworkPolicy блокирует egress** | Runner не может выйти к GitLab API | Проверьте egress-правила: runner должен иметь доступ к порту 443 для GitLab API, Registry и Vault. |

## Лучшие практики (Best Practices)

**Безопасность:**
- Всегда используйте `uv sync --frozen` в CI — это гарантирует, что зависимости не изменятся между сборками.
- Не храните пароли и токены в `CI/CD Variables` в открытом виде — используйте File-тип или Vault OIDC.
- Включите Security-шаблоны: `SAST`, `Secret-Detection`, `Container-Scanning`, `Dependency-Scanning`.
- Запускайте `pip-audit --strict` для проверки зависимостей на известные CVE.
- Используйте `distroless` или `python-slim` для runtime-стадии — минимизация поверхности атаки.

**Производительность:**
- Кэшируйте `.uv-cache` — это сокращает время установки зависимостей на 80–90%.
- Используйте `parallel:matrix` для тестирования на нескольких версиях Python одновременно.
- Настройте `cache:key:files` с привязкой к `uv.lock` — кэш пересобирается только при изменении зависимостей.
- Используйте `uvx ruff check --new-from-rev=HEAD~1` в MR — проверяет только изменённый код.

**Надёжность:**
- Используйте `extends: .pytest_base` для единообразия конфигурации тестирования.
- Задавайте `timeout:` для каждой задачи — предотвращает зависание пайплайна.
- Используйте `retry: 2` для network-dependent задач (pip install, helm pull).
- Тестируйте Docker-образ локально перед коммитом: `docker build -t app:test . && docker run --rm app:test`.

**Мониторинг и observability:**
- Экспортируйте метрики Python-приложения через `prometheus_client` ('gc', 'http_requests_total').
- Настройте `livenessProbe` и `readinessProbe` в Kubernetes Deployment.
- Используйте structured logging (`structlog` или `logging` с JSON-форматом) для парсинга в Kibana/Grafana.

**Жизненный цикл раннера (Runner Lifecycle):**
- Ротируйте `glrt-` токены раннеров каждые 90 дней. Устаревшие registration tokens отключены в GitLab 17.0+ и удалены в 20.0.
- Настройте `concurrent` и `limit` в `config.toml` для предотвращения перегрузки раннеров.
- Используйте `check_interval = 3` для быстрого подхвата задач, но не меньше 2 секунд чтобы не создавать лишнюю нагрузку на GitLab API.
- При обновлении раннера используйте rolling update: остановите приём новых задач, дождитесь завершения текущих, обновите бинарник, проверьте `gitlab-runner verify`, запустите.

**Сеть и изоляция:**
- Настройте NetworkPolicy для namespace `gitlab-runners`, разрешающую только egress к GitLab API, Container Registry и Vault.
- Используйте отдельный ServiceAccount для runner'ов с минимальными привилегиями. Не используйте `default` SA.
- Для Kubernetes Executor включите `pod_annotations` для отслеживания владельца job в Kubernetes.

## Очистка и откат (Cleanup)

**Откат Docker-образа в Registry:**
```bash
# Удаление конкретного тега через API GitLab
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/repositories/<repo_id>/tags/<tag>"

# Полная очистка неиспользуемых образов ( garbage collection )
# Включите Cleanup Policy в GitLab: Settings > Packages and Registries > Cleanup policy
```

**Откат Kubernetes-деплоя:**
```bash
# Откат на предыдущую ревизию
kubectl rollout undo deployment/python-app -n app-prod

# Откат на конкретную ревизию
kubectl rollout undo deployment/python-app -n app-prod --to-revision=3

# Проверка истории
kubectl rollout history deployment/python-app -n app-prod
```

**Очистка артефактов CI:**
```bash
# Удаление артефактов через API (TTL)
# Настройте в Settings > CI/CD > Artifacts expiration

# Ручная очистка через крон
kubectl delete jobs -l app=gitlab-runner -n gitlab-runner
```

**Очистка кэша Python:**
```bash
# Локальная очистка
uv cache clean
rm -rf .venv

# В CI: автоматически через policy expiration в Settings > CI/CD > Caching
```

## Граничные случаи (Edge Cases)

**Мультиплатформенная сборка (linux/amd64, linux/arm64):**
- Используйте `docker buildx` с `--platform=linux/amd64,linux/arm64`.
- Для Kaniko: `--platform=linux/amd64,linux/arm64` в `executor` args.
- Не используйте QEMU-эмуляцию — нативная кросс-компиляция в 10 раз быстрее.

**Монорепозиторий (несколько Python-проектов):**
- Используйте `rules:changes` для запуска тестов только затронутых проектов.
- Настройте `ruff` с `--project` для указания конкретного конфига.

**Интеграция с Vault (секреты):**
- Используйте OIDC для аутентификации GitLab → Vault (без статических секретов).
- См. **[Vault + Kubernetes Integration](../../../Vault/guides/vault_kubernetes_integration.md)**.

**Python-приложение с C-зависимостями (numpy, pandas):**
- Используйте `python:3.13-bookworm` вместо `slim` — включает dev-пакеты для компиляции.
- В Dockerfile: `RUN apt-get update && apt-get install -y gcc g++`.

**Высокая нагрузка в CI (>100 коммитов/день):**
- Используйте `rules:workflow` для дедупликации пайплайнов.
- Настройте `interruptible: true` для MR — это отменяет предыдущие запуски.
- Используйте distributed cache (S3/MinIO) вместо локального кэша раннера.

**Интеграция с ArgoCD:**
- Пайплайн CI только собирает образ и обновляет его версию в GitOps-репозитории.
- ArgoCD синхронизирует состояние кластера через Pull-модель.
- См. **[Обзор ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md)**.

**Дедупликация тестов в матрице:**
- При `parallel:matrix` с несколькими версиями Python убедитесь, что `uv cache` разделяется между задачами.
- Используйте `needs: [linting]` для параллельного запуска тестов на разных версиях.

**Disaster Recovery (DR):**
- Поддерживайте SLA на восстановление пайплайнов: RTO < 15 минут, RPO < 5 минут.
- Храните `config.toml` и `glrt-` токены раннеров в защищённом хранилище (HashiCorp Vault или аналоги) для быстрого восстановления.
- Регулярно тестируйте откат на предыдущий стабильный образ в staging-среде.

**Compliance и аудит:**
- Включите audit log в GitLab (`/var/log/gitlab/audit/`) для отслеживания всех запусков пайплайнов в production.
- Настройте retention для артефактов CI: `90 дней` для SBOM, `30 дней` для бинарных файлов.
- Регулярно проверяйте `bound_claims` и политики Vault (если используется OIDC) — удаляйте неиспользуемые роли.

**Сеть и DNS:**
- Используйте внутренний DNS (CoreDNS) для разрешения `gitlab.example.com` и `vault.example.com` внутри кластера.
- Настройте NetworkPolicy для namespace `gitlab-runners`, разрешающую только необходимые порты (443 для GitLab API, 5000 для Registry).
- Проверяйте egress-правила: runner'ы должны иметь доступ к GitLab API, Container Registry и Vault API.

**Гонки и детерминированность:**
- Для воспроизводимых сборок используйте `SOURCE_DATE_EPOCH` и pinned версии базовых образов.
- Запускайте `uv lock --check` в CI для проверки целостности `uv.lock`.
- Используйте pinned версии базовых образов по дайджесту (`ghcr.io/astral-sh/uv:python3.13.15-bookworm-slim@sha256:...`) вместо тегов.

## Дополнительная информация

### Смотрите также

- **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — детальная настройка KAS.
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — управление доступом через OIDC.
- **[Dockerfile для Python](../../../Docker/Dockerfile/Docker_best_practices/python.md)** — глубокая оптимизация сборки, multi-stage, uv.
- **[Python-менеджер: uv](../../../Linux/Development/python_management.md)** — установка, конфигурация, pyproject.toml.
- **[Кэширование в GitLab CI](../Advanced/gitlab_ci_caching/cache_scenarios.md)** — стратегии кэширования для Python/uv.
- **[Начальное руководство для Python](./beginner_guide_python_app.md)** — базовый пайплайн с Flask, pytest, Docker.
- **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)** — архитектура, executor'ы, безопасность.
- **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)** — пошаговая регистрация и лучшие практики.

### SRE: Наблюдаемость пайплайнов
- **События:** Используйте GitLab CI/CD observability features для экспорта метрик в Prometheus.
- **Трейсинг:** Для investigation медленных пайплайнов используйте встроенную timeline view в GitLab UI.
- **Golden Signals:** Мониторьте latency, throughput, error rate и saturation для каждого stage пайплайна.
- **События Runner'ов:** Мониторьте `gitlab_runner_jobs_duration_seconds` и `gitlab_runner_jobs_failed_total` для ранней диагностики проблем с инфраструктурой.
