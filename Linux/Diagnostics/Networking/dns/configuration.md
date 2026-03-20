# Конфигурация DNS-клиента

## Файлы конфигурации

| Файл | Назначение |
| :--- | :--- |
| `/etc/nsswitch.conf` | Порядок разрешения (files/dns) |
| `/etc/hosts` | Локальная база имён |
| `/etc/resolv.conf` | DNS-серверы (может генерироваться автоматически) |
| `/etc/systemd/resolved.conf` | Настройки `systemd-resolved` |

Подробно — в [Настройка DNS-клиента](../../../Networking/Concepts/dns_client.md).

## systemd-resolved

В современных дистрибутивах (Ubuntu 17.10+, RHEL 7+) за разрешение имён отвечает `systemd-resolved` — локальный кэширующий резолвер.

**Особенности:**

- `/etc/resolv.conf` → symlink на `/run/systemd/resolve/stub-resolv.conf`
- `nameserver 127.0.0.53` — локальный stub-резолвер
- Получает DNS-серверы от DHCP, NetworkManager или статической конфигурации

---

**Связанные темы:**

* [Порядок разрешения имён](./name_resolution.md) — как работает резолвинг
* [Базовая диагностика](./basic_diagnostics.md) — проверка конфигурации
* [Настройка DNS-клиента](../../../Networking/Concepts/dns_client.md)
