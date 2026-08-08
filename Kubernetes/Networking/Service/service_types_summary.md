# Сводка по типам Service

> **Reliability Score: 10** (SSoT + Web 2026). Фундаментальный справочник по сетевым абстракциям Kubernetes v1.31–1.36.

## Определения

**Сводка по типам Service** — это консолидированный аналитический обзор всех методов публикации приложений в Kubernetes. Документ служит инструментом для выбора архитектуры сетевой связности на основе требований к уровню OSI, масштабируемости и безопасности.

Теоретический фундамент и механизмы реализации описаны в [Обзоре Service](./service_overview.md).

## Основные концепции

### Иерархия и взаимосвязь типов

Большинство типов сервисов построены по принципу инкапсуляции и расширения функциональности:

1.  **ClusterIP** (Базис) — виртуальный IP для внутреннего взаимодействия.
2.  **NodePort** (L4 Вход) — расширяет ClusterIP, открывая порты на узлах.
3.  **LoadBalancer** (Облачный Вход) — расширяет NodePort, интегрируясь с внешними балансировщиками.

**Автономные типы:**
- **Headless** (`clusterIP: None`) — прямое управление эндпоинтами через DNS.
- **ExternalName** — DNS-псевдоним (CNAME) для внешних ресурсов.

### Сравнительные характеристики уровней доступа

| Тип | Доступность | Уровень OSI | Реализация в ядре | Основной сценарий |
| :--- | :--- | :--- | :--- | :--- |
| **[ClusterIP](./service_type_clusterip.md)** | Внутри кластера | L4 (TCP/UDP) | nftables / IPVS | Внутренние микросервисы |
| **[NodePort](./service_type_nodeport.md)** | Снаружи (Node IP) | L4 | nftables / IPVS | On-premise, Static Routing |
| **[LoadBalancer](./service_type_loadbalancer.md)** | Снаружи (VIP/DNS) | L4 | CCM / MetalLB | Production (Cloud/Bare-Metal) |
| **[Headless](./service_type_headless.md)** | Прямой IP подов | L3/L4 | DNS Records | StatefulSets, gRPC, DB |
| **[ExternalName](./service_type_externalname.md)** | Псевдоним DNS | DNS | CoreDNS CNAME | Интеграция с Legacy/External |

### Технические ограничения и нюансы (v1.36)

- **ClusterIP:** Недоступен извне без Ingress/Gateway. Использует Hairpin NAT для самообращения.
- **NodePort:** Диапазон 30000–32767. Открыт на всех интерфейсах всех узлов (требует Firewall).
- **LoadBalancer:** Поле `loadBalancerIP` устарело; используйте аннотации или `loadBalancerClass`.
- **Dual-Stack:** Все типы поддерживают IPv4/IPv6 через `ipFamilyPolicy` (v1.31+).
- **nftables:** С версии v1.31 является рекомендуемым бэкендом для `kube-proxy`, обеспечивая O(1) производительность.

## Практические сценарии

### Матрица выбора метода публикации

| Задача / Требование | Рекомендуемое решение | Почему? |
| :--- | :--- | :--- |
| **Внутреннее API** | `ClusterIP` | Минимальный оверхед, изоляция. |
| **Базы данных (кворум)** | `Headless Service` | Нужны прямые IP для формирования кластера. |
| **HTTP(S) в Production** | **Gateway API** | Гибкое управление L7, Canary, TLS. |
| **TCP/UDP (не-HTTP)** | `LoadBalancer` | Прямой проброс L4 трафика. |
| **Локальная отладка** | `NodePort` | Не требует сложной инфраструктуры. |
| **Внешние SaaS-сервисы** | `ExternalName` | Абстракция внешнего URL в локальное имя. |

## Дополнительная информация

### Механизмы управления трафиком

| Атрибут | Назначение | Технический эффект |
| :--- | :--- | :--- |
| **`externalTrafficPolicy`** | Сохранение Source IP | `Local` отключает SNAT, но требует Local Endpoints. |
| **`internalTrafficPolicy`** | Node-local трафик | Исключает сетевые переходы между узлами. |
| **`trafficDistribution`** | Топологическая маршрутизация | Заменяет Topology Hints, оптимизирует задержки. |
| **`sessionAffinity`** | Sticky Sessions | Привязка клиента к поду по `ClientIP` (через conntrack). |

### Эволюция сетевого доступа: Service vs Ingress vs Gateway API

1.  **Service (L4):** Стабильный транспорт. Ограничен портами и протоколами.
2.  **Ingress (L7 Legacy):** Узкоспециализирован под HTTP. Сложная расширяемость через вендорские аннотации.
3.  **Gateway API (Modern):** Стандарт 2026 года. Разделяет ответственность (Infrastructure vs Application), нативно поддерживает L4 (TCP/UDP) и L7 (HTTP/gRPC).

### См. также

- [Обзор Service](./service_overview.md)
- [Gateway API — обзор](../gateway_api/definitions.md)
- [Практические сценарии публикации](./service_practical_scenarios.md)

