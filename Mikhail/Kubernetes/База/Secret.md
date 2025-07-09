# Secret

**Secret** — это объект Kubernetes, предназначенный для хранения небольших объемов чувствительных данных, таких как пароли, токены или ключи. Использование `Secret` позволяет отделить секретные данные от конфигурации подов, что повышает безопасность и гибкость.

**Важно:** По умолчанию данные в `Secret` хранятся в `etcd` в кодировке **Base64**, а не в зашифрованном виде. Base64 — это не шифрование, и данные могут быть легко раскодированы. Для настоящей безопасности необходимо настроить шифрование секретов в `etcd` (Encryption at Rest).

---

### Типы секретов

*   `Opaque`: Произвольные данные в виде пар ключ-значение. Тип по умолчанию.
*   `kubernetes.io/service-account-token`: Используется для хранения токена сервисного аккаунта.
*   `kubernetes.io/dockerconfigjson`: Для хранения учетных данных для доступа к приватному Docker-репозиторию.
*   `kubernetes.io/tls`: Для хранения TLS-сертификата и приватного ключа, обычно используется `Ingress`.

---

### Способы создания и использования

#### 1. Создание секрета

**Декларативно (из манифеста):**
Значения должны быть закодированы в Base64.
`echo -n 'my-super-secret-password' | base64` -> `bXktc3VwZXItc2VjcmV0LXBhc3N3b3Jk`

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

**Императивно (из команды):**
`kubectl` автоматически кодирует значения.

```bash
kubectl create secret generic my-database-secret \
  --from-literal=DB_PASSWORD='my-super-secret-password'
```

#### 2. Использование секрета в поде

Секреты можно использовать двумя основными способами:

**а) Как переменные окружения:**

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

**б) Как файлы в томе:**

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
