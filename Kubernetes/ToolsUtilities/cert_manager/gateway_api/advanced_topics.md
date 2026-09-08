# Интеграция cert-manager с Gateway API: Продвинутые темы и диагностика

## Определения

**Конфликт Hostname** — ситуация, при которой логика `gateway-shim` не может однозначно определить список доменов для выпуска сертификата из-за противоречий между полем `hostname` в слушателе Gateway и явными настройками в ресурсе `Certificate` или аннотациями.

**TLS Passthrough (Сквозной TLS)** — режим работы шлюза, при котором TLS-трафик передаётся бэкенду без расшифровки. Используется ресурс `TLSRoute`. В этом режиме шлюз не управляет сертификатами, и cert-manager на уровне инфраструктуры шлюза не задействуется.

**gateway-shim** — компонент cert-manager, отвечающий за автоматическую генерацию ресурсов `Certificate` на основе структуры и аннотаций `Gateway` и `ListenerSet`.

**Dedicated Challenge Gateway (Выделенный шлюз для проверок)** — архитектурный паттерн, изолирующий трафик ACME-проверок (HTTP-01) на отдельном шлюзе, что предотвращает конфликты с продуксовыми маршрутами и повышает безопасность.

**ListenerSet (v1.21+ Stable)** — ресурс Gateway API, обеспечивающий Self-Service TLS. Позволяет разработчикам приложений самостоятельно определять параметры TLS для своих поддоменов, привязываясь к общему инфраструктурному `Gateway` через `parentRef`. В отличие от прямого управления `Gateway`, `ListenerSet` не требует прав на изменение основного шлюза.

**ReferenceGrant** — механизм безопасности Gateway API, запрещающий неявные кросс-неймспейс ссылки. Разрешает конкретным группам ресурсов (например, `gateway.networking.k8s.io`) доступ к определённым типам объектов (Secret, Service) в другом namespace. Обязателен при работе cert-manager с TLS-секретами в распределённой среде.

**ARI (ACME Renewal Information)** — расширение ACME-протокола (RFC 9773), предоставляющее CA-эмитенту возможность рекомендовать оптимальное окно для продления сертификата. cert-manager v1.21+ интегрирован с ARI и автоматически учитывает `suggestedWindow` при планировании перевыпуска.

**NetworkPolicy** — Kubernetes-ресурс, контролирующий сетевой трафик на уровне подов и namespace. В контексте cert-manager критичен для работы ACME HTTP-01: контроллер должен иметь исходящий доступ к ACME API (порт 443) и входящий доступ для проверок (порт 80).

---

## Основные концепции

### Разрешение конфликтов Hostname

При использовании автоматизации (gateway-shim) cert-manager извлекает список доменов из поля `spec.listeners[].hostname`. 

**Нюансы и рекомендации:**
1.  **Приоритет явных ресурсов:** Если вы создаете ресурс `Certificate` вручную, cert-manager игнорирует попытки автоматического выпуска для тех же доменов через аннотации Gateway. Это рекомендуемый подход для Production-сред.
2.  **Пустые Hostname (Wildcard):** Если в слушателе поле `hostname` не заполнено, Gateway API трактует это как «принимать любой трафик». В этом случае автоматический выпуск через аннотации невозможен — домены должны быть указаны явно в `Certificate`.
3.  **Дублирование в HTTPRoute:** Аннотации на уровне `HTTPRoute` имеют приоритет над аннотациями `Gateway` для конкретного маршрута.

### Механика HTTP-01 ParentRef Fallback (v1.21+)

В 2026 году стандартом для Self-Service TLS является использование `ListenerSet`, который часто работает только на порту 443. Однако проверка HTTP-01 требует порта 80.

**Решение:** Аннотация `acme.cert-manager.io/http01-parentreffallback: "true"`.
- Позволяет `ListenerSet` использовать слушатель порта 80 родительского `Gateway` для размещения временного `HTTPRoute` с ACME-токеном.
- Это исключает необходимость открывать порт 80 в каждом `ListenerSet`.

### Безопасность: ReferenceGrant в мультитеннантных средах

Gateway API запрещает кросс-неймспейс ссылки по умолчанию. Для работы TLS в распределенной среде:
1.  **Namespace `apps`**: Содержит `Certificate` и итоговый `Secret`.
2.  **Namespace `infra`**: Содержит `Gateway`.
3.  **ReferenceGrant**: Должен быть создан в namespace `apps`, разрешая группе `gateway.networking.k8s.io` (ресурс `Gateway`) доступ к объектам `Secret`.

**Минимальный ReferenceGrant:**

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-gateway-secret-access
  namespace: app-namespace
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: Gateway
    namespace: infra-system
  to:
  - group: ""
    kind: Secret
```

**RBAC-рекомендация:** Ограничивайте права на создание `ListenerSet` и `ReferenceGrant`, так как они позволяют манипулировать точками входа в кластер. Используйте `RoleBinding` вместо `ClusterRoleBinding` для namespace-scoped доступа.

### Интеграция ListenerSet с cert-manager (v1.21+)

ListenerSet обеспечивает полную изоляцию ответственности между инфраструктурным и прикладным слоями:

**Архитектура (3-tier):**

| Слой | Ответственный | Ресурсы | Права |
| :--- | :--- | :--- | :--- |
| **Инфраструктура** | Platform Ops | `Gateway`, `ReferenceGrant` | Полный доступ к инфраструктурным namespace |
| **Приложение** | App Dev | `ListenerSet`, `Certificate` | Доступ к своему namespace, создание `ListenerSet` |
| **Автоматизация** | cert-manager | `CertificateRequest`, `Order`, `Challenge` | Автоматический выпуск через аннотации |

**Аннотации cert-manager для ListenerSet:**

| Аннотация | Значение | Описание |
| :--- | :--- | :--- |
| `cert-manager.io/issuer` | Имя Issuer | Используется для namespace-scoped Issuer |
| `cert-manager.io/cluster-issuer` | Имя ClusterIssuer | Рекомендуется для Production |
| `acme.cert-manager.io/http01-parentreffallback` | `"true"` | Позволяет HTTP-01 через 80 порт родительского Gateway |

**Примечание:** При использовании `ListenerSet` cert-manager автоматически определяет родительский `Gateway` через `spec.parentRef` и настраивает ACME-проверки с учётом его слушателей.

### ARI (ACME Renewal Information) и Gateway API

ARI (RFC 9773) позволяет CA-эмитенту рекомендовать оптимальное окно продления. В контексте Gateway API это имеет особое значение:

1. **Автоматическое планирование:** cert-manager v1.21+ считывает `suggestedWindow` из ARI и планирует продление в рекомендованный период, минимизируя нагрузку на ACME API.
2. **Отсутствие `renewBefore`:** При работе с ARI рекомендуется **не указывать** `renewBefore` в ресурсе `Certificate`. cert-manager передаёт управление окном продления протоколу ACME.
3. **Фидбек в статусе:** Состояние ARI транслируется в `status.conditions` ресурсов `Gateway` и `ListenerSet`, что позволяет отслеживать окна продления без обращения к логам.

**Проверка ARI-интеграции:**

```bash
# Просмотр ARI-информации для сертификата
kubectl get certificate <name> -n <namespace> -o jsonpath='{.status.conditions}' | jq .

# Проверка, что cert-manager использует ARI (в логах контроллера)
kubectl logs -n cert-manager -l app=cert-manager --tail=50 | grep -i "ari\|renewal\|suggestedWindow"
```

### NetworkPolicy для ACME挑战ов

При работе с ACME HTTP-01/DNS-01 проверками cert-manager требует специфических сетевых разрешений:

**Исходящие подключения (обязательно):**
- Контроллер cert-manager -> ACME API: порт 443 (DNS-имя: `acme-v02.api.letsencrypt.org`)
- Контроллер cert-manager -> DNS-провайдер: порт 53 (TCP/UDP) для DNS-01

**Входящие подключения (для HTTP-01):**
- Любые -> ACME-токен: порт 80 (на Gateway/Ingress-контроллере)

**Пример NetworkPolicy для cert-manager:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: cert-manager-network-policy
  namespace: cert-manager
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: cert-manager
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Разрешить webhook от API-сервера
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - port: 10250
      protocol: TCP
  egress:
  # Разрешить подключения к ACME API (Let's Encrypt)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - port: 443
      protocol: TCP
  # Разрешить DNS-резолв
  - to:
    - namespaceSelector: {}
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
  # Разрешить подключения к Kubernetes API
  - to:
    - namespaceSelector: {}
    ports:
    - port: 6443
      protocol: TCP
```

**Диагностика NetworkPolicy:**

```bash
# Проверка, что NetworkPolicy применён
kubectl get networkpolicy -n cert-manager

# Проверка подключений от пода cert-manager к ACME API
kubectl exec -n cert-manager deploy/cert-manager -- \
  curl -s -o /dev/null -w "%{http_code}" https://acme-v02.api.letsencrypt.org/directory
# -> Должен вернуть 200

# Просмотр логов с ошибками подключения
kubectl logs -n cert-manager -l app=cert-manager --tail=100 | grep -i "connection\|timeout\|refused"
```

### Мониторинг cert-manager через Prometheus

cert-manager предоставляет нативный эндпоинт для сбора метрик в формате Prometheus на порту `9402`.

**Ключевые метрики Gateway API:**

| Метрика | Описание | Тип |
| :--- | :--- | :--- |
| `certmanager_certificate_ready_status` | Готовность сертификата (1 = Ready) | Gauge |
| `certmanager_certificate_expiration_timestamp_seconds` | Unix-время истечения сертификата | Gauge |
| `certmanager_challenge_ready_status` | Готовность Challenge | Gauge |
| `certmanager_order_ready_status` | Готовность Order | Gauge |
| `certmanager_controller_reconcile_errors_total` | Количество ошибок reconcile | Counter |

**ServiceMonitor для kube-prometheus-stack:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cert-manager
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: cert-manager
  namespaceSelector:
    matchNames:
    - cert-manager
  endpoints:
  - port: tcp-prometheus
    interval: 30s
```

**Алерт-правила (PrometheusRule):**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cert-manager-alerts
  namespace: monitoring
spec:
  groups:
  - name: cert-manager
    rules:
    - alert: CertManagerCertNotReady
      expr: certmanager_certificate_ready_status{condition="True"} == 0
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Certificate {{ $labels.name }} not ready"
        description: "Certificate {{ $labels.name }} in namespace {{ $labels.namespace }} has been in non-ready state for more than 10 minutes."
    - alert: CertManagerCertExpiringSoon
      expr: certmanager_certificate_expiration_timestamp_seconds - time() < 86400 * 7
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Certificate {{ $labels.name }} expires in less than 7 days"
    - alert: CertManagerChallengeFailed
      expr: certmanager_challenge_ready_status{condition="True"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "ACME challenge {{ $labels.name }} failed"
```

**Проверка метрик:**

```bash
# Просмотр всех метрик cert-manager
kubectl port-forward -n cert-manager svc/cert-manager 9402:9402 &
curl -s http://localhost:9402/metrics | grep certmanager_

# Проверка readiness сертификатов
curl -s http://localhost:9402/metrics | grep certmanager_certificate_ready_status

# Проверка времени истечения
curl -s http://localhost:9402/metrics | grep certmanager_certificate_expiration_timestamp_seconds
```

### Интерпретация Status Conditions Gateway API

Состояние выпуска сертификата транслируется в `status.conditions` ресурсов `Gateway` и `ListenerSet`. Правильная интерпретация этих условий критична для диагностики.

**Типы условий (Conditions):**

| Тип | Состояние | Описание |
| :--- | :--- | :--- |
| `Ready` | `True` | Шлюз готов принимать трафик, сертификаты установлены |
| `Ready` | `False` | Ошибка в одном или нескольких слушателях |
| `ResolvedRefs` | `True` | Все ссылки (Secret, Service) разрешены |
| `ResolvedRefs` | `False` | Отсутствует Secret, ReferenceGrant или Service |
| `Accepted` | `True` | Шлюз принят контроллером |
| `Accepted` | `False` | Ошибка конфигурации Gateway |

**Диагностика через kubectl:**

```bash
# Просмотр условий Gateway
kubectl get gateway <name> -n <namespace> -o jsonpath='{.status.conditions}' | jq .

# Просмотр условий ListenerSet
kubectl get listenerset <name> -n <namespace> -o jsonpath='{.status.conditions}' | jq .

# Просмотр только Ready-условий
kubectl get gateway <name> -n <namespace> -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}Type={.type} Status={.status} Reason={.reason} Message={.message}{"\n"}{end}'

# Просмотр Ready и ResolvedRefs вместе
kubectl get gateway <name> -n <namespace> -o json | jq -r '.status.conditions[] | "\(.type): \(.status) (\(.reason)) - \(.message)"'
```

**Типичные ошибки и их интерпретация:**

| Condition Type | Status | Reason | Причина | Решение |
| :--- | :--- | :--- | :--- | :--- |
| `Ready` | `False` | `InvalidCertificateRef` | Secret не найден или невалиден | Проверить Secret и ReferenceGrant |
| `Ready` | `False` | `HostnameConflict` | Конфликт hostname между слушателями | Уникализировать hostname в слушателях |
| `ResolvedRefs` | `False` | `BackendNotFound` | Backend-сервис не найден | Проверить имя и namespace сервиса |
| `ResolvedRefs` | `False` | `ReferenceGrantNotFound` | Отсутствует ReferenceGrant | Создать ReferenceGrant в namespace Secret |

---

## Практические сценарии

### Глубокая диагностика цепочки ресурсов

Если TLS-терминация не работает, используйте метод последовательного анализа (Resource Archaeology):

```bash
# 1. Проверка условий в ресурсе Gateway (уровни ResolvedRefs и Ready)
kubectl describe gateway <name> -n <namespace>

# 2. Проверка статуса в ListenerSet (если используется)
kubectl describe listenerset <name> -n <namespace>

# 3. Анализ CertificateRequest (трансляция ошибок от Issuer)
kubectl get certificaterequest -n <namespace>
kubectl describe certificaterequest <name>

# 4. Отслеживание временных маршрутов ACME
kubectl get httproute -A | grep "acme-http-01"

# 5. Проверка Secret (убедиться, что сертификат сохранён)
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates

# 6. Проверка Order и Challenge
kubectl get order -n <namespace>
kubectl get challenge -n <namespace>
```

### Настройка выделенного шлюза для проверок (Dedicated Challenge Gateway)

Для крупных кластеров рекомендуется выносить все ACME-проверки на отдельный технический шлюз. Это настраивается в `ClusterIssuer`:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    solvers:
    - http01:
        gatewayHTTPRoute:
          parentRefs:
          - name: acme-challenge-gateway
            namespace: cert-manager
            kind: Gateway
```

**Преимущества:**
- Изоляция ACME-трафика от продуктовых маршрутов
- Упрощение NetworkPolicy (только один шлюз нуждается в порту 80)
- Централизованная диагностика ACME-проверок

### Настройка ListenerSet с ReferenceGrant (Self-Service TLS)

Полный пример настройки Self-Service TLS с изоляцией namespace:

```yaml
# 1. ReferenceGrant в namespace приложения (разрешает Gateway доступ к Secret)
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-gateway-tls
  namespace: app-team
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: Gateway
    namespace: infra-system
  to:
  - group: ""
    kind: Secret
---
# 2. ListenerSet в namespace приложения
apiVersion: gateway.networking.k8s.io/v1alpha1
kind: ListenerSet
metadata:
  name: team-a-listeners
  namespace: app-team
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    acme.cert-manager.io/http01-parentreffallback: "true"
spec:
  parentRef:
    name: shared-gateway
    namespace: infra-system
  listeners:
  - name: https-app
    hostname: "app.team-a.example.com"
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs:
      - name: team-a-tls-secret
```

**Верификация:**

```bash
# Проверка, что ListenerSet подключён к Gateway
kubectl get listenerset team-a-listeners -n app-team -o jsonpath='{.status.parentRefListeners}' | jq .

# Проверка, что Secret создан
kubectl get secret team-a-tls-secret -n app-team

# Проверка сертификата
kubectl get certificate -n app-team -o custom-columns=\
  NAME:.metadata.name,\
  READY:.status.conditions[?(@.type=="Ready")].status,\
  SECRET:.spec.secretName
```

### Wildcard-сертификаты через DNS-01 с Gateway API

Для wildcard-сертификатов (`*.example.com`) обязателен метод DNS-01. В Gateway API это реализуется через `ListenerSet` или `Gateway`:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns01
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-dns01-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
---
# Gateway с wildcard hostname
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: wildcard-gateway
  namespace: infra-system
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-dns01
spec:
  gatewayClassName: istio
  listeners:
  - name: https-wildcard
    protocol: HTTPS
    port: 443
    hostname: "*.example.com"
    tls:
      mode: Terminate
      certificateRefs:
      - name: wildcard-tls-secret
```

**Особенности wildcard в Gateway API:**
- Wildcard-сертификаты требуют DNS-01 проверки (HTTP-01 не поддерживается)
- DNS-запись `_acme-challenge.example.com` должна быть доступна из кластера
- При использовании `ListenerSet` wildcard работает только если родительский `Gateway` также слушает wildcard-домен
- Wildcard-сертификат покрывает только один уровень поддоменов (`*.example.com`, но не `*.sub.example.com`)

### NetworkPolicy для ACME挑战ов в Gateway API

Специфичная NetworkPolicy для кластеров с Gateway API и ACME HTTP-01:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: gateway-acme-challenge
  namespace: cert-manager
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: cert-manager
  policyTypes:
  - Egress
  egress:
  # К ACME API (Let's Encrypt)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - port: 443
      protocol: TCP
  # К DNS-серверам
  - to:
    - namespaceSelector: {}
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
---
# NetworkPolicy для Gateway Controller (разрешить входящий HTTP-01)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: gateway-acme-http01
  namespace: infra-system
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: istio-ingressgateway
  policyTypes:
  - Ingress
  ingress:
  # Разрешить ACME HTTP-01 проверки
  - ports:
    - port: 80
      protocol: TCP
```

### Мониторинг Gateway API через Prometheus

Настройка полного мониторинга cert-manager с Gateway API:

```bash
# 1. Установка ServiceMonitor (если kube-prometheus-stack уже установлен)
kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cert-manager
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: cert-manager
  namespaceSelector:
    matchNames:
    - cert-manager
  endpoints:
  - port: tcp-prometheus
    interval: 30s
EOF

# 2. Проверка, что метрики собираются
kubectl port-forward -n cert-manager svc/cert-manager 9402:9402 &
curl -s http://localhost:9402/metrics | grep certmanager_certificate_ready_status | head -5
# -> certmanager_certificate_ready_status{condition="True",name="api-tls",namespace="prod"} 1
# -> certmanager_certificate_ready_status{condition="True",name="web-tls",namespace="prod"} 1
```

### Экстренная ротация сертификатов в Gateway API

Сценарий принудительной ротации при компрометации ключа или ошибке ARI:

```bash
# 1. Принудительное продление через cmctl
cmctl renew <cert-name> -n <namespace>

# 2. Если cert-manager не может продлить — удаление Order для перезапуска
kubectl delete order <order-name> -n <namespace>

# 3. Если Challenge завис — удаление Challenge
kubectl delete challenge <challenge-name> -n <namespace>

# 4. Полная перезапуск выпуска (удаление Certificate + Secret)
kubectl delete secret <secret-name> -n <namespace>
kubectl delete certificate <cert-name> -n <namespace>
# cert-manager автоматически создаст новый Order

# 5. Верификация нового сертификата
cmctl status certificate <cert-name> -n <namespace>
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
```

### Отладка в реальном времени через cmctl

Утилита `cmctl` (v1.20+) предоставляет нативный способ диагностики Gateway API:

```bash
# Проверка готовности инфраструктуры Gateway API для cert-manager
cmctl check api

# Статус сертификата с учетом привязки к Gateway
cmctl status certificate <name>

# Автоматическая диагностика конфигурации (cert-manager v1.20+)
cmctl diagnose certificate <name> -n <namespace>

# Диагностика всех сертификатов в namespace
cmctl diagnose certificate --namespace <namespace> --all

# Инспекция Secret (содержимое сертификата)
cmctl inspect secret <secret-name> -n <namespace>

# Принудительное продление
cmctl renew <name> -n <namespace>

# Принудительное продление всех сертификатов
cmctl renew --all -A
```

---

## Дополнительная информация

### Частые ошибки и методы их устранения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Gateway API not enabled` | Отсутствует флаг в контроллере | Добавить `--enable-gateway-api=true` в аргументы запуска cert-manager. |
| `Forbidden Secret reference` | Отсутствует `ReferenceGrant` | Создать `ReferenceGrant` в namespace, где лежит TLS-секрет. |
| `Hostname conflict` | Неоднозначность доменов | Указать `hostname` в слушателе явно или использовать ручной ресурс `Certificate`. |
| `ResolvedRefs: False` | Ошибка контроллера шлюза | Проверить, поддерживает ли ваш Gateway Controller версию Gateway API v1.1+. |
| `Challenge pending` | Недоступность 80 порта | Проверить наличие слушателя HTTP на родителе и аннотацию `http01-parentreffallback`. |
| `Order invalid` | Ошибка DNS-резолва или Firewall | Проверить DNS-запись `_acme-challenge` и NetworkPolicy для портов 443/53. |
| `CertificateRequest failed` | Невалидный Account Key или EAB | Удалить Secret с аккаунтным ключом и пересоздать Issuer. |
| `RateLimitExceeded` | Превышен лимит Duplicate Certificates | Использовать Staging для тестов; дождаться сброса лимитов (1 неделя). |
| `ListenerSet not ready` | Невалидный `parentRef` или отсутствие `allowedListeners` | Проверить конфигурацию Gateway и RBAC для.namespace приложения. |

### Специфика версий (состояние на 2026 год)

*   **cert-manager v1.21+**: Стабильная поддержка `ListenerSet` и интеграция с протоколом ARI. Теперь ошибки выпуска сертификата транслируются непосредственно в `status.conditions` шлюза с детальным описанием причины (например, `RateLimitExceeded`).
*   **Gateway API v1.1+**: Является стандартом. Использование старых Ingress-контроллеров для новых сервисов не рекомендуется (статус EOL для многих реализаций).

### Смотрите также

- **[Практические сценарии интеграции](./practical_scenarios.md)** -- полные YAML-примеры.
- **[Определения и концепции](./definitions_and_concepts.md)** -- теоретическая база и ролевая модель.
