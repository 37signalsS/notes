# ip route: управление маршрутизацией в Linux

**`ip route`** — команда `iproute2` для управления таблицей маршрутизации ядра Linux.

## Навигация

### Основы

- **[Основы маршрутизации](./ip_route_basics.md)** — структура маршрута, типы, таблицы, proto, scope
- **[Практические сценарии](./ip_route_practical.md)** — просмотр, добавление, удаление, DHCP-нюансы
- **[Правила маршрутизации](./ip_rule_pbr.md)** — ip rule, Policy-Based Routing

---

## Быстрый старт

```bash
# Показать маршруты
ip route show

# Добавить маршрут
ip route add 10.0.0.0/8 via 192.168.1.1 dev eth0

# Проверить маршрут
ip route get 8.8.8.8

# Удалить маршрут
ip route del default
```

---

## Ключевые концепции

- **Таблицы:** local (255), main (254), default (253), custom (1-252)
- **Типы маршрутов:** unicast, local, broadcast, blackhole, unreachable, prohibit
- **Источники (proto):** kernel, static, dhcp, ra, boot
- **Область действия (scope):** global, link, host, nowhere

---

## Связанные документы

- **[Сетевой уровень](../../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md)** — основы маршрутизации
- **[Policy-Based Routing](../../Policy_Based_Routing/index.md)** — множественные таблицы
- **[Оптимизация TCP](../../Concepts/tcp_tuning.md)** — initcwnd, MSS
- **[ip address](./ip_address.md)** — управление адресами
- **[ip neighbour](./ip_neighbour.md)** — ARP/NDP таблица
