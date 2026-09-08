# Pod Terminating — корректное завершение (Graceful Shutdown)

## Определения

**Корректное завершение (Graceful Shutdown)** — регламентированный процесс остановки Pod, при котором приложению предоставляется время на корректную обработку текущих запросов, закрытие сетевых соединений и сохранение состояния перед физическим уничтожением контейнеров.

**Обработчик preStop (preStop hook)** — команда или HTTP-запрос, который `kubelet` выполняет внутри контейнера непосредственно перед отправкой сигнала `SIGTERM`. Основное назначение — искусственная задержка для синхронизации состояния сети или выполнение финализации (например, выход из кворума).

**Период корректного завершения (`terminationGracePeriodSeconds`)** — общее время (по умолчанию 30 секунд), выделяемое на весь процесс остановки пода. Этот интервал включает выполнение `preStop hook` и время на обработку `SIGTERM`. Минимальное значение — 0 (немедленный `SIGKILL`), максимальное — 3600 (1 час).

**Контейнерный Grace Period (K8s 1.25+)** — возможность задать индивидуальный `terminationGracePeriodSeconds` на уровне конкретного контейнера. Полезно, если сайдкару нужно меньше времени на остановку, чем основному приложению.

**Сигнал SIGTERM (Signal Termination)** — стандартный сигнал завершения (номер 15), отправляемый процессу с PID 1. Приложение должно уметь перехватывать этот сигнал для инициации внутренней процедуры остановки.

**Сигнал SIGKILL (Signal Kill)** — принудительный сигнал немедленной остановки (номер 9). Не может быть перехвачен процессом. Отправляется ядром ОС процессам, которые не завершились по истечении `terminationGracePeriodSeconds`.

**Connection Draining (Дренаж соединений)** — процесс, при котором сервер после получения сигнала остановки завершает обработку активных запросов и закрывает существующие соединения, не принимая новые. В Kubernetes реализуется через комбинацию `preStop` + обработчик `SIGTERM` в приложении.

---

## Базовые концепции

### Последовательность событий и сетевая гонка (Race Condition)

Процесс остановки инициируется через API-сервер. Удаление пода — это не последовательность шагов, а **гонка** двух независимых и параллельных цепочек событий:

1.  **Цепочка первая (локальная, быстрая):** `kubelet` на ноде видит `deletionTimestamp`, выполняет `preStop`-хук (если есть) и отправляет `SIGTERM`. Всё это происходит локально на ноде и почти мгновенно.
2.  **Цепочка вторая (глобальная, медленная):** Контроллер эндпоинтов видит удаление и убирает под из `EndpointSlice`. Это изменение должно разойтись всем подписчикам: `kube-proxy` на каждой ноде (обновление правил iptables/ipvs), Ingress-контроллерам, Service Mesh, облачным балансировщикам.

**Проблема задержки (Propagation Delay):** Никакой синхронизации между цепочками нет. Первая цепочка обычно завершается за миллисекунды, вторая на живом кластере занимает от сотен миллисекунд до нескольких секунд. Если приложение при получении `SIGTERM` сразу закрывает слушающий сокет, трафик продолжает идти на него, пока сеть не обновится, что приводит к ошибкам **502 Bad Gateway** или **Connection refused**.

**Решение:** Дать медленной цепочке фору с помощью `preStop` хука.

> **Ирония:** Чем аккуратнее приложение завершается (быстро закрывает сокет при SIGTERM), тем больше пятисотых вы получаете. Приложения, которые «тупят» несколько секунд, случайно оказываются в выигрыше.

### Тайминги: формула расчёта preStop

Правильный расчёт `preStop` и `terminationGracePeriodSeconds` — ключ к нулевому даунтайму:

```
terminationGracePeriodSeconds = preStop sleep + время дренажа приложения + запас

Где:
- preStop sleep: 5–15 секунд (компенсация propagation delay)
- время дренажа приложения: 5–30 секунд (зависит от стека)
- запас: 5–10 секунд (страховка)
```

**Типичные значения:**

| Тип приложения | preStop | Дренаж | terminationGracePeriodSeconds |
| :--- | :--- | :--- | :--- |
| Stateless HTTP (Nginx, Go) | 10с | 5с | 25–30с |
| Java/Spring Boot | 10с | 15–30с | 45–60с |
| gRPC/WebSocket | 15с | 10–20с | 45–60с |
| БД-клиент (pgBouncer) | 10с | 10с | 30–40с |
| Очередь (RabbitMQ consumer) | 5с | 30–60с | 45–90с |
| StatefulSet (PostgreSQL) | 10с | 30–60с | 60–120с |

### Управление Keep-alive и соединениями

Обновление `EndpointSlice` влияет только на **новые** соединения. Долгоживущие TCP-соединения (keep-alive пулы) между прокси (Ingress) и подами продолжают указывать на умирающий под.
- **Проблема:** Клиентский прокси может продолжать слать запросы в умирающий под через уже установленное соединение даже после его удаления из списков эндпоинтов.
- **Решение:** При получении `SIGTERM` приложение должно не только доработать текущие запросы, но и начать отдавать заголовок **`Connection: close`** (HTTP/1.1) или посылать **`GOAWAY`** (HTTP/2 и gRPC). Это заставит прокси корректно закрыть соединение и переоткрыть его на другой, живой под.

### HTTP/2 и GOAWAY

В HTTP/1.1 достаточно заголовка `Connection: close`. В HTTP/2 и gRPC используется фрейм `GOAWAY`, который сигнализирует клиенту, что сервер завершает работу, и перенаправляет новые потоки на другой сервер.

- **Время жизни GOAWAY:** Минимальное recommended значение — 10 секунд (позволяет клиенту переоткрыть соединение до завершения работы сервера).
- **Реализация:** Большинство фреймворков отправляют GOAWAY автоматически при вызове graceful shutdown. Убедитесь, что приложение не закрывает соединение мгновенно, а ждёт завершения активных RPC.
- **Проверка:** Если клиент получает `GOAWAY` и не может переоткрыть соединение — проверьте, что клиентская библиотека поддерживает retry logic.

### Порядок завершения Native Sidecar (K8s 1.29+)

Для контейнеров в `initContainers` с `restartPolicy: Always`:
1.  Сначала завершаются основные контейнеры (`containers[]`).
2.  `kubelet` ожидает их полной остановки.
3.  Только после этого инициируется остановка сайдкаров. Это гарантирует, что сайдкар (например, прокси или сборщик логов) работает до тех пор, пока основное приложение не завершится.

### Проблема PID 1 и проброса сигналов

Если приложение запускается через shell (`ENTRYPOINT /app/start.sh` без `exec`), сигналы `SIGTERM` поглощаются shell-оболочкой.
- **Симптом**: Приложение всегда удаляется ровно через 30 секунд (по `SIGKILL`).
- **Решение**: Использовать `exec` в скриптах или массивную форму в Dockerfile (`CMD ["/app/binary"]`).

---

## Практические сценарии

### Настройка preStop хука (фора для сети)

Самое эффективное средство — дать медленной цепочке фору (обычно 5–15 секунд).

#### Нативный sleep (Kubernetes 1.30+)
Рекомендуемый способ, не требующий наличия шелла или бинарника `sleep` в образе:
```yaml
lifecycle:
  preStop:
    sleep:
      seconds: 10
```

#### На версиях < 1.30
Используется `exec`. **Засада:** В образах `distroless` или `scratch` бинарник `/bin/sleep` отсутствует. Хук молча упадет (`FailedPreStopHook`), и задержка не сработает.
```yaml
lifecycle:
  preStop:
    exec:
      command: ["/bin/sleep", "10"]
```

#### HTTP-хук preStop
Альтернатива `exec` — HTTP-запрос к эндпоинту приложения. Полезно, когда приложение должно само инициировать дренаж:
```yaml
lifecycle:
  preStop:
    httpGet:
      path: /shutdown
      port: 8080
```
Эндпоинт `/shutdown` должен:
1. Поставить флаг `isShuttingDown = true`.
2. Начать отдавать `503` в readinessProbe (чтобы Pod быстро убрался из Endpoints).
3. Доработать активные запросы.
4. Завершиться с кодом 0.

#### Типичные preStop-паттерны для сервисов

| Сервис | Рекомендуемый preStop | Причина |
| :--- | :--- | :--- |
| **Nginx** | `sleep 10` | `worker_shutdown_timeout` по умолчанию 10с |
| **HAProxy** | `sleep 5` + эндпоинт `/haproxy?shutdown` | Быстрый дренаж через stats socket |
| **Tomcat** | `sleep 10` + `/shutdown` | `connectionTimeout` + graceful stop |
| **Spring Boot** | `sleep 5` + `/actuator/shutdown` | Встроенный graceful shutdown |
| **gRPC** | `sleep 15` | Дать время на GOAWAY + переоткрытие |
| **RabbitMQ consumer** | `sleep 5` + `basicCancel` | Ack текущих сообщений, reject новых |
| **PostgreSQL** | `sleep 10` | WAL checkpoint + отключение клиентов |

### Дренаж и завершение в приложении

После получения `SIGTERM` приложение обязано:
1.  Перестать принимать новые соединения.
2.  Доработать уже принятые запросы.
3.  Корректно закрыть соединения (см. раздел Keep-alive и HTTP/2).

**Примеры реализации:**
- **Go**: `srv.Shutdown(ctx)` (вместо резкого выхода). Автоматически закрывает listener и ждёт завершения активных запросов с таймаутом.
- **Java (Spring Boot)**: `server.shutdown=graceful` в конфиге. Включает встроенный механизм дренажа с таймаутом `spring.lifecycle.timeout-per-shutdown-phase`.
- **Node.js**: `server.close()` с ожиданием. Не закрывает существующие соединения, а только прекращает принимать новые.
- **Python (gunicorn)**: Корректная обработка сигнала мастером. `TERM`-сигнал инициирует graceful shutdown воркеров.
- **Python (uvicorn)**: `Server.handle_exit` + signal handler. При `SIGTERM` uvicorn отправляет `lifespan.shutdown` событие.
- **Rust (actix-web)**: `App::on_connect` + custom shutdown handler.

### Верификация Zero-Downtime

Единственный способ подтвердить отсутствие потерь — запуск нагрузки во время выката:
1.  Запустите генератор нагрузки (например, `hey` или `vegeta`) на сервис.
2.  Выполните `kubectl rollout restart deployment/<name>`.
3.  Мониторьте логи ингресса на наличие 502/504 ошибок. Любая «горка» ошибок указывает на дыру в одной из четырех областей: `preStop`, внутренний дренаж, keep-alive или готовность новых подов.

```bash
# Запуск нагрузки (hey)
hey -z 30s -c 10 http://<service>/endpoint

# Запуск выката
kubectl rollout restart deployment/<name>

# Мониторинг ошибок в реальном времени
kubectl logs -l app=<name> -f | grep -E "502|504|connection refused"

# Или через ingress
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx -f | grep -E "502|504"
```

### Диагностика процесса завершения на узле

Если вы сомневаетесь, получает ли контейнер сигналы, проверьте это через CRI (на узле):

```bash
# 1. Поиск контейнера и его PID на хосте
CONTAINER_ID=$(crictl ps --name web-app -q)
PID=$(crictl inspect $CONTAINER_ID | jq .info.pid)

# 2. Мониторинг системных вызовов в реальном времени (нужен strace)
strace -p $PID -e signal

# 3. Проверка дерева процессов
ps -fH -p $PID
```

### Типичные ошибки конфигурации

| Ошибка | Последствие | Решение |
| :--- | :--- | :--- |
| **preStop > GracePeriod** | Контейнер будет убит по `SIGKILL` до того, как завершится `preStop`. | Увеличьте `terminationGracePeriodSeconds`. |
| **Отсутствие PID 1** | Приложение не видит `SIGTERM`. | Используйте `tini` или `exec form`. |
| **Игнорирование SIGTERM** | Приложение резко обрывает транзакции. | Реализуйте обработчик сигнала в коде (Graceful Exit). |
| **Длительный PDB** | `drain` узла зависает из-за блокировки. | Проверьте [Блокировку PDB](./pdb_blocking.md). |
| **preStop без readiness probe** | Pod остаётся в Endpoints до SIGKILL. | Добавьте readinessProbe, возвращающий 503 после SIGTERM. |
| **connection timeout < drain time** | Прокси закрывает соединение до завершения запроса. | Увеличьте `proxy_read_timeout` в Ingress. |

---

## Дополнительная информация

### Взаимодействие с readinessProbe при завершении

При `SIGTERM` приложение должно начать возвращать ошибки в `readinessProbe`:
- Если `readinessProbe` продолжает отдавать `200 OK` после `SIGTERM`, Pod остаётся в Endpoints до истечения `terminationGracePeriodSeconds`.
- Трафик продолжает поступать на умирающий под, создавая ошибки.
- Решение: в обработчике `SIGTERM` установить флаг `isShuttingDown = true` и возвращать `503` из readinessProbe.

### Взаимодействие с DaemonSet при обслуживании узла

Pod'ы DaemonSet **не могут** использовать Pod Disruption Budget. При `kubectl drain`:
- С `--ignore-daemonsets=true` (по умолчанию): поды DaemonSet остаются на узле.
- С `--ignore-daemonsets=false`: поды удаляются принудительно.
- Если DaemonSet настроен с `terminationGracePeriodSeconds: 0`, контейнеры будут убиты мгновенно.

### Graceful Node Shutdown (K8s 1.21+)

При выключении узла через `systemctl poweroff` или IPMI, `kubelet` получает уведомление от `systemd-logind` и завершает поды в порядке приоритета:

```yaml
# kubelet configuration
shutdownGracePeriod: 30s
shutdownGracePeriodCriticalPods: 10s
shutdownGracePeriodByPodPriority:
  - priority: 1000000  # System-critical
    shutdownGracePeriodSeconds: 10
  - priority: 0        # Default
    shutdownGracePeriodSeconds: 30
```

**Важно:** Этот механизм работает **только** при корректной настройке `systemd-logind` и **не заменяет** `kubectl drain` при плановом обслуживании.

### Использование dumb-init и tini

Для приложений, которые не могут корректно работать как PID 1 (например, не умеют собирать "зомби-процессы"), рекомендуется использовать легковесные менеджеры:
```dockerfile
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/app/app.py"]
```

### Мониторинг корректного завершения

```promql
# Поды, завершающиеся по SIGTERM (exitCode 143) — нормальное поведение
kube_pod_container_status_last_terminated_reason{reason="Completed"} > 0

# Поды, убитые по SIGKILL (exitCode 137) — проблема с terminationGracePeriodSeconds
kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} > 0

# Время жизни пода от SIGTERM до завершения (должно быть < terminationGracePeriodSeconds)
histogram_quantile(0.99, rate(kube_pod_container_terminated_reason_seconds_bucket[5m]))
```

```bash
# Быстрая проверка подов, завершающихся по SIGKILL
kubectl get pods -A -o json | jq -r '.items[] | select(.status.containerStatuses[]?.lastState.terminated.exitCode == 137) | "\(.metadata.namespace)/\(.metadata.name) - exitCode 137 (\(.status.containerStatuses[]?.lastState.terminated.reason))"'

# Проверка подов, которые "тормозят" при завершении
kubectl get pods -A -o json | jq -r '.items[] | select(.metadata.deletionTimestamp != null) | "\(.metadata.namespace)/\(.metadata.name): deletionTimestamp=\(.metadata.deletionTimestamp) gracePeriod=\(.metadata.deletionGracePeriodSeconds)s"'
```

### Связанные команды kubectl

| Команда | Назначение |
| :--- | :--- |
| `kubectl delete pod <name> --grace-period=<N>` | Удаление с указанием периода ожидания |
| `kubectl get pod <name> -o jsonpath='{.metadata.deletionTimestamp}'` | Проверка, начато ли удаление |
| `kubectl get pod <name> -o jsonpath='{.spec.containers[*].lifecycle.preStop}'` | Просмотр preStop хуков |
| `kubectl get pod <name> -o jsonpath='{.spec.terminationGracePeriodSeconds}'` | Просмотр лимита завершения |
| `kubectl describe pod <name> | grep -A 20 Events` | События завершения |
| `kubectl logs <name> --previous` | Логи предыдущего контейнера (если был перезапуск) |
| `crictl ps --name <container>` | Поиск контейнера на узле |
| `crictl inspect <container-id> \| jq .info.pid` | PID контейнера на хосте |
| `ps -fH -p <PID>` | Дерево процессов контейнера |

**См. также:**
- [Определения Pod Terminating](./definitions.md) — базовые термины и механизмы.
- [Диагностика Pod Terminating](./diagnostics.md) — алгоритм поиска причин зависания.
- [Финализаторы и CSI](./finalizer_issues.md) — если под застрял из-за дисков.
- [Официальная документация (Termination)](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination) — спецификация.
