# Настройка BasicAuth в Traefik с Kubernetes

## Определения

*   **Basic Authentication (BasicAuth)** — простейший метод аутентификации, при котором клиент передает учетные данные (логин и пароль) в заголовке `Authorization` в формате Base64.
*   **Middleware (Traefik)** — компонент динамической конфигурации Traefik, который позволяет модифицировать запрос до его отправки в бэкенд-сервис или ответ после него.
*   **htpasswd** — стандартная утилита Apache для создания и обновления файлов, используемых для хранения имен пользователей и паролей для базовой аутентификации.
*   **Argon2** — современный и криптостойкий алгоритм хеширования паролей, поддерживаемый в **Traefik v3.0+**, рекомендуемый для новых инсталляций вместо устаревшего MD5 (apr1).

## Основные концепции

### 1. Механизм работы в Kubernetes
В отличие от Docker Compose, где данные могут быть прописаны в Labels, в Kubernetes Traefik использует нативные объекты **Secret** для хранения учетных данных. Middleware обращается к секрету, извлекает список пользователей и проверяет входящие запросы.

### 2. Типы секретов
Для BasicAuth используется стандартный тип `Opaque`. Ключевое различие в способе описания данных в YAML:
*   **`stringData`**: Значения указываются в открытом виде (пароли должны быть уже хешированы). Kubernetes сам закодирует их в Base64 при сохранении.
*   **`data`**: Значения должны быть предварительно закодированы в Base64 пользователем.

### 3. Алгоритмы хеширования
Traefik поддерживает следующие форматы:
*   **MD5 (apr1)**: Традиционный формат `htpasswd`. Широко распространен, но считается слабым против перебора.
*   **BCrypt**: Более безопасный вариант, поддерживается Traefik v2+.
*   **Argon2**: Наиболее безопасный, доступен начиная с Traefik v3.0.

### 4. Способы применения
Middleware может быть применен двумя способами:
1.  **IngressRoute (CRD)**: Прямое указание в списке `middlewares` объекта маршрутизации.
2.  **Standard Ingress**: Через аннотацию `traefik.ingress.kubernetes.io/router.middlewares`.

## Практические сценарии

### Шаг 1: Генерация хешированного пароля

Используйте утилиту `htpasswd` (пакет `apache2-utils` в Debian/Ubuntu или `httpd-tools` в RHEL/CentOS).

**Метод MD5 (совместим со всеми версиями):**
```bash
htpasswd -nb user1 password123
# → user1:$apr1$vL2G.J3z$8oX.3Y3z9x9z9z9z9z9z9z
```

**Метод Argon2 (рекомендуется для Traefik v3.0+):**
```bash
# Требует установленной утилиты argon2
echo -n "password123" | argon2 "salt1234" -e
# Результат в формате Traefik: user1:$argon2id$v=19$m=65536,t=3,p=4$...
```

### Шаг 2: Создание Kubernetes Secret

Для нескольких пользователей перечислите их в одной строке через запятую или в разных строках (в зависимости от ключа). Traefik ожидает ключ `users`.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: auth-secret
  namespace: my-app
type: Opaque
stringData:
  # Можно указать несколько пользователей через запятую
  users: |
    user1:$apr1$vL2G.J3z$8oX.3Y3z9x9z9z9z9z9z9z,
    user2:$apr1$7R3.K9x2$pQ1.2A3z8x8z8z8z8z8z8z
```

### Шаг 3: Создание Middleware

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: basic-auth
  namespace: my-app
spec:
  basicAuth:
    secret: auth-secret
```

### Шаг 4: Применение к маршрутам

#### Сценарий А: Использование IngressRoute (Traefik CRD)
```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app-route
  namespace: my-app
spec:
  entryPoints:
    - websecure
  routes:
  - match: Host(`api.example.com`)
    kind: Rule
    services:
    - name: my-service
      port: 80
    middlewares:
    - name: basic-auth # Имя созданного Middleware
```

#### Сценарий Б: Использование стандартного Ingress
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  namespace: my-app
  annotations:
    # Формат: namespace-name@kubernetescrd
    traefik.ingress.kubernetes.io/router.middlewares: my-app-basic-auth@kubernetescrd
spec:
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-service
            port:
              number: 80
```

## Дополнительная информация

### Типичные ошибки и диагностика

*   **Ошибка 401 Unauthorized**: Проверьте, что в секрете используется ключ именно `users`. Если ключ другой, укажите его в Middleware через параметр `secretKey`.
*   **Спецсимволы в пароле**: При использовании `stringData` в YAML, символы `$` могут интерпретироваться как переменные окружения. Используйте одинарные кавычки для строк или двойные знаки `$$` (в зависимости от способа деплоя, например, Helm).
*   **Проверка логов**: Если аутентификация не работает, проверьте логи пода Traefik:
    ```bash
    kubectl logs -n traefik deployment/traefik | grep basic-auth
    ```

### Рекомендации по безопасности
1.  **Всегда используйте TLS**: BasicAuth передает хеш Base64, который легко декодируется в открытый текст. Без HTTPS ваши пароли будут скомпрометированы при первом же запросе.
2.  **Ротация секретов**: Регулярно обновляйте хеши в Kubernetes Secret. Traefik подхватывает изменения динамически без перезагрузки.
3.  **Ограничение области видимости**: Создавайте Middleware и Secret в том же Namespace, что и защищаемое приложение, чтобы избежать проблем с правами доступа Cross-Namespace.

Подробнее об управлении данными: **[Основы Kubernetes Secret](../Base/secrets/secrets_basics.md)**.
Общая архитектура прокси: **[Обзор Traefik](../../WebServers/Traefik/traefik_overview.md)**.
Альтернативные методы защиты: **[Аутентификация в Kubernetes](./authentication.md)**.
Контроллеры в K8s: **[Ingress Overview](../Networking/Ingress/overview.md)**.
