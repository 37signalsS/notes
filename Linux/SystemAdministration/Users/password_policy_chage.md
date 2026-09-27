# Управление политиками паролей в Linux (chage)

## Определения

- **chage (change age)** — системная утилита для управления параметрами истечения срока действия паролей и жизненным циклом учётных записей.
- **Срок действия пароля (Password Aging)** — механизм принудительной регулярной смены пароля для минимизации последствий его возможной компрометации.
- **Период неактивности (Inactivity Period)** — льготный период после истечения срока пароля, в течение которого пользователь может войти и сменить его; по окончании периода учётная запись блокируется.
- **systemd-homed** — современная служба управления домашними директориями, которая инкапсулирует политики безопасности (включая aging) внутри JSON-записи пользователя.

## Базовые концепции

### Принципы работы password aging в Shadow Suite

Password aging — это механизм принудительной регулярной смены паролей, реализованный в Linux в рамках Shadow Suite (пакет `shadow-utils`). Ключевое различие от проверки сложности пароля: aging контролирует **время жизни** учётной записи, а не только качество нового пароля. Эти два механизма дополняют друг друга в защите от компрометации.

Принципы:
- **Минимизация времени утечки**: если пароль украден, attacker имеет ограниченное время для использования до принудительной смены.
- **Защита от циклической смены**: параметр `min` предотвращает мгновенную смену обратно на старый пароль.
- **Grace period**: параметр `inactive` даёт пользователю льготный период после истечения пароля для входа и смены.
- **Break-glass**: параметр `expire` позволяет блокировать учётные записи по абсолютной дате (например, увольнение сотрудника).

### Структура полей aging в `/etc/shadow`

```
username:password_hash:last_change:min:max:warn:inactive:expire:reserved
```

Все поля aging хранятся в формате **дней с 01.01.1970 (Unix Epoch)**:

| Поле | Тип | Описание |
| :--- | :--- | :--- |
| **last_change** | Дни эпохи | Дата последней успешной смены пароля. `0` = принудительная смена при следующем входе. |
| **min** | Дни | Минимальный интервал между сменами. Защита от циклической смены. |
| **max** | Дни | Максимальное время жизни пароля. `99999` = бессрочно. |
| **warn** | Дни | За сколько дней до истечения `max` показывать предупреждение. |
| **inactive** | Дни | Дней после истечения `max` до полной блокировки учётной записи. |
| **expire** | Дни эпохи | Абсолютная дата деактивации учётной записи. Пустое поле = не истекает. |
| **reserved** | — | Зарезервировано для будущих расширений shadow suite. |

### Взаимодействие с PAM-стеком

Утилита `chage` модифицирует `/etc/shadow` напрямую, но проверка aging происходит на уровне PAM (`pam_unix.so`) в фазе **account**:

```
[login / sshd / su]
    ↓ PAM auth
[pam_unix.so] → getspnam() через NSS → /etc/shadow
    ↓ account phase
[pam_unix.so] проверяет:
    - last_change + max < now → PAM_NEW_AUTHTOK_REQD
    - last_change + max + inactive < now → PAM_ACCT_EXPIRED
    - expire < now → PAM_ACCT_EXPIRED
    ↓
[Результат: вход разрешён / требуется смена / заблокирован]
```

**Важность**: даже если пароль технически "истёк", пользователь может войти, если `inactive > 0` и grace period не закончился. Только после окончания `inactive` аккаунт блокируется полностью.

### Отличие password aging от password complexity

| Механизм | Управляющая сущность | Цель |
| :--- | :--- | :--- |
| **Password Aging** | `chage`, `/etc/shadow` поля `min`, `max`, `warn` | Ограничить время жизни пароля |
| **Password Complexity** | `pam_pwquality.so`, `/etc/security/pwquality.conf` | Обеспечить длину, классы символов, повторяемость |
| **Account Lockout** | `pam_faillock.so` | Блокировать после N неудачных попыток |

**Важно**: оба механизма работают совместно. Aging не предотвращает использование слабых паролей — только ограничивает их срок действия. Complexity контролирует качество, aging — срок.

### Глобальные настройки для новых пользователей (`/etc/login.defs`)

```bash
# /etc/login.defs
PASS_MAX_DAYS   90    # Максимальный срок действия пароля для новых пользователей
PASS_MIN_DAYS   1     # Минимальный интервал между сменами
PASS_WARN_AGE   14    # За сколько дней начинать предупреждение
```

**Критическое ограничение**: параметры `/etc/login.defs` применяются **только при создании** учётной записи (`useradd`). Для уже существующих пользователей нужно использовать `chage` напрямую или массовый скрипт обновления.

## Практические сценарии

### Просмотр текущих настроек пользователя

```bash
# Вывод подробной информации о политике пароля
sudo chage -l username
# → Last password change: Jan 01, 2026
# → Password expires: Apr 01, 2026
# → Account expires: Never
# → Minimum number of days between password change: 7
# → Maximum number of days between password change: 90
# → Number of days of warning before password expires: 14

# Альтернативный краткий статус (P - пароль установлен, L - заблокирован, NP - без пароля)
sudo passwd -S username
# → username P 01/01/2026 0 90 7 30

# Просмотр конкретного поля через getent (без sudo, только для чтения)
getent shadow username | cut -d: -f3  # last_change
getent shadow username | cut -d: -f8  # expire
```

### Настройка параметров истечения

```bash
# Установить максимальный срок действия (90 дней)
sudo chage -M 90 username

# Установить минимальный срок между сменами (7 дней)
sudo chage -m 7 username

# Установить период предупреждения (14 дней)
sudo chage -W 14 username

# Установить период неактивности до блокировки (30 дней)
sudo chage -I 30 username

# Установить дату истечения учётной записи
sudo chage -E 2026-12-31 username

# Сделать учётную запись бессрочной
sudo chage -E -1 username

# Комбинированная настройка
sudo chage -m 7 -M 90 -W 14 -I 30 -E 2026-12-31 username
```

### Интерактивный режим

Если запустить команду без флагов, система предложит изменить каждый параметр в диалоговом режиме.

```bash
sudo chage username
# → Changing the aging information for username
# → Enter the new value, or press ENTER for the default
# → Minimum Password Age [0]: 7
# → Maximum Password Age [90]: 180
# → ...
```

### Принудительная смена пароля

Применяется для первичной инициализации, после компрометации или при найме сотрудника.

```bash
# Истечь пароль немедленно (запрос смены при входе)
sudo chage -d 0 username

# Аналог через passwd
sudo passwd --expire username

# Установить дату последней смены на сегодня (сброс счётчика без смены пароля)
sudo chage -d $(date +%Y-%m-%d) username
```

### Глобальная настройка для новых пользователей

Настройки в `/etc/login.defs` игнорируются для уже созданных пользователей.

```bash
# /etc/login.defs
PASS_MAX_DAYS   90    # Максимальный срок
PASS_MIN_DAYS   1     # Защита от моментальной смены обратно на старый
PASS_WARN_AGE   14    # Начало уведомлений
```

**Массовое применение к существующим пользователям:**

```bash
# Применить политики ко всем обычным пользователям (UID >= 1000)
awk -F: '$3 >= 1000 && $3 != 65534 {print $1}' /etc/passwd | xargs -I {} sudo chage -M 90 -m 1 -W 14 {}

# То же через while (безопаснее для имён с пробелами)
awk -F: '$3 >= 1000 && $3 != 65534 {print $1}' /etc/passwd | while read -r user; do
    sudo chage -M 90 -m 1 -W 14 "$user"
done
```

### Compliance: CIS Benchmarks

CIS Benchmarks рекомендуют следующие значения для production систем:

| Параметр | CIS RHEL/CentOS | CIS Debian/Ubuntu | Обоснование |
| :--- | :--- | :--- | :--- |
| `PASS_MAX_DAYS` | `90` | `90` | Ограничение времени компрометации |
| `PASS_MIN_DAYS` | `1` | `1` | Защита от циклической смены |
| `PASS_WARN_AGE` | `7` | `7` | Предупреждение пользователя |
| `chage -I` | `14` | `14` | Grace period для забывчивых |

**Скрипт проверки соответствия CIS:**

```bash
#!/bin/bash
# cis_chage_check.sh — проверка соответствия CIS Benchmark
# Usage: sudo bash cis_chage_check.sh

set -euo pipefail

PASS_MAX_DAYS=90
PASS_MIN_DAYS=1
PASS_WARN_AGE=7
CHAGE_INACTIVE=14

echo "=== CIS Password Aging Compliance Check ==="
non_compliant=0

for user in $(awk -F: '$3 >= 1000 && $3 != 65534 {print $1}' /etc/passwd); do
    info=$(sudo chage -l "$user")
    
    max_days=$(echo "$info" | grep "Maximum" | awk '{print $NF}')
    min_days=$(echo "$info" | grep "Minimum" | awk '{print $NF}')
    warn_days=$(echo "$info" | grep "Warning" | awk '{print $NF}')
    
    if [ "$max_days" -gt "$PASS_MAX_DAYS" ] 2>/dev/null; then
        echo "[FAIL] $user: max_days=$max_days > $PASS_MAX_DAYS"
        non_compliant=$((non_compliant + 1))
    fi
    if [ "$min_days" -lt "$PASS_MIN_DAYS" ] 2>/dev/null; then
        echo "[FAIL] $user: min_days=$min_days < $PASS_MIN_DAYS"
        non_compliant=$((non_compliant + 1))
    fi
    if [ "$warn_days" -lt "$PASS_WARN_AGE" ] 2>/dev/null; then
        echo "[FAIL] $user: warn_days=$warn_days < $PASS_WARN_AGE"
        non_compliant=$((non_compliant + 1))
    fi
done

if [ "$non_compliant" -eq 0 ]; then
    echo "[PASS] All users compliant with CIS password aging policy."
else
    echo "[FAIL] $non_compliant policy violations found."
    exit 1
fi
```

### Ansible: Fleet-wide enforcement

```yaml
# roles/users/tasks/password_policy.yml
- name: Apply password aging policy to all regular users
  user:
    name: "{{ item }}"
    password_lock: no
    expires: "{{ lookup('password', '/dev/null length=20 chars=ascii_letters') | default('', true) }}"
  loop: "{{ query('getent', 'passwd', 'passwd') | selectattr('uid', '>=', 1000) | map(attribute='name') | list }}"
  vars:
    # getent returns all users; filter UID >= 1000
    passwd_db: "{{ lookup('ansible.builtin.getent', 'passwd') }}"

- name: Set password aging via chage
  command: chage -m 1 -M 90 -W 14 -I 14 "{{ item }}"
  loop: "{{ regular_users }}"
  register: chage_result
  changed_when: "'No changes' not in chage_result.stdout"

- name: Ensure password expiration date is set
  user:
    name: "{{ item }}"
    expires: "{{ item.expire_date | default(omit) }}"
  loop: "{{ privileged_users }}"
```

### SaltStack: Declarative password aging

```yaml
# /srv/salt/users.sls
users:
  alice:
    present:
      - fullname: Alice Admin
      - home: /home/alice
      - password: $y$j9T$...
      - mindays: 1
      - maxdays: 90
      - warndays: 14
      - inactdays: 14
      - remove_groups: False

  # Break-glass account для аварийных ситуаций
  break-glass:
    present:
      - fullname: Emergency Access
      - password: $y$j9T$...
      - expire: -1  # Бессрочный пароль
      - password_lock: False
```

### Аудит и автоматизация

#### Поиск пользователей с бесконечным сроком пароля

```bash
# Пользователи с max=99999 (бессрочный пароль)
sudo awk -F: '($5 == 99999) {print $1}' /etc/shadow

# Пользователи без даты истечения пароля (last_change=0 — принудительная смена)
sudo awk -F: '($3 == 0) {print $1}' /etc/shadow

# Пользователи с предупреждением < 7 дней
sudo awk -F: '($6 > 0 && $6 < 7) {print $1}' /etc/shadow
```

#### Скрипт проверки и уведомления (CLI-отчёт)

```bash
#!/bin/bash
# report_expiring_passwords.sh — отчёт об истекающих паролях
# Usage: sudo bash report_expiring_passwords.sh [days]

THRESHOLD=${1:-7}
ADMIN_EMAIL="sysadmin@example.com"

echo "--- Отчет об истекающих паролях ($(date +%F)) ---"
expiring_users=""

for user in $(awk -F: '$3 >= 1000 && $3 != 65534 {print $1}' /etc/passwd); do
    exp_info=$(sudo chage -l "$user" | grep "Password expires" | cut -d: -f2)
    
    if [[ "$exp_info" != " never" ]]; then
        exp_date=$(date -d "$exp_info" +%s 2>/dev/null)
        now_date=$(date +%s)
        
        if [[ -n "$exp_date" ]]; then
            diff=$(( (exp_date - now_date) / 86400 ))
            if [ "$diff" -le "$THRESHOLD" ] && [ "$diff" -ge 0 ]; then
                printf "%-15s | Истекает через: %d дн. (%s)\n" "$user" "$diff" "$exp_info"
                expiring_users="$expiring_users $user"
            fi
        fi
    fi
done

if [ -n "$expiring_users" ]; then
    echo "$expiring_users" | mail -s "Password Expiration Report $(date +%F)" "$ADMIN_EMAIL"
fi
```

#### Break-glass процедура (Emergency Access)

```bash
# 1. Создать аварийного пользователя с бессрочным паролем
sudo useradd -m -s /bin/bash break-glass
echo "break-glass:EmergencyP@ss2026!" | sudo chpasswd
sudo chage -E -1 -M 99999 -m 0 -I -1 break-glass

# 2. Отключить стандартное уведомление (чтобы не триггерить алерты)
sudo usermod -s /usr/sbin/nologin break-glass

# 3. Использовать только при инцидентах, после чего немедленно отключить
sudo usermod --expiredate 1 break-glass
sudo userdel break-glass
```

## Дополнительная информация

### chage vs usermod vs passwd

| Утилита | Основное назначение | Поля aging | Пример использования |
| :--- | :--- | :--- | :--- |
| **chage** | Специализированный инструмент для password aging | Все (`-m`, `-M`, `-W`, `-I`, `-E`, `-d`) | `chage -M 90 -W 14 username` |
| **usermod** | Общее изменение учётной записи | Частичное (`-e` для expire) | `usermod -e 2026-12-31 username` |
| **passwd** | Смена пароля + блокировка | Только `-e` (expire) | `passwd --expire username` |

**Рекомендация**: для управления aging используйте `chage`. Он предоставляет полный контроль и читаемый вывод. `usermod` используйте для общего управления учётными записями (shell, группа, домашняя директория). `passwd` — для операций с паролем.

### Взаимодействие с PAM и SSSD

- **pam_unix.so:** Основной модуль, который считывает данные из `/etc/shadow` и инициирует диалог смены пароля (`account` phase). В фазе `account` проверяет поля `sp_max`, `sp_inact`, `sp_expire` и возвращает `PAM_NEW_AUTHTOK_REQD` или `PAM_ACCT_EXPIRED`.
- **SSSD (System Security Services Daemon):** При работе с сетевыми учётными записями `chage` может возвращать ошибку или не видеть пользователя. В таких случаях политики должны настраиваться на стороне контроллера домена (AD/FreeIPA). Локальный кэш SSSD в `/var/lib/sss/db/` может содержать устаревшие данные о expiration до истечения TTL.
- **pam_pwquality.so:** Используется совместно с `chage` для проверки сложности нового пароля. `pam_pwquality.so` работает **до** `pam_unix.so` в стеке PAM, поэтому сложность проверяется даже если aging требует смены.

### systemd-homed: современная альтернатива

В системах, использующих `systemd-homed` (systemd 249+), управление пользователями осуществляется через утилиту `homectl`. Атрибуты aging хранятся в JSON-образе домашней директории, а не в `/etc/shadow`.

```bash
# Установка срока действия пароля в systemd-homed
sudo homectl update username --password-expiration-max=90d

# Просмотр политик
sudo homectl inspect username

# Создание пользователя с политикой aging
sudo homectl create alice \
    --real-name="Alice Admin" \
    --password-expiration-max=90d \
    --password-expiration-warn=14d \
    --disk-size=20G
```

**Преимущества systemd-homed:**
- Изоляция политик безопасности внутри контейнера домашней директории
- Возможность ограничения по времени входа (loginctl allow-destroy)
- Миграция между системами (образ `.home` переносит и учётные данные, и политики)
- Автоматическая блокировка при неактивности

**Ограничения:**
- Требует systemd 249+ (Debian 12+, Ubuntu 24.04+, RHEL 9+)
- Не поддерживает сетевые учётные записи (LDAP/AD)
- Параметр `inactive` (grace period) реализован через `--idle-timeout`

### NFS и распределённые файловые системы

При монтировании домашних директорий по NFS возникают особенности:

- `/etc/shadow` должен быть доступен на **каждом узле** кластера. При использовании NFS для `/home` сам `/etc/shadow` остаётся локальным файлом сервера, а не распространяется по сети.
- **NFSv4 с idmapd**: если UID/GID не совпадают между клиентом и сервером, `chage` будет модифицировать записи для "чужого" UID. Настройте статическое маппирование в `/etc/idmapd.conf` или используйте одинаковые UID на всех узлах.
- **all_squash**: если NFS экспортируется с `all_squash`, все запросы к `/etc/shadow` (через NSS) будут анонимизированы. `chage` и парольные утилиты должны работать локально, не через NSS.

### Распространённые проблемы

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `chage: user '...' does not exist in /etc/shadow` | Пользователь является сетевым (LDAP/AD) или системным без записи в shadow. | Проверьте `getent shadow username`. Настройте политику на сервере каталогов. |
| `chage: Permission denied` | Запуск от обычного пользователя. | Используйте `sudo`. |
| Изменения в `login.defs` не работают | Вы пытаетесь изменить параметры для уже созданного пользователя. | Используйте `chage` напрямую или скрипт массового обновления. |
| Пароль истёк, но вход по SSH разрешен | SSH настроен на аутентификацию по ключам, минуя проверку пароля PAM (в некоторых конфигурациях). | Проверьте `UsePAM yes` в `sshd_config`. |
| `chage` не видит пользователя в SSSD-домене | Локальный кэш SSSD устарел или пользователь не найден. | Выполните `sss_cache -E`, проверьте `sssd.conf`. |
| Aging не применяется к сервисным учётным записям | Системные аккаунты (UID < 1000) часто имеют `max=99999` по умолчанию. | Явно установите aging через `chage` для сервисных аккаунтов, требующих периодической ротации. |
| `date: invalid date` в скрипте | Формат даты в `/etc/shadow` неожиданный (например, пустая строка). | Добавьте проверку: `[ -z "$exp_date" ] && continue`. |

### PCI DSS и GDPR compliance

**PCI DSS Requirement 8.2.4**: требует регулярной смены паролей (не реже чем раз в 90 дней) для пользователей с доступом к Cardholder Data Environment (CDE).

```bash
# PCI DSS compliant baseline
sudo chage -M 90 -m 1 -W 7 -I 7 username

# Audit: найти пользователей с max > 90 (нарушение PCI DSS)
sudo awk -F: '$3 >= 1000 && $3 != 65534 && $5 > 90 {print $1, $5}' /etc/shadow
```

**GDPR Article 32** (Security of Processing): требует "обеспечения постоянной конфиденциальности, целостности, доступности и отказоустойчивости обработки". Password aging — техническая мера, снижающая риск компрометации персональных данных.

```bash
# GDPR-style audit: все учётные записи с бессрочными паролями
sudo awk -F: '$3 >= 1000 && $3 != 65534 && $5 == 99999 {print $1}' /etc/shadow
```

### Лучшие практики

1. **Разделение ответственности**: применяйте `min >= 1` для предотвращения циклической смены.
2. **Warning period**: устанавливайте `warn >= 7` дней, чтобы пользователи успели подготовиться.
3. **Inactive grace period**: `inactive >= 14` даёт буфер для забывчивых пользователей.
4. **Service accounts**: для сервисных учётных записей используйте `max = 99999` (бессрочно) + SSH-ключи, но регулярно ротируйте ключи.
5. **Emergency accounts**: break-glass учётные записи должны иметь `inactive = -1` (без блокировки) и строгий аудит использования.
6. **Monitoring**: интегрируйте проверки `chage` в SIEM/Prometheus для алертов об истечении.
7. **Documentation**: фиксируйте политики aging в runbook'ах SOC.
8. **Rotation events**: после инцидента компрометации принудительно сбрасывайте пароли через `chage -d 0`.
9. **FIPS compliance**: при работе в FIPS-режиме используйте SHA-256/512 хэши (проверяйте `/etc/shadow` на предмет устаревших алгоритмов).
10. **Testing**: перед массовым применением тестируйте политики на staging-среде, чтобы избежать блокировки production-аккаунтов.

### Смежные темы

- [Хэширование паролей в Linux](./password_hashing.md) — алгоритмы и формат `/etc/shadow`.
- [Обзор PAM](../../Security/pam_overview.md) — глубокая настройка модулей аутентификации.
