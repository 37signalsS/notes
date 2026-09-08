# Rancher Pipelines — конвейеры доставки (Legacy)

## Определения

**Rancher Pipelines** — устаревший и полностью удаленный механизм CI/CD (Continuous Integration / Continuous Delivery), который был интегрирован непосредственно в платформу Rancher. Система базировалась на Jenkins и обеспечивала базовую автоматизацию сборки образов и их деплоя через веб-интерфейс Rancher.

**Статус на 2026 год:** Инструмент **удален** из платформы с версии **v2.7.0** (выпущена в 2023 г.). Его использование в современных инсталляциях невозможно. Документация сохранена для понимания исторического контекста и облегчения миграции устаревших репозиториев, содержащих конфигурационные файлы `.rancher-pipeline.yml`.

### Хронология жизненного цикла (исторически значимо для миграции)

| Этап | Версия | Дата | Событие |
| :--- | :--- | :--- | :--- |
| **Внедрение** | v2.0.x | 2019 г. | Пайплайны как встроенная функция CI/CD. |
| **Deprecation** | **v2.5.0** | 2020 г. | Объявлено устаревание; функционал доступен через feature flag `legacy`. |
| **Ограничение K8s** | v2.5+ | 2021 г. | Пайплайны **не поддерживаются на Kubernetes v1.21+** (подсистема Jenkins/CD несовместима с новыми версиями). |
| **Removal** | **v2.7.0** | 2023 г. | Полностью удалены из UI и backend (раздел «Removed Legacy Features» в release notes). |
| **EOL** | — | 2023+ | Функция недоступна в любых актуальных инсталляциях Rancher Manager. |

Роль замены перешла к **Rancher Continuous Delivery** на базе **Fleet** (GitOps) и отдельным CI-системам (GitHub Actions, GitLab CI).

## Базовые концепции

### Архитектура решения (архивные данные)

Механизм работал по эфемерной модели:
1.  **Управляющий компонент:** Rancher Server выступал в роли оркестратора.
2.  **Исполнители (Agents):** При запуске пайплайна Rancher динамически создавал под с Jenkins Agent в том кластере/namespace, где был настроен проект.
3.  **Хранение:** Состояние и логи хранились в Persistent Volume, подключенном к Jenkins-мастеру (управляемому Rancher).
4.  **Безопасность:** Использовались встроенные секреты Rancher для доступа к Docker Registry и Git-репозиториям.

### Модель пайплайна: этапы и шаги (архивный формат)

Конфигурация задавалась либо через UI, либо файлом `.rancher-pipeline.yml` (или `.rancher-pipeline.yaml`) в корне репозитория. Структура наследовала логику Jenkins и состояла из **Stages** (этапов) и **Steps** (шагов):

*   **Stages (этапы):** выполняются строго последовательно; следующий этап начинается только после полного завершения предыдущего.
*   **Steps (шаги):** внутри одного этапа выполняются **параллельно** (concurrently).
*   **Conditions (условия):** как на этапе, так и на шаге можно задавать триггерные условия через `when: { branch, event }`.
*   **Timeout:** глобальный таймаут пайплайна в минутах.
*   **Notification:** конфигурация уведомлений (каналы и условия отправки).

Доступные типы шагов:

| Тип шага | Ключ в YAML | Назначение |
| :--- | :--- | :--- |
| **Run Script** | `runScriptConfig` | Выполнение произвольных команд в контейнере (build, test, lint) внутри workspace. |
| **Build & Publish Image** | `publishImageConfig` | Сборка Docker-образа и опциональная публикация в удалённый registry. |
| **Deploy YAML** | `applyYamlConfig` | Применение Kubernetes-манифеста из репозитория. |
| **Deploy Catalog App** | `applyAppConfig` | Установка/обновление приложения из каталога (catalog) Rancher. |
| **Publish Catalog Template** | `publishCatalogConfig` | Публикация Helm-шаблона в отдельный Git-репозиторий каталога. |

Каждый шаг поддерживал продвинутые параметры: собственные environment-переменные (`env`), импорт секретов проекта (`envFrom. sourceName/sourceKey/targetKey`), условия запуска.

#### Переменные подстановки пайплайна (Pipeline Variable Substitution)

Во время выполнения пайплайна переменные `CICD_*` подставляются в скрипты, теги образов и манифесты. Ключевые из них:

| Переменная | Описание |
| :--- | :--- |
| `CICD_GIT_REPO_NAME` | Имя репозитория (без организации). |
| `CICD_GIT_URL` | URL Git-репозитория. |
| `CICD_GIT_COMMIT` | SHA коммита, по которому выполняется сборка. |
| `CICD_GIT_BRANCH` | Ветка события. |
| `CICD_GIT_REF` | Git ref события. |
| `CICD_GIT_TAG` | Имя тега (для события `tag`). |
| `CICD_EVENT` / `CICD_TRIGGER_TYPE` | Тип триггера (`push`, `pull_request`, `tag`). |
| `CICD_PIPELINE_ID` / `CICD_PIPELINE_NAME` | Идентификатор и имя пайплайна. |
| `CICD_EXECUTION_SEQUENCE` | Номер сборки пайплайна. |
| `CICD_EXECUTION_ID` | Составной идентификатор `{CICD_PIPELINE_ID}-{CICD_EXECUTION_SEQUENCE}`. |
| `CICD_REGISTRY` | Адрес registry из предыдущего шага публикации образа. |
| `CICD_IMAGE` | Имя образа, собранного на предыдущем шаге (без тега). |

Для шага публикации образа использовались также `Docker`-специфичные переменные (`PLUGIN_INSECURE`, `PLUGIN_BUILD_ARGS`, `PLUGIN_DEBUG`, `PLUGIN_MIRROR` и др.), передаваемые через `env` шага.

### Полный пример архивной конфигурации `.rancher-pipeline.yml`

```yaml
# Архивный полный пример (v2.5/2.6)
branch:
  include: [ master, feature/* ]
  exclude: [ dev ]
timeout: 30

notification:
  recipients:
    - recipient: "#mychannel"
      notifier: "c-wdcsr:n-c9pg7"
    - recipient: "test@example.com"
      notifier: "c-wdcsr:n-lkrhd"
  condition: [ "Failed", "Success", "Changed" ]

stages:
  - name: Build and test
    when:
      branch: master
      event: [ push, pull_request ]
    steps:
      - runScriptConfig:
          image: golang
          shellScript: go build ./...
        env:
          CGO_ENABLED: "0"
        envFrom:
          - sourceName: my-secret
            sourceKey: secret-key
            targetKey: ALIAS_ENV
  - name: Publish image
    steps:
      - publishImageConfig:
          dockerfilePath: ./Dockerfile
          buildContext: .
          imageName: registry.example.com/myapp:${CICD_GIT_COMMIT}
          pushRemote: true
  - name: Deploy
    steps:
      - applyYamlConfig:
          path: ./k8s/deployment.yaml
```

> Подставляемые переменные `CICD_GIT_COMMIT`, `CICD_IMAGE`, `CICD_REGISTRY` могли использоваться в манифестах Kubernetes для деплоя собранного образа без ручного фиксирования тега.

### Причины отказа от встроенных пайплайнов

1.  **Сложность поддержки:** Содержание Jenkins внутри Rancher требовало значительных ресурсов и усложняло обновление платформы.
2.  **Переход к GitOps:** Индустрия сместилась в сторону декларативного управления (Pull-модель), реализованного в Rancher через Fleet.
3.  **Несовместимость с K8s 1.21+:** встроенная подсистема CD строилась на устаревших API, несовместимых с новыми версиями Kubernetes.
4.  **Специализация инструментов:** Внешние CI-системы (GitLab, GitHub) предоставляют значительно более широкие возможности масштабирования и безопасности.

## Практические сценарии миграции

### Стратегия миграции (2026)

Для замены функционала Rancher Pipelines в современной инфраструктуре используется разделение ответственности (Separation of Concerns):

| Функция | Устаревший инструмент | Современная замена (2026) |
| :--- | :--- | :--- |
| **Сборка и тесты (CI)** | Rancher Pipelines | GitHub Actions, GitLab CI, Gitea Actions |
| **Доставка в кластер (CD)** | Rancher Pipelines | **Fleet** (нативно), ArgoCD, Flux |
| **Управление Jenkins** | Встроено в Rancher | Отдельный Helm-чарт `jenkins/jenkins` |

### Пример архивной конфигурации `.rancher-pipeline.yml`

Если вы обнаружили этот файл в корне репозитория, его необходимо переписать под современные стандарты.

```yaml
# Архивный пример (v2.5/2.6)
stages:
  - name: Build
    steps:
      - publishImageConfig:
          dockerfilePath: ./Dockerfile
          imageName: registry.example.com/myapp:${CICD_GIT_COMMIT}
          pushRemote: true
  - name: Deploy
    steps:
      - applyYamlConfig:
          path: ./k8s/deployment.yaml
```

**Инструкция по миграции:**
1.  **Секция `publishImageConfig`:** Перенесите в `.github/workflows/main.yml` (используя `docker/build-push-action`) или `.gitlab-ci.yml` (используя `kaniko` или `docker-in-docker`).
2.  **Секция `applyYamlConfig`:** Замените на создание **GitRepo** в интерфейсе Fleet или добавление приложения в ArgoCD.

### Миграция CI-части в GitHub Actions

Для репозиториев на GitHub типовой миграцией является GitHub Actions + GitHub Container Registry (GHCR). Замена шага `publishImageConfig`:

```yaml
# .github/workflows/main.yml
name: build-and-push

on:
  push:
    branches: [ master ]

env:
  IMAGE: ghcr.io/${{ github.repository }}:${{ github.sha }}

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write          # право публиковать в GHCR
    steps:
      - uses: actions/checkout@v4

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: ${{ env.IMAGE }}
```

**Объяснение параметров:**
*   `permissions.packages: write` — обязательное разрешение для публикации в пакеты GHCR (замена встроенных учётных данных Rancher).
*   `secrets.GITHUB_TOKEN` — автоматический токен GitHub, используется вместо личного API-ключа.
*   `github.sha` — заменяет `${CICD_GIT_COMMIT}`; тег образа соответствует коммиту.

**Проверка результата:** после push образ должен появиться в Packages репозитория; далее его можно забрать через Fleet/ArgoCD по тегу.

### Миграция CI-части в GitLab CI + Kaniko

Для GitLab типовым вариантом является сборка через **Kaniko** (без привилегированного Docker daemon). Kaniko — это самый безопасный способ сборки в кластере: подробности и настройка — в [Kaniko (сборка образов)](../../Docker/Dockerfile/dockerfile_kaniko.md). Подробные примеры пайплайнов — в [Примеры пайплайнов GitLab CI](../../CI-CD/GitLab_CI/Tutorials/gitlab_ci_pipeline_examples.md).

```yaml
# .gitlab-ci.yml (фрагмент сборки и публикации образа)
stages:
  - build
  - deploy

variables:
  IMAGE: registry.gitlab.com/$CI_PROJECT_PATH:$CI_COMMIT_SHA

build:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:debug
    entrypoint: [""]
  script:
    - /kaniko/executor
      --context "${CI_PROJECT_DIR}"
      --dockerfile "${CI_PROJECT_DIR}/Dockerfile"
      --destination "${IMAGE}"
  rules:
    - if: $CI_COMMIT_BRANCH == "master"

# Пример деплоя в K8s через kubeconfig/Service Account (без Fleet) — см. kubeconfig_and_connection
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl set image deployment/myapp myapp=${IMAGE} -n production
  rules:
    - if: $CI_COMMIT_BRANCH == "master"
```

**Объяснение параметров:**
*   `image.name: kaniko executor:debug` + `entrypoint: [""]` — обязательная обёртка для запуска Kaniko как CI-задачи.
*   `--destination ${IMAGE}` — заменяет `pushRemote: true` из Rancher; registry определяется из URL проекта GitLab.
*   Переменные `CI_PROJECT_PATH`, `CI_COMMIT_SHA` — встроенные переменные GitLab, аналог `CICD_*`.

Конкретный развёрнутый пример GitLab CI + деплой в Kubernetes — в [Руководство по GitLab CI для деплоя (Spring Boot)](../../CI-CD/GitLab_CI/Tutorials/spring_boot_gitlab_ci_deploy.md).

### Использование Fleet для CD (GitOps-путь)

Fleet является основным наследником функционала деплоя в Rancher. 
*   **Преимущество:** Fleet автоматически отслеживает изменения в Git и синхронизирует состояние кластера.
*   **Масштабируемость:** Один "Bundle" Fleet может быть развернут на тысячи кластеров одновременно на основе селекторов (Labels).
*   **Полная методология GitOps** (включая ArgoCD/Flux, модели Push/Pull) — в [GitOps: Обзор](../../GitOps/GitOps_overview.md).

**Типовой сценарий «построили образ в CI, доставили во Fleet»:**

1.  **CI-система** собирает образ и публикует его в registry (GHCR/GitLab Registry/Harbor).
2.  **CI-система** обновляет тег образа в манифесте в Git-репозитории приложений (например, через `helm set` или `kustomize edit set image`).
3.  **Fleet** (GitRepo, указывающий на репозиторий приложений) автоматически применяет изменения в целевых кластерах по Pull-модели.

Схема пути: `CI (сборка) → Registry → Git (манифесты) → Fleet (CD) → Kubernetes`.

### Автономный Jenkins как альтернатива (если команда сохраняет Jenkins)

Если организация сознательно сохраняет Jenkins, его следует развернуть как внешний отдельный компонент, а не как встроенный в Rancher. Применяется стандартный подход установки по Helm-чарту `jenkins/jenkins` (собственный release, свои PersistentVolume). Rancher при этом используется только для управления кластером, а не для хоста Jenkins.

**Рекомендации для автономного Jenkins в Kubernetes:**
*   Используйте Kubernetes-плагин Jenkins для динамических Pod-агентов (канал как у Rancher Pipelines, но полностью под вашим контролем).
*   Храните секреты в Jenkins Credentials или внешних менеджерах secret (см. ниже).
*   Уведомления отправляйте через плагины или webhook (аналог блока `notification` из `.rancher-pipeline.yml`).
*   Доставку (CD) выполняйте через Fleet/ArgoCD, Jenkins отвечает только за сборку и тесты (Separation of Concerns).

## Диагностика и устранение неполадок

### Обнаружение устаревших артефактов пайплайнов

Для поиска репозиториев, требующих миграции, просканируйте их на наличие архивных файлов:

```bash
# Найти архивные конфиги пайплайнов в Git-репозиториях
find /srv/git -maxdepth 3 -name ".rancher-pipeline.yml" -o -name ".rancher-pipeline.yaml" 2>/dev/null

# Проверить наличие в текущем репозитории
[ -f .rancher-pipeline.yml ] && echo "Найден архивный .rancher-pipeline.yml — требуется миграция"
```

### При попытке использовать пайплайны в современных версиях

*   **Симптом:** в UI отсутствует раздел Pipelines/вариант создания пайплайна.
*   **Причина:** функция удалена в v2.7.0, feature flag `legacy` больше не включается.
*   **Решение:** перейти на Fleet (CD) + внешнюю CI-систему, как описано в стратегии миграции.

### Ошибки при запуске CI после миграции

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `denied: requested access to the resource is denied` при push в registry | Отсутствует вход в registry / нет разрешения. | Проверьте `docker/login-action` и `permissions.packages: write` (GitHub) или CI_JOB_TOKEN (GitLab). |
| Kaniko: `failed to authenticate with registry` | Нет `--destination` / нет доступа к registry. | Убедитесь в настройке пары registry в переменных CI. |
| GitLab runner не видит docker daemon | Используется `docker-in-docker` без настроенного Docker-in-Docker. | Переключитесь на Kaniko (без daemon) или настройте DinD; см. `docker-in-docker`. |
| Деплой не нашёл образ по тегу | CI ещё не загрузил образ в registry, а CD уже дёрнул манифест. | Убедитесь в последовательности стадий: push → обновление Git → Fleet. |

## Дополнительная информация

### Безопасность при миграции

*   **Registry Credentials:** Вместо встроенных учетных записей пайплайнов используйте `ImagePullSecrets` на уровне Namespace.
*   **CI/CD Tokens:** Для связи внешних CI-систем с Rancher создавайте **Service Accounts** с ограниченными правами в нужном кластере/проекте, а не используйте личные API-ключи администраторов.
*   **Подключение к кластеру:** как правильно формировать kubeconfig и Service Account для CI/CD — в [Подключение и kubeconfig](../../Kubernetes/Operations/kubeconfig_and_connection.md).
*   **Секреты:** современные подходы к управлению секретами в K8s и их внешние менеджеры — в [Управление секретами](../../Kubernetes/Base/secrets/creating_secrets.md) и [Внешние менеджеры секретов](../../Kubernetes/Base/secrets/external_managers.md).

### Рекомендации по оптимизации сборки

Независимо от выбранной CI-системы, используйте современные методы сборки:
*   **Multi-stage builds:** Для уменьшения размера финального образа (см. [Оптимизация Dockerfile](../../Docker/Dockerfile/Docker_best_practices/build_optimization.md)).
*   **BuildKit:** Для ускорения сборки через кэширование слоев (см. [BuildKit](../../Docker/Dockerfile/dockerfile_buildkit.md)).
*   **Rootless:** Сборка образов (например, через Kaniko) без привилегий root для повышения безопасности CI-агентов.
*   **Определение один раз — применение много раз:** объединяйте одинаковые шаги/скрипты в переиспользуемые компоненты (GitLab `include`, GitHub reusable workflows); полный список антипаттернов CI/CD — в [Антипаттерны CI/CD](../../CI-CD/ci_cd_antipatterns.md).

### Проверка успешности миграции (чек-лист)

1.  Архивный `.rancher-pipeline.yml` удалён из всех активных веток.
2.  CI собирает образ по коммиту/тегу и публикует в registry (образ виден в UI Registry).
3.  CD (Fleet/ArgoCD) применяет манифесты с новым тегом в целевой кластер (`kubectl get pods` показывает новый образ).
4.  `ImagePullSecrets` для приватного registry созданы в namespace приложения.
5.  Уведомления о статусе сборок приходят в рабочие каналы.

---

**См. также:**

*   [Rancher: Обзор платформы](./rancher_overview.md) — актуальные компоненты (Fleet, NeuVector).
*   [GitOps: Обзор концепции](../../GitOps/GitOps_overview.md) — современная методология доставки.
*   [Секреты Kubernetes](../../Kubernetes/Base/secrets/creating_secrets.md) — управление учетными данными в K8s.

**Внешние ресурсы:**

*   [Fleet Documentation](https://fleet.rancher.io/) — официальный гид по замене CD-части пайплайнов.
*   [GitLab CI/CD Documentation](https://docs.gitlab.com/ee/ci/) — для реализации CI-части.
