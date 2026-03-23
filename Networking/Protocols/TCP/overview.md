# Протокол TCP (Transmission Control Protocol): Обзор

## Определения

**TCP (Transmission Control Protocol)** — основной протокол транспортного уровня (L4) в стеке TCP/IP, обеспечивающий **надежную передачу потока байт** между приложениями.

### Сервисная модель: надежный поток байт

В отличие от [UDP](../udp.md), TCP предоставляет сервис **надежной передачи потока байт (reliable byte stream)**:

1. Отправитель передает непрерывный поток данных
2. TCP разделяет поток на **сегменты** и отправляет по сети
3. Получатель собирает сегменты, восстанавливает поток и передает приложению

**Результат:** получатель получает тот же поток байт без искажений, потерь и в правильном порядке.

---

## Основные концепции

### Ключевые характеристики

| Характеристика | Описание | Реализация |
| :--- | :--- | :--- |
| **Надежность** | Гарантирует доставку данных | ACK, retransmission |
| **Упорядоченность** | Данные получаются в порядке отправки | Sequence Numbers |
| **Ориентация на соединение** | Требуется установка соединения | Handshake |
| **Управление потоком** | Защита буфера получателя от переполнения | Window (Flow Control) |
| **Управление перегрузкой** | Адаптация к пропускной способности сети | Congestion Control |

### Заголовок TCP

**Структура заголовка:**

- **Минимальный размер:** 20 байт (без опций)
- **Максимальный размер:** 60 байт (с опциями)

**Основные поля:**

| Поле | Размер | Описание |
| :--- | :--- | :--- |
| **Source/Destination Port** | 16 бит | Порт источника и получателя |
| **Sequence Number** | 32 бита | Номер первого байта данных в сегменте |
| **Acknowledgment Number** | 32 бита | Номер следующего ожидаемого байта |
| **Флаги (URG, ACK, PSH, RST, SYN, FIN)** | 6 бит | Тип пакета (SYN — установка, ACK — подтверждение, FIN — завершение) |
| **Window** | 16 бит | Размер свободного буфера получателя (управление потоком) |
| **Checksum** | 16 бит | Контрольная сумма для обнаружения повреждений |
| **Options** | переменная | Дополнительные опции (MSS, Window Scale, SACK, Timestamps) |

**Флаги TCP:**

- **SYN** — синхронизация, установка соединения
- **ACK** — подтверждение получения
- **FIN** — завершение соединения
- **RST** — немедленный сброс соединения
- **PSH** — немедленная доставка данных приложению
- **URG** — срочные данные (устарел)

**Подробнее:** [Формат заголовка TCP](./Header_Format/index.md)

### Место в стеке TCP/IP

TCP работает на **транспортном уровне** модели [TCP/IP](../../OSI_TCP_IP_Model/tcp_ip_model.md):

```
Прикладной уровень (HTTP, DNS, SMTP)
         ↓
Транспортный уровень (TCP / UDP) ← TCP здесь
         ↓
Сетевой уровень (IP)
         ↓
Канальный уровень (Ethernet, Wi-Fi)
```

### Сравнение TCP и UDP

| Критерий | TCP | [UDP](../udp.md) |
| :--- | :--- | :--- |
| Надежность | Да (ACK, retransmission) | Нет |
| Упорядоченность | Да | Нет |
| Соединение | Требуется (handshake) | Не требуется |
| Контроль перегрузки | Да | Нет |
| Задержка | Выше (из-за handshake) | Ниже |
| Use cases | Web, email, файлы | DNS, VoIP, стриминг |

---

## Практические сценарии

### Когда использовать TCP

- **Веб-трафик (HTTP/HTTPS)** — требуется надежная доставка HTML, CSS, JS
- **Электронная почта (SMTP, IMAP)** — важна целостность сообщений
- **Передача файлов (FTP, SFTP)** — критична полная доставка без потерь
- **Базы данных** — запросы и результаты должны доставляться полностью

### Когда использовать UDP

- **DNS-запросы** — один запрос/ответ, важна скорость
- **VoIP и видеоконференции** — допустимы потери, критична задержка
- **Онлайн-игры** — минимальная латентность важнее потерь
- **Стриминг** — буферизация компенсирует потери

---

## Дополнительная информация

### Структура документации TCP

| Раздел | Файл | Описание |
| :--- | :--- | :--- |
| **Заголовок** | [Header_Format/index.md](./Header_Format/index.md) | Структура заголовка, поля, флаги |
| **Опции** | [Header_Format/options.md](./Header_Format/options.md) | MSS, Window Scale, SACK, Timestamps |
| **Handshake** | [connection/tcp_connection_management_overview.md](./connection/tcp_connection_management_overview.md) | Установка соединения (3-way handshake) |
| **Состояния** | [connection/tcp_connection_states.md](./connection/tcp_connection_states.md) | 11 состояний TCP, диагностика |
| **Завершение** | [connection/tcp_connection_termination.md](./connection/tcp_connection_termination.md) | Четырёхэтапное завершение |
| **Надежность** | [reliability_mechanisms/](./reliability_mechanisms/) | Sequence Numbers, ACK, retransmission |
| **Управление потоком** | [Flow_Control/](./Flow_Control/) | Window, receiver window |
| **Перегрузка** | [congestion/tcp_congestion_control_overview.md](./congestion/tcp_congestion_control_overview.md) | cwnd, BBR, CUBIC |

### Связанные темы

- **[TLS](../tls.md)** — шифрование поверх TCP (HTTPS = HTTP + TLS + TCP)
- **[Оптимизация TCP в Linux](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — sysctl-параметры, BBR, initcwnd
- **[tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)** — анализ TCP-трафика
- **[Wireshark: Диагностика производительности](../../ServicesAndTools/Wireshark/tcp_performance/tcp_performance_diagnostics.md)** — анализ узких мест через Wireshark
- **[SYN-флуд](../../Concepts/dos_ddos_overview.md#syn-флуд)** — DDoS-атака на TCP-handshake

### RFC и стандарты

- **RFC 793** — базовая спецификация TCP (1981)
- **RFC 5681** — управление перегрузкой (2009)
- **RFC 7323** — window scaling, timestamps (2014)
- **RFC 6675** — SACK-based loss recovery (2012)
