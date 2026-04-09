# Vagrant: Решение проблем — Практические сценарии

## Сценарий 1: Работа через прокси-сервер

**Проблема:** Vagrant не может скачать box'ы или выполнить сетевые операции внутри ВМ.

**Решение:**

```bash
# Переменные для утилит Linux
export http_proxy="http://user:pass@proxy.example.com:port/"
export https_proxy="http://user:pass@proxy.example.com:port/"

# Специальные переменные для Vagrant
export VAGRANT_HTTP_PROXY="${http_proxy}"
export VAGRANT_HTTPS_PROXY="${https_proxy}"

# Для постоянного добавления в ~/.bashrc или ~/.zshrc
```

**Автоматизация через плагин:**

```bash
vagrant plugin install vagrant-proxyconf
```

```ruby
# В Vagrantfile
Vagrant.configure("2") do |config|
  if Vagrant.has_plugin?("vagrant-proxyconf")
    config.proxy.http     = ENV["HTTP_PROXY"]
    config.proxy.https   = ENV["HTTPS_PROXY"]
    config.proxy.no_proxy = "localhost,127.0.0.1"
  end
end
```

## Сценарий 2: Ошибка "диск уже существует" в Libvirt

**Симптом:**

```
Error creating storage: storage volume 'data-disk.qcow2' already exists
```

**Причина:** Рассинхронизация между Vagrant и libvirt после некорректного удаления.

**Решение:**

```bash
# 1. Уничтожить ВМ
vagrant destroy -f

# 2. Проверить пул хранения libvirt
virsh --connect qemu:///system vol-list default

# 3. Удалить оставшиеся диски
virsh --connect qemu:///system vol-delete --pool default data-disk.qcow2

# 4. Удалить локальное состояние
rm -rf .vagrant

# 5. Повторить запуск
vagrant up
```

## Сценарий 3: Конфликты имён в Libvirt

**Проблема:** Ошибки при создании ВМ из-за специальных символов в имени.

**Причина:** Libvirt формирует имя домена как `проект_машина`. Символ `_` может вызывать конфликты.

**Решение:**

```ruby
# Правильно:
config.vm.define "web-server"
config.vm.define "db-node"

# Неправильно:
config.vm.define "web_server"  # Может вызвать конфликт
```

## Сценарий 4: Ручная очистка рассинхронизированных ВМ (Libvirt)

**Симптом:** `vagrant status` показывает "not created", но `virsh list --all` показывает домены.

### Диагностика

```bash
# Проверить состояние в Libvirt
virsh --connect qemu:///system list --all

# Проверить состояние в Vagrant
vagrant status
vagrant global-status

# Проверить привязку ID
cat .vagrant/machines/*/libvirt/id 2>/dev/null
```

### Очистка

**Способ 1: Через virsh (точечная)**

```bash
# Найти имена доменов
virsh --connect qemu:///system list --all

# Остановить домен (если работает)
virsh --connect qemu:///system destroy domain-name

# Удалить домен и хранилище
virsh --connect qemu:///system undefine domain-name --remove-all-storage

# Очистить кэш Vagrant
vagrant global-status --prune
```

**Способ 2: Через vagrant destroy (по ID)**

```bash
# Найти ID машины
vagrant global-status

# Удалить по ID
vagrant destroy <machine-id> -f
```

## Сценарий 5: SSH не подключается

**Симптом:** `vagrant ssh` завершается с ошибкой аутентификации.

**Возможные причины и решения:**

| Причина | Решение |
| --- | --- |
| SSH-сервис не запущен | `vagrant reload` для перезагрузки |
| Неправильный ключ | `vagrant destroy` + `vagrant up` |
| Порт SSH изменён | Проверить `config.ssh.port` в Vagrantfile |
| Гостевые дополнения не установлены | Установить `vagrant-vbguest` плагин |

**Диагностика:**

```bash
# Проверить конфигурацию SSH
vagrant ssh-config

# Принудительное пересоздание ключа
vagrant destroy -f && vagrant up

# Проверить лог Vagrant
VAGRANT_LOG=info vagrant up 2>&1 | tee vagrant.log
```

## Сценарий 6: Недостаточно места на диске

**Симптом:**

```
Error while creating new volume: No space left on device
```

**Решение:**

```bash
# Проверить свободное место
df -h

# Очистить кэш box'ов
vagrant box prune

# Удалить неиспользуемые box'ы
vagrant box list
vagrant box remove <unused-box>

# Очистить логи и временные файлы
sudo journalctl --vacuum-time=7d
sudo apt-get autoremove
```

**Профилактика:**

```ruby
# В Vagrantfile для Libvirt
config.vm.provider "libvirt" do |libvirt|
  libvirt.storage_pool_name = "default"
  # Указать другой пул с большим местом
  # libvirt.storage_pool_name = "data-pool"
end
```

## Сценарий 7: Ошибки вложенной виртуализации

**Симптом:** ВМ запускается, но Docker/KVM внутри не работают.

**Причина:** Вложенная виртуализация не включена на уровне хоста.

**Проверка:**

```bash
# Проверить поддержку вложенной виртуализации
cat /sys/module/kvm/parameters/ignore_msrs

# Для Intel
grep -E 'vmx|nested' /proc/cpuinfo

# Для AMD
grep -E 'svm|nested' /proc/cpuinfo
```

**Включение:**

```bash
# Для Intel
echo "options kvm-intel nested=1" | sudo tee /etc/modprobe.d/kvm-intel.conf

# Для AMD
echo "options kvm-amd nested=1" | sudo tee /etc/modprobe.d/kvm-amd.conf

# Перезагрузить модуль
sudo modprobe -r kvm-intel && sudo modprobe kvm-intel
```

```ruby
# В Vagrantfile
config.vm.provider "libvirt" do |libvirt|
  libvirt.nested = true
end
```

## Сценарий 8: Проблемы с общими папками (Synced Folders)

**Симптом:**

```
Mounting shared folders failed
```

**Решение для VirtualBox:**

```bash
# Переустановить Guest Additions
vagrant plugin install vagrant-vbguest
vagrant vbguest --do install
```

**Решение для Libvirt:**

```ruby
# Использовать NFS вместо virtiofs
config.vm.synced_folder ".", "/vagrant", type: "nfs"

# Или отключить, если не нужно
config.vm.synced_folder ".", "/vagrant", disabled: true
```

**Альтернатива — rsync:**

```ruby
config.vm.synced_folder ".", "/vagrant",
  type: "rsync",
  rsync__exclude: [".git/", ".vagrant/"],
  rsync__args: ["--verbose", "--archive", "--delete"]
```
