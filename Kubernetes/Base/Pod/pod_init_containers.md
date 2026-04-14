# Init Containers

## Определения

**Init Container** — специализированный контейнер, который запускается перед основными контейнерами приложения и должен успешно завершиться до их запуска. Init-контейнеры выполняются последовательно, в порядке объявления в спецификации пода. Могут содержать утилиты, скрипты настройки или код, не представленный в образе основного приложения.

**Native Sidecar** — механизм Kubernetes 1.29+ (stable в 1.33+), позволяющий определить sidecar как init-контейнер с `restartPolicy: Always`, работающий на протяжении всего жизненного цикла пода ([KEP-3839](https://github.com/kubernetes/enhancements/blob/master/keps/sig-node/3839-sidecar-containers.md)).

Подробнее о sidecar-паттернах: [Sidecar Patterns](./pod_sidecar_patterns.md).

---

## Базовые концепции

### Назначение и сценарии

Init-контейнеры подходят для выполнения подготовительных задач, отделённых от логики основного приложения:

| Сценарий | Описание |
| :--- | :--- |
| Подготовка конфигурации | Генерация или модификация конфигурационных файлов для основного приложения |
| Ожидание зависимостей | Блокировка запуска до доступности внешних сервисов (БД, API) |
| Миграции БД | Запуск скриптов обновления схемы БД перед стартом приложения |
| Управление правами | Изменение прав на файлы в томах для непривилегированного пользователя |
| Скачивание артефактов | Загрузка файлов, библиотек или бинарников из репозитория |
| Клонирование репозиториев | Инициализация volume с кодом или данными из Git |
| Генерация конфигов из шаблонов | Динамическое создание конфигурационных файлов с использованием значений пода (IP, hostname) |

**Преимущества использования init-контейнеров:**

- **Отделение инструментов от приложения** — не нужно включать утилиты (sed, nslookup, curl, python) в образ приложения
- **Безопасность** — init-контейнеры могут работать с повышенными правами доступа к файловой системе, не предоставляя их основному приложению
- **Блокировка запуска** — механизм «заморозки» основных контейнеров до выполнения требований (например, доступность БД)
- **Снижение attack surface** — инструменты настройки остаются в init-контейнере, не попадая в финальный образ приложения

**Порядок выполнения и запуск:**

1. Kubelet замораживает запуск контейнеров пода до готовности сети и хранилищ
2. Init-контейнеры запускаются **последовательно**, в порядке объявления в `spec.initContainers`
3. Каждый init-контейнер должен завершиться с кодом `0` перед запуском следующего
4. При ошибке kubelet перезапускает init-контейнер согласно `restartPolicy` пода
5. После успешного завершения всех init-контейнеров kubelet запускает основные контейнеры параллельно

**Ключевые отличия от обычных контейнеров:**

| Характеристика | Init Container | Обычный контейнер |
| :--- | :--- | :--- |
| Порядок запуска | До `containers`, **последовательно** | Параллельно после завершения всех init |
| Завершение | **Обязательно** завершается с кодом `0` | Работает до остановки (долгоживущий) |
| Probes | Не поддерживают `livenessProbe`, `readinessProbe`, `startupProbe` | Поддерживают все типы проб |
| Lifecycle hooks | Не поддерживают `postStart` / `preStop` | Поддерживают `postStart` и `preStop` |
| Порты в Service | Порты **не** агрегируются в Endpoints/Service | Порты доступны через Service |
| Состояние Ready | Под не переходит в `Ready` до завершения всех init | Определяется readiness probe |
| Поле статуса | `status.initContainerStatuses` | `status.containerStatuses` |
| Индикатор в `kubectl get pods` | `Init:X/Y` (например, `Init:0/2`, `Init:1/2`) | `Running`, `Completed` и т.д. |
| Перезапуск при `restartPolicy: Never` | Под переходит в `Failed` при ошибке init | Контейнер не перезапускается |

### Обработка ресурсов (Requests/Limits)

Init-контейнеры поддерживают все поля ресурсов, что и обычные контейнеры (requests/limits по CPU, memory), но kubelet обрабатывает их иначе при планировании пода.

**Правило расчёта эффективного запроса/лимита:**

Планировщик вычисляет ресурсы для пода по формуле:

```text
Эффективный request = max(init-контейнеры) + sum(app-контейнеры)
Эффективный limit   = max(init-контейнеры) + sum(app-контейнеры)
```

Где:

- `max(init-контейнеры)` — **наибольший** request/limit среди всех init-контейнеров (не сумма)
- `sum(app-контейнеры)` — **сумма** всех request/limit основных контейнеров

**Почему так:** Init-контейнеры запускаются последовательно, поэтому одновременно работает только один из них. Планировщик резервирует ресурсы для самого «тяжёлого» init-контейнера, а не для всех сразу.

**Практическое следствие:** Init-контейнеры могут резервировать значительные ресурсы для инициализации, которые не будут использоваться в течение всего жизненного цикла пода.

```yaml
# Пример: init-контейнер требует 512Mi, основной — 128Mi
# Планировщик зарезервирует: max(512Mi) + 128Mi = 640Mi
# Во время работы пода будет использоваться только 128Mi
```

> **Рекомендация:** Задавайте минимальные ресурсы для init-контейнеров, если они не требуют значительных ресурсов для выполнения (например, простой nslookup или sed).

### Политика перезапуска (Restart Policy)

- Init-контейнеры **всегда** используют `restartPolicy: OnFailure`, даже если на поде установлен `Always`
- При ошибке (ненулевой код выхода) kubelet перезапускает init-контейнер
- При успешном завершении init-контейнер не перезапускается
- Если на поде установлен `restartPolicy: Never` — при ошибке init-контейнера под переходит в фазу `Failed`

---

## Практические сценарии

### Ожидание зависимости

Init-контейнер ожидает доступности БД перед запуском основного приложения:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-init
spec:
  containers:
  - name: app-container
    image: my-app:1.0
    ports:
    - containerPort: 8080
  initContainers:
  - name: wait-for-db
    image: busybox:1.36
    command: ['sh', '-c', 'until nc -z db-service 5432; do echo "Waiting for DB..." && sleep 2; done']
```

### Ожидание нескольких сервисов

Под с двумя init-контейнерами, которые последовательно ожидают доступности сервисов `my-service` и `mydb` перед запуском основного приложения:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-multiple-inits
spec:
  containers:
  - name: myapp
    image: my-app:1.0
    ports:
    - containerPort: 8080
  initContainers:
  # Первый init-контейнер — ждёт my-service
  - name: wait-for-my-service
    image: busybox:1.36
    command: ['sh', '-c', 'until nslookup my-service; do echo "Waiting for my-service..." && sleep 1; done']
  # Второй init-контейнер — ждёт mydb (запустится только после первого)
  - name: wait-for-mydb
    image: busybox:1.36
    command: ['sh', '-c', 'until nslookup mydb; do echo "Waiting for mydb..." && sleep 1; done']
```

**Порядок запуска:**

1. `wait-for-my-service` — циклически проверяет доступность `my-service` через `nslookup`
2. После успешного завершения — запускается `wait-for-mydb`
3. После завершения обоих — запускается основной контейнер `myapp`

**Проверка статуса:**

```bash
kubectl get pod app-with-multiple-inits
# → Init:0/2  (ни один init-контейнер ещё не завершился)
# → Init:1/2  (первый завершился, второй работает)
# → 1/1       (все init завершены, основной контейнер работает)

# Просмотр логов конкретного init-контейнера
kubectl logs app-with-multiple-inits -c wait-for-my-service
kubectl logs app-with-multiple-inits -c wait-for-mydb

# Детальная информация
kubectl describe pod app-with-multiple-inits
# Раздел Events покажет: "Init container wait-for-my-service succeeded"
```

> **Важно:** Если сервисы ещё не созданы, init-контейнеры будут работать бесконечно. Убедитесь, что ожидаемые ресурсы существуют, или используйте `activeDeadlineSeconds` для ограничения времени.

**Идемпотентность и shared volumes:**

Init-контейнеры, записывающие файлы в `emptyDir` volume, должны быть готовы к тому, что файл уже существует после перезапуска:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: init-with-shared-volume
spec:
  volumes:
  - name: config-data
    emptyDir: {}
  containers:
  - name: app
    image: my-app:1.0
    volumeMounts:
    - name: config-data
      mountPath: /etc/config
  initContainers:
  - name: generate-config
    image: busybox:1.36
    command: ['sh', '-c', 'echo "db_host=mydb" > /config/app.conf || true']
    volumeMounts:
    - name: config-data
      mountPath: /config
```

> **Предостережение:** Файлы в `emptyDir` сохраняются между перезапусками init-контейнера. Код должен быть идемпотентным — проверять существование файла или перезаписывать его без ошибки.

### Подготовка контента с shared volume

Init-контейнер скачивает статический контент и передаёт его основному контейнеру nginx через общий `emptyDir` volume:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx-with-init
spec:
  volumes:
  - name: workdir
    emptyDir: {}
  containers:
  - name: nginx
    image: nginx:1.28
    ports:
    - containerPort: 80
    volumeMounts:
    - name: workdir
      mountPath: /usr/share/nginx/html
  initContainers:
  - name: install
    image: busybox:1.36
    command: ['wget', '-O', '/work-dir/index.html', 'https://info.cern.ch/']
    volumeMounts:
    - name: workdir
      mountPath: /work-dir
```

**Как это работает:**

1. Init-контейнер `install` запускается первым
2. Скачивает `index.html` с внешнего сайта в `/work-dir/` (общий `emptyDir` volume)
3. Init-контейнер завершается с кодом `0`
4. Запускается основной контейнер `nginx`
5. nginx монтирует тот же `emptyDir` в `/usr/share/nginx/html` — стандартную директорию для раздачи статики
6. nginx отдаёт скачанный init-контейнером файл вместо дефолтного приветствия

**Преимущество такого подхода:**

- Основной образ nginx не содержит утилит (`wget`, `curl`, `git`)
- Контент подготавливается до запуска приложения — nginx стартует с уже готовой статикой
- init-контейнер может содержать любые инструменты, не увеличивая attack surface основного приложения

**Проверка:**

```bash
# Отслеживание статуса пода
kubectl get pod nginx-with-init -w
# → PodInitializing  (init-контейнер работает)
# → Running          (init завершён, nginx запущен)

# Войти в основной контейнер
kubectl exec -it nginx-with-init -- bash

# Проверить содержимое
curl http://localhost
# → Вернёт контент, скачанный init-контейнером (не дефолтный nginx welcome)

# Посмотреть логи init-контейнера
kubectl logs nginx-with-init -c install
# → Connecting to info.cern.ch... saving to '/work-dir/index.html'
```

> **Важно:** Если init-контейнер записывает файл в тот же путь, где у основного образа уже есть файл (например, `/usr/share/nginx/html/index.html`), файл основного контейнера будет **переопределён** содержимым из shared volume.

---

## Дополнительная информация

### Диагностика статусов

При просмотре `kubectl get pod` статус пода с init-контейнерами отображается в формате `Init:X/Y`, где `X` — количество завершённых init-контейнеров, `Y` — общее количество:

| Статус | Расшифровка | Описание |
| :--- | :--- | :--- |
| `Init:0/2` | 0 из 2 завершено | Первый init-контейнер ещё не завершился (может быть в `Running` или `Waiting`) |
| `Init:1/2` | 1 из 2 завершено | Первый init-контейнер завершён, второй работает или ожидает |
| `PodInitializing` | Все init завершены | Основные контейнеры запускаются |
| `Running` | Все контейнеры работают | Init-контейнеры завершены, основные контейнеры активны |
| `Init:Error` | Ошибка init-контейнера | Init-контейнер завершился с ненулевым кодом выхода |
| `Init:CrashLoopBackOff` | Циклический краш init-контейнера | Init-контейнер несколько раз перезапускался и продолжает завершаться с ошибкой |

**Детальная диагностика через `kubectl describe pod`:**

```bash
kubectl describe pod <pod-name>
```

В выводе — разделы `Init Containers` и `Containers` с детализацией по каждому контейнеру:

| Состояние (State) | Причина (Reason) | Что означает |
| :--- | :--- | :--- |
| `Running` | — | Контейнер работает (init-контейнер в процессе выполнения) |
| `Waiting` | `PodInitializing` | Основной контейнер ждёт завершения init-контейнеров |
| `Waiting` | `CrashLoopBackOff` | Контейнер перезапускается после repeated crashes |
| `Terminated` | `Completed` | Контейнер успешно завершён (нормально для init-контейнера) |
| `Terminated` | `Error` | Контейнер завершился с ошибкой (ненулевой код выхода) |

**Ключевые команды диагностики:**

```bash
# Проверка статуса пода в реальном времени
kubectl get pod <pod-name> -w

# Детальная информация: контейнеры, команды, события
kubectl describe pod <pod-name>

# Логи init-контейнера
kubectl logs <pod-name> -c <init-container-name>

# Логи основного контейнера
kubectl logs <pod-name> -c <container-name>

# Логи в реальном времени (флаг -f)
kubectl logs <pod-name> -c <init-container-name> -f
```

**Сценарий дебага: под завис на `Init:0/2`:**

1. `kubectl describe pod <pod-name>` — проверить состояние init-контейнера и события
2. `kubectl logs <pod-name> -c <init-container-name>` — посмотреть вывод init-контейнера
3. Если init-контейнер ожидает внешний сервис (например, `nslookup my-service`) — убедиться, что сервис существует
4. Если сервис не создан — создать его или исправить имя в манифесте

**Сценарий дебага: `Init:CrashLoopBackOff`:**

1. `kubectl describe pod <pod-name>` — проверить количество рестартов и причину ошибки
2. `kubectl logs <pod-name> -c <init-container-name>` — посмотреть лог текущего экземпляра
3. `kubectl logs <pod-name> -c <init-container-name> --previous` — посмотреть лог предыдущего (упавшего) экземпляра
4. Проверить корректность команды (`command`/`args`) в манифесте

### Особенности поведения

**`activeDeadlineSeconds` и init-контейнеры:**

Параметр `activeDeadlineSeconds` на уровне пода ограничивает общее время жизни пода, включая init-контейнеры. Если deadline истекает во время работы init-контейнера — под будет завершён.

> **Рекомендация:** Не используйте `activeDeadlineSeconds` для подов с долгоживущими приложениями. Этот параметр предназначен для объектов `Job`, где контейнер выполняет задачу с ограниченным временем выполнения.

**Уникальность имён:**

Все контейнеры в поде (основные, init, sidecar) должны иметь уникальные имена. При дубликате kubelet вернёт ошибку валидации.

**Перезапуск init-контейнеров:**

Под может быть перезапущен с повторным выполнением init-контейнеров в следующих случаях:

- Инфраструктурный контейнер (pause container) был перезапущен вручную через container runtime на ноде
- Все контейнеры в поде завершились, и `restartPolicy: Always` потребовал перезапуска, но записи о выполнении init-контейнеров были потеряны из-за работы Pod Garbage Collector

**Изменение образа init-контейнера:**

Изменение образа init-контейнера в спецификации пода **не вызывает** автоматический перезапуск пода (в отличие от изменения образа основного контейнера в Deployment). Для применения изменений требуется пересоздать под вручную или через контроллер (Deployment, StatefulSet).

**Resource sharing:**

Init-контейнеры делят те же ресурсы CPU, memory и network с основным приложением, так как все контейнеры в поде находятся в одном cgroup и разделяют network namespace. Однако поскольку init-контейнеры работают последовательно, их ресурсы не суммируются при планировании.

**Security Context и volumes:**

Init-контейнеры поддерживают:

- `securityContext` (включая `privileged`, `runAsUser`, `capabilities`)
- Монтирование volumes (`emptyDir`, `configMap`, `secret`, `hostPath`, и другие)
- Переменные окружения и `envFrom`
- `command` и `args` для переопределения entrypoint

Init-контейнер может иметь доступ к файловой системе или секретам, которые не доступны основному приложению — это позволяет безопасно подготовить данные для основного контейнера.

## См. также

- [Жизненный цикл пода](./pod_lifecycle_and_state.md)
- [Sidecar Patterns](./pod_sidecar_patterns.md)
- [KEP-3839: Native Sidecar](https://github.com/kubernetes/enhancements/blob/master/keps/sig-node/3839-sidecar-containers.md)
