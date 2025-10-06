# Secret

**Secret** — это объект Kubernetes, предназначенный для хранения небольших объемов чувствительных данных, таких как пароли, токены или ключи. Использование `Secret` позволяет отделить конфигурацию от секретных данных, что повышает безопасность и гибкость.

> **Важно:** По умолчанию данные в `Secret` хранятся в `etcd` в кодировке **Base64**, а не в зашифрованном виде. Base64 — это не шифрование, и данные могут быть легко раскодированы. Для защиты секретов необходимо настраивать шифрование неактивных данных (Encryption at Rest).

## Типы секретов

*   `Opaque`: Произвольные данные в виде пар ключ-значение. Тип по умолчанию.
*   `kubernetes.io/service-account-token`: Используется для хранения токена сервисного аккаунта.
*   `kubernetes.io/dockerconfigjson`: Для хранения учетных данных для доступа к приватному Docker-репозиторию.
*   `kubernetes.io/tls`: Для хранения TLS-сертификата и приватного ключа, обычно используется `Ingress`.

## Создание Secret

### Декларативно (из манифеста)

**`data` (значения в Base64)**

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
  DB_PASSWORD: bXktc3VwZXItc2VjcmV0LXBhc3N3b3Jk
```

**`stringData` (обычный текст)**

Это более удобный способ, так как Kubernetes автоматически кодирует значения.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-database-secret-2
type: Opaque
stringData:
  # Kubernetes сам преобразует это значение в Base64
  DB_PASSWORD: "my-super-secret-password"
```

### Императивно (из команды)

`kubectl` автоматически кодирует значения в Base64.

```bash
kubectl create secret generic my-database-secret \
  --from-literal=DB_PASSWORD='my-super-secret-password'
```

## Использование Secret в Pod'ах

### Как переменные окружения

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app-pod
spec:
  containers:
    - name: my-app
      image: my-app-image
      env:
        - name: DATABASE_PASSWORD
          valueFrom:
            secretKeyRef:
              name: my-database-secret # Имя секрета
              key: DB_PASSWORD        # Ключ в секрете
```

### Как файлы в томе (volume)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app-pod
spec:
  containers:
    - name: my-app
      image: my-app-image
      volumeMounts:
        - name: secret-volume
          mountPath: "/etc/secrets"
          readOnly: true
  volumes:
    - name: secret-volume
      secret:
        secretName: my-database-secret
```

В этом случае в директории `/etc/secrets` внутри контейнера будет создан файл с именем `DB_PASSWORD`, содержащий раскодированное значение.

## Рекомендации

*   **Включите Encryption at Rest** для `etcd`, чтобы шифровать секреты на диске.
*   **Используйте RBAC** для ограничения доступа к `Secret`.
*   Для более высокого уровня безопасности рассмотрите использование внешних систем управления секретами, таких как **HashiCorp Vault**.
