# Повторная передача в TCP (Retransmission)

## Определения

**Повторная передача (Retransmission)** — фундаментальный механизм надежности TCP, заключающийся в повторной отправке сегментов данных, получение которых не было подтверждено в установленный срок. Это основной метод компенсации потерь в IP-сетях.

**Retransmission Timeout (RTO):** Время ожидания подтверждения (ACK), по истечении которого сегмент считается официально потерянным. Значение RTO динамически адаптируется к сетевым условиям на основе измерений RTT.

**Fast Retransmit:** Механизм восстановления данных до истечения таймера RTO, инициируемый получением 3 дублирующих ACK (DupACK). Позволяет минимизировать задержку при единичных потерях.

**Spurious Retransmission (Ложная ретрансмиссия):** Повторная отправка данных, которые на самом деле не были потеряны, а лишь задержались в сети или подтверждение на них не успело дойти до отправителя. Расточительна и может ухудшать производительность.

---

## Базовые концепции

### 1. Тайм-аут повторной передачи (RTO)
TCP рассчитывает время ожидания на основе измерений **RTT** (Round-Trip Time).

- **Алгоритм расчета (RFC 6298):** Использует сглаженное значение RTT (**SRTT**) и дисперсию (**RTTVAR**). Формула: `RTO = SRTT + max(G, 4 * RTTVAR)`, где G — гранулярность системного таймера.
- **Алгоритм Карна (Karn's Algorithm):** TCP не учитывает измерения RTT для ретрансмитированных сегментов (так как невозможно понять, на какую из отправок пришел ACK), чтобы не искажать расчеты.
- **Экспоненциальный рост (Backoff):** Если после ретрансмиссии ACK снова не получен, значение RTO удваивается (до предела `tcp_retries2`). Это защищает сеть от перегрузки во время сбоев.

#### Формулы обновления (RFC 6298, Sec. 2)

```text
При получении первого замера RTT (R):
  SRTT   ← R
  RTTVAR ← R / 2
  RTO    ← SRTT + max(G, 4 × RTTVAR)

При последующих замерах (R'):
  RTTVAR ← (1 - β) × RTTVAR + β × |SRTT - R'|    (β = 1/4)
  SRTT   ← (1 - α) × SRTT + α × R'                (α = 1/8)
  RTO    ← SRTT + max(G, 4 × RTTVAR)
```

**Граничные значения RTO:**
- `net.ipv4.tcp_rto_min` = 200 мс (по умолчанию). Для локальных сетей можно снизить до 5 мс.
- `net.ipv4.tcp_rto_max` = 120 000 мс (по умолчанию).
- При Backoff RTO удваивается до `2^n × базовый_RTO`, где n = `tcp_retries2` (по умолчанию 15, т.е. ~924 сек).

**Поведение при простое (Idle):**
- При `tcp_slow_start_after_idle=1` (по умолчанию) RTO сбрасывается при простое > 1 секунды, `cwnd` сбрасывается до начального значения.
- При `tcp_slow_start_after_idle=0` RTO сохраняется, что выгодно для_keep-alive соединений.

---

### 2. Быстрая ретрансмиссия (Fast Retransmit)
Позволяет восстановить данные до истечения таймера RTO, что критично для минимизации задержек.

- **Триггер:** Получение **3 дублирующих подтверждений (DupACK)** с одним и тем же номером.
- **Логика:** Получение 3-х DupACK свидетельствует о том, что пакеты, отправленные *после* потерянного, успешно дошли. Значит, сеть не оборвана, а произошел единичный пропуск.
- **Fast Recovery:** После быстрой ретрансмиссии TCP переходит в режим восстановления, временно уменьшая окно перегрузки (`cwnd`), но не сбрасывая его до 1 MSS.

#### Механика Fast Recovery (RFC 5681, Sec. 3.2)

```text
1. Получен 3-й DupACK →:
   - ssthresh ← max(FlightSize / 2, 2 × SMSS)
   - retransmit lost segment
   - cwnd ← ssthresh + 3 × SMSS  (учитывая 3 полученных DupACK)

2. Получен дополнительный DupACK →:
   - cwnd ← cwnd + SMSS  (продолжаем получать данные)

3. Получен partial ACK (ACK, подтверждающий новые данные, но не все丢失的数据):
   - retransmit first unacknowledged segment
   - cwnd ← cwnd - SMSS + SMSS  (сжимаем, но не сбрасываем)
   - НЕ выходим из Recovery, пока не будут подтверждены все丢失的数据

4. Получен full ACK (подтверждает все丢失的数据):
   - Выходим из Recovery
   - cwnd ← min(ssthresh,-flightsize) (RFC 5681)
```

**Частичный ACK (Partial ACK):** В классическом Reno при partial ACK TCP может неправильно выйти из Recovery. **NewReno** (RFC 2582) исправляет это, оставаясь в Recovery до получения полного подтверждения всех丢失的数据. Сегодня все современные ОС используют варианты NewReno или SACK-based recovery.

---

### 3. Современные алгоритмы (RACK-TLP)
В современных стеках (Linux с ядер 4.15+, RFC 8985) классические механизмы дополнены:

- **Tail Loss Probe (TLP):** Зондирование «хвоста» передачи. Если данных больше нет (и DupACK невозможны), TLP отправляет один пробный сегмент перед RTO, чтобы спровоцировать ответ от получателя.
- **RACK (Recent Acknowledgment):** Обнаруживает потери на основе **времени доставки**, а не номеров последовательностей. Это делает TCP устойчивым к переупорядочиванию пакетов (Packet Reordering).

#### RACK: детали алгоритма

RACK заменяет классическое «считаем DupACK» на временна́ю эвристику:

```text
Решение о потере принимается, если:
  current_time > rack_detect_time
  Где: rack_detect_time = max(sent_time_of_lost_segment + rack_rtt_var, reorder_win)
```

- **rack_rtt_var:** Сглаженное отклонение RTT. Автоматически учитывает jitter.
- **reorder_win:** Минимальное окно терпимости к переупорядочиванию (по умолчанию~2 мс, но динамически). Если пакеты переупорядочены в пределах этого окна, RACK не считает это потерей.
- **RACK-TLP联合:** TLP запускает RACK-проверку: если пробный сегмент не провоцирует DupACK или новый ACK, RACK подтверждает потерю.

```bash
# Включение RACK (включено по умолчанию в Linux 4.15+)
sysctl net.ipv4.tcp_recovery=1
# Значение: 1 = RACK включен
```

**Преимущества RACK перед DupACK:**
- Устойчив к переупорядочиванию (reordering tolerance через reorder_win).
- Работает для только что отправленных сегментов (не нужно ждать 3 DupACK).
- Автоматически адаптируется к jitter (rack_rtt_var).

#### TLP: детали алгоритма

TLP решает проблему «хвоста» — когда丢失的是最后一个 сегмент и DupACK невозможны:

```text
TLP Timer = 2 × RTT  (или 10 мс, что больше)
```

1. Таймер TLP запускается при отправке последнего сегмента.
2. По истечении: отправляется «пробный сегмент» (probe) с SSN = last_sent_SN.
3. Если получатель отвечает DupACK → RACK определяет потерю.
4. Если получатель молчит → RTO срабатывает как обычно.

```bash
# Управление TLP через sysctl
sysctl net.ipv4.tcp_early_retrans
# Значение: 4 = TLP + RACK (по умолчанию в современных ядрах)
# Значение: 3 = TLP без RACK
# Значение: 0 = отключен
```

---

### 4. Борьба с ложными ретрансмиссиями

#### Eifel Algorithm (RFC 3522)

Eifel использует **TCP Timestamps** (opt Kind=8) для определения, является ли ACK ответом на первую передачу или на ретрансмиссию:

```text
При отправке сегмента S:
  tsval_before ← текущий Timestamp Value
  отправить S с tsval_before

При получении ACK на S:
  если ACK.tsval == tsval_before:
      это ответ на ПЕРВУЮ передачу → ACK был задержан, потеря не была реальной
      → НЕ уменьшать cwnd (восстановить до значения до ретрансмиссии)
  иначе:
      это ответ на ретрансмиссию → потеря была реальной
      → оставить cwnd уменьшенным
```

```bash
# Eifel включен по умолчанию в Linux
# Для полной проверки через ss:
ss -ti dst 1.2.3.4 | grep -i eifel
```

#### F-RTO (Forward RTO-Recovery, RFC 4653)

F-RTO определяет ложные RTO без Timestamps, отправляя 2 пробных сегмента:

```text
После RTO:
1. Отправить 1 пробный сегмент (против обычного 1)
2. Если получен ACK > SND.UNA:
   → ACK подтверждает данные, отправленные ДО таймаута
   → RTO был ложным → восстановить cwnd до 2×SMSS
   иначе:
   → RTO был реальным → оставить cwnd = 1 SMSS
```

**Linux включает F-RTO по умолчанию** (`net.ipv4.tcp_frto=2`).

#### D-SACK (Duplicate SACK, RFC 2883)

D-SACK — расширение SACK, позволяющее **получателю** сообщить отправителю о ложных ретрансмиссиях:

```text
Отправитель получает SACK-блок:
  Seq=1000, Len=500

Отправитель проверяет:
  Если Seq=1000 уже был отправлен и подтвержден:
      → Это D-SACK блок (получатель сообщает: "я уже получил это, ты отправил повторно")
      → Считаем Spurious Retransmission
      → Увеличиваем reorder_win для RACK
```

```bash
# D-SACK включен по умолчанию
sysctl net.ipv4.tcp_dsack
# → net.ipv4.tcp_dsack = 1

# Счетчик ложных ретрансмиссий через nstat
nstat -az | grep -i spurious
# → TcpExtTCPSpuriousRtxHostQueues    142    0.0
# → TcpExtTCPSpuriousRto               23    0.0
```

**Как D-SACK влияет на поведение:**
1. При обнаружении D-SACK отправитель увеличивает `reorder_win` (RACK become more tolerant).
2. Если слишком много D-SACK → TCP может перейти в «conservative» режим (менее агрессивно снижает cwnd).

---

### 5. SACK + Retransmission: взаимодействие

Без SACK отправитель может ретрансмитировать только **первый丢失的 сегмент** (не зная о других). С SACK отправитель получает точную карту丢失的 данных и может ретрансмитировать **сразу несколько сегментов**.

#### SACK-based Recovery (RFC 6675)

```text
Алгоритм SACK Recovery:
1. Получен 3-й DupACK → определить丢失的 сегмент через SACK-блоки
2. Retransmit lost segment (самый старый丢失的)
3. Если получен additional SACK:
   - Определить следующий丢失的 сегмент
   - Retransmit его (если cwnd позволяет)
4. Если partial ACK → retransmit next lost segment (как в NewReno)
5. Если все丢失的数据 retransmitted и ACK > recovery_point → выйти из Recovery
```

```bash
# Проверка SACK-based recovery в ядре
sysctl net.ipv4.tcp_sack
# → net.ipv4.tcp_sack = 1  (включен по умолчанию)

# Счетчик SACK Recovery
nstat -az | grep -i sackrecovery
# → TcpExtTCPSACKRecovery     312    0.0
```

**Ограничение.receiver reneging:** Получатель может отменить ранее подтвержденные SACK-блоки (reneging). Отправитель должен это учитывать — если получатель reneges, отправитель считает это потерей.

#### SACK vs Non-SACK: сравнение

| Аспект | Без SACK | С SACK |
| :--- | :--- | :--- |
| **Количество丢失的** | Можно определить только первый丢失的 | Можно определить все丢失的 сегменты |
| **Ретрансмиссия** | По одному сегменту за RTT | Несколько сегментов за RTT |
| **Восстановление** | Медленное (много RTT) | Быстрое (один RTT для множественных потерь) |
| **Linux по умолчанию** | Выключено | Включено (`tcp_sack=1`) |

---

### 6. Retransmission + Congestion Control: взаимодействие

Разные CC-алгоритмы по-разному реагируют на ретрансмиссии:

| Событие | Tahoe | Reno/NewReno | CUBIC | BBR |
| :--- | :--- | :--- | :--- | :--- |
| **RTO** | cwnd = 1 MSS | cwnd = 1 MSS | cwnd = 1 MSS, ssthresh = cwnd × 0.7 | cwnd = 1 MSS, pacing rate restored |
| **Fast Retransmit** | cwnd = 1 MSS | cwnd = ssthresh + 3 | cwnd = cwnd × 0.7 | cwnd = винт洲 (probe_bw) |
| **Spurious RTO** | cwnd = 1 MSS (всегда) | cwnd = 1 MSS (всегда) | cwnd = 1 MSS (всегда) | cwnd восстанавливается (BBR обнаруживает через RTT) |

**Ключевое:** Все классические алгоритмы (Tahoe, Reno, CUBIC) сбрасывают `cwnd` до 1 MSS при RTO. Только BBR может восстановить `cwnd` после ложного RTO, используя временны́е эвристики.

```bash
# Проверка текущего CC-алгоритма
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = cubic

# Как CC алгоритм реагирует на RTO (пример для CUBIC)
# 1. RTO сработал → cwnd = 1 MSS
# 2. Slow Start → cwnd растет экспоненциально
# 3. Достиг ssthresh → Congestion Avoidance → линейный рост
```

---

### 7. Влияние NIC Offloading на анализ ретрансмиссий

NIC Offloading (TSO, GRO, LRO, Checksum Offload) может создавать **ложные сигналы** о ретрансмиссиях в tcpdump/Wireshark:

| Offloading | Проблема | Решение |
| :--- | :--- | :--- |
| **TSO/GSO** | Один большой сегмент разбивается NIC → Wireshark видит «дубли» | Отключить: `ethtool -K eth0 tso off` (для анализа) |
| **GRO/LRO** | Мелкие пакеты объединяются NIC → Wireshark не видит losses | Проверять через `ss -ti` (ядро видит реальные данные) |
| **Checksum Offload** | Неверные checksum в дампе → ложные `TcpInCsumErrors` | Отключить: `ethtool -K eth0 tx off rx off` (для анализа) |

```bash
# Отключение offloading для анализа (не для прода!)
sudo ethtool -K eth0 tso off gso off gro off lro off tx off rx off

# После анализа — включить обратно
sudo ethtool -K eth0 tso on gso on gro on lro on tx on rx on
```

**Важно:** Всегда проверяйте `ss -ti` вместо tcpdump для определения реальных ретрансмиссий. Ядро видит реальные сегменты до/после offloading.

---

## Практические сценарии

### Сценарий 1: Тюнинг RTO для низких задержек
В локальных сетях или ЦОД стандартный минимальный RTO (200 мс) может быть избыточным.

```bash
# Установка минимального RTO (rto_min) в 5 мс для локальной подсети
sudo ip route change 10.0.0.0/24 dev eth0 rto_min 5ms

# Проверка
ip route show | grep 10.0.0.0
# → 10.0.0.0/24 dev eth0 rto_min 5ms
```

**Когда это выгодно:**
- Локальные ЦОД (RTT < 1 мс).
- Высокочастотные транзакции (trading, real-time gaming).
- Стоимость RTO=200мс: каждая потеря добавляет 200мс задержки.

**Когда это вредно:**
- WAN/интернет (RTT > 10 мс): RTO=5мс будет срабатывать при正常的 jitter.
- Мобильные сети: нестабильный RTT.

### Сценарий 2: Глобальные лимиты повторных передач
Параметр `tcp_retries2` определяет агрессивность TCP перед разрывом связи.

```bash
# Уменьшение количества попыток до 8 (ускоряет обнаружение обрыва)
sudo sysctl -w net.ipv4.tcp_retries2=8
# → net.ipv4.tcp_retries2 = 8
# → Время до разрыва: ~15 секунд (вместо ~13 минут при значении 15)

# Увеличение до 20 (для очень нестабильных каналов)
sudo sysctl -w net.ipv4.tcp_retries2=20
# → Время до разрыва: ~15 минут
```

**Формула расчета времени до разрыва:** `T ≈ Σ(2^n × RTO)`, где n от 0 до `tcp_retries2`. При RTO=200мс и `tcp_retries2=8`: T ≈ 200×(2^8 - 1)/1000 ≈ 51 секунда.

### Сценарий 3: Диагностика типов ретрансмиссий через ss
Анализ состояния активной сессии:

```bash
ss -ti dst 1.2.3.4
# → cubic rto:204 rtt:15.2/0.5 cwnd:10 retrans:0/52 sack_retrans:12 backoff:0
```
- **retrans:0/52:** В данный момент активных потерь нет, всего за сессию было 52 ретрансмиссии.
- **sack_retrans:12:** Указывает, сколько потерь было эффективно восстановлено через SACK.
- **backoff:0:** Если значение > 0, значит соединение находится в фазе экспоненциального ожидания (сеть лежит).

### Сценарий 4: Отключение RACK для отладки
Если RACK ошибочно классифицирует reordered packets как losses:

```bash
# Временное отключение RACK
sudo sysctl -w net.ipv4.tcp_recovery=0
# → Восстанавливаем DupACK-based loss detection

# После отладки — включить обратно
sudo sysctl -w net.ipv4.tcp_recovery=1
```

### Сценарий 5: Анализ TLP через nstat

```bash
# Счетчик TLP
nstat -az | grep -i taillossprobe
# → TcpExtTCPTailLossProbe    45    0.0

# Соотношение TLP к общим ретрансмиссиям
TLP=$(nstat -az TcpExtTCPTailLossProbe 2>/dev/null | awk '/TcpExtTCPTailLossProbe/{print $2}')
RETRANS=$(nstat -az TcpRetransSegs 2>/dev/null | awk '/TcpRetransSegs/{print $2}')
if [ "$RETRANS" -gt 0 ] 2>/dev/null; then
    RATIO=$(echo "scale=2; $TLP * 100 / $RETRANS" | bc 2>/dev/null)
    echo "TLP составляет ${RATIO}% от общих ретрансмиссий"
fi
# → Если TLP > 30% → много коротких транзакций с потерей «хвоста»
# → Рассмотреть увеличение tcp_notsent_lowat
```

### Сценарий 6: Обнаружение Spurious Retransmissions

```bash
# Проверка ложных ретрансмиссий
nstat -az | grep -iE 'Spurious|TCPSpurious'
# → TcpExtTCPSpuriousRtxHostQueues    142    0.0
# → TcpExtTCPSpuriousRto               23    0.0

# Соотношение ложных к общим
TOTAL=$(nstat -az TcpRetransSegs 2>/dev/null | awk '/TcpRetransSegs/{print $2}')
SPURIOUS=$(nstat -az TcpExtTCPSpuriousRto 2>/dev/null | awk '/TcpExtTCPSpuriousRto/{print $2}')
if [ "$TOTAL" -gt 0 ] 2>/dev/null; then
    RATIO=$(echo "scale=2; $SPURIOUS * 100 / $TOTAL" | bc 2>/dev/null)
    echo "Spurious Retransmissions: ${RATIO}% от общих ретрансмиссий"
    if (( $(echo "$RATIO > 20" | bc -l 2>/dev/null || echo 0) )); then
        echo ">>> ВНИМАНИЕ: > 20% ложных ретрансмиссий!"
        echo ">>> Рекомендация: увеличить tcp_rto_min (для локальных сетей: 5 мс)"
        echo ">>> Или проверить стабильность маршрута (mobile, Wi-Fi)"
    fi
fi
```

---

## Полный справочник sysctl для ретрансмиссий

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `net.ipv4.tcp_retries2` | 15 | Максимальное количество повторных передач перед разрывом (~13 мин). |
| `net.ipv4.tcp_rto_min` | 200 мс | Минимальный RTO. Снижение до 5 мс выгодно для локальных сетей. |
| `net.ipv4.tcp_rto_max` | 120000 мс | Максимальный RTO. |
| `net.ipv4.tcp_frto` | 2 | F-RTO: 0=отключен, 2=включен (RFC 4653). |
| `net.ipv4.tcp_recovery` | 1 | RACK: 0=отключен, 1=включен (Linux 4.15+). |
| `net.ipv4.tcp_early_retrans` | 4 | TLP: 0=отключен, 3=TLP, 4=TLP+RACK. |
| `net.ipv4.tcp_sack` | 1 | SACK: 0=отключен, 1=включен. Обязателен для RFC 6675. |
| `net.ipv4.tcp_dsack` | 1 | D-SACK: 0=отключен, 1=включен. Помогает обнаруживать spurious retrans. |
| `net.ipv4.tcp_slow_start_after_idle` | 1 | Сброс cwnd/RTO при простое > 1 сек. Для keep-alive: отключить (0). |
| `net.ipv4.tcp_no_metrics_save` | 0 | Не сохранять метрики (ssthresh, rtt) при закрытии соединения. |
| `net.ipv4.tcp_moderate_rcvbuf` | 1 | Автоматическая настройка receive buffer (RLINK). |
| `net.core.rmem_max` | 212992 | Максимальный размер receive buffer. Для BDP > 21 Мбит: увеличить. |
| `net.core.wmem_max` | 212992 | Максимальный размер send buffer. |

---

## Сравнение с QUIC

QUIC (RFC 9000) реализует ретрансмиссию на уровне приложения, что дает преимущества:

| Аспект | TCP | QUIC |
| :--- | :--- | :--- |
| **RTO** | Ядро ОС (RFC 6298) | Приложение (RFC 9000, Sec. 6.2) |
| **Fast Retransmit** | 3 DupACK (ядро) | 3 PTO (приложение) |
| **SACK** | Опционально (ядро) | Всегда (QUIC ACK Frames) |
| **Spurious Detection** | Eifel/F-RTO/D-SACK (ядро) | Приложение знает все отправленные пакеты |
| **Адаптация RTO** | Медленная (SRTT/RTTVAR через ядро) | Быстрая (приложение видит все acks) |
| **Pacing** | Ограничено (fq qdisc) | Встроен (QUIC Pacing) |
| **0-RTT** | Невозможен | Возможен (early data) |

---

## Диагностика

### Инструменты

| Инструмент | Назначение | Пример |
| :--- | :--- | :--- |
| `ss -ti` | Состояние соединения (cwnd, retrans, rto, backoff) | `ss -ti dst 8.8.8.8` |
| `nstat` | Глобальные счетчики SNMP (ретрансмиссии, ошибки) | `nstat -az \| grep -i retrans` |
| `tcpretrans` (eBPF) | Трассировка каждой ретрансмиссии в реальном времени | `sudo tcpretrans` |
| `tcpdrop` (eBPF) | Отслеживание отбрасывания пакетов ядром | `sudo tcpdrop` |
| `tshark` | Анализ дампов (фильтры по типам ретрансмиссий) | `tshark -r cap.pcap -Y "tcp.analysis.retransmission"` |
| `ethtool -S` | Статистика NIC (ошибки L1/L2) | `ethtool -S eth0 \| grep -i error` |

### Быстрый старт

```bash
# 1. Проверка глобальной статистики
nstat -az | grep -E 'TcpRetransSegs|TcpOutSegs|TcpExtTCPTimeouts|TcpExtTCPFastRetrans|TcpExtTCPTailLossProbe'

# 2. Проверка конкретного соединения
ss -ti dst 8.8.8.8

# 3. Трассировка в реальном времени
sudo tcpretrans -L $(whoami | awk '{print $1}')

# 4. Анализ дампа
tshark -r capture.pcap -Y "tcp.analysis.retransmission" -T fields -e frame.time -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport
```

> **См. также:** [Диагностика надежности](./diagnostics.md) — полный каталог счетчиков `nstat`, eBPF-инструменты, tcpdump/tshark фильтры, Prometheus/Grafana алерты.

---

## Дополнительная информация

### См. также
- **[Подтверждения (ACK)](./acknowledgments.md):** Работа DupACK и роль SACK в восстановлении.
- **[Диагностика надежности](./diagnostics.md):** Мониторинг счетчиков ретрансмиссий через `nstat`, eBPF, tcpdump, Prometheus.
- **[Управление перегрузкой](../congestion/tcp_congestion_control_overview.md):** Поведение окна в фазах Recovery.
- **[Контрольная сумма](./checksum.md):** Silent Drop → RTO цепочка.
- **[Порядковые номера](./sequence_numbers.md):** PAWS, wrap-around.
- **[Концепции надежности](./concepts.md):** Архитектура механизмов, QUIC comparison.
- **[Диагностика TCP-соединений](../connection/tcp_connection_diagnostics.md):** Анализ состояний соединений.
- **[NIC Offloading](../connection/tcp_data_transfer.md):** TSO/GRO/GSO и их влияние на анализ.

### Стандарты (RFC)
- **RFC 9293:** Transmission Control Protocol (2022).
- **RFC 6298:** Computing TCP's Retransmission Timer.
- **RFC 5681:** TCP Congestion Control.
- **RFC 2582:** NewReno Modification to Fast Recovery.
- **RFC 6675:** SACK-based Loss Recovery (Conservative Loss Recovery).
- **RFC 8985:** The TCP RACK-TLP Loss Detection Algorithm.
- **RFC 3522:** The Eifel Detection Algorithm for TCP.
- **RFC 4653:** F-RTO: Forward RTO-Recovery.
- **RFC 2883:** An Extension to SACK (D-SACK).
