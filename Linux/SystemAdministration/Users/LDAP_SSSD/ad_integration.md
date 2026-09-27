# Интеграция SSSD с Active Directory

## Определения

Базовая информация о протоколах LDAP и Kerberos доступна в **[обзорном разделе](./index.md)**.

- **Active Directory (AD)** — служба каталогов от Microsoft, интегрирующая LDAP, Kerberos и DNS для централизованного управления ресурсами.
- **SSSD (System Security Services Daemon)** — системная служба Linux для подключения к провайдерам идентификации. Провайдер `ad` в SSSD оптимизирован для специфики Microsoft AD.
- **Global Catalog (GC)** — роль контроллера домена, содержащая частичную копию всех объектов леса AD. SSSD использует порт 3268 для ускоренного поиска пользователей из других доменов леса.
- **Read-Only Domain Controller (RODC)** — контроллер домена «только для чтения». SSSD поддерживает работу с RODC, что критично для безопасности филиалов.
- **Cross-forest Trust** — доверительные отношения между лесами AD. SSSD позволяет аутентифицировать пользователей из доверенных лесов.
- **SID (Security Identifier)** — уникальный идентификатор Windows, который SSSD преобразует в числовые UID/GID.
- **realmd** — демон и утилита командной строки для автоматического обнаружения и присоединения Linux-хостов к доменам Active Directory, FreeIPA или Kerberos.
- **adcli** — утилита для управления workstation-объектами в AD (создание, обновление, удаление, сброс пароля компьютера).
- **GPO (Group Policy Object)** — объект групповой политики AD. SSSD может применять фильтрацию доступа на основе GPO (`ad_gpo_access_control`).
- **CLDAP (Connectionless LDAP)** — UDP-версия LDAP (порт 389), используемая AD для site-aware discovery. SSSD отправляет UDP-запросы для определения сайта и ближайшего DC.
- **UAC (User Account Control)** — флаги учетной записи AD. SSSD игнорирует отключенные (`UF_ACCOUNTDISABLE`) и неистекшие (`UF_DONT_EXPIRE_PASSWD`) учетные записи в соответствии с провайдером `ad`.
- **idmap range** — диапазон UID/GID, назначаемый алгоритмическим маппингом. Определяет `ldap_idmap_range_min` и `ldap_idmap_range_max` в `sssd.conf`.

## Базовые концепции

### Механизмы маппинга идентификаторов

AD по умолчанию не содержит POSIX-атрибутов. SSSD предлагает два способа их получения:

1.  **Алгоритмический маппинг (`ldap_id_mapping = True`)**: SSSD вычисляет UID/GID на основе SID.
    - **Плюсы**: Идентификаторы консистентны на всех Linux-хостах без правки AD.
    - **Минусы**: Могут возникнуть конфликты, если в сети используются разные алгоритмы вычисления.
    - **Алгоритм**: В качестве основы используется Domain SID. SSSD конвертирует подчасти SID в числовые идентификаторы. Диапазон задается через `ldap_idmap_range_min`/`max`.
2.  **Явный маппинг (`ldap_id_mapping = False`)**: Считывание атрибутов `uidNumber` и `gidNumber` напрямую из AD.
    - **Плюсы**: Полный контроль над ID.
    - **Минусы**: Требует расширения схемы и ручного заполнения полей в Windows.
    - **Важно**: При явном маппинге убедитесь, что диапазоны не пересекаются с локальными UID/GID и алгоритмическими диапазонами.

### Протоколы взаимодействия с AD

Провайдер `ad` использует несколько протоколов одновременно:

| Протокол | Порт | Назначение |
| :--- | :--- | :--- |
| **LDAP/LDAPS** | 389 / 636 TCP | Поиск пользователей, групп, атрибутов. LDAPS обязателен для production. |
| **Kerberos** | 88 TCP/UDP | Получение TGT, двунаправленная аутентификация хоста. |
| **CLDAP** | 389 UDP | Определение сайта (site-aware discovery) и ближайшего DC. |
| **DNS** | 53 TCP/UDP | SRV-записи (`_ldap._tcp.dc._msdcs.<domain>`) для обнаружения контроллеров домена. |
| **Global Catalog** | 3268 TCP | Поиск в других доменах леса без указания полного DN. |

### Обнаружение сайтов (Site-aware Discovery)

SSSD использует механизм CLDAP (UDP 389) для определения своего сайта AD. Это позволяет:
- Подключаться к ближайшему контроллеру домена (DC).
- Снижать задержки и нагрузку на WAN-каналы.
- Автоматически переключаться на резервные DC при сбоях.

Если автоопределение не работает (фильтр UDP 389 на брандмауэре), используйте `ad_site = <SiteName>` в `sssd.conf`. Имя сайта можно узнать через Active Directory Sites and Services на DC.

### Обработка групповой политики (GPO)

SSSD может синхронизировать права доступа с AD через GPO. Параметр `ad_gpo_access_control` управляет поведением:

| Значение | Описание |
| :--- | :--- |
| `disabled` | GPO не обрабатывается. Доступ определяется только параметрами `access_provider`. |
| `permissive` | GPO проверяется, но ошибки не блокируют вход. Используется для отладки. |
| `enforcing` | GPO строго применяется. Если политика запрещает вход — доступ отклоняется. |

Дополнительные параметры GPO:
- **`ad_gpo_map_interactive`**: Список служб, для которых применяется интерактивная политика (например, `+sshd`, `+login`).
- **`ad_gpo_map_remote_interactive`**: Для удаленных сессий (RDP, SSH).
- **`ad_gpo_allow_remote`**: Разрешает обработку GPO при удаленном доступе.

### Глобальный каталог (GC) и междоменный поиск

Для лесов с несколькими доменами SSSD автоматически использует Global Catalog (GC) для:
- Поиска пользователей из других доменов леса без указания полного DN.
- Разрешения вложенных групп (`tokenGroups` через GC).

GC слушает порт **3268 TCP**. Убедитесь, что этот порт открыт на контроллерах домена, если пользователи из других доменов не отображаются.

### Работа в сложных лесах (Multi-domain)

Провайдер `ad` автоматически обнаруживает структуру леса. Для корректной работы с доверенными лесами важно:
- Использование Global Catalog (GC) для междоменного поиска.
- Настройка `subdomains_provider = ad` (включено по умолчанию для провайдера `ad`).
- Разрешение DNS имен всех доменов леса.
- `realmd` автоматически добавляет discovered поддомены в `sssd.conf` через блоки `[domain/realm]`.

### Доверительные отношения (Trusts)

SSSD поддерживает аутентификацию пользователей из доверенных лесов через:
- **External Trust** — одностороннее или двустороннее доверие между отдельными доменами.
- **Forest Trust** — доверие между лесами. Требует поддержки GC и правильной DNS-резолвеции.

Для использования users из доверенного леса убедитесь, что:
1. SSSD имеет доступ к GC (порт 3268).
2. В доверенном лесу включен SID filtering (или настроены соответствующие разрешения).
3. `krb5.conf` содержит правила `domain_realm` для обоих лесов.

### Взаимодействие с Kerberos

SSSD использует Kerberos (TGT — Ticket Granting Ticket) для Kerberos-аутентификации. Для провайдера `ad` файл `/etc/krb5.conf` создается автоматически через `realmd`. Ключевые параметры:
- **`default_realm`**: Realm домена AD (в верхнем регистре).
- **`dns_lookup_kdc`**: `true` — позволяет автоматически находить KDC через DNS SRV.
- **`dns_lookup_realm`**: `false` — realm определяется из домена, а не из DNS.
- **`forwardable`**: `true` — билеты можно пересылать на другие хосты.

Для LDAP-среды требуется ручная настройка `krb5.conf` (см. **[Конфигурация LDAP и SSSD](./configuration.md)**).

### Политики паролей и учетные записи

SSSD через провайдер `ad` наследует политики безопасности AD:
- **Срок действия пароля**: При истечении срока SSSD возвращает ошибку `Password expired`. Пользователь должен сменить пароль через Windows-инструменты или `passwd` (если настроен канал смены).
- **Блокировка учетной записи**: После нескольких неудачных попыток вход блокируется на уровне AD.
- **UserAccountControl (UAC)**: SSSD учитывает флаги UAC. Например, `UF_ACCOUNTDISABLE` исключает учетную запись из поиска.

## Практические сценарии

### 1. Автоматическое подключение через realmd

Рекомендуемый метод для большинства современных дистрибутивов (RHEL 8/9, Ubuntu 22.04+).

```bash
# Обнаружение параметров домена
realm discover example.com
# → realm-name: EXAMPLE.COM
# → domain-name: example.com
# → server-software: active-directory
# → client-software: sssd
# → required-package: sssd

# Присоединение к домену
# Автоматически настраивает sssd.conf, krb5.conf и обновляет DNS
sudo realm join example.com -U Administrator

# Проверка статуса
realm list
# → example.com
#    domain-status: Online
#    server-software: active-directory
#    client-software: sssd

# Просмотр всех обнаруженных доменов леса
realm list --all
```

Для выхода из домена:
```bash
sudo realm leave example.com
```

### 2. Продвинутая конфигурация /etc/sssd/sssd.conf

Файл должен иметь владельца `root:root` и права `600`.

```ini
[sssd]
domains = example.com
config_file_version = 2
services = nss, pam
# Для GPO и расширенных атрибутов можно добавить ifp
# services = nss, pam, ifp

[nss]
filter_users = root,daemon,bin,sys,sync
filter_groups = root,daemon,bin,sys,sync
negative_timeout = 60

[pam]
offline_credentials_expiration = 7

[domain/example.com]
id_provider = ad
auth_provider = ad
access_provider = ad

# Принудительное указание сайта, если автоопределение недоступно
ad_site = Moscow_Office

# Список DC: первый в списке — предпочтительный для чтения
# Для смены паролей SSSD автоматически найдет writable DC
ad_server = rodc01.example.com, rwdc01.example.com
# Или явный backup для операций записи:
# ad_server = rodc01.example.com
# ad_backup_server = rwdc01.example.com

# Параметры маппинга
ldap_id_mapping = True
use_fully_qualified_names = False
fallback_homedir = /home/%u@%d
# %u — логин пользователя, %d — короткое имя домена (до первой точки)

# Управление доступом через GPO
ad_gpo_access_control = enforcing
ad_gpo_map_interactive = +sshd
# ad_gpo_map_remote_interactive = +sshd, +rdp

# Безопасность и кэширование
cache_credentials = True
krb5_store_password_if_offline = True

# Производительность для больших лесов
enumerate = False
ldap_page_size = 5000
ldap_search_timeout = 60
entry_cache_timeout = 1800
```

#### Несколько доменов в одной конфигурации

```ini
[sssd]
domains = corp_ad, ext_ldap
config_file_version = 2
services = nss, pam

[domain/corp_ad]
id_provider = ad
auth_provider = ad
ad_server = dc01.corp.example.com
ad_site = Default-First-Site-Name

[domain/ext_ldap]
id_provider = ldap
auth_provider = ldap
ldap_uri = ldaps://ldap01.ext.example.com:636
ldap_search_base = dc=ext,dc=example,dc=com
ldap_schema = rfc2307bis
```

### 3. Интеграция с RODC

При работе с RODC необходимо учитывать, что он не поддерживает смену паролей.
- В `ad_server` рекомендуется указывать RODC первым для чтения, а RWDC — вторым или через `ad_backup_server` для операций записи.
- Убедитесь, что пароли необходимых пользователей реплицируются на RODC (Password Replication Policy в AD).
- Для проверки Policy используйте ADUC (`Active Directory Users and Computers`) → свойства контроллера → вкладка `Password Replication Policy`.

### 4. Динамическое обновление DNS (TSIG)

SSSD обновляет записи хоста в AD DNS.
- **Проблема**: Хост может сменить IP, и запись не обновится из-за прав.
- **Решение**: SSSD использует GSS-TSIG. Убедитесь, что в свойствах зоны AD DNS разрешены «Secure only» обновления.

Проверка обновления DNS:
```bash
# До обновления
dig +short host01.example.com

# Принудительное обновление (если не работает автоматически)
sudo sssctl domain-status example.com --online
# Или через adcli:
sudo adcli update --computer-name=$(hostname)
```

### 5. Управление доменом через realm и adcli

Помимо `realm`, для тонкого управления workstation-объектом используйте `adcli`:

```bash
# Показать информацию о компьютере в AD
adcli info example.com
# → Computer: HOST01$
# → Domain: EXAMPLE.COM
# → Site: Moscow_Office
# → DC: dc01.example.com

# Сброс пароля компьютера (если истек)
sudo adcli update --computer-name=$(hostname) --reset-password

# Просмотр всех доменов леса
realm discover --all example.com
```

### 6. Проверка Kerberos и членства

```bash
# Получение TGT для тестового пользователя
kinit administrator@EXAMPLE.COM
# Проверка билетов
klist -v
# → Ticket cache: KCM:1000
# → Default principal: administrator@EXAMPLE.COM
# → Valid starting       Expires              Service principal
# → 09/13/2026 18:00:00  09/14/2026 18:00:00  krbtgt/EXAMPLE.COM@EXAMPLE.COM

# Проверка доменной группы через id
id user@example.com
# → uid=10001(user@example.com) gid=10001(group@example.com) groups=10001(group@example.com),10002(sudo)

# Проверка разрешения имен
getent passwd user@example.com
# → user@example.com:*:10001:10001:User:/home/user@example.com:/bin/bash
```

### 7. Настройка GPO и доступ

Для отладки GPO используйте `permissive` режим:

```ini
ad_gpo_access_control = permissive
```

После проверки политик переключитесь на `enforcing`. Для просмотра примененных политик:

```bash
# В Windows: rsop.msc или gpresult /h result.html
# На Linux через SSSD логи:
sudo sssctl debug-level 6
journalctl -u sssd -f | grep -i gpo
```

### 8. Расширенные атрибуты AD

SSSD может получать дополнительные атрибуты из AD через `ldap_user_extra_attrs` и `ldap_group_extra_attrs`:

```ini
[domain/example.com]
ldap_user_extra_attrs = sshPublicKey, email, givenname, sn, displayname
ldap_group_extra_attrs = description, mail

[sssd]
services = nss, pam, ifp

[ifp]
allowed_uids = root, sshd
user_attributes = sshPublicKey, email, givenname, sn
```

Настройте `sshd` для использования ключей из AD:

```text
# /etc/ssh/sshd_config
AuthorizedKeysCommand /usr/bin/sss_ssh_authorizedkeys
AuthorizedKeysCommandUser sssd
```

### 9. Активация профиля через authselect (RHEL)

```bash
# Активация SSSD с автоматическим созданием домашних директорий
sudo authselect select sssd with-mkhomedir --force
sudo systemctl enable --now oddjobd
```

На Debian/Ubuntu используйте `pam-auth-update`:

```bash
sudo pam-auth-update --enable sssd
sudo systemctl enable --now oddjobd
```

### 10. Автоматизация через Ansible

Для массового развертывания и ввода хостов в Active Directory рекомендуется использовать Ansible. Это обеспечивает идемпотентность и исключает ошибки ручной настройки.

Основные сценарии автоматизации (System Roles, `realm` module) описаны в разделе **[Ansible Identity Management](../../../../Ansible/ansible-identity-management.md)**.

### 11. Валидация конфигурации перед применением

```bash
# Проверка синтаксиса sssd.conf
sudo sssctl config-check

# Проверка доступности AD
sudo sssctl domain-status example.com

# Проверка домена через realm
realm list

# Проверка DNS
dig +short _ldap._tcp.dc._msdcs.example.com srv

# Проверка портов
nc -zv dc01.example.com 389
nc -zv dc01.example.com 636
nc -zv dc01.example.com 88
nc -zv dc01.example.com 3268
nc -zv dc01.example.com 389  # UDP для CLDAP

# Проверка времени (критично для Kerberos)
chronyc tracking
```

## Дополнительная информация

### Рекомендации (2026)

- **Производительность**: Отключите `enumerate = True`. Для крупных лесов увеличьте `ldap_page_size` (по умолчанию 1000).
- **Сайты**: Проверьте доступность порта **389 UDP** (CLDAP) для работы механизма автоопределения сайтов.
- **Безопасность**: Используйте `ad_gpo_access_control = enforcing` для синхронизации прав доступа Linux-серверов с политиками безопасности AD.
- **Доверительные отношения**: При работе с cross-forest trust проверяйте доступность GC и корректность SID filtering.
- **RODC**: В филиалах используйте RODC первым в списке `ad_server`, но настройте Password Replication Policy для критичных учетных записей.

### Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Preauthentication failed` | Рассинхронизация времени (> 5 мин). | Проверьте `chronyd` и связь с контроллером домена. |
| `System Error` при логине | Ошибка маппинга или прав на `sssd.conf`. | `chmod 600 /etc/sssd/sssd.conf`. Очистите кэш: `sss_cache -E`. |
| Не видны группы из других доменов | Нет доступа к Global Catalog. | Проверьте порт **3268 TCP** на контроллерах домена. |
| DNS обновление завершилось с ошибкой | Недостаточно прав у учетной записи компьютера. | Проверьте права в свойствах DNS-зоны на стороне AD. |
| `Cannot contact LDAP server` | Брандмауэр блокирует порт 389/636, или DNS не резолвится. | Проверьте `nc -zv dc01.example.com 389` и `/etc/resolv.conf`. |
| `KDC has no support for encryption type` | Устаревший алгоритм шифрования Kerberos. | Обновите krb5.conf, добавьте `default_tkt_enctypes = aes256-cts-hmac-sha1-96`. |
| `rpcbind: RPC: Program not registered` | Служба `rpcbind` не запущена или не настроена. | Запустите `sudo systemctl enable --now rpcbind`. Требуется для некоторых операций AD. |
| `No DNS domain configured` | Отсутствует domain в `sssd.conf` или realm. | Проверьте `realm list` и блок `[domain/example.com]`. |
| `GPO processing failed` | Ошибка чтения GPO или неправильный `ad_gpo_map_*`. | Переключитесь в `permissive` для диагностики. Проверьте логи SSSD. |
| Пароль не меняется при входе | `krb5_store_password_if_offline = True` без writable DC. | Убедитесь, что `ad_backup_server` указывает на RWDC, или удалите параметр. |

### Логирование и анализ AD-специфичных ошибок

SSSD ведет подробные логи в `/var/log/sssd/`. Для AD-интеграции наиболее важны:

```bash
# Основной лог домена
sudo tail -f /var/log/sssd/sssd_example.com.log

# Поиск ошибок Kerberos
sudo grep -i "kerberos\|kinit\|preauth" /var/log/sssd/sssd_example.com.log

# Поиск ошибок LDAP/ bind
sudo grep -i "ldap\|bind\|SASL" /var/log/sssd/sssd_example.com.log

# Поиск ошибок GPO
sudo grep -i "gpo" /var/log/sssd/sssd_example.com.log

# Анализ через journalctl
journalctl -u sssd --since "1 hour ago" | grep -E "Error|Failed|DENIED"
```

### SELinux и права доступа

На RHEL-подобных системах проверяйте контексты:

```bash
# Файл конфигурации
ls -Z /etc/sssd/sssd.conf
# → system_u:object_r:etc_t:s0 /etc/sssd/sssd.conf

# База LDB
ls -Z /var/lib/sss/db/*
# → system_u:object_r:sssd_var_lib_t:s0 ...

# Логи
ls -Z /var/log/sssd/
# → system_u:object_r:sssd_log_t:s0 ...

# Ключ хоста (keytab)
ls -Z /etc/krb5.keytab
# → system_u:object_r:krb5_keytab_t:s0 /etc/krb5.keytab
```

Некорректные контексты маскируются под общие ошибки аутентификации. Восстановите контексты:

```bash
sudo restorecon -Rv /etc/sssd /var/lib/sss /var/log/sssd
```

### Миграция с winbind

Если в системе ранее использовался winbind, выполните полный переход:

```bash
# 1. Остановка winbind
sudo systemctl disable --now winbind nmb

# 2. Удаление winbind из nsswitch.conf
sudo sed -i '/winbind/d' /etc/nsswitch.conf

# 3. Удаление настроек winbind из smb.conf (если есть)
# sudo mv /etc/samba/smb.conf /etc/samba/smb.conf.bak

# 4. Очистка кэша winbind
sudo net cache flush

# 5. Установка SSSD и зависимостей
sudo dnf install sssd sssd-ad sssd-tools libnss-sssd libpam-sssd oddjob-mkhomedir

# 6. Присоединение через realm (автоматически перезаписывает sssd.conf)
sudo realm join example.com -U Administrator

# 7. Валидация
id user@example.com
getent passwd user@example.com
```

### Смежные темы

- [Конфигурация LDAP и SSSD](./configuration.md) — общие принципы и параметры.
- [Администрирование и отладка SSSD](./operations.md) — работа с `sssctl` и журналами.
- [Ansible Identity Management](../../../../Ansible/ansible-identity-management.md) — автоматизация присоединения.
- [Samba: Интеграция с AD](../../../Networking/Services/samba/samba_ad.md) — альтернативный метод через Winbind.
- [Kerberos](../../../../Security/Concepts/kerberos.md) — основы работы билетов и Keytab.
- [PAM (Pluggable Authentication Modules)](../../../Security/pam_overview.md) — детальный разбор стека аутентификации.
