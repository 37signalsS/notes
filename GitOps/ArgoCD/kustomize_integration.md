# Argo CD: Интеграция с Kustomize (Управление оверлеями и кастомизациями)

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Kustomize v5.x; Kubernetes 1.28–1.32+; bare-metal / on-premise)

> **Контекст развертывания:** Kustomize является встроенным в Kubernetes движком декларативной кастомизации манифестов без шаблонизации (template-free). В составе Argo CD движок Kustomize интегрирован в процесс `argocd-repo-server` как первоклассный инструмент наряду с Helm. Argo CD v3.x поставляется с Kustomize v5.x, поддерживает запуск нескольких версий бинарного файла Kustomize, передачу параметров кастомизации через `Application.spec.source.kustomize`, использование Kustomize Components, рендеринг Helm-чартов внутри Kustomize (`--enable-helm`), а также снятие ограничений безопасности на относительные пути (`--load-restrictor LoadRestrictionsNone`) через глобальную конфигурацию `argocd-cm`.

## Определения

**Kustomize** — декларативный инструмент управления конфигурациями Kubernetes, позволяющий создавать специализированные варианты манифестов (оверлеи) на базе общих базовых шаблонов (bases) без изменения исходных YAML-файлов и без применения шаблонизаторов вроде Jinja или Go Templates.

**Base (Базовая конфигурация)** — директория с исходными декларативными манифестами Kubernetes и файлом `kustomization.yaml`, содержащим список ресурсов (`resources`), общих для всех контуров развертывания.

**Overlay (Оверлей окружения)** — специфичная для целевой среды (dev, stage, prod) директория с файлом `kustomization.yaml`, ссылающаяся на базу (`resources: [../../base]`) и накладывающая патчи (patches), префиксы, суффиксы, метки, аннотации и переопределения образов контейнеров.

**Kustomize Components** — расширение Kustomize, позволяющее выделять модульные и опциональные наборы манифестов и патчей (например, включение мониторинга, активация внешнего TLS, аутентификация), подключаемые к оверлеям через секцию `components: [...]`.

**`spec.source.kustomize`** — декларативная секция ресурса `Application` в Argo CD, позволяющая динамически переопределять параметры Kustomize (подмена тегов образов, добавление префиксов/суффиксов, инъекция меток) без коммита изменений в Git-репозиторий.

**Load Restrictions (Ограничения загрузки)** — механизм безопасности Kustomize, запрещающий по умолчанию загрузку файлов и баз, расположенных за пределами корневой директории выполняемого `kustomization.yaml` (`LoadRestrictionsRoot`). В Argo CD настраивается через флаг `--load-restrictor LoadRestrictionsNone` в `argocd-cm`.

**Kustomize Build Options (`kustomize.buildOptions`)** — глобальный параметр в ConfigMap `argocd-cm`, определяющий системные флаги, передаваемые утилите Kustomize при вызове команды `kustomize build` компонентом `argocd-repo-server`.

**Server-Side Apply (SSA) в Kustomize** — режим синхронизации Argo CD (`ServerSideApply=true`), при котором сгенерированные манифесты Kustomize передаются в Kubernetes API с расчетом слияния на стороне сервера (field ownership), исключая ограничения аннотации `kubectl.kubernetes.io/last-applied-configuration` (256 КБ).

---

## Архитектура и базовые концепции

### Внутренний механизм выполнения Kustomize в Argo CD

Argo CD не запускает `kubectl apply -k` непосредственно в целевом кластере. Сборка манифестов изолирована внутри пода `argocd-repo-server`:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Рендеринг Kustomize в Argo CD                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ 1. Git Repository (GitLab / Gitea)                                          │
│    ├── base/             (базовые Deployment, Service, ConfigMap)           │
│    └── envs/prod/        (kustomization.yaml, patches, replicas)            │
│           │                                                                 │
│           │ git clone / fetch (локальный кэш /tmp)                          │
│           ▼                                                                 │
│ 2. argocd-repo-server                                                       │
│    ├─ Чтение Application.spec.source.kustomize                             │
│    ├─ Чтение флагов kustomize.buildOptions из ConfigMap argocd-cm          │
│    ├─ Выполнение команды:                                                   │
│    │  kustomize build envs/prod/ --load-restrictor LoadRestrictionsNone     │
│    │  [+ kustomize edit set image / nameprefix из spec.source.kustomize]    │
│    └─ Вывод чистого YAML-потока в stdout                                    │
│           │                                                                 │
│           │ gRPC (чистый поток YAML-манифестов)                             │
│           ▼                                                                 │
│ 3. argocd-application-controller                                           │
│    ├─ Вычисление diff между Desired State (YAML) и Live State (K8s API)     │
│    └─ Применение ресурсов в целевой кластер через Server-Side Apply         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Сравнение Kustomize и Helm в экосистеме Argo CD

| Критерий | Kustomize | Helm |
| :--- | :--- | :--- |
| **Парадигма** | Декларативная композиция и оверлеи (без шаблонов) | Параметризованная шаблонизация (Go text/template) |
| **Обработка синтаксиса** | Строгая валидация структуры Kubernetes YAML на каждом шаге | Ошибки шаблонизации могут приводить к невалидному YAML |
| **Управление версиями образов** | Нативная секция `images:` с заменой имени, тега или дайджеста | Переопределение через `values.yaml` (`image.tag`) |
| **Генерация ConfigMap/Secret** | Автоматический хеш-суффикс (`configMapGenerator`), вызывающий rolling-restart | Требуются аннотации вида `checksum/config: {{ ... }}` |
| **Поддержка сторонних пакетов** | Ссылки на удаленные Git-репозитории (`resources: [github.com/...]`) | Скачивание OCI/HTTP Helm-репозиториев |
| **Встроенная поддержка** | Встроена в `kubectl` и `argocd-repo-server` | Требует бинарник `helm` в `argocd-repo-server` |

---

## Практические сценарии

### Сценарий 1: Базовое развертывание Kustomize-приложения через Application

Декларативное описание приложения, использующего оверлей `envs/production` с переопределением образа контейнера и добавлением общего префикса.

**Структура репозитория Git (`https://git.company.internal/infra/billing-service.git`):**
```text
billing-service/
├── base/
│   ├── kustomization.yaml
│   ├── deployment.yaml
│   └── service.yaml
└── envs/
    ├── dev/
    │   ├── kustomization.yaml
    │   └── patch-replicas.yaml
    └── prod/
        ├── kustomization.yaml
        └── patch-resources.yaml
```

**Манифест `envs/prod/kustomization.yaml`:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

patches:
  - path: patch-resources.yaml
    target:
      kind: Deployment
      name: billing-api
```

**Манифест `Application` в Argo CD (`billing-prod.yaml`):**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-prod
  namespace: argocd
  labels:
    environment: production
    app.kubernetes.io/part-of: billing
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: 'https://git.company.internal/infra/billing-service.git'
    targetRevision: main
    path: envs/prod
    kustomize:
      namePrefix: prod-
      nameSuffix: -svc
      images:
        - 'harbor.company.internal/apps/billing-api:v2.14.0'
      commonLabels:
        environment: production
        tier: backend
      commonAnnotations:
        app.company.internal/owner: billing-team
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: billing
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

```bash
# Применение манифеста приложения
kubectl apply -f billing-prod.yaml
# → result: application.argoproj.io/billing-prod created

# Запуск ручной синхронизации и проверка статуса
argocd app sync billing-prod
# → result:
# TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS    HEALTH        HOOK  MESSAGE
# 2026-10-13T19:35:00Z             ConfigMap     billing      prod-billing-cfg-7h9k    Synced   Healthy             configmap/prod-billing-cfg-7h9k created
# 2026-10-13T19:35:01Z      apps  Deployment     billing       prod-billing-api-svc    Synced   Progressing         deployment.apps/prod-billing-api-svc created
# 2026-10-13T19:35:02Z            Service        billing       prod-billing-api-svc    Synced   Healthy             service/prod-billing-api-svc created
```

---

### Сценарий 2: Разрешение внешних путей баз (`LoadRestrictionsNone`)

**Проблема:** В production-репозиториях базовые конфигурации часто выносятся за пределы директории приложения, например:
```text
shared/
└── common-base/
apps/
└── payment/
    └── envs/prod/kustomization.yaml  # resources: [../../../shared/common-base]
```
По умолчанию Kustomize v5 блокирует ссылки, выходящие выше корневого каталога сборки, возвращая ошибку:
`security; file is not in or below current working directory`.

**Решение:** Разрешить выход за пределы корня через глобальный ConfigMap `argocd-cm`.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd-cm
    app.kubernetes.io/part-of: argocd
data:
  # Глобальные опции сборки Kustomize для repo-server
  kustomize.buildOptions: "--load-restrictor LoadRestrictionsNone"
```

```bash
# Применение обновленной конфигурации
kubectl apply -f argocd-cm.yaml
# → result: configmap/argocd-cm configured

# Перезапуск пода argocd-repo-server для гарантированного применения
kubectl rollout restart deployment argocd-repo-server -n argocd
# → result: deployment.apps/argocd-repo-server restarted

kubectl rollout status deployment argocd-repo-server -n argocd --timeout=90s
# → result: deployment "argocd-repo-server" successfully rolled out
```

---

### Сценарий 3: Использование Helm-чартов внутри Kustomize (`--enable-helm`)

Kustomize v5 поддерживает встроенную загрузку и рендеринг Helm-чартов через директиву `helmCharts:` в `kustomization.yaml`. Это позволяет применять патчи Kustomize поверх манифестов публичных или внутренних чартов без создания оберточных скриптов.

**1. Активация флага `--enable-helm` в `argocd-cm`:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Комбинация разрешения внешних путей и поддержки Helm в Kustomize
  kustomize.buildOptions: "--load-restrictor LoadRestrictionsNone --enable-helm"
```

```bash
kubectl apply -f argocd-cm.yaml
# → result: configmap/argocd-cm configured
```

**2. Описание `kustomization.yaml` с внешним Helm-чартом:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

helmCharts:
  - name: redis
    repo: https://charts.bitnami.com/bitnami
    version: 19.6.4
    releaseName: cache-cluster
    namespace: billing
    valuesFile: custom-values.yaml
    includeCRDs: true

# Наложение GitOps-патчей поверх сгенерированного чартом манифеста
patches:
  - target:
      kind: StatefulSet
      name: cache-cluster-node
    patch: |-
      - op: add
        path: /spec/template/spec/priorityClassName
        value: system-cluster-critical
```

---

### Сценарий 4: Подключение нескольких версий Kustomize

В корпоративных средах разные сервисы могут зависеть от разных версий Kustomize (например, легаси v3/v4 со старым синтаксисом `bases` и актуальный v5 со строгим `resources`). Argo CD позволяет подключать произвольные бинарные версии Kustomize в под `argocd-repo-server`.

**1. Монтирование альтернативных бинарников в `argocd-repo-server` (Helm `values.yaml`):**

```yaml
repoServer:
  initContainers:
    - name: install-kustomize-v5-4
      image: registry.k8s.io/kustomize/kustomize:v5.4.3
      command: ["/bin/cp", "/app/kustomize", "/custom-tools/kustomize.v5.4.3"]
      volumeMounts:
        - name: custom-tools
          mountPath: /custom-tools
  extraContainers: []
  volumeMounts:
    - name: custom-tools
      mountPath: /usr/local/bin/kustomize.v5.4.3
      subPath: kustomize.v5.4.3
  volumes:
    - name: custom-tools
      emptyDir: {}
```

**2. Регистрация версии в `argocd-cm`:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  kustomize.version.v5.4.3: "/usr/local/bin/kustomize.v5.4.3"
  kustomize.buildOptions.v5.4.3: "--load-restrictor LoadRestrictionsNone"
```

**3. Использование специфичной версии в `Application`:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: legacy-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://git.company.internal/infra/legacy.git'
    targetRevision: main
    path: overlays/prod
    kustomize:
      version: v5.4.3
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: legacy
```

---

### Сценарий 5: Kustomize Components для опциональных модулей

Kustomize Components позволяют подключать функции (например, sidecar-контейнеры логирования или mTLS-прокси) только в нужных окружениях без дублирования манифестов.

**Структура репозитория:**
```text
service/
├── base/
│   ├── kustomization.yaml
│   └── deployment.yaml
├── components/
│   └── otel-sidecar/
│       ├── kustomization.yaml
│       └── patch-sidecar.yaml
└── envs/
    ├── dev/
    │   └── kustomization.yaml
    └── prod/
        └── kustomization.yaml   # components: [../../components/otel-sidecar]
```

**Манифест `components/otel-sidecar/kustomization.yaml`:**
```yaml
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component

patches:
  - path: patch-sidecar.yaml
    target:
      kind: Deployment
      name: .*
```

**Манифест `envs/prod/kustomization.yaml`:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

components:
  - ../../components/otel-sidecar
```

---

## Операции и команды

| Операция | Команда / Манифест | Назначение |
| :--- | :--- | :--- |
| **Локальная проверка сборки** | `kustomize build envs/prod --load-restrictor LoadRestrictionsNone` | Рендеринг манифестов локально перед отправкой коммита в Git. |
| **Тестирование diff через CLI** | `argocd app diff <app-name> --local ./envs/prod` | Сравнение локального рендера Kustomize с текущим состоянием в кластере. |
| **Переопределение образа в CLI** | `argocd app set <app-name> --kustomize-image nginx=nginx:1.27.0` | Динамическое обновление тега образа в `Application.spec.source.kustomize`. |
| **Проверка сгенерированного YAML** | `argocd app manifests <app-name> --source live` | Просмотр готового потока манифестов, скомпилированного repo-server. |
| **Сброс кэша сборки** | `argocd app get <app-name> --hard-refresh` | Принудительный сброс Redis-кэша и повторный запуск `kustomize build`. |

---

## Диагностика и устранение неполадок

| Типичная ошибка | Причина | Команда диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **`security; file is not in or below current working directory`** | Оверлей ссылается на базовую конфигурацию за пределами текущей директории (`../../base`). | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server \| grep "security"` | Добавить `kustomize.buildOptions: "--load-restrictor LoadRestrictionsNone"` в ConfigMap `argocd-cm` и перезапустить repo-server. |
| **`error: unknown flag: --enable-helm`** | Используется устаревшая версия Kustomize (< v4.1) либо опечатка во флагах `kustomize.buildOptions`. | `kubectl exec -n argocd deploy/argocd-repo-server -- kustomize version` | Обновить версию Kustomize или исправить флаги в `argocd-cm`. |
| **`ConfigMap hash changed on every sync`** | Динамические данные (время сборки, случайный токен) попадают в `configMapGenerator`. | `argocd app diff <app-name>` | Исключить динамические поля из `configMapGenerator` или использовать флаг `generatorOptions.disableNameSuffixHash: true`. |
| **`failed to find image in manifests`** | Имя образа в `spec.source.kustomize.images` не совпадает с полем `image:` в исходном Deployment. | Сравнить манифест `base/deployment.yaml` с `Application.spec.source.kustomize.images` | Указать точное имя образа в `spec.source.kustomize.images[].name`. |
| **`Server-side apply conflict`** | Несколько менеджеров полей (`fieldManager`) одновременно изменяют аннотации или селекторы Kustomize. | `kubectl get <resource> -n <ns> -o yaml \| grep -A 10 managedFields` | Добавить опцию `--force-conflicts` в `syncOptions` приложения либо удалить конфликтующие поля из оверлея. |

---

## Лучшие практики

1. **Разделяйте Base и Overlays:** В `base/` храните только минимальный жизнеспособный набор манифестов. Все отличия сред (реплики, лимиты CPU/Memory, Ingress хосты) выносите строго в `envs/{dev,stage,prod}`.
2. **Используйте хеш-суффиксы генераторов:** Не отключайте `nameSuffixHash` для ConfigMap и Secret. Хеш в имени гарантирует атомарный `RollingUpdate` подов при изменении конфигурации без необходимости внешних утилит (Reloader).
3. **Всегда включайте `ServerSideApply=true`:** Манифесты Kustomize при накоплении патчей превышают лимит аннотации `kubectl.kubernetes.io/last-applied-configuration` (256 КБ). SSA решает эту проблему на уровне K8s API.
4. **Не храните незашифрованные секреты в `secretGenerator`:** При использовании Kustomize генерируйте секреты через SOPS/KSOPS либо монтируйте их внешними операторами (ESO).
5. **Фиксируйте глобальные флаги сборки:** На уровне платформенного чарта Argo CD всегда декларируйте `kustomize.buildOptions: "--load-restrictor LoadRestrictionsNone"`.

---

## Дополнительная информация

- [Argo CD: Интеграция с Helm](./helm_integration.md) — Управление Helm-чартами и values-файлами в Argo CD.
- [Argo CD: Синхронизация и её политики](./synchronization.md) — Опции синхронизации, SSA и автоисправление дрейфа.
- [Argo CD: Игнорирование различий](./synchronization/ignore_differences.md) — Исключение динамических полей Kustomize из цикла сверки.
- [Kustomize в CD-конвейерах](../../Kubernetes/ToolsUtilities/kustomize/kustomize_cd_integration.md) — Общие архитектурные паттерны Kustomize в CI/CD.
- [Управление секретами и шифрование в GitOps](../secrets_encryption.md) — Использование SOPS, age и Sealed Secrets с Kustomize.
- [Официальная документация Argo CD: Kustomize](https://argo-cd.readthedocs.io/en/stable/user-guide/kustomize/)
