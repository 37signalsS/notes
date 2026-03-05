# Настройка BasicAuth в Traefik с Kubernetes

## Определения

**Basic Authentication (BasicAuth)** в Traefik — это middleware, которое защищает сервисы, требуя от пользователя ввести имя и пароль для получения доступа. В Kubernetes конфигурация этой аутентификации хранится в стандартных ресурсах `Secret`.

## Основные концепции

### 1. Формат секрета: `data` vs `stringData`

В Kubernetes `Secret` можно определять двумя способами:

* **`data`**: требует, чтобы значения были предварительно закодированы в **Base64**.
* **`stringData`**: позволяет указывать значения в виде обычного текста, Kubernetes кодирует их автоматически.

### 2. Требования Traefik

Ключевая особенность Traefik для `basicAuth` заключается в том, что он **не принимает пароли в открытом виде**. Пароль должен быть хэширован с использованием `htpasswd` (обычно с MD5, но поддерживаются и другие алгоритмы).

## Практические сценарии

### Шаг 1: Генерация хэша пароля

Используйте утилиту `htpasswd` для создания хэшированной строки.

```bash
# Укажите имя пользователя и пароль
htpasswd -nb admin supersecret
```

Пример вывода:

```
admin:$apr1$2a9XgJ3z$4oD.3Y3z9x9z9z9z9z9z9z
```

### Шаг 2: Создание Kubernetes Secret

**Вариант А: `stringData` (рекомендуемый)**

Этот метод проще, так как не требует ручного кодирования.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: traefik-auth-secret
  namespace: default
stringData:
  users: admin:$apr1$2a9XgJ3z$4oD.3Y3z9x9z9z9z9z9z9z
```

**Вариант Б: `data`**

Здесь нужно вручную закодировать строку в Base64.

```bash
echo -n 'admin:$apr1$2a9XgJ3z$4oD.3Y3z9x9z9z9z9z9z9z' | base64
# Вывод: YWRtaW46JGFwcjEkMmE5WGdKM3okNE9ELjNZM3o5eDl6OXo5ejo5ejk5eg==
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: traefik-auth-secret
  namespace: default
data:
  users: YWRtaW46JGFwcjEkMmE5WGdKM3okNE9ELjNZM3o5eDl6OXo5ejo5ejk5eg==
```

### Шаг 3: Подключение секрета к Middleware

Создайте ресурс `Middleware` и укажите в нем созданный секрет.

```yaml
apiVersion: traefik.containo.us/v1alpha1
kind: Middleware
metadata:
  name: auth
  namespace: default
spec:
  basicAuth:
    secret: traefik-auth-secret
```

Этот middleware теперь можно применять к любым IngressRoute для их защиты.

## Дополнительная информация

Хотя `stringData` упрощает создание секрета, важно помнить, что **для Traefik `basicAuth` всегда требуется хэшированный пароль**, а не пароль в открытом виде. Несоблюдение этого требования — частая причина ошибок при настройке.

### Связанные темы

* **[Authentication](./authentication.md)** — аутентификация в Kubernetes
* **[Secret](./application_secrets_management.md)** — работа с секретами
* **[Ingress Overview](../Networking/Ingress/overview.md)** — ingress-контроллеры
* **[Traefik](../Networking/gateway_api/traefik.md)** — документация по Traefik
