# Application-Level Chaos Engineering

## Определения

**Application-Level Chaos** — направление Chaos Engineering, ориентированное на инъекцию сбоев внутри процесса приложения: исключения в коде, исчерпание пулов потоков и соединений, утечки памяти, CPU starvation на уровне cgroups.

**Exception Injection** — целенаправленное выброс исключения в конкретном методе/классе приложения без изменения кода. Реализуется через Chaosblade (Java/Go/C++), Chaos Monkey for Spring Boot (аннотации), AOP или environment variables.

**Thread Pool Exhaustion** — состояние, при котором все потоки в пуле заняты, новые задачи не могут быть выполнены и накапливаются в очереди. Chaos Engineering проверяет, что приложение возвращает 503 (RejectedExecutionException), а не зависает.

**Connection Pool Exhaustion** — состояние, при котором все соединения с базой данных/внешним сервисом заняты. Проверяется, что приложение возвращает ошибку gracefully, а не блокирует новые запросы.

**Memory Leak Injection** — симутация утечки памяти для проверки работы GC и OOMKilled механизма. Позволяет выявить неэффективный GC, отсутствие лимитов памяти, отсутствие alerting на memory usage.

**CPU Starvation (cgroups)** — ограничение CPU для контейнера/процесса через cgroups v1/v2 для проверки graceful degradation при нехватке вычислений. Используется Chaos Mesh StressChaos или direct cgroups manipulation.

**Latency Injection at Driver Level** — добавление задержки на уровне драйвера базы данных или HTTP-клиента для проверки таймаутов. Используется Toxiproxy или Chaos Mesh IOChaos.

## Основные концепции

### Уровни fault injection

```
L0 — Infrastructure: pod kill, node drain, disk full
L1 — Network: delay, loss, partition (tc, iptables)
L2 — Runtime: CPU hog, memory hog, IO stress
L3 — Application: exception injection, latency injection, thread pool exhaustion
L4 — Kernel: syscall errors, file descriptor exhaustion
```

Application-level chaos работает на уровне L3-L4, воздействуя непосредственно на процесс приложения.

### Методологии инъекции

**Chaosblade (Alibaba):**
- CLI для инъекции сбоев на уровне JVM/Go/C++.
- Поддерживает: throw exception, delay, return null, OOM, CPU load.
- Работает через attach к процессу или через agent.

**Chaos Monkey for Spring Boot:**
- Аннотации для инъекции сбоев в методы.
- Пример: `@ChaosMonkey("latency")` добавляет задержку к методу.

**Custom chaos agent:**
- Внедрение кода через aspect-oriented programming (AOP).
- Или через environment variables: `CHAOS_LATENCY_MS=500`, `CHAOS_EXCEPTION=RuntimeException`.

**cgroups-based starvation:**
- Ограничение CPU/memory через cgroups v2.
- Пример: `echo "50000 100000" > /sys/fs/cgroup/cpu/app.slice/cpu.max` (50% CPU).

### Безопасность application-level chaos

- **Идентификация target:** всегда указывайте точный класс/метод/процесс.
- **Ограничение времени:** `duration=30s`, не бесконечные эксперименты.
- **Emergency stop:** kill -9 процесс, если приложение не recovering.
- **Staging first:** первый эксперимент только в тестовой среде.
- **Observability:** tracing (Jaeger) для отслеживания инъекции.

## Практические сценарии

### Сценарий 1: Exception injection в Java (Chaosblade)

**Цель:** Проверить, что при выбросе `CustomException` в `UserService.getUserInfo` система обрабатывает ошибку корректно.

**Предварительные требования:**

```bash
# Установка Chaosblade
curl -sSL https://chaosblade-oss.alibaba.com/install.sh | bash

# Проверка
blade --version
# → 1.7.0
```

**Инжектируем исключение:**

```bash
# Находим PID Java-приложения
PID=$(jps -l | grep user-service | awk '{print $1}')

# Инжектируем исключение
blade create jvm throwCustomException \
  --exception java.lang.RuntimeException \
  --classname com.example.service.UserService \
  --methodname getUserInfo \
  --pid $PID \
  --duration 60s

# → Success: Create chaosblade by cmd: jvm ...
```

**Наблюдаем:**

```bash
# Приложение должно вернуть 500 или fallback
curl -s http://user-service/api/users/123
# → 500 Internal Server Error (или fallback)

# Проверка логов
kubectl logs -n production deploy/user-service | grep -E "(CustomException|RuntimeException|chaosblade)"
# → WARN: CustomException injected by chaosblade

# Метрики error rate
curl -s http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~"5.."}[1m]))
# → Выросло во время инъекции
```

**Очистка:**

```bash
# Удаляем эксперимент
blade destroy $(blade list | grep throwCustomException | awk '{print $1}')
# → Success: Destroy chaosblade success.
```

### Сценарий 2: Thread pool exhaustion

**Цель:** Проверить, что при исчерпании пула потоков приложение возвращает 503, а не зависает.

**Инструмент:** Chaosblade или custom script.

**Инжектируем нагрузку на пул:**

```bash
# Java: уменьшаем размер пула через JMX
blade create jvm modifyField \
  --classname com.example.service.WorkerPool \
  --fieldname corePoolSize \
  --value 1 \
  --pid $PID \
  --duration 120s

# Или: инжектируем блокирующую задачу
blade create jvm throwCustomException \
  --exception java.util.concurrent.RejectedExecutionException \
  --classname com.example.service.TaskExecutor \
  --methodname submit \
  --pid $PID \
  --duration 60s
```

**Наблюдаем:**

```bash
# Приложение должно возвращать 503, а не зависать
for i in {1..50}; do
  curl -s -o /dev/null -w "%{http_code}\n" http://user-service/api/async-task
done | sort | uniq -c
# → 50 раз 503 (RejectedExecutionException)

# Проверка метрик пула
curl -s http://user-service:8080/actuator/metrics/tasks.running
# → 1 (максимальный размер пула)

# Проверка, что новые задачи отклоняются, а не накапливаются
curl -s http://user-service:8080/actuator/metrics/tasks.rejected
# → > 0
```

### Сценарий 3: Connection pool exhaustion

**Цель:** Проверить, что при исчерпании пула соединений с БД приложение возвращает ошибку gracefully.

**Инструмент:** Chaosblade + PostgreSQL.

**Инжектируем сбой:** уменьшаем пул соединений.

```bash
# Java/HikariCP: уменьшаем maximumPoolSize до 1
blade create jvm modifyField \
  --classname com.zaxxer.hikari.HikariDataSource \
  --fieldname maximumPoolSize \
  --value 1 \
  --pid $PID \
  --duration 120s
```

**Наблюдаем:**

```bash
# Генерация нагрузки
kubectl exec -n production deploy/load-generator -- k6 run --vus 50 --duration 2m script.js

# Приложение должно возвращать 503, а не зависать
curl -s http://user-service/api/users
# → 503 Service Unavailable

# Проверка метрик пула
curl -s http://user-service:8080/actuator/metrics/hikaricp.connections.active
# → 1 (максимальный размер)

curl -s http://user-service:8080/actuator/metrics/hikaricp.connections.pending
# → > 0 (ожидающие соединения)

# Проверка логов БД
kubectl logs -n production postgres-primary-0 | grep -E "(too many connections|connection refused)"
# → Нет ошибок (пool exhausted на стороне приложения, не БД)
```

### Сценарий 4: Memory leak injection

**Цель:** Проверить, что GC корректно работает и приложение не падает с OOMKilled при утечке памяти.

**Инструмент:** stress-ng или custom Java agent.

**Инжектируем утечку:**

```bash
# Java: инжектируем утечку через Chaosblade
blade create jvm createMemoryLeak \
  --classname com.example.service.CacheManager \
  --methodname put \
  --pid $PID \
  --duration 180s \
  --size 10MB

# Или: stress-ng через cgroups
kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: memory-leak
  namespace: chaos-testing
spec:
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: user-service
  stressors:
    memory:
      workers: 1
      size: "50%"
  duration: "3m"
EOF
```

**Наблюдаем:**

```bash
# Проверка использования памяти
kubectl top pods -n production -l app=user-service
# → user-service-xxx   500m   400Mi/512Mi (выросло)

# Проверка GC logs
kubectl logs -n production deploy/user-service | grep -E "(GC| garbage|Full GC)"
# → [GC (Allocation Failure) ... 1500M->1200M]

# Проверка, что приложение не падает
kubectl get pods -n production -l app=user-service
# → Running (не CrashLoopBackOff)

# Проверка OOMKilled
kubectl get pods -n production -l app=user-service -o jsonpath='{.items[0].status.containerStatuses[0].lastState}'
# → {} (не было OOMKilled)
```

### Сценарий 5: CPU starvation via cgroups

**Цель:** Проверить, что при ограничении CPU приложение деградирует gracefully, а не зависает.

**Инструмент:** Chaos Mesh StressChaos или cgroups напрямую.

**Инжектируем ограничение:**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: cpu-starvation
  namespace: chaos-testing
spec:
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: user-service
  stressors:
    cpu:
      workers: 2
      load: 90
  duration: "3m"
```

**Наблюдаем:**

```bash
# Проверка CPU
kubectl top pods -n production -l app=user-service
# → user-service-xxx    900m    256Mi/512Mi

# Проверка latency
kubectl exec -n production deploy/load-generator -- k6 run --vus 10 --duration 1m script.js
# → p99 latency вырос, но error rate < 5%

# Проверка, что приложение не зависает
curl -s http://user-service/api/health
# → 200 OK (degraded, но alive)

# Проверка cgroups
kubectl exec -n production deploy/user-service -- cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us
# → 50000 (ограничение 50%)
```

### Сценарий 6: Latency injection на уровне драйвера

**Цель:** Проверить, что таймауты на уровне драйвера БД корректно обрабатывают задержки.

**Инструмент:** Toxiproxy или Chaos Mesh IOChaos.

**Инжектируем задержку:**

```bash
# Toxiproxy: добавляем задержку на PostgreSQL port
docker run -d --name toxiproxy -p 8474:8474 -p 5432:5432 shopify/toxiproxy

curl -X POST http://localhost:8474/proxies/postgres -d '{
  "name":"postgres",
  "listen":"0.0.0.0:5432",
  "upstream":"postgres:5432",
  "enabled":true
}'

curl -X POST http://localhost:8474/proxies/postgres/toxics -d '{
  "name":"latency",
  "type":"latency",
  "attributes":{"latency":5000}
}'
```

**Наблюдаем:**

```bash
# Приложение должно получить timeout, а не зависнуть
curl -s -w "\n%{time_total}\n" http://user-service/api/users/123
# → 504 Gateway Timeout (после 5s)
# → time_total: 5.2s

# Проверка метрик
curl -s http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~"5.."}[1m]))
# → Выросло (timeout errors)

# Проверка, что соединения освобождаются
curl -s http://user-service:8080/actuator/metrics/hikaricp.connections.active
# → 0 (все соединения освободились после timeout)
```

### Сценарий 7: File descriptor exhaustion

**Цель:** Проверить, что при исчерпании файловых дескрипторов приложение корректно обрабатывает ошибки.

**Инструмент:** Chaos Mesh или custom script.

**Инжектируем сбой:**

```bash
# Устанавливаем жесткий лимит дескрипторов
kubectl exec -n production deploy/user-service -- sh -c "ulimit -n 10"

# Или через cgroups
echo "10" > /sys/fs/cgroup/pids/user-service.slice/pids.max
```

**Наблюдаем:**

```bash
# Приложение должно возвращать 503, а не падать
curl -s http://user-service/api/users
# → 503 Service Unavailable

# Проверка логов
kubectl logs -n production deploy/user-service | grep -E "(Too many open files|EMFILE|ENFILE)"
# → WARN: Too many open files

# Проверка дескрипторов
kubectl exec -n production deploy/user-service -- lsof | wc -l
# → 10 (максимальный лимит)
```

## Операции и команды

### Chaosblade

```bash
# Список экспериментов
blade list

# Создание: исключение в Java
blade create jvm throwCustomException \
  --exception java.lang.RuntimeException \
  --classname com.example.service.UserService \
  --methodname getUserInfo \
  --pid $PID \
  --duration 60s

# Создание: утечка памяти
blade create jvm createMemoryLeak \
  --classname com.example.service.CacheManager \
  --methodname put \
  --pid $PID \
  --duration 180s \
  --size 10MB

# Создание: модификация поля
blade create jvm modifyField \
  --classname com.example.service.WorkerPool \
  --fieldname corePoolSize \
  --value 1 \
  --pid $PID \
  --duration 120s

# Удаление эксперимента
blade destroy <record-id>
```

### cgroups v2 (напрямую)

```bash
# Ограничение CPU (50% = 50000 100000)
echo "50000 100000" | sudo tee /sys/fs/cgroup/cpu/app.slice/cpu.max

# Ограничение памяти (256MB)
echo "268435456" | sudo tee /sys/fs/cgroup/memory/app.slice/memory.max

# Проверка использования
cat /sys/fs/cgroup/cpu/app.slice/cpu.stat
# → usage_usec 123456789
# → user_usec 98765432
# → system_usec 24691357
```

### Stress-ng

```bash
# CPU hog
stress-ng --cpu 4 --cpu-load 90 --timeout 180s

# Memory hog
stress-ng --vm 1 --vm-bytes 512M --timeout 180s

# IO stress
stress-ng --io 4 --io-ops 1000 --timeout 180s
```

### Java JMX (через jconsole/jmxterm)

```bash
# Подключение к JMX
jconsole <pid>:9010

# Или через jmxterm
java -jar jmxterm-1.0.2-uber.jar -l service:jmx:rmi:///jndi/rmi://localhost:9010/jmxrmi

# Изменение поля
bean = MBeanProxy.newProxyName("com.example.service", "WorkerPool", "type=WorkerPool,name=pool")
set corePoolSize 1
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Chaosblade не инжектирует исключение** | Неверный classname/methodname или PID | Проверьте `jps -l`, точное имя класса с package, метод существует |
| **Exception injection не влияет** | Кэширование результата или circuit breaker | Очистите кэш, отключите circuit breaker на время эксперимента |
| **Thread pool не истощается** | Размер пула слишком большой или задачи выполняются быстро | Уменьшите `corePoolSize`, увеличьте длительность задачи |
| **Connection pool не истощается** | Пулы на уровне приложения и драйвера разные | Проверьте `maximumPoolSize` на уровне HikariCP и драйвера |
| **Memory leak не обнаруживается** | GC эффективно очищает или лимит слишком высокий | Увеличьте размер утечки, проверьте GC logs, снизьте `-Xmx` |
| **CPU starvation не работает** | cgroups v1/v2 conflict или неправильный путь | Проверьте `stat -fc %T /sys/fs/cgroup`, используйте правильный cgroup path |
| **File descriptor exhaustion не срабатывает** | Лимит не применяется или приложение не использует FD | Проверьте `ulimit -n`, `lsof | wc -l`, убедитесь, что приложение открывает соединения |
| **Latency injection игнорируется** | Драйвер имеет собственный таймаут или пул соединений кеширует | Настройте драйвер timeout < injected latency, отключите connection pooling |

## Лучшие практики

### Безопасность

1. **Всегда тестируйте в staging** — application-level chaos может оставить приложение в нестабильном состоянии.
2. **Ограничивайте duration** — максимум 5 минут для exception injection, 10 минут для memory leak.
3. **Имейте emergency stop** — kill -9 процесс, если приложение не recovering.
4. **Уведомляйте команду** — эксперименты на уровне кода могут повлиять на всех пользователей.
5. **Не инжектируйте в критичные периоды** — релизы, маркетинговые акции.

### Проектирование экспериментов

6. **Тестируйте один паттерн за раз** — exception injection отдельно от thread pool exhaustion.
7. **Используйте production-реализацию** — тестируйте реальные конфигурации пулов, не mock.
8. **Определите success criteria** — например: "при thread pool exhaustion приложение возвращает 503 за <100ms".
9. **Тестируйте recovery** — после отключения инъекции пул должен восстановиться за <30s.
10. **Ведите runbook** — шаги, контакты, emergency stop, критерии успеха.

### Мониторинг

11. **Экспортируйте метрики пулов** — active connections, pending tasks, rejected tasks.
12. **Настройте алерты на OOM** — `container_memory_working_set_bytes / container_spec_memory_limit_bytes > 0.9`.
13. **Используйте tracing** — Jaeger trace должен показывать, где произошла инъекция.
14. **Мониторьте GC** — GC pause time, frequency, promoted bytes.

### Избегайте ошибок

15. **Не инжектируйте в production без staging** — первый эксперимент всегда в тестовой среде.
16. **Не используйте слишком большие значения** — memory leak 1GB может уронить весь узел.
17. **Не забывайте про cleanup** — убедитесь, что все поля возвращены к исходным значениям, процессы убиты.
18. **Не тестируйте несколько методов одновременно** — если исключение произошло, вы не поймете, в каком методе.
19. **Не игнорируйте side effects** — exception injection в одном методе может повлиять на транзакцию БД.

## Дополнительная информация

### Связанные технологии

- **Chaosblade** — CLI для application-level chaos (Java, Go, C++).
- **Chaos Monkey for Spring Boot** — аннотации для инъекции сбоев в Spring-приложения.
- **Toxiproxy** — TCP proxy для инъекции задержек на уровне драйвера.
- **cgroups v2** — механизм ограничения ресурсов на уровне ОС.

### См. также

- [Chaos Engineering — инструменты](chaos_engineering_tools.md) — Chaosblade, Toxiproxy.
- [Chaos Engineering — resilience patterns](chaos_resilience_patterns_testing.md) — testing Circuit Breaker, Bulkhead через application chaos.
- [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — Game Days.
