# L4-маршрутизация — TCPRoute и UDPRoute

**Надёжность:** 10 (SSoT + Спецификация Gateway API v1.6)

## Определения

**L4-маршрутизация** — передача трафика на транспортном уровне (TCP/UDP) без анализа содержимого пакетов прикладного уровня. Контроллер оперирует только портами и IP-адресами, не расшифровывая протоколы (например, SSH или проприетарные бинарные протоколы баз данных).

**TCPRoute (v1)** — ресурс Gateway API для маршрутизации TCP-трафика. С июля 2026 года (версия v1.6) находится в статусе **Standard (GA)**.

**UDPRoute (v1)** — ресурс Gateway API для маршрутизации UDP-трафика. С июля 2026 года (версия v1.6) находится в статусе **Standard (GA)**.

## Базовые концепции

### Область применения

L4-маршрутизация используется в случаях, когда L7-анализ невозможен (шифрованные протоколы без SNI) или нецелесообразен (требуется максимальная скорость):

- **Базы данных:** PostgreSQL, MySQL, Redis, ClickHouse.
- **Системные службы:** SSH, SFTP.
- **Сетевые службы:** DNS (UDP), NTP.
- **Игры и мультимедиа:** Игровые серверы, VoIP (SIP), потоковое вещание.

### Статус ресурсов и версии

К середине 2026 года основные ресурсы транспортного уровня стабилизированы:

| Ресурс | Версия API (v1.6+) | Статус | Примечание |
| :--- | :--- | :--- | :--- |
| **TCPRoute** | `gateway.networking.k8s.io/v1` | **Standard (GA)** | Поддержка во всех мажорных контроллерах |
| **UDPRoute** | `gateway.networking.k8s.io/v1` | **Standard (GA)** | Рекомендуется для DNS и игровых серверов |
| **TLSRoute** | `gateway.networking.k8s.io/v1` | **Standard (GA)** | Маршрутизация по SNI без терминации TLS |

> **Примечание:** В версиях Gateway API ниже v1.6 данные ресурсы могут находиться в канале `v1alpha2` (Experimental). Для использования стабильных версий `v1` необходимо обновить CRD до версии v1.6.0+.

### Особенности настройки

Настройка L4-маршрутов требует координации портов на разных уровнях:

1. **Инфраструктура:** Балансировщик нагрузки (Cloud LB или MetalLB) должен поддерживать проброс произвольных портов.
2. **Gateway Listener:** Слушатель в ресурсе `Gateway` должен быть настроен на протокол `TCP` или `UDP` и соответствующий порт.
3. **Route:** Ресурс `TCPRoute`/`UDPRoute` связывает слушателя с сервисом бэкенда.

## Практические сценарии

### Настройка TCPRoute (Пример: Доступ к PostgreSQL)

**1. Настройка слушателя в Gateway:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: database-gateway
spec:
  gatewayClassName: envoy-gateway
  listeners:
  - name: postgres
    protocol: TCP
    port: 5432
    allowedRoutes:
      kinds:
      - kind: TCPRoute
```

**2. Создание маршрута TCPRoute:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: TCPRoute
metadata:
  name: postgres-route
spec:
  parentRefs:
  - name: database-gateway
    sectionName: postgres
  rules:
  - backendRefs:
    - name: postgres-service
      port: 5432
```

### Настройка UDPRoute (Пример: Внешний DNS)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: UDPRoute
metadata:
  name: dns-external-route
spec:
  parentRefs:
  - name: udp-gateway
    sectionName: dns-listener
  rules:
  - backendRefs:
    - name: coredns-svc
      port: 53
```

## Дополнительная информация

### Ограничения L4-маршрутизации

- **Отсутствие метаданных:** Невозможно использовать маршрутизацию по путям, хостам (кроме SNI в TLSRoute) или заголовкам.
- **Порты:** Каждый шлюз (Gateway) ограничен количеством доступных портов на внешнем IP-адресе.
- **Производительность:** Хотя L4 быстрее L7 за счет отсутствия разбора протокола, проксирование через Envoy или Traefik всё же создает минимальные задержки по сравнению с чистым `IPVS` или **eBPF (Cilium 1.20+)**. Cilium реализует L4-маршрутизацию на уровне ядра, что делает его предпочтительным выбором для высоконагруженных бинарных протоколов.

**См. также:**

- [Определения Gateway API](./definitions.md) — базовые концепции и архитектура.
- [Ресурсы (CRD)](./resources.md) — обзор всех типов объектов (включая TLSRoute).
- [Реализации: Envoy Gateway](./envoy_gateway.md) — рекомендуемый контроллер для L4.
- [Cilium: Высокопроизводительный CNI](../Network/CNI/cilium.md) — архитектура eBPF.
- [Traefik](./traefik.md) — особенности работы с контроллером Traefik v3.x.

**Родительская тема:** [Gateway API](./definitions.md)
