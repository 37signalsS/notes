# Управление TCP-соединением (TCP Connection Management)

## Навигация

**Основная информация:**

- **[tcp_connection_refusal.md](./tcp_connection_refusal.md)** — сценарии отказа, RST, тайм-ауты
- **[tcp_data_transfer.md](./tcp_data_transfer.md)** — передача данных, поток байт, PSH, seq/ack
- **[tcp_connection_termination.md](./tcp_connection_termination.md)** — четырёхэтапное завершение
- **[tcp_connection_states.md](./tcp_connection_states.md)** — полная таблица состояний
- **[tcp_connection_diagnostics.md](./tcp_connection_diagnostics.md)** — практические сценарии

---

## Определения

**Управление соединением (Connection Management)** — механизмы TCP для установки, поддержания и завершения надежного соединения между двумя узлами.

**Ключевые процессы:**

- **Handshake (трёхэтапное рукопожатие)** — установка соединения
- **Data Transfer** — двусторонняя передача данных
- **Termination (четырёхэтапное завершение)** — корректный разрыв соединения

**Состояния соединения:** 11 состояний конечного автомата TCP.

---

## Установка соединения: TCP Handshake

**Цель handshake:**

1. Убедиться, что обе стороны существуют и готовы к обмену данным
2. Согласовать начальные параметры (Sequence Numbers, MSS, Window Scale)
3. Выделить ресурсы (буферы, управляющие структуры)

**Аналогия с телефонным звонком:**

Установка TCP-соединения похожа на звонок по телефону:

- **SYN** — вы набираете номер и слышите гудок
- **SYN-ACK** — абонент поднимает трубку и говорит «Алло»
- **ACK** — вы начинаете разговор

Если абонент не поднимает трубку (нет приложения на порту) — соединение не устанавливается, и нет смысла говорить «в пустоту».

**Процесс:** 3 сегмента (three-way handshake)

```
   Клиент                                     Сервер
     |                                            |
     |  SYN (seq=x) ----------------------------> |  LISTEN
     |      (Состояние: SYN_SENT)                 |      ↓
     |                                            |  SYN-RCVD
     |  <---------------------------- SYN-ACK ----|
     |           (seq=y, ack=x+1)                 |
     |                                            |
     |  ACK (seq=x+1, ack=y+1) -----------------> |
     |      (Состояние: ESTABLISHED)              |  (Состояние: ESTABLISHED)
     |                                            |
     |◄══════════ Передача данных ══════════════►|
```

### Детальный алгоритм

#### Шаг 1: SYN от клиента

| Параметр | Значение |
| :--- | :--- |
| **Флаги** | `SYN=1` |
| **Sequence Number** | `seq=x` (случайный ISN) |
| **Опции** | MSS, Window Scale, SACK permitted, Timestamps |
| **Состояние клиента** | `SYN_SENT` |

**Назначение:** инициация соединения, отправка клиентских параметров.

---

#### Шаг 2: SYN-ACK от сервера

| Параметр | Значение |
| :--- | :--- |
| **Флаги** | `SYN=1, ACK=1` |
| **Sequence Number** | `seq=y` (случайный ISN сервера) |
| **Acknowledgment Number** | `ack=x+1` (подтверждение SYN клиента) |
| **Опции** | MSS, Window Scale, SACK permitted, Timestamps |
| **Состояние сервера** | `SYN_RECEIVED` |

**Варианты реакции сервера:**

| Ситуация | Реакция |
| :--- | :--- |
| **Порт открыт, ресурсы есть** | Отправить `SYN-ACK`, перейти в `SYN_RECEIVED` |
| **Порт закрыт** | Отправить `RST` |
| **Нет ресурсов** | Отправить `RST` или игнорировать |
| **SYN-cookie включен** | Отправить `SYN-ACK` без выделения памяти |

---

#### Шаг 3: ACK от клиента

| Параметр | Значение |
| :--- | :--- |
| **Флаги** | `ACK=1` |
| **Sequence Number** | `seq=x+1` |
| **Acknowledgment Number** | `ack=y+1` (подтверждение SYN сервера) |
| **Состояние клиента** | `ESTABLISHED` |

**Реакция сервера:**

- Получение `ACK` → переход в `ESTABLISHED`
- Тайм-аут без `ACK` → переход в `CLOSED`, сокет удаляется

---

### Почему 3 этапа, а не 2?

**Проблема 2-этапного handshake:**

```
1. Клиент → SYN → Сервер
2. Сервер → SYN-ACK → Клиент
```

**Недостаток:** сервер не знает, получил ли клиент его `SYN-ACK`. Если `SYN-ACK` потерян, клиент будет ждать вечно, а сервер выделит ресурсы.

**Решение (3 этапа):**

- Третий `ACK` подтверждает, что клиент получил `SYN-ACK`
- Обе стороны уверены в готовности к передаче данных

## Связанные документы

**Детальное описание:**

- **[Отказ в установке соединения](./tcp_connection_refusal.md)** — сценарии отказа, RST, тайм-ауты
- **[Передача данных](./tcp_data_transfer.md)** — поток байт, PSH, seq/ack
- **[Завершение соединения](./tcp_connection_termination.md)** — четырёхэтапное завершение
- **[Состояния TCP](./tcp_connection_states.md)** — полная таблица состояний

**Протоколы:**

- **[Флаги TCP](../Header_Format/index.md)** — SYN, FIN, ACK, RST
- **[Sequence Numbers](../reliability_mechanisms/sequence_numbers.md)** — нумерация байт
- **[Acknowledgments](../reliability_mechanisms/acknowledgments.md)** — подтверждения

**Оптимизация:**

- **[TCP tuning](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — управление параметрами
- **[TCP Fast Open](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_fast_open.md)** — сокращение handshake до 1 RTT
- **[TIME_WAIT](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_timewait.md)** — управление состоянием TIME_WAIT
- **[TLS Handshake](../../tls.md#упрощённый-tls-12-handshake-2-rtt)** — TLS 1.2 (2-RTT) и **[TLS 1.3](../../tls.md#упрощённый-tls-13-handshake-1-rtt)** (1-RTT) поверх TCP-handshake

## RFC

- **RFC 793** — Базовая спецификация TCP, состояния
- **RFC 7323** — Window Scale, Timestamps
- **RFC 6298** — RTO (Retransmission Timeout) calculation
