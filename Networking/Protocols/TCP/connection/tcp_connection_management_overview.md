# Управление TCP-соединением — Обзор

> **Примечание:** Этот файл был декомпозирован на тематические заметки. Актуальная информация находится в директории **[connection/](./connection/)**.

## Навигация

- **[connection/tcp_connection_overview.md](./connection/tcp_connection_overview.md)** — определения, handshake, состояния
- **[connection/tcp_connection_refusal.md](./connection/tcp_connection_refusal.md)** — сценарии отказа, RST, тайм-ауты
- **[connection/tcp_data_transfer.md](./connection/tcp_data_transfer.md)** — передача данных, поток байт, PSH, seq/ack
- **[connection/tcp_connection_termination.md](./connection/tcp_connection_termination.md)** — четырёхэтапное завершение
- **[connection/tcp_connection_states.md](./connection/tcp_connection_states.md)** — полная таблица состояний
- **[connection/tcp_connection_diagnostics.md](./connection/tcp_connection_diagnostics.md)** — практические сценарии

## Краткое описание

**Управление соединением (Connection Management)** — механизмы TCP для установки, поддержания и завершения надежного соединения между двумя узлами.

**Ключевые процессы:**
- **Handshake** — трёхэтапное рукопожатие для установки соединения
- **Data Transfer** — двусторонняя передача данных
- **Termination** — четырёхэтапное завершение соединения

## Связанные документы

- **[Флаги TCP](../Header_Format/index.md)** — SYN, FIN, ACK, RST
- **[Sequence Numbers](../reliability_mechanisms/sequence_numbers.md)** — нумерация байт
- **[Acknowledgments](../reliability_mechanisms/acknowledgments.md)** — подтверждения
- **[TCP Overview](../overview.md)** — общая информация о протоколе

## RFC

- **RFC 793** — Базовая спецификация TCP, состояния
- **RFC 7323** — Window Scale, Timestamps
- **RFC 6298** — RTO (Retransmission Timeout) calculation
