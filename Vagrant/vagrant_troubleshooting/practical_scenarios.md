# Vagrant Troubleshooting — Практические сценарии

**Актуально для:** Vagrant 2.4.x

## Определения

Этот документ содержит пошаговые сценарии решения типичных проблем Vagrant в средах DevOps, SRE и системного администрирования. Каждый сценарий строится по схеме: **симптом → диагностика → решение → верификация**.

**Ключевые термины:**
- **State Desync** — рассогласование между локальным состоянием Vagrant (`.vagrant/`) и реальными ресурсами гипервизора. Файл `.vagrant/machines/<name>/<provider>/id` содержит устаревший UUID.
- **Guest Additions** — набор драйверов и сервисов, поставляемый гипервизором (VirtualBox Guest Additions, QEMU Guest Agent). Обеспечивают общие папки, буфер обмена, синхронизацию времени. Drift версий — частая причина проблем с производительностью.
- **Air-Gapped среда** — окружение без доступа в интернет, где все артефакты (box'ы, плагины) должны быть предварительно подготовлены на машине с доступом.
- **Nested virtualization** — запуск гипервизора внутри ВМ. Требует поддержки на хосте (Intel VT-x/AMD-V) и включения `nested=1` в KVM.
- **Post-mortem** — систематизированный сбор артефактов (логи, статусы, debug-вывод) после инцидента для анализа паттернов и предотвращения повторений.

Перед началом работы убедитесь, что вы понимаете базовые концепции состояния Vagrant. При проблемах с определёнными доменами используйте специализированные файлы:
- [Основные концепции](./basic_concepts.md) — архитектура состояния, каталог ошибок, переменные окружения.
- [Дополнительная информация](./additional_info.md) — профилактика, бэкапы, CI/CD, air-gapped сценарии.
- [Настройка сети](../vagrant_networking.md) — детали конфигурации сетей, NFS, firewall.
- [Хранилище и общие папки](../vagrant_storage_and_folders.md) — virtiofs, rsync, управление дисками.
- [Apple Silicon](../vagrant_macos_apple_silicon.md) — специфика ARM64 и QEMU.

## Матрица быстрого диагностирования

| Симптом | Первая команда диагностики | Вероятная причина | Раздел |
| :--- | :--- | :--- | :--- |
| `Box not found` / таймаут загрузки | `vagrant box list` | Прокси, DNS, SSL, отсутствие box | [Сценарий 1](#сценарий-1-прокси-сервер-и-загрузка-образов) |
| `vagrant up` зависает на `Bringing machine up` | `ps aux \| grep vagrant` | Зависший процесс, блокировка файлов `.vagrant/` | [Сценарий 2](#сценарий-2-рассинхронизация-состояния-state-desync) |
| `Machine not found` | `vagrant global-status` | State Desync: `.vagrant/` ссылается на несуществующую ВМ | [Сценарий 2](#сценарий-2-рассинхронизация-состояния-state-desync) |
| `SSH timeout` / `Permission denied` | `vagrant ssh-config && ssh -vvv` | Ключ, cloud-init, firewall, sshd | [Сценарий 3](#сценарий-3-ssh-не-подключается) |
| `Mounting shared folders failed` | `vagrant ssh -c "findmnt"` | Guest Additions, firewall, права | [Сценарий 4](#сценарий-4-общие-папки) |
| `No space left on device` | `df -hT ~/.vagrant.d` | Пулы хранилища, кэш образов | [Сценарий 5](#сценарий-5-недостаточно-места-на-диске) |
| `VT-x is not available` | `systeminfo \| grep -i virtualization` | Hyper-V, WSL2, Memory Integrity | [Сценарий 9](#сценарий-9-конфликт-virtualbox-и-hyper-v-windows) |
| `Call to virNetworkCreate failed` | `virsh net-list --all` | Конфликт подсетей с Docker/VPN | [Сценарий 6](#сценарий-6-конфликты-сетевых-мостов) |
| ВМ зависает при загрузке | `virsh dump <domain> \| grep -i panic` | Проблемы с образом, нехватка RAM, nested | [Сценарий 7](#сценарий-7-вложенная-виртуализация-nested-virtualization) |

---

## Сценарий 1: Прокси-сервер и загрузка образов

**Симптом:** Vagrant не может скачать образы или выполнить `vagrant plugin install`. Ошибки вида `Failed to download box`, `SSL certificate problem`, `Connection timed out`.

**Причина:** В корпоративных сетях без настроенного прокси Vagrant блокируется на уровне фаервола. Кроме того, стандартные переменные `http_proxy` не передаются ядру Vagrant — требуются отдельные переменные `VAGRANT_HTTP_PROXY`.

### Диагностика

```bash
# 1. Проверьте доступность Vagrant Cloud напрямую
curl -I https://vagrantcloud.com
# → HTTP/2 200 (если прокси не настроен)

# 2. Проверьте переменные окружения
env | grep -i proxy
# → http_proxy=http://proxy.corp.example.com:3128

# 3. Проверьте DNS
dig vagrantcloud.com +short
# → 2606:4700:6803::6815:2481 (или другой IP)
```

### Решение

**На уровне хоста (для всех команд Vagrant):**

```bash
export http_proxy="http://proxy.corp.example.com:3128"
export https_proxy="http://proxy.corp.example.com:3128"
export no_proxy="localhost,127.0.0.1,.local,.corp.example.com"

# Специальные переменные для ядра Vagrant (загрузка образов)
export VAGRANT_HTTP_PROXY="${http_proxy}"
export VAGRANT_HTTPS_PROXY="${https_proxy}"
export VAGRANT_NO_PROXY="${no_proxy}"
# → VAGRANT_NO_PROXY=localhost,127.0.0.1,.local,.corp.example.com
```

**Версия для CI/CD (GitLab CI, Jenkins):**

```yaml
variables:
  HTTP_PROXY: "http://proxy.corp.example.com:3128"
  HTTPS_PROXY: "http://proxy.corp.example.com:3128"
  NO_PROXY: "localhost,127.0.0.1,.local"
  VAGRANT_HTTP_PROXY: "http://proxy.corp.example.com:3128"
  VAGRANT_HTTPS_PROXY: "http://proxy.corp.example.com:3128"
```

**Внутри гостевой ОС (для apt, yum, curl):**

```bash
vagrant plugin install vagrant-proxyconf
# → Installed 'vagrant-proxyconf' gem
```

```ruby
Vagrant.configure("2") do |config|
  if Vagrant.has_plugin?("vagrant-proxyconf")
    config.proxy.http     = ENV["HTTP_PROXY"] || "http://proxy.corp.example.com:3128"
    config.proxy.https    = ENV["HTTPS_PROXY"] || "http://proxy.corp.example.com:3128"
    config.proxy.no_proxy = "localhost,127.0.0.1,.local,.corp.example.com"
  end
end
```

### Требования (Prerequisites)

- Доступ к корпоративному прокси (`proxy.corp.example.com:3128`) или возможность настроить его обход.
- Права на установку плагинов (`vagrant plugin install`/`vagrant plugin repair`).

### Верификация

```bash
# Box должен скачиваться без ошибок
vagrant box add bento/ubuntu-24.04 --provider libvirt
# → Successfully added box 'bento/ubuntu-24.04' with provider 'libvirt'

# Плагин должен устанавливаться
vagrant plugin install vagrant-vbguest
# → Installed 'vagrant-vbguest' gem
```

### Отмена изменений

```bash
unset http_proxy https_proxy no_proxy VAGRANT_HTTP_PROXY VAGRANT_HTTPS_PROXY VAGRANT_NO_PROXY
# → All proxy variables unset
```

---

## Сценарий 2: Рассинхронизация состояния (State Desync)

**Симптом:** `Machine not found`, `vagrant halt` завершается ошибкой, `vagrant ssh` зависает или возвращает `Permission denied` для несуществующей ВМ.

**Причина:** Локальное состояние Vagrant (`.vagrant/`) было удалено вручную, повреждено или перемещено, но ресурсы у гипервизора остались. Файл `.vagrant/machines/<name>/<provider>/id` содержит устаревший или неверный UUID.

### Диагностика

```bash
# 1. Проверьте глобальный статус
vagrant global-status
# → id   name   provider   state   directory
#   123  default libvirt   running /Users/mac/project

# 2. Проверьте реальное состояние в гипервизоре
virsh list --all              # Libvirt
# → Name      State     Autostart
#   basic-jammy running    -
VBoxManage list vms           # VirtualBox
# → "MyVM" {12345678-abcd-efgh-ijkl-1234567890ab}

# 3. Сравним UUID из .vagrant/ с реальным
cat .vagrant/machines/default/libvirt/id
# → 2a1b3c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p
virsh list --all | grep <name>
# → basic-jammy       running   2a1b3c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p
```

### Требования (Prerequisites)

- Доступ к хост-гипервизору (Libvirt или VirtualBox) с правами на чтение списка ВМ.
- UUID из `.vagrant/machines/<name>/<provider>/id` должен совпадать с UUID в гипервизоре.

### Решение: Гранулярное восстановление

Если ВМ существует в гипервизоре, но Vagrant её не видит — исправьте только `id` файл:

```bash
# 1. Получите реальный UUID из гипервизора
virsh list --all
# → basic-jammy  running  2a1b3c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p

# 2. Исправьте id в .vagrant/
echo "2a1b3c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p" > .vagrant/machines/default/libvirt/id

# 3. Перепроверьте SSH-ключ
vagrant ssh-config
# → Host default
#   HostName 192.168.121.10
```

### Решение: Полный сброс

Если состояние невосстановимо:

```bash
# 1. Принудительное удаление (даже если ВМ не видна Vagrant)
vagrant destroy -f
# → ✓ Deleting VM
# → ✓ Deleting VM

# 2. Очистка глобального реестра
vagrant global-status --prune
# → id   name   provider   state   directory
#   (empty)

# 3. Удаление локальных метаданных проекта
rm -rf .vagrant

# 4. Повторный запуск
vagrant up
# → Bringing machine 'default' up...
```

### Валидация

```bash
vagrant status
# → default                  running (libvirt)
vagrant ssh -c "whoami"
# → vagrant
```

### Восстановление данных перед destroy

Если данные внутри ВМ критичны — сначала используйте `guestmount` или SCP (см. [Сценарий 17](#сценарий-17-восстановление-данных-из-повреждённой-вм)). Для профилактики — см. [Дополнительная информация](./additional_info.md) раздел «Регулярная очистка».

---

## Сценарий 3: SSH не подключается

**Симптом:** `vagrant ssh` зависает или выдает `Permission denied (publickey)`, `Connection timed out`.

### Требования (Prerequisites)

- ВМ должна быть в состоянии `running` (`vagrant status`).
- SSH-ключ в `.vagrant/machines/<name>/<provider>/private_key` должен существовать и иметь права `600`.

### Диагностика

```bash
# 1. Просмотр эффективной SSH-конфигурации
vagrant ssh-config
# → Host default
#   HostName 192.168.121.10
#   User vagrant
#   Port 22

# 2. Прямое подключение с детализацией
ssh -vvv -i .vagrant/machines/default/libvirt/private_key vagrant@192.168.121.10 -p 22
# → debug1: Trying 192.168.121.10...
#   debug1: SSH2_MSG_KEXINIT sent

# 3. Проверка доступности порта
nc -zv 192.168.121.10 22
# → Connection to 192.168.121.10 port 22 [tcp/ssh] succeeded!
```

### Возможные причины и решения

| Причина | Решение |
| :--- | :--- |
| **Рассинхронизация ключа** | `vagrant destroy -f && vagrant up` для перегенерации. Или удалите ключ: `rm -f .vagrant/machines/default/libvirt/private_key && vagrant up` |
| **Падение sshd** | Подключитесь через GUI провайдера (virt-manager, VirtualBox UI) и выполните: `sudo systemctl restart sshd` |
| **Cloud-init блокирует SSH** | Подождите 2-3 минуты после `vagrant up`. В некоторых образах (например, Ubuntu cloud) SSH недоступен до завершения cloud-init. |
| **Firewall внутри гостя** | `vagrant ssh -c "sudo ufw allow 22/tcp"` или отключите ufw временно |
| **Сеть недоступна** | Проверьте `ip a` внутри ВМ через GUI. Убедитесь, что интерфейс получил IP. |
| **Изменённый порт** | Проверьте `config.vm.network "forwarded_port"` в Vagrantfile. По умолчанию для QEMU (Apple Silicon) порт SSH — **50022**, не 2222. |

### Валидация

```bash
vagrant ssh -c "whoami"
# → vagrant
```

### Очистка

```bash
# Для принудительной перегенерации SSH-ключа:
rm -f .vagrant/machines/default/libvirt/private_key
vagrant up
# → SSH key regenerated
```

---

## Сценарий 4: Общие папки

**Симптом:**
```
Mounting shared folders failed.
```

**Причина:** Несовпадение версий Guest Additions (VirtualBox), отсутствие `virtiofs`/`nfs`, проблемы с правами или firewall. См. такжe [Определения: Guest Additions](./basic_concepts.md).

### Требования (Prerequisites)

- ВМ в состоянии `running`.
- Установленный и совместимый Guest Additions (VirtualBox) или `qemu-guest-agent` (Libvirt).

### Диагностика

```bash
# 1. Проверка типа монтирования
vagrant ssh -c "findmnt -t nfs4,virtiofs,vboxsf,9p"
# → /vagrant  /Users/mac/project  virtiofs  rw,relatime

# 2. Проверка доступности NFS-портов (если используется NFS)
sudo rpcinfo -p <host_ip> | grep nfs
# → nfs       2049/tcp

# 3. Проверка логов гипервизора
# Libvirt:
sudo journalctl -u libvirtd -n 50 | grep -i error
# → (пустой вывод = OK)
# VirtualBox:
VBoxManage list runningvms
# → "default" {12345678-abcd-efgh-ijkl}
```

### Решение: VirtualBox

```bash
# Автоматическое обновление Guest Additions
vagrant plugin install vagrant-vbguest
# → Installed 'vagrant-vbguest' gem
vagrant reload
```

### Решение: Libvirt

Переключитесь на `virtiofs` (рекомендуется для Vagrant 2.4+):

```ruby
config.vm.synced_folder ".", "/vagrant",
  type: "virtiofs",
  virtiofs_direct_io: true
```

Или используйте NFS:

```ruby
config.vm.network "private_network", ip: "192.168.56.10"
config.vm.synced_folder ".", "/vagrant",
  type: "nfs",
  nfs_version: 4,
  mount_options: ["actimeo=1"]
```

### Валидация

```bash
vagrant ssh -c "findmnt -t virtiofs,nfs4"
# → /vagrant  /Users/mac/project  virtiofs  rw,relatime...
```

### Очистка зависших монтирований

```bash
# Принудительное размонтирование
vagrant ssh -c "sudo umount -l /vagrant"
# → umount: /vagrant: 1 filesystem detached
vagrant reload
# → Bringing machine 'default' up...
```

---

## Сценарий 5: Недостаточно места на диске

**Симптом:**
```
Error while creating new volume: No space left on device
```

**Причина:** Накопленные образы, неиспользуемые тома, сброшенные снимки и системные логи.

### Требования (Prerequisites)

- Доступ к каталогу хоста `~/.vagrant.d` и `/var/lib/libvirt/images`.
- Права `sudo` для управления томами Libvirt и системными логами.

### Диагностика

```bash
# 1. Проверка точек монтирования
df -hT ~/.vagrant.d /var/lib/libvirt/images
# → Filesystem     Type      Size  Used Avail Use% Mounted on
#   /dev/sda1      ext4       50G   45G  2.1G  95% /var/lib/libvirt/images

# 2. Поиск больших файлов
du -sh ~/.vagrant.d/boxes/*
# → 8.2G    /home/user/.vagrant.d/boxes/bento
du -sh /var/lib/libvirt/images/*
# → 15G     /var/lib/libvirt/images/default_vm1.qcow2
```

```bash
# 3. Проверка пулов Libvirt
virsh --connect qemu:///system pool-list --all
# → Name    State   Autostart
#   default active   yes
virsh --connect qemu:///system pool-info default
# → Name:           default
#   State:          active
#   Autostart:      yes
```

### Решение

```bash
# 1. Очистка устаревших образов (оставляет последнюю версию)
vagrant box prune --keep 1
# → Removing box 'bento/ubuntu-24.04' (version 202501.0)

# 2. Удаление неиспользуемых томов Libvirt
virsh --connect qemu:///system vol-list default | grep -v "Name" | \
  xargs -n1 virsh vol-delete --pool default
# → (тома удалены)

# 3. Очистка системных логов хоста
sudo journalctl --vacuum-time=7d
# → Vacuuming journal...

# 4. Удаление сиротских snapshot'ов VirtualBox
VBoxManage list hdds | grep "^UUID:" | while read uuid; do
  VBoxManage modifyhd $uuid --compact
done
# → 0%...100% (конденсация завершена)

# 5. Расширение пула (если диск хоста позволяет)
# Для LVM:
sudo lvextend -L +20G /dev/vg0/var-lib-libvirt-images
# → Extending logical volume /dev/vg0/var-lib-libvirt-images
sudo resize2fs /dev/vg0/var-lib-libvirt-images
# → Resizing the filesystem on /dev/vg0/... to ...
```

### Очистка / Отмена изменений

```bash
# Если расширение диска нежелательно — удалите неиспользуемые тома вручную:
virsh --connect qemu:///system vol-delete <volume> --pool default
# → Volume <volume> deleted
```

### Валидация

```bash
df -hT /var/lib/libvirt/images
# → Доступное место увеличилось
```

---

## Сценарий 6: Конфликты сетевых мостов

**Симптом:**
```
Call to virNetworkCreate failed: Requested operation is not valid: network is already active
```
или `IP address is already in use`.

**Причина:** Подсеть `192.168.121.0/24` (по умолчанию для Libvirt) пересекается с Docker, VPN (Tailscale, ZeroTier) или другим экземпляром Vagrant.

### Требования (Prerequisites)

- Доступ к `iptables`/`ip` командам на хосте.
- Права `sudo` для управления сетями Libvirt.

### Диагностика

```bash
# 1. Список всех сетей Libvirt
virsh --connect qemu:///system net-list --all
# → Name               State      Autostart
#   default            active     yes
#   vagrant-libvirt    active     yes

# 2. Проверка занятых IP
sudo arp-scan --interface=virbr0 --localnet
# → 192.168.121.10  00:11:22:33:44:55  QEMU

# 3. Проверка конфликтов с Docker
docker network ls
# → bridge    bridge  ...
docker network inspect bridge | grep "Subnet"
# → "Subnet": "172.17.0.0/16"
```

### Решение

**Вариант A: Смена подсети в Vagrantfile**

```ruby
config.vm.network "private_network", ip: "10.10.10.10"
# Используйте подсети из диапазона 10.0.0.0/8 или 172.16.0.0/12
# избегайте 192.168.121.0/24 (Libvirt по умолчанию)
```

**Вариант B: Перезапуск зависшей сети**

```bash
virsh --connect qemu:///system net-destroy vagrant-libvirt
# → Network vagrant-libvirt destroyed
virsh --connect qemu:///system net-start vagrant-libvirt
# → Network vagrant-libvirt started
```

**Вариант C: Удаление неиспользуемой сети**

```bash
virsh --connect qemu:///system net-undefine vagrant-libvirt-old
# → Network vagrant-libvirt-old has been undefined
```

### Валидация

```bash
vagrant up
# → Default: SSH address: 10.10.10.10:22
```

### Очистка

```bash
# Если сеть была удалена временно — восстановите:
virsh --connect qemu:///system net-start vagrant-libvirt
# → Network vagrant-libvirt started
```

---

## Сценарий 7: Вложенная виртуализация (Nested Virtualization)

**Симптом:** ВМ запускается, но внутри неё невозможно запустить Docker (KVM), Minikube или другой гипервизор. Ошибки: `kvm: failed to open /dev/kvm`, `virt-fw-arn: KVM not supported`.

### Требования (Prerequisites)

- Физический хост с поддержкой VT-x (Intel) или AMD-V (AMD).
- Kernel module `kvm_intel`/`kvm_amd` загружен на хосте.

### Диагностика

```bash
# 1. Проверка на физическом хосте (L0)
cat /sys/module/kvm_intel/parameters/nested   # Intel (должно быть Y)
# → Y
cat /sys/module/kvm_amd/parameters/nested     # AMD (должно быть 1)
# → 1

# 2. Проверка внутри гостевой ОС (L1)
vagrant ssh -c "lsmod | grep kvm"
# → kvm_intel  ...
vagrant ssh -c "dmesg | grep -i kvm"
# → kvm: nested KVM enabled
```

### Решение

**Включение nested на хосте:**

```bash
# Intel
echo "options kvm_intel nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
# → Written: /etc/modprobe.d/kvm-nested.conf
sudo modprobe -r kvm_intel && sudo modprobe kvm_intel
# → (module reloaded with nested=1)

# AMD
echo "options kvm_amd nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
# → Written: /etc/modprobe.d/kvm-nested.conf
sudo modprobe -r kvm_amd && sudo modprobe kvm_amd
```

**Конфигурация Vagrantfile:**

```ruby
config.vm.provider "libvirt" do |lv|
  lv.nested = true
  lv.cpu_mode = "host-passthrough"
  lv.cpus = 4
  lv.memory = 4096
end
```

### Валидация

```bash
vagrant ssh -c "kvm-ok"  # Ubuntu/Debian
# → KVM acceleration can be used

vagrant ssh -c "docker run --rm --privileged alpine uname -a"
# → Должен работать без ошибок
```

### Очистка

```bash
# Отключение nested virtualization (если больше не нужно):
echo "options kvm_intel nested=0" | sudo tee /etc/modprobe.d/kvm-nested.conf
# → Written
sudo modprobe -r kvm_intel && sudo modprobe kvm_intel
```

### Примечание по производительности

Nested virtualization снижает производительность на 20-40% из-за двойной трансляции адресов (EPT/VP). Для production-сред используйте bare-metal L1 или облачные инстансы с аппаратной поддержкой nested (OpenStack, AWS `c5.metal`).

---

## Сценарий 8: Провайдеры и архитектурные ограничения (Apple Silicon)

**Симптом 1:** `The provider 'virtualbox' is not supported on this architecture.`

**Причина:** Apple Silicon (ARM64) не поддерживает VirtualBox. Требуется QEMU или VMware.

### Диагностика

```bash
# Проверка архитектуры хоста
arch -64 uname -m
# → aarch64

# Проверка доступных провайдеров
vagrant plugin list | grep -i "vagrant-q\|vagrant-vm"
# →vagrant-qemu-colcha (0.x.x, global)
```

### Требования (Prerequisites)

- На Apple Silicon: установлен плагин `vagrant-qemu` или `vagrant-vmware-desktop`.
- На ARM64: box должен иметь тег `arm64` или `aarch64`.
- `rsync` установлен (для синхронизации файлов на macOS).

### Решение

**Симптом 1:** Используйте `qemu` или `vmware_desktop` провайдер:

```bash
# Использование qemu провайдера
vagrant up --provider=qemu
# → Bringing machine 'default' up with 'qemu' provider

# Или vmware_desktop (если установлен)
vagrant up --provider=vmware_desktop
# → Bringing machine 'default' up with 'vmware_desktop' provider
```

См. [Vagrant на Apple Silicon](../vagrant_macos_apple_silicon.md).

**Симптом 2:** ВМ на QEMU зависает при загрузке.

**Причина:** Попытка запуска `x86_64` образа на ARM64 хосте без поддержки эмуляции.

**Решение:** Используйте образы с тегом `arm64` или `aarch64`:

```bash
vagrant box list | grep arm64
# → generic/ubuntu2204-arm64
```

**Симптом 3:** `rsync` не найден при синхронизации на macOS.

**Решение:**

```bash
brew install rsync
# → ==> Downloading https://brew.sh/.../rsync...
#   -> Installing dependencies for rsync
```

QEMU на macOS требует `rsync` как метод синхронизации по умолчанию.

### Валидация

```bash
vagrant status
# → default                  running (qemu)
vagrant ssh -c "uname -m"
# → aarch64
```

### Очистка

```bash
# Если архитектурный конфликт не решить — удалите ВМ и создайте заново:
vagrant destroy -f
rm -rf .vagrant
```

---

## ~~Сценарий 15~~: Устаревший дубликат (объединён с Сценарием 8)

> **Примечание:** Этот сценарий был объединён с [Сценарием 8](#сценарий-8-провайдеры-и-архитектурные-ограничения-apple-silicon) в связи с полным дублированием содержимого. Оригинальная версия сохранена в [Vagrant на Apple Silicon](../vagrant_macos_apple_silicon.md).

---

## Сценарий 9: Конфликт VirtualBox и Hyper-V (Windows)

**Симптом:** VirtualBox ВМ падает с ошибкой `VT-x is not available` или работает крайне медленно (иконка черепахи).

**Причина:** Hyper-V (или функции на его базе: WSL2, Memory Integrity, Docker Desktop) захватывает эксклюзивный доступ к аппаратной виртуализации.

### Требования (Prerequisites)

- Windows 10/11 хост с включённым Hyper-V или Memory Integrity.
- Права администратора для выполнения `Disable-WindowsOptionalFeature` и `bcdedit`.

### Диагностика

```powershell
# Проверка статуса Hyper-V
Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
# → State : Enabled

# Проверка Memory Integrity
msinfo32 | select-string "Memory Integrity"
# → Memory Integrity : On
```

### Решение A: Отключение Hyper-V (если VirtualBox критичен)

```powershell
Disable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
# → Online: True
bcdedit /set hypervisorlaunchtype off
# → The operation completed successfully.
# Требуется перезагрузка
```

### Решение B: Использование Hyper-V как провайдера

```bash
vagrant up --provider=hyperv
# → Bringing machine 'default' up with 'hyperv' provider
```

**Примечание:** Hyper-V провайдер в Vagrant имеет ограниченную поддержку сетей (только DHCP/NAT).

### Валидация

```powershell
# После перезагрузки:
Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All | select State
# → State : Disabled
```

### Очистка

```powershell
# Восстановление Hyper-V (если решено вернуться):
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
bcdedit /set hypervisorlaunchtype auto
# → Требуется перезагрузка
```

---

## Сценарий 10: Ошибки при скачивании образов

**Симптом:**
```
SSL certificate problem: unable to get local issuer certificate
```
или `The request timed out`.

**Причина:** Корпоративный SSL-прокси, устаревшие CA-сертификаты, DNS-неполадки или проблемы с сетью Vagrant Cloud.

### Требования (Prerequisites)

- Корневой CA-сертификат прокси добавлен в системное доверие (`update-ca-certificates` / `trust anchor`).
- Доступ к `vagrantcloud.com` или локальное зеркало.

### Диагностика

```bash
# Проверка SSL-цепочки
curl -v https://vagrantcloud.com
# → SSL connection using TLSv1.3 / TLS_AES_256_GCM_SHA384

# Проверка DNS
nslookup vagrantcloud.com
# → Address:  104.21.30.209#53
```

### Решение

**Крайняя мера — отключение проверки SSL (только для отладки, не в проде):**

```bash
vagrant box add <name> --insecure
# → Successfully added box '<name>'
```

**Альтернативное зеркало:**

```bash
# Скачайте .box вручную через браузер на машине с доступом
vagrant box add my-box ./package.box --provider libvirt
# → Successfully added box 'my-box' with provider 'libvirt'
```

**Фиксация версии и checksum:**

```ruby
config.vm.box = "bento/ubuntu-24.04"
config.vm.box_version = "202501.0"
config.vm.box_download_checksum = "sha256:abc123..."
config.vm.box_download_checksum_type = "sha256"
```

### Валидация

```bash
vagrant box list | grep bento
# → bento/ubuntu-24.04 (libvirt)
vagrant box update --dry-run
# → Box is at latest version
```

### Очистка

```bash
# Если --insecure использовался для отладки — замените на корректный сертификат:
vagrant box remove <name> --provider libvirt
sudo update-ca-certificates --fresh
# → Updating certificates in /etc/ssl/certs...
```

---

## Сценарий 11: Провижининг и automation failures

**Симптом:** `vagrant provision` завершается с ошибкой, скрипты отрабатывают некорректно, Ansible теряет связь с ВМ.

**Причина:** Несвоевременные таймауты, отсутствие идемпотентности, проблемы с сетью или правами в гостевой ОС.

### Требования (Prerequisites)

- ВМ в состоянии `running` с доступом по SSH.
- Провижининг-скрипты находятся в синхронизированной папке (обычно `/vagrant`).
- Пользователь `vagrant` имеет права `sudo` без пароля.

### Диагностика

```bash
# 1. Запуск с детальным логированием
VAGRANT_LOG=debug vagrant provision 2>&1 | tee provision_debug.log
# → DEBUG ... Provisioning with shell...

# 2. Проверка статуса провижинера
vagrant status
# → default                  running (libvirt)

# 3. Ручной запуск провижининга
vagrant ssh -c "sudo /vagrant/scripts/setup.sh"
# → Configuring services...
```

### Распространённые причины

| Причина | Решение |
| :--- | :--- |
| **Idempotency** | Скрипты должны быть идемпотентными. Используйте `systemctl is-active` вместо `systemctl start`. |
| **Таймауты** | Увеличьте `config.vm.boot_timeout` до 600–1200 секунд для CI. |
| **Права sudo** | Убедитесь, что пользователь `vagrant` имеет права на `sudo` без пароля. |
| **Сеть в гостевой ОС** | Проверьте `ip a` и `ip route` перед запуском провижининга. |
| **Ansible: inconsistent inventory** | Используйте `config.vm.provision "ansible"` с явным указанием `playbook`. |

### Валидация

```bash
vagrant up --no-provision
# → Bringing machine 'default' up...
vagrant provision
# → Succeeded!
```

### Очистка

```bash
# Очистка временных файлов провижининга:
rm -f provision_debug.log
```

---

## Сценарий 12: Дисковое пространство и производительность

**Симптом:** ВМ работает медленно, `iotop` показывает высокую нагрузку, `df -h` показывает 100% utilisation на диске.

### Требования (Prerequisites)

- Доступ к хост-диску `/var/lib/libvirt/images` (или аналогичному пути для VirtualBox).
- Права `sudo` для управления томами и LVM.

### Диагностика

```bash
# 1. Внутри ВМ
vagrant ssh -c "df -h /"
# → /dev/vda1      20G   18G  1.2G  95% /
vagrant ssh -c "iostat -x 1 5"
# → avg-cpu...  %util  85.00

# 2. На хосте
df -hT /var/lib/libvirt/images
# → /dev/sda2      ext4  100G   92G  5.1G  95% /var/lib/libvirt/images
iostat -x 1 5
# → nvme0n1  ...  %util  78.00
```

### Решение: Расширение диска

```bash
# 1. Увеличение размера виртуального диска (Libvirt)
qemu-img resize /var/lib/libvirt/images/<vm_name>.qcow2 +20G
# → Image resized

# 2. Перезагрузка ВМ
vagrant reload
# → Reloading machine 'default'...

# 3. Расширение раздела внутри гостевой ОС
vagrant ssh -c "sudo growpart /dev/vda 1"
# → CHANGED: partition=1 ... 
vagrant ssh -c "sudo resize2fs /dev/vda1"
# → Resizing the filesystem on /dev/vda1 to ...
```

### Валидация

```bash
vagrant ssh -c "df -h /"
# → /dev/vda1      40G   18G  21G  47% /
```

### Очистка (rollback)

```bash
# Если расширение диска не удалось — уменьшите обратно:
qemu-img resize /var/lib/libvirt/images/<vm_name>.qcow2 -20G
# → Image resized (may need to shrink filesystem first)
```

### Решение: Переход на virtiofs

Если общие папки тормозят, переключитесь с NFS на `virtiofs`:

```ruby
config.vm.synced_folder ".", "/vagrant", type: "virtiofs"
```

---

## Сценарий 13: Процедура пост-мортем

При сложных инцидентах собирайте артефакты в определённом порядке для последующего анализа и post-mortem документирования.

### Требования (Prerequisites)

- Справочный журнал событий (logbook) для фиксации времени и контекста инцидента.
- Убедитесь, что ВМ находится в состоянии `poweroff` или `crashed` (не `running`) для получения чистого дампа.

### Диагностика

Определите тип инцидента перед сбором артефактов:

```bash
# 1. Определите состояние ВМ
vagrant status
# → default                  poweroff (libvirt)

# 2. Проверьте журнал событий ВМ
vagrant ssh -c "sudo journalctl -b -1 -p err" 2>/dev/null || echo "VM not accessible"
# → (или выведите ошибки предыдущей загрузки)

# 3. Сбор сводки о системе хоста
uname -a > /tmp/host-info.txt
sudo dmididecode -s system-product-name >> /tmp/host-info.txt
```

### Шаг 1: Снимок состояния

```bash
# Глобальный статус
vagrant global-status --prune > /tmp/vagrant-global-status.txt
# → id   name   provider   state   directory

# Статус конкретного проекта
vagrant status > /tmp/vagrant-status.txt
# → default                  running (libvirt)

# Список образов
vagrant box list > /tmp/vagrant-boxes.txt
# → bento/ubuntu-24.04 (libvirt)

# Список плагинов
vagrant plugin list > /tmp/vagrant-plugins.txt
# → vagrant-libvirt (0.x.x, global)
```

### Шаг 2: Сбор логов

```bash
# Debug-лог Vagrant
VAGRANT_LOG=debug vagrant up 2>&1 | tee /tmp/vagrant-debug.log
# → DEBUG ... Starting domain 'default'

# Логи гипервизора
# Libvirt:
sudo journalctl -u libvirtd --since "1 hour ago" > /tmp/libvirtd.log
# → (journal entries written)
sudo journalctl -u virtlogd --since "1 hour ago" > /tmp/virtlogd.log
# → (journal entries written)

# VirtualBox:
VBoxManage list systemlogs > /tmp/vbox-system-logs.txt
# → VMName: default
```

### Шаг 3: Анализ паттернов

```bash
grep -iE "error|timeout|failed|panic|fatal" /tmp/vagrant-debug.log | head -50
# → [ERROR ] ... timed out waiting for SSH
```

### Шаг 4: Документирование

```markdown
## Incident Report: <date>

**Симптом:** <error message>
**ВМ:** <name>
**Провайдер:** libvirt/virtualbox
**Хост:** <OS, kernel>

**Шаги воспроизведения:**
1. ...
2. ...

**Артефакты:**
- /tmp/vagrant-debug.log
- /tmp/libvirtd.log

**Решение:**
<краткое описание>
```

### Валидация

```bash
# Проверка полноты артефактов
ls -la /tmp/vagrant-debug.log /tmp/libvirtd.log /tmp/vagrant-status.txt /tmp/vagrant-boxes.txt /tmp/vagrant-plugins.txt
# → Все файлы присутствуют, размер > 0

# Проверка наличия ключевых маркеров в логах
grep -c "error\|failed\|timeout" /tmp/vagrant-debug.log
# → 5 (количество найденных маркеров)
```

### Очистка

```bash
# Удаление временных артефактов post-mortem:
rm -f /tmp/vagrant-debug.log /tmp/libvirtd.log /tmp/virtlogd.log /tmp/vbox-system-logs.txt
rm -f /tmp/vagrant-global-status.txt /tmp/vagrant-status.txt /tmp/vagrant-boxes.txt /tmp/vagrant-plugins.txt
rm -f /tmp/host-info.txt /tmp/vm-dump.log
```

---

## Сценарий 14: Мульти-машинные конфигурации

**Симптом:** `vagrant up` запускает только часть ВМ, одна из машин не стартует, зависимые сервисы не видят друг друга.

**Причина:** Нарушен порядок запуска, зависимые сервисы стартуют до готовности базы, провижининг конфликтует с сетевыми настройками.

### Требования (Prerequisites)

- Машины определены в `Vagrantfile` с `config.vm.define`.
- Сеть между машинами настроена (`private_network` или `host-only`).

### Диагностика

```bash
# 1. Проверка статуса всех машин
vagrant status
# → web                    not created (libvirt)
#   db                     running (libvirt)

# 2. Проверка сети между машинами
vagrant ssh web -c "ping -c1 db.local"
# → PING db.local (192.168.56.11): 4 bytes from ...
vagrant ssh db -c "ss -tulnp"
# → 5432  LISTEN  postgres
```

### Решение

**Явный запуск в правильном порядке:**

```bash
vagrant up db
# → Bringing machine 'db' up...
vagrant up web
# → Bringing machine 'web' up...
```

**Автоматическое ожидание готовности:**

```ruby
config.vm.provision "shell", inline: <<-SHELL
  until nc -z 192.168.56.11 5432; do
    echo "Waiting for DB..."
    sleep 2
  done
SHELL
# → Waiting for DB...
#   Connected!
```

**Изоляция проблемной ВМ:**

```bash
# Запуск без провижининга для диагностики
vagrant up web --no-provision
# → Vagrant machine 'web' is running
vagrant provision web
# → Setup complete
```

### Валидация

```bash
# Проверка связности между машинами
vagrant ssh web -c "ping -c3 db.local"
# → 3 packets transmitted, 3 received

# Проверка порта БД
vagrant ssh db -c "ss -tulnp | grep 5432"
# → 5432  LISTEN  postgres
```

### Очистка

```bash
# Если временно изменены сетевые настройки — удалите статические IP:
vagrant destroy -f
rm -rf .vagrant
```

---

## Сценарий 16: Синхронизация времени (Clock Drift)

**Симптом:** Ошибки TLS-рукопожатий, истечение сертификатов, сбои Kerberos, репликация в PostgreSQL/MongoDB падает.

**Причина:** Расхождение времени между хостом и гостем более 5 минут. В виртуализированных средах drift может достигать нескольких секунд за час, особенно после `vagrant suspend/resume`.

### Требования (Prerequisites)

- ВМ в состоянии `running`.
- `systemd-timesyncd` или `ntpd` установлен и доступен в гостевой ОС.

### Диагностика

```bash
# На хосте
date -u
# → Sat Oct 17 08:22:34 UTC 2026

# Внутри ВМ
vagrant ssh -c "date -u"
# → Sat Oct 17 08:30:12 UTC 2026

vagrant ssh -c "timedatectl show | grep NTPSynchronized"
# → NTPSynchronized=no
```

### Решение

```bash
# Включение NTP внутри гостевой ОС
vagrant ssh -c "sudo timedatectl set-ntp true"
# → (no output = success)
vagrant ssh -c "sudo timedatectl status"
# → Synchronized: yes

# Проверка синхронизации
vagrant ssh -c "timedatectl show | grep NTPSynchronized"
# → NTPSynchronized=yes
```

### Валидация

```bash
vagrant ssh -c "chrony sources -v"
# → MS Name/IP address         Stratum  Poll  ...
#   ^* clock.example.com          3     4   ...
```

### Очистка

```bash
# Для отключения NTP (если требуется ручное управление временем):
vagrant ssh -c "sudo timedatectl set-ntp false"
# → (no output = success)
```

---

## Сценарий 17: Восстановление данных из повреждённой ВМ

**Симптом:** ВМ не загружается, но диск (том) доступен. Требуется извлечение данных без загрузки ОС.

### Требования (Prerequisites)

- Доступ к диску ВМ на хосте (qcow2, vdi, raw).
- Установлен `libguestfs-tools` (`guestmount`) на хосте.
- Если используется SCP — ВМ должна отвечать на SSH, даже если приложения не работают.

### Диагностика

```bash
# 1. Проверка доступности диска ВМ
ls -lh /var/lib/libvirt/images/<vm_name>.qcow2
# → -rw-------  1 libvirt-qemu libvirt  15G ...

# 2. Проверка целостности образа
qemu-img check /var/lib/libvirt/images/<vm_name>.qcow2
# → No errors detected

# 3. Проверка доступности SSH (для Solution B)
nc -zv <vm_ip> 22
# → Connection to <vm_ip> port 22 [tcp/ssh] succeeded!
```

### Решение A: Монтирование через guestmount

```bash
# Установка libguestfs
sudo apt-get install -y libguestfs-tools
# → Setting up libguestfs-tools (1:1.48...)

# Монтирование qcow2 образа (только для чтения)
sudo guestmount -a /var/lib/libvirt/images/<vm_name>.qcow2 -i --ro /mnt/vm-recovery
# → (mount successful)

# Копирование данных
sudo cp -r /mnt/vm-recovery/home/vagrant/project ./recovered/
# → copied 150 files

# Размонтирование
sudo guestunmount /mnt/vm-recovery
# → unmounted
```

### Решение B: Ручной экспорт через SCP

```bash
# Получение параметров SSH
vagrant ssh-config > ssh_config
# → Host default
#   HostName 192.168.121.10

# Копирование данных
scp -F ssh_config default:/var/lib/mysql/backup.sql ./
# → backup.sql                                    100%  45MB
```

### Решение C: Подключение диска к другой ВМ

Через интерфейс гипервизора подключите диск повреждённой ВМ как дополнительное устройство к рабочей ВМ, затем смонтируйте внутри неё:

```bash
# Libvirt: подключение диска как второго устройства
virsh attach-disk <working_vm> /var/lib/libvirt/images/<vm_name>.qcow2 vdb --read-only
# → Disk attached at vdb
```

### Валидация

```bash
ls -la recovered/
# → drwxr-xr-x  project
#   drwxr-xr-x  .vagrant
```

### Очистка

```bash
# Отсоединение диска от восстанавливающей ВМ:
virsh detach-disk <working_vm> vdb --confirm
# → Disk detached from vdb
```

---

## Сценарий 18: Плагины и зависимости

**Симптом:** `Plugin error`, `vagrant up` завершается с ошибкой загрузки плагина после обновления Ruby или Vagrant.

**Причина:** Incompatibility между версиями Ruby/Vagrant и установленных плагинов, повреждённый кэш gem.

### Требования (Prerequisites)

- Vagrant запущен с системным Ruby или встроенным (Vagrant 2.4+ bundle).
- Права на чтение/запись в `~/.vagrant.d/`.

### Диагностика

```bash
# Проверка установленных плагинов
vagrant plugin list
# → vagrant-libvirt (0.x.x, global)

# Попытка восстановления
vagrant plugin repair
# → Repairing installed plugins...
```

### Решение

```bash
# Полная очистка и переустановка всех плагинов
vagrant plugin expunge --reinstall
# → Removed ALL installed gems (12)
#   Reinstall complete

# Или точечное обновление
vagrant plugin update vagrant-vbguest
# → Updating vagrant-vbguest to 0.x.x
vagrant plugin update vagrant-libvirt
# → Updating vagrant-libvirt to 0.x.x
```

### Валидация

```bash
vagrant plugin list
# → vagrant-libvirt (0.x.x, global), vagrant-vbguest (0.x.x, global)
vagrant up
# → Bringing machine 'default' up...
```

### Очистка

```bash
# Полная очистка без переустановки (если плагины конфликтуют)
vagrant plugin expunge
# → Removed ALL installed gems
```

---

## Сценарий 19: Офлайн-работа (Air-Gapped среды)

**Симптом:** `vagrant up` завершается с ошибкой `Failed to download box` или `Connection timed out` в изолированной сети без доступа в интернет.

**Причина:** Отсутствие локального кэша box'ов и плагинов в air-gapped окружении.

### Требования (Prerequisites)

- Доступ к машине с интернетом для подготовки артефактов.
- USB-накопитель или внутренний репозиторий для переноса `box`-файлов и плагинов.
- На целевой машине: установленный Vagrant и Ruby для плагинов.

**Подготовка на машине с доступом (Диагностика):**

```bash
# 1. Скачивание box-файла
vagrant box add bento/ubuntu-24.04 --provider libvirt
# → Successfully added box 'bento/ubuntu-24.04' (version: 202501.0)

# 2. Экспорт списка плагинов
vagrant plugin list > plugins.txt
# → vagrant-libvirt (0.x.x, global)

# 3. Упаковка проекта
tar czf vagrant-offline.tar.gz Vagrantfile .vagrant/
# → Vagrantfile
#   .vagrant/
```

### Решение

Перенос и установка в изолированной сети:

```bash
# Установка плагинов (если есть локальный кэш)
vagrant plugin install vagrant-libvirt
# → Installed 'vagrant-libvirt' gem

# Добавление box из локального файла
vagrant box add bento/ubuntu-24.04 ./bento-ubuntu-24.04-libvirt.box --provider libvirt
# → Successfully added box 'bento/ubuntu-24.04' with provider 'libvirt'
```

### Валидация

```bash
vagrant box list | grep bento
# → bento/ubuntu-24.04 (libvirt)
vagrant plugin list
# → vagrant-libvirt (0.x.x, global)
```

### Очистка

```bash
# Если box был добавлен с неправильным именем — удалите:
vagrant box remove bento/ubuntu-24.04 --provider libvirt
# → Removed box 'bento/ubuntu-24.04'
```

---

## Сценарий 20: Зависание и паника ядра (Kernel Panic)

**Симптом:** ВМ зависает на загрузке, экран остается чёрным, в консоли гипервизора виден `panic`.

### Требования (Prerequisites)

- Доступ к гипервизору (Libvirt или VirtualBox) с правами на получение дампа.
- Понимание работы с `virsh`/`VBoxManage` командами.

### Диагностика

```bash
# Libvirt: получение дампа логов
sudo virsh dump <domain_name> /tmp/vm-dump.log
# → Domain <name> dump saved

# Поиск panic в логах
grep -i "kernel panic\|general protection fault\|oops" /tmp/vm-dump.log
# → [12345.678901] Kernel panic - not syncing: Fatal exception
```

### Распространённые причины

| Причина | Решение |
| :--- | :--- |
| **Несовместимость образа** | Используйте образы с поддержкой вашего провайдера (например, `bento/ubuntu-24.04` для VirtualBox/Libvirt). |
| **Недостаток RAM** | Увеличьте `config.vm.provider "libvirt" do \|lv\| lv.memory = 2048 end` |
| **Проблемы с облачными образами** | Избегайте образов с предустановленным cloud-init для офлайн-сред. Используйте `bento/*` или `generic/*`. |
| **Nested virtualization** | Проверьте поддержку nested на хосте (см. [Сценарий 7](#сценарий-7-вложенная-виртуализация-nested-virtualization)). |

### Решение

```bash
# 1. Запуск в safe mode (если поддерживается)
vagrant up --provider=libvirt
# → Bringing machine 'default' up...

# 2. Отключение проблемного провижининга
vagrant up --no-provision
# → Default: SSH address: 192.168.121.10

# 3. Если ВМ стартовала — проверьте логи внутри
vagrant ssh -c "sudo journalctl -b -p err"
# → Oct 17 08:00:00 vm kernel: [    1.234567] error ...
```

### Валидация

```bash
vagrant ssh -c "dmesg | grep -c panic"
# → 0 (количество паник за текущую загрузку)
```

### Очистка

```bash
# Если проблема в oversubscribed ресурсах — уменьшите back:
# В Vagrantfile:
config.vm.provider "libvirt" do |lv|
  lv.memory = 2048
# → Memory reduced to 2GB
end
```

---

## Сценарий 21: Безопасность и секреты

**Симптом:** В Vagrantfile обнаружены пароли, API-ключи или SSH-ключи в открытом виде. При коммите в репозиторий секреты становятся доступны всей команде.

**Причина:** Жёсткая привязка секретов в конфигурационных файлах. Отсутствие `.gitignore` для файлов с токенами.

### Требования (Prerequisites)

- Vagrantfile находится под контролем версий (git).
- Установлен менеджер секретов или доступен механизм передачи env-переменных.

### Диагностика

```bash
# Проверка наличия секретов в Vagrantfile
git ls-files -i --exclude-standard | grep -E '\.env$|\.vault$'
# → (пустой вывод = .env/.vault в .gitignore)

# Поиск потенциальных секретов в истории коммитов
git log --oneline --all -S "password" -- Vagrantfile
# → a1b2c3d Add DB config
```

### Решение

**Переменные окружения:**

```ruby
config.vm.provision "shell", env: {
  "DB_PASSWORD" => ENV['DB_PASSWORD']
}
# → Переменная передаётся в gостевую ОС без хардкода
```

**Плагин `vagrant-env`:**

```ruby
# Файл .env (добавьте в .gitignore)
DB_PASSWORD=super_secret
# → .env добавлен в .gitignore
```

**Vagrant Cloud Auth:**

```bash
vagrant cloud auth login
# → Login successful
# Токен хранится в ~/.vagrant.d/data/vagrant_cloud_token
```

### Ротация SSH-ключей

```bash
# Принудительная перегенерация
rm -f .vagrant/machines/default/libvirt/private_key
vagrant up
# → Warning: No key file exists, generating new key

# Использование собственного ключа
config.ssh.private_key_path = ["~/.ssh/id_ed25519"]
# → SSH будет использовать ~/.ssh/id_ed25519 вместо insecure_private_key
```

### Валидация

```bash
# Проверка отсутствия секретов в Vagrantfile
git grep -nE "(password|secret|api_key)" Vagrantfile
# → (пустой вывод = секреты не в коде)

# Проверка .gitignore
git check-ignore .env
# → .env
```

### Очистка

```bash
# Удаление скомпрометированных ключей и токенов:
shred -u .vagrant/machines/default/libvirt/private_key
rm -f .vagrant/machines/default/libvirt/private_key
# → (key securely deleted)
```

---

## Сценарий 22: Траблшутинг в CI/CD

**Симптом:** Vagrant падает в пайплайне с неинформативными ошибками, не оставляет следов для пост-мортема.

**Причина:** Отсутствие debug-логирования, конфликты `.vagrant/` при параллельных сборках, превышение таймаутов в CI-окружениях.

### Требования (Prerequisites)

- CI-agent с установленным Vagrant.
- Доступ к артефакт-хранилищу для сохранения логов.
- Переменные окружения CI (`CI_JOB_ID` и т.п.) доступны.

### Диагностика

```bash
# 1. Проверка доступности Vagrant в CI
which vagrant
# → /usr/bin/vagrant

# 2. Проверка версии
vagrant --version
# → Vagrant 2.4.9

# 3. Проверка артефактов предыдущего запуска
ls -la $CI_PROJECT_DIR/vagrant_debug.log
# → -rw-r--r--  10M
```

### Лучшие практики

```bash
# 1. Отключение интерактивного режима
export VAGRANT_NO_TTY=1
# → No TTY allocated

# 2. Логирование в файл
VAGRANT_LOG=debug vagrant up --provider=libvirt > vagrant_debug.log 2>&1
# → Debug log written to vagrant_debug.log

# 3. Изоляция состояний
export VAGRANT_DOTFILE_PATH=/tmp/vagrant-${CI_JOB_ID}
mkdir -p $VAGRANT_DOTFILE_PATH
# → Created /tmp/vagrant-12345

# 4. Увеличение таймаутов
# В Vagrantfile:
config.vm.boot_timeout = 900
# → VM will wait up to 900 seconds

# 5. Атомарный запуск
vagrant up --no-provision
# → Bringing machine 'default' up...
vagrant provision
# → Setup complete
```

### Валидация

```bash
# Проверка статуса
vagrant status
# → default                  running (libvirt)

# Проверка доступности сервиса
vagrant ssh -c "curl -sf http://localhost:3000/health"
# → OK
```

### Очистка

```bash
# Удаление артефактов CI после успешного билда:
rm -f vagrant_debug.log
rm -rf $VAGRANT_DOTFILE_PATH
```

---

## Сценарий 23: Резервное копирование окружения

**Симптом:** Необходимо создать переносимый архив рабочей среды для миграции или бэкапа.

**Причина:** Требуется сохранить текущее состояние ВМ (образ + метаданные) для восстановления или переноса на другой хост.

### Требования (Prerequisites)

- ВМ остановлена (`vagrant halt`) для согласованного snapshot'а.
- Достаточно места на диске для `box`-файла (размер диска ВМ).
- Доступна целевая директория для бэкапа.

### Диагностика

```bash
# Проверка текущего состояния ВМ перед бэкапом
vagrant status
# → default                  running (libvirt)

# Проверка доступного места на диске
df -h / | awk 'NR==2{print $4}'
# → 25G

# Проверка целостности текущего box (если уже существует)
vagrant box list | grep bento
# → bento/ubuntu-24.04 (libvirt)
```

### Решение

```bash
# 1. Остановка ВМ
vagrant halt
# → Forcing graceful shutdown...

# 2. Упаковка текущего состояния
vagrant package --output project-backup-$(date +%Y%m%d).box
# → ==> Generating and packaging a box...

# 3. Экспорт метаданных
cp -r .vagrant ./vagrant-metadata-backup
# → copied .vagrant directory
vagrant global-status --prune > global-status-backup.txt
# → wrote global-status to file

# 4. Список плагинов
vagrant plugin list > plugins-backup.txt
# → vagrant-libvirt (0.x.x, global)
```

### Валидация

```bash
# Проверка архива
ls -lh project-backup-*.box
# → -rw-r--r--  5.2G  project-backup-20250101.box

vagrant box add test-restore ./project-backup-20250101.box --name test-restore
# → Successfully added box 'test-restore'
vagrant up --provider=libvirt
# → Bringing machine 'default' up...
```

### Очистка

```bash
# Удалите тестовый restore после валидации:
vagrant destroy -f
vagrant box remove test-restore
# → Removed box 'test-restore'
```

---

## Сценарий 24: Триггеры и автоматизация

**Симптом:** Нужно автоматизировать pre-flight проверки и пост-действия без изменения основного Vagrantfile.

**Причина:** Отсутствие механизма хуков для условных проверок и cleanup-операций.

### Требования (Prerequisites)

- Установлен плагин `vagrant-trigger` (`vagrant plugin install vagrant-trigger`).
- Понимание lifecycle хуков Vagrant (`up`, `down`, `destroy`, `provision`).

### Диагностика

```bash
# Проверка установленного плагина триггеров
vagrant plugin list | grep trigger
# → vagrant-trigger (0.x.x, global)

# Проверка активных триггеров в Vagrantfile
grep -c "config.trigger" Vagrantfile
# → 3
```

### Решение

```ruby
# Проверка свободного места перед запуском
config.trigger.before :up do |trigger|
  trigger.run = {
    inline: "df -hT ~/.vagrant.d | awk 'NR==2 {exit ($5+0 > 90)}' || (echo 'Disk full!' && exit 1)"
  }
  trigger.abort = true
end
# → Pre-flight check: disk space < 90%

# Очистка после destroy
config.trigger.after :destroy do |trigger|
  trigger.run = {
    inline: "rm -f /tmp/vagrant-*"
  }
end
# → Cleanup: removed /tmp/vagrant-*

# Проверка сервиса после up
config.trigger.after :up do |trigger|
  trigger.run_remote = {
    inline: "systemctl is-active --quiet nginx || (echo 'Nginx failed!' && exit 1)"
  }
  trigger.abort = true
end
# → Health check: nginx is active
```

### Валидация

```bash
# Проверка срабатывания триггеров
VAGRANT_LOG=info vagrant up 2>&1 | grep -i trigger
# → INFO trigger: before :up hook fired
```

---

## Сценарий 25: Восстановление повреждённой конфигурации `.vagrant/`

**Симптом:** Метаданные проекта повреждены или утеряны после сбоя диска или некорректного завершения Vagrant.

**Причина:** Нарушение записи в `.vagrant/` (unexpected shutdown, disk corruption). UUID ВМ в файле `id` утрачен или неверен.

### Требования (Prerequisites)

- ВМ должна существовать в гипервизоре (иначе используйте `vagrant destroy -f` + `vagrant up`).
- Резервная копия важных данных должна быть создана.

### Диагностика

```bash
# 1. Проверка существования ВМ в гипервизоре
virsh list --all # Libvirt
# → Name      State
#   default   running
VBoxManage list vms # VirtualBox
# → "default" {12345678-abcd-efgh-ijkl}

# 2. Проверка повреждения .vagrant/
ls -la .vagrant/machines/default/libvirt/
# → id  private_key  Vagrantfile.json
```

### Решение

**Восстановление на основе существующей ВМ:**

```bash
# 1. Проверьте существование ВМ в гипервизоре
virsh list --all # Libvirt
VBoxManage list vms # VirtualBox

# 2. Если ВМ существует, но Vagrant её не видит — исправьте id
echo "<provider_uuid>" > .vagrant/machines/default/libvirt/id
# → UUID записан в .vagrant/machines/default/libvirt/id

# 3. Если SSH-ключ рассинхронизирован — перегенерируйте
rm -f .vagrant/machines/default/libvirt/private_key
vagrant ssh-config
# → Warning: No key file exists, generating new key

# 4. Изоляция проблемного провижининга
vagrant up --no-provision
# → Bringing machine 'default' up...
vagrant provision
# → Setup complete

# 5. Крайняя мера — полное удаление метаданных проекта
rm -rf .vagrant
vagrant global-status --prune
vagrant up
# → Bringing machine 'default' up...
```

### Валидация

```bash
vagrant status
# → default                  running (libvirt)
vagrant ssh -c "whoami"
# → vagrant
```

### Очистка

Если восстановление не удалось — полное удаление и пересоздание (см. также [Сценарий 2](#сценарий-2-рассинхронизация-состояния-state-desync) для методики State Desync).

---

## Лучшие практики

Общие рекомендации для DevOps/SRE при работе с Vagrant:

- **Всегда создавайте snapshot перед экспериментами:** `vagrant snapshot save "pre-change"` и откатывайтесь при необходимости.
- **Используйте фиксированные версии box'ов:** `config.vm.box_version` и `config.vm.box_download_checksum` предотвращают неожиданный drift образов.
- **В CI всегда используйте атомарный запуск:** `vagrant up --no-provision` → `vagrant provision` для изоляции проблем провижининга.
- **Логи для post-mortem:** `VAGRANT_LOG=debug vagrant up 2>&1 | tee debug.log` и `sudo journalctl -u libvirtd --since "1 hour ago"`.
- **Регулярная очистка:** `vagrant box prune --keep 1`, `vagrant global-status --prune`, удаление неиспользуемых томов `virsh vol-delete`.
- **Air-gapped подготовка:** заранее скачивайте box'ы и экспортируйте плагины на машине с доступом.
- **SSH-ключи:** используйте `~/.ssh/id_ed25519` через `config.ssh.private_key_path` вместо `insecure_private_key`.
- **NTP:** включайте `timedatectl set-ntp true` внутри ВМ для предотвращения clock drift.

## Дополнительная информация

- [Основные концепции](./basic_concepts.md) — архитектура сбоев, каталог ошибок, переменные окружения.
- [Дополнительная информация](./additional_info.md) — профилактика, бэкапы, CI/CD, air-gapped, регулярная очистка.
- [Vagrantfile: Валидация](../vagrantfile.md) — синтаксическая проверка конфигурации.
- [Настройка сети](../vagrant_networking.md) — детальная настройка сетей, NFS, firewall.
- [Хранилище и папки](../vagrant_storage_and_folders.md) — virtiofs, rsync, управление дисками.
- [Apple Silicon](../vagrant_macos_apple_silicon.md) — специфика ARM64 и QEMU.
