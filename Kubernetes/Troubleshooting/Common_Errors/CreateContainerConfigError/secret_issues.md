# CreateContainerConfigError: Проблемы с Secret

## Definitions

**Secret-related CreateContainerConfigError** — ошибка, возникающая когда Pod ссылается на Secret, который не существует, содержит недостающие ключи или не может быть смонтирован из-за некорректной конфигурации.

## Basic Concepts

### Типичные сообщения об ошибке

| Сообщение | Причина |
|-----------|---------|
| `secret "x" not found` | Secret не существует в namespace |
| `secret "x" not found: key "y" not found` | Secret существует, ключ отсутствует |
| `invalid character in secret key` | Ключ содержит недопустимые символы |

### Способы использования Secret в Pod

| Способ | Синтаксис | Поведение |
|--------|-----------|-----------|
| **Все ключи как env** | `envFrom.secretRef` | Каждый ключ → переменная окружения |
| **Отдельный ключ как env** | `env.valueFrom.secretKeyRef` | Один ключ → одна переменная |
| **Как volume (файлы)** | `volumes.secret` | Каждый ключ → файл с декодированным содержимым |

### Типы Secret

| Тип | Назначение |
|-----|------------|
| `Opaque` | Произвольные данные (по умолчанию) |
| `kubernetes.io/tls` | TLS-сертификаты (`tls.crt`, `tls.key`) |
| `kubernetes.io/dockerconfigjson` | Учётные данные container registry |
| `kubernetes.io/service-account-token` | Токен ServiceAccount (монтируется автоматически) |

### Создание Secret

```bash
# Из литералов
kubectl create secret generic db-credentials \
  --from-literal=username=admin \
  --from-literal=password=SuperSecret123 \
  -n <namespace>

# Из файла
kubectl create secret generic tls-secret \
  --from-file=tls.crt=/path/to/cert.pem \
  --from-file=tls.key=/path/to/key.pem \
  --type=kubernetes.io/tls
```

> Общие концепции Secret: [secrets_basics.md](../../../Base/secrets/secrets_basics.md).

## Practical Scenarios

### Сценарий 1: Secret не существует

**Сообщение:**

```
Error: secret "db-credentials" not found
```

**Диагностика:**

```bash
kubectl get secret db-credentials -n <namespace>
```

**Решение:** Создать недостающий Secret.

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

Или через `stringData` (автоматическое кодирование в base64):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: default
type: Opaque
stringData:
  username: admin
  password: SuperSecret123
```

### Сценарий 2: Ключ Secret отсутствует

**Сообщение:**

```
secret "db-credentials" not found: key "password" not found
```

**Диагностика:**

```bash
# Проверка ключей Secret
kubectl get secret db-credentials -n <namespace> -o jsonpath='{.data}'
```

**Решение:**

```bash
# Добавление ключа в Secret (с base64-кодированием)
kubectl patch secret db-credentials \
  -p '{"data":{"password":"'"$(echo -n 'newpassword' | base64)"'"}}'

# Через stringData (без base64)
kubectl patch secret db-credentials \
  -p '{"stringData":{"password":"newpassword"}}'
```

### Сценарий 3: Namespace mismatch

**Симптом:** Secret существует, но Pod не может его найти.

**Диагностика:**

```bash
# Namespace Secret
kubectl get secret db-credentials -n <namespace-a>

# Namespace Pod
kubectl get pod <pod-name> -n <namespace-b>
```

**Решение:** Создать Secret в том же namespace, что и Pod.

### Сценарий 4: Secret обновлён, Pod не подхватил изменения

**Особенность:** При монтировании как volume обновление происходит автоматически (~60 сек). При использовании как env — требуется restart Pod.

**Решение:**

```bash
kubectl rollout restart deployment/<deployment-name> -n <namespace>
```

### Сценарий 5: Использование в Pod

```yaml
# Все ключи как переменные окружения
envFrom:
- secretRef:
    name: db-credentials

# Отдельный ключ как переменная
env:
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: db-credentials
      key: password
      optional: false  # true — не блокирует запуск при отсутствии ключа

# Монтирование как volume
volumes:
- name: secrets
  secret:
    secretName: db-credentials
    defaultMode: 0400  # Права доступа к файлам
volumeMounts:
- name: secrets
  mountPath: /etc/secrets
  readOnly: true
```

## Additional Information

### Отличие Secret от ConfigMap

| Аспект | ConfigMap | Secret |
|--------|-----------|--------|
| **Хранение** | Plain text | Base64 (не шифрование) |
| **etcd** | Обычное хранение | Опционально шифрование at rest |
| **Размер** | До 1 MiB | До 1 MiB |
| **Назначение** | Конфигурация | Пароли, токены, ключи |

Подробнее: [secrets_basics.md](../../../Base/secrets/secrets_basics.md), [ConfigMap](../../../Base/configmap.md).

### Безопасность Secret

- Secret хранится в etcd в base64 — **это не шифрование**. Для защиты данных включите шифрование at rest в etcd: [etcd_storage.md](../../../Base/secrets/etcd_storage.md).
- Ограничьте доступ через RBAC: [rbac_overview.md](../../../Security/rbac/rbac_overview.md).
- Для хранения в Git используйте [Sealed Secrets](../../../Security/sealed_secrets_overview.md) или [SOPS](../../../../Security/Tools/sops_overview.md).

### Связанные ресурсы

- Определения: [definitions.md](./definitions.md)
- Диагностика: [diagnostics.md](./diagnostics.md)
- ConfigMap: [configmap_issues.md](./configmap_issues.md)
- RBAC: [rbac_issues.md](./rbac_issues.md)
- Профилактика: [prevention.md](./prevention.md)
