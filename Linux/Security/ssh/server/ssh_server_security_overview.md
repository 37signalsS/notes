# SSH Server Security Overview

## Definitions → Basic Concepts → Practical Scenarios → Additional Information

## Definitions

**Безопасность SSH-сервера** — комплекс мер по защите `sshd` от несанкционированного доступа, brute-force атак и эксплуатации уязвимостей. `sshd` — критическая служба удалённого управления, требующая многоуровневой защиты.

**Defense in Depth** — принцип многослойной безопасности: компрометация одного уровня не даёт полного контроля.

## Basic Concepts

### Компоненты защиты SSH-сервера

Безопасность SSH строится на четырёх уровнях:

1. **Аутентификация** — подтверждение личности пользователя. Методы: [SSH-ключи (pubkey)](./ssh_authentication.md) (рекомендуется), парольная (отключается), Kerberos/GSSAPI. Ключевые директивы: `PubkeyAuthentication`, `PasswordAuthentication`, `PermitRootLogin`.

2. **Контроль доступа** — ограничение круга допущенных субъектов. Механизмы: [AllowUsers/AllowGroups](./ssh_access_control.md) в `sshd_config`, фильтрация по IP через файрвол (iptables/nftables), [Port Knocking](./port_knocking.md) для скрытия порта.

3. **Укрепление конфигурации (Hardening)** — отключение неиспользуемых функций, ограничение алгоритмов шифрования, настройка таймаутов и логирования. Полное руководство: [SSH Hardening Best Practices](./ssh_hardening_best_practices.md).

4. **Мониторинг и реагирование** — анализ логов (`auth.log`, `btmp`, `wtmp`), обнаружение brute-force, автоматическая блокиция через [fail2ban](../../Tools/fail2ban.md), аудит через [ssh-audit](./ssh_hardening_best_practices.md#аудит-безопасности). Подробнее: [SSH Monitoring and Troubleshooting](./ssh_monitoring_and_troubleshooting.md).

### Модель угроз SSH

| Угроза | Описание | Метод защиты |
| :--- | :--- | :--- |
| **Brute-force** | Перебор паролей | Отключение `PasswordAuthentication`, fail2ban |
| **MITM** | Перехват и подмена трафика | Проверка host key (`known_hosts`), строгая проверка ключей |
| **Утечка приватного ключа** | Компрометация клиента | Passphrase на ключе, отзыв через удаление из `authorized_keys` |
| **Неавторизованный доступ** | Вход постороннего | `AllowUsers`/`AllowGroups`, файрвол, Port Knocking |
| **Уязвимости алгоритмов** | Устаревшие шифры | Ограничение `KexAlgorithms`, `Ciphers`, `MACs` |
| **Сканирование портов** | Обнаружение SSH-службы | Смена порта, Port Knocking, fail2ban |

## Practical Scenarios

### Быстрый чек-лист безопасности SSH

```bash
# 1. Проверить текущую конфигурацию
sudo sshd -T | grep -E "pubkeyauth|passwordauth|permitroot|loglevel"

# 2. Убедиться, что вход по паролю отключён
sudo sshd -T | grep "passwordauthentication"
# Ожидается: passwordauthentication no

# 3. Проверить разрешённых пользователей
sudo sshd -T | grep -E "allowusers|allowgroups"

# 4. Проверить уровень логирования
sudo sshd -T | grep "loglevel"
# Ожидается: loglevel VERBOSE или INFO

# 5. Проверить наличие fail2ban
systemctl status fail2ban

# 6. Просканировать ssh-audit
ssh-audit localhost
```

## Additional Information

### Структура документации по SSH-серверу

| Файл | Тема | Описание |
| :--- | :--- | :--- |
| [ssh_authentication.md](./ssh_authentication.md) | Аутентификация | Типы ключей, генерация, `authorized_keys`, права доступа |
| [ssh_access_control.md](./ssh_access_control.md) | Контроль доступа | AllowUsers/AllowGroups, фильтрация по IP, смена порта |
| [ssh_hardening_best_practices.md](./ssh_hardening_best_practices.md) | Hardening | Директивы sshd_config, алгоритмы шифрования, резервный SSH |
| [ssh_monitoring_and_troubleshooting.md](./ssh_monitoring_and_troubleshooting.md) | Мониторинг | Логи, аудит входов, обнаружение атак, ssh-audit |
| [port_knocking.md](./port_knocking.md) | Port Knocking | Настройка knockd, скрытие SSH от сканирования |

### Связанные темы (клиентская часть)

- [SSH Overview](../ssh_overview.md) — обзор протокола и архитектуры
- [SSH Client Config](../ssh_client_config.md) — настройка клиента
- [SSH Troubleshooting](../ssh_troubleshooting.md) — диагностика проблем подключения
