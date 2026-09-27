# Диагностика и устранение неисправностей SSH

## Определения

**SSH Troubleshooting** — систематический процесс выявления проблем подключения: анализ клиентской конфигурации, сетевого пути, серверных настроев и аутентификации.

**Verbose Mode** — режим детализации SSH-клиента (`-v`, `-vv`, `-vvv`). Показывает каждый этап подключения в реальном времени — основной диагностический инструмент.

**SSH Handshake** — начальный этап соединения: согласование версии протокола, алгоритмов шифрования, обмена ключами. Сбои чаще всего вызваны несовместимостью конфигураций, сетевыми ограничениями или устаревшими алгоритмами.

**SSH-агент (ssh-agent)** — фоновый процесс, хранящий расшифрованные приватные ключи в оперативной памяти. Позволяет аутентифицироваться без повторного ввода парольной фразы. Должен быть запущен в текущей сессии: `eval "$(ssh-agent -s)"`.

**BatchMode** — режим SSH, при котором клиент не запрашивает ввод от пользователя (пароль, подтверждение fingerprint). Используется в CI/CD и автоматизации. При проблемах отключает интерактивные промпты, превращая их в ошибки.

**GSSAPI (Generic Security Services Application Program Interface)** — механизм аутентификации, часто используемый в корпоративных средах (Kerberos). При недоступности KDC вызывает задержки при подключении.

**StrictHostKeyChecking** — директива клиента, управляющая проверкой ключей хостов:
- `no` — автоматически добавлять новые ключи (уязвимо к MITM).
- `yes` — отклонять новые ключи без явного добавления в `known_hosts`.
- `accept-new` — автоматически добавлять новые, но отклонять измененные.

**ControlPersist / Stale Socket** — механизм мультиплексирования, при котором сокет управления остается после закрытия сессии на заданное время. При утечках или сбоях Ansible/CI/CD старые сокеты блокируют повторное подключение.

**TCPKeepAlive vs ServerAlive** — два независимых уровня проверки связи:
- `TCPKeepAlive` — транспортные keep-alive пакеты TCP-стека (уровень ОС). Может не обнаруживать зависший sshd.
- `ServerAliveInterval` — прикладной уровень SSH (шифрованные пакеты). Проверяет живость именно SSH-сессии.

## Базовые концепции

### Систематический подход

Диагностика идёт по цепочке: **Клиент → Сеть → Сервер → Аутентификация**.

| Этап | Что проверять | Инструменты |
| :--- | :--- | :--- |
| **Клиент** | Адрес, порт, DNS, локальный файрвол, `~/.ssh/config`, ssh-agent | `ssh -v`, `nslookup`, `ssh -G`, `getent hosts`, `ssh-add -l` |
| **Сеть** | Маршрут, блокировки портов, MTU (актуально для PQC), ARP | `ping`, `nc -zv`, `mtr`, `traceroute`, `tcpdump`, `ip neigh` |
| **Сервер** | Статус `sshd`, порт прослушивания, файрвол, ресурсы, journald | `systemctl status sshd`, `ss -tlpn`, `sshd -T`, `df -h`, `journalctl` |
| **Аутентификация** | Ключи, права доступа, FIDO2 токены, сертификаты CA, PAM | `ssh -vvv`, логи сервера, `ssh-keygen -L`, `ssh-add -l`, `faillock` |

### Этапы подключения SSH (RFC 4253)

Понимание последовательности помогает локализовать проблему по времени её возникновения в verbose-логе:

1.  **TCP- Handshake (L4):** Клиент отправляет SYN, сервер отвечает SYN-ACK. Если зависание здесь — проблема в маршрутизации или файрволе.
2.  **Обмен версиями:** Клиент и сервер обмениваются идентификаторами (`SSH-2.0-OpenSSH_9.8`). Несовпадение версий обычно не блокирует соединение.
3.  **KEX (Key Exchange):** Согласование алгоритмов и генерация общего секрета (например, Curve25519, MLKEM768). Сбои здесь — несовместимость алгоритмов или MTU-проблемы.
4.  **Аутентификация сервера:** Клиент проверяет host key. Ошибка `Host key verification failed` возникает именно здесь.
5.  **Аутентификация клиента:** Сервер проверяет ключ, пароль, сертификат или FIDO2. Ошибка `Permission denied` возникает здесь.
6.  **Сессия:** Установление канала, запрос PTY, запуск команды или shell.

### Источники информации

**Детальный вывод клиента:**

| Флаг | Детализация | Когда использовать |
| :--- | :--- | :--- |
| `-v` | Основные этапы (согласование, аутентификация) | Большинство типичных проблем |
| `-vv` | Выбранные алгоритмы, детали обмена (KEX) | Проблемы совместимости и шифрования |
| `-vvv` | Каждый пакет, отладка протокола | Ошибки FIDO2, SSH-агента и сертификатов |
| `-o LogLevel=DEBUG3` | Максимальная детализация без дублирования `-vvv` | Анализ проблем с прокси и конфигом |

**Логи сервера:**

| Дистрибутив | Команда / Путь |
| :--- | :--- |
| **systemd (все)** | `sudo journalctl -u ssh -f` (или `sshd`) |
| **Debian / Ubuntu** | `sudo tail -f /var/log/auth.log` |
| **RHEL / Rocky / Alma** | `sudo tail -f /var/log/secure` |

**Шаблоны поиска в логах:**

```bash
# Неудачные попытки аутентификации
sudo journalctl -u ssh --since "1 hour ago" | grep -E "Failed|refused|invalid user"

# Подозрительные IP (brute-force)
sudo journalctl -u ssh --since "24 hours ago" | grep -E "Invalid user|authentication failure" | awk '{for(i=1;i<=NF;i++) if($i~/^from=/) print substr($i,6)}' | sort | uniq -c | sort -rn | head

# Успешные входы
sudo journalctl -u ssh --since "24 hours ago" | grep "Accepted"
```

**Проверка эффективной конфигурации:**

Иногда реальные настройки отличаются от тех, что вы видите в файлах (из-за `Include`, `Match` блоков или значений по умолчанию).

```bash
# На стороне клиента: показать все примененные параметры для конкретного хоста
ssh -G myserver.com

# На стороне сервера: показать итоговую конфигурацию демона (effective config)
sudo sshd -T

# Запроsupported алгоритмы шифрования
ssh -Q cipher
ssh -Q cipher-auth
ssh -Q kex
ssh -Q key
ssh -Q mac
```

## Практические сценарии

### Сценарий 1: Соединение не устанавливается

**Симптомы:** `Connection timed out`, `Connection refused`, `No route to host`, `Unknown host`.

```bash
# 1. Разрешается ли имя?
nslookup <hostname>
dig +short <hostname>
```

Если DNS не сработал:
- **Проверить статическую запись** — `/etc/hosts` проверяется раньше DNS (через `nsswitch.conf`): `grep <hostname> /etc/hosts`.
- **Проверить резолвер** — какой DNS-сервер используется: `cat /etc/resolv.conf` (строка `nameserver`).
- **Проверить доступность резолвера:** `ping -c 3 <NS_IP>`.
- ** getent:** Если `dig` сработал, а `ssh` нет — проблема в системном резолвере (libc). Проверить: `getent hosts <hostname>`.
- **IPv6 vs IPv4:** Иногда клиент пытается использовать IPv6, который не настроен. Решение: `ssh -4 user@host`.

```bash
# 2. Проверить сетевой маршрут (если IP известен, но недоступен)
mtr -rw <server_ip>  # Объединяет ping и traceroute
# Потеря пакетов после конкретного хопа указывает на проблемный участок.

# 3. Проверить доступность порта
nc -zv <server_ip> 22
# succeeded! — порт открыт, проблема в sshd
# Connection refused — порт закрыт, sshd не запущен или файрвол шлет REJECT
# timed out — блокировка файрволом (DROP)
```

```bash
# 4. Проверить статус службы
sudo systemctl status sshd  # или ssh в Debian

# 5. Проверить порт прослушивания
sudo ss -tlpn | grep -E 'ssh|sshd'

# 6. Проверить файрвол
sudo iptables -L -n
sudo nft list ruleset
```

### Сценарий 2: Доступ запрещён (Аутентификация)

**Симптом:** `Permission denied (publickey,password)`.

#### Проблемы с authorized_keys (ключ добавлен, но запрашивает пароль)

1. **Неверные права доступа (Blocking Rule):**
   SSH-сервер игнорирует ключи, если права слишком открыты.
   ```bash
   chmod 700 ~/.ssh
   chmod 600 ~/.ssh/authorized_keys
   chmod 755 ~  # Домашняя директория НЕ должна быть 777
   ```

2. **Владелец файлов:**
   Убедитесь, что владельцем является текущий пользователь, а не `root`.
   ```bash
   chown -R $USER:$USER ~/.ssh
   ```

3. **Ошибки в формате ключа:**
   Ключ должен быть одной длинной строкой без переносов. Проверка: `cat -A ~/.ssh/authorized_keys`.

4. **SELinux (для RHEL / Alma / Rocky):**
   ```bash
   ls -Z ~/.ssh/authorized_keys  # Проверка контекста
   restorecon -Rv ~/.ssh          # Исправление
   ```

#### Диагностика через ssh-copy-id

```bash
# Типичная ошибка: ssh-copy-id зависает или падает
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@host
# → /usr/bin/ssh-copy-id: ERROR: failed to add key(s)

# Причины:
# 1. На сервере отключена аутентификация по ключам:
sudo sshd -T | grep pubkeyauthentication
# → pubkeyauthentication no

# 2. Нет прав на запись в authorized_keys:
# → Проверьте права и владельца (см. выше)

# 3. Неверный путь к authorized_keys:
sudo sshd -T | grep authorizedkeysfile
```

#### Проблемы FIDO2 / Security Keys

При использовании ключей типа `ed25519-sk`:
- **Симптом:** `sign_and_send_pubkey: signing failed: challenge-response failed`.
- **Причины:**
    - Отсутствует библиотека `libfido2` в системе.
    - Пользователь не коснулся токена вовремя (timeout).
- **Диагностика:** `ssh -vvv` покажет ожидание ответа от токена: `debug1: expect confirm at token`.

#### Проблемы SSH CA (Сертификаты)

- **Проверка сертификата:**
  ```bash
  ssh-keygen -L -f ~/.ssh/id_ed25519-cert.pub
  ```
- **Типичные ошибки:** `Certificate invalid: expired` (истек срок) или `principal mismatch` (имя пользователя не входит в список `Principals:` в сертификате).

#### Проблемы SSH-агента

```bash
# 1. Проверить, запущен ли агент
echo $SSH_AUTH_SOCK
# → /tmp/ssh-XXXX/agent.YYY (если пусто — агент не запущен)

# 2. Проверить загруженные ключи
ssh-add -l
# → The agent has no identities. (ключи не загружены)
# → Could not open a connection to your authentication agent. (агент не жив)

# 3. Загрузить ключ
ssh-add ~/.ssh/id_ed25519
# Enter passphrase for ...

# 4. Ошибка: Too many authentication failures
# Причина: в агенте загружено >6 ключей, сервер отклоняет соединение
# Решение: указать ключ явно
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519_prod user@host
```

### Сценарий 2.1: Учетная запись заблокирована

1. **Блокировка PAM (faillock):**
   - **Проверка:** `sudo faillock --user <username>`
   - **Сброс:** `sudo faillock --user <username> --reset`

2. **Заблокированный пароль в `/etc/shadow`:**
   Если в поле пароля стоит `!` или `*`, вход по паролю невозможен.
   - **Проверка:** `sudo passwd -S <username>` (статус `L` — locked).

3. **Срок действия пароля истек:**
   - **Проверка:** `chage -l <username>`

### Сценарий 2.2: Системные и внешние ограничения

1. **Файл `/etc/nologin`:** Если существует, вход разрешен только для `root`.
2. **Отсутствие свободного места:** Если диск заполнен, SSH не сможет создать сессию или записать логи.
   - **Проверка:** `df -h`
3. **Некорректная оболочка (Shell):**
   - **Проверка:** `getent passwd <username> | cut -d: -f7` (проверить наличие пути в `/etc/shells`).

### Сценарий 2.3: Изменение ключа хоста

**Симптом:** `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!`

**Проверка ключа без подключения — `ssh-keyscan`:**
```bash
# Получить fingerprint текущего ключа сервера
ssh-keyscan -t ed25519 target-host 2>/dev/null | ssh-keygen -lf -
```

**Решение:** Если изменение легитимно (переустановка ОС): `ssh-keygen -R <hostname_or_ip>`.

### Сценарий 2.4: Проблемы инициализации оболочки

**Симптом:** Соединение устанавливается, но сессия сразу закрывается или «висит».
- **Диагностика:** Попробовать вход без выполнения скриптов инициализации (`.bashrc`, `.zshrc`):
  ```bash
  ssh user@host "/bin/bash --noprofile --norc"
  ```

### Сценарий 2.5: Ограничения ресурсов сервера

1. **MaxStartups:** Количество одновременных «недоаутентифицированных» соединений.
2. **MaxSessions:** Лимит открытых сессий в рамках одного TCP-соединения (мультиплексирование).

### Сценарий 3: Медленное подключение

1. **Таймаут GSSAPI-аутентификации:**
   - **Диагностика:** В verbose-логе ищите строки `GSSAPI` или `Kerberos`.
   - **Решение:** `GSSAPIAuthentication no` в `~/.ssh/config`.
2. **Проблемы с Reverse DNS (на стороне сервера):**
   - **Диагностика:** В verbose-логе ищите длинные задержки между `Connecting` и `Authentication`.
   - **Решение:** `UseDNS no` в `/etc/ssh/sshd_config` (на стороне сервера).
3. **PQC (Post-Quantum) Handshake (2026+):**
   Пакеты KEXINIT в постквантовых алгоритмах значительно больше (несколько КБ).
   - **Симптом:** Зависание после обмена версиями.
   - **Причина:** Проблемы с MTU/фрагментацией в сети.
   - **Диагностика:** Временно отключить PQC: `ssh -o "KexAlgorithms=curve25519-sha256" user@host`.

### Сценарий 4: Соединение «зависает» (MTU/MSS)

**Симптом:** Мелкие команды (ls) работают, крупные (ls -R, cat файла) «вешают» терминал.
- **Диагностика:** `ping -M do -s 1472 <host>` (поиск максимального MTU).
- **Решение:** MSS Clamping на роутере или уменьшение MTU на интерфейсе.

### Сценарий 5: Разрыв соединения при бездействии

**Решение:** Настройка keep-alive.

| Параметр | Сторона | Файл |
| :--- | :--- | :--- |
| `ServerAliveInterval` | Клиент | `~/.ssh/config` |
| `ClientAliveInterval` | Сервер | `/etc/ssh/sshd_config` |
| `TCPKeepAlive` | Сервер (TCP) | `/etc/ssh/sshd_config` |

```ini
# Пример клиентской настройки
Host *
  ServerAliveInterval 60
  ServerAliveCountMax 3
```

### Сценарий 6: Проблемы с передачей файлов (scp, sftp, rsync)

**Симптом:** `scp` зависает, `rsync` обрывается на больших файлах, `sftp` не может подключиться.

#### scp / sftp

```bash
# 1. Проверить, что подсистема sftp включена на сервере
sudo sshd -T | grep sftp
# → subsystem sftp /usr/lib/openssh/sftp-server

# 2. Для scp проверить shell и права
# scp требует доступного shell (не nologin), если не используется subsystem

# 3. Диагностика через sftp клиент
sftp -v user@host
# Ищите ошибки "Subsystem request failed" или "Connection closed"
```

#### rsync через SSH

```bash
# 1. Проверить, что remote-shell доступен
rsync -avz --progress --rsh="ssh -vvv" /src/ user@host:/dst/

# 2. Частая ошибка: неверные права на целевую директорию
# → Permission denied (write)
# Решение: chown/chmod на удаленной стороне

# 3. Ограничение ресурсов на удаленной стороне
# Если сессия рвется на больших файлах — проверьте ulimit, disk quota
```

### Сценарий 7: Базовая диагностика Jump Host / Bastion цепочки

**Симптом:** `ssh -J bastion user@target` зависает или падает с `Connection timed out`.

```bash
# 1. Проверить доступность Jump Host напрямую
ssh -v user@bastion
# Если не проходит — проблема на L3/L4 (маршрут, файрвол, sshd на bastion)

# 2. Проверить проброс порта через bastion
ssh -J bastion -o ProxyCommand="nc -zv %h %p" user@target

# 3. Проверить AllowTcpForwarding на bastion
ssh user@bastion "sudo sshd -T | grep allowtcpforwarding"
# → allowtcpforwarding yes

# 4. Проверить целостность host key bastion
ssh-keygen -F bastion
# → Found a key belonging to hostname
# → Not found: ключ не добавлен
```

> **См. также:** [Конфигурация клиента SSH](./ssh_client_config.md) — продвинутые сценарии с `ProxyJump` и `ProxyCommand`.

### Сценарий 8: Диагностика CI/CD и автоматизации

**Симптом:** `GIT_SSH_COMMAND="ssh -vvv"` показывает `Permission denied (publickey)` в пайплайне, хотя локально работает.

```bash
# 1. Проверить, загружен ли ключ в агент пайплайна
ssh-add -l
# → Если "The agent has no identities" — ключ не добавлен

# 2. Проверить права на приватный ключ в окружении CI
ls -la ~/.ssh/id_ed25519
# → Должен быть 600

# 3. Проверить known_hosts
# В CI/CD часто отсутствует known_hosts
# Решение:
#   - StrictHostKeyChecking=accept-new
#   - или явный ssh-keyscan в шаге before_script

# 4. Ansible: зависание при первом запуске
# Причина: ControlPersist сокет от предыдущего сбоя
ansible all -m shell -a 'exit' --ssh-extra-args='-O exit'
# → Принудительное закрытие всех сокетов
```

### Сценарий 9: Анализ логов и автоматизация диагностики

#### Паттерны journald / syslog

```bash
# Топ-10 IP по количеству неудачных попыток за последний час
sudo journalctl -u ssh --since "1 hour ago" | \
  grep "Failed password" | \
  awk '{for(i=1;i<=NF;i++) if($i~/^from=/) print substr($i,6)}' | \
  sort | uniq -c | sort -rn | head

# Поиск попыток входа под несуществующими пользователями
sudo journalctl -u ssh --since "24 hours ago" | grep "Invalid user"

# Поиск успешных входов для аудита
sudo journalctl -u ssh --since "24 hours ago" | grep "Accepted"
```

#### Сценарии brute-force

```bash
# 1. Проверить, активна ли атака
sudo journalctl -u ssh --since "10 minutes ago" | grep -c "Failed password"
# → Если >100 за 10 минут — активная атака

# 2. Временная блокировка через nftables (без fail2ban)
sudo nft add element inet filter ssh_bruteforce { $(sudo journalctl -u ssh --since "5 minutes ago" | grep "Failed password" | awk '{for(i=1;i<=NF;i++) if($i~/^from=/) print substr($i,6)}' | sort | uniq) }
```

### Сценарий 10: Edge cases и нестандартные окружения

#### Unicode и локали

При проблемах с отображением (кракозябры в менеджере пакетов, editor):
```bash
# Указать локаль при подключении
ssh -o "SetEnv=LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8" user@host
```

#### PTY allocation failed

```bash
# Симптом: "PTY allocation request failed on channel 0"
# Причина: на сервере исчерпан лимит PTY или нет свободных устройств /dev/pts
# Диагностика на сервере:
ssh user@host "ls /dev/pts | wc -l"
ssh user@host "cat /proc/sys/kernel/pty/max"
```

#### tcp_wrappers (legacy)

В старых дистрибутивах (RHEL 6, CentOS 6) работают `hosts.allow` / `hosts.deny`:
```bash
# Проверка
cat /etc/hosts.deny | grep sshd
# → sshd: ALL (блокирует всех)
cat /etc/hosts.allow | grep sshd
# → sshd: 10.0.0.0/24 (разрешает подсеть)
```

#### Конфликты с systemd / logind

Если при выходе из SSH сессия продолжает висеть на сервере:
```bash
# Проверить KillUserProcesses
cat /etc/systemd/logind.conf | grep KillUserProcesses
# → KillUserProcesses=yes (по умолчанию в Fedora/RHEL)
# Решение: использовать tmux/screen, или отключить KillUserProcesses
```

## Дополнительная информация

### Запуск `sshd` в отладочном режиме

Безопасный способ тестирования конфигурации сервера (не уходит в фон, только одно соединение):
```bash
sudo /usr/sbin/sshd -d -p 2222
```

### Ошибки SSH Multiplexing

**Симптом:** `unix_listener: path too long`.
- **Причина:** Длина пути Unix-сокета (ControlPath) ограничена ~108 символами.
- **Решение:** Использовать сокращенный путь в `~/.ssh/config`: `ControlPath ~/.ssh/S/%r@%h:%p`.

### Проблема «Too many authentication failures»

Если в `ssh-agent` много ключей, сервер блокирует соединение после нескольких попыток.
- **Решение:** `ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa user@host`.

### Анализ трафика с помощью Wireshark/tcpdump

| Этап | Пакет | Интерпретация |
| :--- | :--- | :--- |
| **KEX Init** | `Key Exchange Init` | Если обрывается здесь — проблема в MTU или шифрах. |
| **New Keys** | `New Keys` | Канал установлен — проблема только в аутентификации. |

### Быстрая диагностика: чек-лист

```bash
# 1. Эффективная конфигурация
ssh -G myserver.com | grep -E "hostname|port|user"

# 2. Проверка доступности и баннера
nc -zv myserver.com 22
ssh user@host -v 2>&1 | head -20

# 3. Алгоритмы и аутентификация
ssh user@host -vv 2>&1 | grep -E "kex|cipher|Authentications"

# 4. Проверка на сервере
sudo sshd -t && sudo journalctl -u ssh -n 50
```

### Поддерживаемые алгоритмы

```bash
# Проверить, что поддерживает клиент
ssh -Q cipher
ssh -Q cipher-auth
ssh -Q kex
ssh -Q key
ssh -Q mac

# Проверить эффективные алгоритмы для конкретного хоста
ssh -vvv user@host 2>&1 | grep -E "kex| cipher|mac"
```

### См. также

- [Конфигурация клиента SSH](./ssh_client_config.md) — `~/.ssh/config`, `ssh -G`, verbose-режим, Jump-хосты.
- [SSH Authentication](./server/ssh_authentication.md) — ключи, FIDO2, CA, `ssh-copy-id`, права доступа.
- [Практическое использование SSH и туннелирование](./ssh_usage_and_tunnels.md) — Port Forwarding, SOCKS5, `scp`/`sftp`/`rsync`.
- [Инструменты сетевого мониторинга](../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для диагностики SSH-трафика.
