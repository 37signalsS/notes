# SSH Monitoring and Troubleshooting

## Definitions → Basic Concepts → Practical Scenarios → Additional Information

## Definitions

**SSH Monitoring** — процесс сбора, анализа и визуализации данных о работе SSH-сервера: логи аутентификации, активные сессии, попытки несанкционированного доступа.

**SSH Forensics** — ретроспективный анализ логов для расследования инцидентов: кто, когда и откуда подключался, какие команды выполнялись.

## Basic Concepts

### Журналы SSH

| Файл | Система | Содержание |
| :--- | :--- | :--- |
| `/var/log/auth.log` | Debian/Ubuntu | События аутентификации (успешные/неудачные входы SSH, sudo) |
| `/var/log/secure` | RHEL/CentOS | Аналог `auth.log` |
| `/var/log/btmp` | Все | Неудачные попытки входа (двоичный формат) |
| `/var/log/wtmp` | Все | История успешных входов/выходов (двоичный формат) |
| `/var/log/lastlog` | Все | Время последнего входа каждого пользователя |

### Уровни логирования sshd

| Уровень | Директива `LogLevel` | Содержание |
| :--- | :--- | :--- |
| **Базовый** | `INFO` | Успешные/неудачные входы, закрытие сессий |
| **Расширенный** | `VERBOSE` | Отпечатки SSH-ключей (fingerprint) |
| **Детальный** | `DEBUG` | Пошаговая отладка SSH-протокола (только для диагностики) |

**Настройка:** `/etc/ssh/sshd_config`
```ini
LogLevel VERBOSE
```

### Типичные паттерны в логах

| Паттерн | Значение |
| :--- | :--- |
| `Accepted publickey for user from 192.168.1.100` | Успешный вход по ключу |
| `Failed password for user from 10.0.0.5` | Неудачная попытка входа (пароль) |
| `Invalid user admin from 10.0.0.5` | Несуществующий пользователь |
| `Connection closed by authenticating user` | Клиент прервал аутентификацию |
| `Received disconnect from 192.168.1.100` | Нормальное завершение сессии |
| `Bad ownership or modes for directory` | Нарушены права `~/.ssh` |

## Practical Scenarios

### Сценарий 1: Анализ неудачных попыток входа (brute-force detection)

**Задача:** Выявить IP-адреса с множественными неудачными попытками.

```bash
# Неудачные входы (auth.log)
grep "Failed" /var/log/auth.log | awk '{print $(NF-3)}' | sort | uniq -c | sort -rn

# Неудачные входы (journalctl, последние 24 часа)
journalctl -u sshd --since "24 hours ago" | grep "Failed" | awk '{print $(NF-3)}' | sort | uniq -c | sort -rn

# Просмотр btmp (неудачные попытки)
lastb | head -20
lastb | awk '{print $3}' | sort | uniq -c | sort -rn | head
```

### Сценарий 2: Аудит успешных входов

**Задача:** Получить список всех успешных подключений за период.

```bash
# Успешные входы (auth.log)
grep "Accepted" /var/log/auth.log | awk '{print $1, $2, $3, $9, $11}'

# История входов (wtmp)
last | grep -E "pts|tty" | head -30

# Последний вход каждого пользователя
lastlog

# Конкретный пользователь
last username
lastb username
```

### Сценарий 3: Расширенное логирование SFTP

**Задача:** Логировать файловые операции через SFTP.

```bash
# 1. Изменить Subsystem в /etc/ssh/sshd_config
sudo sed -i 's|^Subsystem sftp.*|Subsystem sftp /usr/lib/openssh/sftp-server -f AUTHPRIV -l INFO|' /etc/ssh/sshd_config

# 2. Перезапустить SSH
sudo systemctl restart sshd

# 3. Просмотр логов SFTP
grep sftp /var/log/auth.log
```

### Сценарий 4: Мониторинг активных SSH-сессий

**Задача:** Получить список текущих подключений.

```bash
# Активные сессии (who)
who

# Детальная информация (w)
w

# Сетевые подключения SSH
ss -tnp | grep :22

# Процессы sshd
ps aux | grep sshd | grep -v grep
```

### Сценарий 5: Проверка конфигурации sshd

**Задача:** Убедиться в корректности конфигурации до перезапуска.

```bash
# Проверка синтаксиса
sudo sshd -t

# Показать эффективную конфигурацию
sudo sshd -T

# Проверить конкретную директиву
sudo sshd -T | grep -i loglevel
sudo sshd -T | grep -i auth
```

### Сценарий 6: Отладка sshd в реальном времени

**Задача:** Запустить sshd в режиме отладки для диагностики.

```bash
# Остановить sshd
sudo systemctl stop sshd

# Запустить в debug-режиме (foreground)
sudo /usr/sbin/sshd -d -p 2222

# Клиент подключается к порту 2222
ssh -vvv -p 2222 user@host

# После диагностики перезапустить штатно
sudo systemctl start sshd
```

## Additional Information

### Инструменты аудита

**ssh-audit** — анализ алгоритмов, шифров и уязвимостей SSH-сервера.

```bash
# Установка
pip install ssh-audit

# Аудит
ssh-audit <hostname>
ssh-audit -p 2239 <hostname>  # Нестандартный порт
```

**fail2ban** — автоматическая блокировка brute-force. См. [fail2ban: настройка и использование](../../Tools/fail2ban.md).

### Автоматизация мониторинга

```bash
# Скрипт: топ-10 IP с неудачными входами за 24 часа
journalctl -u sshd --since "24 hours ago" \
  | grep "Failed" \
  | awk '{print $(NF-3)}' \
  | sort | uniq -c | sort -rn | head -10

# Скрипт: количество неудачных входов за последний час
journalctl -u sshd --since "1 hour ago" | grep -c "Failed"
```

### Связанные темы

- [SSH Troubleshooting](../ssh_troubleshooting.md) — диагностика проблем подключения
- [SSH Hardening Best Practices](./ssh_hardening_best_practices.md) — укрепление безопасности
- [SSH Authentication](./ssh_authentication.md) — методы аутентификации
- [Logging Overview](../../../SystemAdministration/Logging/logging_overview.md) — общая система логов
- [fail2ban](../../Tools/fail2ban.md) — защита от brute-force
