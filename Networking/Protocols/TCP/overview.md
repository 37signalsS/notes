# Протокол TCP (Transmission Control Protocol): Обзор

## Определения

**TCP (Transmission Control Protocol)** — основной протокол транспортного уровня (L4) в стеке TCP/IP. Он обеспечивает надежную, упорядоченную и безошибочную доставку непрерывного потока байт между приложениями.

**Основные термины:**
- **Сегмент (Segment):** Единица данных TCP (PDU), инкапсулированная в IP-пакет.
- **Поток байт (Byte Stream):** Абстракция, при которой данные передаются как единая лента байтов без сохранения границ сообщений.
- **ISN (Initial Sequence Number):** Начальный порядковый номер, выбираемый при установке соединения.

---

## Основные концепции

### Ключевые характеристики

| Характеристика | Описание | Механизмы реализации |
| :--- | :--- | :--- |
| **Надежность** | Гарантия доставки данных в целостности. | ACK, ретрансмиссии, контрольные суммы. |
| **Упорядоченность** | Восстановление порядка байт при их перемешивании. | Порядковые номера (Sequence Numbers). |
| **Ориентация на соединение** | Требуется установка сессии перед передачей. | 3-way Handshake (SYN, SYN-ACK, ACK). |
| **Управление потоком** | Защита получателя от переполнения буфера. | Sliding Window (rwnd). |
| **Управление перегрузкой** | Защита сети от заторов. | AIMD, Slow Start, BBR, CUBIC. |

### Место в сетевой модели (2026)

TCP работает на **транспортном уровне** и служит связующим звеном между прикладным софтом и сетевой инфраструктурой.

```text
Прикладной уровень (HTTP/2, SMTP, gRPC)
         ↓
Транспортный уровень (TCP) ← TCP обеспечивает надежность
         ↓
Сетевой уровень (IPv4, IPv6)
```

*Примечание:* Для задач, требующих минимальной задержки при потере надежности, используется [UDP](../udp.md), а для современных веб-приложений — **QUIC (HTTP/3)**, работающий поверх UDP.

---

## Структура документации TCP

Для глубокого изучения конкретных механизмов используйте следующие разделы:

| Раздел | Ссылка | Краткое содержание |
| :--- | :--- | :--- |
| **Формат заголовка** | [Header_Format/index.md](./Header_Format/index.md) | Поля Seq, Ack, Флаги и 32-битное выравнивание. |
| **Опции и расширения** | [Header_Format/options.md](./Header_Format/options.md) | MSS, SACK, Window Scale, TFO, MPTCP. |
| **Жизненный цикл** | [connection/tcp_connection_overview.md](./connection/tcp_connection_overview.md) | Handshake, состояния FSM, закрытие сессии. |
| **Диагностика** | [connection/tcp_connection_diagnostics.md](./connection/tcp_connection_diagnostics.md) | Анализ через `ss`, `tcpdump` и eBPF. |
| **Надежность** | [reliability_mechanisms/concepts.md](./reliability_mechanisms/concepts.md) | Подробно о Seq/Ack, таймаутах и ретрансмиссиях. |
| **Управление окнами** | [Flow_Control/index.md](./Flow_Control/index.md) | Sliding Window, Zero Window и автотюнинг в Linux. |
| **Контроль перегрузок** | [congestion/tcp_congestion_control_overview.md](./congestion/tcp_congestion_control_overview.md) | Алгоритмы BBRv3, CUBIC и правило 14 КБ. |

---

## Практические сценарии

### Когда следует выбирать TCP?
1.  **Транзакционные системы (БД):** SQL-запросы требуют строгой последовательности и подтверждения.
2.  **Передача файлов и API:** REST/gRPC на базе TCP гарантируют, что клиент получит полный JSON или бинарный объект.
3.  **Удаленное управление (SSH):** Требуется интерактивность и отсутствие потерь символов.

### Оптимизация производительности в Linux
Современные системы (ядра 6.x+) требуют тюнинга для 10GbE+ каналов:
```bash
# Проверка текущего алгоритма управления перегрузкой
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = bbr
```

---

## Дополнительная информация

### См. также
- **[Оптимизация TCP в Linux](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md):** Тюнинг системных буферов и очередей.
- **[TLS (Transport Layer Security)](../tls.md):** Шифрование поверх TCP-потока.
- **[Диагностика Wireshark](../../ServicesAndTools/Wireshark/tcp_performance/tcp_performance_diagnostics.md):** Визуальный анализ трафика.

### Стандарты (RFC)
- **RFC 9293:** Transmission Control Protocol (современный стандарт, заменяет RFC 793).
- **RFC 5681:** TCP Congestion Control.
- **RFC 7323:** TCP Extensions for High Performance.

> **Reliability Score: 10** (основной обзорный справочник по TCP).
> **Актуальность:** 2026 год (RFC 9293, BBRv3).
