# Port Knocking — технология скрытия портов

## Определения

**Port Knocking** (портовый «стук») — метод сетевой защиты, основанный на предоставлении доступа к закрытому порту (например, SSH) только после получения сервером серии пакетов («стуков») на определённую последовательность заранее заданных портов. Это позволяет скрыть наличие сервиса от автоматизированных сканеров и ботов, так как порт кажется закрытым до выполнения условий.

**Single Packet Authorization (SPA)** — усовершенствованная форма Port Knocking, использующая один криптографически подписанный и зашифрованный пакет для авторизации. SPA решает основные проблемы классического Port Knocking: уязвимость к перехвату (replay attacks) и медлительность. Основной инструмент реализации — **fwknop**.

**knockd** — легковесный демон, который прослушивает сетевой интерфейс (через `libpcap`) в ожидании заданных последовательностей и выполняет системные команды (обычно модификацию правил файрвола) при совпадении.

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
[openSSH]
    sequence = 7001,8001,9001
    seq_timeout = 5
    # Добавляем IP в сет на 30 секунд
    command = /usr/sbin/nft add element inet filter knock_authorized { %IP% timeout 30s }
    tcpflags = syn
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

#### 4. Запуск сервера
```bash
sudo systemctl enable --now fwknop-server
```

#### 5. Клиентский вызов
```bash
# Отправка SPA-пакета
fwknop -n server_label -a 1.2.3.4
# server_label берется из ~/.fwknoprc клиента
```

## Дополнительная информация

### Безопасность и ограничения

- **Replay Attacks**: Классический Port Knocking уязвим к перехвату трафика. Злоумышленник может повторить последовательность «стуков». SPA (fwknop) полностью защищен от этого благодаря зашифрованным временным меткам.
- **NAT и прокси**: Симметричный NAT может изменять исходящие порты клиента, что нарушит последовательность для `knockd`. SPA через UDP обычно проходит через NAT стабильнее.
- **Скрытность**: Пакеты `knockd` — это обычные SYN-пакеты. SPA-пакеты `fwknop` содержат зашифрованный payload и могут маскироваться под ICMP или UDP-шум.
- **IPv6**: Поддержка IPv6 в `knockd` ограничена или требует специальных патчей. `fwknop` поддерживает IPv6 «из коробки».

### Диагностика и логгирование

1. **Просмотр логов knockd**:
   ```bash
   tail -f /var/log/knockd.log
   # → [2026-08-08 12:00] eth0: 1.2.3.4: openSSH: Stage 1/3, 2/3, 3/3, OPEN SESAME
   ```
2. **Просмотр текущих разрешений (nftables)**:
   ```bash
   nft list set inet filter knock_authorized
   ```
3. **Проверка через tcpdump**:
   Если стук не срабатывает, проверьте, доходят ли пакеты до интерфейса:
   ```bash
   sudo tcpdump -i eth0 port 7000 or port 8000 or port 9000
   ```

### См. также

- [SSH Hardening Best Practices](./ssh_hardening_best_practices.md) — комплексные меры защиты SSH.
- [SSH Access Control](./ssh_access_control.md) — фильтрация доступа на уровне демона sshd.
- [Fail2ban](../../Tools/fail2ban.md) — автоматическая блокировка при попытках подбора пароля.
- [nftables — моделирование угроз](../../../Networking/Settings/tools/nftables/threat_modeling.md) — защита от сканирования.
