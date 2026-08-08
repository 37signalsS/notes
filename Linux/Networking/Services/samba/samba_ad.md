# Samba: Интеграция с Active Directory

## Определения

**Samba AD Member** — роль сервера Samba, при которой он является полноправным членом домена Active Directory (AD). В этом режиме Samba делегирует аутентификацию контроллерам домена (DC) через протокол Kerberos, а для управления идентификаторами (UID/GID) использует подсистему `idmap`.

**winbindd** — специализированный демон Samba, выступающий мостом между NT-идентификаторами (SID) и Unix-идентификаторами. Обеспечивает прозрачный маппинг пользователей и групп домена в операционную систему Linux.

**Kerberos Keytab** — файл (обычно `/etc/krb5.keytab`), содержащий секретные ключи учетной записи компьютера. Позволяет Samba выполнять аутентификацию на DC без интерактивного ввода пароля.

**idmap (ID Mapping)** — критически важная подсистема, определяющая логику преобразования SID (Windows) в UID/GID (Linux). Ошибки в настройке `idmap` приводят к потере доступа к файлам или дублированию идентификаторов.

**PAC (Privilege Attribute Certificate)** — часть билета Kerberos, содержащая информацию о членстве пользователя в группах. Samba анализирует PAC для принятия решений о доступе.

## Базовые концепции

### Выбор метода интеграции: Winbind vs SSSD

| Характеристика | Winbind (Native) | SSSD (System Service) |
| :--- | :--- | :--- |
| **Поддержка ACL** | Полная (рекомендуется для Samba) | Ограниченная |
| **Производительность** | Оптимизировано для SMB-трафика | Оптимизировано для системного входа (SSH) |
| **Сложные леса AD** | Отличная поддержка Trust отношений | Зависит от версии и настройки |
| **Вердикт** | **Обязателен** для высоконагруженных файловых серверов. | Подходит для простых шар на обычных серверах. |

> Для полноценной работы файлового сервера Samba с поддержкой расширенных прав доступа Windows (NTFS ACL) связка **Samba + Winbind** является «золотым стандартом».

### Архитектура подсистемы idmap

Настройка `idmap` всегда состоит из двух частей:
1.  **Default (`*`)**: для локальных пользователей и доменов, не описанных явно. Должен использовать бэкенд `tdb`.
2.  **Domain Specific**: для каждого домена AD, с которым работает сервер.

**Рекомендуемые бэкенды 2026:**
- **`rid`**: (Алгоритмический) UID вычисляется на основе RID пользователя. Не требует записи данных в AD. Идеально для одного домена.
- **`ad`**: (RFC2307) Считывает `uidNumber` и `gidNumber` напрямую из атрибутов объекта в AD. Требует ручного управления ID в Windows.
- **`autorid`**: Автоматически выделяет диапазоны для каждого домена в лесу. Удобно для крупных структур.

### Требования к инфраструктуре

- **DNS**: Сервер Linux должен использовать DNS-серверы контроллера домена.
- **Время**: Синхронизация через [Chrony](../chrony_ntp.md) обязательна. Расхождение > 300с ломает Kerberos.
- **Порты**: Открытый доступ к DC по портам 88 (Kerberos), 389 (LDAP), 445 (SMB), 135/49152+ (RPC).

## Практические сценарии

### 1. Подготовка системы и установка

```bash
# Установка необходимых компонентов
sudo apt-get install -y samba winbind libnss-winbind libpam-winbind krb5-user
```

**Конфигурация `/etc/krb5.conf`:**
```ini
[libdefaults]
    default_realm = EXAMPLE.COM
    dns_lookup_realm = false
    dns_lookup_kdc = true
```

### 2. Эталонная конфигурация `smb.conf` (Hardened 2026)

```ini
[global]
   workgroup = EXAMPLE
   realm = EXAMPLE.COM
   security = ADS
   
   # Безопасность и аутентификация
   kerberos method = secrets and keytab
   dedicated keytab file = /etc/krb5.keytab
   winbind sealed pipes = yes
   require strong auth = yes
   
   # Запрет небезопасных протоколов
   client min protocol = SMB3_11
   server min protocol = SMB3_11
   client signing = required
   server signing = required

   # Настройка ID Mapping (Backend: RID)
   idmap config * : backend = tdb
   idmap config * : range = 3000-7999
   
   idmap config EXAMPLE : backend = rid
   idmap config EXAMPLE : range = 10000-999999
   
   # Оптимизация Winbind
   winbind enum users = no
   winbind enum groups = no
   winbind use default domain = yes
   winbind refresh tickets = yes
   winbind multi-domain names = no
```

### 3. Присоединение к домену и управление Keytab

```bash
# 1. Получение билета администратора
kinit Administrator@EXAMPLE.COM

# 2. Ввод в домен с созданием записи в keytab
sudo net ads join -U Administrator

# 3. Обновление и проверка keytab (важно для автоматического обновления пароля компьютера)
sudo net ads keytab create -U Administrator
sudo klist -k /etc/krb5.keytab
```

### 4. Настройка системного окружения (NSS/PAM)

**`/etc/nsswitch.conf`**:
Обеспечивает видимость доменных пользователей командами `id`, `ls`, `getent`.
```text
passwd:         files winbind
group:          files winbind
```

**PAM (Автоматическое создание Home-директорий)**:
Добавьте в `/etc/pam.d/common-session`:
```text
session required    pam_mkhomedir.so skel=/etc/skel/ umask=0022
```

## Мониторинг и диагностика

### Проверка статуса интеграции

```bash
# Тест доверительных отношений
net ads testjoin # → Join is OK

# Проверка связи winbind с DC
wbinfo -t # → checking the trust secret via RPC calls succeeded

# Просмотр информации о домене
net ads info
```

### Отладка маппинга и разрешений

```bash
# Проверка преобразования SID -> UID
wbinfo -n "Domain Users" # Получить SID
wbinfo -S <SID>          # Получить GID

# Проверка видимости через ОС
getent passwd "username"

# Сброс кеша winbind (при проблемах с маппингом)
sudo systemctl stop winbind
sudo rm -f /var/lib/samba/*.tdb
sudo systemctl start winbind
```

### Управление логами в реальном времени

```bash
# Увеличение уровня логирования без перезагрузки
sudo smbcontrol winbindd debug 10
# (Просмотр лога в /var/log/samba/log.winbindd)
# Сброс уровня обратно
sudo smbcontrol winbindd debug 1
```

## Дополнительная информация

- [Samba: Обзор](./index.md) — архитектура, демоны и порты.
- [Samba: Настройка сервера](./samba_setup.md) — создание файловых ресурсов.
- [Samba: Безопасность и VFS](./samba_security.md) — настройка ACL и аудит.
- [Синхронизация времени (Chrony)](../chrony_ntp.md) — критическое условие работы AD.
- [Протокол Kerberos](../../../../Security/Concepts/kerberos.md) — глубокое погружение в принципы работы.
- [Управление пользователями в Linux](../../../SystemAdministration/users_management.md) — базовые концепции NSS/PAM.
