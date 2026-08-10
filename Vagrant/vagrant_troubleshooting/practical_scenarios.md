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

**Причина:** Локальное состояние Vagrant (`.vagrant/`) было удалено вручную, но ресурсы у гипервизора (virsh) остались. Это типичный случай **State Desync** (рассинхронизации состояния).

**Решение (Глубокая очистка):**

```bash
# 1. Попытка штатного удаления (иногда помогает, если .vagrant еще жив)
vagrant destroy -f

# 2. Поиск зависших томов в пуле Libvirt
virsh --connect qemu:///system vol-list default

# 3. Принудительное удаление диска
virsh --connect qemu:///system vol-delete --pool default data-disk.qcow2

# 4. Удаление зависшего домена (ВМ)
virsh --connect qemu:///system undefine <domain_name> --remove-all-storage

# 5. Очистка кэша глобального статуса
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
# 1. Запуск с подробным логированием (самый эффективный метод)
VAGRANT_LOG=debug vagrant ssh

# 2. Просмотр эффективной конфигурации SSH, которую генерирует Vagrant
vagrant ssh-config

# 3. Прямое подключение с максимальной детализацией (-vvv)
ssh -vvv -i .vagrant/machines/default/libvirt/private_key vagrant@192.168.121.10 -p 22
```

### Возможные причины и решения:

| Причина | Решение |
| :--- | :--- |
| **Смена ключа** | Vagrant при первой загрузке меняет небезопасный ключ на уникальный. При сбое процесса ключ может рассинхронизироваться. Выполните: `vagrant destroy -f && vagrant up` |
| **Сбой сети (Port Forwarding)** | Проверьте порт через `nc -zv localhost 2222`. Измените порт в конфигурации, если он занят. |
| **Падение SSHD в гостевой ОС** | Подключитесь через GUI провайдера (например, `virt-manager` или VirtualBox UI) и проверьте статус: `systemctl status sshd`. |
| **Защита Cloud-Init** | В некоторых образах SSH блокируется до завершения `cloud-init`. Подождите 2-3 минуты. |

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

# Очистка неиспользуемых томов Libvirt
virsh --connect qemu:///system vol-list default | grep -v "Name" | xargs -n1 virsh vol-delete --pool default
```

## Сценарий 6: Ошибки вложенной виртуализации (Nested Virtualization)

**Симптом:** ВМ запускается, но внутри неё невозможно запустить Docker (с использованием KVM), гипервизор или Minikube.

**Диагностика и решение:**
1. **Проверка хоста:** Убедитесь, что вложенность активирована на физическом хосте (L0).
   ```bash
   cat /sys/module/kvm_intel/parameters/nested # Для Intel (должно быть Y)
   cat /sys/module/kvm_amd/parameters/nested   # Для AMD (должно быть 1)
   ```
2. **Конфигурация Vagrant:** Для провайдера `libvirt` должен быть включен параметр `nested`:
   ```ruby
   config.vm.provider "libvirt" do |libvirt|
     libvirt.nested = true
     libvirt.cpu_mode = "host-passthrough"
   end
   ```
3. **SSoT по настройке:** Подробные шаги для различных ОС и гипервизоров см. в:
   **[Вложенная виртуализация: Практические сценарии](../../Linux/Virtualization/nested_virtualization/practical_scenarios.md)**.

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
# Требует libvirt >= 6.2.0 и поддержку на хосте
config.vm.synced_folder ".", "/vagrant", type: "virtiofs"

# Если virtiofs недоступен, используйте NFS
config.vm.synced_folder ".", "/vagrant", type: "nfs"
```

## Сценарий 8: Ошибки NFS и права доступа (Host Firewall/Permissions)

**Симптом:** Vagrant зависает на этапе `Mounting NFS shared folders...` или выдает `Permission denied`.

**Причина:** 
1. Firewall на хосте блокирует запросы от ВМ.
2. Отсутствует запись в `/etc/exports` (Vagrant должен добавлять её автоматически, но иногда это требует `sudo`).
3. Служба NFS не запущена.

**Решение:**
1.  **Проверка Firewall (Linux/macOS):**
    Разрешите трафик из подсети ВМ (обычно `192.168.121.0/24` для libvirt).
2.  **Перезагрузка NFS:**
    ```bash
    sudo systemctl restart nfs-server # Linux
    sudo nfsd restart                # macOS
    ```
3.  **Ручная очистка /etc/exports:**
    Если файл переполнен мусором от старых проектов, Vagrant может ошибаться. Очистите неактуальные записи вручную.

## Сценарий 9: Конфликт VirtualBox и Hyper-V (Windows)

**Симптом:** VirtualBox ВМ падает с ошибкой `VT-x is not available` или работает крайне медленно (иконка черепахи в углу).

**Причина:** Включенный Hyper-V (или функции на его базе: WSL2, Memory Integrity, Docker Desktop) захватывает эксклюзивный доступ к VT-x.

**Решение:**
1.  **Отключение Hyper-V (если VirtualBox критичен):**
    ```powershell
    Disable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
    bcdedit /set hypervisorlaunchtype off
    # Требуется перезагрузка
    ```
2.  **Использование Hyper-V как провайдера:**
    ```bash
    vagrant up --provider=hyperv
    ```
    *Примечание: Hyper-V провайдер в Vagrant имеет ограниченную поддержку сетей (только DHCP/NAT).*

## Сценарий 10: Проблемы при скачивании образов (SSL/Timeouts)

**Симптом:**
```
SSL certificate problem: unable to get local issuer certificate
```
или `The request timed out`.

**Решение:**
1.  **Отключение проверки SSL (крайняя мера):**
    ```bash
    export VAGRANT_SERVER_URL="https://vagrantcloud.com"
    # Для Windows: set VAGRANT_SERVER_URL=...
    ```
    Или используйте флаг `--insecure` (не рекомендуется): `vagrant box add <name> --insecure`.
2.  **Использование альтернативного зеркала:**
    Скачайте файл `.box` вручную через браузер и добавьте локально:
    ```bash
    vagrant box add my-box ./package.box
    ```

## Сценарий 11: Apple Silicon (M1/M2/M3) — Специфические ошибки

**Симптом 1:** `The provider 'virtualbox' is not supported on this architecture.`
**Решение:** Используйте `qemu` или `vmware_desktop`. См. **[Vagrant на Apple Silicon](../vagrant_macos_apple_silicon.md)**.

**Симптом 2:** ВМ на базе QEMU зависает при запуске.
**Причина:** Попытка запустить `x86_64` образ на ARM64 процессоре.
**Решение:** Ищите образы с тегом `arm64` или `aarch64` на Vagrant Cloud (например, `generic/ubuntu2204-arm64`).

**Симптом 3:** Проблемы с `rsync` при синхронизации папок.
**Решение:** Убедитесь, что `rsync` установлен на хосте (`brew install rsync`). QEMU на Mac часто требует именно этот метод.

## См. также

- [Vagrant Troubleshooting: Основные концепции](./basic_concepts.md) — обзор архитектуры сбоев.
- [Vagrant Troubleshooting: Дополнительная информация](./additional_info.md) — профилактика и бэкапы.
- [Vagrant Networking](../vagrant_networking.md) — детальная настройка сетей.
- [Управление дисками и папками](../vagrant_storage_and_folders.md) — работа с `virtiofs` и хранилищами.
- [Диагностика SSH](../../Linux/Security/ssh/ssh_troubleshooting.md) — фундаментальные методы отладки протокола.
