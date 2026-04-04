# Конфигурация DNS-клиента

## Определения

**DNS-клиент** — компонент ОС, ответственный за разрешение доменных имён в IP-адреса. В Linux управляется комбинацией конфигурационных файлов и служб (`systemd-resolved`, NetworkManager).

**Системный резолвер** — механизм glibc, использующий `/etc/nsswitch.conf` для определения порядка разрешения имён. Подробнее — в [Настройка DNS-клиента](../../../Networking/Concepts/dns_client.md).

## Базовые концепции

### Файлы конфигурации

| Файл | Назначение | Диагностика |
| :--- | :--- | :--- |
| `/etc/nsswitch.conf` | Порядок разрешения (`files dns`) | Проверить строку `hosts:` |
| `/etc/hosts` | Локальная база имён (наивысший приоритет) | Проверить на несанкционированные записи |
| `/etc/resolv.conf` | DNS-серверы (может генерироваться автоматически) | Проверить symlink и содержимое |
| `/etc/systemd/resolved.conf` | Настройки `systemd-resolved` | Проверить секцию `[Resolve]` |

### systemd-resolved

В современных дистрибутивах (Ubuntu 17.10+, RHEL 7+, Debian 10+) за разрешение имён отвечает `systemd-resolved` — локальный кэширующий резолвер.

**Особенности:**

- `/etc/resolv.conf` → symlink на `/run/systemd/resolve/stub-resolv.conf`
- `nameserver 127.0.0.53` — локальный stub-резолвер
- Получает DNS-серверы от DHCP, NetworkManager или статической конфигурации

## Практические сценарии

### Сценарий 1: Проверка конфигурации при проблемах с DNS

```bash
# 1. Проверить порядок разрешения имён
grep '^hosts:' /etc/nsswitch.conf
# Ожидается: hosts: files dns

# 2. Проверить /etc/hosts на несанкционированные записи
cat /etc/hosts

# 3. Проверить resolv.conf (файл или symlink)
ls -l /etc/resolv.conf
cat /etc/resolv.conf

# 4. Проверить статус systemd-resolved
resolvectl status

# 5. Проверить статистику кэша
resolvectl statistics
```

### Сценарий 2: Проблема с перезаписью resolv.conf

**Симптом:** Ручные изменения в `/etc/resolv.conf` сбрасываются после перезагрузки.

**Диагностика:**

```bash
# Проверить, является ли файл symlink
ls -l /etc/resolv.conf
# Если → /run/systemd/resolve/stub-resolv.conf, управляет systemd-resolved
# Если → /run/NetworkManager/resolv.conf, управляет NetworkManager
```

**Решение:**

| Менеджер | Где настраивать DNS |
| :--- | :--- |
| `systemd-resolved` | `/etc/systemd/resolved.conf` → секция `[Resolve]`, `DNS=` |
| NetworkManager | `nmcli connection modify <conn> ipv4.dns "8.8.8.8 8.8.4.4"` |
| `netplan` | YAML-конфиг → `nameservers: addresses: [8.8.8.8]` |

```bash
# После изменений в resolved.conf
sudo systemctl restart systemd-resolved
```

### Сценарий 3: Конфликт служб управления DNS

**Симптом:** Несколько служб пытаются управлять `/etc/resolv.conf`, DNS работает нестабильно.

**Диагностика:**

```bash
# Проверить, какой сервис управляет resolv.conf
ls -l /etc/resolv.conf

# Проверить конфигурацию NetworkManager
cat /etc/NetworkManager/NetworkManager.conf

# Проверить статус systemd-resolved
systemctl status systemd-resolved
```

**Решение — отключить управление DNS со стороны NetworkManager:**

```ini
# /etc/NetworkManager/NetworkManager.conf
[main]
dns=none
```

Или настроить координацию:

```ini
[main]
dns=systemd-resolved
```

### Сценарий 4: Проверка конфигурации systemd-resolved

```bash
# Проверить текущие DNS-серверы
resolvectl status

# Проверить статистику запросов
resolvectl statistics

# Очистить кэш при проблемах
resolvectl flush-caches

# Тестовый запрос через systemd-resolved
resolvectl query example.com
```

## Дополнительная информация

**Связанные темы:** [Настройка DNS-клиента](../../../Networking/Concepts/dns_client.md) — полное руководство по конфигурации · [Порядок разрешения имён](./name_resolution.md) · [Базовая диагностика](./basic_diagnostics.md)
