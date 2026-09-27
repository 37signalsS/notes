# Vagrant Troubleshooting — Практические сценарии

## Введение

Этот документ содержит пошаговые сценарии решения типичных проблем Vagrant в средах DevOps, SRE и системного администрирования. Каждый сценарий строится по схеме: **симптом → диагностика → решение → верификация**.

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
| `VT-x is not available` | `systeminfo \| grep -i virtualization` | Hyper-V, WSL2, Memory Integrity | [Сценарий 6](#сценарий-6-конфликт-virtualbox-и-hyper-v-windows) |
| `Call to virNetworkCreate failed` | `virsh net-list --all` | Конфликт подсетей с Docker/VPN | [Сценарий 7](#сценарий-7-конфликты-сетевых-мостов) |
| ВМ зависает при загрузке | `virsh dump <domain> \| grep -i panic` | Проблемы с образом, нехватка RAM, nested | [Сценарий 8](#сценарий-8-влагая-виртуализация-nested-virtualization) |

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

# 3. Проверьте DNS
dig vagrantcloud.com +short
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

### Верификация

```bash
# Box должен скачиваться без ошибок
vagrant box add bento/ubuntu-24.04 --provider libvirt

# Плагин должен устанавливаться
vagrant plugin install vagrant-vbguest
```

### Отмена изменений

```bash
unset http_proxy https_proxy no_proxy VAGRANT_HTTP_PROXY VAGRANT_HTTPS_PROXY VAGRANT_NO_PROXY
```

---

## Сценарий 2: Рассynchronization состояния (State Desync)

**Симптом:** `Machine not found`, `vagrant halt` завершается ошибкой, `vagrant ssh` зависает или возвращает `Permission denied` для несуществующей ВМ.

**Причина:** Локальное состояние Vagrant (`.vagrant/`) было удалено вручную, повреждено или перемещено, но ресурсы у гипервизора остались. Файл `.vagrant/machines/<name>/<provider>/id` содержит устаревший или неверный UUID.

### Диагностика

```bash
# 1. Проверьте глобальный статус
vagrant global-status
# → id   name   provider   state   directory

# 2. Проверьте реальное состояние в гипервизоре
virsh list --all              # Libvirt
VBoxManage list vms           # VirtualBox

# 3. Сравните UUID из .vagrant/ с реальным
cat .vagrant/machines/default/libvirt/id
virsh list --all | grep <name>
```

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
```

### Решение: Полный сброс

Если состояние невосстановимо:

```bash
# 1. Принудительное удаление (даже если ВМ не видна Vagrant)
vagrant destroy -f

# 2. Очистка глобального реестра
vagrant global-status --prune

# 3. Удаление локальных метаданных проекта
rm -rf .vagrant

# 4. Повторный запуск
vagrant up
```

### Восстановление данных перед destroy

Если данные внутри ВМ критичны, см. [Дополнительная информация](./additional_info.md) — раздел «Восстановление данных из повреждённой ВМ» (guestmount, SCP).

---

## Сценарий 3: SSH не подключается

**Симптом:** `vagrant ssh` зависает или выдает `Permission denied (publickey)`, `Connection timed out`.

### Диагностика

```bash
# 1. Просмотр эффективной SSH-конфигурации
vagrant ssh-config

# 2. Прямое подключение с детализацией
ssh -vvv -i .vagrant/machines/default/libvirt/private_key vagrant@192.168.121.10 -p 22

# 3. Проверка доступности порта
nc -zv 192.168.121.10 22
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

---

## Сценарий 4: Общие папки

**Симптом:**
```
Mounting shared folders failed.
```

**Причина:** Несовпадение версий Guest Additions (VirtualBox), отсутствие `virtiofs`/`nfs`, проблемы с правами или firewall.

### Диагностика

```bash
# 1. Проверка типа монтирования
vagrant ssh -c "findmnt -t nfs4,virtiofs,vboxsf,9p"

# 2. Проверка доступности NFS-портов (если используется NFS)
sudo rpcinfo -p <host_ip> | grep nfs

# 3. Проверка логов гипервизора
# Libvirt:
sudo journalctl -u libvirtd -n 50 | grep -i error
# VirtualBox:
VBoxManage list runningvms
```

### Решение: VirtualBox

```bash
# Автоматическое обновление Guest Additions
vagrant plugin install vagrant-vbguest
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
vagrant reload
```

---

## Сценарий 5: Недостаточно места на диске

**Симптом:**
```
Error while creating new volume: No space left on device
```

### Диагностика

```bash
# 1. Проверка точек монтирования
df -hT ~/.vagrant.d /var/lib/libvirt/images

# 2. Поиск больших файлов
du -sh ~/.vagrant.d/boxes/*
du -sh /var/lib/libvirt/images/*

# 3. Проверка пулов Libvirt
virsh --connect qemu:///system pool-list --all
virsh --connect qemu:///system pool-info default
```

### Решение

```bash
# 1. Очистка устаревших образов (оставляет последнюю версию)
vagrant box prune --keep 1

# 2. Удаление неиспользуемых томов Libvirt
virsh --connect qemu:///system vol-list default | grep -v "Name" | \
  xargs -n1 virsh vol-delete --pool default

# 3. Очистка системных логов хоста
sudo journalctl --vacuum-time=7d

# 4. Удаление сиротских snapshot'ов VirtualBox
VBoxManage list hdds | grep "^UUID:" | while read uuid; do
  VBoxManage modifyhd $uuid --compact
done

# 5. Расширение пула (если диск хоста позволяет)
# Для LVM:
sudo lvextend -L +20G /dev/vg0/var-lib-libvirt-images
sudo resize2fs /dev/vg0/var-lib-libvirt-images
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

### Диагностика

```bash
# 1. Список всех сетей Libvirt
virsh --connect qemu:///system net-list --all

# 2. Проверка занятых IP
sudo arp-scan --interface=virbr0 --localnet

# 3. Проверка конфликтов с Docker
docker network ls
docker network inspect bridge | grep "Subnet"
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
virsh --connect qemu:///system net-start vagrant-libvirt
```

**Вариант C: Удаление неиспользуемой сети**

```bash
virsh --connect qemu:///system net-undefine vagrant-libvirt-old
```

### Валидация

```bash
vagrant up
# → Default: SSH address: 10.10.10.10:22
```

---

## Сценарий 7: Вложенная виртуализация (Nested Virtualization)

**Симптом:** ВМ запускается, но внутри неё невозможно запустить Docker (KVM), Minikube или другой гипервизор. Ошибки: `kvm: failed to open /dev/kvm`, `virt-fw-arn: KVM not supported`.

### Диагностика

```bash
# 1. Проверка на физическом хосте (L0)
cat /sys/module/kvm_intel/parameters/nested   # Intel (должно быть Y)
cat /sys/module/kvm_amd/parameters/nested     # AMD (должно быть 1)

# 2. Проверка внутри гостевой ОС (L1)
vagrant ssh -c "lsmod | grep kvm"
vagrant ssh -c "dmesg | grep -i kvm"
```

### Решение

**Включение nested на хосте:**

```bash
# Intel
echo "options kvm_intel nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
sudo modprobe -r kvm_intel && sudo modprobe kvm_intel

# AMD
echo "options kvm_amd nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
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

### Примечание по производительности

Nested virtualization снижает производительность на 20-40% из-за двойной трансляции адресов (EPT/VP). Для production-сред используйте bare-metal L1 или облачные инстансы с аппаратной поддержкой nested (OpenStack, AWS `c5.metal`).

---

## Сценарий 8: Провайдеры и архитектурные ограничения

**Симптом 1:** `The provider 'virtualbox' is not supported on this architecture.`

**Причина:** Apple Silicon (ARM64) не поддерживает VirtualBox. Требуется QEMU/VMware.

**Решение:**

```bash
# Использование qemu провайдера
vagrant up --provider=qemu

# Или vmware_desktop (если установлен)
vagrant up --provider=vmware_desktop
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
```

QEMU на macOS требует `rsync` как метод синхронизации по умолчанию.

---

## Сценарий 9: Конфликт VirtualBox и Hyper-V (Windows)

**Симптом:** VirtualBox ВМ падает с ошибкой `VT-x is not available` или работает крайне медленно (иконка черепахи).

**Причина:** Hyper-V (или функции на его базе: WSL2, Memory Integrity, Docker Desktop) захватывает эксклюзивный доступ к аппаратной виртуализации.

### Диагностика

```powershell
# Проверка статуса Hyper-V
Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
# → State : Enabled

# Проверка Memory Integrity
msinfo32 | grep "Memory Integrity"
```

### Решение A: Отключение Hyper-V (если VirtualBox критичен)

```powershell
Disable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
bcdedit /set hypervisorlaunchtype off
# Требуется перезагрузка
```

### Решение B: Использование Hyper-V как провайдера

```bash
vagrant up --provider=hyperv
```

**Примечание:** Hyper-V провайдер в Vagrant имеет ограниченную поддержку сетей (только DHCP/NAT).

---

## Сценарий 10: Ошибки при скачивании образов

**Симптом:**
```
SSL certificate problem: unable to get local issuer certificate
```
или `The request timed out`.

### Диагностика

```bash
# Проверка SSL-цепочки
curl -v https://vagrantcloud.com

# Проверка DNS
nslookup vagrantcloud.com
```

### Решение

**Крайняя мера — отключение проверки SSL:**

```bash
vagrant box add <name> --insecure
```

**Альтернативное зеркало:**

```bash
# Скачайте .box вручную через браузер на машине с доступом
vagrant box add my-box ./package.box --provider libvirt
```

**Фиксация версии и checksum:**

```ruby
config.vm.box = "bento/ubuntu-24.04"
config.vm.box_version = "202501.0"
config.vm.box_download_checksum = "sha256:abc123..."
config.vm.box_download_checksum_type = "sha256"
```

---

## Сценарий 11: Провижининг и automation failures

**Симптом:** `vagrant provision` завершается с ошибкой, скрипты отрабатывают некорректно, Ansible теряет связь с ВМ.

### Диагностика

```bash
# 1. Запуск с детальным логированием
VAGRANT_LOG=debug vagrant provision 2>&1 | tee provision_debug.log

# 2. Проверка статуса провижинера
vagrant status

# 3. Ручной запуск провижининга
vagrant ssh -c "sudo /vagrant/scripts/setup.sh"
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
vagrant provision
# → Succeeded!
```

---

## Сценарий 12: Дисковое пространство и производительность

**Симптом:** ВМ работает медленно, `iotop` показывает высокую нагрузку, `df -h` показывает 100% utilisation на диске.

### Диагностика

```bash
# 1. Внутри ВМ
vagrant ssh -c "df -h /"
vagrant ssh -c "iostat -x 1 5"

# 2. На хосте
df -hT /var/lib/libvirt/images
iostat -x 1 5
```

### Решение: Расширение диска

```bash
# 1. Увеличение размера виртуального диска (Libvirt)
qemu-img resize /var/lib/libvirt/images/<vm_name>.qcow2 +20G

# 2. Перезагрузка ВМ
vagrant reload

# 3. Расширение раздела внутри гостевой ОС
vagrant ssh -c "sudo growpart /dev/vda 1"
vagrant ssh -c "sudo resize2fs /dev/vda1"
```

### Решение: Переход на virtiofs

Если общие папки тормозят, переключитесь с NFS на `virtiofs`:

```ruby
config.vm.synced_folder ".", "/vagrant", type: "virtiofs"
```

---

## Сценарий 13: Процедура пост-мортем

При сложных инцидентах собирайте артефакты в определённом порядке.

### Шаг 1: Снимок состояния

```bash
# Глобальный статус
vagrant global-status --prune > /tmp/vagrant-global-status.txt

# Статус конкретного проекта
vagrant status > /tmp/vagrant-status.txt

# Список образов
vagrant box list > /tmp/vagrant-boxes.txt

# Список плагинов
vagrant plugin list > /tmp/vagrant-plugins.txt
```

### Шаг 2: Сбор логов

```bash
# Debug-лог Vagrant
VAGRANT_LOG=debug vagrant up 2>&1 | tee /tmp/vagrant-debug.log

# Логи гипервизора
# Libvirt:
sudo journalctl -u libvirtd --since "1 hour ago" > /tmp/libvirtd.log
sudo journalctl -u virtlogd --since "1 hour ago" > /tmp/virtlogd.log

# VirtualBox:
VBoxManage list systemlogs > /tmp/vbox-system-logs.txt
```

### Шаг 3: Анализ паттернов

Ищите в логах ключевые маркеры:

```bash
grep -iE "error|timeout|failed|panic|fatal" /tmp/vagrant-debug.log | head -50
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

---

## Сценарий 14: Мульти-машинные конфигурации

**Симптом:** `vagrant up` запускает только часть ВМ, одна из машин не стартует, зависимые сервисы не видят друг друга.

### Диагностика

```bash
# 1. Проверка статуса всех машин
vagrant status

# 2. Проверка сети между машинами
vagrant ssh web -c "ping -c1 db.local"
vagrant ssh db -c "ss -tulnp"
```

### Решение

**Явный запуск в правильном порядке:**

```bash
vagrant up db
vagrant up web
```

**Автоматическое ожидание готовности:**

```ruby
config.vm.provision "shell", inline: <<-SHELL
  until nc -z 192.168.56.11 5432; do
    echo "Waiting for DB..."
    sleep 2
  done
SHELL
```

**Изоляция проблемной ВМ:**

```bash
# Запуск без провижининга для диагностики
vagrant up web --no-provision
vagrant provision web
```

---

## Сценарий 15: Apple Silicon (M1/M2/M3)

**Симптом 1:** `The provider 'virtualbox' is not supported on this architecture.`

**Решение:** Используйте `qemu` или `vmware_desktop`. Подробности в [Vagrant на Apple Silicon](../vagrant_macos_apple_silicon.md).

**Симптом 2:** ВМ на QEMU зависает при загрузке.

**Причина:** Попытка запуска `x86_64` образа на ARM64 хосте без эмуляции.

**Решение:**

```bash
# Найдите образ с нужной архитектурой
vagrant box list | grep arm64
# → generic/ubuntu2204-arm64

# Укажите провайдер явно
vagrant up --provider=qemu
```

**Симптом 3:** Проблемы с `rsync`.

**Решение:**

```bash
brew install rsync
```

---

## Сценарий 16: Синхронизация времени (Clock Drift)

**Симптом:** Ошибки TLS-рукопожатий, истечение сертификатов, сбои Kerberos, репликация в PostgreSQL/MongoDB падает.

**Причина:** Расхождение времени между хостом и гостем более 5 минут. В виртуализированных средах drift может достигать нескольких секунд за час, особенно после `vagrant suspend/resume`.

### Диагностика

```bash
# На хосте
date -u

# Внутри ВМ
vagrant ssh -c "date -u"
vagrant ssh -c "timedatectl show | grep NTPSynchronized"
```

### Решение

```bash
# Включение NTP внутри гостевой ОС
vagrant ssh -c "sudo timedatectl set-ntp true"
vagrant ssh -c "sudo timedatectl status"

# Проверка синхронизации
vagrant ssh -c "timedatectl show | grep NTPSynchronized"
# → NTPSynchronized=yes
```

---

## Сценарий 17: Восстановление данных из повреждённой ВМ

**Симптом:** ВМ не загружается, но диск (том) доступен. Требуется извлечение данных без загрузки ОС.

### Решение A: Монтирование через guestmount

```bash
# Установка libguestfs
sudo apt-get install -y libguestfs-tools

# Монтирование qcow2 образа (только для чтения)
sudo guestmount -a /var/lib/libvirt/images/<vm_name>.qcow2 -i --ro /mnt/vm-recovery

# Копирование данных
sudo cp -r /mnt/vm-recovery/home/vagrant/project ./recovered/

# Размонтирование
sudo guestunmount /mnt/vm-recovery
```

### Решение B: Ручной экспорт через SCP

```bash
# Получение параметров SSH
vagrant ssh-config > ssh_config

# Копирование данных
scp -F ssh_config default:/var/lib/mysql/backup.sql ./
```

### Решение C: Подключение диска к другой ВМ

Через интерфейс гипервизора подключите диск повреждённой ВМ как дополнительное устройство к рабочей ВМ, затем смонтируйте внутри неё.

---

## Сценарий 18: Плагины и зависимости

**Симптом:** `Plugin error`, `vagrant up` завершается с ошибкой загрузки плагина после обновления Ruby или Vagrant.

### Диагностика

```bash
vagrant plugin list
vagrant plugin repair
```

### Решение

```bash
# Полная очистка и переустановка всех плагинов
vagrant plugin expunge --reinstall

# Или точечное обновление
vagrant plugin update vagrant-vbguest
vagrant plugin update vagrant-libvirt
```

### Валидация

```bash
vagrant plugin list
# → Все плагины загружены
vagrant up
```

---

## Сценарий 19: Офлайн-работа (Air-Gapped среды)

Для изолированных сред без доступа в интернет подготовьте артефакты на машине с доступом:

```bash
# 1. Скачивание box-файла
vagrant box add bento/ubuntu-24.04 --provider libvirt

# 2. Экспорт списка плагинов
vagrant plugin list > plugins.txt

# 3. Упаковка проекта
tar czf vagrant-offline.tar.gz Vagrantfile .vagrant/
```

Перенос и установка в изолированной сети:

```bash
# Установка плагинов (если есть локальный кэш)
vagrant plugin install vagrant-libvirt

# Добавление box из локального файла
vagrant box add bento/ubuntu-24.04 ./bento-ubuntu-24.04-libvirt.box --provider libvirt
```

---

## Сценарий 20: Зависание и паника ядра (Kernel Panic)

**Сиymptom:** ВМ зависает на загрузке, экран остается чёрным, в консоли гипервизора виден panic.

### Диагностика

```bash
# Libvirt: получение дампа логов
sudo virsh dump <domain_name> /tmp/vm-dump.log

# Поиск panic в логах
grep -i "kernel panic\|general protection fault\|oops" /tmp/vm-dump.log
```

### Распространённые причины

| Причина | Решение |
| :--- | :--- |
| **Несовместимость образа** | Используйте образы с поддержкой вашего провайдера (например, `bento/ubuntu-24.04` для VirtualBox/Libvirt). |
| **Недостаток RAM** | Увеличьте `config.vm.provider "libvirt" do \|lv\| lv.memory = 2048 end` |
| **Проблемы с облачными образами** | Избегайте образов с предустановленным cloud-init для офлайн-сред. Используйте `bento/*` или `generic/*`. |
| **Nested virtualization** | Проверьте поддержку nested на хосте (см. [Сценарий 8](#сценарий-8-влагая-виртуализация-nested-virtualization)). |

### Решение

```bash
# 1. Запуск в safe mode (если поддерживается)
vagrant up --provider=libvirt

# 2. Отключение проблемного провижининга
vagrant up --no-provision

# 3. Если ВМ стартовала — проверьте логи внутри
vagrant ssh -c "sudo journalctl -b -p err"
```

---

## Сценарий 21: Безопасность и секреты

**Симптом:** В Vagrantfile обнаружены пароли, API-ключи или SSH-ключи в открытом виде. При коммите в репозиторий секреты становятся доступны всей команде.

### Решение

**Переменные окружения:**

```ruby
config.vm.provision "shell", env: {
  "DB_PASSWORD" => ENV['DB_PASSWORD']
}
```

**Плагин `vagrant-env`:**

```ruby
# Файл .env (добавьте в .gitignore)
DB_PASSWORD=super_secret
```

**Vagrant Cloud Auth:**

```bash
vagrant cloud auth login
# Токен хранится в ~/.vagrant.d/data/vagrant_cloud_token
```

### Ротация SSH-ключей

```bash
# Принудительная перегенерация
rm -f .vagrant/machines/default/libvirt/private_key
vagrant up

# Использование собственного ключа
config.ssh.private_key_path = ["~/.ssh/id_ed25519"]
```

---

## Сценарий 22: Траблшутинг в CI/CD

**Симптом:** Vagrant падает в пайплайне с неинформативными ошибками, не оставляет следов для пост-мортема.

### Лучшие практики

```bash
# 1. Отключение интерактивного режима
export VAGRANT_NO_TTY=1

# 2. Логирование в файл
VAGRANT_LOG=debug vagrant up --provider=libvirt > vagrant_debug.log 2>&1

# 3. Изоляция состояний
export VAGRANT_DOTFILE_PATH=/tmp/vagrant-${CI_JOB_ID}
mkdir -p $VAGRANT_DOTFILE_PATH

# 4. Увеличение таймаутов
# В Vagrantfile:
config.vm.boot_timeout = 900

# 5. Атомарный запуск
vagrant up --no-provision
vagrant provision
```

### Валидация

```bash
# Проверка статуса
vagrant status

# Проверка доступности сервиса
vagrant ssh -c "curl -sf http://localhost:3000/health"
```

---

## Сценарий 23: Резервное копирование окружения

**Симптом:** Необходимо создать переносимый архив рабочей среды для миграции или бэкапа.

### Решение

```bash
# 1. Остановка ВМ
vagrant halt

# 2. Упаковка текущего состояния
vagrant package --output project-backup-$(date +%Y%m%d).box

# 3. Экспорт метаданных
cp -r .vagrant ./vagrant-metadata-backup
vagrant global-status --prune > global-status-backup.txt

# 4. Список плагинов
vagrant plugin list > plugins-backup.txt
```

### Валидация

```bash
# Проверка архива
vagrant box add test-restore ./project-backup-20250101.box --name test-restore
vagrant up --provider=libvirt
```

---

## Сценарий 24: Триггеры и автоматизация

**Симптом:** Нужно автоматизировать pre-flight проверки и пост-действия без изменения основного Vagrantfile.

### Решение

```ruby
# Проверка свободного места перед запуском
config.trigger.before :up do |trigger|
  trigger.run_local = {
    inline: "df -hT ~/.vagrant.d | awk 'NR==2 {exit ($5+0 > 90)}' || (echo 'Disk full!' && exit 1)",
    abort: true
  }
end

# Очистка после destroy
config.trigger.after :destroy do |trigger|
  trigger.run_local = {
    inline: "rm -f /tmp/vagrant-*"
  }
end

# Проверка сервиса после up
config.trigger.after :up do |trigger|
  trigger.run_remote = {
    inline: "systemctl is-active --quiet nginx || (echo 'Nginx failed!' && exit 1)",
    abort: true
  }
end
```

---

## Сценарий 25: Восстановление повреждённой конфигурации `.vagrant/`

**Симптом:** Метданные проекта повреждены или утеряны после сбоя диска или некорректного завершения Vagrant.

### Решение

```bash
# 1. Проверьте существование ВМ в гипервизоре
virsh list --all # Libvirt
VBoxManage list vms # VirtualBox

# 2. Если ВМ существует, но Vagrant её не видит — исправьте id
echo "<provider_uuid>" > .vagrant/machines/default/libvirt/id

# 3. Если SSH-ключ рассинхронизирован — перегенерируйте
rm -f .vagrant/machines/default/libvirt/private_key
vagrant ssh-config

# 4. Изоляция проблемного провижининга
vagrant up --no-provision
vagrant provision

# 5. Крайняя мера — полное удаление метаданных проекта
rm -rf .vagrant
vagrant global-status --prune
vagrant up
```

---

## См. также

- [Основные концепции](./basic_concepts.md) — архитектура сбоев, каталог ошибок, переменные окружения.
- [Дополнительная информация](./additional_info.md) — профилактика, бэкапы, CI/CD, air-gapped.
- [Vagrantfile: Валидация](../vagrantfile.md) — синтаксическая проверка конфигурации.
- [Настройка сети](../vagrant_networking.md) — детальная настройка сетей, NFS, firewall.
- [Хранилище и папки](../vagrant_storage_and_folders.md) — virtiofs, rsync, управление дисками.
