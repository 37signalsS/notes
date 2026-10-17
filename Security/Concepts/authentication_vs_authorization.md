# Аутентификация против Авторизации

> **Актуально для:** Linux (systemd 256+, PAM 1.7+, sudo 1.9+), OpenSSH 10.x, LDAP/LDAPS, Kerberos 5, OAuth 2.1, OIDC, SAML 2.0

## Определения

В контексте системной безопасности **аутентификация** и **авторизация** — это два фундаментальных и взаимосвязанных, но принципиально разных процесса.

- **Аутентификация (Authentication)** отвечает на вопрос: «**Кто вы?**» (установление подлинности).
- **Авторизация (Authorization)** отвечает на вопрос: «**Что вам разрешено?**» (определение прав доступа).

## Основные концепции

### Аутентификация

- **Цель:** подтверждение заявленной личности пользователя или сервиса.
- **Факторы:** то, что вы знаете (пароль), то, что у вас есть (токен), или то, чем вы являетесь (биометрия).
- **Результат:** установление идентичности (Identity).
- **Механизмы:** логин/пароль, [MFA/TOTP](./mfa_totp.md), [Kerberos](./kerberos.md), X.509-сертификаты ([PKI](./pki_overview.md)), SSH-ключи.

### Авторизация

- **Цель:** ограничение доступа к ресурсам и действиям на основе установленной личности.
- **Механизмы:** роли ([RBAC](../../Kubernetes/Security/rbac/rbac_overview.md)), списки доступа (ACL), атрибуты (ABAC).
- **Результат:** разрешение (`Allow`) или отказ (`Deny`) в доступе.
- **Протоколы:** [OAuth 2.1](./oauth2_overview.md) (делегирование авторизации).

### Модели контроля доступа

Существует несколько базовых моделей, определяющих, как права связываются с субъектами и ресурсами:

| Модель | Описание | Где применяется |
| :--- | :--- | :--- |
| **DAC (Discretionary)** | Владелец ресурса сам решает, кто может получить доступ. Права назначаются через классические права Unix (`chmod`). | Локальные файлы в Linux, общие папки |
| **MAC (Mandatory)** | Доступ определяется глобальной политикой безопасности, enforced ядром или политическим модулем (SELinux, AppArmor). | Военные/гос. системы, контейнеры, защищённые серверы |
| **RBAC (Role-Based)** | Права связываются с ролями, роли — с пользователями. Масштабируется лучше DAC. | Linux sudo, Kubernetes, Vault, большинство корпоративных систем |
| **ABAC (Attribute-Based)** | Решения принимаются на основе атрибутов субъекта, ресурса, действия и окружения (время, IP, MFA). | Dynamic policies, Zero Trust, Vault Sentinel, OPA/Gatekeeper |

В Linux все три модели (`DAC` через права, `ACL` как расширение DAC, `MAC` через `selinux/apparmor`, `RBAC` через `sudo`) могут работать одновременно. Их взаимодействие определяется иерархией: **MAC > POSIX ACL > DAC**. Детали см. в разделах **[Управление привилегиями](../../Linux/SystemAdministration/privilege_management.md)** и **[ACL и атрибуты](../../Linux/Security/Concepts/File_Permissions/acl_immutable_timestamps.md)**.

### Сводная таблица различий

| Характеристика | Аутентификация | Авторизация |
| :--- | :--- | :--- |
| **Ключевой вопрос** | Кто вы? | Что вам можно? |
| **Порядок выполнения** | Всегда первая | Всегда после аутентификации |
| **Передача данных** | Через формы входа, ID-токены | Через Access-токены, сессии |
| **Пример** | Ввод PIN-кода на смартфоне | Доступ к приложению после разблокировки |

### Почему их путают

- Оба процесса часто происходят рядом и могут использовать один и тот же токен.
- В интерфейсах инструментов (Postman и аналоги) всё лежит во вкладке `Authorization`.
- HTTP-заголовок называется `Authorization`, хотя в нём часто передают credentials именно для аутентификации.

Последовательность различается на практике так:

1. **Identification:** «Я — alice@example.com» (заявление личности).
2. **Authentication:** «Вот пароль / токен / ключ, который это доказывает».
3. **Authorization:** «Alice может читать заказы, но не может удалять пользователей».

### Уровни концепций аутентификации

Basic Auth, API Key, Bearer Token, JWT, Session-based auth, OAuth 2.1 и OpenID Connect нельзя складывать в один список как равнозначные «виды аутентификации» — это сущности разных уровней:

| Уровень | Примеры |
| :--- | :--- |
| HTTP-схема передачи credentials | Basic, Bearer |
| Credential / секрет / идентификатор доступа | password, API key, access token, session id |
| Формат токена | JWT |
| Модель хранения состояния входа | session-based auth |
| Фреймворк делегированного доступа | OAuth 2.1 |
| Identity layer поверх OAuth 2.1 | OpenID Connect |

Типичная ошибка — смотреть на список методов в инструменте и считать Basic Auth, Bearer Token, JWT, API Key и OAuth 2.1 одним типом сущностей. Сначала определяется уровень термина, и только потом сравниваются плюсы, минусы и сценарии применения.

### Credentials

Credentials — данные, с помощью которых клиент доказывает системе личность, право доступа или владение секретом. Это не всегда пароль:

| Credential | Что доказывает |
| :--- | :--- |
| username + password | Пользователь знает пароль. |
| API key | Клиент владеет выданным ключом. |
| access token | Клиент получил право обращаться к ресурсу. |
| session id | У клиента есть активная серверная сессия. |
| client secret | Приложение знает секрет клиента. |
| SSH key | Клиент владеет приватным ключом, соответствующим доверенному публичному ключу. |
| service account token | Машинная рабочая нагрузка удостоверена платформой. |
| FIDO2/U2F security key | Физический токен (YubiKey, Nitrokey) доказывает владение аппаратным устройством. |

### Типичные смешения понятий

| Пара | В чем разница |
| :--- | :--- |
| Bearer и JWT | Bearer говорит, *как передаётся* токен; JWT — *как он устроен внутри*. Bearer-токен может быть JWT, но не обязан — это может быть opaque token (случайная строка без claims). |
| JWT и авторизация | JWT — формат токена, а не протокол авторизации; авторизация может использовать claims из JWT. Корректная формулировка: «Bearer authentication с JWT access token». |
| JWT и OAuth 2.1 | JWT — формат токена; OAuth 2.1 — фреймворк получения и использования access token для делегированного доступа. |
| OAuth 2.1 и OpenID Connect | OAuth 2.1 сам по себе не даёт стандартного способа сообщить приложению, кто пользователь; OIDC добавляет identity-слой и ID token. |
| Session id и access token | Session id — ключ к серверной сессии; access token — credential для доступа к защищённому ресурсу. |
| API key и пользовательский логин | API key идентифицирует приложение/интеграцию/технического клиента; логин идентифицирует человека. |

## Архитектура: конвейер аутентификации и авторизации в Linux

Процесс входа и выдачи прав в Linux состоит из нескольких узлов, каждый из которых отвечает за свою задачу. Ниже — типичный конвейер для интерактивного входа по SSH с локальной авторизацией команд:

```text
Клиент (ssh)                 →  sshd                 →  PAM
  SSH-ключ / сертификат          auth-модуль (pam_sss/pam_unix)
                                   ↓
                          account-модуль (pam_sss)   →  NSS (files → sssd → LDAP)
                                   ↓
                            Session-модуль           →  /etc/security/limits.conf
                                   ↓
                                  Shell               →  sudo / polkit
                                   ↓
                          Команда (systemctl ...)   →  systemd / RBAC
```

1. **Идентификация:** пользователь сообщает имя (`alice`).
2. **Аутентификация:** PAM проверяет credentials (хэш пароля из `/etc/shadow`, SSH-ключ, TOTP через `pam_google_authenticator.so`, сертификат Kerberos).
3. **Разрешение сессии:** PAM `account`-модуль проверяет срок действия учётной записи, а `session`-модуль применяет `pam_limits.so` и монтирует home-директорию.
4. **Авторизация действий:** при вызове `sudo` или `pkexec` выполняется проверка прав через `/etc/sudoers` или Polkit-правила.

Для сервисных (машинных) учётных записей конвейер упрощается — аутентификация происходит по service account token или сертификату, а авторизация через RBAC (Kubernetes) или роли (Vault). Подробнее в разделе **«Управление сервисными аккаунтами»** ниже.

## Локальная аутентификация и авторизация в Linux

На уровне операционной системы аутентификация и авторизация реализуются через несколько взаимосвязанных компонентов:

### NSS (Name Service Switch)

**NSS** — механизм диспетчеризации в glibc, определяющий порядок поиска данных о пользователях и группах. Конфигурируется в `/etc/nsswitch.conf`:

```text
passwd:         files sssd
group:          files sssd
shadow:         files
```

При запросе `id alice` система обращается к NSS, которая по порядку проверяет локальные файлы (`/etc/passwd`, `/etc/group`) и, при отсутствии, внешние источники (SSSD → LDAP/AD). Подробнее: **[Управление пользователями в Linux](../../Linux/SystemAdministration/users_management.md)**.

### PAM (Pluggable Authentication Modules)

**PAM** — модульный фреймворк, который разделяет приложения (login, sshd, sudo) от методов проверки подлинности. Приложение вызывает PAM-функции, а PAM выполняет стек модулей, настроенных в `/etc/pam.d/<service>`.

Четыре типа модулей:

| Тип | Назначение |
| :--- | :--- |
| `auth` | Проверка подлинности (пароль, токен, биометрия) |
| `account` | Проверка правил учётной записи (срок действия, время доступа) |
| `session` | Действия до/после доступа (логирование, монтирование home) |
| `password` | Управление паролями (сложность, обновление) |

**Пример конфигурации `/etc/pam.d/sshd` (Debian/Ubuntu):**
```text
auth       include   system-login
@include common-auth
@include common-account
@include common-session
```

Часто используемые модули:
- `pam_unix.so` — локальная проверка пароля через `/etc/shadow`
- `pam_faillock.so` — блокировка после N неудачных попыток (замена `pam_tally2`)
- `pam_sss.so` — аутентификация через SSSD/LDAP
- `pam_google_authenticator.so` — MFA/TOTP
- `pam_u2f.so` / `pam_fido2.so` — аппаратные токены FIDO2/U2F (YubiKey, Nitrokey)
- `pam_access.so` — доступ по IP/хосту через `/etc/security/access.conf`

Полное описание PAM, контрольные флаги и расширенный синтаксис: **[PAM — обзор](../../Linux/Security/pam_overview.md)**.

### Локальные файлы авторизации

Права доступа в Linux основаны на UID/GID и классической триаде:

| Файл | Назначение |
| :--- | :--- |
| `/etc/passwd` | UID, GID, домашняя директория, shell |
| `/etc/group` | Группы и их члены |
| `/etc/shadow` | Хэши паролей, сроки действия (поля `sp_max`, `sp_min`, `sp_warn`, `sp_expire`) |
| `/etc/sudoers` | Правила делегирования привилегий |
| `/etc/sudoers.d/` | Дополнительные файлы правил |

Права на критичные файлы:
```bash
sudo chmod 644 /etc/passwd
sudo chmod 600 /etc/shadow
sudo chown root:root /etc/passwd /etc/shadow /etc/group
```

### sudo и Polkit

**sudo** — основной инструмент делегирования привилегий в Linux. Требует пароль текущего пользователя, логирует все команды в syslog/journald:

```bash
# Выполнение одной команды
sudo systemctl restart nginx

# Просмотр прав текущего пользователя
sudo -l

# Редактирование sudoers через безопасный редактор
sudo visudo
```

**Файл `/etc/sudoers` — ключевые директивы:**
```text
# Разрешить группе wheel без пароля для systemctl
%wheel ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *

# Prevents root from running sudo itself (root is already root)
Defaults !root_sudo

# Требовать TTY
Defaults requiretty

# Логирование
Defaults logfile="/var/log/sudo.log"
Defaults log_input, log_output
Defaults iolog_dir=/var/log/sudo-io
```

**Алиасы для масштабирования:**
```text
User_Alias  ADMINS = jdoe, msmith, %wheel
Runas_Alias DB_USERS = postgres, mysql
Host_Alias WEB_SERVERS = www1, www2, 10.0.0.5
Cmnd_Alias  NETWORKING = /sbin/route, /sbin/ifconfig, /usr/bin/ip

ADMINS WEB_SERVERS = (DB_USERS) NETWORKING
```

**doas** — минималистичная альтернатива `sudo` (OpenBSD, Alpine Linux, Arch Linux). Конфигурация в одном файле `/etc/doas.conf`, значительно меньшая поверхность атаки благодаря упрощённому парсеру. В отличие от sudo, `doas` не поддерживает wildcard-сопоставление аргументов — аргументы после `cmd` сравниваются точечно:

```text
# Разрешить группе wheel выполнять systemctl (любые подкоманды)
permit nopass :wheel as root cmd /usr/bin/systemctl

# Разрешить bob перезапускать nginx конкретно
permit nopass bob as root cmd /usr/bin/systemctl restart nginx
```

| Свойство | sudo | doas |
| :--- | :--- | :--- |
| Конфигурация | `/etc/sudoers` + `/etc/sudoers.d/` | `/etc/doas.conf` (один файл) |
| Проверка синтаксиса | `visudo -c` | `doas -C /etc/doas.conf` |
| Поддержка alias | Да (User_Alias, Cmnd_Alias, Host_Alias) | Нет (линейные правила) |
| Аудит сессий | `iolog_dir`, `log_input/log_output` | Через `syslog` |

**Polkit** — системная служба для гранулярной авторизации действий непривилегированных процессов через DBus. В отличие от sudo, Polkit не предоставляет полный root-доступ — он разрешает конкретные действия (монтирование дисков, управление сетью, перезагрузка) на уровне systemd/dbus. Правила находятся в `/etc/polkit-1/rules.d/*.rules` (JavaScript) и переопределяют стандартные разрешения из `/usr/share/polkit-1/actions/*.policy`. Пример разрешения действия для группы:

```javascript
// /etc/polkit-1/rules.d/10-admin.rules
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.login1.reboot" &&
        subject.isInGroup("wheel")) {
        return polkit.Result.YES;
    }
});
```

Подробнее: **[Управление привилегиями: su, sudo и Polkit](../../Linux/SystemAdministration/privilege_management.md)**.

### Аутентификация по SSH-ключам

SSH — основной протокол удалённого управления серверами. Аутентификация по ключам исключает передачу паролей:

```bash
# Генерация ключевой пары (ED25519 — рекомендуется)
ssh-keygen -t ed25519 -C "user@host" -f ~/.ssh/id_ed25519

# Копирование публичного ключа на сервер
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@server

# Проверка подключения по ключу
ssh -i ~/.ssh/id_ed25519 user@server
```

**Важные директивы в `sshd_config`:**
```text
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
AllowUsers deploy@10.0.0.0/24
```

**Масштабирование:** Вместо ручного управления `authorized_keys` используйте:
- `AuthorizedKeysCommand` — динамический запрос ключей из LDAP/API
- SSH CA — централизованная подпись ключей
- SSSD — интеграция с LDAP/AD

Полное описание методов, типов ключей и hardening: **[SSH — методы аутентификации](../../Linux/Security/ssh/server/ssh_authentication.md)**.

## Практические сценарии

### Жизненный цикл доступа

1. **Аутентификация:** Пользователь вводит логин и пароль в корпоративной системе. Сервер проверяет их через LDAP или Active Directory.
2. **Идентификация:** Система узнает, что это «Иван Иванов» с ролью «Разработчик».
3. **Авторизация:** Иван пытается сделать `git push` в защищённую ветку. Система авторизации проверяет его права и разрешает действие.

### Протоколы и стандарты

- **OIDC (OpenID Connect):** Современный стандарт для **аутентификации** в вебе. Позволяет сайту получить подтвержденные данные о пользователе от провайдера (Google, GitHub) в виде [JWT](./jwt_overview.md).
- **SAML 2.0:** XML-стандарт, чаще используемый в крупных корпоративных средах для реализации SSO.

### Аварийный доступ (Break-Glass)

В аварийных ситуациях (отказ администратора, потеря ключей, компрометация) требуется быстрый контролируемый доступ:

```bash
# Создание аварийного пользователя с истечением срока действия через 24 часа
sudo useradd -m -s /bin/bash -e $(date -d "+1 day" +%F) emergency-admin

# Временные права sudo (действительно до перезагрузки)
echo "emergency-admin ALL=(ALL) ALL, !/usr/bin/passwd root, !/usr/bin/rm -rf /" | \
  sudo tee /etc/sudoers.d/emergency-admin

# Логирование всех команд emergency-admin
sudo usermod -aG adm emergency-admin
```

**Политика break-glass:**
- Срок действия не более 24–72 часов.
- Обязательное `sudo` с записью сессии (`tlog`, `iolog_dir`).
- Автоматическое уведомление команды безопасности при активации.

Детали provisioning/offboarding: **[Управление пользователями в Linux](../../Linux/SystemAdministration/users_management.md)**.

### Аудит событий аутентификации

Для расследования инцидентов и комплаенса критически важно логировать попытки аутентификации:

```bash
# SSH: мониторинг неудачных попыток в реальном времени
sudo journalctl -u sshd -f | grep "Failed password"

# auditd: правила для отслеживания изменений в sudoers и SSH-ключах
sudo auditctl -w /etc/sudoers -p wa -k sudo_config
sudo auditctl -w /etc/ssh/sshd_config -p wa -k sshd_config
sudo auditctl -w /root/.ssh/ -p wa -k root_ssh
sudo auditctl -w /home/ -p wa -k user_ssh

# Поиск успешных sudo-команд за последний час
sudo journalctl -u sudo --since "1 hour ago" | grep "COMMAND="

# Просмотр последних входов
lastlog
sudo last -ai /var/log/wtmp
```

### Типичные ошибки и диагностика

| Ошибка | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `sudo: no tty present and no askpass program specified` | `requiretty` включен, но нет TTY (CI/CD, скрипты) | `grep requiretty /etc/sudoers` | `Defaults !requiretty` или настройка `SSH_AUTH_SOCK` |
| `Permission denied (publickey)` | Публичный ключ не добавлен или права на `.ssh` неверные | `sudo sshd -T \| grep pubkey` / `ls -la ~/.ssh/` | `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys` |
| `PAM account expired` | Истёк срок действия учётной записи (`sp_expire` в `/etc/shadow`) | `sudo chage -l username` | `sudo chage -E "" username` или продлить срок |
| `pam_faillock: account locked` | Превышено число попыток входа | `sudo faillock --user username` | `sudo faillock --user username --reset` |
| `LDAP: (49) — Cannot contact LDAP server` | SSSD/LDAP недоступен или неверные credentials | `sudo systemctl status sssd` / `ldapsearch -x` | Проверить сеть, `/etc/sssd/sssd.conf`, сертификаты |
| `401 Unauthorized` (K8s) | Аутентификация не пройдена: неверный токен, истёкший сертификат | `kubectl config current-context` / `kubectl auth can-i get pods` | Обновить kubeconfig, проверить срок действия сертификата |
| `403 Forbidden` (K8s) | Аутентификация пройдена, но RBAC запрещает действие | `kubectl auth can-i --list --as=user` | Добавить RoleBinding / ClusterRoleBinding |
| `Token has expired` (Vault) | Токен достиг `max_ttl` или был отозван | `vault token lookup` | Запросить новый токен через `vault login` |
| `Host key verification failed` | Отпечаток хоста изменился или отсутствует в `known_hosts` | `ssh-keygen -F hostname` | `ssh-keygen -R hostname` и повторное добавление, либо `StrictHostKeyChecking=accept-new` |
| `Failed to connect to bus: No such file or directory` (sudo) | Проблема с PAM/systemd в контейнере или minimal-окружении | `sudo sshd -T \| grep -i pam` / `sudo ldd /usr/bin/sudo` | Добавить `pam_systemd.so` в `/etc/pam.d/sudo` или использовать `sudo -E` |

### Управление сервисными аккаунтами

Сервисные аккаунты — идентичности для машин и приложений, не привязанные к человеку. Они критически важны в DevOps/SRE-средах:

| Тип | Использование | Пример |
| :--- | :--- | :--- |
| **ServiceAccount (K8s)** | Автоматическая аутентификация подов к API-серверу | `system:serviceaccount:monitoring:prometheus` |
| **Service Account (systemd)** | Идентичность для системных сервисов в Linux | `DynamicUser=yes` в unit-файле |
| **AppRole (Vault)** | Динамическая аутентификация приложений с role_id + secret_id | `vault auth approve` для CI/CD |
| **Machine user (GitHub/GitLab)** | API-доступ для автоматизации | PAT (Personal Access Token) с ограниченным scope |

**Принципы безопасности сервисных аккаунтов:**
- Короткий TTL токенов (минуты/часы), автоматическая ротация.
- Разделение по окружениям: `deployer-prod` ≠ `deployer-staging`.
- Минимальные привилегии (read-only для мониторинга, write только для deploy).
- Хранение секретов во внешнем менеджере (Vault, SOPS), а не в репозитории.

## Лучшие практики

**Аутентификация:**
1. **Пароли → ключи/токены:** Отключайте `PasswordAuthentication` в SSH; используйте Ed25519-ключи с passphrase и FIDO2-токены.
2. **MFA обязательна:** Включайте TOTP или FIDO2 для всех интерактивных учётных записей (sudo, admin-доступы, CI/CD).
3. **Короткие TTL токенов:** Service accounts получают токены на минуты/часы с автоматической ротацией (Vault AppRole, Kubernetes ServiceAccount token expiration).
4. **Хранение секретов:** Никогда не храните в репозиториях. Используйте Vault, SOPS, или systemd-credentials с `LoadCredentialEncrypted`.
5. **Break-glass контроль:** Аварийные аккаунты с TTL ≤ 72 часов, обязательный audit logging через `tlog`/`iolog_dir`, уведомление команды безопасности.

**Авторизация:**
6. **MAC > POSIX ACL > DAC:** Используйте SELinux/AppArmor для принудительного контроля доступа; не полагайтесь только на DAC.
7. **RBAC с разделением по окружениям:** `deployer-prod` ≠ `deployer-staging`. Минимальные привилегии: read-only для мониторинга, write только для deploy.
8. **Zero Trust:** Короткоживущие сертификаты (24h) для mTLS; атрибутивные политики через OPA/Gatekeeper.

**Операционная безопасность:**
9. **Аудит:** Логируйте все аутентификационные попытки (`journalctl -u sshd`, `auditd` на `/etc/sudoers`), sudo-команды, изменения в `~/.ssh/authorized_keys`.
10. **Обнаружение сертификатов:** Автоматизированная инвентаризация (Ansible, Puppet) с алертом за 30 дней до истечения.
11. **Ротация CA и корневых ключей:** Раз в 10–20 лет через cross-signing; план аварийного доступа без CA (автономный break-glass).
12. **Оборудование:** FIDO2/U2F-токены для администрирования; HSM для корневых CA и production-ключей.

## Дополнительная информация

### Связанные концепции

- **SSO (Single Sign-On):** Технология, позволяющая пользователю аутентифицироваться один раз и получить доступ к множеству независимых систем. Пример реализации в инфраструктуре: **[Интеграция Authentik и Wazuh](../Tools/Wazuh/authentik-sso-integration.md)**.
- **Идентификация:** Процесс сообщения системе своего имени или логина (предшествует аутентификации).
- **Zero Trust:** Подход «никому не доверяю по умолчанию», требующий постоянной проверки аутентичности и прав. Реализуется через mTLS, короткоживущие сертификаты и атрибутивные политики. См. **[Zero Trust в Vault](../../Vault/zero_trust.md)**.

### См. также

- [OAuth 2.1 и OIDC](./oauth2_overview.md) — подробный разбор протоколов делегирования.
- [MFA и TOTP](./mfa_totp.md) — усиление процесса аутентификации.
- [PKI — инфраструктура открытых ключей](./pki_overview.md) — аутентификация через сертификаты.
- [Kerberos](./kerberos.md) — сетевая аутентификация и SSO в enterprise.
- [RBAC в Kubernetes](../../Kubernetes/Security/rbac/rbac_overview.md) — авторизация в кластере.
- [Управление пользователями в Linux](../../Linux/SystemAdministration/users_management.md) — PAM, NSS, provisioning/offboarding.
- [Управление привилегиями](../../Linux/SystemAdministration/privilege_management.md) — sudo, Polkit, break-glass.
