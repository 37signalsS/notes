# Алгоритмы управления перегрузкой TCP

## Определения

**Алгоритм congestion control** — конкретная реализация логики управления окном перегрузки (`cwnd`) в TCP. Определяет, как отправитель реагирует на сигналы перегрузки (потери пакетов, рост задержки, явные уведомления ECN).

**Ключевые подходы:**

- **Loss-based (Reno, CUBIC):** реагируют на потерю пакетов как сигнал перегрузки
- **Delay-based (Vegas, BBR):** измеряют задержку и пропускную способность для проактивного обнаружения

**SSoT:** базовые концепции Slow Start, AIMD, Fast Recovery — в [`tcp_congestion_control_overview.md`](./tcp_congestion_control_overview.md).

---

## Основные концепции

### Эволюция алгоритмов

| Поколение | Алгоритмы | Сигнал перегрузки | Год |
| :--- | :--- | :--- | :--- |
| **1-е (классические)** | Tahoe, Reno, NewReno | Потеря пакетов (RTO/DupACK) | 1988–2003 |
| **2-е (гибридные)** | CUBIC, HTCP | Потеря + время с последней потери | 2004–2015 |
| **3-е (модельные)** | BBR, Vegas | Пропускная способность + RTT | 2016+ |

### CUBIC (по умолчанию в Linux, FreeBSD 14+, Windows Vista+)

**Особенности:**

- Алгоритм по умолчанию в Linux, FreeBSD (с 14.x), Windows (с Vista)
- Функция роста зависит от **времени с момента последней потери**
- Агрессивнее AIMD на каналах с большим BDP (Bandwidth-Delay Product)

**Формула роста:**

```
W(t) = C × (t - K)³ + W_max

где:
  t — время с момента последней потери
  K — время до достижения W_max
  W_max — cwnd перед последней потерей
  C — константа масштабирования (по умолчанию 0.4)
```

**Преимущества:**

- Высокая утилизация каналов с большим BDP
- Стабильность в гетерогенных сетях
- Справедливое распределение пропускной способности (fairness)

**Недостатки:**

- Может создавать очереди в буферах маршрутизаторов (bufferbloat)
- Менее эффективен в мобильных сетях с переменными потерями

### BBR (Bottleneck Bandwidth and Round-trip time)

**Разработчик:** Google (2016)

**Принцип:** строит модель сети на основе **пропускной способности** и **RTT**, а не реагирует на потери.

**Ключевое отличие от loss-based алгоритмов:**

| Подход | Логика | Проблема |
| :--- | :--- | :--- |
| **Reno/CUBIC (loss-based)** | Потеря = перегрузка → уменьшаем cwnd | Ложные потери в WiFi/мобильных сетях |
| **BBR (model-based)** | Измеряет реальную пропускную способность и RTT | Требует accurate измерений |

**Ключевые метрики:**

- **BDP (Bandwidth-Delay Product):** `max_bandwidth × min_rtt`
- **Target cwnd:** `BDP × gain_factor`

**Фазы работы:**

1. **Startup:** агрессивный рост (аналог Slow Start, но быстрее) — поиск максимальной пропускной способности
2. **Drain:** очистка очереди, если была создана в Startup
3. **ProbeBW:** циклическое изменение скорости для поиска оптимума (pacing rate ±25%)
4. **ProbeRTT:** периодическое снижение cwnd для измерения min_rtt (каждые ~10 сек)

**Преимущества BBR:**

- Эффективная работа в сетях с высокой задержкой (LDN — Long Distance Networks)
- Устойчивость к переменной пропускной способности (мобильные сети, WiFi)
- Минимизация bufferbloat (не создаёт излишних очередей в буферах)
- Лучшая утилизация каналов с большим BDP

### Версии BBR

| Версия | Год | Улучшения |
| :--- | :--- | :--- |
| **BBRv1** | 2016 | Базовая версия |
| **BBRv2** | 2020 | Fairness с CUBIC, поддержка ECN, улучшенная реакция на потери |
| **BBRv3** | 2023 | Дальнейшая оптимизация fairness, улучшенная конвергенция |

**Требования к ядру Linux:**

- Ядро ≥ 4.9 — BBRv1 (встроен)
- Ядро ≥ 5.19 или 6.1+ (зависит от дистрибутива) — BBRv2/v3

---

## Практические сценарии

### Выбор алгоритма по сценарию

| Сценарий | Рекомендуемый алгоритм | Обоснование |
| :--- | :--- | :--- |
| **Веб-сервер (общий)** | `bbr` | Низкая задержка, хорошая утилизация канала |
| **ЦОД (data center)** | `dctcp` | Оптимизирован для низких задержек, ECN support |
| **Мобильные сети** | `bbr` | Устойчивость к переменным потерям |
| **Высокоскоростные каналы (>1 Гбит/с)** | `bbr` | Лучшая утилизация BDP |
| **Совместимость (старые ядра)** | `cubic` | По умолчанию, стабилен, предсказуем |

### Включение BBR в Linux

```bash
# Проверка доступных алгоритмов
sysctl net.ipv4.tcp_available_congestion_control

# Включение BBR (runtime)
sysctl -w net.ipv4.tcp_congestion_control=bbr

# Постоянная настройка
echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.d/99-bbr.conf

# Для ядра < 4.9 требуется модуль
modprobe tcp_bbr

# Проверка активного алгоритма
sysctl net.ipv4.tcp_congestion_control
ss -ti | grep bbr
```

> **Примечание:** для BBRv2/v3 рекомендуется `net.core.default_qdisc = fq` (детали в [`tcp_congestion_diagnostics.md`](./tcp_congestion_diagnostics.md)).

### Другие алгоритмы

| Алгоритм | Описание | Статус |
| :--- | :--- | :--- |
| **Reno** | Классический AIMD + Fast Recovery | Устарел (исторический) |
| **NewReno** | Улучшенный Fast Recovery (RFC 6582) | Устарел |
| **Vegas** | Измерение задержки для раннего обнаружения перегрузки | Редко используется |
| **Westwood** | Оценка доступной пропускной способности на основе ACK | Мобильные сети (нишевый) |
| **HTCP** | Hamilton TCP, адаптивный для высокоскоростных сетей | Нишевый |
| **DCTCP** | Data Center TCP, для ЦОД с ECN | ЦОД (Facebook, Azure) |

---

## Дополнительная информация

### Связанные документы

- Базовые алгоритмы: Slow Start, AIMD, Fast Recovery — [`tcp_congestion_control_overview.md`](./tcp_congestion_control_overview.md)
- Диагностика и выбор алгоритма: [`tcp_congestion_diagnostics.md`](./tcp_congestion_diagnostics.md)
- Оптимизация initcwnd (правило 14 КБ): [`tcp_initcwnd_and_optimization.md`](./tcp_initcwnd_and_optimization.md)
- Настройка TCP в Linux: [`tcp_tuning_overview.md`](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)
- Алгоритмы в Linux-практике: [`tcp_congestion_algorithms.md`](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_congestion_algorithms.md)

### RFC и стандарты

| RFC | Описание |
| :--- | :--- |
| **RFC 5681** | Congestion Control (Slow Start, AIMD, Fast Recovery) |
| **RFC 6582** | NewReno Fast Recovery |
| **RFC 8312** | CUBIC Congestion Control |
| **RFC 9002** | QUIC Loss Detection and Congestion Control (BBR-like) |
