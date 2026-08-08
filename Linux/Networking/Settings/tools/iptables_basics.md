# iptables: основы и практические сценарии

## Определения

**Netfilter** — это встроенный в ядро Linux фреймворк для перехвата и манипуляции сетевыми пакетами. Он обеспечивает фильтрацию, трансляцию адресов (NAT) и модификацию пакетов.

**iptables** — классическая утилита командной строки для управления правилами Netfilter. 
**Статус (2026):** Находится в режиме ограниченной поддержки (Legacy Maintenance Mode). В современных дистрибутивах (Debian 12+, Ubuntu 24.04+, RHEL 9+) заменена на **[nftables](./nftables/architecture_and_concepts.md)**, но продолжает использоваться в устаревших системах и через слой совместимости `iptables-nft`.

**Conntrack (Connection Tracking)** — подсистема Netfilter, отслеживающая состояние сетевых соединений. Она позволяет создавать правила на основе контекста сессии, что делает файрвол «умным» (Stateful).

См. также:
- **[Общие вопросы настройки файрволов](./firewall_common.md)** — сохранение правил, выбор DROP против REJECT.
- **[nftables: архитектура](./nftables/architecture_and_concepts.md)** — современная замена iptables.
- **[Интеграция Docker с iptables](../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — глубокий разбор цепочек Docker.

## Основные концепции

### Структура: Таблицы и цепочки

iptables организует правила в **таблицы** (по назначению) и **цепочки** (по этапу прохождения пакета). Пакет проходит через таблицы и цепочки в строго определенном порядке.

**Основные таблицы:**
- `filter`: Основная таблица для принятия решений о допуске пакета (`ACCEPT`, `DROP`, `REJECT`).
- `nat`: Используется для трансляции адресов. Включает `PREROUTING` (для DNAT), `POSTROUTING` (для SNAT/MASQUERADE) и `OUTPUT`.
- `mangle`: Для модификации заголовков пакетов (изменение TTL, TOS, маркировка пакетов для маршрутизации).
- `raw`: Используется для исключения пакетов из отслеживания состояний (`NOTRACK`).

**Стандартные цепочки:**
- `INPUT`: Пакеты, предназначенные самому хосту.
- `OUTPUT`: Пакеты, генерируемые локальными процессами.
- `FORWARD`: Пакеты, проходящие сквозь хост (роутинг).
- `PREROUTING`: Пакеты, только что пришедшие на сетевой интерфейс, до принятия решения о маршрутизации.
- `POSTROUTING`: Пакеты, покидающие сетевой интерфейс, после маршрутизации.

### Анатомия правила

Правило состоит из **критериев** (match) и **цели** (target). Пакет проверяется правилами цепочки последовательно.

**Основные цели (Targets):**
- `ACCEPT`: Пропустить пакет.
- `DROP`: Молча отбросить (клиент ждет таймаута).
- `REJECT`: Отклонить и отправить уведомление (ICMP Unreachable).
- `LOG`: Записать в системный журнал и продолжить проверку следующими правилами.
- `MASQUERADE`: Динамический SNAT (для внешних интерфейсов с динамическим IP).
- `REDIRECT`: Перенаправление пакета на локальный порт (проксирование).

## Практические сценарии

### 1. Базовая защита узла (Stateful)

```bash
# 1. Разрешить трафик для уже установленных соединений
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 2. Разрешить loopback-интерфейс
sudo iptables -A INPUT -i lo -j ACCEPT

# 3. Разрешить SSH (порт 22) и стандартный веб (80, 443)
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo iptables -A INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT

# 4. Установка политик по умолчанию (сначала разрешите SSH, чтобы не потерять доступ!)
sudo iptables -P INPUT DROP
sudo iptables -P FORWARD DROP
sudo iptables -P OUTPUT ACCEPT
```

### 2. Трансляция адресов (NAT)

```bash
# Настройка Masquerading для выхода локальной сети в интернет через eth0
sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE

# Проброс порта (DNAT): внешний порт 8080 -> внутренний IP 192.168.1.10:80
sudo iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination 192.168.1.10:80

# Перенаправление трафика с порта 80 на локальный 3128 (Transparent Proxy)
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-ports 3128
```

### 3. Защита от перебора (Module Recent)

Модуль `recent` позволяет создавать динамические списки IP-адресов прямо в памяти файрвола.

```bash
# Блокировка IP на 60 секунд, если совершено более 3 попыток подключения к SSH за минуту
sudo iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -m recent --set --name SSH_BRUTE
sudo iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -m recent --update --seconds 60 --hitcount 4 --name SSH_BRUTE -j DROP
```

### 4. Ограничение скорости (Module Limit)

Защита от DoS-атак и флуда.

```bash
# Ограничение входящих ICMP (ping) - 1 пакет в секунду
sudo iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 1/s --limit-burst 5 -j ACCEPT
```

### 5. Оптимизация TCP (Mangle)

Исправление проблем с MTU в туннелях (VPN, GRE).

```bash
# Корректировка MSS для всех пересылаемых пакетов
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1360
```

## Диагностика и отладка

```bash
# Просмотр всех правил с номерами, счетчиками и детализацией
sudo iptables -nvL --line-numbers

# Просмотр конкретной таблицы (например, nat)
sudo iptables -t nat -nvL

# Очистка всех правил в текущей таблице
sudo iptables -F

# Мониторинг отброшенных пакетов (если включен LOG)
sudo journalctl -kf | grep "IN="
```

## Дополнительная информация

### Пользовательские цепочки (User-defined chains)

Для структурирования сложных наборов правил рекомендуется создавать свои цепочки.
```bash
# Создание цепочки для фильтрации трафика конкретного приложения
sudo iptables -N APP_FILTER
sudo iptables -A INPUT -p tcp --dport 8080 -j APP_FILTER
sudo iptables -A APP_FILTER -s 10.0.0.0/24 -j ACCEPT
sudo iptables -A APP_FILTER -j DROP
```

### Взаимодействие с Docker

Docker манипулирует таблицей `nat` и цепочкой `FORWARD`. Правила Docker часто имеют более высокий приоритет, чем пользовательские правила в `INPUT`. Для надежной фильтрации трафика к контейнерам всегда используйте цепочку **`DOCKER-USER`**.

### Сохранение правил

В режиме Legacy правила сбрасываются при перезагрузке. Используйте:
- **Debian/Ubuntu**: `iptables-persistent` (`netfilter-persistent save`).
- **RHEL**: `iptables-services` (`service iptables save`).
- **Ручной метод**: `iptables-save > /etc/iptables.rules` и загрузка через скрипты `up`.
