# Диагностика проблем производительности клиента TCP

## Сценарий 2: Тормозит клиент

**Симптомы:**

- Большой RTT (миллисекунды вместо микросекунд)
- Уменьшение Window Size со стороны клиента
- События **TCP Zero Window** или **TCP Window Full**

### Диагностика

#### 1. Проверить Expert Information

```
Analyze → Expert Information → Искать "tcp 0 window"
```

#### 2. Анализ Window Size

- Добавить столбец `Calculated Window Size`
- Отследить уменьшение окна от клиента:

  ```
  64KB → 46KB → 32KB → 19KB → 0KB (Zero Window)
  ```

#### 3. График Window Scaling

```
Statistics → TCP Stream Graphs → Window Scaling
```

- Зелёная линия — размер окна клиента
- Резкое падение до 0 → клиент не успевает обрабатывать

#### 4. Проверить Bytes in Flight

- Рост до границы окна → остановка
- Клиент не подтверждает → буфер заполнен

### Причины

| Причина | Описание |
| :--- | :--- |
| **Приложение не успевает** | Не читает данные из сокета достаточно быстро |
| **CPU клиента загружен** | Нехватка процессорного времени на обработку |
| **Недостаточный буфер** | Малый размер `SO_RCVBUF` |

### Пример диагностики

```
Сервер отправляет 14KB → Клиент подтверждает через 18μs
Сервер отправляет ещё 14KB → Окно клиента: 89KB → 76KB
...
Сервер отправляет 19KB → Клиент: Window = 19KB (Window Full)
Пауза 32ms → Клиент: Window = 0 (Zero Window)
Пауза 20ms → Клиент: Window = 93KB (освободил буфер)
```

### Решение

**Увеличить буфер приема:**

```bash
# Проверка текущих значений
sysctl net.ipv4.tcp_rmem
sysctl net.core.rmem_max

# Увеличение буфера
sysctl -w net.ipv4.tcp_rmem='4096 87380 16777216'
sysctl -w net.core.rmem_max=16777216

# Для постоянного применения добавить в /etc/sysctl.conf
```

**Настройка приложения:**

```python
# Python пример увеличения буфера
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024)
```

---

## Связанные документы

- **[Обзор диагностики](./tcp_performance_diagnostics.md)** — базовые концепции
- **[Диагностика проблем сервера](./tcp_server_performance_issues.md)** — проблемы на стороне сервера
- **[Потери в сети](./tcp_network_losses_and_offloading.md)** — диагностика сетевых проблем
- **[Оптимизация TCP в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — настройка параметров
