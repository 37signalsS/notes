# Установка DNS-сервера BIND

## Определения

**BIND9 (Berkeley Internet Name Domain version 9)** — наиболее распространённая реализация DNS-сервера, обеспечивающая гибкость и поддержку современных стандартов безопасности.

**dnsutils** — пакет диагностических утилит (таких как `dig`, `nslookup`, `host`), необходимых для проверки работы DNS-серверов.

## Базовые концепции

### Состав пакетов

При установке BIND в различных дистрибутивах могут использоваться разные пакеты:

| Пакет | Назначение |
|-------|------------|
| `bind9` / `bind` | Основной демон DNS-сервера (`named`). |
| `bind9utils` / `bind-utils` | Утилиты для управления и проверки конфигурации (`rndc`, `named-checkconf`). |
| `dnsutils` / `bind-utils` | Клиентские утилиты для диагностики (`dig`, `nslookup`). |
| `bind9-doc` | Локальная справочная документация. |

## Практические сценарии

### Установка в Debian / Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y bind9 dnsutils
sudo systemctl enable --now bind9
```

#### Проверка статуса службы

```bash
systemctl status bind9
```

### Установка в дистрибутивах семейства RHEL (Red Hat Enterprise Linux)

К семейству RHEL относятся CentOS, Rocky Linux и AlmaLinux.

```bash
sudo dnf install -y bind bind-utils
sudo systemctl enable --now named
```

> **Примечание:** В этих дистрибутивах демон всегда называется `named`.

### Установка в Alpine Linux

```bash
apk add bind bind-utils
rc-update add named
rc-service named start
```

### Проверка работоспособности

После установки рекомендуется выполнить базовую проверку:

1. **Версия ПО:**

   ```bash
   named -v
   ```

2. **Порты (UDP/TCP 53):**

   ```bash
   ss -tlnp | grep :53
   ```

3. **Локальный запрос:**

   ```bash
   dig @127.0.0.1 localhost
   ```

4. **Проверка синтаксиса:**

   ```bash
   sudo named-checkconf
   ```

## Дополнительная информация

- Актуально для версий BIND 9.18+ **LTS (Long Term Support)** и 9.20+ **ESV (Extended Support Version)**.
- При возникновении ошибок запуска проверьте настройки AppArmor или SELinux.
- Убедитесь, что брандмауэр разрешает входящий трафик на порты `53/udp` и `53/tcp`.

**См. также:**

- [Диагностика и решение проблем](./troubleshooting.md)
- [Настройка Master-сервера](./master_server_local_zone.md)
- [Средства диагностики DNS](../../../Diagnostics/Networking/dns/overview.md)
