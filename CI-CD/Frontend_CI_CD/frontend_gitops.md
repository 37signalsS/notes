**Актуально для:** Argo CD v3.x, Kubernetes 1.29–1.36

# GitOps для фронтенда

## Определения

- **GitOps** — declarative подход к CD, где Git является единственным источником истины для состояния системы.
- **Drift Detection** — обнаружение расхождений между состоянием в Git и реальным состоянием кластера.
- **Progressive Delivery** — постепенная поставка: canary, blue-green, feature flags.
- **Argo CD** — GitOps-контроллер для Kubernetes с веб-UI и RBAC.
- **ApplicationSet** — Argo CD CRD для управления множеством приложений из одного манифеста.
- **Image Updater** — Argo CD компонент для автоматического обновления тегов образов.
- **ImageUpdater CR** — CRD `imageupdaters.argocd-image-updater.argoproj.io` v1.x для конфигурации политик обновления и Git write-back.
- **Preview-окружение** — временный namespace/environment, создаваемый автоматически для каждого MR/PR.
- **Sync wave** — механизм упорядочивания применения ресурсов в Argo CD.
- **Ignore difference** — правило Argo CD для игнорирования управляемых полей (например, replicas, controlled by HPA).
- **Fleet repository** — Git-репозиторий, содержащий все манифесты GitOps-контроллера.

---

## Предварительные требования

- **Kubernetes:** кластер v1.29+ с включёнными стабильными API-группами (`apps/v1`, `networking.k8s.io/v1`, `autoscaling/v2`).
- **Argo CD:** v3.x установлен в namespace `argocd`; CLI `argocd` v3.x настроен (`argocd login`).
- **Argo CD Image Updater:** v1.x установлен в namespace `argocd` для автоматического обновления образов.
- **Git-репозиторий:** HTTPS/SSH доступ для контроллера; deploy key или robot account с правами `read` на манифесты и `write` для Image Updater (Git write-back).
- **Registry:** внутренний OCI-реестр с поддержкой digest и Referrers API; контроллеры имеют права на чтение образов.
- **Ingress/Service:** базовый доступ к приложениям через Ingress или Gateway API для preview-окружений.
- **CI/CD:** пайплайн собирает образ, генерирует digest, обновляет тег/манифест в Git или триггерит Image Updater.
- **RBAC:** сервис-аккаунты Argo CD имеют минимальные права; namespace-изоляция для preview/production.
- **Сеть:** egress от контроллеров к registry, Git-хосту, Vault; ingress к UI Argo CD.

---

## Основные концепции

### Почему GitOps для фронтенда

Фронтенд имеет специфику, которая хорошо ложится на GitOps:
- **Статика и манифесты:** `dist/`, `Ingress`, `ConfigMap` — всё declarative.
- **Preview-окружения:** каждый MR → отдельное приложение в Argo CD; команда QA/дизайна видит изменения без ручного деплоя.
- **Откат:** `git revert` + синхронизация — мгновенный откат без доступа к кластеру.
- **Аудит:** история Git = история деплоев, каждый коммит привязан к MR/approval.
- **Immutable артефакты:** фронтенд-сборка — это неизменяемый образ; версия в кластере = digest, а не тег.

### Архитектура GitOps-пайплайна для фронтенда

```
CI (сборка образа, digest)
  │
  ├─► Образ pushed в registry
  │
  ├─► Манифест обновлён в Git (tag или digest)
  │     или
  ├─► Image Updater обновил тег в Git
  │
  ▼
Git-репозиторий (fleet repo)
  │
  ├─► Argo CD обнаруживает изменение
  │     │
  │     ├─► Рендеринг манифестов (Kustomize/Helm/Jsonnet)
  │     │
  │     ├─► Валидация: Cosign подпись, SBOM, Admission controller (OPA/Kyverno)
  │     │
  │     ├─► Применение к кластеру
  │     │
  │     └─► Health check → Synced/Healthy или OutOfSync
  │
  ▼
Kubernetes (Deployment, Service, Ingress/Gateway, HPA, PDB)
```

### Паттерны развёртывания

| Паттерн | Описание | Применимость к фронтенду |
| :--- | :--- | :--- |
| **Branch-based** | Каждая ветка → своя среда | Preview-окружения для MR |
| **Overlay-based** | Один манифест, оверлеи по окружениям | dev/staging/prod различаются ConfigMap, replicas, resources |
| **Image-based** | Только тег образа меняется в Git | Immutable deploy, Argo CD Image Updater |
| **Pull Request-based** | Argo CD ApplicationSet по списку MR | Автоматические review apps |

### Drift Detection и auto-heal

Argo CD сравнивает состояние кластера с Git:

- **Argo CD:** `argocd app get frontend` → `OutOfSync` означает дрейф.
- **Auto-heal:** автоматическое исправление дрейфа (опасно в production без approval).
- **Manual:** дрейф зафиксирован, требуется ручное исправление через Git.

### Изображения в GitOps

В GitOps образ — это артефакт между CI и CD:
- **Digest pinning:** production использует `@sha256:...`; теги допустимы только для dev/staging.
- **Referrers API:** attestation (SBOM, Cosign) прикрепляются к образу; контроллер проверяет подпись перед деплоем.
- **Image Policy:** Argo CD Image Updater фильтрует допустимые теги через `updateStrategy` и `allowTags`/`ignoreTags` в `ImageUpdater` CR (semver, regex).

Детали — в **[GitOps: образы контейнеров и их жизненный цикл](../../GitOps/Concepts/containerization_and_image_storage.md)**.

### Preview-окружения в GitOps

Для фронтенда preview-окружения — основной use case GitOps:
- **ApplicationSet (Argo CD):** генератор `pullRequest` создаёт приложение для каждого MR с уникальным namespace `preview-<number>`.
- **Kustomize overlay:** каждый MR получает свой overlay с `namePrefix`/`namespace`.
- **TTL:** автоматическое удаление preview-приложения после merge/close MR через `argocd-delete-preview` или GitLab CI job.
- **Стоимость:** preview-окружения потребляют ресурсы; ограничьте количество одновременно живущих preview через ResourceQuota.

---

## Практические сценарии

### Сценарий 1: Argo CD ApplicationSet для preview-окружений

```yaml
# applicationset.yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: frontend-preview
  namespace: argocd
spec:
  generators:
    - pullRequest:
        github:
          owner: org
          repo: frontend
          tokenRef:
            secretName: github-token
            key: token
  template:
    metadata:
      name: "frontend-preview-{{number}}"
      annotations:
        argocd.argoproj.io/sync-options: Prune=true
    spec:
      project: default
      source:
        repoURL: https://github.com/org/frontend.git
        targetRevision: "{{head_sha}}"
        path: k8s/preview
      destination:
        server: https://kubernetes.default.svc
        namespace: preview
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

Для production используйте отдельное приложение с manual approval или Image Updater:

```yaml
# argocd-image-updater
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: frontend-production
  namespace: argocd
spec:
  source:
    repoURL: https://github.com/org/frontend.git
    targetRevision: main
    path: k8s/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: false
    syncOptions:
      - ApplyOutOfSyncOnly=true
```

**Валидация:**
- `argocd app list` — для каждого MR есть `frontend-preview-<number>`.
- `argocd app get frontend-preview-42` → `Sync Status: Synced`, `Health Status: Healthy`.
- После merge MR preview-приложение удаляется (Prune).
- Для production: `argocd app get frontend-production` → `Synced`, `Healthy`.

**Troubleshooting:**
- *Preview app не создаётся:* проверьте GitHub token, права на repo, `argocd-repo-server` логи.
- *Preview app зависает в `Progressing`:* проверьте readiness probe, namespace `preview` существует.
- *OutOfSync после rollout:* HPA управляет `replicas` → добавьте `ignoreDifferences` в ArgoCD.
- *Self-heal конфликтует с manual deploy:* отключите `selfHeal` для production.

### Сценарий 2: Argo CD Image Updater для автоматического обновления тегов

Argo CD Image Updater автоматически сканирует реестр, выбирает целевой тег по semver-политике и коммитит обновление в Git через `ImageUpdater` CR — единый механизм для отслеживания образов, выбора тега и записи в Git.

**1. Установка Argo CD Image Updater:**

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd-image-updater argo/argocd-image-updater \
  --namespace argocd \
  --version 1.3.x
# → NAME: argocd-image-updater
# → STATUS: deployed
```

**2. Конфигурация Git credentials для write-back:**

```bash
# Создание SSH deploy key с правами на push
kubectl create secret generic git-ssh-deploykey \
  --from-file=identity=/path/to/id_ed25519 \
  --from-file=known_hosts=/path/to/known_hosts \
  -n argocd
```

**3. ImageUpdater CR для frontend production:**

```yaml
# argocd-image-updater-frontend.yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: frontend-prod-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:org/frontend-gitops.git"
      branch: "main"
      writeBackTarget: "helmvalues:./overlays/production/values.yaml"
      user: "Argo CD Image Updater"
      email: "argocd-image-updater@example.com"
      commitUser: "git-ssh-deploykey"
  applicationRefs:
  - namePattern: "frontend-production"
    images:
    - alias: "frontend"
      imageName: "registry.example.com/frontend/app:^1.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        allowTags: "^v?1\\.[0-9]+\\.[0-9]+$"
        ignoreTags: ["*alpha*", "*beta*", "*rc*", "*dev*"]
        pullSecret: "secret://argocd/registry-robot-secret"
        platforms:
          - "linux/amd64"
```

**Эквивалентность компонентов:**

| Компонент | Конфигурация |
| :--- | :--- |
| `ImageRepository` | `ImageUpdater.spec.applicationRefs[].images[]` с `pullSecret` и `platforms` |
| `ImagePolicy` | `commonUpdateSettings.updateStrategy` + `allowTags`/`ignoreTags` |
| `ImageUpdateAutomation` | `writeBackConfig` (method: `git`, `gitConfig`) |
| `GitRepository` | `Application.spec.source.repoURL` + `writeBackConfig.gitConfig.repository` |

> **Примечание:** таблица показывает, как Flux-компоненты (`ImageRepository`, `ImagePolicy`, `ImageUpdateAutomation`, `GitRepository`) соответствуют параметрам `ImageUpdater` CR в Argo CD — удобно при миграции с Flux.

**Валидация:**
- `kubectl get imageupdater frontend-prod-updater -n argocd` — `ImageUpdater` CR применён.
- `argocd app get frontend-production` — статус `Synced`, `Healthy`.
- После нового push образа в registry, через 1–2 минуты Image Updater обновляет тег в `values.yaml` и Argo CD автоматически синхронизирует.
- `kubectl describe imageupdater frontend-prod-updater -n argocd` — статус последнего сканирования и commit hash.

**Troubleshooting:**
- *Image Updater не обновляет тег:* проверьте `applicationRefs.namePattern` (должен совпадать с именем Argo CD Application), `imageName`, `pullSecret`, `argocd-image-updater` логи.
- *Неправильный тег:* проверьте `allowTags`/`ignoreTags` regex и `updateStrategy`; используйте `newest-build` для простого latest.
- *Git write-back fails:* проверьте SSH deploy key, права на запись в репо, `gitConfig.repository` URL.
- *Commit race condition:* два updaters обновляют один файл → используйте отдельные `writeBackTarget` или отключите один из updaters.

### Сценарий 3: Drift Detection и manual reconciliation

```bash
# Argo CD: проверка дрейфа
argocd app get frontend-production
# → Sync Status: OutOfSync

# Просмотр diff
argocd app diff frontend-production

# Ручная синхронизация
argocd app sync frontend-production

# Принудительная синхронизация (игнорируя дрейф)
argocd app sync frontend-production --force
```

**Валидация:**
- После `argocd app sync` статус → `Synced`, `Healthy`.

**Troubleshooting:**
- *Дрейф ConfigMap/Secret:* изменения в кластере не должны применяться императивно — всё через Git.
- *Argo CD force sync не помогает:* проверьте `ignoreDifferences` и `resource.exclusions`.

### Сценарий 4: Progressive Delivery через Argo Rollouts или Flagger

Для фронтенда canary полезен для SSR/SSG приложений, где можно сравнить технические метрики (error rate, latency) перед полным переключением.

**Argo Rollouts (с Argo CD):**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: frontend-ssr
  namespace: production
spec:
  replicas: 5
  strategy:
    canary:
      steps:
        - setWeight: 10
        - pause: {duration: 5m}
        - setWeight: 25
        - pause: {duration: 5m}
        - setWeight: 50
        - pause: {duration: 10m}
        - setWeight: 100
      analysis:
        templates:
          - templateName: success-rate
        args:
          - name: service-name
            value: frontend-ssr
  selector:
    matchLabels:
      app.kubernetes.io/name: frontend
  template:
    metadata:
      labels:
        app.kubernetes.io/name: frontend
    spec:
      containers:
        - name: ssr
          image: registry.example.com/frontend:${VERSION}
```

**Flagger (поверх обычного Deployment):**

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: frontend-ssr
  namespace: production
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: frontend-ssr
  service:
    port: 80
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    metrics:
      - name: request-success-rate
        thresholdRange:
          min: 99
        interval: 1m
```

**Валидация:**
- `kubectl-argo-rollouts get rollout frontend-ssr -n production` — шаги canary видны.
- `kubectl get pods -n production -l app.kubernetes.io/name=frontend` — старые и новые поды одновременно.
- После успешного canary все поды обновлены.

**Troubleshooting:**
- *Canary зависает на шаге:* проверьте analysis template, Prometheus доступность, пороговое значение.
- *HPA "дребезг" во время canary:* фиксируйте replicas во время rollout или используйте `behavior` stabilization.
- *Flagger не создаёт canary service:* проверьте CRD `flagger.app/v1beta1`, namespace label `app.kubernetes.io/name`.

### Сценарий 5: GitLab CI + GitOps для preview-окружений

Для команд, использующих GitLab CI без полноценного GitOps-контроллера, preview можно организовать через `kubectl apply` в preview namespace с ApplicationSet-подобной логикой:

```yaml
# .gitlab-ci.yml
stages:
  - build
  - deploy-preview

deploy_preview:
  stage: deploy-preview
  image: bitnami/kubectl:latest
  script:
    - kubectl create namespace preview-${CI_COMMIT_REF_SLUG} --dry-run=client -o yaml | kubectl apply -f -
    - kubectl apply -f k8s/preview/ -n preview-${CI_COMMIT_REF_SLUG}
    - kubectl expose deployment frontend-ssr -n preview-${CI_COMMIT_REF_SLUG} --port=80 --target-port=3000
  environment:
    name: preview/$CI_COMMIT_REF_SLUG
    url: https://${CI_COMMIT_REF_SLUG}.preview.example.com
  only:
    - merge_requests
```

**Валидация:**
- `kubectl get namespaces` — namespace `preview-<branch>` создан.
- `kubectl get pods -n preview-<branch>` — pods `Running`.
- `curl https://<branch>.preview.example.com` — `200`.

**Troubleshooting:**
- *Namespace не удаляется:* добавьте cleanup job в `.gitlab-ci.yml` или используйте Argo CD ApplicationSet с `Prune=true`.
- *Ingress конфликтует:* каждый preview должен иметь уникальный `host` (branch name).
- *Рекурсивный деплой:* `kubectl apply` без `--prune` оставляет старые ресурсы.

---

## Операционные команды

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `argocd app get frontend-production` | Статус приложения | # → Sync Status: Synced, Health Status: Healthy |
| `argocd app diff frontend-production` | Diff дрейфа | # → список изменённых полей |
| `argocd app sync frontend-production` | Ручная синхронизация | # → успешная синхронизация |
| `argocd app sync frontend-production --force` | Force sync | # → принудительное применение |
| `argocd app history frontend-production` | История деплоев | # → список revision с изменениями |
| `argocd app rollback frontend-production <revision>` | Откат к ревизии | # → rolled back |
| `argocd app set frontend-production --ignore-diff 'spec.replicas'` | Игнорирование дрейфа | # → OutOfSync исчезнет для replicas |
| `argocd app delete frontend-preview-42` | Удаление preview | # → app deleted |
| `kubectl get imageupdaters -n argocd` | ImageUpdater CR | # → список конфигураций |
| `kubectl describe imageupdater frontend-prod-updater -n argocd` | Статус Image Updater | # → статус последнего сканирования |
| `kubectl-argo-rollouts get rollout frontend-ssr` | Статус Rollout | # → шаги canary, paused/running |
| `kubectl-argo-rollouts abort rollout frontend-ssr` | Отмена rollout | # → aborted |
| `kubectl-argo-rollouts promote frontend-ssr` | Продвижение шага | # → следующий шаг canary |
| `kubectl get applications -n argocd` | Список приложений | # → Synced/OutOfSync |
| `kubectl get appprojects -n argocd` | Проекты Argo CD | # → список проектов |
| `argocd admin settings rbac can role:dev get applications dev/*` | Проверка RBAC | # → yes/no |

---

## Валидация

- **Argo CD UI:** приложение `frontend-production` имеет статус `Synced`, здоровье `Healthy`.
- **Drift detection:** после ручного изменения ConfigMap в кластере Argo CD показывает `OutOfSync`.
- **Preview apps:** для каждого MR создаётся приложение `frontend-preview-<number>`.
- **Image Updater:** тег образа в Git обновляется автоматически при новом image push (`ImageUpdater` CR в неймспейсе `argocd`).
- **Auto-heal:** дрейф исправляется автоматически в течение 3 минут (sync interval).
- **Rollout status:** `kubectl-argo-rollouts get rollout` показывает текущий шаг canary.
- **RBAC:** `argocd admin settings rbac can` возвращает `yes` для разрешённых ролей.
- **Certificate/Ingress:** preview-окружения доступны по уникальному host.

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Argo CD показывает OutOfSync | Дрейф ConfigMap/Secret | Проверить diff, внести изменения в Git |
| Preview app не создаётся | ApplicationSet не видит MR | Проверить GitHub token, permissions |
| Image Updater не обновляет тег | `applicationRefs` не совпадает с Application, либо нет прав на запись в Git | Проверить `namePattern`, Git credentials, `argocd-image-updater` логи |
| Image Updater не сканирует образ | `pullSecret` или registry недоступен | Проверить `pullSecret`, `imageName`, registry connectivity |
| Дрейф накапливается | Ручные изменения в кластере | Включить alerts на drift; `selfHeal: true` в prod |
| Kustomize конфликтует | Слишком много оверлеев | Использовать Helm или Jsonnet для сложных случаев |
| Argo CD UI не доступен | Ingress/сертификат | Проверить `argocd-server` service, cert-manager |
| Медленная синхронизация | Большое количество файлов | Использовать `resource.exclusions` или Helm |
| HPA конфликтует с GitOps | Git отслеживает `replicas` | Добавить `ignoreDifferences` в ArgoCD |
| Canary зависает | Analysis template падает | Проверить Prometheus, пороговые значения |
| Preview namespace не очищается | Нет TTL/Prune | Настроить `argocd-delete-preview` или cleanup job |
| RBAC запрещает sync | AppProject ограничения | Проверить destination, source Whitelist |
| Stale preview-окружения | MR закрыт без cleanup | Добавить webhook на merge/close для удаления |

---

## Инцидент: compromised Git-репозиторий / unauthorized deployment

1. **Немедленный отзыв:** `argocd app sync frontend-production --dry-run` → применить known-good digest или `git revert` + синхронизация.
2. **Изоляция:** `argocd app pause frontend-production` — приостановка автоматических обновлений.
3. **Аудит:** `argocd app history frontend-production`; проверка Git-истории (`git log`); audit logs Argo CD (`kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server`).
4. **Ротация:** смена deploy key/robot account; обновление `argocd-cm` и secrets.
5. **Очистка:** удалить несанкционированные приложения; `argocd delete app <compromised-app>`.
6. **Постмортем:** blameless postmortem; обновление RBAC, AppProject, NetworkPolicy для Argo CD.

---

## Особые случаи

- **Graceful shutdown preview-окружений:** Argo CD при `Prune=true` удаляет namespace; убедитесь, что приложение корректно обрабатывает `SIGTERM` и `terminationGracePeriodSeconds`.
- **ApplicationSet RBAC:** права на `applicationsets` должны быть только у администраторов; шаблон `project` не должен быть шаблонизирован из данных MR для недоверенных источников.
- **Argo CD для preview:** Argo CD ApplicationSet с `pullRequest` генератором — самый простой вариант для preview. Поддерживает TTL/Prune для автоочистки.
- **HPA и GitOps:** HPA управляет `replicas`; Git должен хранить статический `replicas` (например, 2), а не актуальный. Добавьте `ignoreDifferences` в Argo CD для `spec.replicas`.
- **Cache invalidation для статики:** при обновлении фронтенда CDN кэширует старые assets; используйте fingerprinting (contenthash) в именах файлов илиPurge CDN cache через webhook после успешного sync.
- **Multi-cluster GitOps:** ApplicationSet с `Cluster Generator` или `Matrix Generator` для деплоя одного фронтенда на несколько кластеров (hub-spoke).
- **Drift Detection в production:** включите алерты на `OutOfSync` в production; дрейф — симптом проблемы, а не решение.
- **Fleet (fleet) vs per-app репозиторий:** fleet repo хранит все приложения; per-app repo — для команд с полной автономией. Оба варианта поддерживаются Argo CD.
- **Sync waves и hooks:** Argo CD поддерживает `wave` и `hook` для фронтенда, который зависит от backend (поднять backend API, затем frontend Ingress).
- **SSO и RBAC:** Argo CD поддерживает Dex/GitLab/GitHub OIDC; RBAC в `argocd-rbac-cm` ограничивает доступ к namespace/project. Для фронтенд-команды — read-only доступ к production, write к dev/preview.

---

## Лучшие практики

1. Используйте Git как единственный источник истины; запретите `kubectl edit/apply` в production.
2. Включите drift detection alerts; дрейф — симптом проблемы, а не решение.
3. Для preview-окружений используйте Argo CD ApplicationSet с TTL/Prune (автоочистка preview после merge/close MR).
4. Применяйте `autoHeal: false` в production; дрейф должен быть явно подтверждён через PR.
5. Используйте digest pinning для production образов; теги — только для dev/staging.
6. Настройте RBAC Argo CD: каждый проект имеет доступ только к своим namespace.
7. Для Progressive Delivery используйте Argo Rollouts или Flagger вместе с GitOps; для фронтенда это особенно полезно при SSR/SSG.
8. Храните конфигурацию GitOps-контроллера в отдельном репозитории (fleet repo).
9. Используйте ignore differences для managed полей (`replicas`, `status`, HPA-managed values).
10. Настройте admission controller (OPA/Gatekeeper/Kyverno) для проверки манифестов перед применением.
11. Включите sync waves и hooks для зависимых компонентов (backend → frontend).
12. Для preview-окружений установите ResourceQuota и LimitRange, чтобы не превысить лимиты кластера.
13. Настройте алерты на `OutOfSync` и `SyncFailed` в production.
14. Для SSO используйте GitLab/GitHub OIDC через Dex или нативный OIDC; не храните локальные учётки.

---

## Дополнительная информация

### См. также

- **[GitOps: обзор](../../GitOps/GitOps_overview.md)** — принципы, паттерны, сравнение с классическим CD.
- **[Прогрессивная доставка в GitOps](../../GitOps/Concepts/progressive_delivery_gitops.md)** — Argo Rollouts, Flagger, canary.
- **[Argo CD Image Updater](../../GitOps/ArgoCD/argocd_image_updater.md)** — конфигурация автоматического обновления образов через `ImageUpdater` CR.
