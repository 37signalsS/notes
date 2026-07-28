# Интеграция SSSD с Active Directory

Интеграция Linux-серверов и рабочих станций в Active Directory (AD) — стандартная задача в смешанных инфраструктурах. **SSSD (System Security Services Daemon)** является современным и рекомендуемым способом обеспечения аутентификации и получения информации из AD без необходимости установки тяжеловесных клиентов (например, Winbind).

---

## Подключение к домену

Наиболее простым и автоматизированным способом подключения является использование утилиты **realmd**. Она автоматически обнаруживает параметры домена, устанавливает необходимые пакеты и настраивает SSSD и Kerberos.

### Использование realmd

```bash
# Подключение к домену
realm join example.com -U Administrator
```

Команда выполнит:
1. Настройку `/etc/krb5.conf`.
2. Создание учетной записи компьютера в AD.
3. Генерацию `/etc/sssd/sssd.conf`.
4. Настройку NSS и PAM.

---

## Ручная настройка sssd.conf

Если автоматическая настройка через `realmd` не используется или требует корректировки, файл `/etc/sssd/sssd.conf` должен содержать следующие ключевые параметры.

### Пример конфигурации

```ini
[sssd]
domains = example.com
config_file_version = 2
services = nss, pam

[domain/example.com]
# Провайдер ad оптимизирован для работы с Active Directory
id_provider = ad
auth_provider = ad
chpass_provider = ad
access_provider = ad

ad_domain = example.com
krb5_realm = EXAMPLE.COM

# Параметры, добавляемые realmd
realmd_tags = manages-system joined-with-adcli

# Кэширование для офлайн-входа
cache_credentials = True

# Автоматическое определение домашней директории и оболочки
fallback_homedir = /home/%u@%d
default_shell = /bin/bash

# Маппинг идентификаторов (SID в UID/GID)
# True — автоматическая генерация ID на основе SID (не требует POSIX-атрибутов в AD)
ldap_id_mapping = True

# Использовать полные имена (user@domain.com)
use_fully_qualified_names = False
```

---

## Безопасность и права доступа

Файл конфигурации SSSD содержит чувствительные данные (например, параметры привязки к домену) и **должен** иметь строго ограниченные права доступа.

```bash
# Установка владельца и прав доступа
chown root:root /etc/sssd/sssd.conf
chmod 600 /etc/sssd/sssd.conf
```

---

## Активация и запуск

После внесения изменений в конфигурацию необходимо перезапустить службу и добавить её в автозагрузку.

```bash
# Перезапуск и активация
systemctl enable --now sssd
```

---

## Настройка PAM и домашних директорий

Для корректной работы аутентификации и автоматического создания домашних каталогов при первом входе необходимо настроить модули PAM.

### Автоматическое создание директорий

В современных дистрибутивах (Debian/Ubuntu) настройка выполняется в `/etc/pam.d/common-session`.

```text
# Добавить в конец файла common-session
session required pam_mkhomedir.so skel=/etc/skel/ umask=0077
```

*Примечание: В системах RHEL/Fedora рекомендуется использовать `authselect` для управления профилями PAM.*

---

## Верификация

Проверка корректности интеграции выполняется с помощью стандартных системных команд.

```bash
# Проверка получения информации о доменном пользователе
id username

# Проверка через getent
getent passwd username
```

---

## Дополнительная информация

**Связанные темы:**

- [Конфигурация LDAP и SSSD](./configuration.md) — общие принципы настройки.
- [Эксплуатация и отладка](./operations.md) — поиск и устранение неисправностей.
- [Samba: Интеграция с Active Directory](../../../Networking/Services/samba/samba_ad.md) — совместная работа Samba и SSSD.
