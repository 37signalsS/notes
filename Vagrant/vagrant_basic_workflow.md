# Базовый рабочий процесс в Vagrant

## Определения

**Жизненный цикл Vagrant (Vagrant Workflow)** — стандартизированная последовательность этапов управления виртуальной средой: от инициализации проекта до полной очистки ресурсов.

**Vagrantfile** — декларативный файл конфигурации на языке Ruby, описывающий целевое состояние инфраструктуры (Infrastructure as Code).

**Provisioning (Провижининг)** — процесс автоматической настройки гостевой ОС сразу после её запуска (установка ПО, конфигурация сервисов).

**Box** — базовый шаблон виртуальной машины, упакованный в формат `.box` и привязанный к конкретному провайдеру. Содержит предустановленную ОС и пользователя `vagrant`. Кэшируется в `~/.vagrant.d/boxes/`.

**Провайдер (Provider)** — программный слой виртуализации (VirtualBox, Libvirt/KVM, VMware, Hyper-V, QEMU), через который Vagrant создаёт и управляет ВМ. Vagrant служит унифицированным интерфейсом над разными гипервизорами.

**Снимок состояния (Snapshot)** — именованная точка восстановления ВМ, фиксирующая состояние диска и оперативной памяти. Позволяет мгновенно откатиться к стабильному состоянию перед рискованными операциями.

**Коммуникатор (Communicator)** — программный мост для отправки команд внутрь ВМ. Основные типы: `ssh` (Linux/macOS) и `winrm` (Windows). От коммуникатора зависят этап провижининга и монтирования общих папок.

**Плагин (Plugin)** — расширение CLI для поддержки провайдеров, автоматизации (vbguest, proxyconf) или интеграции с внешними системами.

## Базовые концепции

### Основные команды управления

| Команда | Действие | Технические детали |
| :--- | :--- | :--- |
| **`vagrant init`** | Инициализация | Создает `Vagrantfile`. Пример: `vagrant init bento/ubuntu-24.04`. |
| **`vagrant validate`**| Валидация | Проверяет Ruby-синтаксис и логику `Vagrantfile`. |
| **`vagrant up`** | Запуск | Поддерживает флаги: `--provider` (выбор гипервизора), `--provision` (принудительная настройка). |
| **`vagrant ssh`** | Подключение | Использует параметры из `.vagrant/` для входа под пользователем `vagrant`. |
| **`vagrant provision`**| Настройка | Запускает скрипты автоматизации на уже работающей ВМ. |
| **`vagrant reload`** | Перезагрузка | Эквивалент `halt` + `up`. Требуется для применения изменений в сетях или ресурсах. |
| **`vagrant halt`** | Остановка | Посылает сигнал завершения (ACPI) гостевой ОС. |
| **`vagrant destroy`** | Удаление | Уничтожает ВМ и освобождает диск. Флаг `-f` отключает подтверждение. |

### Жизненный цикл команды `vagrant up`

При запуске `vagrant up` Vagrant последовательно выполняет следующие этапы:

1. **Валидация** — проверка Ruby-синтаксиса `Vagrantfile`.
2. **Поиск образа** — проверка наличия box в `~/.vagrant.d/boxes/` или загрузка из удалённого репозитория.
3. **Создание ВМ** — вызов API провайдера для создания виртуальной машины.
4. **Загрузка ОС** — запуск ВМ и ожидание готовности коммуникатора (SSH/WinRM).
5. **Провижининг** — выполнение shell/ansible скриптов настройки.
6. **Монтирование** — создание общих папок (NFS, virtiofs, vboxsf).
7. **Информирование** — вывод итогового статуса и карты проброшенных портов.

На любом этапе может произойти сбой: от ошибок синтаксиса до нехватки ресурсов хоста. Для диагностики используйте `VAGRANT_LOG=debug`.

### Механизм выбора провайдера

Если в `Vagrantfile` описано несколько провайдеров, Vagrant выбирает один по следующим правилам (в порядке приоритета):

1. Явное указание в CLI: `vagrant up --provider=libvirt`.
2. Переменная окружения: `export VAGRANT_DEFAULT_PROVIDER=virtualbox`.
3. Первый найденный блок `config.vm.provider` в `Vagrantfile`.
4. Наличие установленного гипервизора в системе (по умолчанию ищется VirtualBox).

### Управление образами (Boxes)

Образы являются базовыми шаблонами и кэшируются глобально в системе.

```bash
# Список всех локально доступных образов
vagrant box list

# Проверка наличия обновлений для образов текущего проекта
vagrant box outdated

# Обновление до последней версии (требует перезапуска ВМ)
vagrant box update

# Удаление старых версий для экономии места
vagrant box prune

# Добавление образа из локального файла или URL
vagrant box add custom-image ./package.box
vagrant box add bento/ubuntu-24.04 --provider libvirt
```

### Создание переносимых образов (Packaging)

Используйте `vagrant package`, чтобы создать `.box` файл из текущей ВМ для передачи коллегам или повторного использования:

```bash
# Упаковка текущего состояния ВМ (должна быть остановлена)
vagrant package --output custom-dev-box-2026.01.box

# Проверка содержимого архива
tar -tzf custom-dev-box-2026.01.box | head -20
# → metadata.json
# → Vagrantfile
# → box.ovf
# → ...
```

### Управление плагинами

Плагины расширяют функциональность Vagrant (поддержка провайдеров, автоматизация, прокси).

```bash
# Список установленных плагинов
vagrant plugin list

# Установка плагина
vagrant plugin install vagrant-libvirt

# Обновление всех плагинов
vagrant plugin update

# Удаление плагина
vagrant plugin uninstall vagrant-old-plugin

# Полный сброс плагинов (при повреждении зависимостей)
vagrant plugin expunge --reinstall
```

### Снимки состояния (Snapshots)

Позволяют фиксировать стабильное состояние ВМ перед рискованными операциями.

| Команда | Описание |
| :--- | :--- |
| **`vagrant snapshot save <name>`** | Создает именованную точку восстановления (включая RAM и диск). |
| **`vagrant snapshot restore <name>`** | Мгновенный откат к состоянию снимка. |
| **`vagrant snapshot list`** | Дерево снимков для текущей ВМ. |

> **Примечание:** Поддержка снимков зависит от провайдера. VirtualBox и VMware поддерживают полные снимки (включая RAM). Libvirt поддерживает снимки только диска.

### Диагностика и глобальный статус

```bash
# Текущее состояние ВМ в директории проекта
vagrant status

# Карта проброшенных портов (Host -> Guest)
vagrant port

# Глобальный реестр всех машин Vagrant на данном хосте
vagrant global-status

# Очистка реестра от удаленных вручную машин
vagrant global-status --prune
```

## Практические сценарии

### Сценарий 1: Быстрый запуск и проверка

```bash
mkdir web-dev && cd web-dev
vagrant init bento/ubuntu-24.04
vagrant up --provider virtualbox
vagrant ssh -c "uptime"
# → result: отчет о времени работы и нагрузке ВМ
```

### Сценарий 2: Использование внешнего SSH-клиента (ssh-config)

Если вам нужно использовать нативный SSH, SCP или IDE (VS Code) для работы с ВМ.

```bash
# 1. Получение параметров подключения
vagrant ssh-config > v_config

# 2. Подключение через системный ssh
ssh -F v_config default
```

### Сценарий 3: Атомарный цикл разработки (Reload + Provision)

При изменении сетевых настроек и скриптов установки одновременно:

```bash
# Перезапуск с принудительным запуском всех провижинеров
vagrant reload --provision
```

### Сценарий 4: Экономия ресурсов (Suspend/Resume)

Для быстрого переключения между проектов без полной остановки сервисов.

```bash
# Сохранение состояния ВМ (включая RAM) в файл на диск — мгновенное восстановление
vagrant suspend

# Возобновление работы (быстрее чем vagrant up)
vagrant resume

# Штатное выключение: гостевая ОС корректно завершает работу
vagrant halt

# Проверка статуса
vagrant status
# → current state: saved (suspended)
```

**Важно:** При `suspend` время гостевой ОС останавливается. После `resume` возможен clock drift — настройте NTP внутри гостя.

### Сценарий 5: Валидация перед коммитом

Автоматическая проверка корректности `Vagrantfile` в pre-commit хуке или CI:

```bash
# Локальная проверка
vagrant validate
# → результат: Vagrantfile validated successfully

# В CI/CD пайплайне
if ! vagrant validate; then
  echo "ERROR: Invalid Vagrantfile"
  exit 1
fi
```

### Сценарий 6: Упаковка готовой ВМ в образ

Создание переносимого `.box` файла из настроенной ВМ:

```bash
# 1. Остановить ВМ
vagrant halt

# 2. Упаковать с описанием версии
vagrant package --output project-base-2026.01.box

# 3. Добавить в локальный реестр
vagrant box add project-base ./project-base-2026.01.box

# 4. Использовать в новом проекте
vagrant init project-base
```

### Сценарий 7: Добавление box из локального файла или URL

Для изолированных сред или кастомных образов:

```bash
# Из локального файла
vagrant box add custom-ubuntu ./ubuntu-24.04-custom.box

# Из URL с проверкой контрольной суммы
vagrant box add bento/ubuntu-24.04 \
  --url https://artifacts.example.com/boxes/ubuntu-24.04.box \
  --checksum sha256:e3b0c44298fc... \
  --checksum-type sha256

# С указанием провайдера
vagrant box add multi-provider-box ./box.libvirt.box --provider libvirt
```

### Сценарий 8: Инлайн-команды через SSH

Выполнение команд внутри ВМ без интерактивного сеанса:

```bash
# Однострочная команда
vagrant ssh -c "systemctl status nginx"

# Передача переменной окружения
APP_VERSION=2.1.0 vagrant ssh -c "echo Deploying $APP_VERSION"

# Выполнение скрипта с аргументами
vagrant ssh -c "bash -s" -- -c "arg1 arg2" < local-script.sh
```

### Сценарий 9: Полная очистка окружения

Безопасное удаление ВМ и очистка метаданных:

```bash
# 1. Остановка ВМ
vagrant halt

# 2. Удаление ВМ и дисков
vagrant destroy -f

# 3. Очистка глобального реестра от записей о удалённых машинах
vagrant global-status --prune

# 4. Удаление неиспользуемых версий образов
vagrant box prune --keep 1
```

### Сценарий 10: Неинтерактивный режим для CI/CD

Использование Vagrant в пайплайнах без подтверждений:

```bash
# Отключение TTY и принудительное удаление без подтверждения
export VAGRANT_NO_TTY=1
export VAGRANT_DEFAULT_PROVIDER=libvirt

vagrant up --no-provision
vagrant provision
vagrant ssh -c "run-tests.sh"
vagrant destroy -f
```

### Сценарий 11: Управление плагинами

Установка, обновление и удаление плагинов в рабочих окружениях:

```bash
# Установка провайдера
vagrant plugin install vagrant-libvirt

# Обновление всех плагинов
vagrant plugin update

# Проверка целостности зависимостей
vagrant plugin repair

# Полный сброс (при неразрешимых конфликтах)
vagrant plugin expunge --reinstall

# Экспорт списка плагинов для воспроизводимости
vagrant plugin list > plugins.txt
```

## Дополнительная информация

### Сравнение режимов выключения

| Метод | Состояние данных | Потребление RAM | Время запуска |
| :--- | :--- | :--- | :--- |
| **`suspend`** | Сохранены (Snapshot) | 0 (на диске) | Мгновенно |
| **`halt`** | Сохранены | 0 | Среднее (загрузка ОС) |
| **`destroy`** | **Удалены** | 0 | Долго (создание + provision) |

### Переменные окружения Vagrant

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| **`VAGRANT_CWD`** | Путь к директории с `Vagrantfile` | `/path/to/project` |
| **`VAGRANT_DOTFILE_PATH`** | Путь к `.vagrant/` (изоляция состояний) | `/tmp/vagrant-ci-${ID}` |
| **`VAGRANT_HOME`** | Путь к глобальному кэшу (`~/.vagrant.d`) | `/mnt/data/vagrant.d` |
| **`VAGRANT_LOG`** | Уровень логирования | `debug`, `info`, `warn`, `error` |
| **`VAGRANT_LOG_FILE`** | Файл для записи логов | `/tmp/vagrant-debug.log` |
| **`VAGRANT_DEFAULT_PROVIDER`** | Провайдер по умолчанию | `libvirt`, `virtualbox` |
| **`VAGRANT_NO_PARALLEL`** | Отключить параллельный запуск | `true` |
| **`VAGRANT_NO_TTY`** | Отключить интерактивный режим | `1` |
| **`VAGRANT_BOX_UPDATE_CHECK`** | Отключить проверку обновлений box | `0` |

### Типичные ошибки базового рабочего процесса

| Ошибка / Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Box not found` | Неверное имя или отсутствует провайдер | `vagrant box add bento/ubuntu-24.04 --provider virtualbox` |
| `SSH timeout` | Не запущен `sshd`, не настроен `cloud-init`, недостаток RAM | Проверьте `vagrant ssh-config`, увеличьте `config.vm.boot_timeout` |
| `Permission denied (publickey)` | Рассинхронизация ключа или неправильные права | `vagrant destroy -f && vagrant up` для перегенерации |
| `No space left on device` | Переполнение `~/.vagrant.d/` или пула хранилища | `vagrant box prune`, проверьте `df -hT` |
| `VT-x is not available` | Аппаратная виртуализация отключена или захвачена Hyper-V | Включите VT-x/AMD-V в BIOS; отключите Hyper-V |
| `Machine not found` | State Desync: `.vagrant/` ссылается на несуществующую ВМ | `vagrant global-status --prune && vagrant up` |

### Рекомендации по эксплуатации

1.  **Безопасность:** Не забывайте выполнять `vagrant destroy`, если проект больше не нужен, чтобы не хранить старые образы с потенциальными уязвимостями.
2.  **Идемпотентность:** Всегда проверяйте, что `vagrant provision` можно запускать многократно без побочных эффектов.
3.  **Локальный кэш:** Директория `~/.vagrant.d/` может занимать десятки гигабайт. Регулярно используйте `vagrant box prune`.
4.  **Валидация:** Добавьте `vagrant validate` в pre-commit или CI для раннего обнаружения ошибок конфигурации.
5.  **Отладка:** При «зависании» команд используйте уровни логирования: `VAGRANT_LOG=info vagrant up`.

### См. также

- [Конфигурация Vagrantfile](./vagrantfile.md) — детальный справочник параметров.
- [Vagrant Provisioning](./vagrant_provisioning.md) — автоматизация настройки.
- [Vagrant Troubleshooting](./vagrant_troubleshooting/basic_concepts.md) — глубокая отладка и логирование.
- [Packer и Пайплайн box](./vagrant_packer_boxes.md) — сборка собственных `.box` и публикация.
- [Плагины и команды](./vagrant_plugins_and_commands.md) — экосистема плагинов и вспомогательные команды.
- [Vagrant и альтернативы](./vagrant_vs_alternatives.md) — выбор слоя инструмента (Docker/Terraform/Minikube).
