# SSH Hardening Best Practices

## Definitions → Basic Concepts → Practical Scenarios → Additional Information

## Definitions

**SSH Hardening** — комплекс мер по усилению безопасности SSH-сервера: отключение неиспользуемых функций, ограничение методов аутентификации, настройка файрвола, логирование и защита от автоматических атак.

**Defense in Depth** — принцип многослойной защиты, при котором компрометация одного уровня не даёт полного доступа к системе.

## Basic Concepts

### Уровни защиты SSH

| Уровень | Механизм | Описание |
| :--- | :--- | :--- |
| **Сетевой** | Файрвол (iptables/nftables) | Фильтрация по IP, ограничение скорости |
| **Транспортный** | Port Knocking / SPA | Скрытие порта от сканирования |
| **Прикладной** | sshd_config | Аутентификация, таймауты, баннеры |
| **Мониторинг** | fail2ban, логи | Блокировка brute-force, аудит |

### Ключевые директивы sshd_config

#### Аутентификация

| Директива | Рекомендуемое значение | Описание |
| :--- | :--- | :--- |
| `PubkeyAuthentication` | `yes` | Разрешить вход по ключам |
| `PasswordAuthentication` | `no` | Запретить вход по паролю |
| `PermitRootLogin` | `no` | Запретить вход root |
| `MaxAuthTries` | `3` | Ограничить попытки |
| `PermitEmptyPasswords` | `no` | Запретить пустые пароли |
| `ChallengeResponseAuthentication` | `no` | Отключить challenge-response |
| `AuthenticationMethods` | `publickey` | Требовать только pubkey |
| `PubkeyAcceptedAlgorithms` | `ssh-ed25519,rsa-sha2-512` | Ограничить алгоритмы |

#### Сетевые настройки

| Директива | Рекомендуемое значение | Описание |
| :--- | :--- | :--- |
| `Port` | Нестандартный (например, `2239`) | Снизить шум от ботов |
| `ListenAddress` | Конкретный IP | Слушать только на нужном интерфейсе |
| `Protocol` | `2` | Только SSHv2 (по умолчанию) |
| `LoginGraceTime` | `30` | Таймаут на аутентификацию (сек) |
| `ClientAliveInterval` | `300` | Таймаут неактивности (сек) |
| `ClientAliveCountMax` | `2` | Кол-во пустых интервалов до разрыва |
| `MaxSessions` | `3` | Макс. сессий на подключение |

#### Безопасность и логирование

| Директива | Рекомендуемое значение | Описание |
| :--- | :--- | :--- |
| `LogLevel` | `VERBOSE` | Детальное логирование (отпечатки ключей) |
| `Banner` | `/etc/ssh/banner` | Показать предупреждение до входа |
| `X11Forwarding` | `no` | Отключить, если не используется |
| `AllowTcpForwarding` | `no` | Отключить, если не используется |
| `PermitTunnel` | `no` | Отключить туннели |
| `AllowAgentForwarding` | `no` | Отключить agent forwarding |
| `PrintMotd` | `no` | Отключить MOTD (опционально) |
| `UsePAM` | `yes` | Использовать PAM (для совместимости) |
| `StrictModes` | `yes` | Проверять права файлов |
| `IgnoreRhosts` | `yes` | Игнорировать `.rhosts` |

### Алгоритмы шифрования (OpenSSH 8.8+)

Старые алгоритмы уязвимы. Рекомендуется явно задать современные:

```ini
# KexAlgorithms (обмен ключами)
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org,diffie-hellman-group16-sha512

# Ciphers (шифрование)
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com

# MACs (целостность)
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com
```

**Проверка текущих настроек:**

```bash
ssh -Q kex       # Доступные KexAlgorithms
ssh -Q cipher    # Доступные Ciphers
ssh -Q mac       # Доступные MACs
```

## Practical Scenarios

### Сценарий 1: Базовое укрепление SSH

**Задача:** Применить минимально безопасную конфигурацию.

```bash
# 1. Резервная копия
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak

# 2. Применить основные директивы
sudo tee -a /etc/ssh/sshd_config.d/hardening.conf << 'EOF'
# Аутентификация
PubkeyAuthentication yes
PasswordAuthentication no
PermitRootLogin no
MaxAuthTries 3
PermitEmptyPasswords no
AuthenticationMethods publickey

# Сеть
Port 2239
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
MaxSessions 3

# Безопасность
X11Forwarding no
AllowTcpForwarding no
PermitTunnel no
LogLevel VERBOSE
Banner /etc/ssh/banner
EOF

# 3. Создать баннер
sudo tee /etc/ssh/banner << 'EOF'
AUTHORIZED ACCESS ONLY. All connections are monitored and recorded.
EOF

# 4. Проверить конфигурацию
sudo sshd -t

# 5. Перезапустить SSH (убедиться в наличии ключей!)
sudo systemctl restart sshd
```

### Сценарий 2: Настройка резервного SSH-доступа

**Задача:** Создать резервный экземпляр `sshd` на другом порту для восстановления доступа после сбоя файрвола.

```bash
# 1. Копия конфигурации
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config_alt

# 2. Минимальный конфиг (/etc/ssh/sshd_config_alt)
sudo tee /etc/ssh/sshd_config_alt << 'EOF'
Port 2222
ListenAddress 192.168.100.10
PidFile /run/sshd-alt.pid
PubkeyAuthentication yes
PasswordAuthentication no
PermitRootLogin no
EOF

# 3. Запуск вручную
sudo /usr/sbin/sshd -f /etc/ssh/sshd_config_alt

# 4. Системная служба (создать /etc/systemd/system/sshd-alt.service)
sudo tee /etc/systemd/system/sshd-alt.service << 'EOF'
[Unit]
Description=OpenSSH Server (Alternative)
After=network.target

[Service]
ExecStart=/usr/sbin/sshd -f /etc/ssh/sshd_config_alt -D
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now sshd-alt
```

### Сценарий 3: Изменение порта SSH при включенном SELinux

**Задача:** Перенести SSH на нестандартный порт без ошибок запуска.

```bash
# 1. Изменить порт в sshd_config
sudo sed -i 's/^#*Port.*/Port 5022/' /etc/ssh/sshd_config

# 2. Добавить порт в SELinux
sudo semanage port -a -t ssh_port_t -p tcp 5022

# 3. Открыть порт в файрволе
sudo firewall-cmd --permanent --add-port=5022/tcp
sudo firewall-cmd --reload

# 4. Перезапустить SSH
sudo systemctl restart sshd

# 5. Проверить
sudo semanage port -l | grep ssh
ss -tlnp | grep 5022
```

### Сценарий 4: Ограничение алгоритмов шифрования

**Задача:** Отключить устаревшие алгоритмы и оставить только современные.

```bash
# Добавить в sshd_config или отдельный файл
sudo tee /etc/ssh/sshd_config.d/ciphers.conf << 'EOF'
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org,diffie-hellman-group16-sha512
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com
HostKeyAlgorithms ssh-ed25519,rsa-sha2-512,rsa-sha2-256
EOF

# Проверить
sudo sshd -t
sudo systemctl restart sshd

# Протестировать подключение
ssh -oKexAlgorithms=curve25519-sha256 user@host
```

## Additional Information

### Инструменты защиты от атак

**fail2ban** — анализ логов и автоматическая блокировка IP при brute-force. См. [fail2ban: настройка и использование](../../Tools/fail2ban.md).

**Endlessh** — SSH-tarpit, бесконечно отправляющий баннер ботам, замедляя сканирование. [GitHub](https://github.com/skeeto/endlessh).

**Port Knocking** — скрытие SSH от сканирования через последовательность "стуков". См. [Port Knocking](./port_knocking.md).

### Аудит безопасности

```bash
# Проверить конфигурацию SSH
sudo sshd -T                          # Показать эффективную конфигурацию
sudo sshd -T | grep -i auth           # Только директивы аутентификации
sudo sshd -T | grep -i cipher         # Только шифрование

# Сканирование уязвимостей
ssh-audit <hostname>                  # Анализ алгоритмов и настроек
```

### Связанные темы

- [SSH Authentication](./ssh_authentication.md) — методы аутентификации
- [SSH Access Control](./ssh_access_control.md) — управление доступом
- [SSH Server Security Overview](./ssh_server_security_overview.md) — общая структура безопасности
- [Port Knocking](./port_knocking.md) — скрытие SSH
- [fail2ban](../../Tools/fail2ban.md) — защита от brute-force
