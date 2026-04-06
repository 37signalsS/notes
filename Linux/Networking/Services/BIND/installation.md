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

Актуально для BIND 9.18+ (LTS) и 9.20+ (ESV). При проблемах с запуском проверьте логи AppArmor/SELinux, откройте в брандмауэре UDP/53 и TCP/53. Подробнее: [Troubleshooting](./troubleshooting.md), [Диагностика DNS](../../../Diagnostics/Networking/dns/overview.md), [Настройка master-сервера](./master_server_local_zone.md).
