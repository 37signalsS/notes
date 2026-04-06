# Samba: Troubleshooting

## Definitions

**testparm** — утилита проверки синтаксиса `smb.conf`. Показывает ошибки конфигурации и итоговые параметры после обработки всех директив.

**smbstatus** — утилита просмотра активных сессий, подключённых пользователей, открытых файлов и блокировок.

## Basic Concepts

### Диагностические утилиты

| Утилита | Назначение |
| :--- | :--- |
| `testparm [-v] [-s]` | Проверка конфигурации; `-v` — все параметры, `-s` — без пауз |
| `smbstatus [-S] [-v]` | Активные сессии; `-S` — статистика по шарам, `-v` — с блокировками |
| `pdbedit -L [-v] [-u user]` | Управление базой пользователей Samba |
| `smbclient -L //server [-U%]` | Тест видимости шар с сервера/клиента |
| `net ads testjoin` | Проверка членства в домене AD |
| `klist` | Просмотр Kerberos-билетов |

> **Важно:** Параметры `read raw`, `write raw`, `socket options` не влияют на производительность SMB2/SMB3 — см. [безопасность и VFS](./samba_security.md).

### Файлы логов

| Путь | Описание |
| :--- | :--- |
| `journalctl -u smb -f` | Журнал smbd (systemd) |
| `journalctl -u nmb -f` | Журнал nmbd (systemd) |
| `journalctl -u winbind -f` | Журнал winbind (systemd) |
| `/var/log/samba/log.%m` | Лог по клиенту (%m = NetBIOS-имя) |
| `/var/log/samba/log.smbd` | Общий лог smbd |

## Practical Scenarios

### Быстрая диагностика

```bash
# 1. Проверка конфигурации
testparm -s

# 2. Статус служб
systemctl status smb nmb winbind

# 3. Активные сессии
smbstatus

# 4. Список пользователей
pdbedit -L

# 5. Тест видимости шар
smbclient -L //localhost -U%
```

### Таблица распространённых ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` | UNIX-права на директорию | Проверить `chown`/`chmod`, `valid users` |
| `NT_STATUS_ACCESS_DENIED` | Аутентификация | `smbpasswd -a <user>`, проверить `ntlm auth` |
| `NT_STATUS_BAD_NETWORK_NAME` | Шара не найдена | Проверить имя шары в `smb.conf`, `testparm` |
| `NT_STATUS_LOGON_FAILURE` | Неверный пароль | Перезадать пароль через `smbpasswd` |
| Медленная работа | Сеть/MTU, DNS | Проверить задержки, отключить DNS-lookup в `[global]` |
| Проблемы с доменом | Рассинхронизация времени | Настроить NTP, проверить Kerberos (`klist`) |
| `winbind: can't fetch domain info` | Нет связи с DC | Проверить сеть, DNS, `net ads testjoin` |

### Управление пользователями

```bash
# Добавление
smbpasswd -a username
# или
pdbedit -a -u username

# Список
pdbedit -L

# Подробная информация
pdbedit -v username

# Деактивация / активация
smbpasswd -d username  # отключить
smbpasswd -e username  # включить

# Удаление
smbpasswd -x username
# или
pdbedit -x username
```

### Уровни логирования

```ini
[global]
   log level = 3
   log file = /var/log/samba/log.%m
   max log size = 10000
```

Уровни: `0` — только критические, `1` — стандартный, `2` — подробности, `3+` — отладка. Для продакшена не выше `2`.

### Kerberos-диагностика (AD-членство)

```bash
# Проверка билета
klist

# Получение билета
kinit administrator@EXAMPLE.COM

# Проверка keytab
klist -ke

# Синхронизация времени (NTP критичен для Kerberos)
timedatectl status
```

> Рассинхронизация >5 минут делает Kerberos-билеты невалидными.

## Additional Information

Связанные документы: [обзор Samba](./index.md), [настройка сервера](./samba_setup.md), [безопасность и VFS](./samba_security.md), [AD-интеграция](./samba_ad.md). Kerberos: [протокол Kerberos](../../../../Security/Concepts/kerberos.md).
