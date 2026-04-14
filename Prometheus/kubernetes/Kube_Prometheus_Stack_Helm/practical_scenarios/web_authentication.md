# Web Authentication for Prometheus, Alertmanager, Grafana (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** аутентификация веб-интерфейсов Prometheus, Alertmanager и Grafana в kube-prometheus-stack.  
> **Смежные темы:** [Prometheus Operator Security](../../operator/Security/index.md) — YAML-примеры встроенной auth, Ingress Basic Auth, TLS; [Access Control](../../operator/Security/access_control.md) — NetworkPolicies, RBAC; [HTTP Authentication](../../../../Networking/Protocols/HTTP/http_authentication.md) — теория Basic/Digest/Bearer auth.

## Definitions

**Веб-аутентификация Prometheus** — механизм ограничения доступа к веб-интерфейсу Prometheus (`/graph`, `/api/v1/*`, `/targets`). По умолчанию Prometheus **не требует** аутентификации — любой, кто имеет доступ к порту 9090, может просматривать все метрики и выполнять произвольные PromQL-запросы.

**Веб-аутентификация Alertmanager** — ограничение доступа к UI Alertmanager (`/#/alerts`, `/api/v2/*`). Alertmanager **не имеет встроенной аутентификации**; защита возможна только на уровне reverse proxy (Ingress).

**Веб-аутентификация Grafana** — встроенная система аутентификации с поддержкой локальных пользователей, OAuth, LDAP, SAML. Графана — единственный компонент стека с полноценной многопользовательской системой доступа.

**Basic Auth** — простейшая HTTP-аутентификация (RFC 7617). Логин и пароль передаются в заголовке `Authorization: Basic <base64>`. Без TLS — пароли передаются в открытом виде.

## Basic Concepts

### Матрица аутентификации компонентов

| Компонент | Встроенная auth | Ingress Basic Auth | OAuth/LDAP | TLS |
|---|---|---|---|---|
| **Prometheus** | Да (через `web.webConfig.basicAuth`, v2.48+) | Да (nginx/traefik) | Нет | Да (mTLS для scrape) |
| **Alertmanager** | **Нет** | Да (nginx/traefik) | Нет | Да (Ingress TLS) |
| **Grafana** | Да (локальные пользователи) | Возможно (но избыточно) | Да (GitHub, GitLab, Google, OIDC, LDAP, SAML) | Да (Ingress TLS) |

### Три уровня защиты

```
Уровень 1: Сетевая изоляция (наиболее безопасный)
    └── Prometheus в закрытом контуре, доступ только через VPN
    └── Нет внешних Ingress, нет публичных IP

Уровень 2: Ingress Basic Auth (компромисс)
    └── NGINX/Traefik Ingress с basic auth annotations
    └── Подходит для всех компонентов, включая Alertmanager

Уровень 3: Нативная аутентификация (Prometheus v2.48+)
    └── Prometheus: web.webConfig.basicAuth
    └── Grafana: встроенная система пользователей
    └── Alertmanager: только Ingress (нет native auth)
```

### Безопасность через obscurity — почему недостаточен «закрытый контур»

Даже в закрытом контуре с VPN:

- Любой с доступом к VPN получает полный доступ к метрикам (включая секреты, которые могут быть в label'ах)
- PromQL позволяет извлечь чувствительные данные (токены, ключи из configmap через `kube_secret_*`)
- Для compliance (PCI DSS, SOC 2) аутентификация обязательна независимо от сетевой изоляции

## Practical Scenarios

### Сценарий 1: Prometheus — встроенная Basic Auth (нативная, v2.48+)

**Задача:** Включить нативную аутентификацию Prometheus без reverse proxy.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    web:
      webConfig:
        basicAuth:
          username:
            name: prometheus-auth
            key: username
          password:
            name: prometheus-auth
            key: password
```

**Создание Secret:**

```bash
kubectl create secret generic prometheus-auth \
  --from-literal=username="admin" \
  --from-literal=password="$(openssl rand -base64 20)" \
  -n monitoring
```

> **YAML-примеры и детали:** [Prometheus Operator Security — Встроенная аутентификация](../../operator/Security/index.md).

### Сценарий 2: Prometheus — Ingress Basic Auth (nginx)

**Задача:** Защитить Prometheus через NGINX Ingress с htpasswd.

```yaml
# values.yaml
prometheus:
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - prometheus.k8s.domain.local
    annotations:
      nginx.ingress.kubernetes.io/auth-type: basic
      nginx.ingress.kubernetes.io/auth-secret: prometheus-auth
      nginx.ingress.kubernetes.io/auth-realm: "Authentication Required"
```

**Создание htpasswd-секрета:**

```bash
# Генерация htpasswd файла
htpasswd -cb auth admin 'your-secure-password'

# Создание Kubernetes Secret
kubectl create secret generic prometheus-auth --from-file=auth -n monitoring
```

> **YAML-примеры и детали:** [Prometheus Operator Security — Ingress Basic Auth](../../operator/Security/index.md).

### Сценарий 3: Alertmanager — Ingress Basic Auth (единственный вариант)

**Задача:** Защитить Alertmanager, у которого нет встроенной аутентификации.

```yaml
# values.yaml
alertmanager:
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - alertmanager.k8s.domain.local
    annotations:
      nginx.ingress.kubernetes.io/auth-type: basic
      nginx.ingress.kubernetes.io/auth-secret: alertmanager-auth
      nginx.ingress.kubernetes.io/auth-realm: "Authentication Required"
```

```bash
htpasswd -cb auth admin 'alertmanager-password'
kubectl create secret generic alertmanager-auth --from-file=auth -n monitoring
```

> **Важно:** Alertmanager **не имеет** встроенной аутентификации. Ingress Basic Auth — единственный способ защитить веб-интерфейс.

### Сценарий 4: Grafana — кастомный пароль администратора

**Задача:** Переопределить автосгенерированный пароль Grafana.

```yaml
# values.yaml
grafana:
  adminPassword: "my-secure-password"  # Простой вариант (не для production)
```

**Production-вариант — через Secret:**

```yaml
# values.yaml
grafana:
  admin:
    existingSecret: grafana-admin-secret
    userKey: admin-user
    passwordKey: admin-password
```

```bash
kubectl create secret generic grafana-admin-secret \
  --from-literal=admin-user="admin" \
  --from-literal=admin-password="$(openssl rand -base64 20)" \
  -n monitoring
```

> **YAML-примеры и детали:** [Prometheus Operator Security — Grafana](../../operator/Security/index.md).  
> **OAuth/LDAP в Grafana:** [Grafana User Management](../../../../Grafana/grafana_user_management_and_authentication.md).

### Сценарий 5: Grafana — OAuth (GitHub/GitLab/Google)

**Задача:** Настроить единый вход через корпоративный провайдер.

```yaml
# values.yaml
grafana:
  grafana.ini:
    auth.github:
      enabled: true
      allow_sign_up: true
      client_id: ${GITHUB_CLIENT_ID}
      client_secret: ${GITHUB_CLIENT_SECRET}
      scopes: user:email,read:org
      auth_url: https://github.com/login/oauth/authorize
      token_url: https://github.com/login/oauth/access_token
      api_url: https://api.github.com/user
      allowed_organizations: my-company
```

> **Подробнее:** [Grafana OAuth и LDAP](../../../../Grafana/grafana_user_management_and_authentication.md) — полный обзор OAuth, SAML, LDAP, сервисных аккаунтов.

### Сценарий 6: Ingress с TLS для всех компонентов

**Задача:** Шифрование трафика через HTTPS (обязательно при Basic Auth).

```yaml
# values.yaml — Prometheus
prometheus:
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - prometheus.k8s.domain.local
    tls:
      - secretName: prometheus-tls
        hosts:
          - prometheus.k8s.domain.local

# values.yaml — Grafana
grafana:
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - grafana.k8s.domain.local
    tls:
      - secretName: grafana-tls
        hosts:
          - grafana.k8s.domain.local
```

> **Важно:** Basic Auth **без TLS** передаёт пароли в base64 (эквивалент открытого текста). TLS обязателен для production.

### Сценарий 7: Закрытый контур (air-gapped) — максимальная изоляция

**Задача:** Prometheus без внешнего доступа — только через VPN.

```yaml
# values.yaml — без Ingress
prometheus:
  ingress:
    enabled: false  # Доступ только через port-forward или VPN

alertmanager:
  ingress:
    enabled: false

grafana:
  ingress:
    enabled: false
```

**Доступ через port-forward:**

```bash
kubectl port-forward -n monitoring svc/kube-prometheus-grafana 3000:80
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090
```

> **Связано:** [Offline Air-gapped Installation](./offline_airgapped_installation.md).

## Additional Information

### Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| Prometheus UI требует auth, но не принимает пароль | Secret не создан или неверный key | `kubectl get secret prometheus-auth -n monitoring -o yaml`; проверить key names |
| Ingress Basic Auth не работает | Secret `auth` не в формате htpasswd | Пересоздать: `htpasswd -cb auth admin 'pass'`; `kubectl create secret generic ... --from-file=auth` |
| Grafana «Login failed» после смены пароля | Secret обновлён, но pod не перезагружен | `kubectl rollout restart deployment -n monitoring -l app.kubernetes.io/name=grafana` |
| Alertmanager доступен без auth | `alertmanager.ingress.annotations` без auth-* | Добавить `auth-type`, `auth-secret`, `auth-realm` annotations |
| TLS ошибка в браузере | Self-signed сертификат | Добавить CA в доверенные или использовать cert-manager + Let's Encrypt |

### Диагностика

```bash
# Проверить, что Secret существует
kubectl get secret prometheus-auth -n monitoring
kubectl get secret alertmanager-auth -n monitoring
kubectl get secret grafana-admin-secret -n monitoring

# Проверить содержимое Secret (base64)
kubectl get secret prometheus-auth -n monitoring -o jsonpath='{.data}' | jq

# Проверить Ingress annotations
kubectl get ingress -n monitoring -o yaml | grep -A 3 auth

# Протестировать Basic Auth curl'ом
curl -u admin:password https://prometheus.k8s.domain.local/-/healthy

# Проверить TLS-сертификат
kubectl get secret prometheus-tls -n monitoring -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout
```

### Best Practices

1. **TLS + Basic Auth — минимум для production** — Basic Auth без TLS = пароли в открытом виде.
2. **Alertmanager — только Ingress auth** — встроенной аутентификации нет; всегда защищайте через reverse proxy.
3. **Grafana OAuth > Basic Auth** — для корпоративной среды используйте OAuth/LDAP вместо htpasswd.
4. **Отдельные Secrets для каждого компонента** — не переиспользуйте один Secret для Prometheus, Alertmanager и Grafana.
5. **Регулярно ротируйте пароли** — минимум раз в 90 дней для production.
6. **NetworkPolicy как дополнительный слой** — даже с auth, ограничьте доступ к pod'ам на уровне сети.
7. **Не храните пароли в values.yaml** — используйте Kubernetes Secrets + `existingSecret`/`existingSecret` паттерн.

### Связанные ресурсы

| Ресурс | Описание |
|---|---|
| [Prometheus Operator Security](../../operator/Security/index.md) — YAML-примеры: встроенная auth, Ingress Basic Auth, Grafana Secret, TLS, mTLS |
| [Access Control (NetworkPolicies, RBAC)](../../operator/Security/access_control.md) — сетевой контроль доступа |
| [Secrets Best Practices](../../operator/Security/secrets_best_practices.md) — управление секретами Alertmanager (slack, pagerduty, smtp) |
| [Grafana User Management](../../../../Grafana/grafana_user_management_and_authentication.md) — OAuth, LDAP, SAML, сервисные аккаунты, API-ключи |
| [HTTP Authentication Theory](../../../../Networking/Protocols/HTTP/http_authentication.md) — Basic, Digest, Bearer, SSO |
| [Offline Air-gapped Installation](./offline_airgapped_installation.md) — доступ без внешнего Ingress |
