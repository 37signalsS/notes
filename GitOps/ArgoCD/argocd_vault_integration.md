# Интеграция Argo CD и HashiCorp Vault: Argo CD Vault Plugin

**Актуально для:** Argo CD v2.10–v3.5+, Argo CD Vault Plugin (AVP) v1.18.x, HashiCorp Vault 1.18–1.21 / OpenBao 2.x

## Определения

**Argo CD Vault Plugin (AVP)** — специализированный плагин управления конфигурациями (Config Management Plugin, CMP v2) для Argo CD, выполняющий динамическую интерполяцию (подстановку) секретных данных из HashiCorp Vault / OpenBao в Kubernetes-манифесты непосредственно в момент их рендеринга в оперативной памяти пода `argocd-repo-server`.

**HashiCorp Vault / OpenBao** — централизованная система управления секретами, шифрования данных и управления доступом. В on-premise архитектурах развертывается как отказоустойчивый кластер (StatefulSet с Raft Integrated Storage) для предоставления статических и динамических учетных данных.

**Config Management Plugin v2 (CMP v2)** — стандартная архитектура расширения Argo CD (начиная с v2.4, обязательный стандарт в v2.8+; CMP v1 удален), при которой плагины генерации запускаются в виде изолированных sidecar-контейнеров внутри пода `argocd-repo-server` и взаимодействуют с ядром по протоколу gRPC через локальный UNIX domain socket.

**argocd-cmp-server** — легковесный gRPC-демон Argo CD, работающий как entrypoint внутри sidecar-контейнера плагина. Принимает tar-поток с манифестами, запускает команды плагина и возвращает отрендеренный YAML.

**Secret Zero (Проблема первого секрета)** — фундаментальная дилемма доставки первичного секрета (ServiceAccount Token, AppRole SecretID), необходимого приложению или плагину для первичной аутентификации в Vault.

**Kubernetes Auth Method** — метод аутентификации в Vault, при котором клиент подтверждает подлинность с помощью криптографически подписанного JSON Web Token (JWT) ServiceAccount пода. Проверка подписи выполняется Vault через Kubernetes TokenReviewer API или открытые ключи API-сервера.

**AppRole Auth Method** — метод межсистемной машинной аутентификации в Vault на основе статического `RoleID` и защищенного `SecretID`, предназначенный для сценариев, когда Argo CD и Vault находятся в разных кластерах или дата-центрах.

**KV Secrets Engine (v1 и v2)** — движок хранения данных «ключ-значение» в Vault. Версия 2 (v2, путь API `secret/data/<path>`) поддерживает версионирование секретов, мягкое удаление (soft delete), метаданные и откат к предыдущим ревизиям.

**Redis Manifest Cache** — промежуточный слой кэширования Argo CD (`argocd-redis` / `redis-ha`), хранящий готовые отрендеренные манифесты для ускорения синхронизации и снятия нагрузки с Git-репозиториев и плагинов.

**External Secrets Operator (ESO)** — оператор Kubernetes, реализующий модель постоянной асинхронной синхронизации (Pull/Reconciliation) секретов из Vault в нативные объекты `Secret` Kubernetes через CRD `SecretStore` и `ExternalSecret`.

**Vault Secrets Operator (VSO)** — официальный Kubernetes-нативный оператор от HashiCorp, управляющий жизненным циклом статических (`VaultStaticSecret`), динамических (`VaultDynamicSecret`) и PKI-секретов с нативной поддержкой ротации и триггеров rollout-restart.

---

## Базовые концепции и архитектура

### Проблема управления секретами в GitOps

В методологии GitOps репозиторий Git является единственным источником истины (SSoT). Поскольку стандартные манифесты Kubernetes `Secret` кодируют значения алгоритмом Base64, их сохранение в Git в открытом виде является критической уязвимостью.

Существуют три основные архитектурные модели доставки секретов в GitOps:

1. **Модель интерполяции на лету (In-memory Interpolation / AVP):**
   - В Git хранятся шаблоны манифестов с плейсхолдерами вида `<path:secret/data/app#password>`.
   - Подстановка реальных значений выполняется в оперативной памяти пода `argocd-repo-server` перед отправкой манифестов в Kubernetes API.
   - Секреты попадают в etcd кластера как стандартные `Secret`, но никогда не сохраняются в истории Git.
2. **Модель внутрикластерного оператора (Operator Pull / ESO, VSO):**
   - В Git хранятся декларативные CRD-ресурсы (`ExternalSecret`, `VaultStaticSecret`), содержащие только ссылки на пути в Vault.
   - Оператор внутри кластера автономно опрашивает Vault и создает нативные секреты в etcd.
3. **Модель прямого монтирования в память (In-memory Mount / CSI Driver):**
   - Секреты монтируются напрямую в `tmpfs` пода через Secrets Store CSI Driver без создания объекта `Secret` в etcd.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Сравнение моделей доставки секретов                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ 1. Интерполяция (AVP):                                                      │
│    Git (Плейсхолдер) ──▶ Argo CD CMP ──[Vault API]──▶ k8s Secret (etcd)     │
│                                                                             │
│ 2. Оператор (ESO / VSO):                                                    │
│    Git (CRD ссылка) ──▶ Argo CD Sync ──▶ K8s API ──▶ Operator ──▶ etcd      │
│                                                         │                   │
│                                                    [Vault API]              │
│ 3. CSI Driver:                                                              │
│    Pod Spec ──▶ CSI Driver ──[Vault API]──▶ tmpfs Pod Volume (Без etcd)     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Архитектура CMP v2: взаимодействие repo-server и AVP

В архитектуре CMP v2 процесс `argocd-repo-server` полностью изолирован от внешних исполняемых файлов плагина. Взаимодействие происходит по схеме:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│         Под argocd-repo-server: Архитектура CMP v2 с AVP Sidecar            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────┐     ┌─────────────────────────────────┐  │
│  │ Контейнер repo-server         │     │ Sidecar-контейнер AVP           │  │
│  │ (Основной процесс Argo CD)    │     │ (argocd-cmp-server + AVP)       │  │
│  │                               │     │                                 │  │
│  │ 1. Git Clone / Fetch          │     │ 3. Прием tar stream через сокет │  │
│  │ 2. Упаковка директории в tar  │     │ 4. Выполнение discovery         │  │
│  │ 5. Отправка tar по gRPC ─────┼─────┼─▶ 5. argocd-vault-plugin        │  │
│  │                               │     │      generate ./                │  │
│  │                               │     │           │                     │  │
│  │                               │     │           ▼                     │  │
│  │                               │     │      HTTPS mTLS / K8s Auth      │  │
│  │                               │     │           │                     │  │
│  │ 7. Получение готового YAML ◀──┼─────┼───────────┘                     │  │
│  │ 8. Сохранение в Redis Cache   │     │                                 │  │
│  │ 9. Передача в Controller      │     │                                 │  │
│  └──────────────┬────────────────┘     └────────────────┬────────────────┘  │
│                 │                                       │                   │
│                 ▼                                       ▼                   │
│          ┌─────────────────────────────────────────────────────┐            │
│          │ Разделяемый том emptyDir: /var/run/argocd           │            │
│          │ - argocd-cmp-server.socket (UNIX domain socket)     │            │
│          └─────────────────────────────────────────────────────┘            │
│                                                                             │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼ HTTPS (TCP 8200)
                        ┌───────────────────────────┐
                        │ HashiCorp Vault (On-Prem) │
                        │ - TokenReviewer Auth      │
                        │ - KV v2 Secrets Engine    │
                        │ - Audit Device            │
                        └───────────────────────────┘
```

1. **Fetch & Packaging:** `repo-server` клонирует репозиторий приложения и упаковывает рабочую директорию в сжатый tar-поток.
2. **Передача через UNIX Socket:** Поток передается по gRPC в локальный сокет `/var/run/argocd/argocd-cmp-server.socket`.
3. **Discovery:** Демон `argocd-cmp-server` внутри sidecar проверяет условия обнаружения (наличие `.yaml` файлов или аннотации `avp.kubernetes.io/path`).
4. **Аутентификация и чтение секретов:** Бинарник `argocd-vault-plugin` считывает projected ServiceAccount token (`/var/run/secrets/kubernetes.io/serviceaccount/token`), аутентифицируется в Vault по протоколу TLS и запрашивает секреты по путям из плейсхолдеров.
5. **Генерация (Generate):** Плейсхолдеры заменяются на расшифрованные строки (или base64-значения). Итоговый YAML-манифест возвращается в `repo-server` через stdout.
6. **Кэширование и применение:** `repo-server` сохраняет отрендеренный манифест в `argocd-redis` и передает его в `argocd-application-controller` для применения через Kubernetes API.

### Методы аутентификации в On-Premise инфраструктуре

В закрытых корпоративных контурах (без облачных провайдеров) используются два метода аутентификации:

| Метод | Механизм передачи учетных данных | Область применения | Безопасность |
| :--- | :--- | :--- | :--- |
| **Kubernetes Auth** | Projected ServiceAccount Token (`/var/run/secrets/...`) с валидацией аудитории (`audience="vault"`). | Рекомендуемый стандарт для Argo CD внутри Kubernetes. | Максимальная: токены короткоживущие, ротируются kubelet автоматически, секреты не хранятся на диске. |
| **AppRole** | Пара `RoleID` (статический идентификатор) + `SecretID` (секретный токен с TTL и ограничением по CIDR). | Межкластерное взаимодействие, когда Vault развернут на внешних виртуальных машинах или bare-metal. | Высокая при условии безопасной доставки SecretID через Kubernetes Secret и ограничения по IP-подсетям. |
| **Static Token** | Статический токен администратора через переменную `VAULT_TOKEN`. | Исключительно локальная отладка и dev-стенды. | **Недопустимо в Production** (риск утечки долгоживущего токена). |

### Синтаксис плейсхолдеров AVP

Плагин поддерживает несколько вариантов синтаксиса для подстановки значений из Vault KV v2:

| Синтаксис | Описание | Пример в манифесте |
| :--- | :--- | :--- |
| `<key>` | Подстановка ключа из пути, заданного аннотацией `avp.kubernetes.io/path`. | `password: <db_password>` |
| `<path:key>` | Полный путь к секрету и ключу через двоеточие. | `password: <secret/data/production/db:password>` |
| `<path#key>` | Полный путь к секрету и ключу через решетку. | `password: <secret/data/production/db#password>` |
| `<path:key \| base64>` | Автоматическое кодирование подставляемого значения в Base64. | `tls.key: <secret/data/certs#key \| base64>` |
| `<env:VAR_NAME>` | Подстановка значения локальной переменной окружения sidecar. | `cluster_env: <env:ENVIRONMENT_NAME>` |

> **Критическое правило для KV v2:** При обращении к KV v2 через полный путь необходимо явно указывать префикс `data` в пути: `<secret/data/app#key>`. Если указать `<secret/app#key>`, Vault вернет ошибку `404 Not Found`, так как API KV v2 разделяет точки монтирования метаданных и значений.

---

## Практические сценарии

### Сценарий 1: Подготовка HashiCorp Vault в On-Premise среде

Настройка корпоративного Vault для взаимодействия с ServiceAccount Argo CD.

**1. Включение KV-хранилища версии 2:**

```bash
# Проверка статуса хранилища
vault status
# → Key             Value
# → ---             -----
# → Sealed          false
# → Total Shares    5
# → Threshold       3
# → Version         1.20.1

# Включение KV v2 на пути secret/
vault secrets enable -path=secret kv-v2
# → Success! Enabled the kv-v2 secrets engine at: secret/

# Создание тестового секрета приложения
vault kv put secret/production/billing-service \
    db_user="billing_app" \
    db_password="SuperSecurePassword2026!" \
    api_key="sec_token_998124819"
# → === Secret Path ===
# → secret/data/production/billing-service
# → ======= Metadata =======
# → Key                Value
# → ---                -----
# → created_time       2026-10-12T16:40:00Z
# → deletion_time      n/a
# → destroyed          false
# → version            1
```

**2. Создание политики безопасности с минимальными правами (Least Privilege):**

Создайте файл `argocd-policy.hcl`:

```hcl
# Разрешение только на чтение секретов в ветке production
path "secret/data/production/*" {
  capabilities = ["read"]
}

# Запрет на доступ к системным веткам
path "secret/data/admin/*" {
  capabilities = ["deny"]
}
```

Применение политики:

```bash
vault policy write argocd-repo-policy argocd-policy.hcl
# → Success! Uploaded policy: argocd-repo-policy
```

**3. Настройка метода аутентификации Kubernetes:**

В Kubernetes 1.21+ и Vault 1.9+ обязательным требованием является указание параметра `issuer`. Для надежности настраивается доступ к Kubernetes API через CA кластера.

```bash
# Включение метода k8s auth
vault auth enable kubernetes
# → Success! Enabled kubernetes auth method at: kubernetes/

# Извлечение параметров кластера изнутри пода или контроллера
SA_CA_CERT="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
K8S_HOST="https://kubernetes.default.svc:443"

# Конфигурация Kubernetes auth в Vault
vault write auth/kubernetes/config \
    kubernetes_host="${K8S_HOST}" \
    kubernetes_ca_cert=@${SA_CA_CERT} \
    issuer="https://kubernetes.default.svc.cluster.local"
# → Success! Data written to: auth/kubernetes/config

# Создание роли с жесткой привязкой к ServiceAccount argocd-repo-server
vault write auth/kubernetes/role/argocd-vault-role \
    bound_service_account_names=argocd-repo-server \
    bound_service_account_namespaces=argocd \
    policies=argocd-repo-policy \
    audience="vault" \
    ttl=1h \
    max_ttl=4h
# → Success! Data written to: auth/kubernetes/role/argocd-vault-role
```

**4. Верификация аутентификации из пода:**

```bash
# Получение Projected Token из пода repo-server
kubectl exec -n argocd deploy/argocd-repo-server -c repo-server -- \
  cat /var/run/secrets/kubernetes.io/serviceaccount/token > /tmp/sa.jwt

# Тестовый вход от имени роли
vault write auth/kubernetes/login \
    role=argocd-vault-role \
    jwt=@/tmp/sa.jwt
# → Key                  Value
# → ---                  -----
# → token                hvs.CAESIJ...
# → token_accessor       aBcDeFg...
# → token_duration       1h
# → token_policies       ["argocd-repo-policy" "default"]
```

---

### Сценарий 2: Развертывание AVP как CMP v2 Sidecar

Для интеграции плагина необходимо настроить два компонента: манифест плагина `plugin.yaml` в ConfigMap и декларацию sidecar-контейнера в Deployment `argocd-repo-server`.

**1. ConfigMap с конфигурацией плагина `avp-cmp-plugin-config`:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: avp-cmp-plugin-config
  namespace: argocd
data:
  plugin.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata:
      name: argocd-vault-plugin
    spec:
      version: v1.0
      discover:
        find:
          glob: ".*\\.yaml"
      generate:
        command: ["argocd-vault-plugin"]
        args: ["generate", "./"]
      allowConcurrency: true
      lockRepo: false
```

**Параметры `plugin.yaml`:**
- `spec.discover.find.glob` — маска поиска файлов. Плагин активируется для каталогов, содержащих файлы YAML.
- `spec.generate.command` и `args` — команда запуска генерации. Флаг `./` указывает на текущую рабочую директорию распакованного репозитория.
- `allowConcurrency: true` — разрешает параллельную обработку приложений несколькими воркерами (критично для производительности SRE).
- `lockRepo: false` — запрещает монопольную блокировку репозитория на время генерации манифестов.

**2. Патч для Deployment `argocd-repo-server`:**

Манифест включает `initContainer` для копирования бинарника CMP-сервера и sidecar-контейнер с AVP.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: argocd-repo-server
  namespace: argocd
spec:
  template:
    spec:
      # Инициализирующий контейнер копирует бинарный файл argocd
      initContainers:
        - name: copyutil
          image: quay.io/argoproj/argocd:v2.10.9
          command: [cp, -n, /usr/local/bin/argocd, /var/run/argocd/argocd-cmp-server]
          volumeMounts:
            - mountPath: /var/run/argocd
              name: var-files
        - name: download-avp
          image: alpine:3.20
          command: [sh, -c]
          args:
            - |
              wget -qO /custom-tools/argocd-vault-plugin \
                https://github.com/argoproj-labs/argocd-vault-plugin/releases/download/v1.18.1/argocd-vault-plugin_1.18.1_linux_amd64 && \
              chmod +x /custom-tools/argocd-vault-plugin
          volumeMounts:
            - name: custom-tools
              mountPath: /custom-tools

      containers:
        # Sidecar CMP v2
        - name: argocd-vault-plugin
          command: [/var/run/argocd/argocd-cmp-server]
          image: alpine:3.20
          securityContext:
            runAsNonRoot: true
            runAsUser: 999
            runAsGroup: 999
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          resources:
            limits:
              cpu: 500m
              memory: 512Mi
            requests:
              cpu: 100m
              memory: 128Mi
          env:
            - name: AVP_TYPE
              value: "vault"
            - name: AVP_AUTH_TYPE
              value: "k8s"
            - name: AVP_K8S_ROLE
              value: "argocd-vault-role"
            - name: AVP_K8S_MOUNT
              value: "kubernetes"
            - name: VAULT_ADDR
              value: "https://vault.internal.corp:8200"
            - name: VAULT_CACERT
              value: "/etc/ssl/certs/vault-ca.pem"
            - name: ARGOCD_EXEC_TIMEOUT
              value: "90s"
          volumeMounts:
            - name: var-files
              mountPath: /var/run/argocd
            - name: cmp-plugin-config
              mountPath: /home/argocd/cmp-server/config/plugin.yaml
              subPath: plugin.yaml
            - name: custom-tools
              mountPath: /usr/local/bin/argocd-vault-plugin
              subPath: argocd-vault-plugin
            - name: vault-ca
              mountPath: /etc/ssl/certs/vault-ca.pem
              subPath: vault-ca.pem
              readOnly: true
            - name: cmp-tmp
              mountPath: /tmp
          readinessProbe:
            exec:
              command: [test, -S, /var/run/argocd/argocd-cmp-server.socket]
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            exec:
              command: [test, -S, /var/run/argocd/argocd-cmp-server.socket]
            initialDelaySeconds: 10
            periodSeconds: 30

      volumes:
        - name: var-files
          emptyDir: {}
        - name: custom-tools
          emptyDir: {}
        - name: cmp-tmp
          emptyDir: {}
        - name: cmp-plugin-config
          configMap:
            name: avp-cmp-plugin-config
        - name: vault-ca
          configMap:
            name: internal-ca-bundle
```

---

### Сценарий 3: Конвейеры рендеринга AVP с Helm и Kustomize

В реальных GitOps-репозиториях манифесты структурируются с помощью Helm или Kustomize. Стандартный запуск `argocd-vault-plugin generate ./` не умеет шаблонизировать Helm-чарты. Для этого настраиваются специализированные CMP v2 конвейеры (pipelines).

#### Конвейер AVP + Helm

Конфигурация `plugin.yaml` для рендеринга Helm с последующей интерполяцией секретов:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ConfigManagementPlugin
metadata:
  name: avp-helm
spec:
  version: v1.0
  discover:
    fileName: "Chart.yaml"
  init:
    command: ["sh", "-c"]
    args: ["helm dependency build ."]
  generate:
    command: ["sh", "-c"]
    args:
      - |
        helm template "${ARGOCD_APP_NAME}" -n "${ARGOCD_APP_NAMESPACE}" . \
          ${ARGOCD_ENV_HELM_ARGS} | \
        argocd-vault-plugin generate -
```

**Фрагмент `values.yaml` чарта приложения:**

```yaml
database:
  host: "postgres.internal.corp"
  port: 5432
  user: "<secret/data/production/billing-service#db_user>"
  password: "<secret/data/production/billing-service#db_password>"
```

#### Конвейер AVP + Kustomize

Конфигурация `plugin.yaml` для сборки оверлеев Kustomize с передачей потока в AVP:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ConfigManagementPlugin
metadata:
  name: avp-kustomize
spec:
  version: v1.0
  discover:
    fileName: "kustomization.yaml"
  generate:
    command: ["sh", "-c"]
    args:
      - "kustomize build . | argocd-vault-plugin generate -"
```

**Фрагмент `secret.yaml` в Kustomize-оверлее:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: billing-credentials
  annotations:
    avp.kubernetes.io/path: "secret/data/production/billing-service"
type: Opaque
stringData:
  DB_USER: <db_user>
  DB_PASSWORD: <db_password>
  API_KEY: <api_key>
```

---

### Сценарий 4: Декларативное описание Application и параметры Sync Waves

Привязка приложения к CMP v2 и управление очередностью синхронизации через паттерн App-of-Apps.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-service
  namespace: argocd
  annotations:
    # Гарантирует развертывание секретов до развертывания основного Deployment
    argocd.argoproj.io/sync-wave: "-5"
spec:
  project: default
  source:
    repoURL: 'git@gitlab.internal.corp:fintech/billing-service.git'
    targetRevision: main
    path: deploy/k8s
    plugin:
      name: argocd-vault-plugin
      env:
        - name: AVP_TYPE
          value: vault
        - name: AVP_AUTH_TYPE
          value: k8s
        - name: AVP_K8S_ROLE
          value: argocd-vault-role
        - name: VAULT_ADDR
          value: "https://vault.internal.corp:8200"
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ApplyOutOfSyncOnly=true
```

---

### Сценарий 5: Автоматический перезапуск подов при ротации секретов (Rolling Update)

**Проблема:** AVP подставляет секреты только при наступлении GitOps-события (коммит в Git или ручной Sync). Если администратор изменил пароль в Vault, Argo CD не обнаружит расхождение (Drift), так как хэш коммита в Git не изменился.

**Решение 1: Вычисление Checksum аннотации в Helm/Kustomize**

В шаблоне `Deployment` добавляется аннотация с контрольной суммой файла секрета. При любом изменении значений в секрете хэш меняется, вызывая стандартный Rolling Update:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
spec:
  template:
    metadata:
      annotations:
        # Автоматический пересчет хэша манифеста секрета
        checksum/vault-secrets: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
    spec:
      containers:
        - name: app
          image: registry.internal.corp/billing:v2.4.0
          envFrom:
            - secretRef:
                name: billing-credentials
```

**Решение 2: Использование оператора Reloader**

Оператор Reloader отслеживает изменения в целевом объекте `Secret` внутри Kubernetes и выполняет rollout restart зависимых Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
  annotations:
    # Перезапуск пода при изменении секрета billing-credentials в неймспейсе
    secret.reloader.stakater.com/reload: "billing-credentials"
spec:
  replicas: 3
  # ...
```

---

### Сценарий 6: Сетевая безопасность и изоляция (NetworkPolicy и RBAC)

Для соответствия требованиям безопасности необходимо изолировать сетевой контур пода `argocd-repo-server`.

**1. NetworkPolicy для изоляции repo-server и разрешения доступа к Vault:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-repo-server-egress
  namespace: argocd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-repo-server
  policyTypes:
    - Egress
  egress:
    # 1. Доступ к CoreDNS кластера
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53

    # 2. Доступ к локальному HashiCorp Vault (On-Prem)
    - to:
        - ipBlock:
            cidr: 10.100.50.15/32 # IP балансировщика Vault
      ports:
        - protocol: TCP
          port: 8200

    # 3. Доступ к Kubernetes API Server для TokenReviewer
    - to:
        - ipBlock:
            cidr: 10.96.0.1/32
      ports:
        - protocol: TCP
          port: 443

    # 4. Доступ к Redis Cache
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-redis
      ports:
        - protocol: TCP
          port: 6379

    # 5. Доступ к корпоративному GitLab/Gitea
    - to:
        - ipBlock:
            cidr: 10.100.10.0/24
      ports:
        - protocol: TCP
          port: 443
        - protocol: TCP
          port: 22
```

---

### Сценарий 7: Защита кэша Redis от утечки секретов (SRE & Sysadmin Hardening)

#### Архитектурная уязвимость AVP в Redis

При рендеринге манифестов `argocd-repo-server` сохраняет готовый вывод в Redis с префиксом ключа `mfst|...`. Поскольку AVP заменяет плейсхолдеры реальными значениями, **пароли, закрытые ключи и токены сохраняются в оперативной памяти Redis в незашифрованном открытом виде**.

Если к Redis имеют доступ другие сервисы или в кластере отсутствует шифрование трафика, возникает прямая угроза компрометации.

#### Меры защиты Redis для SRE/Sysadmin:

1. **Включение парольной аутентификации (AUTH):** Убедитесь, что в ConfigMap `argocd-cm` и Secret `argocd-secret` задан стойкий пароль `REDIS_PASSWORD`.
2. **Включение TLS-шифрования трафика к Redis:** Запуск с флагом `--redis-use-tls` предотвращает перехват сетевого трафика.
3. **Ограничение времени жизни кэша:** Уменьшите время жизни кэша манифестов в параметрах `argocd-cmd-params-cm`:
   ```yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: argocd-cmd-params-cm
     namespace: argocd
   data:
     # Снижение времени удержания отрендеренных манифестов в памяти Redis до 3 минут
     repo.server.manifest.cache.expiration: "3m"
   ```
4. **Очистка скомпрометированного кэша манифестов без простоя:**
   При плановой или экстренной ротации секретов в Vault необходимо принудительно удалить старые манифесты из Redis:

```bash
# Поиск и удаление ключей отрендеренных манифестов приложения billing
kubectl exec -it -n argocd deploy/argocd-redis -- \
  redis-cli --scan --pattern "mfst|*billing-service*" | \
  xargs -r kubectl exec -i -n argocd deploy/argocd-redis -- redis-cli del
# → (integer) 4

# Проверка использования памяти Redis
kubectl exec -it -n argocd deploy/argocd-redis -- redis-cli info memory | grep used_memory_human
# → used_memory_human:14.28M
```

---

### Сценарий 8: Стратегия миграции с AVP на External Secrets Operator (ESO)

Для устранения рисков хранения секретов в Redis и обеспечения автоматической синхронизации рекомендуется планомерная миграция с AVP на External Secrets Operator (ESO).

#### Сравнение AVP, ESO и VSO в On-Premise инфраструктуре:

| Критерий | Argo CD Vault Plugin (AVP) | External Secrets Operator (ESO) | Vault Secrets Operator (VSO) |
| :--- | :--- | :--- | :--- |
| **Принцип работы** | Интерполяция при сборке в CMP sidecar | Асинхронный контроллер (Pull) | Нативный оператор от HashiCorp |
| **Хранение секретов** | Память sidecar + **открытый кэш Redis** | Только в `etcd` (как нативный `Secret`) | Только в `etcd` / память подов |
| **Авторотация при дрейфе** | Нет (требует Git commit или ручной Sync) | **Да** (по параметру `refreshInterval: 1h`) | **Да** (Event-driven / lease renewal) |
| **Динамические секреты Vault** | Не поддерживаются | Базовая поддержка | **Полная нативная поддержка** |
| **Точка отказа** | Зависимость сборщика от доступности Vault | Разделение: сборщик независим от Vault | Разделение: сборщик независим от Vault |
| **Рекомендация** | Поддержка legacy-репозиториев | **Рекомендуемый отраслевой стандарт** | Для Enterprise-сред с глубокой связкой с Vault |

#### Пошаговый план миграции:

1. **Развертывание ESO в кластере через Helm:**
   ```bash
   helm repo add external-secrets https://charts.external-secrets.io
   helm upgrade --install external-secrets external-secrets/external-secrets \
     -n external-secrets --create-namespace \
     --set installCRDs=true
   # → STATUS: deployed
   ```

2. **Создание кластерного хранилища `ClusterSecretStore` с Kubernetes Auth:**
   ```yaml
apiVersion: external-secrets.io/v1
    kind: ClusterSecretStore
   metadata:
     name: vault-backend
   spec:
     provider:
       vault:
         server: "https://vault.internal.corp:8200"
         path: "secret"
         version: "v2"
         caProvider:
           type: ConfigMap
           name: internal-ca-bundle
           namespace: external-secrets
           key: vault-ca.pem
         auth:
           kubernetes:
             mountPath: "kubernetes"
             role: "argocd-vault-role"
             serviceAccountRef:
               name: external-secrets-sa
               namespace: external-secrets
   ```

3. **Замена манифеста секрета с плейсхолдерами AVP на декларативный `ExternalSecret`:**
   ```yaml
apiVersion: external-secrets.io/v1
    kind: ExternalSecret
   metadata:
     name: billing-credentials-es
     namespace: production
   spec:
     refreshInterval: "1h"
     secretStoreRef:
       name: vault-backend
       kind: ClusterSecretStore
     target:
       name: billing-credentials # Имя целевого k8s Secret
       creationPolicy: Owner
     data:
       - secretKey: DB_USER
         remoteRef:
           key: production/billing-service
           property: db_user
       - secretKey: DB_PASSWORD
         remoteRef:
           key: production/billing-service
           property: db_password
   ```

4. **Результат:** Argo CD больше не выполняет обращений к Vault, манифесты в Redis не содержат паролей, а обновление данных в Vault автоматически транслируется в Kubernetes Secret в течение 1 часа.

---

## Справочник конфигурации и переменных окружения AVP

Все параметры AVP конфигурируются через переменные окружения sidecar-контейнера или манифеста `Application`:

| Переменная окружения | Описание | Значение по умолчанию | Обязательность |
| :--- | :--- | :--- | :--- |
| `AVP_TYPE` | Тип используемого бэкенда секретов. Для Vault задается строго `vault`. | `vault` | Да |
| `AVP_AUTH_TYPE` | Метод аутентификации (`k8s`, `kubernetes`, `approle`, `token`). | `token` | Да |
| `VAULT_ADDR` | Сетевой URL API сервера HashiCorp Vault. | `http://localhost:8200` | Да |
| `AVP_K8S_ROLE` | Имя роли в Vault Kubernetes Auth Method. | — | Обязательно при `AVP_AUTH_TYPE=k8s` |
| `AVP_K8S_MOUNT` | Точка монтирования метода Kubernetes Auth в Vault. | `kubernetes` | Нет |
| `AVP_K8S_TOKEN_PATH`| Путь к ServiceAccount JWT-токену на файловой системе. | `/var/run/secrets/kubernetes.io/serviceaccount/token` | Нет |
| `AVP_ROLE_ID` | Role ID для машинной аутентификации AppRole. | — | Обязательно при `AVP_AUTH_TYPE=approle` |
| `AVP_SECRET_ID` | Secret ID для машинной аутентификации AppRole. | — | Обязательно при `AVP_AUTH_TYPE=approle` |
| `AVP_PATH_VERSION` | Версия движка KV secrets engine (`1` или `2`). | `2` | Нет |
| `VAULT_CACERT` | Путь к доверенному корневому сертификату CA для проверки TLS. | — | Рекомендуется для on-premise TLS |
| `VAULT_NAMESPACE` | Пространство имен Vault (для Enterprise-редакций). | — | Нет |
| `ARGOCD_EXEC_TIMEOUT` | Таймаут выполнения скрипта плагина в секундах. | `90s` | Нет |

---

## Диагностика и типичные ошибки (Troubleshooting)

### Систематическая матрица сбоев

| Ошибка / Симптом | Первопричина | Диагностическая команда | Метод устранения |
| :--- | :--- | :--- | :--- |
| **`Permission Denied (403)` при входе в Vault** | ServiceAccount не привязан к роли в Vault или истек TTL токена. | `vault read auth/kubernetes/role/argocd-vault-role` | Проверить поля `bound_service_account_names` и `bound_service_account_namespaces` в роли Vault. |
| **`claim "iss" is invalid`** | Несовпадение эмитента JWT-токена в Kubernetes 1.21+ с настройкой Vault. | `kubectl get --raw /.well-known/openid-configuration` | Выставить в Vault параметр `issuer="https://kubernetes.default.svc.cluster.local"` либо обновить Vault до актуальной версии. |
| **`audience mismatch`** | Токен пода выписан для другой аудитории, отличной от настроенной в роли. | `cat /tmp/sa.jwt \| jq -R 'split(".") \| .[1] \| @base64d \| fromjson'` | Добавить `audience="vault"` в команду `vault write auth/kubernetes/role/...`. |
| **`Vault is sealed (503)`** | Ноды кластера Vault находятся в запечатанном состоянии после рестарта. | `vault status` | Выполнить процедуру unseal через кворум ключей (`vault operator unseal`) или настроить Transit Auto-unseal. |
| **`Plugin not found` в UI Argo CD** | Sidecar-контейнер не запустился или UNIX-сокет не создан в `/var/run/argocd`. | `kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-repo-server` | Проверить логи `argocd-cmp-server` и наличие монтирования тома `var-files`. |
| **`ARGOCD_EXEC_TIMEOUT exceeded`** | Долгая загрузка чартов Helm или сетевая задержка к Vault. | `kubectl logs -n argocd deploy/argocd-repo-server -c argocd-vault-plugin` | Увеличить `ARGOCD_EXEC_TIMEOUT` до `180s` и проверить NetworkPolicy. |
| **Секреты не обновляются в поде после смены в Vault** | Argo CD кэширует манифест в Redis, а Git-хэш не изменился. | `argocd app get <app> --hard-refresh` | Выполнить Hard Refresh в UI/CLI, сбросить кэш Redis или настроить Reloader. |

### Практические команды диагностики

**1. Проверка работоспособности UNIX domain socket в sidecar:**

```bash
# Проверка наличия файла сокета в разделяемом томе
kubectl exec -n argocd deploy/argocd-repo-server -c argocd-vault-plugin -- \
  ls -la /var/run/argocd/argocd-cmp-server.socket
# → srwxr-xr-x 1 argocd argocd 0 Oct 12 16:45 /var/run/argocd/argocd-cmp-server.socket
```

**2. Ручное тестирование генерации манифестов внутри контейнера:**

```bash
# Переход в контейнер плагина и тестовый запуск интерполяции
kubectl exec -it -n argocd deploy/argocd-repo-server -c argocd-vault-plugin -- sh

# Внутри контейнера:
echo '
apiVersion: v1
kind: Secret
metadata:
  name: test-secret
stringData:
  db_pass: <secret/data/production/billing-service#db_password>
' | argocd-vault-plugin generate -
# → apiVersion: v1
# → kind: Secret
# → metadata:
# →   name: test-secret
# → stringData:
# →   db_pass: SuperSecurePassword2026!
```

**3. Проверка сетевого соединения с Vault по TLS:**

```bash
kubectl exec -n argocd deploy/argocd-repo-server -c argocd-vault-plugin -- \
  wget --spider --ca-certificate=/etc/ssl/certs/vault-ca.pem https://vault.internal.corp:8200/v1/sys/health
# → Connecting to vault.internal.corp:8200 (10.100.50.15:8200)
# → remote file exists
```

---

## Лучшие практики (Best Practices)

### Безопасность (Security)
- **Принцип наименьших привилегий (POLP):** Никогда не выдавайте роли `argocd-vault-role` доступ к корню `secret/*`. Ограничивайте пути маской префикса приложения: `secret/data/{{identity.entity.aliases.auth_kubernetes_...}}/*` или отдельными политиками.
- **Обязательный mTLS и проверка CA:** В корпоративных сетях всегда передавайте `VAULT_CACERT`. Отключение проверки сертификатов (`VAULT_SKIP_VERIFY=true`) в продакшене категорически запрещено.
- **Сетевой карантин Redis:** Доступ к порту 6379 должен быть разрешен исключительно подам `argocd-repo-server`, `argocd-application-controller` и `argocd-server`.
- **Защита Root Filesystem:** Sidecar-контейнеры должны работать с параметрами `readOnlyRootFilesystem: true`, `runAsNonRoot: true` и полным сбросом привилегий `capabilities: drop: ["ALL"]`.

### Надежность и SRE (Reliability & Observability)
- **Метрики CMP в Prometheus:** Отслеживайте гистограмму `argocd_cmp_generate_duration_seconds_bucket` для своевременного обнаружения деградации сетевых ответов от Vault.
- **Ограничение ресурсов:** Задавайте жесткие лимиты памяти (`limits.memory`) для sidecar-контейнеров плагина, так как разбор объемных манифестов Helm/Kustomize в памяти может приводить к OOMKilled.
- **Мониторинг доступности Vault:** Сбой кластера Vault блокирует процедуру Sync в Argo CD. Настройте синтетический мониторинг эндпоинта `/v1/sys/health` сервера Vault с алертом на `is_sealed: true`.

---

## Ограничения и граничные случаи (Edge Cases)

1. **Несовместимость с Source Hydrator (Argo CD v3.x):** Механизм Source Hydrator в современных версиях Argo CD фиксирует отрендеренные манифесты обратно в Git-ветку аудита. Использование AVP совместно с гидрацией недопустимо, так как расшифрованные пароли будут закоммичены в репозиторий.
2. **Многострочные секреты (TLS-сертификаты и SSH-ключи):** При подстановке RSA-ключей с переносами строк используйте фильтр base64 (`<path:secret#key | base64>`) с размещением в поле `data`, а не `stringData`, чтобы избежать нарушения синтаксиса отступов YAML.
3. **Поведение при недоступности Vault:** Если Vault возвращает ошибку 500/503 или недоступен по сети, генерация CMP завершается с ненулевым exit code. Argo CD помечает приложение статусом `SyncFailed`. При этом **работающие поды в Kubernetes не перезапускаются и продолжают функционировать со старыми секретами**.
4. **Конфликт версий движков KV v1 и KV v2:** Если в Vault используются оба движка на разных путях, убедитесь, что параметр `AVP_PATH_VERSION` соответствует целевому пути, иначе запросы к KV v1 по формату `data/` завершатся ошибкой `404`.

---

## Дополнительная информация

- [Управление секретами в GitOps](../secrets_encryption.md) — базовые модели шифрования в Git, сравнение SOPS, Sealed Secrets и Vault.
- [Расширение через Custom Tooling (CMP v2)](./argocd_custom_tooling.md) — детальная архитектура Config Management Plugins v2, передача параметров и изоляция sidecar.
- [Интеграция Vault с Kubernetes](../../Vault/guides/vault_kubernetes_integration.md) — настройка StatefulSet Vault на базе Raft, Kubernetes Auth и политик доступа.
- [Харденинг и безопасность Argo CD](./argocd_security_hardening.md) — NetworkPolicies, изоляция Redis, mTLS и защита контроллеров.
- [Диагностика и мониторинг Argo CD](./argocd_troubleshooting_and_monitoring.md) — анализ метрик, отладка контроллеров и управление кэшем Redis.
- [Внешние менеджеры секретов в Kubernetes](../../Kubernetes/Base/secrets/external_managers.md) — развертывание и эксплуатация External Secrets Operator (ESO) и VSO.
- [RBAC — модель доступа](./argocd_rbac_deep.md) — разграничение прав доступа команд к приложениям Argo CD.
