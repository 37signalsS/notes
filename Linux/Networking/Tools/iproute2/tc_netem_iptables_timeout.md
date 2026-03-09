# tc netem: эмуляция таймаутов через iptables

## Обзор

Для тестирования обработки таймаутов в распределённых системах `tc netem` недостаточен — требуется эмуляция полного отсутствия ответа (connection timeout) или блокировка на уровне данных (request timeout).

---

## Connection Timeout

### Сценарий

Сервис не отвечает на подключение. Клиент должен корректно обработать таймаут, а не зависнуть.

### DROP — молчаливое отбрасывание

Пакеты просто исчезают, клиент отправляет повторные SYN с экспоненциальным backoff:

```bash
# Блокировка входящих на порт 12345
iptables -A INPUT -p tcp --dport 12345 -j DROP
```

**Поведение клиента:**

- Клиент отправляет SYN-пакеты с увеличивающимся таймаутом (1с, 2с, 4с, 8с...)
- Соединение зависает на этапе handshake
- **Рекомендация:** Использовать `settimeout()` для ограничения времени подключения

**Диагностика:**

```bash
tcpdump -i lo -nn port 12345
# Видны повторные SYN без SYN-ACK в ответ
```

**Удаление правила:**

```bash
iptables -D INPUT -p tcp --dport 12345 -j DROP
# Или удалить все правила: iptables -F
```

> **Docker:** Для блокировки трафика контейнера используйте цепочку `DOCKER-USER`:
>
> ```bash
> iptables -I DOCKER-USER -p tcp -d CONTAINER_IP -j DROP
> ```

---

### REJECT — отклонение с ICMP-сообщением

```bash
iptables -A INPUT -p tcp --dport 12345 -j REJECT
```

**Поведение клиента:**

- Клиент получает ICMP port unreachable
- Ошибка `[Errno 111] Connection refused` через ~1 секунду
- Быстрое завершение без длительных ожиданий

**Диагностика:**

```bash
tcpdump -i lo -nn icmp
# Видны ICMP 127.0.0.1 tcp port 12345 unreachable
```

---

### REJECT with TCP RST

```bash
iptables -A INPUT -p tcp --dport 12345 -j REJECT --reject-with tcp-reset
```

**Поведение клиента:**

- Мгновенное получение RST-пакета
- Ошибка `Connection reset by peer`
- Самый быстрый вариант отказа

---

### REJECT with ICMP host unreachable

```bash
iptables -A INPUT -p tcp --dport 12345 -j REJECT --reject-with icmp-host-unreachable
```

**Поведение клиента:**

- Ошибка `[Errno 113] No route to host`
- Клиент не увеличивает таймаут между попытками

---

## Request Timeout

### Сценарий

Соединение устанавливается, но данные не передаются. Тестирование обработки зависших запросов.

### Фильтр по флагу PSH

Соединение устанавливается (SYN/ACK проходят), но блокируются пакеты с данными (флаг PSH):

```bash
# DROP пакетов с флагом PSH
iptables -A INPUT -p tcp --tcp-flags PSH PSH --dport 12345 -j DROP
```

**Поведение клиента:**

- Handshake проходит успешно
- Клиент не может отправить данные серверу
- Повторные отправки с экспоненциальным backoff

**Диагностика:**

```bash
tcpdump -i lo -nn port 12345
# Видно установленное соединение, но нет ACK на данные
```

---

### REJECT для PSH-пакетов

```bash
# REJECT с ICMP
iptables -A INPUT -p tcp --tcp-flags PSH PSH --dport 12345 -j REJECT

# REJECT с TCP RST
iptables -A INPUT -p tcp --tcp-flags PSH PSH --dport 12345 -j REJECT --reject-with tcp-reset
```

**Поведение при RST:**

- Клиент получает `Connection reset by peer` при установленном соединении
- Непредвиденное закрытие сокета сервером

**Поведение при icmp-host-unreachable:**

- Клиент не увеличивает таймаут между попытками
- Равномерные интервалы между ICMP-сообщениями

---

## Сводная таблица методов эмуляции

| Метод | Команда | Поведение клиента | Время до ошибки |
|-------|---------|-------------------|-----------------|
| **DROP (connection)** | `iptables -A INPUT -p tcp --dport 12345 -j DROP` | Повторные SYN, backoff | 30-120 сек |
| **REJECT (connection)** | `iptables -A INPUT -p tcp --dport 12345 -j REJECT` | ICMP unreachable | ~1 сек |
| **REJECT + RST** | `iptables -A INPUT -p tcp --dport 12345 -j REJECT --reject-with tcp-reset` | RST-пакет | Мгновенно |
| **DROP (request)** | `iptables -A INPUT -p tcp --tcp-flags PSH PSH --dport 12345 -j DROP` | Повторные PSH | 30-120 сек |
| **REJECT + RST (request)** | `iptables -A INPUT -p tcp --tcp-flags PSH PSH --dport 12345 -j REJECT --reject-with tcp-reset` | RST после handshake | Мгновенно |
| **netem delay** | `tc qdisc add dev lo root netem delay 1s` | Задержка всех пакетов | 2-4 сек |
| **netem loss** | `tc qdisc add dev lo root netem loss 50%` | Ретрансмиссии | Нестабильно |

---

## Предупреждения о типовых ошибках

| Ошибка | Последствия | Решение |
|--------|-------------|---------|
| Применение к неправильному интерфейсу | Блокировка SSH-сессии | Использовать `tc qdisc show` для проверки |
| Отсутствие очистки после тестов | Постоянная деградация сети | Всегда выполнять `tc qdisc del` |
| Комбинирование несовместимых параметров | Непредсказуемое поведение | Проверять совместимость параметров |
| Применение на production без тестов | Отказ сервиса | Тестировать на staging-окружении |
| Задержка >1 сек без учёта RTO | Массовые ретрансмиссии | Использовать iptables для таймаутов |

---

## Связанные темы

- **[iptables](../Settings/tools/iptables_basics.md)** — основы файрвола
- **[tc netem основы](./tc_netem_basics.md)** — базовая эмуляция сети
- **[tcpdump](../tcpdump.md)** — диагностика сетевых проблем
