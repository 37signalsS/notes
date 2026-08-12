# Веб-аутентификация для Prometheus, Alertmanager и Grafana (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **Источник темы:** аутентификация веб-интерфейсов Prometheus, Alertmanager и Grafana в kube-prometheus-stack.  
> **Смежные темы:** [Безопасность Prometheus Operator](../../operator/Security/index.md) — YAML-примеры встроенной auth, Ingress Basic Auth, TLS; [Access Control](../../operator/Security/access_control.md) — NetworkPolicies, RBAC; [HTTP Authentication](../../../../Networking/Protocols/HTTP/http_authentication.md) — теория Basic/Digest/Bearer auth.

## Определения

**Веб-аутентификация Prometheus** — ограничение доступа к веб-интерфейсу Prometheus (`/graph`, `/api/v1/*`, `/targets`). По умолчанию Prometheus **не требует** аутентификации. Начиная с версии v2.24+ поддерживается нативная аутентификация через файл конфигурации (`--web.config.file`), что позволяет защитить интерфейс без внешних прокси.

**Веб-аутентификация Alertmanager** — ограничение доступа к UI Alertmanager (`/#/alerts`, `/api/v2/*`). Также поддерживает нативную аутентификацию через файл конфигурации. Без неё защита возможна только на уровне Ingress/Reverse Proxy.

**Веб-аутентификация Grafana** — встроенная система управления пользователями с поддержкой локальных учётных записей, OAuth (Google, GitHub, GitLab, OIDC), LDAP и SAML.

**Basic Auth** — метод HTTP-аутентификации (RFC 7617), передающий учётные данные в заголовке `Authorization`. **Критически важно:** Basic Auth без TLS передаёт пароли в кодировке base64, что эквивалентно открытому тексту. TLS обязателен для любой промышленной инсталляции.

## Основные концепции

### Матрица методов аутентификации (2024–2025)

| Компонент | Нативная Basic Auth | Ingress Basic Auth | OAuth / OIDC | TLS (HTTPS) |
|---|---|---|---|---|
| **Prometheus** | Да (`spec.web.webConfig`) | Да (NGINX/Traefik) | Через Oauth2-proxy | Обязательно |
| **Alertmanager** | Да (`spec.web.webConfig`) | Да (NGINX/Traefik) | Через Oauth2-proxy | Обязательно |
| **Grafana** | Да (встроенная) | Да (избыточно) | Да (нативно) | Обязательно |

### Три уровня стратегии защиты

```
Уровень 1: Сетевая изоляция (Network Level)
    └── Доступ только через VPN или пограничный шлюз.
    └── Отсутствие публичных Ingress и внешних IP.

Уровень 2: Шлюзовая авторизация (Ingress Level)
    └── Проверка на уровне Ingress NGINX/Traefik через аннотации.
    └── Использование htpasswd или внешних auth-сервисов.

Уровень 3: Прикладная авторизация (Application Level)
    └── Нативная настройка внутри Prometheus/Alertmanager (v2.48+).
    └── Использование Kubernetes Secrets для хранения хэшированных паролей.
```

## Практические сценарии

### Сценарий 1: Prometheus — Нативная Basic Auth (Bcrypt)

Рекомендуемый метод для современных версий Оператора (v0.70+).

**Шаг 1: Генерация хэша пароля**
Prometheus требует пароли в формате Bcrypt.
```bash
# Генерация хэша через Python
python3 -c 'import bcrypt; print(bcrypt.hashpw("secure_password".encode(), bcrypt.gensalt()).decode())'
```

**Шаг 2: Создание Secret с конфигурацией**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: prometheus-web-config
  namespace: monitoring
stringData:
  web-config.yaml: |
    basic_auth_users:
      admin: "$2b$12$HashedPasswordResult..."
```

**Шаг 3: Настройка в values.yaml**
```yaml
prometheus:
  prometheusSpec:
    web:
      webConfig:
        key: web-config.yaml
        name: prometheus-web-config
```

### Сценарий 2: Alertmanager — Нативная Auth и связь с Prometheus

При включении авторизации на Alertmanager необходимо обновить настройки Prometheus, иначе алерты перестанут доставляться.

**Шаг 1: Создание Secret для Alertmanager (аналогично сценарию 1).**

**Шаг 2: Настройка Prometheus в values.yaml:**
```yaml
prometheus:
  prometheusSpec:
    alerting:
      alertmanagers:
        - name: alertmanager-operated
          namespace: monitoring
          port: web
          basicAuth:
            username:
              name: alertmanager-auth-credentials # Секрет с логином
              key: user
            password:
              name: alertmanager-auth-credentials # Секрет с паролем
              key: password
```

### Сценарий 3: Ingress Basic Auth (NGINX)

Метод через использование внешнего файла `htpasswd`.

**Шаг 1: Генерация файла htpasswd и создание секрета**
```bash
# Создание файла (утилита из apache2-utils)
htpasswd -cb auth admin 'mypassword'

# Создание секрета в Kubernetes
kubectl create secret generic monitoring-basic-auth --from-file=auth -n monitoring
```

**Шаг 2: Настройка аннотаций в values.yaml**
```yaml
prometheus:
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      nginx.ingress.kubernetes.io/auth-type: basic
      nginx.ingress.kubernetes.io/auth-secret: monitoring-basic-auth
      nginx.ingress.kubernetes.io/auth-realm: "Authentication Required"
    hosts:
      - prometheus.example.com
```

### Сценарий 4: Grafana — Использование существующего секрета

Для предотвращения утечки пароля из Git-репозитория используйте `existingSecret`.

```yaml
# values.yaml
grafana:
  admin:
    existingSecret: grafana-admin-secret
    userKey: admin-user
    passwordKey: admin-password
```

**Генерация секрета с рандомным паролем:**
```bash
kubectl create secret generic grafana-admin-secret \
  --from-literal=admin-user="admin" \
  --from-literal=admin-password="$(openssl rand -base64 24)" \
  -n monitoring
```

### Сценарий 5: Настройка TLS для всех интерфейсов

```yaml
# Пример для Prometheus Ingress
prometheus:
  ingress:
    enabled: true
    hosts:
      - prometheus.example.com
    tls:
      - secretName: prometheus-tls-cert
        hosts:
          - prometheus.example.com
```

## Диагностика и отладка

### Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| Бесконечный запрос логина | Неверный алгоритм хэширования в Secret | Используйте только Bcrypt для нативной auth. |
| Prometheus: `401 Unauthorized` при отправке алерта | Отсутствует `basicAuth` в конфиге алертинга | Добавьте учетные данные в `alerting.alertmanagers`. |
| Ingress: `403 Forbidden` | Ошибка в правах секрета или аннотации | Проверьте, что секрет находится в том же namespace, что и Ingress. |
| Grafana: Пароль не подходит | Кэширование или неверный ключ в секрете | Перезапустите под Grafana: `kubectl rollout restart deployment`. |

### Полезные команды

```bash
# Проверка содержимого секрета (декодирование base64)
kubectl get secret prometheus-web-config -n monitoring -o jsonpath='{.data.web-config\.yaml}' | base64 -d

# Тестирование доступа через curl
curl -v -u admin:mypassword https://prometheus.example.com/-/healthy

# Проверка логов контейнера на ошибки аутентификации
kubectl logs -l app.kubernetes.io/name=prometheus -n monitoring -c prometheus
```

## Дополнительная информация

### Рекомендации (Best Practices)

1.  **Никакой Basic Auth без TLS.** Это базовое требование безопасности.
2.  **Используйте OAuth/OIDC для Grafana.** Это позволяет внедрить MFA и централизованно управлять пользователями.
3.  **Принцип минимальных привилегий.** Используйте разные секреты для разных компонентов.
4.  **NetworkPolicy.** В дополнение к авторизации ограничьте доступ к портам 9090 и 9093 на уровне сети.
5.  **Ротация секретов.** Используйте внешние инструменты (например, Vault) для автоматической смены паролей.

### Связанные ресурсы

* [Безопасность Prometheus Operator](../../operator/Security/index.md) — детальные примеры YAML.
* [Grafana User Management](../../../../Grafana/grafana_user_management_and_authentication.md) — OAuth, LDAP, SAML.
* [Secrets Best Practices](../../operator/Security/secrets_best_practices.md) — хранение секретов.
* [HTTP Authentication Theory](../../../../Networking/Protocols/HTTP/http_authentication.md).
