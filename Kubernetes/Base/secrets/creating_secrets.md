# Создание и использование Secret в Pod'ах

## Способы создания

### Декларативно (из манифеста) с `stringData` (рекомендуемый)

Это наиболее удобный способ, так как Kubernetes автоматически кодирует значения в Base64.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-cred
type: Opaque
stringData:
  # Kubernetes сам преобразует это значение в Base64
  username: "app"
  password: "my-super-secret-password"
```

### Декларативно (из манифеста) с `data`

Значения должны быть предварительно закодированы в Base64.

```bash
# Кодирование пароля в Base64
 echo -n 'my-super-secret-password' | base64
# Вывод: bXktc3VwZXItc2VjcmV0LXBhc3N3b3Jk
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-database-secret
type: Opaque
data:
  # ключ: значение (в base64)
  password: bXktc3VwZXItc2VjcmV0LXBhc3N3b3Jk
```

### Императивно (из команды)

`kubectl` автоматически кодирует значения в Base64.

```bash
kubectl create secret generic db-cred \
  --from-literal=username=app \
  --from-literal=password='S3cUr3!'
```
