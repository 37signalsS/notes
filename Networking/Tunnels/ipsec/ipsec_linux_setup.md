# IPSec: практическая настройка на Linux

## Сценарий: Подключение к API партнёра через IPSec

**Контекст:** Организация «СуперСервис» подключается к закрытому API «МегаТелеком». Инфраструктура партнёра стандартизирована, требуется IPSec Network-Network.

**Схема:**

```
IPSec: 10.0.1.1 <-> 10.0.255.1
Сервис: 192.168.1.1 <-> 192.168.255.1
```

**Особенности Network-Network:**

- IPSec поднимается между одними IP-адресами (внешние интерфейсы)
- Сервис работает между другими IP-адресами (внутренние сети)
- Фильтрация внутри инфраструктуры партнёра по внутренним IP

---

## Настройка на Linux (KAME/racoon)

### Установка (Debian/Ubuntu)

```bash
apt-get install racoon ipsec-tools
```

### Компоненты KAME

- **racoon** — демон управления ISAKMP-туннелем (IKE)
- **setkey** — утилита управления SA/SP-туннелями

---

## Конфигурация racoon (`/etc/racoon.conf`)

```bash
# Путь к файлу с PSK-ключами
path pre_shared_key "/etc/racoon/psk.txt";
log debug;

# Интерфейс для ISAKMP-туннеля
listen {
    isakmp 10.0.1.1 [500];
    strict_address;
}

# Фаза 1: настройки ISAKMP SA
remote 10.0.255.1 {
    nat_traversal off;
    exchange_mode main;
    my_identifier address 10.0.1.1;
    proposal {
        encryption_algorithm 3des;
        hash_algorithm sha1;
        authentication_method pre_shared_key;
        dh_group modp1024;
        lifetime time 86400 sec;
    }
}

# Фаза 2: параметры IPsec SA
sainfo address 192.168.1.1 any address 192.168.255.1 any {
    pfs_group modp1024;
    lifetime time 28800 sec;
    encryption_algorithm 3des;
    authentication_algorithm hmac_sha1;
    compression_algorithm deflate;
}
```

### Файл PSK-ключей (`/etc/racoon/psk.txt`)

```bash
# Формат: <REMOTE IP> <PASSWORD>
# Владелец: пользователь, от имени которого запущен racoon
10.0.255.1 SUPERPASSWORD
```

---

## Конфигурация setkey (`/etc/ipsec-tools.conf`)

```bash
flush;
spdflush;

# Исходящий трафик: 192.168.1.1 → 192.168.255.1
spdadd 192.168.1.1/32 192.168.255.1/32 any -P out ipsec
esp/tunnel/10.0.1.1-10.0.255.1/require;

# Входящий трафик: 192.168.255.1 → 192.168.1.1
spdadd 192.168.255.1/32 192.168.1.1/32 any -P in ipsec
esp/tunnel/10.0.255.1-10.0.1.1/require;
```

### Альтернатива через iproute2

```bash
ip xfrm state  # управление SA
ip xfrm policy # управление SP
```

---

## Настройка сети

### Добавление secondary IP

```bash
ip addr add 192.168.1.1/32 dev eth1 label eth1:1
```

### Маршрут до сервиса партнёра

```bash
ip route add 192.168.255.1/32 dev eth1:1 src 192.168.1.1
```

### Статическая ARP-запись (обход проблемы с /32 маской)

```bash
arp -s 192.168.255.1 00:00:00:00:00:01 -i eth1:1
```

**Важно:** Без статической ARP Linux будет слать ARP-запросы на 192.168.255.1, но не получит ответа (маска /32). Результат: `No route to host`.

---

## Альтернативные реализации IPSec на Linux

| Решение | Описание |
|---------|----------|
| **KAME** | Из BSD, наиболее предсказуемый (racoon + setkey) |
| **strongSwan** | Современная реализация с поддержкой IKEv2 |
| **LibreSwan** | Форк FreeSwan, фокус на безопасности |
| **Shorewall** | Фронтенд для iptables + IPSec |

---

## Связанные документы

- **[IPSec: архитектура](./ipsec_architecture.md)** — концепции SA, SP, режимы инкапсуляции
- **[GRE с IPsec](./gre/gre.md)** — комбинация GRE + IPSec
- **[Troubleshooting IPSec](./ipsec_troubleshooting.md)** — диагностика проблем
