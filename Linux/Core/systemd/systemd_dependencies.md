# Управление зависимостями в systemd

## Определения

* **Зависимости (Dependencies)** — механизмы системы инициализации `systemd`, определяющие логические взаимосвязи и временной порядок активации юнитов. Они позволяют строить сложный граф состояний системы, гарантируя запуск служб только при готовности необходимых ресурсов.
* **Логическая зависимость (Logic Dependency)** — определяет, должен ли один юнит быть активирован при запросе на активацию другого.
* **Порядок запуска (Ordering)** — определяет временную последовательность выполнения (кто за кем). **Важно:** логическая зависимость сама по себе не гарантирует очередность запуска.
* **Атомарная транзакция** — минимальный набор операций запуска/остановки, который `systemd` выполняет как единое целое. Если хотя бы одна зависимость не может быть удовлетворена, вся транзакция откатывается.
* **Очередь заданий (Job Queue)** — внутренний механизм `systemd`, где операции (`start`, `stop`, `reload`) ставятся в очередь и выполняются параллельно, если между ними нет блокирующих связей `After=`/`Before=`.
* **Циклическая зависимость (Ordering Cycle)** — ситуация, когда юнит А требует запуска перед Б, а Б — перед А. `systemd` принудительно разрывает цикл, удаляя одну из связей, что может привести к неожиданному поведению.
* **Условия (Conditions)** — директивы `Condition...` в секции `[Unit]`, которые пропускают запуск юнита без ошибки, если условие не выполнено. В отличие от логических зависимостей, условия не создают связей в графе.
* **Таргет-якорь (Target Anchor)** — специальный юнит `.target`, используемый как точка синхронизации для группы зависимостей (аналог runlevel).

## Основные концепции

### Архитектура разрешения зависимостей

При любой операции (`start`, `stop`, `reload`) `systemd` не выполняет действие немедленно. Вместо этого:

1. **Формирует запрос** через D-Bus и строит граф зависимостей для целевого юнита.
2. **Вычисляет минимальный набор** юнитов, которые нужно запустить/остановить.
3. **Создает транзакцию** — атомарный набор заданий (`jobs`), которые могут выполняться параллельно, если между ними нет блокирующих связей (`After=`/`Before=`).
4. **Выполняет задания** в порядке приоритета. Если любая зависимость не может быть удовлетворена, вся транзакция откатывается.

### Типы логических директив

Для обеспечения надежности рекомендуется всегда комбинировать логическую связь с директивами порядка (`After`/`Before`).

| Директива | Уровень связи | Поведение |
| :--- | :--- | :--- |
| **`Wants=`** | Слабая | Рекомендуемый метод. Пытается запустить зависимый юнит, но его сбой не мешает запуску основного. |
| **`Requires=`** | Сильная | Обязательный юнит. Если зависимость не может быть активирована, основной юнит завершится с ошибкой. |
| **`Requisite=`** | Проверочная | Проверяет, запущен ли юнит. Если нет — немедленный сбой основного юнита без попытки запустить зависимый. |
| **`Upholds=`** | Активная | (v247+) Пока запущен основной юнит, `systemd` будет следить за работой зависимого и перезапускать его при падении. |
| **`BindsTo=`** | Жесткая | Связывает жизненные циклы. Если зависимый юнит пропадает (например, извлечен диск), основной юнит мгновенно останавливается. |
| **`PartOf=`** | Групповая | Связывает юниты для операций `stop` и `restart`. Остановка/рестарт родителя повлечет те же действия для ребенка. |
| **`Conflicts=`** | Отрицательная | Взаимное исключение. Запуск юнита А автоматически останавливает юнит Б. |

> **Различие `Requires=` и `Requisite=`:** `Requires=` активно запускает зависимость, `Requisite=` только проверяет её состояние. Используйте `Requisite=`, когда зависимость управляется внешним процессом (например, D-Bus service), и вы не хотите, чтобы `systemd` пытался её запустить.

### Директивы порядка запуска (Ordering)

| Директива | Поведение |
| :--- | :--- |
| **`After=`** | Текущий юнит начнет запуск только после **успешного завершения** активации перечисленных юнитов. |
| **`Before=`** | Текущий юнит должен полностью запуститься до того, как начнется активация перечисленных юнитов. |

> **Критическое правило:** Всегда используйте `After=` совместно с `Requires=`. Без `After=` оба юнита начнут запускаться одновременно (параллельно), что приведет к ошибке, если основной юнит обратится к еще не готовой зависимости.

### Условия и зависимости

Директивы `Condition...` и `Assert...` работают на стыке зависимостей и условий запуска:

* **`Condition...`** — пропускают запуск без ошибки, если условие не выполнено. Не создают логических зависимостей в графе.
* **`Assert...`** — прерывают запуск с критической ошибкой, если условие не выполнено.

Часто используемые условия:

| Директива | Назначение |
| :--- | :--- |
| `ConditionPathExists=` | Проверка наличия файла/директории. Префикс `!` инвертирует условие. |
| `ConditionDirectoryNotEmpty=` | Проверка, что директория не пуста. |
| `ConditionVirtualization=` | Проверка типа контейнера или гипервизора. |
| `ConditionEnvironment=` | Наличие переменной окружения. |
| `ConditionSecurity=` | Проверка наличия security-фичи (например, `ConditionSecurity=selinux`). |
| `ConditionACPower=` | Проверка, что система работает от сети, а не от батареи. |

### Распространение команд (Propagation)

В сложных архитектурах (например, Proxy + Backend) требуется передача сигналов перезагрузки:

* **`PropagatesReloadTo=`** — передает команду `reload` указанным юнитам.
* **`ReloadPropagatedFrom=`** — принимает команду `reload` от указанных юнитов.
* **`PropagatesStopTo=`** / **`StopPropagatedFrom=`** — аналогично для команд остановки.

### Секция [Install]: Связывание с таргетами

Директивы секции `[Install]` определяют, как юнит связывается с таргетами при выполнении `systemctl enable`:

| Директива | Поведение |
| :--- | :--- |
| **`WantedBy=`** | Создает символическую ссылку в `.wants/` указанного юнита. Слабая связь. |
| **`RequiredBy=`** | Создает символическую ссылку в `.requires/` указанного юнита. Сильная связь. |
| **`Also=`** | Список юнитов, которые нужно включить/выключить вместе с текущим. |
| **`Alias=`** | Альтернативное имя юнита. |
| **`DefaultInstance=`** | Для шаблонов — экземпляр по умолчанию при включении. |

> **Практический нюанс:** `WantedBy=` создает лишь символическую ссылку. Если целевой таргет (`multi-user.target`) не активен, связь не сработает. `RequiredBy=` работает аналогично, но создает ссылку в `.requires/`.

## Практические сценарии

### 1. Ожидание сетевой связности

Для сервисов, которым недостаточно простого наличия сетевого стека, а требуется активный IP и доступ к сети.

```ini
[Unit]
Description=Cloud Backup Agent
# Пытаемся запустить сеть, если она не запущена
Wants=network-online.target
# Ждем фактической готовности сети
After=network-online.target
```

### 2. Связка приложения с базой данных

Классический пример использования сильной зависимости.

```ini
[Unit]
Description=Web API Service
Requires=postgresql.service
After=postgresql.service
```

### 3. Использование Sidecar-агента (v247+)

Если приложению нужен вспомогательный сервис (например, `fluent-bit` для сбора логов), который должен работать «тенью».

```ini
[Unit]
Description=Main App with Log Shipper
Upholds=fluent-bit.service
After=fluent-bit.service
```

### 4. Привязка к физическому устройству

Для сервисов, работающих с монтируемыми томами или специфическим оборудованием.

```ini
[Unit]
Description=Database on External SSD
BindsTo=dev-disk-by\x2duuid-xxx.device
After=dev-disk-by\x2duuid-xxx.device
```

### 5. Многоуровневое приложение (Multi-Tier)

Для распределенных приложений с несколькими уровнями зависимостей. Используйте слабые связи между уровнями, чтобы сбой нижнего уровня не каскадировал вверх.

```ini
# /etc/systemd/system/frontend.service
[Unit]
Description=Frontend Nginx
Wants=api.service
After=api.service

# /etc/systemd/system/api.service
[Unit]
Description=API Backend
Wants=cache.service
After=cache.service
Requires=database.service
After=database.service

# /etc/systemd/system/cache.service
[Unit]
Description=Redis Cache
Wants=database.service

# /etc/systemd/system/database.service
[Unit]
Description=PostgreSQL Primary
```

### 6. Зависимости шаблонных экземпляров

При использовании шаблонов (`user@.service`) можно создавать зависимости на конкретные экземпляры:

```ini
# /etc/systemd/system/vpn@.service
[Unit]
Description=VPN Tunnel for %i
After=network-online.target
Wants=network-online.target
# Зависимость от уникального устройства tun%i
BindsTo=sys-subsystem-net-devices-tun%i.device
After=sys-subsystem-net-devices-tun%i.device
```

### 7. Передача перезагрузки конфигурации

Для сервисов, которые должны перезагружать конфигурацию вместе с зависимым прокси:

```ini
# /etc/systemd/system/app.service
[Unit]
PropagatesReloadTo=proxy.service

[Service]
ExecReload=/bin/kill -HUP $MAINPID
```

При `systemctl reload app.service` сигнал `SIGHUP` также будет отправлен `proxy.service`.

### 8. Режим обслуживания (Maintenance Mode)

Используйте `Conflicts=` для автоматического останавливания сервисов при включении режима обслуживания:

```ini
# /etc/systemd/system/maintenance.target
[Unit]
Description=Maintenance Mode
Conflicts=nginx.service postgresql.service
After=nginx.service postgresql.service

# Активация:
# sudo systemctl isolate maintenance.target
```

### 9. Зависимости через socket-activation

Вместо прямых `After=`/`Requires=` используйте socket-activation для отложенного запуска. Это убирает сервис из критической цепи загрузки:

```ini
# /etc/systemd/system/ssh.socket
[Socket]
ListenStream=22

[Install]
WantedBy=sockets.target

# /etc/systemd/system/ssh@.service
[Unit]
Description=SSH Per-Connection Daemon
After=network-online.target
```

### 10. Временные юниты с зависимостями

`systemd-run` позволяет создавать временные сервисы с зависимостями без правки файлов:

```bash
sudo systemd-run --unit=backup-job \
  --description="One-shot backup" \
  --requires=database.service \
  --after=database.service \
  --property=MemoryMax=1G \
  /usr/local/bin/backup.sh
```

### 11. Drop-in переопределение зависимостей

Изменение зависимостей без редактирования основного unit-файла (например, для пакетного сервиса):

```bash
sudo systemctl edit nginx.service
```

Создаст `/etc/systemd/system/nginx.service.d/override.conf`:

```ini
[Unit]
Requires=network-online.target
After=network-online.target
```

### 12. Управление зависимостями через цель (Target)

Создайте виртуальный таргет для группировки связанных сервисов:

```ini
# /etc/systemd/system/myapp.target
[Unit]
Description=MyApp Stack Target
Requires=database.service redis.service
After=database.service redis.service

# /etc/systemd/system/frontend.service
[Unit]
Wants=myapp.target
After=myapp.target
```

## Диагностика и отладка

### Анализ дерева зависимостей

```bash
# Кто нужен моему сервису (прямые зависимости)
systemctl list-dependencies my-app.service

# Кому нужен мой сервис (обратные зависимости)
systemctl list-dependencies --reverse my-app.service

# Все зависимости, включая неактивные
systemctl list-dependencies --all my-app.service
```

### Инспекция свойств зависимостей

```bash
# Показать все свойства юнита, включая зависимости
systemctl show my-app.service -p Requires,Wants,After,Before,BindsTo,PartOf,Conflicts

# Проверить результат выполнения Condition* директив
systemctl show my-app.service -p ConditionResult

# Проверить, какие юниты были переопределены
systemd-delta
```

### Визуализация графа

```bash
# Граф всех сервисных зависимостей
systemd-analyze dot --to-pattern='*.service' --from-pattern='*.service' | dot -Tsvg > deps.svg

# Граф конкретного сервиса
systemd-analyze dot my-app.service | dot -Tsvg > my-app-deps.svg

# Рекурсивный список с типами
systemd-analyze list-dependencies my-app.service
```

### Поиск циклических зависимостей

Ситуация, когда А требует Б, а Б требует А, приводит к ошибке `Found ordering cycle on...`. `systemd` принудительно разрывает цикл, удаляя один из юнитов.

```bash
# Поиск в журнале текущей загрузки
journalctl -b | grep "ordering cycle"

# Визуализация критической цепи для конкретного юнита
systemd-analyze critical-chain my-app.service

# Проверка синтаксиса на циклические ссылки
systemd-analyze verify /etc/systemd/system/my-app.service
```

### Анализ влияния на загрузку

Если зависимости выстроены неэффективно, загрузка превращается в «паровозик» (последовательный запуск), что увеличивает общее время старта.

```bash
# Поиск самого длинного пути в графе загрузки
systemd-analyze critical-chain

# Список самых медленных юнитов
systemd-analyze blame

# Дамп внутреннего состояния (таймауты, свойства, зависимости)
systemd-analyze dump my-app.service

# Проверка очереди заданий (заблокированные старты)
systemctl list-jobs
```

## Диагностика и устранение неисправностей

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Dependency failed` | Не удалось запустить зависимый юнит (`Requires=`/`Wants=`). | `systemctl list-dependencies <unit>`; проверьте failed-юниты. | Исправьте или отключите проблемную зависимость. |
| `Ordering cycle` | Противоречивые `After=`/`Before=`. | `systemd-analyze critical-chain <unit>` для визуализации. | Пересмотрите порядок зависимостей. |
| `Found ordering cycle on ...` | Циклические зависимости. | `systemd-analyze critical-chain <unit>` | Разорвите цикл; пересмотрите `After=`/`Before=`. |
| `Job is queued but not starting` | Блокирующая зависимость или `Condition*` не выполнена. | `systemctl list-jobs`; проверьте `ConditionPathExists=`, `ConditionVirtualization=`. | Убедитесь, что условия выполнены. |
| `Unit is masked` | Юнит заблокирован на уровне файловой системы. | `systemctl status <unit>` | `systemctl unmask <unit> && systemctl daemon-reload` |
| `ConditionPathExists=... failed` | Файл/директория не существует. | `systemd-analyze verify <unit>` | Создайте путь или настройте `ConditionPathExists=`. |
| `Conflicts=` не останавливает цель | `Conflicts=` работает только при активации одного из юнитов. | `systemctl status <unit>` | Используйте `systemctl stop` явно или `Before=` с `Conflicts=`. |
| `PartOf=` не останавливает ребенка | `PartOf=` срабатывает только при остановке/рестарте родителя, не при падении. | `systemctl show <parent> -p PartOf` | Добавьте `BindsTo=` если нужно поведение «падает вместе». |
| `BindsTo=` срабатывает на missing device | Устройство отключено, но юнит должен оставаться активным. | `systemctl status <unit>` | Замените `BindsTo=` на `Requires=` для устройств, которые могут временно исчезать. |
| Зависимость не применяется после редактирования | Выполнено изменение unit-файла, но `daemon-reload` не запущен. | `systemctl status <unit>` | `systemctl daemon-reload && systemctl restart <unit>` |

## Рекомендации

1. **Всегда комбинируйте `Requires=` с `After=`:** Без `After=` зависимость может запуститься параллельно, что вызовет гонку состояний.
2. **Предпочитайте `Wants=` сильным связям:** Используйте `Requires=` только для критически важных зависимостей. Слабые связи повышают отказоустойчивость.
3. **Используйте `Conflicts=` для взаимного исключения:** Если два сервиса не могут работать одновременно (например, активный/standby), `Conflicts=` автоматически управляет переключением.
4. **Группируйте через таргеты:** Для сложных стеков создайте виртуальный `.target` с агрегированными зависимостями, а остальные сервисы ссылайтесь на него через `Wants=`.
5. **Socket-activation вместо постоянных зависимостей:** Для сервисов с низкой частотой обращений используйте socket-activation, чтобы убрать их из критической цепи загрузки.
6. **Аудитируйте переопределения:** Регулярно запускайте `systemd-delta` для обнаружения локальных изменений и drop-in оверлеев, которые могут ломать зависимости.
7. **Не забывайте про `daemon-reload`:** Любое изменение зависимостей в unit-файле требует `systemctl daemon-reload` перед применением.
8. **Избегайте глубоких цепочек:** Каждый уровень `After=` добавляет латентность. Где возможно, группируйте сервисы под общим таргетом и делайте их параллельными.
9. **Используйте шаблоны для экземпляров:** `myapp@.service` с `%i` позволяет управлять dozens экземплярами с единой конфигурацией зависимостей.
10. **Документируйте rationale:** В комментариях unit-файла указывайте, почему выбрана именно эта связь (особенно для неочевидных `BindsTo=` или `Conflicts=`).

## Ограничения и крайние случаи

* **Циклические зависимости:** `systemd` принудительно разрывает циклы, удаляя одну из зависимостей. Это может привести к неожиданному поведению. Используйте `systemd-analyze critical-chain` для визуализации.
* **Masked dependencies:** Если юнит А требует юнит Б, а юнит Б замаскирован, запуск А завершится ошибкой, даже если Б не требуется для фактической работы.
* **Condition* директивы:** Они пропускают запуск без ошибки. `systemctl status` покажет `inactive (dead)` с пометкой `condition`, что может сбивать с толку в скриптах. Используйте `systemctl show -p ConditionResult` для проверки.
* **daemon-reload и running процессы:** `daemon-reload` не перезапускает running процессы. Если вы изменили `User=` или `Environment=`, изменения вступят в силу только после `restart`.
* **After= на failed-юниты:** Если юнит, указанный в `After=`, завершился с ошибкой (`failed`), текущий юнит все равно может запуститься, если связь слабая (`Wants=`). Сильная связь (`Requires=`) откажет.
* **BindsTo= и transient-юниты:** Если зависимый юнит является временным (transient) и завершается, `BindsTo=` немедленно остановит основной юнит. Это может быть нежелательно для фоновых задач.
* **Conflicts= и порядок запуска:** `Conflicts=` не вляет на порядок запуска. Добавьте `Before=` или `After=`, если нужна детерминированная последовательность.
* **network-online.target:** Может никогда не наступить, если `systemd-networkd-wait-online` или `NetworkManager-wait-online` зависают. Используйте `ConditionPathExists=/run/systemd/netif/links/2` для проверки конкретного интерфейса.
* **PartOf= и падения:** `PartOf=` не вызывает остановку дочернего юнита при падении родителя. Используйте `BindsTo=` для каскадного падения.
* **Requires= с Condition...:** Если `Requires=` указан, но `Condition...` не выполнен, юнит пропускается. Зависимость не запускается, но и ошибки не возникает.
* **Static units:** Статические юниты (генерируемые из fstab или udev) не имеют файлов на диске. Их зависимости нельзя изменить без создания оверлея в `/etc/systemd/system/`.

## Очистка и обслуживание

### Удаление зависимостей

```bash
# Удалить drop-in переопределение
sudo rm /etc/systemd/system/my-app.service.d/override.conf

# Убрать символическую ссылку автозапуска
sudo systemctl disable my-app.service

# Отменить маскировку зависимого юнита
sudo systemctl unmask postgresql.service
```

### Проверка после изменений

```bash
# Перечитать конфигурацию
sudo systemctl daemon-reload

# Проверить синтаксис
systemd-analyze verify my-app.service

# Визуализировать новые зависимости
systemd-analyze dot my-app.service | dot -Tsvg > deps-after.svg

# Проверить, что нет циклических ссылок
systemd-analyze critical-chain my-app.service
```

### Возврат к исходному состоянию

```bash
# Откатить все локальные изменения в unit-файлах (только для пакетных юнитов)
sudo systemctl revert my-app.service

# Удалить все drop-in'ы для конкретного юнита
sudo rm -rf /etc/systemd/system/my-app.service.d/

# Очистить кэш зависимостей (необязательно, daemon-reload обычно достаточно)
sudo systemctl daemon-reload
```

## Дополнительная информация

### См. также
* [Обзор юнитов systemd](./systemd_units_overview.md) — фундаментальные типы объектов управления.
* [Структура юнит-файла](./systemd_unit_file_structure.md) — детальный разбор всех секций, включая `[Install]` и условия.
* [Диагностика загрузки (boot_troubleshooting)](./boot_troubleshooting.md) — решение проблем с «зависшими» зависимостями.
* [Типы сервисов (systemd_service_types)](./systemd_service_types.md) — как тип запуска влияет на определение «готовности» для `After=`.
* [Анализ производительности (performance)](./performance.md) — `systemd-analyze critical-chain`, `dot`, `dump` для визуализации графов.
