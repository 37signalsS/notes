# SSH — лучшие практики укрепления безопасности (Hardening)

## Определения

**SSH Hardening (Закалка SSH)** — комплекс мер по усилению безопасности SSH-сервера: отключение неиспользуемых функций, ограничение методов аутентификации, настройка криптографических параметров и мониторинг для защиты от автоматизированных и направленных атак.

**Defense in Depth (Эшелонированная защита)** — принцип многослойной защиты, при котором компрометация одного уровня (например, подбор пароля) не дает полного доступа к системе благодаря другим барьерам (например, 2FA или ограничение прав пользователя).

**Post-Quantum Cryptography (PQC)** — криптография, устойчивая к атакам квантовых компьютеров. В современных реализациях SSH (OpenSSH 9.8+) используются гибридные схемы, сочетающие классические алгоритмы (X25519) и постквантовые (ML-KEM/Kyber).

## Основные концепции

### Уровни защиты SSH

Безопасность SSH должна выстраиваться на нескольких эшелонах:

| Уровень | Механизм | Описание |
| :--- | :--- | :--- |
| **Сетевой** | Файрвол (nftables/iptables) | Ограничение доступа по IP, rate limiting новых соединений. |
| **Транспортный** | Port Knocking / SPA | Скрытие порта от сканеров до прохождения первичной проверки. |
| **Прикладной** | `sshd_config` | Тонкая настройка демона (аутентификация, шифры, таймауты). |
| **Мониторинг** | fail2ban, аудит | Блокировка атакующих на основе анализа логов и аудит конфига. |

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

### Современные алгоритмы (Стандарты 2026)

Для обеспечения долгосрочной безопасности (включая защиту от квантовых угроз) следует ограничить поддерживаемые алгоритмы:

```ssh
# 1. KexAlgorithms (Обмен ключами) — Приоритет ML-KEM и Ed25519
KexAlgorithms mlkem768x25519-sha256,sntrup761x25519-sha512@openssh.com,curve25519-sha256,curve25519-sha256@libssh.org

# 2. Ciphers (Шифрование) — Только современные AEAD шифры
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com

# 3. MACs (Целостность) — Использовать только EtM (Encrypt-then-MAC)
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com,hmac-sha2-256

# 4. HostKeyAlgorithms — Только безопасные типы
HostKeyAlgorithms ssh-ed25519,ssh-ed25519-cert-v01@openssh.com,rsa-sha2-512,rsa-sha2-256
```

**Диагностика доступных алгоритмов:**
```bash
ssh -Q kex       # Список поддерживаемых KEX
ssh -Q cipher    # Список поддерживаемых шифров
ssh -Q mac       # Список поддерживаемых MAC
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
LogLevel VERBOSE
StrictModes yes

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

# 4. Проверка и перезапуск
sudo sshd -t && sudo systemctl restart sshd
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

[Install]
WantedBy=multi-user.target
EOF

# 4. Активация
sudo systemctl daemon-reload
sudo systemctl enable --now sshd-alt
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

## Дополнительная информация

### Инструменты защиты

- **[fail2ban](../../Tools/fail2ban.md)** — блокировка IP после нескольких неудачных попыток входа (L7 анализ логов).
- **[Port Knocking](./port_knocking.md)** — механизм скрытия порта до прохождения последовательности «стуков».
- **Endlessh** — SSH-ловушка (tarpit), которая бесконечно удерживает соединения ботов, замедляя их сканирование.

### Регулярный аудит

1. **Проверка эффективного конфига**: `sudo sshd -T` (показывает настройки с учетом всех `Include` и `Match`).
2. **Аудит логов**: `journalctl -u sshd --since "yesterday"` для поиска аномалий.
3. **Обновление системы**: Уязвимости вроде `regreSSHion` (CVE-2024-6387) требуют немедленного обновления пакета `openssh-server`.

### См. также

- [SSH Server Security Overview](./ssh_server_security_overview.md) — общая стратегия защиты.
- [SSH Access Control](./ssh_access_control.md) — ограничение доступа по IP и пользователям.
- [SSH Authentication](./ssh_authentication.md) — методы аутентификации и ключи.
- [fail2ban](../../Tools/fail2ban.md) — автоматизация блокировок.
