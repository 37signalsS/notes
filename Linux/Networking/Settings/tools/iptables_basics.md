# iptables: основы и практические сценарии

## Определения

**Netfilter** — это встроенный в ядро Linux фреймворк для перехвата и манипуляции сетевыми пакетами. Он обеспечивает фильтрацию, трансляцию адресов (NAT) и модификацию пакетов.

**iptables** — классическая утилита командной строки для управления правилами Netfilter. 
**Статус (2026):** Находится в режиме ограниченной поддержки (Legacy Maintenance Mode). В современных дистрибутивах (Debian 12+, Ubuntu 24.04+, RHEL 9+) заменена на **[nftables](./nftables/architecture_and_concepts.md)**, но продолжает использоваться через слой совместимости `iptables-nft`.

**Conntrack (Connection Tracking)** — подсистема Netfilter, отслеживающая состояние сетевых соединений. Позволяет создавать правила на основе контекста (например, "разрешить ответные пакеты для уже установленного соединения").

См. также:
- **[Общие вопросы настройки файрволов](./firewall_common.md)** — сохранение правил, выбор DROP vs REJECT.
- **[nftables: архитектура](./nftables/architecture_and_concepts.md)** — современная замена iptables.
- **[Интеграция Docker с iptables](../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — глубокий разбор.

## Основные концепции

### Структура: Таблицы и цепочки

iptables организует правила в **таблицы** (по назначению) и **цепочки** (по этапу прохождения пакета).

**Основные таблицы:**
- `filter` — основная таблица для принятия решений о допуске пакета (`ACCEPT`, `DROP`, `REJECT`).
- `nat` — используется для **NAT (Network Address Translation)** (преобразование IP-адресов или портов).
- `mangle` — для специализированной модификации заголовков (изменение TTL, маркировка пакетов для PBR).

**Стандартные цепочки таблицы `filter`:**
- `INPUT` — для пакетов, входящих на сам хост.
- `OUTPUT` — для пакетов, созданных локальными процессами.
- `FORWARD` — для пакетов, проходящих через хост транзитом (актуально для роутеров и Docker-хостов).

### Анатомия правила

Каждое правило состоит из **критериев** (match) и **цели** (target). Пакет проверяется правилами цепочки сверху вниз до первого совпадения.

**Основные цели (Targets):**
- `ACCEPT` — пропустить пакет.
- `DROP` — молча отбросить пакет (клиент ждет таймаута).
- `REJECT` — отклонить с отправкой **ICMP Unreachable**.
- `LOG` — записать информацию в `dmesg/journald` и продолжить проверку.

## Практические сценарии

### 1. Построение базового набора правил (Stateful)

**Задача:** Создать минимально безопасную конфигурацию для сервера.

```bash
# 1. Разрешить уже установленные соединения
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
# → success

# 2. Разрешить локальный интерфейс
sudo iptables -A INPUT -i lo -j ACCEPT
# → success

# 3. Разрешить SSH (порт 22) и веб (80, 443)
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo iptables -A INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT
# → success

# 4. Разрешить входящий ping
sudo iptables -A INPUT -p icmp --icmp-type echo-request -j ACCEPT
# → success

# 5. Установить политики по умолчанию (ВНИМАНИЕ: делайте это последним!)
sudo iptables -P INPUT DROP
sudo iptables -P FORWARD DROP
sudo iptables -P OUTPUT ACCEPT
# → success
```

### 2. Защита от самоблокировки (iptables-apply)

При настройке удаленного сервера всегда используйте `iptables-apply`. Она откатит правила через 10 секунд, если вы не подтвердите доступ.

```bash
# Тестирование правил из файла
sudo iptables-apply /etc/network/iptables.rules
# → Can you establish a new connection? [y/N]
```

### 3. Диагностика и управление

```bash
# Просмотр правил с номерами и счетчиками (v - verbose, n - numeric)
sudo iptables -nvL --line-numbers
# → Chain INPUT (policy DROP 150 packets, 12K bytes)
# → num   pkts bytes target     prot opt in     out     source               destination
# → 1      10K  800K ACCEPT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            ctstate RELATED,ESTABLISHED

# Удаление правила по номеру
sudo iptables -D INPUT 1
# → success

# Вставка правила в начало цепочки
sudo iptables -I INPUT 1 -s 192.168.1.100 -j DROP
# → success

# Очистка (Flush) всех правил
sudo iptables -F
# → success
```

## Дополнительная информация

### Сохранение правил
По умолчанию правила `iptables` сбрасываются после перезагрузки. Для сохранения используйте пакеты `iptables-persistent` (Debian/Ubuntu) или `iptables-services` (RHEL).
Подробнее: **[Сохранение правил между перезагрузками](./firewall_common.md#сохранение-правил-между-перезагрузками)**.

### Проблема Docker Bypass
Docker вставляет свои правила в таблицу `nat` и цепочку `FORWARD` напрямую, часто игнорируя ваши правила в `INPUT`. Для фильтрации трафика к контейнерам всегда используйте цепочку **`DOCKER-USER`**.

### Слой совместимости iptables-nft
В 2026 году команда `iptables` является лишь интерфейсом к движку `nftables`. Проверить режим работы можно командой:
```bash
ls -l $(which iptables)
# → /usr/sbin/iptables -> xtables-nft-multi
```

---
**Reliability Score: 10** (Подтверждено статусом legacy-инструмента в 2026 и документацией Netfilter)
