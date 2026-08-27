# Argo CD: Динамические окружения с Crossplane и GitLab CI

> **Актуальность (2026):** Динамические окружения (Preview Environments) являются стандартом для зрелых DevOps-команд. Использование связки Argo CD + Crossplane позволяет автоматизировать не только деплой кода, но и создание полноценной облачной инфраструктуры (БД, S3, очереди) для каждой ветки, обеспечивая 100% изоляцию и соответствие состоянию в Git. В версии Argo CD v3.x ApplicationSet Controller интегрирован в ядро системы, Progressive Sync позволяет выполнять поэтапную раскатку, а `scmProvider` генератор поддерживает GitLab, GitHub и Bitbucket.

## Предварительные требования

Для работы с динамическими окружениями необходимы:

1. **Argo CD v3.x:** Установлен и настроен (см. [Установка и настройка](./argocd_installation_and_setup.md)).
2. **Crossplane v1.14+:** Установлен в кластере с настроенным провайдером (Yandex Cloud, AWS, GCP, Azure). См. [Crossplane: Обзор](../Crossplane/overview.md).
3. **Git-хостинг:** GitLab, GitHub или Bitbucket с доступом к API для `scmProvider` генератора.
4. **Container Registry:** Docker Hub, GitLab Registry, Harbor или GHCR для публикации образов.
5. **Ingress Controller или Gateway API:** Для маршрутизации трафика в preview-среды.
6. **cert-manager:** Для автоматического выпуска TLS-сертификатов (Let's Encrypt).
7. **ExternalDNS:** Для автоматической регистрации DNS-записей (Cloudflare, Route53, Yandex DNS).
8. **GitLab CI / GitHub Actions:** Настроенный пайплайн для сборки и пуша образов.

## Определения

**Динамическое окружение (Review App / Preview Environment)** — временный, полностью изолированный экземпляр приложения и всей необходимой ему инфраструктуры, создаваемый автоматически для конкретной ветки кода или Merge Request (MR).

**ApplicationSet Controller** — компонент Argo CD, автоматизирующий генерацию объектов `Application`. Позволяет использовать генераторы для массового создания приложений на основе внешних источников. В v3.x интегрирован в ядро системы.

**scmProvider generator** — специализированный генератор в `ApplicationSet`, который отслеживает API Git-хостингов (GitLab, GitHub, Bitbucket) и динамически создает/удаляет приложения при появлении или удалении веток/PR.

**Crossplane** — Kubernetes-native фреймворк для управления внешними облачными ресурсами через стандартный API Kubernetes (IaC). Позволяет описывать базы данных, кластеры и сети как обычные манифесты YAML.

**Crossplane Composition** — набор Managed Resources (MR), описывающий, как создаётся абстрактный ресурс (например, PostgreSQL-кластер) из низкоуровневых облачных сервисов. Определяет связи между ресурсами, параметры подключения и политики жизненного цикла.

**Composite Resource Definition (XRD)** — описание схемы вашего собственного высокоуровневого API (например, абстрактный ресурс "PostgreSQL-Cluster"). Позволяет платформенным командам создавать пользовательские ресурсы, скрывая детали реализации.

**ExternalDNS** — инструмент для автоматического управления записями в DNS-провайдерах (Cloudflare, AWS Route53, Yandex DNS) на основе Ingress-ресурсов или сервисов Kubernetes.

**Review App Namespace** — изолированный namespace в Kubernetes, создаваемый автоматически для каждой ветки или MR. Содержит все ресурсы приложения и инфраструктуры, необходимые для работы preview-окружения.

## Базовые концепции

### Архитектура и поток данных (Workflow)

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                    Жизненный цикл динамического окружения              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. Git Event         2. CI Pipeline       3. ApplicationSet           │
│  ┌──────────┐        ┌──────────┐         ┌──────────┐                │
│  │ Push     │───────▶│ Build +  │────────▶│ Generate │                │
│  │ feat/*   │        │ Push     │         │ App      │                │
│  └──────────┘        │ Image    │         └──────────┘                │
│                      └──────────┘              │                       │
│                                                ▼                       │
│  6. Cleanup           5. DNS + Access      4. Crossplane              │
│  ┌──────────┐        ┌──────────┐         ┌──────────┐                │
│  │ Delete   │◀───────│ External │◀────────│ Create   │                │
│  │ App + MR │        │ DNS +    │         │ Infra    │                │
│  └──────────┘        │ Ingress  │         │ (DB, S3) │                │
│                      └──────────┘         └──────────┘                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

1.  **Событие в Git:** Разработчик создает ветку с префиксом `feat/` или пушит в существующий Merge Request.
2.  **CI-пайплайн (GitLab CI / GitHub Actions):**
    - Сборка Docker-образа с тегом, соответствующим Short Commit SHA.
    - Пуш образа в Container Registry.
    - (Опционально) Обновление метаданных в репозитории конфигураций (GitOps-репозитории).
3.  **Argo CD ApplicationSet:**
    - Постоянно опрашивает GitLab/GitHub API (через `scmProvider`).
    - Обнаруживает новую ветку и генерирует объект `Application`.
    - `Application` ссылается на Helm-чарт, где описаны и само приложение, и его зависимости (Crossplane resources).
4.  **Инстанцирование инфраструктуры (Crossplane):**
    - Kubernetes-контроллер Crossplane видит новые ресурсы (например, `PostgreSQLInstance`).
    - Выполняет вызовы к облачному API для создания реальных ресурсов.
5.  **Сетевой доступ (DNS):**
    - Ingress-контроллер создает точку входа.
    - `ExternalDNS` автоматически регистрирует запись вида `feat-123.preview.example.com`.
6.  **Жизненный цикл и очистка:**
    - При закрытии Merge Request ветка удаляется.
    - Argo CD обнаруживает отсутствие ветки, удаляет `Application` и все связанные ресурсы (включая облачные).

### Сравнение подходов к динамическим окружениям

| Подход | Преимущества | Недостатки | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Helm + ApplicationSet** | Простота, быстрый старт | Ограниченная изоляция инфраструктуры | Простые приложения без БД |
| **Crossplane + ApplicationSet** | Полная изоляция (приложение + инфра), GitOps для всего стека | Сложность настройки, время создания ресурсов (5-10 мин) | **Рекомендуется для зрелых команд** |
| **Terraform + CI** | Широкая экосистема провайдеров | Нет нативной интеграции с Argo CD, state-менеджмент | Если Crossplane не поддерживает провайдера |
| **Virtual Clusters (vCluster)** | Полная изоляция кластера | Высокие ресурсы, сложность управления | Мультикластер-сценарии |

### Нормализация имён и DNS

При создании динамических окружений критически важно корректно нормализовать имена веток для использования в DNS, namespace и именах ресурсов:

| Ветка | Нормализованное имя | Namespace | DNS |
| :--- | :--- | :--- | :--- |
| `feat/user-auth` | `feat-user-auth` | `preview-feat-user-auth` | `feat-user-auth.preview.example.com` |
| `fix/bug-123` | `fix-bug-123` | `preview-fix-bug-123` | `fix-bug-123.preview.example.com` |
| `feature/JIRA-456` | `feature-jira-456` | `preview-feature-jira-456` | `feature-jira-456.preview.example.com` |

**Правила нормализации:**
- Замена `/` на `-`
- Удаление специальных символов (`_`, `.`, `@`)
- Приведение к нижнему регистру
- Ограничение длины DNS-записи (63 символа)

## Практические сценарии

### Сценарий 1: Конфигурация ApplicationSet для GitLab

Этот манифест является "точкой входа" для автоматизации.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: preview-environments
  namespace: argocd
spec:
  generators:
    - scmProvider:
        gitlab:
          group: "my-org/apps" # Группа проектов
          allBranches: true # Отслеживать все ветки (или фильтровать)
          tokenRef:
            secretName: gitlab-access-token
            key: token
        filters:
          - branchMatch: ^feat/.* # Только ветки с префиксом feat/
  template:
    metadata:
      name: "app-{{branchNormalized}}" # Нормализованное имя ветки для DNS
    spec:
      project: preview-apps
      source:
        repoURL: https://gitlab.com/my-org/manifests.git
        targetRevision: "{{branch}}"
        path: charts/standard-app
        helm:
          values: |
            ingress:
              host: "{{branchNormalized}}.preview.example.com"
            infrastructure:
              databaseName: "{{branchNormalized}}"
      destination:
        namespace: "preview-{{branchNormalized}}"
        server: https://kubernetes.default.svc
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

**Создание секрета с токеном GitLab:**
```bash
kubectl -n argocd create secret generic gitlab-access-token \
  --from-literal=token=<your-gitlab-token> \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Сценарий 2: ApplicationSet для GitHub

Для GitHub используется `scmProvider.github` с фильтрацией по префиксам веток.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: preview-environments-github
  namespace: argocd
spec:
  generators:
    - scmProvider:
        github:
          organization: "my-org"
          allBranches: true
          tokenRef:
            secretName: github-access-token
            key: token
        filters:
          - branchMatch: ^feat/.*
          - labelMatch: "preview"
  template:
    metadata:
      name: "app-{{branchNormalized}}"
    spec:
      project: preview-apps
      source:
        repoURL: https://github.com/my-org/manifests.git
        targetRevision: "{{branch}}"
        path: charts/standard-app
        helm:
          values: |
            ingress:
              host: "{{branchNormalized}}.preview.example.com"
      destination:
        namespace: "preview-{{branchNormalized}}"
        server: https://kubernetes.default.svc
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

**Создание секрета с токеном GitHub:**
```bash
kubectl -n argocd create secret generic github-access-token \
  --from-literal=token=<your-github-token> \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Сценарий 3: Matrix Generator для multi-cluster preview environments

Если preview-окружения должны разворачиваться в нескольких кластерах, используйте `matrix` генератор для комбинации `scmProvider` и `list` генераторов.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: preview-multi-cluster
  namespace: argocd
spec:
  generators:
    - matrix:
        generators:
          - scmProvider:
              gitlab:
                group: "my-org/apps"
                allBranches: true
                tokenRef:
                  secretName: gitlab-access-token
                  key: token
              filters:
                - branchMatch: ^feat/.*
          - list:
              elements:
                - cluster: prod-cluster
                  url: https://prod-cluster.example.com
                - cluster: staging-cluster
                  url: https://staging-cluster.example.com
  template:
    metadata:
      name: "app-{{branchNormalized}}-{{cluster}}"
    spec:
      project: preview-apps
      source:
        repoURL: https://gitlab.com/my-org/manifests.git
        targetRevision: "{{branch}}"
        path: charts/standard-app
        helm:
          values: |
            infrastructure:
              databaseName: "{{branchNormalized}}-{{cluster}}"
      destination:
        namespace: "preview-{{branchNormalized}}"
        server: "{{url}}"
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

### Сценарий 4: Описание динамической БД (Crossplane + Yandex Cloud)

Ресурс внутри Helm-чарта приложения, который создает изолированную БД.

```yaml
apiVersion: postgresql.managed-kubernetes.yandex.cloud/v1alpha1
kind: Database
metadata:
  name: {{ .Values.infrastructure.databaseName }}
spec:
  forProvider:
    clusterIdRef:
      name: shared-preview-cluster # Использование общего кластера для экономии
    name: {{ .Values.infrastructure.databaseName }}
    owner: db-admin
    lcCollate: en_US.UTF-8
  providerConfigRef:
    name: yc-config
```

**Crossplane Composition для PostgreSQL (упрощённый пример):**
```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: postgresql-preview
  labels:
    provider: yandex-cloud
spec:
  compositeTypeRef:
    apiVersion: database.example.com/v1alpha1
    kind: PostgreSQLInstance
  resources:
    - name: postgresql-cluster
      base:
        apiVersion: managed-postgresql.yandex-cloud.jet.crossplane.io/v1beta1
        kind: Cluster
        spec:
          forProvider:
            environment:
              - name: PGHOST
            config:
              resources:
                presetId: s2.micro
                diskSizeBytes: 10737418240
      patches:
        - type: FromCompositeFieldPath
          fromFieldPath: spec.parameters.clusterName
          toFieldPath: metadata.labels["crossplane.io/claim-name"]
```

### Сценарий 5: Автоматизация DNS и SSL

Для Review Apps критически важен автоматический доступ по HTTPS.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "app.fullname" . }}
  annotations:
    # ExternalDNS подхватит этот хост и создаст запись в Cloudflare/Yandex DNS
    external-dns.alpha.kubernetes.io/hostname: {{ .Values.ingress.host }}
    # Cert-manager выпустит Wildcard или индивидуальный сертификат
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
    - hosts: [{{ .Values.ingress.host | quote }}]
      secretName: {{ include "app.fullname" . }}-tls
  rules:
    - host: {{ .Values.ingress.host | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ include "app.fullname" . }}
                port: {number: 80}
```

**Wildcard TLS для *.preview.example.com:**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-preview-tls
  namespace: argocd
spec:
  secretName: wildcard-preview-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - "*.preview.example.com"
  renewBefore: 360h
```

### Сценарий 6: Ограничение ресурсов (ResourceQuota и LimitRange)

Защита кластера от неконтролируемого роста количества временных сред.

**ResourceQuota для preview namespace:**
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: preview-quota
  namespace: {{ .Release.Namespace }}
spec:
  hard:
    requests.cpu: "500m"
    requests.memory: "1Gi"
    limits.cpu: "2"
    limits.memory: "4Gi"
    count/pods: "10"
    count/services: "5"
    count/ingresses.networking.k8s.io: "2"
```

**LimitRange для предотвращения перерасхода:**
```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: preview-limits
  namespace: {{ .Release.Namespace }}
spec:
  limits:
  - type: Container
    default:
      cpu: 200m
      memory: 256Mi
    defaultRequest:
      cpu: 100m
      memory: 128Mi
    max:
      cpu: "1"
      memory: 2Gi
    min:
      cpu: 50m
      memory: 64Mi
```

**Глобальная квота на количество preview namespaces:**
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: preview-namespace-quota
  namespace: argocd
spec:
  hard:
    count/namespaces.preview.argoproj.io: "20"
```

### Сценарий 7: NetworkPolicy для изоляции preview-окружений

Ограничьте сетевую связность между preview-окружениями и основным кластером.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: preview-isolation
  namespace: {{ .Release.Namespace }}
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: istio-system
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: argocd-server
    ports:
    - port: 80
      protocol: TCP
    - port: 443
      protocol: TCP
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: {{ .Release.Namespace }}
    ports:
    - port: 5432
      protocol: TCP
    - port: 6379
      protocol: TCP
  - to: []
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 10.0.0.0/8
        - 172.16.0.0/12
        - 192.168.0.0/16
    ports:
    - port: 443
      protocol: TCP
```

### Сценарий 8: Управление секретами в preview-окружениях

Для безопасной передачи секретов в динамические окружения используйте Sealed Secrets или External Secrets Operator.

**Sealed Secrets для preview:**
```yaml
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: {{ include "app.fullname" . }}-secrets
  namespace: {{ .Release.Namespace }}
spec:
  encryptedData:
    DB_PASSWORD: {{ .Values.secrets.dbPassword | b64enc | quote }}
    API_KEY: {{ .Values.secrets.apiKey | b64enc | quote }}
  template:
    metadata:
      name: {{ include "app.fullname" . }}-secrets
      namespace: {{ .Release.Namespace }}
```

**Vault Agent Injector для динамических секретов:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "app.fullname" . }}
spec:
  template:
    metadata:
      annotations:
        vault.hashicorp.com/agent-inject: "true"
        vault.hashicorp.com/role: "preview-{{ .Values.infrastructure.databaseName }}"
        vault.hashicorp.com/agent-inject-secret-db: "secret/data/preview/{{ .Values.infrastructure.databaseName }}"
    spec:
      containers:
      - name: app
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
```

## Управление жизненным циклом и очисткой

### Стратегии оптимизации затрат (FinOps)

1.  **Общие ресурсы:** Использование одной инстанции БД (Shared Instance) с разными логическими базами/схемами для Review Apps вместо создания отдельных кластеров.
2.  **TTL (Time To Live):** Автоматическое удаление окружений по истечении времени.
    - *Реализация:* CronJob в GitLab CI, который удаляет ветки в GitOps-репозитории, если в оригинальном MR не было активности > 3 дней.
3.  **HPA (Horizontal Pod Autoscaler):** Установка минимального количества реплик (например, 1) для всех preview-сред.
4.  **ResourceQuota:** Ограничение ресурсов на уровень namespace (CPU, Memory, количество подов).
5.  **Очистка образов:** Автоматическое удаление неиспользуемых Docker-образов из registry.

**CronJob для TTL-очистки:**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: preview-cleanup
  namespace: argocd
spec:
  schedule: "0 */6 * * *" # Каждые 6 часов
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: cleanup
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              # Удаление preview namespaces старше 72 часов
              kubectl get ns -l argocd.argoproj.io/managed-by=argocd \
                -o jsonpath='{range .items[?(@.metadata.name starts with "preview-")]}{.metadata.name}{" "}{.metadata.creationTimestamp}{"\n"}{end}' | \
              while read ns created; do
                age=$(($(date +%s) - $(date -d "$created" +%s)))
                if [ $age -gt 259200 ]; then
                  echo "Deleting namespace $ns (age: $age seconds)"
                  kubectl delete ns "$ns"
                fi
              done
          restartPolicy: OnFailure
```

### Очистка инфраструктуры

Argo CD гарантирует, что при удалении объекта `Application` будут удалены все дочерние ресурсы в Kubernetes. Благодаря `Finalizers` в Crossplane, облачные ресурсы не будут считаться удаленными в Kubernetes, пока облачный провайдер не подтвердит их физическое уничтожение.

**Lifecycle preview-окружения:**
```text
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  MR Created  │───▶│  Preview     │───▶│  MR Updated  │───▶│  Preview     │
│  Branch:     │    │  Created     │    │  (new push)  │    │  Updated     │
│  feat/*      │    │  (infra +    │    │              │    │  (re-sync)   │
└──────────────┘    │   app)       │    └──────────────┘    └──────────────┘
                    └──────────────┘           │                     │
                           │                   │                     │
                           ▼                   ▼                     ▼
                    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
                    │  MR Merged   │    │  MR Closed   │    │  Branch      │
                    │  or Deleted  │    │  (no merge)  │    │  Deleted     │
                    └──────────────┘    └──────────────┘    └──────────────┘
                           │                   │                     │
                           ▼                   ▼                     ▼
                    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
                    │  Preview     │    │  Preview     │    │  Preview     │
                    │  Promoted    │    │  Destroyed   │    │  Destroyed   │
                    │  to Prod     │    │  (App + MR)  │    │  (App + MR)  │
                    └──────────────┘    └──────────────┘    └──────────────┘
```

**Deletion Policy для Crossplane ресурсов:**
- `DeletionPolicy: Delete` (по умолчанию) — физическое удаление ресурса в облаке.
- `DeletionPolicy: Orphan` — удаление только объекта в Kubernetes. Рекомендуется для критических БД в Prod.

### Rollback preview-окружения

Если preview-окружение сломалось после обновления:

```bash
# 1. Просмотр истории Application
argocd app history app-<branchNormalized>

# 2. Откат на предыдущую версию
argocd app rollback app-<branchNormalized> <revision>

# 3. Или откат через Git (рекомендуется)
git revert <commit-hash>
git push origin feat/<branch>
# Argo CD автоматически обнаружит изменения и откатит окружение
```

## Мониторинг и наблюдаемость

### Метрики для мониторинга preview-окружений

| Метрика | Описание | Источник |
| :--- | :--- | :--- |
| `argocd_app_info{namespace="preview-*"}` | Количество активных preview-приложений | Argo CD |
| `crossplane_resource_ready` | Готовность Crossplane ресурсов | Crossplane |
| `preview_environment_age_seconds` | Возраст preview-окружения | Custom |
| `preview_environment_cost_usd` | Расчётная стоимость окружения | Custom |

**Prometheus Alert для долгоживущих preview:**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: preview-env-alerts
  namespace: argocd
spec:
  groups:
  - name: preview-environments
    rules:
    - alert: PreviewEnvironmentTooOld
      expr: time() - kube_namespace_created_timestamp{namespace=~"preview-.*"} > 259200
      for: 1h
      labels:
        severity: warning
      annotations:
        summary: "Preview environment {{ $labels.namespace }} is older than 72 hours"
        description: "Consider cleaning up unused preview environments"
```

### Просмотр состояния preview-окружений

```bash
# Все активные preview namespaces
kubectl get ns -l argocd.argoproj.io/managed-by=argocd | grep preview

# Состояние ApplicationSet
kubectl get applicationset preview-environments -n argocd -o yaml

# Все preview Applications
kubectl get applications -n argocd -l app.kubernetes.io/part-of=preview-environments

# Crossplane ресурсы в preview namespace
kubectl get managed -n preview-feat-user-auth

# Проверка DNS записей
kubectl get ingress -n preview-feat-user-auth
```

## Технические нюансы и ограничения

| Аспект | Описание / Решение |
| :--- | :--- |
| **Инициализация данных** | Использование `Yandex DataTransfer` или `Job` с `pg_dump` для клонирования эталонной БД при создании новой среды. |
| **Кеширование образов** | Динамические среды генерируют много уникальных образов. Настройте политику очистки (Registry Cleanup Policy) в GitLab/Harbor. |
| **Время старта** | Создание облачной БД может занимать 5-10 минут. Используйте `Health Checks` в Argo CD для визуализации готовности. |
| **Лимиты API** | Слишком частые опросы GitLab API могут привести к Rate Limiting. Настройте `reconcile` интервал в ApplicationSet. |
| **Crossplane Composition** | Используйте XRD и Composition для абстракции облачных ресурсов. Подробнее: [Crossplane: Обзор](../Crossplane/overview.md). |
| **Multi-tenancy** | Один кластер Argo CD может управлять preview-окружениями для нескольких команд через AppProject. |
| **GitOps reconciliation** | При параллельном обновлении ApplicationSet и Application могут возникать conflicts. Используйте `FailOnSharedResource=true`. |

## Типичные ошибки и решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `ApplicationSet generation failed` | Ошибка в шаблоне переменных | Проверьте синтаксис `{{branchNormalized}}` и доступность переменных |
| `Crossplane resource stuck in Creating` | Таймаут облачного API | Увеличьте `--timeout` в ApplicationSet, проверьте логи Crossplane provider |
| `DNS record not created` | ExternalDNS не подхватил Ingress | Проверьте аннотацию `external-dns.alpha.kubernetes.io/hostname` |
| `TLS certificate not issued` | cert-manager не выпустил сертификат | Проверьте ClusterIssuer и DNS-запись (для HTTP-01 валидации) |
| `Namespace quota exceeded` | Достигнут лимит preview namespaces | Увеличьте ResourceQuota или очистите неактивные окружения |
| `Rate limit exceeded (GitLab/GitHub API)` | Слишком частые опросы API | Увеличьте `reconcile` интервал в scmProvider генераторе |

## Ограничения

1. **Время создания:** Создание облачных ресурсов (БД, S3) может занимать 5-10 минут. Preview-окружение готово только после создания всей инфраструктуры.
2. **Стоимость:** Каждое preview-окружение потребляет ресурсы (CPU, Memory, облачные сервисы). Необходим严格的 контроль через ResourceQuota и TTL.
3. **Rate Limits:** GitLab/GitHub API имеют лимиты запросов. При большом количестве веток возможны задержки генерации ApplicationSet.
4. **Crossplane maturity:** Не все облачные сервисы имеют полную поддержку в Crossplane. Проверяйте доступность Managed Resources для вашего провайдера.
5. **DNS propagation:** Регистрация DNS-записей может занимать до 5 минут. Используйте короткие TTL для preview-записей.
6. **Multi-cluster:** При использовании matrix генератора для multi-cluster preview, каждый кластер должен иметь настроенный Crossplane и провайдеры.

## Edge Cases

1. **Одновременные обновления MR и ApplicationSet:** Если разработчик пушит изменения в MR в момент, когда ApplicationSet генерирует Application, возможны conflicts. Используйте `requeueAfter` для контроля частоты reconciling.
2. **Удаление ветки во время создания:** Если ветка удалена до завершения создания Crossplane ресурсов, Argo CD начнёт удаление, но Crossplane может оставить "осиротевшие" ресурсы в облаке. Решение: настройка `DeletionPolicy: Delete` для всех Managed Resources.
3. **Слишком длинные имена веток:** DNS-записи ограничены 63 символами. Используйте `branchNormalized` для сокращения длинных имён.
4. **Shared Preview Cluster:** При использовании общего кластера БД для всех preview-окружений, падение кластера влияет на все среды. Рекомендуется использовать dedicated кластер для критических preview.
5. **Helm values конфликт:** Если в Helm-чарте используются именованные шаблоны, которые конфликтуют с переменными ApplicationSet, используйте `ignoreMissingValueFiles: true`.
6. **Preview для mono-repo:** При работе с монорепозиторием используйте `list` генератор вместо `scmProvider` для более гибкой конфигурации.
7. **Очистка при Argo CD downtime:** Если Argo CD недоступен во время удаления MR, Application не будет удалена автоматически. Настройте CronJob для проверки и очистки "осиротевших" Application.

## См. также

- [Argo CD: Установка и настройка](./argocd_installation_and_setup.md)
- [Crossplane: Интеграция с GitOps](../Crossplane/gitops_integration.md)
- [Crossplane: Обзор](../Crossplane/overview.md)

### См. также

- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Изоляция проектов, квоты, restrictions, кастомные роли.
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.
- [Отслеживание ресурсов](./argocd_resource_tracking.md) — Методы отслеживания ресурсов: Label, Annotation, Annotation+Label.

### Ссылки
- [Argo CD ApplicationSet Generator: SCM Provider](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators-SCM-Provider/)
- [Crossplane Documentation](https://docs.crossplane.io/)
