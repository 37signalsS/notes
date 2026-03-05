# Proxy Sidecar: Реализации и Сценарии

## Определения

**Proxy Sidecar** — прозрачный сетевой прокси, который развертывается вместе с каждым экземпляром приложения (в одном Pod в Kubernetes) и обрабатывает весь его входящий и исходящий трафик. Этот паттерн является основой плоскости данных (Data Plane) в большинстве [Service Mesh](./service_mesh_concepts.md).

**Перехват трафика:** Обычно настраивается на уровне сетевого пространства имен (например, с помощью `iptables` или eBPF), что делает работу прокси прозрачной для приложения.

**Альтернатива Ambient:** В Istio 1.29+ доступна **Ambient Mesh** — архитектура без sidecar, где прокси разделяются на уровне ноды (Ztunnel) и неймспейса (Waypoint Proxy). Подробнее в [Istio: компоненты и архитектура](./istio_architecture.md).

---

## Основные концепции: Envoy vs Linkerd-proxy

В современных service mesh доминируют две реализации sidecar-прокси: **Envoy** (используется в Istio) и **linkerd2-proxy** (используется в Linkerd).

| Критерий | Envoy | Linkerd-proxy |
| :--- | :--- | :--- |
| **Архитектура** | Высокопроизводительный L4/L7-прокси на C++ с модульной архитектурой "filter chain". | Компактный и сверхбыстрый L4/L7-прокси на Rust, с фокусом на безопасность и низкие накладные расходы. |
| **Конфигурация** | Динамическая, через семейство протоколов xDS. Обладает богатой и гибкой моделью. | Управляется централизованно через control plane. Модель конфигурации минималистична. |
| **Протоколы** | HTTP/1.1, HTTP/2, HTTP/3, gRPC, TCP, UDP. | HTTP/1.x, HTTP/2, gRPC, TCP. |
| **Расширяемость** | Высокая: кастомные фильтры, Lua, WebAssembly (WASM). | Ограниченная, философия "безопасных настроек по умолчанию". |
| **mTLS** | Управляется плоскостью управления (например, Istio), поддерживает SPIFFE-идентичности. | Встроен и включен по умолчанию для всего TCP-трафика. |
| **Наблюдаемость** | Админ-интерфейс (`/stats`, `/config_dump`), интеграция с Prometheus, Jaeger. | Встроенные метрики, `linkerd tap` для диагностики в реальном времени. |
| **Производительность** | ~5–10 мс задержка, 100–300 МБ RAM на под. | ~1–3 мс задержка, 40–60% меньше CPU/RAM. |

**Альтернативы:**
- **Ztunnel (Istio Ambient):** Легковесный прокси на Rust для L4-функциональности (mTLS, L4-политики). Работает на уровне ноды (DaemonSet).
- **Cilium Proxy (eBPF):** Прозрачный прокси на основе eBPF, альтернатива классическим sidecar.

Более детальное сравнение платформ доступно в документе [Сравнение Istio и Linkerd](./istio_vs_linkerd.md).

---

## Практические сценарии

### Внедрение (Injection) Sidecar в Kubernetes

Внедрение прокси обычно автоматизировано плоскостью управления.

#### Istio (Sidecar-модель)

Требуется добавить метку `istio-injection=enabled` к `namespace`:

```bash
kubectl label namespace my-app istio-injection=enabled
```

**Проверка:**
```bash
# Проверка статуса инъекции
kubectl get namespace my-app --show-labels

# Проверка sidecar в поде
kubectl get pods -n my-app -o wide
```

#### Linkerd

Требуется добавить аннотацию `linkerd.io/inject: enabled` к объекту (например, Deployment):

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

**Проверка:**
```bash
# Проверка инъекции
linkerd check -n my-app

# ПросмотрInjected-контейнеров
kubectl get pods -n my-app -o jsonpath='{.items[*].spec.containers[*].name}'
```

### Диагностика трафика

#### Envoy (Istio)

Доступ к административному интерфейсу для получения статистики и конфигурации (выполняется внутри sidecar-контейнера или через `istioctl`).

```bash
# Статистика по всем метрикам (через istioctl)
istioctl proxy-config endpoints deploy/my-app -n my-app

# Дамп конфигурации Envoy
istioctl proxy-config bootstrap deploy/my-app -n my-app

# Прямой доступ к админ-интерфейсу Envoy
kubectl exec -it my-app-pod -c istio-proxy -- curl http://127.0.0.1:15000/stats

# Список кластеров
kubectl exec -it my-app-pod -c istio-proxy -- curl http://127.0.0.1:15000/clusters

# Проверка активных соединений
istioctl proxy-config status deploy/my-app -n my-app
```

**Полезные команды `istioctl`:**
```bash
# Анализ конфигурации на ошибки
istioctl analyze -n my-app

# Проверка статуса sidecar
istioctl proxy-status

# Трассировка запроса
istioctl x describe pod my-app-pod -n my-app
```

#### Linkerd

Используется встроенный CLI для получения "золотых сигналов" и наблюдения за трафиком в реальном времени.

```bash
# Статистика по всем Deployment в namespace
linkerd stat deploy -n my-app

# "Прослушивание" трафика к конкретному сервису
linkerd tap deploy/my-backend -n my-app

# Проверка статуса mesh
linkerd check -n my-app

# Визуализация топологии
linkerd viz graph deploy -n my-app
```

**Полезные команды `linkerd`:**
```bash
# Детальная статистика с разбивкой по операциям
linkerd stat routes deploy/my-app -n my-app

# Проверка профилей сервиса
linkerd profile -n my-app my-service

# Трассировка с фильтрацией
linkerd tap deploy/my-app --to deploy/backend -n my-app
```

### Отладка сетевых проблем

#### Istio

```bash
# Проверка правил маршрутизации
istioctl proxy-config route deploy/my-app -n my-app

# Проверка кластеров (балансировка)
istioctl proxy-config cluster deploy/my-app -n my-app

# Проверка listener'ов
istioctl proxy-config listener deploy/my-app -n my-app

# Логирование sidecar
kubectl logs my-app-pod -c istio-proxy -n my-app
```

#### Linkerd

```bash
# Трассировка ошибок
linkerd tap deploy/my-app --error -n my-app

# Проверка профилей с маршрутами
linkerd profile -n my-app my-service --tap deploy/my-app

# Логирование proxy
kubectl logs my-app-pod -c linkerd-proxy -n my-app
```

### Ambient Mesh (Istio 1.29+)

В Ambient-режиме sidecar отсутствует. Диагностика выполняется через Ztunnel и Waypoint Proxy.

```bash
# Проверка статуса Ambient
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

**Примечание:** Ztunnel работает как DaemonSet на ноде, поэтому ресурсы разделяются между всеми подами.

### Best Practices

1.  **Ресурсы:** Всегда устанавливайте `requests` и `limits` для sidecar-контейнеров.
2.  **Логирование:** Используйте выборочное логирование (access log) для отладки, отключайте в production.
3.  **Мониторинг:** Настройте алерты на аномалии в метриках sidecar (ошибки, задержки).
4.  **Безопасность:** Ограничьте доступ к админ-интерфейсу Envoy (`15000`).
5.  **Ambient:** Рассмотрите Ambient для массовых развертываний с низким оверхедом.

### Актуальность

- **Istio 1.29:** Ambient Mesh production-ready, sidecar остается основным способом для сложных сценариев.
- **Envoy 1.30+:** Поддержка HTTP/3, улучшенная производительность, WASM-фильтры.
- **Linkerd 2.x:** Стабильная работа, фокус на безопасности и простоте.
- **eBPF:** Растущая конкуренция (Cilium), но sidecar остается доминирующим паттерном.

**Источники:**
- [Envoy Proxy Documentation](https://www.envoyproxy.io/docs)
- [Linkerd Proxy Architecture](https://linkerd.io/docs/reference/architecture/)
- [Istio Ambient Documentation](https://istio.io/latest/docs/ambient/)

### Связанные документы

- **Базовые концепции:** [Service Mesh Concepts](./service_mesh_concepts.md)
- **Архитектура Istio:** [Istio Architecture](./istio_architecture.md)
- **Сравнение:** [Istio vs Linkerd](./istio_vs_linkerd.md)
- **Трафик:** [Traffic Management](./traffic_management.md)
- **Docker Sidecar:** [Docker Container Network Mode](../Docker/Docker_network/special_modes/container_network.md)
