# Samba: Устранение неполадок

## Проверка конфигурации

```bash
# Синтаксическая проверка
testparm

# Проверка с подробным выводом
testparm -v

# Проверка доступных шар
testparm -s
```

## Диагностика подключений

```bash
# Проверка служб
systemctl status smb nmb winbind

# Просмотр активных сессий
smbstatus

# Проверка пользователей
pdbedit -L

# Тест подключения
smbclient -L //localhost -U%
```

## Распространённые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` | Неправильные UNIX-права | `chown`, `chmod`, проверка `valid users` |
| `NT_STATUS_ACCESS_DENIED` | Ошибка аутентификации | Проверка `smbpasswd`, `ntlm auth` |
| `NT_STATUS_BAD_NETWORK_NAME` | Шара не существует | Проверка имени шары в `smb.conf` |
| `NT_STATUS_LOGON_FAILURE` | Неверный пароль | `smbpasswd -a <user>`, проверка PAM |
| Медленная работа | MTU/сетевые настройки | `socket options`, `read raw` |
| Проблемы с доменом | Рассинхронизация времени | Настройка NTP, проверка Kerberos |
| `winbind: can't fetch domain info` | Нет связи с DC | Проверка сети, DNS, `net ads testjoin` |

## Пользователи Samba

Samba использует собственную базу паролей (`/var/lib/samba/private/smbpasswd`).

**Управление через `smbpasswd`:**
```bash
smbpasswd -a [user]  # Добавление пользователя
smbpasswd -x [user]  # Удаление
smbpasswd -e [user]  # Активация
smbpasswd -d [user]  # Деактивация
```

**Управление через `pdbedit`:**
```bash
pdbedit -a -u smbuser  # Добавление
pdbedit -L             # Список пользователей
pdbedit -v smbuser     # Подробная информация
pdbedit -x smbuser     # Удаление
```

## Логи

```bash
# Журналы Samba (Debian/Ubuntu)
journalctl -u smb -f
journalctl -u nmb -f
journalctl -u winbind -f

# Логи в файлах
/var/log/samba/log.smbd
/var/log/samba/log.nmbd
/var/log/samba/log.winbindd

# Увеличение уровня логирования (в smb.conf)
[global]
   log level = 3
```

## Kerberos-проблемы

```bash
# Проверка билета
klist

# Получение нового билета
kinit administrator@EXAMPLE.COM

# Проверка ключей
klist -ke

# Синхронизация времени
timedatectl status
sudo systemctl restart systemd-timesyncd
```

## Связанные документы

- [Базовые концепции](./samba_basics.md)
- [Настройка Samba](./samba_setup.md)
- [AD-интеграция](./samba_ad.md) — домен, winbind, idmap
- [Kerberos](../../../Security/Concepts/kerberos.md)
