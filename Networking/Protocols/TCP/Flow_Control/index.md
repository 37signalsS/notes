# Управление потоком в TCP (Flow Control)

## Определения

**Управление потоком (Flow Control)** — механизм TCP, предотвращающий переполнение буфера получателя путём ограничения скорости передачи данных отправителем.

**Ключевое отличие от Congestion Control:**

- **Flow Control:** защита **получателя** (receiver-centric)
- **Congestion Control:** защита **сети** (network-centric)

**Реализация:** поле [Window Size](../header_format.md#7-размер-окна-window-size-16-бит) в заголовке TCP.

---

## Basic Concepts

### Механизм работы

**Принцип:** получатель явно указывает, сколько данных он готов принять.

```
Отправитель                          Получатель
     |                                    |
     |  Данные (1000 байт) -------------> |  Буфер: 4000/5000 байт
     |                                    |  Свободно: 1000 байт
     |  <--- ACK, Window = 1000 --------- |  (указывает свободное место)
     |                                    |
     |  Данные (1000 байт) -------------> |  Буфер: 5000/5000 байт
     |                                    |  Свободно: 0 байт
     |  <--- ACK, Window = 0 ------------ |  (STOP!)
     |                                    |
     |  [Ожидание]                        |  [Чтение приложением]
     |                                    |  Буфер: 3000/5000 байт
     |  <--- ACK, Window = 2000 --------- |  Свободно: 2000 байт
     |                                    |
     |  Данные (2000 байт) -------------> |
```

### Receiver Window (rwnd)

**rwnd (receiver window)** — текущий размер окна, объявленный получателем.

**Формула доступного окна:**

```
Доступное окно = min(cwnd, rwnd)

где:
  cwnd — окно перегрузки (congestion window)
  rwnd — окно получателя (receiver window)
```

**В заголовке TCP:**

- Поле `Window Size` = 16 бит → максимум 65535 байт
- С опцией [Window Scale](../header_format.md#масштаб-окна-window-scale) → до 1 ГБ

---

## Файлы

| Файл | Описание |
|------|----------|
| [mechanisms.md](./mechanisms.md) | Zero Window, Zero-Window Probe, скользящее окно |
| [practical.md](./practical.md) | Диагностика, настройка буферов, Window Scaling в действии |

---

## Additional Information

### Взаимосвязь Flow Control и Congestion Control

**Важно:** это **разные механизмы** с разными целями.

| Характеристика | Flow Control | Congestion Control |
| :--- | :--- | :--- |
| **Цель** | Защита получателя | Защита сети |
| **Параметр** | rwnd (receiver window) | cwnd (congestion window) |
| **Кто контролирует** | Получатель | Отправитель |
| **Причина ограничения** | Мало буфера у получателя | Перегрузка в сети |
| **Механизм** | Window Size в ACK | Алгоритмы (Slow Start, AIMD) |

**Итоговое окно отправки:**

```
Effective Window = min(cwnd, rwnd)
```

**Сценарии:**

| Ситуация | cwnd | rwnd | Effective Window | Ограничитель |
| :--- | :--- | :--- | :--- | :--- |
| Быстрый получатель, свободная сеть | 50000 | 100000 | 50000 | Congestion |
| Медленный получатель, свободная сеть | 50000 | 10000 | 10000 | Flow |
| Быстрый получатель, перегрузка | 5000 | 100000 | 5000 | Congestion |
| Медленный получатель, перегрузка | 5000 | 1000 | 1000 | Flow |

### RFC и стандарты

| RFC | Описание |
| :--- | :--- |
| **RFC 793** | Базовый механизм flow control |
| **RFC 1323** | Window Scaling option |
| **RFC 7323** | Обновление RFC 1323 |

### Связанные темы

- **[Congestion Control](./congestion_control.md)** — управление перегрузкой сети
- **[Header Format](../header_format.md#7-размер-окна-window-size-16-бит)** — поле Window Size
- **[Оптимизация TCP](../../../../Linux/Networking/Concepts/tcp_tuning.md)** — настройка буферов
- **[Wireshark: Диагностика производительности](../../../ServicesAndTools/Wireshark/tcp_performance/tcp_performance_diagnostics.md)** — диагностика Zero Window
