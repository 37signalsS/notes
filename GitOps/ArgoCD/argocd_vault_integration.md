# Интеграция Argo CD и HashiCorp Vault: Argo CD Vault Plugin

> **Актуальность (2026):** Argo CD Vault Plugin (AVP) по-прежнему используется для проектов с глубокой кастомизацией манифестов на лету. Однако отраслевым стандартом 2026 года для Kubernetes-native сред являются **External Secrets Operator (ESO)** и официальный **Vault Secrets Operator (VSO)**. Основная причина — архитектурные риски AVP, связанные с кэшированием секретов в Redis. Подробнее см. раздел [Безопасность и современные альтернативы](#безопасность-и-современные-альтернативы-2026).

## Предварительные требования

1. **ArgoCD v2.4+:** CMP v2 поддерживается начиная с v2.4. Рекомендуется v2.8+ для полной функциональности AVP.
2. **HashiCorp Vault:** Установленный и доступный экземпляр Vault (v1.13+).
3. **KV Secrets Engine v2:** Активированный и настроенный KV v2 на пути `secret/`.
4. **Kubernetes Auth Method:** Настроенный метод аутентификации в Vault для ServiceAccount `argocd-repo-server`.
5. **Доступ к `argocd-repo-server`:** Права на модификацию Deployment (kubectl edit/deploy).
6. **Kubernetes v1.20+:** Требуется для работы с Kubernetes Auth Method в Vault 1.9+.

## Определения

**Argo CD Vault Plugin (AVP)** — плагин управления конфигурациями (Config Management Plugin), предназначенный для динамической подстановки секретных данных из внешних хранилищ (Vault, AWS Secrets Manager, GCP Secret Manager, Azure Key Vault) в манифесты Kubernetes непосредственно в момент их рендеринга на стороне Argo CD.

**HashiCorp Vault** — централизованная система управления секретами, обеспечивающая их безопасное хранение, аудит доступа и динамическую генерацию учетных данных.

**CMP v2 (Config Management Plugin)** — современный механизм расширения Argo CD (начиная с v2.4), использующий sidecar-контейнеры в поде `argocd-repo-server` для выполнения логики генерации манифестов в изолированном окружении.

**App-of-Apps** — паттерн проектирования в Argo CD, при котором одно «корневое» приложение управляет жизненным циклом множества дочерних приложений (включая специализированные «приложения с секретами»).

**Secret Zero (Проблема первого секрета)** — проблема безопасной доставки первичных учетных данных (токена или ключа), необходимых для первоначальной аутентификации во внешнем хранилище.

**Kubernetes Auth Method** — метод аутентификации в Vault, позволяющий подам Kubernetes аутентифицироваться через ServiceAccount Token без передачи секретов.

**AppRole Auth Method** — метод аутентификации в Vault через RoleID и SecretID, подходящий для CI/CD систем и автоматизации.

**Dynamic Secrets** — временные учетные данные, автоматически генерируемые Vault для конкретного приложения с ограниченным временем жизни.

## Базовые концепции

### Проблема хранения секретов в GitOps

В классическом GitOps манифесты хранятся в Git. Поскольку стандартные секреты Kubernetes используют только кодирование Base64, их хранение в репозиториях без шифрования (например, через SOPS или Sealed Secrets) является критическим нарушением безопасности.

**Argo CD Vault Plugin** позволяет хранить в Git только шаблоны (плейсхолдеры). Реальные значения подставляются только в оперативной памяти компонента `argocd-repo-server` перед отправкой манифестов в API Kubernetes.

### Архитектура и механизм работы (CMP v2)

Плагин функционирует как sidecar-контейнер в поде `argocd-repo-server`:

```
┌─────────────────────────────────────────────────────────────────────┐
│          CMP v2: Архитектура AVP                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  argocd-repo-server Pod                                      │  │
│  │  ┌──────────────────┐  ┌──────────────────┐                │  │
│  │  │  repo-server     │  │  AVP Sidecar     │                │  │
│  │  │  (main container)│◀▶│  (CMP v2)        │                │  │
│  │  │  - git clone      │  │  - argocd-vault- │                │  │
│  │  │  - manifest       │  │    plugin         │                │  │
│  │  │    rendering      │  │  - Vault Auth     │                │  │
│  │  └──────────────────┘  └──────────────────┘                │  │
│  │         │                       │                            │  │
│  │         ▼                       ▼                            │  │
│  │  ┌──────────────────────────────────────┐                  │  │
│  │  │  /var/run/argocd (shared volume)     │                  │  │
│  │  │  - UNIX socket for communication     │                  │  │
│  │  │  - Generated manifests (YAML)        │                  │  │
│  │  └──────────────────────────────────────┘                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│                          ┌──────────┐                               │
│                          │  Vault   │                               │
│                          │  Server  │                               │
│                          └──────────┘                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

1.  **Загрузка (Fetch):** Argo CD получает манифесты из Git-репозитория.
2.  **Обнаружение (Discovery):** CMP-сервер сканирует файлы по заданным правилам (например, наличие специфической аннотации `avp.kubernetes.io/path` или совпадение имени файла).
3.  **Аутентификация:** Плагин аутентифицируется в Vault (обычно через Kubernetes Auth Method).
4.  **Рендеринг (Generate):** Плагин запрашивает секреты, заменяет теги на реальные значения и возвращает готовый YAML.
5.  **Применение (Apply):** Argo CD применяет итоговые манифесты. Секреты попадают в кластер, минуя Git.

### Методы аутентификации AVP

| Метод | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Kubernetes Auth** | Аутентификация через ServiceAccount Token | Рекомендуется для Kubernetes кластеров |
| **AppRole** | RoleID + SecretID | CI/CD системы, внешние серверы |
| **Token** | Статический токен | Тестирование, Development |
| **IAM (AWS)** | AWS IAM Roles | AWS инфраструктура |
| **GCP Auth** | GCP IAM | Google Cloud инфраструктура |

### Теги и плейсхолдеры AVP

| Синтаксис | Описание | Пример |
| :--- | :--- | :--- |
| `<key>` | Значение по ключу из аннотации | `<password>` |
| `<path#key>` | Явный путь и ключ | `<secret/data/db#pass>` |
| `<path:key>` | Альтернативный синтаксис | `<secret/data/db:pass>` |
| `<env:VAR>` | Значение переменной окружения | `<env:VAULT_ADDR>` |

## Практические сценарии

### Сценарий 1: Подготовка HashiCorp Vault

Прежде чем Argo CD сможет запрашивать секреты, необходимо настроить Vault.

**1. Активация KV-хранилища:**
```bash
# Включение хранилища Key-Value версии 2
vault secrets enable -path=secret kv-v2

# Создание тестового секрета
vault kv put secret/data/myapp/config user="admin" password="super-secret-password"
```

**2. Создание политики доступа (myapp-policy.hcl):**
```hcl
path "secret/data/myapp/*" {
  capabilities = ["read"]
}
```
Примените политику: `vault policy write myapp-policy myapp-policy.hcl`

**3. Настройка аутентификации Kubernetes:**
```bash
# Включение метода аутентификации
vault auth enable kubernetes

# Настройка связи с API Kubernetes
vault write auth/kubernetes/config \
    issuer="https://kubernetes.default.svc.cluster.local" \
    token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
    kubernetes_host="https://$KUBERNETES_PORT_443_TCP_ADDR:443" \
    kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt

> **Важный нюанс:** Параметр `issuer` стал обязательным начиная с Vault 1.9.0 для работы с Kubernetes 1.20+. Без него аутентификация может возвращать ошибку `claim "iss" is invalid`.

# Создание роли для Argo CD
vault write auth/kubernetes/role/argocd-role \
    bound_service_account_names=argocd-repo-server \
    bound_service_account_namespaces=argocd \
    policies=myapp-policy \
    ttl=24h
```

**4. Проверка доступа:**
```bash
# Имитация токена из пода
kubectl exec -n argocd deployment/argocd-repo-server -- \
  cat /var/run/secrets/kubernetes.io/serviceaccount/token > /tmp/sa-token

# Тестирование аутентификации
vault write auth/kubernetes/login \
    role=argocd-role \
    jwt=@/tmp/sa-token

# → Должен вернуть token и policies
```

### Сценарий 2: Конфигурация Argo CD (CMP v2)

В современных версиях Argo CD плагин настраивается через sidecar.

**1. Создание ConfigMap с описанием плагина:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: avp-cmp-config
  namespace: argocd
data:
  plugin.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata:
      name: argocd-vault-plugin
    spec:
      discover:
        fileName: ".*\\.yaml$"
        annotation: "avp.kubernetes.io/path"
      generate:
        command: ["argocd-vault-plugin"]
        args: ["generate", "-s", "avp-config"]
      allowConcurrency: true
      lockRepo: false
```

**Параметры plugin.yaml:**
- `discover.fileName` — регулярное выражение для поиска файлов плагина
- `discover.annotation` — аннотация, активирующая плагин для конкретного ресурса
- `generate.command` — команда генерации манифестов
- `generate.args` — аргументы команды (`-s avp-config` указывает источник конфигурации)
- `allowConcurrency` — разрешить параллельную обработку (рекомендуется true)
- `lockRepo` — блокировать репозиторий во время генерации (false для производительности)

**2. Обновление Deployment `argocd-repo-server`:**
Необходимо добавить sidecar-контейнер и init-контейнер для скачивания бинарного файла плагина.

```yaml
spec:
  template:
    spec:
      containers:
      - name: avp
        command: [/var/run/argocd/argocd-cmp-server]
        image: argoproj/argocd:v2.10.0 # Версия должна соответствовать Argo CD
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
            cpu: 200m
            memory: 256Mi
          requests:
            cpu: 100m
            memory: 128Mi
        env:
          - name: ARGOCD_EXEC_TIMEOUT
            value: "60s"
        volumeMounts:
        - name: var-run-argocd
          mountPath: /var/run/argocd
        - name: plugins
          mountPath: /home/argocd/cmp-server/plugins
        - name: custom-tools
          mountPath: /usr/local/bin/argocd-vault-plugin
          subPath: argocd-vault-plugin
        - name: tmp
          mountPath: /tmp
        readinessProbe:
          exec:
            command: [ls, /var/run/argocd/argocd-cmp-server.socket]
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          exec:
            command: [ls, /var/run/argocd/argocd-cmp-server.socket]
          initialDelaySeconds: 10
          periodSeconds: 30
      
      initContainers:
      - name: download-tools
        image: alpine:latest
        command: [sh, -c]
        args:
          - wget -O /custom-tools/argocd-vault-plugin https://github.com/argoproj-labs/argocd-vault-plugin/releases/download/v1.18.1/argocd-vault-plugin_linux_amd64 && chmod +x /custom-tools/argocd-vault-plugin
        volumeMounts:
        - name: custom-tools
          mountPath: /custom-tools
      
      volumes:
      - name: custom-tools
        emptyDir: {}
      - name: tmp
        emptyDir: {}
```

**Параметры безопасности:**
- `runAsUser: 999` — запуск от непривилегированного пользователя (UID 999)
- `readOnlyRootFilesystem: true` — доступ только к необходимым томам
- `capabilities: drop: ["ALL"]` — сброс всех Linux capabilities
- `allowPrivilegeEscalation: false` — запрет повышения привилегий
- `resources.limits` — ограничение потребления ресурсов
- `readinessProbe/livenessProbe` — проверка готовности и работоспособности sidecar

### Сценарий 3: Использование плагина в манифестах

**1. Обычный YAML (через аннотации):**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-app-secret
  annotations:
    avp.kubernetes.io/path: "secret/data/myapp/config"
type: Opaque
stringData:
  username: <user>
  password: <password>
```

**2. Helm Charts (в values.yaml):**
В файле `values.yaml` можно использовать полный путь:
```yaml
db:
  pass: <path:secret/data/myapp/config#password>
```

**3. Синтаксис тегов:**
- `<key>` — подстановка значения по ключу из пути, указанного в аннотации.
- `<path#key>` — явное указание пути и ключа в одном теге.
- `<path:key>` — альтернативный синтаксис (двоеточие вместо #).
- `<env:VAR>` — подстановка значения переменной окружения.

**4. Валидация шаблонов:**
```bash
# Локальная проверка (без подключения к Vault)
argocd-vault-plugin generate ./manifests/

# С指定 переменными окружения
AVP_KV_VERSION=2 VAULT_ADDR=http://vault:8200 \
  argocd-vault-plugin generate ./manifests/
```

### Сценарий 4: Настройка объекта Application

Для активации плагина необходимо указать его имя и передать переменные окружения.

```yaml
spec:
  source:
    path: manifests
    plugin:
      name: argocd-vault-plugin
      env:
        - name: AVP_TYPE
          value: vault
        - name: AVP_AUTH_TYPE
          value: kubernetes
        - name: AVP_K8S_ROLE
          value: argocd-role
        - name: VAULT_ADDR
          value: http://vault.vault.svc:8200
        - name: VAULT_NAMESPACE
          value: "admin" # Для Vault Enterprise
```

### Сценарий 5: Автоматическое обновление подов (Rolling Update)

Argo CD не видит изменений *внутри* Vault. Если пароль изменился в Vault, но манифест в Git не менялся, Argo CD не запустит синхронизацию.
Решение — использование хеширования в аннотациях Deployment.

```yaml
kind: Deployment
spec:
  template:
    metadata:
      annotations:
        # Хеш содержимого секрета. При изменении данных в Vault плагин подставит 
        # новые значения, хеш изменится, что вызовет перезапуск подов.
        checksum/vault-secrets: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
```

### Сценарий 6: Интеграция с AWS Secrets Manager

Для использования AWS Secrets Manager вместо Vault:

```yaml
spec:
  source:
    path: manifests
    plugin:
      name: argocd-vault-plugin
      env:
        - name: AVP_TYPE
          value: aws
        - name: AVP_AUTH_TYPE
          value: iam
        - name: AWS_REGION
          value: us-west-2
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aws-secret
  annotations:
    avp.kubernetes.io/path: "aws/secret/myapp/config"
type: Opaque
stringData:
  api_key: <api_key>
```

**Важно:** IAM-роль ServiceAccount `argocd-repo-server` должна иметь политику `secretsmanager:GetSecretValue` для целевых секретов.

### Сценарий 7: Интеграция с GCP Secret Manager

```yaml
spec:
  source:
    path: manifests
    plugin:
      name: argocd-vault-plugin
      env:
        - name: AVP_TYPE
          value: gcp
        - name: GCP_PROJECT_ID
          value: my-gcp-project
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: gcp-secret
  annotations:
    avp.kubernetes.io/path: "projects/my-gcp-project/secrets/myapp-config/versions/latest"
type: Opaque
stringData:
  password: <password>
```

**Важно:** Workload Identity должен быть настроен для ServiceAccount `argocd-repo-server` с ролью `roles/secretmanager.secretAccessor`.

### Сценарий 8: Интеграция с Azure Key Vault

```yaml
spec:
  source:
    path: manifests
    plugin:
      name: argocd-vault-plugin
      env:
        - name: AVP_TYPE
          value: azurekeyvault
        - name: AZURE_VAULT_NAME
          value: my-keyvault
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: azure-secret
  annotations:
    avp.kubernetes.io/path: "myapp-config"
type: Opaque
stringData:
  connection-string: <connection-string>
```

**Важно:** Managed Identity должен иметь доступ к Key Vault через Azure RBAC (роль `Key Vault Secrets User`).

### Сценарий 9: App-of-Apps с секретами

Паттерн для управления приложениями, требующими секретов:

```
└── root-app (App-of-Apps)
    ├── app-secrets (секреты из Vault)
    ├── app-frontend (без секретов)
    └── app-backend (зависит от app-secrets)
```

**Корневое приложение (root-app):**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root-app
spec:
  source:
    path: apps/root
  destinations:
    - server: https://kubernetes.default.svc
      namespace: argocd
```

**Приложение с секретами (app-secrets):**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: app-secrets
  annotations:
    argocd.argoproj.io/sync-wave: "-10" # Синхронизировать раньше других
spec:
  source:
    path: apps/secrets
    plugin:
      name: argocd-vault-plugin
      env:
        - name: AVP_AUTH_TYPE
          value: kubernetes
        - name: AVP_K8S_ROLE
          value: argocd-role
```

### Сценарий 10: Rollback и откат секретов

При возникновении проблем с секретами:

```bash
# 1. Откат приложения на предыдущую версию
argocd app rollback my-app <revision-number>

# 2. Принудительная синхронизация
argocd app sync my-app --force

# 3. Просмотр изменений
argocd app diff my-app

# 4. Проверка текущих секретов в Vault
vault kv get -version=1 secret/data/myapp/config
```

## Сравнение методов интеграции (2026)

| Критерий | Argo CD Vault Plugin (AVP) | External Secrets Operator (ESO) | Vault Secrets Operator (VSO) |
| :--- | :--- | :--- | :--- |
| **Принцип работы** | Подстановка при рендеринге | Синхронизация в K8s Secret | Нативный контроллер Vault |
| **Где хранятся секреты** | В памяти repo-server + Redis | В etcd (как Secret) | В etcd / Памяти подов |
| **Авто-обновление** | Требует ручного Sync / Хеширования | Автоматическое (polling) | Нативное (Event-driven) |
| **Сложность** | Средняя (CMP v2 sidecar) | Средняя (CRD) | Высокая (Official Operator) |
| **Рекомендация** | Legacy / Сложные шаблоны | **Standard (Production)** | **Enterprise / Vault Native** |
| **Поддержка KV v2** | Да | Да | Да |
| **Динамические секреты** | Ограниченно | Полная | Полная |
| **Multi-tenancy** | Через политики Vault | Через Namespace | Через Namespace |

## Безопасность и современные альтернативы 2026

### Основные риски использования AVP

1.  **Кэширование в Redis:** Argo CD кэширует результат рендеринга (готовый YAML с паролями) в своем Redis. Это означает, что **секреты хранятся в открытом виде в кэше**.
    *   *Решение:* Обязательное шифрование Redis и защита NetworkPolicy.
2.  **Source Hydrator (v3.x):** В Argo CD v3 функция гидрации (hydration), которая сохраняет отрендеренные манифесты в Git для аудита, несовместима с AVP, так как секреты попадут в коммит.
3.  **Отсутствие аудита:** Изменения секретов не отслеживаются через Git history; необходимо настраивать аудит Vault.
4.  **Ограниченная поддержка:** AVP не поддерживает динамические секреты и автоматическую ротацию.

### Рекомендация: External Secrets Operator (ESO) и VSO

В 2026 году ESO и VSO являются предпочтительными решениями.
- **Безопасность:** Секреты никогда не попадают в Argo CD.
- **Нативность:** Использование CRD (`ExternalSecret` или `VaultStaticSecret`), которые безопасно хранить в Git.
- **Автоматизация:** Операторы сами отслеживают изменения в Vault и обновляют секреты без необходимости ручной синхронизации в Argo CD.

**Сравнение решений:**

| Критерий | AVP | ESO | VSO |
| :--- | :--- | :--- | :--- |
| Архитектура | Sidecar в repo-server | Оператор + CRD | Оператор + CRD |
| Безопасность | Секреты в Redis | Только в etcd | Только в etcd |
| Авто-обновление | Нет | Да (polling) | Да (Event-driven) |
| Сложность настройки | Средняя | Средняя | Высокая |

## Технический справочник

### Ключевые переменные окружения AVP

| Переменная | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `AVP_TYPE` | Тип бэкенда (vault, aws, gcp, azurekeyvault) | `vault` |
| `AVP_AUTH_TYPE` | Метод аутентификации (token, kubernetes, approle, iam) | `token` |
| `VAULT_ADDR` | Адрес API Vault | `http://localhost:8200` |
| `AVP_K8S_ROLE` | Роль для Kubernetes Auth | — |
| `VAULT_NAMESPACE` | Пространство имен (для Vault Enterprise) | — |
| `AVP_PATH_VERSION` | Версия KV-хранилища | `latest` |
| `ARGOCD_EXEC_TIMEOUT` | Тайм-аут выполнения команды | `60s` |
| `AVP_ROLE_ID` | RoleID для AppRole Auth | — |
| `AVP_SECRET_ID` | SecretID для AppRole Auth | — |
| `AWS_REGION` | Регион AWS для Secrets Manager | `us-east-1` |
| `GCP_PROJECT_ID` | ID проекта GCP для Secret Manager | — |
| `AZURE_VAULT_NAME` | Имя Azure Key Vault | — |

### Способы установки бинарного файла

1.  **Init-container:** Оптимально для быстрого старта (см. Сценарий 2).
2.  **Custom Image:** Сборка собственного образа `argocd-repo-server`. Рекомендуется для Production.
3.  **Volume Mount:** Монтирование из внешнего тома (NFS, ConfigMap с бинарными данными).
4.  **Helm Chart:** Использование official ArgoCD Helm Chart с параметрами sidecar.

## Диагностика и типичные ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Permission Denied (403)` | ServiceAccount не привязан к роли в Vault | `vault write auth/kubernetes/role/argocd-role ...` |
| `Vault is sealed` | Vault в sealed состоянии | `vault unseal` (проверьте `vault status`) |
| `claim "iss" is invalid` | Отсутствует параметр `issuer` в Vault 1.9+ | Добавьте `issuer="https://kubernetes.default.svc.cluster.local"` |
| `Secrets не обновляются` | Argo CD не видит изменения в Vault | Используйте checksum аннотации или `argocd app sync --force` |
| `Plugin not found` | CMP sidecar не запущен или ошибки в plugin.yaml | Проверьте логи sidecar: `kubectl logs -c avp ...` |
| `Connection refused` | Vault недоступен из кластера | Проверьте NetworkPolicy и доступность Vault |
| `Permission denied (GCP)` | Workload Identity не настроен | Настройте IAM для ServiceAccount |
| `Access denied (AWS)` | IAM-роль не имеет доступа к Secrets Manager | Добавьте политику `secretsmanager:GetSecretValue` |

### Логирование

```bash
# Логи sidecar-контейнера AVP
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -c avp

# Логи repo-server с debug
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -c repo-server

# Проверка plugin.yaml
kubectl exec -it -n argocd deployment/argocd-repo-server -c avp -- \
  cat /home/argocd/cmp-server/config/plugin.yaml

# Ручное тестирование generate
kubectl exec -it -n argocd deployment/argocd-repo-server -c avp -- \
  argocd-vault-plugin generate /tmp/manifests/

# Просмотр переменных окружения
kubectl exec -it -n argocd deployment/argocd-repo-server -c avp -- env

# Проверка регистрации плагина
argocd admin settings repo-server list-plugins --namespace argocd
```

### Валидация конфигурации

```bash
# 1. Проверка доступности Vault
vault status

# 2. Проверка политики
vault policy read myapp-policy

# 3. Проверка роли
vault read auth/kubernetes/role/argocd-role

# 4. Тестирование чтения секрета
vault kv get secret/data/myapp/config

# 5. Проверка ServiceAccount
kubectl get sa argocd-repo-server -n argocd -o yaml
```

## Лучшие практики

### Безопасность
- **Minimal Privileges:** Ограничивайте политики Vault только необходимыми путями.
- **Network Policies:** Ограничьте сетевой доступ AVP sidecar.
- **RBAC:** Используйте отдельные роли Vault для каждого приложения.
- **Secret Rotation:** Регулярно обновляйте секреты в Vault.

### Производительность
- **AllowConcurrency:** Включите параллельную обработку для больших репозиториев.
- **LockRepo:** Отключите блокировку репозитория для производительности.
- **Resources:** Установите appropriate CPU/memory limits для sidecar.

### Надежность
- **Health Checks:** Добавьте liveness/readiness probes для sidecar.
- **Retry Logic:** Реализуйте повторные попытки при временных ошибках.
- **Monitoring:** Настройте алерты на ошибки AVP.

### Безопасность секретов
- **Never Commit Secrets:** Секреты не должны попадать в Git ни в каком виде.
- **Audit Logging:** Включите аудит Vault для отслеживания доступа к секретам.
- **Encryption at Rest:** Шифруйте etcd и Redis в кластере Kubernetes.

## Ограничения и edge cases

### Ограничения

1. **Отсутствие авто-обновления:** AVP не отслеживает изменения секретов в Vault; требуется ручная синхронизация или хеширование.
2. **Кэширование в Redis:** Секреты хранятся в открытом виде в Redis; требуется шифрование.
3. **Source Hydrator v3.x:** Не совместим с функцией гидрации Argo CD v3.
4. **Динамические секреты:** Ограниченная поддержка; рекомендуется ESO или VSO.
5. **Multi-tenancy:** Сложнее настроить чем ESO/VSO; требует отдельных ролей Vault.

### Edge Cases

1. **Конфликт аннотаций:** Если у файла несколько аннотаций AVP, плагин использует первую найденную.
2. **Пустые секреты:** Если ключ не найден в Vault, плагин вернет ошибку; нет fallback.
3. **Версии KV:** Разный синтаксис для KV v1 и KV v2; используйте `AVP_PATH_VERSION`.
4. **Vault Namespace:** Для Enterprise требуется указание `VAULT_NAMESPACE`.
5. **Сеть:** Если Vault недоступен, все рендерения завершаются ошибкой.
6. **Тайм-ауты:** Длинные операции генерации могут превысить `ARGOCD_EXEC_TIMEOUT`.
7. **Helm Dependencies:** При использовании с Helm.chart плагин не обрабатывает dependencies.

## См. также

- [Управление секретами в GitOps](../secrets_encryption.md)
- [Обзор Argo CD: Безопасность](./argocd_overview.md)
- [Интеграция Vault с Kubernetes](../../Vault/guides/vault_kubernetes_integration.md)
- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.
- [Disaster Recovery](./argocd_disaster_recovery.md) — Бэкап, восстановление, etcd snapshot, HA, geo-recovery.
