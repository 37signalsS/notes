# Веб-аутентификация для Prometheus, Alertmanager и Grafana (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **Источник темы:** аутентификация веб-интерфейсов Prometheus, Alertmanager и Grafana в kube-prometheus-stack.  
> **Смежные темы:** [Безопасность Prometheus Operator](../../operator/Security/index.md) — YAML-примеры встроенной auth, Ingress Basic Auth, TLS; [Access Control](../../operator/Security/access_control.md) — NetworkPolicies, RBAC; [HTTP Authentication](../../../../Networking/Protocols/HTTP/http_authentication.md) — теория Basic/Digest/Bearer auth.

## Определения

**Веб-аутентификация Prometheus** — ограничение доступа к веб-интерфейсу Prometheus (`/graph`, `/api/v1/*`, `/targets`). По умолчанию Prometheus **не требует** аутентификации. Начиная с версии v2.24+ поддерживается нативная аутентификация через файл конфигурации (`--web.config.file`), что позволяет защитить интерфейс без внешних прокси.

**Веб-аутентификация Alertmanager** — ограничение доступа к UI Alertmanager (`/#/alerts`, `/api/v2/*`). Также поддерживает нативную аутентификацию через файл конфигурации. Без неё защита возможна только на уровне Ingress/Reverse Proxy.

**Веб-аутентификация Grafana** — встроенная система управления пользователями с поддержкой локальных учётных записей, OAuth (Google, GitHub, GitLab, OIDC), LDAP и SAML.

**Basic Auth** — метод HTTP-аутентификации (RFC 7617), передающий учётные данные в заголовке `Authorization`. **Критически важно:** Basic Auth без TLS передаёт пароли в кодировке base64, что эквивалентно открытому тексту. TLS обязателен для любой промышленной инсталляции.

**OAuth2-proxy** — прокси-сервис, который обеспечивает аутентификацию через внешний Identity Provider (IdP) и передаёт авторизованные запросы к целевому приложению (Prometheus/Alertmanager) через заголовок `X-Forwarded-User`. Используется, когда целевой компонент не поддерживает OIDC/SAML нативно.

**Mutual TLS (mTLS)** — режим TLS, при котором обе стороны (клиент и сервер) предъявляют и проверяют сертификаты. В контексте Prometheus используется для защиты внутреннего трафика между компонентами (например, Prometheus → Alertmanager), чтобы предотвратить подмену и перехват метрик.

**NetworkPolicy** — объект Kubernetes, управляющий сетевым доступом на L3/L4 уровне. В контексте аутентификации используется как второй эшелон защиты: даже если веб-аутентификация скомпрометирована, сетевая изоляция ограничивает круг адресатов.

**cert-manager** — компонент Kubernetes для автоматического управления сертификатами TLS. Интегрируется с Ingress-контроллерами и может автоматически выпускать и обновлять сертификаты для веб-интерфейсов мониторинга.

## Основные концепции

### Матрица методов аутентификации (2024–2025)

| Компонент | Нативная Basic Auth | Ingress Basic Auth | OAuth / OIDC | TLS (HTTPS) |
|---|---|---|---|---|
| **Prometheus** | Да (`spec.web.webConfig`) | Да (NGINX/Traefik) | Через Oauth2-proxy | Обязательно |
| **Alertmanager** | Да (`spec.web.webConfig`) | Да (NGINX/Traefik) | Через Oauth2-proxy | Обязательно |
| **Grafana** | Да (встроенная) | Да (избыточно) | Да (нативно) | Обязательно |

### Архитектура потоков аутентификации

```
Внешний пользователь
    │
    ▼
[Ingress Controller] ── L7: аннотации auth, TLS termination
    │
    ├──► [OAuth2-proxy] ──► Identity Provider (IdP)
    │         │
    │         ▼
    │    X-Forwarded-User
    │         │
    ▼         ▼
[Prometheus / Alertmanager / Grafana] ── L4: NetworkPolicy
    │
    ├── Нативная Basic Auth (web-config.yaml)
    ├── mTLS (внутренний трафик Alertmanager ↔ Prometheus)
    └── Kubernetes Secrets (учётные данные)
```

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

### Изменения в Prometheus 3.0 и Operator v0.80+

Начиная с Operator v0.80+, конфигурация веб-аутентификации и TLS выполняется через блок `spec.web`. Новые флаги валидации имён метрик (`--name-validation-scheme`) могут влиять на работу Admission Webhook при миграции. Prometheus 3.0 также вводит расширенную поддержку OTLP и JWT Bearer Grant для OAuth2, что расширяет возможности интеграции с корпоративными Identity Provider.

### Управление доступом к API vs веб-интерфейс

Веб-аутентификация (`--web.config.file`) контролирует доступ к HTML-интерфейсу и一部分 API. Однако административные API (`/api/v1/status/*`, `/api/v1/metadata`) и Remote Read/Write могут требовать отдельной настройки. При включении Basic Auth убедитесь, что сервисные учётные записи (Service Accounts) и sidecar-компоненты (например, Grafana) имеют действительные `basicAuth` секреты для programmatic-доступа.

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

**Шаг 4: Проверка**
```bash
# Ожидаемый результат: 200 OK при передаче корректных учетных данных
curl -v -u admin:secure_password https://prometheus.example.com/-/healthy
# → HTTP/2 200
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

**Шаг 3: Проверка доставки алерта**
```bash
# Создание тестового алерта и проверка, что он доставляется
curl -X POST http://prometheus:9090/api/v1/alerts \
  -d '{"alerts":[{"labels":{"alertname":"test","severity":"warning"},"annotations":{"summary":"test"},"generatorURL":"http://prometheus:9090"}]}'
# Проверка логов Alertmanager на отсутствие 401
kubectl logs -l app.kubernetes.io/name=alertmanager -n monitoring -c alertmanager | grep -i "unauthorized"
# → (пустой вывод — успех)
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

**Шаг 3: Проверка**
```bash
# Ожидаемый результат: 401 при отсутствии credentials, 200 при наличии
curl -v https://prometheus.example.com/-/healthy
# → HTTP/2 401

curl -v -u admin:mypassword https://prometheus.example.com/-/healthy
# → HTTP/2 200
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

**Проверка входа:**
```bash
# Получение CSRF-токена и проверка авторизации
curl -c cookies -b cookies https://grafana.example.com/login
# → HTML-форма входа

curl -c cookies -b cookies -X POST https://grafana.example.com/login \
  -d "user=admin&password=<RANDOM_PASSWORD>"
# → HTTP/2 302 (редирект на /)
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

**Проверка TLS:**
```bash
# Ожидаемый результат: сертификат соответствует домену, протокол TLS 1.3
curl -v https://prometheus.example.com/-/healthy 2>&1 | grep -E "SSL connection|subject:|issuer:"
# → SSL connection using TLSv1.3 / TLS_AES_256_GCM_SHA384
# → subject: CN=prometheus.example.com
```

### Сценарий 6: OAuth2-proxy для Prometheus и Alertmanager

Используется, когда Prometheus/Alertmanager не имеют встроенной поддержки OIDC/SAML. OAuth2-proxy выступает как reverse proxy, проверяющий identity через внешний IdP и передающий идентификатор пользователя в заголовке.

**Шаг 1: Создание Secret для OAuth2-credentials**
```bash
kubectl create secret generic oauth2-proxy-secret \
  --from-literal=client-id="prometheus-oauth" \
  --from-literal=client-secret="<CLIENT_SECRET>" \
  --from-literal=cookie-secret="$(openssl rand -base64 32)" \
  -n monitoring
```

**Шаг 2: Деплой OAuth2-proxy (standalone)**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oauth2-proxy
  namespace: monitoring
spec:
  replicas: 2
  selector:
    matchLabels:
      app: oauth2-proxy
  template:
    metadata:
      labels:
        app: oauth2-proxy
    spec:
      containers:
        - name: oauth2-proxy
          image: quay.io/oauth2-proxy/oauth2-proxy:v0.15.0
          args:
            - --provider=google
            - --email-domains=*
            - --upstream=http://prometheus-operated:9090
            - --http-address=0.0.0.0:4180
            - --cookie-secret=$(COOKIE_SECRET)
            - --client-id=$(CLIENT_ID)
            - --client-secret=$(CLIENT_SECRET)
          env:
            - name: CLIENT_ID
              valueFrom:
                secretKeyRef:
                  name: oauth2-proxy-secret
                  key: client-id
            - name: CLIENT_SECRET
              valueFrom:
                secretKeyRef:
                  name: oauth2-proxy-secret
                  key: client-secret
            - name: COOKIE_SECRET
              valueFrom:
                secretKeyRef:
                  name: oauth2-proxy-secret
                  key: cookie-secret
          ports:
            - containerPort: 4180
```

**Шаг 3: Настройка Ingress с перенаправлением на OAuth2-proxy**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: prometheus-ingress
  namespace: monitoring
  annotations:
    nginx.ingress.kubernetes.io/auth-url: "http://oauth2-proxy.monitoring.svc.cluster.local:4180/oauth2/auth"
    nginx.ingress.kubernetes.io/auth-signin: "http://$host/oauth2/start?rd=$escaped_request_uri"
spec:
  ingressClassName: nginx
  tls:
    - secretName: prometheus-tls-cert
      hosts:
        - prometheus.example.com
  rules:
    - host: prometheus.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: prometheus-operated
                port:
                  number: 9090
```

**Шаг 4: Проверка**
```bash
# Ожидаемый результат: редирект на страницу авторизации IdP, затем доступ к Prometheus
curl -v https://prometheus.example.com/
# → HTTP/2 302 Location: https://accounts.google.com/...
```

### Сценарий 7: Grafana — Нативная настройка OAuth/LDAP/SAML через provisioning

Grafana поддерживает нативную аутентификацию через конфигурационные файлы provisioning. Это позволяет хранить конфиг в Git и автоматически применять его при старте.

**Шаг 1: Создание ConfigMap с конфигурацией аутентификации**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-auth-config
  namespace: monitoring
data:
  auth_generic_oauth.yaml: |
    apiVersion: 1
    providers:
      - name: OAuth
        type: oauth
        enabled: true
        client_id: "grafana"
        client_secret: "<CLIENT_SECRET>"
        scopes: "openid profile email"
        auth_url: "https://auth.example.com/oauth2/authorize"
        token_url: "https://auth.example.com/oauth2/token"
        api_url: "https://auth.example.com/userinfo"
        allow_sign_up: true
        skip_org_role_sync: false
        role_attribute_path: "contains(groups, 'grafana-admins') && 'Admin' || 'Viewer'"
```

**Шаг 2: Настройка монтирования в values.yaml**
```yaml
grafana:
  sidecar:
    dashboards:
      enabled: true
  extraConfigmapMounts:
    - name: grafana-auth-config
      mountPath: /etc/grafana/provisioning/auth
      configMap: grafana-auth-config
      readOnly: true
```

**Шаг 3: Проверка**
```bash
# Проверка загрузки конфигурации в логах Grafana
kubectl logs -l app.kubernetes.io/name=grafana -n monitoring -c grafana | grep -i "oauth\|auth"
# → t=2026-09-17 lvl=info msg="Starting OAuth authentication"
```

### Сценарий 8: Автоматический TLS через cert-manager

Автоматическая выдача и обновление сертификатов для всех веб-интерфейсов.

**Шаг 1: Создание ClusterIssuer (self-signed или ACME)**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: selfsigned-issuer
spec:
  selfSigned: {}
```

**Шаг 2: Создание сертификата для Prometheus**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: prometheus-tls
  namespace: monitoring
spec:
  secretName: prometheus-tls-cert
  issuerRef:
    name: selfsigned-issuer
    kind: ClusterIssuer
  commonName: prometheus.example.com
  dnsNames:
    - prometheus.example.com
    - alertmanager.example.com
    - grafana.example.com
```

**Шаг 3: Ссылка на секрет в Ingress**
```yaml
prometheus:
  ingress:
    enabled: true
    tls:
      - secretName: prometheus-tls-cert
        hosts:
          - prometheus.example.com
```

**Шаг 4: Проверка обновления сертификата**
```bash
# Проверка срока действия сертификата
kubectl get certificate prometheus-tls -n monitoring
# → NAME             READY   SECRET               AGE
# → prometheus-tls   True    prometheus-tls-cert  5d

# Проверка, что cert-manager обновит сертификат до истечения срока
kubectl describe certificate prometheus-tls -n monitoring | grep -A5 "Events"
# → ... Renewal triggered 15 days before expiry
```

### Сценарий 9: Ограничение доступа через NetworkPolicy

Даже при наличии веб-аутентификации, сетевая изоляция ограничивает круг адресатов и снижает поверхность атаки.

**Шаг 1: Default-deny политика для namespace monitoring**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```

**Шаг 2: Разрешение Ingress-контроллеру и Grafana**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ingress-to-prometheus
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: grafana
      ports:
        - protocol: TCP
          port: 9090
```

**Шаг 3: Проверка**
```bash
# Проверка, что доступ к Prometheus с неавторизованного пода запрещён
kubectl run test-pod --image=busybox --rm -it --restart=Never -- sh
# wget -qO- http://prometheus-operated:9090/-/healthy
# → wget: bad HTTP response
```

### Сценарий 10: mTLS между Prometheus и Alertmanager

Защита внутреннего трафика, чтобы предотвратить подмену Alertmanager и перехват алертов.

**Шаг 1: Создание сертификатов (через cert-manager или вручную)**
```bash
# Генерация CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt \
  -subj "/CN=Monitoring CA"

# Генерация сертификата для Alertmanager
openssl genrsa -out alertmanager.key 2048
openssl req -new -key alertmanager.key -out alertmanager.csr \
  -subj "/CN=alertmanager-operated.monitoring.svc.cluster.local"
openssl x509 -req -in alertmanager.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out alertmanager.crt -days 365 -sha256
```

**Шаг 2: Создание Secrets с сертификатами**
```bash
kubectl create secret tls alertmanager-tls \
  --cert=alertmanager.crt \
  --key=alertmanager.key \
  -n monitoring

kubectl create secret generic alertmanager-ca \
  --from-file=ca.crt=ca.crt \
  -n monitoring
```

**Шаг 3: Настройка в values.yaml**
```yaml
alertmanager:
  alertmanagerSpec:
    web:
      tlsConfig:
        cert:
          secret:
            name: alertmanager-tls
            key: tls.crt
        keySecret:
          name: alertmanager-tls
          key: tls.key
        clientCa:
          secret:
            name: alertmanager-ca
            key: ca.crt
```

**Шаг 4: Настройка Prometheus для проверки сертификата Alertmanager**
```yaml
prometheus:
  prometheusSpec:
    alerting:
      alertmanagers:
        - namespace: monitoring
          name: alertmanager-operated
          port: web
          scheme: https
          tlsConfig:
            caFile: /etc/alertmanager/ca/ca.crt
          # basicAuth остается тем же, что и в сценарии 2
```

### Сценарий 11: Ротация секретов через External Secrets Operator (ESO)

Автоматическая ротация паролей без перезапуска подов.

**Шаг 1: Создание SecretStore**
```yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: vault-backend
  namespace: monitoring
spec:
  provider:
    vault:
      server: "https://vault.example.com"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "monitoring"
```

**Шаг 2: Создание ExternalSecret для Prometheus auth**
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: prometheus-web-config
  namespace: monitoring
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: prometheus-web-config
    creationPolicy: Owner
  data:
    - secretKey: web-config.yaml
      remoteRef:
        key: monitoring/prometheus
        property: web-config.yaml
```

**Шаг 3: Проверка**
```bash
# ESO автоматически обновит Secret при изменении в Vault
kubectl get secret prometheus-web-config -n monitoring -o jsonpath='{.data.web-config\.yaml}' | base64 -d | head -5
# → basic_auth_users:
# →   admin: "$2b$12$..."

# Проверка событий ExternalSecret
kubectl describe externalsecret prometheus-web-config -n monitoring | grep -A5 "Events"
# → ... Secret synchronized successfully
```

## Диагностика и отладка

### Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| Бесконечный запрос логина | Неверный алгоритм хэширования в Secret | Используйте только Bcrypt для нативной auth. |
| Prometheus: `401 Unauthorized` при отправке алерта | Отсутствует `basicAuth` в конфиге алертинга | Добавьте учетные данные в `alerting.alertmanagers`. |
| Ingress: `403 Forbidden` | Ошибка в правах секрета или аннотации | Проверьте, что секрет находится в том же namespace, что и Ingress. |
| Grafana: Пароль не подходит | Кэширование или неверный ключ в секрете | Перезапустите под Grafana: `kubectl rollout restart deployment`. |
| OAuth2-proxy: редирект в цикле | Неверный `cookie-secret` или `redirect-uri` | Проверьте, что `cookie-secret` стабилен (не меняется при каждом деплое). |
| mTLS: `certificate verify failed` | Отсутствует CA в `caFile` или неверный CN | Проверьте CN сертификата = FQDN сервиса. |
| NetworkPolicy: `Connection refused` | Политика блокирует Ingress-контроллер | Добавьте `namespaceSelector` для namespace Ingress. |
| cert-manager: `Certificate not ready` | Отсутствует ClusterIssuer или DNS-запись | Проверьте `kubectl describe certificate` и DNS propagation. |

### Полезные команды

```bash
# Проверка содержимого секрета (декодирование base64)
kubectl get secret prometheus-web-config -n monitoring -o jsonpath='{.data.web-config\.yaml}' | base64 -d

# Тестирование доступа через curl
curl -v -u admin:mypassword https://prometheus.example.com/-/healthy

# Проверка логов контейнера на ошибки аутентификации
kubectl logs -l app.kubernetes.io/name=prometheus -n monitoring -c prometheus

# Проверка конфигурации OAuth2-proxy
kubectl logs -l app=oauth2-proxy -n monitoring | grep -i "error\|unauthorized"

# Проверка TLS-сертификата
openssl s_client -connect prometheus.example.com:443 -servername prometheus.example.com </dev/null 2>/dev/null | openssl x509 -noout -dates -subject

# Проверка NetworkPolicy
kubectl describe networkpolicy allow-ingress-to-prometheus -n monitoring

# Проверка, что Prometheus видит Alertmanager с корректным basicAuth
kubectl exec -it prometheus-main-0 -n monitoring -- wget -qO- http://alertmanager-operated:9093/-/healthy
# → "OK" (при корректной mTLS и auth)
```

## Валидация после внедрения

После каждого сценария выполните следующие проверки:

1. **Доступность UI**: `curl -v https://<component>.example.com/` возвращает `200 OK` при корректных учётных данных и `401/403` при их отсутствии.
2. **Секреты созданы**: `kubectl get secret <secret-name> -n monitoring` — секрет существует и имеет тип `Opaque`.
3. **Логи чистые**: `kubectl logs -l app.kubernetes.io/name=<component> -n monitoring` — отсутствуют ошибки `unauthorized`, `forbidden`, `certificate verify failed`.
4. **NetworkPolicy активна**: `kubectl get networkpolicy -n monitoring` — политики применены.
5. **TLS валиден**: `openssl s_client -connect <host>:443` — сертификат не истёк, CN/SAN совпадают с хостом.
6. **Алерты доставляются**: создайте тестовый алерт и убедитесь, что он появляется в Alertmanager UI.

## Откат и очистка

### Откат изменений

```bash
# Удаление Secret с веб-конфигурацией
kubectl delete secret prometheus-web-config -n monitoring

# Откат values.yaml до исходного состояния (удалите блоки web, webConfig, ingress)
# Переinstall helm-релиз с флагом --reuse-values
helm upgrade prometheus prometheus-community/kube-prometheus-stack \
  -f values.yaml \
  --reuse-values \
  -n monitoring

# Удаление Ingress
kubectl delete ingress prometheus-ingress -n monitoring
```

### Очистка окружения

```bash
# Удаление всех ресурсов, созданных в рамках сценариев
kubectl delete secret --all -n monitoring --field-selector=type=Opaque
kubectl delete configmap grafana-auth-config -n monitoring
kubectl delete certificate prometheus-tls -n monitoring
kubectl delete clusterissuer selfsigned-issuer
kubectl delete deployment oauth2-proxy -n monitoring
kubectl delete networkpolicy --all -n monitoring
```

## Пограничные случаи

| Случай | Поведение | Рекомендация |
|---|---|---|
| **Single-node кластер** | NetworkPolicy работает, но Ingress-контроллер может быть недоступен | Используйте `hostNetwork: true` для Ingress или NodePort. |
| **Read-only файловая система** | Prometheus не может записать `web-config.yaml`, если он смонтирован как readOnly | Убедитесь, что `webConfig` Secret смонтирован как read-write (по умолчанию). |
| **PVC >1Ti с `WaitForFirstConsumer`** | Prometheus не запустится, если StorageClass не поддерживает `WaitForFirstConsumer` | Используйте локальный путь или измените `volumeBindingMode` на `Immediate`. |
| **WAL corruption при аварийном отключении** | Prometheus стартует с пустым WAL, метрики за последние 2 часа потеряны | Настройте `--storage.tsdb.min-block-duration` и `--storage.tsdb.max-block-duration` для частого сброса блоков. |
| **etcd v2 (устаревший)** | Operator v0.70+ требует etcd v3; миграция обязательна | Обновите кластер до etcd v3 перед установкой. |
| **Prometheus 3.0 + legacy validation** | При использовании старых дашбордов с кириллицей в именах метрик возможен отказ Admission Webhook | Установите аргумент `--name-validation-scheme=legacy` в deployment Operator. |
| **Grafana: сброс пароля admin** | При утечке пароля admin требуется сброс без доступа к UI | `kubectl exec -it <grafana-pod> -n monitoring -- grafana-cli admin password <new_password>` |
| **Alertmanager auth rotation** | При смене пароля в Secret Alertmanager перезапускается, алерты могут потеряться на 10-30с | Используйте rolling update с `maxUnavailable: 0` и preStop hook для drain. |
| **OAuth2-proxy за firewall** | IdP недоступен из кластера, OAuth2-proxy возвращает `502` | Разрешите egress к доменам IdP через NetworkPolicy или NAT gateway. |
| **mixed auth (Ingress + native)** | Двойная аутентификация может привести к путанице и двойным запросам credentials | Выбирайте один уровень: либо Ingress, либо нативный. |

## Рекомендации (Best Practices)

1.  **Никакой Basic Auth без TLS.** Это базовое требование безопасности.
2.  **Используйте OAuth/OIDC для Grafana.** Это позволяет внедрить MFA и централизованно управлять пользователями.
3.  **Принцип минимальных привилегий.** Используйте разные секреты для разных компонентов.
4.  **NetworkPolicy.** В дополнение к авторизации ограничьте доступ к портам 9090 и 9093 на уровне сети.
5.  **Ротация секретов.** Используйте внешние инструменты (ESO, Vault) для автоматической смены паролей.
6.  **Изоляция namespace monitoring.** Default-deny NetworkPolicy + разрешение только для необходимых источников.
7.  **mTLS для внутреннего трафика.** Защищайте Alertmanager ↔ Prometheus и Prometheus → Remote Write через mTLS.
8.  **cert-manager для TLS.** Избегайте ручной выдачи сертификатов; автоматизируйте через cert-manager.
9.  **Валидация после каждого изменения.** Всегда проверяйте доступность UI, чистоту логов и доставку алертов.
10. **Резервное копирование секретов.** Регулярно экспортируйте Secrets из namespace monitoring в защищённое хранилище.

### Связанные ресурсы

* [Безопасность Prometheus Operator](../../operator/Security/index.md) — детальные примеры YAML.
* [Grafana User Management](../../../../Grafana/grafana_user_management_and_authentication.md) — OAuth, LDAP, SAML.
* [Secrets Best Practices](../../operator/Security/secrets_best_practices.md) — хранение секретов.
