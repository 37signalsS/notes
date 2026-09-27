# Vagrant: экосистема плагинов и полезные команды

## Определения

**Плагин Vagrant** — Ruby-gem, расширяющий возможности CLI Vagrant: добавляет провайдеры, провижинеры, типы синхронизированных папок и утилиты. Ставится в `~/.vagrant.d/` и переживает перезапуски виртуальных машин.

**Провайдер-плагин** — добавляет поддержку гипервизора/рантама (например, `vagrant-libvirt`, `vagrant-qemu`, `vagrant-parallels`, `vagrant-podman`).

**Утилита-плагин** — упрощает частые операции: копирование файлов (`vagrant-scp`), синхронизация каталогов (`vagrant-sshfs`), изменение размера диска (`vagrant-disksize`), управление `/etc/hosts` (`vagrant-hostmanager`), часовым поясом гостя (`vagrant-timezone`).

**Неосновные (non-primary) команды** — скрытые из базового `vagrant -h`, но рабочие команды (`docker-exec`, `rsync`, `upload` и т.д.). Полный список выдаёт `vagrant list-commands`.

## Базовые концепции

### Жизненный цикл плагинов

```bash
# Установка (с версией и из git можно опционально)
vagrant plugin install vagrant-scp
vagrant plugin install vagrant-hostmanager

# Список установленных
vagrant plugin list

# Обновление всех / конкретного
vagrant plugin update
vagrant plugin update vagrant-scp

# Удаление
vagrant plugin uninstall vagrant-hostmanager

# Проверка целостности зависимостей (после обновления Vagrant)
vagrant plugin repair

# Полный сброс и переустановка (при битых зависимостях)
vagrant plugin expunge --reinstall
```

Менеджер плагинов — часть Vagrant (команда `vagrant plugin`), поэтому «установка плагина» не требует ручной работы с gem.

### Проверка плагина в Vagrantfile

Чтобы `Vagrantfile` не падал у коллег без плагина, проверяйте наличие через `Vagrant.has_plugin?` и `Vagrant.require_plugin`:

```ruby
Vagrant.configure("2") do |config|
  if Vagrant.has_plugin?("vagrant-timezone")
    config.timezone.value = "UTC"
  end

  if Vagrant.has_plugin?("vagrant-hostmanager")
    config.hostmanager.enabled = true
    config.hostmanager.manage_host = true
  end
end
```

### Основные группы команд CLI (2.4.x, 2026)

- **Жизненный цикл:** `up`, `halt`, `suspend`, `resume`, `reload`, `destroy`, `status`, `provision` — см. [Vagrant Basic Workflow](./vagrant_basic_workflow.md).
- **Boxes:** `box add/list/remove/outdated/update/prune` — см. [Vagrant Providers](./vagrant_providers.md).
- **Cloud/публикация:** `cloud` (auth, box, provider, publish, search, version), `login` — см. [Packer и Пайплайн box](./vagrant_packer_boxes.md).
- **Диагностика/верификация:** `validate`, `port`, `ssh-config`, `snapshot`, `upload`, `list-commands`, `global-status` — кратко ниже.

### Machine-readable вывод (`--machine-readable`)

Почти все команды (`status`, `global-status`, `up`, `provision`, `destroy` и др.) принимают флаг `--machine-readable`: вместо человекочитаемой таблицы выдаётся построчный машинный формат, защищённый политикой обратной совместимости Vagrant. Это удобно для автоматизации и скриптов.

Формат строки — `timestamp,target,type,data...`:

- `timestamp` — Unix-время (UTC) вывода сообщения;
- `target` — имя машины (пусто, если сообщение глобальное);
- `type` — тип события;
- `data` — ноль и более значений, зависящих от типа.

Основные типы: `box-name`, `box-provider`, `cli-command`, `error-exit` (тип ошибки + сообщение), `provider-name`, `ssh-config`, `state` (ID состояния), `state-human-short`, `state-human-long`. Для `global-status` дополнительно: `metadata` (например, `metadata,machine-count,1`), `machine-id`, `machine-home`.

```bash
vagrant status --machine-readable
# → 1737100000,default,provider-name,libvirt
# → 1737100000,default,state,running
```

Для перевода в JSON используйте парсеры на Ruby/Python поверх этого формата (например, `vagrant2json`).

## Практические сценарии

### Сценарий 1: Копирование файлов через `vagrant-scp`

`vagrant ssh` не умеет передавать файлы; для SCP-копий между хостом и ВМ ставят `vagrant-scp`:

```bash
vagrant plugin install vagrant-scp

# Хост → гость
vagrant scp ./app.conf default:/tmp/app.conf

# Гость → хост
vagrant scp default:/var/log/app.log ./logs/

# Мульти-машина: имя ВМ вместо default
vagrant scp web:/etc/nginx/nginx.conf ./nginx-web.conf
```

### Сценарий 2: SSHFS-синхронизация через `vagrant-sshfs`

Альтернатива NFS/virtiofs для случаев, когда надо смонтировать каталог на лету по SSH. Требуется `sshfs` в гостевой ОС.

```ruby
config.vm.synced_folder "./data", "/srv/data",
  type: "sshfs",
  sshfs_opts_append: "-o cache=no -o reconnect"
```

По производительности уступает NFS/virtiofs — используйте как удобный «лёгкий» вариант, а не для тяжёлых сборок (сравнение в [Vagrant Storage](./vagrant_storage_and_folders.md)).

### Сценарий 3: Увеличение диска — `vagrant-disksize`

```ruby
# Расширяет корневой диск ВМ при первом up (недетерминированно для разметки!)
config.disksize.size = "50GB"
```

Ограничения: применимо только на первом запуске (ядро образа), расширяет корневой раздел, зависит от схемы разбиения (LVM/тип). Для детерминированного контроля диска лучше сразу собирать box с нужным размером (см. [Packer](./vagrant_packer_boxes.md)) или задавать `machine_virtual_size` в libvirt.

### Сценарий 4: Домены в `/etc/hosts` — `vagrant-hostmanager` и `vagrant-hostsupdater`

Связывание красивого имени ВМ с IP на хосте и между машинами:

```ruby
config.hostmanager.enabled = true
config.hostmanager.manage_host = true   # править /etc/hosts хоста
config.hostmanager.ignore_private_ip = false
config.hostmanager.include_offline = true
```

`vagrant-hostsupdater` — более простая альтернатива (только хост-файлы, нет обмена между машинами). Выбирайте `hostmanager`, если машины должны видеть друг друга по имени (см. [Vagrant Advanced](./vagrant_advanced_usage.md)).

### Сценарий 5: Часовой пояс гостя — `vagrant-timezone`

```ruby
if Vagrant.has_plugin?("vagrant-timezone")
  config.timezone.value = "Europe/Moscow"
  # вариант — синхронизация с хостом: config.timezone.value = :host
end
```

### Сценарий 6: Провайдеры-плагины: Parallels и Podman

```bash
# Parallels Desktop (macOS x86_64/arm64)
vagrant plugin install vagrant-parallels
vagrant up --provider=parallels

# Podman как провайдер (аналог docker-провайдера на Apple Silicon)
vagrant plugin install vagrant-podman
vagrant up --provider=podman
```

Список провайдеров и их роль — в [Vagrant Providers](./vagrant_providers.md).

### Сценарий 7: Диагностика и вспомогательные команды ядра

```bash
# Проверка Vagrantfile без запуска ВМ (ключ для pre-commit/CI)
vagrant validate

# Карта проброшенных портов (частый вопрос: «на каком порту хост то, что в ВМ?»)
vagrant port
vagrant port web

# SSH-конфигурация для внешнего клиента (VS Code, rsync, ProxyJump)
vagrant ssh-config

# Снапшоты состояния ВМ (рабочие точки отката)
vagrant snapshot list
vagrant snapshot push    # именованный снапшот
vagrant snapshot pop

# Копирование файла из гостя на хост без плагинов (ядро, 2.4+)
vagrant upload ./file.txt default:/tmp/file.txt

# Скрытые команды (docker-*, rsync, rsync-auto и др.)
vagrant list-commands
```

### Сценарий 8: Machine-readable вывод в CI/CD

Когда нужно программно определить состояние машины без разбора текстовой таблицы:

```bash
# Состояние всех машин проекта
vagrant status --machine-readable
# → 1737100000,default,provider-name,libvirt
# → 1737100000,default,state,running

# Только state каждой машины (в data могут быть запятые — берём последнее поле)
vagrant status --machine-readable | awk -F',' '$3=="state" {print $2, $NF}'

# Ожидание завершения vagrant up в неинтерактивном режиме: упасть при ошибке
vagrant up --machine-readable | tee up.log
grep -q 'error-exit' up.log && exit 1

# Управление машиной из любой директории по ID из global-status.
# В global-status machine-readable строки глобальные (target пуст), имя машины в них не передаётся —
# выбираем первый machine-id (варианты с фильтром по provider-name тоже допустимы)
mid=$(vagrant global-status --machine-readable | \
  awk -F',' '$3=="machine-id" {print $4; exit}')
vagrant halt "$mid"
```

Важно: `global-status` основан на кэше, поэтому перед критичными сценариями используйте `--prune`, иначе состояния могут быть устаревшими.

### Сценарий 9: Публичный доступ через `vagrant share`

`vagrant share` открывает доступ к запущенной ВМ извне через туннель (реализация поверх ngrok). Требует установленного плагина `vagrant-share` и аккаунта HashiCorp.

```bash
vagrant plugin install vagrant-share
vagrant share                # HTTP-доступ: автоопределение порта веб-сервера внутри ВМ
vagrant share --ssh          # SSH-доступ: генерируется отдельный ключевой обмен
vagrant share --ssh-once     # SSH-доступ строго однократный (ключ после использования уничтожается)
vagrant share --http 8080 --disable-https
```

- Параметры HTTP-шеринга: `--http PORT`, `--https PORT`, `--disable-http`, `--disable-https` (HTTPS-шеринг — только платный ngrok).
- Потребитель подключается через `vagrant connect` (для SSH — `vagrant connect --ssh <NAME>`).
- Это инструмент для разработки и демонстраций, **не для продакшена**: туннель наружу поверх изолированного окружения. Для production-доступа используйте VPN или SSH-bastion, а не `vagrant share`.

## Дополнительная информация

### Типичные ошибки

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Plugin error` при `vagrant up` | Несовместимость версии Vagrant и плагина | `vagrant plugin update`; `vagrant plugin repair`; при необходимости `expunge --reinstall` |
| Плагин «пропал» после обновления Vagrant | Пересборка среды gem'ов | `vagrant plugin repair`, повторить `install` из `plugins.txt` |
| `disksize` не применяется | Разметка диска не поддерживает расширение | Пересобрать box с нужным размером (Packer) |
| `sshfs` не монтируется | Нет `sshfs` в гостевой ОС или плагин macFUSE на хосте (macOS) | `apt install sshfs` / `brew install macfuse sshfs` |
| `Vagrantfile` требует плагин у всех | Явная установка в `global` | Оберните в `if Vagrant.has_plugin?` или закоммитьте `plugins.txt` |

### Лучшие практики

1. **Минимизируйте плагины**: каждый — потенциальный источник несовместимости; предпочитайте функциональность ядра.
2. **Фиксируйте состав плагинов**: `vagrant plugin list > plugins.txt` и восстанавливайте командой `xargs vagrant plugin install < plugins.txt`.
3. **Документируйте зависимость от плагинов в `Vagrantfile`** через `Vagrant.has_plugin?`, чтобы файл оставался рабочим у всех.
4. **Секреты — не в плагинах**: `vagrant-env` удобен, но не единственный путь; используйте переменные окружения CI секретов (`ENV`).
5. **`vagrant validate`** — обязательный шаг перед коммитом и в CI (см. [Vagrant Basic Workflow](./vagrant_basic_workflow.md)).
6. **Для автоматизации используйте `--machine-readable`**, а не текст: вывод стабилен, не зависит от локали и версии, парсится `awk`/`grep`.

### См. также

- [Vagrant Providers](./vagrant_providers.md) — провайдеры-плагины (libvirt, qemu, parallels), источники box.
- [Packer и Пайплайн box](./vagrant_packer_boxes.md) — `vagrant cloud`, `login`, публикация и приватные box.
- [Vagrantfile: Справочник](./vagrantfile.md) — параметры конфигурации и `Vagrant.has_plugin?`.
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — мульти-машины, триггеры, hostmanager-сценарии.