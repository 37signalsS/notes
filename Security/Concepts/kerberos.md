# Kerberos — сетевая аутентификация

**Актуально для:** MIT Kerberos 1.21.x / Windows Server 2025

## Определения

**Kerberos** — протокол сетевой аутентификации, обеспечивающий SSO (Single Sign-On) и защищенную передачу данных через систему билетов и симметричное шифрование.

**Роль в экосистеме:**
*   **Сетевой аутентификатор:** в отличие от PAM, ориентированного на локальную проверку, Kerberos доказывает личность субъекта всей сети через доверенную третью сторону (KDC).
*   **Интеграция:** является фундаментом безопасности **Microsoft Active Directory** (через расширения MS-KILE). В Linux-системах интегрируется через `sssd` или `pam_krb5`.

## Основные концепции

### Ключевые термины

| Термин | Описание |
| :--- | :--- |
| **Principal** | Уникальный идентификатор в формате `primary[/instance]@REALM` (например, `admin/admin@EXAMPLE.COM`). |
| **Realm** | Область аутентификации (логическая группа), обычно в верхнем регистре (например, `EXAMPLE.COM`). |
| **Ticket** | Зашифрованный токен, подтверждающий идентичность владельца. Содержит сессионный ключ и время жизни. |
| **Authenticator** | Временная структура данных (метка времени), зашифрованная сессионным ключом. Используется однократно для предотвращения атак повтора. |
| **SPN (Service Principal Name)** | Идентификатор экземпляра службы в сети (например, `HTTP/web.example.com`). Используется клиентом для запроса билета к конкретному сервису. |
| **Keytab** | Файл, содержащий секретные ключи принципалов. Позволяет автоматизированным службам проходить аутентификацию без интерактивного ввода пароля. |
| **KVNO (Key Version Number)** | Номер версии ключа. При обновлении пароля принципала KVNO увеличивается. Несоответствие KVNO в билете и keytab — частая причина ошибок. |

### Реализации KDC

| Реализация | Платформа | Использование |
| :--- | :--- | :--- |
| **MIT Kerberos** | Linux/Unix | Стандарт de facto для Linux-инфраструктур (FreeIPA, standalone KDC). |
| **Heimdal** | BSD/Linux/macOS | Альтернативная реализация, распространена в OpenBSD и некоторых вендорских дистрибутивах. |
| **Microsoft KDC** | Windows Server | Встроенный KDC в Active Directory. Поддерживает расширения MS-KILE, PAC, delegation. |
| **Samba KDC** | Linux/Windows | Samba может выступать в роли AD DC с собственным Kerberos. |

### Типы кэша учетных данных (Credential Cache)

Kerberos хранит полученные билеты в кэше. Тип кэша определяется переменной окружения `KRB5CCACHE` или параметром `-c` в утилитах.

| Тип | Пример | Особенности |
| :--- | :--- | :--- |
| **FILE** | `FILE:/tmp/krb5cc_1000` | Классический файловый кэш. Доступен для чтения процессам под тем же пользователем. |
| **KEYRING** | `KEYRING:persistent:1000` | Использует kernel keyring (Linux key retention service). Более безопасен: не виден в файловой системе как временный файл. Рекомендуется для сервисов. |
| **KCM** | `KCM:1000` | Kerberos Credential Manager. Используется SSSD как бэкенд кэша. Поддерживает изоляцию между пользователями и контейнерами. |
| **DIR** | `DIR:/var/tmp/krb5cc_1000` | Каталог с файлами кэша. Используется в многопользовательских серверных средах. |

**Проверка типа кэша:**
```bash
echo $KRB5CCACHE
# → KCM:1000
```

### Компоненты инфраструктуры

*   **Client:** Субъект (пользователь или хост), запрашивающий доступ.
*   **KDC (Key Distribution Center):** Центр распределения ключей. Состоит из:
    *   **AS (Authentication Server):** Обрабатывает первичные запросы, выдает TGT.
    *   **TGS (Ticket Granting Server):** Обменивает TGT на сервисные билеты.
*   **SS (Service Server):** Конечный ресурс, принимающий сервисный билет от клиента.

### Процесс аутентификации (Шаги)

1.  **Запрос TGT (AS Request):**
    - Клиент отправляет запрос к AS (включает временную метку, зашифрованную своим ключом — Pre-authentication).
    - AS возвращает **TGT** (зашифрован ключом TGS) и **Session Key** (зашифрован ключом клиента).
2.  **Запрос сервисного билета (TGS Request):**
    - Клиент отправляет к TGS свой TGT и аутентификатор.
    - TGS возвращает **Service Ticket** (зашифрован ключом сервиса) и новый сессионный ключ для связи с сервисом.
3.  **Доступ к ресурсу (AP Request):**
    - Клиент отправляет сервисный билет и аутентификатор к SS.
    - SS расшифровывает билет своим ключом, проверяет аутентификатор и предоставляет доступ.

### Флаги билетов (Ticket Flags)

При просмотре билетов через `klist` можно увидеть флаги, определяющие их возможности:
*   **F (Forwardable):** Билет может быть обменян на новый TGT для использования на другом хосте.
*   **R (Renewable):** Срок жизни билета может быть продлен без повторного ввода пароля (до лимита `renew_until`).
*   **P (Proxyable):** Позволяет сервису запрашивать билеты для других сервисов от имени пользователя.
*   **A (Pre-authenticated):** Подтверждает, что клиент прошел предварительную проверку подлинности.
*   **D (Post-dated):** Билет действителен только после указанной даты. Используется для отложенных задач.

## Расширенные механизмы

### Расширения MS-KILE и сертификат PAC (Privilege Attribute Certificate)
Microsoft расширила стандартный протокол (RFC 4120) для интеграции с Active Directory.
*   **PAC:** Дополнительное поле в билете, содержащее SID пользователя и список его групп. Позволяет сервису сразу определить права доступа без дополнительного запроса к контроллеру домена.
*   **Hardening 2026:** KDC в современных средах (Windows Server 2025+, MIT Kerberos 1.21+) форсируют использование усиленных подписей PAC. MIT Kerberos 1.21+ добавляет `KRB5_PAC_FULL_CHECKSUM` (тип 19) — полный чексуммный буфер KDC над всем содержимым PAC для защиты от атак коллизий (CVE-2022-37967). Windows Server 2025+ требует SHA2-подписи в PAC. Билеты со старыми MD5/HMAC-SHA1 подписями PAC отклоняются для защиты от атак Privilege Escalation.

### Делегирование (Delegation)
Механизм, позволяющий промежуточному звену (например, веб-серверу) обращаться к бэкенду (БД) от имени клиента.
*   **Unconstrained Delegation:** Сервис получает копию TGT пользователя. Крайне небезопасно: при компрометации сервера атакующий получает полный доступ от имени всех пользователей. В 2026 году считается устаревшим (deprecated).
*   **Constrained Delegation (S4U2Self/S4U2Proxy):** Ограничивает список целевых сервисов, к которым можно обращаться.
*   **Resource-Based Constrained Delegation (RBCD):** Настройка прав делегирования на стороне целевого ресурса. Более гибкий и безопасный подход, стандарт для современных AD-инфраструктур.

### Защита Kerberos (FAST — Kerberos Armoring)
**FAST (Flexible Authentication Secure Tunneling)** создает защищенный канал между клиентом и KDC.
*   **Назначение:** Защищает `AS-REQ` и `AS-REP` от перехвата. Без FAST злоумышленник может перехватить `PA-ENC-TIMESTAMP` и выполнить офлайн-перебор пароля (AS-REP Roasting).
*   **Механизм:** Использует ключ компьютера (Armor Ticket) для шифрования обмена данными при получении пользовательского TGT.

## Установка и настройка

### Установка MIT Kerberos KDC

**Debian/Ubuntu:**
```bash
sudo apt update
sudo apt install krb5-kdc krb5-admin-server krb5-config
```

**RHEL/Fedora:**
```bash
sudo dnf install krb5-server krb5-workstation
```

Пакет `krb5-config` (Debian) или `authconfig` (RHEL) запускает интерактивный мастер, который создаёт `/etc/krb5.conf` и `kdc.conf`. Для автоматизации используйте [Ansible Identity Management](../../Ansible/ansible-identity-management.md).

### Конфигурация kdc.conf

Файл `kdc.conf` определяет параметры KDC (в отличие от `krb5.conf`, который настраивает клиентские библиотеки). Расположение: `/etc/krb5kdc/kdc.conf` (Debian) или `/var/kerberos/krb5kdc/kdc.conf` (RHEL).

```ini
[kdcdefaults]
    kdc_ports = 88,750
    kdc_tcp_ports = 88

[realms]
    EXAMPLE.COM = {
        # Управление БД
        database_name = /var/lib/krb5kdc/principal
        admin_keytab = FILE:/etc/krb5kdc/kadm5.keytab
        acl_file = /etc/krb5kdc/kadm5.acl
        key_stash_file = /etc/krb5kdc/.k5EXAMPLE.COM

        # Параметры билетов
        max_life = 12h 0m 0s
        max_renewable_life = 7d 0m 0s

        # Шифрование (2026: только AES-SHA2, отказ от RC4/MD5/3DES)
        master_key_type = aes256-cts-hmac-sha1-96
        supported_enctypes = aes256-cts-hmac-sha384-192:normal aes128-cts-hmac-sha256-128:normal aes256-cts-hmac-sha1-96:normal aes128-cts-hmac-sha1-96:normal
        allow_rc4 = false
        allow_des3 = false

        # Порты
        kadmind_port = 749

        # PKINIT (опционально)
        pkinit_identity = FILE:/etc/krb5kdc/kdccert.pem,/etc/krb5kdc/kdckey.pem
        pkinit_anchors = FILE:/etc/krb5/cacert.pem
    }

[logging]
    kdc = FILE:/var/log/krb5kdc/kdc.log
    admin_server = FILE:/var/log/krb5kdc/kadmin.log
    default = SYSLOG:INFO
```

> **Примечание:** `allow_rc4 = false` и `allow_des3 = false` встроены как defaults в MIT Kerberos 1.21+, но указываются явно для наглядности политики безопасности.

### Создание базы данных Kerberos

```bash
# Создание БД с stash-файлом (автоматический доступ к master key)
sudo kdb5_util create -s -r EXAMPLE.COM
# → Enter KDC database master key:
# → Verify KDC database master key:
# → # KDC database successfully created
```

### Настройка kadm5.acl

Файл `/etc/krb5kdc/kadm5.acl` управляет правами администрирования. Формат: `principal  permissions  [target_principal  [restrictions]]`. Флаги: `a` (all), `l` (list), `i` (inquiries), `p` (post — смена пароля), `t` (policy), `k` (key extraction — `ktadd`/`k5srvutil`). Буквы в верхнем регистре запрещают операцию.

```text
# Разрешить всем пользователям в группе admin/* полный доступ
*/admin@EXAMPLE.COM    *

# Разрешить replica KDC извлекать ключи
host/kdc02.example.com@EXAMPLE.COM ki
```

### Управление службами

```bash
# Запуск и автозапуск
sudo systemctl enable --now krb5-kdc krb5-admin-server

# Проверка статуса
sudo systemctl status krb5-kdc
# → Active: active (running)
```

### Высокая доступность (Primary/Replica KDC)

Для production-сред развертывайте несколько KDC:
- **Primary KDC** — единственный с writable БД, обрабатывает изменения (addprinc, cpw)
- **Replica KDC** — read-only копии, обслуживают TGT/TGS при недоступности primary

```bash
# На primary KDC: создание host-принципала для реплики
sudo kadmin.local -q "addprinc -randkey host/kdc02.example.com"

# Извлечение keytab и передача на реплику (через защищённый канал)
sudo kadmin.local -q "ktadd -k /tmp/host.keytab host/kdc02.example.com"

# Создание dump-файла БД
sudo kdb5_util dump /var/lib/krb5kdc/replica_datatrans

# На реплике: настройка kpropd.acl
echo "host/kdc01.example.com@EXAMPLE.COM" | sudo tee /etc/krb5kdc/kpropd.acl

# Запуск kpropd на реплике (stand-alone mode для инкрементной репликации)
sudo systemctl enable --now kpropd

# Cron на primary для периодической репликации:
# 0,15,30,45 * * * * root kdb5_util dump /var/lib/krb5kdc/replica_datatrans && kprop -f /var/lib/krb5kdc/replica_datatrans kdc02.example.com
```

### Конфигурация клиентов

Клиенты требуют только `/etc/krb5.conf` и синхронизацию времени:

```bash
# Debian/Ubuntu
sudo apt install krb5-user libpam-krb5

# RHEL/Fedora
sudo dnf install krb5-workstation
```

SRV-записи DNS автоматически обнаруживают KDC:
```bash
host -t SRV _kerberos._tcp.EXAMPLE.COM
# → _kerberos._tcp.EXAMPLE.COM has SRV record 0 100 88 kdc01.example.com.
```

## Практические сценарии

### Конфигурация krb5.conf
Основной файл конфигурации в Linux: `/etc/krb5.conf`.

```ini
[libdefaults]
    default_realm = EXAMPLE.COM
    # Рекомендация 2026: полный отказ от слабых алгоритмов (DES, RC4)
    default_tkt_enctypes = aes256-cts-hmac-sha384-192 aes256-cts-hmac-sha1-96
    default_tgs_enctypes = aes256-cts-hmac-sha384-192 aes256-cts-hmac-sha1-96
    permitted_enctypes = aes256-cts-hmac-sha384-192 aes256-cts-hmac-sha1-96
    
    # Форсировать TCP (рекомендуется для больших PAC, которые не влезают в UDP)
    udp_preference_limit = 1 
    
    # Автоматическое обновление билетов SSSD
    renew_lifetime = 7d

[realms]
    EXAMPLE.COM = {
        kdc = kdc01.example.com
        admin_server = kdc01.example.com
    }
```

#### Дополнительные параметры krb5.conf

```ini
[libdefaults]
    dns_lookup_realm = false
    dns_lookup_kdc = true
    ticket_lifetime = 24h
    renew_lifetime = 7d
    forwardable = true
    rdns = false
    default_ccache_name = KCM:1000

[realms]
    EXAMPLE.COM = {
        kdc = kdc01.example.com
        kdc = kdc02.example.com
        admin_server = kdc01.example.com
    }

[domain_realm]
    .example.com = EXAMPLE.COM
    example.com = EXAMPLE.COM
```

### Управление билетами и Keytab в CLI

**1. Получение билета (Аутентификация):**
```bash
kinit username@EXAMPLE.COM
```

**2. Просмотр текущих билетов и их флагов:**
```bash
klist -e -f
# Default principal: username@EXAMPLE.COM
#
# Valid starting       Expires              Service principal
# 12/08/2026 10:00:00  12/08/2026 20:00:00  krbtgt/EXAMPLE.COM@EXAMPLE.COM
#         Flags: FRI A, Etype: aes256-cts-hmac-sha384-192
```

**3. Получение билета с использованием keytab (для сервисов):**
```bash
kinit -k -t /etc/krb5.keytab host/server.example.com@EXAMPLE.COM
```

**4. Запрос конкретного сервисного билета и проверка KVNO:**
```bash
kinit -k -t /etc/krb5.keytab HTTP/web.example.com@EXAMPLE.COM
kvno HTTP/web.example.com
# → HTTP/web.example.com@EXAMPLE.COM: kvno = 2
```

**5. Просмотр всех доступных кэшей билетов:**
```bash
klist -l
# → Cache name: KCM:1000
# → Principal: username@EXAMPLE.COM
```

**6. Уничтожение билетов (выход из сессии):**
```bash
kdestroy
# → Ticket cache FILE:/tmp/krb5cc_1000 destroyed
```

**7. Переключение между кэшами:**
```bash
kswitch -c /tmp/krb5cc_1000
```

**8. Работа с Keytab (ktutil):**
Проверка содержимого keytab без аутентификации:
```bash
ktutil
ktutil: read_kt /etc/krb5.keytab
ktutil: list
# slot KVNO Principal
# ---- ---- ---------------------------------------------------------------------
#    1    2 host/server.example.com@EXAMPLE.COM
```

Создание keytab вручную (для отладки):
```bash
ktutil
ktutil: addent -password -p username@EXAMPLE.COM -k 1 -e aes256-cts-hmac-sha384-192
ktutil: wkt /tmp/my.keytab
ktutil: quit
```

### Управление принципалами на KDC (kadmin.local)

На стороне центра распределения ключей (KDC) используется `kadmin.local` (локально) или `kadmin` (по сети, требует TLS).

```bash
# Создание принципала с случайным ключом (для сервисов)
sudo kadmin.local -q "addprinc -randkey host/server.example.com"

# Создание принципала с паролем (для пользователей)
sudo kadmin.local -q "addprinc username"

# Изменение пароля принципала
sudo kadmin.local -q "cpw username"

# Добавление ключей в существующий keytab
sudo kadmin.local -q "ktadd -k /etc/krb5.keytab host/server.example.com"

# Удаление принципала
sudo kadmin.local -q "delprinc -force username"

# Просмотр списка принципалов
sudo kadmin.local -q "listprincs"
```

### Смена пароля через Kerberos (kpasswd)

Пользователь может сменить свой пароль без доступа к LDAP/AD-инструментам:

```bash
kpasswd username@EXAMPLE.COM
# → New password:
# → Verify password:
```

### Интеграция с Active Directory (realmd / adcli)

В Linux-средах с AD вход в домен и управление computer account автоматизируется через `realmd` и `adcli`. Подробнее см. [Ansible Identity Management](../../Ansible/ansible-identity-management.md) и [Интеграция SSSD с AD](../../Linux/SystemAdministration/Users/LDAP_SSSD/ad_integration.md).

```bash
# Обнаружение параметров домена
realm discover example.com
# → realm-name: EXAMPLE.COM
# → domain-name: example.com
# → server-software: active-directory
# → client-software: sssd

# Присоединение к домену
sudo realm join example.com -U Administrator

# Проверка статуса
realm list

# Выход из домена
sudo realm leave example.com

# Сброс пароля компьютера (обновление keytab)
sudo adcli update --computer-name=$(hostname) --reset-password
sudo klist -kt /etc/krb5.keytab
```

### SSH и GSSAPI

SSH может использовать Kerberos для аутентификации без передачи пароля (GSSAPI). Подробнее о hardening SSH см. [SSH: Аутентификация](../../Linux/Security/ssh/server/ssh_authentication.md).

**На сервере (`/etc/ssh/sshd_config`):**
```ini
GSSAPIAuthentication yes
GSSAPICleanupCredentials yes
```

**На клиенте (`~/.ssh/config` или `/etc/ssh/ssh_config`):**
```ini
Host *.example.com
    GSSAPIAuthentication yes
    GSSAPIDelegateCredentials yes
```

**Проверка:**
```bash
ssh -vvv server.example.com
# → debug1: Authentication succeeded (GSSAPI).
```

> **Важно:** Если KDC недоступен, SSH по умолчанию ждет таймаут GSSAPI перед попыткой других методов. В конфигурации сервера можно отключить GSSAPI, если домен не используется:
> `GSSAPIAuthentication no`

## Устранение неполадок

### Логирование и диагностика

Конфигурация логирования задаётся в `kdc.conf` секции `[logging]`. По умолчанию:
- Debian/Ubuntu: `SYSLOG` или `FILE:/var/log/krb5kdc/kdc.log`
- RHEL/Fedora: `FILE:/var/log/krb5kdc/kdc.log`

| Компонент | Лог-файл / Команда | Что искать |
| :--- | :--- | :--- |
| **KDC (MIT)** | `/var/log/krb5kdc/kdc.log` или `journalctl -u krb5-kdc` | `Preauthentication failed`, `Client not found`, `Etype` ошибки. |
| **KDC (AD)** | Event Viewer → `Конечные точки Kerberos` | Event ID 4768 (TGT issued), 4769 (service ticket), 4771 (preauth fail). |
| **kadmind (MIT)** | `journalctl -u krb5-admin-server` или `FILE:/var/log/krb5kdc/kadmin.log` | `Authorization rejected`, `No permission`. |
| **SSSD** | `/var/log/sssd/sssd_<realm>.log` | Ошибки `LDAP`, `Kerberos`, `GSSAPI`. Используйте `sssctl domain-status`. |
| **SSH** | `journalctl -u sshd` | `GSSAPI` ошибки, `Authentication refused`. |

**Примеры диагностики:**
```bash
# Поиск ошибок Kerberos в логах KDC
sudo grep -i "preauth\|etype\|decrypt" /var/log/krb5kdc/kdc.log

# Поиск ошибок Kerberos в логах SSSD
sudo grep -i "kerberos\|kinit\|preauth" /var/log/sssd/sssd_example.com.log

# Проверка доступности KDC через DNS
host -t SRV _kerberos._udp.example.com
# → _kerberos._udp.example.com has SRV record ...

# Проверка TCP-соединения с KDC
nc -zv kdc01.example.com 88
# → Connection succeeded

# Проверка синхронизации времени
chronyc tracking
# → System time: 0.000000000 seconds slow of NTP time
```

### Типовые ошибки и диагностика

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Clock skew too great** | Разница времени > 5 мин. | Синхронизировать через [Chrony](../../Linux/Core/systemd/time_synchronization.md) или `chronyd -Q`. |
| **Preauthentication failed** | Неверный пароль или отсутствие FAST при строгой политике. | Проверить пароль; настроить FAST в `krb5.conf`. |
| **KDC_ERR_ETYPE_NOSUPP** | Несоответствие алгоритмов шифрования на клиенте и KDC. | Обновить `krb5.conf`, убрать `allow_weak_crypto`. |
| **Decrypt integrity check failed** | Неверный пароль в keytab или несовпадение KVNO. | Перевыпустить keytab; проверить KVNO через `klist -kt` и `kvno principal`. |
| **Client not found** | Ошибка в имени принципала или Realm. | Проверить регистр (Realm ВСЕГДА в верхнем регистре). |
| **kinit: Cannot find KDC for realm** | DNS не настроен или KDC недоступен. | Проверить `/etc/resolv.conf`, SRV-записи и порт 88/TCP-UDP. |
| **klist: No credentials cache** | Билеты не получены или уничтожены. | Выполнить `kinit` или проверить `KRB5CCACHE`. |
| **kdestroy: Ticket cache not found** | Кэш уже удален или путь указан неверно. | Проверить переменную окружения `KRB5CCACHE`. |
| **AS-REP Roasting** | KDC выдаёт ошибку PreauthRequired:false, позволяя перебор. | Включить FAST в `krb5.conf`; настроить `kdc_tcp_ports` и `addrs` в `kdc.conf`. |

## Лучшие практики

### Технические особенности и безопасность

*   **Шифрование (Стандарты 2026):**
    *   **RFC 8009 (AES-SHA2):** Рекомендуется `aes256-cts-hmac-sha384-192` (etype 20).
    *   **Депрекация RC4:** Алгоритм RC4 (`arcfour-hmac`) признан небезопасным (CVE-2026-20833). MIT Kerberos 1.21+ и Windows Server 2025 блокируют его по умолчанию через `allow_rc4 = false`.
    *   **Депрекация DES/3DES:** Полностью отключены в MIT Kerberos 1.21+ через `allow_des3 = false`.
*   **Синхронизация времени:** Разница во времени не должна превышать 5 минут. Kerberos использует метки времени для защиты от атак повторного воспроизведения (Replay Attacks). Для синхронизации используйте [Chrony](../../Linux/Core/systemd/time_synchronization.md).
*   **Keytab Security:** Файлы keytab эквивалентны паролям в открытом виде. Права доступа должны быть `600`, владелец — только тот сервис, который его использует. Периодически ротируйте keytab через `ktadd` с увеличением KVNO.
*   **MIT Kerberos vs Heimdal:** MIT-реализация доминирует в Linux-инфраструктурах (FreeIPA, RHEL IdM). Heimdal распространен в BSD-средах и имеет собственные расширения. Для AD-интеграции используйте MIT (совместимость с `sssd` и `realmd`).
*   **Хранение кэша:** В современном Linux предпочтителен тип кэша `KEYRING` или `KCM` (через SSSD), так как файловые кэши `/tmp/krb5cc_*` доступны для чтения всем процессам пользователя и остаются на диске после выхода.
*   **Ограничение делегирования:** Unconstrained Delegation считается устаревшим (deprecated) — заменяйте на RBCD или Constrained Delegation.

### Мониторинг и алёртинг (SRE)

KDC — критически важная инфраструктурная служба. Её недоступность парализует аутентификацию во всей сети.

**Мониторинг доступности:**
```bash
# Синтетическая проверка: получение TGT через keytab
kinit -k -t /etc/krb5.keytab host/monitoring@EXAMPLE.COM && klist && kdestroy

# Проверка порта KDC
nc -z -w5 kdc01.example.com 88 && nc -z -w5 kdc01.example.com 749
```

**Prometheus exporter** — [camptocamp/prometheus-kerberos-exporter](https://github.com/camptocamp/prometheus-kerberos-exporter) экспортирует метрики доступности KDC:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'kerberos'
    static_configs:
      - targets: ['kdc-exporter:9259']
```

**Ключевые метрики для алёртинга:**
| Метрика | Порог | Описание |
| :--- | :--- | :--- |
| `kerberos_status_available` | `== 0` | KDC недоступен — Critical |
| Auth failure rate (из логов) | `> 10%` | Возможна атака (brute force / roasting) |
| `kdc` replica lag | `> 15мин` | Репликация БД отстаёт — Warning |
| Time sync offset | `> 2сек` | Clock skew → отказ аутентификации |

```yaml
# alerts.yml (пример)
groups:
- name: kerberos
  rules:
  - alert: KerberosKDCUnavailable
    expr: kerberos_status_available == 0
    for: 1m
    labels: {severity: critical}
  - alert: KerberosHighFailureRate
    expr: rate(krb5_preauth_failures[5m]) > 0.1
    for: 5m
    labels: {severity: critical}
```

**Мониторинг времени** — критично для Kerberos:
```bash
chronyc sources -v
# → проверить смещение < ±2 секунд для всех KDC
```

### Управление keytab и backup

**Ротация keytab для сервисов:**
```bash
# 1. Увеличить KVNO и добавить новый ключ
sudo kadmin.local -q "ktadd -k /tmp/new.keytab -w 2 HTTP/web.example.com"

# 2. Атомарная замена (перевод сервиса на новый keytab)
sudo mv /tmp/new.keytab /etc/krb5.keytab
sudo chown root:root /etc/krb5.keytab
sudo chmod 600 /etc/krb5.keytab
# → Перезапустить сервис для перечитывания keytab
```

**Backup базы данных KDC:**
```bash
# Дамп БД с encrypted seeds
sudo kdb5_util dump -f kdb_dump -o /var/backups/krb5kdc_dump_$(date +%F).enc

# Хранить зашифрованным (GPG/AES). Stash-файл также нужно backupить отдельно.
```

**Автоматизация через Ansible** — см. [Ansible Identity Management](../../Ansible/ansible-identity-management.md) для паттернов управления принципалами и keytab через роли `ipaclient`/`krb5_server`.

## Дополнительная информация

### Технические стандарты

*   **RFC 4120** — Kerberos Network Authentication Service (v5), базовый протокол.
*   **RFC 8009** — AES-CTS HMAC-SHA2 encryption types (`aes128-cts-hmac-sha256-128`, `aes256-cts-hmac-sha384-192`).
*   **RFC 4537** — Kerberos encryption algorithm negotiation.
*   **RFC 6806** — Kerberos localization interface.
*   **MS-KILE** — Microsoft Kerberos Protocol Extensions (PAC, constrained delegation).
*   **MS-PKCA** — Microsoft Public Key Cryptography for Kerberos (PKINIT).

### Связанные темы

- [Authentication vs Authorization](./authentication_vs_authorization.md) — различия процессов.
- [LDAP: Обзор](../../LDAP/389ds/overview.md) — хранилище для Kerberos-принципалов.
- [SSSD: Интеграция](../../Linux/SystemAdministration/Users/LDAP_SSSD/index.md) — основной агент аутентификации в Linux.
- [NFS: Безопасность](../../Linux/Networking/Services/nfs/nfs_security.md) — Kerberos для NFSv4 (RPCSEC_GSS).
- [Samba AD](../../Linux/Networking/Services/samba/samba_ad.md) — управление keytab и делегирование в AD.
- [Ansible Identity Management](../../Ansible/ansible-identity-management.md) — автоматизация ввода хостов в домен.
- [SSH: Аутентификация](../../Linux/Security/ssh/server/ssh_authentication.md) — GSSAPI и Kerberos в SSH.
- [Chrony](../../Linux/Core/systemd/time_synchronization.md) — синхронизация времени для Kerberos.
