# Входящий шлюз (Ingress Gateway) в Istio

**Актуально для:** Istio 1.29.x / 1.30+ / 1.31

## Определения

**Ingress Gateway** — выделенный экземпляр прокси Envoy на границе меша, принимающий внешний (north-south) трафик кластера (HTTP/HTTPS/gRPC, TCP/TLS) и направляющий его к сервисам внутри меша. В отличие от sidecar-прокси, который обслуживает только свою рабочую нагрузку, ingress gateway обслуживает всё внешнее «входящее» направление и сам является частью меша (он может применять к проходящему трафику те же политики, что и обычные сервисы).

**North-South трафик** — трафик, входящий в кластер извне (и исходящий наружу), в отличие от East-West трафика между сервисами внутри меша.

**Listener (слушатель)** — конфигурация порта/протокола в ресурсе `Gateway` (Gateway API) или `Gateway` (networking.istio.io), определяющая, какой трафик шлюз принимает на конкретном порту.

**SNI (Server Name Indication)** — расширение TLS, передающее имя хоста внутри TLS ClientHello. Единственный механизм, позволяющий маршрутизировать зашифрованный трафик без его расшифровки (TLS passthrough) и выбирать сертификат на уровне L4/L7.

**TLS Termination** — режим, при котором шлюз расшифровывает TLS и передаёт бэкенду открытый HTTP или перешифрованный трафик.

**TLS Passthrough** — режим, при котором шлюз не расшифровывает TLS, а маршрутизирует зашифрованный поток по SNI.

---

## Основные концепции

### Архитектура и поток трафика

Ingress gateway разворачивается как обычный Deployment (или через helm-чарт `istio/gateway`) в отдельном неймспейсе (`istio-ingress` или `istio-system`), перед ним создаётся Kubernetes `Service` типа `LoadBalancer`/`NodePort`/`ClusterIP` (при bare-metal — через MetalLB/манифест внешнего балансировщика).

```
Внешний клиент
      │
      ▼
Load Balancer (Service: istio-ingressgateway, port 80/443)
      │
      ▼
Ingress Gateway (Envoy) ← конфигурация xDS от istiod
      │  ← терминация TLS / маршрут по hostname / подстановка сертификата
      ▼
HTTPRoute / VirtualService (маршрутизация по хосту, пути, заголовкам)
      │
      ▼
Сервис приложения → Sidecar / Ztunnel (+ mTLS до бэкенда)
```

Ключевые особенности, отличающие ingress gateway от sidecar:

- **Точка входа**: ingress обслуживает внешние хосты и порты, sidecar — только локальный трафик пода.
- **Поддерживаемые протоколы**: HTTP/1.1, HTTP/2 (включая h2c), gRPC, HTTPS (TLS termination), TLS (passthrough), TCP, HTTP/3 (экспериментально).
- **Полноценный участник меша**: трафик через ingress можно дополнительно защищать `AuthorizationPolicy`, собирать телеметрию (Telemetry API), применять mTLS до бэкенда через `DestinationRule`/`BackendTLSPolicy`.
- **Масштабирование**: шлюз масштабируется отдельно от приложений (HPA), что важно при росте внешнего трафика.

### Две модели конфигурации: Gateway API и legacy

**Gateway API (рекомендуется с 2025–2026):**
- Ресурс `Gateway` с `gatewayClassName: istio` и списком `listeners`.
- Ресурс `HTTPRoute` (или `TLSRoute`, `TCPRoute`, `GRPCRoute`) привязывается через `parentRefs`.
- Контроллер шлюза создаёт соответствующий Deployment Envoy автоматически (при использовании `istio/gateway` chart).

**Legacy (networking.istio.io/v1beta1):**
- Ресурс `Gateway` (networking) с `servers` (но хосты слушают через Envoy) + `VirtualService` с `gateways: [...]`.
- Поддерживается, но не рекомендуется для новых проектов. В новых проектах используйте Gateway API.

### SNI, hostname-маршрутизация и выбор сертификата

При одном физическом порту (например, 443) шлюз может обслуживать десятки виртуальных хостов:

- Для **HTTP** — маршрутизация по заголовку `Host` (обычно соответствует `hostnames` в `HTTPRoute`).
- Для **TLS** — выбор фильтр-чейна по **SNI**: клиент передаёт имя хоста в TLS ClientHello, Envoy выбирает соответствующий сертификат (termination) или правило маршрутизации (passthrough) ещё до прочтения HTTP-заголовков.
- Несколько слушателей на одном порту допустимы при непересекающихся `hostname`.

**TLS Termination** (mode: Terminate):
- Шлюз предъявляет сертификат, расшифровывает трафик и передаёт бэкенду HTTP или перешифрованный трафик.
- Сертификат задаётся в `tls.certificateRefs` (ссылка на `Secret` типа `kubernetes.io/tls`).

**TLS Passthrough** (mode: Passthrough):
- Шлюз не видит содержимого запроса, маршрутизация возможна **только по SNI** (ресурс `TLSRoute`).
- Используется, когда шифрование должно сквозным образом доходить до приложения (mTLS до приложения, старые протоколы, требования compliance).

**SNI-направление для re-encrypt**: после терминации ingress может повторно зашифровать трафик в mesh через `istio` mTLS (режим по умолчанию `auto` для mesh-бэкендов) — бэкенд-приложение «видит» TLS от шлюза, но mTLS между шлюзом и sidecar приложения настраивается через `DestinationRule` с `trafficPolicy.tls.mode: ISTIO_MUTUAL`.

### Выдача и ротация сертификатов

Сертификаты для ingress хранятся в Kubernetes `Secret` типа `kubernetes.io/tls` в неймспейсе шлюза (или в другом неймспейсе — тогда требуется `ReferenceGrant`).

Варианты выдачи:
- **cert-manager** (ClusterIssuer + Certificate → Secret, выдача Let's Encrypt / внутреннего CA). Подробности интеграции: [cert-manager: Private CA: Service Mesh](../Kubernetes/ToolsUtilities/cert_manager/Private_CA/service_mesh_integration.md).
- Ручное создание Secret (валид., но не рекомендуется).
- Отдельный `Secret` на каждый виртуальный хост → автоматический выбор по SNI.

Envoy отслеживает изменения Secret (SDS) и подхватывает ротацию сертификата без перезапуска шлюза.

### Взаимодействие с политиками меша

Ingress gateway, будучи workload'ом, подчиняется политикам:
- `AuthorizationPolicy` с `targetRef` на `Gateway` (или selector по меткам шлюза) ограничивает доступ на уровне шлюза (например, allow только из определенных сетей по source IP).
- `RequestAuthentication` применяется на шлюзе для JWT-ожиданий внешних клиентов.
- Телеметрия (Telemetry API) на неймспейсе шлюза включает access-логи и метрики для входящего трафика.
- `Gateway` (Gateway API) может использовать `BackendTLSPolicy`/`DestinationRule` для настройки TLS до бэкендов.

---

## Практические сценарии

### Сценарий 1: Развертывание ingress gateway через helm-чарт (Gateway API)

```bash
# Развертывание шлюза (чарт istio/gateway, неймспейс istio-ingress)
helm install istio-ingress istio/gateway -n istio-ingress --create-namespace \
  --set service.type=LoadBalancer \
  --set service.ports[0].port=80 --set service.ports[0].targetPort=8080 \
  --set service.ports[1].port=443 --set service.ports[1].targetPort=8443

# Проверка
kubectl get gateway,httproute,gatewayclass -A
# → gatewayclass.networking.k8s.io/istio    istio.io/gateway-controller   True
# → gateway.gateway.networking.k8s.io/istio-ingress   istio-ingress
```

Для bare-metal (без облачного балансировщика) используйте `--set service.type=NodePort` или отдельный `Service` с MetalLB.

### Сценарий 2: Внешний HTTPS-доступ к сервису с TLS termination

Создаём `Gateway` c TLS-слушателем и `HTTPRoute`, направляющий весь трафик на сервис приложения:

```yaml
# gateway.yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gateway
  namespace: istio-ingress
spec:
  gatewayClassName: istio
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    hostname: "*.example.com"
  - name: https
    protocol: HTTPS
    port: 443
    hostname: "*.example.com"
    tls:
      mode: Terminate
      certificateRefs:
      - kind: Secret
        name: app-tls-secret
        namespace: istio-ingress
        group: ""
```

```yaml
# httproute.yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: app-route
  namespace: production
spec:
  parentRefs:
  - name: external-gateway
    namespace: istio-ingress
  hostnames:
  - "app.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: app-service
      port: 80
```

Применяем и проверяем:

```bash
kubectl apply -f gateway.yaml -f httproute.yaml

# Статус Gateway: Listener Acceptеd, Programmed
kubectl get gateway external-gateway -n istio-ingress -o wide

# Запрос через шлюз
curl -v http://app.example.com/
# → HTTP/1.1 200 OK

# TLS-подключение с проверкой сертификата
curl -vI https://app.example.com/
# → * Server certificate: CN=app.example.com
# → < HTTP/1.1 200 OK

# Проверка, что выбранSNI-сертификат
echo | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null | openssl x509 -noout -subject
# → subject=/CN=app.example.com
```

### Сценарий 3: Автоматическая выдача сертификата через cert-manager

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: app-tls
  namespace: istio-ingress
spec:
  secretName: app-tls-secret
  dnsNames:
  - app.example.com
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
```

```bash
# Проверка выдачи
kubectl get certificate app-tls -n istio-ingress
# → NAME     READY   SECRET            AGE
# → app-tls  True    app-tls-secret    3m
```

Шлюз подхватит Secret через SDS автоматически (без рестарта). Проверка ротации:

```bash
kubectl get secret app-tls-secret -n istio-ingress -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
```

### Сценарий 4: TLS passthrough (сквозное шифрование) и SNI-маршрутизация

Когда сертификат обслуживается приложением, а шлюз лишь прокидывает TLS-поток:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: passthrough-gw
  namespace: istio-ingress
spec:
  gatewayClassName: istio
  listeners:
  - name: tls
    protocol: TLS
    port: 443
    tls:
      mode: Passthrough
---
apiVersion: gateway.networking.k8s.io/v1
kind: TLSRoute
metadata:
  name: secure-app
  namespace: production
spec:
  parentRefs:
  - name: passthrough-gw
    namespace: istio-ingress
  hostnames:
  - "secure.example.com"
  rules:
  - backendRefs:
    - name: secure-service
      port: 443
```

Проверка, что шифрование дошло до бэкенда (issuer — сертификат приложения, а не шлюза):

```bash
echo | openssl s_client -connect secure.example.com:443 -servername secure.example.com 2>/dev/null | openssl x509 -noout -issuer
# → issuer=/CN=app-internal-ca   (сертификат приложения)
```

**Ограничение**: в режиме Passthrough недоступна маршрутизация по пути/заголовкам (нет доступа к HTTP-содержимому).

### Сценарий 5: Несколько виртуальных хостов на одном порту (SNI)

Один `Gateway`, несколько слушателей с разными `hostname` — Envoy выберет нужный сертификат по SNI:

```yaml
spec:
  listeners:
  - name: a
    protocol: HTTPS
    port: 443
    hostname: a.example.com
    tls:
      mode: Terminate
      certificateRefs:
      - name: a-cert
  - name: b
    protocol: HTTPS
    port: 443
    hostname: b.example.com
    tls:
      mode: Terminate
      certificateRefs:
      - name: b-cert
```

```bash
# Проверка выбранного сертификата для обоих хостов
for h in a.example.com b.example.com; do
  echo "== $h =="; echo | openssl s_client -connect $h:443 -servername $h 2>/dev/null | openssl x509 -noout -subject;
done
# → subject=/CN=a.example.com
# → subject=/CN=b.example.com
```

### Сценарий 6: Политики безопасности на шлюзе

`AuthorizationPolicy` в `istio-ingress`, разрешающий доступ только из эдge-сетей:

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: edge-ingress-policy
  namespace: istio-ingress
spec:
  targetRef:
    kind: Gateway
    group: gateway.networking.k8s.io
    name: external-gateway
  action: ALLOW
  rules:
  - from:
    - source:
        ipBlocks: ["203.0.113.0/24"]
    to:
    - operation:
        methods: ["GET", "POST"]
```

Проверка (из неразрешённой сети):

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://app.example.com/
# → 403
```

### Сценарий 7: mTLS между шлюзом и бэкендом (re-encrypt)

После терминации на шлюзе трафик перешифровывается в mesh (mTLS). Убедиться, что бэкенд принимает только mTLS-трафик шлюза:

```yaml
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata:
  name: default
  namespace: production
spec:
  mtls:
    mode: STRICT
```

Проверка:

```bash
istioctl proxy-status | grep istio-ingressgateway
# → istio-ingressgateway-...  SYNCED  ...

# Шлюз участвует в меше и имеет сертификат
istioctl proxy-config secret deploy/istio-ingressgateway -n istio-ingress | grep -c "istio:/"
# → 1 (mTLS identity выдана istiod)
```

### Сценарий 8: URL rewrite и redirect на шлюзе (HTTPRoute)

Перезапись пути и перенаправления на Istio-шлюзе реализуются фильтрами Gateway API Standard Channel в `HTTPRoute.rules[].filters`. Теория фильтров и полный справочник — [Gateway API: routing features](../Kubernetes/Networking/gateway_api/routing_features.md).

```yaml
# 1. Strip prefix /api/v1 перед бэкендом
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-strip-prefix
  namespace: production
spec:
  parentRefs:
  - name: istio-ingress
    sectionName: https
  hostnames:
  - app.example.com
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api/v1
    filters:
    - type: URLRewriteFilter
      urlRewrite:
        path:
          type: ReplacePrefixMatch
          replacePrefixMatch: /
    backendRefs:
    - name: api-backend
      port: 80
---
# 2. Глобальный redirect: HTTP → HTTPS (301)
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: https-redirect
  namespace: production
spec:
  parentRefs:
  - name: istio-ingress
    sectionName: http
  hostnames:
  - app.example.com
  rules:
  - filters:
    - type: RequestRedirect
      requestRedirect:
        scheme: https
        statusCode: 301
```

```bash
# Проверка, что rewrite применился в RDS шлюза
istioctl proxy-config routes deploy/istio-ingressgateway -n istio-ingress --name http.8443 -o json \
  | jq '.[0].virtualHosts[0].routes[0] | {prefix_rewrite, redirect}'
# → "/"; null  ← prefix rewrite применён, redirect отсутствует на https-роуте

# Проверка rewrite в действии (путь уходит в бэкенд без /api/v1)
curl -s https://app.example.com/api/v1/health
# → 200 OK (бэкенд получил /health)

# Проверка redirect (должен вернуть 301 на https)
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://app.example.com/
# → 301 https://app.example.com/
```

> Не создавайте циклы: `RequestRedirect` на маршруте, который сам обслуживается через этот же listener, приводит к бесконечным 301 — проверяйте `sectionName` (http vs https) при redirect-схемах.

### Сценарий 9: Реальный IP клиента (X-Forwarded-For)

Когда перед Istio-шлюзом стоит внешний балансировщик или reverse proxy, в `X-Forwarded-For` (XFF) оказываются промежуточные адреса, а не клиент. Istio извлекает доверенный адрес клиента по числу доверенных прокси (`numTrustedProxies`) и помещает его в заголовок **`X-Envoy-External-Address`** — его и должны читать бэкенды и access-логи.

Глобальная настройка (IstioOperator):

```yaml
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
spec:
  meshConfig:
    defaultConfig:
      gatewayTopology:
        numTrustedProxies: 2   # LB + reverse proxy перед Istio-шлюзом
```

Или точечно — аннотацией на под шлюза (перекрывает MeshConfig):

```yaml
metadata:
  annotations:
    "proxy.istio.io/config": '{"gatewayTopology": {"numTrustedProxies": 2}}'
```

Если внешний TCP-балансировщик не умеет L7 и передаёт TCP (например, NLB с PROXY protocol), включите приём PROXY protocol на шлюзе:

```yaml
spec:
  meshConfig:
    defaultConfig:
      gatewayTopology:
        proxyProtocol: {}      # слушатели шлюза принимают PROXY protocol
```

> PROXY protocol и L7-заголовки XFF взаимоисключающими по источнику адреса не являются: при конфигурации `gatewayTopology` приоритет у `numTrustedProxies` и полученного XFF; данные PROXY protocol игнорируются.

Два частых подводных камня:

1. **SNAT на балансировщике Kubernetes-сервиса.** Если шлюз экспортируется через `LoadBalancer`/`NodePort` и клиент видит IP узла/балансировщика, проверьте `externalTrafficPolicy: Local` на Service шлюза — он сохраняет исходный IP клиента на L4.
2. **Число хопов должно совпадать с реальностью.** `numTrustedProxies` — это количество L4/L7-прокси перед Istio-шлюзом, которые добавляют свой адрес в XFF. Завысившее значение подделывает адрес клиента (атакующий может вписать свой XFF), заниженное — даёт IP последнего прокси.

```bash
# Проверка: бэкенд отражает полученные заголовки (например, echo-сервис)
curl -s https://app.example.com/headers
# → { "x-envoy-external-address": "203.0.113.50",     ← доверенный адрес клиента
#     "x-forwarded-for": "203.0.113.50, 10.0.1.5" }   ← клиент + IP шлюза

# Проверка в access-логах шлюза
kubectl logs -n istio-ingress deploy/istio-ingressgateway --tail=20 | grep "app.example.com"
# → ... "GET / HTTP/1.1" 200 ... "203.0.113.50" ...
```

### Диагностика и отладка

```bash
# Синхронизация конфигурации шлюза
istioctl proxy-status deploy/istio-ingressgateway -n istio-ingress

# Слушатели (порты и filter chains) — какие хосты обслуживает шлюз
istioctl proxy-config listener deploy/istio-ingressgateway -n istio-ingress
# → 0.0.0.0:8080   envoy.filters.listener.tls_inspector ...
# → 0.0.0.0:8443   envoy.filters.listener.tls_inspector ...

# Маршруты для конкретного listener (какие VirtualService/HTTPRoute активны)
istioctl proxy-config route deploy/istio-ingressgateway -n istio-ingress --name http.8080

# Кластеры бэкендов
istioctl proxy-config cluster deploy/istio-ingressgateway -n istio-ingress | grep -E "outbound|static"

# Логи запросов шлюза (access-логи)
kubectl logs -n istio-ingress deploy/istio-ingressgateway --tail=50 | grep "app.example.com"
# → [2026-09-22T...] "GET / HTTP/1.1" 200 ...  "curl/8.0" ...

# Анализ конфигурации на ошибки
istioctl analyze
# → No validation issues found.
```

---

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `404 Not Found` с корректного хоста | HTTPRoute не привязан к Gateway или не совпадает `hostname` | Проверить `kubectl get httproute -A`, статус `Attached Routes` в Gateway; проверить `parentRefs` и `sectionName` |
| `CertificateNotFound` / `InvalidCertificateRef` | Отсутствует Secret или не тип `kubernetes.io/tls` | Создать Secret; проверить `type` и namespace (при кросс-namespace — `ReferenceGrant`) |
| `ResolvedRefs: False` | Кросс-namespace ссылка на Secret без `ReferenceGrant` | Добавить `ReferenceGrant` в неймспейсе хранения Secret |
| TLS-сертификат «не тот» (mismatch) | Несколько хостов на порту, SNI не выбран; сертификат не покрывает хост | Проверить `hostname` в listener и `dnsNames` сертификата; проверить через `openssl s_client -servername` |
| `AdmissionRefused`/`Unsupported protocol` | Listener с неподдерживаемым `protocol` (например, `UDP`) | Использовать поддержку: HTTP, HTTPS, TLS, TCP, HTTP/3 |
| Вместо HTTP виден `plaintext` в сертификате | Passthrough выбран для терминации (или наоборот) | Проверить `tls.mode` — `Terminate` vs `Passthrough` |
| `503` внутри меша при обратном проксировании | Нет `DestinationRule`/`BackendTLSPolicy` для бэкенда или mTLS mismatch | Создать `PeerAuthentication STRICT`, проверить кластеры: `istioctl proxy-config cluster ...` |
| Бэкенд видит в XFF IP промежуточных прокси, а не клиента | Не задан `gatewayTopology.numTrustedProxies` или SNAT на балансировщике | Задать `numTrustedProxies` (MeshConfig/аннотация `proxy.istio.io/config`); проверить `externalTrafficPolicy: Local` на Service шлюза |
| Бесконечные 301-редиректы | `RequestRedirect` на маршруте того же listener (цикл scheme/host) | Проверить `sectionName` parentRefs; разнести http/https по разным listener'ам |
| Rewrite-префикс не применяется (404 у бэкенда) | `URLRewriteFilter` не в том `rules[]`, или path не совпадает с `matches` | Проверить порядок `rules`, тип `PathPrefix` и `replacePrefixMatch`; смотреть `prefix_rewrite` в RDS шлюза |

---

## Операции и команды

### Управление ingress gateway

| Действие | Команда |
| :--- | :--- |
| Развернуть шлюз через Helm | `helm install istio-ingress istio/gateway -n istio-ingress --create-namespace --set service.type=LoadBalancer` |
| Развернуть через istioctl | `istioctl install --set profile=ingress --set components.ingressGateways[0].enabled=true -y` |
| Статус подов | `kubectl get pods -n istio-ingress` |
| Статус Gateway/HTTPRoute | `kubectl get gateway,httproute -A -o wide` |
| Статус config distribution | `istioctl proxy-status deploy/istio-ingressgateway -n istio-ingress` |
| Масштабирование HPA | `kubectl autoscale deploy/istio-ingressgateway -n istio-ingress --cpu-percent=70 --min=2 --max=10` |
| PDB для обновлений | `kubectl apply -f ingress-gateway-pdb.yaml` (minAvailable: 1–2) |
| Graceful shutdown drain | `istioctl experimental prestop --gateway=istio-ingress` |
| Access логи | `kubectl logs -n istio-ingress deploy/istio-ingressgateway --tail=50 \| grep app.example.com` |
| Секреты TLS | `istioctl proxy-config secret deploy/istio-ingressgateway -n istio-ingress` |

---

## Очистка и откат

При удалении ingress gateway избавьтесь от всех созданных ресурсов:

```bash
# 1. Удаление HTTPRoute, Gateway, Certificate, Secret
kubectl delete -f httproute.yaml -f gateway.yaml -f certificate.yaml 2>/dev/null
kubectl delete secret app-tls-secret -n istio-ingress 2>/dev/null

# 2. Удаление AuthorizationPolicy и прочих политик на шлюзе
kubectl delete authorizationpolicy edge-ingress-policy -n istio-ingress 2>/dev/null
kubectl delete peerauthentication default -n production 2>/dev/null

# 3. Удаление Deployment/Service шлюза (если через Helm)
helm uninstall istio-ingress -n istio-ingress

# 4. Удаление HPA и PDB
kubectl delete hpa istio-ingressgateway -n istio-ingress 2>/dev/null
kubectl delete pdb istio-ingressgateway-pdb -n istio-ingress 2>/dev/null

# 5. Проверка, что шлюз удалён
kubectl get pods -n istio-ingress
# → No resources found

# 6. Проверка, что DNS больше не маршрутизируется к удалённому шлюзу
kubectl exec -n production deploy/my-app -- curl -sS -o /dev/null -w "%{http_code}\n" http://app.example.com/
# → connection refused или таймаут
```

---
## Лучшие практики эксплуатации

1. **Правильное именование неймспейса**: выделяйте шлюзы в отдельный неймспейс (`istio-ingress`), чтобы политики приложений не влияли на границу.
2. **Gateway API как единственный способ конфигурации**: не смешивайте legacy-`Gateway` (networking) и Gateway API на одном и том же шлюзе.
3. **Автоматизация сертификатов**: выдавайте сертификаты через cert-manager и контролируйте срок действия выделенными алертами; ротация происходит через SDS без рестарта.
4. **`ReferenceGrant` для кросс-namespace сертификатов**: создавайте минимальные по привилегиям ReferenceGrant.
5. **Масштабирование и HA**: снабдите ingress gateway HPA и `PodDisruptionBudget` (см. [istio_architecture.md](./istio_architecture.md)), мониторьте метрики шлюза (`requests`, `latency`, `5xx`).
6. **Default-deny на шлюзе**: применяйте `AuthorizationPolicy` с `action: DENY`/ALLOW по `ipBlocks` на границе первым делом.
7. **Мониторинг**: проверяйте `istioctl analyze` после каждого изменения; смотрите входящий трафик в Kiali на неймспейсе шлюза.
8. **SNI и wildcard**: используйте wildcard-сертификаты для группы одноимённых хостов, но держите их только в неймспейсах шлюза.
9. **Логи**: включайте access-логи на шлюзе через `Telemetry API` (а не глобально), чтобы не захламлять storage; фильтруйте по path.

---

## Дополнительная информация

### Связь с другими ресурсами меша

- Настройка способности: `gatewayClassName: istio` создаёт контроллер; сам шлюз становится workload'ом и виден в `istioctl proxy-status`.
- В Ambient-режиме шлюзы работают так же, но трафик внутри меша покрывается Ztunnel; L7-функции шлюза выполняет сам Envoy шлюза.
- Сквозная диагностика между ingress и сервисами описана в [Управление трафиком в Service Mesh](./traffic_management.md).

### См. также

- [Gateway API: миграция TLS и маршрутизация](../Kubernetes/Networking/gateway_api/migration_tls_and_routing.md) — базовые понятия Terminate/Passthrough, ReferenceGrant
- [Gateway API: routing features](../Kubernetes/Networking/gateway_api/routing_features.md) — URLRewriteFilter, RequestRedirect, CORS и другие фильтры HTTPRoute
- [Политики безопасности Istio](./istio-security-policies.md) — AuthorizationPolicy, RequestAuthentication, BackendTLSPolicy
- [Архитектура и компоненты Istio](./istio_architecture.md) — связь шлюзов с Control Plane и моделями Sidecar/Ambient
- [cert-manager: интеграция с Service Mesh](../Kubernetes/ToolsUtilities/cert_manager/Private_CA/service_mesh_integration.md) — выпуск сертификатов для шлюзов

Документация: [Istio: Ingress Gateways](https://istio.io/latest/docs/tasks/traffic-management/ingress/ingress-control/), [Istio: Network Topologies (XFF/XFCC, numTrustedProxies)](https://istio.io/latest/docs/ops/configuration/traffic-management/network-topologies/).