# Стратегии организации репозиториев и модели ветвления в GitOps

**Актуально для:** Argo CD v2.10–v3.x, Flux v2.2–v2.4+, Kubernetes 1.28–1.32+ (On-Premise / Bare-Metal)

Руководство для DevOps-инженеров, SRE и системных администраторов по проектированию структуры Git-репозиториев, выбору топологии хранения манифестов и моделей ветвления. Разбираются компромиссы между монорепозиториями и мультирепозиториями, причины, по которым ветки окружений признаны антипаттерном в продакшене, а также надежные паттерны продвижения артефактов (promotion) в изолированных корпоративных средах.

---

## Определения

| Термин | Определение |
| :--- | :--- |
| **Репозиторий приложения (App Repo)** | Репозиторий разработчиков, содержащий исходный код сервиса, модульные тесты, Dockerfile и манифесты конвейера CI (например, `.gitlab-ci.yml`). |
| **Конфигурационный репозиторий (Config / Fleet Repo)** | Выделенный репозиторий манифестов Kubernetes (Kustomize/Helm), являющийся единственным источником правды (SSoT) для кластеров и обслуживаемый GitOps-контроллерами. |
| **Раздельный репозиторий (Split-Repo Pattern)** | Архитектурный паттерн полной физической изоляции исходного кода приложения от манифестов развертывания в разных Git-репозиториях. |
| **Environment Branches (Ветки окружений)** | Модель ветвления, при которой каждому окружению (`dev`, `stage`, `prod`) соответствует долгоживущая Git-ветка в одном репозитории. |
| **Directory-per-Environment (Окружение в каталоге)** | Модель организации, при которой все среды описаны в виде изолированных каталогов (`overlays/dev`, `overlays/prod`) внутри единой магистральной ветки `main`. |
| **Продвижение (Promotion)** | Контролируемый процесс переноса протестированной версии артефакта или набора параметров из менее критичной среды в более критичную (Dev → Staging → Prod). |
| **Дрейф веток (Branch Drift)** | Неконтролируемое расхождение кодовой базы или манифестов между долгоживущими ветками, приводящее к конфликтам слияния и непредсказуемому поведению. |
| **CODEOWNERS** | Декларативный конфигурационный файл Git-платформы (GitLab/GitHub), определяющий обязательных рецензентов (ревьюеров) для конкретных директорий или файлов. |

---

## Архитектура и базовые концепции

### 1. Топологии репозиториев: Monorepo vs Multi-repo vs Split-repo

В корпоративной практике On-Premise инфраструктуры выбор структуры репозиториев определяет сетевую безопасность, права доступа и стабильность CI/CD-пайплайнов:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        App Repo (Код сервиса)                          │
│  src/ + Dockerfile + .gitlab-ci.yml                                    │
│  [CI Runner: Сборка, Тесты, Trivy SAST, Сборка образа в Harbor]        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 1. Пуш образа & Дайджеста
                                    ▼
                     ┌─────────────────────────────┐
                     │ OCI Registry (Harbor Corp)  │
                     └──────────────┬──────────────┘
                                    │ 2. CI обновляет тег/дайджест
                                    ▼ (через MR или Commit)
┌────────────────────────────────────────────────────────────────────────┐
│                   Config / Fleet Repo (GitOps SSoT)                    │
│  apps/billing/overlays/prod/deployment-patch.yaml                      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 3. Pull-синхронизация
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  Kubernetes Cluster (Argo CD / Flux)                   │
│  Reconciliation Loop: Приведение etcd к состоянию ветки main           │
└────────────────────────────────────────────────────────────────────────┘
```

#### Сравнительный анализ топологий

| Критерий | Monorepo (Код + Манифесты вместе) | Multi-repo (Отдельный репо манифестов на сервис) | Split-repo / Config-Monorepo (Выделенный репо для всех манифестов) |
| :--- | :--- | :--- | :--- |
| **Разграничение RBAC** | Сложное: разработчики имеют доступ к манифестам продакшена. | Простое на уровне репозитория, но порождает сотни репозиториев. | **Идеальное:** разработчики имеют доступ только к App Repo, SRE управляет Config Repo. |
| **Триггеры CI/CD** | Риск паразитных циклов: коммит в манифест запускает полную пересборку кода. | Чистые триггеры, но сложно отслеживать зависимости между сервисами. | **Чистые триггеры:** CI правит только конкретный файл в Config Repo. |
| **Аудит изменений** | Размыт между коммитами разработчиков и релизными тегами. | Разрознен по десяткам репозиториев. | **Централизованный:** вся история развертываний кластера в одном месте. |
| **Масштабируемость** | Замедление `git clone` и git-операций со временем. | Высокие накладные расходы на администрирование репозиториев. | **Стабильная:** минимальный размер репозитория (только YAML-текст). |

**Рекомендация для продакшена:** Паттерн **Split-repo** с разделением на репозитории разработки (App Repos) и единый репозиторий манифестов инфраструктуры и приложений (Fleet/Config Monorepo).

---

### 2. Модели ветвления: почему Environment Branches — антипаттерн в GitOps

Исторически команды пытались перенести модель GitFlow на управление инфраструктурой, создавая ветки `development`, `staging` и `production`. В контексте GitOps этот подход приводит к деградации надежности:

```text
[АНТИПАТТЕРН: Environment Branches]

feature-branch ──► development ──(git merge)──► staging ──(git merge)──► production
                       ▲                            ▲                          ▲
                       │                            │                          │
                 ArgoCD Dev                   ArgoCD Stage               ArgoCD Prod

Проблема:
1. Конфликты при слиянии: в prod другие реплики (10 vs 2), другие ресурсы CPU/RAM,
   другие URL баз данных. `git merge` пытается затереть prod-конфигурацию настройками dev!
2. Cherry-pick ад: аварийный хотфикс в prod невозможно просто перенести назад без сайд-эффектов.
3. Дрейф веток: через 3 месяца ветки dev и prod имеют разную историю и не сливаются.
```

#### Анатомия проблем Environment Branches:

1. **Конфликты слияния конфигураций (Merge Hell):** Окружения отличаются не только версией образа, но и параметрами (размеры пулов коннектов, ingress-хосты, доступы). При попытке сделать `git merge staging -> production` Git пытается разрешить различия файлов значений, затирая специфичные для продакшена параметры настройками тестовой среды.
2. **Нарушение принципа детерминированности:** Ветви неизбежно расходятся по истории коммитов. Через несколько спринтов `production` накапливает сотни хотфиксов, отсутствующих в `development`, что делает прямой мердж невозможным.
3. **Ложное ощущение безопасности:** Успешный запуск манифеста в ветке `staging` не гарантирует, что при слиянии в `production` не возникнет конфликт разметки или непреднамеренное удаление блока переменных.

---

### 3. Целевой паттерн: Directory-per-Environment на базе Trunk-Based Development

Стандартом корпоративного GitOps является модель **одной магистральной ветки (`main`)**, где изоляция окружений достигается за счет каталогов и инструментов оверлеев (Kustomize или директорий значений Helm):

```text
[ПАТТЕРН: Directory-per-Environment в ветке main]

ветка main:
  ├── base/                         # Общие манифесты (Deployment, Service)
  └── overlays/
      ├── dev/                      # image: v1.3.0, replicas: 1, ingress: dev.corp
      ├── staging/                  # image: v1.2.0, replicas: 2, ingress: stage.corp
      └── production/               # image: v1.2.0, replicas: 10, ingress: prod.corp

Продвижение (Promotion):
- Изменение ТОЛЬКО тега или дайджеста образа в файле overlays/<env>/kustomization.yaml
- Никаких слияний веток. Все изменения проходят через Pull/Merge Request в main.
```

#### Преимущества модели:
- **Отсутствие конфликтов слияния:** Конфигурация продакшена никогда не смешивается с dev-конфигурацией.
- **Прозрачный аудит и история:** Любой инженер видит точное состояние всех сред в одном коммите ветки `main`.
- **Простая автоматизация:** Скрипту CI достаточно обновить одну строку с тегом образа в файле целевой директории.

---

## Практические сценарии и конфигурация

### Сценарий 1: Эталонная структура Split-repo с Kustomize Overlays

Структура корпоративного GitOps-репозитория манифестов для группы микросервисов:

```text
fleet-gitops-repo/
├── .gitlab/
│   └── CODEOWNERS                  # Разграничение прав на аппрув продакшена
├── apps/
│   └── billing-service/
│       ├── base/
│       │   ├── deployment.yaml
│       │   ├── service.yaml
│       │   └── kustomization.yaml
│       └── overlays/
│           ├── dev/
│           │   ├── kustomization.yaml
│           │   └── patches/
│           │       └── resources.yaml
│           ├── stage/
│           │   ├── kustomization.yaml
│           │   └── patches/
│           │       └── replicas.yaml
│           └── prod/
│               ├── kustomization.yaml
│               └── patches/
│                   ├── resources.yaml
│                   └── ingress.yaml
└── infrastructure/
    ├── cert-manager/
    └── ingress-nginx/
```

#### Базовый манифест сервиса
```yaml
# apps/billing-service/base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
```

```yaml
# apps/billing-service/base/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: billing-service
  template:
    metadata:
      labels:
        app.kubernetes.io/name: billing-service
    spec:
      containers:
        - name: app
          image: harbor.internal.corp/finance/billing-service:placeholder
          ports:
            - containerPort: 8080
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
```

#### Оверлей для Production
```yaml
# apps/billing-service/overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

# Неизменяемый образ с фиксацией по SHA256-дайджесту
images:
  - name: harbor.internal.corp/finance/billing-service
    newName: harbor.internal.corp/finance/billing-service
    digest: sha256:7f9b8c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b

patches:
  - path: patches/resources.yaml
```

```yaml
# apps/billing-service/overlays/prod/patches/resources.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
spec:
  replicas: 10
  template:
    spec:
      containers:
        - name: app
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2000m"
              memory: "2Gi"
```

---

### Сценарий 2: CI-пайплайн безопасного продвижения (Promotion) между средами

В репозитории приложения (`App Repo`) CI-пайплайн собирает образ, пушит его в корпоративный Harbor и автоматически инициирует обновление тега в `Config Repo` через выделенный служебный токен.

```yaml
# .gitlab-ci.yml в репозитории приложения (App Repo)
stages:
  - build-and-test
  - publish
  - promote-dev
  - promote-prod

variables:
  GITOPS_REPO: "git@git.internal.corp:platform/fleet-gitops.git"
  IMAGE_NAME: "harbor.internal.corp/finance/billing-service"

build-and-publish:
  stage: publish
  image: docker:27.0-cli
  script:
    - docker build -t ${IMAGE_NAME}:${CI_COMMIT_SHORT_SHA} .
    - docker push ${IMAGE_NAME}:${CI_COMMIT_SHORT_SHA}
    - IMAGE_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' ${IMAGE_NAME}:${CI_COMMIT_SHORT_SHA} | cut -d'@' -f2)
    - echo "IMAGE_DIGEST=${IMAGE_DIGEST}" >> build.env
  artifacts:
    reports:
      dotenv: build.env

# Автоматическое продвижение в dev сразу после сборки
deploy-to-dev:
  stage: promote-dev
  image: alpine/git:2.45.2
  before_script:
    - eval $(ssh-agent -s)
    - echo "$GITOPS_DEPLOY_KEY" | tr -d '\r' | ssh-add -
    - git config --global user.email "ci-bot@internal.corp"
    - git config --global user.name "GitOps Promotion Bot"
  script:
    - git clone ${GITOPS_REPO} gitops-workspace
    - cd gitops-workspace/apps/billing-service/overlays/dev
    - sed -i "s|digest: sha256:.*|digest: ${IMAGE_DIGEST}|" kustomization.yaml
    - git add kustomization.yaml
    - git commit -m "chore(billing): promote image to dev [${CI_COMMIT_SHORT_SHA}] [skip ci]"
    - git push origin main

# Продвижение в production требует создания Merge Request и ручного подтверждения
promote-to-production:
  stage: promote-prod
  image: alpine/git:2.45.2
  when: manual
  only:
    - tags
  script:
    - echo "Создание ветки и MR для ревью релиза в production..."
    - git clone ${GITOPS_REPO} gitops-workspace
    - cd gitops-workspace
    - git checkout -b promote-billing-${CI_COMMIT_TAG}
    - cd apps/billing-service/overlays/prod
    - sed -i "s|digest: sha256:.*|digest: ${IMAGE_DIGEST}|" kustomization.yaml
    - git commit -am "release(billing): promote ${CI_COMMIT_TAG} to production"
    - git push origin promote-billing-${CI_COMMIT_TAG}
    # Вызов GitLab API для создания Merge Request с обязательным ревью
    - |
      curl --request POST --header "PRIVATE-TOKEN: ${GITOPS_API_TOKEN}" \
        --data "source_branch=promote-billing-${CI_COMMIT_TAG}&target_branch=main&title=Release+billing+${CI_COMMIT_TAG}+to+production" \
        "https://git.internal.corp/api/v4/projects/platform%2Ffleet-gitops/merge_requests"
```

---

### Сценарий 3: Разграничение ответственности через CODEOWNERS

Для защиты ветки `main` в `Config Repo` настраивается защита критических каталогов через `CODEOWNERS`. Это гарантирует, что разработчики могут самостоятельно мерджить изменения в `overlays/dev`, но правки `overlays/prod` требуют обязательного одобрения инженера SRE или тимлида.

```text
# .gitlab/CODEOWNERS в корне fleet-gitops-repo

# Дефолтные владельцы всех манифестов
* @sre-team

# Разработчики команды биллинга могут утверждать изменения только для своего dev и stage
/apps/billing-service/overlays/dev/   @billing-lead @billing-devs
/apps/billing-service/overlays/stage/ @billing-lead @qa-lead

# Все production оверлеи требуют аппрува строго от SRE-инженера
/apps/*/overlays/prod/                @sre-team @security-team

# Инфраструктурные чарты и компоненты кластера
/infrastructure/                      @platform-team @sre-team
```

---

## Операции и регламентные команды

### 1. Проверка различий между средами (Environment Drift Inspection)

Перед релизом в прод системный администратор проверяет, какие именно параметры отличаются между Staging и Production:

```bash
# Генерация манифестов и проверка diff между оверлеями
kubectl kustomize apps/billing-service/overlays/stage > /tmp/stage-rendered.yaml
kubectl kustomize apps/billing-service/overlays/prod > /tmp/prod-rendered.yaml

# Визуализация различий (без учета тривиальных расхождений по неймспейсам)
diff -u /tmp/stage-rendered.yaml /tmp/prod-rendered.yaml | grep -E "^[+-]" | head -n 30
# → -    replicas: 2
# → +    replicas: 10
# → -        memory: 512Mi
# → +        memory: 2Gi
# → -    digest: sha256:1a2b...
# → +    digest: sha256:7f9b...
```

### 2. Экстренное замораживание продвижения (Promotion Freeze)

В случае масштабного инцидента в On-Premise инфраструктуре администратор временно блокирует возможность автоматических коммитов от ботов:

```bash
# Временный запрет пуша в ветку main через CLI GitLab (или снятие прав у токена бота)
curl --request PUT --header "PRIVATE-TOKEN: $ADMIN_TOKEN" \
  "https://git.internal.corp/api/v4/projects/platform%2Ffleet-gitops/protected_branches/main" \
  --data "push_access_level=0"
# → {"name":"main","push_access_levels":[{"access_level":0,"access_level_description":"No one"}]}
```

---

## Диагностика и устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Паразитный цикл сборки (CI Loop Storm)** | CI-бот коммитит тег в тот же репозиторий, где настроен пайплайн сборки кода | История GitLab CI: пайплайны запускаются бесконечно после каждого коммита | Добавить директиву `[skip ci]` в сообщение коммита бота либо разделить репозитории на App Repo и Config Repo. |
| **Конфликт слияния (Merge Conflict) в production** | Использование Environment Branches; в prod был сделан ручной хотфикс | `git merge staging` завершается ошибкой `Automatic merge failed` | Отказаться от слияния веток. Перейти на модель `overlays/prod` в единой ветке `main`. |
| **Argo CD игнорирует обновление тега** | В Kustomization указан мутабельный тег без дайджеста, кэш `repo-server` не инвалидирован | `argocd app diff <app>` показывает отсутствие различий | Использовать immutable digests (`sha256:...`) либо сбросить кэш через `argocd app get <app> --refresh`. |
| **Ошибка Permission Denied при авто-промоут** | Истек токен сервисного аккаунта бота или SSH deploy key был удален | Логи CI-раннера: `remote: You are not allowed to push code to protected branch` | Проверить права deploy key в настройках защищенной ветки `main` (разрешить запись сервисному аккаунту). |

---

## Рекомендации и Best Practices

1. **Строго Trunk-Based для GitOps:** Никогда не использовать ветки под окружения. Единственным источником истины для всех кластеров должна быть единая ветка `main` с изолированными оверлеями директорий.
2. **Изоляция App Repo и Config Repo:** Разделять репозитории разработки и манифестов. Это упрощает RBAC, предотвращает утечки боевых манифестов и гарантирует независимость CI от CD.
3. **Продвижение только через дайджесты (SHA256):** Процесс промоушена должен оперировать неизменяемыми криптографическими дайджестами образов, исключая мутабельные теги (`latest`, `release`).
4. **Обязательное ревью через CODEOWNERS для Prod:** Любое изменение каталога `overlays/prod` должно требовать утверждения минимум от одного дежурного SRE-инженера.
5. **Предотвращение бесконечных циклов CI:** Все автоматические коммиты от скриптов продвижения и ботов обязаны содержать маркер `[skip ci]`.

---

## Дополнительная информация

**Связанные документы:**
- [GitOps: декомпозиция методологии и апгрейд CIOps](./gitops_decomposition.md) — разбор push vs pull, SSA и циклов согласования.
- [Организация Flux CD monorepo](./flux_monorepo_organization.md) — архитектура каталогов `clusters/` и `components/` для 20+ кластеров.
- [Kargo: promotion-пайплайны](./kargo_promotion_pipelines.md) — декларативное продвижение артефактов без самописных CI-скриптов.
- [GitOps: пример пайплайна](../gitops_pipeline_example.md) — сквозной конвейер сборки и доставки с интеграцией Cosign и Harbor.

---

## Вопросы для собеседования

### 1. Почему использование веток под окружения (`dev`, `stage`, `prod`) признано антипаттерном в GitOps?
**Ответ:** Разные окружения имеют принципиальные различия в конфигурации (количество реплик, параметры ingress, лимиты памяти, конфигурации баз данных). При использовании модели отдельных веток продвижение изменений выполняется через `git merge`. В процессе слияния Git неизбежно порождает конфликты либо перезаписывает специфичные настройки продакшена значениями из dev. Кроме того, ветки накапливают дрейф (drift), делая будущие слияния невозможными. Решением является модель **Directory-per-Environment** на единой ветке `main`, где параметры сред разнесены по разным папкам оверлеев Kustomize/Helm.

### 2. В чем ключевые преимущества и недостатки разделения репозитория на App Repo и Config Repo (Split-repo)?
**Ответ:** 
- **Преимущества:** 
  1. Четкое разграничение RBAC: разработчики имеют права на запись только в код приложения, а доступ к продакшен-манифестам жестко ограничен SRE-командой.
  2. Чистые триггеры CI/CD: коммиты манифестов не запускают повторную компиляцию и тестирование исходного кода.
  3. Безопасность: скомпрометированный CI-раннер разработки не имеет доступа к закрытым манифестам инфраструктуры.
- **Недостатки:** Повышенная координационная сложность: для релиза фичи, требующей добавления переменной окружения, необходимо синхронизировать изменения в двух репозиториях (сначала обновить Config Repo, затем смерджить App Repo).

### 3. Как организовать продвижение (Promotion) артефакта между средами Dev и Prod в классическом On-Premise стеке GitLab CI + Argo CD?
**Ответ:**
1. В App Repo CI-раннер собирает образ, пушит его в реестр (Harbor) под уникальным тегом/дайджестом.
2. В конце пайплайна шаг продвижения клонирует Config Repo, выполняет команду обновления оверлея (например, `kustomize edit set image` или `sed`), коммитит изменение в ветку `main` с маркером `[skip ci]` и пушит в Git.
3. Для Dev-среды пуш выполняется автоматически. Для Prod-среды создается отдельная ветка и Merge Request, требующий аппрува согласно файлу `CODEOWNERS` от SRE-команды.
4. Контроллер Argo CD считывает изменения ветки `main` и применяет обновленный оверлей в целевой кластер.

### 4. Что произойдет, если скрипт авто-промоушена запушит коммит в Config Repo без метки `[skip ci]`?
**Ответ:** Если в Config Repo настроен собственный пайплайн статической валидации манифестов (линтеры `yamllint`, `kubeconform`), он будет вызван штатно. Однако если Config Repo совмещен с App Repo или если бот по ошибке пушит коммит в репозиторий приложения, это вызовет **паразитный бесконечный цикл (CI loop storm)**: коммит бота запустит новый пайплайн сборки, который соберет новый образ, вызовет скрипт промоушена, который сделает новый коммит, и процесс зациклится до исчерпания ресурсов раннеров.

### 5. Как механизм CODEOWNERS защищает production-окружение в GitOps-репозитории?
**Ответ:** `CODEOWNERS` декларирует правила обязательного код-ревью на уровне путей файловой системы в репозитории. В правилах ветки настраивается запрет прямого пуша в `main` (Protected Branch) и требование обязательного аппрува от владельцев кода при мердже. Каталоги `/apps/*/overlays/dev/` разрешается изменять разработчикам сервиса, в то время как пути `/apps/*/overlays/prod/` и `/infrastructure/` требуют обязательной подписи участников группы `@sre-team`. Это исключает несанкционированные изменения продакшена даже при открытом доступе к репозиторию.
