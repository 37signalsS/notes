# Port Knocking

## Definitions → Basic Concepts → Practical Scenarios → Additional Information

## Definitions

**Port Knocking** — метод защиты сетевых служб, при котором порты по умолчанию закрыты файрволом и открываются только после правильной последовательности соединений ("стуков") к предопределённым закрытым портам. Снижает вероятность обнаружения сервисов автоматическими сканерами и ботами.

**knockd** — демон, мониторящий сетевой трафик и при обнаружении заданной последовательности "стуков" динамически модифицирующий правила файрвола (`iptables`/`nftables`) для временного открытия порта для IP-адреса клиента.

## Basic Concepts

### Принцип работы

1. **Невидимость сервиса** — порт (например, SSH) закрыт файрволом по умолчанию, что предотвращает обнаружение при сканировании.
2. **Последовательность "стуков"** — клиент отправляет TCP/UDP-пакеты на заданную последовательность закрытых портов.
3. **Динамическое открытие** — `knockd` распознаёт правильную последовательность и временно открывает порт для IP клиента.
4. **Автоматическое закрытие** — через заданный интервал или по обратной последовательности порт закрывается.

### Архитектура

- **Сервер**: `knockd` + файрвол (`iptables`/`nftables`)
- **Клиент**: утилита `knock` или `nc` (netcat) для отправки "стуков"
- **Сетевой интерфейс**: `knockd` работает на конкретном интерфейсе (например, `eth0`, `enp3s0`)

## Practical Scenarios

### Настройка Port Knocking для SSH

**Сценарий**: Открытие/закрытие SSH-порта (2239) на интерфейсе `enp3s0`.

#### Серверная часть

1. **Установка knockd и iptables-persistent:**

    ```bash
    sudo apt install knockd iptables-persistent
    ```

2. **Закрытие SSH-порта по умолчанию:**

    ```bash
    sudo iptables -A INPUT -p tcp --dport 2239 -j REJECT --reject-with tcp-reset
    sudo netfilter-persistent save
    ```

3. **Конфигурация `/etc/knockd.conf`:**

    ```ini
    [options]
        logfile = /var/log/knockd.log
        interface = enp3s0

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

    - `%IP%` — IP-адрес клиента, выполнившего последовательность.
    - `iptables -I INPUT` — вставка правила в начало цепочки (приоритет).
    - `iptables -D INPUT` — удаление правила.

4. **Активация knockd (`/etc/default/knockd`):**

    ```ini
    START_KNOCKD=1
    ```

5. **Запуск демона:**

    ```bash
    sudo systemctl enable --now knockd
    sudo systemctl status knockd
    ```

#### Клиентская часть

1. **Установка утилиты knock:**

    ```bash
    sudo apt install knock
    ```

2. **Открытие SSH-порта:**

    ```bash
    knock <IP_сервера> 7000 8000 9000
    ssh user@<IP_сервера> -p 2239
    ```

    Альтернатива через `nc`:

    ```bash
    nc -zvw1 <IP_сервера> 7000
    nc -zvw1 <IP_сервера> 8000
    nc -zvw1 <IP_сервера> 9000
    ```

3. **Закрытие SSH-порта:**

    ```bash
    knock <IP_сервера> 9000 8000 7000
    ```

## Additional Information

### Дополнительные рекомендации

- **Автоматическое закрытие**: Параметр `cmd_timeout = 10` в секции `[openSSH]` автоматически удаляет правило `ACCEPT` через 10 секунд. Повышает безопасность, предотвращая бессрочный доступ.
- **Безопасность**: Port Knocking — дополнительный механизм обфускации, не заменяющий аутентификацию по SSH-ключам или полноценный файрвол.
- **Ограничения NAT**: Затруднено использование при нахождении клиента за NAT (непредсказуемый/динамический IP).
- **Совместимость**: Поддержка `iptables` и `nftables`. Для `nftables` требуются соответствующие команды в `command`.
- **Логирование**: Логи `knockd` доступны в `/var/log/knockd.log` — полезны для отладки и мониторинга попыток сканирования.
- **Альтернативы**: [Single Packet Authorization (SPA)](../spa/spa_overview.md) — более безопасный аналог Port Knocking с использованием криптографически подписанных пакетов.
