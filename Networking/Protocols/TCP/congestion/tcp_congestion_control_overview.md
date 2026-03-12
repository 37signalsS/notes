# Управление перегрузкой TCP — Обзор и базовые алгоритмы

## Определения

**Congestion Control** — механизм TCP для предотвращения перегрузки сети путём адаптации скорости передачи к доступной пропускной способности канала.

**Ключевое отличие от [Flow Control](./Flow_Control/flow_control.md):**

- **Congestion Control:** защита **сети** (network-centric), параметр `cwnd`
- **Flow Control:** защита **получателя** (receiver-centric), параметр `rwnd`

**Итоговое окно отправки:**

```
Effective Window = min(cwnd, rwnd)
```

---

## Основные концепции

### Окно перегрузки (Congestion Window, cwnd)

**cwnd** — переменная состояния TCP на стороне отправителя, ограничивающая объём данных, которые могут быть отправлены без подтверждения.

**Принцип работы:**

```
Отправитель                          Сеть                           Получатель
     |                                |                                 |
     |  cwnd = 10 MSS                 |  Пропускная способность: ?      |
     |  [Отправка 10 сегментов] ----->|                                 |
     |                                |                                 |
     |  <---- ACK (10 сегментов) -----|                                 |
     |  cwnd = 20 MSS (Slow Start)    |                                 |
     |  [Отправка 20 сегментов] ----->|                                 |
     |                                |                                 |
     |  <---- ACK (потеря 1 пакет) ---|  Перегрузка! Потеря пакета      |
     |  cwnd = 10 MSS (AIMD)          |                                 |
```

**Единицы:** измеряется в **MSS (Maximum Segment Size)**.

---

### Ключевые алгоритмы

#### 1. Медленный старт (Slow Start)

**Цель:** быстро определить доступную пропускную способность при старте соединения.

**Механизм:**

- **Начальное значение:** `initcwnd = 10 MSS` (RFC 5681, ~14.6 КБ)
- **Рост:** экспоненциальный (+1 MSS на каждый ACK)
- **Завершение:** при достижении `ssthresh` или потере пакета

**Динамика роста:**

```
RTT 0:  cwnd = 10 MSS   (отправка 10 сегментов)
RTT 1:  cwnd = 20 MSS   (получено 10 ACK, +10 MSS)
RTT 2:  cwnd = 40 MSS   (получено 20 ACK, +20 MSS)
RTT 3:  cwnd = 80 MSS   (получено 40 ACK, +40 MSS)
...
```

**Почему «медленный»:** название историческое, на самом деле рост быстрый (экспоненциальный).

---

#### 2. Избегание перегрузки (Congestion Avoidance, AIMD)

**AIMD (Additive Increase Multiplicative Decrease)** — алгоритм работы после достижения порога `ssthresh`.

**Механизм:**

- **Additive Increase:** +1 MSS на RTT (линейный рост)
- **Multiplicative Decrease:** при потере пакета `cwnd = cwnd / 2`

**Динамика:**

```
cwnd
  │
  │     ╱│       ╱───
  │    ╱ │      ╱
  │   ╱  │     ╱
  │  ╱   │    ╱
  │ ╱    │   ╱
  │╱     │  ╱
  └──────┴─┴─────────────► время
         │  │
         │  потеря (cwnd/2)
         ssthresh
         (Slow Start → AIMD)
```

**Порог ssthresh (slow start threshold):**

- Начальное значение: обычно 65535 байт
- При потере пакета: `ssthresh = cwnd / 2`

---

#### 3. Быстрое восстановление (Fast Recovery)

**Цель:** избежать полного сброса `cwnd` при единичных потерях.

**Триггер:** получение **3 дубликатов ACK** (DupACK).

**Алгоритм (RFC 5681):**

1. `ssthresh = cwnd / 2`
2. `cwnd = ssthresh + 3 MSS` (учитываем 3 сегмента, вышедшие из сети)
3. Переход в режим Congestion Avoidance (не Slow Start!)
4. При получении ACK для новых данных — выход из Fast Recovery

**Сравнение с тайм-аутом:**

| Событие | Реакция cwnd | Режим после |
| :--- | :--- | :--- |
| **3 DupACK** | `cwnd = cwnd / 2` | Congestion Avoidance |
| **RTO (тайм-аут)** | `cwnd = 1 MSS` | Slow Start |

---

## Дополнительная информация

### RFC и стандарты

| RFC | Описание |
| :--- | :--- |
| **RFC 5681** | Congestion Control (Slow Start, AIMD, Fast Recovery) |
| **RFC 6675** | SACK-based loss recovery |
| **RFC 7323** | Window Scaling, Timestamps |

### Связанные темы

- **[Алгоритмы congestion control](./tcp_congestion_algorithms.md)** — CUBIC, BBR
- **[Оптимизация initcwnd](./tcp_initcwnd_and_optimization.md)** — правило 14 КБ
- **[Диагностика](./tcp_congestion_diagnostics.md)** — практические сценарии
- **[Flow Control](./Flow_Control/flow_control.md)** — управление потоком получателя
- **[Оптимизация TCP](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — практическая настройка

### Формулы

**Bandwidth-Delay Product (BDP):**

```
BDP = Bandwidth × RTT
```

**Требуемое cwnd для полной утилизации:**

```
cwnd ≥ BDP / MSS
```

**Максимальная пропускная способность:**

```
Throughput = (cwnd × MSS) / RTT
```
