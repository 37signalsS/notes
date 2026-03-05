# Ошибки конфигурации контейнеров (`CreateContainerConfigError`)

## Определения

**`CreateContainerConfigError`** — ошибка, возникающая до запуска контейнера, означающая, что `kubelet` не может создать конфигурацию контейнера из-за проблем с зависимостями (ConfigMap, Secret, Volume).

> - ConfigMap: [`configmap.md`](../../Base/configmap.md)
> - Secrets: [`external_managers.md`](../../Base/secrets/external_managers.md)
> - Volumes: [`pod_volumes.md`](../../Base/Pod/pod_volumes.md)
> - PVC/PV: [`pv_and_pvc.md`](../../Storage/pv_and_pvc.md)
> - RBAC: [`rbac_overview.md`](../../Security/rbac/rbac_overview.md)

## Основные концепции

### Workflow создания контейнера

```
Pod создан
    ↓
Scheduler выбирает узел
    ↓
Kubelet получает задачу
    ↓
Проверка зависимостей (ConfigMap, Secret, PV)
    ↓
❌ Зависимость не найдена → CreateContainerConfigError
    ↓
✅ Все зависимости есть → Create Container → Start
```

### Типы зависимостей

| Зависимость | Описание | Частая ошибка |
|-------------|----------|---------------|
| **ConfigMap** | Конфигурационные данные | `configmap "x" not found` |
| **Secret** | Секретные данные | `secret "x" not found` |
| **PersistentVolumeClaim** | Постоянное хранилище | `pvc "x" not found` |
| **Projected Volume** | Комбинация источников | `projected volume error` |
| **Downward API** | Метаданные пода | `downward API error` |

## Практические сценарии

### Диагностика: пошаговый чек-лист

#### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в разделе `Events`:**
```
Type     Reason     Age                From               Message
----     ------     ----               ----               -------
Warning  Failed     56s (x6 over 1m)   kubelet            Error: configmap "missing-config" not found
Warning  Failed     56s (x6 over 1m)   kubelet            Error: secret "missing-secret" not found
Warning  Failed     40s (x6 over 1m)   kubelet            Error: persistentvolumeclaim "data-pvc" not found
```

#### Шаг 2: Проверка ConfigMap

```bash
# Проверка существования
kubectl get configmap <configmap-name> -n <namespace>

# Проверка содержимого
kubectl get configmap <configmap-name> -o yaml

# Поиск всех ConfigMap в namespace
kubectl get configmap -n <namespace>
```

#### Шаг 3: Проверка Secret

```bash
# Проверка существования
kubectl get secret <secret-name> -n <namespace>

# Проверка типа
kubectl get secret <secret-name> -o jsonpath='{.type}'

# Проверка ключей
kubectl get secret <secret-name> -o jsonpath='{.data}'
```

#### Шаг 4: Проверка PVC

```bash
# Статус PVC
kubectl get pvc -n <namespace>

# Описание PVC
kubectl describe pvc <pvc-name> -n <namespace>

# Проверка привязки
kubectl get pvc -n <namespace> -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,VOLUME:.spec.volumeName
```

### Распространенные случаи и решения

#### 1. Отсутствует ConfigMap

**Сообщение:**
```
Error: configmap "app-config" not found
```

**Причина:** Pod ссылается на ConfigMap, который не существует в данном namespace.

**Решение:**
```bash
# Создание недостающего ConfigMap
kubectl create configmap app-config \
  --from-literal=key1=value1 \
  --from-literal=key2=value2 \
  -n <namespace>

# Или из файла
kubectl create configmap app-config \
  --from-file=config.yaml=/path/to/config.yaml \
  -n <namespace>
```

**Пример манифеста:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: default
data:
  DATABASE_URL: "postgres://db:5432/mydb"
  LOG_LEVEL: "info"
  config.yaml: |
    server:
      port: 8080
    logging:
      level: info
```

**Использование в Pod:**
```yaml
# Как переменные окружения
envFrom:
- configMapRef:
    name: app-config

# Как отдельные переменные
env:
- name: DATABASE_URL
  valueFrom:
    configMapKeyRef:
      name: app-config
      key: DATABASE_URL

# Как volume (файлы)
volumes:
- name: config
  configMap:
    name: app-config
```

> **См. также:** [`configmap.md`](../../Base/configmap.md)

#### 2. Отсутствует Secret

**Сообщение:**
```
Error: secret "db-credentials" not found
```

**Причина:** Pod ссылается на Secret, который не существует.

**Решение:**
```bash
# Создание Secret
kubectl create secret generic db-credentials \
  --from-literal=username=admin \
  --from-literal=password=SuperSecret123 \
  -n <namespace>

# Создание из файла
kubectl create secret generic tls-secret \
  --from-file=tls.crt=/path/to/cert.pem \
  --from-file=tls.key=/path/to/key.pem \
  --type=kubernetes.io/tls
```

**Пример манифеста:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: default
type: Opaque
data:
  username: YWRtaW4=  # base64
  password: U3VwZXJTZWNyZXQxMjM=
```

**Использование в Pod:**
```yaml
# Как переменные окружения
env:
- name: DB_USERNAME
  valueFrom:
    secretKeyRef:
      name: db-credentials
      key: username

# Как volume
volumes:
- name: secrets
  secret:
    secretName: db-credentials
```

> **См. также:** [`external_managers.md`](../../Base/secrets/external_managers.md), [`rbac_overview.md`](../../Security/rbac/rbac_overview.md)

#### 3. PVC не найден или не привязан

**Сообщение:**
```
Error: persistentvolumeclaim "data-pvc" not found
unable to provision volume: persistentvolumeclaim "data-pvc" not found
```

**Причина:** PVC не существует или находится в статусе `Pending`.

**Диагностика:**
```bash
kubectl describe pvc data-pvc
```

**Возможные причины PVC в Pending:**

| Причина | Решение |
|---------|---------|
| **Нет PV** | Создать PV или настроить StorageClass |
| **Неверный StorageClass** | Проверить: `kubectl get storageclass` |
| **Нехватка места** | Освободить место или увеличить quota |
| **AccessMode несовместим** | Изменить accessMode |

**Решение:**
```yaml
# Создание PVC с StorageClass
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard
  resources:
    requests:
      storage: 10Gi
```

**Создание PV (если нет dynamic provisioning):**
```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: data-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: manual
  hostPath:
    path: "/mnt/data"
```

> **См. также:** [`pv_and_pvc.md`](../../Storage/pv_and_pvc.md), [`csi_drivers_comparison.md`](../../Storage/CSI/csi_drivers_comparison.md)

#### 4. Ключ ConfigMap/Secret не существует

**Сообщение:**
```
configmaps "app-config" not found: key "DATABASE_PASSWORD" not found
secret "db-credentials" not found: key "password" not found
```

**Причина:** ConfigMap/Secret существует, но указанный ключ отсутствует.

**Диагностика:**
```bash
# Проверка ключей ConfigMap
kubectl get configmap app-config -o jsonpath='{.data}'

# Проверка ключей Secret
kubectl get secret db-credentials -o jsonpath='{.data}'
```

**Решение:**
```bash
# Добавление ключа в ConfigMap
kubectl patch configmap app-config \
  -p '{"data":{"DATABASE_PASSWORD":"newpassword"}}'

# Добавление ключа в Secret
kubectl patch secret db-credentials \
  -p '{"data":{"password":"'"$(echo -n 'newpassword' | base64)"'"}}'
```

#### 5. Проблемы с Projected Volume

**Сообщение:**
```
Error: projected volume error: configmap "cm1" not found
```

**Причина:** Projected volume объединяет несколько источников, один из которых отсутствует.

**Решение:**
```yaml
# Проверка всех источников в projected volume
volumes:
- name: all-in-one
  projected:
    sources:
    - configMap:
        name: app-config  # ✅ Существует?
    - secret:
        name: db-credentials  # ✅ Существует?
    - downwardAPI:
        items:
        - path: "labels"
          fieldRef:
            fieldPath: metadata.labels
```

#### 6. Проблемы с правами доступа (RBAC)

**Сообщение:**
```
user "system:serviceaccount:default:default" cannot get resource "configmaps" in API group "" in the namespace "default"
```

**Причина:** У ServiceAccount пода нет прав на чтение ConfigMap/Secret.

**Диагностика:**
```bash
kubectl auth can-i get configmaps \
  --as=system:serviceaccount:default:default \
  -n default
```

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: config-reader
  namespace: default
rules:
- apiGroups: [""]
  resources: ["configmaps", "secrets"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: default-config-reader
  namespace: default
subjects:
- kind: ServiceAccount
  name: default
  namespace: default
roleRef:
  kind: Role
  name: config-reader
  apiGroup: rbac.authorization.k8s.io
```

> **См. также:** [`rbac_overview.md`](../../Security/rbac/rbac_overview.md)

#### 7. Проблемы с томами emptyDir

**Сообщение:**
```
Error: failed to create emptyDir volume "cache": quota exceeded
```

**Причина:** Превышен лимит на `emptyDir` или ResourceQuota.

**Решение:**
```yaml
# Указание sizeLimit для emptyDir
volumes:
- name: cache
  emptyDir:
    sizeLimit: 1Gi  # Ограничение размера
```

### Prevention (Профилактика)

#### 1. Валидация манифестов

```bash
# Проверка манифеста перед применением
kubectl apply -f deployment.yaml --dry-run=client

# Проверка с помощью kubeval
kubeval deployment.yaml

# Проверка с помощью kubeconform
kubeconform deployment.yaml
```

#### 2. Использование Kustomize

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- deployment.yaml

configMapGenerator:
- name: app-config
  literals:
  - DATABASE_URL=postgres://db:5432/mydb

secretGenerator:
- name: db-credentials
  literals:
  - username=admin
  - password=SuperSecret
```

**Применение:**
```bash
kubectl apply -k .
```

#### 3. Helm values validation

```yaml
# values.yaml
configMap:
  enabled: true
  data:
    LOG_LEVEL: info

secret:
  enabled: true
  data:
    password: changeme
```

### Чек-лист диагностики

```bash
#!/bin/bash
# Скрипт диагностики CreateContainerConfigError

POD=$1
NS=${2:-default}

echo "=== Описание пода ==="
kubectl describe pod $POD -n $NS | grep -A 5 "Events:"

echo -e "\n=== Проверка ConfigMap ==="
kubectl get configmap -n $NS

echo -e "\n=== Проверка Secret ==="
kubectl get secret -n $NS

echo -e "\n=== Проверка PVC ==="
kubectl get pvc -n $NS

echo -e "\n=== Проверка VolumeMounts ==="
kubectl get pod $POD -n $NS -o jsonpath='{.spec.volumes}'
```

## Дополнительная информация

### Сравнение ошибок

| Ошибка | Когда возникает | Решение |
|--------|-----------------|---------|
| **CreateContainerConfigError** | До запуска, проблемы с зависимостями | Создать ConfigMap/Secret/PVC |
| **ImagePullBackOff** | До запуска, проблемы с образом | Исправить образ/imagePullSecrets |
| **CrashLoopBackOff** | После запуска, падение приложения | Исправить приложение/конфигурацию |

### Best Practices

| Практика | Описание |
|----------|----------|
| **Используйте один namespace** | ConfigMap/Secret должны быть в том же namespace |
| **Валидируйте манифесты** | `kubectl apply --dry-run=client` |
| **Используйте Kustomize/Helm** | Управление зависимостями |
| **Настройте RBAC** | Права для ServiceAccount |
| **Мониторьте события** | Алерты на CreateContainerConfigError |

### Ссылки

- [ConfigMap](https://kubernetes.io/docs/concepts/configuration/configmap/)
- [Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
- [Volumes](https://kubernetes.io/docs/concepts/storage/volumes/)
