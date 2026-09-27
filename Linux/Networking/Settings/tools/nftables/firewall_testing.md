# nftables — тестирование и верификация правил

## Определения

**Тестирование межсетевого экрана** — комплекс мероприятий по проверке корректности работы правил фильтрации, направленный на подтверждение доступности разрешенных ресурсов и блокировку запрещенных векторов трафика.

**Позитивное тестирование** — проверка того, что разрешенный трафик (например, HTTP/HTTPS) беспрепятственно проходит через фильтры.

**Негативное тестирование** — проверка того, что несанкционированный трафик (на закрытые порты или от запрещенных источников) корректно блокируется.

**Синтаксическая валидация** — проверка корректности структуры и параметров правил без их фактического применения в ядре.

**Атомарное применение** — nftables заменяет весь ruleset одним действием. Если синтаксическая ошибка обнаруживается halfway, изменения не применяются, и предыдущая конфигурация остается активной. Это свойство критично при тестировании на production-хостах.

**nftrace** — механизм трассировки ядра nf_tables, который помечает каждый пакет меткой и записывает путь через таблицы, цепочки и правила. Позволяет точно определить, на каком правиле завершилась обработка пакета.

**Conntrack exhaustion** — состояние, при котором таблица отслеживания соединений (`nf_conntrack`) заполнена. При этом новые соединения могут сбрасываться до того, как достигнут файрвол.

## Основные концепции

### Методология верификации

Эффективная проверка конфигурации nftables строится на четырех уровнях:

1.  **Уровень конфигурации (Static):** проверка синтаксиса до загрузки правил.
2.  **Уровень локальной системы (Host-side):** проверка состояния сокетов и привязки интерфейсов.
3.  **Уровень сетевого взаимодействия (Network-side):** имитация действий пользователя и злоумышленника с внешних узлов.
4.  **Уровень ядра (Kernel-trace):** отслеживание пути пакета внутри цепочек nftables.

Каждый уровень должен проходить независимо. Например, успешный `nft --check` не гарантирует, что правила не заблокируют SSH после reload.

### Типы ответов при тестировании

При сканировании портов (например, с помощью `nmap`) крайне важно интерпретировать состояние порта:

| Состояние | Действие файрвола | Технический смысл |
| :--- | :--- | :--- |
| **Open** | `accept` | Пакет принят, приложение ответило. |
| **Filtered** | `drop` | Пакет отброшен «молча». Сканер ожидает таймаута. |
| **Closed** | `reject` | Файрвол ответил ICMP-сообщением об ошибке (Port Unreachable). |

### Счетчики правил

Каждое правило nftables может иметь встроенный счетчик (`counter`). Это первичный источник истины для позитивного и негативного тестирования:

```bash
# Просмотр всех правил со счетчиками
sudo nft list ruleset

# Фильтрация только input-цепочки
sudo nft list chain inet filter input
# → pkts bytes target prot opt source destination
# → 1245 78920 accept all  *       *      ct state established,related
# → 0     0 drop all  *       *      tcp flags & (fin|syn|rst) != syn
```

При тестировании сначала сравнивайте счетчики до и после отправки тестового трафика. Рост счетчиков подтверждает, что правило сработало.

### Жизненный цикл соединения и conntrack

nftables stateful-режим опирается на `nf_conntrack`. При тестировании учитывайте:

- **`ct state established,related accept`** разрешает ответный трафик без явных правил на ответный порт.
- При изменении правил уже установленные соединения остаются в таблице conntrack и могут продолжать работать, даже если новые правила их блокируют.
- Сброс conntrack (`conntrack -D`) принудительно завершает все текущие сессии, заставляя пакеты проходить через новые правила заново.

### Логирование как инструмент верификации

Добавление `log prefix "NFT_DROP: " drop` в цепочку перед финальным drop создает журнальные записи в `journalctl` или `/var/log/kern.log`. Это необходимо для:

- Подтверждения, что блокировка срабатывает именно по ожидаемому правилу.
- Детекции неожиданного трафика (например, сканирования с нового IP).
- Построения временной шкалы инцидента.

Ограничьте `log` через `limit rate 10/minute`, чтобы избежать заполнения диска при DDoS.

### Валидация после редактирования

После любого изменения файла `/etc/nftables.conf`:

```bash
# 1. Синтаксическая проверка
sudo nft --check --file /etc/nftables.conf
# → Пустой вывод = успех. Любая строка = ошибка синтаксиса.

# 2. Применение и проверка
sudo nft --file /etc/nftables.conf

# 3. Проверка работоспособности SSH (из другого терминала/сессии)
ssh -o ConnectTimeout=5 user@host 'echo SSH_OK'

# 4. Проверка счетчиков
sudo nft list ruleset | grep -E 'counter|drop'
```

## Практические сценарии

### 1. Проверка синтаксиса (Dry-run)

Прежде чем применить изменения, которые могут заблокировать доступ (особенно по SSH), необходимо выполнить проверку файла конфигурации.

```bash
# Проверка файла на наличие ошибок синтаксиса без загрузки в ядро
sudo nft --check --file /etc/nftables.conf
# Результат: (пустой вывод означает отсутствие ошибок)
```

**Расширенный dry-run с отладочным выводом:**

```bash
# Проверка с включенным дебагом nftables для выявления неочевидных проблем
sudo nft --debug=all --check --file /etc/nftables.conf
# → Показывает разбор выражений, работу sets/maps и другие детали
```

### 2. Трассировка пакетов (nft monitor trace)

Это самый мощный способ понять, на каком именно правиле срабатывает `drop` или `accept`.

**Шаг 1: Добавление метаданных трассировки в правило**
```bash
# Включить трассировку для трафика с конкретного IP
nft add rule inet filter input ip saddr 192.168.1.50 meta nftrace set 1
```

**Шаг 2: Мониторинг событий**
```bash
# Просмотр пути пакета через цепочки и таблицы в реальном времени
sudo nft monitor trace
```

**Расширенный анализ трассировки:**

```bash
# Захват трассировки в JSON для последующего анализа
sudo nft monitor trace --json > /tmp/nftrace.json

# Фильтрация трассировки по целевому IP
sudo nft monitor trace | grep '<Target_IP>'
```

**Важно:** `nftrace` работает на уровне ядра и требует, чтобы пакеты проходили через nf_tables. Если трафик маршрутизируется через `netdev`-семейство (flowtables), `nft monitor trace` может не показать событий. В этом случае используйте `tc` или `ebpf`-инструменты.

### 3. Тестирование с помощью hping3 и nping (Имитация атак)

`hping3` позволяет точно контролировать флаги пакетов, что полезно для проверки защиты от SYN-флуда или некорректных пакетов. `nping` (из набора Nmap) предоставляет похожий функционал с поддержкой IPv6.

```bash
# Имитация SYN-флуда (проверка лимитов или synproxy)
sudo hping3 -S -p 80 --flood <Target_IP>

# Проверка прохождения пакетов с конкретными флагами (например, FIN+ACK)
sudo hping3 -F -A -p 80 <Target_IP>

# Имитация фрагментированных пакетов
sudo hping3 -f -p 80 <Target_IP>

# Аналогичные тесты через nping (поддержка IPv6)
sudo nping --tcp --flags SYN --rate 1000 --source-port 80 <Target_IP>
sudo nping --tcp --flags FIN,ACK <Target_IP>
```

### 4. Внешнее сканирование (Nmap)

**Для IPv4:**
```bash
# Быстрое сканирование основных портов
nmap -F <Target_IP>

# Определение версии службы и ОС
sudo nmap -sV -O <Target_IP>

# Проверка причины состояния порта (фильтр/открыт/закрыт)
nmap --reason <Target_IP>

# Сканирование с явным указанием TCP connect() (без SYN stealth)
nmap -sT -p 22,80,443 <Target_IP>

# UDP-сканирование (медленное, требует прав root)
sudo nmap -sU --top-ports 20 <Target_IP>
```

**Для IPv6:**
```bash
# Сканирование IPv6 адреса
nmap -6 <Target_IPv6>

# Сканирование конкретных портов IPv6
nmap -6 -p 22,80,443 <Target_IPv6>
```

### 5. Эмуляция сервисов

Если на сервере нет запущенного приложения, используйте временные серверы для проверки правил.

```bash
# Через Netcat (TCP)
nc -l -p 8888

# Через Python (быстрый HTTP сервер)
python3 -m http.server 8080

# Через socat (TCP/UDP, больше контроля)
socat TCP-LISTEN:8888,reuseaddr,fork -
socat UDP-LISTEN:8888,reuseaddr,fork -

# Через iperf3 (тестирование пропускной способности через файрвол)
iperf3 -s -p 5201  # сервер
iperf3 -c <server_ip> -t 10 -P 4  # клиент
```

### 6. Управление состоянием (Conntrack)

Помните, что `nftables` отслеживает состояния. Если ваше соединение уже установлено (`established`), изменение правил может не повлиять на него.

```bash
# Просмотр текущих соединений
sudo conntrack -L

# Мониторинг событий conntrack в реальном времени
sudo conntrack -E

# Принудительный сброс состояний для конкретного IP (чтобы новые правила применились сразу)
sudo conntrack -D -s 192.168.1.50

# Проверка использования таблицы conntrack
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → nf_conntrack_count = 45000
# → nf_conntrack_max   = 262144
```

### 7. Проверка политик по умолчанию и счетчиков

Перед любым изменением запишите текущие значения счетчиков. После тестирования сравните, чтобы убедиться, что только ожидаемые правила сработали.

```bash
# Снимок счетчиков до изменений
sudo nft list ruleset > /tmp/nft-before.txt
grep -E 'counter|policy' /tmp/nft-before.txt

# Применение новой конфигурации
sudo nft --file /etc/nftables.conf

# Снимок после
sudo nft list ruleset > /tmp/nft-after.txt

# Diff: какие правила сработали
diff --side-by-side --suppress-common-lines /tmp/nft-before.txt /tmp/nft-after.txt
```

### 8. Тестирование rate limiting

```bash
# Проверка лимита SSH (ожидайте reject/drop после превышения)
for i in $(seq 1 20); do
  nc -zv <Target_IP> 22
done
# → Первые N соединений пройдут, затем начнутся таймауты или rejects.

# Проверка ICMP rate limit
ping -c 20 <Target_IP>
# → Не более X echo-reply в секунду, остальные дропаются (проверка через счетчик)
```

### 9. Тестирование IPv6

IPv6 требует отдельного подхода из-за отсутствия NAT и зависимости от ICMPv6 (NDP, PMTUD).

```bash
# Сканирование основных портов IPv6
nmap -6 -p 22,80,443,ICMP <IPv6_Address>

# Проверка прохождения NDP
sudo ndisc6 -1 <IPv6_Address> <Interface>
# → Должен получить Advertisement

# Проверка ICMPv6
sudo ndping <IPv6_Address>
ping6 -c 5 <IPv6_Address>
```

### 10. Автоматизированное smoke-тестирование

Для CI/CD или регулярных проверок используйте простой bash-скрипт:

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET="<Target_IP>"
ALLOWED_PORTS=(22 80 443)
BLOCKED_PORTS=(23 2323 3389 4444)
SSH_USER="user"

echo "[*] Positive tests..."
for port in "${ALLOWED_PORTS[@]}"; do
  if nc -z -w3 "$TARGET" "$port"; then
    echo "  [OK] Port $port is open"
  else
    echo "  [FAIL] Port $port is closed"
    exit 1
  fi
done

echo "[*] Negative tests..."
for port in "${BLOCKED_PORTS[@]}"; do
  if nc -z -w3 "$TARGET" "$port"; then
    echo "  [FAIL] Port $port should be blocked"
    exit 1
  else
    echo "  [OK] Port $port is blocked"
  fi
done

echo "[*] SSH connectivity..."
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$SSH_USER@$TARGET" 'echo SSH_OK' | grep -q SSH_OK; then
  echo "  [OK] SSH is reachable"
else
  echo "  [FAIL] SSH is not reachable"
  exit 1
fi

echo "[*] All tests passed."
```

### 11. Безопасный atomic reload с откатом

```bash
#!/usr/bin/env bash
set -euo pipefail

CONF="/etc/nftables.conf"
BACKUP="/tmp/nft-backup-$(date +%Y%m%d-%H%M%S).conf"

# 1. Резервная копия текущих правил
sudo nft list ruleset > "$BACKUP"

# 2. Синтаксическая проверка
if ! sudo nft --check --file "$CONF"; then
  echo "Syntax check failed. Aborting."
  exit 1
fi

# 3. Применение
sudo nft --file "$CONF"

# 4. Ожидание подтверждения (отдельная сессия/админ)
echo "Rules reloaded. Verify SSH in another session."
echo "To rollback: sudo nft flush ruleset && sudo nft -f $BACKUP"
```

## Предварительные требования

| Компонент | Версия/требование | Проверка |
| :--- | :--- | :--- |
| nftables | ≥ 1.0.0 (ядро Linux ≥ 4.19) | `nft --version` |
| nft | Пакет `nftables` установлен | `which nft` |
| conntrack | Пакет `conntrack-tools` (опционально) | `conntrack --version` |
| nmap | ≥ 7.0 | `nmap --version` |
| hping3 / nping | hping3 или nmap | `which hping3 nping` |
| nc / ncat | netcat или nmap ncat | `which nc ncat` |
| Права | root или sudo | `sudo -l` |

Перед тестированием на production-хосте убедитесь, что у вас есть консольный доступ (IPMI/iDRAC/iLO/виртуальная консоль), чтобы избежать блокировки SSH.

## Валидация результатов

После каждой команды ожидайте явный результат:

```bash
# Пример: dry-run
sudo nft --check --file /etc/nftables.conf
# → (пустой вывод) = ошибок нет

# Пример: сканирование открытого порта
nmap -p 80 <Target_IP>
# → 80/tcp open http

# Пример: заблокированный порт
nmap -p 23 <Target_IP>
# → 23/tcp filtered telnet
# или
# → 23/tcp closed telnet (если reject)
```

## Диагностика и устранение неполадок

**Правила не применяются после reload:**
```bash
# Очистка и перезагрузка
sudo nft flush ruleset
sudo systemctl restart nftables
```

**Порт недоступен несмотря на правило:**
```bash
# 1. Проверка статуса nftables
sudo systemctl status nftables

# 2. Проверка конкретного правила и счетчиков
sudo nft list chain inet filter input

# 3. Проверка слушающего сокета
sudo ss -tlnp | grep <port>

# 4. Проверка внешнего доступа
sudo nmap -p <port> localhost

# 5. Проверка conntrack (возможно, соединение уже established)
sudo conntrack -L | grep <port>
```

**Случайная блокировка собственного IP:**
```bash
# Проверка текущих правил
sudo nft list ruleset

# Экстренный сброс (если есть консольный доступ)
sudo nft flush ruleset
```

**nft monitor trace не показывает события:**
```bash
# 1. Проверьте, установлен ли nftrace в 1
sudo nft list ruleset | grep nftrace

# 2. Убедитесь, что пакеты проходят через классический путь
# Flowtables (netdev family) не генерируют события для monitor trace.
# Для flowtables используйте tc или ebpf.

# 3. Проверьте, не отброшен ли пакет до nf_tables (например, raw/PREROUTING)
```

**Conntrack переполнен:**
```bash
# Проверка текущей нагрузки
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max

# Временное увеличение лимита
sudo sysctl -w net.netfilter.nf_conntrack_max=524288

# Постоянное изменение в /etc/sysctl.d/99-conntrack.conf
# net.netfilter.nf_conntrack_max = 524288
```

### Краевые случаи и ограничения

1.  **Атомарность:** nftables применяет изменения атомарно. Ошибка в синтаксисе halfway не частично активирует правила.
2.  **IPv6:** Если семейство `inet` используется, правило `tcp dport 80 accept` создаст записи и для IPv6. Для IPv6-only используйте `ip6` семейство.
3.  **Логирование `full`:** Записывает полные дампы пакетов, что может создать нагрузку на диск. Используйте только для диагностики.
4.  **Rate limit:** В nftables `limit rate` работает для любых протоколов. Для тонкой настройки UDP используйте Fail2ban.
5.  **Per-interface правила:** `iif "eth1"` требует точного имени интерфейса (проверьте через `ip link`).
6.  **Conntrack:** nftables использует `nf_conntrack`. При высокой нагрузке увеличьте `net.netfilter.nf_conntrack_max`.
7.  **notrack и helpers:** Использование `notrack` отключает отслеживание соединения, что может сломать FTP ALG и другие helpers. Используйте осторожно.
8.  **Flowtables:** При использовании flowtables пакеты попадают в цепочки `ingress`/`egress` семейства `netdev` и обходят классические `filter`-цепочки. Убедитесь, что политики согласованы.
9.  **TCP flags проверка:** Не все флаги TCP равнозначны. Например, пакет с флагами `FIN,PSH,URG` без `ACK` может быть некорректным, но `nftables` проверяет только битовую маску. Убедитесь, что выражения вида `tcp flags & (fin|syn|rst) != syn` покрывают ожидаемые аномалии.
10. **Race condition при live-тестировании:** При тестировании rate-limit или connection tracking exhaustion на production-хосте возможны кратковременные ложные срабатывания. Проводите тесты в maintenance-окнах или на клонах конфигурации.

### Best Practices

- **Тестируйте в maintenance-окне** при изменении production-файрвола. Держите консольный доступ готовым.
- **Версионируйте конфигурации** и тестовые сценарии в Git. Каждый релиз правил должен иметь тег.
- **Используйте staging-среду**, максимально приближенную к production (профиль трафика, количество соединений).
- **Автоматизируйте smoke-тесты** и прогоняйте их после каждого применения правил.
- **Логируйте все drops** с лимитом, но без полного дампа пакетов в production.
- **Счетчики — ваш primary source of truth.** Не полагайтесь только на `nc`/`nmap`; всегда проверяйте рост счетчиков `nft list ruleset`.
- **IPv6 не является опциональным.** Если сеть использует IPv6, тестируйте его отдельно; блокировка ICMPv6 может сломать маршрутизацию и NDP.

## Связанные темы

- **[nftables — моделирование угроз и схемы защиты](./threat_modeling.md):** стратегии построения правил.
- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md):** база хуков и приоритетов.
- **[nftables — практические сценарии](./practical_scenarios.md):** production-шаблоны stateful-файрвола, NAT, балансировки.
- **[nmap (Network Mapper)](../../../../Diagnostics/Networking/nmap.md):** подробное руководство по сканированию.
- **[Анализ сокетов с помощью ss](../../../../Diagnostics/Networking/ss.md):** локальная диагностика.
- **[Альтернативы ping](../../../../../Networking/Troubleshooting/ping_alternatives.md):** использование `hping3` и `tcping`.
