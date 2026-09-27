# Дисциплины очередей TCP в Linux

## Определения

**Дисциплина очередей (Queueing Discipline, qdisc)** — механизм ядра Linux, управляющий очередями сетевых пакетов перед их передачей драйверу сетевой карты (**NIC**). Он определяет алгоритм планирования, приоритизации и активного управления очередями (**AQM — Active Queue Management**).

**Bufferbloat (Раздувание буфера)** — деградация производительности сети из-за чрезмерно больших буферов в промежуточных узлах, что приводит к росту задержек (Latency) и джиттера при высокой нагрузке.

**Pacing (Сглаживание)** — механизм равномерного распределения пакетов во времени. Позволяет избежать всплесков трафика (Bursts), которые могут привести к потерям на коммутаторах с малым объемом памяти.

**EDT (Earliest Departure Time)** — современная модель планирования в Linux (начиная с ядра 4.19), где каждому пакету назначается временная метка выхода. Это обеспечивает сверхточный pacing, не требующий создания множества мелких очередей.

## Основные концепции

### Роль qdisc в сетевом стеке

Qdisc находится между сетевым стеком протоколов и драйвером интерфейса. В современных ядрах (2026) qdisc тесно интегрирован с механизмами **TSO (TCP Segmentation Offload)** и **GSO (Generic Segmentation Offload)**.

```text
[ Приложение ] → [ TCP Стек ] → [ GSO/TSO ] → [ qdisc (EDT) ] → [ NIC Driver ]
```

### Взаимодействие с алгоритмами перегрузки

Выбор qdisc критически влияет на эффективность алгоритмов контроля перегрузки:

| Алгоритм | Рекомендуемая qdisc | Обоснование |
| :--- | :--- | :--- |
| **BBR (v1/v2/v3)** | **`fq`** | BBR полагается на точный pacing. `fq` реализует EDT-планирование, что необходимо для расчета пропускной способности. |
| **CUBIC / Reno** | **`fq_codel`** | Эффективная изоляция потоков и борьба с Bufferbloat через алгоритм CoDel. |
| **Edge / WAN Shaper** | **`cake`** | Наиболее совершенный алгоритм для пограничных устройств, учитывающий NAT и приоритизацию трафика (DiffServ). |

### Основные типы дисциплин (2026)

#### Классические и базовые
*   **pfifo_fast:** Исторический дефолт в Linux. Имеет три полосы приоритетов (bands), но не борется с bufferbloat. Не рекомендуется для высоконагруженных систем.
*   **mq (Multi-Queue):** Специальная qdisc-обертка для многоочередных сетевых карт. Она создает отдельную под-qdisc для каждой аппаратной очереди NIC, позволяя параллельно обрабатывать трафик на разных ядрах CPU.
*   **mqprio (Multi-Queue Priority):** Расширение `mq`, позволяющее назначить приоритеты аппаратным очередям NIC через Traffic Classes. Позволяет напрямую маппить DSCP/PCP на аппаратные очереди, минуя программные классификаторы. Используется на NIC с hardware offload для QoS.
*   **noqueue:** Используется для виртуальных интерфейсов (loopback, bridge, veth), где физическая передача отсутствует и очереди в ядре только создают лишние накладные расходы.
*   **ingress:** Специальная бесклассовая дисциплина для входящего трафика. Поддерживает только **policing** (отбрасывание избыточных пакетов), не шейпинг. Для полноценного шейпинга входящего трафика используется связка с IFB (Intermediate Functional Block).

#### Иерархические (шейпинг и приоритизация)
*   **HTB (Hierarchical Token Bucket):** Классическая дисциплина для иерархического шейпинга. Позволяет создавать дерево классов с гарантированным `rate` и максимальным `ceil`, поддерживает заимствование полосы между классами. Требует настройки фильтров для классификации трафика. Широко используется в production для ограничения скорости по классам трафика.
*   **TBF (Token Bucket Filter):** Простая бесклассовая дисциплина для точного ограничения скорости без иерархии. Работает по принципу «токен-ведро»: токены добавляются с фиксированной скоростью, каждый пакет потребляет токены, избыток буферизуется или отбрасывается. Подходит для одиночного ограничения скорости на интерфейсе.

#### Современные AQM (Active Queue Management)
*   **fq (Fair Queuing):** Современный стандарт для серверных систем. Поддерживает **EDT**, обеспечивает справедливое распределение полосы между сокетами и реализует pacing на уровне ядра. Необходим для корректной работы BBR.
*   **fq_codel (Fair Queuing + CoDel):** Универсальное решение для десктопов. Борется с bufferbloat, используя алгоритм CoDel (Controlled Delay) для активного отбрасывания пакетов из «застоявшихся» очередей.
*   **CAKE (Common Applications Kept Enhanced):** Разработан для роутеров. Комбинирует AQM и иерархический шейпинг, автоматически учитывая накладные расходы линков и приоритизируя мелкие пакеты (ACK, DNS). Включает фильтрацию ACK и host-fairness.

#### Эмуляция и тестирование
*   **netem (Network Emulator):** Дисциплина для эмуляции проблем реальных сетей — задержек, потерь, джиттера, дублирования и изменения порядка пакетов. Используется в тестовых средах для chaos engineering и проверки устойчивости приложений к сетевым аномалиям. Не является шейпером — для ограничения скорости необходимо связывать с HTB или TBF.

#### Программируемые
*   **clsact (Classifier Action):** Специальная qdisc, используемая как точка прикрепления для **eBPF-программ** (Ingress/Egress). Позволяет реализовывать произвольную логику фильтрации и модификации трафика без создания классической иерархии классов.

## Практические сценарии

### 1. Проверка текущей конфигурации

```bash
# Проверка дисциплины по умолчанию
sysctl net.core.default_qdisc

# Просмотр qdisc для конкретного интерфейса
tc qdisc show dev eth0

# Детальная статистика (дропы, переполнения, pacing)
tc -s qdisc show dev eth0
```

### 2. Оптимизация сервера под BBRv3

Для работы BBRv3 необходимо убедиться, что используется дисциплина `fq`, так как она обеспечивает необходимый механизму EDT-pacing.

**Настройка через sysctl:**
```ini
# /etc/sysctl.d/99-bbr.conf
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
```

**Принудительная смена в runtime:**
```bash
sudo tc qdisc replace dev eth0 root fq
```

### 3. Борьба с Bufferbloat на рабочей станции

**Диагностика:** Если при полной загрузке канала (например, скачивание) время отклика (ping) вырастает на сотни миллисекунд — буферы переполнены.

**Решение:**
```bash
# Установка fq_codel для минимизации задержек
sudo tc qdisc replace dev eth0 root fq_codel
```

### 4. Шейпинг трафика на пограничном шлюзе (CAKE)

Если сервер раздает интернет и нужно ограничить скорость, сохранив плавность работы:

```bash
# Ограничение исходящего трафика до 50 Мбит/с с учетом Ethernet-заголовков
sudo tc qdisc add dev eth1 root cake bandwidth 50mbit ethernet
```

### 5. Модули ядра для qdisc

Многие дисциплины очередей загружаются как отдельные модули ядра. Если модуль не загружен, команда `tc qdisc add` вернет ошибку.

```bash
# Проверка загруженных модулей
lsmod | grep sch_

# Основные модули
# sch_fq       — Fair Queuing (обязательна для BBR)
# sch_fq_codel — FQ + CoDel AQM
# sch_cake     — CAKE шейпинг
# sch_htb      — Hierarchical Token Bucket
# sch_tbf      — Token Bucket Filter
# sch_netem    — Network Emulation
# sch_mqprio   — Multi-Queue Priority
# sch_ingress  — Policing входящего трафика
# ifb          — Intermediate Functional Block (для ingress shaping)

# Загрузка модуля
sudo modprobe sch_fq

# Постоянная загрузка модуля при старте системы
echo "sch_fq" | sudo tee /etc/modules-load.d/sch_fq.conf
```

> **Совет:** Модуль загружается автоматически при первом использовании соответствующей дисциплины через `tc`. Ручная загрузка нужна, если необходимо убедиться в наличии модуля до применения правил (например, в скриптах автоматизации).

### 6. Диагностика и мониторинг qdisc

#### Просмотр статистики

Ключ `-s` (statistics) критически важен для анализа работы очередей:

```bash
# Статистика qdisc (общая)
tc -s qdisc show dev eth0

# Пример вывода для fq:
# qdisc fq 0: root refcnt 2 limit 10000p bytes 10485760
#  Sent 1234567890 bytes 1234567 pkt
#  backlog 0b 0p requeues 0
#  memory 0b 0p  mark 0 0
#  capacity_estimate 0b

# Ключевые поля:
#   sent     — общего объем переданных данных (байты/пакеты)
#   backlog  — текущее количество данных в очереди (байты/пакеты)
#   requeues — количество возвратов пакетов обратно в очередь (высокое значение → проблемы с драйвером NIC)
#   dropped  — пакеты, отброшенные из-за переполнения очередей или policing
#   overlimits — количество задержек пакетов из-за достижения лимита скорости

# Статистика классов (для HTB/иерархических дисциплин)
tc -s class show dev eth0

# Статистика фильтров (счётчики совпадений)
tc -s filter show dev eth0

# Мониторинг в реальном времени
watch -n 1 "tc -s qdisc show dev eth0"
```

#### Интерпретация ключевых полей

| Поле | Что означает | Норма | Проблема |
| :--- | :--- | :--- | :--- |
| **dropped** | Пакеты, отброшенные qdisc | 0 | Рост → переполнение очередей или policing |
| **overlimits** | Задержки из-за лимита скорости | Ожидаемо при шейпинге | Критический рост → burst слишком мал |
| **backlog** | Текущий размер очереди | 0–100 пакетов | Стабильно высокий → bufferbloat |
| **requeues** | Возвраты пакетов в очередь | 0 | Рост → проблема в драйвере NIC или IFB |

#### Диагностика bufferbloat через qdisc

```bash
# Проверка длины очереди при нагрузке
tc -s qdisc show dev eth0
# → Если backlog стабильно высокий (>1000 пакетов) при полной загрузке — bufferbloat

# Параллельный мониторинг пинга и очереди
# Терминал 1: пинг до целевого хоста
ping -i 0.1 <target>

# Терминал 2: мониторинг очереди
watch -n 0.5 "tc -s qdisc show dev eth0 | grep -E 'backlog|dropped'"
```

### 7. Персистентность настроек tc

Правила `tc` **не сохраняются после перезагрузки**. Для автоматического применения необходимо настроить persistent mechanisms.

#### Вариант 1: systemd-юнит (рекомендуется для production)

```ini
# /etc/systemd/system/tc-qos.service
[Unit]
Description=Traffic Control QoS rules
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/tc-apply.sh
ExecStop=/usr/local/bin/tc-cleanup.sh

[Install]
WantedBy=multi-user.target
```

```bash
# /usr/local/bin/tc-apply.sh
#!/bin/bash
set -e
IFACE="${TC_IFACE:-eth0}"

# Сброс предыдущих правил
tc qdisc del dev $IFACE root 2>/dev/null || true

# Применение BBR + fq
tc qdisc replace dev $IFACE root fq

echo "tc rules applied on $IFACE"
```

```bash
# /usr/local/bin/tc-cleanup.sh
#!/bin/bash
IFACE="${TC_IFACE:-eth0}"
tc qdisc del dev $IFACE root 2>/dev/null || true
echo "tc rules removed on $IFACE"
```

```bash
sudo chmod +x /usr/local/bin/tc-apply.sh /usr/local/bin/tc-cleanup.sh
sudo systemctl enable --now tc-qos.service
```

> **Преимущество:** Управление через `systemctl start/stop tc-qos` позволяет корректно откатить правила.

#### Вариант 2: Скрипт в `/etc/network/if-up.d/` (классический)

```bash
#!/bin/bash
# /etc/network/if-up.d/99-tc-qos
IFACE="${IFACE:-eth0}"
tc qdisc del dev $IFACE root 2>/dev/null || true
tc qdisc replace dev $IFACE root fq
```

```bash
sudo chmod +x /etc/network/if-up.d/99-tc-qos
```

#### Вариант 3: networkd-dispatcher (для systemd-networkd)

```bash
#!/bin/bash
# /etc/networkd-dispatcher/routable.d/99-tc-qos.sh
tc qdisc replace dev $IFACE root fq
```

```bash
sudo chmod +x /etc/networkd-dispatcher/routable.d/99-tc-qos.sh
```

### 8. Промышленные сценарии (DevOps/SRE)

#### Сценарий A: Ограничение исходящего трафика по классам (HTB)

Задача: гарантировать 200 Мбит для API-трафика, остальное (до 1 Гбит) — для фоновых задач (бэкапы, логи), с возможностью заимствования полосы.

```bash
# 1. Корневая дисциплина HTB
sudo tc qdisc replace dev eth0 root handle 1: htb default 20

# 2. Общий класс-родитель (1 Гбит)
sudo tc class add dev eth0 parent 1: classid 1:1 htb rate 1gbit ceil 1gbit

# 3. Класс для API (rate — гарантия, ceil — максимум при свободной полосе)
sudo tc class add dev eth0 parent 1:1 classid 1:10 htb rate 200mbit ceil 1gbit prio 0

# 4. Класс для фонового трафика
sudo tc class add dev eth0 parent 1:1 classid 1:20 htb rate 800mbit ceil 1gbit prio 1

# 5. fq_codel внутри каждого класса для борьбы с bufferbloat
sudo tc qdisc add dev eth0 parent 1:10 fq_codel
sudo tc qdisc add dev eth0 parent 1:20 fq_codel

# 6. Фильтры: направляем трафик на порт 443 (API) в класс 1:10
sudo tc filter add dev eth0 parent 1: protocol ip flower ip_proto tcp dst_port 443 flowid 1:10

# Валидация
tc -s class show dev eth0
# → Класс 1:10 должен показывать sent bytes для API-трафика
```

#### Сценарий B: Шейпинг входящего трафика (IFB)

Задача: ограничить входящий трафик до 50 Мбит/с для имитации условий промышленного канала.

```bash
# 1. Загрузка модуля и активация IFB
sudo modprobe ifb
sudo ip link set ifb0 up

# 2. Перенаправление входящего трафика с eth0 на ifb0
sudo tc qdisc add dev eth0 handle ffff: ingress
sudo tc filter add dev eth0 parent ffff: protocol ip u32 match u32 0 0 \
    action mirred egress redirect dev ifb0

# 3. Применение шейпинга на ifb0
sudo tc qdisc add dev ifb0 root cake bandwidth 50mbit

# Валидация
tc qdisc show dev ifb0
# → qdisc cake ... root ... bandwidth 50Mbit
```

#### Сценарий C: Тестирование устойчивости к потерям (netem)

Задача: проверить поведение приложения при потерях 1% пакетов и задержке 50 мс.

```bash
# 1. Применение netem
sudo tc qdisc add dev eth0 root netem delay 50ms 10ms loss 1%

# 2. Тестирование (например, curl до сервиса)
curl -w "time_total: %{time_total}\n" -o /dev/null -s http://target:8080/api

# 3. Сброс после тестов
sudo tc qdisc del dev eth0 root
```

#### Сценарий D: Диагностика проблемы «-dependent pacing»

Симптом: BBR установлен, но `ss -tin` не показывает `pacing_rate`.

```bash
# 1. Проверка текущей qdisc
tc qdisc show dev eth0
# → Если pfifo_fast или noqueue — BBR не может использовать pacing

# 2. Замена на fq (обязательна для BBR)
sudo tc qdisc replace dev eth0 root fq

# 3. Проверка pacing_rate для активных соединений
ss -tin state established | grep -o "pacing_rate [^ ]*"
# → pacing_rate 130Mbps (ожидаемое значение)
```

## Дополнительная информация

### Выбор qdisc по ролям (2026)

| Роль системы | Рекомендация | Примечание |
| :--- | :--- | :--- |
| **High-Perf Server / API** | **`fq`** | Требуется для BBRv3 и точного pacing. |
| **Workstation / Laptop** | **`fq_codel`** | Оптимально для интерактивности (Zoom, игры). |
| **Router / VPN GW** | **`cake`** | Лучшее управление очередями при шейпинге. |
| **Container (veth)** | **`noqueue`** | Минимизация CPU оверхеда внутри пода. |

### Ограничения и особенности

*   **Offloading:** Аппаратный оффлоадинг (TSO/GSO) может конфликтовать с некоторыми функциями qdisc (например, шейпингом). При аномалиях проверяйте статус через `ethtool -k <iface>`. Например, `ethtool -k eth0 | grep -E "tcp-segmentation|generic-segmentation"`.
*   **Влияние на CPU:** AQM-дисциплины (`fq_codel`, `cake`) потребляют больше ресурсов CPU, чем простые `pfifo`, что может быть заметно на скоростях 40G+. На 100G+ линках рекомендуется `mq` + аппаратный offload для классификации.
*   **Одновременное применение:** Нельзя применить несколько экземпляров одной qdisc к одному интерфейсу. Для комбинирования эффектов (например, шейпинг + эмуляция задержек) используйте иерархию классов (HTB + netem как leaf-qdisc).
*   **Персистентность:** Правила `tc` теряются при перезагрузке. Обязательно настройте persistent mechanisms (systemd-юниты или скрипты в `/etc/network/if-up.d/`).
*   **Ядерные модули:** Дисциплины `fq`, `fq_codel`, `cake`, `htb`, `netem` загружаются как модули. Если модуль не загружен, команда `tc qdisc add` завершится ошибкой. Загрузите модуль вручную (`modprobe sch_<name>`) или добавьте в `/etc/modules-load.d/`.
*   **Совместимость прошивок:** Встроенные ОС (OpenWrt, RouterOS) имеют усеченный набор qdisc. Проверяйте доступность нужных дисциплин через `tc qdisc show` перед применением правил.
*   **Влияние на TCP pacing:** Дисциплины `fq` и `cake` реализуют pacing на уровне ядра (EDT). Дисциплины `pfifo_fast`, `htb`, `tbf` — нет. Для BBR pacing обязателен `fq`.

### См. также
* **[Управление трафиком через tc](../../Tools/iproute2/tc.md)** — практический справочник по утилите.
* **[Алгоритмы контроля перегрузки](./tcp_congestion_algorithms.md)** — подробнее о связи BBR и fq.
* **[Оптимизация TCP: Обзор](./tcp_tuning_overview.md)** — комплексная настройка сетевого стека.
* **[QoS: Концепции и механизмы](../../../../Networking/Concepts/qos.md)** — policing vs shaping, DiffServ, ECN, иерархический шейпинг.
* **[tc netem: Эмуляция сетевых проблем](../../../../Linux/Networking/Tools/iproute2/tc_netem.md)** — задержки, потери, джиттер для тестов.
