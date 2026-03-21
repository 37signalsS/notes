# GRE (Generic Routing Encapsulation)

**GRE** — протокол туннелирования для инкапсуляции широкого спектра сетевых протоколов (IPv4, IPv6, Ethernet) внутри IP-пакетов.

## Навигация

### Основы

- **[Архитектура и концепции](./gre_architecture.md)** — формат заголовка, версии, сравнение с другими протоколами
- **[Практические сценарии](./gre_practical_scenarios.md)** — point-to-point, mGRE, GRETAP
- **[GRE с IPsec](./gre_ipsec_integration.md)** — защищённая комбинация
- **[Troubleshooting](./gre_troubleshooting.md)** — диагностика проблем

---

## Ключевые характеристики

- **Протокол:** IP 47
- **Уровень:** L2/L3 (GRETAP для L2)
- **Шифрование:** Отсутствует (требуется IPsec)
- **Топология:** Point-to-Point, Multipoint (mGRE)
- **Overhead:** 24-42 байта

---

## Быстрый старт

```bash
# Point-to-Point GRE
ip link add gre0 type gre remote 192.0.2.2 local 192.0.2.1 key 100
ip link set gre0 up
ip address add 10.0.1.1/30 dev gre0
```

---

## Связанные документы

- **[IPSec](../ipsec/ipsec.md** — защищённое туннелирование
- **[VXLAN](../vxlan.md** — масштабируемое L2-туннелирование
- **[Обзор туннелирования](../tunneling_overview.md)** — классификация протоколов
