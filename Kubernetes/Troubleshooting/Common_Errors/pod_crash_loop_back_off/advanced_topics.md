# Продвинутые темы и лучшие практики: CrashLoopBackOff

## Определения

**Продвинутая диагностика CrashLoopBackOff** — применение глубоких методов анализа системных вызовов, метрик давления на ресурсы (PSI), приоритетов ядра (OOM Score) и жизненного цикла контейнеров для выявления скрытых причин нестабильности.

Полное описание базовых механизмов и пошаговый алгоритм поиска неисправностей представлены в разделах:
- **[Определения и концепции](./definitions_and_concepts.md)** — SSoT по теории.
- **[Диагностика и чек-лист](./diagnostics.md)** — основной алгоритм.

## Основные концепции

### Механизм oom_score_adj и приоритеты выживания

Kubernetes управляет вероятностью завершения процесса при нехватке памяти через параметр ядра `/proc/self/oom_score_adj`. Понимание этих значений помогает диагностировать, почему падает конкретный под при общем дефиците ресурсов на узле.

| Класс QoS | Значение oom_score_adj | Приоритет выживания |
| :--- | :--- | :--- |
| **Guaranteed** | -997 | Максимальный (убиваются последними) |
| **Burstable** | `min(max(2, 1000 - (1000 * memoryRequest) / memoryCapacity), 999)` | Средний |
| **BestEffort** | 1000 | Минимальный (убиваются первыми) |

**Продвинутый инсайт:** Если под в классе `Guaranteed` попадает в `CrashLoopBackOff` с кодом 137, значит, он превысил *свой собственный* лимит. Если падает `BestEffort`, он мог быть принесен в жертву ради стабильности узла, даже если не потреблял много памяти.

### Мониторинг давления на ресурсы (PSI — Pressure Stall Information)

В средах с **Cgroup v2** (Kubernetes 1.25+) диагностика смещается от «сколько использовано» к «сколько времени потеряно на ожидание». Метрики PSI позволяют предсказать краш до его наступления.

- **`memory.pressure`**: Показывает процент времени, когда процессы ожидали освобождения или подкачки памяти. Резкий рост `full` pressure — предвестник OOMKilled.
- **`cpu.pressure`**: Показывает конкуренцию за процессорное время. Высокие значения могут приводить к нарушению таймаутов `livenessProbe` и последующему циклу перезапусков.

Подробнее о механизме: **[Pressure Stall Information (PSI)](../../../Linux/Core/kernel/psi.md)**.

### Нюансы Cgroup v2

В отличие от v1, cgroup v2 реализует **единую иерархию**. Для `CrashLoopBackOff` это означает:
1.  **OOM-группа:** По умолчанию, если один процесс в контейнере убит по OOM, ядро убивает все процессы в этой cgroup (весь контейнер). Это исключает ситуацию «зомби-контейнеров», где основной процесс жив, а вспомогательные (например, обработчики очередей) упали.
2.  **Точность лимитов:** Cgroup v2 корректнее учитывает память Page Cache, что снижает количество ложных срабатываний OOM при активной работе с диском.

## Практические сценарии

### Сценарий 1: Native Sidecars (K8s 1.29+ GA)

Механизм нативных sidecar-контейнеров решает проблему Race Condition, когда основное приложение падает из-за неготовности прокси или агента.

```yaml
spec:
  initContainers:
  - name: network-proxy
    image: envoyproxy/envoy:v1.28
    restartPolicy: Always # Ключевой параметр для Native Sidecar
    startupProbe:
      httpGet:
        path: /ready
        port: 8001
  containers:
  - name: app
    image: my-app:latest
    # Запустится ТОЛЬКО после того, как network-proxy станет Ready
```

**Преимущество:** Нативный sidecar гарантированно получает сигнал `SIGTERM` *после* основного контейнера, что критично для корректного завершения сетевых соединений в Service Mesh.

### Сценарий 2: Глубокая eBPF-трассировка (Inspektor Gadget)

Если приложение падает «тихо» (без логов), используйте eBPF для отслеживания системных вызовов.

```bash
# 1. Трассировка попыток открытия файлов (поиск отсутствующих конфигов)
kubectl gadget trace open -n my-ns --pod <pod-name>

# 2. Мониторинг сигналов (кто именно отправляет SIGKILL/SIGTERM)
kubectl gadget trace signal -n my-ns --pod <pod-name>
```

# → Результат: Вы можете увидеть, что приложение упало с ошибкой `ENOENT` при попытке открыть `/etc/config/secret.json`, даже если само приложение не успело вывести эту ошибку в логи.

### Сценарий 3: Использование termination-log для богатой диагностики

Kubernetes может считывать причину падения напрямую из файла внутри контейнера. Это позволяет передать детали ошибки в API, которые будут видны в `kubectl describe pod`.

```yaml
spec:
  containers:
  - name: app
    image: my-app
    terminationMessagePath: /dev/termination-log
    terminationMessagePolicy: FallbackToLogsOnError
```

**Рекомендация:** Настройте ваше приложение так, чтобы при критическом сбое (panic, unhandled exception) оно записывало краткую причину в `/dev/termination-log`. Это избавит от необходимости копаться в гигабайтах логов.

### Сценарий 4: Расширенный скрипт Post-Mortem

Скрипт для автоматического сбора данных при обнаружении `CrashLoopBackOff`.

```bash
#!/bin/bash
# collect-pod-debug.sh <pod-name> <namespace>

POD=$1
NS=${2:-default}

echo "--- Сбор oom_score_adj ---"
kubectl exec $POD -n $NS -- cat /proc/1/oom_score_adj

echo "--- Анализ PSI (Memory) ---"
# Требуется доступ к хосту или привилегированный контейнер
kubectl debug node/$(kubectl get pod $POD -n $NS -o jsonpath='{.spec.nodeName}') \
  -it --image=busybox --quiet -- chroot /host cat /proc/pressure/memory | head -n 1

echo "--- Проверка последнего сообщения о завершении ---"
kubectl get pod $POD -n $NS -o jsonpath='{.status.containerStatuses[0].lastState.terminated.message}'
```

## Дополнительная информация

### Лучшие практики (Best Practices)

1.  **Startup Boost:** Используйте `requests.cpu` < `limits.cpu`. В моменты инициализации (JIT-компиляция в Java, прогрев кэшей) приложение может легально потреблять больше ресурсов. Throttling на старте — частая причина `CrashLoopBackOff` по таймауту проб.
2.  **Идемпотентность Init-контейнеров:** Помните, что Init-контейнеры могут перезапускаться. Их действия (миграции БД, создание папок) должны быть безопасными при повторном вызове.
3.  **Использование preStop Hooks:** Для отладки «зависающих» завершений добавьте в `preStop` команду сбора дампов: `preStop: exec: command: ["/bin/sh", "-c", "gcore -o /dumps/app.core 1"]`.

### Ссылки

- **[KEP-3839: Sidecar Containers](https://github.com/kubernetes/enhancements/tree/master/keps/sig-node/3839-sidecar-containers)** — история и детали реализации нативных сайдкаров.
- **[eBPF для SRE (Cilium)](https://cilium.io/blog/2021/12/01/cilium-service-mesh/)** — продвинутая наблюдаемость.
- **[Оптимизация JVM в Kubernetes](https://www.overops.com/blog/how-to-optimize-java-within-docker-containers/)** — решение проблем с памятью и процессором.

---

### Связанные файлы

- **[Диагностика и чек-лист](./diagnostics.md)** — практические шаги отладки.
- **[Распространенные решения](./common_cases_and_solutions.md)** — база знаний по типовым ошибкам.
