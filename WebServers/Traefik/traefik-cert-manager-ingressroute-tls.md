# Автоматический TLS с cert-manager, Let's Encrypt и Traefik IngressRoute

**Актуально для:** cert-manager 1.21.x / Traefik 3.7.x

## Определения

**ClusterIssuer** — общекластерный ресурс cert-manager (`cert-manager.io/v1`), описывающий метод взаимодействия и аутентификации с центром сертификации (ACME CA, например Let's Encrypt). Доступен для обслуживания запросов на сертификаты из всех пространств имен кластера.

**Issuer** — ресурс cert-manager с функциональностью, аналогичной `ClusterIssuer`, но изолированный рамками одного пространства имен (`namespaced`).

**Certificate** — декларативный ресурс cert-manager (`cert-manager.io/v1`), определяющий требования к TLS-сертификату (доменные имена SAN, алгоритм и размер закрытого ключа, политика ротации, ссылка на Issuer). Инициирует цепочку согласования: `Certificate → CertificateRequest → Order → Challenge → Secret`.

**IngressRoute** — пользовательский ресурс Traefik (`traefik.io/v1alpha1`), заменяющий стандартный Kubernetes `Ingress`. Предоставляет расширенные возможности маршрутизации L7, привязку Middleware, поддержку TCP/UDP и гибкую конфигурацию TLS-терминации.

**TLSOption** — ресурс Traefik (`traefik.io/v1alpha1`), определяющий параметры TLS-рукопожатия для входящих соединений: минимальную и максимальную версии TLS, наборы шифров (cipher suites), строгую проверку SNI и параметры mTLS.

**Middleware** — ресурс Traefik (`traefik.io/v1alpha1`) для модификации запросов и ответов в конвейере маршрутизации (редиректы, добавление/удаление заголовков, rate limiting, базовая аутентификация).

**HTTP-01 challenge** — протокольный метод ACME (RFC 8555) для подтверждения владения доменным именем. Сервер CA отправляет валидационный HTTP-запрос по пути `http://<domain>/.well-known/acme-challenge/<token>` на порт 80.

**Subject Alternative Name (SAN)** — расширение стандарта X.509, позволяющее защитить единым TLS-сертификатом список нескольких FQDN (доменных имен).

**ACME Order / Challenge** — внутренние вспомогательные CRD cert-manager: `Order` представляет заказ сертификата у ACME-сервера, а `Challenge` отслеживает жизненный цикл и статус конкретной проверки владения доменом.

**Solver Pod (`cert-manager-acmesolver`)** — эфемерный под, развертываемый cert-manager для обслуживания входящих HTTP-запросов ACME-проверки по пути `/.well-known/acme-challenge/*` на локальном порту (по умолчанию 8089).

---

## Основные концепции

### Архитектура связки: cert-manager и Traefik в HA Bare-Metal

В production-окружениях на bare-metal серверах встроенный в Traefik Community механизм ACME (`acme.json`) непригоден для отказоустойчивых инсталляций (High Availability).

```text
[ Let's Encrypt CA ]
        ▲
        │ 1. ACME API (HTTPS:443)
        ▼
[ cert-manager controller ] ──► 2. Создает временный Ingress & Solver Pod (:8089)
        │                                ▲
        │ 3. Сохраняет TLS-сертификат   │ 4. Маршрутизирует /.well-known/acme-challenge/
        ▼                                │    на solver pod через IngressClass "traefik"
[ Kubernetes Secret (tls) ]       [ Traefik Ingress Controller (HA: 3+ реплики) ]
        ▲                                │
        │ Читает сертификат              │ 5. Завершает TLS (443) и маршрутизирует
        └────────────────────────────────┴──► к целевым сервисам приложений (IngressRoute)
```

**Ключевые архитектурные причины разделения:**
1. **Отсутствие распределенных блокировок в Traefik OSS:** При запуске двух и более реплик Traefik встроенный клиент ACME пытается писать в файл `acme.json`, что приводит к гонкам (race conditions), порче файла ключей и исчерпанию rate limits Let's Encrypt.
2. **cert-manager как Single Source of Truth (SSoT):** cert-manager централизованно берет на себя взаимодействие с Let's Encrypt, прохождение проверок, контроль сроков действия и ротацию ключей. Выпущенные сертификаты сохраняются в стандартные Kubernetes Secrets (`kubernetes.io/tls`).
3. **Traefik как Data Plane:** Все реплики Traefik подхватывают Secret из Kubernetes API и монтируют его в память роутера. Масштабирование Traefik до 3, 5 или 10 реплик происходит без накладных расходов на ACME.

### Особенности взаимодействия IngressRoute и cert-manager

Контроллер `ingress-shim` из состава cert-manager предназначен для работы со стандартными объектами `networking.k8s.io/v1 Ingress`. Он отслеживает аннотации вида `cert-manager.io/cluster-issuer` и автоматически генерирует ресурсы `Certificate`.

> [!IMPORTANT]
> `ingress-shim` **не обрабатывает** CRD Traefik `IngressRoute`. Аннотации cert-manager на `IngressRoute` полностью игнорируются. Для выпуска сертификата требуется **явное создание отдельного манифеста `Certificate`**.

Однако при решении проверки HTTP-01 cert-manager создает:
1. Эфемерный под `cert-manager-acmesolver`.
2. Эфемерный Kubernetes Service.
3. Временный стандартный **Kubernetes Ingress** с полем `spec.ingressClassName: traefik`.

Поэтому в конфигурации Traefik на bare-metal **обязан** быть включен провайдер стандартных Ingress (`providers.kubernetesIngress.enabled: true`), даже если все рабочие нагрузки используют исключительно `IngressRoute`.

### Staging и Production Issuer: управление лимитами Let's Encrypt

Публичный ACME CA Let's Encrypt накладывает жесткие лимиты на частоту обращений к Production API. Ошибки в конфигурации DNS или сети при первичном развертывании быстро приводят к временной блокировке домена.

| Параметр лимита | Let's Encrypt Production | Let's Encrypt Staging |
| :--- | :--- | :--- |
| **ACME Directory URL** | `https://acme-v02.api.letsencrypt.org/directory` | `https://acme-staging-v02.api.letsencrypt.org/directory` |
| **Новые сертификаты на домен** | 50 в неделю | 30 000 в неделю |
| **Дубликаты сертификатов (точный набор имен)** | 5 в неделю | 30 000 в неделю |
| **Ошибки авторизации (Failed Validation)** | 5 ошибок на аккаунт/хост в час | 60 ошибок в час |
| **Доверие браузеров и ОС** | Доверенный (ISRG Root X1) | Недоверенный (Fake LE Intermediate X1) |
| **Назначение** | Эксплуатация (Production) | Тестирование конфигурации, отладка сети и DNS |

### Механика HTTP-01 и глобальный редирект HTTP → HTTPS

В production-окружениях Traefik порт 80 (entryPoint `web`) настраивается на безусловный редирект на 443 (entryPoint `websecure`).

При поступлении проверочного запроса Let's Encrypt:
1. Запрос приходит на порт 80: `GET /.well-known/acme-challenge/<token>`.
2. Временный Ingress-ресурс, созданный cert-manager для solver-пода, регистрирует в Traefik маршрут с высоким приоритетом.
3. Если глобальный редирект настроен на уровне entryPoint (`redirections.entryPoint`), Traefik может вернуть HTTP 301/308 на HTTPS.
4. Сервер Let's Encrypt строго следует спецификации ACME (RFC 8555 §8.3): он автоматически переходит по редиректам (до 10 переходов) и **игнорирует невалидные или самоподписанные сертификаты** на порту HTTPS во время проверки HTTP-01.
5. Валидация успешно проходит даже при отсутствии первоначального валидного сертификата на `websecure`.

### Пространства имен и изоляция секретов

По умолчанию Traefik работает с отключенным кросс-неймспейс доступом (`providers.kubernetesCRD.allowCrossNamespace: false`):
- `IngressRoute` в пространстве имен `production` может ссылаться на TLS Secret **только** внутри пространства имен `production`.
- Попытка сослаться на Secret из `default` или `traefik` приведет к ошибке конфигурации роутера и отдаче дефолтного самоподписанного сертификата Traefik.
- Манифест `Certificate` cert-manager должен создаваться в том же пространстве имен, где находится обслуживаемый им `IngressRoute`.

---

## Практические сценарии

### Сценарий 1: Подготовка Traefik v3 на Bare-Metal (Helm values)

Настройка Traefik в кластере Kubernetes на bare-metal серверах (с использованием NodePort, HostPort или MetalLB).

```yaml
# values-traefik.yaml
deployment:
  replicas: 3

ports:
  web:
    port: 8000
    exposedPort: 80
    redirections:
      entryPoint:
        to: websecure
        scheme: https
        permanent: true
        priority: 10
  websecure:
    port: 8443
    exposedPort: 443
    asDefault: true

providers:
  kubernetesCRD:
    enabled: true
    allowCrossNamespace: false
  kubernetesIngress:
    enabled: true
    publishedService:
      enabled: true

# Включение сбора метрик Prometheus
metrics:
  prometheus:
    entryPoint: metrics
    addEntryPointsLabels: true
    addRoutersLabels: true
    addServicesLabels: true
```

Развертывание чарта:

```bash
# Добавление репозитория и установка Traefik
helm repo add traefik https://traefik.github.io/charts
helm repo update
helm upgrade --install traefik traefik/traefik -n traefik --create-namespace -f values-traefik.yaml
# → Release "traefik" has been upgraded. Happy Helming!

# Проверка статуса подов
kubectl get pods -n traefik -l app.kubernetes.io/name=traefik
# → traefik-74f8c9b68d-8j7k2   1/1     Running   0          42s
# → traefik-74f8c9b68d-l9x4z   1/1     Running   0          42s
# → traefik-74f8c9b68d-w2m8q   1/1     Running   0          42s
```

### Сценарий 2: Развертывание ClusterIssuer (Staging и Production)

Создание общекластерных эмитентов Let's Encrypt с привязкой к IngressClass Traefik.

```yaml
# cluster-issuers.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-staging-account-key
    solvers:
      - http01:
          ingress:
            ingressClassName: traefik
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
      - http01:
          ingress:
            ingressClassName: traefik
```

Применение и проверка состояния:

```bash
kubectl apply -f cluster-issuers.yaml
# → clusterissuer.cert-manager.io/letsencrypt-staging created
# → clusterissuer.cert-manager.io/letsencrypt-prod created

# Проверка готовности ClusterIssuer
kubectl get clusterissuer
# → NAME                  READY   AGE
# → letsencrypt-staging   True    15s
# → letsencrypt-prod      True    15s
```

### Сценарий 3: Выпуск SAN-сертификата (ECDSA P-256 + ARI)

Выпуск единого TLS-сертификата для нескольких хостов (SAN) с современным алгоритмом ключа ECDSA и политикой ротации ключа `Always`.

```yaml
# certificate-app.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: app-wildcard-tls
  namespace: default
spec:
  secretName: app-wildcard-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - example.com
    - www.example.com
    - api.example.com
  privateKey:
    algorithm: ECDSA
    encoding: PKCS8
    size: 256
    rotationPolicy: Always
  # При использовании cert-manager 1.21+ с поддержкой ARI (ACME Renewal Information)
  # окно продления координируется автоматически сервером Let's Encrypt.
```

Применение и мониторинг жизненного цикла:

```bash
kubectl apply -f certificate-app.yaml
# → certificate.cert-manager.io/app-wildcard-tls created

# Контроль прохождения заказа и выпуска
kubectl get certificate app-wildcard-tls -n default
# → NAME               READY   SECRET             AGE
# → app-wildcard-tls   True    app-wildcard-tls   45s

# Детализация состояния через cmctl
cmctl status certificate app-wildcard-tls -n default
# → Certificate: Ready=True, Secret: app-wildcard-tls, Not After: 2026-11-15T08:30:00Z
```

### Сценарий 4: Привязка сертификата к IngressRoute с TLSOption и Middleware

Комплексная настройка L7-роутинга Traefik: завершение TLS с привязкой сертификата, применение жестких параметров шифрования (`TLSOption`) и канонического редиректа `www` на основной домен.

```yaml
# app-routing-tls.yaml
apiVersion: traefik.io/v1alpha1
kind: TLSOption
metadata:
  name: modern-tls-policy
  namespace: default
spec:
  minVersion: VersionTLS12
  sniStrict: true
  cipherSuites:
    - TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256
    - TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384
    - TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: redirect-www-to-root
  namespace: default
spec:
  redirectRegex:
    regex: "^https://www\\.example\\.com/(.*)"
    replacement: "https://example.com/${1}"
    permanent: true
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: security-headers
  namespace: default
spec:
  headers:
    stsSeconds: 63072000
    stsIncludeSubdomains: true
    stsPreload: true
    frameDeny: true
    contentTypeNosniff: true
    browserXssFilter: true
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: app-ingressroute
  namespace: default
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`example.com`)
      kind: Rule
      middlewares:
        - name: security-headers
      services:
        - name: app-backend-service
          port: 8080
    - match: Host(`www.example.com`)
      kind: Rule
      middlewares:
        - name: redirect-www-to-root
      services:
        - name: app-backend-service
          port: 8080
  tls:
    secretName: app-wildcard-tls
    options:
      name: modern-tls-policy
      namespace: default
```

Проверка применения:

```bash
kubectl apply -f app-routing-tls.yaml
# → tlsoption.traefik.io/modern-tls-policy created
# → middleware.traefik.io/redirect-www-to-root created
# → middleware.traefik.io/security-headers created
# → ingressroute.traefik.io/app-ingressroute created

# Проверка доступности и сертификата через curl
curl -Iv https://example.com/healthz
# → * Server certificate:
# → *  subject: CN=example.com
# → *  issuer: C=US, O=Let's Encrypt, CN=R3
# → *  SSL connection using TLSv1.3 / TLS_AES_128_GCM_SHA256
# → HTTP/2 200
```

### Сценарий 5: Сетевая безопасность (NetworkPolicy) в On-Premise CNI

В защищенных bare-metal кластерах (Calico, Cilium, kube-ovn) с запрещающей политикой по умолчанию (`DefaultDeny`) необходимо разрешить обмен трафиком между Traefik, cert-manager и внешним миром.

```yaml
# netpol-certmanager-traefik.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-acme-solver-ingress
  namespace: default
spec:
  podSelector:
    matchLabels:
      acme.cert-manager.io/http01-solver: "true"
  policyTypes:
    - Ingress
  ingress:
    # Разрешить входящие подключения только от подов Traefik
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: traefik
          podSelector:
            matchLabels:
              app.kubernetes.io/name: traefik
      ports:
        - protocol: TCP
          port: 8089
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-cert-manager-controller-egress
  namespace: cert-manager
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: cert-manager
  policyTypes:
    - Egress
  egress:
    # Разрешить доступ к DNS кластера
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
    # Разрешить исходящий HTTPS-трафик к ACME API Let's Encrypt (порт 443)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - protocol: TCP
          port: 443
```

---

## Операции и команды

### Сводная таблица команд оператора (SRE / Sysadmin)

| Задача | Команда | Назначение / Ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка статуса CRD** | `kubectl get certificates,clusterissuers,issuers -A` | Обзор состояния всех объектов cert-manager в кластере. |
| **Инспекция сертификата** | `cmctl status certificate <name> -n <ns>` | Подробный статус сертификата, дата истечения и привязанный Secret. |
| **Штатное продление** | `cmctl renew <name> -n <ns>` | Запуск немедленного внепланового продления без удаления Secret. |
| **Просмотр заказов ACME** | `kubectl get orders,challenges -n <ns>` | Отображение активных запросов на выпуск и задач проверки владения. |
| **Инспекция X.509 Secret** | `cmctl inspect secret <secret-name> -n <ns>` | Анализ содержимого `tls.crt` без ручного декодирования base64. |
| **Диагностика через OpenSSL**| `kubectl get secret <name> -n <ns> -o jsonpath='{.data.tls\.crt}' \| base64 -d \| openssl x509 -noout -text` | Полный листинг сертификата X.509, проверка SAN и типа открытого ключа. |
| **Проверка HTTP-01** | `curl -Iv http://<domain>/.well-known/acme-challenge/test-probe` | Проверка реакции порта 80 Traefik (ожидается `HTTP 404` или `HTTP 301/308`). |

### Безопасное принудительное продление (Zero-Downtime Renewal)

> [!WARNING]
> Практика удаления Secret (`kubectl delete secret <name>`) для принудительного продления является **деструктивной и устаревшей**. При удалении Secret роутеры Traefik кратковременно переключаются на самоподписанный внутренний сертификат Traefik, что вызывает предупреждения в браузерах пользователей и сбои API-клиентов.

Канонический и безопасный способ продления сертификата в cert-manager v1.x:

```bash
# Инициация перевыпуска без удаления существующего Secret
cmctl renew app-wildcard-tls -n default
# → Manually triggered issuance of Certificate default/app-wildcard-tls

# Отслеживание генерации нового заказа
kubectl get orders -n default -w
# → NAME                           STATE   AGE
# → app-wildcard-tls-xxxx-yyyy     valid   5s

# Проверка даты действия нового сертификата в Secret
kubectl get secret app-wildcard-tls -n default -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
# → notBefore=Oct 16 11:15:00 2026 GMT
# → notAfter=Jan 14 11:15:00 2027 GMT
```

Traefik автоматически считывает обновленный Secret из Kubernetes API и обновляет TLS-контекст роутеров в памяти без перезапуска подов.

---

## Диагностика и устранение неисправностей

### Алгоритм пошаговой локализации сбоя

При возникновении проблем с выпуском сертификата локализация выполняется строго по цепочке ресурсов:

```text
[Certificate] ──► [CertificateRequest] ──► [Order] ──► [Challenge] ──► [Ingress / Solver Pod] ──► [Traefik / Port 80]
```

```bash
# Шаг 1. Проверить события Certificate
kubectl describe certificate <cert-name> -n <namespace>
# Если статус False/Unknown — смотрим имя CertificateRequest

# Шаг 2. Проверить CertificateRequest
kubectl describe certificaterequest <cr-name> -n <namespace>

# Шаг 3. Проверить Order
kubectl describe order <order-name> -n <namespace>

# Шаг 4. Проверить Challenge
kubectl describe challenge <challenge-name> -n <namespace>
# В поле 'Reason' и 'Message' содержится точный ответ от Let's Encrypt API

# Шаг 5. Проверить наличие временного Ingress и пода solver
kubectl get ingress,pods -n <namespace> -l acme.cert-manager.io/http01-solver=true
```

### Сводная таблица типовых неисправностей

| Симптом | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **`Challenge` завис в состоянии `pending`** | Порт 80 закрыт на firewall хоста / роутере, либо A-запись DNS не указывает на внешний IP кластера. | `curl -Iv http://<domain>/.well-known/acme-challenge/probe`<br>`dig +short <domain>` | Открыть порт 80 TCP на внешнем файрволе/шлюзе; убедиться, что DNS указывает на публичный IP Traefik. |
| **`Challenge` завершился с ошибкой `404 Not Found`** | В Traefik отключен провайдер `kubernetesIngress`. Traefik не видит временный Ingress от cert-manager. | `kubectl get ingress -n <ns>`<br>Проверить логи Traefik: `kubectl logs -n traefik -l app.kubernetes.io/name=traefik` | Включить `providers.kubernetesIngress.enabled: true` в Helm-параметрах Traefik. |
| **`Challenge` завершился с ошибкой `502/503 Service Unavailable`** | NetworkPolicy блокирует трафик от подов Traefik к эфемерному поду `cert-manager-acmesolver` на порт 8089. | `kubectl get pods -n <ns> -l acme.cert-manager.io/http01-solver=true`<br>Проверить логи solver-пода. | Применить NetworkPolicy, разрешающую входящий трафик от Traefik к подам с меткой `acme.cert-manager.io/http01-solver=true` на порт 8089. |
| **Ошибка `429 Too Many Requests` (Rate Limit)** | Превышен лимит Let's Encrypt (5 неудачных валидаций в час или 50 сертификатов в неделю). | `kubectl describe challenge <name>` (сообщение `too many failed authorizations lately`). | Переключить `issuerRef` на `letsencrypt-staging` до устранения сетевых неполадок. Проверить историю на https://crt.sh. |
| **Traefik отдает `TRAEFIK DEFAULT CERT` вместо Let's Encrypt** | Secret еще не создан, либо `secretName` в `IngressRoute` указан с ошибкой, либо `IngressRoute` и Secret в разных namespace. | `kubectl get ingressroute <name> -n <ns> -o yaml`<br>`kubectl get secret -n <ns>` | Убедиться, что `Certificate` и `IngressRoute` находятся в одном namespace; проверить готовность Secret (`kubectl get secret <name>`). |
| **Сбой `Internal error occurred: failed calling webhook`** | Под `cert-manager-webhook` не готов, либо NetworkPolicy блокирует доступ API-сервера к порту вебхука 10250/tcp. | `kubectl get pods -n cert-manager -l app=webhook`<br>`kubectl logs -n cert-manager -l app=webhook` | Проверить готовность пода webhook, разрешить доступ от control-plane к подам webhook в CNI. |
| **Бесконечный редирект (Redirect Loop)** | Traefik перенаправляет HTTP на HTTPS, а целевой бэкенд за Traefik также пытается выполнить редирект на HTTPS, не видя заголовка `X-Forwarded-Proto`. | `curl -Iv http://<domain>` (повторяющиеся заголовки Location). | Настроить передачу заголовков `X-Forwarded-Proto: https` и доверие к прокси в бэкенд-приложении. |

---

## Лучшие практики

1. **Staging-first подход:** Любые изменения доменной структуры, добавление новых поддоменов или настройка сетевых шлюзов на bare-metal должны первично валидироваться через `letsencrypt-staging`. Переключение на `letsencrypt-prod` выполняется только после получения статуса `Ready=True`.
2. **Использование ECDSA P-256:** Рекомендуется явно указывать `privateKey.algorithm: ECDSA` и `size: 256`. Сертификаты на эллиптических кривых значительно компактнее RSA 2048/4096, снижают вычислительную нагрузку на CPU нод при TLS-хендшейках и обеспечивают лучшую пропускную способность сетевого стека.
3. **Обязательная ротация ключей (`rotationPolicy: Always`):** Задавайте `rotationPolicy: Always` в манифестах `Certificate`. При каждом перевыпуске сертификата cert-manager генерирует новую пару закрытого и открытого ключей, снижая риски долговременной компрометации.
4. **Не отключать `kubernetesIngress` в Traefik:** Даже при 100% использовании IngressRoute CRD в кластере, поддержка стандартного Ingress в Traefik обязательна для работоспособности HTTP-01 ACME solver.
5. **Отказ от деструктивных команд:** Исключите использование `kubectl delete secret` в регламентах эксплуатации. Используйте утилиту `cmctl renew` для штатного и аварийного перевыпуска сертификатов.
6. **Строгая изоляция секретов по пространствам имен:** Не включайте `providers.kubernetesCRD.allowCrossNamespace: true` без крайней необходимости. Размещайте манифесты `Certificate` строго в целевом namespace приложения.
7. **Харденинг TLS через `TLSOption`:** Применяйте единый общекластерный или локальный профиль `TLSOption` с запретом устаревших протоколов TLS 1.0/1.1 и слабых наборов шифров CBC.
8. **Мониторинг истечения сроков через Prometheus:** Настройте алерты в Alertmanager по экспортируемым метрикам cert-manager:
   ```promql
   # Предупреждение за 14 дней до истечения сертификата
   (certmanager_certificate_expiration_timestamp_seconds - time()) / 86400 < 14
   ```

---

## Дополнительная информация

### Связанные документы базы знаний

- **[Traefik в Kubernetes: CRD, RBAC, Helm](./traefik-kubernetes.md)** — архитектура контроллера Traefik в Kubernetes, манифесты IngressRoute, Middleware и базовая конфигурация.
- **[Traefik: TLS Options и mTLS](./traefik-tls-options.md)** — глубокая настройка шифрования, управление cipher suites, строгий SNI и взаимная аутентификация клиентов.
- **[Traefik: Мониторинг сертификатов](./traefik-cert-monitoring.md)** — мониторинг жизненного цикла сертификатов, Prometheus-метрики и правила Alertmanager.
- **[Traefik: Развертывание на Bare-Metal](./traefik-bare-metal.md)** — специфика развертывания Traefik на физических серверах без облачных балансировщиков.
- **[Traefik: Rules и приоритеты роутинга](./traefik-routers-and-rules.md)** — синтаксис правил Host, PathPrefix, регулярных выражений и приоритеты роутеров.
- **[Traefik: Middleware для управления трафиком](./traefik-middlewares-traffic.md)** — настройка RateLimit, CircuitBreaker, Buffering и сжатия трафика.
- **[Cert-manager: Определения и основные понятия](../../Kubernetes/ToolsUtilities/cert_manager/definitions.md)** — архитектура контроллеров cert-manager, webhook, cainjector и жизненный цикл CRD.
- **[Cert-manager: Установка и настройка](../../Kubernetes/ToolsUtilities/cert_manager/installation.md)** — развертывание cert-manager через Helm, предварительные требования и валидация.
- **[Cert-manager: Интеграция с Ingress](../../Kubernetes/ToolsUtilities/cert_manager/ingress/overview.md)** — принципы работы ingress-shim и аннотаций для стандартного Kubernetes Ingress.
- **[Cert-manager: Let's Encrypt сценарии](../../Kubernetes/ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md)** — типовые сценарии ClusterIssuer, DNS-01 challenge и протокол ARI.
- **[Gateway API: Traefik](../../Kubernetes/Networking/gateway_api/traefik.md)** — альтернатива IngressRoute на базе современного стандарта Gateway API.
