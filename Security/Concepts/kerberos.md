# Kerberos — сетевая аутентификация

## Определение

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
*   **Hardening 2026:** KDC в современных средах (Windows Server 2025+, MIT Kerberos 1.21+) форсирует использование подписей `PAC_SHA2_CHECKSUM`. Билеты со старыми MD5/HMAC-SHA1 подписями PAC отклоняются для защиты от атак Privilege Escalation.

### Делегирование (Delegation)
Механизм, позволяющий промежуточному звену (например, веб-серверу) обращаться к бэкенду (БД) от имени клиента.
*   **Unconstrained Delegation:** Сервис получает копию TGT пользователя. Крайне небезопасно: при компрометации сервера атакующий получает полный доступ от имени всех пользователей. В 2026 году считается устаревшим (deprecated).
*   **Constrained Delegation (S4U2Self/S4U2Proxy):** Ограничивает список целевых сервисов, к которым можно обращаться.
*   **Resource-Based Constrained Delegation (RBCD):** Настройка прав делегирования на стороне целевого ресурса. Более гибкий и безопасный подход, стандарт для современных AD-инфраструктур.

### Защита Kerberos (FAST — Kerberos Armoring)
**FAST (Flexible Authentication Secure Tunneling)** создает защищенный канал между клиентом и KDC.
*   **Назначение:** Защищает `AS-REQ` и `AS-REP` от перехвата. Без FAST злоумышленник может перехватить `PA-ENC-TIMESTAMP` и выполнить офлайн-перебор пароля (AS-REP Roasting).
*   **Механизм:** Использует ключ компьютера (Armor Ticket) для шифрования обмена данными при получении пользовательского TGT.

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

## Дополнительная информация

### Технические особенности и безопасность

*   **Шифрование (Стандарты 2026):**
    *   **RFC 8009 (AES-SHA2):** Рекомендуется `aes256-cts-hmac-sha384-192`.
    *   **Депрекация RC4:** Алгоритм RC4 (`arcfour-hmac`) признан небезопасным (CVE-2026-20833). Большинство KDC в 2026 году блокируют его по умолчанию.
*   **Синхронизация времени:** Разница во времени не должна превышать 5 минут. Kerberos использует метки времени для защиты от атак повторного воспроизведения (Replay Attacks). Для синхронизации используйте [Chrony](../../Linux/Core/systemd/time_synchronization.md).
*   **Keytab Security:** Файлы keytab эквивалентны паролям в открытом виде. Права доступа должны быть `600`, владелец — только тот сервис, который его использует.
*   **MIT Kerberos vs Heimdal:** MIT-реализация доминирует в Linux-инфраструктурах (FreeIPA, RHEL IdM). Heimdal распространен в BSD-средах и имеет собственные расширения. Для AD-интеграции используйте MIT (совместимость с `sssd` и `realmd`).
*   **Хранение кэша:** В современном Linux предпочтителен тип кэша `KEYRING` или `KCM` (через SSSD), так как файловые кэши `/tmp/krb5cc_*` доступны для чтения всем процессам пользователя и остаются на диске после выхода.

### Логирование и диагностика

| Компонент | Лог-файл / Команда | Что искать |
| :--- | :--- | :--- |
| **KDC (MIT)** | `/var/log/krb5kdc.log` | Ошибки аутентификации, `Preauthentication failed`, `TGT renewal`. |
| **KDC (AD)** | Event Viewer → `Logon/Logoff` и `Kerberos` | Event ID 4768 (TGT issued), 4769 (service ticket), 4771 (preauth fail). |
| **SSSD** | `/var/log/sssd/sssd_<realm>.log` | Ошибки `LDAP`, `Kerberos`, `GSSAPI`. Используйте `sssctl domain-status`. |
| **SSH** | `journalctl -u sshd` | `GSSAPI` ошибки, `Authentication refused`. |

**Примеры диагностики:**
```bash
# Поиск ошибок Kerberos в логах SSSD
sudo grep -i "kerberos\|kinit\|preauth" /var/log/sssd/sssd_example.com.log

# Проверка доступности KDC через DNS
host -t SRV _kerberos._udp.example.com
# → _kerberos._udp.example.com has SRV record ...

# Проверка TCP-соединения с KDC
nc -zv kdc01.example.com 88
# → Connection succeeded

# Проверка времени с KDC
rpcinfo -p kdc01.example.com | grep 88
```

### Типовые ошибки и диагностика

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Clock skew too great** | Разница времени > 5 мин. | Синхронизировать время через NTP/Chrony. |
| **Preauthentication failed** | Неверный пароль или отсутствие FAST при строгой политике. | Проверить пароль; настроить FAST в `krb5.conf`. |
| **KDC_ERR_ETYPE_NOSUPP** | Несоответствие алгоритмов шифрования. | Обновить `krb5.conf`, убрать `allow_weak_crypto`. |
| **Decrypt integrity check failed** | Неверный пароль в keytab или несовпадение KVNO. | Перевыпустить keytab, проверить KVNO через `klist -kt` и `kvno principal`. |
| **Client not found** | Ошибка в имени принципала или Realm. | Проверить регистр (Realm ВСЕГДА в верхнем регистре). |
| **kinit: Cannot find KDC for realm** | DNS не настроен или KDC недоступен. | Проверить `/etc/resolv.conf`, SRV-записи и порт 88/TCP-UDP. |
| **klist: No credentials cache** | Билеты не получены или уничтожены. | Выполнить `kinit` или проверить `KRB5CCACHE`. |
| **kdestroy: Ticket cache not found** | Кэш уже удален или путь указан неверно. | Проверить переменную окружения `KRB5CCACHE`. |

### Связанные темы

- [Authentication vs Authorization](./authentication_vs_authorization.md) — различия процессов.
- [LDAP: Обзор](../../LDAP/389ds/overview.md) — хранилище для Kerberos-принципалов.
- [SSSD: Интеграция](../../Linux/SystemAdministration/Users/LDAP_SSSD/index.md) — основной агент аутентификации в Linux.
- [NFS: Безопасность](../../Linux/Networking/Services/nfs/nfs_security.md) — Kerberos для NFSv4 (RPCSEC_GSS).
- [Samba AD](../../Linux/Networking/Services/samba/samba_ad.md) — управление keytab и делегирование в AD.
- [Ansible Identity Management](../../Ansible/ansible-identity-management.md) — автоматизация ввода хостов в домен.
- [SSH: Аутентификация](../../Linux/Security/ssh/server/ssh_authentication.md) — GSSAPI и Kerberos в SSH.
- [Chrony](../../Linux/Core/systemd/time_synchronization.md) — синхронизация времени для Kerberos.
