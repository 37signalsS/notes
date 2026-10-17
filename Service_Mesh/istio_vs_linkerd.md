# Сравнение Istio и Linkerd

**Актуально для:** Istio 1.31.x / Linkerd 2.20+

## Определения

**Istio** и **Linkerd** — две ведущие реализации [Service Mesh](./service_mesh_concepts.md) для управления, обеспечения безопасности и наблюдения за микросервисными приложениями в Kubernetes. В 2026 году обе платформы достигли высокой зрелости, но продолжают следовать разным философиям: Istio как универсальный «швейцарский нож» для энтерпрайза и Linkerd как максимально производительное и простое в эксплуатации решение.

**Istio (1.30+)** — полнофункциональная платформа, поддерживаемая Google и Red Hat. Стандартом де-факто в 2026 году стала архитектура **Ambient Mesh**, устраняющая необходимость в sidecar-контейнерах для большинства задач. В 1.30 конфигурация расширений прокси (Wasm/Lua) унифицирована через API `TrafficExtension`, заменяющий `WasmPlugin`.

**Linkerd (2.20+)** — проект CNCF, ориентированный на минимальные задержки и безопасность. В последних версиях фокус сместился на **HAZL** (High Availability Zone Load Balancing, функция Buoyant Enterprise) с учётом rate-limit-ответов, автоматическую ротацию trust-якорей mTLS и нативные сайдкары Kubernetes, которые с v2.20 стали типом внедрения по умолчанию.

---

## Предварительные требования

Общие требования для развертывания Service Mesh (Istio или Linkerd) в Kubernetes:

- **Kubernetes:** версия 1.31+ (минимум для Linkerd 2.20). Рекомендуется 1.32–1.37.
- **CNI-плагин:** работающий CNI (Calico, Cilium, Flannel, bridge/macvlan) — основной CNI должен загружаться перед istio-cni/linkerd-cni.
- **Gateway API CRDs:** обязательны для управления трафиком через `HTTPRoute`/`Gateway`. Установить:
  ```bash
  kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml
  kubectl get crd gateways.gateway.networking.k8s.io
  # → True (Established)
  ```
- **Ядро Linux:** 5.13+ (для nftables); 5.10+ с eBPF-поддержкой (для ускорения через SOCKMAP/XDP).
- **Доступ к API Kubernetes:** для проверки статуса подов, логов и конфигурации прокси.
- **Ресурсы Control Plane:** для Istio — istiod 2+ реплики (500m CPU / 1Gi RAM на реплику); для Linkerd — 1–2 реплики control plane (100m CPU / 128Mi RAM на реплику).
- **Сетевые политики:** при использовании NetworkPolicy убедитесь, что трафик между подами и control plane не блокируется.

---

## Основные концепции

Ключевые архитектурные и функциональные различия между платформами:

| Аспект | Istio (Ambient / Sidecar) | Linkerd (Native Sidecar) |
| :--- | :--- | :--- |
| **Философия** | **Гибкость и мощность**: исчерпывающий набор функций (WASM, сложные L7-политики). | **Простота и скорость**: минимальный оверхед, безопасность по умолчанию, HAZL. |
| **Прокси** | **Envoy (C++) / Ztunnel (Rust)**: высокая расширяемость через WASM в Envoy. | **Linkerd-proxy (Rust)**: компактный микро-прокси, оптимизированный под конкретные задачи меша. |
| **Архитектура** | Control Plane `istiod`. Модель **Ambient** (ztunnel + waypoint) — основной выбор в 2026. | Control Plane (Destination, Identity). Модель **Sidecar** с нативными сайдкарами K8s (по умолчанию с v2.20). |
| **Управление трафиком** | **Gateway API (GAMMA)**: основной стандарт. Сложные L7-правила, зеркалирование. | **Gateway API (GAMMA)**: фокусируется на надежности (ретраи, таймауты) и зональной маршрутизации. SMI-ресурсы (TrafficSplit) — устаревший legacy-механизм. |
| **Безопасность (mTLS)** | Автоматическая. Гибкие политики через `AuthorizationPolicy` и внешние PDP. | Автоматическая. Включена по умолчанию для всего TCP-трафика. |
| **Наблюдаемость** | Глубокая интеграция с внешними системами через OpenTelemetry, Kiali. | Встроенный `linkerd-viz` и высокоскоростной `tap` для анализа трафика в реальном времени. |
| **Производительность** | Ambient: < 0.5 мс (L4), ~2–4 мс (L7). Оверхед на память снижен до минимума. | Sidecar: ~1–2 мс задержка. Минимальное потребление CPU/RAM среди всех sidecar-решений. |
| **Мультикластер** | Полнофункциональная поддержка через мульти-праймери или шлюзы (East-West). | Простая настройка через `linkerd-multicluster` и автоматическое зеркалирование сервисов. |
| **Поддерживаемые версии (v2026)** | Kubernetes 1.32–1.37, Gateway API v1.6.x. | Kubernetes 1.31–1.35, Gateway API до 1.5.x. |

### Архитектура Control Plane

**Istio (istiod):**
Единый бинарный компонент, объединяющий Pilot, Citadel и Galley. Отвечает за:
- xDS-дистрибуцию конфигурации в Envoy/Ztunnel
- Service Discovery (агрегация эндпоинтов из kube-apiserver)
- Управление идентификацией (CA, выпуск SPIFFE X.509)
- Валидацию ресурсов Gateway API и Istio API

**Linkerd (Destination + Identity):**
Два отдельных компонента:
- **destination:** конфигурация маршрутизации, discovery эндпоинтов
- **identity:** выпуск и ротация сертификатов mTLS (SVID по SPIFFE ID)
- **proxy-injector:** вебхук для внедрения сайдкаров
- **sp-validator:** валидатор ServiceProfile

### Архитектура Data Plane

**Istio Ambient (рекомендуемая модель 2026):**
- **Ztunnel (L4):** DaemonSet на каждом узле, обрабатывает mTLS и L4-авторизацию через HBONE (HTTP/2 CONNECT). Написан на Rust, минимальный оверхед.
- **Waypoint Proxy (L7):** Deployment, разворачиваемый по требованию для L7-задач (маршрутизация, фильтры). Создаётся через Gateway API (`istio-waypoint`).
- **istio-cni:** DaemonSet, выполняет перехват трафика (iptables/nftables/eBPF) без привилегированного init-контейнера.

**Linkerd (Native Sidecar):**
- **linkerd-proxy:** контейнер в каждом Pod (initContainer с `restartPolicy: Always` по умолчанию с 2.20). Микро-прокси на Rust с фокусом на минимальный оверхед.
- **CNI-плагин (опционально):** для прозрачного перехвата без `NET_ADMIN` в init-контейнере.

### Управление сертификатами и идентификацией

**Istio:**
istiod выступает как единый CA, выпуская кратковременные X.509 сертификаты (SPIFFE ID на основе ServiceAccount). Ротация автоматическая; SDS (Secret Discovery Service) доставляет сертификаты в Ztunnel/Sidecar.

**Linkerd:**
Identity-компонент управляет доверенными якорями (trust anchors). В open-source Linkerd 2.20 ротация trust anchors остаётся ручной (`linkerd identity` / `linkerd upgrade --identity-trust-anchors-file`). **Автоматическая ротация trust-якорей** доступна в **Buoyant Enterprise for Linkerd (BEL) 2.20+** через встроенный rotation operator. Сертификаты распределяются через прокси без монтирования в том.

### Жизненный цикл и обновления

**Istio:**
- Ambient: обновление Ztunnel/Waypoint происходит без перезапуска подов (прозрачно через DaemonSet/Deployment)
- Sidecar: обновление образа `proxyv2` требует `kubectl rollout restart` (полный перезапуск пода)
- Конфигурация через xDS: дельта-обновления без потерь соединений

**Linkerd:**
- Обновление Control Plane: Helm upgrade (zero-downtime при правильном порядке компонентов)
- Sidecar: обновление образа `linkerd-proxy` требует перезапуска подов
- Конфигурация: централизованная, без поддержки частичных дельт на уровне прокси

---

## Практические сценарии

### Канареечное развертывание и управление трафиком

В 2026 году основным способом управления трафиком стал **Gateway API** (инициатива GAMMA, определённая Gateway API для Service Mesh).

| Задача | Istio (HTTPRoute) | Linkerd (HTTPRoute / ServiceProfile) |
| :--- | :--- | :--- |
| **Разделение трафика** | Веса на уровне `HTTPRoute.rules.backendRefs`. | Веса на уровне `HTTPRoute` или `ServiceProfile`. |
| **Ретраи и таймауты** | Настройка в `HTTPRoute.rules.filters` или VirtualService. | Настройка через `ServiceProfile` или Gateway API. |
| **Зеркалирование** | Нативная поддержка через `RequestMirror` в `HTTPRoute` (Istio extension filter). | В open-source Linkerd 2.20 **нет** встроенной поддержки зеркалирования; используйте Sidecar с `TCP` mirroring или Buoyant Enterprise for Linkerd. |
| **HAZL (Zone-aware)** | Реализуется через `LocalityLoadBalancerSetting`. | **HAZL**: автоматически удерживает трафик в зоне, учитывает rate-limit-ответы (`429`) и временно выводит перегруженные эндпоинты из пула. **Примечание:** HAZL — функция Buoyant Enterprise for Linkerd (BEL), не входит в open-source дистрибутив. |

### Сценарий: Канареечное развертывание через Gateway API

Идентичный `HTTPRoute` работает для Istio и Linkerd, что упрощает переносимость:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-canary
  namespace: prod
spec:
  parentRefs:
  - name: api-service
    kind: Service
    group: ""
  rules:
  - backendRefs:
    - name: api-v1
      port: 8080
      weight: 90
    - name: api-v2
      port: 8080
      weight: 10
```

Примечание: в GAMMA-режиме `HTTPRoute` привязывается к `Service` напрямую, а не к `Gateway`. Поведение по умолчанию — reject unmatched requests.

### Сценарий: Установка Istio (Ambient)

```bash
# Скачать istioctl
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.31.2 sh -
cd istio-1.31.2
export PATH=$PWD/bin:$PATH

# Установка istiod и CNI в режиме Ambient
istioctl install --set profile=ambient -y

# Проверка установки
istioctl version
# → client version: 1.31.2
# → control plane version: 1.31.2

# Проверка DaemonSet ztunnel и istio-cni-node
kubectl get pods -n istio-system -l app=ztunnel
kubectl get pods -n istio-system -l app=istio-cni-node
```

### Сценарий: Установка Linkerd

```bash
# Установка через CLI
curl --proto '=https' --tlsv1.2 -sSfL https://run.linkerd.io/install | sh
export PATH=$HOME/.linkerd2/bin:$PATH

# Валидация кластера
linkerd check --pre

# Установка control plane
linkerd install --crds | kubectl apply -f -
linkerd install | kubectl apply -f -

# Установка расширения viz (метрики, tap, dashboard)
linkerd viz install | kubectl apply -f -

# Проверка
linkerd check
# → Linkerd core control plane is healthy

# Включение инъекции для namespace
kubectl annotate namespace my-app linkerd.io/inject=enabled

# Перезапуск подов для применения сайдкара
kubectl rollout restart deployment -n my-app
```

### Сценарий: Мультикластерная настройка Linkerd (2.20+)

В Linkerd 2.20 мультикластерная связь настраивается через декларативный workflow с `link-gen` (заменяет устаревшие команды `link`/`connect`):

```bash
# На primary-кластере (west): установить multicluster control plane
linkerd multicluster install | kubectl apply -f -
linkerd multicluster check
# → Linkerd multicluster is ready

# Сгенерировать Link CR и секреты для связи с remote-кластером (east)
linkerd --context=east multicluster link-gen --cluster-name east | \
  kubectl --context=west apply -f -

# Проверить, что кластеры видят друг друга
linkerd multicluster gateways
# → CLUSTER   NAME               AGE
# → east      linkerd-gateway    2m

# Экспортировать сервис для зеркалирования
kubectl label svc my-service mirror.linkerd.io/exported=true
```

### Сценарий: Валидация установки и работоспособности меша

После установки обеих платформ выполните комплексную проверку:

**Istio (Ambient):**
```bash
# 1. Статус Control Plane
istioctl proxy-status
# → Все поды: SYNCED

# 2. Участие пода в Ambient-меше
istioctl x describe pod my-app-pod -n my-app
# → L4 traffic handled by ztunnel on node-1

# 3. Проверка mTLS между сервисами
istioctl proxy-config secret my-app-pod -n my-app -o json | \
  jq '.dynamicActiveSecrets[0].secret.tlsCertificate.certificateChain.inlineBytes' | \
  base64 -d | openssl x509 -noout -subject
# → subject: CN=spiffe://cluster.local/ns/my-app/sa/my-app

# 4. Анализ конфигурации на ошибки
istioctl analyze -A
```

**Linkerd:**
```bash
# 1. Полный чек здоровья
linkerd check
# → Linkerd core control plane is healthy

# 2. Инъекция сайдкара подтверждена
kubectl get pods -n my-app -o jsonpath='{.items[*].spec.initContainers[*].name}'
# → linkerd-proxy (native sidecar, restartPolicy: Always)

# 3. Проверка mTLS
linkerd viz stat deploy -n my-app
# → MESHED  SUCCESS      RPS  P99_LATENCY
# → my-app      1/1  100.00%    25rps          2ms
```

### Сценарий: Бэкап и восстановление конфигурации Istio

```bash
# Экспорт ресурсов Gateway API и Istio API
kubectl get httproute,gateway,peerauthentication,authorizationpolicy,telemetry,destinationrule -A -o yaml > istio-mesh-backup-$(date +%F).yaml

# Включённые namespace для инъекции
kubectl get ns -l istio-injection=enabled -o yaml > istio-ns-backup-$(date +%F).yaml

# Восстановление
kubectl apply -f istio-mesh-backup-2026-09-18.yaml
kubectl apply -f istio-ns-backup-2026-09-18.yaml
```

### Сценарий: Бэкап и восстановление конфигурации Linkerd

```bash
# Экспорт конфигурации Linkerd (CRD, ServiceProfiles, метки namespace)
kubectl get crd,serviceprofile,meshpolicy,server,serverauthorization -n linkerd -o yaml > linkerd-crds-backup-$(date +%F).yaml
kubectl get ns -l linkerd.io/inject=enabled -o yaml > linkerd-ns-backup-$(date +%F).yaml

# Экспорт trust anchor и issuer (critical для восстановления mTLS)
kubectl -n linkerd get cm linkerd-config -ojsonpath="{.data.values}" | \
  yq e .identityTrustAnchorsPEM - > linkerd-trust-anchors-$(date +%F).crt
kubectl -n linkerd get secret linkerd-identity-issuer -o jsonpath='{.data.ca.crt}' | base64 -d > linkerd-issuer-$(date +%F).crt
kubectl -n linkerd get secret linkerd-identity-issuer -o jsonpath='{.data.key.pem}' | base64 -d > linkerd-issuer-$(date +%F).key

# Восстановление trust anchor bundle при ротации
linkerd upgrade --identity-trust-anchors-file=bundle.crt | kubectl apply -f -
```

### Сценарий: Бенчмаркинг производительности

```bash
# Генерация нагрузки (vegeta)
echo 'GET http://my-app.prod/api/v1' | vegeta attack -rate=1000 -duration=30s | vegeta report

# Метрики Istio
istioctl proxy-config listener deploy/my-app -n my-app -o json | jq '.[] | select(.name|contains("inbound")) | .per_filter_config'

# Метрики Linkerd
linkerd viz stat deploy -n my-app --duration 1m
# → NAME     MESHED  SUCCESS      RPS  P99_LATENCY
# → my-app      1/1  99.95%    850rps          3ms
```

### Сценарий: Миграция с Sidecar на Ambient (Istio)

```bash
# 1. Убедиться, что кластер установлен в режиме Ambient
istioctl install --set profile=ambient -y

# 2. Отключить automatic sidecar injection для namespace
kubectl label namespace my-app istio-injection-

# 3. Перезапустить поды (они подключатся к Ambient через ztunnel)
kubectl rollout restart deployment/my-app -n my-app

# 4. Проверить, что поды в Ambient-режиме
istioctl x describe pod my-app-pod -n my-app
# → L4 traffic handled by ztunnel on node-1

# 5. Если нужен L7 — создать waypoint
istioctl waypoint apply -n my-app --enroll-namespace
```

### Сценарий: Анализ трафика (Diagnostics)

**Istio (режим Ambient):**
Проверка участия пода в меше и его сетевого пути:

```bash
istioctl x describe pod my-app-pod -n prod
# → Pod is part of ambient mesh.
# → L4 traffic handled by ztunnel on node-1.
# → L7 traffic handled by Waypoint Proxy: waypoint-prod.
```

**Linkerd (режим Sidecar):**
Проверка состояния нативных сайдкаров:

```bash
kubectl get pods -n my-app -o jsonpath='{.items[*].spec.initContainers[*].name}'
# → linkerd-proxy (restartPolicy: Always)

linkerd viz stat deploy -n my-app
# → NAME     MESHED  SUCCESS      RPS  P99_LATENCY
# → my-app      1/1  100.00%    25rps          2ms
```

---

## Дополнительная информация

### Рекомендации по выбору в 2026 году

**Выбирайте Istio, если требуется:**

- **Ambient Mesh:** вы хотите минимизировать оверхед на каждый под, используя общие прокси на уровне ноды/неймспейса.
- **Сложная L7-логика:** фильтрация по любым заголовкам, cookies, маршрутизация.
- **Расширяемость:** использование WebAssembly (WASM) для кастомной обработки трафика.
- **Гетерогенные среды:** поддержка VM (виртуальных машин) наравне с Kubernetes-контейнерами.
- **Мультикластер:** сложные топологии с East-West трафиком.

**Выбирайте Linkerd, если требуется:**

- **Максимальная производительность:** Linkerd-proxy на Rust остается самым быстрым sidecar-решением.
- **HAZL (Buoyant Enterprise):** критично сокращение затрат на межзонный трафик и минимизация задержек в мультизональных кластерах.
- **Простота управления:** минимальный порог входа, отсутствие сложных концепций (вроде Waypoint прокси).
- **Безопасность:** вы хотите гарантированно безопасный mTLS «из коробки» без сложной настройки политик.

### Актуальные тенденции

1. **GAMMA (Gateway API for Mesh Management):** обе платформы полностью перешли на Gateway API как основной интерфейс управления трафиком внутри кластера.
2. **eBPF Acceleration:** использование eBPF для ускорения передачи данных между сокетами (SOCKMAP) стало стандартом в 2026 году, что практически нивелировало «налог на сайдкар».
3. **Sidecarless vs Native Sidecar:** борьба между моделью без сайдкаров (Istio Ambient) и моделью с нативными сайдкарами Kubernetes (Linkerd) привела к значительному улучшению стабильности обоих подходов.
4. **Расширяемость прокси:** Istio консолидировал Wasm/Lua-конфигурацию в API `TrafficExtension` (1.30+), вытеснив разрозненные `WasmPlugin`; расширяемость Envoy остаётся ключевым преимуществом перед компактным Linkerd-proxy.

### Типичные ошибки и их решение

| Ошибка | Istio | Linkerd |
| :--- | :--- | :--- |
| **Зависание Job при завершении** | Используйте Native Sidecar (`restartPolicy: Always` в initContainers). | По умолчанию с 2.20+ (Native Sidecar GA). |
| **Connection reset / mTLS STRICT** | Проверьте `PeerAuthentication`, убедитесь в инъекции у отправителя. | Проверьте `linkerd check`, убедитесь в аннотации `linkerd.io/inject: enabled`. |
| **Прокси не синхронизируется** | `istioctl proxy-status` → проверьте логи `istiod`. | `linkerd check` → проверьте доступность Destination/Identity. |
| **Отсутствие маршрутизации** | Проверьте `HTTPRoute` parentRefs (GAMMA привязка к Service). | Проверьте `ServiceProfile` и `HTTPRoute` parentRefs. |
| **Высокое потребление ресурсов** | Создайте ресурс `Sidecar` с ограниченным `egress.hosts`. | Убедитесь в правильных `requests/limits` для `linkerd-proxy`. |

### Крайние случаи и ограничения

1. **hostNetwork: true:** поды с включённым `hostNetwork` не поддерживают корректный перехват трафика. Istio отключает инъекцию по умолчанию; Linkerd требует явного решения архитектора.
2. **StatefulSet с volumeClaimTemplates:** при rolling update Native Sidecar завершается после основного контейнера, но перед отключением PVC. Это гарантирует корректный drain соединений к БД.
3. **Изменение образа прокси:** обновление образа Envoy (`proxyv2`) или Linkerd-proxy требует перезапуска подов (`kubectl rollout restart`). Control Plane не выполняет hot-update бинарного файла.
4. **Совместная работа с другими CNI:** при использовании Cilium в режиме eBPF-редирек для Istio убедитесь, что `istio-cni` не конфликтует с Cilium CNI.
5. **Liveness Probe и sidecar:** probe приложения должна проверять порт приложения (`localhost:8080`), а не `localhost:15001` (порт прокси).

### Лучшие практики эксплуатации

1. **Ресурсные квоты:** всегда устанавливайте `requests` и `limits` для сайдкаров. В Istio 1.31 Envoy требует ~0.20 vCPU и 60MB RAM на 1,000 RPS. Для Linkerd-proxy: `requests.cpu: 50m`, `requests.memory: 64Mi`; лимиты: `cpu: 200m`, `memory: 128Mi`.
2. **Scoping конфигурации:** используйте ресурс `Sidecar` (Istio) для ограничения списка сервисов. Для Linkerd применяйте `ServiceProfile` с явным списком сервисов.
3. **Gateway API (GAMMA):** используйте `HTTPRoute` вместо `VirtualService`/`ServiceProfile` для обеспечения переносимости между мешами. Учитывайте поведение «reject by default».
4. **eBPF Acceleration:** включайте SOCKMAP для обхода TCP-стека ядра (Istio CNI / Cilium). Снижает задержки на 15–20%.
5. **Безопасность:** ограничивайте доступ к административному порту Envoy (15000) и Linkerd (4191) через NetworkPolicies.
6. **Телеметрия:** отключайте детальные Access Logs в продакшене, используя `Telemetry` API (Istio) для выборочного логирования только ошибок и медленных запросов. Linkerd по умолчанию собирает лёгкие метрики (RPS, latency, success rate); избыточное логирование включайте через `linkerd tap` только для отладки.
7. **Native Sidecar для Jobs/CronJobs:** всегда используйте нативный сайдкар для рабочих нагрузок с завершаемым выполнением.
8. **Валидация после изменений:** после изменения ресурсов выполняйте `istioctl proxy-status` или `linkerd check`.
9. **Мониторинг ресурсов:** настройте алерты на `envoy_server_memory_allocated` и `envoy_cluster_upstream_cx_active` (Istio) или `linkerd_proxy_latency` (Linkerd).
10. **Восстановление после сбоев:** храните резервные копии ресурсов Gateway API, Istio/Linkerd CRD и аннотаций namespace.

### См. также

- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md)
- [Управление трафиком в Istio](./traffic_management.md)
- [Канареечное обновление Istio](./istio_canary_upgrades.md)
- [Интеграция виртуальных машин (VM Workloads) в Istio](./istio_vm_workloads.md)

Документация: [Istio Official Docs](https://istio.io/latest/docs/), [Linkerd Official Docs](https://linkerd.io/docs/).
