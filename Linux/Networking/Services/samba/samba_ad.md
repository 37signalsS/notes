# Samba: Интеграция с Active Directory

## Определения

**Samba AD Member** — роль сервера Samba, при которой он является полноправным членом домена Active Directory (AD). В этом режиме Samba делегирует аутентификацию контроллерам домена (DC) через протокол Kerberos, а для управления идентификаторами (UID/GID) использует подсистему `idmap`.

**Samba AD DC** — режим работы Samba как контроллера домена Active Directory. Samba самостоятельно управляет базой данных каталога, реплицирует изменения между узлами и обрабатывает запросы LDAP/Kerberos. Используется в средах, где отсутствуют Windows-контроллеры.

**winbindd** — специализированный демон Samba, выступающий мостом между NT-идентификаторами (SID) и Unix-идентификаторами. Обеспечивает прозрачный маппинг пользователей и групп домена в операционную систему Linux.

**Kerberos Keytab** — файл (обычно `/etc/krb5.keytab`), содержащий секретные ключи учетной записи компьютера. Позволяет Samba выполнять аутентификацию на DC без интерактивного ввода пароля.

**idmap (ID Mapping)** — критически важная подсистема, определяющая логику преобразования SID (Windows) в UID/GID (Linux). Ошибки в настройке `idmap` приводят к потере доступа к файлам или дублированию идентификаторов.

**PAC (Privilege Attribute Certificate)** — часть билета Kerberos, содержащая информацию о членстве пользователя в группах. Samba анализирует PAC для принятия решений о доступе. PAC включает SID групп, флаги привилегий и ограничения (constraints).

**SID (Security Identifier)** — уникальный идентификатор безопасности Windows, присваиваемый каждому объекту домена (пользователь, группа, компьютер). Имеет форму `S-1-5-21-<domain>-<rid>`. В Samba SID преобразуется в числовой UID/GID через idmap.

**Trust Relationship (Доверительное отношение)** — связь между доменами AD, позволяющая пользователям одного домена получать доступ к ресурсам другого. Samba AD Member поддерживает входящие доверительные отношения с Windows DC.

**SID History** — атрибут учетной записи AD, содержащий предыдущие SID пользователя. Позволяет сохранить доступ к файлам при миграции между доменами. Samba передает SID History в PAC и корректно преобразует их в UID/GID.

**CSE (Client Side Extension)** — клиентские расширения Group Policy Objects (GPO). Samba AD Member не выполняет полную обработку GPO; политики применяются на стороне клиентов Windows/macOS, а Samba обеспечивает только файловый доступ.

## Базовые концепции

### Выбор метода интеграции: Winbind vs SSSD

| Характеристика | Winbind (Native) | SSSD (System Service) |
| :--- | :--- | :--- |
| **Поддержка ACL** | Полная (рекомендуется для Samba) | Ограниченная |
| **Производительность** | Оптимизировано для SMB-трафика | Оптимизировано для системного входа (SSH) |
| **Сложные леса AD** | Отличная поддержка Trust отношений | Зависит от версии и настройки |
| **Kerberos** | Встроенный, используется напрямую | Через krb5.conf |
| **Вердикт** | **Обязателен** для высоконагруженных файловых серверов. | Подходит для простых шар на обычных серверах. |

> Для полноценной работы файлового сервера Samba с поддержкой расширенных прав доступа Windows (NTFS ACL) связка **Samba + Winbind** является «золотым стандартом».
>
> SSSD может использоваться для системного входа и NSS/PAM, но для Samba-шар с NTFS ACL предпочтителен Winbind из-за более точного маппинга SID и поддержки `winbind sealed pipes`.

### Архитектура подсистемы idmap

Настройка `idmap` всегда состоит из двух частей:
1.  **Default (`*`)**: для локальных пользователей и доменов, не описанных явно. Должен использовать бэкенд `tdb`.
2.  **Domain Specific**: для каждого домена AD, с которым работает сервер.

**Рекомендуемые бэкенды 2026:**
- **`rid`**: (Алгоритмический) UID вычисляется на основе RID пользователя. Не требует записи данных в AD. Идеально для одного домена.
- **`ad`**: (RFC2307) Считывает `uidNumber` и `gidNumber` напрямую из атрибутов объекта в AD. Требует ручного управления ID в Windows.
- **`autorid`**: Автоматически выделяет диапазоны для каждого домена в лесу. Удобно для крупных структур.

**Проектирование диапазонов (Range Design):**
Каждый домен должен иметь непересекающийся диапазон UID/GID. При интеграции с существующими Linux-серверами используйте бэкенд `ad` с явным указанием `uidNumber`/`gidNumber`, чтобы избежать конфликтов с локальными пользователями.

**Пример диапазонов:**
- `*` (default): 3000–7999 (локальные пользователи)
- `EXAMPLE.COM`: 10000–999999 (доменные пользователи)
- `TRUSTED.COM`: 1000000–1999999 (доверенный домен)

### Архитектура кеша Winbind

Winbind кэширует данные о пользователях, группах и SID для снижения задержек при обращении к DC. Кеш хранится в базах данных TDB (`/var/lib/samba/*.tdb`).

- **Время жизни кеша:** по умолчанию данные о пользователях кэшируются на 15 минут. Для динамических сред можно снизить до 5 минут.
- **Сброс кеша:** требуется после изменения `idmap` или проблем с маппингом. Полный сброс — удаление файлов `*.tdb` и перезапуск `winbindd`.
- **Влияние на производительность:** отключение `winbind enum users/groups = no` предотвращает полное перечисление каталога при запуске и критически важно для доменов с >10 000 пользователей.

### Trust Relationship и Cross-Forest

При интеграции в сложную среду AD с несколькими доменами или лесами:

- **External Trust:** связь между двумя доменами в разных лесах. Требует явного указания `winbind trusted domains = yes`.
- **Forest Trust:** автоматическое доверие между всеми доменами в лесу. Поддерживается нативно через глобальный каталог.
- **SID Filtering:** Samba уважает SID фильтрацию Windows. Дополнительные SID из доверенного домена игнорируются для предотвраждения escalation.

### SSSD для Samba (Альтернативный подход)

Хотя Winbind является предпочтительным для Samba, SSSD может использоваться для:
- Системного входа пользователей (SSH, sudo)
- Кэширования учетных данных для офлайн-работы
- Централизованного управления доступом через HBAC

**Важно:** При использовании SSSD для системного входа и Winbind для Samba убедитесь, что UID/GID идентичны в обеих системах, иначе права на файлы будут некорректными.

### Требования к инфраструктуре

- **DNS**: Сервер Linux должен использовать DNS-серверы контроллера домена. Обязательна обратная DNS-зона (PTR) для сервера.
- **Время**: Синхронизация через [Chrony](../chrony_ntp.md) обязательна. Расхождение > 300с ломает Kerberos. Рекомендуется `makestep 1 3` для быстрого перехода.
- **Порты**: Открытый доступ к DC по портам 88 (Kerberos), 389 (LDAP), 445 (SMB), 135/49152+ (RPC), 636 (LDAPS).
- **NTP Source**: На стороне DC должен быть настроен источник времени; Linux-сервер должен синхронизироваться только с DC, а не с внешними источниками.

## Практические сценарии

### 1. Предварительные проверки перед присоединением к домену

Перед выполнением `net ads join` выполните проверки:

```bash
# 1. Проверка разрешения имени домена
host -t SRV _ldap._tcp.example.com
# → _ldap._tcp.example.com has SRV record ...

# 2. Проверка обратного DNS
host $(hostname -I | awk '{print $1}')
# → samba-srv.example.com has address ...

# 3. Проверка синхронизации времени
chronyc tracking | grep "System time"
# → System time     : 0.000000003 seconds slow of NTP time

# 4. Проверка доступности портов DC
nc -zv dc01.example.com 88 && nc -zv dc01.example.com 389 && nc -zv dc01.example.com 445
# → Connection succeeded
```

### 2. Установка компонентов

```bash
# Debian / Ubuntu / Mint
sudo apt update && sudo apt install -y samba winbind libnss-winbind libpam-winbind krb5-user

# RHEL / Rocky / AlmaLinux / Fedora
sudo dnf install -y samba-winbind samba-winbind-clients krb5-workstation
```

### 3. Эталонная конфигурация `smb.conf` (Hardened 2026)

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
   client ipc signing = auto
   
   # Запрет небезопасных протоколов
   client min protocol = SMB3_11
   server min protocol = SMB3_11
   client signing = required
   server signing = required
   ntlm auth = ntlmv2-only
   lanman auth = no

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
   winbind normalize names = yes
   winbind offline logon = true
   
   # Логирование
   log level = 3
   max log size = 10000
```

### 4. Присоединение к домену и управление Keytab

```bash
# 1. Получение билета администратора
kinit Administrator@EXAMPLE.COM

# 2. Ввод в домен с созданием записи в keytab
sudo net ads join -U Administrator

# 3. Обновление и проверка keytab (важно для автоматического обновления пароля компьютера)
sudo net ads keytab create -U Administrator
sudo klist -k /etc/krb5.keytab

# 4. Проверка присоединения
net ads testjoin
# → Join is OK
```

### 5. Типичные ошибки присоединения к домену

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `kinit: Cannot find KDC for realm` | DNS не настроен или realm не указан | Проверьте `/etc/resolv.conf` и `/etc/krb5.conf` (DNS lookup). |
| `NT_STATUS_ACCESS_DENIED` при join | Учетная запись Administrator не имеет прав на добавление компьютеров | Добавьте права на OU или используйте учетную запись с делегированием. |
| `NT_STATUS_INVALID_PARAMETER` | Несоответствие SMBv3.1.1 | Проверьте `server min protocol = SMB3_11` в `smb.conf`. |
| `clock skew too great` | Расхождение времени > 5 мин | Настройте Chrony на синхронизацию с DC. |
| `The specified domain either does not exist or could not be contacted` | Проблемы с DNS suffix или DNS-сервером | Добавьте домен в `/etc/resolv.conf` (search/reverse zone). |

### 6. Настройка системного окружения (NSS/PAM)

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

**Проверка видимости:**
```bash
getent passwd "EXAMPLE\username"
# → EXAMPLE\username:x:10000:10000:User:/home/username:/bin/bash
```

### 7. Управление кешем Winbind

```bash
# Просмотр текущих записей в кеше
wbinfo -c
# → EXAMPLE\username

# Очистка всего кеша (при смене idmap или проблемах с маппингом)
sudo systemctl stop winbind
sudo rm -f /var/lib/samba/*.tdb /var/cache/samba/*.tdb
sudo systemctl start winbind

# Проверка преобразования SID -> UID
wbinfo -n "EXAMPLE\username"
# → S-1-5-21-...-500 SID_USER (1)
wbinfo -S "S-1-5-21-...-500"
# → 10000
```

### 8. Ротация Keytab и мониторинг срока действия

Keytab содержит ключи для аутентификации на DC. Пароль компьютера в AD автоматически обновляется каждые 30 дней, но keytab должен обновляться синхронно.

```bash
# Проверка срока действия ключей
sudo klist -k /etc/krb5.keytab

# Принудительное обновление keytab
sudo net ads keytab create -U Administrator

# Автоматизация через cron (если AD не реплицирует ключи автоматически)
# Добавьте в crontab:
0 0 * * 0 /usr/bin/net ads keytab create -U Administrator >/dev/null 2>&1
```

### 9. Конфигурация SSSD для Samba (Альтернатива)

Для сред, где SSSD уже используется для системного входа:

```ini
# /etc/sssd/sssd.conf
[sssd]
domains = example.com
config_file_version = 2
services = nss, pam

[domain/example.com]
id_provider = ad
auth_provider = ad
access_provider = ad
ad_site = Default-First-Site-Name
ldap_id_mapping = True
use_fully_qualified_names = False
fallback_homedir = /home/%u@%d
ad_gpo_access_control = enforcing
cache_credentials = True
krb5_store_password_if_offline = True
```

После настройки SSSD убедитесь, что UID/GID пользователей совпадают с теми, что ожидает Samba (через winbind).

### 10. Отказоустойчивый вход в домен (Multi-DC)

При наличии нескольких контроллеров домена настройте `smb.conf` для использования нескольких KDC:

```ini
[global]
   kerberos server = dc01.example.com dc02.example.com dc03.example.com
   winbind refresh tickets = yes
```

### 11. Миграция с NT4-домена на AD

При переходе с NT4-style security domains (`security = user` + локальные пользователи) на AD:

1. Сохраните текущие UID/GID всех локальных пользователей.
2. Настройте `idmap config * : backend = tdb` с сохранением старых диапазонов.
3. Настройте `idmap config NT4DOMAIN : backend = rid` для нового домена.
4. Постепенно перемещайте пользователей в AD, сохраняя UID через `uidNumber`.

## Мониторинг и диагностика

### Проверка статуса интеграции

```bash
# Тест доверительных отношений
net ads testjoin # → Join is OK

# Проверка связи winbind с DC
wbinfo -t # → checking the trust secret via RPC calls succeeded

# Просмотр информации о домене
net ads info
# → LDAP server: dc01.example.com
# → Bind path: dc=example,dc=com
```

### Отладка маппинга и разрешений

```bash
# Проверка преобразования SID -> UID
wbinfo -n "Domain Users" # Получить SID
wbinfo -S <SID>          # Получить GID

# Проверка видимости через ОС
getent passwd "username"
getent group "DOMAIN\Domain Users"

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

# Постоянное отслеживание ошибок аутентификации
journalctl -t winbind -f | grep "error"
```

### Мониторинг истечения ключей Keytab

```bash
# Проверка срока действия всех ключей
for principal in $(klist -k /etc/krb5.keytab | awk '{print $2}' | tail -n +2); do
    echo "Keytab entry: $principal"
    klist -k /etc/krb5.keytab | grep -i "$principal"
done
```

### Интеграция с системами мониторинга

- **Zabbix / Prometheus**: Используйте `wbinfo -t` и `net ads testjoin` в пользовательских проверках.
- **node_exporter**: текстовые метрики для сбора статуса `smbd` и `winbindd`.
- **Логи**: `journalctl -t winbind -t smbd -p err..emerg` — основной источник ошибок.

### Типовые ошибки AD-интеграции 2026

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `NT_STATUS_ACCESS_DENIED` при входе | Устаревший NTLM или неверный UID | Проверьте `ntlm auth = ntlmv2-only`, убедитесь в корректности `idmap`. |
| `wbinfo -t` → `NT_STATUS_ACCESS_DENIED` | Пароль компьютера в AD не совпадает с локальным | Переприсоединитесь к домену или обновите keytab. |
| Дубликаты UID/GID | Пересечение диапазонов в `idmap config` | Пересмотрите диапазоны: каждый домен должен иметь уникальный пул. |
| `getent passwd` не видит доменных пользователей | NSS настроен некорректно | Проверьте `/etc/nsswitch.conf`, `winbind enum users = no`. |
| `net ads join` завершается с `kinit failed` | DNS или время не настроены | Проверьте `chronyc tracking` и DNS SRV-записи. |

## Документация раздела

- [Обзор Samba](./index.md) — архитектура, демоны и порты.
- [Настройка сервера](./samba_setup.md) — создание файловых ресурсов.
- [Безопасность и VFS](./samba_security.md) — hardening и модульное расширение.
- [Устранение неполадок](./samba_troubleshooting.md) — решение типовых проблем.

## См. также

- [SSSD и интеграция с Active Directory](../../../SystemAdministration/Users/LDAP_SSSD/ad_integration.md) — альтернативный метод интеграции.
- [Протокол Kerberos](../../../../Security/Concepts/kerberos.md)
- [Синхронизация времени (Chrony)](../chrony_ntp.md)
- [NSS и PAM](../../../SystemAdministration/Users/LDAP_SSSD/index.md)
- [Group Policy (GPO)](./samba_gpo.md) — управление политиками.
- [Кластеризация (CTDB)](./samba_cluster.md) — высокая доступность.
- [SIEM и комплаенс](./samba_siem.md) — аудит и безопасность.
