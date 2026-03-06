# Samba: Интеграция с Active Directory

## Требования

- Настроенный домен Active Directory
- Синхронизация времени (Kerberos требует точного времени)
- Пакет `winbind`

## Настройка членства в домене

### Шаг 1: Установка пакетов

```bash
# Debian/Ubuntu
sudo apt-get install -y samba winbind libnss-winbind libpam-winbind

# RHEL/CentOS
sudo yum install -y samba-winbind samba-winbind-clients
```

### Шаг 2: Конфигурация (`/etc/samba/smb.conf`)

```ini
[global]
   workgroup = EXAMPLE
   realm = EXAMPLE.COM
   security = ADS
   encrypt passwords = yes
   kerberos method = secrets and keytab
   
   # ID mapping (важно для корректного маппинга UID/GID)
   idmap config * : backend = tdb
   idmap config * : range = 3000-7999
   idmap config EXAMPLE : backend = rid
   idmap config EXAMPLE : range = 10000-999999
   
   winbind use default domain = yes
   winbind offline logon = yes
```

### Шаг 3: Присоединение к домену

```bash
# Присоединение к домену
sudo net ads join -U Administrator

# Проверка подключения
net ads testjoin

# Запуск служб
sudo systemctl enable --now smb nmb winbind
```

### Шаг 4: Настройка NSS и PAM

**`/etc/nsswitch.conf`:**

```yaml
passwd:         compat winbind
group:          compat winbind
shadow:         compat
```

**PAM (автоматическое создание домашних директорий):**

```bash
sudo pam-auth-update
```

## Проверка и диагностика

```bash
# Информация о домене
net ads info

# Список пользователей домена
wbinfo -u
getent passwd

# Список групп домена
wbinfo -g
getent group

# Проверка маппинга UID/GID
wbinfo --uid-to-sid 10000
wbinfo --sid-to-uid S-1-5-21-...

# Проверка билета Kerberos
klist
```

## idmap: маппинг UID/GID

**Важно:** Для корректной работы в домене требуется централизованное управление UID/GID через `idmap`. Без этого возможны конфликты прав доступа.

### Бэкенды idmap

| Бэкенд | Описание | Использование |
| :--- | :--- | :--- |
| `tdb` | Локальная база (тривиальный) | Для локальных пользователей (`*`) |
| `rid` | Маппинг на основе RID домена | Для доменных пользователей |
| `ad` | Маппинг из атрибутов AD | Для сложных схем |
| `autorid` | Автоматическое выделение диапазонов | Для нескольких доменов |

### Пример конфигурации idmap

```ini
[global]
   # Локальные пользователи (3000-7999)
   idmap config * : backend = tdb
   idmap config * : range = 3000-7999
   
   # Домен EXAMPLE (10000-999999)
   idmap config EXAMPLE : backend = rid
   idmap config EXAMPLE : range = 10000-999999
   
   # Домен TRUSTED (2000000-2999999)
   idmap config TRUSTED : backend = rid
   idmap config TRUSTED : range = 2000000-2999999
```

## Уровни безопасности (`security`)

| Режим | Описание |
| :--- | :--- |
| `security = user` | Стандартный режим, локальная аутентификация |
| `security = ads` | Член домена Active Directory, Kerberos |
| `security = domain` | Устаревший режим для NT4-доменов |

## Связанные документы

- [Базовые концепции](./samba_basics.md)
- [Настройка Samba](./samba_setup.md)
- [Kerberos: централизованная аутентификация](../../../../Security/Concepts/kerberos.md)
- [Управление пользователями](../../../SystemAdministration/users_management.md)
