# Service Mesh: основные концепции

## Определения

**Service Mesh (Сетка сервисов)** — выделенный инфраструктурный слой для управления сетевыми взаимодействиями между микросервисами на уровнях L4–L7. Основная задача — вынести сетевую логику (маршрутизацию, безопасность, наблюдаемость) из кода приложения на уровень платформы.

**Ключевые характеристики:**

- **Прозрачность:** интеграция сервисов не требует изменения кода приложений.
- **Децентрализация:** управление трафиком распределено между прокси-серверами (Data Plane).
- **Идентичность:** каждый сервис обладает криптографической идентичностью на основе стандартов **SPIFFE/SPIRE**, что позволяет строить политики безопасности независимо от IP-адресов.

**Модели развертывания:**
- **Sidecar Pattern:** прокси запускается в каждом Pod рядом с приложением. Это классическая модель, обеспечивающая максимальную изоляцию. Подробнее: [Proxy Sidecar](./proxy_sidecar.md).
- **Sidecar-less (Ambient Mesh):** архитектура, при которой функции прокси разделены между общим узловым компонентом (L4 — Ztunnel, DaemonSet на каждой ноде) и опциональным шлюзом неймспейса (L7 — Waypoint Proxy, на основе Envoy/Gateway API). Этот режим (Istio Ambient) стабилен (GA) с версии Istio 1.24 и в 2026 году считается рекомендуемой моделью для новых развертываний. Подробнее: [Архитектура Istio](./istio_architecture.md).

---

## Основные концепции

### Взаимодействие с CNI

Service Mesh работает **поверх** CNI (Container Network Interface). В то время как CNI обеспечивает базовую связность (L3/L4), Mesh добавляет интеллектуальное управление и безопасность:

- **CNI:** «Может ли Pod A достучаться до Pod B?»
- **Service Mesh:** «Разрешено ли Pod A вызывать метод GET /auth у Pod B? Зашифрован ли этот трафик? Какова задержка (P99)?»

В современных инфраструктурах (2026) Service Mesh часто интегрируется с CNI через **eBPF**. Это позволяет использовать механизмы вроде **SOCKMAP** для ускорения передачи данных между сокетами, минуя полный стек TCP/IP ядра, что снижает накладные расходы прокси (sidecar tax) на 15–20%.

### Архитектура

Service Mesh состоит из двух плоскостей:

| Компонент | Назначение | Технологии (2026) |
| :--- | :--- | :--- |
| **Data Plane (Плоскость данных)** | Перехват, обработка и пересылка трафика. Сбор телеметрии. | Envoy, Linkerd-proxy, Ztunnel (Rust), eBPF-программы ядра (Cilium). |
| **Control Plane (Плоскость управления)** | Централизованное управление конфигурацией, выдача сертификатов, сервис-дискавери. | Istiod (Istio), Linkerd control plane, Cilium Operator (для eBPF-меша). |

### Протокол xDS и распространение конфигурации

Прокси в плоскости данных получают конфигурацию от Control Plane через семейство протоколов **xDS** поверх gRPC. Это основа динамического управления мешем без перезапуска подов:

- **CDS (Cluster Discovery Service):** динамические списки upstream-сервисов. При изменении эндпоинтов Control Plane отправляет дельту, и прокси перестраивает пулы соединений на лету.
- **LDS (Listener Discovery Service):** конфигурация слушателей — портов, протоколов и цепочек фильтров, определяющих обработку трафика.
- **RDS (Route Discovery Service):** таблицы маршрутизации для L7-запросов. Отвечают за выбор upstream на основе заголовков, путей и весов.
- **EDS (Endpoint Discovery Service):** динамические списки эндпоинтов (IP:port). EDS — основной механизм обслуживания сервисов; доставка только дельты, а не полного конфига.
- **SDS (Secret Discovery Service):** распределение TLS-сертификатов и доверенных корневых CA. В Istio SDS используется для доставки mTLS-сертификатов (SPIFFE-идентификаторы), что исключает необходимость монтирования секретов в pod.

**Push-модель:** в 2026 году все основные реализации используют push-модель, где Control Plane инициирует отправку дельты-конфигурации при любом изменении ресурсов. Это обеспечивает согласованность состояния меша в течение секунд.

### Service Discovery и жизненный цикл конфигурации

Service Mesh интегрируется с реестром сервисов (в Kubernetes — API Server и EndpointSlice) для автоматического обнаружения эндпоинтов:

1. **Регистрация:** при создании Pod Kubernetes добавляет его в EndpointSlice соответствующего Service.
2. **Агрегация:** Control Plane (например, istiod) отслеживает изменения EndpointSlice через watch-механизм.
3. **Распространение:** при изменении эндпоинтов Control Plane формирует дельту EDS и отправляет её прокси через xDS.
4. **Применение:** прокси обновляет внутренние пулы соединений без перезапуска и без потерь активных соединений.

Этот механизм работает для всех моделей: Sidecar, Ambient (Ztunnel + Waypoint) и eBPF-мешей.

### Управление идентичностью и сертификатами

**SPIFFE/SPIRE** — открытые стандарты для криптографической идентичности рабочих нагрузок (workload identity). В Service Mesh каждый pod получает уникальный **SVID** (SPIFFE Verifiable Identity Document) в форме X.509-сертификата с URI SAN.

**Жизненный цикл сертификата:**
1. **Выпуск:** Control Plane (istiod, Linkerd Identity) выступает как доверенный CA и выдает кратковременные сертификаты (обычно TTL 24 часа).
2. **Распределение:** сертификаты доставляются через SDS напрямую в прокси, минуя том pod.
3. **Ротация:** происходит автоматически задолго до истечения срока. Ротация не прерывает соединения — прокси поддерживают оба сертификата (старое и новое) в течение grace period.
4. **Проверка:** при каждом соединении прокси взаимно проверяют сертификаты (mTLS). Идентичность определяется по SPIFFE URI, а не по IP.

**Trust Bundle:** корневые CA distributing через ConfigMap или секрет. При росте мультикластерной инфраструктуры trust bundle необходимо экспортировать из Primary и импортировать в Remote кластеры.

### Протокол HBONE

**HBONE (HTTP-Based Overlay Network Environment)** — протокол инкапсуляции, используемый в Istio Ambient Mesh. Он построен на HTTP/2 CONNECT и обеспечивает:

- Транспортное шифрование между узлами (mTLS на уровне L4 через Ztunnel).
- Возможность передавать метаданные идентичности источника вместе с трафиком.
- Прозрачное туннелирование TCP-трафика через стандартные HTTP/2 соединения.

HBONE позволяет Ztunnel обрабатывать весь TCP-трафик как HTTP/2, что упрощает маршрутизацию и наблюдаемость на уровне кластера.

---

## Ключевые возможности

### 1. Управление трафиком (Gateway API и GAMMA)

В 2026 году основным стандартом управления трафиком стал **Kubernetes Gateway API** (инициатива **GAMMA** по применению Gateway API в мешах). Это позволяет использовать универсальные ресурсы (например, `HTTPRoute`) для настройки меша.

- **Маршрутизация:** Canary (взвешенная), Blue-Green, A/B-тестирование на основе заголовков или cookie.
- **Устойчивость (Resilience):** автоматические ретраи (retry), таймауты, разрыв цепи (**Circuit Breaking**) для предотвращения каскадных сбоев.
- **Балансировка:** интеллектуальное распределение с учетом зон доступности — **Locality Load Balancing / Topology Aware Routing** (Istio, открытый Linkerd) или **HAZL** (High Availability Zone Load Balancing, функция Buoyant Enterprise for Linkerd) — для минимизации задержек.

### 2. Безопасность (Zero Trust)

- **mTLS по умолчанию:** автоматическое двустороннее шифрование трафика. Прокси проверяют сертификаты друг друга при каждом соединении. В Ambient/Istio mTLS выполняется на уровне узла через **Ztunnel**, что не требует per-pod прокси.
- **Workload Identity:** использование SPIFFE-идентификаторов для аутентификации. Безопасность строится на «кто вызывает», а не «с какого IP».
- **Авторизация (L7):** гранулярные политики доступа, запрещающие или разрешающие конкретные методы API (например, `POST` запрещен, `GET` разрешен). Реализуется через `AuthorizationPolicy` (Istio), `CiliumNetworkPolicy` (Cilium) или авторизационные аннотации.
- **Модель Zero Trust:** mesh опирается на принцип «отрицать по умолчанию и разрешать явно» — политики безопасности применяются к каждому соединению независимо от сетевого расположения. Подробнее: [Zero Trust: обзор концепций](../Networking/Concepts/zero_trust_overview.md).

### 3. Наблюдаемость (Observability)

- **Золотые сигналы:** автоматический сбор метрик (RPS, Error Rate, Latency, Saturation) без участия разработчика.
- **Распределенная трассировка:** автоматическая передача контекста (trace context) между сервисами для визуализации пути запроса (OpenTelemetry, Jaeger, Tempo).
- **Топология:** построение динамической карты связей между микросервисами в реальном времени (Kiali для Istio, Viz для Linkerd, Hubble для Cilium).

---

## Практические сценарии

### Сценарий 1: Валидация работоспособности меша после установки

После развертывания Control Plane и включения Data Plane выполните комплексную проверку:

```bash
# 1. Проверка статуса синхронизации xDS
istioctl proxy-status
# → Все поды в состоянии SYNCED; при наличии NOT SYNCED проверьте доступность istiod

# 2. Проверка участия пода в меше
kubectl get pod my-app-pod -n my-app -o jsonpath='{.spec.initContainers[*].name}'
# → istio-proxy (или linkerd-proxy) присутствует в initContainers

# 3. Проверка mTLS между сервисами
istioctl proxy-config secret my-app-pod -n my-app -o json | jq '.dynamicActiveSecrets[0].secret.tlsCertificate.certificateChain.inlineBytes' | base64 -d | openssl x509 -noout -subject
# → subject: CN=spiffe://cluster.local/ns/my-app/sa/my-app

# 4. Проверка маршрутизации
istioctl proxy-config route deploy/my-app -n my-app -o json | jq '.virtualHosts[0].routes[0]'
# → Должен отражать актуальные HTTPRoute/VirtualService
```

### Сценарий 2: Добавление legacy-сервиса в mesh без перезапуска

При интеграции существующего приложения (например, базы данных на VM или устаревшего deployment) используйте исключения:

```bash
# Для Istio: создание ServiceEntry для внешнего сервиса
cat <<EOF | kubectl apply -f -
apiVersion: networking.istio.io/v1beta1
kind: ServiceEntry
metadata:
  name: legacy-db
  namespace: prod
spec:
  hosts:
  - legacy-db.corp.internal
  ports:
  - number: 5432
    name: tcp
    protocol: TCP
  location: MESH_EXTERNAL
  resolution: DNS
EOF

# Проверка, что трафик направляется через mesh
istioctl proxy-config clusters deploy/my-app -n prod | grep legacy-db
# → cluster.outbound|5432||legacy-db.corp.internal

# Для отключения mTLS с legacy-сервисом используйте PeerAuthentication PERMISSIVE
# или AuthorizationPolicy с исключением.
```

### Сценарий 3: Резервное копирование и восстановление конфигурации

Регулярный бэкап конфигурации меша критичен для восстановления после сбоев Control Plane:

```bash
# Экспорт ресурсов Gateway API и Istio/Linkerd CRD
kubectl get httproute,gateway,peerauthentication,authorizationpolicy,telemetry,destinationrule,virtualservice -A -o yaml > mesh-config-backup-$(date +%F).yaml

# Экспорт аннотаций namespace (инъекция, Ambient-режим)
kubectl get ns -l istio-injection=enabled -o yaml > mesh-ns-backup-$(date +%F).yaml
kubectl get ns -l istio.io/dataplane-mode=ambient -o yaml > mesh-ambient-backup-$(date +%F).yaml

# Восстановление
kubectl apply -f mesh-config-backup-2026-09-18.yaml
kubectl apply -f mesh-ns-backup-2026-09-18.yaml
```

### Сценарий 4: Мониторинг здоровья Control Plane и Data Plane

Настройте базовый мониторинг для раннего обнаружения проблем:

```bash
# Проверка состояния istiod
kubectl get pods -n istio-system -l app=istiod
# → istiod-6d4f8b9b5-x2abc   1/1     Running   0  2d

# Проверка DaemonSet Ztunnel (Ambient)
kubectl get pods -n istio-system -l app=ztunnel -o wide
# → ztunnel-abc12   1/1     Running   0  2d   node-1

# Проверка CNI
kubectl get pods -n istio-system -l app=istio-cni-node
# → istio-cni-node-xyz   1/1     Running   0  2d

# Сбор метрик Ztunnel
kubectl exec -n istio-system -l app=ztunnel -- curl -s localhost:15020/metrics | grep ztunnel

# ПроверкаWaypoint Proxy (Ambient)
istioctl waypoint list -n prod
# → NAME              AGE
# → namespace-waypoint   5d
```

### Сценарий 5: Поэтапная миграция с Sidecar на Ambient (Istio)

Переход на Ambient Mesh позволяет снизить overhead на 90% без перерыва обслуживания:

```bash
# 1. Убедиться, что кластер установлен в режиме Ambient
istioctl install --set profile=ambient -y

# 2. Отключить automatic sidecar injection для namespace
kubectl label namespace my-app istio-injection-

# 3. Перезапустить поды (они подключатся к Ambient через ztunnel)
kubectl rollout restart deployment/my-app -n my-app

# 4. Проверить, что поды в Ambient-режиме
istioctl experimental ambient describe pod my-app-pod -n my-app
# → L4 traffic handled by ztunnel on node-1

# 5. Если нужен L7 — создать waypoint
istioctl waypoint apply -n my-app --enroll-namespace

# 6. Валидация: проверить, что L7-трафик проходит через waypoint
istioctl proxy-status | grep my-app
# → my-app-pod  SYNCED  waypoint: namespace-waypoint
```

### Сценарий 6: Диагностика каскадных сбоев в mesh

При распространении ошибок между сервисами системно анализируйте конфигурацию:

```bash
# 1. Анализ всего кластера на ошибки
istioctl analyze -A
# → Info/Warning/Error по ресурсам Gateway API, VirtualService, DestinationRule

# 2. Проверка статуса эндпоинтов
kubectl get endpoints my-service -n prod -o yaml
# → Убедитесь, что эндпоинты Ready, а не NotReady

# 3. Проверка outlier detection
istioctl proxy-config cluster deploy/my-app -n prod | grep my-service
# → Проверьте поле `outlier_detection` — есть ли ejection

# 4. Проверка таймаутов и ретраев
istioctl proxy-config route deploy/my-app -n prod -o json | jq '.virtualHosts[] | select(.name=="my-service.prod.svc.cluster.local:80") | .routes[] | {timeout, retries}'

# 5. Сбор access-логов (временно)
kubectl logs my-app-pod -c istio-proxy -n prod | grep "502\|503\|504"
```

### Сценарий 7: Включение наблюдаемости для нового сервиса

Настройте сбор метрик и трассировки для сервиса, только что добавленного в mesh:

```bash
# 1. Включите access-логи через Telemetry API
cat <<EOF | kubectl apply -f -
apiVersion: telemetry.istio.io/v1alpha1
kind: Telemetry
metadata:
  name: enable-access-logging
  namespace: my-app
spec:
  accessLogging:
  - providers:
    - name: envoy
  metrics:
  - providers:
    - name: prometheus
  tracing:
  - providers:
    - name: otel
EOF

# 2. Настройте PodMonitor для Prometheus
cat <<EOF | kubectl apply -f -
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: istio-proxy-metrics
  namespace: my-app
spec:
  selector:
    matchLabels:
      istio-injection: enabled
  podMetricsEndpoints:
  - port: 15090
    path: /stats/prometheus
EOF

# 3. Проверьте, что метрики появляются
kubectl exec -n my-app deploy/my-app -- curl -s localhost:15090/stats/prometheus | head -20
```

---

## Типичные ошибки и устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **mTLS handshake failure** | `PeerAuthentication: STRICT` на сервере, а клиент не имеет сайдкара | Проверьте инъекцию на namespace отправителя; временно переведите в `PERMISSIVE` для диагностики |
| **Pods не получают IP из меша** | CNI не перехватывает трафик | Проверьте метку `istio.io/dataplane-mode=ambient`; проверьте логи `istio-cni-node` |
| **Waypoint не создаётся** | Нет Gateway API CRD или недостаточно прав | Установите CRD: `kubectl get crd gateways.gateway.networking.k8s.io`; проверьте RBAC istiod |
| **Высокий CPU на ноде от Ztunnel** | Конфликт правил iptables/nftables | Переключите на `nftables` (`values.global.nativeNftables=true`); проверьте количество правил: `iptables -L -t nat -v | wc -l` |
| **Сервис не обнаруживается (No Healthy Upstream)** | Эндпоинт не Ready или отсутствует в `egress.hosts` ресурса `Sidecar` | Проверьте readiness probe; добавьте namespace в `Sidecar.egress.hosts` |
| **Сертификат истёк / mTLS не работает** | CA недоступен или trust bundle устарел | Проверьте `istioctl proxy-config secret`; перевыпустите trust anchors через `istioctl x create-credential` |
| **xDS не синхронизируется (NOT SYNCED)** | istiod перегружен или сетевой разрыв | Проверьте ресурсы istiod; убедитесь в отсутствии NetworkPolicy между istiod и подами |
| **Зависание Pod при удалении (Terminating)** | Sidecar не завершается вовремя | Увеличьте `terminationGracePeriodSeconds` до 60s; проверьте `preStop` хук |
| **Access-логи не пишутся** | Telemetry API не настроен или уровень логирования выключен | Примените ресурс `Telemetry` с `accessLogging`; проверьте `kubectl logs -c istio-proxy` |

---

## Лучшие практики эксплуатации

1.  **Ресурсные квоты:** всегда устанавливайте `requests` и `limits` для сайдкаров. В 2026 году Envoy требует ~0.5 vCPU и 50MB RAM на 1,000 RPS. Для Ztunnel (Ambient) используйте `requests.cpu: 50m` и `requests.memory: 64Mi` как минимум.
2.  **Стандартизация на Gateway API (GAMMA):** в новых проектах используйте `HTTPRoute` вместо `VirtualService`/`ServiceProfile` для обеспечения переносимости между мешами. Учитывайте поведение «reject by default» при привязке роута к `Service`.
3.  **Scoping конфигурации:** используйте ресурс `Sidecar` (Istio) или `ServiceProfile` (Linkerd) для ограничения списка сервисов, о которых знает прокси. Это критично для снижения потребления RAM в больших кластерах.
4.  **Градуальное внедрение:** начинайте с Ambient L4 (mTLS) для всего кластера, затем добавляйте Waypoint Proxy только для сервисов, требующих L7. При переходе с Sidecar оставляйте оба режима параллельно 2–4 недели.
5.  **Мониторинг Ztunnel:** настраивайте алерты на использование ресурсов Ztunnel, так как он обслуживает все поды на ноде. Норма: CPU < 200m, Memory < 256Mi на узел.
6.  **eBPF-акселерация:** включайте SOCKMAP (Istio CNI / Cilium) для обхода TCP-стека ядра. Снижает задержки на 15–20%. Приоритетен для новых инсталляций `nftables` над `iptables`.
7.  **Сертификаты:** настройте автоматическую ротацию trust anchors перед истечением срока (рекомендуемый срок — 90 дней для промежуточных CA). Используйте `istioctl proxy-config secret` для проверки.
8.  **Валидация после изменений:** после изменения ресурсов выполняйте `istioctl analyze` и `istioctl proxy-status` для подтверждения распространения конфигурации.
9.  **Бэкап конфигурации:** регулярно экспортируйте ресурсы меша и ConfigMap `istio` в `istio-system`. Храните бэкапы вне кластера.
10. **Изоляция сред:** разделяйте кластеры по окружениям (dev/staging/prod) разными неймспейсами или отдельными кластерами. Istio не предоставляет встроенной изоляции между окружениями внутри одного кластера на уровне Control Plane.

---

## Дополнительная информация

### Операционные аспекты (2026)

1.  **Sidecar Tax (Налог на сайдкар):** даже с оптимизациями добавление прокси увеличивает задержку. В 2026 году это решается через переход на **Ambient Mesh** (Ztunnel + Waypoint) или использование **eBPF-акселерации** (SOCKMAP-обход TCP/IP-стека ядра, снижение задержек на 15–20%).
2.  **Ресурсное планирование:** прокси потребляют память и CPU. В Sidecar-модели это может составлять до 10–15% ресурсов кластера. Ambient Mesh снижает этот показатель до 1–3%.
3.  **Управление сертификатами:** ротация сертификатов mTLS происходит автоматически (обычно раз в 24 часа), что исключает риски простоя из-за истечения срока действия.
4.  **Планирование емкости провайдеров (Capacity Planning):** в мультикластерных конфигурациях важно учитывать overhead Control Plane (например, Istiod) и резерировать ресурсы для распределенной трассировки.
5.  **Совместимость с существующими сервисами:** при интеграции mesh с устаревшими системами (VM, внешние базы данных) настройте исключения из mTLS/проксирования через `ServiceEntry` (Istio) или явные политики, чтобы не потерять связность.

### Сложная маршрутизация между сервисами

Service Mesh используется для настройки сложной маршрутизации между сервисами, которую стандартные Kubernetes-средства не могут реализовать: canary-развертывания с точной долей трафика, A/B-тестирование, межсервисная безопасность без изменения кода приложения. Mesh комбинируется с **Zero Trust Network Access (ZTNA)** — архитектурным подходом, при котором ни один пользователь, устройство или сервис не считаются доверенными по умолчанию. В контексте Kubernetes, ZTNA реализуется через mTLS (взаимная аутентификация), policy engine (Istio AuthorizationPolicy, Linkerd AuthorizationPolicy) и идентifiability (SPIFFE/SVID). Практический паттерн: Istio + ZTNA позволяет настроить маршрутизацию между сервисами и одновременно обеспечить безопасность по принципу «никогда не доверяй, всегда проверяй» — каждый запрос между сервисами аутентифицируется и авторизуется на основе политик, независимо от сетевого положения. Подробнее о ZTNA — в [Zero Trust (Нулевое доверие)](../Concepts/zero_trust_overview.md).

### Актуальность

Основной тренд 2026 года — **унификация**. Использование Gateway API (GAMMA) позволяет переключаться между Istio, Linkerd и Cilium без полной переработки манифестов управления трафиком. Наблюдаемые тренды: переход от Sidecar к Ambient/eBPF-моделям, конвергенция с CNI через eBPF. SMI (Service Mesh Interface, ресурсы `TrafficSplit`) считается устаревшим — функция перехвачена Gateway API/GAMMA.

### См. также

- [Управление трафиком (Gateway API)](./traffic_management.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)
- [Gateway API: Глубокое погружение](../Kubernetes/Networking/gateway_api/definitions.md)
- [Ограничение скорости (Rate Limiting) в Istio](./istio_rate_limiting.md)
- [Интеграция виртуальных машин (VM Workloads) в Istio](./istio_vm_workloads.md)

Документация: [CNCF Service Mesh Landscape](https://landscape.cncf.io/guide#service-mesh), [Service Mesh Interface (SMI)](https://smi-spec.io/).
