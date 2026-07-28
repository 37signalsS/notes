# Прокси Sidecar: реализации и сценарии

## Определения

**Proxy Sidecar (сайдкар-прокси)** — специализированный сетевой прокси, развёртываемый в одном Pod с приложением (в отдельном контейнере) и обрабатывающий весь входящий и исходящий трафик. Этот паттерн является фундаментом плоскости данных (Data Plane) в архитектуре [Service Mesh](./service_mesh_concepts.md).

**Перехват трафика (Interception):** процесс прозрачного перенаправления сетевых пакетов из сетевого пространства имён (Network Namespace) приложения в прокси.
- **iptables:** традиционный метод через правила NAT/REDIRECT. Создаёт накладные расходы на прохождение пакетов через стек ядра.
- **eBPF (SOCKMAP):** современный метод (стандарт в 2026 году), позволяющий «сшивать» сокеты приложения и прокси на уровне ядра, минуя полный стек TCP/IP, что снижает задержки на 15–20%.

**Native Sidecar (нативный сайдкар):** механизм Kubernetes 1.29+ (стабилен в 1.33+), позволяющий запускать прокси как `initContainer` с `restartPolicy: Always`. Это гарантирует, что прокси будет готов *до* старта приложения и завершится *после* него, решая проблему гонки состояний (Race Condition).

**Альтернатива Ambient:** в Istio 1.30+ официально стабилизирована [Ambient Mesh](./istio_architecture.md) — архитектура без sidecar на уровне каждого пода, где функции разделены между Ztunnel (L4 на уровне узла) и Waypoint Proxy (L7 на уровне неймспейса).

---

## Основные концепции: Envoy и Linkerd-proxy

В современных Service Mesh доминируют две реализации sidecar-прокси: **Envoy** (Istio, Consul, Kuma) и **linkerd2-proxy** (Linkerd).

### Сравнение реализаций (июль 2026)

| Критерий | Envoy (Istio 1.30+) | Linkerd-proxy (Linkerd 2.20+) |
| :--- | :--- | :--- |
| **Архитектура** | L4/L7-прокси на C++ с модульной архитектурой «filter chain». | Компактный L4/L7-прокси на Rust, фокус на безопасность и минимальный оверхед. |
| **Конфигурация** | Динамическая, через xDS (gRPC). Богатая и гибкая модель. | Централизованная через Control Plane. Минималистичная модель. |
| **Протоколы** | HTTP/1.x, HTTP/2, HTTP/3 (QUIC), gRPC, TCP, UDP, MongoDB, Redis. | HTTP/1.x, HTTP/2, gRPC, TCP. |
| **Расширяемость** | Высокая: кастомные фильтры, Lua, WebAssembly (WASM). | Ограниченная: философия «безопасных настроек по умолчанию». |
| **Ускорение** | eBPF SOCKMAP, XDP для Ingress. | eBPF-оптимизация, нативные сайдкары. |
| **Производительность** | ~2–5 мс задержка, 50–150 МБ RAM на под. | ~1–2 мс задержка, 10–40 МБ RAM на под. |
| **AI Support** | LLM-фильтры (Rate Limit токенов, балансировка промптов). | Базовая маршрутизация. |

---

## Практические сценарии

### Внедрение (инъекция) sidecar в Kubernetes

#### Istio (Native Sidecar модель)

Включение автоматической инъекции через метку на namespace. В версии 1.30+ прокси по умолчанию внедряется как нативный сайдкар.

```bash
kubectl label namespace my-app istio-injection=enabled
# → namespace/my-app labeled
```

Проверка конфигурации внедренного пода:
```bash
kubectl get pod my-app-pod -n my-app -o jsonpath='{.spec.initContainers[?(@.name=="istio-proxy")].restartPolicy}'
# → Always
```

#### Linkerd

Аннотация на уровне Deployment (Linkerd 2.20 также поддерживает нативные сайдкары):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  annotations:
    linkerd.io/inject: enabled
spec:
  template:
    spec:
      containers:
      - name: app
        image: my-app:latest
```

Проверка состояния инъекции:
```bash
linkerd check -n my-app
# → Status: success

kubectl get pods -n my-app -o jsonpath='{.items[*].spec.initContainers[*].name}'
# → linkerd-proxy (если используется Native Sidecar)
```

### Диагностика и отладка трафика

#### Envoy (Istio / Gateway API)

Просмотр текущих эндпоинтов (endpoints) для приложения:
```bash
istioctl proxy-config endpoints deploy/my-app -n my-app
# → ENDPOINT             STATUS  CLUSTER
# → 10.244.0.10:8080    HEALTHY out.my-app.svc.cluster.local
```

Получение базовой конфигурации (bootstrap) для проверки настроек администрирования:
```bash
istioctl proxy-config bootstrap deploy/my-app -n my-app
```

Прямое обращение к административному интерфейсу Envoy (порт 15000):
```bash
kubectl exec -it my-app-pod -c istio-proxy -- curl http://127.0.0.1:15000/stats | grep upstream_rq_2xx
# → cluster.outbound|8080||my-app.svc.cluster.local.upstream_rq_2xx: 150
```

Просмотр слушателей (listeners) и цепочек фильтров:
```bash
istioctl proxy-config listener deploy/my-app --port 8080 -o json
```

Проверка статуса синхронизации конфигурации с Control Plane:
```bash
istioctl proxy-status
# → NAME CDS LDS EDS RDS
# → my-app-pod SYNCED SYNCED SYNCED SYNCED
```

#### Linkerd

Получение статистики по ресурсам в реальном времени:
```bash
linkerd stat deploy -n my-app
# → NAME     MESHED  SUCCESS      RPS  P99_LATENCY
# → my-app      1/1  100.00%    10rps          5ms
```

Глубокая диагностика трафика (tap):
```bash
linkerd tap deploy/my-app -n my-app
# → req id=0:1 proxy=in src=10.244.1.5:45678 dst=10.244.1.10:8080 method=GET path=/api/v1
```

### Отладка сетевых проблем

#### Istio

Анализ маршрутов (routes):
```bash
istioctl proxy-config route deploy/my-app -n my-app
```

Проверка корректности конфигурации всего неймспейса:
```bash
istioctl analyze -n my-app
# → Info [IST0102] The namespace is not annotated with istio-injection=enabled
```

Логирование запросов (Access Logs) — включение через Telemetry API или настройку прокси:
```bash
kubectl logs my-app-pod -c istio-proxy -n my-app | grep "GET /health"
```

#### Linkerd

Трассировка ошибок (только запросы с 5xx кодами):
```bash
linkerd tap deploy/my-app --error -n my-app
```

Просмотр логов прокси-контейнера:
```bash
kubectl logs my-app-pod -c linkerd-proxy -n my-app
```

### Режим Ambient (Istio 1.30+)

Диагностика в режиме без sidecar через Ztunnel и Waypoint Proxy:

```bash
# Список Waypoint-прокси в неймспейсе
istioctl waypoint list -n my-app

# Проверка сетевого состояния пода (Ambient)
istioctl experimental ambient describe pod my-app-pod
# → L4 traffic handled by ztunnel-xyz
# → L7 traffic handled by waypoint-ns

# Логи Ztunnel (DaemonSet в istio-system)
kubectl logs -n istio-system -l app=ztunnel
```

---

## Дополнительная информация

### Сравнение производительности (2026)

| Метрика | Envoy (Sidecar) | Linkerd-proxy | Ztunnel (Ambient L4) | Waypoint (Ambient L7) |
| :--- | :--- | :--- | :--- | :--- |
| **Задержка (P50)** | ~3–5 мс | ~1–2 мс | < 0.5 мс | ~2–4 мс |
| **CPU (на под)** | 50–500 mCPU | 20–200 mCPU | ~20 mCPU (shared) | 100–300 mCPU |
| **RAM (на под)** | 50–150 МБ | 10–40 МБ | ~50 МБ (node) | 100–250 МБ |
| **Старт (Native)** | ~0.5–1 сек | ~0.3–0.6 сек | N/A | ~1–2 сек |

### Лучшие практики эксплуатации

1. **Ресурсные квоты:** всегда устанавливать `requests` и `limits` для сайдкаров. В 2026 году Envoy требует ~0.5 vCPU и 50MB RAM на 1,000 RPS.
2. **Scoping конфигурации:** использовать ресурс `Sidecar` (Istio) для ограничения списка сервисов, о которых знает прокси. Это критично для снижения потребления RAM в больших кластерах.
3. **eBPF Acceleration:** при использовании CNI (Cilium, Calico VPP), включайте SOCKMAP для обхода TCP-стека ядра между приложением и прокси.
4. **Безопасность:** ограничивать доступ к административному порту Envoy (15000) и Linkerd (4191) через NetworkPolicies.
5. **Телеметрия:** отключать детальные Access Logs в продакшене, используя `Telemetry` API для выборочного логирования только ошибок.

### Актуальность и ссылки

- **Istio 1.30+:** Ambient Mesh стабилен, Native Sidecars включены по умолчанию.
- **Envoy 1.39+:** поддержка LLM-фильтров для AI Gateway.
- **Linkerd 2.20+:** поддержка HAZL (Zone-aware balancing) и нативных сайдкаров.

**См. также:**
- [Архитектура Istio](./istio_architecture.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)
- [Паттерны Sidecar в Kubernetes](../Kubernetes/Base/Pod/pod_sidecar_patterns.md)

Документация: [Envoy Proxy](https://www.envoyproxy.io/docs), [Linkerd Docs](https://linkerd.io/2.20/docs/), [Istio Ambient](https://istio.io/latest/docs/ambient/).
