# Ephemeral Containers — эфемерные контейнеры

## Определения

**Ephemeral Container (эфемерный контейнер)** — временный контейнер, запускаемый в существующем работающем Pod для пользовательских действий: отладка, траблшутинг, инспектирование состояния. Не предназначен для сборки приложений.

**Distroless-образ** — минимальный контейнерный образ без shell и утилит (только приложение и runtime-библиотеки). Стандартный `kubectl exec` не работает, требует ephemeral containers для отладки.

**Process Namespace Sharing** — механизм совместного использования PID-namespace между контейнерами в поде, позволяющий видеть процессы других контейнеров.

---

## Базовые концепции

### Общие сведения

- Статус: **stable** с Kubernetes 1.25
- Создаются через специальный **ephemeral containers handler API**, а не через спецификацию пода
- **Невозможно** добавить ephemeral контейнер через `kubectl edit` или обновлением pod spec
- **Невозможно** удалить или модифицировать ephemeral контейнер после добавления
- **Не поддерживаются** Static Pods (поды системных компонентов: kubelet, kube-proxy и др.)
- Автоматически **не перезапускаются** при завершении
- Удаляются вместе с подом

### Ограничения и запреты

Ephemeral контейнеры используют ту же структуру `containerSpec`, что и обычные контейнеры, но многие поля **запрещены**:

| Запрещённое поле | Причина |
|:---|:---|
| `ports` | Эфемерные контейнеры не имеют портов |
| `resources` (requests/limits) | Ресурсы пода не меняются после создания |
| `livenessProbe`, `readinessProbe`, `startupProbe` | Не предназначены для production-работы |
| `lifecycle` (postStart/preStop) | Нет lifecycle hooks |
| `restartPolicy` | Никогда не перезапускаются |

### Влияние на ресурсы пода

- Ephemeral контейнер использует **те же ресурсы**, что выделены поду изначально
- Если контейнер вызовет превышение ресурсов — kubelet может **выселить** под (eviction)
- **Рекомендация:** с осторожностью запускать в production-подах, особенно с утилитами интенсивного анализа

### Когда использовать

| Сценарий | Почему `kubectl exec` не работает | Решение |
|:---|:---|:---|
| Distroless-образ | Нет shell и утилит | Ephemeral container с busybox/ubuntu |
| Приложение крашится при старте | Контейнер не в Running | `kubectl debug --copy-to` |
| Нужны доп. утилиты (tcpdump, ps, strace) | Образ минимальный | Ephemeral container с netshoot |
| Изолированная отладка команды | Нужно изменить команду запуска | `kubectl debug --set-image` |

---

## Практические сценарии

### Сценарий 1: Базовая отладка ephemeral контейнером

**Проблема:** Pod запущен, но `kubectl exec` невозможен (нет shell в образе).

```bash
# Создаём тестовый pod (pause-контейнер, без shell)
kubectl run ephemeral-demo --image=k8s.gcr.io/pause:3.1 --restart=Never

# Попытка exec завершится ошибкой:
kubectl exec -it ephemeral-demo -- /bin/sh
# → Error: unable to upgrade connection: container not found ("ephemeral-demo")

# Добавляем ephemeral контейнер для отладки
kubectl debug -it ephemeral-demo \
  --image=busybox:1.36.1 \
  --target=ephemeral-demo
```

| Параметр | Описание |
|:---|:---|
| `--image=busybox:1.36.1` | Образ отладочного контейнера |
| `--target=ephemeral-demo` | Целевой контейнер для совместного использования namespaces |
| `-it` | Интерактивный режим сTTY |

**Проверка:**

```bash
# Ephemeral контейнер появляется в описании пода
kubectl describe pod ephemeral-demo
# → Ephemeral Containers:
#     Debug:
#       Image:      busybox:1.36.1
#       State:      Running

# После отладки удаляем тестовый pod
kubectl delete pod ephemeral-demo
```

> **Примечание:** В production не нужно удалять pod приложения — ephemeral контейнер просто добавляется и не влияет на работу основного приложения.

### Сценарий 2: Process Namespace Sharing

**Цель:** Видеть процессы других контейнеров в поде.

```bash
# Добавляем ephemeral контейнер с общим PID-namespace
kubectl debug -it ephemeral-demo \
  --image=busybox:1.36.1 \
  --target=ephemeral-demo \
  --share-processes
```

Результат: внутри ephemeral контейнера команда `ps` покажет процессы всех контейнеров пода.

### Сценарий 3: Копирование пода для отладки (Copy-to)

**Проблема:** Конфигурация пода мешает отладке (приложение крашится, нет shell).

```bash
# Создаём pod, который будет "спать" (симуляция работающего приложения)
kubectl run myapp --image=busybox:1.36.1 -- sleep 86400

# Создаём копию пода с дополнительным отладочным контейнером
kubectl debug myapp \
  --image=ubuntu:24.04 \
  --copy-to=myapp-debug

# Результат: новый pod myapp-debug с двумя контейнерами:
# 1. myapp (оригинальный)
# 2. debugger (ephemeral с ubuntu)
```

| Параметр | Описание |
|:---|:---|
| `--copy-to=myapp-debug` | Имя нового debug-пода |
| `--image=ubuntu:24.04` | Образ отладочного контейнера |
| `-it` | Автоматическое подключение к оболочке (по умолчанию) |
| `--attach=false` | Отключить автоподключение (войти позже через `kubectl attach`) |

**Повторное подключение к ephemeral контейнеру:**

```bash
# Если сессия потеряна — подключаемся обратно (пока контейнер работает)
kubectl attach -it myapp-debug -c debugger
```

**Параметр `--share-processes`:**

```bash
kubectl debug myapp \
  --image=ubuntu:24.04 \
  --copy-to=myapp-debug \
  --share-processes
```

> **Важно:** После отладки обязательно удалить debug-под:
>
> ```bash
> kubectl delete pod myapp myapp-debug
> ```

### Сценарий 3.1: Особенности жизненного цикла ephemeral контейнера

**Завершение при выходе из оболочки:**

Ephemeral контейнер, запущенный с интерактивной оболочкой (`-it`), завершает работу при выходе из оболочки. Контейнер переходит в статус `Completed` или `Error` и **недоступен для повторного подключения**.

```bash
# Запускаем ephemeral контейнер
kubectl debug -it myapp --image=busybox:1.36.1

# Внутри оболочки:
/ exit

# Контейнер завершил работу — повторный kubectl exec невозможен
# Нужно создавать новый ephemeral контейнер
```

**Множественные ephemeral контейнеры:**

Каждый запуск `kubectl debug` создаёт **новый** ephemeral контейнер в поде. Предыдущие контейнеры остаются в списке с статусом `Completed`:

```bash
# Первый ephemeral контейнер
kubectl debug -it myapp --image=busybox:1.36.1
# → exit

# Второй ephemeral контейнер
kubectl debug -it myapp --image=ubuntu:24.04
# → exit

# Проверка описания пода:
kubectl describe pod myapp
# → Ephemeral Containers:
#     debugger-xxxx:  State: Terminated (Completed)
#     debugger-yyyy:  State: Terminated (Completed)
```

> **Примечание:** Kubernetes не удаляет завершённые ephemeral контейнеры автоматически. Они сохраняются до удаления пода.

### Сценарий 3.2: Отладка образов с нестандартным ENTRYPOINT

Некоторые образы (например, `curlimages/curl`) имеют ENTRYPOINT, ожидающий аргументов. Без явного указания shell такой контейнер не сможет запустить интерактивную сессию.

```bash
# Проблема: образ curl ожидает аргументы для ENTRYPOINT
kubectl debug -it myapp --image=curlimages/curl
# → Ошибка: контейнер не может запустить shell

# Решение: явно указать shell после --
kubectl debug -it myapp --image=curlimages/curl -- /bin/sh
```

**Правило:** При использовании образов с неизвестным ENTRYPOINT/CMD всегда добавляйте `-- /bin/sh` (или `-- /bin/bash`) в конец команды для гарантии запуска оболочки.

**Сетевая изоляция в поде:**

Все контейнеры в поде разделяют **одно сетевое пространство** (network namespace). Это позволяет обращаться к основному приложению через `localhost`:

```bash
# Ephemeral контейнер с curl для отладки web-приложения
kubectl debug -it myapp --image=curlimages/curl -- /bin/sh

# Внутри ephemeral контейнера:
/ curl http://localhost:8080/health
# → Обращаемся к основному контейнеру пода
```

### Сценарий 4: Изменение команды запуска контейнера

**Проблема:** Приложение крашится сразу после запуска (exit code 1).

```bash
# Создаём pod, который сразу падает
kubectl run myapp --image=busybox:1.36.1 -- /bin/sh -c "exit 1"

# Проверяем статус
kubectl describe pod myapp
# → State: Terminated, Reason: Error, Exit Code: 1
# Pod перезапускается (CrashLoopBackOff)

# Создаём копию пода с изменённой командой на shell
kubectl debug myapp \
  --copy-to=myapp-debug \
  --container=myapp \
  -- /bin/sh
```

| Параметр | Описание |
|:---|:---|
| `--container=myapp` | Имя контейнера для изменения команды |
| `-- /bin/sh` | Новая команда запуска |

> **Без `--container`:** `kubectl debug` создаст **новый** ephemeral контейнер с указанной командой, а не изменит существующий.

### Сценарий 5: Изменение образа контейнера

**Проблема:** Нужно отладить pod с изменённым образом (добавить утилиты).

```bash
# Создаём pod
kubectl run myapp --image=myapp:1.0

# Создаём копию пода с изменённым образом
kubectl debug myapp \
  --copy-to=myapp-debug \
  --set-image=*=ubuntu:24.04
```

**Синтаксис `--set-image`:**

```bash
# Изменить образ ВСЕХ контейнеров на ubuntu
--set-image=*=ubuntu:24.04

# Изменить образ конкретного контейнера
--set-image=myapp=ubuntu:24.04
```

Синтаксис идентичен команде `kubectl set image`.

### Сценарий 6: Отладка на конкретной ноде

**Проблема:** Нужен доступ к файловой системе ноды или host-network.

```bash
# Создаём ephemeral pod на конкретной ноде
kubectl debug node/mynode \
  -it \
  --image=ubuntu:24.04
```

**Особенности:**

- Имя debug-пода генерируется автоматически на основе имени ноды
- Файловая система ноды примонтирована в `/host` (непривилегированный доступ)
- Некоторые системные процессы могут быть недоступны без привилегий
- Альтернатива привилегированным подам, когда `securityContext.privileged` запрещён

> **Ограничение:** Без привилегий чтение некоторых `/proc` данных и выполнение команд может быть запрещено.

---

## Дополнительная информация

### Автоматическая генерация имён

Если не указано `--container`, `kubectl debug` автоматически генерирует имя ephemeral контейнера (например, `debugger-xxxx`).

### Сравнение методов отладки

| Метод | Применение | Создание нового пода | Изменение команды |
|:---|:---|:---|:---|
| `kubectl debug <pod>` | Добавить ephemeral контейнер | Нет | Нет |
| `kubectl debug <pod> --copy-to=<name>` | Копия пода для отладки | Да | Опционально |
| `kubectl debug <pod> --set-image` | Изменить образ | Опционально | Нет |
| `kubectl debug <pod> --container=<name> -- <cmd>` | Изменить команду | Опционально | Да |
| `kubectl debug node/<node>` | Отладка ноды | Да | N/A |

### Разрешённые поля ephemeral контейнеров

Полный список полей доступен в [официальной документации Kubernetes](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.29/#ephemeralcontainer-v1-core).

### Связанные разделы

- [Distroless debugging](../../../Docker/Docker_troubleshooting/debugging_distroless.md)
- [Troubleshooting Overview](../../Troubleshooting/troubleshooting_overview.md)
- [Pod Lifecycle](./pod_lifecycle_and_state.md)
- [Pod Practical Scenarios](./pod_practical_scenarios_commands.md)
- [Vault Agent Sidecar (shareProcessNamespace пример)](../../../Vault/guides/vault_agent/sidecar_pattern.md)
