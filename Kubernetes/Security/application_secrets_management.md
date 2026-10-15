# Управление секретами и конфигурациями приложений

## Определения

- **Secret**: Объект Kubernetes для хранения конфиденциальных данных (пароли, токены, ключи API). Данные кодируются в base64, но по умолчанию **не шифруются** в etcd. Для реальной защиты необходимо включить [Encryption at Rest](../Base/secrets/etcd_storage.md).
- **ConfigMap**: Ресурс для хранения несекретных конфигураций (URL, порты, настройки приложений). Позволяет отделить параметры запуска от кода и образа контейнера. Данные также хранятся в etcd без шифрования по умолчанию.
- **initContainer**: Вспомогательный контейнер, завершающий работу до старта основного приложения. Идеален для подготовки конфигов из шаблонов, миграции БД, загрузки зависимостей.
- **Native Sidecar Container (K8s 1.28+)**: Sidecar-контейнеры с собственным жизненным циклом (`restartPolicy: Always` внутри `initContainers`), работающие на протяжении всей жизни пода. Используются для динамического обновления секретов, проксирования, мониторинга.
- **Secrets Store CSI Driver**: Механизм монтирования секретов из внешних хранилищ (Vault, AWS KMS, Azure Key Vault) напрямую в файловую систему пода как tmpfs-том. Секреты никогда не попадают в etcd.
- **Vault Secrets Operator (VSO)**: Современный оператор для синхронизации секретов из HashiCorp Vault в нативные объекты `Secret` Kubernetes с поддержкой автоматической ротации.
- **Immutable Secrets/ConfigMaps**: Ресурсы с `immutable: true`. Запрещают изменение данных, снижают нагрузку на `kube-apiserver` (kubelet не опрашивает их на предмет изменений) и предотвращают случайные ошибки при обновлении.
- **envFrom**: Механизм инъекции всех ключей из ConfigMap/Secret в переменные окружения контейнера за один раз (вместо поштучного `valueFrom`).
- **Projected Volume**: Тип тома, объединяющий несколько секретов/configmap'ов в одну точку монтирования с возможностью задать права доступа и порядок обновления.
- **SecretProviderClass**: CRD для CSI Driver, описывающий какие секреты брать из внешнего хранилища и как их монтировать (имена файлов, permissions, синхронизация с K8s Secret).

**Важно:** Этот документ описывает паттерны *доставки* и *потребления* секретов приложениями. Для стратегий хранения в Git см. [Sealed Secrets](./sealed_secrets_overview.md) или [SOPS](../../Security/Tools/sops_overview.md).

## Основные концепции

### Модели доставки секретов

Проблема "секретов в коде" решается разделением ответственности между инфраструктурой и приложением. Существует три основных подхода:

#### 1. Модель синхронизации (Push/Pull)

Внешний оператор (ESO, VSO) считывает данные из внешнего хранилища и создает нативный `Secret` в Kubernetes.
- **Плюсы**: Приложению не нужны специальные библиотеки; стандартная работа через `env` или `volume`.
- **Минусы**: Секреты хранятся в etcd (нужно шифрование etcd); администраторы кластера могут их прочитать; задержка синхронизации (ESO poll interval).

#### 2. Модель прямого монтирования (CSI)

Секреты монтируются напрямую из внешнего хранилища в память пода (tmpfs).
- **Плюсы**: Секреты никогда не попадают в etcd и API Kubernetes; максимальная безопасность.
- **Минусы**: Сложнее в настройке; требует установки CSI-драйверов на узлы; обновление секрета требует перезапуска пода (CSI v1.6+ поддерживает `RequiresRepublish` для автоматического обновления файлов).

#### 3. Модель конфигурации в Pod (initContainer + volume)

Секреты передаются через `env` или `volume`, а `initContainer` генерирует финальный конфиг из шаблона.
- **Плюсы**: Простота; не требует внешних зависимостей; работает в любом кластере.
- **Минусы**: Секреты хранятся в etcd; при обновлении Secret нужен перезапуск Pod (если не используется projected volume с auto-update).

### Паттерн динамической генерации

Если приложение ожидает специфический формат файла (например, `.ini` или `.properties`) с подставленными секретами, используется `initContainer` для генерации финального конфига из шаблона. Финальный конфиг хранится в `emptyDir` с `medium: Memory` (tmpfs), что исключает запись секретов на диск.

### Механизмы доступа приложения к секретам

| Механизм | Способ обновления | Когда использовать |
| :--- | :--- | :--- |
| `env` / `valueFrom` | Перезапуск Pod | Простые приложения,一次性 конфигурации |
| `envFrom` | Перезапуск Pod | Все ключи из Secret/ConfigMap как ENV |
| `volume` (Secret/ConfigMap) | kubelet auto-update (период) | Приложения, читающие файлы конфигурации |
| `projected volume` | kubelet auto-update (период) | Несколько секретов/configmap'ов в одной точке |
| CSI Driver | depends (file refresh или Pod restart) | Внешние хранилища, max безопасность |
| Native Sidecar (1.28+) | Бесконечный цикл обновления | Динамические секреты, Vault Agent |

## Практические сценарии

### Сценарий 1: Базовое использование Secret и ConfigMap

```bash
# Создание Secret из literals
kubectl create secret generic my-db-creds \
  --from-literal=username=admin \
  --from-literal=password='S3cr3tP@ss'

# Создание Secret из YAML
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: my-api-key
  namespace: default
type: Opaque
data:
  api_key: c2VjcmV0LWFwaS1rZXk=   # echo -n 'secret-api-key' | base64
  endpoint: aHR0cHM6Ly9hcGkuZXhhbXBsZS5jb20=
EOF

# Создание ConfigMap
kubectl create configmap app-config \
  --from-literal=LOG_LEVEL=info \
  --from-literal=MAX_CONNECTIONS=100

# Использование в Pod
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: app-with-secrets
spec:
  containers:
  - name: app
    image: my-app:latest
    envFrom:
    - configMapRef:
        name: app-config
    - secretRef:
        name: my-db-creds
    env:
    - name: API_KEY
      valueFrom:
        secretKeyRef:
          name: my-api-key
          key: api_key
    - name: API_ENDPOINT
      valueFrom:
        secretKeyRef:
          name: my-api-key
          key: endpoint
EOF
```

**Проверка:**
```bash
kubectl exec app-with-secrets -- env | grep -E "(LOG_LEVEL|username|password|API_KEY)"
# → LOG_LEVEL=info
# → username=admin
# → password=S3cr3tP@ss
# → API_KEY=secret-api-key
```

### Сценарий 2: Монтирование Secret/ConfigMap как файл

```bash
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: app-with-volume-secrets
spec:
  containers:
  - name: app
    image: nginx:alpine
    volumeMounts:
    - name: db-creds
      mountPath: /etc/secrets/db
      readOnly: true
    - name: app-config
      mountPath: /etc/config
      readOnly: true
    - name: tls-certs
      mountPath: /etc/tls
      readOnly: true
  volumes:
  - name: db-creds
    secret:
      secretName: my-db-creds
      defaultMode: 0400    # Только чтение для владельца
  - name: app-config
    configMap:
      name: app-config
  - name: tls-certs
    secret:
      secretName: my-tls-cert
      items:
      - key: tls.crt
        path: server.crt
      - key: tls.key
        path: server.key
      defaultMode: 0400
EOF
```

**Проверка:**
```bash
kubectl exec app-with-volume-secrets -- ls -la /etc/secrets/db/
# → total 0
# → drwxr-xr-x ... .
# → drwxr-xr-x ... ..
# → -r-------- ... password
# → -r-------- ... username

kubectl exec app-with-volume-secrets -- cat /etc/secrets/db/username
# → admin
```

### Сценарий 3: Генерация конфига через `envsubst` (Рекомендуемый для шаблонов)

Использование `envsubst` (пакет `gettext`) позволяет элегантно подставлять переменные окружения в шаблон.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  initContainers:
  - name: config-builder
    image: alpine:3.18
    command: ['sh', '-c']
    args:
      - apk add --no-cache gettext && envsubst < /tmpl/config.yaml.tmpl > /config/config.yaml
    envFrom:
    - secretRef:
        name: my-db-crets
    volumeMounts:
    - name: template-vol
      mountPath: /tmpl
    - name: config-vol
      mountPath: /config
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: config-vol
      mountPath: /app/config
  volumes:
  - name: template-vol
    configMap:
      name: app-config-template
  - name: config-vol
    emptyDir:
      medium: Memory # Важно: храним секрет только в RAM
```

**Пример шаблона ConfigMap:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config-template
data:
  config.yaml.tmpl: |
    database:
      host: ${DB_HOST}
      port: ${DB_PORT}
      username: ${username}
      password: ${password}
    logging:
      level: ${LOG_LEVEL}
```

### Сценарий 4: Native Sidecar для динамического обновления секретов (K8s 1.28+)

Для приложений, требующих динамического обновления секретов без перезагрузки:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-dynamic-secrets
spec:
  initContainers:
  - name: vault-agent
    image: hashicorp/vault-agent:latest
    restartPolicy: Always # Делает контейнер sidecar-ом
    args: ["agent", "-config=/etc/vault/config.hcl"]
    env:
    - name: VAULT_ADDR
      value: "http://vault.vault.svc:8200"
    volumeMounts:
    - name: config-vol
      mountPath: /app/config
    - name: vault-token
      mountPath: /var/run/secrets/vault
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: config-vol
      mountPath: /app/config
  volumes:
  - name: config-vol
    emptyDir:
      medium: Memory
  - name: vault-token
    emptyDir:
      medium: Memory
```

### Сценарий 5: Secrets Store CSI Driver (Максимальная безопасность)

Этот метод исключает создание `Secret` в Kubernetes. Приложение видит секреты как файлы в `/mnt/secrets-store`.

```bash
# Установка CSI Driver
helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts
helm install csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver \
  --namespace kube-system \
  --set rotation.enabled=true \
  --set rotation.pollInterval=2m
```

```yaml
# SecretProviderClass: описывает, что и откуда брать
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vault-db-creds
  namespace: default
spec:
  provider: vault
  parameters:
    roleName: "my-app"
    vaultAddress: "http://vault.vault.svc:8200"
    objects: |
      - objectName: "db-password"
        secretPath: "secret/data/myapp/db"
        secretKey: "password"
  secretObjects:
  - secretName: vault-db-creds-sync
    type: Opaque
    data:
    - objectName: db-password
      key: password
---
# Pod с монтированием
apiVersion: v1
kind: Pod
metadata:
  name: app-with-csi-secrets
spec:
  serviceAccountName: my-app
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: secrets-store-inline
      mountPath: "/mnt/secrets-store"
      readOnly: true
  volumes:
    - name: secrets-store-inline
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: "vault-db-creds"
```

> Подробнее: [Внешние менеджеры секретов](../Base/secrets/external_managers.md)

### Сценарий 6: Projected Volume для объединения нескольких секретов

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-projected-secrets
spec:
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: combined-secrets
      mountPath: /etc/secrets
      readOnly: true
  volumes:
  - name: combined-secrets
    projected:
      defaultMode: 0400
      sources:
      - secret:
          name: my-db-creds
          items:
          - key: username
            path: db/username
          - key: password
            path: db/password
      - configMap:
          name: app-config
          items:
          - key: LOG_LEVEL
            path: config/log_level
      - secret:
          name: my-tls-cert
          items:
          - key: tls.crt
            path: tls/server.crt
          - key: tls.key
            path: tls/server.key
      - downwardAPI:
          items:
          - path: "labels"
            fieldRef:
              fieldPath: metadata.labels
```

### Сценарий 7: Иммутабельные Secret/ConfigMaps

Для ресурсов, которые не должны меняться в течение жизненного цикла пода:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-immutable-secret
  namespace: production
type: Opaque
immutable: true
data:
  api_key: c2VjcmV0LWtleQ==
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-immutable-config
  namespace: production
immutable: true
data:
  APP_VERSION: "2.1.0"
  FEATURE_FLAGS: "enable-new-ui,enable-dark-mode"
```

**Проверка:**
```bash
# Попытка обновленияimmutable ресурса — ошибка
kubectl patch secret my-immutable-secret -n production -p '{"data":{"api_key":"bmV3LXZhbHVl"}}'
# → Error: the object has been modified; please apply your changes to the latest version

# Просмотр статуса immutability
kubectl get secret my-immutable-secret -n production -o jsonpath='{.immutable}'
# → true
```

### Сценарий 8: Helm Secrets для безопасного хранения в Git

Для использования в Helm-чартах. Подробное руководство по интеграции helm-secrets с SOPS, паттерну `existingSecret` и лучшим практикам см. в [Helm + секреты](../../Base/secrets/helm_secrets.md).

```bash
# Установка helm-secrets плагина
helm plugin install https://github.com/jkroepke/helm-secrets

# Шифрование секретного файла
sops --encrypt --age age1... secrets.yaml > secrets.enc.yaml

# Деплой с расшифровкой
helm secrets upgrade --install my-release ./chart \
  -f values.yaml \
  -f secrets://secrets.enc.yaml
```

**Структура Helm-чарта:**
```
chart/
  templates/
    deployment.yaml
  values.yaml
  secrets.yaml          # ← зашифрованный (не коммитить!)
  secrets.enc.yaml      # ← зашифрованный версия (коммитить)
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в статусе `CreateContainerConfigError`** | Secret или ConfigMap не найден, или ключ в `secretKeyRef` не существует | `kubectl describe pod <pod>` → проверьте Events. Убедитесь, что Secret существует: `kubectl get secret <name>`. Проверьте ключ: `kubectl get secret <name> -o jsonpath='{.data}'`. |
| **Pod в статусе `ImagePullBackOff` + `CreateContainerConfigError`** | secretRef ссылается на несуществующий Secret | Создайте Secret заново или проверьте имя в манифесте. |
| **Значение переменной окружения пустое** | Неправильное имя ключа в `secretKeyRef` | Проверьте ключи: `kubectl get secret <name> -o jsonpath='{.data}' \| base64 -d`. |
| **CSI Driver: том пуст** | Ошибка в `SecretProviderClass` или нет доступа к хранилищу | `kubectl describe pod` → проверьте `FailedMount` события. Проверьте логи CSI-драйвера: `kubectl logs -n kube-system ds/csi-secrets-store`. |
| **CSI Driver: `SecretProviderClassNotFound`** | CRD не установлен или имя неправильное | Установите CSI Driver: `kubectl get crd secretproviderclasses.secrets-store.csi.x-k8s.io`. |
| **Обновление Secret не отражается в Pod** | Приложение не перечитывает файлы | Используйте projected volume с `auto` update или native sidecar для динамического обновления. |
| **Ошибка `etcd key not found`** | Секрет удален из etcd, но Pod все еще ссылается | Восстановите Secret из бэкапа или пересоздайте Pod. |
| **Pod не может прочитать файл в volume** | Неправильные права доступа (permissions) | Установите `defaultMode: 0400` в volume или используйте `fsGroup` в `securityContext`. |
| **Secret не синхронизируется из Vault** | ESO/VSO не может подключиться к Vault | Проверьте `kubectl describe externalsecret <name>`. Убедитесь, что `ClusterSecretStore` доступен. |
| **`immutable: true` блокирует обновление** | Ресурс помечен как immutable | Удалите и пересоздайте ресурс (это необратимая операция). |

### Диагностические команды

```bash
# Просмотр всех Secret в namespace
kubectl get secrets -n <namespace>

# Просмотр содержимого Secret (base64)
kubectl get secret <name> -o jsonpath='{.data}' | base64 -d

# Просмотр событий Pod (выявляет ошибки монтирования)
kubectl describe pod <pod-name> | grep -A5 Events

# Проверка CSI SecretProviderClassPodStatus
kubectl get secretproviderclasspodstatus -n <namespace>

# Проверка ExternalSecret статуса
kubectl get externalsecret -n <namespace> -o wide
kubectl describe externalsecret <name>

# Список всех ExternalSecrets со статусом готовности
kubectl get externalsecret -A

# Компактная таблица всех ExternalSecrets с состоянием синхронизации
kubectl get externalsecrets -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,STORE:.spec.secretStoreRef.name,READY:.status.conditions[0].status'

# Статус синхронизации ExternalSecret (условия Ready, SecretSynced)
kubectl get externalsecret <name> -n <ns> -o jsonpath='{.status.conditions[*]}'

# Принудительная синхронизация через обновление аннотации
kubectl annotate externalsecret <name> -n <ns> force-sync=$(date +%s) --overwrite

# Статус SecretStore и ClusterSecretStore
kubectl get secretstore,clustersecretstore -A -o wide
kubectl get clustersecretstore

# Просмотр шаблонизации значений в spec ExternalSecret
kubectl get externalsecret <name> -n <ns> -o yaml | grep -A10 'template:'

# Просмотр логов CSI-драйвера
kubectl logs -n kube-system ds/csi-secrets-store

# Проверка RBAC для Secret
kubectl auth can-i get secret <name> --as=system:serviceaccount:<ns>:<sa-name>

# Проверка, что Secret существует и содержит нужные ключи
kubectl get secret <name> -o jsonpath='{.data.<key>}' | base64 --decode
```

## Безопасность и лучшие практики

### RBAC и минимальные привилегии

```yaml
# Пример Role, разрешающей доступ только к конкретному Secret
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: secret-reader
  namespace: production
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["my-app-creds"]
  verbs: ["get"]
---
# Пример RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: secret-reader-binding
  namespace: production
subjects:
- kind: ServiceAccount
  name: my-app-sa
  namespace: production
roleRef:
  kind: Role
  name: secret-reader
  apiGroup: rbac.authorization.k8s.io
```

### Проверка доступа

```bash
# Проверка прав ServiceAccount к конкретному Secret
kubectl auth can-i get secret my-app-creds \
  --as=system:serviceaccount:production:my-app-sa \
  -n production
# → yes

# Проверка, что SA не имеет лишних прав
kubectl auth can-i list secrets --as=system:serviceaccount:production:my-app-sa -n production
# → no
```

### Рекомендации по безопасности

1. **RBAC**: Ограничивайте доступ к объектам `Secret`. Только ServiceAccount, от имени которого работает под, должен иметь права `get` на нужные секреты. См. [RBAC](./rbac/rbac_overview.md).
2. **Memory-backed emptyDir**: Всегда используйте `medium: Memory` для томов, содержащих временные файлы с секретами. Это предотвращает утечку данных на диск (особенно на HDD/SSD без шифрования).
3. **Immutable ресурсы**: Если конфигурация или секрет не должны меняться в течение жизненного цикла пода, установите `immutable: true`. Это защищает от случайных изменений и снижает нагрузку на API.
4. **Security Context**:
   - `runAsNonRoot: true`: Запускайте контейнеры от не-привилегированных пользователей.
   - `fsGroup`: Используйте для предоставления прав на чтение томов с секретами определенной группе пользователей.
   - `readOnlyRootFilesystem: true`: Рекомендуется для минимизации поверхности атаки.
5. **Избегайте `kubectl create secret` в CI/CD**: Используйте declarative подходы (Sealed Secrets, SOPS, ESO, CSI Driver) вместо императивных команд.
6. **Не коммитьте секреты в Git в открытом виде**: Используйте шифрование (Sealed Secrets, SOPS) или внешние хранилища (Vault, ESO).
7. **Ротация секретов**: Регулярно обновляйте пароли и токены. Используйте автоматическую ротацию через ESO/VSO или CSI Driver (RequiresRepublish).
8. **Мониторинг**: Отслеживайте события `FailedMount` и ошибки CSI-драйвера через Prometheus (метрики `csi_seconds`).

## Дополнительная информация

### См. также
- **[Основы Kubernetes Secret](../Base/secrets/secrets_basics.md)** — типы и базовое использование.
- **[Хранение Secret в etcd](../Base/secrets/etcd_storage.md)** — шифрование etcd (Encryption at Rest) и бэкапы.
- **[Внешние менеджеры секретов](../Base/secrets/external_managers.md)** — детали работы ESO и CSI Driver.
