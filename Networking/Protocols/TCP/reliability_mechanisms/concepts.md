# Механизмы надежности TCP — Концепции

## Определения

**Надежность TCP** — гарантия доставки данных без потерь, дублирования и нарушений порядка, несмотря на ненадежность базовой сети.

**Ключевые механизмы:**

* **Sequence Numbers** — нумерация байт для упорядочивания
* **Acknowledgments (ACK)** — подтверждения получения
* **Retransmission** — повторная передача при потерях
* **Checksum** — контроль целостности

## Основные компоненты надежности

### 1. Нумерация последовательности (Sequence Numbers)

TCP нумерует **байты**, а не сегменты.

**Initial Sequence Number (ISN):**

* Случайное 32-битное число при установке соединения
* Защищает от старых дубликатов сегментов
* Обменивается в [handshake](./connection_management.md#установка-соединения-tcp-handshake)

**Назначение:**

* Восстановление порядка (reordering)
* Обнаружение дубликатов
* Точное подтверждение полученных данных

**Подробнее:** [Sequence Numbers](sequence_numbers.md)

### 2. Подтверждения (Acknowledgments)

**Типы подтверждений:**

#### Кумулятивное подтверждение (Cumulative ACK)

ACK подтверждает **все байты до указанного номера**.

**Преимущество:** простой механизм, меньше служебного трафика.

**Недостаток:** при потере одного сегмента отправитель не знает о полученных после него.

#### Выборочное подтверждение (Selective Acknowledgment, SACK)

Получатель явно указывает полученные блоки данных.

**Преимущество:** точная ретрансмиссия только потерянных сегментов.

**Опция TCP:** [SACK в заголовке](./header_format.md#выборочное-подтверждение-selective-acknowledgment-sack)

**Подробнее:** [Acknowledgments](acknowledgments.md)

### 3. Повторная передача (Retransmission)

**Триггеры ретрансмиссии:**

#### Тайм-аут (RTO — Retransmission Timeout)

1. Отправка сегмента → запуск таймера
2. Если ACK не получен до истечения RTO → ретрансмиссия
3. RTO удваивается после каждой ретрансмиссии (exponential backoff)

**Расчет RTO (RFC 6298):**

```
SRTT (Smoothed RTT) = (1 - α) × SRTT + α × RTT
RTTVAR (RTT Variance) = (1 - β) × RTTVAR + β × |SRTT - RTT|
RTO = SRTT + max(4, 4 × RTTVAR)

где:
  α = 1/8 (сглаживание SRTT)
  β = 1/4 (сглаживание RTTVAR)
  Начальное RTO = 1 секунда
```

#### Быстрая ретрансмиссия (Fast Retransmit)

**Триггер:** получение **3 дубликатов ACK** (DupACK).

**Преимущество перед RTO:**

* Быстрее (не нужно ждать тайм-аут)
* Выше пропускная способность

**Подробнее:** [Retransmission](retransmission.md)

### 4. Скользящее окно (Sliding Window)

**Концепция:** отправитель может передавать несколько сегментов без ожидания ACK.

**Параметры:**

```
LastByteAcked — последний подтвержденный байт
LastByteSent  — последний отправленный байт
LastByteWritten — последний записанный в сокет байт

Effective Window = LastByteAcked + Window - LastByteSent
```

**Ограничения:**

```
LastByteSent - LastByteAcked ≤ cwnd (congestion window)
LastByteSent - LastByteAcked ≤ rwnd (receiver window)
```

**Подробнее:** [Sliding Window](sliding_window.md)

### 5. Контрольная сумма (Checksum)

**Назначение:** обнаружение ошибок в заголовке и данных.

**Особенности:**

* Обязательно для TCP (в отличие от UDP)
* Включает **pseudo-header** (IP-адреса, протокол, длина)
* Если ошибка — сегмент отбрасывается без ACK

**Подробнее:** [Checksum](checksum.md)

## Взаимодействие с Congestion Control

**Потеря пакета → реакция:**

| Механизм обнаружения | Действие cwnd | Алгоритм |
| :--- | :--- | :--- |
| **3 DupACK (Fast Retransmit)** | `cwnd = cwnd / 2` | Fast Recovery |
| **RTO (тайм-аут)** | `cwnd = 1 MSS` | Slow Start |

**Важно:** RTO — более серьезное событие, означает значительную перегрузку или потерю связи.

**Подробнее:** [Congestion Control](./congestion_control.md)

## Диагностика

### Мониторинг ретрансмиссий

```bash
# Статистика TCP
netstat -s | grep -i retrans

# Детальная информация о сокетах
ss -tmo
```

**Подробнее:** [Диагностика](./reliability_mechanisms/diagnostics.md)

## Связанные темы

* **[Header Format](./header_format.md)** — поля Sequence Number, ACK
* **[Connection Management](./connection_management.md)** — handshake, состояния
* **[Congestion Control](./congestion_control.md)** — управление перегрузкой
* **[tcpdump](../../../../Linux/Diagnostics/Networking/tcpdump.md)** — анализ трафика

## RFC и стандарты

| RFC | Описание |
| :--- | :--- |
| **RFC 793** | Базовая спецификация TCP, Sequence Numbers, ACK |
| **RFC 6298** | Расчет RTO (Retransmission Timeout) |
| **RFC 2018** | SACK (Selective Acknowledgment) |
| **RFC 6675** | SACK-based loss recovery |
| **RFC 7323** | Timestamps для точного RTT |
