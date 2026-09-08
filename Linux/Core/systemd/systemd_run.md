# systemd-run: Запуск временных юнитов и динамическое управление

## Определения

* **`systemd-run`** — системная утилита для динамического создания и запуска временных объектов управления (юнитов). Позволяет упаковывать произвольные команды в контекст `systemd` «на лету», обеспечивая их изоляцию, квотирование ресурсов и централизованное логирование без предварительного создания файлов конфигурации.
* **Временный юнит (Transient Unit)** — объект управления (обычно `.service`, `.scope` или `.timer`), создаваемый программно через API systemd. Такие юниты по умолчанию не сохраняются после перезагрузки и автоматически удаляются из памяти после завершения работы (если не указано иное). Ключевая особенность: конфигурация существует только в памяти PID 1, без файла на диске в `/etc/systemd/system`.
* **D-Bus / Varlink API** — механизмы межпроцессного взаимодействия, через которые `systemd-run` отправляет запрос на создание transient-юнита демону `systemd` (PID 1). Запрос транслируется в job, который добавляется в очередь зависимостей.
* **Job Mode (Режим задания)** — политика поведения при конфликте имен. Определяет, что произойдет, если transient-юнит с таким же именем уже существует: замена (`replace`), отказ (`fail`), изоляция (`isolate`) или параллельный запуск (`replace-irreversibly`).
* **Cgroup Delegation (Делегирование cgroup)** — передача управления подгруппами контрольных групп временному юниту. Без делегирования `systemd` не может эффективно применять лимиты ресурсов для отдельных transient-сервисов.

## Предварительные требования

### Версии и совместимость

* **systemd:** для всех рассматриваемых сценариев требуется systemd ≥ 230. Рекомендуется ≥ 247 (RHEL 9 / Ubuntu 22.04 / Debian 12) для полной поддержки `CPUQuotaPeriodSec=`, `MemoryPressure=`, cgroup v2 и современных директив sandboxing.
* **Ядро Linux:** поддержка cgroup v2 доступна начиная с ядра 4.15. Для PSI (Pressure Stall Information) и стабильного делегирования контроллеров рекомендуется ядро ≥ 5.4.
* **Права доступа:** создание системных transient-юнитов требует `root`. Для пользовательских transient-юнитов используется флаг `--user` и требуется активная сессия или включенный `lingering`.

### Проверка окружения

```bash
# Версия systemd
systemd --version
# → systemd 252 (252.4-1)

# Проверка поддержки cgroup v2
stat -fc %T /sys/fs/cgroup/
# → cgroup2fs

# Проверка доступных контроллеров
cat /sys/fs/cgroup/cgroup.controllers
# → cpu io memory pids

# Проверка, что systemd-run доступен
which systemd-run
# → /usr/bin/systemd-run
```

## Основные концепции

### Архитектура и механизм работы

`systemd-run` не запускает процесс напрямую. Вместо этого утилита:

1. **Формирует запрос** на создание transient-юнита с заданными параметрами (`ExecStart`, ресурсы, изоляция, пользователь).
2. **Передает запрос** демону `systemd` (PID 1) через D-Bus или Varlink API.
3. **Демон строит граф зависимостей** и помещает задание (`job`) в очередь. Если указан `--slice`, юнит встраивается в соответствующую ветку cgroup.
4. **Запускает процесс** в рамках новой контрольной группы (cgroup), привязанной к transient-юниту. Привязка гарантирует, что все дочерние процессы наследуют лимиты.
5. **Управляет жизненным циклом:** отслеживает выход процесса, применяет политики `Restart=` (если указано), собирает логи в `journald`.

По завершении процесса transient-юнит выгружается из памяти, если не использованы флаги `--remain-after-exit` или `--no-collect`.

### Режимы работы: Service против Scope

Критически важно понимать различие между основными режимами запуска:

| Режим | Флаг | Жизненный цикл | Описание |
| :--- | :--- | :--- | :--- |
| **Service** | (по умолчанию) | Независимый | Процесс запускается как дочерний от PID 1. Он продолжает выполнение, даже если вызывающая оболочка (shell) закрыта. `systemd-run ./backup.sh` создаёт transient service, которым systemd управляет как полноценным сервисом. |
| **Scope** | `--scope` | Связанный | Создаёт scope для процесса, который запускается непосредственно от текущего окружения. Процесс остаётся дочерним для вызывающего процесса, но попадает под управление `systemd` для применения лимитов ресурсов. Завершается при выходе из shell. |

**Поведение cgroup:**
* Обычный запуск (`./backup.sh`) — процесс становится частью cgroup текущего shell, без отдельного systemd unit.
* `systemd-run --scope ./backup.sh` — создаёт отдельный scope и помещает процесс под контроль systemd. У процесса появляется собственная cgroup, которую можно увидеть через `systemctl status run-*.scope`.

**Когда использовать scope:**
* Интерактивные задачи, отладка и временные ограничения ресурсов.
* Тяжёлые команды, которые не хочется превращать в постоянный unit.

### Жизненный цикл временных юнитов

По умолчанию временный сервис удаляется из памяти `systemd` сразу после завершения процесса. Однако это поведение можно изменить:
* **`--remain-after-exit`** — юнит остается в состоянии `active (exited)` после завершения процесса. Это позволяет изучить логи и статус завершения.
* **`--collect`** — (по умолчанию для большинства случаев) указывает `systemd` немедленно выгрузить юнит после его остановки. Если флаг не используется, юнит может висеть в состоянии `failed`, пока не будет сброшен вручную (`systemctl reset-failed`).

### Отсутствие файла конфигурации на диске

Не каждый systemd-юнит существует как файл в `/etc/systemd/system`. Transient unit создаётся прямо во время работы системы и может появиться без собственного unit-файла:

```bash
# Создание transient service
systemd-run --unit=backup-now /usr/local/bin/backup.sh

# Появляется unit:
systemctl status backup-now.service

# Но поиск файла ничего не даст:
find /etc/systemd/system -name '*backup-now*'
# → нет результатов
```

Потому что конфигурация существует только в памяти systemd.

### Управление ресурсами и иерархией

`systemd-run` позволяет на лету встраивать процессы в нужную ветку `cgroups`:
* **`--slice=<name>.slice`** — помещает юнит в указанный слайс (например, `background.slice`). Позволяет группировать временные задачи для совместного ограничения ресурсов.
* **`-p`, `--property=`** — установка любой директивы unit-файла. Примеры: `CPUWeight=200`, `MemoryMax=512M`, `IOWeight=100`.

### Основные флаги и параметры

Полный перечень флагов, разделенный по назначению:

| Флаг | Назначение | Пример |
| :--- | :--- | :--- |
| `--unit=NAME` | Имя transient-юнита | `--unit=backup-job` |
| `--system` | Создать системный юнит (по умолчанию для root) | `--system --unit=job` |
| `--user` | Создать пользовательский юнит | `--user --unit=my-task` |
| `--scope` | Режим scope вместо service | `--scope ./task.sh` |
| `--uid=USER` | Запустить процесс от указанного пользователя | `--uid=app-user` |
| `--gid=GROUP` | Запустить процесс от указанной группы | `--gid=app-group` |
| `--nice=N` | Установить приоритет планировщика (-20..19) | `--nice=10` |
| `--working-directory=DIR` | Установить рабочую директорию | `--working-directory=/srv/app` |
| `--description=STRING` | Описание юнита | `--description="Nightly cleanup"` |
| `--property=KEY=VALUE` | Директива unit-файла (можно повторять) | `-p MemoryMax=2G -p CPUQuota=50%` |
| `--slice=SLICE` | Целевой слайс | `--slice=background.slice` |
| `--on-active=TIME` | Запуск через указанный интервал | `--on-active="30min"` |
| `--on-calendar=SPEC` | Календарное расписание | `--on-calendar="daily"` |
| `--on-boot=SEC` | Запуск после загрузки (сек) | `--on-boot=300` |
| `--on-startup=SEC` | Запуск после старта systemd | `--on-startup=300` |
| `--on-unit-active=SEC` | Интервал после успешного запуска | `--on-unit-active=1h` |
| `--on-unit-inactive=SEC` | Интервал после завершения | `--on-unit-inactive=30min` |
| `--job-mode=MODE` | Политика конфликтов (`replace`, `fail`, `isolate`) | `--job-mode=fail` |
| `--wait` | Ждать завершения transient-юнита | `--wait --unit=job` |
| `--collect` | Собрать и выгрузить юнит после остановки | `--collect` |
| `--no-collect` | Не выгружать юнит автоматически | `--no-collect` |
| `--remain-after-exit` | Оставить юнит active (exited) после завершения | `--remain-after-exit` |
| `--signal=SIGNAL` | Сигнал для отправки при остановке | `--signal=SIGTERM` |
| `--terminate` | Принудительно завершить при остановке | `--terminate` |
| `--kill-who=WHO` | Кого убивать (`main`, `control`, `all`) | `--kill-who=all` |
| `--quiet` | Подавить вывод | `--quiet` |
| `--verbose` | Подробный вывод | `--verbose` |
| `--timer-property=KEY=VALUE` | Директива для transient-таймера | `--timer-property=AccuracySec=10s` |

## Практические сценарии

### 1. Ограничение ресурсов для тяжелых задач

Мгновенное наложение лимитов на сборку или аналитическую команду в текущей сессии.

```bash
systemd-run --scope -p MemoryMax=1G -p CPUQuota=50% ./build_project.sh
# → Процесс будет ограничен 1 ГБ RAM и половиной мощностей одного ядра.
```

**Валидация:**
```bash
# Проверка параметров cgroup
systemctl show run-*.scope \
  -p MemoryMax \
  -p CPUQuota \
  -p MemoryCurrent

# Дерево cgroups
systemd-cgls
```

### 2. Временная изоляция тяжёлой команды через `--scope`

Запуск уже существующего скрипта под контролем systemd без создания постоянного unit-файла. Подходит для интерактивных задач, отладки и разовых ограничений ресурсов.

```bash
# Обычный запуск — процесс становится частью cgroup текущего shell
./backup.sh

# Запуск через scope — создаётся отдельный transient unit
systemd-run --scope ./backup.sh

# Проверка: у процесса появилась собственная cgroup
systemctl status run-*.scope
```

Временно ограничиваем ресурсы:

```bash
# Не даём задаче использовать больше двух CPU (200% = 2 полных ядра)
systemd-run --scope -p CPUQuota=200% ./backup.sh

# Ограничиваем память
systemd-run --scope -p MemoryMax=2G ./backup.sh
```

**Проверка, что ограничение применилось:**

```bash
# Дерево cgroups
systemd-cgls

# Для конкретного scope — параметры ControlGroup, MemoryCurrent, MemoryMax
systemctl show run-*.scope \
  -p ControlGroup \
  -p MemoryCurrent \
  -p MemoryMax
```

### 3. Создание изолированной «песочницы» (Sandboxing)

Запуск потенциально небезопасного процесса с жестким ограничением прав.

```bash
systemd-run --wait --collect --user \
  -p PrivateTmp=yes \
  -p ProtectSystem=strict \
  -p CapabilityBoundingSet="" \
  -p NoNewPrivileges=yes \
  /usr/bin/python3 suspicious_script.py
# → Процесс запускается с пустой /tmp, неизменяемой ФС и без системных привилегий.
```

### 4. Динамические таймеры

Запуск задачи в будущем без засорения `/etc/systemd/system/`.

```bash
# Разовый запуск через 30 минут
systemd-run --on-active="30min" --unit=delayed-job.service /usr/local/bin/notify.sh

# Запуск каждые 4 часа
systemd-run --on-calendar="00/4:00:00" --unit=cleanup-task.service /usr/bin/find /tmp -mtime +1 -delete
```

### 5. Работа в контейнерах и удаленных системах

Интеграция с `systemd-machined` позволяет запускать задачи внутри контейнеров.

```bash
# Запуск команды внутри контейнера nspawn
sudo systemd-run -M my-container -p User=app-user /usr/bin/reindex-db.sh

# Запуск на удаленном хосте через SSH
systemd-run -H user@remote-host --user uptime
```

### 6. Анализ результата выполнения (Exit Status)

Использование `--remain-after-exit` для отложенной проверки.

```bash
systemd-run --unit=check-status --remain-after-exit /usr/bin/false
# Проверка результата позже
systemctl status check-status
# → Main PID: 1234 (code=exited, status=1/FAILURE)
# Очистка
systemctl stop check-status
```

### 7. Запуск под другим пользователем и группой

Для разовых задач, требующих выполнения от имени сервисного аккаунта, используются флаги `--uid` и `--gid`. Это избавляет от необходимости создавать постоянные unit-файлы с `User=`/`Group=` или использовать `sudo -u`.

```bash
# Запуск от имени пользователя app-user
sudo systemd-run --unit=app-task \
  --uid=app-user \
  --gid=app-group \
  -p MemoryMax=512M \
  /usr/local/bin/task.sh

# Валидация
systemctl show app-task.service -p User -p Group
# → User=app-user
# → Group=app-group
```

### 8. Управление приоритетом и рабочей директорией

```bash
# Снижение приоритета (nice=10) и смена рабочей директории
systemd-run --unit=low-prio-job \
  --nice=10 \
  --working-directory=/srv/batch \
  -p CPUQuota=20% \
  /usr/local/bin/batch-worker.sh
```

### 9. Интеграция с CI/CD пайплайнами

В CI/CD-средах `systemd-run` позволяет запускать одноразовые задачи сборки, тестирования или деплоя с гарантированными ресурсами и централизованным логированием.

```bash
# В контексте CI/CD агента
sudo systemd-run --unit=ci-build-${CI_JOB_ID} \
  --slice=ci-jobs.slice \
  -p MemoryMax=4G \
  -p CPUQuota=100% \
  -p IOWeight=50 \
  -p PrivateTmp=yes \
  -p ProtectSystem=strict \
  /usr/local/bin/ci-runner.sh \
    --job ${CI_JOB_ID} \
    --commit ${CI_COMMIT_SHA}

# Проверка статуса и логирования
systemctl status ci-build-${CI_JOB_ID}.service
journalctl -u ci-build-${CI_JOB_ID}.service -f
```

**Преимущества для CI/CD:**
* Каждая задача получает изолированный transient-юнит с собственным cgroup.
* Ресурсы ограничены на уровне ядра, а не через `nice`/`ulimit`.
* Логи автоматически попадают в `journald` с тегом юнита.
* При падении агента transient-юниты автоматически очищаются.

### 10. Переменные окружения и окружение

Для передачи переменных окружения используйте директиву `Environment=` через `--property`. Для сложных сценариев с множеством переменных создайте файл в `environment.d/` или используйте `EnvironmentFile=`.

```bash
# Передача отдельных переменных
systemd-run --unit=db-migrate \
  -p Environment="DB_HOST=10.0.0.1" \
  -p Environment="DB_PORT=5432" \
  /usr/local/bin/migrate.sh

# Или через файл (глобально для transient-юнита)
sudo systemd-run --unit=app-start \
  -p EnvironmentFile=/etc/myapp/env.production \
  /usr/bin/myapp
```

### 11. Обработка сигналов и корректное завершение

`systemd-run` наследует механизмы управления сигналами от systemd:

```bash
# Отправка специфического сигнала при остановке
systemd-run --unit=graceful-stop \
  --signal=SIGUSR1 \
  --terminate \
  -p TimeoutStopSec=30 \
  /usr/bin/myapp

# Игнорирование сигналов (для демонов, управляемых самими собой)
systemd-run --unit=supervised \
  -p IgnoreSIGPIPE=yes \
  -p KillSignal=SIGTERM \
  -p SendSIGKILL=no \
  /usr/bin/myapp
```

### 12. Валидация ресурсов перед массовым запуском

```bash
# Проверка доступных лимитов на хосте перед запуском серии transient-юнитов
systemctl show -p DefaultMemoryLimit -p DefaultCPUQuota system

# Запуск с валидацией: если лимит слишком низкий, systemd вернет ошибку
sudo systemd-run --unit=validated-job \
  -p MemoryMax=512M \
  -p CPUQuota=50% \
  /usr/local/bin/task.sh

# Проверка, что юнит создался и находится в нужном состоянии
systemctl is-active validated-job.service
# → active
```

## Диагностика и управление

### Поиск и идентификация transient-юнитов

Transient unit можно обнаружить даже если он был создан не через `systemd-run`, а скриптом, CI/CD или оркестратором.

```bash
# Список всех сервисов (включая transient)
systemctl list-units --type=service --all

# Для конкретного юнита — проверка признака transient
systemctl show backup-now.service \
  -p Transient \
  -p ExecStart \
  -p User \
  -p MainPID \
  -p FragmentPath

# Если Transient=yes — юнит создан в runtime.
# FragmentPath обычно не указывает на обычный unit-файл.
```

**Важно:** наличие systemd-сервиса в `systemctl status` ещё не означает, что его конфигурация лежит на диске. Если `Transient=yes`, часть или вся конфигурация существует только в runtime state PID 1.

### Источники transient-юнитов

Transient units создают не только вручную через `systemd-run`:
* **Скрипты администрирования**, которым нужен единый механизм запуска и логирования без создания постоянных файлов.
* **CI/CD-пайплайны**, запускающие одноразовые задачи сборки, тестирования или деплоя.
* **Оркестраторы и системы управления конфигурацией**, создающие сервисы под конкретную операцию.
* **Временные задания с ограничениями ресурсов**:

```bash
systemd-run \
  --unit=test-job \
  -p MemoryMax=2G \
  -p CPUQuota=50% \
  /usr/local/bin/task.sh
```

В таком случае systemd создаёт `.service` и `cgroup` на время выполнения задачи.

### Диагностика временных юнитов

```bash
# Список всех активных временных юнитов (часто с префиксом run-*)
systemctl list-units "run-r*"

# Просмотр параметров, примененных к временному юниту
systemctl show run-r12345.service

# Дерево контрольных групп
systemd-cgls

# Для scope-юнитов — параметры cgroup и потребления ресурсов
systemctl show run-*.scope \
  -p ControlGroup \
  -p MemoryCurrent \
  -p MemoryMax

# Чтение логов задачи в реальном времени
journalctl -u run-r12345.service -f

# Принудительная остановка временного юнита
systemctl stop run-r12345.service

# Просмотр exit-статуса
systemctl show run-r12345.service -p ExecMainStatus -p Result
```

### Типичные ошибки и решения

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Failed to connect to bus: No such file or directory` | Отсутствует D-Bus или не настроен `$XDG_RUNTIME_DIR` для `--user` режима. | Для системных юнитов: запускайте через `sudo`. Для пользовательских: убедитесь, что сессия активна или включен `lingering` (`loginctl enable-linger`). |
| `Unit name run-r12345.service is masked or invalid` | Конфликт имен или поврежденный симлинк маскирования. | Проверьте: `systemctl status run-r12345.service`. Если юнит не существует — это ожидаемо для уже завершенного transient-юнита. |
| `Property MemoryMax exceeds configured limit` | Запрос на превышение глобального лимита в `system.conf` или родительского slice. | Увеличьте `DefaultMemoryLimit=` в `/etc/systemd/system.conf` или снизьте запрашиваемый лимит. |
| `Transient unit vanished` | Юнит завершился быстрее, чем `systemd-run` успел его зарегистрировать (race condition). | Добавьте `--wait` или небольшой `ExecStartPre=/bin/sleep 1` для отладки. |
| `Failed at step Memory cgroup` | Ошибка delegation или ядро не поддерживает запрашиваемый контроллер. | Проверьте: `/sys/fs/cgroup/cgroup.controllers`. Убедитесь, что родительская cgroup делегирует контроллеры (`Delegate=yes` в родительском slice). |
| `Permission denied` при записи в cgroup | Отсутствуют права root или родительский slice не делегировал контроллер. | Запускайте через `sudo`. Проверьте `Delegate=yes` для родительского slice. |
| `CPUQuota` не применяется | Включен `CPUQuotaPeriodSec` с некорректным значением или отсутствует `CPUAccounting=`. | Установите `CPUAccounting=yes` явно через `--property`. Проверьте: `systemctl show <unit> -p CPUQuota`. |

## Рекомендации по эксплуатации (Best Practices)

1. **Именование:** Используйте осмысленные имена через `--unit=` с префиксом, отражающим owner (например, `ci-build-1234`, `backup-now`). Это упрощает поиск в `journalctl` и `systemctl`.
2. **Ресурсы всегда:** Для transient-юнитов, выполняющих значимую работу, всегда задавайте лимиты (`MemoryMax=`, `CPUQuota=`). Отсутствие лимитов чревато влиянием на соседние сервисы.
3. **Изоляция по умолчанию:** В CI/CD и для непроверенного кода применяйте `PrivateTmp=yes`, `ProtectSystem=strict`, `NoNewPrivileges=yes`.
4. **Логирование:** Не перенаправляйте stdout/stderr в файлы вручную. Используйте встроенное логирование `journald`: `journalctl -u <unit> -f`.
5. **Очистка:** После отладки удаляйте completed transient-юниты: `systemctl reset-failed` и `systemctl stop <unit>`. Для автоматической очистки используйте `--collect` (по умолчанию).
6. **Slice для группировки:** Для связанных transient-задач создавайте отдельный slice (`--slice=my-batch.slice`) с предuplifted лимитами, а не задавайте лимиты на каждый юнит индивидуально.
7. **Job mode:** В автоматизированных сценариях используйте `--job-mode=fail`, чтобы случайный дубликат не перезаписал running задачу.
8. **Валидация перед запуском:** Проверяйте синтаксис unit-файлов через `systemd-analyze verify` и состояние cgroup контроллеров перед массовым запуском transient-юнитов.
9. **User mode:** Для пользовательских transient-юнитов включайте `lingering`, если задача должна выполняться без активной сессии: `sudo loginctl enable-linger $USER`.
10. **Секреты:** Не передавайте пароли через командную строку (`--property=Environment="PASS=secret"`), так как они попадут в `ps` и `journalctl`. Используйте `systemd-creds` или `EnvironmentFile=` с правами `600`.

## Ограничения и крайние случаи (Edge Cases)

### Поведение при завершении родительского процесса

* **Service mode (по умолчанию):** transient-сервис продолжает работу после закрытия shell, так как он запущен PID 1. Завершение shell не влияет на сервис.
* **Scope mode (`--scope`):** scope привязан к сессии. При закрытии shell или завершении родительского процесса scope получает `SIGHUP` и останавливается. Это ожидаемое поведение для интерактивных задач.

### Поведение при перезагрузке

Transient-юниты по определению не выживают перезагрузку системы. Если требуется персистентность:
* Создайте постоянный unit-файл в `/etc/systemd/system/`.
* Используйте `systemd-run` с `--on-calendar` для динамических таймеров, но помните, что сам transient-таймер не переживет перезагрузку.

### Ограничения cgroup v1

* В системах с cgroup v1 `systemd-run` может не поддерживать все современные директивы (`CPUQuotaPeriodSec=`, `MemoryPressure=`).
* Рекурсивный подсчет ресурсов в `systemd-cgtop` отсутствует.
* Некоторые дистрибутивы (RHEL 7, CentOS 7) имеют устаревший systemd с ограниченной поддержкой transient-юнитов.

### Ограничения на количество transient-юнитов

* `systemd` не накладывает жестких лимитов на количество transient-юнитов, но каждый юнит потребляет память PID 1.
* В системах с большим количеством одновременно выполня transient-юнитов (>1000) возможна деградация производительности менеджера.
* Рекомендуется группировать связанные задачи в slice и использовать `systemd-run` только для действительно ad-hoc операций.

### Ограничения сигналов

* `systemd-run --signal=` отправляет сигнал только главному процессу (Main PID) юнита.
* Для multicast-сигналов всем процессам cgroup используйте `--kill-who=all` в combination с `--terminate`.
* Сигнал `SIGKILL` нельзя переназначить через `--signal=`.

### Взаимодействие с SELinux/AppArmor

* В enforcing-режиме SELinux может блокировать создание cgroup или запись в `memory.max`. Проверяйте логи: `ausearch -m avc -ts recent | grep systemd-run`.
* AppArmor-профили для systemd могут ограничивать доступ к `/usr/bin/systemd-run` или `dbus`. При ошибках проверьте: `journalctl -u systemd | grep DENIED`.

### Ограничения в контейнерах

* В контейнерах без полного systemd (Docker по умолчанию) `systemd-run` может отсутствовать или не иметь доступа к D-Bus хоста.
* В Podman с `--systemd=true` утилита работает корректно, если монтировать `/sys/fs/cgroup` и `/run/systemd`.
* В средах с оркестрацией контейнеров transient-юниты создаются на уровне узла, а не контейнера. Их использование оправдано только для node-level операций.

## Очистка и обслуживание

### Удаление завершенных transient-юнитов

```bash
# Сброс failed-юнитов (очищает список)
sudo systemctl reset-failed

# Принудительная остановка и удаление lingering-юнитов
sudo systemctl stop backup-now.service
sudo systemctl reset-failed backup-now.service
```

### Поиск orphaned transient-юнитов

```bash
# Юниты в состоянии failed или exited, которые остались из-за отсутствия --collect
systemctl --failed --type=service --no-legend | awk '{print $1}' | grep '^run-'
```

### Мониторинг transient-юнитов в production

```bash
# Список всех transient-юнитов (постоянный polling для мониторинга)
watch -n 5 'systemctl list-units --type=service --all --no-legend | grep -E "run-|Transient=yes"'

# Экспорт метрик cgroup для внешнего мониторинга
systemd-cgtop --batch --iterations=1 --raw | awk '\
  $1 ~ /\.service$/ || $1 ~ /\.scope$/ {print $1, $2, $3, $4}'
```

## Дополнительная информация

### Сравнение с обычным запуском

| Характеристика | Прямой запуск (`./app`) | `systemd-run` (service) | `systemd-run --scope` |
| :--- | :--- | :--- | :--- |
| **Логирование** | stdout/stderr терминала | Централизованно в `journald` | Централизованно в `journald` |
| **Ресурсы** | `ulimit` (базово) | Полный контроль `cgroups v2` | Полный контроль `cgroups v2` |
| **Выживание** | Зависит от родителя/SIGHUP | Независимо от сессии | Зависит от вызывающего shell |
| **Безопасность** | Права текущего пользователя | Настраиваемый Sandbox (Namespaces) | Права текущего пользователя |
| **cgroup** | Наследует cgroup родителя | Отдельный unit + cgroup | Отдельный scope + cgroup |
| **Перезагрузка** | Не выживает | Не выживает | Не выживает |
| **Создание unit-файла** | Нет | Нет (transient) | Нет (transient) |
| **Сигналы** | Наследует от shell | Обрабатываются PID 1 | Наследует от shell |
| **Nice/Приоритет** | Текущий nice | Настраиваемый | Настраиваемый |

### См. также

* [Таймеры systemd (Timers)](./timers.md) — для постоянных расписаний.
* [Журналирование (journald)](../../SystemAdministration/Logging/journald.md) — работа с логами.
* [Контрольные группы (cgroups)](../cgroups.md) — механизмы ограничения ресурсов.
* [Обзор системы systemd](./overview.md) — базовые принципы и архитектура.
* [Управление службами (systemctl)](./service_management.md) — базовые команды управления.
* [systemd-analyze: Диагностика](./performance.md) — проверка корректности расписаний (`calendar`).
* [Пользовательские службы](./user_services.md) — режим `--user` и linger.
* [Практические сценарии systemd](./systemd_practical_scenarios.md) — архитектурные паттерны.
