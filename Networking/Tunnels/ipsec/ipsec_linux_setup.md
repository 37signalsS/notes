# IPsec: настройка KAME/racoon на Linux

> **Основной документ:** [ipsec.md](./ipsec.md).

Данный файл содержит историческую документацию по устаревшей реализации IPsec через стек KAME/racoon.

> **Устаревшая реализация:** KAME/racoon не обновляется с 2010-х. Для современных систем используйте **[strongSwan](./ipsec.md)** или **LibreSwan**.

---

## Определения

**KAME** — стек IPv6 и IPsec из BSD, портированный на Linux. Включает демон **racoon** (управление IKE) и утилиту **setkey** (управление SA/SP).

---

## Основные концепции

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
| `/etc/racoon/psk.txt` | Pre-Shared Key (PSK) для аутентификации |
| `/etc/ipsec-tools.conf` | Политики безопасности (SP) для setkey |

---

## Практические сценарии

### Полная конфигурация KAME/racoon (Network-to-Network)

**Сценарий:** Подключение к API партнёра через IPsec.

```
IPsec Gateway: 10.0.1.1 <-> 10.0.255.1
Local Service: 192.168.1.1 <-> 192.168.255.1
```

### Установка (Debian/Ubuntu)

```bash
apt-get install racoon ipsec-tools
```

### Конфигурация racoon (`/etc/racoon.conf`)

```bash
path pre_shared_key "/etc/racoon/psk.txt";
log debug;

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
        encryption_algorithm 3des; # Устаревший алгоритм!
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
}
```

### Управление и диагностика

```bash
# Применение политик setkey
setkey -f /etc/ipsec-tools.conf

# Запуск racoon
service racoon start

# Просмотр логов
journalctl -u racoon -f
```

---

## Дополнительная информация

### Почему KAME устарел
- **Поддержка IKEv2:** Отсутствует (только IKEv1).
- **Алгоритмы:** 3DES, SHA-1 считаются небезопасными.
- **Миграция:** рекомендуется перейти на strongSwan. См. **[Основной документ](./ipsec.md)**.

### Связанные документы

- **[IPsec (основной документ)](./ipsec.md)** — определения, протоколы, настройка strongSwan, troubleshooting
- **[Архитектура IPsec](./ipsec_architecture.md)** — детальное описание SA, SP, режимы инкапсуляции
- **[Диагностика IPsec](./ipsec_troubleshooting.md)** — проверка SA, анализ трафика, логи
