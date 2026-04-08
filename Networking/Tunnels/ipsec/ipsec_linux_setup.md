# IPsec: настройка KAME/racoon на Linux

> **SSoT:** Основной документ по IPsec — [ipsec.md](./ipsec.md). Данный файл содержит историческую документацию по устаревшей реализации KAME/racoon.
>
> **⚠ Устаревшая реализация:** KAME/racoon не обновляется с 2010-х. Для современных развёртываний используйте [strongSwan](./ipsec.md#установка-strongswan-debianubuntu) или [LibreSwan](./ipsec.md).

---

## Definitions

**KAME** — стек IPv6 и IPsec из BSD, портированный на Linux. Включает демон **racoon** (управление IKE) и утилиту **setkey** (управление SA/SP).

---

## Basic Concepts

### Компоненты KAME

| Компонент | Назначение |
|-----------|------------|
| **racoon** | Демон управления ISAKMP-туннелем (IKEv1) |
| **setkey** | Утилита управления SA/SP-туннелями |
| **ipsec-tools** | Пакет с racoon и setkey для Linux |

### Ключевые файлы конфигурации

| Файл | Назначение |
|------|------------|
| `/etc/racoon.conf` | Основная конфигурация IKE (фазы 1 и 2) |
| `/etc/racoon/psk.txt` | Pre-Shared Key для аутентификации |
| `/etc/ipsec-tools.conf` | Политики безопасности (SP) для setkey |

---

## Practical Scenarios

### Полная конфигурация KAME/racoon (Network-Network)

**Сценарий:** Подключение к API партнёра через IPSec.

```
IPSec: 10.0.1.1 <-> 10.0.255.1
Сервис: 192.168.1.1 <-> 192.168.255.1
```

### Установка (Debian/Ubuntu)

```bash
apt-get install racoon ipsec-tools
```

### Конфигурация racoon (`/etc/racoon.conf`)

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

### Конфигурация setkey (`/etc/ipsec-tools.conf`)

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

### Настройка сети

**Добавление secondary IP:**

```bash
ip addr add 192.168.1.1/32 dev eth1 label eth1:1
```

**Маршрут до сервиса партнёра:**

```bash
ip route add 192.168.255.1/32 dev eth1:1 src 192.168.1.1
```

**Статическая ARP-запись (обход проблемы с /32 маской):**

```bash
arp -s 192.168.255.1 00:00:00:00:00:01 -i eth1:1
```

> **Важно:** Без статической ARP Linux будет слать ARP-запросы на 192.168.255.1, но не получит ответа (маска /32). Результат: `No route to host`.

### Управление службами

```bash
# Применение политик setkey
setkey -f /etc/ipsec-tools.conf

# Запуск racoon
service racoon start

# Перезагрузка конфигурации
service racoon reload
```

---

## Additional Information

### Альтернативные реализации IPsec на Linux

| Решение | Описание | Актуальность |
|---------|----------|--------------|
| **strongSwan** | Современная реализация, поддержка IKEv2, активная разработка | **Рекомендуется** |
| **LibreSwan** | Форк FreeSWAN, фокус на безопасности, поддержка Red Hat | Актуально |
| **KAME/racoon** | Из BSD, наиболее предсказуемый, устаревший | Устаревший |
| **Shorewall** | Фронтенд для iptables + IPsec | Обёртка |

### Почему KAME устарел

- **Последнее обновление:** 2010-е годы
- **Поддержка IKEv2:** Отсутствует (только IKEv1)
- **Алгоритмы:** 3DES, SHA-1 — считаются небезопасными
- **Сообщество:** Минимальная поддержка и документация

### Миграция на strongSwan

Для миграции с KAME на strongSwan:

1. Замените `racoon.conf` на эквивалент в `/etc/ipsec.conf`
2. Перенесите PSK из `/etc/racoon/psk.txt` в `/etc/ipsec.secrets`
3. Замените `setkey` политики на `ip xfrm` или доверьтесь charon
4. См. [базовую конфигурацию strongSwan](./ipsec.md#базовая-конфигурация-strongswan-etciptconf)

### Связанные документы

- **[IPsec (основной SSoT)](./ipsec.md)** — определения, протоколы, настройка strongSwan, troubleshooting
- **[Архитектура IPsec](./ipsec_architecture.md)** — детальное описание SA, SP, режимы инкапсуляции
- **[Диагностика IPsec](./ipsec_troubleshooting.md)** — проверка SA, анализ трафика, логи
- **[GRE с IPsec](../gre/gre.md)** — комбинация GRE + IPsec
