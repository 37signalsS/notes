# Samba: Безопасность и производительность

## Конфигурация безопасности

**Минимальные безопасные настройки для `/etc/samba/smb.conf`:**

```ini
[global]
   # Версии протокола
   server min protocol = SMB3
   server max protocol = SMB3_11
   
   # Аутентификация
   ntlm auth = only-ntlmv2-permit
   reject md5 passwords = yes
   
   # Шифрование
   smb encrypt = auto  # или 'required' для обязательного шифрования
   
   # Защита
   map to guest = Never  # отключить гостевой доступ по умолчанию
   restrict anonymous = 2  # запретить анонимные запросы
```

## VFS (Virtual File System) модули

Samba поддерживает модули VFS для расширения функциональности:

| Модуль | Описание |
| :--- | :--- |
| `vfs_objects` | Рекурсивное удаление объектов |
| `vfs_audit` | Аудит операций с файлами |
| `vfs_full_audit` | Расширенное логирование |
| `vfs_recycle` | Корзина для удалённых файлов |
| `vfs_shadow_copy` | Снимки (snapshots) для Volume Shadow Copy |
| `vfs_virusfilter` | Проверка файлов на вирусы |

**Пример использования:**

```ini
[secure_share]
   path = /srv/samba/secure
   vfs objects = full_audit recycle
   full_audit:success = open mkdir rename unlink
   full_audit:failure = open mkdir
   recycle:repository = /srv/samba/.recycle/%U
```

## Производительность и оптимизация

**Настройки для улучшения производительности:**

```ini
[global]
   # Размер блоков
   socket options = TCP_NODELAY IPTOS_LOWDELAY
   read raw = yes
   write raw = yes
   
   # Кэширование
   max xmit = 65535
   getwd cache = yes
   
   # Для больших файлов
   strict allocate = no
   strict sync = no
   sync always = no
```

**Диагностика производительности:**

```bash
# Мониторинг подключений
smbstatus

# Статистика по шарам
smbstatus -S

# Тестирование скорости
smbclient //server/share -U user -c 'prompt; mget *'
```

## Аудит и логирование

**Включение расширенного логирования:**

```ini
[global]
   log level = 2
   log file = /var/log/samba/%m.log
   max log size = 10000
   log rotation = daily
```

**Аудит операций с файлами:**

```ini
[global]
   vfs objects = full_audit
   
[audited_share]
   path = /srv/samba/audited
   vfs objects = full_audit
   full_audit:success = open mkdir rename unlink chmod chown
   full_audit:failure = open mkdir
   full_audit:prefix = %u|%I|%m|%S
```

## SELinux

**Настройка контекстов для CentOS/RHEL:**

```bash
# Установка правильного контекста
sudo chcon -t samba_share_t /srv/samba/public/

# Постоянное решение
sudo semanage fcontext -a -t samba_share_t '/srv/samba/public(/.*)?'
sudo restorecon -Rv /srv/samba/public/

# Разрешение доступа к домашним директориям
sudo setsebool -P samba_enable_home_dirs on
```

Подробнее см. [SELinux](../../../Security/Mechanisms/SELinux.md).

## Связанные документы

- [Базовые концепции](./samba_basics.md)
- [Настройка Samba](./samba_setup.md)
- [AD-интеграция](./samba_ad.md) — домен, winbind
- [Настройка файрвола](../../../Development/build_tools.md)
