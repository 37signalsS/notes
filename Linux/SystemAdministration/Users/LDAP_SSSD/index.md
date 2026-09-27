# Централизованное управление пользователями (LDAP, SSSD)

## Определения

- **LDAP (Lightweight Directory Access Protocol)** — сетевой протокол прикладного уровня для доступа к распределенной иерархической службе каталогов. Является промышленным стандартом для хранения учетных записей, групп и политик доступа.
- **SSSD (System Security Services Daemon)** — системная служба Linux, выступающая посредником между локальной ОС и внешними провайдерами идентификации (LDAP, Active Directory, FreeIPA). Обеспечивает кэширование, работу в автономном (offline) режиме и интеграцию с Kerberos.
- **NSS (Name Service Switch)** — механизм системной библиотеки C (glibc), определяющий источники данных для системных баз (пользователи, группы, хосты). Конфигурируется в `/etc/nsswitch.conf`.
- **PAM (Pluggable Authentication Modules)** — модульная архитектура Linux для управления аутентификацией приложений (sshd, login, sudo). Использует модуль `pam_sss.so` для взаимодействия с SSSD.
- **MFA (Multi-Factor Authentication)** — многофакторная аутентификация, поддерживаемая SSSD через интеграцию с Kerberos (OTP), AD (GPO) или внешние PAM-модули.
- **GSSAPI (Generic Security Service API)** — интерфейс, позволяющий приложениям использовать Kerberos для безопасной аутентификации без передачи пароля в открытом виде.
- **SASL (Simple Authentication and Security Layer)** — фреймворк для добавления поддержки аутентификации в протоколы (например, LDAP), обеспечивающий использование механизмов GSSAPI, DIGEST-MD5 и др.
- **LDB (Lightweight Database)** — встраиваемая база данных на основе LDAP-подобного движка, используемая SSSD для локального хранения кэша пользователей, групп и атрибутов.
- **Responder (Респондер)** — специализированный процесс SSSD (например, `sssd_nss`, `sssd_pam`), который обрабатывает запросы от конкретных подсистем ОС.
- **InfoPipe** — респондер SSSD, предоставляющий D-Bus интерфейс для получения информации о пользователях и метрик производительности.
- **KCM (Kerberos Cache Manager)** — встроенный в SSSD менеджер кэша Kerberos-билетов, обеспечивающий изоляцию данных между контейнерами и пользователями.
- **Realm** — область аутентификации Kerberos, обычно соответствует верхнему регистру DNS-домена (например, `DOMAIN.LOCAL`). Все машины домена должны принадлежать одному realm.
- **HBAC (Host Based Access Control)** — правила, определяющие, какие пользователи могут входить на какие хосты через какие сервисы (например, SSH). В FreeIPA управляется централизованно.
- **RBAC (Role Based Access Control)** — управление правами доступа к ресурсам на основе ролей, в контексте LDAP/SSSD часто реализуется через групповое членство и sudo-правила.
- **AutoFS (Automatic Filesystem Mount)** — механизм автомонтирования сетевых файловых систем по требованию. SSSD может выступать источником данных для AutoFS, обеспечивая централизованное управление точками монтирования.

## Базовые концепции

### Архитектура и жизненный цикл запроса

SSSD инкапсулирует сложность взаимодействия с удаленными серверами, предоставляя системе стандартные интерфейсы.

1.  **id_provider**: Извлекает метаданные (UID, GID, Home, Shell).
2.  **auth_provider**: Выполняет проверку подлинности (Password, OTP, Kerberos).
3.  **access_provider**: Применяет политики доступа (HBAC во FreeIPA, GPO в AD, фильтры в LDAP).
4.  **chpass_provider**: Управляет процессом смены паролей.

#### Схема прохождения запроса (2026)

```text
[ Приложение / SSHD ]  --> [ PAM (pam_sss) ] --\
                                                --> [ SSSD (Daemon) ] <--> [ LDAP / AD / FreeIPA ]
[ Команды id / ls ]    --> [ NSS (nss_sss) ] --/           |
                                                 [ Локальный кэш (LDB) ]
                                                           |
                                                 [ systemd-logind / homed ]
```

### Ключевые компоненты интеграции

| Компонент | Роль в системе | Приоритет |
| :--- | :--- | :--- |
| `/etc/nsswitch.conf` | Определяет порядок опроса источников (files -> sss). | Критический |
| `/etc/sssd/sssd.conf` | Центральная конфигурация доменов и параметров кэша. | Критический (права 600) |
| `/etc/krb5.conf` | Настройки Kerberos-реалма для работы SSO. | Опционально (для AD/IPA) |
| `sssctl` | Инструмент инспекции состояния и очистки кэша. | Эксплуатационный |

### Схемы LDAP и POSIX-атрибуты

Для хранения данных пользователей и групп в LDAP используются стандартные схемы. Выбор схемы влияет на способ хранения членства в группах и совместимость с серверами.

- **RFC 2307**: Классическая схема. Членство в группе хранится через атрибут `memberUid` на стороне группы (список логинов). Требует перечисления группы для получения списка пользователей.
- **RFC 2307bis**: Современный стандарт. Членство в группе храниется через атрибут `member` на стороне группы (список DN пользователей). Позволяет использовать вложенные группы (nested groups) и операционный атрибут `memberOf` на стороне пользователя.

**Ключевые объектные классы:**
- `inetOrgPerson` / `posixAccount` / `shadowAccount` — пользователь с POSIX-атрибутами (`uidNumber`, `gidNumber`, `homeDirectory`, `loginShell`).
- `groupOfNames` / `groupOfMembers` — группа с атрибутом `member` (DN) или `memberUid` (UID).

### Разрешение членства в группах

SSSD поддерживает несколько моделей разрешения групп:
- **Первичная группа (Primary Group)**: Указывается в атрибуте `gidNumber` записи пользователя. Файлы, создаваемые пользователем, по умолчанию наследуют GID этой группы.
- **Дополнительные группы (Supplementary Groups)**: Опираются на атрибуты членства в группе (`memberUid` или `member`). Определяются через `getgrnam()` и `getgrent()`.
- **Вложенные группы (Nested Groups)**: Поддерживаются в `rfc2307bis` через атрибут `member`. SSSD может рекурсивно распаковывать вложенность при включенном `ldap_group_nesting_level`.

### Политики паролей и блокировка учетных записей

SSSD интегрируется с механизмами защиты паролей на стороне LDAP-сервера:
- **ppolicy overlay** (OpenLDAP) или встроенные политики (389DS, AD): ограничение по сложности, истории, сроку действия.
- **Account Lockout**: Временная блокировка после N неудачных попыток входа. На стороне клиента SSSD кэширует статус блокировки, что предотвращает дальнейшие попытки подбора даже при недоступности сервера.
- **Кэширование паролей**: При `cache_credentials = true` SSSD сохраняет хэши паролей в локальном кэше LDB. Это позволяет проводить аутентификацию в offline-режиме, но требует дополнительных мер защиты базы LDB (`chmod 600` на `/var/lib/sss/db/`).

### Управление домашними директориями

При первом входе пользователя LDAP необходимо создать домашнюю директорию. Существует три механизма:
1.  **pam_mkhomedir.so**: PAM-модуль, создающий `/home/<user>` из `/etc/skel` при входе. Минимальная настройка.
2.  **oddjob-mkhomedir**: Демон `oddjobd` с D-Bus интерфейсом. Более безопасен, так как не требует привилегий PAM на момент создания директории.
3.  **systemd-homed**: Современный подход, где домашняя директория — зашифрованный LUKS2-образ. SSSD может выступать источником данных для `systemd-homed`, позволяя создавать портативные профили.

### Интеграция с sudo

SSSD может извлекать правила sudo напрямую из LDAP без редактирования локального `/etc/sudoers`:
- В `/etc/nsswitch.conf` добавляется строка `sudoers: files sss`.
- В LDAP создаются объекты класса `sudoRole` с атрибутами `sudoUser`, `sudoHost`, `sudoCommand`.
- Преимущество: централизованное обновление правил, немедленное вступление в силу без перезапуска sudo.

### Интеграция с AutoFS

Для автоматического монтирования сетевых файловых систем (NFS, CIFS) SSSD может служить источником карт автомонтирования:
- В `/etc/nsswitch.conf` указывается `automount: files sss`.
- В SSSD настраивается секция `[autofs]` с указанием `autofs_provider = ldap`.
- Карты монтирования хранятся в атрибутах LDAP (например, `auto.mount`), что позволяет управлять тысячами точек монтирования из единого центра.

### SELinux и контексты безопасности

В RHEL/Rocky/AlmaLinux SELinux играет критическую роль при работе SSSD:
- Процесс `sssd` работает в домене `sssd_t`.
- Доступ к портам LDAP/LDAPS (389/636) и Kerberos (88/464) требует соответствующих правил SELinux.
- Файлы конфигурации и базы LDB должны иметь корректные контексты (`sssd_var_lib_t`, `etc_t`).
- Отказ в доступе (`AVC denial`) часто проявляется как `System Error` при входе, что диагностируется через `ausearch -m avc -ts recent`.

### Современные тенденции (2026)

- **Интеграция с [systemd-homed](../systemd-homed.md)**: SSSD может выступать источником данных для `systemd-homed`, позволяя создавать портативные домашние директории для пользователей LDAP.
- **Native MFA**: Прямая поддержка OTP-токенов в SSSD снижает зависимость от сторонних PAM-скриптов.
- **Smart Card / Passkey**: Усиление безопасности через поддержку аппаратных ключей (FIDO2/U2F) на уровне аутентификации в SSSD.
- **Migration from nscd/winbind**: В 2026 году `nscd` считается устаревшим. SSSD — рекомендованная замена для всех новых развертываний. Для Samba-сред preffered решение зависит от сценария (ACL → winbind, системный вход → SSSD).

## Практические сценарии

### Выбор архитектуры IdM

| Решение | Целевое назначение | Плюсы / Минусы |
| :--- | :--- | :--- |
| **OpenLDAP** | Минималистичные окружения. | +Легкость, -Нет Kerberos «из коробки». |
| **FreeIPA (IdM)** | Иерархические Linux-инфраструктуры. | +HBAC, DNS, CA, Sudo-политики. |
| **Active Directory** | Гетерогенные сети (Win+Lin). | +Централизация, -Сложность маппинга SID/UID. |

### Жизненный цикл управления (Lifecycle)

1.  **Регистрация (Enrollment)**: Ввод хоста в домен с помощью `realm join` или `ipa-client-install`. Для массового развертывания используется **[автоматизация через Ansible](../../../../Ansible/ansible-identity-management.md)**.
2.  **Авторизация**: Настройка `access_provider` для ограничения входа (например, только члены группы `sysadmins`).
3.  **Эксплуатация**: Мониторинг состояния через `sssctl domain-status` и обновление Keytab.
4.  **Вывод из эксплуатации**: Удаление учетной записи компьютера (`realm leave`) и очистка локальных кэшей.

### Валидация и проверка работоспособности

После настройки выполните базовые проверки для подтверждения корректности интеграции:

```bash
# Проверка статуса домена
sudo sssctl domain-status domain.local
# → Domain example.com: Online, Server: dc1.example.com

# Проверка разрешения имен пользователей
getent passwd ldap_user
# → ldap_user:x:10000:10000:LDAP User:/home/ldap_user:/bin/bash

# Проверка разрешения групп
getent group ldap_group
# → ldap_group:x:10000:

# Проверка аутентификации через PAM
su - ldap_user -c "id"
# → uid=10000(ldap_user) gid=10000(ldap_user) groups=10000(ldap_user)

# Проверка кэша Kerberos
klist -kt /etc/krb5.keytab

# Проверка списка хостов в домене
realm list
# → corp.example.com
#     configured: kerberos-member
#     server-software: active-directory
#     client-software: sssd
```

### Навигация по документации

Для глубокого погружения используйте следующие разделы:

1.  **[Установка и настройка LDAP и SSSD](./configuration.md)**: Подробные параметры `sssd.conf`, настройка TLS, выбор схем (`rfc2307` vs `rfc2307bis`), SSH-ключи из LDAP, централизованные sudo-правила через LDAP.
2.  **[Интеграция SSSD с Active Directory](./ad_integration.md)**: Специфика провайдера `ad`, маппинг ID (Algorithmic vs Explicit), GPO, CLDAP, Global Catalog, RODC.
3.  **[Эксплуатация и отладка SSSD](./operations.md)**: Работа с `sssctl`, `sss_override`, уровни логирования, паттерны анализа логов, аварийное восстановление, тюнинг для больших каталогов, централизованный сбор логов и аудит.

## Дополнительная информация

### Безопасность и соответствие (Compliance)

- **Шифрование трафика**: Использование LDAPS (636) или StartTLS (389) обязательно. Незащищенный LDAP (Bind без TLS) запрещен во всех современных стандартах (SOC2, PCI-DSS).
- **Минимальные привилегии**: Учетная запись `Bind DN` должна иметь права только на чтение (Read-Only) необходимых атрибутов.
- **Аудит**: SSSD логирует попытки входа и ошибки доступа в `/var/log/sssd/`. Рекомендуется интегрировать этот каталог с централизованными системами сбора логов (Vector, ELK, Graylog).
- **SELinux**: В RHEL-подобных системах убедитесь, что контексты безопасности корректны. Отказы SELinux часто маскируются под общие ошибки входа.

### Безопасность SSSD (Security Hardening)

Конфигурация SSSD по умолчанию ориентирована на удобство. В продакшене необходимо ужесточить параметры безопасности.

#### Защита кэша паролей

При `cache_credentials = true` SSSD хранит хэши паролей в LDB. Это критичная поверхность атаки:

```bash
# Проверка прав на каталог кэша
ls -la /var/lib/sss/db/
# → -rw------- 1 root root 12K Sep 17 10:00 cache_example.com.ldb
# → Права должны быть 600 (только root)

# Исправление прав (если нарушены)
sudo chown -R root:root /var/lib/sss/db/
sudo chmod 600 /var/lib/sss/db/*.ldb
sudo chmod 600 /var/lib/sss/db/*.tdb
```

**Рекомендации:**
- На публичных/общедоступных хостах (shared workstations, киоски) — `cache_credentials = false`.
- При полном шифровании диска (LUKS) — `cache_credentials = true` допустимо.
- Без шифрования диска — хранение хэшей паролей рискованно: физический доступ к диску = компрометация паролей.

#### Защита ключей (Keytab)

```bash
# Проверка прав на keytab
ls -la /etc/krb5.keytab
# → -rw------- 1 root root 1280 Sep 17 10:00 /etc/krb5.keytab
# Права: 400 или 600 (только root)

# Ротация keytab (AD)
sudo adcli update --computer-name=$(hostname) --reset-password

# Ротация keytab (FreeIPA)
sudo ipa-getkeytab -s ipa01.example.com -p host/$(hostname)@EXAMPLE.COM -k /etc/krb5.keytab

# Проверка срока действия
sudo klist -kt /etc/krb5.keytab
```

**Рекомендации:**
- Не хранить keytab в общедоступных местах (`/tmp`, NFS-share).
- Ротация keytab каждые 90-180 дней (политика организации).
- При компрометации хоста — немедленная ротация через `adcli update --reset-password`.

#### Ограничение Bind DN

Учетная запись для SSSD (`ldap_default_bind_dn`) должна иметь минимальные привилегии:

```ldif
# Пример ACI для read-only Bind DN (OpenLDAP)
dn: olcDatabase={1}mdb,cn=config
changetype: modify
add: olcAccess
olcAccess: {0}to attrs=userPassword
  by dn="cn=sssd_readonly,ou=services,dc=example,dc=com" read
  by * none
olcAccess: {1}to *
  by dn="cn=sssd_readonly,ou=services,dc=example,dc=com" read
  by * none
```

**Запрещено:**
- Использование `cn=admin` или `cn=Directory Manager` как Bind DN.
- Bind DN с правами на запись (write/add/delete) — только read + search.
- Хранение пароля Bind DN в `sssd.conf` без шифрования (рассмотрите Vault или `ldap_default_authtok_type = obfuscated`).

#### Аудит через auditd

Мониторинг изменений критичных файлов SSSD:

```bash
# Добавление правил auditd
sudo auditctl -w /etc/sssd/sssd.conf -p wa -k sssd_config
sudo auditctl -w /etc/krb5.conf -p wa -k krb5_config
sudo auditctl -w /etc/krb5.keytab -p wa -k keytab_access
sudo auditctl -w /var/lib/sss/db/ -p wa -k sssd_cache
sudo auditctl -w /etc/nsswitch.conf -p wa -k nsswitch_config

# Просмотр событий
sudo ausearch -k sssd_config --recent
sudo ausearch -k keytab_access --recent
```

**Что отслеживать:**
- Изменение `sssd.conf` (внедрение вредоносного Bind DN или отключение TLS).
- Доступ к keytab (попытки извлечения ключей).
- Модификация `nsswitch.conf` (отключение `sss` для обхода LDAP).
- Записи в `/var/lib/sss/db/` (подмена кэша).

#### Изоляция через SELinux

На RHEL-подобных системах SELinux обеспечивает дополнительный уровень изоляции:

```bash
# Проверка текущего контекста sssd
ps -eZ | grep sssd
# → system_u:system_r:sssd_t:s0  1234 ?  00:00:01 sssd

# Проверка доступа к ресурсам
sudo ausearch -m avc -ts recent | grep sssd

# Восстановление контекстов (при сбоях)
sudo restorecon -Rv /etc/sssd /var/lib/sss /var/log/sssd

# Полезные SELinux-булевы
getsebool -a | grep sssd
# → sssd_use_nfs → off (включить, если домашние на NFS)
# → sssd_use_nfs_home_dirs → off
```

#### Сводная таблица hardening

| Параметр | Значение по умолчанию | Рекомендация для продакшена |
| :--- | :--- | :--- |
| `cache_credentials` | `false` | `true` (только при шифровании диска) |
| Права `sssd.conf` | - | `600 root:root` |
| Права LDB-баз | - | `600 root:root` |
| Права keytab | - | `400 root:root` |
| Bind DN | - | Read-only, минимальные привилегии |
| `ldap_tls_reqcert` | `allow` | `demand` (проверка сертификата) |
| TLS | Опционально | LDAPS (636) или StartTLS (389) |
| `debug_level` | `3` | `3` (6-9 только для отладки) |
| `auditd` правила | Нет | Мониторинг sssd.conf, keytab, nsswitch.conf |
| SELinux | - | Контексты `sssd_t`, `sssd_var_lib_t` |

### Производительность и тюнинг

- **Эффект перечисления (Enumeration)**: Параметр `enumerate = false` критически важен для больших каталогов (>1000 объектов) во избежание деградации производительности. При `enumerate = true` SSSD выгружает весь каталог в память.
- **Размер кэша**: В крупных инсталляциях (>10 000 пользователей) необходимо увеличивать `entry_cache_timeout` и выделять достаточно места для базы LDB в `/var/lib/sss/db/`.
- **Пагинация**: Для больших каталогов настройте `ldap_page_size` (по умолчанию 1000), чтобы избежать таймаутов на стороне сервера.
- **Negative Timeout**: Параметр `negative_timeout` в секции `[nss]` контролирует, как долго SSSD кэширует ответ «пользователь не найден». Слишком большое значение затрудняет отладку.

### Мониторинг и метрики

Для интеграции с системами мониторинга активируйте респондер `ifp` (InfoPipe):

```ini
[sssd]
services = nss, pam, ifp

[ifp]
allowed_uids = root, prometheus
user_attributes = +email, +phone
```

После настройки метрики доступны через D-Bus или специализированные экспортеры (например, `sssd_exporter` для Prometheus).

**Ключевые точки наблюдения:**
- Состояние домена: `sssctl domain-status`
- Размер кэша LDB: `du -sh /var/lib/sss/db/`
- Частота ошибок аутентификации: `journalctl -u sssd --since "1 hour ago" | grep -i "error\|fail"`
- Доступность LDAP-сервера: `ldapsearch -x -H ldaps://server -b "dc=example,dc=com" "(objectClass=*)" -s base`

### Миграция с устаревших решений

- **nscd → SSSD**: `nscd` (Name Service Cache Daemon) устарел. Остановите и отключите `nscd`, затем включите `sssd`. Убедитесь, что в `/etc/nsswitch.conf` заменен `nscd` на `sss`.
- **Winbind → SSSD**: В средах Samba, где не требуется полная совместимость с ACL Windows, можно перейти на SSSD для системного входа, оставив winbind только для файловых шаров. Сравнение см. в разделе [Winbind vs SSSD](#winbind-vs-sssd).
- **Локальные пользователи → LDAP**: Используйте `sss_override` для переноса локальных переопределений атрибутов в централизованный каталог.

### Автоматизация через Ansible

Для массового развертывания SSSD и ввода хостов в домен рекомендуется использовать Ansible. Подробные playbook-примеры см. в [Ansible Identity Management](../../../../Ansible/ansible-identity-management.md). Ниже — ключевые сценарии.

#### Пример 1: Массовое присоединение к AD

```yaml
- name: "Enrollment Linux-хостов в Active Directory"
  hosts: linux_servers
  become: true
  vars:
    ad_realm: "CORP.EXAMPLE.COM"
    ad_domain: "corp.example.com"
    ad_server: "dc01.corp.example.com"
    ad_join_user: "join_svc"
    ad_join_password: "{{ vault_ad_join_password }}"
  tasks:
    - name: Установка зависимостей
      ansible.builtin.package:
        name:
          - sssd
          - sssd-ad
          - realmd
          - adcli
          - oddjob-mkhomedir
        state: present

    - name: Присоединение к домену
      ansible.builtin.command:
        cmd: "realm join {{ ad_domain }} -U {{ ad_join_user }} --install=/"
      register: realm_join
      changed_when: "'already' not in realm_join.stderr"
      no_log: true

    - name: Активация authselect
      ansible.builtin.command:
        cmd: "authselect select sssd with-mkhomedir --force"
      changed_when: true
```

#### Пример 2: Настройка SSSD через шаблон

```yaml
- name: "Настройка SSSD для LDAP"
  hosts: ldap_clients
  become: true
  vars:
    ldap_uri: "ldaps://ldap01.example.com:636"
    ldap_search_base: "dc=example,dc=com"
    ldap_bind_dn: "cn=sssd_readonly,ou=services,dc=example,dc=com"
    ldap_bind_password: "{{ vault_ldap_bind_password }}"
  tasks:
    - name: Установка SSSD
      ansible.builtin.package:
        name:
          - sssd
          - sssd-ldap
          - sssd-tools
          - oddjob-mkhomedir
        state: present

    - name: Настройка sssd.conf
      ansible.builtin.template:
        src: templates/sssd.conf.j2
        dest: /etc/sssd/sssd.conf
        owner: root
        group: root
        mode: "0600"
        validate: "sssctl config-check -f %s"
      notify: restart sssd

    - name: Активация NSS
      ansible.builtin.lineinfile:
        path: /etc/nsswitch.conf
        regexp: "{{ item.regexp }}"
        line: "{{ item.line }}"
      loop:
        - { regexp: '^passwd:', line: 'passwd:     files sss' }
        - { regexp: '^group:', line: 'group:      files sss' }
        - { regexp: '^sudoers:', line: 'sudoers:    files sss' }

  handlers:
    - name: restart sssd
      ansible.builtin.systemd:
        name: sssd
        state: restarted
```

#### Пример 3: Откат при ошибке присоединения

```yaml
- name: "Откат Enrollment при ошибке"
  hosts: linux_servers
  become: true
  tasks:
    - name: Выход из домена
      ansible.builtin.command:
        cmd: "realm leave {{ ad_domain }}"
      register: realm_leave
      failed_when: false
      changed_when: "'not joined' not in realm_leave.stderr"

    - name: Восстановление nsswitch.conf
      ansible.builtin.copy:
        content: |
          passwd:     files
          group:      files
        dest: /etc/nsswitch.conf

    - name: Очистка кэша SSSD
      ansible.builtin.command:
        cmd: "sss_cache -E"
      failed_when: false

    - name: Перезапуск SSSD
      ansible.builtin.systemd:
        name: sssd
        state: restarted
```

### Сравнение: FreeIPA vs裸LDAP vs Active Directory

| Критерий | OpenLDAP | FreeIPA | Active Directory |
| :--- | :--- | :--- | :--- |
| **Сложность настройки** | Средняя | Низкая (Installer) | Высокая (Windows Server) |
| **Kerberos «из коробки»** | Нет (требует MIT KDC) | Да (MIT Kerberos) | Да (Встроенный) |
| **HBAC (разрешение доступа к хостам)** | Нет | Да (набор правил) | Ограниченно (GPO) |
| **Централизованные SUDO-правила** | Да (через `sudoRole`) | Да (IPA SUDO rules) | Ограниченно (GPO) |
| **DNS** | Нет | Да (интегрированный) | Да (интегрированный) |
| **CA (Центр сертификации)** | Нет | Да (Dogtag) | Да (AD CS) |
| **Масштаб** | 100K+ объектов | 50K+ хостов | 100K+ объектов |
| **Репликация** | Syncrepl | MMR (Multi-Master) | Multi-Master |
| **Интеграция с Windows** | Ограниченно | Ограниченно | Нативная |
| **Стоимость** | Бесплатно | Бесплатно | CAL лицензии |
| **Когда выбирать** | Минималистичные LDAP-среды, специфичные схемы | Linux-ориентированные среды, HBAC, CA | Гетерогенные сети Win+Lin, GPO |

**Рекомендация:** Для Linux-инфраструктуры >50 хостов — FreeIPA. Для гетерогенных сетей (Windows + Linux) — Active Directory. Для минималистичных сред — OpenLDAP.

### Winbind vs SSSD

| Критерий | Winbind (Samba) | SSSD |
| :--- | :--- | :--- |
| **Назначение** | Интеграция с файловыми шарами Samba | Системный вход, NSS, PAM, sudo |
| **NT ACL на файловых шарах** | Полная поддержка | Не поддерживается |
| **Kerberos SSO** | Да | Да |
| **GPO** | Ограниченно | Да (адаптировано для Linux) |
| **Вложенные группы** | Ограниченно | Да (rfc2307bis) |
| **Offline-аутентификация** | Да (net cache) | Да (LDB cache) |
| **Cross-forest trust** | Да | Да |
| **Performance** | Средняя | Высокая ( NSS-оптимизация) |
| **Когда выбирать** | Требуются NT ACL на файловых шарах | Системный вход, sudo, HBAC |

**Гибрид:** В средах Samba с файловыми шарами можно использовать SSSD для системного входа (NSS/PAM/sudo) и winbind только для ACL файловых шаров. В `nsswitch.conf`: `passwd: files sss`, `group: files sss`, но с запущенным `winbindd` для доступа к файловым ресурсам.

Подробнее: [Samba AD Integration](../../../../Linux/Networking/Services/samba/samba_ad.md).

### Смежные темы

- [PAM (Pluggable Authentication Modules)](../../../Security/pam_overview.md) — механизмы модульной аутентификации.
- [389 Directory Server (389DS)](../../../../LDAP/389ds/overview.md) — администрирование современного LDAP-сервера.
- [FreeIPA Overview](../../../../LDAP/FreeIPA/freeipa_overview.md) — архитектура и развертывание FreeIPA.
- [Протокол Kerberos](../../../../Security/Concepts/kerberos.md) — принципы работы билетов и SSO.
- [Управление пользователями Linux](../user_commands.md) — команды для работы с локальными аккаунтами.
- [Файлы конфигурации пользователей и групп](../users_config_files.md) — структура `/etc/passwd`, `/etc/shadow` и `/etc/nsswitch.conf`.
- [systemd-homed](../systemd-homed.md) — портативные домашние директории как альтернатива классическим `/home`.
- [AutoFS — автоматическое монтирование](../../../FileSystems/mounting/scenarios/autofs_mount.md) — интеграция сетевых ФС с LDAP через SSSD.
- [Samba AD Integration](../../../../Linux/Networking/Services/samba/samba_ad.md) — интеграция Linux с AD через Samba/Winbind.
- [Ansible Identity Management](../../../../Ansible/ansible-identity-management.md) — автоматизация управления идентификацией.
- [Управление SSH-ключами в масштабных инфраструктурах](../../../../Linux/Security/ssh/server/ssh_key_management_at_scale.md) — LDAP/SSSD для SSH-ключей.
