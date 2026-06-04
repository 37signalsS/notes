# Прокси Sidecar: реализации и сценарии

## Определения

**Proxy Sidecar** — прозрачный сетевой прокси, развёртываемый в одном Pod с приложением и обрабатывающий весь входящий и исходящий трафик. Паттерн является основой плоскости данных (Data Plane) в большинстве [Service Mesh](./service_mesh_concepts.md).

**Перехват трафика:** настраивается на уровне сетевого пространства имён (например, `iptables` или eBPF), что делает прокси прозрачным для приложения.

**Альтернатива Ambient:** в Istio 1.29+ доступна [Ambient Mesh](./istio_architecture.md) — архитектура без sidecar, где прокси разделяются на уровне ноды (Ztunnel) и неймспейса (Waypoint Proxy).

---

## Основные концепции: Envoy и Linkerd-proxy

В современных Service Mesh доминируют две реализации sidecar-прокси: **Envoy** (Istio) и **linkerd2-proxy** (Linkerd).

| Критерий | Envoy | Linkerd-proxy |
| :--- | :--- | :--- |
| **Архитектура** | L4/L7-прокси на C++ с модульной архитектурой «filter chain». | Компактный L4/L7-прокси на Rust, фокус на безопасность и низкий оверхед. |
| **Конфигурация** | Динамическая, через xDS. Богатая и гибкая модель. | Централизованная через Control Plane. Минималистичная модель. |
| **Протоколы** | HTTP/1.1, HTTP/2, HTTP/3, gRPC, TCP, UDP. | HTTP/1.x, HTTP/2, gRPC, TCP. |
| **Расширяемость** | Высокая: кастомные фильтры, Lua, WASM. | Ограниченная: философия «безопасных настроек по умолчанию». |
| **mTLS** | Управляется Control Plane (Istio), SPIFFE-идентичности. | Встроен, включён по умолчанию для всего TCP. |
| **Наблюдаемость** | `/stats`, `/config_dump`, Prometheus, Jaeger. | Встроенные метрики, `linkerd tap` для диагностики в реальном времени. |
| **Производительность** | ~5–10 мс задержка, 100–300 МБ RAM на под. | ~1–3 мс задержка, 40–60 % меньше CPU/RAM. |

**Альтернативы:**

- **Ztunnel (Istio Ambient):** легковесный прокси на Rust для L4-функциональности (mTLS, L4-политики), DaemonSet на ноде. Подробнее: [Архитектура Istio](./istio_architecture.md).
- **Cilium Proxy (eBPF):** прозрачный прокси на eBPF, альтернатива классическим sidecar.

Детальное сравнение платформ представлено в [сравнении Istio и Linkerd](./istio_vs_linkerd.md).

---

## Практические сценарии

### Внедрение (инъекция) sidecar в Kubernetes

#### Istio (модель sidecar)

Включение автоматической инъекции через метку на namespace:

```bash
kubectl label namespace my-app istio-injection=enabled
# → namespace/my-app labeled
```

Проверка меток и состояния подов:

```bash
kubectl get namespace my-app --show-labels
# → my-app Active istio-injection=enabled

kubectl get pods -n my-app -o wide
# → READY 2/2 (приложение + sidecar)
```

#### Linkerd

Аннотация на уровне Deployment:

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

Проверка корректности внедрения:

```bash
linkerd check -n my-app
# → Status: success

kubectl get pods -n my-app -o jsonpath='{.items[*].spec.containers[*].name}'
# → app linkerd-proxy
```

### Диагностика трафика

#### Envoy (Istio)

Просмотр текущих эндпоинтов для приложения:

```bash
istioctl proxy-config endpoints deploy/my-app -n my-app
# → ENDPOINT STATUS CLUSTER
# → 10.244.0.10:8080 HEALTHY out.my-app.svc.cluster.local
```

Получение базовой конфигурации (bootstrap):

```bash
istioctl proxy-config bootstrap deploy/my-app -n my-app
```

Прямое обращение к административному интерфейсу Envoy:

```bash
kubectl exec -it my-app-pod -c istio-proxy -- curl http://127.0.0.1:15000/stats
# → cluster.outbound|8080||my-app.svc.cluster.local.upstream_rq_2xx: 150
```

Проверка статуса синхронизации конфигурации:

```bash
istioctl proxy-status
# → NAME CDS LDS EDS RDS
# → my-app-pod SYNCED SYNCED SYNCED SYNCED
```

#### Linkerd

Получение статистики по Deployment:

```bash
linkerd stat deploy -n my-app
# → NAME MESHED SUCCESS RPS P99_LATENCY
# → my-app 1/1 100.00% 10rps 5ms
```

Диагностика трафика в реальном времени (tap):

```bash
linkerd tap deploy/my-app -n my-app
# → req id=0:1 proxy=in src=10.244.1.5:45678 dst=10.244.1.10:8080 method=GET path=/
```

### Отладка сетевых проблем

#### Istio

Проверка маршрутов (routes):

```bash
istioctl proxy-config route deploy/my-app -n my-app
```

Просмотр настроек слушателей (listeners):

```bash
istioctl proxy-config listener deploy/my-app -n my-app
```

Анализ конфигурации на наличие ошибок:

```bash
istioctl analyze -n my-app
# → Info [IST0102] The namespace is not annotated with istio-injection=enabled
```

#### Linkerd

Трассировка ошибок (запросы с ненулевым кодом ответа):

```bash
linkerd tap deploy/my-app --error -n my-app
```

Просмотр логов прокси-контейнера:

```bash
kubectl logs my-app-pod -c linkerd-proxy -n my-app
```

### Ambient Mesh (Istio 1.29+)

Диагностика в режиме без sidecar через Ztunnel и Waypoint Proxy:

```bash
# Список Waypoint-прокси в неймспейсе
istioctl x waypoint list -n default

# Проверка логов Ztunnel (DaemonSet)
kubectl logs -n istio-system -l app=ztunnel

# Описание сетевого состояния пода
istioctl x describe pod my-app-pod -n default
```

---

## Дополнительная информация

### Сравнение производительности

| Метрика | Envoy (Istio sidecar) | Ztunnel (Ambient) | Linkerd-proxy |
| :--- | :--- | :--- | :--- |
| **Задержка (P50)** | ~5–10 мс | ~2–4 мс | ~1–3 мс |
| **CPU (на под)** | 50–500 mCPU | ~20–150 mCPU (shared) | 20–250 mCPU |
| **RAM (на под)** | 100–300 МБ | ~30–100 МБ (shared) | 50–150 МБ |
| **Время старта** | ~1–3 сек | ~0.5–1 сек | ~0.5–1 сек |

### Лучшие практики

1. **Управление ресурсами:** всегда устанавливать `requests` и `limits` для sidecar-контейнеров во избежание OOM.
2. **Логирование:** использовать `access log` только для отладки, отключать в промышленной эксплуатации для снижения нагрузки на диск и CPU.
3. **Мониторинг:** настраивать алерты на аномалии в метриках прокси (рост 5xx ошибок, увеличение задержек).
4. **Безопасность:** ограничивать доступ к административному интерфейсу Envoy (порт `15000`) через политики доступа.

### Актуальность

- **Istio 1.29+:** Ambient Mesh официально готов к использованию (Production-ready), хотя классический sidecar остается основным вариантом для сложных L7-сценариев.
- **Envoy 1.30+:** добавлена полная поддержка HTTP/3 и улучшены механизмы WASM-расширений.
- **Linkerd 2.x:** сохраняет лидерство в простоте настройки и минимальном потреблении ресурсов.

### См. также

- [Архитектура Istio](./istio_architecture.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)
- [Паттерны Sidecar в Kubernetes](../Kubernetes/Base/Pod/pod_sidecar_patterns.md)

Документация: [Envoy Proxy](https://www.envoyproxy.io/docs), [Linkerd Architecture](https://linkerd.io/docs/reference/architecture/), [Istio Ambient](https://istio.io/latest/docs/ambient/).
