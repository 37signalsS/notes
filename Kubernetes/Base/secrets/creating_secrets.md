# Создание Secret в Kubernetes

## Определения

**Secret** — объект Kubernetes для хранения конфиденциальных данных. Значения кодируются в Base64 (не шифрование!).

> Подробнее о безопасности см. [Безопасность Secret](security.md) и [Хранение в etcd](etcd_storage.md).

## Практические сценарии

### Декларативно с `stringData` (рекомендуемый)

Это наиболее удобный и безопасный для GitOps способ. Kubernetes автоматически кодирует значения в Base64, а вы работаете с обычным текстом.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-cred
type: Opaque
stringData:
  # Kubernetes сам преобразует это значение в Base64 и поместит в поле 'data'
  username: "app"
  password: "my-super-secret-password"
```

> **Примечание:** Поле `stringData` является "write-only". При чтении секрета через `kubectl get secret -o yaml` вы всегда будете видеть только поле `data` с Base64-кодированными значениями. `stringData` существует для удобства написания манифестов.

### Декларативно с `data`

Значения необходимо предварительно закодировать в Base64 вручную:

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

### Императивно через kubectl

`kubectl` автоматически кодирует значения в Base64:

```bash
# Из литералов
kubectl create secret generic db-cred \
  --from-literal=username=app \
  --from-literal=password='S3cUr3!'

# Из файлов (приватный ключ, сертификат)
kubectl create secret tls my-tls-secret \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key

# Из директории с файлами
kubectl create secret generic my-secret \
  --from-file=path/to/directory/
```

### Приоритет `stringData` над `data`

При указании одинакового ключа в обоих полях, `stringData` имеет приоритет:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: combined-secret
type: Opaque
data:
  username: YWRtaW4=     # "admin" в base64
stringData:
  username: administrator  # Приоритетнее, результат: "administrator"
```

### Типы Secret

#### TLS Secret

Для TLS сертификатов используется тип `kubernetes.io/tls`:

```bash
# Генерация приватного ключа и самоподписанного сертификата
openssl genrsa -out tls.key 2048
openssl req -new -x509 -key tls.key -out tls.crt -days=365

# Создание Secret
kubectl create secret tls my-tls-secret \
  --cert=tls.crt \
  --key=tls.key
```

#### Docker Registry Secret

Для доступа к приватным Docker registry:

```bash
# Из существующего docker config
kubectl create secret generic regcred \
  --from-file=.dockerconfigjson=<path/to/config.json> \
  --type=kubernetes.io/dockerconfigjson

# Явно указать параметры
kubectl create secret docker-registry myregistry-secret \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=user \
  --docker-password=password \
  --docker-email=email@example.com
```

**Использование в Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  template:
    spec:
      containers:
        - name: app
          image: ghcr.io/username/myapp:v1.0.0
      imagePullSecrets:
        - name: myregistry-secret
```

**Сценарий: GitHub Container Registry (GHCR)**

```bash
# Создание токена: Профиль → Settings → Developer settings → Personal access tokens
# Scope: read:packages (pull), write:packages (push)

# Создание Secret
kubectl create secret docker-registry registry-secret \
  --docker-server=ghcr.io \
  --docker-username=<username> \
  --docker-password=<token> \
  -n <namespace>
```

**Автоматизация через ServiceAccount:**

Чтобы не указывать `imagePullSecrets` в каждом Deployment, можно привязать Secret к ServiceAccount:

```bash
kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "registry-secret"}]}' \
  -n <namespace>
```

Подробнее о работе с GHCR в контексте werf: [Werf: Настройка доступа к GitHub Container Registry](../../../CI-CD/Tools/werf_overview.md#сценарий-1-настройка-доступа-к-github-container-registry).

## Дополнительная информация

### Типы Secret

По умолчанию используется тип `Opaque`. Другие типы см. в [Основах Secret](secrets_basics.md#типы-secret).

### Использование созданных Secret

- [Монтирование как том](using_secrets.md#как-файлы-в-томе-volume)
- [Переменные окружения](using_secrets.md#как-переменные-окружения-env-envfrom)

### Связанные темы

- [Основы Secret](secrets_basics.md)
- [Использование Secret](using_secrets.md)
- [Хранение в etcd](etcd_storage.md)
- [Безопасность](security.md)
