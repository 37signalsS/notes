# Установка BIND

## Определения

**BIND9** — текущая стабильная ветка программного обеспечения BIND (Berkeley Internet Name Domain).

**dnsutils** — пакет утилит для диагностики DNS (`dig`, `nslookup`, `host`, `nsupdate`).

## Базовые концепты

### Пакеты BIND

| Пакет | Назначение |
|-------|------------|
| `bind9` | Основной демон DNS-сервера |
| `bind9utils` | Дополнительные утилиты (`rndc`, `nsupdate`) |
| `dnsutils` | Клиентские утилиты (`dig`, `nslookup`, `host`) |
| `bind9-doc` | Документация (при наличии в репозитории) |

## Практические сценарии

### 1. Установка на Debian/Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y bind9 dnsutils
sudo systemctl enable --now bind9
```

**Проверка установки:**

```bash
# Статус службы
systemctl status bind9

# Версия BIND
named -v

# Проверка конфигурации
named-checkconf
```

### 2. Установка на RHEL/CentOS/Rocky Linux

```bash
sudo dnf install -y bind bind-utils
sudo systemctl enable --now named
```

> **Примечание:** В RHEL-семействе демон называется `named` (Name Daemon), а не `bind9`.

### 3. Установка на Alpine Linux

```bash
apk add bind bind-utils
rc-update add named
rc-service named start
```

### 4. Проверка базовой работоспособности

```bash
# Проверка listening-портов (UDP/TCP 53)
ss -tlnp | grep :53

# Тест локального разрешения
dig @127.0.0.1 localhost

# Проверка версии через dig
dig @127.0.0.1 version.bind chaos txt
```

## Дополнительная информация

- **AppArmor/SELinux:** При проблемах с запуском проверьте логи безопасности
- **Брандмауэр:** Откройте порты UDP/53 и TCP/53 для входящих соединений
- **Обновления безопасности:** Проверяйте CVE-уведомления (CVE-2025-13878 исправлена в 9.18.44/9.20.18)
- **Сопутствующие заметки:**
  - [Troubleshooting](./troubleshooting.md) — диагностика и отладка
  - [Диагностика DNS](../../../Diagnostics/Networking/dns_diagnostics.md) — утилиты `dig`, `nslookup`
  - [Настройка первичного сервера](./master_server_local_zone.md) — следующая конфигурация
