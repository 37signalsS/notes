# Алгоритмы управления перегрузкой TCP в Linux

Данное руководство фокусируется на практической настройке и выборе алгоритмов в ядре Linux. Теоретические основы, формулы и детальное сравнение логики работы алгоритмов доступны в справочнике: **[Алгоритмы управления перегрузкой TCP (Теория)](../../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md)**.

## Определения

**Алгоритм управления перегрузкой (Congestion Control Algorithm)** — программный модуль ядра Linux, регулирующий размер окна перегрузки (`cwnd`) и скорость отправки пакетов на основе сигналов обратной связи от сети.

**Loss-based алгоритмы (CUBIC, Reno)** — классические механизмы, реагирующие на потерю пакетов (Duplicate ACK или таймауты) как на единственный признак перегрузки.

**Model-based алгоритмы (BBR)** — строят математическую модель канала на основе измерения минимального RTT и максимальной пропускной способности, стараясь работать в точке, где очереди в сети минимальны.

**BBRv3** — стандарт 2026 года (ядра 6.x+). Третья итерация алгоритма Google, в которой исправлены проблемы «несправедливости» по отношению к CUBIC-потокам и улучшена работа в сетях с потерями, не связанными с перегрузкой (например, Wi-Fi/4G).

**ECN (Explicit Congestion Notification)** — механизм явного уведомления о перегрузке (RFC 3168). Позволяет маршрутизаторам сигнализировать о заполнении очереди до отбрасывания пакетов. Обязателен для L4S и рекомендуется для BBRv2/v3.

**L4S (Low Latency, Low Loss, Scalable throughput)** — архитектура (RFC 9330), позволяющая поддерживать сверхнизкую задержку (<10 мс) даже при полной загрузке канала за счет частой маркировки ECN на маршрутизаторах и проактивного реагирования отправителя (BBRv3/DCTCP).

**Pacing Rate** — целевая скорость отправки пакетов, вычисляемая алгоритмом (например, BBR) для предотвращения всплесков трафика (bursts). Реализуется через механизм EDT (Earliest Departure Time) в дисциплине очередей `fq`.

## Основные концепции

### Зависимость от дисциплины очередей (qdisc)

Эффективность алгоритма напрямую зависит от механизма выхода пакетов в сеть.
*   **BBR требует `fq`**: Алгоритм BBR использует механизм **EDT (Earliest Departure Time)** для точного соблюдения темпа отправки (Pacing). Без дисциплины `fq` BBR не сможет эффективно оценивать полосу пропускания.
*   **CUBIC универсален**: Эффективно работает с `fq_codel` и `cake`, которые активно борются с Bufferbloat на стороне коммутатора.

### Управление доступными алгоритмами

Ядро Linux позволяет ограничивать выбор алгоритмов для приложений в целях безопасности и стабильности.
*   `net.ipv4.tcp_available_congestion_control` — список всех модулей, загруженных в память.
*   `net.ipv4.tcp_allowed_congestion_control` — подмножество алгоритмов, которые разрешено выбирать непривилегированным процессам.
*   `net.ipv4.tcp_congestion_control` — алгоритм, назначаемый всем новым соединениям по умолчанию.

### Версии ядер и поддержка алгоритмов

| Ядро Linux | CUBIC | BBRv1 | BBRv2 | BBRv3 | DCTCP | Hybla |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **4.9+** | Да | Да | Нет | Нет | Нет | Нет |
| **5.4+** | Да | Да | Да | Нет | Да (модуль) | Да (модуль) |
| **5.18+** | Да | Да | Да | Нет | Да | Да |
| **6.1+** | Да | Да | Да | Да (опционально) | Да | Да |
| **6.6+** | Да | Да | Да | **Да (по умолчанию)** | Да | Да |

BBRv3 активируется автоматически при обращении к алгоритму `bbr` на ядрах 6.6+. На ядрах 5.18–6.5 по умолчанию загружается BBRv2.

### Взаимодействие с ECN и L4S

Для работы BBRv3 в режиме L4S требуется:
1. Включение ECN на хосте: `net.ipv4.tcp_ecn = 1`.
2. Поддержка ECN на всех коммутаторах в пути (включая виртуальные коммутаторы гипервизоров).
3. Дисциплина очереди `fq` на интерфейсе.

Если хотя бы один узел в пути не поддерживает ECN, система переходит в режим совместимости, и BBRv3 работает как model-based алгоритм без L4S-телеметрии.

## Практические сценарии

### 1. Проверка текущего состояния

```bash
# Список доступных в данный момент алгоритмов
sysctl net.ipv4.tcp_available_congestion_control

# Просмотр алгоритма для конкретных сокетов (ищите поле 'cong:')
ss -tin state established
# → bbr wscale:7,7 rto:204 rtt:0.52/0.03 cwnd:320 pacing_rate 1.2Gbps
```

### 2. Включение BBRv3 (Рекомендация 2026)

Для высоконагруженных серверов (Web, API, CDN) BBRv3 является оптимальным выбором.

**Постоянная настройка (`/etc/sysctl.d/99-network-bbr.conf`):**
```ini
# 1. Обязательная дисциплина очереди для реализации Pacing
net.core.default_qdisc = fq

# 2. Установка BBR по умолчанию
net.ipv4.tcp_congestion_control = bbr

# 3. Включение ECN (необходимо для BBRv2/v3 и поддержки L4S)
net.ipv4.tcp_ecn = 1
```
Применить: `sudo sysctl -p /etc/sysctl.d/99-network-bbr.conf`

**Валидация:**
```bash
# Проверка алгоритма по умолчанию
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = bbr

# Проверка дисциплины очереди на интерфейсе
tc qdisc show dev eth0
# → qdisc fq 8001: root

# Проверка ECN
ethtool -k eth0 | grep ecn
# → ecn: off (на NIC уровне, ECN работает на IP уровне)
nstat -az | grep -i ecn
# → TcpExtECN0ece: 0
# → TcpExtECN0ect1: 4521
```

### 3. Настройка для Low-Latency (DCTCP)

Внутри ЦОД (Data Center) для минимизации задержек в очередях используется **DCTCP**.

**Требования:**
*   Поддержка ECN на всех коммутаторах в сети.
*   Загрузка модуля: `sudo modprobe tcp_dctcp`.

```bash
# Установка DCTCP для конкретного маршрута к бэкендам
sudo ip route add 10.0.0.0/24 via 192.168.1.1 dev eth0 congctl dctcp
```

### 4. Взаимодействие с L4S (RFC 9330)

В ядрах 6.4+ реализована поддержка **L4S (Low Latency, Low Loss, Scalable throughput)**. При использовании BBRv3 и включенном ECN система может взаимодействовать с сетевым оборудованием для мгновенной корректировки скорости до возникновения потерь.

### 5. Расследование деградации пропускной способности (SRE Incident Response)

**Цель:** Выявить, является ли причина деградации неправильным алгоритмом, Bufferbloat или проблемой на сетевом пути.

**Шаг 1. Сбор базовых метрик:**

```bash
# Текущий алгоритм и параметры
sysctl net.ipv4.tcp_congestion_control
sysctl net.ipv4.tcp_available_congestion_control
sysctl net.ipv4.tcp_slow_start_after_idle
sysctl net.core.default_qdisc

# Активные соединения и их параметры
ss -tin state established '( dport = :443 )' | head -n 20
# Обратите внимание на: cwnd, pacing_rate, rtt, min_rtt, app_limited
```

**Шаг 2. Проверка Bufferbloat:**

```bash
# Без нагрузки
ping -c 20 8.8.8.8
# → rtt min/avg/max/mdev = 12.345/13.456/18.901/1.234 ms

# Под нагрузкой (iperf3 или утилитой вашего сервиса)
iperf3 -c <сервер> -t 60 -P 4 &
ping -c 60 8.8.8.8
# → rtt min/avg/max/mdev = 12.345/145.678/892.123/189.456 ms

# Если max RTT вырос в 5–10+ раз — Bufferbloat подтвержден.
```

**Шаг 3. Проверка счетчиков потерь:**

```bash
nstat -az | grep -E 'TcpExtTCPRetrans|TcpExtTCPSynRetrans|TcpExtTCPTimeouts'
# → TcpExtTCPRetransSegs: 1245
# → TcpExtTCPSynRetrans: 23
# → TcpExtTCPTimeouts: 89
```

**Шаг 4. Анализ и решение:**

| Наблюдение | Вероятная причина | Действие |
| :--- | :--- | :--- |
| Низкий `pacing_rate`, высокий RTT под нагрузкой | Отсутствует `fq` qdisc | `tc qdisc replace dev eth0 root fq` |
| `cwnd: 10` при высокой нагрузке | `tcp_slow_start_after_idle = 1` | Установить в 0 |
| Высокие `RetransSegs` + низкий throughput | CUBIC реагирует на помехи | Переключить на BBR |
| RTT под нагрузкой ×10 от базового | Bufferbloat | BBRv3 + `fq` или `fq_codel` на маршрутизаторе |

### 6. Настройка хоста контейнеров (Docker/LXC)

**Цель:** Оптимизация сетевого стека хоста для виртуализации без использования облачных технологий.

**Предпосылки:**
*   Ядро Linux 6.1+ (рекомендуется 6.6+ для BBRv3).
*   Доступ к `/etc/sysctl.d/` и `tc`.
*   Docker или LXC установлен на хосте.

**Шаг 1. Базовая настройка хоста:**

```bash
sudo tee /etc/sysctl.d/99-container-host.conf << 'EOF'
# === QoS: Fair Queuing для контейнеров ===
net.core.default_qdisc = fq

# === Алгоритм контроля перегрузки ===
net.ipv4.tcp_congestion_control = bbr

# === ECN для L4S-совместимости ===
net.ipv4.tcp_ecn = 1

# === Отключение сброса окна при простое (важно для контейнеров) ===
net.ipv4.tcp_slow_start_after_idle = 0

# === Увеличение лимитов соединений для высокой плотности контейнеров ===
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 16384
EOF

sudo sysctl -p /etc/sysctl.d/99-container-host.conf
```

**Шаг 2. Настройка `tc` для корневого интерфейса:**

```bash
# Проверка текущей дисциплины
tc qdisc show dev eth0

# Установка fq (обязательна для BBR)
sudo tc qdisc replace dev eth0 root fq
```

**Шаг 3. Проверка в контейнере:**

```bash
# Контейнер наследует алгоритм от хоста, но можно проверить
docker exec <container> sysctl net.ipv4.tcp_congestion_control
# → bbr

# Если контейнеру требуется другой алгоритм (например, для тестирования):
docker exec <container> sh -c "sysctl -w net.ipv4.tcp_congestion_control=cubic"
```

**Важно:** В Docker контейнеры по умолчанию используют сетевой стек хоста. Настройка на уровне хоста затрагивает все контейнеры. Для изоляции используйте отдельные сетевые пространства имен или виртуальные машины.

### 7. Мониторинг и оповещения (SRE Monitoring)

**Цель:** Настроить мониторинг ключевых метрик алгоритмов перегрузки для proactive-отклика.

**Метрики для мониторинга:**

| Метрика | Команда сбора | Порог для алерта |
| :--- | :--- | :--- |
| **Текущий алгоритм** | `sysctl net.ipv4.tcp_congestion_control` | Отклонение от expected |
| **Доступные алгоритмы** | `sysctl net.ipv4.tcp_available_congestion_control` | Отсутствие `bbr` |
| **Ретрансмиссии** | `nstat -az \| grep TcpExtTCPRetransSegs` | Рост >100/мин |
| **Таймауты** | `nstat -az \| grep TcpExtTCPTimeouts` | Рост >10/мин |
| **ECN CE пакеты** | `nstat -az \| grep TcpExtECN` | Резкий рост = перегрузка на маршрутизаторе |
| **Счетчики BBR** | `nstat -az \| grep -i Bbr` | `BbrBwProbeDown` = 0 при высокой нагрузке |
| **cwnd для BBR** | `ss -ti \| grep cwnd` | Постоянное `cwnd: 10` при нагрузке |

**Пример Bash-скрипта для мониторинга:**

```bash
#!/bin/bash
# /usr/local/bin/tcp-congestion-monitor.sh

THRESHOLD_RETRANS=100
THRESHOLD_TIMEOUTS=10

RETRANS=$(nstat -az | awk '/TcpExtTCPRetransSegs/ {print $2}')
TIMEOUTS=$(nstat -az | awk '/TcpExtTCPTimeouts/ {print $2}')

if [ "$RETRANS" -gt "$THRESHOLD_RETRANS" ]; then
    echo "ALERT: TCP retransmissions exceeded threshold: $RETRANS"
fi

if [ "$TIMEOUTS" -gt "$THRESHOLD_TIMEOUTS" ]; then
    echo "ALERT: TCP timeouts exceeded threshold: $TIMEOUTS"
fi

# Проверка дисциплины очереди
QDISC=$(tc qdisc show dev eth0 | awk '{print $2}')
if [ "$QDISC" != "fq" ] && [ "$QDISC" != "fq_codel" ]; then
    echo "ALERT: Unexpected qdisc on eth0: $QDISC"
fi
```

Интеграция с Prometheus/node_exporter: метрики доступны через `/proc/net/netstat` и `/proc/net/snmp`.

### 8. Валидация набора серверов (Fleet Check)

**Цель:** Быстрая проверка корректности настроек на группе серверов без облачных инструментов.

```bash
#!/bin/bash
# fleet_tcp_check.sh — проверка всех серверов из inventory

INVENTORY="servers.txt"  # список хостов или IP

while read -r host; do
    echo "=== $host ==="
    ssh "$host" "
        echo 'Algorithm:' \$(sysctl -n net.ipv4.tcp_congestion_control)
        echo 'Available:' \$(sysctl -n net.ipv4.tcp_available_congestion_control)
        echo 'ECN:' \$(sysctl -n net.ipv4.tcp_ecn)
        echo 'Qdisc:' \$(tc qdisc show dev eth0 | awk '{print \$2}')
        echo 'Retrans:' \$(nstat -az | awk '/TcpExtTCPRetransSegs/ {print \$2}')
    "
done < "$INVENTORY"
```

### 9. Откат к CUBIC (Rollback Procedure)

**Ситуация:** BBRv3 вызывает нестабильность на старом оборудовании или в гетерогенной среде.

```bash
# 1. Откат sysctl
sudo tee /etc/sysctl.d/99-tcp-rollback.conf << 'EOF'
net.core.default_qdisc = fq_codel
net.ipv4.tcp_congestion_control = cubic
net.ipv4.tcp_ecn = 0
EOF

sudo sysctl -p /etc/sysctl.d/99-tcp-rollback.conf

# 2. Проверка
sysctl net.ipv4.tcp_congestion_control
# → cubic

ss -tin state established | head -n 5
# → cubic wscale:7,7 rto:204 rtt:15.2/0.5 cwnd:120

# 3. Очистка (если требуется полное удаление BBR-файла)
sudo rm /etc/sysctl.d/99-network-bbr.conf
sudo sysctl --system
```

## Диагностика и мониторинг

Для оценки эффективности работы алгоритма используйте счетчики `nstat`:

```bash
# Проверка сигналов перегрузки (ECN)
nstat -az | grep -E 'TcpExtTCPBacklogCoalesce|TcpExtTCPACKCompressed'

# Эффективность BBR (ищите рост этих счетчиков при нагрузке)
nstat -az | grep -i 'BBR'

# Счетчики ECN
nstat -az | grep -i 'ECN'

# Общие счетчики ретрансмиссий
nstat -az | grep -E 'TcpExtTCPRetrans|TcpExtTCPSynRetrans|TcpExtTCPTimeouts'
```

Если в выводе `ss -ti` для BBR наблюдается постоянное значение `cwnd: 10`, это может указывать на:
1.  Сброс окна после простоя (`tcp_slow_start_after_idle`).
2.  Ограничение со стороны приложения (`app_limited`).

## Дополнительная информация

### Рекомендации по выбору (2026)

| Сценарий применения | Рекомендуемый алгоритм | Примечание |
| :--- | :--- | :--- |
| **Публичные Web-серверы / API** | **BBR (v3)** | Игнорирует случайные потери, обеспечивает минимальный TTFB. |
| **Стриминг / CDN / Ретрансляция** | **BBR (v3)** | Максимальная утилизация «толстых» каналов. |
| **Внутренние сети ЦОД** | **DCTCP** или **CUBIC** | Минимальный оверхед в стабильной среде. |
| **Нестабильные каналы (Wi-Fi, 4G)** | **BBR** | Намного стабильнее CUBIC при высоких потерях. |
| **Спутниковые / космические каналы** | **Hybla** или **BBR** | Компенсация экстремально высокого RTT (500 мс+). |
| **Универсальное применение (неизвестная среда)** | **CUBIC** | Стабильность и совместимость с любым оборудованием. |

### Типичные ошибки и их устранение

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Низкая скорость на высокоскоростном канале | `cwnd` ограничен малым значением | `ss -ti`: `cwnd: 10`, `app_limited` | Увеличить `initcwnd` до 32 MSS, отключить `tcp_slow_start_after_idle` |
| Резкие всплески трафика при BBR | Отсутствует дисциплина `fq` | `tc qdisc show dev eth0` | `sudo tc qdisc replace dev eth0 root fq` |
| Постоянные ретрансмиссии на Wi-Fi | CUBIC/Reno воспринимают помехи как перегрузку | `nstat -az \| grep Retrans` | Переключить на BBR или Westwood |
| Высокий RTT только под нагрузкой | Bufferbloat | `ss -ti`: `rtt` vs `min_rtt` | BBRv3 или `fq_codel` на маршрутизаторе |
| DCTCP не снижает задержку | ECN отклющен на коммутаторе | `nstat -az \| grep ECN` | Включить ECN на всех узлах маршрута |
| Длинный RTT, низкая скорость | Используется Reno/CUBIC без компенсации RTT | `ss -ti`: `rtt: 500+`, `cwnd` мал | Переключить на Hybla |
| BBR: `pacing_rate` отсутствует в `ss` | Неправильный qdisc | `tc qdisc show dev eth0` | Заменить на `fq` |
| CUBIC: синусоидальные колебания `cwnd` | Мелкие буферы на высоких скоростях | `ss -ti` под нагрузкой | Переключить на BBRv3 |

### Известные ограничения и edge cases

*   **BBR и синтетические сети:** В виртуализированных средах с большим внутренним RTT (например, VPN-туннели) BBR может недооценивать пропускную способность. Рекомендуется ручная калибровка или использование CUBIC.
*   **CUBIC и экзопонические сети:** При RTO < 1 секунда CUBIC может генерировать всплески, не успев завершить ProbeBW. В таких средах рекомендуется увеличить `tcp_slow_start_after_idle` или использовать BBRv3.
*   **DCTCP и гетерогенные сети:** Если хотя бы один коммутатор в пути не поддерживает ECN, DCTCP работает в режиме fallback (похожем на Reno), теряя преимущества. Обязательно проверять ECN-статистику (`nstat -az | grep ECN`) на всех узлах пути.
*   **Hybla и Windows:** Hybla не является стандартным алгоритмом в Windows. Для гибридных сред (Linux ↔ Windows) лучше использовать BBRv3 или CUBIC на стороне Linux.
*   **Ядра старше 5.4:** DCTCP и BBRv2/v3 недоступны. На таких системах используйте CUBIC и `fq_codel` для борьбы с Bufferbloat.

### Лучшие практики (SRE/Sysadmin)

1.  **Всегда используйте `fq` с BBR:** Без дисциплины `fq` алгоритм BBR теряет возможность точного pacing, что приводит к всплескам и неэффективной оценки полосы.
2.  **Включайте ECN глобально:** Начиная с 2026 года ECN является обязательным компонентом для современных алгоритмов (L4S, BBRv3). Включайте `net.ipv4.tcp_ecn = 1` на всех серверах.
3.  **Не смешивайте алгоритмы без AQM:** При наличии одновременно CUBIC и BBR потоков внедрите `fq_codel` или `cake` на маршрутизаторах для справедливого распределения полосы.
4.  **Тестируйте на этапе Staging:** Любое изменение алгоритма влияет на все соединения. Валидируйте на тестовом стенде перед применением на production.
5.  **Документируйте откат:** Всегда имейте готовый rollback-скрипт для возврата к CUBIC, если BBR вызовет неожиданное поведение.
6.  **Мониторьте `min_rtt`:** В `ss -ti` поле `min_rtt` показывает baseline-задержку канала. Если `min_rtt` растет — возможно, изменился маршрут или появились очереди на промежуточных узлах.
7.  **Настраивайте `initcwnd` совместно с BBR:** Для минимизации TTFB на высокоскоростных каналах используйте `initcwnd = 32` (10-е правило RFC 6928) вместе с `fq` qdisc.

### См. также
* **[Теория управления перегрузкой TCP](../../../../Networking/Protocols/TCP/congestion/tcp_congestion_control_overview.md)** — детальный разбор фаз (Slow Start, AIMD).
* **[Дисциплины очередей (qdisc)](./tcp_queueing_disciplines.md)** — почему BBR не работает без `fq`.
* **[Диагностика сокетов TCP](./tcp_socket_diagnostics.md)** — интерпретация метрик `ss`.
* **[Оптимизация буферов TCP](./tcp_buffer_tuning.md)** — расчет BDP для алгоритмов.
* **[Обзор тюнинга TCP](./tcp_tuning_overview.md)** — комплексная настройка сетевого стека.
