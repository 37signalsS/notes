# Argo CD Image Updater — автоматизация обновления образов

**Argo CD Image Updater** — это контроллер для Argo CD, который отслеживает изменения в реестрах контейнеров (Container Registries) и автоматически обновляет версии образов в приложениях. Это позволяет реализовать цикл непрерывной доставки (CD), где публикация нового образа в реестре инициирует автоматический деплой без ручного редактирования Git-репозитория.

**Актуально для:** Argo CD Image Updater v1.3.x (покрывает v1.0.x–v1.3.x; v1.0.0 — breaking change: переход с аннотаций на CRD `ImageUpdater`; v1.2.x — `registry-scanner` v1.x, `argocd` v3.4+; v1.3.x — Argo CD v3.5+). Проект в Labs (argoproj-labs), не в core Argo CD — не входит в CNCF Graduation path. Для нативной интеграции без аннотаций — Flux Image Automation (CNCF Graduated).

## Предварительные требования

| # | Требование | Детали | Команда проверки | Ожидаемый результат |
|---|------------|--------|------------------|---------------------|
| 1 | **Kubernetes кластер** | v1.28+ (актуальные LTS: 1.28, 1.29, 1.30). Image Updater требует apiextensions.k8s.io/v1 для CRD. | `kubectl version --short` | `Server Version: v1.28.x` или выше |
| 2 | **Argo CD установлен** | v2.8+ или v3.x. Image Updater v1.x совместим с Argo CD v2.8-v3.5+. Проверьте совместимость в Release Notes. | `kubectl get pods -n argocd -l app.kubernetes.io/part-of=argocd` | Все поды `Running`, `READY 1/1` |
| 3 | **Argo CD Application CRD** | Должен быть установлен (входит в стандартную установку Argo CD). | `kubectl get crd applications.argoproj.io` | `NAME: applications.argoproj.io, ESTABLISHED: True` |
| 4 | **Доступ к реестру образов** | Учетные данные для аутентификации в целевом реестре (Harbor, Docker Hub, ECR, GAR, ACR, Quay, Nexus). Поддерживаются: basic auth, bearer token, IAM (AWS ECR IRSA, Azure WI, GCP WI). | `crane auth login <registry> -u <user> -p <pass>` → `Login Succeeded` | Успешный логин, токен сохранен в `~/.docker/config.json` |
| 5 | **Git-репозиторий (для Git write-back)** | Репозиторий с доступом на запись (push). Поддерживаются: GitHub, GitLab, Bitbucket, Gitea, Gogs, Azure DevOps. Аутентификация: SSH key, HTTPS token, GitHub App, GitLab Deploy Token. | `git ls-remote <repo-url>` | Список refs без ошибок аутентификации |
| 6 | **Helm / Kustomize (опционально)** | Если приложения используют Helm или Kustomize. Image Updater работает с любым типом source. | `helm version --short` / `kustomize version` | Версии установлены |
| 7 | **Сетевой доступ** | Исходящий трафик от пода `argocd-image-updater` к API реестров (порт 443 HTTPS) и к Git API (443/22). При необходимости — настройте NetworkPolicy / Egress. | `kubectl run -i --rm --restart=Never test --image=curlimages/curl -- curl -s https://harbor.example.com/api/v2.0/health` | `{"status":"healthy"}` |
| 8 | **RBAC для Image Updater** | ServiceAccount с правами: `get/list/watch/update/patch` на `applications.argoproj.io`, `configmaps` (argocd-image-updater-config), `secrets` (pull secrets, git credentials). | `kubectl auth can-i patch applications.argoproj.io --as=system:serviceaccount:argocd:argocd-image-updater -n argocd` | `yes` |
| 9 | **kubectl / argocd CLI** | Для управления и диагностики. argocd CLI v2.8+ для совместимости с Image Updater. | `argocd version --client` | `argocd: v2.8.x+...` |

> **Примечание:** Cloud IAM (AWS ECR IRSA, Azure Workload Identity, GCP Workload Identity) — это настройка идентичности пода, а не "облачная зависимость". Конфигурация выполняется через ServiceAccount annotations и IAM политики; логика Image Updater остается одинаковой.

## Определения

| Термин | Определение |
|--------|-------------|
| **Image Updater** | Вспомогательный контроллер Argo CD (проект argoproj-labs), опрашивающий API реестров образов (Harbor, Docker Hub, AWS ECR, GCP GAR, Azure ACR, Quay, Nexus, Generic OCI) на наличие новых тегов и автоматически обновляющий параметры приложений Argo CD. Не входит в core Argo CD. |
| **ImageUpdater CR** | Custom Resource Definition (v1.0+), декларативная конфигурация обновления образов. Заменяет аннотационный подход (legacy). Содержит `applicationRefs` (селекторы приложений), `images` (образы для отслеживания), `writeBackConfig` (метод записи). |
| **Write-back Method** | Механизм фиксации изменений версии образа:<br>• **Git (Declarative)** — запись обновленного тега обратно в Git-репозиторий в виде коммита (создает файл `.argocd-source-<app-name>.yaml` с переопределенными параметрами). Рекомендуется для GitOps (Production, Staging).<br>• **API / argocd (Imperative)** — временное переопределение параметров приложения в оперативной памяти Argo CD через его API. Для Dev/QA сред. |
| **Update Strategy** | Алгоритм выбора «наилучшего» тега из списка доступных в реестре:<br>• **SemVer** — семантическое версионирование с поддержкой диапазонов (`^1.0`, `~1.2`, `>=1.0 <2.0`).<br>• **Latest** / **NewestBuild** — самый последний созданный образ по дате (timestamp).<br>• **Name** — алфавитный порядок тегов.<br>• **Digest** — использование SHA256 хеша (для неизменяемых тегов, максимальная детерминированность). |
| **Pull Secret** | Секрет Kubernetes типа `kubernetes.io/dockerconfigjson`, используемый контроллером для аутентификации в приватных реестрах. Указывается в `commonUpdateSettings.pullSecret` или в `registries.conf`. |
| **Registry Configuration** | Конфигурация реестра в ConfigMap `argocd-image-updater-config` (ключ `registries.conf`), определяющая: `name`, `prefix` (путь к образам), `api_url`, `credentials` (ссылка на Secret), `default`, `insecure`, `ping` (health check endpoint). |
| **Webhook Receiver** | HTTP-эндпоинт Image Updater (порт 8080), принимающий уведомления от реестров (Harbor, Docker Hub, Quay, generic) о появлении новых образов для немедленной проверки без ожидания `check.interval`. Требует Ingress/Service. |
| **Image List Annotation (Legacy)** | Основная аннотация `argocd-image-updater.argoproj.io/image-list`, перечисляющая образы для отслеживания в формате `<alias>=<image>[:<filter>]`. Пример: `app=my-registry/api:^1.0`. Может содержать несколько образов через запятую или YAML-список. **Устарело в v1.0+**. |
| **Force Update** | Аннотация `argocd-image-updater.argoproj.io/force-update: "true"` — принудительно запускает проверку и обновление вне очереди интервала. Сбрасывается контроллером после выполнения. |
| **Check Interval** | Параметр `check.interval` в ConfigMap (дефолт `2m`) — частота опроса реестров. Поддерживает Go duration синтаксис (`30s`, `5m`, `1h`). |
| **Registries.conf** | YAML-конфигурация внутри ConfigMap `argocd-image-updater-config`, описывающая список реестров с их параметрами доступа. Структура: `registries: [{name, prefix, api_url, credentials, default, insecure, ping}]`. |
| **Kustomize Image Override** | Механизм обновления образов в Kustomize через поле `images:` в `kustomization.yaml`. Требует `writeBackTarget: "kustomizeimage:./path"`. |
| **Helm Parameter Override** | Механизм обновления Helm-параметров. Требует `writeBackTarget: "helmvalues:./values.yaml"` и соответствующие параметры в `values.yaml`. |
| **SemVer Range** | Синтаксис фильтрации версий по семантическому версионированию: `^1.0.0` (>=1.0.0 <2.0.0), `~1.2.3` (>=1.2.3 <1.3.0), `>=1.0.0 <2.0.0`, `1.2.x`. Поддерживает pre-release (`1.0.0-rc.1`) при явном указании. |
| **Digest Pinning** | Стратегия `digest` — фиксация образа по SHA256 дайджесту (`image@sha256:...`). Гарантирует иммутабельность; обновления применяются только при появлении нового дайджеста в реестре (при пересборке образа). |

## Базовые концепции

### Архитектура взаимодействия (v1.x CRD-based)

```
┌─────────────────────────────────────────────────────────────────────┐
│         Argo CD Image Updater v1.x: Архитектура автоматизации       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │  Container   │    │ argocd-image │    │  argocd-     │          │
│  │  Registry    │◀───│ -updater     │───▶│ application  │          │
│  │  (Harbor,    │    │ (Контроллер) │    │ controller   │          │
│  │   ECR, etc.) │    └──────────────┘    └──────────────┘          │
│  └──────────────┘           │                   │                   │
│         │                   ▼                   ▼                   │
│         │         ┌──────────────┐    ┌──────────────┐             │
│         │         │  ImageUpdater│    │  Application │             │
│         │         │     CR       │    │  (Git/Helm/  │             │
│         │         └──────────────┘    │   Kustomize) │             │
│         │                              └──────────────┘             │
│         ▼                                                           │
│  ┌──────────────┐    ┌──────────────┐                              │
│  │ Webhook      │    │  Git         │                              │
│  │ Receiver     │    │  Repository  │                              │
│  │ (Опционально)│    │  (Write-back)│                              │
│  └──────────────┘    └──────────────┘                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Механизм работы (v1.x)

1. **Обнаружение:** Контроллер читает ресурсы `ImageUpdater` в кластере.
2. **Селекция приложений:** Для каждого `ImageUpdater` применяются `applicationRefs` (namePattern, labelSelector) для поиска целевых `Application` объектов.
3. **Конфигурация образов:** Для каждого выбранного приложения берутся `images` из CR (alias, imageName, commonUpdateSettings).
4. **Опрос реестра:** Для каждого образа выполняется запрос к API реестра. Контроллер учитывает настройки аутентификации из `argocd-image-updater-config` / `registries.conf`.
5. **Сравнение:** Найденные теги фильтруются согласно стратегии (SemVer, Latest/NewestBuild, Name, Digest) и настройкам `allowTags`/`ignoreTags`.
6. **Обновление:** Если найден тег новее текущего, инициируется запись изменений через `writeBackConfig` (git или argocd API).

### Write-back методы: Git vs API

| Критерий | Git write-back | API write-back |
| :--- | :--- | :--- |
| **Согласованность** | Высокая (Git — SSoT) | Средняя (параметры в памяти) |
| **Аудит** | Полная история коммитов | Только текущее состояние |
| **Сложность настройки** | Высокая (SSH/HTTPS ключи) | Низкая (токен ArgoCD) |
| **Конфликты** | Возможны при параллельных коммитах | Отсутствуют |
| **Рекомендуемая среда** | Production, Staging | Dev, QA, Testing |
| **Восстановление** | Через `git revert` | Через `argocd app rollback` |

### Аутентификация в реестрах

Image Updater поддерживает несколько способов авторизации:

- **Секреты Kubernetes:** Указание в `commonUpdateSettings.pullSecret: "secret://<namespace>/<secret-name>"` или в `registries.conf`.
- **Глобальная настройка:** Определение учетных данных в ConfigMap `argocd-image-updater-config`.
- **Cloud IAM:** Использование ролей (например, IAM Roles for Service Accounts в AWS ECR).
- **Azure Workload Identity:** Для Azure ACR.
- **GCP Workload Identity:** Для GCP GAR.

**Важно:** Secret должен содержать ключи `username` и `password` в формате `docker-registry`:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: harbor-pull-secret
  namespace: argocd
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: <base64-encoded>
```

### Полный список полей ImageUpdater CR (v1.x)

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `spec.applicationRefs[].namePattern` | Glob-паттерн имени Application | `production-*`, `my-app` |
| `spec.applicationRefs[].labelSelector` | Label selector для Application | `env=production` |
| `spec.applicationRefs[].images[].alias` | Уникальный алиас образа | `nginx`, `backend` |
| `spec.applicationRefs[].images[].imageName` | Полное имя образа с тегом/фильтром | `harbor.example.com/myapp:^1.0` |
| `spec.applicationRefs[].images[].commonUpdateSettings.updateStrategy` | Стратегия | `semver`, `newest-build`, `name`, `digest` |
| `spec.applicationRefs[].images[].commonUpdateSettings.allowTags` | Regex для разрешенных тегов | `^v?[0-9]+\.[0-9]+$` |
| `spec.applicationRefs[].images[].commonUpdateSettings.ignoreTags` | Массив игнорируемых тегов | `["latest", "dev", "rc"]` |
| `spec.applicationRefs[].images[].commonUpdateSettings.pullSecret` | Ссылка на pull secret | `secret://argocd/harbor-secret` |
| `spec.writeBackConfig.method` | Метод записи | `git`, `argocd` |
| `spec.writeBackConfig.gitConfig.repository` | Git репозиторий | `git@github.com:org/repo.git` |
| `spec.writeBackConfig.gitConfig.branch` | Ветка | `main` |
| `spec.writeBackConfig.gitConfig.writeBackTarget` | Цель: `helmvalues:./values.yaml`, `kustomizeimage:./kustomization.yaml` | `helmvalues:./values.yaml` |

## Настройка и конфигурация

### Конфигурация контроллера (ConfigMap)

Основные настройки контроллера хранятся в `argocd-image-updater-config`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  # Интервал опроса реестров (по умолчанию 2 минуты)
  check.interval: "2m"
  # Настройка логирования
  log.level: "info"
  # Конфигурация реестров
  registries.conf: |
    registries:
    - name: Harbor
      prefix: harbor.example.com
      api_url: https://harbor.example.com/api/v2.0
      credentials: secret://argocd/harbor-pull-secret
    - name: DockerHub
      prefix: docker.io
      api_url: https://registry.hub.docker.com
      default: true
    - name: AWS ECR
      prefix: 123456789.dkr.ecr.us-east-1.amazonaws.com
      api_url: https://123456789.dkr.ecr.us-east-1.amazonaws.com
      credentials: secret://argocd/ecr-credentials
      default: false
    - name: GCP GAR
      prefix: us-central1-docker.pkg.dev
      api_url: https://us-central1-docker.pkg.dev
      credentials: secret://argocd/gar-credentials
```

**Параметры реестра:**

| Параметр | Описание | Обязательный |
| :--- | :--- | :--- |
| `name` | Уникальное имя реестра | Да |
| `prefix` | Префикс пути к образам | Да |
| `api_url` | URL API реестра | Да |
| `credentials` | Ссылка на Secret | Да |
| `default` | Реестр по умолчанию | Нет (false) |
| `insecure` | Отключение TLS-проверки | Нет (false) |

### ImageUpdater CR (v1.x — основной способ)

Деларативная конфигурация через Custom Resource:

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: production-image-updater
  namespace: argocd  # Должен совпадать с namespace Applications
spec:
  # Глобальная конфигурация write-back (переопределяется на уровне applicationRefs)
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:myorg/infra.git"
      branch: "main"
      writeBackTarget: "helmvalues:./apps/my-app/values.yaml"
  
  # Селекция приложений и настройка образов
  applicationRefs:
  - namePattern: "production-*"
    labelSelector: "env=production"
    images:
    - alias: "frontend"
      imageName: "harbor.example.com/myorg/frontend:^1.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        allowTags: "^v?[0-9]+\\.[0-9]+\\.[0-9]+$"
        ignoreTags: ["latest", "dev", "rc", "alpha", "beta"]
        pullSecret: "secret://argocd/harbor-pull-secret"
    - alias: "backend"
      imageName: "harbor.example.com/myorg/backend:~2.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        pullSecret: "secret://argocd/harbor-pull-secret"
  
  - namePattern: "staging-*"
    writeBackConfig:
      method: "git"
      gitConfig:
        branch: "develop"
        writeBackTarget: "helmvalues:./apps/my-app/values.yaml"
    images:
    - alias: "frontend"
      imageName: "harbor.example.com/myorg/frontend"
      commonUpdateSettings:
        updateStrategy: "newest-build"
        pullSecret: "secret://argocd/harbor-pull-secret"
```

### Стратегии обновления (v1.x)

| Стратегия | Описание | Пример | Когда использовать |
| :--- | :--- | :--- | :--- |
| **SemVer** | Выбор по семантическому версионированию. Поддерживает диапазоны. | `semver` + `imageName: "repo/app:^1.0"` | Стабильные релизы, Production |
| **NewestBuild** / **Latest** | Выбор самого последнего созданного образа (по дате). | `newest-build` | Dev, Nightly builds |
| **Name** | Алфавитный порядок тегов. | `name` | Нестандартная нумерация |
| **Digest** | Использование SHA256 хеша (для неизменяемых тегов). | `digest` | Критические среды, Security |

**Примеры диапазонов SemVer (в поле `imageName`):**
- `^1.0` — все версии 1.x.x
- `~1.2` — все версии 1.2.x
- `>=1.0 <2.0` — все версии от 1.0 до 2.0
- `1.2.x` — конкретная минорная версия

### Аннотации (Legacy v0.x — для миграции)

> **Внимание:** Аннотационный подход объявлен **legacy** в v1.0.0. Поддерживается ограниченно для обратной совместимости. Новые проекты должны использовать **ImageUpdater CR**.

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `argocd-image-updater.argoproj.io/image-list` | Список образов и фильтры | `app=my-registry/app:^1.0` |
| `argocd-image-updater.argoproj.io/<name>.update-strategy` | Стратегия обновления | `semver`, `latest`, `name`, `digest` |
| `argocd-image-updater.argoproj.io/write-back-method` | Метод записи | `git`, `argocd` |
| `argocd-image-updater.argoproj.io/write-back-target` | Цель записи | `git:secret:argocd/git-creds` |
| `argocd-image-updater.argoproj.io/<name>.kustomize.image-name` | Имя образа в Kustomize | `my-org/frontend` |
| `argocd-image-updater.argoproj.io/<name>.helm.image-name` | Имя параметра Helm | `image.repository` |
| `argocd-image-updater.argoproj.io/<name>.helm.image-tag` | Имя параметра тега | `image.tag` |
| `argocd-image-updater.argoproj.io/<name>.pull-secret` | Ссылка на Secret | `secret://argocd/pull-secret` |
| `argocd-image-updater.argoproj.io/<name>.registry` | Имя реестра из конфигурации | `harbor` |
| `argocd-image-updater.argoproj.io/force-update` | Принудительное обновление | `true` |

## Практические сценарии (v1.x CRD-based)

### Сценарий 1: Установка Image Updater v1.x

```bash
# 1. Добавление Helm-чарта ArgoCD
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# 2. Установка Image Updater v1.x
# Примечание: chart version ≠ app version. Chart 1.x.x устанавливает app v1.x.x
helm install argocd-image-updater argo/argocd-image-updater \
  --namespace argocd \
  --version 1.3.1  # версия чарта, см. https://artifacthub.io/packages/helm/argo/argocd-image-updater

# 3. Проверка статуса
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-image-updater

# 4. Проверка CRD
kubectl get crd imageupdaters.argocd-image-updater.argoproj.io
```

### Сценарий 2: Автоматизация через Git write-back (Helm) — Production

Рекомендуемый метод для соблюдения принципов GitOps. Контроллер создает файл `.argocd-source-<app-name>.yaml` в репозитории.

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: production-image-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:myorg/infra.git"
      branch: "main"
      # writeBackTarget указывает путь к values.yaml относительно корня репозитория
      writeBackTarget: "helmvalues:./apps/my-app/values.yaml"
  applicationRefs:
  - namePattern: "my-app-prod"
    images:
    - alias: "app-image"
      # Образ с SemVer фильтром: только минорные обновления v1.x
      imageName: "harbor.example.com/myorg/my-app:^1.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        allowTags: "^v?[0-9]+\\.[0-9]+\\.[0-9]+$"
        ignoreTags: ["latest", "dev", "rc"]
        pullSecret: "secret://argocd/harbor-pull-secret"
```

**Ожидаемый `values.yaml`:**
```yaml
image:
  repository: harbor.example.com/myorg/my-app
  tag: "1.0.0"  # Будет обновляться Image Updater
```

### Сценарий 3: API write-back (Dev/QA)

Для Dev/QA сред, где не требуется история коммитов в Git:

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: dev-image-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "argocd"
  applicationRefs:
  - namePattern: "my-app-dev"
    images:
    - alias: "app"
      imageName: "harbor.example.com/myorg/my-app"
      commonUpdateSettings:
        updateStrategy: "newest-build"
        pullSecret: "secret://argocd/harbor-pull-secret"
```

### Сценарий 4: Использование Kustomize

Для Kustomize контроллер использует механизм переопределения образов (`images:` в `kustomization.yaml`):

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: kustomize-image-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:myorg/infra.git"
      branch: "main"
      # Для Kustomize используем kustomizeimage target
      writeBackTarget: "kustomizeimage:./apps/my-app"
  applicationRefs:
  - namePattern: "my-app-*"
    images:
    - alias: "web"
      imageName: "harbor.example.com/myorg/frontend:^1.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        pullSecret: "secret://argocd/harbor-pull-secret"
```

**Ожидаемый `kustomization.yaml`:**
```yaml
images:
- name: harbor.example.com/myorg/frontend
  newTag: "1.0.0"  # Будет обновляться Image Updater
```

### Сценарий 5: Несколько образов в одном приложении

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: multi-image-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:myorg/infra.git"
      branch: "main"
      writeBackTarget: "helmvalues:./apps/my-app/values.yaml"
  applicationRefs:
  - namePattern: "my-app-prod"
    images:
    - alias: "frontend"
      imageName: "harbor.example.com/myorg/frontend:^1.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        pullSecret: "secret://argocd/harbor-pull-secret"
    - alias: "backend"
      imageName: "harbor.example.com/myorg/backend:^2.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        pullSecret: "secret://argocd/harbor-pull-secret"
    - alias: "database"
      imageName: "docker.io/library/postgres:16"
      commonUpdateSettings:
        updateStrategy: "semver"
        allowTags: "^16\\.[0-9]+$"
```

### Сценарий 6: Webhook Receiver для немедленного обновления

Для немедленного отклика на появление новых образов настройте webhook receiver:

```yaml
# 1. Service для webhook receiver
apiVersion: v1
kind: Service
metadata:
  name: argocd-image-updater-webhook
  namespace: argocd
spec:
  ports:
  - port: 80
    targetPort: 8080
  selector:
    app.kubernetes.io/name: argocd-image-updater
---
# 2. Ingress для внешнего доступа
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-image-updater-webhook
  namespace: argocd
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
  - host: image-updater.example.com
    http:
      paths:
      - path: /webhook
        pathType: Prefix
        backend:
          service:
            name: argocd-image-updater-webhook
            port:
              number: 80
```

**Настройка в Harbor (Project → Webhooks):**
- URL: `https://image-updater.example.com/webhook`
- Events: `PUSH_ARTIFACT`
- Secret: (опционально, для валидации HMAC)

### Сценарий 7: AWS ECR с IAM Roles (IRSA)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  registries.conf: |
    registries:
    - name: AWS ECR
      prefix: 123456789.dkr.ecr.us-east-1.amazonaws.com
      api_url: https://123456789.dkr.ecr.us-east-1.amazonaws.com
      credentials: secret://argocd/ecr-credentials
      default: true
---
apiVersion: v1
kind: Secret
metadata:
  name: ecr-credentials
  namespace: argocd
type: Opaque
stringData:
  username: AWS
  password: <ecr-token-from-aws-cli-get-login-password>
---
# ServiceAccount с IRSA annotation
apiVersion: v1
kind: ServiceAccount
metadata:
  name: argocd-image-updater
  namespace: argocd
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/argocd-image-updater-ecr-read
```

### Сценарий 8: Digest Pinning для Production

Максимальная детерминированность — обновление только при изменении дайджеста (пересборке образа):

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: digest-pinning-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:myorg/infra.git"
      branch: "main"
      writeBackTarget: "helmvalues:./apps/my-app/values.yaml"
  applicationRefs:
  - namePattern: "my-app-prod"
    images:
    - alias: "app"
      imageName: "harbor.example.com/myorg/my-app"
      commonUpdateSettings:
        updateStrategy: "digest"
        pullSecret: "secret://argocd/harbor-pull-secret"
```

**Результат в values.yaml:**
```yaml
image:
  repository: harbor.example.com/myorg/my-app
  tag: "sha256:abc123..."  # Полный дайджест
```

### Сценарий 9: Разные write-back для разных сред в одном CR

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: multi-env-updater
  namespace: argocd
spec:
  # Глобальные настройки (для production)
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:myorg/infra.git"
      branch: "main"
      writeBackTarget: "helmvalues:./apps/my-app/values.yaml"
  applicationRefs:
  - namePattern: "my-app-prod"
    images:
    - alias: "app"
      imageName: "harbor.example.com/myorg/my-app:^1.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        pullSecret: "secret://argocd/harbor-pull-secret"
  
  # Override для staging — API write-back, другая ветка
  - namePattern: "my-app-staging"
    writeBackConfig:
      method: "argocd"
    images:
    - alias: "app"
      imageName: "harbor.example.com/myorg/my-app"
      commonUpdateSettings:
        updateStrategy: "newest-build"
        pullSecret: "secret://argocd/harbor-pull-secret"
  
  # Override для dev — Git write-back в develop ветку
  - namePattern: "my-app-dev"
    writeBackConfig:
      method: "git"
      gitConfig:
        branch: "develop"
        writeBackTarget: "helmvalues:./apps/my-app/values.yaml"
    images:
    - alias: "app"
      imageName: "harbor.example.com/myorg/my-app"
      commonUpdateSettings:
        updateStrategy: "newest-build"
        pullSecret: "secret://argocd/harbor-pull-secret"
```

## Сравнение с Flux Image Automation

| Характеристика | Argo CD Image Updater v1.x | Flux Image Automation |
| :--- | :--- | :--- |
| **Интеграция** | Внешний аддон (Labs проект). | Встроено в ядро (Image Controller). CNCF Graduated. |
| **Точность записи** | Создает отдельный YAML-файл (минимум конфликтов). | Изменяет оригинальный YAML (маркеры в комментариях). |
| **Управление** | Через CRD `ImageUpdater` (v1.x) / аннотации (legacy v0.x). | Через Custom Resources (`ImagePolicy`, `ImageRepository`, `ImageUpdateAutomation`). |
| **Масштабирование** | Один `ImageUpdater` CR управляет множеством Application через селекторы. | Независимые политики для всего кластера. |
| **Управление тегами** | SemVer, NewestBuild, Name, Digest. | SemVer, Numerical, Alphabetical. |
| **Multi-registry** | Да, через `registries.conf` в ConfigMap. | Да, через `ImageRepository` CRD. |
| **Webhook** | Да, встроенный receiver (порт 8080). | Да, через `Receiver` CRD. |
| **Аудит** | Через Git-коммиты (Git write-back) или API логи. | Через Git-коммиты. |
| **Production readiness** | Да (используется в крупных компаниях). | Да (CNCF Graduated). |
| **Кривая обучения** | Низкая (CRD декларативно). | Средняя (CRD). |

## Диагностика и отладка (v1.x)

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **No image found** | Нет `ImageUpdater` CR или неверное `imageName` / `namePattern`. | Проверьте `kubectl get imageupdater -n argocd`. Убедитесь, что `applicationRefs.namePattern` матчит Application. |
| **Rate limit exceeded** | Превышен лимит запросов к реестру. | Увеличьте `check.interval` в ConfigMap, добавьте аутентификацию, используйте приватный реестр. |
| **Failed to login** | Неверные учетные данные в Secret или отсутствует pullSecret. | Проверьте Secret: `kubectl get secret -n argocd <secret-name> -o yaml`. Убедитесь, что `pullSecret` указан в CR. |
| **No write-back method** | Не указан `writeBackConfig.method` в CR. | Добавьте `writeBackConfig.method: git` или `argocd` в ImageUpdater CR. |
| **Image not in registry** | Образ или тег не найден / не проходит фильтр `allowTags`/`ignoreTags`. | Проверьте имя образа и доступные теги: `crane ls <image>`. Проверьте regex в `allowTags`. |
| **Git write-back failed** | Ошибка доступа к Git-репозиторию / неверный `writeBackTarget`. | Проверьте Secret с credentials для Git. Проверьте `writeBackTarget` формат (`helmvalues:./path`). |
| **Invalid semver range** | Неверный синтаксис диапазона в `imageName`. | Используйте стандартный синтаксис SemVer: `^1.0`, `~1.2`, `>=1.0 <2.0`. |
| **spec.namespace validation error** | Используется удаленное поле `spec.namespace` в CR. | Удалите `spec.namespace` — контроллер использует `metadata.namespace`. |

### Полезные команды для отладки (v1.x)

```bash
# Просмотр логов контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater --tail=100

# Просмотр конфигурации реестров
kubectl get configmap argocd-image-updater-config -n argocd -o yaml

# Просмотр ImageUpdater CR
kubectl get imageupdater -n argocd
kubectl get imageupdater -n argocd -o yaml
kubectl describe imageupdater <name> -n argocd

# Проверка приложений, управляемых ImageUpdater
kubectl get applications -n argocd -o json | jq -r '.items[] | select(.metadata.name | test("my-app")) | .metadata.name'

# Проверка доступных тегов в реестре
crane ls harbor.example.com/my-app --limit 10

# Принудительное обновление приложения
kubectl annotate app my-app -n argocd argocd-image-updater.argoproj.io/force-update=true --overwrite

# Проверка статуса Image Updater deployment
kubectl get deployment argocd-image-updater -n argocd

# Просмотр событий Image Updater
kubectl get events -n argocd --field-selector involvedObject.name=argocd-image-updater

# Проверка registry-scanner логов (отдельный контейнер в v1.2+)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater -c registry-scanner --tail=50
```

### Валидация конфигурации

```bash
# Проверка доступности реестра
curl -s https://harbor.example.com/api/v2.0/health | jq .

# Проверка credentials
crane auth whoami https://harbor.example.com

# Просмотр информации об образе
crane manifest harbor.example.com/my-app:latest

# Валидация ImageUpdater CR (dry-run)
kubectl apply -f imageupdater.yaml --dry-run=server
```

## Рекомендации и лучшие практики (v1.x)

### Безопасность

- **Приватные реестры:** Всегда используйте аутентификацию для доступа к реестрам.
- **Least Privilege:** Создавайте отдельные Service Account для Image Updater с минимальными правами (`get/list/watch/update/patch` на `applications.argoproj.io`, `configmaps`, `secrets`).
- **Secrets:** Храните credentials в Kubernetes Secrets, не в ConfigMap. Используйте `pullSecret` в CR для указания секрета на уровне образа.
- **Image Signing:** Используйте Cosign или Notary для подписи образов. Image Updater v1.x поддерживает проверку подписей через `commonUpdateSettings.verifySignatures` (экспериментально).
- **Webhook Security:** Настройте webhook secret для проверки подлинности запросов от реестра.

### Производительность

- **Интервал опроса:** Настройте `check.interval` в ConfigMap в зависимости от требуемой отзывчивости (по умолчанию `2m`). Для production рекомендуется `5m`-`10m` + webhook.
- **Кеширование:** Image Updater кеширует результаты запросов к реестру. Registry-scanner (v1.2+) имеет отдельный кэш.
- **Rate Limiting:** Для публичных реестров (Docker Hub) используйте аутентификацию для увеличения лимитов (200 req/6h vs 100 анонимно).
- **Параллелизм:** Контроллер обрабатывает приложения параллельно, но реестры могут иметь ограничения. Настройте `concurrency` при необходимости.

### Надежность

- **Health Checks:** Image Updater проверяет доступность реестра перед обновлением (`ping` endpoint в `registries.conf`).
- **Retry Logic:** Автоматические повторные попытки при временных ошибках (exponential backoff).
- **Graceful Degradation:** При недоступности реестра Image Updater продолжает работать с последней известной версией.
- **Мониторинг:** Добавьте алерты на CrashLoopBackOff пода Image Updater. Экспортируются Prometheus метрики (`argocd_image_updater_*`).

### GitOps Best Practices

- **Отдельные CR на среду:** Используйте разные `ImageUpdater` CR для prod/staging/dev с разными `writeBackConfig` и стратегиями.
- **SemVer ranges в imageName:** Задавайте фильтры прямо в `imageName` (`harbor.example.com/app:^1.0`), а не в отдельных полях.
- **allowTags / ignoreTags:** Всегда указывайте `allowTags` regex для production, чтобы избежать случайного обновления на `latest` или pre-release.
- **Digest pinning для critical:** Для критических сервисов используйте `updateStrategy: digest` — обновление только при изменении SHA256 дайджеста.
- **Webhook вместо polling:** Настройте webhook receiver в Harbor/Quay/Docker Hub для немедленной реакции, уменьшите `check.interval` до `10m`-`30m`.

### Устранение проблем

- **Логирование:** Включите `log.level: debug` в ConfigMap для отладки, затем верните `info`.
- **Тестирование:** Используйте отдельный `ImageUpdater` CR с `method: argocd` для тестирования в Dev/QA среде.
- **Откат:** При проблемах с обновлением используйте `argocd app rollback` (API write-back) или `git revert` (Git write-back).

## Ограничения и edge cases (v1.x)

### Ограничения

1. **Только чтение образов:** Image Updater не может создавать или удалять образы в реестре.
2. **Одновременная запись:** При использовании Git write-back возможны конфликты коммитов при параллельных обновлении нескольких ImageUpdater CR.
3. **Rate Limits:** Публичные реестры (Docker Hub) имеют ограничения на количество запросов.
4. **Docker Hub Rate Limiting:** Без аутентификации — 100 запросов в 6 часов для anonymous, 200 для authenticated.
5. **OCI:** Поддержка OCI-реестров ограничена (не все API доступны, зависит от registry-scanner).
6. **Multi-cluster:** В v1.x нет нативной поддержки multi-cluster (Application в другом кластере). Требует отдельный ImageUpdater в каждом кластере.
7. **spec.namespace removed:** Поле `spec.namespace` удалено в v1.0 — CR должен быть в том же namespace, что и Application.

### Edge Cases

1. **Несколько приложений:** Один `ImageUpdater` CR через `namePattern`/`labelSelector` может обновлять множество приложений одновременно.
2. **Диапазоны SemVer:** При использовании `^1.0` обновляются только минорные/патч версии (1.x.x), мажорные (2.0.0) — нет.
3. **Digest Pinning:** При фиксации по дайджесту (`digest`) обновления применяются только при появлении нового дайджеста в реестре (пересборка образа с тем же тегом).
4. **Latest Tag:** Использование `newest-build` без `allowTags` не рекомендуется для Production (нарушает детерминизм, может подхватить broken build).
5. **Временные ошибки реестра:** Image Updater повторяет попытки при временных ошибках с exponential backoff.
6. **Конфликты Git:** При параллельных коммитах в Git возможны конфликты — использует `git merge` стратегию, при конфликте повторяет через интервал.
7. **Аннотации (legacy):** Image Updater v1.x не валидирует legacy аннотации — ошибки в синтаксисе приводят к тихим сбоям. Мигрируйте на CRD.
8. **Registry-scanner sidecar:** В v1.2+ registry-scanner вынесен в отдельный контейнер — проверяйте логи обоих контейнеров при проблемах с опросом реестра.

## Дополнительная информация

### См. также

- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.

### Связанные документы

- [Argo CD: Обзор системы](./argocd_overview.md)
- [Синхронизация в Argo CD](./synchronization.md)
- [Версионирование и тегирование образов](../../Docker/Docker_registries/image_versioning_and_tagging.md)

### Официальные ресурсы

- [Документация Argo CD Image Updater v1.x](https://argocd-image-updater.readthedocs.io/en/stable/)
- [Argo CD Image Updater — GitHub](https://github.com/argoproj-labs/argocd-image-updater)
- [Migration Guide: Annotations to CRD](https://argocd-image-updater.readthedocs.io/en/stable/configuration/migration/)
