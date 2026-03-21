# IPSec (IP Security)

**IPSec** — набор протоколов для организации защищённого соединения на сетевом уровне (L3) путём аутентификации и шифрования IP-пакетов.

## Навигация

### Основы

- **[Архитектура и концепции](./ipsec_architecture.md)** — SA, SP, режимы инкапсуляции, NAT-T, MTU
- **[Настройка на Linux](./ipsec_linux_setup.md)** — KAME/racoon, конфигурация, сетевая настройка
- **[Диагностика](./ipsec_troubleshooting.md)** — проверка SA, анализ трафика, логи

---

## Ключевые особенности

- Не создаёт явных туннельных интерфейсов (использует SA + SP)
- Двухфазная модель: ISAKMP SA → IPsec SA
- ESP (протокол 50) — шифрование + аутентификация
- AH (протокол 51) — только аутентификация

---

## Быстрый старт

```bash
# Установка KAME
apt-get install racoon ipsec-tools

# Запуск диагностики
racoonctl show-sa isakmp
racoonctl show-sa esp
```

---

## Связанные документы

- **[Обзор туннелирования](../tunneling_overview.md** — классификация туннельных протоколов
- **[GRE с IPsec](../gre/gre.md** — комбинация GRE + IPSec
- **[WireGuard](../../../Vpn/wireguard.md** — современная альтернатива
- **[MTU и VPN](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — проблемы фрагментации
