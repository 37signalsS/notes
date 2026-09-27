# Port Knocking — технология скрытия портов

## Определения

**Port Knocking** (портовый «стук») — метод сетевой защиты, основанный на предоставлении доступа к закрытому порту (например, SSH) только после получения сервером серии пакетов («стуков») на определённую последовательность заранее заданных портов. Это позволяет скрыть наличие сервиса от автоматизированных сканеров и ботов, так как порт кажется закрытым до выполнения условий.

**Single Packet Authorization (SPA)** — усовершенствованная форма Port Knocking, использующая один криптографически подписанный и зашифрованный пакет для авторизации. SPA решает основные проблемы классического Port Knocking: уязвимость к перехвату (replay attacks) и медлительность. Основной инструмент реализации — **fwknop**.

**knockd** — легковесный демон, который прослушивает сетевой интерфейс (через `libpcap`) в ожидании заданных последовательностей и выполняет системные команды (обычно модификацию правил файрвола) при совпадении.

**fwknopd** — демон-сервер для SPA, который перехватывает одиночные пакеты, расшифровывает их, проверяет HMAC и временные метки, а затем динамически открывает порт через файрвол.

**Sequence (последовательность)** — упорядоченный список портов (и/или протоколов), который клиент должен «постучать» для активации правила. Например: `7000,8000,9000` (TCP SYN по порядку).

**Seq Timeout** — максимальный интервал времени (в секундах), за который клиент должен завершить всю последовательность. При превышении стук отклоняется.

**TCP Flags filter** — возможность knockd анализировать только пакеты с определенными флагами TCP (например, `syn`), что снижает количество ложных срабатываний.

## Основные концепции

### Принцип работы

1. **Default Deny (Запрет по умолчанию)**: Целевой порт (например, 22 или нестандартный 2239) полностью закрыт правилом `REJECT` или `DROP` в файрволе.
2. **Пассивный мониторинг**: Демон (`knockd` или `fwknopd`) анализирует входящий трафик на уровне L2/L3. Важно: демон видит пакеты через `libpcap` даже если они отбрасываются (dropped) файрволом.
3. **Триггер (Стук)**: Клиент отправляет последовательность пакетов (для PK) или один зашифрованный пакет (для SPA).
4. **Динамическое правило**: При валидном «стуке» демон добавляет временное разрешающее правило в файрвол только для IP-адреса отправителя.
5. **Таймаут и сессия**: Через заданное время (например, 30 секунд) правило автоматически удаляется, но уже установленная TCP-сессия (SSH-туннель) сохраняется благодаря правилам `ESTABLISHED,RELATED`.

### Сравнение Port Knocking и SPA

| Характеристика | Port Knocking (knockd) | SPA (fwknop) |
| :--- | :--- | :--- |
| **Количество пакетов** | Несколько (обычно 3–5) | Один |
| **Безопасность** | Уязвим к Replay-атакам (перехвату «стука») | Защищен шифрованием (AES/GnuPG) и HMAC |
| **Скрытность** | «Стуки» видны в логах промежуточных систем | Пакет выглядит как случайный шум (UDP/ICMP/TCP) |
| **Сложность** | Очень прост в настройке | Требует генерации ключей и настройки клиента |
| **Работа за NAT** | Возможны проблемы при изменении портов/IP | Работает стабильно |
| **Производительность** | Минимальная нагрузка (простая проверка портов) | Незначительная нагрузка (расшифровка) |

### Архитектура и поток пакетов

```
Клиент → [Стук: 7000 → 8000 → 9000] → Файрвол (DROP) → libpcap → knockd
                                                              ↓
                                                   [Проверка последовательности]
                                                              ↓
                                                   [Добавление правила ACCEPT]
                                                              ↓
Клиент → [SSH SYN] → Файрвол (ACCEPT для %IP%) → sshd → Сессия
```

Для SPA поток упрощается:
```
Клиент → [Один зашифрованный пакет UDP/ICMP] → Файрвол (DROP) → libpcap → fwknopd
                                                              ↓
                                                   [Расшифровка + проверка HMAC]
                                                              ↓
                                                   [Добавление правила ACCEPT]
                                                              ↓
Клиент → [SSH SYN] → Файрвол (ACCEPT) → sshd → Сессия
```

## Предварительные требования

### Аппаратные и программные требования

- **ОС**: Linux 4.18+ (ядро с поддержкой `nf_tables` для nftables или `netfilter` для iptables)
- **Права**: root-доступ или `sudo` для установки пакетов и изменения правил файрвола
- **Библиотеки**: `libpcap` (устанавливается как зависимость `knockd` или `fwknop`)
- **Файрвол**: `iptables` (legacy или nf_tables) или `nftables`
- **Сеть**: Открытые порты для «стуков» на файрволе (должны достигать интерфейса, на котором слушает демон)

### Требования к сетевым интерфейсам

Демон `knockd`/`fwknopd` привязан к конкретному интерфейсу (например, `eth0`). Для серверов с несколькими интерфейсами:
- Укажите правильный внешний интерфейс в конфигурации
- Для bonding/VLAN интерфейсов убедитесь, что демон слушает на `bond0`/`vlan100`, а не на физическом enslaved-интерфейсе
- Для Docker-хостов убедитесь, что knocking-интерфейс не является `docker0` (bridge), иначе стуки из контейнеров будут обрабатываться иначе

### Подготовка окружения

```bash
# Обновление пакетов
sudo apt update && sudo apt upgrade -y

# Установка базовых утилит
sudo apt install -y tcpdump iptables-persistent

# Проверка версии ядра (nftables требует >= 4.18)
uname -r
```

### Выбор портов для «стука»

Рекомендации по выбору портов:
- Используйте порты из диапазона 1024–65535 (непривилегированные)
- Избегайте стандартных портов сервисов (например, 443, 8080, 3306)
- Для knockd используйте порты, которые не используются другими сервисами на сервере
- Для fwknop UDP-порт по умолчанию 62201, но рекомендуется изменить на кастомный

## Практические сценарии

### Сценарий 1: Настройка knockd (iptables)

**Задача**: Динамическое открытие порта SSH (2239) на интерфейсе `eth0`.

#### 1. Установка компонентов
```bash
sudo apt update && sudo apt install knockd iptables-persistent -y
```

#### 2. Блокировка порта по умолчанию
```bash
# Блокируем доступ, отправляя TCP RST (имитация закрытого порта)
sudo iptables -A INPUT -p tcp --dport 2239 -j REJECT --reject-with tcp-reset
sudo netfilter-persistent save
```

#### 3. Настройка конфигурации `/etc/knockd.conf`
```ini
[options]
    logfile = /var/log/knockd.log
    interface = eth0

[openSSH]
    sequence = 7000,8000,9000
    seq_timeout = 5
    command = /usr/sbin/iptables -I INPUT -s %IP% -p tcp --dport 2239 -j ACCEPT
    tcpflags = syn

[closeSSH]
    sequence = 9000,8000,7000
    seq_timeout = 5
    command = /usr/sbin/iptables -D INPUT -s %IP% -p tcp --dport 2239 -j ACCEPT
    tcpflags = syn
```

#### 4. Активация демона
В файле `/etc/default/knockd` установите `START_KNOCKD=1`.
```bash
sudo systemctl enable --now knockd
```

#### 5. Клиентская сторона (отправка «стука»)
Установка клиента на любой Linux/macOS:
```bash
# Debian/Ubuntu
sudo apt install knockd -y

# RHEL/CentOS/Fedora
sudo dnf install knockd -y

# macOS (Homebrew)
brew install knockd
```

Отправка стука с клиента:
```bash
# Стандартный клиент knock
knock server.example.com 7000 8000 9000

# С указанием задержки между стуками (по умолчанию 3 сек, для медленных сетей увеличьте)
knock -d 200 server.example.com 7000 8000 9000

# Альтернатива: nmap (если knock не установлен)
nmap -Pn --max-retries 0 -p 7000 server.example.com && \
nmap -Pn --max-retries 0 -p 8000 server.example.com && \
nmap -Pn --max-retries 0 -p 9000 server.example.com

# Альтернатива: netcat (для проверки отдельных портов)
nc -z -w 2 server.example.com 7000 && \
nc -z -w 2 server.example.com 8000 && \
nc -z -w 2 server.example.com 9000
```

#### 6. Валидация работы
```bash
# На сервере: просмотр логов knockd в реальном времени
sudo journalctl -u knockd -f

# На клиенте: подключение по SSH после стука
ssh -p 2239 user@server.example.com

# Проверка, что порт виден как закрытый до стука (с другого хоста)
nmap -Pn -p 2239 server.example.com
# → state: filtered (или closed, если используется REJECT)

# Проверка активных правил iptables
sudo iptables -L INPUT -v -n | grep 2239
```

#### 7. Автоматическое закрытие (closeSSH)
При необходимости можно настроить автоматическое закрытие порта после отправки обратной последовательности. В текущей конфигурации `/etc/knockd.conf` уже есть секция `[closeSSH]`:
```ini
[closeSSH]
    sequence = 9000,8000,7000
    seq_timeout = 5
    command = /usr/sbin/iptables -D INPUT -s %IP% -p tcp --dport 2239 -j ACCEPT
    tcpflags = syn
```
Для использования:
```bash
# На клиенте: отправка close-последовательности
knock server.example.com 9000 8000 7000
```

#### 8. Откат и очистка
```bash
# Остановка демона
sudo systemctl disable --now knockd

# Удаление правил iptables, добавленных knockd
sudo iptables -D INPUT -p tcp --dport 2239 -j REJECT --reject-with tcp-reset

# Восстановление политики по умолчанию (если нужно снова открыть порт)
sudo iptables -A INPUT -p tcp --dport 2239 -j ACCEPT

# Сохранение правил
sudo netfilter-persistent save

# Удаление пакета
sudo apt purge knockd -y
```

---

### Сценарий 2: Настройка knockd (nftables)

Использование `nftables` позволяет более элегантно управлять временными доступами через именованные наборы (sets).

**1. Настройка nftables (базовые правила):**
```bash
# Создаем таблицу и цепочку, если их нет
nft add table inet filter
nft add chain inet filter input { type filter hook input priority 0; policy accept; }

# Создаем сет с автоматическим удалением по таймауту
nft add set inet filter knock_authorized { type ipv4_addr; flags timeout; }

# Добавляем правило: разрешить SSH, если IP в сете
nft add rule inet filter input ip saddr @knock_authorized tcp dport 2239 accept

# Блокируем SSH для всех остальных
nft add rule inet filter input tcp dport 2239 reject
```

**2. Конфигурация `/etc/knockd.conf`:**
```ini
[options]
    logfile = /var/log/knockd.log
    interface = eth0

[openSSH]
    sequence = 7001,8001,9001
    seq_timeout = 5
    # Добавляем IP в сет на 30 секунд
    command = /usr/sbin/nft add element inet filter knock_authorized { %IP% timeout 30s }
    tcpflags = syn

[closeSSH]
    sequence = 9001,8001,7001
    seq_timeout = 5
    # Удаляем IP из сета
    command = /usr/sbin/nft delete element inet filter knock_authorized { %IP% }
    tcpflags = syn
```

**3. Валидация работы:**
```bash
# Просмотр логов knockd
sudo journalctl -u knockd -f

# Проверка содержимого сета knock_authorized
sudo nft list set inet filter knock_authorized

# Клиентский стук (такой же, как в сценарии 1)
knock server.example.com 7001 8001 9001

# Проверка через tcpdump
sudo tcpdump -i eth0 port 7001 or port 8001 or port 9001

# Подключение по SSH
ssh -p 2239 user@server.example.com
```

**4. Откат:**
```bash
# Остановка knockd
sudo systemctl disable --now knockd

# Удаление набора и правил nftables
sudo nft delete rule inet filter input ip saddr @knock_authorized tcp dport 2239 accept
sudo nft delete rule inet filter input tcp dport 2239 reject
sudo nft delete set inet filter knock_authorized

# Очистка конфигурации
sudo rm /etc/knockd.conf
```

---

### Сценарий 3: Настройка Single Packet Authorization (fwknop)

**fwknop** (FireWall Knock Operator) — стандарт для SPA.

#### 1. Установка
```bash
sudo apt install fwknop-server fwknop-client -y
```

#### 2. Генерация ключей (на стороне сервера для клиента)
```bash
fwknop -A tcp/2239 -D eth0 --key-gen --use-hmac --save-rc-stanza
# → Сгенерирует файл .fwknoprc с ключами KEY_BASE64 и HMAC_KEY_BASE64
```

#### 3. Настройка сервера (`/etc/fwknop/access.conf`)
```text
SOURCE          ANY
OPEN_PORTS      tcp/2239
KEY_BASE64      <ВАШ_КЛЮЧ>
HMAC_KEY_BASE64 <ВАШ_HMAC_КЛЮЧ>
FW_ACCESS_TIMEOUT 30
```

**Важные директивы `access.conf`:**
- `SOURCE` — ограничение по IP. Для фиксированного клиента укажите `192.168.1.100/32`, для любых — `ANY`
- `OPEN_PORTS` — порты, которые будут открыты при успешном стуке
- `FW_ACCESS_TIMEOUT` — время (сек), на которое открывается порт
- `REQUIRE_SOURCE_ADDRESS` — по умолчанию `Y`. Если `N`, то любой SPA-пакет от любого отправителя откроет порт (опасно)
- `DATA_COLLECT_MODE` — `NONE` по умолчанию. Для отладки можно включить `PCAP_SAVE_FILE` для сохранения захваченных пакетов

#### 3.1. Расширенная конфигурация `/etc/fwknop/fwknop.conf`
```ini
[options]
    # Интерфейс для прослушивания (обычно внешний)
    INTERFACE eth0

    # IP-адрес для пакетов, которые отправляет fwknopd (при необходимости)
    # LOCAL_ADDR 192.168.1.1

    # Логирование
    ENABLE_LOGGING Y
    LOG_FILE /var/log/fwknop.log

    # Уровень детализации логов (0-7)
    VERBOSITY 5

    # IPv6 поддержка
    IPV6_SUPPORT Y

    # Максимальный размер пакета SPA (MTU)
    MAX_SPA_PACKET_SIZE 1500

    # Включение PCAP для отладки
    # PCAP_SAVE_FILE /var/log/fwknop.pcap
```

#### 4. Запуск сервера
```bash
sudo systemctl enable --now fwknop-server
```

Проверка статуса:
```bash
# Статус systemd
sudo systemctl status fwknop-server

# Проверка слушающего порта (по умолчанию UDP 62201)
sudo ss -u -lpn | grep fwknop
# → udp UNCONN 0 0 0.0.0.0:62201 0.0.0.0:* users:(("fwknopd",pid=1234,fd=5))

# Просмотр логов
sudo journalctl -u fwknop-server -f
```

#### 5. Клиентская настройка и вызов

##### Настройка клиента (`~/.fwknoprc`)
На клиентской машине создайте файл `~/.fwknoprc`:
```ini
[server_label]
SPA_SERVER      server.example.com
SPA_SERVER_PORT 62201
SPA_PROTO       udp
ACCESS          tcp/2239
KEY_BASE64      <ТОТ_ЖЕ_КЛЮЧ_ЧТО_И_НА_СЕРВЕРЕ>
HMAC_KEY_BASE64 <ТОТ_ЖЕ_HMAC_КЛЮЧ>
```

Отправка SPA-пакета:
```bash
# Стандартный вызов (использует данные из ~/.fwknoprc)
fwknop -n server_label -a 1.2.3.4

# С указанием интерфейса (если несколько)
fwknop -n server_label -a 1.2.3.4 -i eth0

# Прямой вызов без .fwknoprc (удобно для скриптов)
fwknop -S server.example.com -P 62201 -A tcp/2239 \
       --key <base64_key> --hmac-key <base64_hmac_key> \
       -a 1.2.3.4

# Проверка доступа после отправки SPA
ssh -p 2239 user@server.example.com
```

#### 6. Валидация безопасности SPA
```bash
# На сервере: проверка, что порт 2239 закрыт без SPA
nmap -Pn -p 2239 server.example.com
# → state: filtered

# После SPA: порт должен быть открыт только для вашего IP
nmap -Pn -p 2239 server.example.com -S 1.2.3.4

# Проверка файрвола: убедитесь, что правило добавляется только для источника
sudo iptables -L INPUT -v -n | grep 2239
# → ACCEPT tcp -- 1.2.3.4 0.0.0.0/0 tcp dpt:2239

# Проверка логов fwknop
sudo grep "Access granted" /var/log/fwknop.log
```

#### 7. Откат и очистка
```bash
# Остановка сервиса
sudo systemctl disable --now fwknop-server

# Удаление правил iptables, добавленных fwknopd
sudo iptables-save | grep -v "fwknop" | sudo iptables-restore
sudo netfilter-persistent save

# Удаление конфигурации (если нужно полностью убрать SPA)
sudo apt purge fwknop-server fwknop-client -y
```

## Дополнительная информация

### Безопасность и ограничения

- **Replay Attacks**: Классический Port Knocking уязвим к перехвату трафика. Злоумышленник может повторить последовательность «стуков». SPA (fwknop) полностью защищен от этого благодаря зашифрованным временным меткам.
- **NAT и прокси**: Симметричный NAT может изменять исходящие порты клиента, что нарушит последовательность для `knockd`. SPA через UDP обычно проходит через NAT стабильнее.
- **Скрытность**: Пакеты `knockd` — это обычные SYN-пакеты. SPA-пакеты `fwknop` содержат зашифрованный payload и могут маскироваться под ICMP или UDP-шум.
- **IPv6**: Поддержка IPv6 в `knockd` ограничена или требует специальных патчей. `fwknop` поддерживает IPv6 «из коробки».
- **Rate Limiting**: Избыточно частые стуки могут быть отброшены файрволом или маршрутизатором перед достижением демона. Убедитесь, что промежуточные устройства не ограничивают частоту на нужных портах.
- **Зависимость от libpcap**: Демон требует доступа к raw-сокетам. В контейнерах или виртуализированных окружениях может потребоваться дополнительная настройка прав (`CAP_NET_RAW`, `CAP_NET_ADMIN`).
- **Единая точка отказа**: Если демон `knockd`/`fwknopd` упал, порт остается закрытым. Настройте мониторинг процесса (systemd watchdog, external health check).

### Практические сценарии: автоматизация и интеграция

### Сценарий 4: Автоматизация knocking через bash-функции и SSH wrapper

Для регулярного использования удобно инкапсулировать логику knocking в функции или обертку над `ssh`.

#### 1. Bash-функции в `~/.bashrc` / `~/.zshrc`

```bash
# Функция knock для сервера
knock_ssh() {
    local SERVER="$1"
    local USER="$2"
    local SEQUENCE="7000 8000 9000"
    local SSH_PORT=2239

    echo "[*] Отправка стука на $SERVER..."
    knock -d 100 "$SERVER" $SEQUENCE

    echo "[*] Ожидание открытия порта..."
    sleep 1

    echo "[*] Подключение по SSH..."
    ssh -p "$SSH_PORT" "$USER@$SERVER"
}

# Функция для SPA (fwknop)
fwknop_ssh() {
    local SERVER="$1"
    local USER="$2"
    local LABEL="server_label"

    echo "[*] Отправка SPA-пакета..."
    fwknop -n "$LABEL" -a "$(curl -s ifconfig.me)"

    echo "[*] Подключение по SSH..."
    ssh -p 2239 "$USER@$SERVER"
}
```

Использование:
```bash
# Port Knocking
knock_ssh server.example.com admin

# SPA
fwknop_ssh server.example.com admin
```

#### 2. SSH wrapper-скрипт

```bash
#!/usr/bin/env bash
# /usr/local/bin/ssh-knock-wrapper
set -euo pipefail

SERVER="${1:-}"
USER="${2:-$(whoami)}"
PORT="${3:-2239}"
SEQUENCE="${KNOCK_SEQUENCE:-7000 8000 9000}"

if [[ -z "$SERVER" ]]; then
    echo "Usage: $0 <server> [user] [port]" >&2
    exit 1
fi

echo "[*] Knocking $SERVER..."
if ! knock -d 100 "$SERVER" $SEQUENCE; then
    echo "[!] Knock failed" >&2
    exit 1
fi

sleep 1
exec ssh -p "$PORT" "$USER@$SERVER"
```

```bash
sudo chmod +x /usr/local/bin/ssh-knock-wrapper
# Использование
ssh-knock-wrapper server.example.com admin
```

#### 3. Systemd-сервис для автоматического knocking (keepalive)

Для поддержания сессии активной можно настроить systemd-сервис, который периодически отправляет стук:

```ini
# /etc/systemd/system/knock-keepalive.service
[Unit]
Description=SSH Port Knocking Keepalive
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/knock -d 100 server.example.com 7000 8000 9000
User=root

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/knock-keepalive.timer
[Unit]
Description=Run knock keepalive every 25 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=25min
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now knock-keepalive.timer
```

#### 4. Интеграция с Ansible ( Fleet management)

При массовом управлении серверами Port Knocking можно проверять через `wait_for`:

```yaml
- name: Ensure SSH port is accessible after knock
  block:
    - name: Send knock sequence
      command: knock -d 100 {{ inventory_hostname }} 7000 8000 9000
      delegate_to: localhost
      become: false

    - name: Wait for SSH port to open
      wait_for:
        host: "{{ inventory_hostname }}"
        port: 2239
        state: started
        timeout: 10
      delegate_to: localhost
```

### Диагностика и логгирование

#### 1. Просмотр логов knockd
```bash
# Логи systemd (рекомендуется)
sudo journalctl -u knockd -f

# Файловый лог (если настроен)
tail -f /var/log/knockd.log

# Пример успешного стука:
# [2026-09-09 10:15:32] eth0: 1.2.3.4: openSSH: Stage 1/3, 2/3, 3/3, OPEN SESAME

# Пример неудачи (неверная последовательность):
# [2026-09-09 10:16:01] eth0: 1.2.3.4: openSSH: incorrect sequence 7000,9000,8000
```

#### 2. Просмотр логов fwknopd
```bash
# Логи systemd
sudo journalctl -u fwknop-server -f

# Файловый лог
tail -f /var/log/fwknop.log

# Пример успешного SPA:
# [2026-09-09 10:20:15] fwknopd: Access granted: 1.2.3.4 -> tcp/2239

# Пример неудачи (неверный HMAC):
# [2026-09-09 10:20:16] fwknopd: Invalid HMAC from 1.2.3.4
```

#### 3. Проверка текущих правил файрвола

**iptables:**
```bash
# Правила для порта 2239
sudo iptables -L INPUT -v -n | grep 2239

# Все динамические правила (предполагаем, что knockd добавляет с комментарием)
sudo iptables -L INPUT -v -n --line-numbers | grep -A1 "2239"
```

**nftables:**
```bash
# Просмотр набора knock_authorized
nft list set inet filter knock_authorized

# Пример вывода:
# table inet filter {
#     set knock_authorized {
#         type ipv4_addr
#         elements = { 1.2.3.4 timeout 25s }
#     }
# }

# Правила, использующие набор
nft list chain inet filter input
```

#### 4. Проверка через tcpdump
```bash
# Если стук не срабатывает, проверьте, доходят ли пакеты до интерфейса:
sudo tcpdump -i eth0 port 7000 or port 8000 or port 9000

# Для fwknop (UDP 62201 по умолчанию):
sudo tcpdump -i eth0 udp port 62201

# Детальный анализ с сохранением в файл:
sudo tcpdump -i eth0 -w /tmp/knock_debug.pcap port 7000 or port 8000 or port 9000
tshark -r /tmp/knock_debug.pcap -Y "tcp.flags.syn == 1" -T fields -e ip.src -e tcp.dstport
```

#### 5. Диагностика проблем с libpcap
```bash
# Проверка, что интерфейс доступен для захвата
sudo tcpdump -D
# → 1.eth0
# → 2.any (Pseudo-device that captures on all interfaces)

# Проверка прав на raw-сокеты
sudo getpcaps $(pgrep knockd)
# → Capabilities: = cap_net_admin,cap_net_raw+ep

# Если демон не может открыть интерфейс, проверьте:
# - Нет ли других процессов, захватывающих тот же интерфейс
# - Не отключен ли promiscuous mode (для knockd это не требуется, но полезно для отладки)
sudo ip link set eth0 promisc on
```

#### 6. Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Stage 1/3, ...` не появляется в логах | Пакеты не доходят до демона | Проверьте файрвол, маршрутизацию, tcpdump |
| `incorrect sequence` | Неверный порядок портов | Проверьте конфиг knockd и команду knock |
| `fwknopd: Invalid HMAC` | Несовпадение ключей | Перегенерируйте ключи, проверьте `access.conf` и `.fwknoprc` |
| Порт остается закрытым после стука | Правило не добавляется | Проверьте права knockd, путь к iptables/nft, SELinux/AppArmor |
| `Sequence timeout` | Стук занял слишком много времени | Увеличьте `seq_timeout` или оптимизируйте сеть |
| NAT: стук не проходит | Симметричный NAT меняет порты | Используйте фиксированный диапазон портов на файрволе NAT |

### Best Practices

1. **Многофакторность**: Port Knocking — только один из уровней защиты. Обязательно сочетайте с:
   - Ключевой аутентификацией (ED25519/FIDO2) — [SSH Authentication](./ssh_authentication.md)
   - Fail2ban для блокировки brute-force — [Fail2ban](../../Tools/fail2ban.md)
   - Жестким `sshd_config` — [SSH Hardening Best Practices](./ssh_hardening_best_practices.md)

2. **Используйте SPA для критических узлов**: Классический Port Knocking подходит для защиты от случайных сканеров, но для критической инфраструктуры выбирайте `fwknop`.

3. **Случайные последовательности**: Не используйте predictable sequences (`7000,8000,9000`) в production. Генерируйте уникальные последовательности для каждого сервера/группы.

4. **Мониторинг демона**: Добавьте `knockd`/`fwknopd` в мониторинг (systemd watchdog, check by ICMP/UDP on knock port, health check script).

5. **Аудит логов**: Регулярно анализируйте логи на предмет:
   - Неудачных попыток стука (возможная разведка)
   - Успешных доступов из неожиданных подсетей
   - Частых повторений (возможный replay-атака)

6. **Сегментация сети**: Разные последовательности/ключи для доступа к dev/stage/prod окружениям.

7. **Fail-safe**: Убедитесь, что у администратора есть запасной механизм доступа (например, out-of-band консоль, rescue mode) на случай отказа knockd.

### Edge Cases и ограничения

1. **Высоконагруженные серверы**: На серверах с >100K pps `knockd` через libpcap может потреблять значительные ресурсы CPU. Рассмотрите использование `nf_tables` с динамическими наборами или hardware offload.

2. **Латентность стука**: При высоком RTT (международные каналы, спутниковая связь) увеличьте `seq_timeout` до 10–15 секунд и задержку между стуками (`knock -d`).

3. **Пакеты разных размеров**: Некоторые файрволы/NAT могут фрагментировать или отклонять пакеты, превышающие MTU. Для fwknop настройте `MAX_SPA_PACKET_SIZE` под вашу сеть.

4. **Последовательные SYN-сканеры**: Сканеры вроде `masscan` могут отправить SYN на все 65535 портов за секунды. knockd обработает это как отдельные стуки, но не активирует правило без правильного порядка. Это нормально, но может создать шум в логах.

5. **Два администратора одновременно**: Если два администратора стучат одновременно, оба получат доступ. Порядок стука имеет значение только для последовательности, но не для параллелизма.

6. **Стук после reboot**: Правила файрвола сбрасываются при перезагрузке. Убедитесь, что `netfilter-persistent` или `nftables` запускается до `knockd`/`fwknopd`.

7. **SSH Keepalive**: Если SSH-сессия долго неактивна, но TCP-соединение остается, файрвол не закроет доступ благодаря `ESTABLISHED,RELATED`. Однако при разрыве TCP-сессии (timeout на маршрутизаторе) потребуется повторный стук.

### См. также

- [SSH Hardening Best Practices](./ssh_hardening_best_practices.md) — комплексные меры защиты SSH.
- [SSH Access Control](./ssh_access_control.md) — фильтрация доступа на уровне демона sshd.
- [Fail2ban](../../Tools/fail2ban.md) — автоматическая блокировка при попытках подбора пароля.
- [nftables — моделирование угроз](../../../Networking/Settings/tools/nftables/threat_modeling.md) — защита от сканирования.
- [Networking/Concepts/network_ports.md](../../../../Networking/Concepts/network_ports.md) — теория портов и их состояний.
