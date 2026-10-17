# Внешние системы управления секретами

**Актуально для:** Kubernetes 1.30–1.34+, External Secrets Operator v0.14+ / Helm-чарт 2.13.x (API external-secrets.io/v1), Secrets Store CSI Driver v1.6.x, HashiCorp Vault 1.18–1.21 / OpenBao 2.x (on-premise / bare-metal)

## Определения

- **Внешние менеджеры секретов (External Secret Managers)** — централизованные платформы управления жизненным циклом конфиденциальных данных (HashiCorp Vault, OpenBao, Infisical), развернутые в локальной или гибридной инфраструктуре для безопасного хранения, генерации, аудита и динамической ротации ключей, токенов и паролей.
- **External Secrets Operator (ESO)** — Kubernetes-оператор, реализующий модель асинхронной синхронизации (Pull-модель): считывает конфиденциальные данные из внешнего API хранилища и материализует/обновляет нативные объекты `Secret` внутри кластера. Приложения работают со стандартными механизмами Kubernetes (переменные окружения `envFrom`, тома `volumeMounts`) и не требуют внедрения внешних SDK.
- **Secrets Store CSI Driver** — драйвер интерфейса CSI (Container Storage Interface), реализующий доставку секретов «по требованию» (On-demand): секреты монтируются непосредственно в файловую систему Pod в момент его монтирования как виртуальный том `tmpfs`, не сохраняясь в базе данных `etcd` в виде нативных объектов `Secret`.
- **Vault Secrets Operator (VSO)** — нативный оператор для Kubernetes от HashiCorp/OpenBao, управляющий синхронизацией статических (`VaultStaticSecret`), динамических (`VaultDynamicSecret`) и PKI-сертификатов (`VaultPKISecret`) из Vault с поддержкой автоматического обновления и инициирования rollout-restart рабочих нагрузок.
- **OpenBao** — открытая реализация платформы управления секретами под эгидой Linux Foundation (форк Vault, созданный после смены лицензии на BSL). Сохраняет полную совместимость с API HashiCorp Vault v1/v2 и является основным выбором для полностью открытых локальных сред без коммерческих подписок.
- **SecretStore / ClusterSecretStore** — Custom Resource Definitions (CRD) оператора ESO, определяющие конфигурацию подключения, адрес сервера и метод аутентификации во внешнем хранилище. `SecretStore` изолирован пространством имен (namespace-scoped), `ClusterSecretStore` доступен во всем кластере.
- **ExternalSecret** — декларативный ресурс ESO, описывающий маппинг внешних путей и ключей хранилища в нативный объект `Secret` Kubernetes с заданным интервалом проверки изменений (`refreshInterval`).
- **PushSecret** — ресурс ESO, обеспечивающий обратную синхронизацию: отправку сгенерированных внутри кластера секретов (или результатов генераторов паролей) во внешнее хранилище Vault для интеграции с внешними сервисами.
- **SecretProviderClass (SPC)** — CRD драйвера Secrets Store CSI, декларирующий схему извлечения секретов из конкретного провайдера (например, Vault Provider), параметры путей и формат маппинга файлов.
- **Projected ServiceAccount Token (TokenRequest API)** — короткоживущий криптографический JWT-токен пода с ограниченной областью действия (`audience`) и временным сроком жизни, монтируемый ядром kubelet для аутентификации компонентов в локальном Vault без использования устаревших статических токенов.
- **Дрейф секретов (Drift Detection)** — процесс выявления расхождений между актуальным значением секрета во внешнем хранилище и его копией в нативном `Secret` кластера, выполняемый контроллером оператора по расписанию.
- **Цикл согласования (Reconciliation Loop)** — периодический цикл контроллера Kubernetes, в рамках которого проверяется состояние целевого ресурса, опрашивается источник истины и устраняются расхождения между декларативным состоянием и реальным кластером.

---

## Архитектура и базовые концепции

### Зачем нужны внешние менеджеры в On-Premise инфраструктуре

Хранение конфиденциальных данных в стандартных объектах Kubernetes `Secret` создает критические риски в локальных дата-центрах и bare-metal инсталляциях:

1. **Изоляция базы данных etcd:** Нативные секреты сериализуются в Base64 и без активации KMS-плагина сохраняются в открытом виде в `etcd`. Внешний менеджер секретов позволяет минимизировать количество чувствительных данных в etcd либо исключить их хранение полностью (при использовании Secrets Store CSI Driver все данные живут исключительно в оперативной памяти `tmpfs` рабочего узла).
2. **Централизация и единый аудит (Zero Trust):** Жизненный цикл паролей баз данных, приватных ключей и токенов API управляется в одном месте. Системы класса HashiCorp Vault / OpenBao обеспечивают неизменяемый журнал аудита (кто, в какое время, с какого ServiceAccount и какой секрет прочитал).
3. **Динамические учетные записи и короткий TTL:** Вместо бессрочных статических паролей внешние системы позволяют генерировать одноразовые учетные записи баз данных со сроком жизни от нескольких минут до нескольких часов, автоматически удаляя их по истечении аренды (lease).
4. **Устранение «отравленной истории» в GitOps:** В репозиторий Git коммитятся только декларативные ссылки на пути (`ExternalSecret`, `SecretProviderClass`), а сами секреты никогда не покидают периметр защищенного хранилища.

### Модели доставки секретов

В Kubernetes выделяют три ключевые модели взаимодействия с внешними хранилищами:

```
[Внешнее хранилище: HashiCorp Vault / OpenBao]
       │                           │                           │
  (1) Pull / Sync            (2) On-Demand              (3) Sidecar / Direct
       │                           │                           │
       ▼                           ▼                           ▼
[External Secrets Op]    [Secrets Store CSI]        [Vault Agent Container]
       │                           │                           │
       ▼                           ▼                           ▼
[etcd: Secret K8s]        [Узел K8s: tmpfs]          [Shared Volume: tmpfs]
       │                           │                           │
       ▼                           ▼                           ▼
[Pod: ENV / Volume]       [Pod: Mount Volume]        [Pod: Mount Volume]
```

1. **Синхронизация через оператор (Pull/Sync — ESO / VSO):** Фоновый оператор периодически считывает данные из Vault по протоколу HTTPS и создает/обновляет стандартные объекты `Secret` в Kubernetes. Приложения получают данные привычным способом (через `env`, `envFrom` или `secretVolume`).
2. **Монтирование по требованию (On-Demand — Secrets Store CSI Driver):** Том монтируется kubelet в момент создания Pod. Драйвер CSI перехватывает системный вызов `NodePublishVolume`, связывается с провайдером Vault, считывает секрет и монтирует виртуальную файловую систему в оперативную память контейнера. Секрет не появляется в `etcd`.
3. **Прямое внедрение (Direct / Sidecar Injection — Vault Agent):** В Pod через Mutating Admission Webhook внедряется служебный контейнер (в современных кластерах — Native Sidecar Container). Агент самостоятельно аутентифицируется в Vault, выполняет рендеринг конфигурационных файлов по шаблонам Consul-Template и обновляет их при изменении.

### Сравнительный анализ моделей доставки секретов (On-Premise)

| Критерий | External Secrets Operator (ESO) | Secrets Store CSI Driver | Vault Agent (Native Sidecar) | Vault Secrets Operator (VSO) |
| :--- | :--- | :--- | :--- | :--- |
| **Хранение в etcd** | Да (создает нативный `Secret`) | **Нет** (только оперативная память `tmpfs`) | **Нет** (только общий том `emptyDir/tmpfs`) | Да (создает нативный `Secret`) |
| **Способ передачи в приложение** | Переменные окружения (ENV) и файлы | **Только файлы** (или опциональный sync в Secret) | Файлы произвольного формата (шаблоны) | Переменные окружения (ENV) и файлы |
| **Совместимость с ПО** | **Абсолютная** (любые legacy и cloud-native сервисы) | Приложения, умеющие читать файлы конфигурации | Приложения, читающие файлы на диске | **Абсолютная** (нативные объекты K8s) |
| **Компоненты в кластере** | `Deployment` контроллера + CRD | `DaemonSet` драйвера + `DaemonSet` провайдера на каждом узле | Sidecar-контейнер в каждом целевом Pod | `Deployment` контроллера + CRD |
| **Потребление ресурсов** | Минимальное (один оператор на кластер) | Среднее (DaemonSet агентов на каждом узле) | Высокое (дополнительный контейнер на каждый Pod) | Минимальное (один оператор на кластер) |
| **Динамические секреты (DB lease)** | Ограниченно (периодический Pull статических KV) | Нет (ориентирован на KV) | **Да** (полноценное продление аренды и рендеринг) | **Да** (`VaultDynamicSecret`, `VaultPKISecret`) |
| **Ротация в приложении** | Требует перезапуска пода (Reloader) | Автоматически обновляет файл на `tmpfs` | Автоматически обновляет файл + отправка `SIGHUP` | Автоматический `rolloutRestartTargets` |
| **Аутентификация** | TokenRequest API / AppRole / mTLS | TokenRequest API пода / SecretRef | TokenRequest API пода (Auto-Auth) | TokenRequest API / AppRole |

### Архитектура и жизненный цикл согласования ESO

В основе работы External Secrets Operator лежит контроллер с циклом согласования (Reconciliation Loop):

1. **Декларация `ExternalSecret`:** Разработчик или администратор описывает манифест `ExternalSecret`, указывая ссылку на хранилище (`secretStoreRef`), список извлекаемых ключей (`data` / `dataFrom`), и параметры целевого секрета (`target`).
2. **Периодический опрос (Drift Detection):** Каждые `refreshInterval` контроллер инициирует проверку внешнего источника. Если значение в Vault изменилось, оператор формирует обновление для кластера.
3. **Безопасная аутентификация:** Контроллер генерирует или извлекает проекционный JWT ServiceAccount для аутентификации в Vault по методу `kubernetes`, получая временный клиентский токен с жестко ограниченным TTL.
4. **Применение политик создания (`creationPolicy`):**
   - `Owner` (рекомендуется): Оператор полностью управляет нативным `Secret`. Ручные правки в объекте Kubernetes перезаписываются оператором при следующем цикле.
   - `Merge`: Оператор дописывает свои ключи в уже существующий `Secret`, не затирая данные, созданные другими процессами (например, Helm-релизом).
   - `Orphan`: Оператор создает `Secret`, но не связывает его жизненный цикл с `ExternalSecret`.
5. **Применение политик удаления (`deletionPolicy`):**
   - `Retain` (по умолчанию): При удалении ресурса `ExternalSecret` целевой нативный `Secret` в Kubernetes сохраняется, предотвращая немедленный отказ приложений.
   - `Delete`: При удалении `ExternalSecret` нативный объект `Secret` немедленно удаляется.
6. **Трансляция статуса в API:** Результат согласования фиксируется в блоке `status.conditions` (`Ready`, `SecretSynced`, `RefreshFailed`). Это позволяет SRE-командам строить мониторинг и алертинг на основе метрик Prometheus.

### Модель безопасности и идентификация в On-Premise (Zero Trust)

В полностью закрытом локальном контуре (без облачных IAM-ролей) доверие между кластером Kubernetes и Vault строится на базе **Kubernetes TokenReview API**:

1. Pod или оператор ESO использует проецируемый токен ServiceAccount (`/var/run/secrets/kubernetes.io/serviceaccount/token`), выпускаемый kube-apiserver через механизм `TokenRequest`.
2. При создании токена обязательно задается атрибут `audience` (например, `audience: "vault"`), что предотвращает использование токена в других сервисах в случае его утечки.
3. Клиент отправляет JWT в Vault по пути `v1/auth/kubernetes/login`.
4. Vault обращается к `TokenReview` API кластера Kubernetes по защищенному каналу с проверкой валидности подписи, срока действия токена, имени ServiceAccount и его namespace.
5. При успешной проверке Vault сопоставляет ServiceAccount с ролью Vault Role и выпускает кратковременный токен доступа с привязанными политиками ACL.

---

## Практические сценарии

### 1. Развертывание External Secrets Operator в отказоустойчивой конфигурации (HA)

В production-окружениях bare-metal кластеров ESO должен развертываться в режиме высокой доступности (HA) с резервированием контроллеров, лидер-выборами (Leader Election) и экспортом метрик для Prometheus.

#### Установка через Helm (ESO 2.13.x)

Создайте файл настроек `eso-values.yaml`:

```yaml
# eso-values.yaml
replicaCount: 2

leaderElect: true

installCRDs: true

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

podDisruptionBudget:
  enabled: true
  minAvailable: 1

affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: external-secrets
          topologyKey: kubernetes.io/hostname

serviceMonitor:
  enabled: true
  interval: 30s
  additionalLabels:
    prometheus: k8s

webhook:
  replicaCount: 2
  podDisruptionBudget:
    enabled: true
    minAvailable: 1

certController:
  replicaCount: 1
```

Выполните установку:

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm repo update
helm upgrade --install external-secrets external-secrets/external-secrets \
  --namespace external-secrets \
  --create-namespace \
  -f eso-values.yaml
# → Release "external-secrets" has been upgraded. Happy Helming!
```

Проверка состояния развернутых компонентов:

```bash
kubectl get pods -n external-secrets -o wide
# → NAME                                                READY   STATUS    RESTARTS   AGE
# → external-secrets-7d84878b68-b7l89                   1/1     Running   0          45s
# → external-secrets-7d84878b68-x9k2p                   1/1     Running   0          45s
# → external-secrets-cert-controller-584768846c-k4m2w   1/1     Running   0          45s
# → external-secrets-webhook-6577889759-9f7w8           1/1     Running   0          45s
# → external-secrets-webhook-6577889759-q8z1z           1/1     Running   0          45s

kubectl get crd | grep external-secrets.io
# → clusterexternalsecrets.external-secrets.io
# → clustersecretstores.external-secrets.io
# → externalsecrets.external-secrets.io
# → pushsecrets.external-secrets.io
# → secretstores.external-secrets.io
```

#### Развертывание через Argo CD Application (GitOps)

В GitOps-контуре развертывание ESO осуществляется манифестом `Application`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: external-secrets-operator
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://charts.external-secrets.io
    chart: external-secrets
    targetRevision: 2.13.0
    helm:
      releaseName: external-secrets
      values: |
        replicaCount: 2
        leaderElect: true
        installCRDs: true
        serviceMonitor:
          enabled: true
  destination:
    server: https://kubernetes.default.svc
    namespace: external-secrets
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

---

### 2. Настройка подключения к локальному HashiCorp Vault / OpenBao

#### Шаг 1: Конфигурация Kubernetes Auth на стороне Vault

На управляющем сервере Vault активируйте метод аутентификации `kubernetes` и настройте валидацию токенов кластера:

```bash
# Активация метода аутентификации
vault auth enable -path=kubernetes kubernetes
# → Success! Enabled kubernetes auth method at: kubernetes/

# Передача CA-сертификата кластера и адреса API сервера Kubernetes
vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc:443" \
  kubernetes_ca_cert=@/etc/kubernetes/pki/ca.crt
# → Success! Data written to: auth/kubernetes/config
```

Создайте политику ACL для ESO, ограничивающую доступ только к чтению секретов сервисов:

```hcl
# /etc/vault/policies/eso-policy.hcl
path "secret/data/production/*" {
  capabilities = ["read"]
}
path "secret/metadata/production/*" {
  capabilities = ["read", "list"]
}
```

Примените политику и создайте привязку к ServiceAccount:

```bash
vault policy write eso-policy /etc/vault/policies/eso-policy.hcl
# → Success! Uploaded policy: eso-policy

vault write auth/kubernetes/role/eso-role \
  bound_service_account_names=eso-sa \
  bound_service_account_namespaces=external-secrets \
  policies=eso-policy \
  audience="vault" \
  ttl=1h
# → Success! Data written to: auth/kubernetes/role/eso-role
```

#### Шаг 2: Создание ServiceAccount и ClusterSecretStore

Создайте выделенный ServiceAccount в кластере Kubernetes:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: eso-sa
  namespace: external-secrets
```

Определите манифест `ClusterSecretStore` с защитой по mTLS и указанием доверенного корпоративного Root CA:

```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: vault-cluster-backend
spec:
  provider:
    vault:
      server: "https://vault.internal.corp:8200"
      path: "secret"
      version: "v2"
      caProvider:
        type: ConfigMap
        name: internal-ca-bundle
        key: ca.crt
        namespace: external-secrets
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "eso-role"
          serviceAccountRef:
            name: "eso-sa"
            namespace: "external-secrets"
            audiences:
              - "vault"
```

Проверка статуса подключения к Vault:

```bash
kubectl get clustersecretstore vault-cluster-backend
# → NAME                    AGE   STATUS   CAPABILITIES   READY
# → vault-cluster-backend   12s   Valid    ReadWrite      True
```

---

### 3. Синхронизация секретов через ExternalSecret

#### Важнейшее правило адресации путей в KV v2

В движке Vault KV версии 2 внутренний HTTP API требует префикс `data/` (`v1/secret/data/production/app`).
Оператор ESO **автоматически внедряет данный префикс** при формировании HTTP-запроса.

- **Правильно в `remoteRef.key`:** `production/db` (путь относительно mount point `secret`)
- **Неправильно:** `secret/production/db` или `secret/data/production/db` (приведет к ошибке `404 Secret Not Found`)

#### Сценарий А: Выборка конкретных полей и переименование ключей

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: app-db-credentials
  namespace: production
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-cluster-backend
    kind: ClusterSecretStore
  target:
    name: app-db-credentials
    creationPolicy: Owner
    deletionPolicy: Retain
  data:
    - secretKey: DB_USER
      remoteRef:
        key: production/db
        property: username
    - secretKey: DB_PASSWORD
      remoteRef:
        key: production/db
        property: password
```

#### Сценарий Б: Выгрузка всех ключей объекта через `dataFrom`

Если в секрете Vault хранится множество параметров конфигурации, используйте конструкцию `extract`:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: app-full-config
  namespace: production
spec:
  refreshInterval: 30m
  secretStoreRef:
    name: vault-cluster-backend
    kind: ClusterSecretStore
  target:
    name: app-full-config
    creationPolicy: Owner
  dataFrom:
    - extract:
        key: production/common-config
```

#### Сценарий В: Шаблонизация и генерация DSN / Dockerconfigjson

Шаблонизатор ESO (engine v2) позволяет генерировать сложные конфигурационные файлы, вычислять хеши и собирать connection string на лету:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: backend-database-secret
  namespace: production
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-cluster-backend
    kind: ClusterSecretStore
  target:
    name: backend-database-secret
    creationPolicy: Owner
    template:
      engineVersion: v2
      type: Opaque
      metadata:
        labels:
          app.kubernetes.io/part-of: backend
        annotations:
          managed-by: external-secrets
      data:
        # Генерация готового JDBC / DSN URL
        DATABASE_URL: "postgresql://{{ .user }}:{{ .password }}@pg-cluster.internal.corp:5432/main_db?sslmode=verify-full"
        # Генерация конфигурационного файла Spring/Quarkus
        application.properties: |
          datasource.username={{ .user }}
          datasource.password={{ .password }}
          datasource.pool.max-size=20
  data:
    - secretKey: user
      remoteRef:
        key: production/postgres
        property: username
    - secretKey: password
      remoteRef:
        key: production/postgres
        property: password
```

Проверка результата синхронизации:

```bash
kubectl get externalsecret backend-database-secret -n production
# → NAME                      STORE                   REFRESH INTERVAL   STATUS         READY
# → backend-database-secret   vault-cluster-backend   1h                 SecretSynced   True

kubectl get secret backend-database-secret -n production -o yaml
# → apiVersion: v1
# → kind: Secret
# → metadata:
# →   name: backend-database-secret
# → data:
# →   DATABASE_URL: cG9zdGdyZXNxbDovL3...
# →   application.properties: ZGF0YXNvdXJjZS51...
```

---

### 4. Публикация секретов из кластера во внешний Vault (PushSecret)

В GitOps-архитектуре часто требуется сгенерировать сложный пароль внутри кластера (например, пароль администратора MinIO или ClickHouse) и опубликовать его в Vault для других систем.

```yaml
# 1. Генерация случайного стойкого пароля средствами ESO
apiVersion: generators.external-secrets.io/v1alpha1
kind: Password
metadata:
  name: generated-db-password
  namespace: production
spec:
  length: 32
  digits: 8
  symbols: 0
  noUpper: false
  allowRepeat: true
---
# 2. Создание нативного секрета из генератора
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: cluster-generated-secret
  namespace: production
spec:
  refreshInterval: 1h
  target:
    name: cluster-generated-secret
    creationPolicy: Owner
  dataFrom:
    - sourceRef:
        generatorRef:
          apiVersion: generators.external-secrets.io/v1alpha1
          kind: Password
          name: generated-db-password
---
# 3. Экспорт сгенерированного секрета в Vault
apiVersion: external-secrets.io/v1alpha1
kind: PushSecret
metadata:
  name: push-to-vault
  namespace: production
spec:
  refreshInterval: 1h
  secretStoreRefs:
    - name: vault-cluster-backend
      kind: ClusterSecretStore
  selector:
    secret:
      name: cluster-generated-secret
  data:
    - match:
        secretKey: password
        remoteRef:
          remoteKey: production/generated/db
          property: password
```

---

### 5. Использование Secrets Store CSI Driver с провайдером Vault

Подход обеспечивает максимальную изоляцию: секреты физически не существуют в `etcd` и монтируются ядром Linux в `tmpfs` контейнера.

#### Установка CSI Driver и Vault Provider

```bash
# 1. Установка базового CSI Driver
helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts
helm install csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver \
  --namespace kube-system \
  --set enableSecretRotation=true \
  --set rotationPollInterval=120s
# → STATUS: deployed

# 2. Установка HashiCorp Vault Provider для CSI
helm repo add hashicorp https://helm.releases.hashicorp.com
helm install vault-csi-provider hashicorp/vault \
  --namespace kube-system \
  --set "injector.enabled=false" \
  --set "server.enabled=false" \
  --set "csi.enabled=true"
# → STATUS: deployed
```

Проверка состояния демонов на каждом узле кластера:

```bash
kubectl get daemonset -n kube-system -l app.kubernetes.io/instance=csi-secrets-store
# → NAME                         DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE
# → csi-secrets-store-driver     3         3         3       3            3
```

#### Описание SecretProviderClass

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vault-tls-certs
  namespace: production
spec:
  provider: vault
  parameters:
    vaultAddress: "https://vault.internal.corp:8200"
    roleName: "eso-role"
    vaultCACertPath: "/etc/ssl/certs/ca-certificates.crt"
    objects: |
      - objectName: "server.crt"
        secretPath: "secret/data/production/tls"
        secretKey: "certificate"
      - objectName: "server.key"
        secretPath: "secret/data/production/tls"
        secretKey: "private_key"
```

#### Монтирование тома в Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secure-web-api
  namespace: production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: secure-web-api
  template:
    metadata:
      labels:
        app: secure-web-api
    spec:
      serviceAccountName: eso-sa
      containers:
        - name: web-api
          image: internal-registry.corp/apps/web-api:v2.4.0
          volumeMounts:
            - name: certs-volume
              mountPath: "/etc/ssl/certs/app"
              readOnly: true
      volumes:
        - name: certs-volume
          csi:
            driver: secrets-store.csi.k8s.io
            readOnly: true
            volumeAttributes:
              secretProviderClass: "vault-tls-certs"
```

Валидация смонтированных файлов внутри пода:

```bash
kubectl exec -n production deploy/secure-web-api -- ls -la /etc/ssl/certs/app
# → total 0
# → drwxrwxrwx 2 root root 80 Oct 17 21:00 .
# → -rw-r--r-- 1 root root 1240 Oct 17 21:00 server.crt
# → -rw-r--r-- 1 root root 1675 Oct 17 21:00 server.key
```

---

### 6. Интеграция через Vault Agent (Native Sidecar Container)

Начиная с Kubernetes 1.29+ внедрен стабильный механизм **Native Sidecar Containers** (`initContainers` с полем `restartPolicy: Always`). Vault Agent запускается до старта основного приложения, выполняет первичную выгрузку файлов и продолжает работать в фоне для ротации.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-processor
  namespace: production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: payment-processor
  template:
    metadata:
      labels:
        app: payment-processor
    spec:
      serviceAccountName: eso-sa
      volumes:
        - name: shared-secrets
          emptyDir:
            medium: Memory
        - name: vault-config
          configMap:
            name: vault-agent-config
      initContainers:
        - name: vault-agent
          image: hashicorp/vault:1.21.0
          restartPolicy: Always
          args: ["agent", "-config=/etc/vault/vault-agent-config.hcl"]
          volumeMounts:
            - name: shared-secrets
              mountPath: "/vault/secrets"
            - name: vault-config
              mountPath: "/etc/vault"
      containers:
        - name: app
          image: internal-registry.corp/finance/processor:v1.12.0
          volumeMounts:
            - name: shared-secrets
              mountPath: "/vault/secrets"
              readOnly: true
```

---

### 7. Автоматический перезапуск приложений при ротации секретов (SRE-паттерн)

Если приложение считывает значения секретов из переменных окружения (`env` / `envFrom`), при изменении нативного объекта `Secret` переменные внутри запущенных контейнеров **не обновляются** (они инициализируются ядром Linux только при системном вызове `execve`).

Для обеспечения прозрачной ротации применяется оператор **Stakater Reloader**:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-backend
  namespace: production
  annotations:
    # Автоматический перезапуск пода при изменении любого Secret или ConfigMap, смонтированного в него
    reloader.stakater.com/auto: "true"
spec:
  replicas: 3
  template:
    metadata:
      labels:
        app: payment-backend
    spec:
      containers:
        - name: server
          image: internal-registry.corp/apps/payment:v3.1.0
          envFrom:
            - secretRef:
                name: app-db-credentials
```

При обновлении данных в Vault:
1. ESO обнаруживает дрейф и обновляет объект `Secret/app-db-credentials`.
2. Reloader перехватывает событие обновления через Informer и выполняет скользящий перезапуск (`RollingUpdate`) Deployment.

---

## Операции и команды

Справочник базовых команд для инженера DevOps / SRE при эксплуатации внешних систем управления секретами:

| Задача | Команда | Ожидаемый результат / Описание |
| :--- | :--- | :--- |
| **Список всех ExternalSecret** | `kubectl get externalsecrets.external-secrets.io -A -o wide` | Вывод имени, namespace, целевого `Secret`, статуса и времени обновления |
| **Детализация синхронизации** | `kubectl describe externalsecret <name> -n <ns>` | Анализ секции `Events` и условий `status.conditions` |
| **Принудительная ресинхронизация** | `kubectl annotate externalsecret <name> force-sync="$(date +%s)" -n <ns> --overwrite` | Немедленный запуск опроса внешнего хранилища без ожидания `refreshInterval` |
| **Проверка статуса хранилищ** | `kubectl get clustersecretstore,secretstore -A` | Проверка флага `READY=True` для всех подключений к Vault |
| **Инспекция CSI SecretProvider** | `kubectl get secretproviderclasses.secrets-store.csi.x-k8s.io -A` | Список зарегистрированных классов монтирования томов |
| **Статус монтирования CSI подами** | `kubectl get secretproviderclasspodstatus -A` | Отображение привязки конкретного Pod к томам и секретам CSI |
| **Логи контроллера ESO** | `kubectl logs -n external-secrets -l app.kubernetes.io/name=external-secrets -c external-secrets --tail=100 -f` | Мониторинг HTTP-запросов к Vault и ошибок авторизации |
| **Тестирование токена K8s в Vault** | `vault write auth/kubernetes/login role=eso-role jwt="$(kubectl create token eso-sa -n external-secrets --audience=vault)"` | Ручная валидация работы механизма Kubernetes Auth со стороны CLI Vault |

### Принудительный перезапуск синхронизации (Force-Sync)

```bash
kubectl annotate externalsecret backend-database-secret force-sync="$(date +%s)" -n production --overwrite
# → externalsecret.external-secrets.io/backend-database-secret annotated

kubectl get externalsecret backend-database-secret -n production
# → NAME                      STORE                   REFRESH INTERVAL   STATUS         READY
# → backend-database-secret   vault-cluster-backend   1h                 SecretSynced   True
```

### Мониторинг ключевых метрик Prometheus для SRE

Оператор ESO экспортирует стандартные метрики Prometheus на порту `8080` (`/metrics`). Ключевые метрики для настройки алертов в Alertmanager:

```promql
# 1. Наличие сбойных секретов (алерт при значении > 0 более 15 минут)
sum(externalsecret_status_condition{condition="Ready",status="False"}) by (namespace, name) > 0

# 2. Ошибки синхронизации оператора (рост темпа сбоев)
sum(rate(externalsecret_sync_calls_error[5m])) by (namespace) > 0

# 3. Время обработки цикла синхронизации (SLA оператора)
histogram_quantile(0.99, sum(rate(externalsecret_reconcile_duration_seconds_bucket[5m])) by (le))

# 4. Ошибки автоматической ротации Secrets Store CSI Driver
sum(rate(secretsstore_csi_rotation_error_total[5m])) > 0
```

---

## Диагностика и устранение неполадок

### Сводная матрица типовых неисправностей

| Симптом / Ошибка | Первопричина | Метод локализации | Решение |
| :--- | :--- | :--- | :--- |
| `status: SecretSyncedError` / `secret not found` | В `remoteRef.key` указан путь с префиксом `secret/` или `data/` | `kubectl describe externalsecret` | Укажите путь относительно точки монтирования (например, `production/app` вместо `secret/data/production/app`) |
| `permission denied` при обращении к Vault | Политика ACL в Vault не разрешает чтение пути, либо истек токен | Логи подов Vault: `vault audit log` | Проверьте `vault policy read eso-policy` и убедитесь в наличии `capabilities = ["read"]` для пути `secret/data/...` |
| `audience claim does not match` | Токен ServiceAccount выпущен с другим `audience` | Проверка `audiences` в `ClusterSecretStore` | Задайте поле `audience: "vault"` в `auth/kubernetes/role` и `audiences: ["vault"]` в `serviceAccountRef` |
| `no matches for kind "SecretStore" in version "external-secrets.io/v1beta1"` | Применение устаревших манифестов API `v1beta1` | `kubectl api-resources \| grep external-secrets` | Переведите все манифесты на версию `apiVersion: external-secrets.io/v1` |
| `ClusterSecretStore: InvalidProviderConfig` / `connection refused` | Vault запечатан (sealed), неверный FQDN или отсутствует доступ | `kubectl describe clustersecretstore` | Проверьте состояние `vault status` (хранилище должно быть распечатано); проверьте сетевой доступ и NetworkPolicy |
| CSI Driver: `FailedMount: volumeattributes: provider not found: provider "vault"` | На узле не запущен daemonset провайдера Vault | `kubectl get pods -n kube-system -l app=vault-csi-provider` | Установите DaemonSet Vault CSI Provider на все рабочие узлы кластера |
| CSI Driver: `failed to get node publish secret` | Секрету авторизации не хватает метки драйвера | `kubectl describe pod <name>` | Установите метку `kubectl label secret <name> secrets-store.csi.k8s.io/used=true` |
| Приложение работает со старыми паролями после ротации | Значения переданы через ENV и закешированы процессом | Сравнение `kubectl get secret` и `env` в Pod | Настройте оператор Stakater Reloader или переведите приложение на чтение файлов из тома |

### Детальные сценарии отладки

#### Проблема 1: Ошибка пути Vault KV v2 (`secret not found`)

- **Симптом:**
  ```text
  Warning  UpdateFailed  35s  external-secrets  could not get secret data from provider: Vault failed to read secret: 404 Not Found
  ```
- **Причина:** Пользователь указал в манифесте `remoteRef.key: secret/data/production/db`. Оператор формирует запрос к `https://vault:8200/v1/secret/data/secret/data/production/db`, возвращающий 404.
- **Исправление:**
  ```yaml
  # Правильная конфигурация:
  data:
    - secretKey: password
      remoteRef:
        key: production/db    # префикс mount point 'secret' и 'data/' опущены
        property: password
  ```

#### Проблема 2: Vault запечатан (Vault is sealed)

- **Симптом:**
  ```text
  Error from provider: Error making API request. Code: 503. Errors: * Vault is sealed
  ```
- **Диагностика:**
  ```bash
  vault status
  # → Key             Value
  # → ---             -----
  # → Sealed          true
  # → Total Shares    5
  # → Threshold       3
  ```
- **Исправление:** Выполните процедуру распечатывания (unseal) кворумом операторов либо проверьте работу службы авто-распечатывания (Auto-unseal via Transit / PKCS#11 HSM).

---

## Рекомендации и лучшие практики

### 1. Архитектурный выбор решения

1. **Используйте External Secrets Operator (ESO) по умолчанию:**
   - Для абсолютного большинства микросервисов, которым требуются стандартные переменные окружения и совместимость со сторонними Helm-чартами без правки их кода.
2. **Используйте Secrets Store CSI Driver:**
   - Для высоконагруженных систем с критическими требованиями комплаенса (PCI DSS, строгая изоляция), где сохранение расшифрованных секретов на диск в `etcd` категорически запрещено политиками безопасности.
3. **Используйте Vault Agent / VSO:**
   - При работе с динамическими секретами баз данных (Dynamic DB Leases со сроком жизни до 1 часа) и автоматической ротацией внутренних TLS-сертификатов через HashiCorp Vault PKI Engine.

### 2. Паттерн первичного развертывания («Secret Zero» Bootstrap)

Не пытайтесь доставлять учетные данные для самого оператора ESO через ESO. Применяйте гибридный подход:

```
[Git-репозиторий платформы]
       │
       ├─► [SealedSecrets / SOPS (age)] ──► Креденшилы Vault, адреса, TLS CA ──► [Старт ESO]
       │
       └─► [ExternalSecret манифесты]  ──► Секреты прикладных сервисов       ──► [Синхронизация из Vault]
```

- **Bootstrap-уровень (Git-шифрование):** Манифесты подключения к Vault, приватные ключи для расшифровки репозиториев и базовые конфигурации хранятся в Git в зашифрованном виде с помощью **Bitnami Sealed Secrets** или **Mozilla SOPS + age**.
- **Runtime-уровень (Внешний менеджер):** Все прикладные секреты микросервисов, пароли баз данных и токены API управляются централизованно в HashiCorp Vault / OpenBao и доставляются оператором ESO.

### 3. Разграничение доступа и изоляция (RBAC)

1. **Запрет доступа разработчиков к `ClusterSecretStore`:** Ресурс `ClusterSecretStore` должен создаваться исключительно администраторами платформы в пространстве имен `external-secrets`. Разработчикам приложений предоставляются права только на создание `ExternalSecret` в рамках их персональных namespace.
2. **Использование namespace-scoped `SecretStore` для команд:** В мультиарендных (multi-tenant) кластерах каждой команде настраивается собственный локальный `SecretStore`, привязанный к уникальной роли Vault и выделенной ветке путей (`secret/data/teams/team-alpha/*`), что исключает доступ к секретам соседних сервисов.
3. **Минимизация прав ServiceAccount:** ServiceAccount, используемый оператором, должен иметь доступ исключительно к TokenReview API, но не обладать правами чтения секретов в кластере через нативный RBAC.

### 4. Оптимизация нагрузки и SRE-параметры

1. **Не устанавливайте агрессивный `refreshInterval`:** Значение по умолчанию должно составлять **от 15 минут до 1 часа** (`refreshInterval: 1h`). Слишком частый опрос (например, `5s`) при наличии сотен `ExternalSecret` вызовет лавинообразную нагрузку на API Vault (Thundering Herd Problem) и может привести к исчерпанию лимитов соединений.
2. **Экстренная ротация через аннотацию:** Для внеплановой немедленной ротации используйте аннотацию `force-sync` вместо уменьшения постоянного интервала опроса.
3. **Отказоустойчивость контроллера:** Всегда развертывайте ESO с флагом `leaderElect: true` минимум в 2 репликах с `podAntiAffinity` по физическим узлам.

---

## Дополнительная информация

### Смотрите также

- [Безопасность Secret](file:///C:/Users/Elise/notes/Kubernetes/Base/secrets/security.md) — механизмы защиты секретов на уровне кластера и RBAC.
- [Хранение в etcd](file:///C:/Users/Elise/notes/Kubernetes/Base/secrets/etcd_storage.md) — внутреннее устройство etcd, риски утечки и шифрование данных at rest.
- [Создание Secret](file:///C:/Users/Elise/notes/Kubernetes/Base/secrets/creating_secrets.md) — базовые типы секретов и способы работы с нативным API.
- [Использование Secret](file:///C:/Users/Elise/notes/Kubernetes/Base/secrets/using_secrets.md) — монтирование через volume, env и envFrom.
- [Helm + секреты](file:///C:/Users/Elise/notes/Kubernetes/Base/secrets/helm_secrets.md) — интеграция секретов в процесс деплоя через Helm.
- [Секреты в StatefulSet](file:///C:/Users/Elise/notes/Kubernetes/Base/secrets/statefulset_secrets.md) — специфика работы с постоянными хранилищами баз данных.
- [Интеграция Vault с Kubernetes](file:///C:/Users/Elise/notes/Vault/guides/vault_kubernetes_integration.md) — детальная настройка Vault Kubernetes Auth, TokenReview и VSO.
- [Vault AppRole](file:///C:/Users/Elise/notes/Vault/guides/vault_auth_approle.md) — аутентификация для внешних процессов и CI/CD контуров.
- [GitOps: Управление секретами и шифрование](file:///C:/Users/Elise/notes/GitOps/secrets_encryption.md) — шифрование в Git через SOPS, Sealed Secrets и сравнение с ESO.
- [Сценарии использования Reloader](file:///C:/Users/Elise/notes/Kubernetes/ToolsUtilities/reloader/reloader_usage_scenarios.md) — настройка автоматического перезапуска рабочих нагрузок при обновлении ConfigMap и Secret.
- [Обзор Sealed Secrets](file:///C:/Users/Elise/notes/Kubernetes/Security/sealed_secrets_overview.md) — асимметричное шифрование секретов для GitOps-пайплайнов.