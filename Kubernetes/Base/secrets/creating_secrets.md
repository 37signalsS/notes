# Создание Secret в Kubernetes

## Определения

**Secret** — объект Kubernetes для хранения конфиденциальных данных. Значения кодируются в Base64 (не шифрование!).

> Подробнее о безопасности см. [Безопасность Secret](security.md) и [Хранение в etcd](etcd_storage.md).

## Практические сценарии

### Декларативно с `stringData` (рекомендуемый)

Kubernetes автоматически кодирует значения в Base64:

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
