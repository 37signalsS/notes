# Настройка BasicAuth в Traefik с Kubernetes

## Определения

*   **Basic Authentication (BasicAuth)** — простейший метод аутентификации, при котором клиент передает учетные данные (логин и пароль) в заголовке `Authorization` в формате Base64.
*   **Middleware (Traefik)** — компонент динамической конфигурации Traefik, который позволяет модифицировать запрос до его отправки в бэкенд-сервис или ответ после него.
*   **MiddlewareChain (цепочка middleware)** — последовательная обработка запроса несколькими middleware в порядке их перечисления. Запрос проходит через каждый middleware по очереди; один middleware может изменить, отклонить или завершить обработку.
*   **ForwardAuth** — middleware делегирования аутентификации внешнему HTTP-сервису. Вместо проверки пароля локально, Traefik перенаправляет запрос на сторонний сервис (например, Authelia, Authentik, Casdoor), который принимает решение о допуске.
*   **IPAllowList** — middleware ограничения доступа по IP-адресам. Часто комбинируется с BasicAuth для двухфакторной проверки (что запрос от разрешенного IP **и** имеет правильные учетные данные).
*   **RateLimit** — middleware ограничения частоты запросов. Защита от brute-force атак на BasicAuth.
*   **htpasswd** — стандартная утилита Apache для создания и обновления файлов, используемых для хранения имен пользователей и паролей для базовой аутентификации.
*   **Argon2** — современный и криптостойкий алгоритм хеширования паролей, поддерживаемый в **Traefik v3.0+**, рекомендуемый для новых инсталляций вместо устаревшего MD5 (apr1).
*   **kubernetes.io/basic-auth** — специальный тип Kubernetes Secret, предназначенный для хранения пар логин/пароль. Содержит обязательные ключи `username` и `password`. Traefik поддерживает и `Opaque`, и `kubernetes.io/basic-auth`.

## Основные концепции

### 1. Механизм работы в Kubernetes
В отличие от Docker Compose, где данные могут быть прописаны в Labels, в Kubernetes Traefik использует нативные объекты **Secret** для хранения учетных данных. Middleware обращается к секрету, извлекает список пользователей и проверяет входящие запросы.

**Цепочка обработки запроса:**
```
Клиент (curl, браузер)
        │
        ▼
Entrypoint (:80/:443)
        │
        ▼
Router (match: Host(`api.example.com`))
        │
        ▼
Middleware Chain:
  ├─ IPAllowList (проверка IP → 403 если не прошел)
  ├─ RateLimit (проверка частоты → 429 если превышена)
  └─ BasicAuth (проверка логин/пароля → 401 если неверно)
        │
        ▼
Service → Backend Pod
```

**Порядок middleware важен:** если `BasicAuth` стоит перед `RateLimit`, то брутфорс будет считаться только по успешным авторизациям. Если `RateLimit` перед `BasicAuth` — лимит считается по всем запросам, включая неаутентифицированные.

### 2. Типы секретов
Для BasicAuth используется стандартный тип `Opaque`. Ключевое различие в способе описания данных в YAML:
*   **`stringData`**: Значения указываются в открытом виде (пароли должны быть уже хешированы). Kubernetes сам закодирует их в Base64 при сохранении.
*   **`data`**: Значения должны быть предварительно закодированы в Base64 пользователем.
*   **`kubernetes.io/basic-auth`**: Типизированный Secret с обязательными ключами `username` и `password`. Однако для BasicAuth в Traefik используется ключ `users` (содержащий хеши в формате htpasswd), поэтому тип `Opaque` является предпочтительным.

### 3. Алгоритмы хеширования
Traefik поддерживает следующие форматы:
*   **MD5 (apr1)**: Традиционный формат `htpasswd`. Широко распространен, но считается слабым против перебора.
*   **BCrypt**: Более безопасный вариант, поддерживается Traefik v2+.
*   **Argon2**: Наиболее безопасный, доступен начиная с Traefik v3.0.

**Сравнение алгоритмов:**

| Алгоритм | Формат хеша | Версия Traefik | Защита от GPU-перебора | Рекомендация |
|:---|:---|:---|:---|:---|
| MD5 (apr1) | `$apr1$...` | v1.x+ | Слабая | Только legacy-системы |
| BCrypt | `$2a$...` / `$2b$...` | v2.x+ | Средняя | Универсальный выбор |
| Argon2 | `$argon2id$...` | v3.0+ | Высокая | Рекомендуется для новых部署 |

### 4. Способы применения
Middleware может быть применен двумя способами:
1.  **IngressRoute (CRD)**: Прямое указание в списке `middlewares` объекта маршрутизации.
2.  **Standard Ingress**: Через аннотацию `traefik.ingress.kubernetes.io/router.middlewares`.
3.  **Gateway API (HTTPRoute)**: Через `extensionRef` на Traefik Middleware CRD (Traefik v3.3+).

### 5. Cross-Namespace ограничения
По умолчанию Traefik **не позволяет** использовать Middleware из другого Namespace. Это критично для централизованного управления аутентификацией. Решения:
*   **Вариант А:** Создавайте Middleware в каждом Namespace (шаблонизация через Helm/Kustomize).
*   **Вариант Б:** Используйте `--providers.kubernetesIngress.allowExternalNameServices=true` (Traefik v2.5+) или `allowCrossNamespace=true` (небезопасно).
*   **Вариант В:** Централизованная аутентификация через `ForwardAuth` (Middleware в namespace traefik, ссылка на внешний сервис).

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

### Сценарий 5: Комбинированная защита (BasicAuth + RateLimit + IPAllowList)

Для продакшн-окружения рекомендуется слойная защита: ограничение по IP, затем rate limit, затем аутентификация.

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: ip-whitelist
  namespace: my-app
spec:
  ipAllowList:
    sourceRange:
      - "10.0.0.0/8"        # Внутренняя сеть
      - "192.168.1.0/24"     # Офис
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: rate-limit
  namespace: my-app
spec:
  rateLimit:
    average: 100             # Среднее количество запросов в секунду
    burst: 50                # Всплеск (дополнительные запросы)
    period: 1s
    sourceCriterion:
      ipStrategy:
        depth: 1             # Глубина прокси (если за LB)
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: basic-auth
  namespace: my-app
spec:
  basicAuth:
    secret: auth-secret
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: security-chain
  namespace: my-app
spec:
  chain:
    middlewares:
      - name: ip-whitelist
      - name: rate-limit
      - name: basic-auth
```

**Применение цепочки:**
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
    - name: security-chain
```

**Порядок цепочки и логика:**
1. `IPAllowList` — мгновенное отклонение с 403 для неразрешенных IP (самый дешевый фильтр).
2. `RateLimit` — защита от brute-force по всем запросам (включая неаутентифицированные).
3. `BasicAuth` — проверка учетных данных только для прошедших первые два фильтра.

### Сценарий 6: ForwardAuth (делегирование аутентификации)

Для централизованного управления аутентификацией (SSO, MFA) Traefик делегирует проверку внешнему сервису.

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: forward-auth
  namespace: my-app
spec:
  forwardAuth:
    address: "http://authelia.auth.svc.cluster.local:8080/api/verify?rd=https://auth.example.com"
    trustForwardHeader: true
    authResponseHeaders:
      - Remote-User
      - Remote-Groups
      - Remote-Email
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app-route
  namespace: my-app
spec:
  entryPoints:
    - websecure
  routes:
  - match: Host(`app.example.com`)
    kind: Rule
    services:
    - name: my-service
      port: 80
    middlewares:
    - name: forward-auth
```

**Популярные auth-сервисы для ForwardAuth:**
- **Authelia**: SSO + MFA для интранета (LDAP/OIDC backend).
- **Authentik**: Гибкая платформа аутентификации с Web UI.
- **Casdoor**: Легковесная альтернатива с поддержкой множества провайдеров.

### Сценарий 7: Автоматическая ротация паролей

Скрипт для автоматической генерации и обновления Secret с новыми хешами паролей:

```bash
#!/bin/bash
# rotate-basic-auth.sh — генерация новых паролей и обновление Secret
set -euo pipefail

NAMESPACE="my-app"
SECRET_NAME="auth-secret"
USERS=("user1" "user2" "user3")
NEW_PASS_LENGTH=24

generate_password() {
    openssl rand -base64 $NEW_PASS_LENGTH | tr -d '=/+' | head -c $NEW_PASS_LENGTH
}

create_htpasswd() {
    local users=("$@")
    local htpasswd_content=""
    
    for user in "${users[@]}"; do
        local pass=$(generate_password)
        local hash=$(htpasswd -nbBC 10 "" "$pass" | tr -d ':\n' | sed 's/$2y/$2a/')
        if [ -n "$htpasswd_content" ]; then
            htpasswd_content="${htpasswd_content},"
        fi
        htpasswd_content="${htpasswd_content}${user}:${hash}"
        echo "${user}: ${pass}" >> /tmp/new_passwords.txt
    done
    
    echo "$htpasswd_content"
}

# Очистка предыдущего файла паролей
rm -f /tmp/new_passwords.txt
touch /tmp/new_passwords.txt

# Генерация новых хешей
HTPASSWD_DATA=$(create_htpasswd "${USERS[@]}")

# Обновление/создание Secret
kubectl create secret generic "$SECRET_NAME" \
    --namespace="$NAMESPACE" \
    --from-literal=users="$HTPASSWD_DATA" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "Пароли обновлены. Сохранены в /tmp/new_passwords.txt"
echo "ВАЖНО: Отправьте новые пароли пользователям и удалите /tmp/new_passwords.txt"

# Проверка применения
kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.users}' | base64 -d | head -c 100
echo "..."
```

**Helm-шаблон для автоматической ротации (через CronJob):**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: rotate-basic-auth
  namespace: kube-system
spec:
  schedule: "0 2 1 *"  # 1-е число каждого месяца в 02:00
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: secret-rotator
          containers:
          - name: rotate
            image: bitnami/kubectl:latest
            command: ["/bin/bash", "/scripts/rotate-basic-auth.sh"]
            volumeMounts:
            - name: scripts
              mountPath: /scripts
          volumes:
          - name: scripts
            configMap:
              name: rotate-script
              defaultMode: 0755
          restartPolicy: OnFailure
```

### Сценарий 8: Шаблонизация через Helm

**templates/auth-secret.yaml:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "mychart.fullname" . }}-auth
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "mychart.labels" . | nindent 4 }}
type: Opaque
stringData:
  users: {{ .Values.auth.users | quote }}
```

**templates/middleware.yaml:**
```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: {{ include "mychart.fullname" . }}-auth
  namespace: {{ .Release.Namespace }}
spec:
  basicAuth:
    secret: {{ include "mychart.fullname" . }}-auth
    removeHeader: true  # Удаляет заголовок Authorization перед отправкой в бэкенд
```

**values.yaml:**
```yaml
auth:
  users: "user1:$2a$10$...,user2:$2a$10$..."
```

**Установка с передачей паролей:**
```bash
# Через --set
HTPASSWD=$(htpasswd -nbBC 10 "" 'mypassword' | tr -d ':\n' | sed 's/$2y/$2a/')
helm install my-app . --set auth.users="admin:${HTPASSWD}"

# Через файл значений
helm install my-app . -f values-production.yaml
```

## Дополнительная информация

### Диагностические команды

```bash
# Просмотр логов Traefik с фильтрацией по basic-auth
kubectl logs -n traefik deployment/traefik --tail=200 | grep -i "basic-auth\|401\|auth"

# Проверка是否存在 Middleware
kubectl get middleware -n my-app
kubectl describe middleware basic-auth -n my-app

# Проверка Secret
kubectl get secret auth-secret -n my-app -o yaml
kubectl get secret auth-secret -n my-app -o jsonpath='{.data.users}' | base64 -d

# Проверка маршрутов Traefik (Dashboard или API)
kubectl port-forward -n traefik svc/traefik 8080:8080
# Затем: http://localhost:8080/dashboard/

# Тест аутентификации изнутри кластера
kubectl run test-curl --rm -i --restart=Never --image=curlimages/curl -- \
  curl -v -u user1:password123 http://my-service.my-app.svc.cluster.local

# Проверка аннотаций Ingress
kubectl get ingress my-app-ingress -n my-app -o yaml | grep -A5 annotations

# Проверка событий (Events) — ошибки создания/синхронизации
kubectl get events -n my-app --field-selector reason=Reconciling | tail -20

# Сравнение хешей в Secret и в htpasswd-файле
kubectl get secret auth-secret -n my-app -o jsonpath='{.data.users}' | base64 -d | \
  htpasswd -v -B - <(echo "user1:mypassword") 2>&1
```

### Типичные ошибки и диагностика

| Симптом | Вероятная причина | Решение |
|:---|:---|:---|
| `401 Unauthorized` на все запросы | Ключ в Secret называется не `users` | Укажите `secretKey` в Middleware или переименуйте ключ |
| `401 Unauthorized` только для нового пользователя | Неверный формат хеша в Secret | Убедитесь, что хеш сгенерирован `htpasswd` (MD5/BCrypt/Argon2) |
| Secret создан, но Middleware не работает | Namespace Middleware и Secret различаются | Создайте их в одном Namespace |
| Middleware создан, но не применяется | Неверный формат ссылки в аннотации | Формат: `namespace-name@kubernetescrd` |
| `$` в пароле ломает YAML | Интерпретация как переменная окружения | Используйте `$$` в Helm, одинарные кавычки в kubectl |
| BasicAuth + ForwardAuth конфликтуют | Оба Middleware применяются одновременно | Используйте цепочку `chain` с правильным порядком |
| RateLimit не срабатывает за LB | IP-адреса являются адресами балансировщика | Укажите `sourceCriterion.ipStrategy.depth: 1` |
| `403 Forbidden` при корректных данных | `IPAllowList` блокирует запрос | Проверьте `sourceRange` и реальный IP клиента |
| Медленная работа при большом количестве пользователей | BCrypt/Argon2 хеши вычисляются долго | Переключитесь на MD5 (apr1) для сервисов с высокой нагрузкой (компромисс безопасности) |

### Типичные ошибки (Antipatterns)

1. **Хранение паролей в открытом виде в Secret** — Secret по умолчанию не шифруется. Используйте Sealed Secrets или Encryption at Rest.
2. **Отсутствие RateLimit перед BasicAuth** — brute-force атака не ограничена. Всегда комбинируйте с RateLimit.
3. **Использование MD5 (apr1) в новом部署** — MD5 считается небезопасным. Используйте BCrypt или Argon2.
4. **Передача BasicAuth через HTTP** — Base64 легко декодируется. Всегда используйте TLS.
5. **Хранение хешей паролей в Git** — даже зашифрованные. Используйте External Secrets Operator или Sealed Secrets для продакшн.
6. **Cross-Namespace без необходимости** — каждый Namespace со своим Secret и Middleware проще в управлении и безопаснее.
7. **Игнорирование `removeHeader: true`** — если Middleware не удаляет `Authorization` перед проксированием, хеш пароля попадает в бэкенд-приложение.

### Рекомендации по безопасности

1.  **Всегда используйте TLS**: BasicAuth передает хеш Base64, который легко декодируется в открытый текст. Без HTTPS ваши пароли будут скомпрометированы при первом же запросе.
2.  **Ротация секретов**: Регулярно обновляйте хеши в Kubernetes Secret. Traefik подхватывает изменения динамически без перезагрузки.
3.  **Ограничение области видимости**: Создавайте Middleware и Secret в том же Namespace, что и защищаемое приложение, чтобы избежать проблем с правами доступа Cross-Namespace.
4.  **Комбинируйте защиту**: BasicAuth + RateLimit + IPAllowList — минимально необходимый набор для продакшн.
5.  **Мониторинг**: Настройте алерты на количество 401/403 ответов для обнаружения атак.
6.  **Логирование**: Включите access log в Traefik для аудита всех попыток аутентификации.
7.  **ForwardAuth вместо BasicAuth для SSO**: Если в организации уже есть LDAP/OIDC, делегируйте аутентификацию вместо дублирования учетных записей.

### См. также

**Аутентификация и безопасность:**
- **[Аутентификация в Kubernetes](./authentication.md)** — общие методы AuthN (OIDC, Webhook, Bearer Token).
- **[RBAC Overview](./rbac/rbac_overview.md)** — авторизация доступа к ресурсам кластера.
- **[Network Policies](../Networking/Network/NetworkPolicy/definitions.md)** — сетевая изоляция подов.
- **[Pod Security Context](./pod_security_context.md)** —限制 контейнеров на уровне подов.

**Traefik и Ingress:**
- **[Обзор Traefik](../../WebServers/Traefik/traefik_overview.md)** — архитектура, Middleware, Providers.
- **[Ingress Overview](../Networking/Ingress/overview.md)** — объект Ingress и контроллеры.
- **[Сравнение Ingress-контроллеров](../Networking/Ingress/controllers_comparison.md)** — NGINX vs Traefik vs HAProxy.
- **[Gateway API + Traefik](../Networking/gateway_api/traefik.md)** — переход на Gateway API.

**Секреты и конфигурация:**
- **[Основы Kubernetes Secret](../Base/secrets/secrets_basics.md)** — типы, жизненный цикл, шифрование.
- **[Создание Secret](../Base/secrets/creating_secrets.md)** — способы создания (kubectl, манифест, Helm).
- **[Sealed Secrets](./sealed_secrets_overview.md)** — шифрование секретов для Git.
- **[External Secrets Operator](../Base/secrets/external_managers.md)** — синхронизация с внешними KMS.
- **[Helm Templating](../ToolsUtilities/Helm/templating/functions.md)** — `htpasswd` функция в шаблонах.
