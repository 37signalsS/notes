# Управление службами через systemctl

## Определения

* **Служба (Service)** — в экосистеме `systemd` это процесс или группа процессов, жизненным циклом которых управляет система инициализации. Каждая служба описывается в текстовом юнит-файле (например, `nginx.service`).
* **`systemctl`** — центральная утилита командной строки для взаимодействия с менеджером `systemd`. Она позволяет изменять состояние системы, управлять службами, анализировать их свойства и настраивать параметры автозагрузки.
* **`run0`** — (systemd v256+) современная замена `sudo`, работающая через API менеджера служб. Позволяет запускать команды с повышенными привилегиями без использования SUID-битов.
* **Job (Задание)** — атомарная операция изменения состояния, поставленная в очередь `systemd`. При любой команде (`start`, `stop`, `reload`) утилита не выполняет действие немедленно, а строит граф зависимостей и помещает задания в очередь для параллельного или последовательного выполнения.
* **Транзакция** — механизм `systemd`, гарантирующий, что либо все зависимости удовлетворены и операция выполнена, либо вся операция откатывается при невозможности удовлетворить хотя бы одну зависимость.
* **Sub State (Подсостояние)** — детализированное состояние юнита, специфичное для его типа. Для сервисов это `running`, `exited`, `dead`, `failed`, `reloading` и др.

## Основные концепции

### Управление состоянием юнита

Базовые команды для изменения текущего состояния службы в режиме реального времени.

```bash
# Запуск и остановка
sudo systemctl start nginx.service
sudo systemctl stop nginx.service

# Перезапуск (полная остановка и новый запуск, приводит к простою)
sudo systemctl restart nginx.service

# Перечитывание конфигурации (без остановки процесса)
sudo systemctl reload nginx.service

# Отправка специфического сигнала процессам юнита
sudo systemctl kill -s SIGUSR1 nginx.service
```

#### Расширенные команды управления состоянием

| Команда | Описание | Техническая суть |
| :--- | :--- | :--- |
| **`try-restart <unit>`** | Перезапустить, только если юнит активен. | Если юнит `inactive` или `failed`, команда завершается без ошибки. Полезно в скриптах для избежания лишних операций. |
| **`try-reload-or-restart <unit>`** | Попытка reload, иначе restart, иначе нет. | Безошибочная версия `reload-or-restart`. Если reload не поддерживается (`Type=simple`), выполняется restart. |
| **`reload-or-restart <unit>`** | Reload если поддерживается, иначе restart. | Может вернуть ошибку, если юнит не активен. Для типов `oneshot` и `notify` reload часто недоступен. |
| **`isolate <target>`** | Переключение на указанный таргет. | Останавливает все юниты, не принадлежащие целевому таргету (кроме помеченных `IgnoreOnIsolate=yes`). Изменение volatile: действует только в текущей сессии и сбрасывается после перезагрузки. Используется для перехода в rescue/emergency режимы. |
| **`cancel <JOB>`** | Отмена задания в очереди. | Позволяет прервать запуск или остановку юнита, который еще не выполнен. ID задания можно получить через `list-jobs`. |
| **`list-jobs`** | Список заданий в очереди. | Показывает, какие старты/остановки запланированы, и их порядок. |
| **`reset-failed [UNIT...]`** | Сброс состояния failed. | Очищает счетчик сбоев и переводит юнит в `inactive`. Необходимо перед повторным запуском после `Restart=on-failure` exhaustion. |
| **`poweroff`** | Выключение системы. | Активирует `poweroff.target`. |
| **`reboot`** | Перезагрузка системы. | Активирует `reboot.target`. |
| **`suspend`** | Сон в оперативной памяти. | Активирует `sleep.target` с соответствующим ядерным вызовом. |
| **`hibernate`** | Сон на диск. | Запись RAM на диск и отключение питания. |
| **`halt`** | Остановка системы без выключения. | Активирует `halt.target`. |
| **`default`** | Переключение на таргет по умолчанию. | Эквивалентно `isolate default.target`. |
| **`rescue`** | Однопользовательский режим. | Активирует `rescue.target` с запросом root-пароля. |
| **`emergency`** | Аварийный режим. | Активирует `emergency.target` с корнем в read-only. |

### Анализ статуса и метаданных

Команда `status` — основной инструмент оперативной диагностики.

```bash
systemctl status nginx.service
# → ● nginx.service - A high performance web server
# →    Loaded: loaded (/lib/systemd/system/nginx.service; enabled; ...)
# →    Active: active (running) since Sat 2024-06-08 10:00:00 MSK; 1h ago
# →      Main PID: 1234 (nginx)
# →     Tasks: 2 (limit: 4915)
# →    Memory: 45.2M
# →    CGroup: /system.slice/nginx.service
```

**Мониторинг ресурсов через `status`:**

```bash
# Извлечение текущего использования памяти, CPU и задач из вывода status
systemctl status myapp.service | grep -E 'Memory:|CPU:|Tasks:'
```

**Ключевые поля статуса:**
* **`Loaded`** — путь к файлу на диске и статус автозагрузки (`enabled`/`disabled`).
* **`Active`** — текущее состояние (например, `active (running)`, `failed`, `inactive (dead)`).
* **`Main PID`** — идентификатор основного процесса.
* **`CGroup`** — контрольная группа, через которую `systemd` изолирует процессы и ограничивает ресурсы.

**Подсостояния (Sub States) для сервисов:**
* **`running`** — процесс активен и работает (для `Type=simple`/`forking`/`notify`).
* **`exited`** — процесс завершился успешно (для `Type=oneshot`).
* **`dead`** — юнит остановлен и не запущен.
* **`failed`** — юнит завершился с ошибкой или превысил лимиты.
* **`reloading`** — выполняется перезагрузка конфигурации.
* **`activating`** / **`deactivating`** — промежуточные состояния во время запуска или остановки.

Для автоматизации и программного доступа используются:
* **`systemctl is-active <unit>`** — возвращает только статус (`active`, `inactive` и т.д.).
* **`systemctl is-failed <unit>`** — возвращает `failed`, если юнит завершился с ошибкой.
* **`systemctl is-enabled <unit>`** — возвращает статус автозагрузки (`enabled`, `disabled`, `masked`, `static`, `indirect`).
* **`systemctl is-system-running`** — возвращает общее состояние системы (`running`, `degraded`, `starting`, `stopping`).
* **`systemctl show <unit>`** — выводит все внутренние свойства юнита в формате `Key=Value`. Используйте `-p` для выбора конкретного свойства:

```bash
# Переменные среды, переданные в сервис
systemctl show myapp.service -p Environment

# Живые метрики cgroup (MemoryCurrent — учтённый RSS процесса)
systemctl show -p MainPID,MemoryCurrent,TasksCurrent myapp.service
```

### Управление автозагрузкой и блокировка

| Команда | Описание | Техническая суть |
| :--- | :--- | :--- |
| **`enable <unit>`** | Включить автозапуск. | Создает симлинки в `/etc/systemd/system/*.wants/`. |
| **`disable <unit>`** | Отключить автозапуск. | Удаляет симлинки. |
| **`enable --now`** | Включить и запустить. | Комбинация `enable` и `start`. |
| **`mask <unit>`** | Полная блокировка. | Привязывает юнит к `/dev/null`. Его невозможно запустить даже вручную. |
| **`unmask <unit>`** | Снятие блокировки. | Удаляет ссылку на `/dev/null`. |
| **`set-default <target>`** | Таргет загрузки по умолчанию. | Перезаписывает симлинк `default.target` на заданный таргет. Действует на все последующие загрузки, но не меняет текущий режим. |
| **`get-default`** | Показать таргет по умолчанию. | Выводит имя таргета, на который ссылается `default.target`. |

**Важные нюансы:**
*   **Start vs Enable:** `start` запускает службу немедленно, но не сохраняет состояние после перезагрузки. `enable` настраивает автозапуск, но не запускает службу в текущий момент.
*   **Masking:** Это "жесткий" запрет. Если служба замаскирована, `systemd` откажется её запускать, даже если она потребуется другому юниту как зависимость.
*   **Static units:** Некоторые юниты (например, `.socket` или `.device`) имеют статус `static` — они не могут быть включены напрямую, но активируются автоматически при срабатывании зависимости.

### Архитектура и принцип работы systemctl

`systemctl` является клиентом для D-Bus API менеджера `systemd` (PID 1). При выполнении любой операции утилита:

1. **Формирует запрос** и передает его через D-Bus демону `systemd`.
2. **Демон строит граф зависимостей** для целевого юнита и вычисляет минимальный набор операций.
3. **Создает транзакцию** — атомарный набор заданий (`jobs`), которые могут выполняться параллельно, если между ними нет блокирующих связей (`After=`/`Before=`).
4. **Выполняет задания** в порядке приоритета. Если любая зависимость не может быть удовлетворена, вся транзакция откатывается.
5. **Обновляет состояние** юнитов и возвращает результат клиенту.

Понимание этого механизма важно для диагностики: `systemctl status` показывает состояние, актуальное на момент запроса, а не в момент выполнения команды. Если юнит находится в очереди (`activating`), его состояние может быстро измениться.

## Практические сценарии

### Анализ состава и проблем системы

```bash
# Показать все активные юниты
systemctl list-units

# Показать только юниты, завершившиеся с ошибкой
systemctl --failed
# Эквивалентно:
systemctl list-units --state=failed

# Показать только socket-юниты и их состояние
systemctl list-units --type=socket --all

# Показать зависимости службы
systemctl list-dependencies nginx.service
```

### Редактирование и переопределение (Overrides)

Никогда не редактируйте файлы в `/usr/lib/systemd/system/` напрямую, так как они затираются при обновлении пакетов.

1.  **Drop-in (Переопределение части настроек):**
    ```bash
    sudo systemctl edit nginx.service
    ```
    Это создаст файл в `/etc/systemd/system/nginx.service.d/override.conf`.

2.  **Full Edit (Полная копия):**
    ```bash
    sudo systemctl edit --full nginx.service
    ```
    Копирует системный файл в `/etc`, позволяя полностью заменить его содержимое.

**Важное правило для списков:** Если вы переопределяете директиву, которая может встречаться несколько раз (например, `ExecStart`), её нужно сначала очистить пустой строкой:
```ini
[Service]
ExecStart=
ExecStart=/usr/sbin/nginx -g 'daemon off;'
```

### Применение изменений и daemon-reload

#### Что делает `daemon-reload`

Команда `systemctl daemon-reload` заставляет `systemd` перечитать все файлы юнитов с диска и перестроить граф зависимостей. Она необходима после любого ручного изменения конфигурационных файлов (если не использовался `systemctl edit`). Сами запущенные процессы при этом **не перезапускаются**.

#### Последовательность действий
1.  Изменить файл конфигурации.
2.  Выполнить `sudo systemctl daemon-reload`.
3.  Перезапустить службу: `sudo systemctl restart <unit>`.

### Поиск реальной конфигурации сервиса

Иногда unit-файл выглядит нормально, но параметр, явно влияющий на работу сервиса, в нём отсутствует. Причина в том, что `systemd` собирает конфигурацию не только из основного файла, но и из drop-in переопределений.

#### Просмотр итоговой конфигурации

```bash
systemctl cat nginx.service
```

Команда покажет основной unit и применённые drop-in конфигурации, например:

```
/etc/systemd/system/nginx.service
/etc/systemd/system/nginx.service.d/override.conf
```

В `override.conf` может находиться параметр, отсутствующий в основном файле:

```ini
[Service]
LimitNOFILE=65535
Environment="APP_ENV=prod"
```

#### Поиск всех локальных изменений

```bash
# Для конкретного сервиса
systemd-delta nginx.service

# Общая сводка по всем переопределениям
systemd-delta
```

`systemd-delta` показывает unit-файлы, которые отличаются от поставленных системой, включая override.

#### Проверка эффективного состояния

```bash
systemctl show nginx.service \
  -p LimitNOFILE \
  -p Environment \
  -p FragmentPath \
  -p DropInPaths
```

Здесь отображается эффективное состояние запущенного юнита, а не просто содержимое файла. Если в drop-in изменён `User=app`, а в основном файле `User=nginx`, то `systemctl show` покажет `app`.

**Важно:** на production-сервере сервис может вести себя иначе после локального override. При странном поведении systemd-сервиса полезно разделять две вещи: что написано в unit-файле и какую конфигурацию PID 1 реально применил.

### Управление состоянием системы

```bash
# Переключение в rescue mode (однопользовательский, требует root-пароль)
sudo systemctl rescue

# Переключение в emergency mode (минимальный набор служб, корень в read-only)
sudo systemctl emergency

# Возврат к нормальному режиму (default target)
sudo systemctl default

# Блокировка сеанса (ингибирование sleep/suspend/hibernate)
systemctl inhibit --what=handle-lid-switch sleep
```

#### Переключение таргетов на лету vs режим по умолчанию

Два действия над режимом системы принципиально различаются — на экзамене LPI их специально путают:

* **`isolate`** — изменение режима **прямо сейчас**, в оперативной памяти. После перезагрузки всё вернётся к таргету по умолчанию.
* **`set-default`** — настройка режима **по умолчанию навсегда**: при каждой последующей загрузке система стартует в указанном состоянии.

```bash
# Зафиксировать текстовый многопользовательский режим на всех будущих загрузках
sudo systemctl set-default multi-user.target
# → Removed "/etc/systemd/system/default.target".
# → Created symlink "/etc/systemd/system/default.target" → "/usr/lib/systemd/system/multi-user.target".
# (точный путь к юниту зависит от дистрибутива)

# Проверить, какой таргет установлен по умолчанию
systemctl get-default
# → multi-user.target

# Переключиться в аварийный режим прямо сейчас, без перезагрузки
sudo systemctl isolate rescue.target
```

**Важно:** `isolate` принудительно останавливает все юниты, кроме входящих в целевой таргет, — сетевые службы и SSH-сессия обрываются мгновенно. Не запускайте `isolate rescue.target` или `isolate emergency.target` на боевом сервере по SSH: связь пропадёт, а вернуться в нормальный режим (`sudo systemctl default`) можно будет только с физической консоли.

Типичная ловушка экзамена: «как изменить конфигурацию для всех последующих загрузок?». `isolate` меняет режим только текущей сессии (сбросится после первого же ребута), а персистентное изменение дефолтного режима загрузки выполняет исключительно `set-default`.

### Работа с сокетами и таймерами

```bash
# Активация сокета (Socket Activation)
sudo systemctl enable --now docker.socket
systemctl status docker.socket

# Остановка сокета (не останавливает службу, если есть активные соединения)
sudo systemctl stop docker.socket

# Статус таймера
systemctl status backup.timer
sudo systemctl enable --now backup.timer
```

### Автоматизация и скриптование

```bash
# Проверка статуса в скриптах (возвращает 0 только для active)
systemctl is-active --quiet nginx.service && echo "OK" || echo "FAIL"

# Проверка автозагрузки
systemctl is-enabled --quiet nginx.service

# Проверка общего состояния системы (degraded = есть failed-юниты)
systemctl is-system-running
# → running / degraded / starting / stopping

# Просмотр очереди заданий
systemctl list-jobs
# → JOB   UNIT                 TYPE     STATE
# → 123   nginx.service        start    waiting

# Отмена задания по ID
sudo systemctl cancel 123

# Извлечение конкретного свойства для мониторинга
systemctl show nginx.service -p ActiveState -p SubState -p MainPID
# → ActiveState=active
# → SubState=running
# → MainPID=1234
```

### Сброс состояний и очистка

```bash
# Сброс failed-юнитов (очищает счетчик сбоев)
sudo systemctl reset-failed

# Сброс конкретного сервиса
sudo systemctl reset-failed backup-now.service

# Принудительная остановка lingering-юнита
sudo systemctl stop backup-now.service
sudo systemctl reset-failed backup-now.service
```

### Управление удаленными хостами и пользователями

*   **Удаленное управление (`-H`):**
    ```bash
    systemctl -H user@remote-host status nginx.service
    ```
*   **Пользовательские службы (`--user`):**
    ```bash
    systemctl --user status my-bot.service
    ```
    Подробнее: **[Пользовательские службы systemd](./user_services.md)**.

## Диагностика и журналы

*   **Логи в реальном времени:** `journalctl -u nginx.service -f`
*   **Проверка синтаксиса:** `systemd-analyze verify /etc/systemd/system/my-service.service`
*   **Сводка расхождений:** `systemd-delta` (показывает, какие файлы были переопределены).
*   **Анализ безопасности:** `systemd-analyze security nginx.service` — вычисляет Exposure Score.
*   **Анализ времени загрузки:** `systemd-analyze blame` — показывает, какие юниты тормозят загрузку.
*   **Визуализация зависимостей:** `systemd-analyze plot > graph.svg` — графическое представление временной шкалы загрузки.
*   **Очередь заданий:** `systemctl list-jobs` — показывает pending операции и их блокирующие зависимости.

## Таблица типичных ошибок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Job failed` при `start` | Отсутствует бинарный файл или ошибка прав доступа. | `journalctl -u <unit> -n 50`; проверьте `ExecStart` и права на файл. |
| `Unit is masked` | Юнит привязан к `/dev/null`. | `sudo systemctl unmask <unit>` перед запуском. |
| `Dependency failed` | Не удалось запустить зависимый юнит (`Requires=`/`Wants=`). | `systemctl list-dependencies <unit>`; проверьте failed-юниты. |
| `Ordering cycle` | Противоречивые `After=`/`Before=`. | `systemd-analyze critical-chain <unit>` для визуализации; пересмотрите порядок. |
| `Job is queued but not starting` | Блокирующая зависимость или `Condition*` не выполнена. | `systemctl list-jobs`; проверьте `ConditionPathExists=`, `ConditionVirtualization=`. |
| `Reload failed` | Юнит не поддерживает `SIGHUP` или reload сконфигурирован некорректно. | Используйте `restart` вместо `reload` или проверьте конфигурацию приложения. |
| `Timeout stop failed` | `ExecStop=` не завершился за `TimeoutStopSec=`. | Увеличьте таймаут или исправьте скрипт остановки. Проверьте `KillMode=`. |
| `Failed at step cgroup` | Ошибка delegation или отсутствие прав на запись в cgroup. | Проверьте `Delegate=yes` в родительском slice и права root. |
| `Unit entered failed state` | Процесс завершился с ненулевым кодом. | `journalctl -u <unit> -n 100 --no-pager`; проверьте `Restart=on-failure` и счетчик сбоев. |

## Рекомендации по эксплуатации (Best Practices)

1. **Reload vs Restart:** Используйте `reload` только если приложение гарантированно поддерживает перезагрузку конфигурации без потери соединений (nginx, haproxy, apache). Для остальных случаев предпочитайте `restart`.
2. **Try-* команды в скриптах:** В automation используйте `try-reload-or-restart` или `try-restart`, чтобы избежать ошибок при остановленных сервисах.
3. **Masking для защиты:** Замаскируйте ненужные или опасные сервисы (например, `telnet.socket`) вместо простого `disable`.
4. **Валидация перед применением:** Всегда запускайте `systemd-analyze verify /etc/systemd/system/my-service.service` после создания или изменения юнита.
5. **Наблюдаемость:** Используйте `systemctl status` как первую команду диагностики — она содержит последние логи, cgroup иерархию и статус зависимостей в одном выводе.
6. **Избегайте ручного редактирования `/usr/lib`:** Все изменения через `systemctl edit` или drop-in файлы в `/etc/systemd/system/`.
7. **Учет ресурсов:** Включайте `CPUAccounting=yes`, `MemoryAccounting=yes` в production-юнитах для детализированной наблюдаемости через `systemd-cgtop`.
8. **Ограничение TasksMax:** Устанавливайте `TasksMax=` для защиты от fork-бомб, особенно для публично доступных сервисов.
9. **Диспетчеризация сигналов:** Понимайте разницу между `SIGTERM` (вежливое завершение) и `SIGKILL` (принудительное). Настраивайте `TimeoutStopSec=` и `KillMode=` под поведение вашего приложения.
10. **Проверка после перезагрузки:** После изменений в юнитах, критичных для загрузки, выполняйте `systemctl daemon-reload && systemctl restart <unit>` и проверяйте `systemctl is-active` до перезагрузки.

## Ограничения и крайние случаи

* **Circular dependencies:** `systemd` принудительно разрывает циклы, удаляя одну из зависимостей. Это может привести к неожиданному поведению. Используйте `systemd-analyze critical-chain` для визуализации.
* **Masked dependencies:** Если юнит А требует юнит Б, а юнит Б замаскирован, запуск А завершится ошибкой, даже если Б не требуется для фактической работы.
* **Condition* директивы:** Они пропускают запуск без ошибки. `systemctl status` покажет `inactive (dead)` с пометкой `condition`, что может сбивать с толку в скриптах. Используйте `systemctl show -p ConditionResult` для проверки.
* **daemon-reload и running процессы:** `daemon-reload` не перезапускает running процессы. Если вы изменили `User=` или `Environment=`, изменения вступят в силу только после `restart`.
* **KillMode=control-group:** По умолчанию systemd убивает все процессы в cgroup при остановке. Для приложений, запускающих дочерние процессы (supervisord, s6), используйте `KillMode=mixed`, чтобы SIGTERM получил только основной процесс.
* **Boot-time ordering:** Директивы `After=` и `Before=` не создают логических зависимостей. Юнит может запуститься до зависимости, если последняя не активна, но порядок соблюдается только при успешной активации.
* **socket activation и ошибки:** Если сокет активен, но служба падает, `systemd` автоматически перезапустит её при новом соединении. Однако это создает латентность на первый запрос.
* **Static units:** Некоторые юниты имеют статус `static` и не могут быть включены/выключены через `enable/disable`. Они активируются только через зависимости. Попытка `enable` завершится ошибкой.

## Очистка и обслуживание

### Удаление устаревших unit-файлов

```bash
# Удаление unit-файла, созданного через edit --full
sudo rm /etc/systemd/system/nginx.service

# Удаление drop-in переопределения
sudo rm /etc/systemd/system/nginx.service.d/override.conf

# Применение изменений
sudo systemctl daemon-reload
```

### Снятие блокировок и сброс состояний

```bash
# Если юнит был замаскирован
sudo systemctl unmask nginx.service

# Сброс failed-состояния
sudo systemctl reset-failed nginx.service

# Принудительная остановка lingering-юнита
sudo systemctl stop backup-now.service
sudo systemctl reset-failed backup-now.service
```

### Очистка очередей и orphaned юнитов

```bash
# Отмена всех pending заданий
sudo systemctl cancel

# Поиск failed-транзиентных юнитов
systemctl --failed --type=service --no-legend | awk '{print $1}' | grep '^run-'

# Полная перезагрузка конфигурации (при массовых изменениях)
sudo systemctl daemon-reload
```

### Валидация после изменений

```bash
# Проверка синтаксиса конкретного юнита
systemd-analyze verify /etc/systemd/system/nginx.service

# Проверка всех юнитов в директории
systemd-analyze verify /etc/systemd/system/*.service

# Визуализация зависимостей
systemd-analyze plot > /tmp/systemd-graph.svg
```

## Дополнительная информация

### См. также

* [Обзор юнитов systemd](./systemd_units_overview.md) — классификация и жизненный цикл.
* [Структура юнит-файла](./systemd_unit_file_structure.md) — разбор секций и директив.
* [Типы сервисов systemd](./systemd_service_types.md) — подробнее о директиве `Type=`.
