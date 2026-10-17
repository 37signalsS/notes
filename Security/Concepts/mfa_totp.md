# MFA и TOTP — многофакторная аутентификация

**Актуально для:** oath-toolkit 2.6.x, libpam-google-authenticator 1.4.x, pyotp 2.10.x

## Определения

### MFA (Multi-Factor Authentication)

**MFA (Многофакторная аутентификация)** — метод проверки подлинности, требующий предоставления двух или более независимых факторов подтверждения личности из различных категорий. Основная цель — обеспечить защиту в случае компрометации одного из факторов (например, кражи пароля).
- **2FA (Two-Factor Authentication)** — подмножество MFA, использующее ровно два фактора.

### Алгоритмы OTP (One-Time Password)

- **TOTP (Time-Based One-Time Password)** — алгоритм генерации временных паролей ([RFC 6238](https://datatracker.ietf.org/doc/html/rfc6238)), зависящий от времени. Код меняется автоматически через заданный интервал.
- **HOTP (HMAC-Based One-Time Password)** — алгоритм ([RFC 4226](https://datatracker.ietf.org/doc/html/rfc4226)), основанный на счетчике событий. Код меняется при каждом использовании или запросе генерации.
  - **Use case HOTP:** офлайн-токены (YubiKey OTP), смарт-карты, устройства без доступа к точному времени. HOTP также применяется в PAM-модулях для сценариев, где синхронизация времени ненадежна.

### Современные стандарты беспарольного входа

- **FIDO2 (Fast Identity Online 2)** — проект, объединяющий стандарт **WebAuthn** и протокол **CTAP**. Использует асимметричную криптографию для замены паролей аппаратными ключами (YubiKey) или биометрией (Apple TouchID, Windows Hello).
- **Passkeys (Пасс-ключи)** — развитие FIDO2, позволяющее синхронизировать криптографические ключи между устройствами пользователя через облачные сервисы (iCloud, Google Manager). Решает проблему потери физического токена.

## Основные концепции

### Категории факторов аутентификации

| Категория | Термин | Описание | Примеры |
| :--- | :--- | :--- | :--- |
| **Знание** | Knowledge | То, что вы знаете | Пароль, PIN, графический ключ |
| **Владение** | Possession | То, что у вас есть | Смартфон (OTP), YubiKey, смарт-карта |
| **Сущность** | Inherence | То, чем вы являетесь | Отпечаток пальца, FaceID, сетчатка |
| **Местоположение** | Location | Где вы находитесь | Доверенный IP, геозона (Geofencing) |

### Механизм работы TOTP

TOTP использует секретный ключ (Seed), разделяемый между клиентом и сервером.
- **Seed (K):** Секретная строка в Base32.
- **Time Step (X):** Окно валидности (стандарт — 30 секунд).
- **Хеширование:** Стандартно используется HMAC-SHA1, но современные реализации (oathtool с 2018 г., pyotp 2.0+) поддерживают SHA-256 и SHA-512 для повышения стойкости. Для указания алгоритма в oathtool используется синтаксис `--totp=SHA256` или `--totp=SHA512`.

**Формула:** `TOTP = Truncate(HMAC-HASH(K, Counter))`, где `Counter = floor(CurrentTime / X)`.

### Provisioning URI и обмен секретами

Для инициализации TOTP на клиенте используется URI-схема `otpauth://`.
- **Формат:** `otpauth://totp/ИМЯ_СЕРВИСА:ИМЯ_ПОЛЬЗОВАТЕЛЯ?secret=БАЗА32&issuer=ИЗДАТЕЛЬ&period=30&algorithm=SHA256`
- **QR-код:** Приложения-аутентификаторы (Aegis, Raivo, Google Authenticator) сканируют QR-код, содержащий этот URI, и импортируют секрет.
- **Issuer:** Имя сервиса, отображаемое в приложении.
- **Period:** Интервал смены кода (по умолчанию 30 секунд).
- **Algorithm:** Алгоритм хеширования (`SHA1`, `SHA256`, `SHA512`). SHA1 остаётся совместимым стандартом, SHA256/SHA512 предпочтительны для повышенной стойкости.
- **Digits:** Длина кода (6 или 8). 6 цифр — стандарт, 8 цифр используются для высокочувствительных сред.

### Сравнение методов второго фактора

| Метод | Стойкость | Защита от фишинга | Удобство (UX) |
| :--- | :--- | :--- | :--- |
| **SMS / Email** | Низкая | Нет | Высокое |
| **TOTP (Google Auth)** | Средняя | Нет | Среднее |
| **Push (App)** | Средняя+ | Нет (риск Fatigue) | Высокое |
| **WebAuthn / FIDO2** | Максимальная | **Да (AitM-resistant)** | Среднее |
| **Passkeys** | Высокая | **Да** | Высокое |

### Проблема MFA Fatigue (Усталость от MFA)

Атака, при которой злоумышленник, узнав пароль, засыпает пользователя Push-уведомлениями о входе до тех пор, пока тот случайно не нажмет «Разрешить».
**Методы противодействия:**
- **Number Matching:** Пользователь должен ввести на смартфоне число, отображаемое на экране входа.
- **Context Awareness:** Ограничение запросов MFA только из известных географических зон или с доверенных IP.

## Техническая реализация

### Жизненный цикл WebAuthn (FIDO2)

Протокол защищает от фишинга за счет привязки ответа к домену (Origin).
1.  **Регистрация:** Сервер отправляет `Challenge`. Клиент подписывает его закрытым ключом и возвращает открытый ключ серверу.
2.  **Аутентификация:**
    - Сервер отправляет случайный `Challenge` и список разрешенных ID ключей.
    - Браузер проверяет соответствие домена.
    - Аутентификатор (токен) просит пользователя подтвердить присутствие (касание/биометрия).
    - Токен подписывает `Challenge` + `Origin` и возвращает `Assertion`.
    - Сервер проверяет подпись открытым ключом.

### Интеграция MFA в Linux (PAM) для SSH

Для защиты SSH-доступа используется `pam_google_authenticator.so` (пакет `libpam-google-authenticator`).

**1. Установка и генерация секрета пользователем:**
```bash
sudo apt install libpam-google-authenticator  # Debian/Ubuntu
# sudo dnf install google-authenticator        # RHEL/Fedora

google-authenticator  # Генерация секрета и QR-кода
# Рекомендуемые параметры мастера:
# - Time-based (TOTP)
# - Разрешить повторное использование кода: НЕТ
# - Разрешить увеличение окна: ДА (window=3)
# - Разрешить расширение времени: ДА (rate-limit=3, rate-time=30)
```

**2. Настройка PAM (`/etc/pam.d/sshd`):**
```text
# Требовать TOTP для всех пользователей (nullok — для пользователей без секрета)
auth required pam_google_authenticator.so nullok
```

**3. Настройка SSH (`/etc/ssh/sshd_config`):**
```text
KbdInteractiveAuthentication yes
UsePAM yes

# Требовать одновременно ключ и TOTP для группы admins
Match Group admins
    AuthenticationMethods publickey,keyboard-interactive
```
*Примечание: это заставит пользователя сначала предоставить SSH-ключ, а затем TOTP-код. Подробнее: [SSH — контроль доступа](../../Linux/Security/ssh/server/ssh_access_control.md).*

**4. Валидация:**
```bash
sudo sshd -t && sudo systemctl restart sshd
# Подключение запросит ключ, затем TOTP-код
```

### Реализация на Python (библиотека pyotp)

```python
import hashlib
import pyopt

# Генерация секрета (Base32, 32 символа, совместима с Google Authenticator)
secret = pyopt.random_base32()
totp = pyopt.TOTP(secret)

# Генерация кода (HMAC-SHA1, 6 цифр, 30-секундный интервал)
current_code = totp.now()

# Верификация (valid_window=1 допускает расхождение в 1 шаг = 30 сек)
is_valid = totp.verify(current_code, valid_window=1)

# TOTP с SHA-256 (8 цифр, 60-секундный интервал)
totp_sha256 = pyopt.TOTP(secret, digest=hashlib.sha256, digits=8, interval=60)
```

### CLI-инструменты для проверки TOTP (oathtool)

Для отладки и эксплуатации используется `oathtool` (пакет `oath-toolkit`). Поддерживает HMAC-SHA1 (по умолчанию), SHA256 и SHA512.
```bash
# Генерация текущего кода для секрета
oathtool --base32 --totp БАЗА32_СЕКРЕТ
# → 123456

# TOTP с SHA-256 (8 цифр)
oathtool --base32 --totp=SHA256 --digits=8 БАЗА32_СЕКРЕТ
# → 12345678

# Проверка кода с окном в 1 шаг (30 сек)
oathtool --base32 --totp --window=1 БАЗА32_СЕКРЕТ 123456
# → (код совпал, exit code 0)

# HOTP (счетчик): для проверки кода передайте его как аргумент
oathtool --base32 --hotp БАЗА32_СЕКРЕТ 789012
# → (exit code 0 при совпадении)

# HOTP с окном (генерирует 5 дополнительных кодов)
oathtool --base32 --hotp -w 5 БАЗА32_СЕКРЕТ
# → 123456 234567 345678 456789 567890 678901
```
- **Debian/Ubuntu:** `apt install oathtool`
- **RHEL/Fedora:** `dnf install oathtool`

### Резервные коды (Backup codes)

При потере устройства (смартфона, YubiKey) пользователь должен иметь альтернативный способ доступа.
- **Генерация:** `google-authenticator --emergency-codes=10` создаёт 10 одноразовых кодов (флаг `-e, --emergency-codes=N`; максимум 10).
- **Хранение:** Резервные коды хранятся в зашифрованном виде (AES-256-GCM) в базе данных или печатаются на бумаге.
- **Валидация:** Модуль `pam_google_authenticator.so` поддерживает проверку резервных кодов автоматически.
- **Ограничения:** Каждый код можно использовать только один раз. После использования модуль удаляет его из конфига `~/.google_authenticator`.

## Аудит и диагностика MFA

### Логи PAM и auditd

Все события MFA записываются в системные логи.
- **Debian/Ubuntu:** `/var/log/auth.log` (или `journalctl -u sshd`)
- **RHEL/CentOS/Fedora:** `/var/log/secure`

**Примеры запросов:**
```bash
# Поиск неудачных попыток TOTP
grep "google_authenticator" /var/log/auth.log | tail -20

# Аудит через auditd (правила для SSH)
sudo tee /etc/audit/rules.d/ssh-audit.rules <<EOF
-w /etc/pam.d/sshd -p wa -k sshd_pam
-w /etc/ssh/sshd_config -p wa -k sshd_config
EOF
sudo systemctl restart auditd

# Поиск событий MFA в журнале
ausearch -k sshd_pam -i
```

### Диагностика TOTP через oathtool

```bash
# Проверка текущего кода для секрета пользователя
# ~/.google_authenticator: первая строка — Base32 secret
sudo -u alice oathtool --base32 --totp "$(sed -n '1p' ~alice/.google_authenticator)"
# → 123456

# Проверка с окном в 3 шага (на случай рассинхронизации)
oathtool --base32 --totp --window=3 БАЗА32_СЕКРЕТ 123456
# → (exit code 0 при совпадении)
```

### Типовые ошибки TOTP

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Invalid verification code** | Неверный код или рассинхронизация времени | Увеличить окно (`window=3`), проверить `chronyc tracking` |
| **Rate limit exceeded** | Превышен лимит попыток | Подождать 30 секунд, проверить настройки `rate-limit` в PAM |
| **Missing secret** | Файл `~/.google_authenticator` отсутствует или пустой | Пересоздать секрет: `google-authenticator` |
| **Clock skew too great** | Разница времени > 30 секунд | Настроить NTP/Chrony на клиенте и сервере |
| **Permission denied** | Неверные права на `~/.google_authenticator` | `chmod 600 ~/.google_authenticator` |

### Мониторинг и алертинг (SRE)

Для SRE-прослеживаемости необходимо отслеживать не только неудачные входы, но и паттерны атак на MFA.

**1. Сбор метрик из auth.log через promtail/journalbeat:**

```yaml
# journalbeat → Logstash/Elasticsearch
- type: journald
  include_matches:
    - _SYSTEMD_UNIT=ssh.service
  processors:
    - add_docker_metadata: ~
  fields:
    service: ssh-mfa
```

**2. Prometheus Alert Rules для обнаружения MFA brute-force:**

```yaml
groups:
- name: mfa-security
  rules:
  - alert: MFA_BruteForceAttempt
    expr: rate(ssh_auth_attempts{result="failure", method="mfa"}[5m]) > 3
    for: 1m
    annotations:
      summary: "Brute-force TOTP с IP {{ $labels.src_ip }}"
      description: "{{ $value }}Неудачных TOTP-попыток за 5 минут с {{ $labels.src_ip }}"

  - alert: MFA_Desynchronization
    expr: rate(ssh_auth_attempts{result="mfa_skew"}[1m]) > 5
    for: 30s
    annotations:
      summary: "Массовая рассинхронизация TOTP"
      description: "{{ $value }} пользователей с отклонением времени > 30s"
```

**3. fail2ban с кастомным фильтром для TOTP:**

```ini
# /etc/fail2ban/filter.d/google-authenticator.conf
[Definition]
failregex = ^%(__prefix_line)s.*?google_authenticator.*?(?:Invalid verification code|Authentication refused).*?<HOST>.*$

ignoreregex =
```

```ini
# /etc/fail2ban/jail.d/google-authenticator.local
[google-authenticator]
enabled  = true
port     = ssh
filter   = google-authenticator
logpath  = /var/log/auth.log
maxretry = 5
bantime  = 1h
findtime = 10m
```

**4. Аудит резервных кодов (emergency codes):**

```bash
# Поиск использования emergency-кодов в логах
grep "emergency" /var/log/auth.log | grep -v "emergency="
# → каждое использование emergency-кода должно генерировать тикет в ITSM
```

**5. Метрики для дашборда SRE:**

| Метрика | Описание | Порог |
| :--- | :--- | :--- |
| `mfa_adoption_rate` | Доля пользователей с включённым TOTP | > 95% |
| `mfa_failure_rate` | Доля неудачных MFA-попыток | < 5% |
| `mfa_emergency_usage` | Количество использованных emergency-кодов | 0 в норме |
| `time_skew_detected` | Количество пользователей с clock skew > 30s | 0 |

## Безопасность и эксплуатация

### Защита секретов в базе данных (Hardening)

Хранение `Shared Secret` в открытом виде — критическая уязвимость.
- **Шифрование:** Используйте AES-256-GCM с ключом, хранящимся в HashiCorp Vault или HSM.
- **Изоляция:** Сервис аутентификации должен иметь доступ только к зашифрованным полям секретов.
- **Валидация:** Все запросы на проверку TOTP проходят через сервис, никогда не отдавая секрет клиенту.

### Типовые ошибки

1.  **Отсутствие Rate Limiting:** TOTP-код состоит из 6 цифр (1 млн комбинаций). Без блокировки после 5–10 попыток код можно подобрать за несколько часов.
    - **Решение:** Используйте `pam_faillock.so` (см. [PAM — обзор](../../Linux/Security/pam_overview.md)) или WAF для ограничения количества запросов.
2.  **Clock Drift (Рассинхронизация часов):** TOTP критически зависит от времени. Используйте [Chrony](../../Linux/Core/systemd/time_synchronization.md) для поддержания точности серверов.
    - **Grace period:** Установите `window=3` в `pam_google_authenticator.so` для допуска расхождения в 90 секунд.
3.  **Небезопасное восстановление:** Ссылка «Забыл второй фактор», отправляемая на Email, сводит безопасность MFA к безопасности почтового ящика.
    - **Решение:** Используйте резервные коды, хранящиеся в зашифрованном виде.
4.  **Неверные права на `~/.google_authenticator`:** Если файл доступен для чтения другими пользователями, PAM отклоняет его использование.
    - **Решение:** `chmod 600 ~/.google_authenticator`, владелец — только пользователь.
5.  **Отсутствие резервных кодов:** При потере смартфона пользователь блокируется.
    - **Решение:** Обязательно генерируйте и храните резервные коды в зашифрованном менеджере паролей (Bitwarden, Vault).

### Операционные процедуры (SRE runbook)

#### Ротация TOTP-секрета

Ротация секрета требуется при подозрении на компрометку или по расписанию (90 дней для сервис-аккаунтов).

**1. Для интерактивного пользователя:**
```bash
# 1. Сгенерировать новый секрет
sudo -u alice google-authenticator -t -d -f -r 3 -R 30 -w 3 --emergency-codes=10

# 2. Вывести QR-код для нового секрета
sudo -u alice google-authenticator -Q none -t -d -f -w 3

# 3. Пользователь сканирует новый QR-код в аутентификаторе

# 4. Валидация: пользователь логинится с новым кодом
# 5. Старый emergency-код становится недействительным
```

**2. Для сервис-аккаунта:**
```bash
# Генерация секрета без интерактивного ввода
sudo -u svc-user google-authenticator -t -d -f -r 3 -R 30 -w 3 -Q none

# Извлечение секрета для импорта в менеджер (Vault/KMS)
SECRET=$(sed -n '1p' /home/svc-user/.google_authenticator)
vault kv put secret/mfa/svc-user secret=$SECRET

# Валидация: проверка кода через oathtool
oathtool --base32 --totp "$SECRET"
```

#### Резервное копирование и восстановление

**1. Бэкап секрета (odyssey):**
```bash
# Экспорт секрета в зашифрованный файл
sudo -u alice gpg --encrypt --recipient ops@example.com \
  --output /backup/mfa/alice.$(date +%Y%m%d).google_authenticator.gpg \
  /home/alice/.google_authenticator

# Или экспорт в Vault
vault kv put secret/mfa-backup/alice \
  secret=@<(sed -n '1p' /home/alice/.google_authenticator)

# Валидация бэкапа: расшифровать и проверить код
sudo -u alice oathtool --base32 --totp "$(gpg --decrypt /backup/mfa/alice.*.gpg | sed -n '1p')"
```

**2. Восстановление после потери устройства:**
```bash
# 1. Проверить наличие emergency-кода в ~/.google_authenticator
grep "^[0-9]\{8\}$" /home/alice/.google_authenticator | head -5
# → 12345678 90123456 ...

# 2. Войти используя emergency-код вместо TOTP

# 3. После входа — сгенерировать новый секрет (см. ротацию)
```

**3. Проверка целостности:**
```bash
# Убедиться, что файл имеет правильные права
stat -c '%a %U' /home/alice/.google_authenticator  # → 600 alice
```

#### Break-glass (аварийный доступ)

При полной потере доступа к TOTP и emergency-кодам:

1. На втором терминале (IPMI/KVM/console) выполнить вход по ключу без MFA
2. Отключить PAM TOTP временно:
   ```bash
   # Закомментировать строку в /etc/pam.d/sshd
   sed -i 's/^auth required pam_google_authenticator/#auth required pam_google_authenticator/' /etc/pam.d/sshd
   ```
3. Восстановить доступ пользователю
4. После восстановления — включить обратно и сгенерировать новые секреты

## Масштабирование TOTP в корпоративной среде

### Корпоративное управление OTP-секретами

Для инфраструктур >100 хостов ручная настройка MFA через PAM неэффективна.
- **HashiCorp Vault:** Централизованное хранение OTP-секретов с политиками доступа (Sentinel). Поддерживает генерацию TOTP-кодов через API `vault/totp`.
- **Ansible:** Автоматизация настройки `libpam-google-authenticator` на managed-хостах. Пример:
  ```yaml
  - name: Установить Google Authenticator PAM
    ansible.builtin.apt:
      name: libpam-google-authenticator
      state: present

  - name: Убедиться, что pam_google_authenticator включён в sshd
    ansible.builtin.lineinfile:
      path: /etc/pam.d/sshd
      regexp: '^auth.*pam_google_authenticator.so'
      line: 'auth required pam_google_authenticator.so nullok'

  - name: Включить KbdInteractive в sshd_config
    ansible.builtin.lineinfile:
      path: /etc/ssh/sshd_config
      regexp: '^KbdInteractiveAuthentication'
      line: 'KbdInteractiveAuthentication yes'

  - name: Требовать ключ + TOTP для группы admins
    ansible.builtin.blockinfile:
      path: /etc/ssh/sshd_config
      marker: '# {mark} ANSIBLE Managed TOTP for admins'
      block: |
        Match Group admins
            AuthenticationMethods publickey,keyboard-interactive

  - name: Валидация конфигурации SSH
    ansible.builtin.command: sshd -t
    changed_when: false
    check_mode: false

  - name: Перезапустить sshd (только если валидация прошла)
    ansible.builtin.systemd:
      name: ssh
      state: restarted
      enabled: true
  ```
  **Важно:** Ansible не генерирует секреты пользователей — это должен делать пользователь через `google-authenticator`. Для централизованной генерации секретов используйте [HashiCorp Vault](../../Vault/concepts.md) с TOTP secrets engine.
- **Ansible Semaphore:** Поддержка TOTP для локальных учетных записей (см. [Ansible: установка Semaphore](../../Ansible/ansible_semaphore.md)).
- **FreeIPA / IdM:** Централизованное управление OTP-политиками через Ansible роли `ipaclient` (см. [Ansible Identity Management](../../Ansible/ansible-identity-management.md)).

### Rate Limiting на стороне приложения

TOTP-код проверяется на сервере приложения (а не только через PAM). Убедитесь, что приложение ограничивает количество попыток.
- **Nginx/Angie:** `limit_req_zone` для эндпоинта `/api/mfa/verify`.
- **WAF:** Блокировка IP после 5 неудачных попыток.
- **fail2ban:** Фильтр `google_authenticator` в `/etc/fail2ban/filter.d/`.

## Дополнительная информация

### Инструменты

- **oathtool (oath-toolkit):** CLI-генерация и проверка TOTP/HOTP кодов. Используется для отладки и эксплуатации.
- **Bitwarden / Vault:** Корпоративное управление OTP-секретами.
- **Yubico Authenticator:** Хранение OTP-ключей на физическом токене (невозможно извлечь программно).
- **Aegis / Raivo:** Рекомендуемые Open Source приложения для Android/iOS.
- **pamtester:** Тестирование PAM-конфигурации без реального входа.
- **logcheck / swatch:** Автоматическая реакция на паттерны MFA-атак в реальном времени.

### Связанные темы

- [Аутентификация vs Авторизация](./authentication_vs_authorization.md) — основы процессов.
- [Kerberos](./kerberos.md) — интеграция MFA в доменные структуры.
- [Атаки перебором (Brute Force)](./brute_force_attacks.md) — роль MFA в защите от автоматизированных атак.
- [PAM — обзор](../../Linux/Security/pam_overview.md) — глубокая интеграция MFA через PAM, диагностика, faillock.
- [SSH — контроль доступа](../../Linux/Security/ssh/server/ssh_access_control.md) — практический сценарий 2FA через PAM для SSH.
- [Удаленный доступ к серверам](../../Linux/SystemAdministration/remote_access.md) — сравнение методов аутентификации (ключи, сертификаты, MFA, FIDO2).
- [HashiCorp Vault](../../Vault/concepts.md) — централизованное хранение OTP-секретов и политики TOTP.
- [Chrony](../../Linux/Core/systemd/time_synchronization.md) — синхронизация времени для TOTP.
- [Ansible Identity Management](../../Ansible/ansible-identity-management.md) — автоматизация настройки MFA в доменах FreeIPA/AD.
- [fail2ban](../../Linux/Security/Tools/fail2ban.md) — защита от brute-force на уровне PAM и SSH.
