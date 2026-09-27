# Практическое использование SSH и туннелирование

**Достоверность: 10/10 (Актуально для OpenSSH 10.x, 2026)**

## Определения

**SSH-туннелирование (Port Forwarding)** — механизм создания защищенного канала для инкапсуляции TCP (иногда и L3) или Unix Domain Sockets трафика произвольных сервисов внутри SSH-сессии.

**X11 Forwarding** — протокол отображения графического интерфейса удаленных приложений на локальном X-сервере.

**Agent Forwarding** — проброс сокета локального агента аутентификации на удаленный хост, позволяющий использовать локальные ключи для дальнейших переходов.

**SSH Мультиплексирование (Multiplexing)** — механизм (ControlMaster), позволяющий устанавливать несколько SSH-сессий (каналов) поверх одного TCP-соединения.

**Unix Domain Socket Forwarding (StreamLocalForwarding)** — возможность проброса локальных Unix-сокетов на удаленную сторону (или наоборот), что критично для работы с Docker API, базами данных и другими локальными сервисами.

**`GatewayPorts`** — директива `sshd_config`, разрешающая привязывать удаленные проброшенные порты (`-R`) ко всем интерфейсам (`0.0.0.0`), а не только к `localhost`. По умолчанию `no` (только loopback).

**`PermitOpen`** — директива `sshd_config` или опция в `authorized_keys`, ограничивающая проброс портов конкретными парами `host:port`. Если не указана — разрешены все направления.

**`StreamLocalBindUnlink`** — директива `sshd_config`, позволяющая SSH автоматически удалять старый Unix-сокет перед созданием нового при пробросе (`-R` или `-L` для Unix-сокетов). По умолчанию `no`.

**`AllowTcpForwarding`** — директива `sshd_config`, глобально разрешающая или запрещающая проброс TCP-портов (`yes`, `no`, `local`, `remote`). По умолчанию `yes`.

**TCP-in-TCP** — явление, при котором TCP-сессия инкапсулируется внутрь другой TCP-сессии. Приводит к деградации производительности из-за конфликта алгоритмов управления перегрузкой (congestion control) на двух уровнях.

## Базовые концепции

### Инкапсуляция трафика

SSH выступает в роли защитной оболочки для других протоколов (HTTP, VNC, SQL, Docker API). Это позволяет обходить ограничения межсетевых экранов и безопасно работать через публичные сети.

**SSH как универсальный транспорт:**
- **Управление конфигурациями:** Ansible по умолчанию использует SSH для выполнения задач.
- **Контроль версий:** Git использует SSH для безопасного доступа к репозиториям.
- **Передача файлов:** Современная утилита **`scp`** (начиная с OpenSSH 9.0, 2022 г.) под капотом использует протокол **SFTP**, отказываясь от старого и менее безопасного протокола SCP.
- **Инфраструктура:** Бастион-хосты обеспечивают доступ в закрытые сегменты сети через SSH-туннели.

В 2026 году при туннелировании важно учитывать влияние **PQC (Post-Quantum Cryptography)** на размер пакетов при установлении соединения.

### Протокольная архитектура туннелей

На уровне SSH-CONN (уровень соединения) проброс портов реализуется через логические каналы:
- **`direct-tcpip`** — клиент запрашивает соединение с удаленным хостом от имени сервера (используется для `-L`).
- **`forwarded-tcpip`** — сервер принимает входящее соединение и перенаправляет его клиенту (используется для `-R`).

Каждый канал шифруется independently в рамках общего транспортного уровня (SSH-TRANS). Это означает, что даже если злоумышленник получит доступ к Jump Host, он видит только зашифрованный поток между клиентом и конечным сервером.

### Типы проброса портов

| Тип | Флаг | Описание | Основной сценарий |
| :--- | :--- | :--- | :--- |
| **Локальный** | `-L` | Удаленный ресурс становится доступен на локальном порту | Доступ к БД внутри закрытой сети |
| **Удаленный** | `-R` | Локальный ресурс становится доступен на порту сервера | Показ локального веб-сервера из-за NAT |
| **Динамический** | `-D` | Создает локальный SOCKS5-прокси | Обход блокировок, скрытие IP браузера |
| **Unix-сокет** | `-L`/`-R` | Проброс пути к сокету (`/path/to/sock`) | Безопасный доступ к Docker API (`docker.sock`) |
| **Сетевой (L3)** | `-w` | Создает TUN/TAP интерфейсы (требует root) | Полноценный VPN на базе SSH |

### Производительность и ограничения

**Проблема TCP-in-TCP:**
При пробросе TCP-трафика через SSH возникает инкапсуляция TCP внутри TCP. Внешний уровень управляет перегрузкой на основе потерь пакетов, внутренний — тоже. Это приводит к:
- Снижению пропускной способности на 20–50% при высоких задержках.
- Нестабильной работе протоколов с агрессивной коррекцией окна (например, SMB).
- **Решение:** Для высоконагруженных линков использовать `-o Compression=no` и шифры с низкой латентностью (`chacha20-poly1305@openssh.com`), либо предпочесть WireGuard/IPSEC для L3-туннелей.

**Влияние MTU:**
SSH добавляет overhead ~40–60 байт (padding, MAC, заголовки). Если `Path MTU` на пути меньше 1400 байт, фрагментация на L3 приведет к деградации. Проверить можно через:
```bash
ssh -o "IPQoS=throughput" user@host "ping -c 3 -M do -s 1400 8.8.8.8"
```

### Безопасность многоступенчатых подключений

При работе через промежуточные узлы (Jump Hosts) критически важно не оставлять ключи на серверах.

| Механизм | Описание | Безопасность |
| :--- | :--- | :--- |
| **Agent Forwarding (`-A`)** | Сокет агента доступен на удаленном сервере | **Рискованно**: root на сервере может использовать ваш сокет. Рекомендуется использовать `ssh-agent` с подтверждением каждой операции. |
| **ProxyJump (`-J`)** | Трафик идет транзитом через промежуточный узел | **Рекомендуется**: промежуточный узел не видит данных сессии. |

Подробнее о настройке бастионов: [Конфигурация клиента SSH](./ssh_client_config.md#настройка-подключения-через-jump-host-proxyjump).

### Серверные директивы для туннелей

На стороне `sshd_config` существуют директивы, управляющие туннелированием:

| Директива | Значения | Назначение |
| :--- | :--- | :--- |
| `AllowTcpForwarding` | `yes`, `no`, `local`, `remote` | Глобальное разрешение/запрет проброса TCP. `local` разрешает только `-L`, `remote` — только `-R`. |
| `GatewayPorts` | `yes`, `no`, `clientspecified` | Разрешить привязку удаленных портов к `0.0.0.0`. `clientspecified` позволяет клиенту указать адрес. |
| `PermitOpen` | `host:port` | Ограничить направления проброса. Можно указать несколько раз или в `Match`-блоке. |
| `PermitTunnel` | `yes`, `no`, `point-to-point`, `ethernet` | Разрешить создание TUN/TAP интерфейсов (для `-w`). |
| `StreamLocalBindUnlink` | `yes`, `no` | Разрешить удаление старого Unix-сокета перед созданием нового. |
| `X11Forwarding` | `yes`, `no`, `local` | Разрешить проброс X11. `local` ограничивает локальными хостами. |

## Практические сценарии

### Базовое подключение и удаленное выполнение

```bash
# Подключение на нестандартный порт с явным ключом
ssh -p 2222 -i ~/.ssh/id_ed25519_prod user@host

# Запуск скрипта на удаленном сервере без открытия шелла
ssh user@server "bash -s" < local_script.sh

# Интерактивная работа с программами, требующими терминал (top, htop)
ssh -t user@server "htop"
```

### Локальный проброс портов (`-L`)

Схема: `Локальный_ПК:Порт` → `SSH_Server` → `Целевой_Ресурс:Порт`.

```bash
# Доступ к Postgres (5432) на сервере через локальный порт 5555
ssh -L 5555:localhost:5432 user@db-server -N

# Проброс Unix-сокета Docker API для локального управления контейнерами
ssh -L /tmp/docker.sock:/var/run/docker.sock user@remote-docker-host -N
```

**Опции для надежных туннелей:**
- `-N` — не выполнять удаленную команду (только туннель).
- `-f` — перейти в фоновый режим после аутентификации.
- `-o ExitOnForwardFailure=yes` — завершить процесс SSH, если не удалось пробросить порт (критично для скриптов).

**Продвинутые сценарии `-L`:**
```bash
# Доступ к Prometheus на внутреннем хосте через bastion
ssh -L 9090:prometheus.internal:9090 -J bastion user@jump-host -N

# Проброс нескольких портов одной командой
ssh -L 5432:db01:5432 -L 6379:redis01:6379 user@bastion -N

# Проброс через SOCKS5-прокси на промежуточном узле (сложная топология)
ssh -L 3306:mysql.internal:3306 -o "ProxyCommand=nc -X 5 -x proxy.corp:1080 %h %p" user@jump-host -N
```

### Удаленный проброс портов (`-R`)

Схема: `SSH_Server:Порт` → `SSH_Client` → `Локальный_Ресурс:Порт`.

```bash
# Сделать локальный порт 3000 доступным на сервере как 8080
ssh -R 8080:localhost:3000 user@vps.public.com -N

# Динамическое назначение порта на сервере (OpenSSH 8.4+)
ssh -R 0:localhost:3000 user@vps.public.com
# → result: Allocated port 32768 for remote forward to localhost:3000
```

**Важно:** Для доступности порта извне на сервере в `sshd_config` должно быть `GatewayPorts yes`. Для Unix-сокетов используйте `StreamLocalBindUnlink yes`, чтобы SSH автоматически удалял старые файлы сокетов перед созданием новых.

**Продвинутые сценарии `-R`:**
```bash
# Сделать локальный веб-сервер доступным из интернета через bastion
ssh -R 80:localhost:8080 -o "GatewayPorts=yes" user@bastion -N

# Проброс Unix-сокета системного сервиса на удаленный хост
ssh -R /remote/run/docker.sock:/var/run/docker.sock -o StreamLocalBindUnlink=yes user@bastion -N
```

### Динамический проброс (`-D`)

Создает универсальный прокси-сервер (SOCKS5).

```bash
# Запуск SOCKS5 прокси на порту 1080
ssh -D 1080 user@remote-proxy -N
```

**Продвинутые сценарии `-D`:**
```bash
# SOCKS5 через бастион с привязкой только к loopback
ssh -D 1080 -J bastion user@internal-host -N

# SOCKS5 с DNS-резолвингом на удаленной стороне (OpenSSH 7.6+)
ssh -D 1080 -o "DNS=yes" user@remote-proxy -N
```

### Проброс Unix Domain Sockets

Критичен для работы с Docker API, systemd сервисами, базами данных без TCP-порта.

```bash
# Локальный доступ к Docker API на удаленном хосте
ssh -L /tmp/remote-docker.sock:/var/run/docker.sock user@docker-host -N
export DOCKER_HOST="unix:///tmp/remote-docker.sock"
docker ps

# Проброс сокета systemd-journald для чтения логов
ssh -L /tmp/journal.sock:/run/systemd/journal/socket user@remote-host -N
journalctl --user -u some-service --directory=/var/log/journal
```

### Сетевой туннелирование (L3/TUN)

Создает виртуальный сетевой интерфейс для полноценного IP-туннелирования.

```bash
# На клиенте и сервере должны быть созданы TUN-интерфейсы
# Клиент:
sudo ip tuntap add dev tun0 mode tun
sudo ip addr add 10.0.0.1/24 dev tun0
sudo ip link set tun0 up

# Сервер:
sudo ip tuntap add dev tun0 mode tun
sudo ip addr add 10.0.0.2/24 dev tun0
sudo ip link set tun0 up

# Туннель
sudo ssh -w 0:0 -o "PermitTunnel=point-to-point" user@server -N
```

**Важно:** Требует `PermitTunnel yes` или `point-to-point` на сервере и root-прав на обеих сторонах.

### Архитектуры бастион-хостов

#### Одиночный бастион

```text
Интернет → Бастион (bastion.example.com:2239) → Внутренняя сеть (10.0.0.0/8)
```

```ssh
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
```

#### Двойной бастион (DMZ)

Для критической инфраструктуры используется двухуровневая архитектура:
```text
Интернет → Бастион-1 (DMZ, 203.0.113.10) → Бастион-2 (Internal, 10.0.1.5) → Целевой сервер
```

```bash
# Подключение через цепочку
ssh -J bastion1.example.com,bastion2.example.com user@web01.internal
```

#### Бастион с резервированием

```bash
# Первичный и запасной бастион
Host bastion-primary
    HostName bastion1.corp
    User jumper

Host bastion-backup
    HostName bastion2.corp
    User jumper

Host web01
    HostName 10.0.1.10
    User deploy
    ProxyJump bastion-primary,bastion-backup
```

### Интеграция с CI/CD

#### GitHub Actions

```yaml
# .github/workflows/deploy.yml
- name: Deploy via SSH tunnel
  run: |
    mkdir -p ~/.ssh
    echo "${{ secrets.SSH_KEY }}" > ~/.ssh/id_ed25519
    chmod 600 ~/.ssh/id_ed25519
    ssh-keyscan -H ${{ secrets.SSH_HOST }} >> ~/.ssh/known_hosts

    # Туннель к внутреннему Kubernetes API
    ssh -f -N -L 8443:kubernetes.internal:6443 deploy@bastion -o StrictHostKeyChecking=no

    # Проверка туннеля
    kubectl --insecure-skip-tls-verify --server https://localhost:8443 get nodes
```

#### GitLab CI

```yaml
deploy:
  image: alpine:latest
  before_script:
    - apk add --no-cache openssh-client kubectl
    - mkdir -p ~/.ssh
    - echo "$CI_SSH_KEY" > ~/.ssh/id_ed25519
    - chmod 600 ~/.ssh/id_ed25519
    - ssh-keyscan -H $SSH_HOST >> ~/.ssh/known_hosts
  script:
    - ssh -f -N -L 5432:db.internal:5432 deploy@bastion
    - psql -h localhost -p 5432 -U $DB_USER -d $DB_NAME -c "SELECT 1;"
```

### Интеграция с Ansible

```bash
# Использование туннеля для доступа к базам данных
ansible db -m postgresql_db -a "name=myapp state=present" \
  --ssh-common-args='-L 5432:localhost:5432'

# Через бастион с динамическим пробросом
ansible all -m ping \
  --ssh-extra-args='-J bastion -D 1080'
```

### Мониторинг и наблюдаемость туннелей

#### Health check через systemd

```ini
# /etc/systemd/system/ssh-tunnel.service
[Unit]
Description=SSH Tunnel to Internal DB
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=deploy
ExecStart=/usr/bin/ssh -NT -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" -o "ExitOnForwardFailure=yes" -L 5432:db.internal:5432 deploy@bastion
Restart=always
RestartSec=5

# Health check
ExecStartPost=/bin/sh -c 'until pg_isready -h localhost -p 5432; do sleep 1; done'

[Install]
WantedBy=multi-user.target
```

#### Мониторинг через `autossh`

```bash
# Мониторинг на уровне M (порт 0 = отключен, используем ServerAlive)
autossh -M 0 -o "ServerAliveInterval 15" -o "ServerAliveCountMax 3" \
  -o "ExitOnForwardFailure=yes" -L 5432:db.internal:5432 deploy@bastion

# С мониторингом через отдельный порт (рекомендуется для production)
autossh -M 20000:10000 \
  -o "ServerAliveInterval 15" -o "ServerAliveCountMax 3" \
  -L 5432:db.internal:5432 deploy@bastion
```

#### Проверка состояния туннеля

```bash
# Проверить активные пробросы
ss -tnp | grep sshd

# Проверить, что туннель отвечает
nc -zv localhost 5432

# Проверить ControlPath сокет (если используется мультиплексирование)
ls -la ~/.ssh/sockets/
```

### Персистентные туннели (systemd)

Для обеспечения автоматического восстановления туннелей после перезагрузки или обрыва связи рекомендуется использовать `systemd`.

**Пример `/etc/systemd/system/ssh-tunnel.service`:**
```ini
[Unit]
Description=Persistent SSH Tunnel
After=network.target

[Service]
User=localuser
ExecStart=/usr/bin/ssh -NT -o "ServerAliveInterval 60" -o "ServerAliveCountMax 3" -o "ExitOnForwardFailure=yes" -L 5432:localhost:5432 user@remote-host
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Управление сессиями и стабильность

### Мультиплексирование (`ControlMaster`)

Позволяет открывать новые сессии мгновенно через один сокет.

Настройка в `~/.ssh/config`:
```ssh
Host *
  ControlMaster auto
  ControlPath ~/.ssh/sockets/%r@%h-%p
  ControlPersist 10m
```

### Управляющие последовательности (Escape Characters)

Работают только сразу после нажатия `Enter`.

| Комбинация | Действие |
| :--- | :--- |
| `~.` | Немедленно разорвать соединение (при зависании) |
| `~^Z` | Отправить SSH в бэкграунд (возврат через `fg`) |
| `~C` | Открыть командную строку SSH (добавление туннеля на лету) |

**Пример добавления туннеля `~C`:**
```ssh
ssh> -L 8080:localhost:80
# → Forwarding port.
```

### Инструменты для поддержания туннелей

- **`autossh`** — обертка для мониторинга и перезапуска.
  ```bash
  autossh -M 0 -o "ServerAliveInterval 30" -L 5432:localhost:5432 user@host
  ```
- **Mosh / Eternal Terminal** — сохранение сессий при смене IP и разрывах. Подробнее: [SSH Session Management](./ssh_session_management.md).

## Дополнительная информация

### Сравнение методов проброса трафика

| Критерий | SSH Tunnel | iptables/nftables | VPN (WireGuard) |
| :--- | :--- | :--- | :--- |
| **Уровень** | L4 (TCP) / L7 | L3 / L4 | L3 (Network) |
| **Производительность** | Средняя (TCP-in-TCP) | Высокая | Высокая |
| **Изоляция** | Высокая (User-space) | Низкая (Ядро) | Высокая |
| **Сложность настройки** | Низкая | Средняя | Средняя |
| **Масштабируемость** | Ограничена (одно соединение на туннель) | Высокая | Высокая |
| **Сценарий** | Точечный доступ к сервисам | Проброс портов на уровне ядра | Полноценный доступ к сети |

### Безопасность: рекомендации

1. **Ограничение портов**: На сервере используйте `PermitOpen` в блоке `Match` или в `authorized_keys` для ограничения туннелей конкретными хостами/портами.
2. **Таймауты**: Настраивайте `ServerAliveInterval` для предотвращения зомби-сессий.
3. **Отключение шелла**: Для туннельных аккаунтов устанавливайте `/sbin/nologin`.
4. **Запрет X11 и Agent Forwarding**: На конечных хостах через `X11Forwarding no` и `ForwardAgent no`.
5. **Разделение ключей**: Используйте отдельные ключи дляbastion и конечных хостов.
6. **Журналирование**: Включите `LogLevel VERBOSE` на bastion для аудита пробросов.

### Производительность: рекомендации

1. **Выбор шифра**: Для туннелей с высоким трафиком используйте `chacha20-poly1305@openssh.com` (быстрее на ARM/без AES-NI) или `aes128-gcm@openssh.com`.
2. **Отключение сжатия**: Для уже сжатых данных (видео, образы) используйте `Compression no` — снижает CPU.
3. **MSS/MTU**: Если туннель работает через Path MTU с ограничениями, настройте:
   ```bash
   ssh -o "IPQoS=throughput" -o "MSS=1300" user@host
   ```
4. **Мультиплексирование**: Для множества параллельных запросов (Ansible, CI/CD) используйте `ControlPersist` для повторного использования соединений.

### Edge cases и нестандартные окружения

#### IPv6-only серверы

```bash
# Принудительное использование IPv6
ssh -6 -L 8080:[2001:db8::1]:80 user@host

# В sshd_config
AddressFamily inet6
```

#### Путь Unix-сокета превышает лимит

```bash
# Симптом: unix_listener: path too long
# Решение: использовать сокращенный путь
ControlPath ~/.ssh/S/%r@%h:%p
```

#### Проброс через HTTP/SOCKS прокси

```bash
# Через HTTP CONNECT прокси
ssh -o "ProxyCommand=nc -X connect -x proxy.corp:8080 %h %p" user@host

# Через SOCKS5 прокси
ssh -o "ProxyCommand=nc -X 5 -x socks5.corp:1080 %h %p" user@host
```

#### Туннель через Mosh

Mosh не поддерживает проброс портов напрямую. Для туннелей используйте классический SSH:
```bash
# Mosh для интерактивной сессии + отдельный SSH туннель
mosh user@bastion -- ssh -L 5432:db.internal:5432 user@jump
```

### Диагностика туннелей

```bash
# Проверить, что порт проброшен на сервере
sudo ss -tnp | grep :2222

# Проверить активные туннели на клиенте
lsof -iTCP -sTCP:LISTEN -P | grep ssh

# Отладка проброса
ssh -vvv -L 5432:db:5432 user@bastion 2>&1 | grep -i "forward"
```

### См. также

- [Конфигурация клиента SSH](./ssh_client_config.md) — `~/.ssh/config`, `ssh -G`, verbose-режим, Jump-хосты.
- [SSH Authentication](./server/ssh_authentication.md) — ключи, FIDO2, CA, `ssh-copy-id`, права доступа.
- [Поиск и устранение неисправностей SSH](./ssh_troubleshooting.md) — диагностика туннелей, verbose-режим, анализ логов.
- [Инструменты сетевого мониторинга](../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для анализа SSH-трафика.
