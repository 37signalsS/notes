# Vagrant Troubleshooting — Дополнительная информация

## Определения

**Фиксация версии (Version Locking)** — практика жесткого указания версий образов (boxes), плагинов и самого Vagrant в конфигурации для обеспечения идентичности окружений у всех участников команды и в CI/CD. Включает: `config.vagrant.require_version` (минимальная версия Vagrant), `config.vm.box_version` (семантическое версионирование образа), `box_download_checksum` (контрольная сумма для верификации целостности) и фиксированные версии плагинов. Без полной фиксации окружение считается невоспроизводимым.

**Изоляция состояния (State Isolation)** — метод запуска нескольких независимых экземпляров одного и того же проекта путем разделения их метаданных (директории `.vagrant/`), что предотвращает конфликты блокировок и идентификаторов. Реализуется через переменную окружения `VAGRANT_DOTFILE_PATH`. В CI/CD изоляция позволяет запускать параллельные джобы одного проекта на одном агенте без гонок за UUID ВМ.

**Синхронизация времени (Clock Drift)** — расхождение часов между хостом и гостевой ОС, вызванное отсутствием или сбоем NTP-сервиса. В виртуализированных средах drift может достигать нескольких секунд за час, что приводит к ошибкам TLS-рукопожатий, истечению сертификатов X.509, сбоям Kerberos и отказу репликации в СУБД (PostgreSQL, MongoDB). В Vagrant drift особенно критичен при использовании `vagrant suspend/resume`, когда время гостя останавливается.

**Drift Guest Additions** — рассогласование версий гостевых дополнений гипервизора (VirtualBox Guest Additions, QEMU Guest Agent) между хостом и гостевой ОС. Приводит к падению производительности общих папок, некорректному определению размера диска и проблемам с интеграцией курсора/разрешения.

**Сиротские ресурсы (Orphaned Resources)** — объекты гипервизора (тома, сети, домены), оставшиеся после ручного удаления ВМ или сбоя `vagrant destroy`. Накопление сиротских ресурсов приводит к заполнению пулов хранилища и конфликтам подсетей.

## Профилактика и обслуживание

### Регулярная очистка и гигиена

Накопление старых образов и метаданных — основная причина ошибок `No space left on device` и конфликтов портов.

```bash
# Проверка синтаксиса Vagrantfile перед запуском (профилактика ошибок парсинга)
vagrant validate

# Удаление записей о ВМ, которые были удалены вручную в гипервизоре
vagrant global-status --prune

# Проверка устаревших версий образов
vagrant box outdated

# Обновление конкретного образа
vagrant box update --box bento/ubuntu-24.04 --provider virtualbox

# Удаление старых (неиспользуемых) версий образов для освобождения места
vagrant box prune

# Проверка свободного места в ключевых точках
df -hT ~/.vagrant.d /var/lib/libvirt/images
```

### Глубокий сброс окружения плагинов

При обновлении системного Ruby или версии Vagrant плагины могут перестать загружаться. В таких случаях `vagrant plugin update` может быть недостаточно.

```bash
# Полная очистка и переустановка всех плагинов из текущего списка
vagrant plugin expunge --reinstall
```

### Очистка сиротских ресурсов гипервизора

При State Desync или ручном удалении ВМ ресурсы могут оставаться в гипервизоре.

**Libvirt:**
```bash
# Список всех доменов (включая остановленные)
virsh --connect qemu:///system list --all

# Список пулов хранилища и их заполненности
virsh --connect qemu:///system pool-list --all
virsh --connect qemu:///system pool-info default

# Список виртуальных сетей
virsh --connect qemu:///system net-list --all

# Удаление неиспользуемого домена и всех его томов
virsh --connect qemu:///system undefine <domain_name> --remove-all-storage

# Удаление orphaned volume
virsh --connect qemu:///system vol-delete --pool default <volume_name>.qcow2

# Удаление неиспользуемой сети
virsh --connect qemu:///system net-undefine <network_name>
```

**VirtualBox:**
```bash
# Список всех ВМ (включая сохраненные состояния)
VBoxManage list vms
VBoxManage list runningvms

# Удаление ВМ со всеми дисками и состояниями
VBoxManage unregister vm <vm_name> --delete

# Очистка host-only интерфейсов
VBoxManage list hostonlyifs
VBoxManage hostonlyif remove vboxnet1
```

### Синхронизация времени

Настройка NTP внутри гостевой ОС для предотвращения drift:

```bash
# systemd-based Linux
vagrant ssh -c "sudo timedatectl set-ntp true"
vagrant ssh -c "sudo timedatectl status"

# Проверка расхождения
vagrant ssh -c "timedatectl show | grep NTPSynchronized"
# → NTPSynchronized=yes
```

## Практические сценарии

### Работа со снимками состояния (Snapshots)

Снимки позволяют сохранять "контрольные точки" перед выполнением рискованных операций (обновление ядра, установка тяжелого ПО).

**Важно:** Поддержка снимков зависит от провайдера. VirtualBox и VMware поддерживают полные снимки (включая RAM). Libvirt поддерживает снимки только если том использует формат `qcow2` и файловая система гостя поддерживает freeze (ext4, xfs). Docker и Hyper-V имеют ограниченную или отсутствующую поддержку.

**Сценарий: Тестирование провижининга**
1.  Создайте снимок базовой чистой ОС: `vagrant snapshot save "clean-os"`.
2.  Запустите провижининг: `vagrant provision`.
3.  Если скрипты отработали с ошибками — откатитесь: `vagrant snapshot restore "clean-os"`, исправьте код и повторите.

**Управление снимками:**
- `vagrant snapshot save <name>` — создание именованной точки восстановления.
- `vagrant snapshot restore <name>` — мгновенный откат к состоянию снимка.
- `vagrant snapshot list` — дерево снимков для текущей ВМ.
- `vagrant snapshot delete <name>` — удаление снимка.
- `vagrant snapshot push` — создание временного снимка в стеке (удобно для быстрых тестов).
- `vagrant snapshot pop` — откат к последнему снимку в стеке и его удаление.

### Восстановление данных из повреждённой ВМ

Если ВМ повреждена и не загружается, но диск доступен:

1.  **Монтирование диска на хосте:** Используйте `guestmount` (libguestfs) или подключите диск ВМ как дополнительный к другой рабочей машине.
    ```bash
    # Установка libguestfs (Debian/Ubuntu)
    sudo apt-get install -y libguestfs-tools

    # Монтирование qcow2 образа
    guestmount -a /var/lib/libvirt/images/<vm_name>.qcow2 -i --ro /mnt/vm-recovery

    # Копирование данных
    sudo cp -r /mnt/vm-recovery/home/vagrant/project ./recovered/

    # Размонтирование
    guestunmount /mnt/vm-recovery
    ```

2.  **Ручной экспорт через SCP:** Если SSH доступен, но Vagrant-команды ломаются:
    ```bash
    # Получение параметров доступа
    vagrant ssh-config > ssh_config

    # Копирование данных напрямую
    scp -F ssh_config default:/var/lib/mysql/backup.sql ./
    ```

3.  **Извлечение диска через гипервизор:** Если SSH недоступен, подключите диск ВМ к другой рабочей ВМ как дополнительное устройство через интерфейс гипервизора.

### Управление дисковым пространством

При заполнении пулов хранилища или кэша образов:

```bash
# 1. Быстрая диагностика
df -hT ~/.vagrant.d /var/lib/libvirt/images

# 2. Очистка кэша старых образов Vagrant
vagrant box prune --keep 1

# 3. Очистка системных логов старше 7 дней (на хосте)
sudo journalctl --vacuum-time=7d

# 4. Очистка неиспользуемых томов Libvirt
virsh --connect qemu:///system vol-list default | grep -v "Name" | xargs -n1 virsh vol-delete --pool default

# 5. Удаление зависших снимков VirtualBox
VBoxManage list hdds | grep "^UUID:" | while read uuid; do
  VBoxManage modifyhd $uuid --compact
done
```

### Управление Guest Additions

Drift версий гостевых дополнений — частая причина падения производительности общих папок.

```bash
# Автоматическая установка и обновление (VirtualBox)
vagrant plugin install vagrant-vbguest
vagrant up # Плагин автоматически проверит и обновит Guest Additions

# Для Libvirt/QEMU используется QEMU Guest Agent
# Включите его в конфигурации:
config.vm.provider "libvirt" do |lv|
  lv.qemu_use_agent = true
end

# Проверка статуса внутри ВМ
vagrant ssh -c "systemctl status qemu-guest-agent"
```

### Восстановление повреждённой конфигурации `.vagrant/`

Если метаданные проекта повреждены или утеряны:

```bash
# 1. Проверьте существование ВМ в гипервизоре
virsh list --all # Libvirt
VBoxManage list vms # VirtualBox

# 2. Если ВМ существует, но Vagrant её не видит — исправьте id в .vagrant/
echo "<provider_uuid>" > .vagrant/machines/default/libvirt/id

# 3. Если SSH-ключ рассинхронизирован — перегенерируйте
vagrant ssh-config

# 4. Изоляция проблемного провижининга
vagrant up --no-provision
vagrant provision

# 5. Крайняя мера — полное удаление метаданных проекта
rm -rf .vagrant
vagrant global-status --prune
vagrant up
```

### Офлайн-работа (Air-Gapped среды)

Для изолированных сред без доступа в интернет:

1.  **Подготовка артефактов на машине с доступом:**
    ```bash
    # Скачивание box-файла
    vagrant box add bento/ubuntu-24.04 --provider libvirt

    # Экспорт списка плагинов
    vagrant plugin list > plugins.txt

    # Упаковка проекта
    tar czf vagrant-offline.tar.gz Vagrantfile .vagrant/
    ```

2.  **Перенос и установка в изолированной сети:**
    ```bash
    # Перенос через внешний носитель
    # Установка плагинов из локального кэша или файлов
    vagrant plugin install vagrant-libvirt

    # Добавление box из локального файла
    vagrant box add bento/ubuntu-24.04 ./bento-ubuntu-24.04-libvirt.box --provider libvirt
    ```

### Резервное копирование окружений

Создание переносимых архивов рабочих сред:

```bash
# Остановка ВМ
vagrant halt

# Упаковка текущего состояния (включая диски)
vagrant package --output project-backup-$(date +%Y%m%d).box

# Экспорт метаданных
cp -r .vagrant ./vagrant-metadata-backup
vagrant global-status --prune > global-status-backup.txt
```

## Безопасность и автоматизация

### Безопасность секретов и токенов

Никогда не храните пароли, API-ключи или SSH-ключи в открытом виде внутри `Vagrantfile`.

**Рекомендуемые методы:**
1.  **Переменные окружения:**
    ```ruby
    config.vm.provision "shell", env: {"DB_PASSWORD" => ENV['DB_PASSWORD']}
    ```
2.  **Плагин `vagrant-env`:** Позволяет загружать переменные из файла `.env` (добавьте его в `.gitignore`).
3.  **Vagrant Cloud Auth:** Для доступа к приватным образам используйте `vagrant cloud auth login` вместо передачи токенов в конфигурации.

### Управление SSH-ключами

Vagrant использует insecure_private_key по умолчанию. После первого запуска он генерирует уникальный ключ в `.vagrant/machines/<name>/<provider>/private_key`.

**Ротация ключей:**
```bash
# Принудительная перегенерация SSH-ключа
rm -f .vagrant/machines/default/libvirt/private_key
vagrant up # Ключ будет создан заново

# Использование собственного ключа
config.ssh.private_key_path = ["~/.ssh/id_ed25519"]
```

### Траблшутинг в CI/CD и Headless-средах

В автоматизированных средах (Jenkins, GitLab CI, GitHub Actions) стандартный интерактивный вывод Vagrant может быть бесполезен.

**Лучшие практики для CI:**
- **Флаг `--no-tty`:** Отключает интерактивные запросы и цветовую схему.
- **Логирование в файл:**
  ```bash
  VAGRANT_LOG=debug vagrant up --provider=libvirt > vagrant_debug.log 2>&1
  ```
- **Предотвращение параллельных конфликтов:** Используйте `VAGRANT_DOTFILE_PATH`, если на одном агенте CI запускается несколько сборок одного проекта.
- **Увеличение таймаутов:** В CI-облаках дисковая подсистема часто медленнее. Увеличьте `config.vm.boot_timeout` до 600–1200 секунд.
- **Сбор артефактов:** Сохраняйте `vagrant_debug.log` и вывод `vagrant status` как артефакты пайплайна для post-mortem анализа.
- **Атомарный запуск:** Разделите `vagrant up --no-provision` и `vagrant provision` для изоляции проблем.

### Автоматизация через триггеры

Используйте триггеры для автоматической очистки и проверок:

```ruby
# Проверка свободного места перед запуском
config.trigger.before :up do |trigger|
  trigger.run_local = { inline: "df -hT ~/.vagrant.d | awk 'NR==2 {exit ($5+0 > 90)}' || (echo 'Disk full!' && exit 1)" }
end

# Очистка временных файлов после destroy
config.trigger.after :destroy do |trigger|
  trigger.run_local = { inline: "rm -f /tmp/vagrant-*" }
end
```

## См. также

- [Базовый рабочий процесс](../vagrant_basic_workflow.md) — обзор жизненного цикла.
- [Отладка: Основные концепции](./basic_concepts.md) — уровни логирования и переменные окружения.
- [Отладка: Практические сценарии](./practical_scenarios.md) — решение типовых проблем с SSH и провайдерами.
