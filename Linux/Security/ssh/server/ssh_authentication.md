# SSH — методы аутентификации

## Определения

**SSH-аутентификация** — процесс подтверждения личности пользователя (клиента) при подключении к SSH-серверу. Протокол SSH поддерживает несколько механизмов проверки, которые могут использоваться как по отдельности, так и в комбинации (Multi-Factor Authentication).

**Пара ключей (Key Pair)** — основа асимметричного шифрования в SSH. Состоит из двух файлов:
- **Приватный ключ (Private Key)** — секретный файл, хранящийся на стороне клиента. Никогда не передается по сети.
- **Публичный ключ (Public Key)** — открытая часть, которая размещается на сервере (обычно в `~/.ssh/authorized_keys`).

**Аутентификация по ключам (Public Key Authentication)** — метод, при котором сервер проверяет владение приватным ключом через криптографическое «рукопожатие» (handshake). Это исключает передачу паролей и защищает от атак перебором.

#### Механизм защиты от повторов (Anti-Replay)
При аутентификации клиент подписывает своим закрытым ключом блок данных, в который обязательно включается **Session ID** (идентификатор сессии).
*   **Session ID** — уникальная строка, генерируемая во время обмена ключами (KEX).
*   Поскольку Session ID уникален для каждого соединения, подпись клиента действительна **только один раз** и только для текущей сессии.
*   Злоумышленник, перехвативший подпись, не сможет использовать её для входа в другую сессию или на другой сервер, так как там будет другой Session ID.

**Опция `restrict`** — современная директива в `authorized_keys`, которая одновременно отключает все потенциально опасные возможности (проброс портов, агента, X11, TTY, туннелирование), эффективно заменяя набор `no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty,no-user-rc`.

**`permitopen="host:port"`** — разрешает проброс портов (`AllowTcpForwarding`) только к указанным хостам/портам. Может встречаться несколько раз для списка разрешенных направлений.

**`cert-authority`** — тип ключа в `~/.ssh/known_hosts`, помечающий ключ как подпись центра сертификации (CA). При наличии такой записи клиент автоматически доверяет хостам, сертификаты которых подписаны этим CA.

**`no-user-rc`** — запрещает выполнение файла `~/.ssh/rc` при входе пользователя. Полезно для учетных записей автоматизации, чтобы предотвратить побочные эффекты от пользовательских скриптов.

**`AuthorizedKeysFile`** — директива `sshd_config`, задающая путь к файлу с разрешенными ключами. Поддерживает шаблоны: `%u` (пользователь), `%h` (домашняя директория), `%n` (имя хоста).

**`AuthorizedKeysCommand`** — директива `sshd_config`, позволяющая динамически запрашивать публичные ключи через внешнюю команду (например, из LDAP, SSSD, API). Вместо чтения файла `authorized_keys` сервер вызывает указанную программу.

**`TrustedUserCAKeys`** — директива `sshd_config`, указывающая файл с публичным ключом CA. Сервер доверяет любым сертификатам, подписанным этим CA, и не требует явных записей в `authorized_keys`.

**`known_hosts`** — файл клиента (`~/.ssh/known_hosts` или `/etc/ssh/ssh_known_hosts`), содержащий отпечатки ключей хостов, к которым пользователь подключался. Предотвращает атаки man-in-the-middle (MITM).

**`StrictHostKeyChecking`** — параметр клиента SSH, управляющий проверкой ключей хостов:
- `no` — автоматически добавлять новые ключи (небезопасно, уязвимо к MITM).
- `yes` —拒絕 новые ключи, требуя явного добавления в `known_hosts`.
- `accept-new` — автоматически добавлять новые ключи, но отклонять измененные (средняя безопасность).

**`ProxyJump` (`-J`)** — клиентская опция для подключения через промежуточный хост (bastion/jump host) без необходимости настраивать `ProxyCommand` вручную.

**`ForwardAgent`** — проброс SSH-агента клиента на удаленный сервер. Позволяет использовать локальные ключи на промежуточных хостах, но создает риск кражи сокета агента при компрометации промежуточного узла.

**SSH-агент (`ssh-agent`)** — фоновый процесс, кэширующий расшифрованные приватные ключи. Позволяет не вводить пароль от ключа при каждом подключении. Сокет агента (`SSH_AUTH_SOCK`) должен быть защищен (права 700, владелец пользователя).

## Основные концепции

### Поддерживаемые методы аутентификации

| Метод | Описание | Безопасность |
| :--- | :--- | :--- |
| **publickey** | Аутентификация по ключам (ED25519, RSA, ECDSA, FIDO2). | **Высокая** (рекомендуется) |
| **password** | Проверка системного пароля пользователя. | **Низкая** (уязвимо к brute-force) |
| **gssapi-with-mic** | Интеграция с Kerberos/Active Directory (Single Sign-On). | **Высокая** (для доменных сред) |
| **keyboard-interactive** | Интерактивный ввод (используется для TOTP/MFA через PAM). | **Высокая** (с MFA) |
| **challenge-response** | Устаревший синоним для keyboard-interactive. | Зависит от бекенда |

### Типы SSH-ключей и алгоритмы (Стандарты 2026)

| Тип | Длина | Особенности | Рекомендация |
| :--- | :--- | :--- | :--- |
| **ED25519** | 256 бит | Быстрый, безопасный, компактный. | **Основной стандарт** |
| **ED25519-SK** | 256 бит | Ключ, привязанный к аппаратному токену (FIDO2). | **Для критических узлов** |
| **ML-KEM** | 768+ бит | Постквантовый алгоритм (OpenSSH 9.8+). | **Перспективный стандарт** |
| **RSA** | 4096 бит | Высокая совместимость. | Только для старых систем |
| **ECDSA** | 256–521 бит | Быстрый, использует эллиптические кривые NIST. | Допустимо |

### Детальный разбор authorized_keys

Файл `~/.ssh/authorized_keys` — это Single Source of Truth для разрешенных ключей конкретного пользователя.

#### Формат записи
```bash
[опции] <тип_ключа> <тело_публичного_ключа> <комментарий>
```

#### Опции ограничения доступа
Опции указываются в начале строки и позволяют реализовать гранулярный контроль:
- `from="192.168.1.0/24"` — разрешить использование ключа только из этой сети.
- `command="/usr/local/bin/backup.sh"` — принудительно запускать только этот скрипт (ForceCommand).
- `expiry-time="20261231"` — ключ перестанет приниматься после указанной даты.
- `no-port-forwarding,no-agent-forwarding` — запрет проброса портов и агента.
- `restrict` — отключить все опасные возможности одновременно (проброс портов, X11, PTY, агент, туннели, `user-rc`). Рекомендуется для учетных записей автоматизации.
- `permitopen="host:port"` — разрешить проброс портов только к указанному хосту/порту. Можно указать несколько раз.
- `cert-authority` — используется в `known_hosts`, помечает ключ как доверенный CA.
- `no-user-rc` — запретить выполнение `~/.ssh/rc` при входе.

#### Масштабирование и управление (Enterprise)
При росте парка серверов ручное управление `authorized_keys` становится невозможным. Решения:
1.  **AuthorizedKeysCommand**: Директива в `sshd_config`, позволяющая запрашивать ключи из внешних источников (LDAP, БД, API).
    ```ssh
    AuthorizedKeysCommand /usr/bin/sss_ssh_authorizedkeys
    AuthorizedKeysCommandUser sssd
    ```
2.  **SSH CA (Certificates)**: Использование центра сертификации. Сервер доверяет подписи CA, а не отдельным ключам. Подробнее: [SSH-аутентификация по сертификатам](./ssh_certificate_authentication.md).
3.  **Централизация (LDAP/FreeIPA)**: Хранение ключей в атрибутах пользователя в каталоге. См. [LDAP и SSSD](../../../SystemAdministration/Users/LDAP_SSSD/index.md).

### Директивы сервера: AuthorizedKeysFile и шаблоны

Директива `AuthorizedKeysFile` позволяет использовать переменные для путей к файлам ключей:

```ssh
# Стандартный путь
AuthorizedKeysFile .ssh/authorized_keys

# С шаблонами (поддержка %u — пользователь, %h — домашняя директория, %n — имя хоста)
AuthorizedKeysFile /etc/ssh/authorized_keys/%u
AuthorizedKeysFile /etc/ssh/authorized_keys/%u/%n
```

Это особенно полезно в средах с NFS/automount, где домашние директории могут быть недоступны в момент аутентификации.

### Директивы сервера: AuthorizedKeysCommand

Для динамического получения ключей из внешних источников:

```ssh
# Получение ключей через SSSD (LDAP/AD)
AuthorizedKeysCommand /usr/bin/sss_ssh_authorizedkeys
AuthorizedKeysCommandUser sssd

# Получение ключей через пользовательский скрипт (API, БД)
AuthorizedKeysCommand /usr/local/bin/get-ssh-keys.sh %u
AuthorizedKeysCommandUser nobody
```

**Важные ограничения:**
- Команда выполняется от имени `AuthorizedKeysCommandUser` (не root).
- Тайм-аут команды ограничен (по умолчанию 10 секунд в OpenSSH 9.x). Большое количество пользователей может привести к замедлению аутентификации.
- Если команда возвращает не-0, аутентификация завершается ошибкой (ключ не найден).

### Директивы сервера: TrustedUserCAKeys

Для инфраструктуры с центром сертификации (SSH CA):

```ssh
# Доверие подписям CA для пользовательских сертификатов
TrustedUserCAKeys /etc/ssh/ca_user.pub

# Необязательно: требовать principals из определенного файла
# (позволяет дополнительно ограничивать список разрешенных логинов)
TrustedUserCAKeys /etc/ssh/ca_user.pub
```

При использовании `TrustedUserCAKeys` записи в `authorized_keys` для этих пользователей не требуются. Полная документация: [SSH-аутентификация по сертификатам](./ssh_certificate_authentication.md).

### Верификация ключей хостов (Host Key Verification)

Клиент SSH должен проверять подлинность сервера для предотвращения атак man-in-the-middle.

#### Файл known_hosts

Файл `~/.ssh/known_hosts` (или глобальный `/etc/ssh/ssh_known_hosts`) содержит отпечатки ключей доверенных хостов.

**Формат:**
```
[host] [type] [key-body] [comment]
web01.example.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...
```

**Хеширование хостов (Privacy):**
```bash
# Создать хешированную запись (скрывает IP/имя хоста от злоумышленников с доступом к файлу)
ssh-keyscan -H web01.example.com >> ~/.ssh/known_hosts
```

#### Директива StrictHostKeyChecking

```bash
# Клиентский конфиг (~/.ssh/config или ssh -o)
StrictHostKeyChecking yes       # Жесткая проверка (рекомендуется для production)
StrictHostKeyChecking accept-new # Автодобавление новых, отклонение измененных
StrictHostKeyChecking no         # Отключить проверку (опасно, уязвимо к MITM)
```

#### Подключение через Bastion (ProxyJump)

```bash
# Одиночный прыжок через bastion
ssh -J bastion.example.com web01.example.com

# Цепочка прыжков
ssh -J bastion1.example.com,bastion2.example.com web01.example.com

# Конфигурация в ~/.ssh/config
Host web01
  HostName web01.example.com
  ProxyJump bastion.example.com
  User deploy
```

### Безопасность SSH-агента

SSH-агент хранит расшифрованные приватные ключи в памяти. При компрометации сессии злоумышленник может получить доступ к агенту.

```bash
# Добавление ключа в агент с ограниченным временем жизни (1 час)
ssh-add -t 1h ~/.ssh/id_ed25519

# Добавление ключа с подтверждением перед каждым использованием (macOS Keychain)
ssh-add -K ~/.ssh/id_ed25519

# Просмотр загруженных ключей и их Fingerprints
ssh-add -l

# Удаление конкретного ключа
ssh-add -d ~/.ssh/id_ed25519.pub

# Удаление всех ключей
ssh-add -D
```

**ForwardAgent:**
```bash
# Опасно: проброс агента на удаленный хост
ssh -A user@web01.example.com

# Если проброс необходим, ограничьте целевые хосты в ~/.ssh/config:
Host web01
  ForwardAgent yes
  # Дополнительно: разрешить только для конкретного хоста
```

### Валидация ключей и отпечатки

```bash
# Проверка отпечатка (fingerprint) публичного ключа
ssh-keygen -l -f ~/.ssh/id_ed25519.pub
# → MD5:ab:cd:ef:... SHA256:nThbg6kXUpJWGl7E1IGOCspRomTxdCARLviKw6E5SY8

# Проверка наличия хоста в known_hosts
ssh-keygen -F web01.example.com
# →Found matching host key: /Users/user/.ssh/known_hosts:42

# Сканирование ключей хоста (для начального заполнения known_hosts)
ssh-keyscan -p 2222 web01.example.com >> ~/.ssh/known_hosts

# Проверка целостности ключа (тип, длина)
ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub
```

### Контроль прав доступа (StrictModes)

SSH-сервер игнорирует ключи, если права доступа к файлам или директориям позволяют запись другим пользователям (Group/Others Write).

| Путь | Права | Владелец | Описание |
| :--- | :--- | :--- | :--- |
| `~/.ssh/` | `700` | Пользователь | Каталог конфигурации |
| `~/.ssh/authorized_keys` | `600` | Пользователь | Список доверенных ключей |
| `~/.ssh/id_*` | `600` | Пользователь | Приватные ключи (Секретно!) |
| `~/.ssh/id_*.pub` | `644` | Пользователь | Публичные ключи |
| `~/.ssh/config` | `600` | Пользователь | Конфигурация клиента |
| `/etc/ssh/ssh_host_*_key` | `600` | `root` | Приватные ключи сервера |
| `/etc/ssh/ssh_host_*_key.pub` | `644` | `root` | Публичные ключи сервера |

## Практические сценарии

### Сценарий 1: Генерация и установка ключа ED25519

**Задача:** Создать современный ключ и настроить доступ.

```bash
# 1. Генерация (без пароля для автоматизации или с ним для безопасности)
ssh-keygen -t ed25519 -C "admin@workstation" -f ~/.ssh/id_ed25519_work

# 2. Установка через стандартную утилиту
ssh-copy-id -i ~/.ssh/id_ed25519_work.pub user@remote-server

# 3. Резервный ручной метод (если ssh-copy-id нет)
cat ~/.ssh/id_ed25519_work.pub | ssh user@remote-server "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

### Сценарий 2: Отключение входа по паролю (Hardening)

**Задача:** Запретить небезопасную аутентификацию после настройки ключей.

```bash
# В файле /etc/ssh/sshd_config:
# 1. Отключаем пароли
PasswordAuthentication no
# 2. Отключаем пустые пароли
PermitEmptyPasswords no
# 3. Отключаем интерактивные методы (если не используется MFA)
KbdInteractiveAuthentication no

# Перезапуск службы
sudo systemctl restart sshd
```

### Сценарий 3: Защита ключа кодовой фразой (Passphrase)

**Задача:** Использовать `ssh-agent`, чтобы не вводить длинный пароль от ключа при каждом входе.

```bash
# Добавление ключа в агент (действует до закрытия сессии)
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519_work

# Проверка загруженных ключей
ssh-add -l
```

### Сценарий 4: Аутентификация через аппаратный токен (FIDO2)

**Задача:** Создать ключ, который работает только при наличии Yubikey.

```bash
# Требуется OpenSSH 8.2+ и токен с поддержкой FIDO2
ssh-keygen -t ed25519-sk -O resident -C "yubikey-auth"

# При подключении сервер потребует физического подтверждения (нажатия на кнопку)
```

### Сценарий 5: Ограничение rsync через rrsync

**Задача:** Разрешить пользователю `backup` выполнять только `rsync` в read-only режиме из определенной сети, без доступа к shell.

**Запись в `~/.ssh/authorized_keys` пользователя `backup`:**
```text
from="10.0.5.10",command="/usr/bin/rrsync -ro /home/backup/data/",no-pty,no-port-forwarding,no-agent-forwarding ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... backup-key
```

**Требования:**
- Установите `rrsync` (обычно входит в `rsync` или отдельный пакет).
- Директория `/home/backup/data/` должна существовать и иметь права, достаточные для чтения.
- Пользователь `backup` должен иметь валидный shell в `/etc/passwd` (например, `/usr/sbin/nologin` не подойдет для `rrsync` без доработки, обычно `/bin/sh` или `/bin/bash`).

### Сценарий 6: SFTP-only пользователь с chroot jail

**Задача:** Создать пользователя `sftpuser`, который может загружать файлы только в `/sftp/data` и не имеет доступа к SSH-шеллу.

```bash
# 1. Создание пользователя без shell
sudo useradd -m -d /sftp/data -s /usr/sbin/nologin sftpuser

# 2. Настройка sshd_config
sudo tee -a /etc/ssh/sshd_config << 'EOF'

# SFTP-only с chroot
Match Group sftpusers
    ChrootDirectory /sftp/%u
    ForceCommand internal-sftp
    X11Forwarding no
    AllowTcpForwarding no
    PasswordAuthentication no
    PubkeyAuthentication yes
    PermitTunnel no
EOF
```

> **Важно:** `ChrootDirectory` требует, чтобы целевая директория и все её родительские компоненты принадлежали root и имели права не более `755`.

### Сценарий 7: CI/CD деплой-ключ с оборачивающим скриптом

**Задача:** Разрешить CI-системе (`deploy` пользователь) запускать только определенные команды деплоя с IP Jenkins/GitLab CI.

```bash
# 1. Создание оборачивающего скрипта
sudo tee /usr/local/bin/deploy-wrapper.sh << 'EOF'
#!/bin/bash
case "$SSH_ORIGINAL_COMMAND" in
    deploy-staging)
        /opt/deploy/deploy-staging.sh
        ;;
    deploy-prod)
        /opt/deploy/deploy-prod.sh
        ;;
    status)
        /opt/deploy/status.sh
        ;;
    *)
        echo "Command not allowed: $SSH_ORIGINAL_COMMAND"
        exit 1
        ;;
esac
EOF
sudo chmod 755 /usr/local/bin/deploy-wrapper.sh
sudo chown root:root /usr/local/bin/deploy-wrapper.sh

# 2. Запись в authorized_keys
echo 'from="192.168.10.0/24",command="/usr/local/bin/deploy-wrapper.sh",no-pty,no-port-forwarding,no-X11-forwarding,no-agent-forwarding ssh-ed25519 AAAAC3Nza... ci-deploy-key' | sudo tee -a /home/deploy/.ssh/authorized_keys
```

### Сценарий 8: Подключение через Bastion (Jump Host)

**Задача:** Настроить безопасный доступ к внутреннему серверу `web01` через `bastion.example.com` без проброса агента.

```bash
# Вариант 1: CLI
ssh -J deploy@bastion.example.com deploy@web01.example.com

# Вариант 2: ~/.ssh/config
cat >> ~/.ssh/config << 'EOF'
Host bastion
  HostName bastion.example.com
  User deploy
  Port 2239
  IdentityFile ~/.ssh/id_ed25519_bastion

Host web01
  HostName 10.0.1.10
  User deploy
  ProxyJump bastion
  IdentityFile ~/.ssh/id_ed25519_web01
  # Запретить X11 и проброс портов на конечном хосте
  X11Forwarding no
  AllowTcpForwarding no
EOF
```

### Сценарий 9: Emergency Break-Glass аккаунт

**Задача:** Создать аварийный аккаунт `breakglass` с доступом только при включении `PermitRootLogin` и защищенный аппаратным токеном.

```bash
# 1. Генерация ключа на YubiKey (с touch-required)
ssh-keygen -t ed25519-sk -O resident -O verify-required -C "breakglass" -f ~/.ssh/breakglass_sk

# 2. Размещение публичного ключа в authorized_keys root
sudo mkdir -p /root/.ssh
sudo chmod 700 /root/.ssh
cat ~/.ssh/breakglass_sk.pub | sudo tee -a /root/.ssh/authorized_keys
sudo chmod 600 /root/.ssh/authorized_keys

# 3. В sshd_config — только на случай аварии!
# PermitRootLogin prohibit-password
# (разрешает вход по ключам, но не по паролю)

# 4. Мониторинг: любое использование breakglass должно создавать алерт
# В /etc/pam.d/sshd добавьте:
# pam_exec.so /usr/local/bin/alert-breakglass.sh
```

### Сценарий 10: Ротация SSH-ключей и аудит

**Задача:** Автоматизировать проверку и замену старых ключей на всех managed-хостах.

```bash
# 1. Аудит текущих ключей (поиск RSA < 4096 бит, устаревших алгоритмов)
for key in ~/.ssh/id_*; do
    [ -f "$key" ] || continue
    [ "$key" = "${key}.pub" ] && continue
    echo "=== $key ==="
    ssh-keygen -l -f "$key"
    # Проверка алгоритма
    ssh-keygen -l -f "${key}.pub" | awk '{print $4}' | grep -qE 'rsa|ssh-rsa' && echo "WARN: RSA detected"
done

# 2. Проверка хостовых ключей на соответствие политике
sudo sshd -T | grep -i hostkeyalgorithms

# 3. Запуск ssh-audit для проверки шифров
ssh-audit localhost

# 4. Проверка authorized_keys на устаревшие записи (RSA SHA-1)
grep -r 'ssh-rsa' ~/.ssh/authorized_keys /etc/ssh/authorized_keys/ 2>/dev/null | grep -v 'rsa-sha2'
```

## Дополнительная информация

### Диагностика проблем аутентификации

Если доступ отклонен (`Permission denied`), выполните следующие шаги:

1.  **Клиентская отладка:** Запустите с флагом `-vvv` для просмотра процесса согласования методов.
    ```bash
    ssh -vvv user@server
    ```
2.  **Серверные логи:** Изучите сообщения демона `sshd`.
    ```bash
    tail -f /var/log/auth.log # Debian/Ubuntu
    tail -f /var/log/secure   # RHEL/CentOS
    sudo journalctl -u sshd --since "10 minutes ago" | grep -E "Failed|refused|match|denied|invalid user"
    ```
3.  **Проверка эффективного конфига:**
    ```bash
    sudo sshd -T | grep -E "pubkeyauthentication|passwordauthentication|permitroot|authenticationmethods|maxauthtries|loglevel"
    ```
4.  **Проверка прав и прав доступа (StrictModes):**
    ```bash
    namei -mo /home/user/.ssh/authorized_keys
    # Ожидается: drwx------ . ssh/ authorized_keys (600)
    ls -la /home/user/.ssh/
    ```
5.  **Проверка отпечатка ключа:**
    ```bash
    ssh-keygen -l -f ~/.ssh/id_ed25519.pub
    ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub
    ```
6.  **Проверка known_hosts:**
    ```bash
    ssh-keygen -F server.example.com
    # Если хост отсутствует — добавьте вручную или через ssh-keyscan
    ```

### Типичные ошибки и решения

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Bad owner or permissions on /home/user/.ssh/authorized_keys` | Права открыты (например, 644) или владелец root | `chown user:user ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys` |
| `Could not chdir to home directory` | SELinux-контекст некорректен или домашняя директория недоступна | `restorecon -Rv /home/user` (SELinux) или проверить права на `/home/user` |
| `Connection closed by authenticating user` | `AuthenticationMethods` не совпадает с доступными методами | Проверить `sshd -T -C` и конфигурацию PAM |
| `Received disconnect from ...: 11: Bye Bye [preauth]` | `ForceCommand` возвращает не-0 или ключ отклонен `authorized_keys` | Проверить журналы и синтаксис `authorized_keys` |
| `UNREACHABLE! Permission denied (publickey)` в Ansible | `PermitRootLogin no` и подключение идет от root | Указать `ansible_user=deploy` в инвентаре или добавить ключ для root |
| `Host key verification failed` | Хост не в `known_hosts` или его ключ изменился | `ssh-keyscan host >> ~/.ssh/known_hosts` или проверить целостность сервера |
| `Agent admitted failure to sign` | Агент не имеет нужного ключа или ключ защищен паролем | `ssh-add -l` для проверки, `ssh-add ~/.ssh/id_ed25519` для добавления |

### Рекомендации по безопасности

1.  **Приоритет ключей:** Используйте ED25519 как основной тип. ED25519-SK (FIDO2) для критических узлов. RSA-4096 только для совместимости со старыми системами.
2.  **Отключите пароли:** После настройки ключей установите `PasswordAuthentication no`.
3.  **Используйте `restrict`:** Для учетных записей автоматизации применяйте `restrict` в `authorized_keys` вместо отдельных флагов.
4.  **Ротация ключей:** Планируйте замену ключей раз в 6–12 месяцев. Для короткоживущих ключей используйте SSH CA.
5.  **Хранилище ключей:** Приватные ключи должны храниться на encrypted volumes (FileVault, LUKS) или аппаратных токенах (YubiKey).
6.  **Избегайте ForwardAgent:** Используйте `ProxyJump` вместо `ForwardAgent` для доступа через bastion.
7.  **Хранилище known_hosts:** Используйте `hash_host: yes` в Ansible или `ssh-keyscan -H` для хеширования имен хостов.
8.  **MaxAuthTries:** Установите `MaxAuthTries 3` для ограничения попыток перебора.
9.  **Агент с тайм-аутом:** Используйте `ssh-add -t 1h` для ограничения времени жизни ключей в агенте.
10. **Аудит:** Регулярно проверяйте `authorized_keys` на нежелательные ключи. Используйте `ssh-audit` для проверки шифров и алгоритмов.
11. **Отпечатки:** При первом подключении к новому хосту всегда проверяйте fingerprint через независимый канал (не через тот же SSH-сеанс).

### Крайние случаи и ограничения

| Случай | Поведение / Риск | Рекомендация |
| :--- | :--- | :--- |
| **AuthorizedKeysCommand с большим парком (>1000 пользователей)** | Тайм-аут 10 секунд может привести к отказам в обслуживании | Используйте кэширование (SSSD cache) или SSH CA |
| **NFS / automount для домашних директорий** | `AuthorizedKeysFile` может указывать на недоступный путь в момент аутентификации | Используйте `AuthorizedKeysCommand` или статические пути вне NFS |
| **ChrootDirectory с NFS / CIFS** | Монтирование сети внутрь chroot ненадежно | Только локальные файловые системы |
| **FIDO2 ключи без touch-required** | Злоумышленник с физическим доступом к токену может использовать ключ без подтверждения | Всегда используйте `-O verify-required` при генерации SK-ключей |
| **Агент через tmux/screen** | Сокет `SSH_AUTH_SOCK` может стать недоступен после отсоединения | Используйте `tmux` с поддержкой переменных окружения или `keychain` |
| **StrictHostKeyChecking no в CI/CD** | Уязвимость к MITM-атакам при первом подключении к новому хосту | Используйте `accept-new` или предварительно заполняйте `known_hosts` через `ssh-keyscan` |
| **AuthorizedKeysFile с %h на недоступном automount** | Аутентификация завершится ошибкой до монтирования домашней директории | Используйте абсолютные пути или `AuthorizedKeysCommand` |
| **Ротация ключей без инвентаря** | Старые ключи остаются в `authorized_keys` уволенных сотрудников | Ведите реестр ключей; используйте `exclusive: true` в Ansible для управления |

### См. также

- [SSH Server Security Overview](./ssh_server_security_overview.md) — общая стратегия защиты.
- [SSH Hardening Best Practices](./ssh_hardening_best_practices.md) — настройки алгоритмов и KEX.
- [SSH Access Control](./ssh_access_control.md) — лимиты по IP и пользователям, `Match`-блоки, `ForceCommand`.
- [SSH Certificate Authentication](./ssh_certificate_authentication.md) — работа с SSH CA, `TrustedUserCAKeys`, principals.
- [Инструменты сетевого мониторинга](../../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для анализа SSH-трафика
- [PAM: обзор и настройка](../../pam_overview.md) — глубокая интеграция MFA через PAM.
- [MFA и TOTP](../../../../Security/Concepts/mfa_totp.md) — теория многофакторной аутентификации и настройка Google Authenticator.
- [SSH Troubleshooting](../../ssh/ssh_troubleshooting.md) — диагностика неполадок подключения.
- [Управление SSH-ключами через Ansible](../../../../Ansible/ansible_ssh_key_management.md) — автоматизация развертывания ключей.
- [rsync: синхронизация файлов](../../../../Linux/SystemAdministration/rsync.md) — использование `rrsync` для ограниченного доступа.
- [LDAP и SSSD](../../../SystemAdministration/Users/LDAP_SSSD/index.md) — централизация управления ключами и пользователями.
- [Kerberos: основы аутентификации](../../../../Security/Concepts/kerberos.md) — работа с билетами и GSSAPI.
- [Fail2Ban](../../../../Linux/Security/Tools/fail2ban.md) — автоматическая блокировка атакующих.
