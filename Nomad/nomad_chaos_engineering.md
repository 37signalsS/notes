# Nomad — Chaos Engineering

## Определения

**Chaos Engineering для Nomad** — практика контролируемого внесения сбоев в Nomad-кластер для проверки устойчивости приложений и инфраструктуры: убийство аллокаций, drain узлов, сетевые partition, перегрузка ресурсов.

**Blast Radius** — область воздействия эксперимента (одна аллокация, один узел, весь кластер).

**Steady State Hypothesis** — гипотеза о нормальном поведении системы, проверяемая во время эксперимента (доступность сервиса, latency, error rate).

**Game Day** — запланированный эксперимент по хаос-инжинирингу с участием команды.

## Основные концепции

### Области хаос-тестирования в Nomad

| Уровень | Сбои | Инструменты |
| :--- | :--- | :--- |
| **Задача** | Убийство процесса, OOM | `nomad alloc stop`, `kill` |
| **Аллокация** | Перезапуск, остановка | `nomad alloc signal`, `nomad alloc stop` |
| **Узел** | Drain, исключение из кластера | `nomad node drain`, `nomad node eligibility` |
| **Сеть** | Задержки, потери, partition | `tc netem`, `iptables` |
| **Ресурсы** | CPU starvation, disk pressure | `stress-ng`, `fio` |
| **Сервис** | Потеря зависимостей | Убийство Consul/Vault агента |

### Принципы безопасности

1. Начинайте с минимального Blast Radius (одна аллокация).
2. Останавливайте эксперимент при критической деградации.
3. Проводите Game Day только в staging/dev среде.
4. Убедитесь в наличии backup и rollback-процедур.
5. Мониторинг должен быть настроен ДО эксперимента.

## Практические сценарии

### Сценарий 1: Убийство аллокации

```bash
# Найти аллокацию
nomad job status webapp

# Остановить аллокацию
nomad alloc stop <alloc-id>

# Проверить, что Nomad перезапустил задачу
nomad alloc status <new-alloc-id>
# → Task "server" should be "running"
```

**Гипотеза:** После убийства аллокации Nomad перезапустит задачу на том же или другом узле в течение 30 секунд.

### Сценарий 2: Drain узла под нагрузкой

```bash
# Запуск нагрузки (в другом терминале)
hey -z 5m -c 10 http://webapp.service.consul/api

# Drain узла с коротким дедлайном
nomad node drain -enable <node-id> -deadline="2m"

# Мониторинг
watch nomad node status <node-id>
# → Allocations moving from draining to new node

# Проверка доступности сервиса во время drain
curl -s http://webapp.service.consul/api/health
# → Should return 200 throughout
```

### Сценарий 3: Сетевые задержки (tc netem)

```bash
# На Nomad-клиенте: добавление задержки 200ms к исходящему трафику
sudo tc qdisc add dev eth0 root netem delay 200ms 50ms

# Проверка
ping webapp.service.consul
# → RTT should increase

# Удаление
sudo tc qdisc del dev eth0 root
```

### Сценарий 4: Потеря связи с Consul

```bash
# Остановка Consul-агента на клиенте
sudo systemctl stop consul

# Проверка: Nomad должен продолжать работать с кэшированными данными
nomad job status webapp
# → Should show running allocations

# Восстановление
sudo systemctl start consul
```

### Сценарий 5: Исчерпание ресурсов (Disk Pressure)

```bash
# Заполнение диска
dd if=/dev/zero of=/opt/nomad/data/fill bs=1M count=10000

# Проверка: Nomad должен mark allocations как unhealthy
nomad node status <node-id>
# → Disk pressure warning

# Очистка
rm /opt/nomad/data/fill
```

### Сценарий 6: Игровой день (Game Day)

**Чеклист Game Day:**

```
1. Определить цель эксперимента
   - Что проверяем? (resilience, recovery time, monitoring)

2. Подготовить среду
   - Staging/dev кластер
   - Мониторинг настроен (Prometheus, Grafana)
   - Backup создан

3. Определить Blast Radius
   - Какие сервисы затронуты?
   - Есть ли dependent services?

4. Зафиксировать Steady State
   - Запросы в секунду: X
   - Latency P99: Y ms
   - Error rate: Z%

5. Внести сбой
   - Описать что делаем
   - Запустить эксперимент

6. Наблюдать
   - Мониторинг в реальном времени
   - Сравнить с steady state

7. Восстановить
   - Убрать сбой
   - Проверить восстановление

8. Задокументировать
   - Результаты
   - Улучшения
   - Следующие эксперименты
```

## Метрики для оценки устойчивости

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Recovery Time** | Время восстановления после сбоя | < 30 секунд |
| **Error Rate** | Доля ошибок во время сбоя | < 5% |
| **Data Loss** | Потеря данных | 0 |
| **Cascading Failures** | Каскадные сбои | Отсутствуют |

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Service unavailable | Все аллокации убиты одновременно | Убивайте по одной |
| Data loss | Нет persistent storage | Используйте CSI volumes |
| Monitoring gap | Алерты не настроены | Настройте alerting ДО эксперимента |

## Дополнительная информация

- [Chaos Engineering: Обзор](../Chaos_Engineering/chaos_engineering_overview.md) — теория.
- [Chaos Engineering: Инструменты](../Chaos_Engineering/chaos_engineering_tools.md) — Chaos Mesh, Litmus.
- [Nomad — мониторинг](./nomad_monitoring.md) — настройка observability.
- [Nomad — диагностика](./practical_scenarios.md#диагностика-и-устранение-неисправностей) — troubleshooting.
