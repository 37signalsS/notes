# Создание Secret в Kubernetes

## Определения

**Secret** — объект Kubernetes для хранения конфиденциальных данных (пароли, токены, ключи). Значения кодируются в Base64 (не является шифрованием).

> Подробнее о безопасности см. [Безопасность Secret](security.md) и [Хранение в etcd](etcd_storage.md).

## Основные концепции

### Методы создания

1. **Декларативно** — через YAML-манифесты. Рекомендуется для GitOps-процессов.
   - `stringData` — значения в открытом виде (автоматическое кодирование в Base64 при сохранении)
   - `data` — значения, предварительно закодированные в Base64 вручную

2. **Императивно** — через интерфейс командной строки `kubectl create secret`.
   - `--from-literal` — из отдельных пар ключ-значение
   - `--from-file` — из содержимого файлов
   - `--from-env-file` — из файла с переменными окружения

3. **Автоматически** — Kubernetes самостоятельно создаёт некоторые секреты (например, ServiceAccount-токены).

### Типы Secret

Kubernetes поддерживает несколько встроенных типов секретов для различных сценариев (TLS, Docker Registry, Auth).

> Подробное описание типов см. в **[Основы Secret: Типы](secrets_basics.md#типы-secret)**.

## Практические сценарии

### Декларативно с использованием stringData

Это наиболее удобный способ для GitOps. Kubernetes автоматически преобразует текст в Base64.

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

> **Примечание:** Поле `stringData` является "write-only". При чтении секрета через `kubectl get secret -o yaml` вы увидите только поле `data` с Base64.

### Декларативно с использованием data

Значения необходимо закодировать в Base64 вручную перед вставкой в манифест:

```bash
# Кодирование пароля в Base64
echo -n 'my-super-secret-password' | base64
# → bXktc3VwZXItc2VjcmV0LXBhc3N3b3Jk
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-database-secret
type: Opaque
data:
  password: bXktc3VwZXItc2VjcmV0LXBhc3N3b3Jk
```

### Императивное создание через kubectl

Команда `kubectl` самостоятельно выполняет кодирование в Base64.

```bash
# Создание из литералов
kubectl create secret generic db-cred \
  --from-literal=username=app \
  --from-literal=password='S3cUr3!'

# Создание из файлов
kubectl create secret generic my-file-secret \
  --from-file=path/to/config.txt
```

### Создание TLS Secret

Для TLS (Transport Layer Security) сертификатов используется специальный тип `kubernetes.io/tls`.

```bash
# Генерация ключа и сертификата
openssl genrsa -out tls.key 2048
openssl req -new -x509 -key tls.key -out tls.crt -days=365

# Создание Secret
kubectl create secret tls my-tls-secret \
  --cert=tls.crt \
  --key=tls.key
```

### Создание Docker Registry Secret

Используется для предоставления доступа к приватным репозиториям образов.

```bash
# Явное указание параметров
kubectl create secret docker-registry registry-secret \
  --docker-server=ghcr.io \
  --docker-username=<username> \
  --docker-password=<token> \
  --docker-email=admin@example.com
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
        - name: registry-secret
```

Подробнее об интеграции с CI/CD: [Werf: Настройка доступа к GitHub Container Registry](../../../CI-CD/Tools/werf_overview.md#сценарий-1-настройка-доступа-к-github-container-registry).

## Дополнительная информация

### Приоритеты полей

Если в одном манифесте указан один и тот же ключ в `data` и `stringData`, значение из `stringData` имеет приоритет.

### Использование созданных Secret

После создания секреты можно подключить к поду:

- **[Монтирование как тома](using_secrets.md#монтирование-секретов-как-тома-volume)**
- **[Переменные окружения](using_secrets.md#использование-как-переменные-окружения)**

### Связанные темы

[Основы Secret](secrets_basics.md), [Использование Secret](using_secrets.md), [Хранение в etcd](etcd_storage.md), [Безопасность Secret](security.md), [Внешние менеджеры](external_managers.md).

