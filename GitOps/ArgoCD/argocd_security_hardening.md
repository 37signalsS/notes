# Argo CD: Безопасность — Hardening, GPG, NetworkPolicies, mTLS и Proxy

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Kubernetes 1.28–1.32+; bare-metal / on-premise)

---

## Определения

**Hardening (Усиление безопасности)** — комплекс организационных и конфигурационных мер по снижению поверхности атаки контрольной плоскости Argo CD, минимизации привилегий сервисных учетных записей, включению криптографической верификации манифестов и микросегментации сетевых потоков.

**GPG Commit Verification (Проверка подписи коммитов GPG)** — криптографическая валидация авторства и целостности коммитов или тегов в Git-репозитории перед их рендерингом и передачей в кластер. В Argo CD v3.5+ настраивается через политики `sourceIntegrity` в объекте `AppProject`.

**Commit Seal-Signing (Печать одобрения коммитов)** — механизм в Argo CD v3.5+ (`Argocd-gpg-seal`), позволяющий зафиксировать криптографическую контрольную точку в истории Git без переписывания (`rebase`) старых неподписанных коммитов при переходе на строгий режим проверки (`strict`).

**mTLS (Mutual TLS, двусторонний TLS)** — взаимная криптографическая аутентификация между компонентами системы (клиент и сервер проверяют сертификаты друг друга по доверенному CA). В Argo CD применяется на каналах gRPC между `argocd-server`, `argocd-application-controller` и `argocd-repo-server`.

**NetworkPolicy (Сетевая политика)** — объект спецификации Kubernetes API, предписывающий сетевому плагину (CNI: Calico, Cilium, OVN-Kubernetes) правила фильтрации входящего (Ingress) и исходящего (Egress) L3/L4-трафика для подов по селекторам меток, пространствам имен и диапазонам IP/CIDR.

**Pod Security Standards (PSS, профиль Restricted)** — встроенная модель безопасности Kubernetes, регламентирующая максимальный уровень изоляции контейнеров: принудительный запуск от непривилегированного пользователя (`runAsNonRoot`), неизменяемая корневая файловая система (`readOnlyRootFilesystem`), сброс всех Linux capabilities (`drop: [ALL]`) и профиль Seccomp `RuntimeDefault`.

**Application Sync Impersonation (Имперсонация при синхронизации)** — механизм безопасности Argo CD, при котором контроллер выполняет операции развертывания не от имени глобального `argocd-application-controller` с правами `cluster-admin`, а имперсонирует (выступает от лица) выделенного сервисного аккаунта (`ServiceAccount`) конкретного тенанта или проекта.

**Out-of-Bounds (OOB) Symlink Protection** — защита от атак выхода за пределы каталога репозитория (Path Traversal / Arbitrary File Read), блокирующая чтение символических ссылок, указывающих на файлы за пределами рабочего дерева Git в `argocd-repo-server`.

**Least Privilege (Принцип наименьших привилегий)** — архитектурный принцип, согласно которому сервисные аккаунты, учетные записи пользователей и токены автоматизации получают строго минимально необходимый набор прав для выполнения своих задач (отказ от дефолтного `admin`, ограничение доступа к pod exec, сегментация `ClusterRole`).

---

## Базовые концепции и архитектура безопасности

### Модель угроз и эшелонированная защита (Defense-in-Depth)

В парадигме GitOps контроллер развертывания обладает правами прямого воздействия на целевую инфраструктуру. Компрометация компонентов GitOps открывает доступ к изменению состояния кластеров Kubernetes. Защита Argo CD строится по четырем изолированным контурам:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Git Supply Chain & Integrity (Контур источника данных)                  │
│    ├── GPG / Sigstore верификация коммитов (sourceIntegrity)               │
│    ├── Git Submodule & OOB Symlink Restriction (Path Traversal защита)      │
│    └── Изоляция Git Credentials (read-only SSH/Tokens, TLS CA Bundle)       │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ gRPC / mTLS (Strict TLS)
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ 2. Control Plane & API Hardening (Контур управления)                        │
│    ├── Disable Local Admin (`admin.enabled: "false"`)                        │
│    ├── SSO (OIDC/Dex) + RBAC Least Privilege (Casbin policy.csv)            │
│    ├── Блокировка Web Terminal / Pod Exec (`exec.enabled: "false"`)         │
│    └── Audit Logging (JSON structured logs, API audit, RBAC audit)          │
└───────────────────┬─────────────────────────────────────┬───────────────────┘
                    │ gRPC / mTLS                         │ gRPC / mTLS
┌───────────────────▼──────────────────┐   ┌──────────────▼───────────────────┐
│ 3. Execution & Rendering             │   │ 4. Cluster Operations            │
│    argocd-repo-server                │   │    argocd-application-controller │
│    ├── PSS Restricted (non-root)     │   │    ├── Application Sync Impers.  │
│    ├── tmpfs & readOnlyRootFilesystem│   │    ├── Scoped ClusterRole        │
│    └── Memory DoS Limits (10M caps)  │   │    └── NetworkPolicy Isolation   │
└───────────────────┬──────────────────┘   └──────────────┬───────────────────┘
                    │                                     │
                    └──────────────────┬──────────────────┘
                                       │ L3/L4 фильтрация (Default Deny)
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ Сетевой периметр (NetworkPolicies): изоляция Redis, kube-apiserver, DNS     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Архитектура компонентов и риски компрометации

| Компонент | Роль в системе | Основные векторы угроз | Механизмы защиты |
| :--- | :--- | :--- | :--- |
| **`argocd-server`** | API & Web UI шлюз | Brute-force учетных записей, перехват сессий, SSRF, утечка чувствительных метаданных | OIDC SSO, отключение дефолтного admin, Rate Limiting, CSP/HSTS/Clickjacking защита, RBAC audit |
| **`argocd-repo-server`** | Клонирование Git, запуск шаблонизаторов | Path Traversal через symlink, fork-бомбы / утечки памяти через раздутые манифесты, выполнение недоверенных плагинов | `allow.oob.symlinks: "false"`, PSS Restricted, лимит `max.combined.directory.manifests.size`, изоляция плагинов через сокеты CMP v2 |
| **`argocd-application-controller`** | Синхронизация с Kube API | Эскалация привилегий в кластере, несанкционированное удаление production ресурсов | Least Privilege `ClusterRole`, `application.sync.impersonation`, `requireOverridePrivilegeForRevisionSync` |
| **`argocd-redis` / `redis-ha`** | Кэш состояния и сессий | Чтение кэша манифестов без аутентификации, подмена кэша состояний приложений | Сетевая изоляция (доступ только от контроллеров Argo CD), TLS шифрование, аутентификация по паролю |

---

## Практические сценарии

### Сценарий 1: GPG-подпись коммитов и верификация (Source Integrity)

В Argo CD v3.5+ проверка подписей управляется объектом `AppProject` в блоке `spec.sourceIntegrity.git.policies`. Поддерживаются три режима верификации:
- `none` — верификация отключена;
- `head` — верифицируется только коммит или тег, на который указывает целевая ревизия (`targetRevision`);
- `strict` — проверяется целевой коммит и вся цепочка его предков.

#### Шаг 1: Добавление публичных GPG-ключей в связку ключей Argo CD

Публичные ключи хранятся в ConfigMap `argocd-gpg-keys-cm` в пространстве имен `argocd`.

1. Экспорт публичного ключа инженера или релиз-бота в формат ASCII-armored:
```bash
gpg --armor --export 4AEE18F83AFDEB23 > /tmp/release-signer.asc
# → result: файл /tmp/release-signer.asc создан
```

2. Добавление ключа через CLI:
```bash
argocd gpg add --from /tmp/release-signer.asc
# → result: GnuPG key '4AEE18F83AFDEB23' added
```

3. Декларативное описание в ConfigMap `argocd-gpg-keys-cm`:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-gpg-keys-cm
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd-gpg-keys-cm
    app.kubernetes.io/part-of: argocd
data:
  4AEE18F83AFDEB23: |
    -----BEGIN PGP PUBLIC KEY BLOCK-----
    mQENBFmUaEEBCACzXTDt6ZnyaVtueZASBzgnAmK13q9Urgch+sKYeIhdymjuMQta
    ...
    =Bvzs
    -----END PGP PUBLIC KEY BLOCK-----
```

Применение:
```bash
kubectl apply -f argocd-gpg-keys-cm.yaml
# → result: configmap/argocd-gpg-keys-cm configured
```

#### Шаг 2: Настройка политики верификации в AppProject

Конфигурация проекта с обязательной проверкой GPG-подписей:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production-secured
  namespace: argocd
spec:
  description: "Production project with enforced GPG source integrity"
  sourceRepos:
    - "git@gitlab.corp.local:core-infra/*.git"
  destinations:
    - namespace: "production"
      server: "https://kubernetes.default.svc"
  clusterResourceWhitelist:
    - group: ""
      kind: "Namespace"
  # Современная декларация sourceIntegrity (Argo CD v3.5+)
  sourceIntegrity:
    git:
      policies:
        - repos:
            - url: "git@gitlab.corp.local:core-infra/*"
            - url: "!git@gitlab.corp.local:core-infra/untrusted-sandbox.git"
          gpg:
            mode: "strict"
            keys:
              - "4AEE18F83AFDEB23"
```

#### Шаг 3: Commit Seal-Signing для legacy репозиториев (режим strict)

Если в репозитории уже есть старые неподписанные коммиты, включение режима `strict` заблокирует синхронизацию. Для перехода на `strict` без переписывания Git-истории создается коммит-печать (`seal commit`) с Git-трейлером `Argocd-gpg-seal`:

```bash
git commit --allow-empty -s -S \
  --trailer="Argocd-gpg-seal: Baseline security audit passed; prior history trusted as of 2026-10-12" \
  -m "security: establish trusted baseline seal for Argo CD"
# → result: [main 8f9b2c1] security: establish trusted baseline seal for Argo CD

git push origin main
# → result: To gitlab.corp.local:core-infra/apps.git
```

Контроллер Argo CD проверит цепочку коммитов строго до коммита с печатью, пропуская неподписанные предки.

---

### Сценарий 2: Комплексная сетевая микросегментация (NetworkPolicies)

По умолчанию в Kubernetes сетевой трафик между подами не ограничен. Для изоляции управляющего контура Argo CD развертывается политика запрета по умолчанию (`Default Deny`) и точечные разрешающие правила.

#### 1. Политика по умолчанию: Default Deny для namespace `argocd`

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all-argocd
  namespace: argocd
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```

#### 2. NetworkPolicy для `argocd-repo-server`

`argocd-repo-server` принимает gRPC-запросы только от `argocd-server` и `argocd-application-controller`, а в качестве исходящего трафика разрешаются только обращения к локальному DNS и внешним/корпоративным Git/Helm репозиториям:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-repo-server-network-policy
  namespace: argocd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-repo-server
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Прием входящих запросов gRPC (8081) и метрик (8084) от контроллера и API
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-server
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-application-controller
      ports:
        - port: 8081
          protocol: TCP
        - port: 8084
          protocol: TCP
  egress:
    # 1. Доступ к CoreDNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # 2. Доступ к корпоративным Git и OCI Registry (HTTPS 443, SSH 22)
    - to:
        - ipBlock:
            cidr: 10.50.0.0/16 # Подсеть корпоративных VCS/Artifactory
      ports:
        - port: 443
          protocol: TCP
        - port: 22
          protocol: TCP
```

#### 3. NetworkPolicy для `argocd-application-controller`

Контроллер опрашивает Kubernetes API сервер, gRPC порт `repo-server` (8081), порт Redis (6379) и DNS:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-controller-network-policy
  namespace: argocd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-application-controller
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешен сбор метрик (8082) для Prometheus
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - port: 8082
          protocol: TCP
  egress:
    # 1. Доступ к DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # 2. Доступ к repo-server (gRPC 8081)
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-repo-server
      ports:
        - port: 8081
          protocol: TCP
    # 3. Доступ к Redis (6379)
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-redis
      ports:
        - port: 6379
          protocol: TCP
    # 4. Доступ к Control Plane Kubernetes (Kube API Server 6443)
    - to:
        - ipBlock:
            cidr: 10.0.0.1/32 # IP адрес Kube API
      ports:
        - port: 6443
          protocol: TCP
```

#### 4. NetworkPolicy для `argocd-redis`

Redis хранит кэш манифестов и метаданные сессий. Доступ к нему изолируется исключительно компонентами Argo CD:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-redis-network-policy
  namespace: argocd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-redis
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-server
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-application-controller
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-notifications-controller
      ports:
        - port: 6379
          protocol: TCP
  egress: [] # Redis не инициирует исходящих соединений
```

---

### Сценарий 3: mTLS и взаимная аутентификация компонентов

По умолчанию трафик между `argocd-server`, `argocd-application-controller` и `argocd-repo-server` передается по gRPC с самоподписанными сертификатами без строгой валидации цепочки доверия (`strict.tls: false`). В защищенном периметре настраивается внутренний CA и включается mTLS.

#### Шаг 1: Генерация внутренней инфраструктуры открытых ключей (PKI)

1. Выпуск корневого CA и сертификатов сервисов:
```bash
# Генерация закрытого ключа и корневого сертификата CA
openssl req -x509 -newkey rsa:4096 -days 3650 -nodes \
  -keyout /tmp/argocd-ca.key -out /tmp/argocd-ca.crt \
  -subj "/CN=argocd-internal-ca/O=CoreInfra"

# Выпуск серверного сертификата для repo-server
openssl req -newkey rsa:2048 -nodes \
  -keyout /tmp/repo-server.key -out /tmp/repo-server.csr \
  -subj "/CN=argocd-repo-server.argocd.svc"

openssl x509 -req -in /tmp/repo-server.csr \
  -CA /tmp/argocd-ca.crt -CAkey /tmp/argocd-ca.key -CAcreateserial \
  -out /tmp/repo-server.crt -days 730 \
  -extfile <(echo -e "subjectAltName=DNS:argocd-repo-server,DNS:argocd-repo-server.argocd.svc,DNS:argocd-repo-server.argocd.svc.cluster.local")

# Выпуск клиентского сертификата для controller и server
openssl req -newkey rsa:2048 -nodes \
  -keyout /tmp/client.key -out /tmp/client.csr \
  -subj "/CN=argocd-client/O=ArgoCD"

openssl x509 -req -in /tmp/client.csr \
  -CA /tmp/argocd-ca.crt -CAkey /tmp/argocd-ca.key -CAcreateserial \
  -out /tmp/client.crt -days 730
```

2. Создание Secrets в namespace `argocd`:
```bash
# Серверный секрет для repo-server
kubectl create secret generic argocd-repo-server-tls \
  --from-file=tls.crt=/tmp/repo-server.crt \
  --from-file=tls.key=/tmp/repo-server.key \
  --from-file=ca.crt=/tmp/argocd-ca.crt \
  -n argocd
# → result: secret/argocd-repo-server-tls created

# Клиентский секрет для controller и server
kubectl create secret generic argocd-repo-client-tls \
  --from-file=tls.crt=/tmp/client.crt \
  --from-file=tls.key=/tmp/client.key \
  --from-file=ca.crt=/tmp/argocd-ca.crt \
  -n argocd
# → result: secret/argocd-repo-client-tls created
```

#### Шаг 2: Настройка `argocd-cmd-params-cm` для строгого mTLS

Конфигурация передается централизованно через ConfigMap `argocd-cmd-params-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd-cmd-params-cm
    app.kubernetes.io/part-of: argocd
data:
  # Настройки repo-server: включение TLS и требование клиентского CA
  reposerver.disable.tls: "false"
  reposerver.tls.minversion: "1.3"
  reposerver.client.ca.path: "/app/config/tls/ca.crt"

  # Настройки controller: строгая валидация сервера и подача клиентского сертификата
  controller.repo.server.plaintext: "false"
  controller.repo.server.strict.tls: "true"
  controller.repo.server.ca.cert.path: "/app/config/tls/ca.crt"
  controller.repo.server.client.cert.path: "/app/config/tls/tls.crt"
  controller.repo.server.client.cert.key.path: "/app/config/tls/tls.key"

  # Настройки api-server: строгая валидация сервера и подача клиентского сертификата
  server.repo.server.plaintext: "false"
  server.repo.server.strict.tls: "true"
  server.repo.server.ca.cert.path: "/app/config/tls/ca.crt"
  server.repo.server.client.cert.path: "/app/config/tls/tls.crt"
  server.repo.server.client.cert.key.path: "/app/config/tls/tls.key"
```

Секреты монтируются в контейнеры подов в каталог `/app/config/tls`.

---

### Сценарий 4: Pod Security Standards (PSS Restricted) и SecurityContext

Стандарт `Restricted` полностью исключает работу контейнеров от пользователя root и запрещает модификацию корневой файловой системы.

#### 1. Метки пространства имен для Pod Security Admission (PSA)

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: argocd
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
```

#### 2. Пример hardened спецификации Deployment для `argocd-repo-server`

Поскольку `readOnlyRootFilesystem: true` блокирует запись, служебные каталоги для временных файлов Git (`/tmp`, `/tmp/_argocd-repo`), сокетов плагинов (`/plugins`) и кэша монтируются как `emptyDir` тома на `tmpfs`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: argocd-repo-server
  namespace: argocd
spec:
  template:
    spec:
      # Pod-level security context
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
        runAsGroup: 999
        fsGroup: 999
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: argocd-repo-server
          # Container-level security context
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
            seccompProfile:
              type: RuntimeDefault
          volumeMounts:
            # Writable tmpfs mounts для работы git, helm и kustomize
            - name: tmp
              mountPath: /tmp
            - name: repo-cache
              mountPath: /tmp/_argocd-repo
            - name: plugins-socket
              mountPath: /plugins
            - name: tls-certs
              mountPath: /app/config/tls
              readOnly: true
      volumes:
        - name: tmp
          emptyDir:
            medium: Memory
            sizeLimit: 1Gi
        - name: repo-cache
          emptyDir:
            medium: Memory
            sizeLimit: 4Gi
        - name: plugins-socket
          emptyDir: {}
        - name: tls-certs
          secret:
            secretName: argocd-repo-server-tls
```

---

### Сценарий 5: Харденинг repo-server — защита от DoS и Path Traversal

Клонирование внешних репозиториев несет риск атак через специфически сформированные манифесты, символические ссылки на системные файлы или рекурсивные Git-субмодули.

#### Защитные параметры в `argocd-cmd-params-cm`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  # 1. Защита от утечки памяти при парсинге гигантских каталогов YAML (DoS)
  # Лимит общего размера файлов YAML/JSON в рамках одного Application
  reposerver.max.combined.directory.manifests.size: "10M"

  # 2. Блокировка чтения симлинков за пределы репозитория (Path Traversal)
  reposerver.allow.oob.symlinks: "false"

  # 3. Лимиты на размер потоковых манифестов (Tar-архивов)
  reposerver.streamed.manifest.max.tar.size: "50M"
  reposerver.streamed.manifest.max.extracted.size: "500M"

  # 4. Отключение автоматической инициализации Git Submodules
  # Предотвращает неконтролируемые обращения во внешние непроверенные репозитории
  reposerver.enable.git.submodule: "false"

  # 5. Исключение скрытых директорий (.git, .env) из генерации
  reposerver.include.hidden.directories: "false"
```

Применение:
```bash
kubectl apply -f argocd-cmd-params-cm.yaml
kubectl rollout restart deployment/argocd-repo-server -n argocd
# → result: deployment.apps/argocd-repo-server restarted
```

---

### Сценарий 6: Прокси и доверенные сертификаты в On-Premise периметре

В изолированных корпоративных средах выход в Интернет для загрузки внешних Helm-чартов или Git-репозиториев возможен только через корпоративный HTTP/HTTPS прокси. Локальные сервисы (внутренний GitLab, kube-apiserver) должны опрашиваться напрямую.

#### 1. Настройка переменных прокси в Deployment `argocd-repo-server`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: argocd-repo-server
  namespace: argocd
spec:
  template:
    spec:
      containers:
        - name: argocd-repo-server
          env:
            - name: HTTP_PROXY
              value: "http://squid.corp.local:3128"
            - name: HTTPS_PROXY
              value: "http://squid.corp.local:3128"
            - name: NO_PROXY
              # Исключения: loopback, локальный DNS, внутренний kube-apiserver и подсети
              value: "127.0.0.1,localhost,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.svc,.cluster.local,gitlab.corp.local,argocd-repo-server"
```

#### 2. Добавление доверенных корпоративных Root CA для Git и Helm

Если внутренний GitLab или Harbor используют SSL-сертификаты от корпоративного центра сертификации, они регистрируются в ConfigMap `argocd-tls-certs-cm`:

```bash
kubectl create configmap argocd-tls-certs-cm \
  --from-file=corp-root-ca.crt=/etc/ssl/certs/CorpRootCA.pem \
  -n argocd
# → result: configmap/argocd-tls-certs-cm created
```

Компоненты Argo CD автоматически подмонтируют сертификат в системное хранилище и доверяют внутренним ресурсам без отключения SSL-проверки (`insecure: false`).

---

### Сценарий 7: Харденинг контрольной плоскости и аутентификации

Конфигурация базового `argocd-cm` для отключения уязвимых режимов по умолчанию:

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
  # 1. Отключение встроенного локального аккаунта admin (переход строго на SSO)
  admin.enabled: "false"

  # 2. Запрет анонимного доступа
  users.anonymous.enabled: "false"

  # 3. Полное отключение Web Terminal / Exec во избежание интерактивного вмешательства
  exec.enabled: "false"

  # 4. Требование отдельных прав 'override' для синхронизации произвольных ревизий Git
  # Защищает от деплоя произвольных веток пользователями с правом только 'sync'
  application.sync.requireOverridePrivilegeForRevisionSync: "true"

  # 5. Ограничение длительности сессий (таймаут JWT)
  users.session.duration: "8h"

  # 6. Защита от Clickjacking
  server.x.frame.options: "sameorigin"

  # 7. Включение логирования принудительных проверок RBAC
  server.rbac.log.enforce.enable: "true"
```

#### Настройка защиты от спуфинга IP и Rate Limiting в `argocd-cmd-params-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  # Логирование реального IP клиента из заголовка Ingress
  server.enable.source.ip.logging: "true"
  server.client.ip.header: "X-Forwarded-For"

  # Список доверенных обратных прокси (Ingress Controller CIDR)
  server.trusted.proxies: "10.244.0.0/16,172.20.0.0/16"

  # Отключение интерактивной документации Swagger в production
  server.disable.swagger.ui: "true"

  # Минимальная версия TLS для веб-сервера
  server.tls.minversion: "1.3"
```

---

### Сценарий 8: Принцип наименьших привилегий — Scoped RBAC и Impersonation

#### 1. Ограничение прав `argocd-application-controller` (Отказ от глобального cluster-admin)

Вместо дефолтного `ClusterRole` с правами `*` на все ресурсы, создается ограниченный `ClusterRole`, исключающий доступ к чувствительным кластерным объектам (таким как изменение `ValidatingWebhookConfiguration`, `StorageClass` или доступ к etcd):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: argocd-application-controller-scoped
rules:
  # Чтение метаданных кластера
  - apiGroups: [""]
    resources: ["namespaces", "nodes", "configmaps", "services", "endpoints", "persistentvolumeclaims"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  # Управление стандартными рабочими нагрузками
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
    verbs: ["*"]
  # Управление сетевыми политиками и Ingress
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies", "ingresses"]
    verbs: ["*"]
  # Запрет на модификацию ClusterRole/ClusterRoleBinding в рантайме
  - apiGroups: ["rbac.authorization.k8s.io"]
    resources: ["roles", "rolebindings"]
    verbs: ["*"]
```

#### 2. Включение Application Sync Impersonation

Для мультитенантных кластеров контроллер Argo CD настраивается на принудительную имперсонацию выделенных сервисных аккаунтов.

Включение в `argocd-cm`:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  application.sync.impersonation.enabled: "true"
  application.sync.impersonation.enforced: "true"
```

Декларация в `Application`:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-api
  namespace: argocd
spec:
  project: finance
  source:
    repoURL: "git@gitlab.corp.local:finance/billing.git"
    targetRevision: "HEAD"
    path: "manifests"
  destination:
    server: "https://kubernetes.default.svc"
    namespace: "billing-prod"
  # Синхронизация выполняется от имени выделенного SA
  syncPolicy:
    syncOptions:
      - ImpersonateServiceAccount=billing-deployer
```

---

### Сценарий 9: Аудит безопасности и интеграция с SIEM

#### Формат структурированных логов

Все компоненты настраиваются на вывод в формате JSON с временными метками RFC3339 через `argocd-cmd-params-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  log.format.timestamp: "2006-01-02T15:04:05Z07:00"
  server.log.format: "json"
  server.log.level: "info"
  controller.log.format: "json"
  controller.log.level: "info"
  reposerver.log.format: "json"
  reposerver.log.level: "info"
```

#### Экспорт событий Kubernetes (Kubernetes Events Audit)

При операциях создания, изменения и синхронизации приложений Argo CD генерирует стандартные события Kubernetes (`Events`), содержащие имя пользователя и результат действия:

```bash
kubectl get events -n argocd --field-selector reason=OperationCompleted --sort-by='.metadata.creationTimestamp'
# → result: 2m  Normal  OperationCompleted  application/guestbook  Sync operation to 8f9b2c1 succeeded
```

События перенаправляются в централизованный стек логирования (OpenSearch / Elasticsearch / Syslog) через дескрипторы Fluentbit или Vector.

---

## Операции и команды

Сводная таблица основных административных команд сопровождения безопасности:

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Список GPG-ключей** | `argocd gpg list` | Просмотр всех доверенных публичных ключей |
| **Добавление GPG-ключа** | `argocd gpg add --from /path/to/key.asc` | Импорт открытого ключа в `argocd-gpg-keys-cm` |
| **Удаление GPG-ключа** | `argocd gpg rm <KEY_ID>` | Отзыв доверия к скомпрометированному ключу |
| **Проверка статуса GPG в App** | `argocd app get <APP_NAME> -o json \| jq '.status.conditions'` | Проверка ошибок верификации подписи |
| **Проверка mTLS сертификата** | `openssl s_client -connect argocd-repo-server:8081 -CAfile /tmp/ca.crt` | Проверка рукопожатия TLS repo-server |
| **Аудит RBAC решений** | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server \| grep '"enforce"'` | Мониторинг отказов в доступе Casbin RBAC |
| **Проверка NetworkPolicy** | `kubectl describe networkpolicy -n argocd` | Диагностика активных сетевых фильтров |
| **Проверка PSS статуса** | `kubectl get ns argocd -o jsonpath='{.metadata.labels}'` | Контроль активного профиля изоляции пространства имен |

---

## Диагностика и устранение неполадок

### Типичные ошибки и сбои

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `Commit verification failed: target revision ... is not signed by trusted key` | Коммит не подписан GPG, либо ID ключа отсутствует в `argocd-gpg-keys-cm` или в `policies.gpg.keys` проекта | `argocd app get <NAME>`<br>`argocd gpg list` | Подписать коммит доверенным ключом (`git commit -S`) или добавить открытый ключ в связку |
| `rpc error: code = Unavailable desc = connection error: desc = "transport: authentication handshake failed: remote error: tls: bad certificate"` | Ошибка mTLS: клиентский сертификат controller/server не подписан доверенным CA repo-server или истек | `openssl verify -CAfile ca.crt client.crt`<br>`kubectl logs -n argocd deploy/argocd-repo-server` | Обновить секрет `argocd-repo-client-tls` актуальным сертификатом от единого CA |
| `dial tcp 10.96.x.x:8081: i/o timeout` при синхронизации | Сетевой трафик блокируется NetworkPolicy между `argocd-application-controller` и `argocd-repo-server` | `kubectl get networkpolicy -n argocd`<br>Проверка счетчиков сброшенных пакетов CNI (Cilium/Calico) | Сверить селекторы меток `podSelector` в `argocd-repo-server-network-policy` |
| `container has runAsNonRoot and image will run as root` при старте подов | В манифесте Deployment не заданы `runAsUser` и `runAsGroup`, а образ пытается запуститься с UID 0 в namespace с PSS Restricted | `kubectl get events -n argocd --field-selector reason=FailedCreate` | Задать `securityContext.runAsUser: 999` и `runAsGroup: 999` в `spec.template.spec` |
| `read-only file system` при клонировании репозитория в `repo-server` | Включен `readOnlyRootFilesystem: true`, но служебные каталоги Git не вынесены в `emptyDir` | `kubectl logs -n argocd deploy/argocd-repo-server \| grep "read-only"` | Смонтировать `emptyDir` тома в каталоги `/tmp` и `/tmp/_argocd-repo` |
| `fatal: unable to access 'https://gitlab...': Could not resolve host` | `NO_PROXY` не содержит адрес внутреннего DNS или хоста GitLab при наличии `HTTP_PROXY` | `kubectl exec -it deploy/argocd-repo-server -n argocd -- env \| grep PROXY` | Добавить внутренние домены и кластерные CIDR в переменную `NO_PROXY` |
| `out-of-bounds symlink points outside repository root` | Репозиторий содержит символическую ссылку на внешний файл (защита от Path Traversal) | `kubectl logs -n argocd deploy/argocd-repo-server` | Удалить символическую ссылку из Git или реструктурировать исходные манифесты |
| `User "system:serviceaccount:argocd:..." cannot impersonate resource "serviceaccounts"` | Контроллеру запрещено имперсонировать целевой ServiceAccount | `kubectl auth can-i impersonate serviceaccount/<SA> -n <TARGET_NS> --as=system:serviceaccount:argocd:argocd-application-controller` | Создать `Role` с правилом `verbs: ["impersonate"]` для контроллера в целевом namespace |

---

## Рекомендации и лучшие практики

- **Полное отключение локального admin:** После интеграции с корпоративным SSO (GitLab OIDC / Keycloak) выставьте `admin.enabled: "false"` в `argocd-cm`.
- **Строгий режим GPG для Production:** Используйте `mode: "strict"` в `AppProject.spec.sourceIntegrity`. При внедрении в существующие репозитории ставьте контрольную точку через `Argocd-gpg-seal`.
- **PSS Restricted по умолчанию:** Развертывайте Argo CD только в namespaces с меткой `pod-security.kubernetes.io/enforce: restricted`.
- **Взаимный TLS (mTLS):** Защищайте внутренний gRPC трафик между контроллерами с помощью выделенного PKI и флагов `reposerver.client.ca.path` / `controller.repo.server.strict.tls: "true"`.
- **Изоляция сети (Default Deny):** Блокируйте любой непредусмотренный исходящий трафик из namespace `argocd`, особенно к облачным метаданным (169.254.169.254) и внешним неавторизованным ресурсам.
- **Ограничение прав на ревизии:** Обязательно активируйте `application.sync.requireOverridePrivilegeForRevisionSync: "true"`, чтобы разработчики не могли задеплоить произвольный Git-хэш в обход пайплайна.
- **Ограничение размера манифестов:** Устанавливайте `reposerver.max.combined.directory.manifests.size: "10M"` для предотвращения атак исчерпания памяти (OOM DoS).
- **Запрет Web Terminal:** Если в компании нет регламентированной потребности в интерактивном терминале в подах через Argo CD UI, оставляйте `exec.enabled: "false"`.

---

## Ограничения и граничные условия

### Ограничения

- **GPG поддерживается только для Git:** Верификация `sourceIntegrity` не поддерживается для Helm-репозиториев и OCI-источников (для них требуется валидация на этапе CI или через Cosign/Kyverno).
- **NetworkPolicy зависит от CNI:** Стандартные правила Kubernetes NetworkPolicy не работают при отсутствии CNI с поддержкой политик (например, базовый Flannel без Calico/Cilium).
- **Ротация сертификатов mTLS:** Обновление сертификатов mTLS требует синхронной перезагрузки подов `argocd-repo-server`, `argocd-application-controller` и `argocd-server`.
- **Транзитивные зависимости Helm и Kustomize:** Механизм GPG-верификации проверяет только корневой коммит Git-репозитория. Удаленные зависимости (`remote bases` в Kustomize или внешние субчарты) подлежат отдельной валидации сетевыми политиками Egress.

### Edge Cases

- **Истечение срока действия GPG-ключа:** Если у публичного ключа в связке истекает дата валидности (`expiration date`), Argo CD блокирует генерацию манифестов до обновления ключа.
- **Работа через корпоративный прокси при длинных операциях:** Некоторые прокси-серверы обрывают длительные gRPC или Git HTTP сессии по таймауту; требуется тюнинг `server.repo.server.timeout.seconds` и keepalive параметров на прокси.
- **Impersonation и кросс-пространственные зависимости:** При использовании `application.sync.impersonation` целевой аккаунт должен явно обладать правами в пространстве имен целевого приложения, иначе синхронизация упадет с `Forbidden`.

---

## Дополнительная информация

### См. также

- [Установка и базовая настройка](./argocd_installation_and_setup.md) — Базовая установка Argo CD, HA-архитектура и начальная конфигурация.
- [RBAC и разграничение прав](./argocd_rbac_deep.md) — Глубокое погружение в Casbin, policy.csv, сопоставление ролей и действия.
- [AppProject и изоляция ресурсов](./argocd_appproject_deep.md) — Ограничение целевых кластеров, пространств имен и политик sourceRepos.
- [Мультитенантность и изоляция](./argocd_multi_tenancy.md) — Архитектурные паттерны soft и hard мультитенантности, project-per-team.
- [SSO и интеграция с GitLab](./argocd_sso_gitlab.md) — Интеграция корпоративного OIDC провайдера, Dex и маппинг групп.
- [Кастомные плагины (CMP v2)](./argocd_custom_tooling.md) — Безопасная настройка Config Management Plugins через Unix domain сокеты.
- [Интеграция с Vault](./argocd_vault_integration.md) — Работа с секретами через Argo CD Vault Plugin и External Secrets Operator.
- [Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, финализаторы и предотвращение сиротских объектов.
- [Аварийное восстановление и бэкапы](./argocd_disaster_recovery.md) — Экспорт конфигураций, резервное копирование и DR-сценарии.
- [Сетевые политики GitOps](../../Kubernetes/Networking/Network/NetworkPolicy/gitops_ci_cd.md) — CI/CD пайплайны валидации сетевых политик.

### Ссылки

- [Argo CD: Operator Manual Security](https://argo-cd.readthedocs.io/en/stable/operator-manual/security/)
- [Argo CD: Source Integrity & GPG Verification](https://argo-cd.readthedocs.io/en/stable/user-guide/source-integrity-git-gpg/)
- [Kubernetes: Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Kubernetes: Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
