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
kubectl create secret generic db-cred \
  --from-literal=username=app \
  --from-literal=password='S3cUr3!'
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
