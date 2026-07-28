# Vagrant: Решение проблем — Практические сценарии

## Сценарий 1: Работа через прокси-сервер

**Проблема:** Vagrant не может скачать образы (boxes) или выполнить сетевые операции внутри ВМ (например, `apt-get update`).

**Решение на уровне хоста:**

```bash
# Переменные для стандартных утилит Linux (curl, wget)
export http_proxy="http://user:pass@proxy.example.com:8080/"
export https_proxy="http://user:pass@proxy.example.com:8080/"

# Специальные переменные для ядра Vagrant (загрузка образов)
export VAGRANT_HTTP_PROXY="${http_proxy}"
export VAGRANT_HTTPS_PROXY="${https_proxy}"
export VAGRANT_NO_PROXY="127.0.0.1,localhost,192.168.0.0/16"
```

**Решение внутри гостевой ОС (через плагин):**

```bash
vagrant plugin install vagrant-proxyconf
```

```ruby
Vagrant.configure("2") do |config|
  if Vagrant.has_plugin?("vagrant-proxyconf")
    config.proxy.http     = ENV["HTTP_PROXY"]
    config.proxy.https    = ENV["HTTPS_PROXY"]
    config.proxy.no_proxy = "localhost,127.0.0.1,.localdomain"
  end
end
```

## Сценарий 2: Ошибка "диск уже существует" (Libvirt)

**Симптом:**
```
Error creating storage: storage volume 'data-disk.qcow2' already exists
```

**Причина:** Локальное состояние Vagrant (`.vagrant/`) было удалено вручную, но ресурсы у гипервизора (virsh) остались.

**Решение (Глубокая очистка):**

```bash
# 1. Попытка штатного удаления
vagrant destroy -f

# 2. Поиск зависших томов в пуле Libvirt
virsh --connect qemu:///system vol-list default

# 3. Принудительное удаление диска
virsh --connect qemu:///system vol-delete --pool default data-disk.qcow2

# 4. Удаление зависшего домена (ВМ)
virsh --connect qemu:///system undefine <domain_name> --remove-all-storage

# 5. Очистка кэша
vagrant global-status --prune
```

## Сценарий 3: Конфликты сетевых мостов (Network Conflicts)

**Симптом:**
```
Call to virNetworkCreate failed: Requested operation is not valid: network is already active
```
или `IP address is already in use`.

**Причина:** Vagrant пытается создать сеть `vagrant-libvirt` (или другую), но подсеть уже занята Docker, VPN (например, Tailscale) или другим экземпляром Vagrant.

**Решение:**

1.  **Смена подсети в Vagrantfile:**
    ```ruby
    config.vm.network "private_network", ip: "10.10.10.10" # Избегайте стандартных 192.168.121.x
    ```

2.  **Перезапуск зависшей сети Libvirt:**
    ```bash
    # Просмотр сетей
    virsh --connect qemu:///system net-list --all
    
    # Уничтожение и запуск проблемной сети
    virsh --connect qemu:///system net-destroy vagrant-libvirt
    virsh --connect qemu:///system net-start vagrant-libvirt
    ```

## Сценарий 4: SSH не подключается (Connection Timeout / Authentication Failure)

**Симптом:** Команда `vagrant ssh` зависает или выдает `Permission denied (publickey)`.

### Диагностика:

```bash
# 1. Просмотр эффективной конфигурации SSH, которую генерирует Vagrant
vagrant ssh-config

# 2. Прямое подключение с максимальной детализацией (-vvv)
# Скопируйте параметры из предыдущей команды:
ssh -vvv -i .vagrant/machines/default/libvirt/private_key vagrant@192.168.121.10 -p 22
```

### Возможные причины и решения:

| Причина | Решение |
| :--- | :--- |
| **Смена ключа** | Vagrant при первой загрузке меняет небезопасный ключ на уникальный. При сбое процесса ключ может рассинхронизироваться. Выполните: `vagrant destroy -f && vagrant up` |
| **Сбой сети (Port Forwarding)** | Проверьте порт через `nc -zv localhost 2222`. Измените порт в конфигурации, если он занят. |
| **Падение SSHD в гостевой ОС** | Подключитесь через GUI провайдера (например, `virt-manager` или VirtualBox UI) и проверьте статус: `systemctl status sshd`. |

## Сценарий 5: Недостаточно места на диске

**Симптом:**
```
Error while creating new volume: No space left on device
```

**Очистка системы:**

```bash
# Проверить точки монтирования (часто переполняется /var/lib/libvirt/images)
df -hT

# Очистить кэш старых образов Vagrant (~/.vagrant.d/boxes)
vagrant box prune

# Удалить системные логи старше 7 дней (на хосте)
sudo journalctl --vacuum-time=7d
```

## Сценарий 6: Ошибки вложенной виртуализации (Nested Virtualization)

**Симптом:** ВМ запускается, но внутри неё невозможно запустить Docker (KVM) или Minikube.

**Проверка поддержки на хосте:**
```bash
# Должно вернуть 'Y' или '1'
cat /sys/module/kvm_intel/parameters/nested # Для Intel
cat /sys/module/kvm_amd/parameters/nested   # Для AMD
```

**Решение (настройка Libvirt):**
```ruby
config.vm.provider "libvirt" do |libvirt|
  # Включение вложенной виртуализации
  libvirt.nested = true
  # Проброс модели CPU хоста (критично для производительности)
  libvirt.cpu_mode = "host-passthrough"
end
```

## Сценарий 7: Проблемы с общими папками (Synced Folders)

**Симптом:**
```
Mounting shared folders failed
```

**Решение для VirtualBox (Guest Additions):**
Версия Guest Additions в ядре гостевой ОС должна совпадать с версией VirtualBox на хосте.
```bash
vagrant plugin install vagrant-vbguest
vagrant reload
```

**Решение для Libvirt (NFS/Virtiofs):**
```ruby
# Современный и быстрый метод для KVM (Vagrant 2.4+)
config.vm.synced_folder ".", "/vagrant", type: "virtiofs"

# Если virtiofs недоступен, используйте NFS
config.vm.synced_folder ".", "/vagrant", type: "nfs"
```

## См. также

- [Vagrant Troubleshooting: Основные концепции](./basic_concepts.md) — обзор архитектуры сбоев.
- [Vagrant Networking](../vagrant_networking.md) — детальная настройка сетей.
- [Управление дисками и папками](../vagrant_storage_and_folders.md) — работа с `virtiofs` и хранилищами.
- [Диагностика SSH](../../Linux/Security/ssh/ssh_troubleshooting.md) — фундаментальные методы отладки протокола.
