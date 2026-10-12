# Argo CD Image Updater — автоматизация обновления образов

**Актуально для:** Argo CD Image Updater v1.3.x (архитектура CRD `ImageUpdater`, модуль `registry-scanner` v1.x; совместимо с Argo CD v3.1–v3.5+; поддержка legacy-аннотаций v0.x)

**Argo CD Image Updater** — специализированный контроллер для Argo CD (проект под эгидой `argoproj-labs`), отслеживающий появление новых версий образов в реестрах контейнеров и автоматически актуализирующий параметры приложений Argo CD. Инструмент реализует полностью автоматизированный цикл непрерывного развертывания (Continuous Deployment, CD) в парадигме GitOps: сборка и публикация нового контейнера в локальном или корпоративном реестре инициируют создание Git-коммита с обновленным тегом без ручного вмешательства инженера.

## Предварительные требования

| # | Требование | Детали | Команда проверки | Ожидаемый результат |
|---|------------|--------|------------------|---------------------|
| 1 | **Kubernetes кластер** | v1.28+ (On-Premises bare-metal, kubeadm, k3s, Talos). Требуется поддержка `apiextensions.k8s.io/v1` для CRD. | `kubectl version -o json \| jq -r .serverVersion.gitVersion` | `v1.28.x` или выше |
| 2 | **Argo CD** | v3.1–v3.5+ установлен в кластере. Image Updater взаимодействует с CRD `applications.argoproj.io`. | `kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server` | `argocd-server-... 1/1 Running` |
| 3 | **Реестр образов (On-Premises)** | Доступ к корпоративному OCI/Docker v2 реестру (Harbor, GitLab Container Registry, Nexus OSS/Pro, Quay, Docker Registry v2). | `crane auth login harbor.corp.internal -u robot-ci -p "$ROBOT_TOKEN"` | `Login Succeeded` |
| 4 | **Корпоративный корневой CA** | При использовании внутреннего TLS в Harbor/GitLab сертификат CA должен быть доступен для монтирования в под контроллера. | `openssl s_client -connect harbor.corp.internal:443 -servername harbor.corp.internal </dev/null 2>/dev/null \| grep 'Verify return code'` | `Verify return code: 0 (ok)` |
| 5 | **Git-сервер (для Git write-back)** | Доступ на запись (push) в корпоративный Git (GitLab CE/EE, Gitea, Forgejo, Bitbucket Server). Аутентификация: SSH Deploy Key или HTTP Personal/Project Access Token. | `ssh -T -i /path/to/deploy_key git@gitlab.corp.internal` | `Welcome to GitLab, @deploy-bot!` |
| 6 | **Helm / Kustomize** | Утилиты шаблонизации в составе приложений Argo CD (`values.yaml` для Helm или `kustomization.yaml` для Kustomize). | `helm version --short && kustomize version` | `v3.14.x` / `v5.3.x` |
| 7 | **RBAC в кластере** | ServiceAccount контроллера с правами `get/list/watch/update/patch` на ресурсы `applications.argoproj.io`, `imageupdaters.argoproj.io`, `configmaps`, `secrets`. | `kubectl auth can-i patch applications.argoproj.io --as=system:serviceaccount:argocd:argocd-image-updater -n argocd` | `yes` |
| 8 | **Сетевой доступ (Egress)** | Исходящий трафик от пода `argocd-image-updater` к реестрам контейнеров (TCP 443) и к Git-серверу (TCP 22 / 443). | `kubectl run test-egress --rm -i --restart=Never --image=curlimages/curl -- curl -kfsS -o /dev/null https://harbor.corp.internal/api/v2.0/ping` | `# → завершение с кодом 0` |

---

## Термины и определения

| Термин | Определение |
|--------|-------------|
| **Image Updater** | Контроллер Kubernetes, опрашивающий API реестров контейнеров, вычисляющий целевой тег по заданной стратегии и инициирующий обновление манифестов приложения Argo CD. |
| **ImageUpdater CR** | Пользовательский ресурс Kubernetes (`imageupdaters.argocd-image-updater.argoproj.io`), определяющий правила отслеживания образов, селекторы приложений и параметры записи изменений (стандарт в v1.x). |
| **Write-back Method** | Механизм сохранения новой версии образа: **Git write-back** (декларативный, коммит в Git-репозиторий) или **API write-back** (императивный, оперативная память Argo CD). |
| **Git Write-back Target** | Место записи изменений в репозитории: файл параметров Helm (`helmvalues:./path/values.yaml`) или оверлей Kustomize (`kustomizeimage:./path`). По умолчанию создает вспомогательный файл `.argocd-source-<app-name>.yaml`. |
| **Update Strategy** | Алгоритм выбора целевого тега из реестра: `semver` (семантические диапазоны), `newest-build` (по метке времени создания образа), `name` (алфавитная сортировка), `digest` (SHA256 дайджест). |
| **Digest Pinning** | Фиксация образа по неизменяемому криптографическому дайджесту манифеста (`@sha256:...`). Гарантирует побайтовую неизменность запущенного контейнера. |
| **Registry Scanner** | Внутренний модуль Image Updater v1.x, отвечающий за взаимодействие с OCI Distribution Specification / Docker Registry HTTP API V2, получение списка тегов и манифестов. |
| **Webhook Receiver** | Встроенный HTTP-сервер Image Updater (порт 8080), принимающий push-уведомления от реестров контейнеров (Harbor, GitLab) для немедленного обновления без ожидания таймера `check.interval`. |
| **Legacy Annotations** | Устаревший механизм конфигурации v0.x через аннотации ресурса `Application` (`argocd-image-updater.argoproj.io/*`). Поддерживается в v1.x в режиме обратной совместимости. |
| **Allow / Ignore Tags** | Фильтры регулярных выражений (RegEx) для включения или исключения определенных тегов реестра перед выполнением стратегии ранжирования. |

---

## Базовые концепции и архитектура

### Архитектура компонентов (v1.x)

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                       Argo CD Image Updater: Архитектура v1.x                           │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌────────────────────────┐                         ┌────────────────────────────────┐  │
│  │ Corporate Container    │                         │ Argo CD Control Plane          │  │
│  │ Registry               │                         │                                │  │
│  │ (Harbor / GitLab /     │                         │ ┌────────────────────────────┐ │  │
│  │  Nexus / OCI Registry) │                         │ │ Application Controller     │ │  │
│  └───────────┬────────────┘                         │ └──────────────▲─────────────┘ │  │
│              │ OCI / Manifest API                                    │ Watches       │  │
│              │ (Tags, Digests)                                       │ Applications  │  │
│              ▼                                                       │               │  │
│  ┌────────────────────────────────────────────────────────┐          │               │  │
│  │  argocd-image-updater (Pod)                            │          │               │  │
│  │                                                        │          │               │  │
│  │  ┌──────────────────┐       ┌───────────────────────┐  │          │               │  │
│  │  │ Webhook Receiver │       │ Controller Core       │  │          │               │  │
│  │  │ (:8080/webhook)  │───┐   │ (Reconciliation Loop) │  │          │               │  │
│  │  └──────────────────┘   │   └───────────┬───────────┘  │          │               │  │
│  │                         │               │              │          │               │  │
│  │  ┌──────────────────┐   │               ▼              │          │               │  │
│  │  │ Registry Scanner │◀──┴─── ┌───────────────────────┐ │          │               │  │
│  │  │ Engine           │        │ Git Client (go-git)   │ │          │               │  │
│  │  └──────────────────┘        │ (SSH / HTTPS Tokens)  │ │          │               │  │
│  └──────────────────────────────┴──────────┬────────────┴─┘          │               │  │
│                                            │                         │               │  │
│              ┌─────────────────────────────┘ Git Push                │               │  │
│              │                               (Commit & Tag)          │ Sync          │  │
│              ▼                                                       │ Loop          │  │
│  ┌────────────────────────┐                                          │               │  │
│  │ Corporate Git Server   │──────────────────────────────────────────┘               │  │
│  │ (GitLab / Gitea /      │  (Polls Git / Webhook)                                   │  │
│  │  Bitbucket Server)     │                                                          │  │
│  └────────────────────────┘                                                          │  │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### Жизненный цикл сверки (Reconciliation Loop)

1. **Обнаружение объектов ImageUpdater:** Контроллер отслеживает CR `ImageUpdater` в пространстве имен Argo CD.
2. **Селекция целевых приложений:** На основе полей `applicationRefs.namePattern` (glob) и `applicationRefs.labelSelector` выбираются активные `Application` Argo CD.
3. **Получение текущего состояния образов:** Контроллер инспектирует манифесты приложения (`spec.source.helm.parameters`, `spec.source.kustomize.images` или файл `.argocd-source-<app-name>.yaml`).
4. **Запрос к реестру через `registry-scanner`:**
   - Выполняется аутентификация в реестре (используется Secret типа `kubernetes.io/dockerconfigjson` или учетные данные из `registries.conf`).
   - Получается список всех доступных тегов репозитория.
5. **Фильтрация и ранжирование:**
   - Исключаются теги, подпадающие под `ignoreTags`.
   - Проверяется соответствие паттерну `allowTags`.
   - Применяется выбранная стратегия (`semver`, `newest-build`, `name`, `digest`).
6. **Принятие решения об обновлении:**
   - Если найденный тег идентичен текущему — операция завершается без действий.
   - Если найден более свежий тег — запускается процедура Write-back.
7. **Фиксация изменений (Write-back):**
   - **Git write-back:** клонирование ветки через `go-git`, обновление целевого файла параметров, коммит (опционально с GPG/SSH подписью) и `git push`.
   - **API write-back:** вызов gRPC/REST API Argo CD для обновления in-memory параметров в `Application.spec.source`.
8. **Реакция Argo CD:** Argo CD фиксирует изменение в Git (или API) и выполняет автоматическую синхронизацию (Auto-Sync) в кластер.

---

### Сравнение методов фиксации: Git vs API

| Критерий | Git write-back (Декларативный) | API write-back (Императивный) |
| :--- | :--- | :--- |
| **Соответствие GitOps** | **Полное (SSoT)**: Репозиторий всегда отражает реальность | **Частичное**: Параметры живут в Argo CD, Git отстает |
| **История и аудит** | Полная история коммитов в Git с автором и временем | Только логи контроллера и Kubernetes Events |
| **Устойчивость к сбоям** | Высокая: при переустановке Argo CD состояние сохраняется | Низкая: при сбросе кэша Argo CD теги возвращаются к исходным |
| **Откат (Rollback)** | Нативный: стандартная команда `git revert` | Через интерфейс Argo CD (`argocd app rollback`) |
| **Сетевые требования** | Нужен доступ на запись (push) в Git-репозиторий | Доступ только к Kubernetes API / Argo CD API |
| **Риск конфликтов** | Возможен Non-fast-forward конфликт при параллельных коммитах | Отсутствует |
| **Область применения** | **Production, Staging, Pre-prod** | **Dev, QA, эфемерные динамические стенды** |

---

### Механика Git Write-back и файл переопределений

При использовании метода `git` контроллер не пытается напрямую парсить сложные шаблоны Jinja или нестандартные конструкции Helm. По умолчанию контроллер создает в целевом каталоге приложения файл переопределений:

```
.argocd-source-<application-name>.yaml
```

**Пример содержимого для Helm:**
```yaml
helm:
  parameters:
  - name: image.tag
    value: 1.4.2
    forceString: true
```

**Пример содержимого для Kustomize:**
```yaml
kustomize:
  images:
  - harbor.corp.internal/apps/backend:1.4.2
```

Argo CD автоматически считывает файлы с префиксом `.argocd-source-` и накладывает их поверх базовой конфигурации манифестов перед рендерингом. При необходимости прямой модификации файлов репозитория используется параметр `writeBackTarget` (например, `helmvalues:./values.yaml`).

---

### Стратегии выбора версий (Update Strategies)

| Стратегия | Принцип работы | Примеры входных данных | Назначение |
| :--- | :--- | :--- | :--- |
| `semver` | Парсинг тегов по спецификации SemVer 2.0. Поддерживает ограничения (`^`, `~`, `>`, `<=`). | `^1.2` → выберет `1.2.9`, но пропустит `1.3.0`<br>`~1.2.0` → только патчи `1.2.x` | Стабильные продуктовые среды с гарантией обратной совместимости API. |
| `newest-build` | Сравнение даты создания манифеста образа (`created` timestamp из OCI/Docker config). | Сборки с хэшами Git: `feat-login-a1b2c3d`, `master-8f9e0d1` | Стенды разработки (Dev/QA), сборки из основной ветки. |
| `name` | Сортировка по алфавиту (лексикографический порядок). | Теги формата дат: `2026.10.01`, `2026.10.02` | Системы с версионированием по CalVer или алфавитным индексам. |
| `digest` | Отслеживание изменения SHA256 хэша манифеста при неизменном теге. | Мутабельный тег `:stable` или `:release-1.0` | Критические сервисы с неизменяемым дайджестом и защитой от подмены. |

---

### Спецификация CRD `ImageUpdater` (`v1alpha1`)

| Поле спецификации | Тип | Описание |
| :--- | :--- | :--- |
| `spec.writeBackConfig.method` | `string` | Метод сохранения: `git` или `argocd`. |
| `spec.writeBackConfig.gitConfig.repository` | `string` | URL Git-репозитория (`git@gitlab.corp...` или `https://...`). |
| `spec.writeBackConfig.gitConfig.branch` | `string` | Ветка репозитория для коммитов (например, `main`, `release/prod`). |
| `spec.writeBackConfig.gitConfig.writeBackTarget` | `string` | Целевой файл: `helmvalues:./values.yaml`, `kustomizeimage:./overlay`. |
| `spec.writeBackConfig.gitConfig.user` | `string` | Имя автора Git-коммита (дефолт: `argocd-image-updater`). |
| `spec.writeBackConfig.gitConfig.email` | `string` | Email автора Git-коммита. |
| `spec.applicationRefs[].namePattern` | `string` | Шаблон имен приложений Argo CD (поддерживает glob: `prod-*`, `backend`). |
| `spec.applicationRefs[].labelSelector` | `string` | Селектор меток Kubernetes для фильтрации Application. |
| `spec.applicationRefs[].images[].alias` | `string` | Уникальный псевдоним образа в рамках списка `images`. |
| `spec.applicationRefs[].images[].imageName` | `string` | Полный путь к образу в реестре с возможным SemVer фильтром. |
| `spec.applicationRefs[].images[].commonUpdateSettings.updateStrategy` | `string` | Стратегия обновления: `semver`, `newest-build`, `name`, `digest`. |
| `spec.applicationRefs[].images[].commonUpdateSettings.allowTags` | `string` | Регулярное выражение (RegEx) допустимых тегов. |
| `spec.applicationRefs[].images[].commonUpdateSettings.ignoreTags` | `[]string` | Список тегов или масок, исключаемых из поиска. |
| `spec.applicationRefs[].images[].commonUpdateSettings.pullSecret` | `string` | Ссылка на Secret доступа (`secret://<namespace>/<name>`). |
| `spec.applicationRefs[].images[].commonUpdateSettings.platforms` | `[]string` | Фильтрация архитектур: `["linux/amd64"]`, `["linux/arm64"]`. |

---

## Настройка и конфигурация

### Конфигурация контроллера (`argocd-image-updater-config`)

Файл конфигурации `registries.conf` внутри ConfigMap описывает реестры, правила аутентификации и системные таймауты:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  # Интервал опроса реестров по умолчанию (Go duration syntax)
  check.interval: "3m"
  # Уровень детализации журналов: trace, debug, info, warn, error
  log.level: "info"
  # Таймаут запросов к реестрам
  registries.conf: |
    registries:
    - name: Enterprise Harbor
      prefix: harbor.corp.internal
      api_url: https://harbor.corp.internal/api/v2.0
      credentials: secret://argocd/harbor-robot-secret
      default: false
      insecure: false
      ping: true

    - name: Internal GitLab Registry
      prefix: registry.gitlab.corp.internal
      api_url: https://registry.gitlab.corp.internal
      credentials: secret://argocd/gitlab-registry-token
      default: false
      insecure: false

    - name: Nexus Repository Manager
      prefix: nexus.corp.internal:8082
      api_url: https://nexus.corp.internal:8082
      credentials: secret://argocd/nexus-docker-secret
      default: false
      insecure: false

    - name: Docker Hub (Public Mirror / Upstream)
      prefix: docker.io
      api_url: https://registry.hub.docker.com
      credentials: secret://argocd/dockerhub-pull-secret
      default: true
```

---

### Секреты аутентификации для реестров и Git

#### 1. Секрет для реестра контейнеров (Robot Account / Token)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: harbor-robot-secret
  namespace: argocd
type: kubernetes.io/dockerconfigjson
data:
  # Base64 кодированное содержимое auth config
  .dockerconfigjson: eyJhdXRocyI6eyJoYXJib3IuY29ycC5pbnRlcm5hbCI6eyJ1c2VybmFtZSI6InJvYm90JGFyZ29jZC11cGRhdGVyIiwicGFzc3dvcmQiOiJTT01FX1NFQ1JFVF9UT0tFTiJ9fX0=
```

#### 2. Секрет с приватным SSH-ключом для Git Write-back

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: git-writeback-ssh-creds
  namespace: argocd
type: Opaque
stringData:
  sshPrivateKey: |
    -----BEGIN OPENSSH PRIVATE KEY-----
    b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
    QyNTUxOQAAACBP2Z3jEXAMPLEEXAMPLEEXAMPLEEXAMPLEEXAMPLEEXAMPLEAAAIEB
    -----END OPENSSH PRIVATE KEY-----
```

---

## Практические сценарии

### Сценарий 1: Установка Image Updater v1.3.x с корпоративным Root CA

Развертывание через официальный Helm-чарт с монтированием корпоративного корневого сертификата для бесперебойной работы с внутренним Harbor/GitLab.

```bash
# 1. Добавление репозитория argo-helm
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
# → "argo" has been added to your repositories
# → Update Complete. ⎈Successfully got an update from the "argo" chart repository

# 2. Создание ConfigMap с корпоративным корневым CA сертификатом
kubectl create configmap corporate-ca-certs \
  --from-file=ca-certificates.crt=/etc/ssl/certs/corporate-root-ca.crt \
  -n argocd
# → configmap/corporate-ca-certs created

# 3. Установка Helm-чарта с монтированием CA и сервисным аккаунтом
cat << 'EOF' > /tmp/image-updater-values.yaml
config:
  logLevel: info
  checkInterval: 2m
extraVolumes:
  - name: ca-bundle
    configMap:
      name: corporate-ca-certs
extraVolumeMounts:
  - name: ca-bundle
    mountPath: /etc/ssl/certs/ca-certificates.crt
    subPath: ca-certificates.crt
    readOnly: true
metrics:
  enabled: true
  serviceMonitor:
    enabled: false
securityContext:
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 10001
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
EOF

helm install argocd-image-updater argo/argocd-image-updater \
  --namespace argocd \
  --version 1.3.1 \
  -f /tmp/image-updater-values.yaml
# → NAME: argocd-image-updater
# → STATUS: deployed
# → REVISION: 1

# 4. Проверка запуска пода и установки CRD
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-image-updater
# → NAME                                    READY   STATUS    RESTARTS   AGE
# → argocd-image-updater-7bb5df74bd-x8k9m   1/1     Running   0          25s

kubectl get crd imageupdaters.argocd-image-updater.argoproj.io
# → NAME                                              CREATED AT
# → imageupdaters.argocd-image-updater.argoproj.io   2026-10-12T10:00:00Z
```

---

### Сценарий 2: Production Git Write-back с Helm (SemVer)

Конфигурация для продуктовой среды: обновление разрешено только в рамках мажорной версии `2.x.x` (`^2.0`), коммиты пишутся напрямую в репозиторий через SSH, параметры переопределяются в `values.yaml`.

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: billing-prod-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@gitlab.corp.internal:finance/billing-service-gitops.git"
      branch: "main"
      writeBackTarget: "helmvalues:./deploy/helm/values.yaml"
      user: "ArgoCD Automation Bot"
      email: "gitops-bot@corp.internal"
  applicationRefs:
  - namePattern: "billing-service-prod"
    images:
    - alias: "billing-api"
      imageName: "harbor.corp.internal/finance/billing-api:^2.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        allowTags: "^v?2\\.[0-9]+\\.[0-9]+$"
        ignoreTags: ["*alpha*", "*beta*", "*rc*", "*dev*"]
        pullSecret: "secret://argocd/harbor-robot-secret"
        platforms:
        - "linux/amd64"
```

**Ожидаемый результат коммита в `deploy/helm/values.yaml`:**
```yaml
image:
  repository: harbor.corp.internal/finance/billing-api
  tag: "2.4.1" # Обновлено контроллером с версии 2.3.9
```

---

### Сценарий 3: Git Write-back с Kustomize (`kustomizeimage`)

Для проектов, использующих нативный Kustomize, контроллер переопределяет секцию `images` в целевом `kustomization.yaml`.

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: frontend-kustomize-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@gitlab.corp.internal:frontend/portal-gitops.git"
      branch: "main"
      writeBackTarget: "kustomizeimage:./environments/production"
      user: "Image Updater Bot"
      email: "updater@corp.internal"
  applicationRefs:
  - namePattern: "portal-prod"
    images:
    - alias: "web-ui"
      imageName: "harbor.corp.internal/frontend/portal-ui:^1.12"
      commonUpdateSettings:
        updateStrategy: "semver"
        pullSecret: "secret://argocd/harbor-robot-secret"
```

**Ожидаемый `environments/production/kustomization.yaml` после обновления:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
- ../../base
images:
- name: harbor.corp.internal/frontend/portal-ui
  newTag: "1.12.5"
```

---

### Сценарий 4: Git Write-back с Argo CD Source Hydrator и Multiple Sources

В Argo CD v3.5+ и Image Updater v1.3.1+ реализована поддержка объединения параметров для приложений со сложной структурой источников (SourceHydrator / Multi-Source).

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: hydrator-app-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@gitlab.corp.internal:infra/app-configs.git"
      branch: "main"
      # Указывается целевой путь внутри репозитория конфигураций
      writeBackTarget: "helmvalues:./values-override.yaml"
  applicationRefs:
  - namePattern: "hydrated-order-processor"
    images:
    - alias: "processor"
      imageName: "harbor.corp.internal/logistics/order-processor:~3.1.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        pullSecret: "secret://argocd/harbor-robot-secret"
```

Контроллер корректно фиксирует значения тегов в репозитории конфигурации без перезаписи манифестов родительских Helm-чартов, загружаемых из независимых репозиториев.

---

### Сценарий 5: API Write-back для Dev/QA сред (In-Memory Override)

Для тестовых и динамических сред постоянная генерация Git-коммитов засоряет историю репозитория. Метод `argocd` сохраняет новые теги непосредственно в оперативной памяти Argo CD через его API.

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: dev-qa-fast-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "argocd"
  applicationRefs:
  - namePattern: "*-dev"
    labelSelector: "env=development"
    images:
    - alias: "backend"
      imageName: "harbor.corp.internal/dev/core-api"
      commonUpdateSettings:
        updateStrategy: "newest-build"
        pullSecret: "secret://argocd/harbor-robot-secret"
        allowTags: "^feature-.*$"
```

**Проверка результата переопределения через CLI:**
```bash
argocd app get auth-service-dev -o json | jq .spec.source.helm.parameters
# → [
# →   {
# →     "name": "image.tag",
# →     "value": "feature-auth-refactor-98a72b",
# →     "forceString": true
# →   }
# → ]
```

---

### Сценарий 6: On-Premises Harbor Push Webhook Receiver

При классическом опросе реестра по таймеру задержка деплоя составляет от 2 до 10 минут. Настройка Webhook Receiver обеспечивает немедленный отклик (до 5 секунд) после публикации артефакта в Harbor.

#### 1. Создание Service и Ingress для Webhook Receiver

```yaml
apiVersion: v1
kind: Service
metadata:
  name: argocd-image-updater-webhook
  namespace: argocd
spec:
  ports:
  - name: webhook
    port: 8080
    targetPort: 8080
  selector:
    app.kubernetes.io/name: argocd-image-updater
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-image-updater-webhook
  namespace: argocd
  annotations:
    cert-manager.io/cluster-issuer: "corp-ca-issuer"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
spec:
  ingressClassName: nginx
  rules:
  - host: image-updater-hook.corp.internal
    http:
      paths:
      - path: /webhook
        pathType: Prefix
        backend:
          service:
            name: argocd-image-updater-webhook
            port:
              number: 8080
  tls:
  - hosts:
    - image-updater-hook.corp.internal
    secretName: image-updater-webhook-tls
```

#### 2. Настройка Webhook в Harbor

В интерфейсе Harbor (`Administration` → `Projects` → `<project>` → `Webhooks`):
- **Endpoint URL:** `https://image-updater-hook.corp.internal/webhook`
- **Event Types:** отмечен флаг `Artifact pushed` (`PUSH_ARTIFACT`).
- **Auth Header:** при необходимости передача секретного токена заголовка.

При завершении команды `docker push` Harbor отправляет JSON-payload, контроллер немедленно инициирует проверку и обновление соответствующего `ImageUpdater` CR.

---

### Сценарий 7: Интеграция с GitLab Container Registry через Project Deploy Token

```yaml
# 1. Секрет с Deploy Token от проекта GitLab
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-deploy-token-secret
  namespace: argocd
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {
      "auths": {
        "registry.gitlab.corp.internal": {
          "username": "gitlab-deploy-token-12948",
          "password": "gldt-ABcdEFghIJklMNop12345"
        }
      }
    }
---
# 2. ImageUpdater ресурс
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: gitlab-services-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@gitlab.corp.internal:platform/k8s-manifests.git"
      branch: "main"
      writeBackTarget: "helmvalues:./apps/orders/values.yaml"
  applicationRefs:
  - namePattern: "orders-staging"
    images:
    - alias: "orders-app"
      imageName: "registry.gitlab.corp.internal/platform/orders-service:^1.5"
      commonUpdateSettings:
        updateStrategy: "semver"
        pullSecret: "secret://argocd/gitlab-deploy-token-secret"
```

---

### Сценарий 8: Digest Pinning для критических сервисов

При использовании стратегии `digest` гарантируется полная детерминированность: образ жестко привязывается к SHA256-хэшу манифеста. Обновление срабатывает только тогда, когда в реестре пересобирается образ и появляется новый дайджест.

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: core-banking-digest-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@gitlab.corp.internal:banking/core-deployments.git"
      branch: "main"
      writeBackTarget: "helmvalues:./services/ledger/values.yaml"
  applicationRefs:
  - namePattern: "banking-ledger-prod"
    images:
    - alias: "ledger-engine"
      imageName: "harbor.corp.internal/banking/ledger:stable"
      commonUpdateSettings:
        updateStrategy: "digest"
        pullSecret: "secret://argocd/harbor-robot-secret"
```

**Результат в `values.yaml`:**
```yaml
image:
  repository: harbor.corp.internal/banking/ledger
  tag: "stable@sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069"
```

---

### Сценарий 9: Пакетное управление несколькими средами в едином CR

Объединение логики Prod, Staging и Dev в одном манифесте с переопределением веток и стратегий на уровне селекторов:

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: crm-multi-env-updater
  namespace: argocd
spec:
  # Глобальные настройки Git write-back по умолчанию
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@gitlab.corp.internal:crm/gitops-deploy.git"
      user: "CRM AutoUpdater"
      email: "updater@corp.internal"
  applicationRefs:
  # 1. Production: коммиты в main, строгий SemVer
  - namePattern: "crm-prod-*"
    writeBackConfig:
      method: "git"
      gitConfig:
        branch: "main"
        writeBackTarget: "helmvalues:./env/prod/values.yaml"
    images:
    - alias: "crm-backend"
      imageName: "harbor.corp.internal/crm/backend:^3.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        allowTags: "^v?3\\.[0-9]+\\.[0-9]+$"
        pullSecret: "secret://argocd/harbor-robot-secret"

  # 2. Staging: коммиты в ветку develop, NewestBuild
  - namePattern: "crm-stage-*"
    writeBackConfig:
      method: "git"
      gitConfig:
        branch: "develop"
        writeBackTarget: "helmvalues:./env/stage/values.yaml"
    images:
    - alias: "crm-backend"
      imageName: "harbor.corp.internal/crm/backend"
      commonUpdateSettings:
        updateStrategy: "newest-build"
        pullSecret: "secret://argocd/harbor-robot-secret"

  # 3. Dev: API write-back (без коммитов в Git)
  - namePattern: "crm-dev-*"
    writeBackConfig:
      method: "argocd"
    images:
    - alias: "crm-backend"
      imageName: "harbor.corp.internal/crm/backend"
      commonUpdateSettings:
        updateStrategy: "newest-build"
        pullSecret: "secret://argocd/harbor-robot-secret"
```

---

### Сценарий 10: Пошаговая миграция с legacy-аннотаций (v0.x) на CRD (v1.x)

До версии v1.0.0 конфигурация Image Updater выполнялась исключительно через аннотации `Application`. В v1.x аннотации считаются устаревшими (legacy).

#### Пример исходной конфигурации через аннотации (Legacy v0.x):
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-service
  namespace: argocd
  annotations:
    argocd-image-updater.argoproj.io/image-list: "app=harbor.corp.internal/pay/service:^1.2"
    argocd-image-updater.argoproj.io/app.update-strategy: "semver"
    argocd-image-updater.argoproj.io/write-back-method: "git"
    argocd-image-updater.argoproj.io/app.helm.image-name: "image.repository"
    argocd-image-updater.argoproj.io/app.helm.image-tag: "image.tag"
spec:
  # ...
```

#### Пошаговый план миграции:

1. **Создание эквивалентного ресурса `ImageUpdater`:**
   ```yaml
   apiVersion: argocd-image-updater.argoproj.io/v1alpha1
   kind: ImageUpdater
   metadata:
     name: payment-service-updater
     namespace: argocd
   spec:
     writeBackConfig:
       method: "git"
       gitConfig:
         branch: "main"
         writeBackTarget: "helmvalues:./values.yaml"
     applicationRefs:
     - namePattern: "payment-service"
       images:
       - alias: "app"
         imageName: "harbor.corp.internal/pay/service:^1.2"
         commonUpdateSettings:
           updateStrategy: "semver"
           pullSecret: "secret://argocd/harbor-robot-secret"
   ```
2. **Применение CR в кластер:**
   ```bash
   kubectl apply -f payment-service-updater.yaml
   # → imageupdater.argocd-image-updater.argoproj.io/payment-service-updater created
   ```
3. **Удаление legacy-аннотаций из `Application`:**
   ```bash
   kubectl annotate application payment-service -n argocd \
     argocd-image-updater.argoproj.io/image-list- \
     argocd-image-updater.argoproj.io/app.update-strategy- \
     argocd-image-updater.argoproj.io/write-back-method- \
     argocd-image-updater.argoproj.io/app.helm.image-name- \
     argocd-image-updater.argoproj.io/app.helm.image-tag-
   # → application.argoproj.io/payment-service annotated
   ```
4. **Проверка логов контроллера на отсутствие конфликтов:**
   ```bash
   kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater --tail=50 | grep "payment-service"
   # → time="..." level=info msg="Processing application payment-service with CRD configuration"
   ```

---

## Сравнение с альтернативами

| Критерий | Argo CD Image Updater v1.x | Flux Image Automation Controller | Keel |
| :--- | :--- | :--- | :--- |
| **Архитектурная привязка** | Экосистема Argo CD (`argoproj-labs`) | Экосистема Flux v2 (CNCF Graduated) | Независимый контроллер K8s |
| **Метод изменения манифестов** | Запись в `.argocd-source-*` или указанный target файл | Прямое редактирование YAML по меткам `# {"$imagepolicy": ...}` | Прямой патч Deployment в API K8s |
| **Соответствие GitOps** | Высокое (Git write-back) или среднее (API) | Высокое (всегда коммит в Git) | Низкое (обходит Git, пишет в кластер) |
| **Управление политиками** | Декларативное CRD `ImageUpdater` или аннотации | Три CRD: `ImageRepository`, `ImagePolicy`, `ImageUpdateAutomation` | Аннотации в Deployment / HelmRelease |
| **Поддержка Webhook** | Встроенный HTTP Receiver (:8080) | Через Flux `Receiver` CRD | Встроенный Webhook Receiver |
| **Подпись коммитов** | Поддерживается GPG / SSH | Поддерживается GPG / Cosign | Не поддерживается |
| **Порог входа** | Низкий для пользователей Argo CD | Средний (требует связки трех CRD) | Минимальный |

---

## Эксплуатация и мониторинг

### Операционные команды

| Задача | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| **Список всех CR ImageUpdater** | `kubectl get imageupdater -n argocd` | `NAME READY AGE`<br>`prod-updater True 4d` |
| **Просмотр детального состояния CR** | `kubectl describe imageupdater prod-updater -n argocd` | Секции `Spec` и `Status` без ошибок валидации |
| **Логирование процесса сканирования** | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater -f` | `level=info msg="Successfully evaluated image tag..."` |
| **Проверка списка тегов в Harbor через crane** | `crane ls harbor.corp.internal/apps/backend` | Список тегов (`1.0.0`, `1.0.1`, `1.1.0`) |
| **Проверка манифеста и дайджеста образа** | `crane manifest harbor.corp.internal/apps/backend:1.1.0 \| jq .config.digest` | `"sha256:4b227777d4da1fc...\"` |
| **Принудительный запуск проверки (Force Check)** | `kubectl annotate application billing-service-prod -n argocd argocd-image-updater.argoproj.io/force-update=true --overwrite` | `application.argoproj.io/billing-service-prod annotated` |
| **Ручная эмуляция вызова Webhook через curl** | `curl -s -X POST http://localhost:8080/webhook -H "Content-Type: application/json" -d '{"event_data":{"resources":[{"resource_url":"harbor.corp.internal/apps/backend:1.1.1"}]}}'` | `{"status":"success","message":"webhook received"}` |

---

### Мониторинг и метрики Prometheus

Image Updater экспортирует метрики на эндпоинте `:8080/metrics`:

```bash
kubectl run curl-metrics --rm -i --restart=Never --image=curlimages/curl -- \
  curl -s http://argocd-image-updater.argocd.svc.cluster.local:8080/metrics | grep argocd_image_updater
```

#### Ключевые метрики Prometheus:

| Метрика | Тип | Назначение |
| :--- | :--- | :--- |
| `argocd_image_updater_images_checked_total` | Counter | Количество выполненных проверок образов (лейблы: `application`, `image`). |
| `argocd_image_updater_images_updated_total` | Counter | Количество успешно обновленных версий образов (лейблы: `application`, `image`, `method`). |
| `argocd_image_updater_images_errors_total` | Counter | Количество ошибок сканирования или оценки тегов. |
| `argocd_image_updater_git_commit_errors_total` | Counter | Количество сбоев при создании коммита или отправке `git push`. |
| `argocd_image_updater_registry_requests_total` | Counter | Количество HTTP-запросов к API реестров контейнеров. |

---

### Правила алертинга PrometheusRule

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: argocd-image-updater-alerts
  namespace: argocd
  labels:
    role: alert-rules
spec:
  groups:
  - name: argocd-image-updater.rules
    rules:
    - alert: ImageUpdaterGitCommitFailed
      expr: rate(argocd_image_updater_git_commit_errors_total[15m]) > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Сбой Git Write-back в Argo CD Image Updater"
        description: "Контроллер не может выполнить git push в репозиторий приложения {{ $labels.application }}. Проверьте SSH-ключи, права ветки и конфликты коммитов."

    - alert: ImageUpdaterRegistryErrorRate
      expr: rate(argocd_image_updater_images_errors_total[15m]) > 0.1
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Высокий уровень ошибок при опросе реестра контейнеров"
        description: "Ошибки связи с реестром образов для приложения {{ $labels.application }}. Возможен сбой аутентификации, истечение срока токена или сетевая недоступность."

    - alert: ImageUpdaterDown
      expr: absent(up{job="argocd-image-updater"} == 1)
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Под argocd-image-updater недоступен"
        description: "Контроллер Image Updater не отвечает более 5 минут. Проверьте CrashLoopBackOff или исчерпание памяти (OOMKilled)."
```

---

## Диагностика и устранение неполадок

### Матрица типовых инцидентов

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `x509: certificate signed by unknown authority` | Контроллер не доверяет самоподписанному сертификату корпоративного Harbor/GitLab. | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater \| grep x509` | Смонтировать корневой CA в `/etc/ssl/certs/ca-certificates.crt` или указать `insecure: true` в `registries.conf` (для тестовых стендов). |
| `push failed: [remote rejected] (non-fast-forward)` | Конфликт коммитов: ветка в удаленном репозитории изменилась быстрее, чем отработал пуш контроллера. | `kubectl logs ... \| grep "failed to push"` | Контроллер автоматически повторяет попытку с rebase. При регулярных сбоях вынести целевой файл в отдельную изолированную ветку деплоя. |
| `could not find any matching image` | Имя образа в CR не совпадает с `imageName` в манифестах, либо теги не проходят regex-фильтр `allowTags`. | `kubectl describe imageupdater <name>`<br>`crane ls <image>` | Проверить точное совпадение префикса реестра и шаблона регулярного выражения в `allowTags`. |
| `authentication required / unauthorized` | Истек срок действия Robot Token или отсутствует `pullSecret` в `commonUpdateSettings`. | `kubectl get secret <secret-name> -n argocd -o yaml` | Обновить учетные данные в Secret, убедиться в наличии прав на чтение (Pull) в проекте Harbor/GitLab. |
| `invalid semver version format` | Теги в реестре содержат нестандартные префиксы или постфиксы (например, `build-2026.10-v1`), ломающие парсер SemVer. | `kubectl logs ... \| grep "SemVer"` | Задать строгий `allowTags: "^v?[0-9]+\\.[0-9]+\\.[0-9]+$"` или переключить стратегию на `name` / `newest-build`. |
| `path not found in repository / writeBackTarget` | Указанный в `writeBackTarget` путь к `values.yaml` или `kustomization.yaml` не существует в репозитории. | Проверить структуру Git: `git ls-tree -r --name-only HEAD` | Скорректировать относительный путь в `spec.writeBackConfig.gitConfig.writeBackTarget`. |

---

### Разбор инцидента: Ошибка проверки корпоративного TLS сертификата

**Лог ошибки:**
```text
time="2026-10-12T10:14:22Z" level=error msg="failed to inspect image harbor.corp.internal/apps/backend: Get \"https://harbor.corp.internal/v2/\": tls: failed to verify certificate: x509: certificate signed by unknown authority" application=backend-prod
```

**План восстановления:**
1. Извлечь действующий цепочечный CA сертификат корпоративного удостоверяющего центра:
   ```bash
   openssl s_client -showcerts -connect harbor.corp.internal:443 </dev/null 2>/dev/null | openssl x509 -outform PEM > /tmp/corp-ca.crt
   ```
2. Создать или обновить ConfigMap в пространстве имен `argocd`:
   ```bash
   kubectl create configmap custom-ca-bundle --from-file=ca-certificates.crt=/tmp/corp-ca.crt -n argocd --dry-run=client -o yaml | kubectl apply -f -
   # → configmap/custom-ca-bundle configured
   ```
3. Подключить ConfigMap в Deployment `argocd-image-updater`:
   ```yaml
   spec:
     template:
       spec:
         volumes:
         - name: ca-volume
           configMap:
             name: custom-ca-bundle
         containers:
         - name: argocd-image-updater
           volumeMounts:
           - name: ca-volume
             mountPath: /etc/ssl/certs/ca-certificates.crt
             subPath: ca-certificates.crt
             readOnly: true
   ```
4. Перезапустить под контроллера:
   ```bash
   kubectl rollout restart deployment argocd-image-updater -n argocd
   # → deployment.apps/argocd-image-updater restarted
   ```

---

## Рекомендации и лучшие практики

### Безопасность и ограничение привилегий (Security Hardening)

- **Контейнер без привилегий root:** Запуск пода от пользователя с UID `10001` (`runAsNonRoot: true`, `runAsUser: 10001`).
- **Неизменяемая файловая система:** Флаг `readOnlyRootFilesystem: true`. Временные директории для клонирования Git (`/tmp`) монтируются как `emptyDir`.
- **Сброс Linux Capabilities:** Удаление всех привилегий ядра: `capabilities.drop: ["ALL"]`.
- **Сетевая изоляция (NetworkPolicy):** Запрет входящего трафика за исключением порта `8080` (Webhook Receiver) от авторизованных адресов Ingress-контроллера.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-image-updater-netpol
  namespace: argocd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-image-updater
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8080
  egress:
  # DNS
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
  # HTTPS к реестру и Git
  - ports:
    - protocol: TCP
      port: 443
  # SSH к Git
  - ports:
    - protocol: TCP
      port: 22
```

---

### Архитектурные рекомендации SRE и системного администрирования

- **Отказ от `latest` в Production:** Запретить тег `latest` на уровне политики реестра (Harbor Immutable Tag Rules). Для боевых сервисов использовать строгое версионирование по SemVer (`^1.2`) либо Digest Pinning.
- **Использование Webhook вместо агрессивного поллинга:** Установка интервала `check.interval` на `15m`–`30m` в комбинации с Push Webhook. Это защищает корпоративный реестр от перегрузки миллионами холостых запросов к манифестам.
- **Изоляция веток развертывания:** Для предотвращения гонок и конфликтов коммитов (Git Push Conflicts) при массовом обновлении сервисов настройте Git write-back в специализированные ветки среды (`deploy/prod`, `deploy/staging`), изменения из которых мерджатся в `main` через автоматизированные пайплайны.
- **Ротация учетных записей:** Создавайте отдельные ограниченные Robot Accounts для каждого проекта в Harbor / GitLab. Никогда не используйте глобальные административные учетные записи.
- **Подпись Git-коммитов:** Контроллер поддерживает GPG-подпись коммитов через монтирование секретного ключа GPG (`spec.writeBackConfig.gitConfig.signingKey`). Это обеспечивает прохождение политик Branch Protection («Require signed commits»).

---

## Ограничения и граничные случаи (Edge Cases)

1. **Namespace Scoping в v1.x:** Поле `spec.namespace` удалено в v1.0.0. Ресурс `ImageUpdater` обязан находиться в том же пространстве имен, что и отслеживаемые им ресурсы `Application` (по умолчанию `argocd`).
2. **Мультикластерность:** В версии v1.x отсутствует нативная поддержка централизованного управления внешними кластерами из единого центра без прямого доступа контроллера к Application CRD. Рекомендуется развертывать экземпляр Image Updater в каждом кластере управления Argo CD.
3. **Параллельные коммиты в монорепозиториях:** Если один репозиторий содержит десятки микросервисов, одновременное срабатывание вебхуков может приводить к отклонению `git push` (`[remote rejected] non-fast-forward`). Контроллер реализует retry backoff, однако при высокой плотности релизов рекомендуется разделять репозитории конфигураций.
4. **Конфликты с инструментами обновления зависимостей (Renovate / Dependabot):** Если в репозитории параллельно работают Renovate и Image Updater, они могут модифицировать один и тот же файл `values.yaml`. Рекомендуется разграничивать зоны ответственности: Image Updater управляет приложением в `.argocd-source-*` или в оверлеях среды, а Renovate обновляет базовые чарты.

---

## Дополнительная информация

### См. также

- [Argo CD: Обзор системы](./argocd_overview.md) — общая архитектура, компоненты и жизненный цикл приложений.
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — расширенная работа с несколькими источниками манифестов.
- [Синхронизация в Argo CD](./synchronization.md) — механизмы сверки желаемого и фактического состояний.
- [Безопасность Argo CD](./argocd_security_hardening.md) — рекомендации по харденингу контрольной плоскости.
- [Версионирование и тегирование Docker-образов](../../Docker/Docker_registries/image_versioning_and_tagging.md) — стандарты семантического версионирования, иммутабельности и структуры тегов.
- [Harbor: Работа с реестром](../../Docker/Docker_registries/Harbor/usage.md) — настройка Robot Accounts, репликации и Webhooks в корпоративном реестре.

### Официальные ресурсы

- [Официальная документация Argo CD Image Updater](https://argocd-image-updater.readthedocs.io/en/stable/)
- [Исходный код проекта (GitHub argoproj-labs)](https://github.com/argoproj-labs/argocd-image-updater)
- [Argo Helm Charts — argocd-image-updater](https://artifacthub.io/packages/helm/argo/argocd-image-updater)
- [Спецификация OCI Distribution Spec](https://github.com/opencontainers/distribution-spec)
