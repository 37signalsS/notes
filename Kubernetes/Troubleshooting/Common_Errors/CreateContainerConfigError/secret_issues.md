# CreateContainerConfigError: Проблемы с Secret

## 1. Отсутствует Secret

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

> **См. также:** [`../../../Base/secrets/external_managers.md`](../../../Base/secrets/external_managers.md), [`../../../Security/rbac/rbac_overview.md`](../../../Security/rbac/rbac_overview.md)

## 2. Ключ Secret не существует

**Сообщение:**

```
secret "db-credentials" not found: key "password" not found
```

**Причина:** Secret существует, но указанный ключ отсутствует.

**Диагностика:**

```bash
# Проверка ключей Secret
kubectl get secret db-credentials -o jsonpath='{.data}'
```

**Решение:**

```bash
# Добавление ключа в Secret
kubectl patch secret db-credentials \
  -p '{"data":{"password":"'"$(echo -n 'newpassword' | base64)"'"}}'
```
