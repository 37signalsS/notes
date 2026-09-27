# SSH в отказоустойчивых и высокодоступных системах

## Определения

**SSH Multiplexing (ControlPersist)** — механизм OpenSSH для переиспользования одного TCP-соединения для нескольких последовательных SSH-сессий. Снижает накладные расходы на handshake и обеспечивает мгновенное переподключение.

**SSH Connection Keepalive** — механизм поддержания активности SSH-соединения через периодические проверки (ServerAliveInterval/ClientAliveInterval). Предотвращает разрыв соединения при бездействии.

**Bastion HA Cluster** — кластер из нескольких bastion-хостов за общим VIP или DNS, обеспечивающих отказоустойчивый SSH-доступ к внутренним узлам.

**ProxyJump Failover** — автоматическое переключение на резервный bastion при недоступности основного через SSH config.

**SSH Connection Migration** — бесшовная миграция SSH-соединения с одного хоста на другой (например, при обновлении bastion).

**ControlMaster Auto** — параметр OpenSSH, автоматически создающий и управляющий master-соединениями для мультиплексирования.

## Базовые концепции

### Архитектура отказоустойчивого SSH-доступа

```
┌─────────────────────────────────────────────────────────┐
│              Клиент (инженер/CI-CD)                      │
│  ┌─────────────────────────────────────────────────────┐│
│  │  SSH Config: ProxyJump bastion-vip.example.com      ││
│  └───────────────────────┬─────────────────────────────┘│
└──────────────────────────┼──────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   VIP/DNS   │
                    │  bastion-vip│
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────▼─────┐    ┌─────▼─────┐    ┌─────▼─────┐
    │  Bastion  │    │  Bastion  │    │  Bastion  │
    │  (Active) │    │ (Standby) │    │  (Active) │
    └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                    ┌──────▼──────┐
                    │  Internal   │
                    │  Network    │
                    └─────────────┘
```

### Механизмы отказоустойчивости

| Механизм | Описание | Когда использовать |
| :--- | :--- | :--- |
| **SSH Multiplexing** | Переиспользование соединений | Всегда (ускорение + resilience) |
| **Keepalive** | Поддержание активности соединения | Нестабильная сеть |
| **ProxyJump Failover** | Переключение на резервный bastion | HA bastion-кластер |
| **ControlMaster Auto** | Автоматическое управление соединениями | Все сценарии |
| **Connection Migration** | Бесшовная миграция соединения | Обновление bastion без даунтайма |

## Практические сценарии

### Сценарий 1: SSH Multiplexing для мгновенного переподключения

**Задача**: Настроить SSH для мгновенного переподключения после разрыва.

```bash
# ~/.ssh/config

# Базовая настройка Multiplexing
Host bastion
    HostName bastion.example.com
    User admin
    IdentityFile ~/.ssh/id_ed25519

    # Мультиплексирование
    ControlMaster auto
    ControlPersist 3600s  # Соединение живет 1 час после закрытия
    ControlPath ~/.ssh/sockets/%r@%h-%p

    # Keepalive
    ServerAliveInterval 30
    ServerAliveCountMax 3

# Внутренние узлы через bastion
Host 10.0.1.*
    ProxyJump bastion
    User admin
    IdentityFile ~/.ssh/id_ed25519

    # Мультиплексирование для каждого хоста
    ControlMaster auto
    ControlPersist 3600s
    ControlPath ~/.ssh/sockets/%r@%h-%p
```

**Проверка:**
```bash
# Создание директории для сокетов
mkdir -p ~/.ssh/sockets

# Первое подключение (создает master)
ssh -v bastion 2>&1 | grep -i "ControlMaster"

# Проверка активных соединений
ls -la ~/.ssh/sockets/
# → admin@bastion-22

# Второе подключение (использует master)
ssh -v bastion 2>&1 | grep -i "Connection sharing"
# → debug1: Connection sharing enabled
```

### Сценарий 2: Bastion HA с ProxyJump Failover

**Задача**: Настроить автоматическое переключение на резервный bastion.

```bash
# ~/.ssh/config

# Список bastion-хостов
Host bastion-primary
    HostName bastion1.example.com
    User admin
    IdentityFile ~/.ssh/id_ed25519
    ControlMaster auto
    ControlPersist 3600s
    ControlPath ~/.ssh/sockets/%r@%h-%p
    ServerAliveInterval 30
    ServerAliveCountMax 3

Host bastion-secondary
    HostName bastion2.example.com
    User admin
    IdentityFile ~/.ssh/id_ed25519
    ControlMaster auto
    ControlPersist 3600s
    ControlPath ~/.ssh/sockets/%r@%h-%p
    ServerAliveInterval 30
    ServerAliveCountMax 3

# Внутренние узлы с failover
Host 10.0.1.*
    User admin
    IdentityFile ~/.ssh/id_ed25519

    # Проброс через Primary, с fallback на Secondary
    ProxyJump bastion-primary,bastion-secondary
    StrictHostKeyChecking accept-new

    # Мультиплексирование
    ControlMaster auto
    ControlPersist 3600s
    ControlPath ~/.ssh/sockets/%r@%h-%p
```

**Проверка failover:**
```bash
# Тест primary bastion
ssh bastion-primary "echo ok"
# → ok

# Блокировка primary (имитация отказа)
sudo iptables -A INPUT -s $(dig +short bastion1.example.com) -j DROP

# Автоматический fallback на secondary
ssh 10.0.1.10 "hostname"
# → worker-01 (через bastion2)
```

### Сценарий 3: Connection Migration при обновлении bastion

**Задача**: Обновить bastion без разрыва SSH-соединений.

```bash
# 1. Создание нового bastion с тем же VIP
# (淡淡地 cloud provider specific)

# 2. Миграция VIP с старого на новый bastion
#淡淡地 cloud provider specific

# 3. Проверка соединений
# Все активные SSH-сессии продолжают работать через VIP
# Новые подключения идут на новый bastion

# 4. Остановка старого bastion
sudo systemctl stop sshd
```

### Сценарий 4: Автоматическое восстановление SSH-соединений

**Задача**: Скрипт для автоматического переподключения при потере связи.

```bash
#!/bin/bash
# ssh_reconnect.sh — Автоматическое переподключение SSH
# Использование: ./ssh_reconnect.sh <host> [max_attempts]

HOST=$1
MAX_ATTEMPTS=${2:-10}
ATTEMPT=1

while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
    echo "Attempt $ATTEMPT of $MAX_ATTEMPTS..."

    # Попытка подключения
    if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$HOST" "echo connected"; then
        echo "Successfully connected to $HOST"
        break
    fi

    # Экспоненциальная задержка
    DELAY=$((2 ** ATTEMPT))
    echo "Connection failed. Retrying in ${DELAY}s..."
    sleep $DELAY

    ATTEMPT=$((ATTEMPT + 1))
done

if [ $ATTEMPT -gt $MAX_ATTEMPTS ]; then
    echo "Failed to connect after $MAX_ATTEMPTS attempts"
    exit 1
fi
```

## Дополнительная информация

### Мониторинг SSH-соединений

```bash
# Проверка активных SSH-соединений
ss -tnp | grep ssh

# Проверка ControlPersist сокетов
ls -la ~/.ssh/sockets/

# Мониторинг в реальном времени
watch -n 1 'ss -tnp | grep ssh | wc -l'

# Логирование SSH-соединений
sudo journalctl -u sshd -f
```

### Частые ошибки

| Ошибка | Решение |
| :--- | :--- |
| ControlPersist не работает | Проверьте длину пути ControlPath (< 104 символов) |
| Соединение разрывается | Увеличьте ServerAliveInterval/ServerAliveCountMax |
| Failover не срабатывает | Проверьте ProxyJump конфигурацию и сетевую доступность |
| Медленное переподключение | Включите ControlMaster auto и увеличьте ControlPersist |

### См. также

- [Управление персистентными сессиями SSH](./ssh_session_management.md) — tmux, screen
- [SSH Usage and Tunnels](./ssh_usage_and_tunnels.md) — порты и туннели
- [Инструменты сетевого мониторинга](../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для анализа SSH-трафика
- [RKE: Высокая доступность](../../Kubernetes/Installation/RKE/rke_high_availability.md) — SSH в HA кластерах
- [Bastion SSH Access](../../Kubernetes/Troubleshooting/Common_Errors/NodeUnavailability/bastion_ssh_access.md) — bastion для Kubernetes
