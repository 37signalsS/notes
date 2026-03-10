# Service Mesh: Основные концепции

## Определения

**Service Mesh (Сетка сервисов)** — выделенный инфраструктурный слой для управления сетевыми взаимодействиями между микросервисами на уровне L4–L7. Основная задача — вынести логику сети (маршрутизацию, безопасность, наблюдаемость) из кода приложения в платформу.

**Ключевые характеристики:**

- **Прозрачность:** Приложение не требует изменений кода для интеграции.
- **Децентрализация:** Управление трафиком распределено между прокси.
- **Идентичность:** Каждый сервис имеет криптографическую идентичность (SPIFFE/SVID, ServiceAccount).

**Паттерн Sidecar:** Ключевой элемент архитектуры — **прокси sidecar**, легковесный сетевой прокси, который запускается рядом с каждым экземпляром сервиса и перехватывает весь входящий и исходящий трафик. Детальное описание паттерна и реализаций — в [Proxy Sidecar](./proxy_sidecar.md).

**Альтернатива Ambient:** Начиная с Istio 1.29, доступна **Ambient Mesh** — архитектура без sidecar, где прокси разделяются на уровне ноды (Ztunnel) и неймспейса (Waypoint Proxy). Подробнее в [Istio: компоненты и архитектура](./istio_architecture.md).

---

## Основные концепции

### Архитектура

Service Mesh состоит из двух независимых плоскостей:

| Компонент | Назначение | Примеры |
| :--- | :--- | :--- |
| **Data Plane** | Sidecar-прокси (Envoy, linkerd-proxy, Ztunnel), обрабатывающие трафик, применяющие политики, собирающие телеметрию. | Envoy, linkerd2-proxy, Ztunnel (Ambient) |
| **Control Plane** | Централизованное управление: конфигурация xDS, сервис-дискавери, CA для mTLS. | Istiod (Istio), Linkerd control plane, Consul servers |

**Важно:** Плоскости масштабируются независимо. Control Plane не участвует в передаче трафика — только в конфигурации Data Plane.

### Ключевые возможности

#### 1. Управление трафиком

Динамическая маршрутизация на основе L7-атрибутов (хост, путь, заголовки):

- **Маршрутизация:** Canary, blue-green, A/B-тестирование.
- **Отказоустойчивость:** Таймауты, ретраи, circuit breaking, outlier detection.
- **Зеркалирование:** Тестирование под нагрузкой без влияния на пользователей.

Полное описание примитивов и примеров — в [Управлении трафиком в Service Mesh](./traffic_management.md).

#### 2. Безопасность (Zero Trust)

- **mTLS по умолчанию:** Автоматическое сквозное шифрование между сервисами.
- **Идентичность:** SPIFFE/SVID или ServiceAccount Kubernetes как основа для `principal`.
- **Политики доступа:** L7-авторизация на основе идентичности, а не IP (подробнее в [Zero Trust](../Networking/Concepts/zero_trust_overview.md)).
- **Сравнение с VPN:** [VPN vs Service Mesh](../Networking/Concepts/vpn_vs_service_mesh.md).

#### 3. Наблюдаемость (Observability)

Автоматический сбор телеметрии без изменений в коде:

- **Золотые сигналы:** Задержка, трафик, ошибки, насыщенность (saturation).
- **Трассировка:** Распределенная трассировка запросов (Jaeger, Tempo).
- **Топология:** Визуализация карты зависимостей (Kiali, Linkerd Viz).
- **Инструменты:** [Kiali и Dex](./istio_observability_and_tools.md), Grafana, Prometheus.

#### 4. Сегментация сети

Микросегментация на уровне сервисов (L7) вместо макросегментации на уровне подсетей (L3):

- **Политики:** `AuthorizationPolicy` в Istio, `ServiceProfile` в Linkerd.
- **Гранулярность:** Контроль доступа по методам HTTP, путям, заголовкам.
- **См. также:** [Network Segmentation](../Networking/Concepts/network_segmentation_and_microsegmentation.md).

---

## Практические сценарии

### Выбор реализации: Istio vs Linkerd vs Consul

| Критерий | Istio | Linkerd | Consul Connect |
| :--- | :--- | :--- | :--- |
| **Философия** | Максимальная функциональность, гибкость | Простота, производительность, безопасность "из коробки" | Универсальность (Service Discovery + Service Mesh) |
| **Прокси** | Envoy (C++), Ztunnel (Rust, Ambient) | linkerd2-proxy (Rust) | Envoy |
| **Архитектура** | Sidecar или Ambient (без sidecar) | Только sidecar | Sidecar (Consul Connect) |
| **Управление трафиком** | L7-маршрутизация, Gateway API, VirtualService | Базовое (ServiceProfile, TrafficSplit) | L7-маршрутизация через Intentions |
| **mTLS** | Автоматическое, гибкие политики | Включено по умолчанию для TCP | Автоматическое через Connect |
| **Наблюдаемость** | Kiali, Prometheus, Jaeger (требует настройки) | Linkerd Viz (встроено) | Consul UI, интеграция с Prometheus |
| **Сложность** | Высокая (много CRD, настроек) | Низкая (быстрая установка, минимум настроек) | Средняя (требует агентов Consul) |
| **Производительность** | Оверхед sidecar: ~5–10 мс задержка, 100–300 МБ RAM на под | Оверхед: ~1–3 мс, 40–60% меньше CPU/RAM чем Istio | Сопоставим с Istio (Envoy) |
| **Production-ready** | **Да** (Ambient Mesh стабилен с Istio 1.29) | **Да** | **Да** |

**Рекомендации по выбору:**

- **Istio:** Сложные L7-сценарии, мультикластер, кастомные политики, Gateway API.
- **Linkerd:** Простота, низкий оверхед, безопасность "из коробки", быстрый старт.
- **Consul:** Гетерогенные среды (VM + Kubernetes), встроенный service discovery, KV-store.

Детальное сравнение Istio и Linkerd — в [Сравнение Istio и Linkerd](./istio_vs_linkerd.md).

### Интеграция с экосистемой

| Инструмент | Интеграция с Service Mesh |
| :--- | :--- |
| **Prometheus** | Сбор метрик из прокси ( scrape-конфигурация через ServiceMonitor или `annotations`). |
| **Grafana** | Визуализация метрик (дашборды через sidecar или provisioning). |
| **Jaeger/Tempo** | Распределенная трассировка через прокси (Envoy поддерживает Zipkin, Jaeger, OpenTelemetry). |
| **Kiali** | Визуализация топологии, политик, телеметрии для Istio (требует Prometheus). |
| **Vault** | Доставка секретов через sidecar (Vault Agent), интеграция с mTLS (CA). |
| **ArgoCD** | GitOps для конфигураций Istio (VirtualService, DestinationRule). |

**См. также:**

- [Chaos Engineering](../Chaos_Engineering/chaos_engineering_overview.md) — fault injection через Service Mesh.
- [Grafana Dashboards](../Grafana/dashboards/definitions_and_concepts.md) — импорт дашбордов через sidecar.

---

## Дополнительная информация

### Ограничения и операционные аспекты

| Аспект | Описание | Митигация |
| :--- | :--- | :--- |
| **Задержка** | +1–10 мс на hop (sidecar → sidecar). Ambient снижает оверхед. | Использовать Ambient, оптимизировать таймауты. |
| **Потребление ресурсов** | Sidecar: 50–300 МБ RAM, 50–500 mCPU на под. | Ambient (разделение прокси), лимиты ресурсов. |
| **Сложность эксплуатации** | Требует экспертизы: xDS, CRD, mTLS, политики. | Обучение, мониторинг Control Plane, Linkerd для простоты. |
| **Совместимость** | Проблемы с не-HTTP/gRPC, legacy-протоколами, UDP. | Тестирование, fallback на TCP-прокси, Consul Connect. |
| **Отладка** | Трафик прозрачен, но требует инструментов (Kiali, tap). | Kiali, `istioctl analyze`, `linkerd tap`, трассировка. |

### Актуальность

- **Istio 1.29:** Ambient Mesh production-ready, мультикластер в beta, Gateway API GA.
- **Linkerd 2.x:** Стабильная работа, фокус на производительности и безопасности.
- **Gateway API:** Предпочтительный способ конфигурации в Istio (вместо VirtualService/DestinationRule).
- **eBPF:** Растущая конкуренция (Cilium Service Mesh), но классические mesh (Istio, Linkerd) доминируют.

**Источники:**

- [Istio 1.29 Release Notes](https://istio.io/latest/news/releases/1.29.x/announcing-1.29/)
- [Istio Ambient Multicluster Beta](https://istio.io/latest/blog/2026/ambient-multinetwork-multicluster-beta/)
- [Service Mesh Comparison](https://dasroot.net/posts/2025/12/service-mesh-comparison-istio-linkerd-consul-connect/)

### Связанные документы

- **Реализации:** [Istio Architecture](./istio_architecture.md), [Istio vs Linkerd](./istio_vs_linkerd.md)
- **Трафик:** [Traffic Management](./traffic_management.md), [Proxy Sidecar](./proxy_sidecar.md)
- **Observability:** [Kiali и Dex](./istio_observability_and_tools.md)
- **Безопасность:** [Zero Trust](../Networking/Concepts/zero_trust_overview.md), [VPN vs Service Mesh](../Networking/Concepts/vpn_vs_service_mesh.md)
- **Альтернативы:** [Consul Connect](../Consul/consul_overview.md)
