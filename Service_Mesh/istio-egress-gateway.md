# Исходящий шлюз (Egress Gateway) в Istio

## Определения

**Egress Gateway** — выделенный экземпляр прокси Envoy на границе меша для исходящего (north-south) трафика. Весь исходящий трафик приложений (или отдельные сервисы, выбранные политикой) принудительно проходит через этот шлюз, что позволяет централизованно контролировать доступ к внешним сервисам: фильтровать по SNI/хосту, выполнять TLS-ориджинацию (termination и повторное шифрование), вести аудит и enforce default-deny.

**TLS Origination** — инициация TLS-соединения прокси до внешнего сервера. В egress-сценарии трафик от приложения к шлюзу (внутри меша) зашифрован mTLS, а шлюз до внешнего сервиса устанавливает новое TLS-соединение (серверная аутентификация — `SIMPLE`, клиентская — `MUTUAL`).

**Passthrough (egress)** — режим, при котором шлюз не участвует в TLS-хендшейке, а проксирует зашифрованный поток с маршрутизацией по SNI.

**SNI (Server Name Indication)** — имя хоста внутри TLS ClientHello, по которому egress-шлюз выбирает правило маршрутизации зашифрованного исходящего трафика.

**ServiceEntry** — ресурс Istio, описывающий внешний сервис (вне меша) и позволяющий мешу узнать о нём: `resolution: NONE | STATIC | DNS`.

---

## Основные концепции

### Зачем нужен egress gateway

Без egress-шлюза поведение внешнего трафика определяется глобально (`MeshConfig.outboundTrafficPolicy`):
- **ALLOW_ANY (по умолчанию)** — приложения могут ходить куда угодно (passthrough через sidecar/Ztunnel).
- **REGISTRY_ONLY** — только к сервисам, описанным через `ServiceEntry`.

Egress gateway добавляет управляемую точку выхода:
- централизованная фильтрация и мониторинг исходящего трафика;
- единая TLS-ориджинация (приложения не работают с TLS-сертификатами);
- режим default-deny с «белым списком» внешних доменов;
- аудит (единственная точка логирования исходящих вызовов);
- стабильные исходящие IP для внешних поставщиков (NAT на egress gateway);
- изоляция: приложения не ходят в интернет напрямую.

### Архитектура и поток трафика (Sidecar-модель)

```
Приложение
   │
   ▼
Sidecar (mTLS → egress gateway)
   │
   ▼
Egress Gateway (Envoy)  ← маршрут по SNI/хосту, TLS origination, фильтрация
   │
   ▼
Внешний HTTPS-сервис (например, api.example.com)
```

Поток управляется тремя ресурсами:
1. **`Gateway` (networking.istio.io) egress** — объявляет, что egress gateway слушает порт 443 (или 80), повторно используя ресурс Gateway уровня меш-границы.
2. **`VirtualService`** — две части:
   - «исходящая»: направляет трафик приложения (sidecar) в egress gateway (`destination` = egress-gateway service);
   - «на шлюзе»: направляет трафик из egress gateway к внешнему сервису (`destination` = host из ServiceEntry).
3. **`ServiceEntry` + `DestinationRule`** — описывают внешний сервис и политику TLS до него (origination).

В **Ambient-модели** egress gateway также поддерживается: трафик приложения попадает в egress gateway через Ztunnel, а внутри меша используется тот же механизм `ServiceEntry`/`VirtualService`. Для части сценариев (когда внешний сервис требует фиксированных SNI/tls) применяются те же ресурсы.

> Примечание. Наиболее полно документированный и стабильный путь — Sidecar-модель egress gateway. Для Ambient сверяйтесь с актуальными release notes конкретной версии.

### Redirect: как трафик попадает в egress gateway

В классическом решении (Istio docs) трафик направляется в egress gateway через `VirtualService` с `match` по `sourceLabels` приложения. Альтернативный современный способ — `DestinationRule` c `exportTo` и явным маршрутом. Ключевой момент: **не весь трафик** направляется в шлюз — выборку делают политикой на конкретные сервисы, чтобы не принуждать всё к шлюзу без необходимости.

При `resolution: NONE` в `ServiceEntry` с `ALLOW_ANY` трафик идёт напрямую из sidecar (passthrough) — egress gateway нужен там, где требуется управляемость.

### TLS до внешнего сервиса

- **SIMPLE** — серверная аутентификация HTTPS (обычный HTTPS до внешнего API).
- **MUTUAL** — взаимный TLS до внешнего сервиса (клиентские сертификаты, mTLS до внешнего поставщика).
- **DISABLE** — без TLS (не рекомендуется для внешних данных).
- Без origination (passthrough) — внешний сервис получает TLS прямо от приложения.

**`DestinationRule.trafficPolicy.tls.credentialName`** — имя Secret с клиентскими/publisher-сертификатами для MUTUAL; подхватывается egress gateway через SDS.

### Взаимодействие с `outboundTrafficPolicy` и `Sidecar`

Комбинация для default-deny egress:
- `MeshConfig.outboundTrafficPolicy.mode: REGISTRY_ONLY`;
- явные `ServiceEntry` только для разрешённых внешних доменов;
- `Sidecar` ресурс в неймспейсе с `egress.hosts` = только нужные хосты (+ egress gateway);
- egress gateway для разрешённых доменов.

См. [Конфигурация Sidecar в Istio](./istio-sidecar-configuration.md) для деталей `egress.hosts`.

---

## Практические сценарии

### Сценарий 1: Egress gateway с TLS origination (SIMPLE)

Разворачиваем egress gateway (если он не установлен):

```bash
# Включение компонента через istioctl
istioctl install --set profile=default --set components.egressGateways[0].name=istio-egressgateway --set components.egressGateways[0].enabled=true

# Проверка
kubectl get pods -n istio-system -l istio=egressgateway
# → istio-egressgateway-...   1/1   Running   0   5m
```

Описываем внешний сервис (`api.example.com`) и направляем приложение через шлюз:

```yaml
# serviceentry.yaml
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: external-api
spec:
  hosts:
  - api.example.com
  location: MESH_EXTERNAL
  ports:
  - number: 443
    name: https
    protocol: TLS
  resolution: DNS
---
# destinationrule-egress.yaml — TLS origination на egress gateway
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: external-api
spec:
  host: api.example.com
  trafficPolicy:
    tls:
      mode: SIMPLE
---
# gateway-egress.yaml — объявление слушателя на egress gateway
apiVersion: networking.istio.io/v1
kind: Gateway
metadata:
  name: istio-egressgateway
  namespace: istio-system
spec:
  selector:
    istio: egressgateway
  servers:
  - port:
      number: 443
      name: tls
      protocol: TLS
    hosts:
    - api.example.com
---
# virtualservice-redirect.yaml — приложение → egress gateway
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: redirect-to-egress
  namespace: production
spec:
  hosts:
  - api.example.com
  gateways:
  - istio-system/istio-egressgateway   # правила ниже исполняются на egress gateway
  tls:
  # Правило на самом egress gateway: направляем трафик во внешний сервис
  - match:
    - port: 443
      sniHosts:
      - api.example.com
    route:
    - destination:
        host: istio-egressgateway.istio-system.svc.cluster.local
        port:
          number: 443
---
# virtualservice-appside.yaml — приложения (sidecar) направляют трафик в egress gateway
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: app-to-egress
  namespace: production
spec:
  hosts:
  - api.example.com
  gateways:
  - mesh   # правила для sidecar внутри меша
  tls:
  - match:
    - port: 443
      sniHosts:
      - api.example.com
      sourceLabels:
        app: my-app
    route:
    - destination:
        host: istio-egressgateway.istio-system.svc.cluster.local
        port:
          number: 443
```

Полные рабочие манифесты (включая `Gateway` egress) см. в официальном разделе Egress Gateway istio.io; выше показан схематичный классический патерн.

Проверка:

```bash
kubectl exec -n production deploy/my-app -- curl -sS https://api.example.com/ -o /dev/null -w "%{http_code}\n"
# → 200

# Логи egress gateway показывают TLS-соединение до внешнего сервиса
kubectl logs -n istio-system -l istio=egressgateway --tail=20 | grep api.example.com
# → [2026-09-22T...] "CONNECT api.example.com:443 ..." ... TLS
```

### Сценарий 2: Egress с MUTUAL TLS (mTLS до внешнего API)

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: external-bank
spec:
  host: bank.example.com
  trafficPolicy:
    tls:
      mode: MUTUAL
      credentialName: bank-client-cred   # Secret: tls.crt/tls.key + ca.crt
```

```bash
# Подготовка Secret с клиентскими сертификатами
kubectl create secret tls bank-client-cred -n istio-system \
  --cert=client.crt --key=client.key
kubectl -n istio-system create secret generic bank-client-cred-cacert \
  --from-file=ca.crt=ca.crt

# Egress gateway подхватит credential через SDS
kubectl exec deploy/my-app -n production -- curl -sS https://bank.example.com/ -w "%{http_code}\n"
# → 200
```

Проверка установленного контекста TLS:

```bash
istioctl proxy-config secret deploy/istio-egressgateway -n istio-system | grep bank
# → bank-client-cred  ...
```

### Сценарий 3: Default-deny egress с явным «белым списком» + SNI

```bash
# 1. REGISTRY_ONLY — разрешён только явный список
kubectl -n istio-system apply -f - <<EOF
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
metadata:
  name: mesh-egress-deny
spec:
  meshConfig:
    outboundTrafficPolicy:
      mode: REGISTRY_ONLY
EOF
# → Примечание: параметр изменяет MeshConfig; применяйте через istioctl install --set meshConfig.outboundTrafficPolicy.mode=REGISTRY_ONLY
```

```bash
# 2. Разрешённые домены — только ServiceEntry
kubectl apply -f - <<EOF
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: allowed-web
spec:
  hosts:
  - "*.example.com"
  location: MESH_EXTERNAL
  resolution: NONE
  ports:
  - number: 443
    name: https
    protocol: TLS
EOF
```

Проверка:

```bash
kubectl exec deploy/my-app -n production -- curl -sS -o /dev/null -w "%{http_code}\n" https://allowed.example.com/api
# → 200
kubectl exec deploy/my-app -n production -- curl -sS -o /dev/null -w "%{http_code}\n" https://blocked.example.org/api
# → соединение не установлено (default-deny)
```

### Сценарий 4: Egress без шлюза — TLS origination из sidecar

Когда нужен только TLS до внешнего API без централизованного шлюза (простой вариант):

```yaml
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: external-rest
spec:
  hosts:
  - rest.example.com
  location: MESH_EXTERNAL
  ports:
  - number: 443
    name: https
    protocol: TLS
  resolution: DNS
---
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: external-rest
spec:
  host: rest.example.com
  exportTo: ["*"]
  trafficPolicy:
    tls:
      mode: SIMPLE   # или MUTUAL с credentialName
```

Приложение ходит как в обычный сервис:

```bash
kubectl exec deploy/my-app -n production -- curl -sS https://rest.example.com/api 2>/dev/null
# → {"ok":true}
```

### Диагностика и отладка

```bash
# Статус egress gateway
istioctl proxy-status deploy/istio-egressgateway -n istio-system

# Кластеры, которые знает egress gateway (должен быть entry для внешнего хоста)
istioctl proxy-config cluster deploy/istio-egressgateway -n istio-system | grep external-api
# → outbound|443||api.example.com ...

# Статус ServiceEntry
kubectl get serviceentry
# → NAME          HOSTS              LOCATION        AGE
# → external-api  api.example.com    MESH_EXTERNAL   5m

# Анализ конфигурации (замечает битые маршруты)
istioctl analyze -n production

# Проверка, что egress gateway известен мешу как workload
istioctl proxy-config endpoint deploy/istio-egressgateway -n istio-system | grep 15443
```

---

## Типичные ошибки и устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `504 Gateway Timeout` при обращении через egress | `VirtualService`-редирект не сматчил `sniHosts`/`sourceLabels` или egress gateway недоступен | Проверить `istioctl proxy-config route` на шлюзе; лог: `kubectl logs -l istio=egressgateway`; наличие Podов |
| трафик идёт «мимо» шлюза | маршрутизация не для `sourceLabels` приложения | Добавить `match.sourceLabels` в `VirtualService` для исходящей части; проверить namespace приложения |
| `certificate signed by unknown authority` при origination | Нет `ca.crt` в `credentialName` для MUTUAL | Для MUTUAL создать отдельный Secret с `ca.crt` |
| `REGISTRY_ONLY` блокирует легальный сервис | `ServiceEntry` не создан для домена | Создать `ServiceEntry` (wildcard допустим); проверить `kubectl get serviceentry` |
| TLS origination не происходит (передача plaintext на 443) | `DestinationRule` не применяется или не тот namespace | Применить `DestinationRule` в том же namespace, где живёт приложение; проверить `kubectl get destinationrule -A` |
| `DNS`-резолв внешнего хоста не работает в egress | `resolution: DNS`, но шлюз не может резолвить (нет DNS) | Проверить сетевую доступность DNS для egress gateway; использовать `resolution: NONE` с SNI |
| Часть доменов блокируется по политике | не покрыты `/` в SNI-маршруте | Добавить wildcard-хосты в `servers` шлюза и в ServiceEntry |

---

## Лучшие практики эксплуатации

1. **Default-deny в плюс**: даже при активном egress gateway включайте `outboundTrafficPolicy: REGISTRY_ONLY`, чтобы незарегистрированный трафик не обходил шлюз через passthrough.
2. **Изоляция шлюза**: держите egress gateway в собственном неймспейсе (обычно `istio-system` или `istio-egress`), защищайте его `AuthorizationPolicy` (только от подов меша).
3. **Мониторинг**: смотрите метрики egress gateway отдельно, включайте access-логи через `Telemetry API` для аудита исходящих вызовов.
4. **Минимум задержки**: TLS origination на шлюзе добавляет один лишний TLS-хендшейк; для больших объёмов данных сравнивайте «через шлюз» и «из sidecar» (см. нагрузочное тестирование в [istio-performance-tuning.md](./istio-performance-tuning.md)).
5. **TLS-версии**: на egress настраивайте `minProtocolVersion`/`maxProtocolVersion` в `DestinationRule`, чтобы соответствовать внешним требованиям.
6. **SNI-звезды**: используйте wildcard-SNI (`*.example.com`) аккуратно — они снижают изоляцию между доменами.
7. **Сертификаты**: для MUTUAL храните client-credentials в одном месте и автоматизируйте ротацию (cert-manager), иначе mTLS-вызовы к внешним API падают при истечении.

---

## Дополнительная информация

### Связь с другими ресурсами меша

- `Sidecar` ресурс с `egress.hosts` позволяет сузить список известных egress-слушателей до минимума (экономия RAM) — см. [istio-sidecar-configuration.md](./istio-sidecar-configuration.md).
- Для наблюдения за исходящим трафиком используйте `Telemetry API` на неймспейсе egress gateway (см. [istio_observability_and_tools.md](./istio_observability_and_tools.md)).
- Общий подход к `ALLOW_ANY`/`REGISTRY_ONLY` описан в [service_mesh_concepts.md](./service_mesh_concepts.md).

### См. также

- [Входящий шлюз (Ingress Gateway) в Istio](./istio-ingress-gateway.md) — зеркальная граница для входящего трафика
- [Управление трафиком в Service Mesh](./traffic_management.md) — DestinationRule, VirtualService
- [Конфигурация Sidecar в Istio](./istio-sidecar-configuration.md) — egress.hosts, outboundTrafficPolicy
- [Политики безопасности Istio](./istio-security-policies.md) — AuthorizationPolicy для внешнего доступа

Документация: [Istio: Egress Gateways](https://istio.io/latest/docs/tasks/traffic-management/egress/egress-gateway/).