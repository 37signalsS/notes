# SSH — лучшие практики укрепления безопасности (Hardening)

## Определения

**SSH Hardening (Закалка SSH)** — комплекс мер по усилению безопасности SSH-сервера: отключение неиспользуемых функций, ограничение методов аутентификации, настройка криптографических параметров и мониторинг для защиты от автоматизированных и направленных атак. В контексте DevOps/SRE hardening включает интеграцию с системами управления конфигурацией, CI/CD пайплайнами и централизованным мониторингом.

**Defense in Depth (Эшелонированная защита)** — принцип многослойной защиты, при котором компрометация одного уровня (например, подбор пароля) не дает полного доступа к системе благодаря другим барьерам (например, 2FA или ограничение прав пользователя). Для SSH применяется на 4 уровнях: сетевой (firewall, port knocking), транспортный (TLS/SSH версии), прикладной (sshd_config, PAM), операционный (аудит, rotation, compliance).

**Post-Quantum Cryptography (PQC)** — криптография, устойчивая к атакам квантовых компьютеров. В современных реализациях SSH (OpenSSH 9.8+) используются гибридные схемы, сочетающие классические алгоритмы (X25519) и постквантовые (ML-KEM/Kyber). Гибридный подход обеспечивает безопасность даже при взломе одного из компонентов.

**Zero Trust SSH** — архитектурный подход, при котором доступ предоставляется на основе динамической оценки доверия (identity, device posture, context) а не статического сетевого расположения. Реализуется через SSH CA, кратковременные сертификаты и Policy Decision Points.

**Compliance Hardening** — приведение конфигурации SSH в соответствие с отраслевыми стандартами (CIS Benchmarks, DISA STIG, PCI DSS, NIST 800-53) через автоматизированную проверку и исправление отклонений.

## Основные концепции

### Уровни защиты SSH

Безопасность SSH должна выстраиваться на нескольких эшелонах:

| Уровень | Механизм | Описание |
| :--- | :--- | :--- |
| **Сетевой** | Файрвол (nftables/iptables) | Ограничение доступа по IP, rate limiting новых соединений. |
| **Транспортный** | Port Knocking / SPA | Скрытие порта от сканеров до прохождения первичной проверки. |
| **Прикладной** | `sshd_config` | Тонкая настройка демона (аутентификация, шифры, таймауты). |
| **Системный** | systemd hardening, seccomp | Изоляция процесса sshd, ограничение syscalls, drop capabilities. |
| **Операционный** | Аудит, ротация ключей, CI/CD | Непрерывная проверка соответствия, автоматизация обновлений. |
| **Мониторинг** | fail2ban, аудит, SIEM | Блокировка атакующих на основе анализа логов и аудит конфига. |

### Ключевые директивы sshd_config

#### Аутентификация и контроль доступа

| Директива | Рекомендуемое значение | Описание |
| :--- | :--- | :--- |
| **`PubkeyAuthentication`** | `yes` | [Вход по ключам](./ssh_authentication.md) — основной метод. |
| **`PasswordAuthentication`** | `no` | Полное отключение паролей для защиты от brute-force. |
| **`PermitRootLogin`** | `no` | Запрет прямого входа root. Альтернатива: `prohibit-password`. |
| **`MaxAuthTries`** | `3` | Максимальное число попыток аутентификации на одну сессию. |
| **`PermitEmptyPasswords`** | `no` | Запрет входа пользователям без пароля. |
| **`AllowUsers`** | `user1 user2` | [Белый список пользователей](./ssh_access_control.md) (явное разрешение). |
| **`AuthenticationMethods`** | `publickey` | Требовать именно этот метод (можно указать `publickey,keyboard-interactive` для MFA). |
| **`KbdInteractiveAuthentication`** | `no` | Отключение интерактивных методов (если не используется MFA). |
| **`AuthorizedKeysFile`** | `.ssh/authorized_keys .ssh/authorized_keys2` | Пути к файлам ключей; поддерживает шаблоны `%u`, `%h`, `%n`. |
| **`AuthorizedKeysCommand`** | `/usr/bin/sss_ssh_authorizedkeys` | Динамическое получение ключей из LDAP/AD (Enterprise). |
| **`AuthorizedKeysCommandUser`** | `sssd` | Пользователь для выполнения AuthorizedKeysCommand. |
| **`TrustedUserCAKeys`** | `/etc/ssh/ca_user.pub` | [SSH CA](./ssh_certificate_authentication.md) — доверие к сертификатам. |
| **`RevokedKeys`** | `/etc/ssh/revoked_keys` | Список отозванных ключей/сертификатов (KRL). |

#### Сетевые и системные настройки

| Директива | Рекомендуемое значение | Описание |
| :--- | :--- | :--- |
| **`Port`** | Нестандартный (напр. `2239`) | [Смена порта](./ssh_access_control.md) для снижения фонового шума ботов. |
| **`ListenAddress`** | Конкретный IP | Привязка демона только к определенному интерфейсу. |
| **`LoginGraceTime`** | `30s` | Время ожидания завершения аутентификации. |
| **`ClientAliveInterval`** | `300` | Интервал проверки активности клиента (сек). |
| **`ClientAliveCountMax`** | `0` | Разрыв сессии сразу при отсутствии ответа на проверку. |
| **`MaxSessions`** | `2` | Максимальное количество открытых сессий на одно сетевое соединение. |
| **`MaxStartups`** | `10:30:60` | Ограничение параллельных неавторизованных соединений (защита от DoS). |
| **`AddressFamily`** | `inet` | Ограничение до IPv4 (если IPv6 не используется). |
| **`TCPKeepAlive`** | `no` | Отключение TCP keepalive в пользу `ClientAliveInterval` (на уровне SSH). |
| **`UseDNS`** | `no` | Отключение обратного DNS для ускорения входа и защиты от DoS. |
| **`GSSAPIAuthentication`** | `no` | Отключение Kerberos/GSSAPI если не используется в домене. |
| **`KerberosAuthentication`** | `no` | Отключение Kerberos аутентификации. |
| **`DebianBanner`** | `no` | Скрытие версии ОС в баннере (Debian/Ubuntu specific). |

#### Безопасность и логирование

| Директива | Рекомендуемое значение | Описание |
| :--- | :--- | :--- |
| **`LogLevel`** | `VERBOSE` | Логирование отпечатков ключей (Fingerprints) при входе. |
| **`Banner`** | `/etc/ssh/banner` | Предупреждающее сообщение для юр. защиты. |
| **`X11Forwarding`** | `no` | Запрет проброса X11 (предотвращение атак на графический стек). |
| **`AllowTcpForwarding`** | `no` | Запрет использования SSH как прокси/туннеля (если не требуется). |
| **`PermitTunnel`** | `no` | Запрет туннелирования на уровне L2/L3 (TUN/TAP). |
| **`AllowAgentForwarding`** | `no` | Запрет проброса SSH-агента (защита от кражи сокетов агента). |
| **`StrictModes`** | `yes` | Обязательная проверка прав доступа на файлы в `~/.ssh/`. |
| **`UsePAM`** | `yes` | Использование модулей PAM (необходимо для учета сессий и MFA). |
| **`IgnoreRhosts`** | `yes` | Игнорировать устаревшие файлы доверия `.rhosts`. |
| **`PermitUserEnvironment`** | `no` | Запрет пользователям задавать переменные окружения через `~/.ssh/environment`. |
| **`Compression`** | `delayed` | Сжатие только после аутентификации (защита от атак до входа). |
| **`ExposeAuthInfo`** | `no` | Не раскрывать информацию о методах аутентификации до входа. |
| **`FingerprintHash`** | `sha256` | Алгоритм хеширования для отпечатков ключей в логах. |

### Современные алгоритмы (Стандарты 2026)

Для обеспечения долгосрочной безопасности (включая защиту от квантовых угроз) следует ограничить поддерживаемые алгоритмы. Ниже приведены рекомендации для OpenSSH 9.8+ с поддержкой PQC.

#### 1. Полная конфигурация алгоритмов (Production-ready)

```ssh
# KexAlgorithms (Обмен ключами) — Приоритет ML-KEM и Ed25519
# Гибридные PQC алгоритмы в приоритете, затем классические
KexAlgorithms mlkem768x25519-sha256,sntrup761x25519-sha512@openssh.com,curve25519-sha256,curve25519-sha256@libssh.org

# HostKeyAlgorithms — Только безопасные типы хостовых ключей
# Ed25519 приоритетнее RSA; SHA-2 только для RSA
HostKeyAlgorithms ssh-ed25519,ssh-ed25519-cert-v01@openssh.com,rsa-sha2-512,rsa-sha2-256

# Ciphers (Шифрование) — Только современные AEAD шифры
# ChaCha20-Poly1305 предпочтительнее на CPU без AES-NI
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com

# MACs (Целостность) — Использовать только EtM (Encrypt-then-MAC)
# EtM варианты защищают от атак на порядок операций
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com,hmac-sha2-256

# PubkeyAcceptedAlgorithms — Какие типы ключей принимать от клиентов
PubkeyAcceptedAlgorithms ssh-ed25519,ssh-ed25519-cert-v01@openssh.com,rsa-sha2-512,rsa-sha2-256,sk-ssh-ed25519@openssh.com,sk-ssh-ed25519-cert-v01@openssh.com

# CASignatureAlgorithms — Алгоритмы подписи CA для сертификатов
CASignatureAlgorithms ssh-ed25519,rsa-sha2-512,rsa-sha2-256
```

#### 2. Совместимость с Legacy-системами (Fallback)

Если требуется поддержка старых клиентов (OpenSSH < 8.8, старые сетевые устройства), добавьте в конец списков:

```ssh
# Legacy KEX (только если обязательно)
KexAlgorithms +diffie-hellman-group-exchange-sha256

# Legacy Ciphers (AES-CBC с EtM — минимально приемлемо)
Ciphers +aes256-ctr,aes192-ctr,aes128-ctr

# Legacy HostKey (RSA SHA-1 — ТОЛЬКО для совместимости, пометить как deprecated)
HostKeyAlgorithms +ssh-rsa
PubkeyAcceptedAlgorithms +ssh-rsa
```

> **Важно:** Legacy-алгоритмы должны быть в конце списка. OpenSSH выбирает первый совпадающий алгоритм. Используйте `Match`-блоки для изоляции legacy-клиентов в отдельные сегменты сети.

#### Привилегированное разделение (Privilege Separation)

Привилегированное разделение — архитектурный механизм OpenSSH, при котором процесс `sshd` при старте порождает дочерние процессы с минимальными привилегиями для обработки отдельных сессий. Родительский процесс (`master`) работает от `root` только для авторизации и постановки порта, после чего дочерний процесс `ssh-userauth` понижает привилегии до непривилегированного пользователя `ssh-uid` (обычно `nobody` или выделенный пользователь), ограничивая ущерб при компрометации.

**Преимущества для DevOps/SRE:**
- Снижение поверхности атаки при уязвимостях вроде `regreSSHion` (CVE-2024-6387)
- Ограничение доступа к файлам `authorized_keys` только процессом той же сессии
- Защита от escalation даже при compromatation памяти демона

**Проверка статуса:**
```bash
ps -eo pid,user,comm | grep sshd
# → Дочерние процессы должны работать от ssh-uid/nobody, а не root
```

#### Жёсткая настройка SFTP (chroot + internal-sftp)

SFTP часто является единственным обоснованным использованием `AllowTcpForwarding` и `X11Forwarding`. Правильная конфигурация исключает доступ к shell и ограничивает файловую зону.

**Архитектура:**
- `ChrootDirectory` — создание песочницы на уровне файловой системы
- `internal-sftp` — встроенный подпроцесс SFTP вместо внешнего `/usr/lib/openssh/sftp-server`
- `ForceCommand internal-sftp` — принудительный запуск только SFTP

**Безопасность chroot:**
- Каталог chroot должен быть владельцем `root` и иметь права `755` (никто, кроме root, не может писать внутрь)
- Вложенный каталог для данных должен принадлежать пользователю SFTP с правами `700` или `750`
- SELinux/AppArmor должны иметь политики для chroot SFTP (на RHEL/Debian)

```bash
# 1. Создание пользователя без shell
sudo useradd -m -d /sftp/data -s /usr/sbin/nologin sftpuser

# 2. Подготовка структуры каталогов
sudo mkdir -p /sftp/data/{upload,download,archive}
sudo chown root:root /sftp/data
sudo chmod 755 /sftp/data
sudo chown sftpuser:sftpuser /sftp/data/{upload,download,archive}
sudo chmod 700 /sftp/data/{upload,download,archive}

# 3. Настройка sshd_config (в sshd_config.d/99-hardening.conf)
sudo tee -a /etc/ssh/sshd_config.d/99-hardening.conf << 'EOF'

# SFTP-only chroot
Match Group sftpusers
    ChrootDirectory /sftp/data
    ForceCommand internal-sftp
    AllowTcpForwarding no
    X11Forwarding no
    PermitTunnel no
    PermitTTY no
    PubkeyAuthentication yes
    PasswordAuthentication no
    AllowUsers sftpuser
EOF

# 4. SELinux (RHEL/Fedora)
sudo semanage fcontext -a -t ssh_home_t "/sftp/data(/.*)?"
sudo restorecon -Rv /sftp/data

# 5. AppArmor (Ubuntu/Debian) — профиль по умолчанию покрывает internal-sftp
# Проверка: sudo aa-status | grep sshd
```

**Валидация:**
```bash
sudo sshd -t
sudo systemctl restart sshd
# Проверка из клиента:
sftp -P 2239 sftpuser@server
# → Должен сразу показать sftp> приглашение, без shell
```

#### Генерация современных хостовых ключей

```bash
# Удаление старых ключей (RSA1, DSA, ECDSA, RSA < 3072)
sudo rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub

# Генерация Ed25519 (основной)
sudo ssh-keygen -t ed25519 -f /etc/ssh/ssh_host_ed25519_key -N "" -C "host-ed25519-$(date +%F)"

# Генерация RSA-4096 (fallback для legacy)
sudo ssh-keygen -t rsa -b 4096 -f /etc/ssh/ssh_host_rsa_key -N "" -C "host-rsa-4096-$(date +%F)"

# Права доступа
sudo chmod 600 /etc/ssh/ssh_host_*_key
sudo chmod 644 /etc/ssh/ssh_host_*_key.pub
sudo chown root:root /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub

# Перезапуск
sudo systemctl restart sshd
```

#### 4. Диагностика доступных алгоритмов

```bash
# Список поддерживаемых KEX
ssh -Q kex

# Список поддерживаемых шифров
ssh -Q cipher

# Список поддерживаемых MAC
ssh -Q mac

# Список поддерживаемых типов хостовых ключей
ssh -Q key

# Проверка эффективной конфигурации
sudo sshd -T | grep -E "kexalgorithms|ciphers|macs|hostkeyalgorithms|pubkeyacceptedalgorithms"
```

### Systemd Hardening для sshd (OpenSSH 9.0+)

Современные версии OpenSSH поддерживают нативную интеграцию с systemd для изоляции процесса. Эти настройки применяются через drop-in файл systemd, а не через sshd_config.

#### 1. Создание drop-in конфигурации

```bash
# Создание директории для override
sudo mkdir -p /etc/systemd/system/sshd.service.d

# Файл hardening.conf
sudo tee /etc/systemd/system/sshd.service.d/hardening.conf << 'EOF'
[Service]
# Безопасность процесса
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictNamespaces=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictSUIDSGID=yes
RemoveIPC=yes
PrivateUsers=yes

# Ограничение capabilities (CAP_NET_BIND_SERVICE нужен для порта < 1024)
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_DAC_OVERRIDE CAP_SETGID CAP_SETUID
AmbientCapabilities=CAP_NET_BIND_SERVICE

# Seccomp фильтр (OpenSSH 8.4+ имеет встроенный фильтр)
SystemCallFilter=@system-service
SystemCallFilter=~@clock @cpu-time @debug @module @obsolete @raw-io @reboot @swap

# Ограничение ресурсов
LimitNOFILE=65536
LimitNPROC=1024
TasksMax=512

# Логирование
StandardError=journal
SyslogIdentifier=sshd
EOF

# Перезагрузка systemd и перезапуск
sudo systemctl daemon-reload
sudo systemctl restart sshd
```

#### 2. Проверка применения hardening

```bash
# Проверка capabilities процесса
sudo grep -i cap /proc/$(systemctl show --property=MainPID --value sshd)/status

# Проверка seccomp
sudo grep -i seccomp /proc/$(systemctl show --property=MainPID --value sshd)/status

# Проверка namespaces
sudo ls -la /proc/$(systemctl show --property=MainPID --value sshd)/ns/

# systemd-analyze security
systemd-analyze security sshd.service
# Ожидаемый результат: HIGH (или MEDIUM при использовании порта < 1024)
```

#### 3. AppArmor/SELinux профили

**AppArmor (Ubuntu/Debian):**
```bash
# Установка профиля
sudo apt install apparmor-profiles apparmor-utils
sudo aa-enforce /etc/apparmor.d/usr.sbin.sshd

# Или использование встроенного профиля OpenSSH (9.0+)
# Файл: /etc/apparmor.d/usr.sbin.sshd
```

**SELinux (RHEL/Fedora):**
```bash
# SSH уже имеет политику по умолчанию
# Для нестандартного порта:
sudo semanage port -a -t ssh_port_t -p tcp 2239

# Boolean для разрешения chroot SFTP
sudo setsebool -P ssh_chroot_rw_homedirs on
```

### Аудит событий SSH через auditd

`auditd` (Linux Audit Daemon) обеспечивает детализированное журналирование событий безопасности на уровне ядра, включая чтение/запись критичных файлов SSH и все попытки аутентификации. В отличие от стандартного journald, auditd:
- Записывает события в несужемый формат (нельзя изменить без перезагрузки)
- Поддерживает метки ключей (`-k`) для группировки
- Интегрируется с SIEM (Wazuh, Splunk, ELK) через `audisp` или `ausearch`
- Гарантирует целостность журнала даже при переполнении диска (`-f` режим panic)

#### 1. Правила аудита для SSH

```bash
# Наблюдение за sshd_config (любые изменения)
sudo auditctl -w /etc/ssh/sshd_config -p wa -k ssh_config

# Наблюдение за директорией ключей хоста
sudo auditctl -w /etc/ssh/ -p rwxa -k ssh_host_keys

# Наблюдение за authorized_keys всех пользователей
sudo auditctl -w /home/ -p rwxa -k ssh_user_auth

# Наблюдение за выполнением sshd
sudo auditctl -w /usr/sbin/sshd -p x -k sshd_execution

# Правило для отслеживания изменений в сессиях (PAM)
sudo auditctl -w /var/log/faillock -p rw -k ssh_auth_failures
```

#### 2. Постоянные правила (файл `/etc/audit/rules.d/ssh-hardening.rules`)

```bash
sudo tee /etc/audit/rules.d/ssh-hardening.rules << 'EOF'
# SSH Hardening Audit Rules

# Отслеживание изменений конфигурации
-w /etc/ssh/sshd_config -p wa -k ssh_config
-w /etc/ssh/sshd_config.d/ -p rwxa -k ssh_config_dir

# Отслеживание хостовых ключей
-w /etc/ssh/ssh_host_*_key -p rw -k ssh_host_keys
-w /etc/ssh/ssh_host_*_key.pub -p r -k ssh_host_keys_pub

# Отслеживание файлов авторизации пользователей
-w /home/ -p rwxa -k ssh_user_home

# Отслеживание запуска демона
-w /usr/sbin/sshd -p x -k sshd_bin
-w /usr/libexec/openssh/ -p x -k sshd_libs

# Отслеживание PAM модулей SSH
-w /etc/pam.d/sshd -p rw -k ssh_pam
-w /etc/security/faillock -p rw -k ssh_faillock

# Отслеживание CA и отзыва ключей
-w /etc/ssh/ca_* -p rw -k ssh_ca
-w /etc/ssh/revoked_keys -p rw -k ssh_revoked

# Генерация событий при успешном входе
-a always,exit -F arch=b64 -S execve -F exe=/usr/sbin/sshd -F auid>=1000 -F auid!=4294967295 -k ssh_successful_login

# Генерация событий при неудачном входе (через pam_faillock)
-a always,exit -F arch=b64 -S openat -F dir=/var/log/faillock -F success=0 -k ssh_failed_login
EOF

# Перезагрузка правил
sudo augenrules --load
```

#### 3. Поиск и анализ событий

```bash
# Все события SSH за последний час
sudo ausearch -k ssh_* --start recent | aureport -x --summary

# Кто изменял sshd_config
sudo ausearch -k ssh_config -i | grep sshd_config

# Неудачные попытки входа
sudo ausearch -k ssh_failed_login -i | grep "sshd.*Failed"

# Успешные входы
sudo ausearch -k ssh_successful_login -i | grep "sshd.*Accepted"

# Поиск по UID исходного пользователя (auid)
sudo ausearch -k ssh_successful_login -i --debug | grep auid

# Экспорт в XML для SIEM
sudo ausearch -k ssh_* -i --format xml > /tmp/ssh_audit.xml
```

#### 4. Интеграция с SIEM

```bash
# auditd -> Wazuh через ausearch + curl (пример webhook)
sudo tee /etc/audisp/plugins.d/au-wazuh.conf << 'EOF'
# /etc/audisp/plugins.d/au-wazuh.conf
active = yes
direction = out
path = /usr/local/bin/audit2wazuh.sh
type = async
```

```bash
# /usr/local/bin/audit2wazuh.sh
#!/bin/bash
while read line; do
    if echo "$line" | grep -q "sshd.*Accepted"; then
        curl -s -X POST "http://wazuh-manager:55000/ssh/events" \
             -H "Content-Type: application/json" \
             -d "{\"event\":\"ssh_login\",\"data\":\"$line\"}" || true
    fi
done
sudo chmod +x /usr/local/bin/audit2wazuh.sh
```

### Zero Trust SSH — практическая реализация

Zero Trust SSH строится на принципе «никому не доверяй по умолчанию». Вместо сетевой периметровой модели (trusted LAN), доступ предоставляется на основе динамического контекста: identity, device posture, time, network location, MFA.

**Компоненты:**
1. **SSH CA (Certificate Authority)** — кратковременные сертификаты (TTL 1–24 часа) вместо статических ключей
2. **Policy Decision Point (PDP)** — внешний сервис (OIDC, Vault, Teleport), принимающий решение о выдаче сертификата
3. **Session Recording** — запись сессий через `auditd` или специальные протоколы
4. **Short-lived Credentials** — автоматическая ротация без участия администратора

#### 1. Интеграция с HashiCorp Vault (без облака)

Vault выступает как SSH CA и хранилище политик:

```bash
# 1. Включение движка SSH CA в Vault
vault secrets enable -path=ssh-client-signer ssh

# 2. Создание роли
vault write ssh-client-signer/roles/ops-role \
    key_type="ed25519" \
    allowed_users="admin,deploy,sre" \
    default_extensions="permit-pty,permit-port-forwarding" \
    ttl="8h" \
    max_ttl="24h"

# 3. Подпись CSR клиента
vault write -f ssh-client-signer/sign/ops-role public_key=@/home/user/.ssh/id_ed25519.pub

# 4. На стороне сервера: доверие Vault CA
sudo tee /etc/ssh/sshd_config.d/99-vault-ca.conf << 'EOF'
TrustedUserCAKeys /etc/ssh/vault_ca.pub
AuthorizedKeysCommand /usr/bin/vault-ssh-helper
AuthorizedKeysCommandUser root
AuthorizedKeysCommandRunAs root
EOF

# 5. Валидация политик через Vault (вместо static AuthorizedKeysCommand)
# Vault проверяет: IP в whitelist, время доступа, членство в группе
```

#### 2. Интеграция с Teleport (self-hosted)

Teleport предоставляет полноценный Zero Trust платформенный слой:

```bash
# Установка Teleport на сервер (Debian/Ubuntu)
sudo apt install teleport

# Конфигурация SSH-сервиса в Teleport
sudo tee /etc/teleport.yaml << 'EOF'
teleport:
    data_dir: /var/lib/teleport
    log:
        output: syslog
        severity: INFO

ssh_service:
    enabled: yes
    listen_addr: 0.0.0.0:3022
    public_addr: bastion.example.com:3022
    commands:
    - name: hostname
      command: [hostname]
      period: 1h
EOF

# Запуск
sudo systemctl enable --now teleport
```

**Архитектура доступа:**
```
Клиент → tsh (Teleport Client) → Bastion (Teleport Proxy) → SSH Target
                                          ↓
                                    Audit Log + Session Recording
```

#### 3. Политики доступа на основе RBAC

```bash
# Пример: только определенные группы могут подключаться к production
# В sshd_config:
Match Group sre,admin Address 10.0.0.0/8
    AuthenticationMethods publickey,keyboard-interactive
    AllowTcpForwarding yes
    X11Forwarding no
    ForceCommand /usr/local/bin/session-wrapper.sh

# session-wrapper.sh — enforce RBAC + logging
#!/bin/bash
logger -t ssh-rbac "RBAC: user=$USER from=$SSH_CONNECTION"
exec /bin/bash
```

### Соответствие стандартам (OpenSCAP / CIS / DISA STIG)

Compliance Hardening — приведение конфигурации SSH в соответствие с отраслевыми стандартами. В контексте on-prem/self-hosted сред используются:

- **CIS Benchmarks** — два уровня строгости (Level 1, Level 2)
- **DISA STIG** — самый строгий стандарт для госсектора/обороны
- **PCI DSS** — финтех (требует отдельного аудита шифров)
- **NIST 800-53** — федеральные системы США

#### 1. Сопоставление директив SSH со стандартами

| Директива | CIS Ubuntu 24.04 | CIS RHEL 9 | DISA STIG |
| :--- | :--- | :--- | :--- |
| `PermitRootLogin` | 5.2.7 | 5.2.7 | SSG-001 |
| `PasswordAuthentication` | 5.2.8 | 5.2.8 | SSG-002 |
| `PubkeyAuthentication` | 5.2.9 | 5.2.9 | SSG-003 |
| `KexAlgorithms` | 5.2.12 | 5.2.12 | SSG-007 |
| `Ciphers` | 5.2.12 | 5.2.12 | SSG-008 |
| `MACs` | 5.2.12 | 5.2.12 | SSG-009 |
| `ClientAliveInterval` | 5.2.13 | 5.2.13 | SSG-010 |
| `ClientAliveCountMax` | 5.2.13 | 5.2.13 | SSG-011 |
| `StrictModes` | 5.2.14 | 5.2.14 | SSG-012 |
| `IgnoreRhosts` | 5.2.15 | 5.2.15 | SSG-013 |
| `HostbasedAuthentication` | 5.2.16 | 5.2.16 | SSG-014 |
| `PermitEmptyPasswords` | 5.2.17 | 5.2.17 | SSG-015 |

#### 2. Проверка через OpenSCAP

```bash
# Установка SCAP Security Guide
sudo apt install scap-security-guide ssg-debderived  # Debian/Ubuntu
sudo dnf install scap-security-guide ssg-rhel9-ds     # RHEL 9

# Список доступных профилей
oscap info /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml | grep ssh

# Запуск аудита (только SSH-политики)
sudo oscap xccdf eval \
    --profile xccdf_org.ssgproject.content_profile_ssh_server \
    --results /tmp/ssh_audit_results.xml \
    --report /tmp/ssh_audit_report.html \
    /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml

# Генерация remediation-плейбука Ansible
oscap xccdf generate remediation \
    --fix-type ansible \
    --profile xccdf_org.ssgproject.content_profile_ssh_server \
    /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml \
    > /tmp/ssh_remediation.yml
```

#### 3. Автоматизация в CI/CD (GitLab CI пример)

```yaml
# .gitlab-ci.yml
stages:
  - audit
  - compliance

ssh_openscap_audit:
  stage: audit
  image: rhel9/openscap:latest
  script:
    - |
      oscap xccdf eval \
        --profile xccdf_org.ssgproject.content_profile_ssh_server \
        --results ssh-results.xml \
        --report ssh-report.html \
        /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
  artifacts:
    paths:
      - ssh-report.html
    when: always
  only:
    - main
    - merge_requests

ssh_compliance_gate:
  stage: compliance
  image: python:3.11
  script:
    - pip install defusedxml
    - python3 -c "
        import defusedxml.ElementTree as ET
        import sys
        tree = ET.parse('ssh-results.xml')
        root = tree.getroot()
        fails = [r for r in root.findall('.//{http://checklists.nist.gov/xccdf/1.2}result') if r.get('result') == 'fail']
        if fails:
            print(f'SSH Compliance FAIL: {len(fails)} rules failed')
            for f in fails[:5]:
                print(f'  - {f.get(\"idref\")}')
            sys.exit(1)
        print('SSH Compliance PASS')
      "
  dependencies:
    - ssh_openscap_audit
```

## Практические сценарии

### Сценарий 1: Комплексное укрепление (Hardening Checklist)

**Задача:** Применить современную безопасную конфигурацию через модульный файл.

```bash
# 1. Создание директории для конфигов (если не используется)
sudo mkdir -p /etc/ssh/sshd_config.d

# 2. Создание файла закалки
sudo tee /etc/ssh/sshd_config.d/99-hardening.conf << 'EOF'
# Аутентификация
PubkeyAuthentication yes
PasswordAuthentication no
PermitRootLogin no
MaxAuthTries 3
AuthenticationMethods publickey

# Ключи и CA
AuthorizedKeysFile .ssh/authorized_keys
TrustedUserCAKeys /etc/ssh/ca_user.pub
RevokedKeys /etc/ssh/revoked_keys

# Тайм-ауты и ограничения
LoginGraceTime 30s
ClientAliveInterval 300
ClientAliveCountMax 0
MaxSessions 2
MaxStartups 10:30:60

# Безопасность окружения
X11Forwarding no
AllowTcpForwarding no
PermitTunnel no
AllowAgentForwarding no
PermitUserEnvironment no
Compression delayed
ExposeAuthInfo no

# Логирование
LogLevel VERBOSE
FingerprintHash sha256

# Сеть
AddressFamily inet
TCPKeepAlive no
UseDNS no
GSSAPIAuthentication no
KerberosAuthentication no
DebianBanner no

# Криптография (OpenSSH 9.8+)
KexAlgorithms mlkem768x25519-sha256,sntrup761x25519-sha512@openssh.com,curve25519-sha256,curve25519-sha256@libssh.org
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com,hmac-sha2-256
HostKeyAlgorithms ssh-ed25519,ssh-ed25519-cert-v01@openssh.com,rsa-sha2-512,rsa-sha2-256
PubkeyAcceptedAlgorithms ssh-ed25519,ssh-ed25519-cert-v01@openssh.com,rsa-sha2-512,rsa-sha2-256,sk-ssh-ed25519@openssh.com,sk-ssh-ed25519-cert-v01@openssh.com
CASignatureAlgorithms ssh-ed25519,rsa-sha2-512,rsa-sha2-256

# Баннер
Banner /etc/ssh/banner
EOF

# 3. Подготовка баннера
sudo tee /etc/ssh/banner << 'EOF'
***************************************************************************
*                          UNAUTHORIZED ACCESS PROHIBITED                 *
*                  All connections are monitored and recorded.            *
***************************************************************************
EOF

# 4. Генерация современных хостовых ключей (если не созданы)
sudo rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub
sudo ssh-keygen -t ed25519 -f /etc/ssh/ssh_host_ed25519_key -N "" -C "host-ed25519-$(date +%F)"
sudo ssh-keygen -t rsa -b 4096 -f /etc/ssh/ssh_host_rsa_key -N "" -C "host-rsa-4096-$(date +%F)"
sudo chmod 600 /etc/ssh/ssh_host_*_key
sudo chmod 644 /etc/ssh/ssh_host_*_key.pub

# 5. Настройка systemd hardening
sudo mkdir -p /etc/systemd/system/sshd.service.d
sudo tee /etc/systemd/system/sshd.service.d/hardening.conf << 'EOF'
[Service]
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictNamespaces=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictSUIDSGID=yes
RemoveIPC=yes
PrivateUsers=yes
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_DAC_OVERRIDE CAP_SETGID CAP_SETUID
AmbientCapabilities=CAP_NET_BIND_SERVICE
SystemCallFilter=@system-service
SystemCallFilter=~@clock @cpu-time @debug @module @obsolete @raw-io @reboot @swap
LimitNOFILE=65536
LimitNPROC=1024
TasksMax=512
StandardError=journal
SyslogIdentifier=sshd
EOF

# 6. Проверка и перезапуск
sudo sshd -t && sudo systemctl daemon-reload && sudo systemctl restart sshd

# 7. Валидация
sudo sshd -T | grep -E "passwordauthentication|permitrootlogin|pubkeyauthentication|kexalgorithms|ciphers|macs"
systemd-analyze security sshd.service
```

### Сценарий 1а: Валидация соответствия CIS Benchmark (Level 1/Level 2)

**Задача:** Автоматизированная проверка конфигурации SSH на соответствие CIS Linux Benchmark.

```bash
# Установка аудит-сканера
# Для Debian/Ubuntu:
sudo apt install lynis
# Для RHEL/CentOS:
sudo dnf install lynis

# Быстрая проверка SSH
sudo lynis audit system --quick --tests "ssh*" 2>/dev/null | grep -A2 -B2 "SSH"

# Полная проверка с отчетом
sudo lynis audit system --report-file /var/log/lynis-report.dat
grep -i ssh /var/log/lynis-report.dat

# Проверка через ssh-audit (специализированный инструмент)
pip install ssh-audit
ssh-audit localhost -p 2239
# → Ищите [WARN] и [FAIL] в выводе

# Автоматизированная проверка в CI/CD (пример для GitLab CI)
# .gitlab-ci.yml:
# ssh_hardening_check:
#   stage: compliance
#   script:
#     - ssh-audit -p $SSH_PORT $TARGET_HOST --json > audit.json
#     - |
#       python3 -c "
#       import json, sys
#       with open('audit.json') as f: data = json.load(f)
#       fails = [i for i in data if i['severity'] in ('fail', 'warn')]
#       if fails:
#           print('SSH Hardening FAIL:')
#           for f in fails: print(f'  {f[\"algorithm\"]}: {f[\"message\"]}')
#           sys.exit(1)
#       print('SSH Hardening PASS')
#     "
```

### Сценарий 2: Настройка резервного SSH-доступа (Emergency Access)

**Задача:** Запустить второй экземпляр `sshd` с минимальными настройками на альтернативном порту (например, для внутренних нужд или восстановления).

```bash
# 1. Создание отдельного конфига
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config_alt

# 2. Настройка альта (только локальная сеть, порт 2222)
sudo tee /etc/ssh/sshd_config_alt << 'EOF'
Port 2222
ListenAddress 192.168.100.10
PidFile /run/sshd-alt.pid
PubkeyAuthentication yes
PasswordAuthentication no
PermitRootLogin no
StrictModes yes
LogLevel VERBOSE
# Минимальные алгоритмы для совместимости с rescue-клиентами
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com
MACs hmac-sha2-256-etm@openssh.com
HostKeyAlgorithms ssh-ed25519,rsa-sha2-512
EOF

# 3. Создание systemd-сервиса (/etc/systemd/system/sshd-alt.service)
sudo tee /etc/systemd/system/sshd-alt.service << 'EOF'
[Unit]
Description=OpenSSH Server (Alternative Instance)
After=network.target

[Service]
ExecStart=/usr/sbin/sshd -D -f /etc/ssh/sshd_config_alt
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process
Restart=on-failure
# Дополнительный hardening для альтернативного экземпляра
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes

[Install]
WantedBy=multi-user.target
EOF

# 4. Активация
sudo systemctl daemon-reload
sudo systemctl enable --now sshd-alt
```

### Сценарий 2а: Break-Glass доступ через Out-of-Band (IPMI/iDRAC/Console)

**Задача:** Обеспечить аварийный доступ при полной потере SSH (неверный конфиг, потеря ключей, блокировка fail2ban).

```bash
# 1. Подготовка breakglass пользователя (только для аварий)
sudo useradd -m -s /bin/bash breakglass
sudo mkdir -p /home/breakglass/.ssh
sudo chmod 700 /home/breakglass/.ssh

# 2. Генерация выделенного ED25519-SK ключа (FIDO2 токен, touch-required)
ssh-keygen -t ed25519-sk -O resident -O verify-required -C "breakglass-$(date +%F)" -f ~/.ssh/breakglass_sk

# 3. Размещение публичного ключа
cat ~/.ssh/breakglass_sk.pub | sudo tee /home/breakglass/.ssh/authorized_keys
sudo chmod 600 /home/breakglass/.ssh/authorized_keys
sudo chown -R breakglass:breakglass /home/breakglass/.ssh

# 4. Отдельный Match-блок в основном sshd_config (только для breakglass)
sudo tee -a /etc/ssh/sshd_config.d/99-hardening.conf << 'EOF'

# Break-glass доступ: только FIDO2, только с консоли/IPMI подсети
Match User breakglass Address 192.168.100.0/24
    AuthenticationMethods publickey
    PubkeyAcceptedAlgorithms sk-ssh-ed25519@openssh.com
    PermitRootLogin no
    AllowTcpForwarding no
    X11Forwarding no
    PermitTunnel no
    ForceCommand /usr/local/bin/breakglass-audit.sh
EOF

# 5. Скрипт аудита использования breakglass
sudo tee /usr/local/bin/breakglass-audit.sh << 'EOF'
#!/bin/bash
# Вызывается при каждом входе breakglass
logger -t ssh-breakglass "BREAKGLASS ACCESS: user=$USER from=$SSH_CONNECTION cmd=$SSH_ORIGINAL_COMMAND"
# Отправка алерта (email, Slack, PagerDuty, webhook)
curl -X POST -H "Content-Type: application/json" \
     -d "{\"text\":\"🚨 BREAKGLASS SSH ACCESS: $USER from $SSH_CONNECTION\"}" \
     "$ALERT_WEBHOOK_URL" 2>/dev/null || true
# Передача управления в шелл
exec /bin/bash
EOF
sudo chmod 755 /usr/local/bin/breakglass-audit.sh
sudo chown root:root /usr/local/bin/breakglass-audit.sh

# 6. Документирование процедуры восстановления
sudo tee /root/BREAKGLASS_RECOVERY.md << 'EOF'
# Процедура аварийного доступа (Break-Glass)

## Признаки необходимости:
- Потеря всех SSH-ключей администраторов
- Ошибка в sshd_config, блокирующая доступ
- fail2ban заблокировал все админы
- Сетевой firewall блокирует основной порт

## Действия:
1. Подключиться через Out-of-Band (IPMI/iDRAC/iLO/Console)
2. Проверить статус: `systemctl status sshd sshd-alt`
3. Если основной sshd неисправим: `systemctl start sshd-alt` (порт 2222, только 192.168.100.0/24)
4. Если нужен root: использовать FIDO2 токен breakglass пользователя
5. После входа: исправить конфиг, `sshd -t && systemctl reload sshd`
6. Обязательно: отозвать использованный breakglass ключ, сгенерировать новый
EOF
```

### Сценарий 3: Аудит через ssh-audit

**Задача:** Провести независимую проверку безопасности настроек шифрования.

```bash
# 1. Установка инструмента (требуется python3)
pip install ssh-audit

# 2. Сканирование локального сервера (порт 2239)
ssh-audit -p 2239 localhost

# → В выводе ищите красные (критические) и желтые (предупреждения) строки.
# Результат поможет скорректировать Ciphers и MACs под конкретную версию OpenSSH.
```

### Сценарий 4: Безопасное применение конфигурации с атомарным откатом

**Задача:** Внести изменения в `sshd_config` без риска потерять доступ при ошибке синтаксиса или неправильном параметре.

```bash
# 1. Создание бэкапа с временной меткой
BACKUP="/etc/ssh/sshd_config.bak.$(date +%F_%H%M%S)"
sudo cp /etc/ssh/sshd_config "$BACKUP"
sudo md5sum "$BACKUP" > /root/sshd_config_hashes.txt

# 2. Проверка синтаксиса перед применением (ОБЯЗАТЕЛЬНО)
sudo sshd -t
# → Если вывод пустой — синтаксис корректен
# → Если есть ошибки: исправить до продолжения

# 3. Применение через drop-in (рекомендуется) или атомарная замена
# Вариант A: Drop-in (безопаснее, изолирует изменения)
sudo tee /etc/ssh/sshd_config.d/99-hardening.conf << 'EOF'
# ... новые параметры ...
EOF

# Вариант B: Полная замена с валидацией
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.new
# ... редактирование sshd_config.new ...
sudo diff -u "$BACKUP" /etc/ssh/sshd_config.new
sudo sshd -t -f /etc/ssh/sshd_config.new && \
    sudo mv /etc/ssh/sshd_config.new /etc/ssh/sshd_config

# 4. Проверка эффективного конфига
sudo sshd -T | grep -E "passwordauthentication|permitrootlogin|kexalgorithms"

# 5. Откат при ошибке
sudo cp "$BACKUP" /etc/ssh/sshd_config
sudo systemctl restart sshd
```

**Автоматизация через Ansible (идемпотентный apply + rollback):**

```yaml
- name: Бэкап sshd_config
  ansible.builtin.copy:
    src: /etc/ssh/sshd_config
    dest: "/etc/ssh/sshd_config.bak.{{ ansible_date_time.iso8601 }}"
    remote_src: yes
    owner: root
    group: root
    mode: '0600'

- name: Применить SSH hardening
  ansible.builtin.template:
    src: sshd_config.j2
    dest: /etc/ssh/sshd_config
    validate: '/usr/sbin/sshd -t -f %s'
    backup: yes
  notify: restart sshd

- name: Fallback откат при ошибке
  ansible.builtin.copy:
    src: /etc/ssh/sshd_config.bak
    dest: /etc/ssh/sshd_config
    remote_src: yes
  when: sshd_apply_failed | default(false)
```

### Сценарий 5: Митигация CVE-2024-6387 (regreSSHion)

**Уязвимость:** Heap-based buffer overflow в `sshd` при обработке сигналов (SIGALRM) во время аутентификации по паролю. Удаленное выполнение кода (RCE) с привилегиями `root`.

**Пострадавшие версии:** OpenSSH 8.5p1 — 9.7p1

**Задача:** Оценить риск и применить защитные меры.

```bash
# 1. Проверка текущей версии
ssh -V
# → OpenSSH_9.7p1, OpenSSL_3.0.2 ...

# 2. Если версия уязвима — немедленное обновление
sudo apt update && sudo apt upgrade openssh-server  # Debian/Ubuntu
sudo dnf update openssh-server                        # RHEL/Fedora

# 3. Временные меры (если обновление невозможно):
# 3a. Полное отключение парольной аутентификации
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#*ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config

# 3b. Снижение времени ожидания аутентификации
sudo sed -i 's/^#*LoginGraceTime.*/LoginGraceTime 10/' /etc/ssh/sshd_config

# 3c. Включение пользовательской изоляции (mitigation через 2024-09-30 patch)
# OpenSSH 9.8+ автоматически включает privilege separation
sudo sed -i 's/^#*UsePrivilegeSeparation.*/UsePrivilegeSeparation sandbox/' /etc/ssh/sshd_config

# 4. Проверка конфигурации
sudo sshd -t
sudo systemctl reload sshd

# 5. Валидация
sudo sshd -T | grep -E "passwordauthentication|logingracetime|useprivilegeseparation"
```

**Постоянный контроль:**
```bash
# Мониторинг попыток эксплуатации
sudo journalctl -u sshd --since "1 hour ago" | grep -i "signal\|alarm\|overflow"

# Fail2ban блокировка (первый эшелон)
sudo fail2ban-client status sshd
```

### Сценарий 6: Аудит через OpenSCAP

**Задача:** Автоматизированная проверка соответствия SSH-конфигурации профилю CIS Ubuntu 24.04 Level 2.

```bash
# 1. Установка инструментов
sudo apt install libopenscap8 ssg-debderived ssg-base ssg-ubuntu2404-ds

# 2. Просмотр доступных профилей
oscap info /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml | grep -i ssh

# 3. Выполнение аудита
sudo oscap xccdf eval \
    --profile xccdf_org.ssgproject.content_profile_ssh_server \
    --results /tmp/ssh-cis-results.xml \
    --report /tmp/ssh-cis-report.html \
    /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml

# 4. Проверка кода возврата
# 0 = compliant, 1 = ошибка, 2 = несоответствия найдены
echo $?
# → 2 (несоответствия)

# 5. Генерация remediation-плейбука Ansible
oscap xccdf generate remediation \
    --fix-type ansible \
    --profile xccdf_org.ssgproject.content_profile_ssh_server \
    /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml \
    > /tmp/ssh-remediation.yml

# 6. Применение через Ansible (с dry-run сначала)
ansible-playbook --check /tmp/ssh-remediation.yml
ansible-playbook /tmp/ssh-remediation.yml
```

## Дополнительная информация

### Инструменты защиты

- **[fail2ban](../../Tools/fail2ban.md)** — блокировка IP после нескольких неудачных попыток входа (L7 анализ логов).
- **[Port Knocking](./port_knocking.md)** — механизм скрытия порта до прохождения последовательности «стуков».
- **Endlessh** — SSH-ловушка (tarpit), которая бесконечно удерживает соединения ботов, замедляя их сканирование.
- **[auditd](../../Linux/SystemAdministration/Logging/auditd.md)** — ядерный аудит событий безопасности, отслеживание изменений конфигурации и попыток аутентификации.
- **[OpenSCAP](../../Ansible/ansible-os-hardening.md)** — автоматизированный аудит соответствия CIS/DISA STIG через SCAP профили.

### Регулярный аудит

1. **Проверка эффективного конфига**: `sudo sshd -T | grep -E "kexalgorithms|ciphers|macs|hostkeyalgorithms|pubkeyacceptedalgorithms"` — показывает настройки с учетом всех `Include` и `Match`.
2. **Аудит логов**: `journalctl -u sshd --since "yesterday"` для поиска аномалий.
3. **Обновление системы**: Критические уязвимости требуют немедленного обновления:
   - **CVE-2024-6387 (regreSSHion):** RCE в OpenSSH 8.5p1–9.7p1. Требуется обновление до **9.8p1+** или отключение `PasswordAuthentication`.
   - **CVE-2023-38408 (PKCS#11):** Удаленное выполнение кода через `ssh-keysign` при использовании PKCS#11. Требуется обновление до **9.3p2+**.
4. **Аудит через auditd**: `sudo ausearch -k ssh_* -i` — поиск изменений конфигурации и попыток входа.
5. **Compliance-аудит**: Запуск OpenSCAP профилей на соответствие CIS Level 1/Level 2.
6. **Сетевой контроль**: Проверка `ss -tlnp | grep sshd` — убедиться, что `sshd` слушает только на ожидаемых IP (`ListenAddress`).

### См. также

- [SSH Server Security Overview](./ssh_server_security_overview.md) — общая стратегия защиты.
- [SSH Access Control](./ssh_access_control.md) — ограничение доступа по IP и пользователям, `Match`-блоки.
- [SSH Authentication](./ssh_authentication.md) — методы аутентификации, ключи, FIDO2, права доступа.
- [SSH Certificate Authentication](./ssh_certificate_authentication.md) — работа с SSH CA, `TrustedUserCAKeys`, principals.
- [SSH Monitoring and Troubleshooting](./ssh_monitoring_and_troubleshooting.md) — аудит, `auditd`, анализ логов.
- [Инструменты сетевого мониторинга](../../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для анализа SSH-трафика
- [fail2ban](../../Tools/fail2ban.md) — автоматизация блокировок.
- [auditd](../../Linux/SystemAdministration/Logging/auditd.md) — ядерный аудит, отслеживание изменений конфигурации SSH.
- [Ansible: OS Hardening](../../Ansible/ansible-os-hardening.md) — Compliance as Code, OpenSCAP, роли Ansible Lockdown.
