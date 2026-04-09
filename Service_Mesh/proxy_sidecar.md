# Proxy Sidecar: Реализации и Сценарии

## Определения

**Proxy Sidecar** — прозрачный сетевой прокси, развёртываемый в одном Pod с приложением и обрабатывающий весь входящий и исходящий трафик. Паттерн является основой плоскости данных (Data Plane) в большинстве [Service Mesh](./service_mesh_concepts.md).

**Перехват трафика:** настраивается на уровне сетевого пространства имён (например, `iptables` или eBPF), что делает прокси прозрачным для приложения.

**Альтернатива Ambient:** в Istio 1.29+ доступна [Ambient Mesh](./istio_architecture.md) — архитектура без sidecar, где прокси разделяются на уровне ноды (Ztunnel) и неймспейса (Waypoint Proxy).

---

## Основные концепции: Envoy vs Linkerd-proxy

В современных service mesh доминируют две реализации sidecar-прокси: **Envoy** (Istio) и **linkerd2-proxy** (Linkerd).

| Критерий | Envoy | Linkerd-proxy |
| :--- | :--- | :--- |
| **Архитектура** | L4/L7-прокси на C++ с модульной архитектурой «filter chain». | Компактный L4/L7-прокси на Rust, фокус на безопасность и низкий оверхед. |
| **Конфигурация** | Динамическая, через xDS. Богатая и гибкая модель. | Централизованная через control plane. Минималистичная модель. |
| **Протоколы** | HTTP/1.1, HTTP/2, HTTP/3, gRPC, TCP, UDP. | HTTP/1.x, HTTP/2, gRPC, TCP. |
| **Расширяемость** | Высокая: кастомные фильтры, Lua, WASM. | Ограниченная: философия «безопасных настроек по умолчанию». |
| **mTLS** | Управляется control plane (Istio), SPIFFE-идентичности. | Встроен, включён по умолчанию для всего TCP. |
| **Наблюдаемость** | `/stats`, `/config_dump`, Prometheus, Jaeger. | Встроенные метрики, `linkerd tap` для real-time диагностики. |
| **Производительность** | ~5–10 мс задержка, 100–300 МБ RAM на под. | ~1–3 мс задержка, 40–60 % меньше CPU/RAM. |

**Альтернативы:**

- **Ztunnel (Istio Ambient):** легковесный прокси на Rust для L4-функциональности (mTLS, L4-политики), DaemonSet на ноде. Подробнее: [Istio Architecture](./istio_architecture.md).
- **Cilium Proxy (eBPF):** прозрачный прокси на eBPF, альтернатива классическим sidecar.

Детальное сравнение платформ — в [Сравнении Istio и Linkerd](./istio_vs_linkerd.md).

---

## Практические сценарии

### Внедрение (Injection) Sidecar в Kubernetes

#### Istio (Sidecar-модель)

Метка на namespace:

```bash
kubectl label namespace my-app istio-injection=enabled
```

Проверка:

```bash
kubectl get namespace my-app --show-labels
kubectl get pods -n my-app -o wide
```

#### Linkerd

Аннотация на Deployment:

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

Проверка:

```bash
linkerd check -n my-app
kubectl get pods -n my-app -o jsonpath='{.items[*].spec.containers[*].name}'
```

### Диагностика трафика

#### Envoy (Istio)

```bash
# Endpoints
istioctl proxy-config endpoints deploy/my-app -n my-app

# Bootstrap-конфигурация
istioctl proxy-config bootstrap deploy/my-app -n my-app

# Прямой доступ к админ-интерфейсу Envoy
kubectl exec -it my-app-pod -c istio-proxy -- curl http://127.0.0.1:15000/stats

# Кластеры
kubectl exec -it my-app-pod -c istio-proxy -- curl http://127.0.0.1:15000/clusters

# Статус proxy
istioctl proxy-config status deploy/my-app -n my-app
```

Полезные команды `istioctl`:

```bash
# Анализ конфигурации
istioctl analyze -n my-app

# Статус sidecar
istioctl proxy-status

# Описание pod
istioctl x describe pod my-app-pod -n my-app
```

#### Linkerd

```bash
# Статистика по Deployment
linkerd stat deploy -n my-app

# Прослушивание трафика
linkerd tap deploy/my-backend -n my-app

# Статус mesh
linkerd check -n my-app

# Топология
linkerd viz graph deploy -n my-app
```

Полезные команды `linkerd`:

```bash
# Статистика маршрутов
linkerd stat routes deploy/my-app -n my-app

# Профиль сервиса
linkerd profile -n my-app my-service

# Трассировка с фильтром
linkerd tap deploy/my-app --to deploy/backend -n my-app
```

### Отладка сетевых проблем

#### Istio

```bash
# Маршруты
istioctl proxy-config route deploy/my-app -n my-app

# Кластеры (балансировка)
istioctl proxy-config cluster deploy/my-app -n my-app

# Listener'ы
istioctl proxy-config listener deploy/my-app -n my-app

# Логирование sidecar
kubectl logs my-app-pod -c istio-proxy -n my-app
```

#### Linkerd

```bash
# Трассировка ошибок
linkerd tap deploy/my-app --error -n my-app

# Профиль с tap
linkerd profile -n my-app my-service --tap deploy/my-app

# Логирование proxy
kubectl logs my-app-pod -c linkerd-proxy -n my-app
```

### Ambient Mesh (Istio 1.29+)

В Ambient-режиме sidecar отсутствует; диагностика через Ztunnel и Waypoint Proxy:

```bash
# Список Waypoint
istioctl x waypoint list -n default

# Логирование Ztunnel
kubectl logs -n istio-system -l app=ztunnel

# Логирование Waypoint Proxy
kubectl logs -n default -l gateway.istio.io/managed=istio.io-mesh-controller

# Проверка L4-политик
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

Ztunnel работает как DaemonSet, ресурсы разделяются между подами на ноде.

### Best Practices

1. **Ресурсы:** устанавливать `requests` и `limits` для sidecar-контейнеров.
2. **Логирование:** access log — для отладки, отключать в production.
3. **Мониторинг:** алерты на аномалии в метриках sidecar (ошибки, задержки).
4. **Безопасность:** ограничить доступ к админ-интерфейсу Envoy (порт `15000`).
5. **Ambient:** рассмотреть для массовых развёртываний с низким оверхедом.

### Актуальность

- **Istio 1.29:** Ambient Mesh production-ready, sidecar остаётся основным для сложных сценариев.
- **Envoy 1.30+:** HTTP/3, улучшенная производительность, WASM-фильтры.
- **Linkerd 2.x:** стабильная работа, фокус на безопасности и простоте.
- **eBPF:** растущая конкуренция (Cilium), но sidecar остаётся доминирующим паттерном.

Документация: [Envoy Proxy](https://www.envoyproxy.io/docs), [Linkerd Architecture](https://linkerd.io/docs/reference/architecture/), [Istio Ambient](https://istio.io/latest/docs/ambient/). Общее описание sidecar-паттерна в Kubernetes — в [Pod Sidecar Pattern](../Kubernetes/Base/Pod/pod_sidecar_pattern.md).
